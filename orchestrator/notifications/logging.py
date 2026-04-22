"""No-network dispatcher that logs notifications instead of sending them.

:class:`LoggingDispatcher` is the B1 stand-in for the real Telegram
dispatcher shipped in B2. Every ``send()`` call emits a structured log
record at INFO and, if a batch-scoped audit root is configured, appends
a ``notification-sent`` event to ``.huragok/audit/<batch_id>.jsonl``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import structlog

from orchestrator.notifications.base import Notification, NotificationDispatcher
from orchestrator.state import append_audit

__all__ = ["LoggingDispatcher"]


class LoggingDispatcher(NotificationDispatcher):
    """Notification dispatcher that logs instead of sending.

    Constructed with optional ``root`` + ``batch_id`` so it can append a
    ``notification-sent`` audit event per ADR-0002 D9. Without those
    arguments it only logs (useful for unit tests).
    """

    def __init__(
        self,
        *,
        root: Path | None = None,
        batch_id: str | None = None,
    ) -> None:
        self._root = root
        self._batch_id = batch_id
        self._log = structlog.get_logger(__name__).bind(component="notification-dispatcher")
        self._sent: set[str] = set()

    async def send(self, notification: Notification) -> None:
        """Log the notification and append a ``notification-sent`` audit event."""
        if notification.id in self._sent:
            # Idempotency — a double-send with the same id is a no-op.
            return
        self._sent.add(notification.id)

        self._log.info(
            "notification.sent",
            notification_id=notification.id,
            kind=notification.kind,
            summary=notification.summary,
            reply_verbs=notification.reply_verbs,
        )

        if self._root is not None and self._batch_id is not None:
            append_audit(
                self._root,
                self._batch_id,
                {
                    "ts": datetime.now(UTC).isoformat(),
                    "kind": "notification-sent",
                    "notification_id": notification.id,
                    "notification_kind": notification.kind,
                    "summary": notification.summary,
                    "reply_verbs": notification.reply_verbs,
                    "artifact_path": notification.artifact_path,
                },
            )

    @property
    def sent_ids(self) -> frozenset[str]:
        """Return the set of notification ids dispatched so far."""
        return frozenset(self._sent)
