"""Detect reload events from process stdout lines."""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass


@dataclass
class ReloadResult:
    status: str  # "reloaded", "reload_failed", "timeout"
    reload_time_ms: float = 0.0
    error: str | None = None
    suggestion: str | None = None


# Common Python error patterns
_ERROR_PATTERNS = [
    re.compile(r"SyntaxError:"),
    re.compile(r"ImportError:"),
    re.compile(r"ModuleNotFoundError:"),
    re.compile(r"NameError:"),
    re.compile(r"TypeError:"),
    re.compile(r"AttributeError:"),
    re.compile(r"ValueError:"),
    re.compile(r"IndentationError:"),
]

_SUGGESTION_MAP = {
    "SyntaxError": "Fix the syntax error in the indicated file and line",
    "ImportError": "Check that the module is installed and the import path is correct",
    "ModuleNotFoundError": "Install the missing module with pip",
    "IndentationError": "Fix the indentation at the indicated line",
}


class ReloadDetector:
    """Watches stdout lines for reload patterns and errors."""

    def __init__(self, patterns: list[str]) -> None:
        self._patterns = patterns
        self._matched: list[str] = []
        self._error: str | None = None
        self._done = threading.Event()
        self._reload_start: float | None = None
        self._reload_end: float | None = None

    def feed_line(self, line: str) -> None:
        """Feed a line of stdout. Call from the monitoring thread."""
        stripped = line.strip()

        # Check for error patterns
        for ep in _ERROR_PATTERNS:
            if ep.search(stripped):
                if self._error is None:
                    self._error = stripped

        # Check for reload patterns (order matters — first match starts timer)
        for i, pattern in enumerate(self._patterns):
            if pattern in stripped and pattern not in self._matched:
                self._matched.append(pattern)
                if len(self._matched) == 1:
                    self._reload_start = time.monotonic()
                if len(self._matched) == len(self._patterns):
                    self._reload_end = time.monotonic()
                    self._done.set()
                break

    @property
    def is_done(self) -> bool:
        """Whether the detector has completed (reload or error)."""
        return self._done.is_set()

    def mark_error(self, error: str) -> None:
        """Explicitly mark a reload failure with an error message."""
        self._error = error
        self._done.set()

    def get_result(self, timeout: float = 10) -> ReloadResult:
        """Wait for reload completion or timeout. Returns result."""
        self._done.wait(timeout=timeout)

        if self._error:
            suggestion = None
            for prefix, sug in _SUGGESTION_MAP.items():
                if prefix in self._error:
                    suggestion = sug
                    break
            return ReloadResult(
                status="reload_failed",
                error=self._error,
                suggestion=suggestion,
            )

        if self._reload_end and self._reload_start:
            elapsed = (self._reload_end - self._reload_start) * 1000
            return ReloadResult(status="reloaded", reload_time_ms=elapsed)

        return ReloadResult(status="timeout")
