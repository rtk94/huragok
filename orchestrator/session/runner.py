"""Launch, observe, and account for a single ``claude -p`` session.

Each :func:`run_session` call owns one subprocess from spawn to exit. It
emits parsed stream events onto the budget tracker's queue, enforces the
wall-clock timeout by escalating SIGTERM→SIGKILL, and returns a
:class:`SessionResult` describing the outcome. See ADR-0002 D2.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import structlog

from orchestrator.session.events import BudgetEvent, SessionContext
from orchestrator.session.stream import (
    ResultEvent,
    StreamParseError,
    UserEvent,
    parse_event,
)
from orchestrator.state import SessionBudget

__all__ = [
    "DEFAULT_SESSION_PROMPT",
    "SESSION_END_STATES",
    "SessionResult",
    "default_session_env",
    "run_session",
]


# ADR-0002 D2: the minimal deterministic prompt passed to ``claude -p``.
# Per-session variance lives in state.yaml. The ``{role}`` placeholder is
# the one concession to ADR-0003's one-role-per-session model.
DEFAULT_SESSION_PROMPT = (
    "Read .huragok/state.yaml and .huragok/work/{task_id}/. "
    "Execute the {role} agent per .claude/agents/{role}.md. "
    "Return when you have completed your role's responsibilities and "
    "written the required artifacts to the task folder."
)

SESSION_END_STATES = ("clean", "dirty", "timeout", "rate-limited")

# Seconds to wait between SIGTERM and SIGKILL when a session times out.
_GRACE_PERIOD_SECONDS: int = 30

# Stderr tail buffer size, in lines.
_STDERR_TAIL_LINES: int = 50

# Env vars that are safe to inherit from the parent process. Everything
# else is scrubbed. Narrow list by design — subprocess envs should be
# deterministic, not an accident of whatever spawned the daemon.
_INHERIT_ENV_KEYS: frozenset[str] = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TERM",
        "TMPDIR",
        "TZ",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "CLAUDE_CONFIG_DIR",
    }
)


@dataclass(frozen=True, slots=True)
class SessionResult:
    """Outcome of one session, returned by :func:`run_session`."""

    session_id: str
    end_state: Literal["clean", "dirty", "timeout", "rate-limited"]
    exit_code: int | None
    result_event: ResultEvent | None
    stderr_tail: list[str]
    duration_seconds: float


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


async def run_session(
    *,
    root: Path,
    task_id: str,
    role: str,
    session_id: str,
    model: str,
    session_timeout_seconds: int,
    session_budget: SessionBudget,
    event_queue: asyncio.Queue[BudgetEvent],
    claude_binary: str = "claude",
    subagent_model: str = "claude-sonnet-4-6",
    env: dict[str, str] | None = None,
) -> SessionResult:
    """Spawn ``claude -p``, pump its stream-json stdout, return the outcome.

    ``session_budget`` is accepted for contract symmetry with ADR-0002 D2
    (the Supervisor writes it into ``state.yaml`` before calling us); the
    runner itself does no budget enforcement — that is the tracker's job.
    """
    log = structlog.get_logger(__name__).bind(
        component="session-runner",
        session_id=session_id,
        task_id=task_id,
        role=role,
        model=model,
    )

    started_at = datetime.now(UTC)
    monotonic_start = time.monotonic()
    ctx = SessionContext(
        session_id=session_id,
        task_id=task_id,
        role=role,
        model=model,
        started_at=started_at,
    )

    argv = _build_argv(
        claude_binary=claude_binary,
        root=root,
        task_id=task_id,
        role=role,
        model=model,
    )
    process_env = default_session_env(
        subagent_model=subagent_model,
        extra=env,
    )

    log.info("session.spawn", argv=[*argv[:2], "<prompt>"], cwd=str(root))

    await event_queue.put(
        BudgetEvent(kind="session-started", ctx=ctx, at=started_at),
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(root),
            env=process_env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        log.error("session.spawn.failed", error=str(exc))
        result = _make_result(
            session_id=session_id,
            end_state="dirty",
            exit_code=None,
            result_event=None,
            stderr_tail=[f"spawn failed: {exc}"],
            duration=0.0,
        )
        await event_queue.put(
            BudgetEvent(
                kind="session-ended",
                ctx=ctx,
                at=datetime.now(UTC),
                session_result=result,
            ),
        )
        return result

    stderr_tail: deque[str] = deque(maxlen=_STDERR_TAIL_LINES)
    terminal_result: list[ResultEvent] = []
    rate_limited: list[bool] = [False]
    saw_user_error: list[bool] = [False]

    pump_tasks = [
        asyncio.create_task(
            _pump_stdout(
                proc.stdout,
                ctx=ctx,
                event_queue=event_queue,
                terminal_result=terminal_result,
                rate_limited=rate_limited,
                saw_user_error=saw_user_error,
                log=log,
            )
        ),
        asyncio.create_task(_drain_stderr(proc.stderr, stderr_tail)),
    ]

    timed_out = False
    try:
        await asyncio.wait_for(
            _await_completion(proc, pump_tasks),
            timeout=session_timeout_seconds,
        )
    except TimeoutError:
        timed_out = True
        log.warning("session.timeout", timeout_seconds=session_timeout_seconds)
        _terminate(proc)
        try:
            await asyncio.wait_for(proc.wait(), timeout=_GRACE_PERIOD_SECONDS)
        except TimeoutError:
            log.warning("session.kill", reason="grace-period-exceeded")
            _kill(proc)
            await proc.wait()
        for task in pump_tasks:
            if not task.done():
                task.cancel()
        # Swallow any pump-task cancellation / residual exceptions.
        await asyncio.gather(*pump_tasks, return_exceptions=True)

    duration = time.monotonic() - monotonic_start
    exit_code = proc.returncode

    end_state = _classify_end(
        timed_out=timed_out,
        rate_limited=rate_limited[0],
        exit_code=exit_code,
        result_event=terminal_result[0] if terminal_result else None,
        saw_user_error=saw_user_error[0],
    )

    stderr_tail_list = list(stderr_tail)
    result = _make_result(
        session_id=session_id,
        end_state=end_state,
        exit_code=exit_code,
        result_event=terminal_result[0] if terminal_result else None,
        stderr_tail=stderr_tail_list,
        duration=duration,
    )

    log.info(
        "session.end",
        end_state=end_state,
        exit_code=exit_code,
        duration_seconds=round(duration, 3),
        stderr_lines=len(stderr_tail_list),
    )

    await event_queue.put(
        BudgetEvent(
            kind="session-ended",
            ctx=ctx,
            at=datetime.now(UTC),
            session_result=result,
        ),
    )
    return result


# ---------------------------------------------------------------------------
# Environment and argv.
# ---------------------------------------------------------------------------


def default_session_env(
    *,
    subagent_model: str,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return the scrubbed env dict passed to every session subprocess.

    Only a narrow allowlist of keys is inherited from the parent process
    (``PATH``, locale, ``HOME``, etc.). ``CLAUDE_CODE_SUBAGENT_MODEL`` is
    pinned so worker subagents default to Sonnet per ADR-0002 D2.
    ``ANTHROPIC_API_KEY`` is passed through only if the parent has it set.
    Callers may pass ``extra`` to add or override specific keys (tests use
    this to set ``FAKE_CLAUDE_MODE``).
    """
    parent = os.environ
    scrubbed: dict[str, str] = {k: parent[k] for k in _INHERIT_ENV_KEYS if k in parent}
    scrubbed["CLAUDE_CODE_SUBAGENT_MODEL"] = subagent_model
    if "ANTHROPIC_API_KEY" in parent:
        scrubbed["ANTHROPIC_API_KEY"] = parent["ANTHROPIC_API_KEY"]
    if extra:
        scrubbed.update(extra)
    return scrubbed


