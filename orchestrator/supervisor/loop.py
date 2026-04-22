"""Top-level asyncio event loop for the Huragok daemon (ADR-0002 D1).

:func:`run` is the function the CLI ``huragok run`` command enters. It
wires up the budget tracker, the notification dispatcher, the
signal handlers, and the per-iteration state machine driver described
in ADR-0002 D1 and ADR-0003 D1.

The loop does not implement the full Phase-1 feature set — B2 adds the
reply-file → dispatcher handoff, the retry-policy beyond "two dirty ends
and block", and the live session breakdown in ``huragok status``.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import structlog
from uuid_v7.base import uuid7

from orchestrator.budget import (
    BudgetTracker,
    CostReconciler,
    RateLimitLog,
    load_pricing,
)
from orchestrator.budget.pricing import ensure_models_priced
from orchestrator.config import HuragokSettings
from orchestrator.constants import MIN_CLAUDE_CODE_VERSION
from orchestrator.notifications import LoggingDispatcher, Notification, NotificationDispatcher
from orchestrator.paths import daemon_pid_file, task_dir
from orchestrator.session import BudgetEvent, SessionResult, run_session
from orchestrator.state import (
    HistoryEntry,
    SessionBudget,
    StateFile,
    StatusFile,
    append_audit,
    cleanup_stale_tmp,
    read_batch,
    read_state,
    read_status,
    write_state,
    write_status,
)
from orchestrator.supervisor.sd_notify import sd_notify
from orchestrator.supervisor.signals import (
    SignalState,
    install_signal_handlers,
    process_request_files,
    sleep_or_shutdown,
)

__all__ = [
    "DEFAULT_REQUEST_POLL_SECONDS",
    "ROLE_FOR_STATE",
    "SessionAttempt",
    "SupervisorContext",
    "run",
    "run_supervisor",
]


DEFAULT_REQUEST_POLL_SECONDS: float = 1.5

# ADR-0003 D1: role chosen by the Supervisor from the current status.state.
# ``None`` indicates a non-session state (terminal or waiting on operator).
ROLE_FOR_STATE: dict[str, str | None] = {
    "pending": "architect",
    "speccing": "architect",
    "implementing": "implementer",
    "testing": "testwriter",
    "reviewing": "critic",
    "software-complete": None,
    "awaiting-human": None,
    "done": None,
    "blocked": None,
}

# Per ADR-0003 D4: model assignment by role.
MODEL_FOR_ROLE: dict[str, str] = {
    "architect": "claude-opus-4-7",
    "implementer": "claude-sonnet-4-6",
    "testwriter": "claude-sonnet-4-6",
    "critic": "claude-opus-4-7",
    "documenter": "claude-haiku-4-5-20251001",
}

# B1's simplified retry rule: two consecutive dirty ends on a task move it
# to ``blocked``. ADR-0002 D7's full taxonomy and per-category caps are
# B2's job.
DIRTY_END_CAP: int = 2

# Version check: claude --version produces output like "2.1.91 (Claude Code)".
_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


# ---------------------------------------------------------------------------
# Dataclasses.
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SessionAttempt:
    """One row of the in-memory retry counter keyed by task id."""

    task_id: str
    consecutive_dirty: int = 0


@dataclass(slots=True)
class SupervisorContext:
    """Aggregated references passed to the inner iteration helpers.

    Bundled so that refactoring does not force every helper signature to
    change. Not exported beyond the module; tests construct one directly
    when exercising individual iterations.
    """

    root: Path
    settings: HuragokSettings
    dispatcher: NotificationDispatcher
    tracker: BudgetTracker
    rate_limit: RateLimitLog
    signal_state: SignalState
    event_queue: asyncio.Queue[BudgetEvent]
    claude_binary: str
    attempts: dict[str, SessionAttempt]
    request_poll_seconds: float = DEFAULT_REQUEST_POLL_SECONDS
    # Extra env vars to merge onto each session's scrubbed env. Tests use
    # this to pass FAKE_CLAUDE_MODE through without polluting the default
    # inherit allowlist.
    session_env_overrides: dict[str, str] | None = None


# ---------------------------------------------------------------------------
# Entry points.
# ---------------------------------------------------------------------------


async def run(root: Path, settings: HuragokSettings) -> int:
    """Top-level daemon coroutine. Returns the process exit code.

    Covers the startup → main-loop → shutdown sequence described in
    ADR-0002 D1 and D8. Safe to call from ``asyncio.run`` in ``huragok
    run``; the CLI command translates the return code into ``sys.exit``.
    """
    log = structlog.get_logger(__name__).bind(component="supervisor", root=str(root))

    # 1. Sanity checks that must happen before any state mutation.
    version_ok, version_msg = _check_claude_version(settings)
    if not version_ok:
        log.error("supervisor.version.rejected", error=version_msg)
        return 1

    try:
        pricing = load_pricing()
    except Exception as exc:
        log.error("supervisor.pricing.load_failed", error=str(exc))
        return 1
    try:
        ensure_models_priced(pricing, MODEL_FOR_ROLE.values())
    except Exception as exc:
        log.error("supervisor.pricing.missing_model", error=str(exc))
        return 1

    # 2. State-root preparation.
    cleanup_stale_tmp(root)
    pid_path = daemon_pid_file(root)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(f"{os.getpid()}\n")

    # The test harness overrides the Claude binary via the same env var
    # used by the version check so a single knob controls both paths.
    claude_binary = os.environ.get("HURAGOK_CLAUDE_BINARY") or "claude"

    try:
        exit_code = await run_supervisor(
            root=root,
            settings=settings,
            pricing=pricing,
            claude_binary=claude_binary,
        )
    finally:
        with contextlib.suppress(FileNotFoundError):
            pid_path.unlink()
        sd_notify("STOPPING=1")
        log.info("supervisor.stopped")

    return exit_code


async def run_supervisor(
    *,
    root: Path,
    settings: HuragokSettings,
    pricing: object,  # PricingTable — ``object`` to avoid an otherwise unused import
    claude_binary: str = "claude",
    request_poll_seconds: float = DEFAULT_REQUEST_POLL_SECONDS,
    session_env_overrides: dict[str, str] | None = None,
    rate_limit_window_cap: int | None = None,
) -> int:
    """Run the main loop given an already-validated pricing table.

    Split from :func:`run` so tests can construct the context directly
    with a fake ``claude_binary`` and skip the version / PID bookkeeping.
    """
    log = structlog.get_logger(__name__).bind(component="supervisor", root=str(root))

    loop = asyncio.get_running_loop()
    signal_state = SignalState()
    install_signal_handlers(loop, signal_state)

    if rate_limit_window_cap is None:
        rate_limit = RateLimitLog(root)
    else:
        rate_limit = RateLimitLog(root, window_cap=rate_limit_window_cap)
    rate_limit.load()

    dispatcher = LoggingDispatcher(root=root, batch_id=_peek_batch_id(root))

    admin_key = (
        settings.anthropic_admin_api_key.get_secret_value()
        if settings.anthropic_admin_api_key is not None
        else None
    )
    reconciler = CostReconciler(admin_api_key=admin_key) if admin_key else None

    batch_budgets = _load_batch_budgets(root)
    tracker = BudgetTracker(
        root=root,
        pricing=pricing,  # type: ignore[arg-type]  # PricingTable at runtime
        dispatcher=dispatcher,
        max_tokens=batch_budgets.max_tokens if batch_budgets else 0,
        max_dollars=batch_budgets.max_dollars if batch_budgets else 0.0,
        max_wall_clock_seconds=(batch_budgets.wall_clock_hours * 3600) if batch_budgets else 0.0,
        warn_threshold_pct=batch_budgets.warn_threshold_pct if batch_budgets else 80,
        reconciler=reconciler,
        batch_id=_peek_batch_id(root),
    )
    try:
        current_state = read_state(root)
        tracker.seed_from_state(current_state.budget_consumed)
        if current_state.started_at:
            tracker.mark_batch_start(current_state.started_at)
    except FileNotFoundError:
        pass

    event_queue: asyncio.Queue[BudgetEvent] = asyncio.Queue()
    ctx = SupervisorContext(
        root=root,
        settings=settings,
        dispatcher=dispatcher,
        tracker=tracker,
        rate_limit=rate_limit,
        signal_state=signal_state,
        event_queue=event_queue,
        claude_binary=claude_binary,
        attempts={},
        request_poll_seconds=request_poll_seconds,
        session_env_overrides=dict(session_env_overrides) if session_env_overrides else None,
    )

    # Wire up the long-lived component coroutines.
    tracker_task = asyncio.create_task(tracker.run(event_queue, signal_state.shutting_down))
    dispatcher_task = asyncio.create_task(dispatcher.start(signal_state.shutting_down))

    # Signal systemd that we are READY before entering the loop.
    sd_notify("READY=1")
    log.info("supervisor.started", pid=os.getpid())

    try:
        exit_code = await _main_loop(ctx)
    finally:
        signal_state.shutting_down.set()
        # Wait for the long-lived coroutines to exit. Both are designed
        # to drain cleanly when the stop event fires.
        await asyncio.gather(tracker_task, dispatcher_task, return_exceptions=True)

    return exit_code


# ---------------------------------------------------------------------------
# Main loop.
# ---------------------------------------------------------------------------


async def _main_loop(ctx: SupervisorContext) -> int:
    """Drive the state machine until shutdown, halt, or terminal phase."""
    log = structlog.get_logger(__name__).bind(component="supervisor")
    idle_ticks = 0

    while not ctx.signal_state.shutting_down.is_set():
        # 1. Drain any stop/halt/reply requests.
        process_request_files(ctx.root, ctx.signal_state)
        if ctx.signal_state.shutting_down.is_set():
            break

        # 2. Inspect state and decide the next action.
        try:
            state = read_state(ctx.root)
        except FileNotFoundError:
            log.info("supervisor.idle.no_state")
            await sleep_or_shutdown(ctx.signal_state, ctx.request_poll_seconds)
            continue

        if state.phase in ("halted", "complete"):
            log.info("supervisor.phase.terminal", phase=state.phase)
            break

        # 3. Budget / halt-after-session gating.
        if ctx.tracker.over_budget():
            _transition_to_halted(ctx, state, reason="budget-exceeded")
            break
        if ctx.signal_state.halt_after_session.is_set():
            _transition_to_halted(ctx, state, reason="halt-requested")
            break

        # 4. Find the next non-terminal task.
        next_task = _pick_next_task(ctx.root, state)
        if next_task is None:
            log.info("supervisor.idle.no_pending_tasks")
            await _idle_sleep(ctx, idle_ticks)
            idle_ticks += 1
            continue
        idle_ticks = 0

        role = ROLE_FOR_STATE.get(next_task.state)
        if role is None:
            # Terminal in-session state reached but task not marked done.
            # B1 marks trivially-terminal states done; B2's human gate
            # handles the foundational notification loop.
            if next_task.state == "software-complete":
                _mark_task_done(ctx, next_task)
                continue
            log.info(
                "supervisor.task.awaiting",
                task_id=next_task.task_id,
                state=next_task.state,
            )
            await _idle_sleep(ctx, idle_ticks)
            idle_ticks += 1
            continue

        # 5. Rate-limit pre-flight.
        decision = ctx.rate_limit.query()
        if decision.status == "defer":
            log.info(
                "supervisor.rate_limit.defer",
                seconds=decision.defer_seconds,
                count=decision.count_in_window,
            )
            await _dispatch_rate_limit_notification(ctx, decision.defer_seconds)
            interrupted = await sleep_or_shutdown(ctx.signal_state, decision.defer_seconds)
            if interrupted:
                break
            continue
        if decision.status == "warn":
            log.warning(
                "supervisor.rate_limit.warn",
                count=decision.count_in_window,
                cap=decision.window_cap,
            )

        # 6. Launch a session.
        await _launch_session(ctx, state, next_task, role)

    return 0


async def _idle_sleep(ctx: SupervisorContext, idle_ticks: int) -> None:
    """Back off a little when there is no work to do.

    Adds up to ~3 seconds of extra sleep for long idle runs so we do not
    pin the event loop in a tight poll.
    """
    base = ctx.request_poll_seconds
    extra = min(idle_ticks * 0.5, 3.0)
    await sleep_or_shutdown(ctx.signal_state, base + extra)


# ---------------------------------------------------------------------------
# Launch one session.
# ---------------------------------------------------------------------------


async def _launch_session(
    ctx: SupervisorContext,
    state: StateFile,
    task: StatusFile,
    role: str,
) -> None:
    """Run a single session for ``task`` at ``role`` and update on-disk state."""
    log = structlog.get_logger(__name__).bind(component="supervisor")
    session_id = str(uuid7())
    model = MODEL_FOR_ROLE.get(role, "claude-sonnet-4-6")

    batch_id = state.batch_id
    session_timeout_seconds = _session_timeout_seconds(ctx)

    # Persist session-launch metadata BEFORE spawning. ADR-0002 D2 treats
    # session_budget as an advisory hint written into state.yaml.
    state.current_task = task.task_id
    state.current_agent = role  # type: ignore[assignment]
    state.session_id = session_id
    state.session_count = state.session_count + 1
    state.phase = "running"
    state.last_checkpoint = datetime.now(UTC)
    state.session_budget = SessionBudget(
        remaining_tokens=None,
        remaining_dollars=None,
        timeout_seconds=session_timeout_seconds,
    )
    write_state(ctx.root, state)

    if batch_id is not None:
        append_audit(
            ctx.root,
            batch_id,
            {
                "ts": datetime.now(UTC).isoformat(),
                "kind": "session-launched",
                "task_id": task.task_id,
                "role": role,
                "session_id": session_id,
                "model": model,
            },
        )

    ctx.rate_limit.record_launch()
    log.info(
        "supervisor.session.launch",
        task_id=task.task_id,
        role=role,
        session_id=session_id,
        model=model,
    )

    result: SessionResult = await run_session(
        root=ctx.root,
        task_id=task.task_id,
        role=role,
        session_id=session_id,
        model=model,
        session_timeout_seconds=session_timeout_seconds,
        session_budget=state.session_budget,
        event_queue=ctx.event_queue,
        claude_binary=ctx.claude_binary,
        env=ctx.session_env_overrides,
    )

    await _post_session(ctx, state, task, role, session_id, result)


async def _post_session(
    ctx: SupervisorContext,
    state: StateFile,
    task: StatusFile,
    role: str,
    session_id: str,
    result: SessionResult,
) -> None:
    """Apply the session outcome to on-disk state and retry counters."""
    log = structlog.get_logger(__name__).bind(component="supervisor")
    batch_id = state.batch_id
    now = datetime.now(UTC)

    attempt = ctx.attempts.setdefault(task.task_id, SessionAttempt(task_id=task.task_id))

    if result.end_state == "clean":
        attempt.consecutive_dirty = 0
    else:
        attempt.consecutive_dirty += 1

    if batch_id is not None:
        append_audit(
            ctx.root,
            batch_id,
            {
                "ts": now.isoformat(),
                "kind": "session-ended",
                "task_id": task.task_id,
                "role": role,
                "session_id": session_id,
                "end_state": result.end_state,
                "exit_code": result.exit_code,
                "duration_seconds": result.duration_seconds,
            },
        )

    log.info(
        "supervisor.session.end",
        task_id=task.task_id,
        role=role,
        session_id=session_id,
        end_state=result.end_state,
        consecutive_dirty=attempt.consecutive_dirty,
    )

    # B1 retry cap: two consecutive dirty ends transitions the task to
    # blocked. The full seven-category D7 taxonomy is B2.
    if attempt.consecutive_dirty >= DIRTY_END_CAP:
        await _block_task(ctx, state, task, session_id, result.end_state)
        return

    # Freshly re-read status.yaml so that any in-session agent-initiated
    # transition is respected. The supervisor only modifies status on
    # failure or terminal-state advancement - the agent owns the happy
    # path (ADR-0003 D2).
    with contextlib.suppress(FileNotFoundError):
        task = read_status(ctx.root, task.task_id)


async def _block_task(
    ctx: SupervisorContext,
    state: StateFile,
    task: StatusFile,
    session_id: str,
    end_state: str,
) -> None:
    """Mark ``task`` blocked after the retry cap is hit."""
    log = structlog.get_logger(__name__).bind(component="supervisor")
    now = datetime.now(UTC)
    blocker = f"auto-blocked after {DIRTY_END_CAP} consecutive {end_state} session(s)"

    task.history.append(
        HistoryEntry(
            at=now,
            from_=task.state,
            to="blocked",
            by="supervisor",
            session_id=session_id,
        )
    )
    task.state = "blocked"
    if blocker not in task.blockers:
        task.blockers.append(blocker)
    write_status(ctx.root, task)
    log.warning("supervisor.task.blocked", task_id=task.task_id, reason=blocker)

    if state.batch_id is not None:
        append_audit(
            ctx.root,
            state.batch_id,
            {
                "ts": now.isoformat(),
                "kind": "task-blocked",
                "task_id": task.task_id,
                "session_id": session_id,
                "reason": blocker,
            },
        )

    notification = Notification.make(
        kind="blocker",
        summary=f"task {task.task_id} auto-blocked: {blocker}",
        reply_verbs=["iterate", "stop", "escalate"],
        metadata={"task_id": task.task_id, "session_id": session_id},
    )
    await ctx.dispatcher.send(notification)


def _mark_task_done(ctx: SupervisorContext, task: StatusFile) -> None:
    """Transition a ``software-complete`` task to ``done`` (non-UI path).

    B1 uses this for the trivial case where a task has no UI review
    requirement. The foundational UI gate is ADR-0001 D6 / ADR-0004.
    """
    log = structlog.get_logger(__name__).bind(component="supervisor")
    if task.ui_review.required:
        log.info("supervisor.task.awaiting_ui_review", task_id=task.task_id)
        return
    now = datetime.now(UTC)
    task.history.append(
        HistoryEntry(
            at=now,
            from_=task.state,
            to="done",
            by="supervisor",
            session_id=None,
        )
    )
    task.state = "done"
    write_status(ctx.root, task)
    log.info("supervisor.task.done", task_id=task.task_id)


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _pick_next_task(root: Path, state: StateFile) -> StatusFile | None:
    """Return the first non-done, non-blocked task's status, or None."""
    try:
        batch = read_batch(root)
    except FileNotFoundError:
        return None

    # Prefer the current_task if one is live on state.yaml.
    ordered = list(batch.tasks)
    ordered.sort(key=lambda t: (t.priority, t.id))

    for task_entry in ordered:
        try:
            status = read_status(root, task_entry.id)
        except FileNotFoundError:
            status = StatusFile(
                version=1,
                task_id=task_entry.id,
                state="pending",
                foundational=task_entry.foundational,
            )
            # write_status relies on the parent directory existing — a
            # fresh task's folder may not be on disk yet, so create it.
            task_dir(root, task_entry.id).mkdir(parents=True, exist_ok=True)
            write_status(root, status)
        if status.state in ("done", "blocked"):
            continue
        return status
    return None


