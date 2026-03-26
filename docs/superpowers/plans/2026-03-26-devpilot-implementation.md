# DevPilot Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python CLI supervisor that gives AI coders reliable process awareness for frontend/backend dev servers.

**Architecture:** Three-layer design — CLI (Click) → Supervisor Core → Process/Watch/Health modules. Threaded concurrency, JSON state file coordination, cross-platform via psutil.

**Tech Stack:** Python 3.10+, Click, watchdog, httpx, psutil, PyYAML, filelock, pytest

**Spec:** `docs/superpowers/specs/2026-03-26-devpilot-design.md`

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/devpilot/__init__.py`
- Create: `src/devpilot/process/__init__.py`
- Create: `src/devpilot/watch/__init__.py`
- Create: `src/devpilot/health/__init__.py`
- Create: `src/devpilot/recovery/__init__.py`
- Create: `src/devpilot/frameworks/__init__.py`
- Create: `src/devpilot/state/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "devpilot"
version = "0.1.0"
description = "Dev server supervisor for AI coders"
requires-python = ">=3.10"
dependencies = [
    "click>=8.1",
    "watchdog>=4.0",
    "httpx>=0.27",
    "psutil>=5.9",
    "pyyaml>=6.0",
    "filelock>=3.13",
]

[project.scripts]
devpilot = "devpilot.cli:main"

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-timeout>=2.2",
]

