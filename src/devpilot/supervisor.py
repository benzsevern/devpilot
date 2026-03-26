"""Core orchestrator — ties process management, health, and state together."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from devpilot.frameworks.registry import FrameworkRegistry
from devpilot.health.checker import check_health
from devpilot.process.attacher import AttachedProcess
from devpilot.process.manager import ManagedProcess
from devpilot.recovery.strategy import RecoveryStrategy
from devpilot.state.store import StateStore
from devpilot.watch.file_watcher import match_file_to_services
from devpilot.watch.reload import ReloadDetector, ReloadResult


class Supervisor:
    """Manages all services — both managed and attached."""

    def __init__(
        self,
        store: StateStore,
        project_dir: Path,
        max_retries: int = 3,
        backoff_seconds: list[int] | None = None,
    ) -> None:
        self.store = store
        self.project_dir = project_dir
        self._managed: dict[str, ManagedProcess] = {}
        self._attached: dict[str, AttachedProcess] = {}
        self._reload_detectors: dict[str, ReloadDetector] = {}
        self._registry = FrameworkRegistry()
        self._recovery = RecoveryStrategy(max_retries, backoff_seconds)

    def run_service(
        self,
        name: str,
        cmd: str,
        port: int,
        type: str = "backend",
        health_endpoint: str | None = None,
        file_patterns: list[str] | None = None,
        reload_patterns: list[str] | None = None,
    ) -> None:
        """Start a managed service."""
        profile = self._registry.detect(cmd)

        health_ep = health_endpoint or (profile.health_check if profile else None)
        f_patterns = file_patterns or (["**/*.py"] if type == "backend" else [])
        r_patterns = reload_patterns or (profile.reload_patterns if profile else [])
        framework = profile.name if profile else "unknown"

        proc = ManagedProcess(
            name=name,
            cmd=cmd,
            port=port,
            on_line=lambda line, n=name, rp=r_patterns: self._on_stdout_line(n, line, rp),
        )
        proc.start()
        self._managed[name] = proc

        self.store.register_service(
            id=name,
            type=type,
            framework=framework,
            cmd=cmd,
            pid=proc.pid or 0,
            port=port,
            mode="managed",
            health_endpoint=health_ep,
            file_patterns=f_patterns,
            reload_patterns=r_patterns,
        )

    def attach_service(
        self,
        name: str,
        port: int,
        type: str = "backend",
        cmd: str | None = None,
        health_endpoint: str | None = None,
        file_patterns: list[str] | None = None,
        log_file: str | None = None,
    ) -> bool:
        """Attach to an existing process on a port. Returns False if nothing found."""
        attached = AttachedProcess.attach(name=name, port=port)
        if attached is None:
            return False

        self._attached[name] = attached
        self.store.register_service(
            id=name,
            type=type,
            framework="unknown",
            cmd=cmd or "",
            pid=attached.pid,
            port=port,
            mode="attached",
            health_endpoint=health_endpoint,
            file_patterns=file_patterns or [],
            reload_patterns=[],
        )
        return True

    def stop_service(self, name: str) -> None:
        """Stop a managed service or detach from an attached one."""
        if name in self._managed:
            self._managed[name].stop()
            del self._managed[name]
        if name in self._attached:
            del self._attached[name]
        self.store.remove_service(name)

    def stop_all(self) -> None:
        """Stop all services."""
        for name in list(self._managed.keys()):
            self.stop_service(name)
        for name in list(self._attached.keys()):
            self.stop_service(name)

    def is_running(self, name: str) -> bool:
        if name in self._managed:
            return self._managed[name].is_alive()
        if name in self._attached:
            return self._attached[name].is_alive()
        return False

    def get_status(self, name: str | None = None) -> dict[str, Any]:
        """Get status for one or all services, with fresh health checks."""
        state = self.store.read()
        services = state.get("services", {})

        if name:
            if name not in services:
                return {}
            return {name: self._enrich_status(name, services[name])}

        return {
            sid: self._enrich_status(sid, svc)
            for sid, svc in services.items()
        }

    def handle_changed(
        self,
        filepath: str,
        verify_endpoint: str | None = None,
        timeout: float = 10,
    ) -> dict[str, Any]:
        """Process a file change and return results."""
        state = self.store.read()
        services = state.get("services", {})
        matches = match_file_to_services(filepath, services)

        if not matches:
            return {
                "file": filepath,
                "results": [],
                "message": "No registered service watches this file pattern",
            }

        results = []
        for svc_id in matches:
            svc = services[svc_id]
            result = self._check_reload(svc_id, svc, timeout)
            entry: dict[str, Any] = {
                "service": svc_id,
                "reload": result.status,
            }
            if result.reload_time_ms > 0:
                entry["reload_time_ms"] = round(result.reload_time_ms, 1)
            if result.error:
                entry["error"] = result.error
            if result.suggestion:
                entry["suggestion"] = result.suggestion

            # Health check
            port = svc.get("port", 0)
            endpoint = svc.get("health_endpoint")
            if port:
                health = check_health(port=port, endpoint=endpoint if endpoint != "tcp" else None)
                entry["health"] = "healthy" if health.healthy else "unreachable"

            # Optional endpoint verification
            if verify_endpoint:
                from devpilot.health.verifier import verify_endpoint as do_verify
                parts = verify_endpoint.split(" ", 1)
                method = parts[0] if len(parts) > 1 else "GET"
                path = parts[1] if len(parts) > 1 else parts[0]
                vr = do_verify(method, path, port=port)
                entry["verification"] = vr.to_dict()

            results.append(entry)

        return {"file": filepath, "results": results}

    def _enrich_status(self, svc_id: str, svc: dict) -> dict:
        """Add live health check to stored service data."""
        enriched = dict(svc)
        port = svc.get("port", 0)
        endpoint = svc.get("health_endpoint")
        if port:
            health = check_health(port=port, endpoint=endpoint if endpoint != "tcp" else None)
            enriched["status"] = "healthy" if health.healthy else "unreachable"
            enriched["response_time_ms"] = round(health.response_time_ms, 1)
        return enriched

    def _check_reload(self, svc_id: str, svc: dict, timeout: float) -> ReloadResult:
        """Check for reload on a service after a file change.

        For in-process supervisors (same process as `run`), uses the in-memory
        reload detector. For cross-process callers (separate `changed` CLI call),
        polls the state file for reload events written by the monitoring thread.
        """
        if svc.get("mode") == "attached":
            return ReloadResult(status="health_only")

        patterns = svc.get("reload_patterns", [])
        if not patterns:
            return ReloadResult(status="no_reload_expected")

        # If we have an in-memory detector (same process), use it
        if svc_id in self._reload_detectors:
            return self._reload_detectors[svc_id].get_result(timeout=timeout)

        # Cross-process: poll state file for reload events
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            event = self.store.consume_reload_event(svc_id)
            if event:
                return ReloadResult(
                    status=event["status"],
                    reload_time_ms=event.get("reload_time_ms", 0),
                    error=event.get("error"),
                    suggestion=event.get("suggestion"),
                )
            time.sleep(0.5)

        return ReloadResult(status="timeout")

    def _on_stdout_line(self, service_name: str, line: str, reload_patterns: list[str]) -> None:
        """Called for each stdout line from a managed process.

        Feeds the in-memory reload detector AND writes events to the state
        file so cross-process `changed` commands can read them.
        """
        if service_name in self._reload_detectors:
            detector = self._reload_detectors[service_name]
            detector.feed_line(line)

            # Check if detector has completed — if so, write event to state file
            if detector._done.is_set():
                result = detector.get_result(timeout=0)
                self.store.append_reload_event(
                    service_name,
                    status=result.status,
                    reload_time_ms=result.reload_time_ms,
                    error=result.error,
                    suggestion=result.suggestion,
                )
                # Reset detector for next reload cycle
                self._reload_detectors[service_name] = ReloadDetector(reload_patterns)
