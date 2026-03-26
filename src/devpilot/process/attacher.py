"""Discover and attach to existing processes by port."""

from __future__ import annotations

import psutil

from devpilot.process.scanner import find_pid_on_port


class AttachedProcess:
    """A process we don't own — monitor only, limited control."""

    def __init__(self, name: str, port: int, pid: int, process_name: str) -> None:
        self.name = name
        self.port = port
        self.pid = pid
        self.process_name = process_name

    @classmethod
    def attach(cls, name: str, port: int) -> AttachedProcess | None:
        """Try to find and attach to a process on the given port."""
        pid = find_pid_on_port(port)
        if pid is None:
            return None

        try:
            proc = psutil.Process(pid)
            process_name = proc.name()
        except psutil.NoSuchProcess:
            return None

        return cls(name=name, port=port, pid=pid, process_name=process_name)

    def is_alive(self) -> bool:
        """Check if the process is still running."""
        return psutil.pid_exists(self.pid)

    def get_process_info(self) -> dict:
        """Get current process info."""
        try:
            proc = psutil.Process(self.pid)
            return {
                "pid": self.pid,
                "name": proc.name(),
                "status": proc.status(),
                "create_time": proc.create_time(),
            }
        except psutil.NoSuchProcess:
            return {"pid": self.pid, "name": self.process_name, "status": "dead"}