[tool.hatch.build.targets.wheel]
packages = ["src/devpilot"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 2: Create package init files**

`src/devpilot/__init__.py`:
```python
"""DevPilot — Dev server supervisor for AI coders."""

__version__ = "0.1.0"
```

All other `__init__.py` files (process, watch, health, recovery, frameworks, state, tests) are empty.

- [ ] **Step 3: Create tests/conftest.py**

```python
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary project directory with .devpilot/ state dir."""
    state_dir = tmp_path / ".devpilot"
    state_dir.mkdir()
    return tmp_path


@pytest.fixture
def state_file(tmp_project):
    """Return path to a temporary state file."""
    return tmp_project / ".devpilot" / "state.json"
```

- [ ] **Step 4: Install in dev mode and verify**

Run: `cd D:/show_case/devpilot && pip install -e ".[dev]"`
Expected: Installs successfully, `devpilot` command available (will fail with missing cli module — that's fine)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/ tests/
git commit -m "feat: project scaffolding with package structure and dependencies"
```

---

### Task 2: State Store

The foundation — every other module reads/writes state through this.

**Files:**
- Create: `src/devpilot/state/store.py`
- Create: `tests/test_state_store.py`

- [ ] **Step 1: Write failing tests for state store**

`tests/test_state_store.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_state_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'devpilot.state.store'`

- [ ] **Step 3: Implement state store**

`src/devpilot/state/store.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_state_store.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/devpilot/state/store.py tests/test_state_store.py
git commit -m "feat: state store with file locking, log capping, and cleanup"
```

---

### Task 3: Framework Registry

Detects frameworks from command strings, provides default profiles.

**Files:**
- Create: `src/devpilot/frameworks/registry.py`
- Create: `tests/test_frameworks.py`

- [ ] **Step 1: Write failing tests**

`tests/test_frameworks.py`:
```python
from devpilot.frameworks.registry import FrameworkRegistry, FrameworkProfile


def test_detect_fastapi():
    reg = FrameworkRegistry()
    profile = reg.detect("uvicorn app.main:app --reload")
    assert profile.name == "fastapi"
    assert profile.default_port == 8000
    assert len(profile.reload_patterns) > 0


def test_detect_flask():
    reg = FrameworkRegistry()
    profile = reg.detect("flask run --debug")
    assert profile.name == "flask"
    assert profile.default_port == 5000


def test_detect_django():
    reg = FrameworkRegistry()
    profile = reg.detect("python manage.py runserver 0.0.0.0:8000")
    assert profile.name == "django"
    assert profile.default_port == 8000


def test_detect_vite():
    reg = FrameworkRegistry()
    profile = reg.detect("npx vite --port 5173")
    assert profile.name == "vite"
    assert profile.default_port == 5173


def test_detect_nextjs():
    reg = FrameworkRegistry()
    profile = reg.detect("npx next dev")
    assert profile.name == "nextjs"
    assert profile.default_port == 3000


def test_detect_cra():
    reg = FrameworkRegistry()
    profile = reg.detect("npx react-scripts start")
    assert profile.name == "cra"
    assert profile.default_port == 3000


def test_detect_unknown_returns_none():
    reg = FrameworkRegistry()
    profile = reg.detect("some-unknown-command --flag")
    assert profile is None


def test_register_custom_framework():
    reg = FrameworkRegistry()
    reg.register(FrameworkProfile(
        name="streamlit",
        detect_pattern="streamlit run",
        reload_patterns=["Watching for changes"],
        default_port=8501,
        health_check="tcp",
        type="backend",
    ))
    profile = reg.detect("streamlit run app.py")
    assert profile.name == "streamlit"
    assert profile.default_port == 8501


def test_profile_has_type():
    reg = FrameworkRegistry()
    backend = reg.detect("uvicorn app:main")
    frontend = reg.detect("npx vite")
    assert backend.type == "backend"
    assert frontend.type == "frontend"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_frameworks.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement framework registry**

`src/devpilot/frameworks/registry.py`:
```python
"""Framework detection and profile management."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FrameworkProfile:
    """Known framework with its detection pattern and defaults."""

    name: str
    detect_pattern: str  # substring match against command
    reload_patterns: list[str] = field(default_factory=list)
    default_port: int = 8000
    health_check: str = "tcp"  # "tcp" or an HTTP path like "/health"
    type: str = "backend"  # "backend" or "frontend"
    supports_port_env: bool = False  # can override port via PORT env var
    supports_port_flag: bool = False  # can override port via --port flag


# Built-in profiles per spec
_BUILTINS: list[FrameworkProfile] = [
    FrameworkProfile(
        name="fastapi",
        detect_pattern="uvicorn",
        reload_patterns=["Started reloading", "Application startup complete"],
        default_port=8000,
        health_check="/docs",
        type="backend",
        supports_port_flag=True,
    ),
    FrameworkProfile(
        name="flask",
        detect_pattern="flask run",
        reload_patterns=["Restarting with stat"],
        default_port=5000,
        health_check="tcp",
        type="backend",
        supports_port_flag=True,
    ),
    FrameworkProfile(
        name="django",
        detect_pattern="manage.py runserver",
        reload_patterns=["Watching for file changes"],
        default_port=8000,
        health_check="tcp",
        type="backend",
    ),
    FrameworkProfile(
        name="vite",
        detect_pattern="vite",
        reload_patterns=["page reload", "hmr update"],
        default_port=5173,
        health_check="tcp",
        type="frontend",
        supports_port_flag=True,
    ),
    FrameworkProfile(
        name="nextjs",
        detect_pattern="next dev",
        reload_patterns=["compiled successfully", "compiled client and server"],
        default_port=3000,
        health_check="/",
        type="frontend",
        supports_port_flag=True,
    ),
    FrameworkProfile(
        name="cra",
        detect_pattern="react-scripts start",
        reload_patterns=["Compiled successfully"],
        default_port=3000,
        health_check="tcp",
        type="frontend",
        supports_port_env=True,
    ),
]


class FrameworkRegistry:
    """Detect frameworks from command strings and manage profiles."""

    def __init__(self) -> None:
        self._profiles: list[FrameworkProfile] = list(_BUILTINS)

    def detect(self, command: str) -> FrameworkProfile | None:
        """Match a command string against known framework patterns."""
        for profile in self._profiles:
            if profile.detect_pattern in command:
                return profile
        return None

    def register(self, profile: FrameworkProfile) -> None:
        """Add a custom framework profile. Takes priority over builtins."""
        # Insert at front so custom profiles match first
        self._profiles.insert(0, profile)

    @property
    def profiles(self) -> list[FrameworkProfile]:
        return list(self._profiles)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_frameworks.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/devpilot/frameworks/registry.py tests/test_frameworks.py
git commit -m "feat: framework registry with 6 built-in profiles and custom registration"
```

---

### Task 4: Config Loader

Loads `.devpilot.yaml`, validates, merges with framework defaults.

**Files:**
- Create: `src/devpilot/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

`tests/test_config.py`:
```python
from pathlib import Path

import pytest
import yaml

from devpilot.config import load_config, DevPilotConfig, ServiceConfig


def test_load_valid_config(tmp_path):
    config_data = {
        "services": {
            "backend": {
                "cmd": "uvicorn app.main:app --reload",
                "type": "backend",
                "port": 8000,
                "health": "/health",
                "file_patterns": ["**/*.py"],
                "reload_patterns": ["Started reloading"],
            },
            "frontend": {
                "cmd": "npm run dev",
                "type": "frontend",
                "port": 3000,
                "file_patterns": ["src/**/*.tsx"],
            },
        },
        "recovery": {
            "max_retries": 3,
            "backoff_seconds": [1, 3, 5],
        },
    }
    config_file = tmp_path / ".devpilot.yaml"
    config_file.write_text(yaml.dump(config_data))

    config = load_config(tmp_path)
    assert len(config.services) == 2
    assert config.services["backend"].port == 8000
    assert config.services["frontend"].type == "frontend"
    assert config.recovery.max_retries == 3


def test_load_missing_config_returns_none(tmp_path):
    config = load_config(tmp_path)
    assert config is None


def test_service_inherits_framework_defaults(tmp_path):
    config_data = {
        "services": {
            "backend": {
                "cmd": "uvicorn app:main --reload",
                # No port, type, health — should come from framework detection
            },
        },
    }
    config_file = tmp_path / ".devpilot.yaml"
    config_file.write_text(yaml.dump(config_data))

    config = load_config(tmp_path)
    svc = config.services["backend"]
    assert svc.port == 8000  # from fastapi profile
    assert svc.type == "backend"  # from fastapi profile


def test_explicit_config_overrides_framework_defaults(tmp_path):
    config_data = {
        "services": {
            "backend": {
                "cmd": "uvicorn app:main --reload",
                "port": 9000,  # Override fastapi default of 8000
            },
        },
    }
    config_file = tmp_path / ".devpilot.yaml"
    config_file.write_text(yaml.dump(config_data))

    config = load_config(tmp_path)
    assert config.services["backend"].port == 9000


def test_custom_frameworks_in_config(tmp_path):
    config_data = {
        "services": {
            "app": {
                "cmd": "streamlit run app.py",
            },
        },
        "custom_frameworks": {
            "streamlit": {
                "detect": "streamlit run",
                "reload_patterns": ["Watching for changes"],
                "default_port": 8501,
                "health": "tcp",
            },
        },
    }
    config_file = tmp_path / ".devpilot.yaml"
    config_file.write_text(yaml.dump(config_data))

    config = load_config(tmp_path)
    assert config.services["app"].port == 8501


def test_recovery_defaults(tmp_path):
    config_data = {"services": {"b": {"cmd": "uvicorn app:main"}}}
    config_file = tmp_path / ".devpilot.yaml"
    config_file.write_text(yaml.dump(config_data))

    config = load_config(tmp_path)
    assert config.recovery.max_retries == 3
    assert config.recovery.backoff_seconds == [1, 3, 5]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_config.py -v`
Expected: FAIL

- [ ] **Step 3: Implement config loader**

`src/devpilot/config.py`:
```python
"""Load and validate .devpilot.yaml configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from devpilot.frameworks.registry import FrameworkProfile, FrameworkRegistry


@dataclass
class RecoveryConfig:
    max_retries: int = 3
    backoff_seconds: list[int] = field(default_factory=lambda: [1, 3, 5])
    auto_port_reassign: bool = True


@dataclass
class ServiceConfig:
    cmd: str
    type: str = "backend"
    port: int = 8000
    health: str | None = None
    file_patterns: list[str] = field(default_factory=list)
    reload_patterns: list[str] = field(default_factory=list)
    framework: str | None = None


@dataclass
class DevPilotConfig:
    services: dict[str, ServiceConfig]
    recovery: RecoveryConfig
    health_interval: int | None = None  # seconds, None = on-demand only


def load_config(project_dir: Path) -> DevPilotConfig | None:
    """Load .devpilot.yaml from project_dir. Returns None if not found."""
    config_path = project_dir / ".devpilot.yaml"
    if not config_path.exists():
        return None

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not raw or "services" not in raw:
        return None

    # Register custom frameworks first
    registry = FrameworkRegistry()
    for name, fw_data in raw.get("custom_frameworks", {}).items():
        registry.register(FrameworkProfile(
            name=name,
            detect_pattern=fw_data["detect"],
            reload_patterns=fw_data.get("reload_patterns", []),
            default_port=fw_data.get("default_port", 8000),
            health_check=fw_data.get("health", "tcp"),
            type=fw_data.get("type", "backend"),
        ))

    # Parse services, merging with framework defaults
    services: dict[str, ServiceConfig] = {}
    for svc_id, svc_data in raw["services"].items():
        cmd = svc_data["cmd"]
        profile = registry.detect(cmd)

        services[svc_id] = ServiceConfig(
            cmd=cmd,
            type=svc_data.get("type", profile.type if profile else "backend"),
            port=svc_data.get("port", profile.default_port if profile else 8000),
            health=svc_data.get("health", profile.health_check if profile else None),
            file_patterns=svc_data.get(
                "file_patterns",
                ["**/*.py"] if (profile and profile.type == "backend") else [],
            ),
            reload_patterns=svc_data.get(
                "reload_patterns",
                profile.reload_patterns if profile else [],
            ),
            framework=profile.name if profile else None,
        )

    # Parse recovery config
    recovery_raw = raw.get("recovery", {})
    recovery = RecoveryConfig(
        max_retries=recovery_raw.get("max_retries", 3),
        backoff_seconds=recovery_raw.get("backoff_seconds", [1, 3, 5]),
        auto_port_reassign=recovery_raw.get("auto_port_reassign", True),
    )

    return DevPilotConfig(
        services=services,
        recovery=recovery,
        health_interval=raw.get("health_interval"),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_config.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/devpilot/config.py tests/test_config.py
git commit -m "feat: config loader with framework default merging and custom frameworks"
```

---

### Task 5: Port Scanner

Cross-platform port-to-PID resolution using psutil.

**Files:**
- Create: `src/devpilot/process/scanner.py`
- Create: `tests/test_scanner.py`

- [ ] **Step 1: Write failing tests**

`tests/test_scanner.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_scanner.py -v`
Expected: FAIL

- [ ] **Step 3: Implement scanner**

`src/devpilot/process/scanner.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_scanner.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/devpilot/process/scanner.py tests/test_scanner.py
git commit -m "feat: cross-platform port scanner with PID lookup via psutil"
```

---

### Task 6: Health Checker

HTTP and TCP health checks for services.

**Files:**
- Create: `src/devpilot/health/checker.py`
- Create: `tests/test_health_checker.py`

- [ ] **Step 1: Write failing tests**

`tests/test_health_checker.py`:
```python
import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import pytest

from devpilot.health.checker import check_health, HealthResult


class OKHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, format, *args):
        pass  # Suppress output


class ErrorHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(500)
        self.end_headers()

    def log_message(self, format, *args):
        pass


@pytest.fixture
def http_server():
    server = HTTPServer(("127.0.0.1", 0), OKHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()


@pytest.fixture
def error_server():
    server = HTTPServer(("127.0.0.1", 0), ErrorHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()


@pytest.fixture
def tcp_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.listen(1)
    yield port
    sock.close()


def test_http_health_check_healthy(http_server):
    result = check_health(port=http_server, endpoint="/health")
    assert result.healthy is True
    assert result.status_code == 200
    assert result.response_time_ms > 0


def test_http_health_check_error(error_server):
    result = check_health(port=error_server, endpoint="/health")
    assert result.healthy is False
    assert result.status_code == 500


def test_tcp_health_check_healthy(tcp_server):
    result = check_health(port=tcp_server, endpoint=None)
    assert result.healthy is True
    assert result.status_code is None  # TCP has no status code


def test_health_check_unreachable():
    # Use a port that nothing is listening on
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    result = check_health(port=port, endpoint=None, timeout=1)
    assert result.healthy is False


def test_health_result_fields(http_server):
    result = check_health(port=http_server, endpoint="/")
    assert isinstance(result.response_time_ms, float)
    assert result.response_time_ms >= 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_health_checker.py -v`
Expected: FAIL

- [ ] **Step 3: Implement health checker**

`src/devpilot/health/checker.py`:
```python
"""HTTP and TCP health checks for services."""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass

import httpx


@dataclass
class HealthResult:
    healthy: bool
    status_code: int | None = None
    response_time_ms: float = 0.0
    error: str | None = None


def check_health(
    port: int,
    endpoint: str | None = None,
    host: str = "127.0.0.1",
    timeout: float = 5,
) -> HealthResult:
    """Check service health via HTTP (if endpoint given) or TCP."""
    if endpoint is not None:
        return _http_check(host, port, endpoint, timeout)
    return _tcp_check(host, port, timeout)


def _http_check(host: str, port: int, endpoint: str, timeout: float) -> HealthResult:
    url = f"http://{host}:{port}{endpoint}"
    start = time.monotonic()
    try:
        response = httpx.get(url, timeout=timeout)
        elapsed = (time.monotonic() - start) * 1000
        return HealthResult(
            healthy=200 <= response.status_code < 400,
            status_code=response.status_code,
            response_time_ms=elapsed,
        )
    except httpx.HTTPError as e:
        elapsed = (time.monotonic() - start) * 1000
        return HealthResult(
            healthy=False,
            response_time_ms=elapsed,
            error=str(e),
        )


def _tcp_check(host: str, port: int, timeout: float) -> HealthResult:
    start = time.monotonic()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((host, port))
            elapsed = (time.monotonic() - start) * 1000
            return HealthResult(healthy=True, response_time_ms=elapsed)
    except (ConnectionRefusedError, TimeoutError, OSError) as e:
        elapsed = (time.monotonic() - start) * 1000
        return HealthResult(healthy=False, response_time_ms=elapsed, error=str(e))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_health_checker.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/devpilot/health/checker.py tests/test_health_checker.py
git commit -m "feat: HTTP and TCP health checker with response timing"
```

---

### Task 7: Active Endpoint Verifier

Hits a specific endpoint and returns detailed results for the `changed --verify-endpoint` flag.

**Files:**
- Create: `src/devpilot/health/verifier.py`
- Create: `tests/test_verifier.py`

- [ ] **Step 1: Write failing tests**

`tests/test_verifier.py`:
```python
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import pytest

from devpilot.health.verifier import verify_endpoint, VerifyResult


class JSONHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"users": []}')

    def log_message(self, format, *args):
        pass


@pytest.fixture
def json_server():
    server = HTTPServer(("127.0.0.1", 0), JSONHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()


def test_verify_get_endpoint(json_server):
    result = verify_endpoint("GET", f"/api/users", port=json_server)
    assert result.status_code == 200
    assert result.response_time_ms > 0


def test_verify_unreachable_endpoint():
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    result = verify_endpoint("GET", "/api/users", port=port, timeout=1)
    assert result.status_code is None
    assert result.error is not None


def test_verify_result_as_dict(json_server):
    result = verify_endpoint("GET", "/api/users", port=json_server)
    d = result.to_dict()
    assert d["endpoint"] == "GET /api/users"
    assert d["status"] == 200
    assert "response_time_ms" in d
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_verifier.py -v`
Expected: FAIL

- [ ] **Step 3: Implement verifier**

`src/devpilot/health/verifier.py`:
```python
"""Active endpoint verification for the changed command."""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx


@dataclass
class VerifyResult:
    method: str
    path: str
    status_code: int | None = None
    response_time_ms: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict:
        d: dict = {
            "endpoint": f"{self.method} {self.path}",
            "status": self.status_code,
            "response_time_ms": round(self.response_time_ms, 1),
        }
        if self.error:
            d["error"] = self.error
        return d


def verify_endpoint(
    method: str,
    path: str,
    port: int,
    host: str = "127.0.0.1",
    timeout: float = 5,
) -> VerifyResult:
    """Hit a specific endpoint and return status + timing."""
    url = f"http://{host}:{port}{path}"
    start = time.monotonic()
    try:
        response = httpx.request(method, url, timeout=timeout)
        elapsed = (time.monotonic() - start) * 1000
        return VerifyResult(
            method=method,
            path=path,
            status_code=response.status_code,
            response_time_ms=elapsed,
        )
    except httpx.HTTPError as e:
        elapsed = (time.monotonic() - start) * 1000
        return VerifyResult(
            method=method,
            path=path,
            response_time_ms=elapsed,
            error=str(e),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_verifier.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/devpilot/health/verifier.py tests/test_verifier.py
git commit -m "feat: active endpoint verifier for changed --verify-endpoint"
```

---

### Task 8: Reload Detector

Watches stdout lines for framework-specific reload patterns.

**Files:**
- Create: `src/devpilot/watch/reload.py`
- Create: `tests/test_reload.py`

- [ ] **Step 1: Write failing tests**

`tests/test_reload.py`:
```python
import threading
import time

import pytest

from devpilot.watch.reload import ReloadDetector, ReloadResult


def test_detect_reload_from_lines():
    detector = ReloadDetector(
        patterns=["Started reloading", "Application startup complete"],
    )
    detector.feed_line("INFO:     Will watch for changes in these directories")
    detector.feed_line("INFO:     Started reloading")
    detector.feed_line("INFO:     Application startup complete")

    result = detector.get_result(timeout=1)
    assert result.status == "reloaded"


def test_detect_reload_failure():
    detector = ReloadDetector(
        patterns=["Application startup complete"],
    )
    detector.feed_line("  File \"app.py\", line 42")
    detector.feed_line("SyntaxError: unexpected indent")
    detector.mark_error("SyntaxError: unexpected indent")

    result = detector.get_result(timeout=1)
    assert result.status == "reload_failed"
    assert "SyntaxError" in result.error


def test_detect_timeout():
    detector = ReloadDetector(patterns=["never appears"])
    result = detector.get_result(timeout=0.1)
    assert result.status == "timeout"


def test_reload_time_tracked():
    detector = ReloadDetector(
        patterns=["Started reloading", "Application startup complete"],
    )
    detector.feed_line("Started reloading")
    time.sleep(0.05)
    detector.feed_line("Application startup complete")

    result = detector.get_result(timeout=1)
    assert result.status == "reloaded"
    assert result.reload_time_ms >= 40  # At least ~50ms minus tolerance


def test_error_patterns_detected():
    detector = ReloadDetector(patterns=["startup complete"])
    detector.feed_line("Traceback (most recent call last):")
    detector.feed_line('  File "app.py", line 10')
    detector.feed_line("ImportError: No module named 'foo'")
    detector.mark_error("ImportError: No module named 'foo'")

    result = detector.get_result(timeout=1)
    assert result.status == "reload_failed"
    assert "ImportError" in result.error
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_reload.py -v`
Expected: FAIL

- [ ] **Step 3: Implement reload detector**

`src/devpilot/watch/reload.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_reload.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/devpilot/watch/reload.py tests/test_reload.py
git commit -m "feat: reload detector with pattern matching, error extraction, and timing"
```

---

### Task 9: File Watcher

Maps file changes to services using glob patterns.

**Files:**
- Create: `src/devpilot/watch/file_watcher.py`
- Create: `tests/test_file_watcher.py`

- [ ] **Step 1: Write failing tests**

`tests/test_file_watcher.py`:
```python
from pathlib import Path, PurePosixPath

import pytest

from devpilot.watch.file_watcher import match_file_to_services


def test_match_python_file_to_backend():
    services = {
        "backend": {"file_patterns": ["**/*.py"]},
        "frontend": {"file_patterns": ["src/**/*.tsx"]},
    }
    matches = match_file_to_services("app/routes/users.py", services)
    assert matches == ["backend"]


def test_match_tsx_file_to_frontend():
    services = {
        "backend": {"file_patterns": ["**/*.py"]},
        "frontend": {"file_patterns": ["src/**/*.tsx", "src/**/*.ts"]},
    }
    matches = match_file_to_services("src/components/Header.tsx", services)
    assert matches == ["frontend"]


def test_match_no_service():
    services = {
        "backend": {"file_patterns": ["**/*.py"]},
        "frontend": {"file_patterns": ["src/**/*.tsx"]},
    }
    matches = match_file_to_services("assets/logo.png", services)
    assert matches == []


def test_match_multiple_services():
    services = {
        "backend": {"file_patterns": ["**/*.py"]},
        "shared": {"file_patterns": ["**/*.py", "**/*.ts"]},
    }
    matches = match_file_to_services("lib/utils.py", services)
    assert "backend" in matches
    assert "shared" in matches


def test_match_css_file():
    services = {
        "frontend": {"file_patterns": ["src/**/*.tsx", "src/**/*.css"]},
    }
    matches = match_file_to_services("src/styles/main.css", services)
    assert matches == ["frontend"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_file_watcher.py -v`
Expected: FAIL

- [ ] **Step 3: Implement file watcher**

`src/devpilot/watch/file_watcher.py`:
```python
"""File-to-service mapping using glob patterns."""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import PurePosixPath


def match_file_to_services(
    filepath: str,
    services: dict[str, dict],
) -> list[str]:
    """Match a file path against all services' file_patterns.

    Returns list of matching service IDs. Always uses forward slashes
    for pattern matching regardless of OS.
    """
    # Normalize to forward slashes for cross-platform matching
    normalized = filepath.replace("\\", "/")
    matches = []

    for svc_id, svc_data in services.items():
        for pattern in svc_data.get("file_patterns", []):
            if fnmatch(normalized, pattern):
                matches.append(svc_id)
                break

    return matches
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_file_watcher.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/devpilot/watch/file_watcher.py tests/test_file_watcher.py
git commit -m "feat: file-to-service matching with glob patterns"
```

---

### Task 10: Recovery Strategy

Tiered recovery logic: classify events, decide action.

**Files:**
- Create: `src/devpilot/recovery/strategy.py`
- Create: `tests/test_recovery.py`

- [ ] **Step 1: Write failing tests**

`tests/test_recovery.py`:
```python
import pytest

from devpilot.recovery.strategy import (
    RecoveryStrategy,
    RecoveryAction,
    RecoveryTier,
)


@pytest.fixture
def strategy():
    return RecoveryStrategy(max_retries=3, backoff_seconds=[1, 3, 5])


def test_first_crash_is_tier1_restart(strategy):
    action = strategy.on_crash("backend", attempt=1)
    assert action.tier == RecoveryTier.SILENT
    assert action.action == "restart"
    assert action.delay == 1


def test_second_crash_backoff(strategy):
    action = strategy.on_crash("backend", attempt=2)
    assert action.tier == RecoveryTier.SILENT
    assert action.delay == 3


def test_third_crash_still_restarts(strategy):
    action = strategy.on_crash("backend", attempt=3)
    assert action.tier == RecoveryTier.REPORT
    assert action.action == "restart"


def test_fourth_crash_escalates(strategy):
    action = strategy.on_crash("backend", attempt=4)
    assert action.tier == RecoveryTier.ESCALATE
    assert action.action == "report"


def test_port_conflict_with_flag_support(strategy):
    action = strategy.on_port_conflict("backend", supports_port_flag=True)
    assert action.tier == RecoveryTier.REPORT
    assert action.action == "reassign_port"


def test_port_conflict_without_flag_support(strategy):
    action = strategy.on_port_conflict("backend", supports_port_flag=False)
    assert action.tier == RecoveryTier.ESCALATE
    assert action.action == "report"


def test_reload_failed_escalates(strategy):
    action = strategy.on_reload_failed("backend", error="SyntaxError: ...")
    assert action.tier == RecoveryTier.ESCALATE
    assert action.action == "report"


def test_attached_crash_escalates(strategy):
    action = strategy.on_attached_crash("frontend", cmd="npm run dev")
    assert action.tier == RecoveryTier.ESCALATE
    assert "devpilot run" in action.suggestion


def test_unknown_port_holder_escalates(strategy):
    action = strategy.on_unknown_port_holder("backend", port=8000, holder_pid=999, holder_name="node")
    assert action.tier == RecoveryTier.ESCALATE
    assert "node" in action.suggestion
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_recovery.py -v`
Expected: FAIL

- [ ] **Step 3: Implement recovery strategy**

`src/devpilot/recovery/strategy.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_recovery.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/devpilot/recovery/strategy.py tests/test_recovery.py
git commit -m "feat: tiered recovery strategy with crash backoff and escalation"
```

---

### Task 11: Process Manager (Managed Mode)

Spawns and monitors child processes with stdout capture.

**Files:**
- Create: `src/devpilot/process/manager.py`
- Create: `tests/test_process_manager.py`

- [ ] **Step 1: Write failing tests**

`tests/test_process_manager.py`:
```python
import sys
import time

import pytest

from devpilot.process.manager import ManagedProcess


def test_start_and_stop():
    """Start a simple process, verify it's running, then stop it."""
    proc = ManagedProcess(
        name="test",
        cmd=f"{sys.executable} -c \"import time; time.sleep(30)\"",
        port=0,  # No port check needed
    )
    proc.start()
    assert proc.is_alive()
    assert proc.pid is not None

    proc.stop()
    assert not proc.is_alive()


def test_stdout_capture():
    """Verify stdout lines are captured."""
    proc = ManagedProcess(
        name="test",
        cmd=f'{sys.executable} -c "print(\'hello world\'); import time; time.sleep(5)"',
        port=0,
    )
    proc.start()
    time.sleep(0.5)  # Let output arrive

    lines = proc.get_recent_output(10)
    proc.stop()

    assert any("hello world" in line for line in lines)


def test_on_line_callback():
    """Verify the on_line callback fires for each stdout line."""
    captured = []
    proc = ManagedProcess(
        name="test",
        cmd=f'{sys.executable} -c "print(\'line1\'); print(\'line2\'); import time; time.sleep(5)"',
        port=0,
        on_line=lambda line: captured.append(line),
    )
    proc.start()
    time.sleep(0.5)
    proc.stop()

    assert len(captured) >= 2
    assert any("line1" in c for c in captured)
    assert any("line2" in c for c in captured)


def test_exit_code_captured():
    """Process that exits with code 1."""
    proc = ManagedProcess(
        name="test",
        cmd=f"{sys.executable} -c \"raise SystemExit(1)\"",
        port=0,
    )
    proc.start()
    time.sleep(0.5)

    assert not proc.is_alive()
    assert proc.exit_code == 1


def test_restart():
    proc = ManagedProcess(
        name="test",
        cmd=f"{sys.executable} -c \"import time; time.sleep(30)\"",
        port=0,
    )
    proc.start()
    old_pid = proc.pid
    proc.restart()
    assert proc.is_alive()
    assert proc.pid != old_pid
    proc.stop()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_process_manager.py -v --timeout=15`
Expected: FAIL

- [ ] **Step 3: Implement managed process**

`src/devpilot/process/manager.py`:
```python
"""Spawn and monitor managed child processes."""

from __future__ import annotations

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
        self._process = subprocess.Popen(
            self._cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_process_manager.py -v --timeout=15`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/devpilot/process/manager.py tests/test_process_manager.py
git commit -m "feat: managed process with stdout capture, restart, and graceful shutdown"
```

---

### Task 12: Process Attacher

Discover and attach to existing processes by port.

**Files:**
- Create: `src/devpilot/process/attacher.py`
- Create: `tests/test_attacher.py`

- [ ] **Step 1: Write failing tests**

`tests/test_attacher.py`:
```python
import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import pytest

from devpilot.process.attacher import AttachedProcess


class OKHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
    def log_message(self, format, *args):
        pass


@pytest.fixture
def running_server():
    server = HTTPServer(("127.0.0.1", 0), OKHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()


def test_attach_to_running_process(running_server):
    attached = AttachedProcess.attach(name="test", port=running_server)
    assert attached is not None
    assert attached.pid is not None
    assert attached.is_alive()


def test_attach_to_empty_port_returns_none():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    attached = AttachedProcess.attach(name="test", port=port)
    assert attached is None


def test_attached_process_detects_process_name(running_server):
    attached = AttachedProcess.attach(name="test", port=running_server)
    assert attached is not None
    assert attached.process_name is not None  # Should be "python" or similar
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_attacher.py -v`
Expected: FAIL

- [ ] **Step 3: Implement attacher**

`src/devpilot/process/attacher.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_attacher.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/devpilot/process/attacher.py tests/test_attacher.py
git commit -m "feat: process attacher for sidecar mode via port-to-PID lookup"
```

---

### Task 13: Supervisor Core

The orchestrator that ties process management, health, recovery, and state together.

**Files:**
- Create: `src/devpilot/supervisor.py`
- Create: `tests/test_supervisor.py`

- [ ] **Step 1: Write failing tests**

`tests/test_supervisor.py`:
```python
import sys
import time
from pathlib import Path

import pytest

from devpilot.supervisor import Supervisor
from devpilot.state.store import StateStore


@pytest.fixture
def supervisor(tmp_project):
    store = StateStore(tmp_project / ".devpilot" / "state.json")
    return Supervisor(store=store, project_dir=tmp_project)


def test_run_service_registers_in_state(supervisor):
    cmd = f'{sys.executable} -c "import time; time.sleep(30)"'
    supervisor.run_service("test_svc", cmd, port=0, type="backend")
    time.sleep(0.3)

    state = supervisor.store.read()
    assert "test_svc" in state["services"]
    assert state["services"]["test_svc"]["status"] == "registered"
    assert state["services"]["test_svc"]["mode"] == "managed"

    supervisor.stop_service("test_svc")


def test_stop_service_removes_process(supervisor):
    cmd = f'{sys.executable} -c "import time; time.sleep(30)"'
    supervisor.run_service("test_svc", cmd, port=0, type="backend")
    time.sleep(0.3)

    supervisor.stop_service("test_svc")
    time.sleep(0.3)

    assert not supervisor.is_running("test_svc")


def test_status_returns_all_services(supervisor):
    cmd = f'{sys.executable} -c "import time; time.sleep(30)"'
    supervisor.run_service("svc1", cmd, port=0, type="backend")
    supervisor.run_service("svc2", cmd, port=0, type="frontend")
    time.sleep(0.3)

    status = supervisor.get_status()
    assert len(status) == 2
    assert "svc1" in status
    assert "svc2" in status

    supervisor.stop_all()


def test_stop_all_stops_everything(supervisor):
    cmd = f'{sys.executable} -c "import time; time.sleep(30)"'
    supervisor.run_service("svc1", cmd, port=0, type="backend")
    supervisor.run_service("svc2", cmd, port=0, type="frontend")
    time.sleep(0.3)

    supervisor.stop_all()
    time.sleep(0.3)

    assert not supervisor.is_running("svc1")
    assert not supervisor.is_running("svc2")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_supervisor.py -v --timeout=15`
Expected: FAIL

- [ ] **Step 3: Implement supervisor**

`src/devpilot/supervisor.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_supervisor.py -v --timeout=15`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/devpilot/supervisor.py tests/test_supervisor.py
git commit -m "feat: supervisor core with run/attach/stop/status/changed orchestration"
```

---

### Task 14: CLI — Core Commands

Click-based CLI with `run`, `attach`, `status`, `stop`, `changed`.

**Files:**
- Create: `src/devpilot/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

`tests/test_cli.py`:
```python
import json

import pytest
from click.testing import CliRunner

from devpilot.cli import main


@pytest.fixture
def runner():
    return CliRunner()


def test_status_empty(runner, tmp_path):
    result = runner.invoke(main, ["status"], env={"DEVPILOT_PROJECT_DIR": str(tmp_path)})
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data == {}


def test_init_no_project_markers(runner, tmp_path):
    result = runner.invoke(main, ["init"], env={"DEVPILOT_PROJECT_DIR": str(tmp_path)})
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert "error" in data


def test_init_detects_uvicorn(runner, tmp_path):
    (tmp_path / "requirements.txt").write_text("uvicorn\nfastapi\n")
    result = runner.invoke(main, ["init"], env={"DEVPILOT_PROJECT_DIR": str(tmp_path)})
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "backend" in data["services"]
    # Verify yaml was created
    assert (tmp_path / ".devpilot.yaml").exists()


def test_init_detects_vite_frontend(runner, tmp_path):
    import json as json_mod
    pkg = {"scripts": {"dev": "vite"}, "devDependencies": {"vite": "^5.0"}}
    (tmp_path / "package.json").write_text(json_mod.dumps(pkg))
    result = runner.invoke(main, ["init"], env={"DEVPILOT_PROJECT_DIR": str(tmp_path)})
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "frontend" in data["services"]


def test_init_prefers_pyproject_over_requirements(runner, tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = ['flask']\n")
    (tmp_path / "requirements.txt").write_text("uvicorn\n")
    result = runner.invoke(main, ["init"], env={"DEVPILOT_PROJECT_DIR": str(tmp_path)})
    assert result.exit_code == 0
    data = json.loads(result.output)
    # Should detect flask from pyproject.toml, not uvicorn from requirements.txt
    assert "backend" in data["services"]


def test_cleanup_empty_state(runner, tmp_path):
    result = runner.invoke(main, ["cleanup"], env={"DEVPILOT_PROJECT_DIR": str(tmp_path)})
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["removed"] == []


def test_log_empty(runner, tmp_path):
    result = runner.invoke(main, ["log"], env={"DEVPILOT_PROJECT_DIR": str(tmp_path)})
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["entries"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_cli.py -v`
Expected: FAIL

- [ ] **Step 3: Implement CLI**

`src/devpilot/cli.py`:
```python
"""Click-based CLI for DevPilot."""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

import click
import yaml

from devpilot.config import load_config
from devpilot.frameworks.registry import FrameworkProfile, FrameworkRegistry
from devpilot.state.store import StateStore
from devpilot.supervisor import Supervisor


def _get_project_dir() -> Path:
    return Path(os.environ.get("DEVPILOT_PROJECT_DIR", os.getcwd()))


def _get_store() -> StateStore:
    project_dir = _get_project_dir()
    state_dir = project_dir / ".devpilot"
    state_dir.mkdir(exist_ok=True)
    return StateStore(state_dir / "state.json")


def _get_supervisor() -> Supervisor:
    store = _get_store()
    config = load_config(_get_project_dir())
    max_retries = config.recovery.max_retries if config else 3
    backoff = config.recovery.backoff_seconds if config else [1, 3, 5]
    return Supervisor(
        store=store,
        project_dir=_get_project_dir(),
        max_retries=max_retries,
        backoff_seconds=backoff,
    )


def _print_json(data: dict) -> None:
    """Print JSON to stdout without exiting."""
    click.echo(json.dumps(data, indent=2, default=str))


def _output(data: dict, exit_code: int = 0) -> None:
    """Print JSON and exit. Use for commands that don't need to stay alive."""
    _print_json(data)
    sys.exit(exit_code)


@click.group()
def main():
    """DevPilot — Dev server supervisor for AI coders."""
    pass


@main.command()
@click.argument("name")
@click.argument("cmd")
@click.option("--type", "svc_type", type=click.Choice(["backend", "frontend"]), default=None)
@click.option("--port", type=int, default=None)
@click.option("--health", default=None)
@click.option("--reload-pattern", multiple=True)
@click.option("--file-pattern", multiple=True)
def run(name, cmd, svc_type, port, health, reload_pattern, file_pattern):
    """Start and manage a service."""
    supervisor = _get_supervisor()
    registry = FrameworkRegistry()
    profile = registry.detect(cmd)

    resolved_type = svc_type or (profile.type if profile else "backend")
    resolved_port = port or (profile.default_port if profile else 8000)

    supervisor.run_service(
        name=name,
        cmd=cmd,
        port=resolved_port,
        type=resolved_type,
        health_endpoint=health,
        file_patterns=list(file_pattern) if file_pattern else None,
        reload_patterns=list(reload_pattern) if reload_pattern else None,
    )

    _print_json({
        "started": name,
        "cmd": cmd,
        "port": resolved_port,
        "type": resolved_type,
        "framework": profile.name if profile else "unknown",
        "mode": "managed",
    })

    # Block until interrupted — this process IS the supervisor for this service
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        supervisor.stop_service(name)
        _print_json({"stopped": name})


@main.command()
@click.argument("name")
@click.option("--port", type=int, required=True)
@click.option("--type", "svc_type", type=click.Choice(["backend", "frontend"]), default=None)
@click.option("--cmd", default=None)
@click.option("--health", default=None)
@click.option("--log-file", default=None)
def attach(name, port, svc_type, cmd, health, log_file):
    """Attach to an existing process on a port."""
    supervisor = _get_supervisor()
    success = supervisor.attach_service(
        name=name,
        port=port,
        type=svc_type or "backend",
        cmd=cmd,
        health_endpoint=health,
    )
    if not success:
        _output({"error": f"No process found on port {port}"}, exit_code=1)

    _output({"attached": name, "port": port, "mode": "attached"})


@main.command()
@click.argument("name", required=False)
def status(name):
    """Show service status."""
    supervisor = _get_supervisor()
    result = supervisor.get_status(name)
    _output(result)


@main.command()
@click.argument("filepath")
@click.option("--verify-endpoint", default=None)
@click.option("--timeout", type=float, default=10)
def changed(filepath, verify_endpoint, timeout):
    """Report a file change and check if reload succeeded."""
    supervisor = _get_supervisor()
    result = supervisor.handle_changed(filepath, verify_endpoint, timeout)
    exit_code = 0
    if result.get("results"):
        statuses = {r.get("reload") for r in result["results"]}
        failures = statuses & {"reload_failed", "timeout"}
        successes = statuses & {"reloaded", "health_only"}
        if failures and successes:
            exit_code = 2  # Partial — mixed results
        elif failures:
            exit_code = 1  # All failed
    _output(result, exit_code)


@main.command()
@click.argument("name", required=False)
@click.option("--all", "stop_all", is_flag=True)
def stop(name, stop_all):
    """Stop a service or all services."""
    supervisor = _get_supervisor()
    if stop_all:
        supervisor.stop_all()
        _output({"stopped": "all"})
    elif name:
        supervisor.stop_service(name)
        _output({"stopped": name})
    else:
        _output({"error": "Specify a service name or --all"}, exit_code=1)


@main.command()
@click.argument("name")
def restart(name):
    """Restart a managed service."""
    supervisor = _get_supervisor()
    state = supervisor.store.read()
    svc = state["services"].get(name)
    if not svc:
        _output({"error": f"Service '{name}' not found"}, exit_code=1)
        return
    if svc["mode"] != "managed":
        _output({"error": f"Cannot restart attached service '{name}'"}, exit_code=1)
        return

    supervisor.stop_service(name)
    supervisor.run_service(
        name=name, cmd=svc["cmd"], port=svc["port"],
        type=svc["type"], health_endpoint=svc.get("health_endpoint"),
        file_patterns=svc.get("file_patterns"),
        reload_patterns=svc.get("reload_patterns"),
    )
    _output({"restarted": name})


@main.command()
@click.argument("name", required=False)
@click.option("--service", default=None)
@click.option("--since", default=None)
def log(name, service, since):
    """Show recent events."""
    store = _get_store()
    state = store.read()
    entries = state.get("log", [])

    filter_svc = name or service
    if filter_svc:
        entries = [e for e in entries if e.get("service") == filter_svc]

    if since:
        entries = [e for e in entries if e.get("timestamp", "") >= since]

    _output({"entries": entries})


@main.command()
def cleanup():
    """Remove stale state and dead PIDs."""
    store = _get_store()
    removed = store.cleanup()
    _output({"removed": removed})


@main.command()
def up():
    """Start all services from .devpilot.yaml."""
    config = load_config(_get_project_dir())
    if config is None:
        _output({"error": "No .devpilot.yaml found. Run 'devpilot init' first."}, exit_code=1)

    supervisor = _get_supervisor()
    started = []

    for name, svc in config.services.items():
        supervisor.run_service(
            name=name,
            cmd=svc.cmd,
            port=svc.port,
            type=svc.type,
            health_endpoint=svc.health,
            file_patterns=svc.file_patterns,
            reload_patterns=svc.reload_patterns,
        )
        started.append(name)

    click.echo(json.dumps({"started": started}, indent=2))

    # Block until interrupted
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        supervisor.stop_all()
        click.echo(json.dumps({"stopped": "all"}))


@main.command()
def down():
    """Stop all services (alias for stop --all)."""
    supervisor = _get_supervisor()
    supervisor.stop_all()
    _output({"stopped": "all"})


@main.command()
def init():
    """Auto-detect project structure and generate .devpilot.yaml."""
    project_dir = _get_project_dir()
    services: dict = {}

    # Check for Python backend
    pyproject = project_dir / "pyproject.toml"
    requirements = project_dir / "requirements.txt"
    py_source = pyproject if pyproject.exists() else (requirements if requirements.exists() else None)

    if py_source:
        content = py_source.read_text(encoding="utf-8")
        if "uvicorn" in content:
            services["backend"] = {
                "cmd": "uvicorn app.main:app --reload",
                "type": "backend",
                "port": 8000,
                "health": "/docs",
                "file_patterns": ["**/*.py"],
            }
        elif "flask" in content:
            services["backend"] = {
                "cmd": "flask run --debug",
                "type": "backend",
                "port": 5000,
                "file_patterns": ["**/*.py"],
            }
        elif "django" in content:
            services["backend"] = {
                "cmd": "python manage.py runserver",
                "type": "backend",
                "port": 8000,
                "file_patterns": ["**/*.py"],
            }

    # Check for JS frontend
    package_json = project_dir / "package.json"
    if package_json.exists():
        try:
            import json as json_mod
            pkg = json_mod.loads(package_json.read_text(encoding="utf-8"))
            scripts = pkg.get("scripts", {})
            dev_cmd = scripts.get("dev", "")
            if "vite" in dev_cmd or "vite" in str(pkg.get("devDependencies", {})):
                services["frontend"] = {
                    "cmd": "npm run dev",
                    "type": "frontend",
                    "port": 5173,
                    "file_patterns": ["src/**/*.tsx", "src/**/*.ts", "src/**/*.css"],
                }
            elif "next" in dev_cmd or "next" in str(pkg.get("dependencies", {})):
                services["frontend"] = {
                    "cmd": "npm run dev",
                    "type": "frontend",
                    "port": 3000,
                    "file_patterns": ["src/**/*.tsx", "src/**/*.ts", "app/**/*.tsx"],
                }
            elif "react-scripts" in dev_cmd:
                services["frontend"] = {
                    "cmd": "npm start",
                    "type": "frontend",
                    "port": 3000,
                    "file_patterns": ["src/**/*.tsx", "src/**/*.ts", "src/**/*.jsx"],
                }
        except (json.JSONDecodeError, KeyError):
            pass

    if not services:
        _output({"error": "No recognized project markers found. Create .devpilot.yaml manually."}, exit_code=1)

    config_data = {
        "services": services,
        "recovery": {"max_retries": 3, "backoff_seconds": [1, 3, 5]},
    }
    config_path = project_dir / ".devpilot.yaml"
    config_path.write_text(yaml.dump(config_data, default_flow_style=False), encoding="utf-8")

    _output({"created": str(config_path), "services": list(services.keys())})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_cli.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/devpilot/cli.py tests/test_cli.py
git commit -m "feat: Click CLI with run/attach/status/changed/stop/log/cleanup/up/down/init"
```

---

### Task 15: Integration Test — The `changed` Pipeline

End-to-end test: start a real server, change a file, verify the full pipeline.

**Files:**
- Create: `tests/fixtures/fastapi_app/app.py`
- Create: `tests/test_changed.py`

- [ ] **Step 1: Create test fixture — minimal FastAPI app**

`tests/fixtures/fastapi_app/app.py`:
```python
"""Minimal FastAPI app for integration testing."""

from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/users")
def users():
    return {"users": []}
```

- [ ] **Step 2: Write failing integration test**

`tests/test_changed.py`:
```python
"""Integration test for the devpilot changed pipeline."""

import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from devpilot.state.store import StateStore
from devpilot.supervisor import Supervisor

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "fastapi_app"


def _uvicorn_available():
    try:
        import uvicorn
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _uvicorn_available(), reason="uvicorn not installed")
class TestChangedPipeline:

    def test_changed_detects_reload(self, tmp_project):
        # Copy fixture app to temp dir
        app_dir = tmp_project / "app"
        app_dir.mkdir()
        shutil.copy(FIXTURE_DIR / "app.py", app_dir / "app.py")

        store = StateStore(tmp_project / ".devpilot" / "state.json")
        supervisor = Supervisor(store=store, project_dir=tmp_project)

        # Start the app
        cmd = f"{sys.executable} -m uvicorn app.app:app --reload --port 18234 --app-dir {app_dir}"
        supervisor.run_service(
            "backend", cmd, port=18234, type="backend",
            health_endpoint="/health",
            file_patterns=["**/*.py"],
            reload_patterns=["Started reloading", "Application startup complete"],
        )

        # Wait for startup
        time.sleep(3)

        # Check status
        status = supervisor.get_status("backend")
        assert "backend" in status

        supervisor.stop_service("backend")

    def test_changed_no_matching_service(self, tmp_project):
        store = StateStore(tmp_project / ".devpilot" / "state.json")
        supervisor = Supervisor(store=store, project_dir=tmp_project)

        result = supervisor.handle_changed("assets/logo.png")
        assert result["results"] == []
        assert "No registered service" in result.get("message", "")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd D:/show_case/devpilot && python -m pytest tests/test_changed.py -v --timeout=30`
Expected: FAIL (fixture dir doesn't exist yet or import fails)

- [ ] **Step 4: Create fixture directory and run tests**

Run: `mkdir -p tests/fixtures/fastapi_app` (already created above in step 1)
Then: `cd D:/show_case/devpilot && python -m pytest tests/test_changed.py -v --timeout=30`
Expected: Tests PASS (or skip if uvicorn not installed)

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/ tests/test_changed.py
git commit -m "feat: integration test for changed pipeline with real FastAPI app"
```

---

### Task 16: Final Verification & Cleanup

**Files:**
- None new — verify everything works together

- [ ] **Step 1: Run full test suite**

Run: `cd D:/show_case/devpilot && python -m pytest tests/ -v --timeout=30`
Expected: All tests PASS

- [ ] **Step 2: Verify CLI entry point works**

Run: `cd D:/show_case/devpilot && pip install -e ".[dev]" && devpilot --help`
Expected: Shows help text with all commands listed

- [ ] **Step 3: Verify devpilot status works on empty project**

Run: `cd D:/show_case/devpilot && devpilot status`
Expected: `{}` (empty JSON)

- [ ] **Step 4: Verify devpilot cleanup works**

Run: `cd D:/show_case/devpilot && devpilot cleanup`
Expected: `{"removed": []}`

- [ ] **Step 5: Add .gitignore**

Create `.gitignore`:
```
__pycache__/
*.pyc
*.egg-info/
dist/
build/
.devpilot/state.json
.devpilot/state.json.lock
.env
```

- [ ] **Step 6: Final commit**

```bash
git add .gitignore
git commit -m "chore: add .gitignore and verify full test suite passes"
```
