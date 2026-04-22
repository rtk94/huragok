"""Tests for ``orchestrator.notifications.logging``."""

from __future__ import annotations

import json
from pathlib import Path

from orchestrator.notifications import LoggingDispatcher, Notification
from orchestrator.paths import audit_log


async def test_send_logs_and_records_sent_id(tmp_huragok_root: Path) -> None:
    dispatcher = LoggingDispatcher(root=tmp_huragok_root, batch_id="batch-001")
    notif = Notification.make(kind="error", summary="something broke")
    await dispatcher.send(notif)

    assert notif.id in dispatcher.sent_ids


async def test_send_is_idempotent(tmp_huragok_root: Path) -> None:
    dispatcher = LoggingDispatcher(root=tmp_huragok_root, batch_id="batch-001")
    notif = Notification.make(kind="error", summary="once")
    await dispatcher.send(notif)
    await dispatcher.send(notif)  # second call no-ops
    # Only one audit entry.
    lines = audit_log(tmp_huragok_root, "batch-001").read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["kind"] == "notification-sent"
    assert record["notification_id"] == notif.id


async def test_send_without_batch_id_skips_audit(tmp_path: Path) -> None:
    dispatcher = LoggingDispatcher()
    notif = Notification.make(kind="error", summary="no audit")
    # Should not raise.
    await dispatcher.send(notif)
    assert notif.id in dispatcher.sent_ids


async def test_send_records_metadata_fields(tmp_huragok_root: Path) -> None:
    dispatcher = LoggingDispatcher(root=tmp_huragok_root, batch_id="batch-001")
    notif = Notification.make(
        kind="foundational-gate",
        summary="UI gate",
        artifact_path="screenshots/foo.png",
        reply_verbs=["continue", "iterate"],
    )
    await dispatcher.send(notif)
    record = json.loads(audit_log(tmp_huragok_root, "batch-001").read_text().strip())
    assert record["notification_kind"] == "foundational-gate"
    assert record["artifact_path"] == "screenshots/foo.png"
    assert record["reply_verbs"] == ["continue", "iterate"]
