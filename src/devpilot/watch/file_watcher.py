"""File-to-service mapping using glob patterns."""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import PurePosixPath


def _glob_match(filepath: str, pattern: str) -> bool:
    """Match a file path against a glob pattern, supporting ** for recursive."""
    # fnmatch doesn't handle ** (recursive), so handle it explicitly
    if "**" in pattern:
        # PurePosixPath.match handles ** correctly in Python 3.12+
        # For broader compat, split on ** and check parts
        parts = pattern.split("**")
        if len(parts) == 2:
            prefix, suffix = parts
            # Strip leading/trailing slashes from the split
            suffix = suffix.lstrip("/")
            # ** matches any path depth, so just check the suffix
            if prefix and not filepath.startswith(prefix.rstrip("/")):
                return False
            return fnmatch(filepath, f"*{suffix}") or fnmatch(
                filepath.rsplit("/", 1)[-1] if "/" in filepath else filepath,
                suffix,
            )
    return fnmatch(filepath, pattern)


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
            if _glob_match(normalized, pattern):
                matches.append(svc_id)
                break

    return matches
