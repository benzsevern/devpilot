"""Cross-platform port scanning and PID lookup via psutil."""

from __future__ import annotations

import socket

import psutil


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a port is currently in use."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex((host, port))
            return result == 0
    except OSError:
        return False


def find_pid_on_port(port: int) -> int | None:
    """Find the PID of the process listening on a given port."""
    for conn in psutil.net_connections(kind="inet"):
        if conn.laddr and conn.laddr.port == port and conn.status == "LISTEN":
            return conn.pid
    return None


def find_free_port(start: int = 8000, end: int = 65535) -> int:
    """Find the next available port starting from `start`."""
    for port in range(start, end):
        if not is_port_in_use(port):
            return port
    raise RuntimeError(f"No free port found in range {start}-{end}")
