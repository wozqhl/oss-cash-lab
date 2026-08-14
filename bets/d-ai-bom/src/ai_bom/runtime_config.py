"""Redacted public runtime config for GET /v1/config.

Mirrors C/E/F GET /v1/config allowlist — D serve is public like /v1/policy,
so the payload must be strictly non-secret. Knobs only (not the policy dump).
Never copy env/CLI/webhook/policy/exceptions wholesale.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from ai_bom.rate_limit import DEFAULT_RATE_LIMIT_PER_MINUTE
from ai_bom.webhook import parse_webhook_secret, parse_webhook_url

# JSON *keys* that must never appear (case-insensitive exact). hasSecret /
# hasUrl / hasPolicyFile are different keys and are allowed.
FORBIDDEN_RUNTIME_CONFIG_KEYS = (
    "webhookUrl",
    "webhook_url",
    "webhookSecret",
    "webhook_secret",
    "AI_BOM_WEBHOOK_URL",
    "AI_BOM_WEBHOOK_SECRET",
    "secret",
    "token",
    "Authorization",
    "authorization",
    "apiKey",
    "adminToken",
    "Bearer",
    "policy",
    "exceptions",
    "forbiddenLicenseIds",
    "forbiddenPatterns",
    "path",
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


def _scan_path_base(scan_path: Path | str | None) -> str | None:
    """Basename only — never a full host path that might leak user dirs."""
    if scan_path is None or scan_path == "":
        return None
    try:
        name = Path(scan_path).name
    except (TypeError, ValueError):
        return None
    name = str(name).strip()
    if not name or name in (".", ".."):
        return None
    if "/" in name or "\\" in name:
        return None
    return name


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
    rate_limit: int | None = ...,  # type: ignore[assignment]
    cors: Mapping[str, Any] | None = None,
    cors_origins: list[str] | None = None,
    watch: bool = False,
    scan_path: Path | str | None = None,
    has_policy_file: bool = False,
    webhook_url: str | None = None,
    webhook_secret: str | None = None,
) -> dict[str, Any]:
    """Allowlist-only public snapshot. Never spreads env, CORS, webhook, or policy.

    Returns camelCase keys: ok, rateLimit.perMinute, cors.origins, watch,
    scanPathBase (basename only), hasPolicyFile, webhooks.hasUrl/hasSecret.
    Webhook URL is never included (query tokens). Secrets are never included.
    Full policy JSON stays on GET /v1/policy. Exception file contents are omitted.
    """
    if rate_limit is ...:
        per_minute: int | None = DEFAULT_RATE_LIMIT_PER_MINUTE
    else:
        per_minute = _int_or_none(rate_limit)
        if per_minute is not None and per_minute <= 0:
            per_minute = None
    url = parse_webhook_url(webhook_url) if webhook_url else None
    secret = parse_webhook_secret(webhook_secret) if webhook_secret else None
    payload: dict[str, Any] = {
        "ok": True,
        "rateLimit": {"perMinute": per_minute},
        "cors": {"origins": _cors_origins(cors, cors_origins)},
        "watch": bool(watch),
        "hasPolicyFile": bool(has_policy_file),
        "webhooks": {
            "hasUrl": bool(url),
            "hasSecret": bool(secret),
        },
    }
    base = _scan_path_base(scan_path)
    if base is not None:
        payload["scanPathBase"] = base
    return payload
