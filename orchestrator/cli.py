"""Huragok CLI.

Slice A implemented the read-only inspection commands (``status``,
``tasks``, ``show``); B1 promotes ``run``, ``stop``, and ``halt`` to
real implementations that drive the asyncio supervisor defined in
:mod:`orchestrator.supervisor`. ``submit``, ``reply``, and ``logs``
remain B2 stubs.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
from pathlib import Path
from typing import Annotated

import structlog
import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table
from rich.text import Text

from orchestrator.config import load_settings
from orchestrator.constants import (
    IMPLEMENTATION_FILE,
    REVIEW_FILE,
    SPEC_FILE,
    STATUS_FILE,
    TESTS_FILE,
    UI_REVIEW_FILE,
)
from orchestrator.logging_setup import configure_logging
from orchestrator.paths import (
    HuragokNotFoundError,
    daemon_pid_file,
    find_huragok_root,
    requests_dir,
    task_dir,
)
from orchestrator.state import (
    ArtifactFormatError,
    BatchFile,
    StateFile,
    StatusFile,
    read_artifact,
    read_batch,
    read_state,
    read_status,
)

app = typer.Typer(
    name="huragok",
    help="Autonomous multi-agent development orchestration for Claude Code.",
    no_args_is_help=True,
)

stdout = Console()
stderr = Console(stderr=True)


# ---------------------------------------------------------------------------
# Shared helpers.
# ---------------------------------------------------------------------------


def _resolve_root() -> Path:
    """Find the repo root (parent of ``.huragok/``) or exit with an error."""
    try:
        return find_huragok_root()
    except HuragokNotFoundError as exc:
        stderr.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc


def _init_logging() -> None:
    """Configure structlog once per CLI invocation, per ADR-0002 D9."""
    settings = load_settings()
    configure_logging(level=settings.log_level)
    structlog.contextvars.bind_contextvars(component="cli")


def _stub(name: str) -> None:
    """Exit with the canonical Slice-B placeholder message."""
    typer.secho(
        f"huragok {name}: not implemented until Slice B",
        err=True,
        fg=typer.colors.RED,
    )
    raise typer.Exit(1)


def _load_batch_if_any(root: Path) -> BatchFile | None:
    """Read batch.yaml if it exists and validates; otherwise return None."""
    try:
        return read_batch(root)
    except FileNotFoundError:
        return None


def _load_task_statuses(root: Path, batch: BatchFile) -> dict[str, StatusFile]:
    """Load every status.yaml referenced by the batch, where it exists."""
    statuses: dict[str, StatusFile] = {}
    for task in batch.tasks:
        status_path = task_dir(root, task.id) / STATUS_FILE
        if not status_path.exists():
            continue
        try:
            statuses[task.id] = read_status(root, task.id)
        except ValidationError:
            # A malformed status file on one task shouldn't break the
            # whole view; surface as an unknown state instead.
            continue
    return statuses


# ---------------------------------------------------------------------------
# Formatting helpers for the status view.
# ---------------------------------------------------------------------------


def _fmt_duration(seconds: float) -> str:
    total_minutes = int(seconds // 60)
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _fmt_hours(hours: float) -> str:
    return _fmt_duration(hours * 3600)


def _fmt_count(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _pct(numerator: float, denominator: float) -> int:
    if denominator <= 0:
        return 0
    return round(100 * numerator / denominator)


def _count_by_state(statuses: dict[str, StatusFile], total_tasks: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    for status in statuses.values():
        counts[status.state] = counts.get(status.state, 0) + 1
    # Tasks with no status.yaml on disk are implicitly pending.
    counts["pending"] = counts.get("pending", 0) + (total_tasks - len(statuses))
    return counts


def _render_human_status(
    state: StateFile,
    batch: BatchFile | None,
    statuses: dict[str, StatusFile],
) -> None:
    """Print the ADR-0002 D9 status view using rich."""
    header_label = state.batch_id or "no-batch"
    phase_fragment = state.phase
    if state.phase == "paused" and state.halted_reason:
        phase_fragment = f"paused — {state.halted_reason}"
    stdout.print(Text(f"huragok — {header_label} ({phase_fragment})", style="bold"))
    stdout.print("═" * 63)

    if batch is None:
        stdout.print("idle — no batch in flight")
        return

    consumed = state.budget_consumed
    budgets = batch.budgets

    elapsed = _fmt_duration(consumed.wall_clock_seconds)
    wall_budget = _fmt_hours(budgets.wall_clock_hours)
    wall_pct = _pct(consumed.wall_clock_seconds, budgets.wall_clock_hours * 3600)
    stdout.print(f"Elapsed:        {elapsed} / {wall_budget}    ({wall_pct}%)")

    tokens_total = consumed.tokens_input + consumed.tokens_output
    token_pct = _pct(tokens_total, budgets.max_tokens)
    stdout.print(
        f"Tokens:         {_fmt_count(tokens_total)} / {_fmt_count(budgets.max_tokens)}    "
        f"({token_pct}%)  "
        f"input {_fmt_count(consumed.tokens_input)}  output {_fmt_count(consumed.tokens_output)}"
    )

    dollar_pct = _pct(consumed.dollars, budgets.max_dollars)
    stdout.print(
        f"Dollars:        ${consumed.dollars:.2f} / ${budgets.max_dollars:.2f}    "
        f"({dollar_pct}%)  (table est., not reconciled)"
    )
    stdout.print(f"Iterations:     {consumed.iterations} / {budgets.max_iterations}")
    stdout.print(f"Sessions:       {state.session_count} launched")
    stdout.print()

    if state.current_task:
        stdout.print(f"Current task:   {state.current_task}")
        if state.current_agent:
            stdout.print(f"  agent:        {state.current_agent}")
        if state.session_id:
            stdout.print(f"  session:      {state.session_id}")
        stdout.print()

    counts = _count_by_state(statuses, len(batch.tasks))
    in_flight = sum(counts.get(s, 0) for s in ("speccing", "implementing", "testing", "reviewing"))
    stdout.print(
        f"Tasks:          {len(batch.tasks)} total · "
        f"{counts.get('done', 0)} done · {in_flight} in-flight · "
        f"{counts.get('pending', 0)} pending · {counts.get('blocked', 0)} blocked"
    )

    stdout.print()
    if state.awaiting_reply.notification_id:
        stdout.print(f"Pending notifications:  awaiting reply ({state.awaiting_reply.kind})")
    else:
        stdout.print("Pending notifications:  (none)")


# ---------------------------------------------------------------------------
# Commands.
# ---------------------------------------------------------------------------


@app.command()
def status(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit state.yaml as JSON for programmatic use."),
    ] = False,
) -> None:
    """Show the orchestrator's current state."""
    root = _resolve_root()
    _init_logging()

    try:
        state = read_state(root)
    except FileNotFoundError as exc:
        stderr.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(1) from exc

    if json_output:
        payload = state.model_dump(mode="json", by_alias=True)
        typer.echo(json.dumps(payload, indent=2, default=str, sort_keys=False))
        return

    batch = _load_batch_if_any(root)
    statuses = _load_task_statuses(root, batch) if batch is not None else {}
    _render_human_status(state, batch, statuses)


