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
