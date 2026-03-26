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
