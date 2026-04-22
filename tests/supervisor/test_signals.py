"""Tests for ``orchestrator.supervisor.signals``."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from orchestrator.paths import requests_dir
from orchestrator.supervisor.signals import (
    ParsedRequest,  # noqa: F401 — imported to keep the public surface visible
    SignalState,
    process_request_files,
    sleep_or_shutdown,
)


@pytest.fixture
def supervisor_root(tmp_path: Path) -> Path:
    (tmp_path / ".huragok" / "requests").mkdir(parents=True)
    return tmp_path


def test_signal_state_defaults() -> None:
    state = SignalState()
    assert not state.shutting_down.is_set()
    assert not state.halt_after_session.is_set()


def test_process_request_files_handles_missing_dir(tmp_path: Path) -> None:
    state = SignalState()
    drained = process_request_files(tmp_path, state)
    assert drained == []


def test_process_stop_sets_shutting_down(supervisor_root: Path) -> None:
    state = SignalState()
    (requests_dir(supervisor_root) / "stop").write_text("")
    drained = process_request_files(supervisor_root, state)
    assert len(drained) == 1
    assert drained[0].kind == "stop"
    assert state.shutting_down.is_set()
    # File drained.
    assert not (requests_dir(supervisor_root) / "stop").exists()


def test_process_halt_sets_halt_after_session(supervisor_root: Path) -> None:
    state = SignalState()
    (requests_dir(supervisor_root) / "halt").write_text("")
    drained = process_request_files(supervisor_root, state)
    assert len(drained) == 1
    assert drained[0].kind == "halt"
    assert state.halt_after_session.is_set()


def test_process_reply_file_parses_payload(supervisor_root: Path) -> None:
    state = SignalState()
    reply = requests_dir(supervisor_root) / "reply-01ABC.yaml"
    reply.write_text("verb: continue\nnotification_id: 01ABC\n")
    drained = process_request_files(supervisor_root, state)
    assert len(drained) == 1
    assert drained[0].kind == "reply"
    assert drained[0].payload == {"verb": "continue", "notification_id": "01ABC"}
    assert not reply.exists()


def test_process_ignores_unknown_files(supervisor_root: Path) -> None:
    state = SignalState()
    garbage = requests_dir(supervisor_root) / "garbage.txt"
    garbage.write_text("x")
    drained = process_request_files(supervisor_root, state)
    assert drained == []
    assert garbage.exists()


async def test_sleep_or_shutdown_returns_false_on_full_sleep() -> None:
    state = SignalState()
    interrupted = await sleep_or_shutdown(state, 0.05)
    assert interrupted is False


async def test_sleep_or_shutdown_returns_true_when_interrupted() -> None:
    state = SignalState()
    task = asyncio.create_task(sleep_or_shutdown(state, 5.0))
    await asyncio.sleep(0.01)
    state.shutting_down.set()
    result = await asyncio.wait_for(task, timeout=1.0)
    assert result is True
