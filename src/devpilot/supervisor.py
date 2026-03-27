"""Core orchestrator — ties process management, health, and state together."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from devpilot.frameworks.registry import FrameworkRegistry
from devpilot.health.checker import check_health
from devpilot.process.attacher import AttachedProcess
from devpilot.process.manager import ManagedProcess
from devpilot.recovery.strategy import RecoveryStrategy, RecoveryTier
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
        self._crash_counts: dict[str, int] = {}
        self._registry = FrameworkRegistry()
        self._recovery = RecoveryStrategy(max_retries, backoff_seconds)
        self._monitor_stop = threading.Event()
        self._monitor_thread: threading.Thread | None = None

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
            cwd=str(self.project_dir),
        )
        proc.start()
        self._managed[name] = proc

        # Create reload detector so _on_stdout_line can feed it
        if r_patterns:
            self._reload_detectors[name] = ReloadDetector(r_patterns)

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

        # Start crash monitoring if not already running
        self._start_monitor()

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
        self._reload_detectors.pop(name, None)
        self._crash_counts.pop(name, None)
        self.store.remove_service(name)

    def stop_all(self) -> None:
        """Stop all services."""
        self._monitor_stop.set()
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

        First checks the state file for events already written by _on_stdout_line
        (handles both in-process and cross-process scenarios). Falls back to
        polling the in-memory detector or state file until timeout.
        """
        if svc.get("mode") == "attached":
            return ReloadResult(status="health_only")

        patterns = svc.get("reload_patterns", [])
        if not patterns:
            return ReloadResult(status="no_reload_expected")

        # Poll for reload events — check state file first (written by _on_stdout_line
        # when a reload completes), then fall back to in-memory detector
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            # Check state file for an already-written reload event
            event = self.store.consume_reload_event(svc_id)
            if event:
                return ReloadResult(
                    status=event["status"],
                    reload_time_ms=event.get("reload_time_ms", 0),
                    error=event.get("error"),
                    suggestion=event.get("suggestion"),
                )

            # Check in-memory detector if available (same process as `run`)
            detector = self._reload_detectors.get(svc_id)
            if detector and detector.is_done:
                return detector.get_result(timeout=0)

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
            if detector.is_done:
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

    def _start_monitor(self) -> None:
        """Start the crash monitoring thread if not already running."""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._monitor_stop.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def _monitor_loop(self) -> None:
        """Periodically check managed processes for crashes and auto-recover."""
        while not self._monitor_stop.is_set():
            for name in list(self._managed.keys()):
                proc = self._managed.get(name)
                if proc is None:
                    continue
                if not proc.is_alive():
                    self._handle_crash(name, proc)
            self._monitor_stop.wait(timeout=2)

    def _handle_crash(self, name: str, proc: ManagedProcess) -> None:
        """Handle a crashed managed process using the recovery strategy."""
        self._crash_counts[name] = self._crash_counts.get(name, 0) + 1
        attempt = self._crash_counts[name]
        action = self._recovery.on_crash(name, attempt)

        if action.tier == RecoveryTier.SILENT or action.tier == RecoveryTier.REPORT:
            # Auto-restart
            self.store.append_log("auto_restart", name, f"attempt {attempt}, delay {action.delay}s")
            if action.delay > 0:
                time.sleep(action.delay)
            try:
                proc.restart()
                self.store.update_service(name, pid=proc.pid or 0, status="restarted")
                if action.tier == RecoveryTier.REPORT:
                    self.store.update_service(name, status="restarted_with_warning")
            except Exception as e:
                self.store.append_log("restart_failed", name, str(e))
        else:
            # Escalate — report but don't act
            self.store.update_service(name, status="crashed")
            self.store.append_log(
                "escalation", name,
                action.detail or f"Crashed {attempt} times, manual intervention needed",
            )
