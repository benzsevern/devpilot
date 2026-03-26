import json
import time
from pathlib import Path

from devpilot.state.store import StateStore


def test_empty_state_has_schema_version(state_file):
    store = StateStore(state_file)
    state = store.read()
    assert state["schema_version"] == 1
    assert state["services"] == {}
    assert state["log"] == []


def test_register_service(state_file):
    store = StateStore(state_file)
    store.register_service(
        id="backend",
        type="backend",
        framework="fastapi",
        cmd="uvicorn app:main --reload",
        pid=12345,
        port=8000,
        mode="managed",
        health_endpoint="/health",
        file_patterns=["**/*.py"],
        reload_patterns=["Started reloading"],
    )
    state = store.read()
    assert "backend" in state["services"]
    svc = state["services"]["backend"]
    assert svc["pid"] == 12345
    assert svc["port"] == 8000
    assert svc["status"] == "registered"
    assert svc["mode"] == "managed"


def test_update_service_status(state_file):
    store = StateStore(state_file)
    store.register_service(
        id="backend", type="backend", framework="fastapi",
        cmd="uvicorn app:main", pid=100, port=8000, mode="managed",
        health_endpoint="/health", file_patterns=["**/*.py"],
        reload_patterns=[],
    )
    store.update_service("backend", status="healthy")
    svc = store.read()["services"]["backend"]
    assert svc["status"] == "healthy"


def test_remove_service(state_file):
    store = StateStore(state_file)
    store.register_service(
        id="backend", type="backend", framework="fastapi",
        cmd="uvicorn app:main", pid=100, port=8000, mode="managed",
        health_endpoint="/health", file_patterns=["**/*.py"],
        reload_patterns=[],
    )
    store.remove_service("backend")
    state = store.read()
    assert "backend" not in state["services"]


def test_append_log_entry(state_file):
    store = StateStore(state_file)
    store.append_log("auto_restart", "backend", "process_exited_code_1")
    state = store.read()
    assert len(state["log"]) == 1
    entry = state["log"][0]
    assert entry["event"] == "auto_restart"
    assert entry["service"] == "backend"
    assert entry["detail"] == "process_exited_code_1"
    assert "timestamp" in entry


def test_log_capped_at_500(state_file):
    store = StateStore(state_file)
    for i in range(510):
        store.append_log("health_change", "backend", f"event_{i}")
    state = store.read()
    assert len(state["log"]) == 500
    # Oldest should be evicted — first entry should be event_10
    assert state["log"][0]["detail"] == "event_10"


def test_concurrent_writes_dont_corrupt(state_file):
    """Two stores writing to the same file should not corrupt state."""
    store1 = StateStore(state_file)
    store2 = StateStore(state_file)
    store1.register_service(
        id="backend", type="backend", framework="fastapi",
        cmd="uvicorn app:main", pid=100, port=8000, mode="managed",
        health_endpoint="/health", file_patterns=["**/*.py"],
        reload_patterns=[],
    )
    store2.register_service(
        id="frontend", type="frontend", framework="vite",
        cmd="npm run dev", pid=200, port=3000, mode="managed",
        health_endpoint=None, file_patterns=["src/**/*.tsx"],
        reload_patterns=[],
    )
    state = store1.read()
    assert "backend" in state["services"]
    assert "frontend" in state["services"]


def test_append_reload_event(state_file):
    store = StateStore(state_file)
    store.register_service(
        id="backend", type="backend", framework="fastapi",
        cmd="uvicorn app:main", pid=100, port=8000, mode="managed",
        health_endpoint="/health", file_patterns=["**/*.py"],
        reload_patterns=[],
    )
    store.append_reload_event("backend", status="reloaded", reload_time_ms=150.0)
    state = store.read()
    svc = state["services"]["backend"]
    assert svc["last_reload_event"]["status"] == "reloaded"
    assert svc["last_reload_event"]["reload_time_ms"] == 150.0


def test_consume_reload_event(state_file):
    store = StateStore(state_file)
    store.register_service(
        id="backend", type="backend", framework="fastapi",
        cmd="uvicorn app:main", pid=100, port=8000, mode="managed",
        health_endpoint="/health", file_patterns=["**/*.py"],
        reload_patterns=[],
    )
    store.append_reload_event("backend", status="reloaded", reload_time_ms=150.0)
    event = store.consume_reload_event("backend")
    assert event["status"] == "reloaded"

    # Second consume should return None (already consumed)
    event2 = store.consume_reload_event("backend")
    assert event2 is None


def test_cleanup_removes_dead_pids(state_file):
    store = StateStore(state_file)
    # Register with a PID that definitely doesn't exist
    store.register_service(
        id="dead", type="backend", framework="fastapi",
        cmd="uvicorn app:main", pid=999999999, port=8000, mode="managed",
        health_endpoint="/health", file_patterns=["**/*.py"],
        reload_patterns=[],
    )
    removed = store.cleanup()
    assert "dead" in removed
    state = store.read()
    assert "dead" not in state["services"]