def _load_batch_budgets(root: Path) -> _BudgetRef | None:
    """Return a simplified view over the batch.yaml budgets section."""
    try:
        batch = read_batch(root)
    except FileNotFoundError:
        return None
    return _BudgetRef(
        max_tokens=batch.budgets.max_tokens,
        max_dollars=batch.budgets.max_dollars,
        wall_clock_hours=batch.budgets.wall_clock_hours,
        warn_threshold_pct=batch.notifications.warn_threshold_pct,
        session_timeout_minutes=batch.budgets.session_timeout_minutes,
    )


def _peek_batch_id(root: Path) -> str | None:
    """Return ``state.yaml.batch_id`` if the file exists; else ``None``."""
    try:
        return read_state(root).batch_id
    except FileNotFoundError:
        return None


def _session_timeout_seconds(ctx: SupervisorContext) -> int:
    """Resolve the session timeout from batch.yaml, with a 45-minute fallback."""
    budgets = _load_batch_budgets(ctx.root)
    if budgets is None:
        return 45 * 60
    return budgets.session_timeout_minutes * 60


def _transition_to_halted(
    ctx: SupervisorContext,
    state: StateFile,
    *,
    reason: str,
) -> None:
    """Atomically move the batch into ``halted`` with a reason."""
    log = structlog.get_logger(__name__).bind(component="supervisor")
    state.phase = "halted"
    state.halted_reason = reason
    state.last_checkpoint = datetime.now(UTC)
    write_state(ctx.root, state)
    log.warning("supervisor.halted", reason=reason)
    if state.batch_id is not None:
        append_audit(
            ctx.root,
            state.batch_id,
            {
                "ts": datetime.now(UTC).isoformat(),
                "kind": "batch-halted",
                "reason": reason,
            },
        )


