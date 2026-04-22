"""Tests for ``orchestrator.budget.tracker``."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from orchestrator.budget.pricing import load_pricing
from orchestrator.budget.tracker import (
    BudgetTracker,
    CostReconciler,
    CostReconciliationError,
    _extract_total_usd,
)
from orchestrator.notifications import LoggingDispatcher, Notification
from orchestrator.session.events import BudgetEvent, SessionContext
from orchestrator.session.runner import SessionResult
from orchestrator.session.stream import (
    AssistantEvent,
    ResultEvent,
    UsageBlock,
)
from orchestrator.state import read_state


class RecordingDispatcher(LoggingDispatcher):
    """LoggingDispatcher subclass that records every send for assertion."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[Notification] = []

    async def send(self, notification: Notification) -> None:
        self.sent.append(notification)
        await super().send(notification)


def _ctx(session_id: str = "01SESSION") -> SessionContext:
    return SessionContext(
        session_id=session_id,
        task_id="task-test",
        role="architect",
        model="claude-opus-4-7",
        started_at=datetime(2026, 4, 21, 10, 0, tzinfo=UTC),
    )


def _assistant_event(input_tokens: int, output_tokens: int) -> AssistantEvent:
    return AssistantEvent(
        raw={},
        session_id="01SESSION",
        model="claude-opus-4-7",
        usage=UsageBlock(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _result_event() -> ResultEvent:
    return ResultEvent(
        raw={},
        subtype="success",
        session_id="01SESSION",
        model="claude-opus-4-7",
        usage=UsageBlock(input_tokens=100, output_tokens=50),
        total_cost_usd=0.01,
        is_error=False,
        duration_ms=500.0,
    )


async def _feed(tracker: BudgetTracker, events: list[BudgetEvent]) -> None:
    """Put all events onto a queue, then drive one run() cycle to drain."""
    queue: asyncio.Queue[BudgetEvent] = asyncio.Queue()
    for ev in events:
        await queue.put(ev)
    stop = asyncio.Event()
    run_task = asyncio.create_task(tracker.run(queue, stop))
    # Let the tracker consume; wait for the queue to empty.
    while not queue.empty():
        await asyncio.sleep(0)
    stop.set()
    await asyncio.wait_for(run_task, timeout=2.0)


async def test_tracker_accumulates_tokens_and_dollars(tmp_huragok_root: Path) -> None:
    tracker = BudgetTracker(
        root=tmp_huragok_root,
        pricing=load_pricing(),
        dispatcher=RecordingDispatcher(),
        max_tokens=1_000_000,
        max_dollars=100.0,
        max_wall_clock_seconds=3600.0,
        batch_id="batch-001",
    )

    ctx = _ctx()
    events = [
        BudgetEvent(kind="session-started", ctx=ctx, at=ctx.started_at),
        BudgetEvent(
            kind="stream-event",
            ctx=ctx,
            at=ctx.started_at,
            stream_event=_assistant_event(100, 50),
        ),
        BudgetEvent(
            kind="stream-event",
            ctx=ctx,
            at=ctx.started_at,
            stream_event=_assistant_event(50, 25),
        ),
    ]
    await _feed(tracker, events)
    snap = tracker.snapshot()
    assert snap.tokens_input == 150
    assert snap.tokens_output == 75
    assert snap.dollars > 0


async def test_threshold_crossings_emit_notifications(tmp_huragok_root: Path) -> None:
    dispatcher = RecordingDispatcher()
    tracker = BudgetTracker(
        root=tmp_huragok_root,
        pricing=load_pricing(),
        dispatcher=dispatcher,
        max_tokens=200,  # intentionally small
        max_dollars=1_000.0,
        max_wall_clock_seconds=3600.0,
        warn_threshold_pct=80,
        batch_id="batch-001",
    )

    ctx = _ctx()
    events = [
        BudgetEvent(kind="session-started", ctx=ctx, at=ctx.started_at),
        BudgetEvent(
            kind="stream-event",
            ctx=ctx,
            at=ctx.started_at,
            stream_event=_assistant_event(120, 60),  # 180 tokens = 90% of 200
        ),
    ]
    await _feed(tracker, events)
    assert any(n.kind == "budget-threshold" for n in dispatcher.sent)

    # Another event pushing over 100%: the 100% notification fires and
    # over_budget becomes True.
    ctx2 = _ctx()
    over = [
        BudgetEvent(
            kind="stream-event",
            ctx=ctx2,
            at=ctx2.started_at,
            stream_event=_assistant_event(50, 50),
        ),
    ]
    await _feed(tracker, over)
    assert tracker.over_budget()
    # Two notifications now — 80% + 100%.
    kinds = [n.summary for n in dispatcher.sent]
    assert any("80%" in s for s in kinds)
    assert any("100%" in s for s in kinds)


async def test_threshold_notification_is_idempotent(tmp_huragok_root: Path) -> None:
    """Crossing the 80% line twice should only emit one notification."""
    dispatcher = RecordingDispatcher()
    tracker = BudgetTracker(
        root=tmp_huragok_root,
        pricing=load_pricing(),
        dispatcher=dispatcher,
        max_tokens=200,
        max_dollars=1_000.0,
        max_wall_clock_seconds=3600.0,
        warn_threshold_pct=80,
        batch_id="batch-001",
    )
    ctx = _ctx()
    events = [
        BudgetEvent(kind="session-started", ctx=ctx, at=ctx.started_at),
        BudgetEvent(
            kind="stream-event",
            ctx=ctx,
            at=ctx.started_at,
            stream_event=_assistant_event(120, 60),  # 90%
        ),
        BudgetEvent(
            kind="stream-event",
            ctx=ctx,
            at=ctx.started_at,
            stream_event=_assistant_event(1, 1),  # also > 80%
        ),
    ]
    await _feed(tracker, events)
    warn_notes = [n for n in dispatcher.sent if "80%" in n.summary]
    assert len(warn_notes) == 1


async def test_session_end_flushes_state(tmp_huragok_root: Path) -> None:
    tracker = BudgetTracker(
        root=tmp_huragok_root,
        pricing=load_pricing(),
        dispatcher=RecordingDispatcher(),
        max_tokens=10_000,
        max_dollars=100.0,
        max_wall_clock_seconds=3600.0,
        batch_id="batch-001",
    )
    ctx = _ctx()
    tracker.mark_batch_start(ctx.started_at)

    sr = SessionResult(
        session_id="01SESSION",
        end_state="clean",
        exit_code=0,
        result_event=_result_event(),
        stderr_tail=[],
        duration_seconds=12.5,
    )
    events = [
        BudgetEvent(kind="session-started", ctx=ctx, at=ctx.started_at),
        BudgetEvent(
            kind="stream-event",
            ctx=ctx,
            at=ctx.started_at,
            stream_event=_assistant_event(100, 50),
        ),
        BudgetEvent(
            kind="session-ended",
            ctx=ctx,
            at=ctx.started_at,
            session_result=sr,
        ),
    ]
    await _feed(tracker, events)

    # state.yaml should have been rewritten with the new consumed totals.
    state = read_state(tmp_huragok_root)
    assert state.budget_consumed.tokens_input >= 100
    assert state.budget_consumed.tokens_output >= 50
    assert state.budget_consumed.wall_clock_seconds == pytest.approx(12.5)


async def test_seed_from_state_resumes(tmp_huragok_root: Path) -> None:
    tracker = BudgetTracker(
        root=tmp_huragok_root,
        pricing=load_pricing(),
        dispatcher=RecordingDispatcher(),
        max_tokens=10_000,
        max_dollars=100.0,
        max_wall_clock_seconds=3600.0,
    )
    state = read_state(tmp_huragok_root)
    tracker.seed_from_state(state.budget_consumed)
    snap = tracker.snapshot()
    assert snap.tokens_input == state.budget_consumed.tokens_input
    assert snap.tokens_output == state.budget_consumed.tokens_output
    assert snap.dollars == state.budget_consumed.dollars


# ---------------------------------------------------------------------------
# Cost API reconciliation.
# ---------------------------------------------------------------------------


class FakeReconciler(CostReconciler):
    """Test double that short-circuits the HTTP call."""

    def __init__(self, *, payload: object | Exception) -> None:
        super().__init__(admin_api_key="fake-admin-key")
        self._payload = payload
        self.calls: list[tuple[datetime, datetime]] = []

    async def fetch(
        self,
        *,
        session_start: datetime,
        session_end: datetime,
    ) -> float | None:
        self.calls.append((session_start, session_end))
        if isinstance(self._payload, Exception):
            raise self._payload
        if self._payload is None:
            return None
        return float(self._payload)  # type: ignore[arg-type]


async def test_reconcile_supersedes_estimate(tmp_huragok_root: Path) -> None:
    dispatcher = RecordingDispatcher()
    reconciler = FakeReconciler(payload=0.42)
    tracker = BudgetTracker(
        root=tmp_huragok_root,
        pricing=load_pricing(),
        dispatcher=dispatcher,
        max_tokens=10_000,
        max_dollars=100.0,
        max_wall_clock_seconds=3600.0,
        reconciler=reconciler,
        batch_id="batch-001",
    )
    ctx = _ctx()
    tracker.mark_batch_start(ctx.started_at)
    await tracker.reconcile(
        session_id=ctx.session_id,
        session_start=ctx.started_at,
        session_end=ctx.started_at,
    )
    assert tracker.snapshot().dollars == pytest.approx(0.42)
    assert len(reconciler.calls) == 1


async def test_reconcile_empty_response_is_skipped(tmp_huragok_root: Path) -> None:
    reconciler = FakeReconciler(payload=None)
    tracker = BudgetTracker(
        root=tmp_huragok_root,
        pricing=load_pricing(),
        dispatcher=RecordingDispatcher(),
        reconciler=reconciler,
        max_tokens=1_000_000,
        max_dollars=100.0,
        max_wall_clock_seconds=3600.0,
    )
    before = tracker.snapshot().dollars
    await tracker.reconcile(
        session_id="01S",
        session_start=datetime(2026, 4, 21, 10, 0, tzinfo=UTC),
        session_end=datetime(2026, 4, 21, 10, 1, tzinfo=UTC),
    )
    assert tracker.snapshot().dollars == before


async def test_reconcile_error_leaves_estimate_intact(tmp_huragok_root: Path) -> None:
    reconciler = FakeReconciler(payload=CostReconciliationError("boom"))
    tracker = BudgetTracker(
        root=tmp_huragok_root,
        pricing=load_pricing(),
        dispatcher=RecordingDispatcher(),
        reconciler=reconciler,
        max_tokens=1_000_000,
        max_dollars=100.0,
        max_wall_clock_seconds=3600.0,
    )
    before = tracker.snapshot().dollars
    await tracker.reconcile(
        session_id="01S",
        session_start=datetime(2026, 4, 21, 10, 0, tzinfo=UTC),
        session_end=datetime(2026, 4, 21, 10, 1, tzinfo=UTC),
    )
    assert tracker.snapshot().dollars == before


async def test_reconcile_skipped_without_reconciler(tmp_huragok_root: Path) -> None:
    tracker = BudgetTracker(
        root=tmp_huragok_root,
        pricing=load_pricing(),
        dispatcher=RecordingDispatcher(),
        max_tokens=10_000,
        max_dollars=100.0,
        max_wall_clock_seconds=3600.0,
    )
    # Should not raise; should be a no-op.
    await tracker.reconcile(
        session_id="01S",
        session_start=datetime(2026, 4, 21, 10, 0, tzinfo=UTC),
        session_end=datetime(2026, 4, 21, 10, 1, tzinfo=UTC),
    )


def test_extract_total_usd_sums_entries() -> None:
    payload = {
        "data": [
            {
                "results": [
                    {"amount": {"value": 1.25, "currency": "USD"}},
                    {"amount": {"value": 0.50, "currency": "USD"}},
                ]
            },
            {
                "results": [
                    {"amount": {"value": 100.0, "currency": "EUR"}},  # ignored
                    {"amount": {"value": 0.25, "currency": "USD"}},
                ]
            },
        ]
    }
    assert _extract_total_usd(payload) == pytest.approx(2.00)


def test_extract_total_usd_empty_data_returns_none() -> None:
    assert _extract_total_usd({"data": []}) is None
    assert _extract_total_usd({"data": None}) is None


def test_extract_total_usd_bad_shape_raises() -> None:
    with pytest.raises(CostReconciliationError):
        _extract_total_usd(["not", "a", "dict"])
    with pytest.raises(CostReconciliationError):
        _extract_total_usd({"data": "not-a-list"})
