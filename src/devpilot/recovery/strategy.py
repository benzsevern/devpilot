"""Tiered recovery logic for service failures."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RecoveryTier(Enum):
    SILENT = 1   # Auto-recover, don't report
    REPORT = 2   # Auto-recover AND report
    ESCALATE = 3 # Don't act, report with suggestions


@dataclass
class RecoveryAction:
    tier: RecoveryTier
    action: str  # "restart", "reassign_port", "report", "wait"
    service: str
    delay: float = 0
    suggestion: str | None = None
    detail: str | None = None


class RecoveryStrategy:
    """Decide what to do when things go wrong."""

    def __init__(self, max_retries: int = 3, backoff_seconds: list[int] | None = None) -> None:
        self._max_retries = max_retries
        self._backoff = backoff_seconds or [1, 3, 5]

    def on_crash(self, service: str, attempt: int) -> RecoveryAction:
        """Process crashed. Decide whether to restart or escalate."""
        if attempt > self._max_retries:
            return RecoveryAction(
                tier=RecoveryTier.ESCALATE,
                action="report",
                service=service,
                detail=f"Crashed {attempt} times, exceeded max retries ({self._max_retries})",
                suggestion=f"Check logs with 'devpilot log {service}' for recurring errors",
            )

        delay = self._backoff[min(attempt - 1, len(self._backoff) - 1)]

        if attempt >= self._max_retries:
            return RecoveryAction(
                tier=RecoveryTier.REPORT,
                action="restart",
                service=service,
                delay=delay,
                detail=f"Crash attempt {attempt}/{self._max_retries}, restarting with warning",
            )

        return RecoveryAction(
            tier=RecoveryTier.SILENT,
            action="restart",
            service=service,
            delay=delay,
        )

    def on_port_conflict(
        self, service: str, supports_port_flag: bool
    ) -> RecoveryAction:
        """Port already in use on startup."""
        if supports_port_flag:
            return RecoveryAction(
                tier=RecoveryTier.REPORT,
                action="reassign_port",
                service=service,
                detail="Port in use, reassigning to next available",
            )
        return RecoveryAction(
            tier=RecoveryTier.ESCALATE,
            action="report",
            service=service,
            suggestion="Service does not support --port flag. Stop the process using the port or change the service configuration.",
        )

    def on_reload_failed(self, service: str, error: str) -> RecoveryAction:
        """Reload failed due to code error. Never restart — code is broken."""
        return RecoveryAction(
            tier=RecoveryTier.ESCALATE,
            action="report",
            service=service,
            detail=error,
            suggestion="Fix the code error, then run 'devpilot changed <file>' again",
        )

    def on_attached_crash(self, service: str, cmd: str | None = None) -> RecoveryAction:
        """Attached-mode service went down."""
        suggestion = "Restart the service manually"
        if cmd:
            suggestion = f"Use 'devpilot run {service} \"{cmd}\"' for managed mode with auto-restart"
        return RecoveryAction(
            tier=RecoveryTier.ESCALATE,
            action="report",
            service=service,
            suggestion=suggestion,
        )

    def on_unknown_port_holder(
        self, service: str, port: int, holder_pid: int, holder_name: str,
    ) -> RecoveryAction:
        """Unknown process is holding the port."""
        return RecoveryAction(
            tier=RecoveryTier.ESCALATE,
            action="report",
            service=service,
            detail=f"Port {port} held by {holder_name} (pid {holder_pid})",
            suggestion=f"Kill {holder_name} (pid {holder_pid}) or use --port to pick a different port",
        )
