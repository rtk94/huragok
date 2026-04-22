"""Signal wiring and request-file ingestion for the supervisor loop.

The supervisor installs POSIX signal handlers for ``SIGTERM`` / ``SIGINT``
(graceful shutdown) and ``SIGUSR1`` (scan the requests directory now
rather than on the next 1-2s tick). Shutdown is cooperative: every
coroutine polls the :class:`SignalState` between yield points; the
in-flight session is allowed to complete.

A second SIGTERM within the same process lifetime escalates to
immediate termination via ``os._exit`` — that matches ADR-0002 D1's
"second SIGTERM is SIGKILL" rule.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from dataclasses import dataclass, field
from pathlib import Path

import structlog
import yaml

from orchestrator.paths import requests_dir

__all__ = [
    "SignalState",
    "install_signal_handlers",
    "process_request_files",
]


@dataclass(slots=True)
class SignalState:
    """Mutable flags shared between the signal handlers and the supervisor loop."""

    shutting_down: asyncio.Event = field(default_factory=asyncio.Event)
    halt_after_session: asyncio.Event = field(default_factory=asyncio.Event)
    request_file_ready: asyncio.Event = field(default_factory=asyncio.Event)
    _sigterm_count: int = 0


@dataclass(frozen=True, slots=True)
class ParsedRequest:
    """One drained request file awaiting application by the supervisor."""

    kind: str
    path: Path
    payload: dict[str, object]


def install_signal_handlers(
    loop: asyncio.AbstractEventLoop,
    state: SignalState,
) -> None:
    """Install SIGTERM / SIGINT / SIGUSR1 handlers on ``loop``.

    Safe to call once per supervisor run. Silently skips the signals
    that aren't available on the current platform (Windows) — the daemon
    only runs on Linux in production.
    """
    log = structlog.get_logger(__name__).bind(component="signals")

    def _handle_term(signame: str) -> None:
        state._sigterm_count += 1
        if state._sigterm_count >= 2:
            log.warning("signal.term.escalating", reason="second term received")
            # Hard exit — skip graceful shutdown. Matches ADR-0002 D1's
            # "second SIGTERM is SIGKILL" rule.
            os._exit(128 + signal.SIGTERM)
        log.info("signal.term.received", signal=signame)
        state.shutting_down.set()

    def _handle_usr1() -> None:
        log.info("signal.usr1.received")
        state.request_file_ready.set()

    for sig_num, signame in (
        (signal.SIGTERM, "SIGTERM"),
        (signal.SIGINT, "SIGINT"),
    ):
        try:
            loop.add_signal_handler(sig_num, _handle_term, signame)
        except NotImplementedError:  # pragma: no cover — Windows only
            continue

    try:
        loop.add_signal_handler(signal.SIGUSR1, _handle_usr1)
    except NotImplementedError:  # pragma: no cover — Windows only
        pass
    except AttributeError:  # pragma: no cover — SIGUSR1 missing
        pass


# ---------------------------------------------------------------------------
# Request-file ingestion.
# ---------------------------------------------------------------------------


def process_request_files(
    root: Path,
    state: SignalState,
) -> list[ParsedRequest]:
    """Drain ``.huragok/requests/``, applying ``stop`` and ``halt`` markers.

    Returns every request file that was drained, parsed, and removed. The
    caller (the supervisor loop) is responsible for acting on
    ``reply-*.yaml`` payloads by passing them along to the dispatcher.
    ``stop`` and ``halt`` marker files are handled here by flipping the
    corresponding :class:`SignalState` event before deletion.

    Silently returns an empty list when the requests directory does not
    yet exist.
    """
    log = structlog.get_logger(__name__).bind(component="signals")
    dir_path = requests_dir(root)
    if not dir_path.is_dir():
        return []

    drained: list[ParsedRequest] = []
    for entry in sorted(dir_path.iterdir()):
        if not entry.is_file():
            continue
        name = entry.name
        try:
            if name == "stop":
                state.shutting_down.set()
                drained.append(ParsedRequest(kind="stop", path=entry, payload={}))
                entry.unlink(missing_ok=True)
            elif name == "halt":
                state.halt_after_session.set()
                drained.append(ParsedRequest(kind="halt", path=entry, payload={}))
                entry.unlink(missing_ok=True)
            elif name.startswith("reply-") and name.endswith(".yaml"):
                payload = _load_reply(entry)
                drained.append(ParsedRequest(kind="reply", path=entry, payload=payload))
                entry.unlink(missing_ok=True)
            else:
                log.debug("signals.requests.ignored", name=name)
        except OSError as exc:
            log.warning("signals.requests.drain_failed", name=name, error=str(exc))
            continue

    # Clear the edge-trigger; the next SIGUSR1 or 1-2s poll will set it again.
    state.request_file_ready.clear()
    return drained


def _load_reply(path: Path) -> dict[str, object]:
    """Parse a ``reply-*.yaml`` file; silently tolerate malformed payloads."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# Async helper: sleep with interruption on shutdown.
# ---------------------------------------------------------------------------


async def sleep_or_shutdown(
    state: SignalState,
    seconds: float,
) -> bool:
    """Sleep ``seconds`` or return early if shutdown fires.

    Returns ``True`` when shutdown interrupted the sleep, ``False`` when
    the full duration elapsed. Used by the loop's polling rhythm.
    """
    try:
        await asyncio.wait_for(state.shutting_down.wait(), timeout=seconds)
    except TimeoutError:
        return False
    return True


# Public re-export for the loop module.
with contextlib.suppress(ImportError):  # pragma: no cover — circular guard
    pass
