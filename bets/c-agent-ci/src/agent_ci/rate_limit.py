"""In-memory sliding-window HTTP rate limit (client IP).

Mirrors bets/d-ai-bom/src/ai_bom/rate_limit.py (stdlib).
Identity: X-Forwarded-For first hop, else socket remote address.
"""
from __future__ import annotations

import math
import os
import threading
import time
from typing import Any, Mapping

DEFAULT_RATE_LIMIT_PER_MINUTE = 120
WINDOW_SECONDS = 60.0
ENV_RATE_LIMIT_PER_MINUTE = "RATE_LIMIT_PER_MINUTE"
ENV_RATE_LIMIT_RPM = "RATE_LIMIT_RPM"
RATE_LIMIT_SKIP_PATHS = frozenset({"/health", "/ready", "/metrics"})


def skip_rate_limit(path: str | None) -> bool:
    """k8s probes / Prometheus scrapes must never 429."""
    return (path or "/") in RATE_LIMIT_SKIP_PATHS


def _parse_limit(raw: Any) -> tuple[bool, int | None]:
    """
    Parse a limit value.

    Returns (present, value). value None means unlimited (<=0).
    present False means the raw value was missing/empty/unparseable.
    """
    if raw is None or raw == "":
        return False, None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return False, None
    if n <= 0:
        return True, None
    return True, n


def resolve_rate_limit(
    cli_value: Any = None,
    env: Mapping[str, str] | None = None,
) -> int | None:
    """
    CLI `--rate-limit` wins when provided (including 0 = unlimited).
    Else env RATE_LIMIT_PER_MINUTE (F), else RATE_LIMIT_RPM, else 120.
    None means unlimited.
    """
    present, val = _parse_limit(cli_value)
    if present:
        return val
    environ = env if env is not None else os.environ
    present, val = _parse_limit(environ.get(ENV_RATE_LIMIT_PER_MINUTE))
    if present:
        return val
    present, val = _parse_limit(environ.get(ENV_RATE_LIMIT_RPM))
    if present:
        return val
    return DEFAULT_RATE_LIMIT_PER_MINUTE


class SlidingWindowRateLimiter:
    """Thread-safe sliding window: key → timestamps within the last 60s."""

    def __init__(self, window_seconds: float = WINDOW_SECONDS) -> None:
        self.window = float(window_seconds)
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = {}

    def check(self, key: str, limit: int | None, now: float | None = None) -> tuple[bool, int]:
        """
        Record a hit if under limit.

        Returns (allowed, retry_after_seconds).
        limit None or <=0 → always allowed.
        """
        if limit is None or limit <= 0:
            return True, 0
        ts = time.time() if now is None else float(now)
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if t > ts - self.window]
            if len(hits) >= limit:
                oldest = hits[0]
                retry_after = max(1, int(math.ceil(oldest + self.window - ts)))
                self._hits[key] = hits
                return False, retry_after
            hits.append(ts)
            self._hits[key] = hits
            return True, 0

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()


def client_ip_from_headers(
    headers: Mapping[str, str] | None,
    *,
    remote: str | None = None,
) -> str:
    """Best-effort client IP (X-Forwarded-For first hop, else remote)."""
    xff = None
    if headers is not None:
        getter = getattr(headers, "get", None)
        if callable(getter):
            xff = getter("X-Forwarded-For") or getter("x-forwarded-for")
    if xff:
        hop = str(xff).split(",")[0].strip()
        if hop:
            return hop
    if remote:
        return str(remote)
    return "unknown"


def client_ip_from_handler(handler: Any) -> str:
    """Best-effort client IP (X-Forwarded-For first hop, else socket)."""
    remote = None
    try:
        remote = str(handler.client_address[0])
    except Exception:
        remote = None
    headers = getattr(handler, "headers", None)
    return client_ip_from_headers(headers, remote=remote)
