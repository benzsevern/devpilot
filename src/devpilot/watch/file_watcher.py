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
