"""Spawn and monitor managed child processes."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from collections import deque
from typing import Callable

import psutil


class ManagedProcess:
    """A child process with stdout monitoring and lifecycle control."""

    def __init__(
        self,
        name: str,
        cmd: str,
        port: int,
        on_line: Callable[[str], None] | None = None,
    ) -> None:
        self.name = name
        self._cmd = cmd
        self.port = port
        self._on_line = on_line
        self._process: subprocess.Popen | None = None
        self._monitor_thread: threading.Thread | None = None
        self._output: deque[str] = deque(maxlen=200)
        self._stop_event = threading.Event()

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process else None

    @property
    def exit_code(self) -> int | None:
        if self._process is None:
            return None
        return self._process.poll()

    def is_alive(self) -> bool:
        if self._process is None:
            return False
        return self._process.poll() is None

    def start(self) -> None:
        """Start the process and begin monitoring stdout."""
        self._stop_event.clear()
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        self._process = subprocess.Popen(
            self._cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        self._monitor_thread = threading.Thread(
            target=self._monitor_stdout,
            daemon=True,
        )
        self._monitor_thread.start()

    def stop(self, timeout: float = 5) -> None:
        """Gracefully stop the process."""
        self._stop_event.set()
        if self._process is None:
            return

        try:
            parent = psutil.Process(self._process.pid)
            children = parent.children(recursive=True)
            parent.terminate()
            for child in children:
                try:
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass

            _, alive = psutil.wait_procs([parent] + children, timeout=timeout)
            for p in alive:
                try:
                    p.kill()
                except psutil.NoSuchProcess:
                    pass
        except psutil.NoSuchProcess:
            pass

        self._process = None

    def restart(self) -> None:
        """Stop and re-start with the same command."""
        self.stop()
        time.sleep(0.1)
        self.start()

    def get_recent_output(self, n: int = 50) -> list[str]:
        """Return the last n lines of output."""
        return list(self._output)[-n:]

    def _monitor_stdout(self) -> None:
        """Read stdout line by line until process exits or stop is requested."""
        proc = self._process
        if proc is None or proc.stdout is None:
            return

        for line in proc.stdout:
            if self._stop_event.is_set():
                break
            stripped = line.rstrip("\n\r")
            self._output.append(stripped)
            if self._on_line:
                self._on_line(stripped)

        proc.stdout.close()