def _build_argv(
    *,
    claude_binary: str,
    root: Path,
    task_id: str,
    role: str,
    model: str,
) -> list[str]:
    """Compose the ``claude -p`` argv. Deterministic for auditable diffs."""
    prompt = DEFAULT_SESSION_PROMPT.format(task_id=task_id, role=role)
    argv = [
        claude_binary,
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        model,
    ]
    agent_file = root / ".claude" / "agents" / f"{role}.md"
    if agent_file.is_file():
        argv.extend(["--append-system-prompt", agent_file.read_text(encoding="utf-8")])
    return argv


# ---------------------------------------------------------------------------
# Async plumbing.
# ---------------------------------------------------------------------------


async def _pump_stdout(
    reader: asyncio.StreamReader | None,
    *,
    ctx: SessionContext,
    event_queue: asyncio.Queue[BudgetEvent],
    terminal_result: list[ResultEvent],
    rate_limited: list[bool],
    saw_user_error: list[bool],
    log: structlog.stdlib.BoundLogger,
) -> None:
    """Read subprocess stdout line-by-line; parse + publish each event."""
    if reader is None:  # pragma: no cover — asyncio always populates stdout
        return
    while True:
        raw = await reader.readline()
        if not raw:
            return
        try:
            event = parse_event(raw)
        except StreamParseError as exc:
            log.warning(
                "session.stream.malformed",
                error=str(exc),
                preview=raw[:120].decode("utf-8", errors="replace"),
            )
            continue

        if isinstance(event, ResultEvent):
            terminal_result.append(event)
            if event.is_error and event.subtype and "rate" in event.subtype.lower():
                rate_limited[0] = True
        elif isinstance(event, UserEvent) and event.is_error:
            saw_user_error[0] = True

        await event_queue.put(
            BudgetEvent(
                kind="stream-event",
                ctx=ctx,
                at=datetime.now(UTC),
                stream_event=event,
            )
        )


