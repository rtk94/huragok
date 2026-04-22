"""Tests for ``orchestrator.budget.rate_limit``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from orchestrator.budget.rate_limit import LOG_RETENTION_DAYS, RateLimitLog
from orchestrator.paths import rate_limit_log


@pytest.fixture
def rate_limit_root(tmp_path: Path) -> Path:
    (tmp_path / ".huragok").mkdir()
    return tmp_path


def test_load_empty_log(rate_limit_root: Path) -> None:
    log = RateLimitLog(rate_limit_root)
    log.load()
    assert log.entries == []


def test_record_launch_persists_across_reload(rate_limit_root: Path) -> None:
    log = RateLimitLog(rate_limit_root)
    log.load()
    ts = datetime(2026, 4, 21, 10, 0, tzinfo=UTC)
    log.record_launch(ts)

    # Reload a fresh instance and confirm the entry is there.
    fresh = RateLimitLog(rate_limit_root)
    fresh.load()
    assert len(fresh.entries) == 1
    assert fresh.entries[0] == ts


def test_load_truncates_old_entries(rate_limit_root: Path) -> None:
    now = datetime(2026, 4, 21, 10, 0, tzinfo=UTC)
    old = now - timedelta(days=LOG_RETENTION_DAYS + 1)
    recent = now - timedelta(days=1)

    log_path = rate_limit_log(rate_limit_root)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "entries": [old.isoformat(), recent.isoformat()],
            }
        )
    )

    log = RateLimitLog(rate_limit_root)
    log.load(now=now)
    assert len(log.entries) == 1
    assert log.entries[0] == recent


def test_query_returns_ok_when_empty(rate_limit_root: Path) -> None:
    log = RateLimitLog(rate_limit_root, window_cap=10, warn_threshold=0.8)
    log.load()
    decision = log.query()
    assert decision.status == "ok"
    assert decision.count_in_window == 0


def test_query_returns_warn_near_cap(rate_limit_root: Path) -> None:
    now = datetime(2026, 4, 21, 10, 0, tzinfo=UTC)
    log = RateLimitLog(rate_limit_root, window_cap=10, warn_threshold=0.8)
    log.load()
    for i in range(8):
        log.record_launch(now - timedelta(minutes=30 - i))
    decision = log.query(now=now)
    assert decision.status == "warn"
    assert decision.count_in_window == 8


def test_query_returns_defer_at_cap(rate_limit_root: Path) -> None:
    now = datetime(2026, 4, 21, 10, 0, tzinfo=UTC)
    log = RateLimitLog(rate_limit_root, window_cap=5, warn_threshold=0.8)
    log.load()
    for i in range(5):
        log.record_launch(now - timedelta(minutes=30 + i))
    decision = log.query(now=now)
    assert decision.status == "defer"
    assert decision.count_in_window == 5
    assert decision.defer_seconds > 0


def test_entries_outside_window_ignored(rate_limit_root: Path) -> None:
    now = datetime(2026, 4, 21, 10, 0, tzinfo=UTC)
    log = RateLimitLog(rate_limit_root, window_cap=3, warn_threshold=0.5)
    log.load()
    # 6 hours ago is outside the default 5-hour window.
    log.record_launch(now - timedelta(hours=6))
    decision = log.query(now=now)
    assert decision.status == "ok"
    assert decision.count_in_window == 0


def test_load_tolerates_corrupt_file(rate_limit_root: Path) -> None:
    log_path = rate_limit_log(rate_limit_root)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("*** not even yaml ***\n: :")
    log = RateLimitLog(rate_limit_root)
    log.load()  # Must not raise.
    assert log.entries == []


def test_load_ignores_unrecognised_entry_shape(rate_limit_root: Path) -> None:
    log_path = rate_limit_log(rate_limit_root)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "entries": [
                    {"at": "2026-04-21T10:00:00Z"},  # dict form
                    "2026-04-20T10:00:00Z",  # ISO string
                    42,  # garbage — should be dropped
                ],
            }
        )
    )
    log = RateLimitLog(rate_limit_root)
    log.load(now=datetime(2026, 4, 21, 12, 0, tzinfo=UTC))
    assert len(log.entries) == 2


def test_path_property(rate_limit_root: Path) -> None:
    log = RateLimitLog(rate_limit_root)
    assert log.path == rate_limit_log(rate_limit_root)
