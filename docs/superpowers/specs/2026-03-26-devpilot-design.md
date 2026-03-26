# DevPilot — Dev Server Supervisor for AI Coders

**Date:** 2026-03-26
**Status:** Approved

## Problem

CLI AI coders (Claude Code, Cursor, Copilot agent, etc.) struggle when managing frontend and backend dev servers simultaneously. They start servers, make code changes, but have no reliable way to confirm changes are reflected. Without feedback, they enter a panic cycle: killing ports, rotating port numbers, identifying "zombie" processes, and eventually nuking all Python tasks — making things worse.

## Solution

DevPilot is a Python CLI daemon/supervisor that gives AI coders reliable process awareness for dev servers. It manages process lifecycles, watches for file changes, detects reloads, checks health, and provides structured JSON output that AI coders can parse and act on.

## Key Decisions

- **Hybrid model:** Can both start processes (`run` — full control) and attach to existing ones (`attach` — sidecar mode with degraded capabilities)
- **AI-aware:** Accepts context about what the AI changed and correlates it to services, reload signals, and endpoint verification
- **Tiered recovery:** Auto-recovers obvious failures (crashes), escalates ambiguous ones (port conflicts, repeated failures) with context and suggestions
- **Framework detection:** Ships with profiles for common Python backends (FastAPI, Flask, Django) and JS frontends (Vite, Next.js, CRA) with extensible custom profiles
- **Language:** Python, distributed via pip/pipx
- **Target audience:** Any CLI AI coder, not Claude Code-specific

---

## Architecture

Three-layer design:

```
┌─────────────────────────────────────┐
│           CLI Interface             │  devpilot run/attach/status/changed
├─────────────────────────────────────┤
│         Supervisor Core             │  Process lifecycle, health loop, recovery
├──────────┬──────────┬───────────────┤
│ Process  │  File    │  Health       │
│ Manager  │  Watcher │  Checker      │
└──────────┴──────────┴───────────────┘
```

**Process Manager** — Two modes per service:
- **Managed** (`devpilot run`): Spawns the process, owns stdin/stdout/stderr, tracks PID directly. Full lifecycle control.
- **Attached** (`devpilot attach`): Discovers process by port scan, tracks PID via `lsof`/`netstat`. Limited control — can monitor but restart requires the original command (provided via `--cmd` flag).

**File Watcher** — Uses `watchdog` to monitor source directories. Maps files to services based on configured `file_patterns` (e.g., `*.py` → backend, `src/**/*.tsx` → frontend).

**Health Checker** — Polling loop that hits each service's health endpoint (HTTP) or checks TCP port liveness. Tracks response times, status codes, and compares against baseline.

**State** is held in a JSON file (`.devpilot/state.json` in the project) so the CLI can query it without keeping a socket open. File locking via `filelock` for safe concurrent access.

**No separate daemon process.** Each `run` command spawns the target as a child process with monitoring in a background thread. The state file is the shared coordination point.

---

## Service Registry & Framework Detection

Each registered service carries this metadata:

```json
{
  "id": "backend",
  "type": "backend",
  "framework": "fastapi",
  "cmd": "uvicorn app:main --reload",
  "pid": 12345,
  "port": 8000,
  "mode": "managed",
  "health_endpoint": "/health",
  "file_patterns": ["**/*.py"],
  "reload_patterns": ["Started reloading", "Application startup complete"],
  "status": "healthy",
  "last_reload": "2026-03-26T14:32:01Z",
  "started_at": "2026-03-26T14:30:00Z"
}
```

### Built-in Framework Profiles

| Framework | Detection | Reload Pattern | Default Port | Health Check |
|-----------|-----------|---------------|-------------|-------------|
| FastAPI/Uvicorn | `uvicorn` in cmd | `Started reloading` → `Application startup complete` | 8000 | `GET /docs` or TCP |
| Flask | `flask run` in cmd | `Restarting with stat` | 5000 | TCP |
| Django | `manage.py runserver` in cmd | `Watching for file changes` | 8000 | TCP |
| Vite/React | `vite` in cmd | `page reload` or `hmr update` | 5173 | TCP |
| Next.js | `next dev` in cmd | `compiled successfully` or `compiled client and server` | 3000 | `GET /` |
| Create React App | `react-scripts start` | `Compiled successfully` | 3000 | TCP |

