import sys
import time

import pytest

from devpilot.process.manager import ManagedProcess


def test_start_and_stop():
    """Start a simple process, verify it's running, then stop it."""
    proc = ManagedProcess(
        name="test",
        cmd=f"{sys.executable} -c \"import time; time.sleep(30)\"",
        port=0,  # No port check needed
    )
    proc.start()
    assert proc.is_alive()
    assert proc.pid is not None

    proc.stop()
    assert not proc.is_alive()


def test_stdout_capture():
    """Verify stdout lines are captured."""
    proc = ManagedProcess(
        name="test",
        cmd=f'{sys.executable} -c "print(\'hello world\'); import time; time.sleep(5)"',
        port=0,
    )
    proc.start()
    time.sleep(0.5)  # Let output arrive

    lines = proc.get_recent_output(10)
    proc.stop()

    assert any("hello world" in line for line in lines)


def test_on_line_callback():
    """Verify the on_line callback fires for each stdout line."""
    captured = []
    proc = ManagedProcess(
        name="test",
        cmd=f'{sys.executable} -c "print(\'line1\'); print(\'line2\'); import time; time.sleep(5)"',
        port=0,
        on_line=lambda line: captured.append(line),
    )
    proc.start()
    time.sleep(0.5)
    proc.stop()

    assert len(captured) >= 2
    assert any("line1" in c for c in captured)
    assert any("line2" in c for c in captured)


def test_exit_code_captured():
    """Process that exits with code 1."""
    proc = ManagedProcess(
        name="test",
        cmd=f"{sys.executable} -c \"raise SystemExit(1)\"",
        port=0,
    )
    proc.start()
    time.sleep(0.5)

    assert not proc.is_alive()
    assert proc.exit_code == 1


def test_restart():
    proc = ManagedProcess(
        name="test",
        cmd=f"{sys.executable} -c \"import time; time.sleep(30)\"",
        port=0,
    )
    proc.start()
    old_pid = proc.pid
    proc.restart()
    assert proc.is_alive()
    assert proc.pid != old_pid
    proc.stop()
