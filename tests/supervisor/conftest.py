"""Fixtures shared across supervisor tests.

The ``supervisor_tmp_root`` fixture produces a minimally-populated
repo: one batch, one task in ``pending`` state, no agents on disk.
Tests launch the supervisor loop against it using the fake-claude
script so no real ``claude`` binary is required.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "state" / "fixtures"
FAKE_CLAUDE = Path(__file__).resolve().parent.parent / "fixtures" / "fake-claude.sh"


@pytest.fixture
def supervisor_tmp_root(tmp_path: Path) -> Path:
    """Tmp repo containing a valid state.yaml, batch.yaml, and one pending task."""
    huragok = tmp_path / ".huragok"
    huragok.mkdir()
    for sub in ("audit", "logs", "requests", "retrospectives", "work"):
        (huragok / sub).mkdir()

    shutil.copy(FIXTURES_DIR / "state_valid.yaml", huragok / "state.yaml")

    # Write a fresh batch with a single pending task. The existing valid
    # fixture has two tasks; here we want a trivially-small one so the
    # integration test runs fast and deterministically.
    batch = {
        "version": 1,
        "batch_id": "batch-001",
        "created": "2026-04-21T09:00:00Z",
        "description": "Supervisor integration test batch",
        "budgets": {
            "wall_clock_hours": 12.0,
            "max_tokens": 5_000_000,
            "max_dollars": 50.0,
            "max_iterations": 2,
            "session_timeout_minutes": 2,
        },
        "notifications": {
            "telegram_chat_id": None,
            "warn_threshold_pct": 80,
        },
        "tasks": [
            {
                "id": "task-b1-test",
                "title": "B1 integration task",
                "kind": "backend",
                "priority": 1,
                "acceptance_criteria": ["it runs"],
                "depends_on": [],
                "foundational": False,
            }
        ],
    }
    (huragok / "batch.yaml").write_text(yaml.safe_dump(batch, sort_keys=False))

    # Ensure state.yaml matches the batch-001 id and has no current_task.
    state = yaml.safe_load((huragok / "state.yaml").read_text())
    state["batch_id"] = "batch-001"
    state["phase"] = "running"
    state["current_task"] = None
    state["current_agent"] = None
    state["session_count"] = 0
    state["session_id"] = None
    state["budget_consumed"] = {
        "wall_clock_seconds": 0.0,
        "tokens_input": 0,
        "tokens_output": 0,
        "tokens_cache_read": 0,
        "tokens_cache_write": 0,
        "dollars": 0.0,
        "iterations": 0,
    }
    (huragok / "state.yaml").write_text(yaml.safe_dump(state, sort_keys=False))

    return tmp_path
