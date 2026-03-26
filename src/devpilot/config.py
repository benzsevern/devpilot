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
