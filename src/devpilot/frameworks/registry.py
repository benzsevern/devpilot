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
        reload_patterns=["Reloading..."],
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
