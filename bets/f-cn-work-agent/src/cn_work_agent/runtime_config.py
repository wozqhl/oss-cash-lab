"""Redacted public runtime config for GET /v1/config.

Mirrors B GET /admin/config allowlist — F has no admin token on this GET,
so the payload must be strictly non-secret. Never copy config/env wholesale.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from cn_work_agent.approvals import DEFAULT_APPROVALS_MAX
from cn_work_agent.rate_limit import DEFAULT_RATE_LIMIT_PER_MINUTE
from cn_work_agent.verify import list_platforms
from cn_work_agent.webhook import parse_webhook_secret, parse_webhook_url

# JSON *keys* that must never appear (case-insensitive exact). hasCallbackSecret /
# hasSecret / hasUrl are different keys and are allowed.
FORBIDDEN_RUNTIME_CONFIG_KEYS = (
    "callbackSecret",
    "callback_secret",
    "webhookSecret",
    "webhook_secret",
    "approval_webhook_secret",
    "approval_webhook_url",
    "webhookUrl",
    "webhook_url",
    "secret",
    "token",
    "Authorization",
    "authorization",
    "verify_token",
    "encrypt_key",
    "appSecret",
    "verificationToken",
    "apiKey",
    "adminToken",
    "FEISHU_VERIFY_TOKEN",
    "FEISHU_ENCRYPT_KEY",
    "FEISHU_CALLBACK_SECRET",
    "DINGTALK_TOKEN",
    "DINGTALK_SECRET",
    "DINGTALK_CALLBACK_SECRET",
    "WECOM_TOKEN",
    "WECOM_CALLBACK_SECRET",
    "APPROVAL_CALLBACK_SECRET",
    "APPROVAL_WEBHOOK_SECRET",
    "APPROVAL_WEBHOOK_URL",
)

FORBIDDEN_KEY_SET = {k.lower() for k in FORBIDDEN_RUNTIME_CONFIG_KEYS}

# Fixture / shape needles that must be absent from the JSON dump (smoke).
# Do not use short substrings that match allowlisted keys (e.g. "Secret" vs hasSecret).
RUNTIME_CONFIG_SECRET_NEEDLES = (
    "cbsec_must_not_leak",
    "tok_must_not_leak",
    "enc_must_not_leak",
    "dt-tok-must-not-leak",
    "dt-secret-must-not-leak",
    "wc-tok-must-not-leak",
    "whsec_must_not_leak",
    "planted_url_token",
    "http_url_token_must_not_leak",
    "http_whsec_must_not_leak",
    "http_cbsec_must_not_leak",
    "http_tok_must_not_leak",
    "http_enc_must_not_leak",
    "http_dt_tok",
    "http_dt_secret",
    "http_wc_tok",
    "sk-",
    "Bearer ",
    "callbackSecret",
    "encrypt_key",
    "verify_token",
)


def _cors_origins(
    cors: Mapping[str, Any] | None,
    cors_origins: list[str] | None,
) -> list[str]:
    if cors_origins is not None:
        return [str(o).strip() for o in cors_origins if str(o).strip()]
    if not cors:
        return []
    raw = cors.get("origins")
    if isinstance(raw, (list, tuple)):
        return [str(o).strip() for o in raw if str(o).strip()]
    if cors.get("allow_any") or cors.get("allowAny"):
        return ["*"]
    return []


def _rate_limit(rate_limits: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(rate_limits, dict) or not rate_limits:
        return {"perMinute": DEFAULT_RATE_LIMIT_PER_MINUTE}
    return {"perMinute": rate_limits.get("_default")}


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
    approval_ttl_seconds: int | None = None,
    rate_limits: Mapping[str, Any] | None = None,
    cors: Mapping[str, Any] | None = None,
    cors_origins: list[str] | None = None,
    webhook_url: str | None = None,
    webhook_secret: str | None = None,
    approvals_max: int | None = None,
    config: Mapping[str, Any] | None = None,
    enabled: list[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Allowlist-only public snapshot. Never spreads config or env.

    Returns camelCase keys matching B admin-config: approvalTtlSec, rateLimit,
    cors.origins, approvalsMax, webhooks.hasUrl/hasSecret, platforms.
    Webhook URL is never included (query tokens). Secrets are never included.
    """
    plat = list_platforms(config=config, enabled=enabled, env=env)
    cap = DEFAULT_APPROVALS_MAX if approvals_max is None else approvals_max
    try:
        cap_i = int(cap)
    except (TypeError, ValueError):
        cap_i = DEFAULT_APPROVALS_MAX
    url = parse_webhook_url(webhook_url) if webhook_url else None
    secret = parse_webhook_secret(webhook_secret) if webhook_secret else None
    return {
        "ok": True,
        "approvalTtlSec": approval_ttl_seconds,
        "rateLimit": _rate_limit(rate_limits),
        "cors": {"origins": _cors_origins(cors, cors_origins)},
        "approvalsMax": cap_i,
        "webhooks": {
            "hasUrl": bool(url),
            "hasSecret": bool(secret),
        },
        "platforms": list(plat.get("platforms") or []),
    }