@app.command()
def tasks(
    state: Annotated[
        str | None,
        typer.Option("--state", help="Filter by status.yaml.state value."),
    ] = None,
) -> None:
    """List the current batch's tasks, optionally filtered by state."""
    root = _resolve_root()
    _init_logging()

    batch = _load_batch_if_any(root)
    if batch is None or not batch.tasks:
        typer.echo("no batch in flight")
        return

    table = Table(title=f"Tasks — {batch.batch_id}", show_lines=False)
    table.add_column("ID", no_wrap=True)
    table.add_column("State", no_wrap=True)
    table.add_column("Kind", no_wrap=True)
    table.add_column("Priority", justify="right", no_wrap=True)
    table.add_column("Title", overflow="fold")

    statuses = _load_task_statuses(root, batch)
    rendered = 0
    for task in batch.tasks:
        resolved_state = statuses[task.id].state if task.id in statuses else "pending"
        if state is not None and resolved_state != state:
            continue
        table.add_row(task.id, resolved_state, task.kind, str(task.priority), task.title)
        rendered += 1

    if rendered == 0:
        typer.echo("(no tasks match filter)")
        return

    stdout.print(table)


@app.command()
def show(
    task_id: Annotated[str, typer.Argument(help="Task ID to inspect.")],
    full: Annotated[
        bool,
        typer.Option("--full", help="Inline every artifact body under ## headings."),
    ] = False,
) -> None:
    """Show a task's summary; ``--full`` inlines every artifact body."""
    root = _resolve_root()
    _init_logging()

    folder = task_dir(root, task_id)
    if not folder.is_dir():
        stderr.print(f"[red]error:[/red] task not found: {task_id}")
        raise typer.Exit(1)

    status_obj: StatusFile | None = None
    status_path = folder / STATUS_FILE
    if status_path.exists():
        try:
            status_obj = read_status(root, task_id)
        except ValidationError as exc:
            stderr.print(f"[yellow]warn:[/yellow] malformed status.yaml: {exc}")

    title = _artifact_title(folder / SPEC_FILE)

    stdout.print(Text(task_id, style="bold"))
    if title is not None:
        stdout.print(f"  title:        {title}")
    if status_obj is not None:
        stdout.print(f"  state:        {status_obj.state}")
        stdout.print(f"  foundational: {str(status_obj.foundational).lower()}")
        if status_obj.blockers:
            stdout.print("  blockers:")
            for blocker in status_obj.blockers:
                stdout.print(f"    - {blocker}")
        if status_obj.ui_review.required:
            resolved = status_obj.ui_review.resolved or "pending"
            stdout.print(f"  ui_review:    required (resolved: {resolved})")

    artifact_order = (
        SPEC_FILE,
        IMPLEMENTATION_FILE,
        TESTS_FILE,
        REVIEW_FILE,
        UI_REVIEW_FILE,
    )
    present = [name for name in artifact_order if (folder / name).exists()]
    if present:
        stdout.print(f"  artifacts:    {', '.join(present)}")

    if not full:
        return

    for name in present:
        stdout.print()
        stdout.print(Text(f"## {name}", style="bold"))
        stdout.print()
        try:
            _, body = read_artifact(folder / name)
        except ArtifactFormatError as exc:
            stderr.print(f"[yellow]warn:[/yellow] {exc}")
            continue
        stdout.print(body.rstrip() or "(empty body)")


