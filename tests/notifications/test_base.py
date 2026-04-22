"""Tests for ``orchestrator.notifications.base``."""

from __future__ import annotations

import asyncio

from orchestrator.notifications import Notification, NotificationDispatcher


def test_notification_make_assigns_uuidv7_id() -> None:
    notif = Notification.make(kind="blocker", summary="bad thing")
    # UUIDv7 string length is 36 with hyphens; the version nibble lives
    # at position 14 ('7'). We don't hard-code too much so the test is
    # resilient to uuid_v7 library internals.
    assert len(notif.id) == 36
    assert notif.id[14] == "7"
    assert notif.kind == "blocker"
    assert notif.summary == "bad thing"
    assert notif.reply_verbs == []


def test_notification_make_copies_reply_verbs() -> None:
    verbs = ["continue", "stop"]
    notif = Notification.make(kind="error", summary="x", reply_verbs=verbs)
    # mutate the source list; the notification's list stays intact.
    verbs.append("hacked")
    assert notif.reply_verbs == ["continue", "stop"]


async def test_default_start_awaits_stop_event() -> None:
    class Dummy(NotificationDispatcher):
        async def send(self, notification: Notification) -> None:
            pass

    stop = asyncio.Event()
    dispatcher = Dummy()
    task = asyncio.create_task(dispatcher.start(stop))
    # Not yet finished.
    await asyncio.sleep(0)
    assert not task.done()
    stop.set()
    await asyncio.wait_for(task, timeout=1.0)
    assert task.done()
