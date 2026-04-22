"""Tests for the Claude Code version-check hook in the supervisor."""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.config import HuragokSettings
from orchestrator.supervisor.loop import _check_claude_version

FAKE_CLAUDE = Path(__file__).resolve().parent.parent / "fixtures" / "fake-claude.sh"


def test_version_check_accepts_new_enough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HURAGOK_CLAUDE_BINARY", str(FAKE_CLAUDE))
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "version")
    settings = HuragokSettings()
    ok, msg = _check_claude_version(settings)
    assert ok, msg
    assert "2.1.91" in msg


def test_version_check_rejects_too_old(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HURAGOK_CLAUDE_BINARY", str(FAKE_CLAUDE))
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "old-version")
    settings = HuragokSettings()
    ok, msg = _check_claude_version(settings)
    assert not ok
    assert "below minimum" in msg.lower()


def test_version_check_reports_missing_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HURAGOK_CLAUDE_BINARY", "/nonexistent/claude-binary-zzz")
    settings = HuragokSettings()
    ok, msg = _check_claude_version(settings)
    assert not ok
    assert "not found" in msg.lower()