def _artifact_title(spec_path: Path) -> str | None:
    """Pull the first ``# Heading`` from a spec.md body, if present."""
    if not spec_path.exists():
        return None
    try:
        _, body = read_artifact(spec_path)
    except ArtifactFormatError:
        return None
    for line in body.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return None


# ---------------------------------------------------------------------------
# Supervisor lifecycle: run / stop / halt.
# ---------------------------------------------------------------------------


@app.command()
def run() -> None:
    """Start the orchestrator daemon in the foreground."""
    # Imported lazily so that `huragok --help` and read-only commands do not
    # pay the import cost of the asyncio supervisor stack.
    from orchestrator.supervisor.loop import run as supervisor_run

    root = _resolve_root()
    _init_logging()
    settings = load_settings()

    exit_code = asyncio.run(supervisor_run(root, settings))
    raise typer.Exit(exit_code)


@app.command()
def start() -> None:
    """Start the orchestrator daemon as a systemd service (Slice B)."""
    _stub("start")


@app.command()
def stop() -> None:
    """Gracefully stop a running orchestrator daemon.

    Sends SIGTERM to the PID recorded in ``.huragok/daemon.pid``. If no
    daemon is running, exits 0 with a friendly message — a missing
    daemon is not an error condition.
    """
    root = _resolve_root()
    _init_logging()

    pid = _read_daemon_pid(root)
    if pid is None:
        typer.echo("no daemon running")
        return
    if not _process_alive(pid):
        typer.echo(f"stale pid file (pid {pid} not running); removing")
        daemon_pid_file(root).unlink(missing_ok=True)
        return

    # Belt-and-suspenders: write a ``stop`` request marker so the loop's
    # request-file poll picks it up even if signal delivery is slow.
    req_dir = requests_dir(root)
    req_dir.mkdir(parents=True, exist_ok=True)
    (req_dir / "stop").write_text("")

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        typer.echo(f"pid {pid} exited before the signal landed")
        return

    typer.echo(f"sent SIGTERM to pid {pid}")


@app.command()
def halt() -> None:
    """Halt a running batch after the in-flight session finishes.

    Writes ``.huragok/requests/halt`` and sends SIGUSR1 so the daemon
    picks up the request on the next tick. The current session continues
    to completion; no new sessions launch after it.
    """
    root = _resolve_root()
    _init_logging()

    req_dir = requests_dir(root)
    req_dir.mkdir(parents=True, exist_ok=True)
    halt_path = req_dir / "halt"
    halt_path.write_text("")

    pid = _read_daemon_pid(root)
    if pid is None or not _process_alive(pid):
        typer.echo("halt request written; no live daemon to signal")
        return
    try:
        os.kill(pid, signal.SIGUSR1)
    except ProcessLookupError:
        typer.echo("halt request written; daemon exited before signal")
        return
    typer.echo(f"halt request written; signalled pid {pid}")


# ---------------------------------------------------------------------------
# Still-stubbed Slice-B commands (promoted in B2).
# ---------------------------------------------------------------------------


@app.command()
def reply(
    verb: Annotated[str, typer.Argument(help="Reply verb.")],
    notification_id: Annotated[
        str | None,
        typer.Argument(help="Notification to reply to; omit if only one is outstanding."),
    ] = None,
) -> None:
    """Reply to a pending notification (Slice B)."""
    _stub("reply")


@app.command()
def submit(
    batch_path: Annotated[Path, typer.Argument(help="Path to a batch.yaml file.")],
) -> None:
    """Queue a batch for execution (Slice B)."""
    _stub("submit")


@app.command()
def logs(
    follow: Annotated[bool, typer.Option("--follow", "-f", help="Tail the log.")] = False,
    level: Annotated[
        str | None,
        typer.Option("--level", help="Minimum log level to include."),
    ] = None,
) -> None:
    """Tail the current batch log (Slice B)."""
    _stub("logs")


# ---------------------------------------------------------------------------
# CLI internals shared by run / stop / halt.
# ---------------------------------------------------------------------------


def _read_daemon_pid(root: Path) -> int | None:
    """Return the pid recorded in the daemon pid file, or None if absent."""
    pid_path = daemon_pid_file(root)
    try:
        raw = pid_path.read_text().strip()
    except FileNotFoundError:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _process_alive(pid: int) -> bool:
    """Return True if ``pid`` is a live process owned by anyone on this host."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
