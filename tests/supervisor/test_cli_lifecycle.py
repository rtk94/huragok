"""End-to-end lifecycle test for ``huragok run`` / ``huragok stop``.

Runs the daemon in a real subprocess via the venv-installed ``huragok``
console script, invokes ``huragok stop``, and asserts both processes
exit cleanly. The daemon is pointed at the fake claude script via
``HURAGOK_CLAUDE_BINARY`` so no real Claude Code invocation ever occurs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

FAKE_CLAUDE = Path(__file__).resolve().parent.parent / "fixtures" / "fake-claude.sh"


def _find_huragok_binary() -> str | None:
    """Locate the ``huragok`` console script next to the running interpreter."""
    binary = Path(sys.executable).parent / "huragok"
    if binary.is_file():
        return str(binary)
    from_path = shutil.which("huragok")
    return from_path


def _poll_until(
    predicate,  # type: ignore[no-untyped-def]
    *,
    timeout: float = 20.0,
    interval: float = 0.1,
) -> bool:
    """Poll ``predicate`` until it returns truthy or ``timeout`` elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


@pytest.fixture
def huragok_binary() -> str:
    binary = _find_huragok_binary()
    if binary is None:
        pytest.skip("huragok console script not available in the current env")
    return binary


def test_run_then_stop_cleanly(
    supervisor_tmp_root: Path,
    huragok_binary: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``huragok run`` in a subprocess; ``huragok stop`` terminates it."""
    env = os.environ.copy()
    env["HURAGOK_CLAUDE_BINARY"] = str(FAKE_CLAUDE)
    env["FAKE_CLAUDE_MODE"] = "clean"

    daemon = subprocess.Popen(
        [huragok_binary, "run"],
        cwd=str(supervisor_tmp_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        pid_file = supervisor_tmp_root / ".huragok" / "daemon.pid"
        if not _poll_until(pid_file.exists, timeout=20.0):
            daemon.terminate()
            out, err = daemon.communicate(timeout=5)
            pytest.fail(f"pid file never appeared:\nstdout:\n{out}\nstderr:\n{err}")

        stop = subprocess.run(
            [huragok_binary, "stop"],
            cwd=str(supervisor_tmp_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=30.0,
        )
        assert stop.returncode == 0, stop.stderr
    finally:
        try:
            exit_code = daemon.wait(timeout=20.0)
        except subprocess.TimeoutExpired:
            daemon.kill()
            exit_code = daemon.wait()
        assert exit_code == 0, f"daemon exit code was {exit_code}"

    # pid file should be cleaned up on clean shutdown.
    assert not (supervisor_tmp_root / ".huragok" / "daemon.pid").exists()


def test_halt_in_subprocess_writes_marker(
    supervisor_tmp_root: Path,
    huragok_binary: str,
) -> None:
    """``huragok halt`` writes the marker file even with no daemon running."""
    from orchestrator.paths import requests_dir

    env = os.environ.copy()
    result = subprocess.run(
        [huragok_binary, "halt"],
        cwd=str(supervisor_tmp_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    assert result.returncode == 0, result.stderr
    halt_marker = requests_dir(supervisor_tmp_root) / "halt"
    assert halt_marker.exists()


def test_run_then_halt_exits_cleanly_after_session(
    supervisor_tmp_root: Path,
    huragok_binary: str,
) -> None:
    """``huragok halt`` signals the daemon to drain; it exits 0."""
    env = os.environ.copy()
    env["HURAGOK_CLAUDE_BINARY"] = str(FAKE_CLAUDE)
    env["FAKE_CLAUDE_MODE"] = "clean"

    daemon = subprocess.Popen(
        [huragok_binary, "run"],
        cwd=str(supervisor_tmp_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        pid_file = supervisor_tmp_root / ".huragok" / "daemon.pid"
        if not _poll_until(pid_file.exists, timeout=20.0):
            daemon.terminate()
            daemon.communicate(timeout=5)
            pytest.fail("pid file never appeared")

        result = subprocess.run(
            [huragok_binary, "halt"],
            cwd=str(supervisor_tmp_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=10.0,
        )
        assert result.returncode == 0, result.stderr
    finally:
        try:
            exit_code = daemon.wait(timeout=60.0)
        except subprocess.TimeoutExpired:
            daemon.terminate()
            daemon.wait(timeout=10)
            pytest.fail("daemon did not exit after halt + SIGUSR1")
    assert exit_code == 0
