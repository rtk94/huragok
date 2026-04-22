"""Abstract notification dispatcher and the :class:`Notification` payload.

A :class:`Notification` carries the operator-facing summary and the set
of reply verbs the dispatcher recognises. The abstract
:class:`NotificationDispatcher` is the contract B2 implements on top of;
B1 only ships :class:`~.logging.LoggingDispatcher`.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from uuid_v7.base import uuid7

from orchestrator.state.schemas import NotificationKind

__all__ = [
    "Notification",
    "NotificationDispatcher",
]


@dataclass(frozen=True, slots=True)
class Notification:
    """One operator-facing message, routed through a dispatcher.

    ``id`` is a UUIDv7 string, time-ordered for easy correlation with
    audit events. ``kind`` is the typed notification taxonomy from
    ADR-0002 D5. ``reply_verbs`` is the subset of ``continue|iterate|
    stop|escalate`` (plus aliases) the dispatcher should accept for this
    specific notification.
    """

    id: str
    kind: NotificationKind
    summary: str
    created_at: datetime
    artifact_path: str | None = None
    reply_verbs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def make(
        cls,
        *,
        kind: NotificationKind,
        summary: str,
        artifact_path: str | None = None,
        reply_verbs: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Notification:
        """Construct a notification with a fresh UUIDv7 id and ``created_at``."""
        return cls(
            id=str(uuid7()),
            kind=kind,
            summary=summary,
            created_at=datetime.now(UTC),
            artifact_path=artifact_path,
            reply_verbs=list(reply_verbs) if reply_verbs is not None else [],
            metadata=dict(metadata) if metadata is not None else {},
        )


class NotificationDispatcher(ABC):
    """Abstract base for all notification backends.

    Subclasses implement :meth:`send`, which pushes a notification to
    whatever backend the subclass owns. Long-running dispatchers (e.g.
    the B2 Telegram poller) override :meth:`start` to run their own
    coroutine alongside the supervisor; the default awaits the provided
    stop event and returns.
    """

    @abstractmethod
    async def send(self, notification: Notification) -> None:
        """Dispatch ``notification`` to the backend. Must be idempotent.

        Implementations must tolerate being called multiple times with
        the same ``notification.id`` — the Supervisor may retry after a
        transient failure.
        """

    async def start(self, stop_event: asyncio.Event) -> None:
        """Long-running coroutine. Default: await ``stop_event`` and return.

        B2's ``TelegramDispatcher`` overrides this to run the
        ``getUpdates`` long-poll loop until shutdown.
        """
        await stop_event.wait()
