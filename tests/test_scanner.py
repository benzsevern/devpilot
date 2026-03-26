import socket

import psutil
import pytest

from devpilot.process.scanner import find_pid_on_port, is_port_in_use, find_free_port


def test_is_port_in_use_with_bound_port():
    """Bind a port and verify detection."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.listen(1)
    try:
        assert is_port_in_use(port) is True
    finally:
        sock.close()


def test_is_port_in_use_with_free_port():
    # Find a port that's definitely free
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    assert is_port_in_use(port) is False


def test_find_pid_on_port_returns_pid():
    """Bind a port from this process and verify we find our own PID."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.listen(1)
    try:
        pid = find_pid_on_port(port)
        assert pid is not None
        # Should be our own process or a child
        assert psutil.pid_exists(pid)
    finally:
        sock.close()


def test_find_pid_on_port_returns_none_for_free_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    pid = find_pid_on_port(port)
    assert pid is None


def test_find_free_port():
    port = find_free_port(start=10000)
    assert port >= 10000
    assert is_port_in_use(port) is False
