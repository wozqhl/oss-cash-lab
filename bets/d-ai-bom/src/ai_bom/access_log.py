"""Structured JSON HTTP access logs (opt-in). Default off so stack-demo greps stay stable."""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Mapping
from urllib.parse import urlparse

ENV_LOG_FORMAT = "LOG_FORMAT"
SKIP_ACCESS_LOG_PATHS = ("/metrics", "/health", "/ready")


def resolve_log_json(cli_value: bool | None, env: Mapping[str, str] | None = None) -> bool:
    """CLI `--log-json` wins when provided; else env LOG_FORMAT=json. Default off."""
    if cli_value is True:
        return True
    if cli_value is False:
        return False
    environ = env if env is not None else os.environ
    return str(environ.get(ENV_LOG_FORMAT, "")).strip().lower() == "json"


def should_skip_access_log(method: str | None, path: str | None) -> bool:
    if str(method or "").upper() == "OPTIONS":
        return True
    p = str(path or "")
    q = p.find("?")
    if q >= 0:
        p = p[:q]
    return p in SKIP_ACCESS_LOG_PATHS


def format_access_log(
    *,
    service: str,
    method: str,
    path: str,
    status: int,
    duration_ms: float | int,
    request_id: str,
    ts: str | None = None,
    bytes_out: int | None = None,
    remote: str | None = None,
) -> str:
    """One compact JSON object (no trailing newline). No headers/bodies/secrets."""
    from datetime import datetime, timezone

    rec: dict[str, Any] = {
        "ts": ts or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "level": "info",
        "msg": "http",
        "service": service or "",
        "method": str(method or "GET").upper(),
        "path": path or "/",
        "status": int(status or 0),
        "durationMs": int(duration_ms) if not isinstance(duration_ms, bool) else 0,
        "requestId": "" if request_id is None else str(request_id),
    }
    if bytes_out is not None:
        rec["bytesOut"] = int(bytes_out)
    if remote:
        rec["remote"] = str(remote)
    return json.dumps(rec, separators=(",", ":"), ensure_ascii=False)


def write_access_log_line(line: str) -> None:
    s = line if str(line).endswith("\n") else f"{line}\n"
    try:
        sys.stdout.write(s)
        sys.stdout.flush()
    except OSError:
        pass


def emit_access_log(
    handler: Any,
    *,
    service: str,
    status: int,
    bytes_out: int | None = None,
    enabled: bool | None = None,
) -> None:
    """Emit one access line for a completed request. Skip probes / OPTIONS."""
    if enabled is None:
        enabled = bool(
            getattr(handler, "log_json", False)
            or getattr(getattr(handler, "server", None), "log_json", False)
        )
    if not enabled:
        return
    method = str(getattr(handler, "command", None) or "GET").upper()
    parsed = urlparse(getattr(handler, "path", "/") or "/")
    path = parsed.path or "/"
    if should_skip_access_log(method, path):
        return
    t0 = getattr(handler, "_access_t0", None)
    if t0 is None:
        duration_ms = 0
    else:
        duration_ms = max(0, int(round((time.perf_counter() - t0) * 1000)))
    request_id = ""
    resolve = getattr(handler, "_resolve_request_id", None)
    if callable(resolve):
        try:
            request_id = str(resolve() or "")
        except Exception:
            request_id = ""
    remote = ""
    try:
        addr = getattr(handler, "client_address", None)
        if addr:
            remote = str(addr[0])
    except Exception:
        remote = ""
    write_access_log_line(
        format_access_log(
            service=service,
            method=method,
            path=path,
            status=status,
            duration_ms=duration_ms,
            request_id=request_id,
            bytes_out=bytes_out,
            remote=remote or None,
        )
    )


def mark_access_start(handler: Any) -> None:
    handler._access_t0 = time.perf_counter()
