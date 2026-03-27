"""DevPilot MCP Server — expose devpilot tools to any MCP-compatible AI client."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from devpilot.config import load_config
from devpilot.frameworks.registry import FrameworkRegistry
from devpilot.health.checker import check_health
from devpilot.health.verifier import verify_endpoint
from devpilot.state.store import StateStore
from devpilot.supervisor import Supervisor
from devpilot.watch.file_watcher import match_file_to_services

mcp = FastMCP(
    "devpilot",
    instructions="Dev server supervisor for AI coders — manage dev server lifecycles, detect reloads, check health, and recover from crashes",
    host="0.0.0.0",
    port=int(os.environ.get("PORT", "8000")),
)

# --- Helpers ---


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


# --- Tools ---


@mcp.tool()
def devpilot_status(service_name: Optional[str] = None) -> dict:
    """Check the health status of dev server services.

    Returns live health check results for all registered services, or a specific
    service if named. Use this to verify servers are running and responsive.

    Args:
        service_name: Optional name of a specific service to check. If omitted, checks all services.
    """
    supervisor = _get_supervisor()
    return supervisor.get_status(service_name)


@mcp.tool()
def devpilot_changed(
    filepath: str,
    verify_endpoint: Optional[str] = None,
    timeout: float = 15,
) -> dict:
    """Report a file change and check if the dev server reloaded successfully.

    Call this AFTER editing a file to find out which service was affected,
    whether the reload succeeded, and if the server is healthy. This is the
    primary feedback loop for AI coders.

    Args:
        filepath: Path of the changed file (relative to project root).
        verify_endpoint: Optional endpoint to hit after reload (e.g. "/api/hello").
        timeout: Max seconds to wait for reload detection.
    """
    supervisor = _get_supervisor()
    return supervisor.handle_changed(filepath, verify_endpoint, timeout)


@mcp.tool()
def devpilot_run(
    name: str,
    cmd: str,
    port: Optional[int] = None,
    service_type: Optional[str] = None,
    health_endpoint: Optional[str] = None,
    file_patterns: Optional[list[str]] = None,
    reload_patterns: Optional[list[str]] = None,
) -> dict:
    """Start and manage a dev server process.

    DevPilot spawns the process, captures stdout, detects reload patterns,
    and monitors health. Use this instead of running dev servers directly.

    Args:
        name: Unique name for this service (e.g. "api", "frontend").
        cmd: Shell command to start the server (e.g. "uvicorn main:app --reload --port 8000").
        port: Port the server listens on. Auto-detected from framework if omitted.
        service_type: "backend" or "frontend". Auto-detected if omitted.
        health_endpoint: HTTP path for health checks (e.g. "/health"). Uses TCP check if omitted.
        file_patterns: Glob patterns for files this service watches (e.g. ["**/*.py"]).
        reload_patterns: Stdout patterns that indicate a successful reload.
    """
    supervisor = _get_supervisor()
    registry = FrameworkRegistry()
    profile = registry.detect(cmd)

    resolved_type = service_type or (profile.type if profile else "backend")
    resolved_port = port or (profile.default_port if profile else 8000)

    supervisor.run_service(
        name=name,
        cmd=cmd,
        port=resolved_port,
        type=resolved_type,
        health_endpoint=health_endpoint,
        file_patterns=file_patterns,
        reload_patterns=reload_patterns,
    )

    return {
        "started": name,
        "cmd": cmd,
        "port": resolved_port,
        "type": resolved_type,
        "framework": profile.name if profile else "unknown",
        "mode": "managed",
    }


@mcp.tool()
def devpilot_attach(
    name: str,
    port: int,
    service_type: Optional[str] = None,
    cmd: Optional[str] = None,
    health_endpoint: Optional[str] = None,
) -> dict:
    """Attach to an already-running dev server process for monitoring.

    DevPilot discovers the process by port and monitors health, but does NOT
    own or restart it. Use this when the server is started externally.

    Args:
        name: Unique name for this service.
        port: Port the existing server is listening on.
        service_type: "backend" or "frontend".
        cmd: Original command used to start the server (for reference).
        health_endpoint: HTTP path for health checks.
    """
    supervisor = _get_supervisor()
    success = supervisor.attach_service(
        name=name,
        port=port,
        type=service_type or "backend",
        cmd=cmd,
        health_endpoint=health_endpoint,
    )
    if not success:
        return {"error": f"No process found on port {port}"}
    return {"attached": name, "port": port, "mode": "attached"}


@mcp.tool()
def devpilot_stop(name: Optional[str] = None, stop_all: bool = False) -> dict:
    """Stop managed dev server services.

    Gracefully terminates processes. Only stops services that devpilot started
    (managed mode). Never kills processes it didn't start.

    Args:
        name: Name of a specific service to stop.
        stop_all: If true, stop all managed services.
    """
    supervisor = _get_supervisor()
    if stop_all:
        supervisor.stop_all()
        return {"stopped": "all"}
    elif name:
        supervisor.stop_service(name)
        return {"stopped": name}
    else:
        return {"error": "Specify a service name or set stop_all=true"}


@mcp.tool()
def devpilot_init() -> dict:
    """Auto-detect the project structure and generate a .devpilot.yaml config.

    Scans for pyproject.toml, requirements.txt, and package.json to detect
    frameworks (FastAPI, Flask, Django, Vite, Next.js, CRA) and generates
    appropriate configuration.
    """
    import yaml

    project_dir = _get_project_dir()
    services: dict = {}

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

    package_json = project_dir / "package.json"
    if package_json.exists():
        try:
            import json

            pkg = json.loads(package_json.read_text(encoding="utf-8"))
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
        return {"error": "No recognized project markers found. Create .devpilot.yaml manually."}

    config_data = {
        "services": services,
        "recovery": {"max_retries": 3, "backoff_seconds": [1, 3, 5]},
    }
    config_path = project_dir / ".devpilot.yaml"
    config_path.write_text(yaml.dump(config_data, default_flow_style=False), encoding="utf-8")

    return {"created": str(config_path), "services": list(services.keys())}


@mcp.tool()
def devpilot_up() -> dict:
    """Start all services defined in .devpilot.yaml.

    Reads the project configuration and starts each service under supervision.
    Equivalent to running each service with devpilot_run.
    """
    config = load_config(_get_project_dir())
    if config is None:
        return {"error": "No .devpilot.yaml found. Run devpilot_init first."}

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

    return {"started": started}


@mcp.tool()
def devpilot_log(service_name: Optional[str] = None) -> dict:
    """View recent devpilot events (restarts, crashes, recoveries).

    Args:
        service_name: Filter events to a specific service.
    """
    store = _get_store()
    state = store.read()
    entries = state.get("log", [])

    if service_name:
        entries = [e for e in entries if e.get("service") == service_name]

    return {"entries": entries}


@mcp.tool()
def devpilot_cleanup() -> dict:
    """Remove stale state entries for processes that are no longer running."""
    store = _get_store()
    removed = store.cleanup()
    return {"removed": removed}


@mcp.tool()
def devpilot_health_check(port: int, endpoint: Optional[str] = None) -> dict:
    """Perform a direct health check on a port.

    Useful for checking if a server is responding without going through the
    full devpilot service registration.

    Args:
        port: Port number to check.
        endpoint: HTTP endpoint path (e.g. "/health"). Uses TCP check if omitted.
    """
    result = check_health(port=port, endpoint=endpoint)
    return {
        "healthy": result.healthy,
        "status_code": result.status_code,
        "response_time_ms": round(result.response_time_ms, 1),
        "error": result.error,
    }


def main():
    """Entry point for the MCP server."""
    transport = os.environ.get("DEVPILOT_MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        mcp.run(transport="streamable-http")
    elif transport == "sse":
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
