"""Redacted public runtime config for GET /v1/config.

Mirrors B GET /admin/config and F GET /v1/config allowlist — C serve is
typically token-gated for POST /v1/runs, but this GET is public like
/v1/suites iff no secrets leak. Never copy env/CLI/webhook wholesale.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from agent_ci.rate_limit import DEFAULT_RATE_LIMIT_PER_MINUTE
from agent_ci.webhook import parse_webhook_secret, parse_webhook_url

# Mirror serve.py defaults (do not import serve — circular).
DEFAULT_MAX_QUEUE = 16
DEFAULT_RUNS_MAX = 1000

# JSON *keys* that must never appear (case-insensitive exact). hasSecret /
# hasUrl are different keys and are allowed.
FORBIDDEN_RUNTIME_CONFIG_KEYS = (
    "webhookUrl",
    "webhook_url",
    "webhookSecret",
    "webhook_secret",
    "AGENT_CI_WEBHOOK_URL",
    "AGENT_CI_WEBHOOK_SECRET",
    "secret",
    "token",
    "Authorization",
    "authorization",
    "apiKey",
    "adminToken",
    "Bearer",
    "fixtures",
)

FORBIDDEN_KEY_SET = {k.lower() for k in FORBIDDEN_RUNTIME_CONFIG_KEYS}

# Fixture / shape needles that must be absent from the JSON dump (smoke).
# Do not use short substrings that match allowlisted keys (e.g. "Secret" vs hasSecret).
RUNTIME_CONFIG_SECRET_NEEDLES = (
    "whsec_must_not_leak",
    "planted_url_token",
    "http_url_token_must_not_leak",
    "http_whsec_must_not_leak",
    "sk-",
    "Bearer ",
    "webhookUrl",
    "webhookSecret",
    "webhook_url",
    "webhook_secret",
    "Authorization",
)


def _cors_origins(
    cors: Mapping[str, Any] | None,
    cors_origins: list[str] | None,
) -> list[str]:
    if cors_origins is not None:
        return [str(o).strip() for o in cors_origins if str(o).strip()]
    if not cors:
        return []
    if cors.get("allow_any") or cors.get("allowAny"):
        return ["*"]
    raw = cors.get("origins")
    if isinstance(raw, (list, tuple)):
        return [str(o).strip() for o in raw if str(o).strip()]
    return []


def _int_or_none(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _queue_snapshot(
    queue: Mapping[str, Any] | None,
    *,
    max_queue: int | None,
) -> dict[str, int]:
    """Allowlist only: max + cheap current depth. Never copy the queue object."""
    qmax = _int_or_none(max_queue)
    queued = 0
    running = 0
    if isinstance(queue, dict):
        if qmax is None:
            qmax = _int_or_none(queue.get("maxQueue"))
            if qmax is None:
                qmax = _int_or_none(queue.get("max"))
        try:
            queued = int(queue.get("queued") or 0)
        except (TypeError, ValueError):
            queued = 0
        try:
            running = int(queue.get("running") or 0)
        except (TypeError, ValueError):
            running = 0
    if qmax is None:
        qmax = DEFAULT_MAX_QUEUE
    return {"max": int(qmax), "queued": queued, "running": running}


def collect_forbidden_runtime_config_keys(value: Any, path: str = "$") -> list[str]:
    """Walk JSON keys; return paths whose names are forbidden."""
    hits: list[str] = []

    def walk(v: Any, p: str) -> None:
        if v is None:
            return
        if isinstance(v, list):
            for i, item in enumerate(v):
                walk(item, f"{p}[{i}]")
            return
        if isinstance(v, dict):
            for k, child in v.items():
                if str(k).lower() in FORBIDDEN_KEY_SET:
                    hits.append(f"{p}.{k}")
                walk(child, f"{p}.{k}")

    walk(value, path)
    return hits


def runtime_config_leak_needles(payload: Any) -> list[str]:
    dump = json.dumps(payload, ensure_ascii=False)
    return [n for n in RUNTIME_CONFIG_SECRET_NEEDLES if n in dump]


def assert_runtime_config_safe(payload: Any) -> dict[str, Any]:
    """True when payload has no forbidden keys and no secret needles."""
    keys = collect_forbidden_runtime_config_keys(payload)
    leaks = runtime_config_leak_needles(payload)
    return {"ok": (not keys) and (not leaks), "keys": keys, "leaks": leaks}


def summarize_runtime_config(
    *,
    queue: Mapping[str, Any] | None = None,
    max_queue: int | None = None,
    fail_under: float | None = None,
    cors: Mapping[str, Any] | None = None,
    cors_origins: list[str] | None = None,
    rate_limit: int | None = ...,  # type: ignore[assignment]
    runs_max: int | None = None,
    webhook_url: str | None = None,
    webhook_secret: str | None = None,
    suites_count: int | None = None,
) -> dict[str, Any]:
    """Allowlist-only public snapshot. Never spreads env, CORS, or webhook.

    Returns camelCase keys matching B/F: queue.max, failUnder, rateLimit,
    cors.origins, runsMax, webhooks.hasUrl/hasSecret, suitesCount.
    Webhook URL is never included (query tokens). Secrets are never included.
    There is no serve-level failUnder default — key is null when unset.
    """
    if rate_limit is ...:
        per_minute: int | None = DEFAULT_RATE_LIMIT_PER_MINUTE
    else:
        per_minute = _int_or_none(rate_limit)
        if per_minute is not None and per_minute <= 0:
            per_minute = None
    cap = DEFAULT_RUNS_MAX if runs_max is None else runs_max
    try:
        cap_i = int(cap)
    except (TypeError, ValueError):
        cap_i = DEFAULT_RUNS_MAX
    url = parse_webhook_url(webhook_url) if webhook_url else None
    secret = parse_webhook_secret(webhook_secret) if webhook_secret else None
    count = 0 if suites_count is None else suites_count
    try:
        count_i = int(count)
    except (TypeError, ValueError):
        count_i = 0
    return {
        "ok": True,
        "queue": _queue_snapshot(queue, max_queue=max_queue),
        "failUnder": fail_under,
        "rateLimit": {"perMinute": per_minute},
        "cors": {"origins": _cors_origins(cors, cors_origins)},
        "runsMax": cap_i,
        "webhooks": {
            "hasUrl": bool(url),
            "hasSecret": bool(secret),
        },
        "suitesCount": count_i,
    }