Detection logic: parse the command string → match against known patterns → load profile → auto-fill defaults. All defaults overridable via CLI flags or config file. Extensible via `custom_frameworks` in `.devpilot.yaml`.

---

## The `changed` Command — AI-Aware Change Correlation

The core differentiator. When an AI coder edits a file:

```
devpilot changed app/routes/users.py
```

**Pipeline:**

1. **Correlate file → service** — Match file path against registered services' `file_patterns`.
2. **Wait for reload signal** — Watch service stdout for known reload patterns. Timeout after configurable window (default 10s). Results: `reloaded`, `reload_failed`, `timeout`, `no_reload_expected`.
3. **Verify health** — Hit health endpoint to confirm service is responding.
4. **Optional active verification** — If `--verify-endpoint GET /api/users` is passed, hit that endpoint and return status code + response time.

### Output (success):
```json
{
  "file": "app/routes/users.py",
  "service": "backend",
  "reload": "reloaded",
  "reload_time_ms": 1200,
  "health": "healthy",
  "verification": {
    "endpoint": "GET /api/users",
    "status": 200,
    "response_time_ms": 45
  }
}
```

### Output (failure):
```json
{
  "file": "app/routes/users.py",
  "service": "backend",
  "reload": "reload_failed",
  "error": "SyntaxError: unexpected indent (app/routes/users.py, line 42)",
  "health": "unreachable",
  "suggestion": "Fix syntax error on line 42, then re-check"
}
```

The `suggestion` field parses common error patterns and provides actionable hints the AI coder can act on directly.

---

## Auto-Recovery & Escalation

Tiered strategy — never does what the AI coder's panic cycle does:

### Tier 1 — Auto-recover silently
- Process crashed → restart (managed mode only, max 3 retries with backoff)
- Port not responding but process alive → wait up to 5s (likely slow reload)
- Stale PID file → clean up

### Tier 2 — Auto-recover and report
- Process crashed 3+ times → restart but flag in status with last error
- Port conflict on startup → pick next available port, update registry, report new port
- File change detected but no reload signal → report hot-reload may not work for this file type

### Tier 3 — Escalate, don't act
- Unknown process holding port → report PID, process name, suggest action
- Repeated reload failures from code errors → report errors, don't restart (code is broken)
- Attached-mode service crashed → report, suggest `devpilot run` with original command
- Multiple services down simultaneously → report all, don't cascade restarts

**Core principle:** DevPilot never rotates ports randomly, never kills processes it didn't start, never nukes all Python tasks. When uncertain, it reports with context and lets the AI decide.

**Recovery log** — every action logged to state file with timestamps, queryable via `devpilot log`.

---

## CLI Interface

All commands return structured JSON to stdout. Optional `--human` flag for readable output. Exit codes: 0 = success, 1 = error, 2 = partial.

```
devpilot run <name> <cmd>        Start and manage a service
  --type backend|frontend        Service type (auto-detected if omitted)
  --port 8000                    Override default port
  --health /health               Custom health endpoint
  --reload-pattern "regex"       Custom reload detection pattern
  --file-pattern "**/*.py"       Files belonging to this service

devpilot attach <name>           Attach to existing process
  --port 8000                    Required: port to monitor
  --type backend|frontend        Service type
  --cmd "uvicorn app:main"       Original command (enables restart recovery)

devpilot status                  All services summary
devpilot status <name>           Single service detail

devpilot changed <filepath>      Report a file change, get reload/verify result
  --verify-endpoint "GET /path"  Active verification after reload
  --timeout 10                   Reload wait timeout in seconds

devpilot stop <name>             Gracefully stop a managed service
devpilot stop --all              Stop all managed services

devpilot restart <name>          Restart a service

devpilot log                     Recent events across all services
devpilot log <name>              Events for one service

devpilot cleanup                 Remove stale state, dead PIDs, orphan entries

devpilot up                      Start all services from .devpilot.yaml
devpilot down                    Stop all services

devpilot init                    Auto-detect project structure, generate .devpilot.yaml
```

