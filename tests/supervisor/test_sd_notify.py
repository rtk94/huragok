"""Tests for ``orchestrator.supervisor.sd_notify``."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from orchestrator.supervisor.sd_notify import sd_notify


def test_sd_notify_noop_without_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert sd_notify("READY=1") is False


def test_sd_notify_writes_when_socket_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    socket_path = tmp_path / "notify.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    listener.bind(str(socket_path))
    listener.settimeout(1.0)
    try:
        monkeypatch.setenv("NOTIFY_SOCKET", str(socket_path))
        assert sd_notify("READY=1") is True
        message, _ = listener.recvfrom(1024)
        assert message == b"READY=1"
    finally:
        listener.close()


def test_sd_notify_swallows_socket_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # NOTIFY_SOCKET points at a path with no listener — sendto will fail
    # with ECONNREFUSED. We still expect a False return, not a crash.
    monkeypatch.setenv("NOTIFY_SOCKET", str(tmp_path / "no-such-socket"))
    assert sd_notify("READY=1") is False