async def _dispatch_rate_limit_notification(
    ctx: SupervisorContext,
    defer_seconds: int,
) -> None:
    """Emit a rate-limit notification via the dispatcher.

    ADR-0001 D5 says rate-limit pauses longer than 30 minutes become a
    Telegram notification. B1 emits unconditionally so the logging
    dispatcher records every deferral; B2 will add the threshold.
    """
    notification = Notification.make(
        kind="rate-limit",
        summary=f"rate-limit pause: sleeping {defer_seconds}s before next session",
        reply_verbs=["continue", "stop"],
    )
    await ctx.dispatcher.send(notification)


# ---------------------------------------------------------------------------
# Claude Code version check.
# ---------------------------------------------------------------------------


def _check_claude_version(settings: HuragokSettings) -> tuple[bool, str]:
    """Return ``(ok, message)`` for ``claude --version``.

    ``message`` is populated on failure with an operator-facing
    diagnostic. The minimum version lives in
    :data:`~orchestrator.constants.MIN_CLAUDE_CODE_VERSION`.
    """
    binary = os.environ.get("HURAGOK_CLAUDE_BINARY") or "claude"
    try:
        completed = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        return False, f"{binary!r} not found on PATH"
    except subprocess.TimeoutExpired:
        return False, f"{binary!r} did not respond to --version within 10s"

    raw = completed.stdout.strip() or completed.stderr.strip()
    m = _VERSION_RE.search(raw)
    if not m:
        return False, f"could not parse version from {raw!r}"
    observed = tuple(int(part) for part in m.groups())
    required = tuple(int(part) for part in MIN_CLAUDE_CODE_VERSION.split("."))
    if observed < required:
        return False, (
            f"claude version {'.'.join(str(p) for p in observed)} is below minimum "
            f"{MIN_CLAUDE_CODE_VERSION}"
        )
    _ = settings  # Settings reserved for future use (e.g. version-override flag).
    return True, f"claude version {'.'.join(str(p) for p in observed)} accepted"


# Simple record for the internal _load_batch_budgets helper.
@dataclass(frozen=True, slots=True)
class _BudgetRef:
    max_tokens: int
    max_dollars: float
    wall_clock_hours: float
    warn_threshold_pct: int
    session_timeout_minutes: int


# Type alias for backwards readability.
Phase = Literal["idle", "running", "paused", "halted", "complete"]
