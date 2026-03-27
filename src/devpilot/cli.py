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


def _fix_msys_path(value: str | None) -> str | None:
    """Fix MSYS/Git Bash path expansion on Windows.

    Git Bash converts CLI args like /health to C:/Program Files/Git/health.
    Detect and reverse this so health endpoints stay as /health.
    """
    if value is None:
        return None
    # MSYS expands /foo to C:/Program Files/Git/foo (or similar drive letters)
    import re
    m = re.match(r'^[A-Z]:/(?:Program Files(?:/Git)?|usr|mingw\d*)(/.*)$', value, re.IGNORECASE)
    if m:
        return m.group(1)
    return value


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

    health = _fix_msys_path(health)
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
    health = _fix_msys_path(health)
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
    verify_endpoint = _fix_msys_path(verify_endpoint)
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
