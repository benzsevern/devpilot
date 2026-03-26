"""JSON state file with file-locking for cross-process coordination."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil
from filelock import FileLock


class StateStore:
    """Read/write .devpilot/state.json with file locking."""

    def __init__(self, state_file: Path) -> None:
        self._path = Path(state_file)
        self._lock = FileLock(str(self._path) + ".lock", timeout=5)

    def read(self) -> dict[str, Any]:
        """Read current state. Returns empty state if file doesn't exist."""
        with self._lock:
            return self._read_unlocked()

    def register_service(
        self,
        *,
        id: str,
        type: str,
        framework: str,
        cmd: str,
        pid: int,
        port: int,
        mode: str,
        health_endpoint: str | None,
        file_patterns: list[str],
        reload_patterns: list[str],
    ) -> None:
        """Add or overwrite a service entry."""
        now = datetime.now(timezone.utc).isoformat()
        service = {
            "id": id,
            "type": type,
            "framework": framework,
            "cmd": cmd,
            "pid": pid,
            "port": port,
            "mode": mode,
            "health_endpoint": health_endpoint,
            "file_patterns": file_patterns,
            "reload_patterns": reload_patterns,
            "status": "registered",
            "last_reload": None,
            "started_at": now,
        }
        with self._lock:
            state = self._read_unlocked()
            state["services"][id] = service
            self._write_unlocked(state)

    def update_service(self, service_id: str, **fields: Any) -> None:
        """Update fields on an existing service."""
        with self._lock:
            state = self._read_unlocked()
            if service_id not in state["services"]:
                raise KeyError(f"Service '{service_id}' not found")
            state["services"][service_id].update(fields)
            self._write_unlocked(state)

    def remove_service(self, service_id: str) -> None:
        """Remove a service from state."""
        with self._lock:
            state = self._read_unlocked()
            state["services"].pop(service_id, None)
            self._write_unlocked(state)

    def append_log(self, event: str, service: str, detail: str) -> None:
        """Append an event to the log. Caps at 500 entries."""
        entry = {
            "event": event,
            "service": service,
            "detail": detail,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            state = self._read_unlocked()
            state["log"].append(entry)
            if len(state["log"]) > 500:
                state["log"] = state["log"][-500:]
            self._write_unlocked(state)

    def append_reload_event(
        self, service_id: str, status: str, reload_time_ms: float = 0,
        error: str | None = None, suggestion: str | None = None,
    ) -> None:
        """Write a reload event to a service's state (for cross-process communication)."""
        event: dict[str, Any] = {
            "status": status,
            "reload_time_ms": reload_time_ms,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if error:
            event["error"] = error
        if suggestion:
            event["suggestion"] = suggestion
        with self._lock:
            state = self._read_unlocked()
            if service_id in state["services"]:
                state["services"][service_id]["last_reload_event"] = event
                self._write_unlocked(state)

    def consume_reload_event(self, service_id: str) -> dict[str, Any] | None:
        """Read and clear a reload event. Returns None if no event pending."""
        with self._lock:
            state = self._read_unlocked()
            svc = state["services"].get(service_id)
            if not svc:
                return None
            event = svc.pop("last_reload_event", None)
            if event:
                self._write_unlocked(state)
            return event

    def cleanup(self) -> list[str]:
        """Remove services with dead PIDs. Returns list of removed service IDs."""
        removed = []
        with self._lock:
            state = self._read_unlocked()
            to_remove = []
            for sid, svc in state["services"].items():
                if not psutil.pid_exists(svc["pid"]):
                    to_remove.append(sid)
            for sid in to_remove:
                del state["services"][sid]
                removed.append(sid)
            self._write_unlocked(state)
        return removed

    def _read_unlocked(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"schema_version": 1, "services": {}, "log": []}
        text = self._path.read_text(encoding="utf-8")
        if not text.strip():
            return {"schema_version": 1, "services": {}, "log": []}
        return json.loads(text)

    def _write_unlocked(self, state: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(state, indent=2, default=str),
            encoding="utf-8",
        )
