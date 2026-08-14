"""In-memory sliding-window rate limit for webhook routes (IP + platform)."""
from __future__ import annotations

import math
import os
import threading
import time
from typing import Any


DEFAULT_RATE_LIMIT_PER_MINUTE = 60
WINDOW_SECONDS = 60.0

_PLATFORM_ENV = {
    "feishu": "RATE_LIMIT_FEISHU_PER_MINUTE",
    "dingtalk": "RATE_LIMIT_DINGTALK_PER_MINUTE",
    "wecom": "RATE_LIMIT_WECOM_PER_MINUTE",
}


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


def resolve_rate_limits(config: dict[str, Any] | None = None) -> dict[str, int | None]:
    """
    Resolve per-platform limits.

    Priority (highest first):
      per-platform env → per-platform config → RATE_LIMIT_PER_MINUTE env
      → config.rate_limit_per_minute → default 60

    Returns mapping platform → limit (int) or None (unlimited), plus `_default`.
    """
    cfg = config or {}

    # Global base
    present, base = _parse_limit(os.environ.get("RATE_LIMIT_PER_MINUTE"))
    if not present:
        present, base = _parse_limit(cfg.get("rate_limit_per_minute"))
    if not present:
        base = DEFAULT_RATE_LIMIT_PER_MINUTE

    out: dict[str, int | None] = {"_default": base}
    for plat in ("feishu", "dingtalk", "wecom"):
        env_name = _PLATFORM_ENV[plat]
        present, val = _parse_limit(os.environ.get(env_name))
        if present:
            out[plat] = val
            continue
        plat_cfg = cfg.get(plat) if isinstance(cfg.get(plat), dict) else {}
        present, val = _parse_limit(
            plat_cfg.get("rate_limit_per_minute") if plat_cfg else None
        )
        if present:
            out[plat] = val
        else:
            out[plat] = base
    return out


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


def client_ip_from_handler(handler: Any) -> str:
    """Best-effort client IP (X-Forwarded-For first hop, else socket)."""
    xff = None
    try:
        xff = handler.headers.get("X-Forwarded-For") or handler.headers.get("x-forwarded-for")
    except Exception:
        xff = None
    if xff:
        hop = str(xff).split(",")[0].strip()
        if hop:
            return hop
    try:
        return str(handler.client_address[0])
    except Exception:
        return "unknown"


def rate_limit_key(ip: str, platform: str) -> str:
    return f"{ip}:{platform}"
