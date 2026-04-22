"""Notification dispatch interface (ADR-0002 D6).

B1 ships only the abstract :class:`NotificationDispatcher` and a
no-network :class:`LoggingDispatcher` that writes sends into the
structured log and the per-batch audit trail. B2 adds the real
``TelegramDispatcher`` by subclassing the same base.
"""

from orchestrator.notifications.base import (
    Notification,
    NotificationDispatcher,
)
from orchestrator.notifications.logging import LoggingDispatcher

__all__ = [
    "LoggingDispatcher",
    "Notification",
    "NotificationDispatcher",
]
