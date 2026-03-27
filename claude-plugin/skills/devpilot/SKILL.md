---
name: devpilot
description: Dev server supervisor for AI coders — manages process lifecycles, detects reloads, checks health, and recovers from crashes with structured JSON output
---

# devpilot — Dev Server Supervisor for AI Coders

## When This Skill Applies

Use devpilot when you encounter ANY of these situations:
- Dev server crashed or stopped responding
- Hot reload failed or is stuck
- Port conflict (address already in use)
- Zombie processes holding ports
- You're about to kill processes or rotate ports — STOP, use devpilot instead
- User is running a dev server and you're editing files
- You need to verify that your code changes were picked up by the dev server

## Install

**Preferred — MCP server (no local install):**
```bash
claude mcp add devpilot --transport http https://devpilot--benzsevern.run.tools
```

**Local CLI:**
```bash
pip install devpilot-ai
```

**Local MCP server (stdio):**
```bash
pip install "devpilot-ai[mcp]"
claude mcp add devpilot -- devpilot-mcp
```

## Core Workflow for AI Coders

### Step 1: Check if devpilot is available
If using MCP, the devpilot tools are already available. If using CLI:
```bash
devpilot --help
```
If not installed, install it: `pip install devpilot-ai`

### Step 2: Initialize the project (first time)
```bash
devpilot init
```
This auto-detects frameworks and generates `.devpilot.yaml`.

### Step 3: Start or attach to the dev server

**If you're starting the server:**
```bash
devpilot run api "uvicorn main:app --reload --port 8000"
```

**If the server is already running:**
```bash
devpilot attach api --port 8000
```

### Step 4: After editing files, check the result
```bash
devpilot changed src/main.py
```

**Read the JSON output:**
- `"reload": "reloaded"` + `"healthy": true` → your changes are live, continue
- `"reload": "reload_failed"` → code error, check the `error` field, fix it
- `"reload": "timeout"` → server is slow, wait and retry
- `"healthy": false` → server is down, check `devpilot status`

### Step 5: Check overall health
```bash
devpilot status
```

## CRITICAL RULES

1. **NEVER kill processes you didn't start.** Use `devpilot stop` for managed services only.
2. **NEVER rotate ports randomly.** If there's a port conflict, `devpilot` handles it with its recovery strategy.
3. **NEVER run `kill -9` or `taskkill /F` on dev servers.** Use `devpilot stop <name>` instead.
4. **ALWAYS check `devpilot changed <file>` after editing code** before assuming the server reloaded.
5. **If devpilot reports an escalation**, read the suggestion — it's telling you what a human should decide.

## Commands Reference

| Command | When to Use |
|---------|------------|
| `devpilot init` | First time in a project — generates config |
| `devpilot run <name> <cmd>` | Start a new dev server under supervision |
| `devpilot attach <name> --port N` | Monitor an existing server (don't own it) |
| `devpilot status [name]` | Check health of all or one service |
| `devpilot changed <filepath>` | After editing a file — get reload + health status |
| `devpilot stop [name] [--all]` | Gracefully stop managed services |
| `devpilot restart <name>` | Restart a managed service |
| `devpilot up` | Start all services from `.devpilot.yaml` |
| `devpilot down` | Stop all services |
| `devpilot log` | View recent events and recovery actions |
| `devpilot cleanup` | Remove stale state and dead PIDs |

## Supported Frameworks (auto-detected)

- FastAPI/Uvicorn (port 8000)
- Flask (port 5000)
- Django (port 8000)
- Vite (port 5173)
- Next.js (port 3000)
- Create React App (port 3000)

Custom frameworks can be added in `.devpilot.yaml` under `custom_frameworks`.

## Recovery Tiers

devpilot uses tiered recovery — it escalates, never panics:

| Tier | What Happens | Example |
|------|-------------|---------|
| **Silent** | Auto-restart with backoff, no user action needed | Process crashed once, restarting in 1s |
| **Report** | Auto-recover + tell you what happened | 3rd crash in a row, reassigning port |
| **Escalate** | Stop and explain — YOU decide | Unknown process on the port, code has syntax errors |

## Example `.devpilot.yaml`

```yaml
services:
  api:
    cmd: "uvicorn main:app --reload --port 8000"
    port: 8000
    health: /health
    file_patterns:
      - "src/**/*.py"
      - "app/**/*.py"
  frontend:
    cmd: "npm run dev"
    port: 3000
    file_patterns:
      - "src/**/*.tsx"
      - "src/**/*.css"

recovery:
  max_retries: 3
  backoff_seconds: [1, 3, 5]
```

## Troubleshooting

**"devpilot: command not found"**
→ Install with `pip install devpilot-ai` or `pipx install devpilot`

**Port conflict on start**
→ `devpilot` auto-detects and reassigns if the framework supports `--port`. Otherwise it tells you what's holding the port.

**Attached service crashed**
→ devpilot can't restart what it didn't start. It reports the crash with a suggestion to switch to managed mode (`devpilot run` instead of `attach`).

**All services down**
→ `devpilot cleanup` to clear stale state, then `devpilot up` to restart from config.
