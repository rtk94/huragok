"""Integration tests for the supervisor loop.

Each test uses the fake-claude fixture under ``tests/fixtures/`` so no
real Claude Code binary is invoked. The minimal repo fixture gives us a
pending task; the loop should launch exactly one session and then stop
when we flip the shutdown event.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from orchestrator.budget.pricing import load_pricing
from orchestrator.config import HuragokSettings
from orchestrator.paths import audit_log
from orchestrator.state import read_state, read_status
from orchestrator.supervisor.loop import run_supervisor

FAKE_CLAUDE = Path(__file__).resolve().parent.parent / "fixtures" / "fake-claude.sh"


async def test_loop_launches_one_session_and_updates_state(
    supervisor_tmp_root: Path,
) -> None:
    """Smoke: one fake-clean session changes state.yaml and the audit log."""
    settings = HuragokSettings()

    loop_task = asyncio.create_task(
        run_supervisor(
            root=supervisor_tmp_root,
            settings=settings,
            pricing=load_pricing(),
            claude_binary=str(FAKE_CLAUDE),
            request_poll_seconds=0.1,
            session_env_overrides={"FAKE_CLAUDE_MODE": "clean"},
        )
    )

    # Wait until a session has been recorded, then tell the loop to stop.
    async def wait_for_session() -> None:
        for _ in range(200):  # up to 20s
            state = read_state(supervisor_tmp_root)
            if state.session_count >= 1:
                return
            await asyncio.sleep(0.1)
        raise AssertionError("session never observed")

    await asyncio.wait_for(wait_for_session(), timeout=30.0)

    # Write a stop request so the loop drains and exits cleanly.
    stop_path = supervisor_tmp_root / ".huragok" / "requests" / "stop"
    stop_path.write_text("")

    exit_code = await asyncio.wait_for(loop_task, timeout=10.0)
    assert exit_code == 0

    # state.yaml should have recorded at least one session. The loop may
    # launch several sessions before observing the stop marker because
    # fake-claude returns in milliseconds; we assert only the core
    # bookkeeping contract, not an exact count.
    final_state = read_state(supervisor_tmp_root)
    assert final_state.session_count >= 1
    assert final_state.budget_consumed.tokens_input > 0
    assert final_state.budget_consumed.dollars > 0
    assert final_state.session_id is not None

    # Audit log should have session-launched / session-ended entries.
    audit_path = audit_log(supervisor_tmp_root, "batch-001")
    assert audit_path.exists()
    events = [json.loads(line) for line in audit_path.read_text().splitlines() if line]
    kinds = [e["kind"] for e in events]
    assert "session-launched" in kinds
    assert "session-ended" in kinds
    ended = next(e for e in events if e["kind"] == "session-ended")
    assert ended["end_state"] == "clean"
    assert ended["role"] == "architect"

    # status.yaml should have been written for the task; since fake-claude
    # doesn't simulate agent state transitions, the state remains at the
    # initial ``pending``. That's the expected B1 behaviour for this test.
    status = read_status(supervisor_tmp_root, "task-b1-test")
    assert status.task_id == "task-b1-test"


async def test_loop_exits_on_stop_request_even_without_work(
    supervisor_tmp_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the batch is already done, the loop should exit on stop quickly."""
    # Mark the task as done before the loop starts — no work to do.
    from datetime import UTC, datetime

    from orchestrator.paths import task_dir
    from orchestrator.state import HistoryEntry, StatusFile, write_status

    task_dir(supervisor_tmp_root, "task-b1-test").mkdir(parents=True, exist_ok=True)
    done_status = StatusFile(
        version=1,
        task_id="task-b1-test",
        state="done",
        history=[],
    )
    done_status.history.append(
        HistoryEntry(
            at=datetime.now(UTC),
            from_="pending",
            to="done",
            by="test",
            session_id=None,
        )
    )
    write_status(supervisor_tmp_root, done_status)

    settings = HuragokSettings()
    loop_task = asyncio.create_task(
        run_supervisor(
            root=supervisor_tmp_root,
            settings=settings,
            pricing=load_pricing(),
            claude_binary=str(FAKE_CLAUDE),
            request_poll_seconds=0.05,
        )
    )
    await asyncio.sleep(0.1)  # let the loop observe no pending work
    (supervisor_tmp_root / ".huragok" / "requests" / "stop").write_text("")
    exit_code = await asyncio.wait_for(loop_task, timeout=5.0)
    assert exit_code == 0


async def test_loop_blocks_task_after_two_dirty_ends(
    supervisor_tmp_root: Path,
) -> None:
    """Two consecutive crash sessions transition the task to blocked."""
    settings = HuragokSettings()

    loop_task = asyncio.create_task(
        run_supervisor(
            root=supervisor_tmp_root,
            settings=settings,
            pricing=load_pricing(),
            claude_binary=str(FAKE_CLAUDE),
            request_poll_seconds=0.05,
            session_env_overrides={"FAKE_CLAUDE_MODE": "crash"},
        )
    )

    async def wait_for_blocked() -> None:
        for _ in range(300):  # up to 30s
            try:
                status = read_status(supervisor_tmp_root, "task-b1-test")
            except FileNotFoundError:
                await asyncio.sleep(0.1)
                continue
            if status.state == "blocked":
                return
            await asyncio.sleep(0.1)
        raise AssertionError("task never transitioned to blocked")

    try:
        await asyncio.wait_for(wait_for_blocked(), timeout=45.0)
    finally:
        (supervisor_tmp_root / ".huragok" / "requests" / "stop").write_text("")
        await asyncio.wait_for(loop_task, timeout=10.0)

    status = read_status(supervisor_tmp_root, "task-b1-test")
    assert status.state == "blocked"
    assert status.blockers, "blockers list should be populated"