async def _drain_stderr(
    reader: asyncio.StreamReader | None,
    tail: deque[str],
) -> None:
    """Accumulate the last ``_STDERR_TAIL_LINES`` lines of stderr."""
    if reader is None:  # pragma: no cover
        return
    while True:
        raw = await reader.readline()
        if not raw:
            return
        tail.append(raw.decode("utf-8", errors="replace").rstrip("\r\n"))


async def _await_completion(
    proc: asyncio.subprocess.Process,
    pump_tasks: list[asyncio.Task[None]],
) -> None:
    """Wait for the subprocess to exit and every pump task to drain."""
    await proc.wait()
    await asyncio.gather(*pump_tasks, return_exceptions=True)


def _terminate(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        proc.send_signal(signal.SIGTERM)


def _kill(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        proc.kill()


# ---------------------------------------------------------------------------
# End-state classification.
# ---------------------------------------------------------------------------


def _classify_end(
    *,
    timed_out: bool,
    rate_limited: bool,
    exit_code: int | None,
    result_event: ResultEvent | None,
    saw_user_error: bool,
) -> Literal["clean", "dirty", "timeout", "rate-limited"]:
    """Apply ADR-0002 D2's session-end taxonomy (B1 subset)."""
    if timed_out:
        return "timeout"
    if rate_limited:
        return "rate-limited"
    if exit_code == 0 and result_event is not None and not result_event.is_error:
        return "clean"
    return "dirty"


def _make_result(
    *,
    session_id: str,
    end_state: Literal["clean", "dirty", "timeout", "rate-limited"],
    exit_code: int | None,
    result_event: ResultEvent | None,
    stderr_tail: list[str],
    duration: float,
) -> SessionResult:
    return SessionResult(
        session_id=session_id,
        end_state=end_state,
        exit_code=exit_code,
        result_event=result_event,
        stderr_tail=stderr_tail,
        duration_seconds=round(duration, 3),
    )