---

## Project Configuration

`.devpilot.yaml` in project root:

```yaml
services:
  backend:
    cmd: "uvicorn app.main:app --reload"
    type: backend
    port: 8000
    health: /health
    file_patterns:
      - "**/*.py"
    reload_patterns:
      - "Started reloading"
      - "Application startup complete"

  frontend:
    cmd: "npm run dev"
    type: frontend
    port: 3000
    file_patterns:
      - "src/**/*.tsx"
      - "src/**/*.ts"
      - "src/**/*.css"

recovery:
  max_retries: 3
  backoff_seconds: [1, 3, 5]
  auto_port_reassign: true

custom_frameworks:
  streamlit:
    detect: "streamlit run"
    reload_patterns: ["Watching for changes"]
    default_port: 8501
    health: TCP
```

`devpilot init` scans for `requirements.txt` + `package.json`, `pyproject.toml` + `vite.config.ts`, etc. and generates a starter config.

---

## Package Structure

```
devpilot/
├── pyproject.toml
├── src/
│   └── devpilot/
│       ├── __init__.py
│       ├── cli.py              # Click-based CLI entry point
│       ├── config.py           # .devpilot.yaml loading & validation
│       ├── supervisor.py       # Core orchestrator
│       ├── process/
│       │   ├── __init__.py
│       │   ├── manager.py      # Spawn & track managed processes
│       │   ├── attacher.py     # Discover & attach to existing processes
│       │   └── scanner.py      # Port scanning, PID lookup
│       ├── watch/
│       │   ├── __init__.py
│       │   ├── file_watcher.py # watchdog-based file monitoring
│       │   └── reload.py       # Stdout pattern matching for reload detection
│       ├── health/
│       │   ├── __init__.py
│       │   ├── checker.py      # HTTP & TCP health checks
│       │   └── verifier.py     # Active endpoint verification
│       ├── recovery/
│       │   ├── __init__.py
│       │   └── strategy.py     # Tiered recovery logic
│       ├── frameworks/
│       │   ├── __init__.py
│       │   └── registry.py     # Framework detection & profiles
│       └── state/
│           ├── __init__.py
│           └── store.py        # JSON state file read/write with file locking
├── tests/
│   ├── conftest.py
│   ├── test_cli.py
│   ├── test_process_manager.py
│   ├── test_attacher.py
│   ├── test_file_watcher.py
│   ├── test_health_checker.py
│   ├── test_recovery.py
│   ├── test_frameworks.py
│   └── test_changed.py         # Integration test for changed pipeline
└── README.md
```

### Dependencies
- `click` — CLI framework
- `watchdog` — file system events
- `httpx` — async HTTP for health checks
- `psutil` — cross-platform process inspection
- `pyyaml` — config file parsing
- `filelock` — safe concurrent state file access

**Distribution:** `pip install devpilot` / `pipx install devpilot`
**Python:** 3.10+

---

## Testing Strategy

**Unit tests** per module:
- `test_frameworks.py` — detection from command strings, profile loading, custom registration
- `test_process_manager.py` — spawn, kill, PID tracking, stdout capture (mock subprocesses)
- `test_attacher.py` — port-to-PID resolution, process name matching, degraded mode
- `test_file_watcher.py` — file pattern matching, change-to-service correlation
- `test_health_checker.py` — HTTP checks, TCP fallback, timeout handling
- `test_recovery.py` — tier classification, retry counting, backoff timing, escalation triggers
- `test_cli.py` — command parsing, JSON output format, exit codes

**Integration test** (`test_changed.py`):
1. Start a real minimal FastAPI app via `devpilot run`
2. Confirm healthy
3. Modify a source file
4. Call `devpilot changed <file>`
5. Assert reload detected, health confirmed, correct JSON
6. Introduce syntax error, call `changed` again
7. Assert `reload_failed` with error extracted

**Test fixtures:** Minimal FastAPI app and minimal Vite scaffold in `tests/fixtures/`.
**No mocking of state file** — tests use real temp-directory state files to catch serialization bugs.
