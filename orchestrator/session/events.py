"""Events pumped from the session runner onto the budget-tracker queue.

The runner produces one :class:`BudgetEvent` per parsed stream-json line,
plus a lifecycle pair (``session-started`` / ``session-ended``) that lets
the tracker flush state at the right moments. Every event carries its
session context so the tracker can correctly associate usage with a
session even when (future) multiple runners produce events concurrently.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:  # pragma: no cover — typing-only imports
    from orchestrator.session.runner import SessionResult
    from orchestrator.session.stream import StreamEvent

BudgetEventKind = Literal["session-started", "stream-event", "session-ended"]


@dataclass(frozen=True, slots=True)
class SessionContext:
    """Immutable session metadata passed alongside every event."""

    session_id: str
    task_id: str
    role: str
    model: str
    started_at: datetime


@dataclass(frozen=True, slots=True, kw_only=True)
class BudgetEvent:
    """A single item on the ``event_queue`` consumed by the budget tracker.

    Exactly one of :attr:`stream_event` and :attr:`session_result` is
    populated, depending on :attr:`kind`. ``session-started`` events carry
    neither.
    """

    kind: BudgetEventKind
    ctx: SessionContext
    at: datetime
    stream_event: StreamEvent | None = None
    session_result: SessionResult | None = None


__all__ = [
    "BudgetEvent",
    "BudgetEventKind",
    "SessionContext",
]
