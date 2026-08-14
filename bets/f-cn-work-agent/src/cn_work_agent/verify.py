"""Multi-IM webhook verification helpers (Feishu / DingTalk / WeCom mocks)."""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Any, Mapping
from urllib.parse import parse_qs

from cn_work_agent.webhook import (
    sign_webhook_body as sign_callback_body,
    verify_webhook_signature as _verify_hmac_header,
)


class VerifyError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


PLATFORMS = ("feishu", "dingtalk", "wecom")


def _env(name: str) -> str | None:
    v = os.environ.get(name)
    return v if v else None


def env_feishu_verify_token() -> str | None:
    return _env("FEISHU_VERIFY_TOKEN")


def env_feishu_encrypt_key() -> str | None:
    return _env("FEISHU_ENCRYPT_KEY")


def env_dingtalk_token() -> str | None:
    return _env("DINGTALK_TOKEN")


def env_dingtalk_secret() -> str | None:
    return _env("DINGTALK_SECRET")


def env_wecom_token() -> str | None:
    return _env("WECOM_TOKEN")


def env_verify_token() -> str | None:
    """Back-compat alias for Feishu verify token."""
    return env_feishu_verify_token()


def env_encrypt_key() -> str | None:
    """Back-compat alias for Feishu encrypt key."""
    return env_feishu_encrypt_key()


def enabled_platforms(selected: list[str] | None = None) -> list[str]:
    """Return platforms that are enabled for serving.

    If selected is provided (CLI --platform), intersect with known platforms.
    Otherwise all three connectors are enabled (auth still optional / open mode).
    """
    if selected:
        out = [p for p in selected if p in PLATFORMS]
        return out or list(PLATFORMS)
    return list(PLATFORMS)


def _platform_ids_from_config(config: Mapping[str, Any] | None) -> list[str]:
    """IDs from config `platforms` list or object keys (order preserved)."""
    if not isinstance(config, dict):
        return []
    raw = config.get("platforms")
    out: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        pid = str(value or "").strip().lower()
        if pid and pid not in seen:
            seen.add(pid)
            out.append(pid)

    if isinstance(raw, dict):
        for key in raw.keys():
            add(key)
    elif isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, str):
                add(item)
            elif isinstance(item, dict):
                add(item.get("id") or item.get("platform"))
    return out


def configured_platform_ids(
    config: Mapping[str, Any] | None = None,
    enabled: list[str] | None = None,
) -> list[str]:
    """Known three first, then extras from config / enabled if already present."""
    ids: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        pid = str(value or "").strip().lower()
        if pid and pid not in seen:
            seen.add(pid)
            ids.append(pid)

    for p in PLATFORMS:
        add(p)
    for p in _platform_ids_from_config(config):
        add(p)
    if enabled:
        for p in enabled:
            add(p)
    return ids


def list_platforms(
    *,
    config: Mapping[str, Any] | None = None,
    enabled: list[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Public inventory JSON: id / enabled / hasCallbackSecret. Never secrets.

    Health still lists platform id strings; this is the product HTTP list.
    """
    if enabled is None:
        enabled_set = set(PLATFORMS)
    else:
        enabled_set = {str(p).strip().lower() for p in enabled if str(p).strip()}
    rows: list[dict[str, Any]] = []
    for pid in configured_platform_ids(config, enabled=list(enabled_set) if enabled is not None else None):
        secret = resolve_callback_secret(pid, env=env, config=config)
        rows.append(
            {
                "id": pid,
                "enabled": pid in enabled_set,
                "hasCallbackSecret": bool(secret),
            }
        )
    return {"ok": True, "count": len(rows), "platforms": rows}


def compute_signature(timestamp: str, nonce: str, encrypt_key: str, body: bytes) -> str:
    """Feishu/Lark event signature: sha256(timestamp + nonce + encrypt_key + body)."""
    raw = f"{timestamp}{nonce}{encrypt_key}".encode("utf-8") + body
    return hashlib.sha256(raw).hexdigest()


def compute_dingtalk_sign(timestamp: str, secret: str) -> str:
    """Simplified DingTalk robot-style sign: hex(hmac_sha256(secret, ts + '\\n' + secret))."""
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), string_to_sign, hashlib.sha256).hexdigest()


def compute_wecom_signature(token: str, timestamp: str, nonce: str, encrypt: str) -> str:
    """WeCom-like msg_signature: sha1(sort(token, timestamp, nonce, encrypt))."""
    pieces = sorted([token, timestamp, nonce, encrypt])
    return hashlib.sha1("".join(pieces).encode("utf-8")).hexdigest()


def _lower_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {str(k).lower(): v for k, v in headers.items()}


def verify_feishu(
    headers: Mapping[str, str],
    body: bytes,
    payload: dict[str, Any],
    *,
    verify_token: str | None = None,
    encrypt_key: str | None = None,
) -> None:
    token = verify_token if verify_token is not None else env_feishu_verify_token()
    key = encrypt_key if encrypt_key is not None else env_feishu_encrypt_key()

    if token:
        got = payload.get("token")
        if got is None:
            h = _lower_headers(headers)
            got = h.get("x-lark-token") or h.get("x-feishu-token")
        if got != token:
            raise VerifyError("bad_verify_token")

    if key:
        h = _lower_headers(headers)
        sig = h.get("x-lark-signature") or h.get("x-feishu-signature")
        ts = h.get("x-lark-request-timestamp") or h.get("x-feishu-request-timestamp") or ""
        nonce = h.get("x-lark-request-nonce") or h.get("x-feishu-request-nonce") or ""
        if not sig:
            raise VerifyError("missing_signature")
        expected = compute_signature(ts, nonce, key, body)
        if not hmac.compare_digest(str(sig), expected):
            raise VerifyError("bad_signature")


def verify_dingtalk(
    headers: Mapping[str, str],
    body: bytes,
    payload: dict[str, Any],
    *,
    token: str | None = None,
    secret: str | None = None,
) -> None:
    """DingTalk-like: DINGTALK_TOKEN in payload/header; optional timestamp+sign.

    Sign headers: X-DingTalk-Timestamp + X-DingTalk-Sign (or query timestamp/sign).
    """
    tok = token if token is not None else env_dingtalk_token()
    sec = secret if secret is not None else env_dingtalk_secret()

    if tok:
        h = _lower_headers(headers)
        got = payload.get("token") or payload.get("sessionWebhook")
        if got is None:
            got = h.get("x-dingtalk-token")
        # Also accept token nested under dingTalk style
        if got is None and isinstance(payload.get("chatbotCorpId"), str):
            got = payload.get("token")
        if got != tok:
            raise VerifyError("bad_verify_token")

    if sec:
        h = _lower_headers(headers)
        ts = h.get("x-dingtalk-timestamp") or ""
        sig = h.get("x-dingtalk-sign") or ""
        if not ts or not sig:
            raise VerifyError("missing_signature")
        expected = compute_dingtalk_sign(ts, sec)
        if not hmac.compare_digest(str(sig), expected):
            raise VerifyError("bad_signature")


def verify_wecom(
    headers: Mapping[str, str],
    body: bytes,
    payload: dict[str, Any],
    *,
    token: str | None = None,
    query: Mapping[str, str] | None = None,
) -> None:
    """WeCom-like: WECOM_TOKEN via msg_signature over timestamp/nonce/echostr|body."""
    tok = token if token is not None else env_wecom_token()
    if not tok:
        return

    q = dict(query or {})
    h = _lower_headers(headers)
    ts = q.get("timestamp") or h.get("x-wecom-timestamp") or ""
    nonce = q.get("nonce") or h.get("x-wecom-nonce") or ""
    sig = q.get("msg_signature") or h.get("x-wecom-signature") or ""
    echostr = q.get("echostr") or ""

    if not sig:
        raise VerifyError("missing_signature")

    if echostr:
        encrypt = echostr
    else:
        # POST: sign over plaintext body string (simplified mock; real WeCom uses Encrypt)
        encrypt = payload.get("Encrypt") or body.decode("utf-8", errors="replace")

    expected = compute_wecom_signature(tok, ts, nonce, encrypt)
    if not hmac.compare_digest(str(sig), expected):
        raise VerifyError("bad_signature")


def verify_request(
    headers: Mapping[str, str],
    body: bytes,
    payload: dict[str, Any],
    *,
    verify_token: str | None = None,
    encrypt_key: str | None = None,
) -> None:
    """Back-compat Feishu verify entrypoint used by smoke / older callers."""
    verify_feishu(
        headers,
        body,
        payload,
        verify_token=verify_token,
        encrypt_key=encrypt_key,
    )


def verify_platform(
    platform: str,
    headers: Mapping[str, str],
    body: bytes,
    payload: dict[str, Any],
    *,
    query: Mapping[str, str] | None = None,
) -> None:
    """Dispatch verification by platform. No-op when that platform's secrets unset."""
    if platform == "feishu":
        verify_feishu(headers, body, payload)
        return
    if platform == "dingtalk":
        verify_dingtalk(headers, body, payload)
        return
    if platform == "wecom":
        verify_wecom(headers, body, payload, query=query)
        return
    raise VerifyError(f"unknown_platform:{platform}")


def parse_query(path_with_query: str) -> dict[str, str]:
    """Parse query string from a request path into flat str->str map (first value)."""
    if "?" not in path_with_query:
        return {}
    qs = parse_qs(path_with_query.split("?", 1)[1], keep_blank_values=True)
    return {k: (v[0] if v else "") for k, v in qs.items()}


# --- Inbound IM approval-callback HMAC (POST /approvals/{id}/decide) ---
# Optional per-platform secret. Default off (unsigned POST still 200).
# MVP header: X-Callback-Signature: sha256=<hex> HMAC-SHA256 of raw body
# (same style as outbound X-Webhook-Signature). Optional X-Callback-Timestamp
# unix-seconds; reject if |now - ts| > 300s. GET decide is unsigned (demo cards).
# Feishu/DingTalk/WeCom adapters can copy this header in production later.
# Do not reuse IM webhook verify_token / encrypt_key / dingtalk.secret.

CALLBACK_SIGNATURE_HEADER = "X-Callback-Signature"
CALLBACK_TIMESTAMP_HEADER = "X-Callback-Timestamp"
CALLBACK_SKEW_SECONDS = 300
ENV_CALLBACK_GLOBAL = "APPROVAL_CALLBACK_SECRET"
ENV_CALLBACK_BY_PLATFORM = {
    "feishu": "FEISHU_CALLBACK_SECRET",
    "dingtalk": "DINGTALK_CALLBACK_SECRET",
    "wecom": "WECOM_CALLBACK_SECRET",
}
# HMAC secret keys only — never verify_token / encrypt_key / token / secret
# (those are IM inbound webhook auth and are set in local-mvp).
CALLBACK_SECRET_KEYS = (
    "callbackSecret",
    "callback_secret",
    "verificationToken",
    "verification_token",
    "appSecret",
    "app_secret",
)


def parse_callback_secret(raw: Any) -> str | None:
    if raw is None:
        return None
    secret = str(raw).strip()
    return secret or None


def _platform_block(config: Mapping[str, Any] | None, platform: str) -> dict[str, Any]:
    """feishu: {...} or platforms.feishu: {...} when platforms is an object."""
    if not isinstance(config, dict) or not platform:
        return {}
    plats = config.get("platforms")
    if isinstance(plats, dict):
        nested = plats.get(platform)
        if isinstance(nested, dict):
            if any(k in nested for k in CALLBACK_SECRET_KEYS):
                return nested
    top = config.get(platform)
    if isinstance(top, dict):
        return top
    if isinstance(plats, dict) and isinstance(plats.get(platform), dict):
        return plats[platform]  # type: ignore[index]
    return {}


def resolve_callback_secret(
    platform: str | None,
    *,
    env: Mapping[str, str] | None = None,
    config: Mapping[str, Any] | None = None,
) -> str | None:
    """Per-platform inbound decide HMAC secret. Default None (verification off).

    Precedence: per-platform env (`FEISHU_CALLBACK_SECRET` / …) if set
    (including empty) → global env `APPROVAL_CALLBACK_SECRET` if set →
    platform block `callbackSecret` / `callback_secret` / `verificationToken` /
    `appSecret` (top-level `feishu` or `platforms.feishu` object) → top-level
    `callbackSecret`. Does **not** read IM `verify_token` / `encrypt_key` /
    DingTalk `secret` / WeCom `token`.
    """
    plat = str(platform or "").strip().lower()
    environ = env if env is not None else os.environ
    env_name = ENV_CALLBACK_BY_PLATFORM.get(plat)
    if env_name and env_name in environ:
        return parse_callback_secret(environ.get(env_name, ""))
    if ENV_CALLBACK_GLOBAL in environ:
        return parse_callback_secret(environ.get(ENV_CALLBACK_GLOBAL, ""))
    block = _platform_block(config, plat)
    for key in CALLBACK_SECRET_KEYS:
        if key in block:
            return parse_callback_secret(block.get(key))
    if isinstance(config, dict):
        for key in ("callbackSecret", "callback_secret"):
            if key in config:
                return parse_callback_secret(config.get(key))
    return None


def _header_value(headers: Mapping[str, str] | None, name: str) -> str:
    if not headers:
        return ""
    want = name.lower()
    getter = getattr(headers, "get", None)
    if callable(getter):
        for candidate in (name, name.lower(), want):
            got = getter(candidate)
            if got not in (None, ""):
                return str(got).strip()
    try:
        items = headers.items()
    except Exception:
        return ""
    for k, v in items:
        if str(k).lower() == want:
            return str(v).strip()
    return ""


def verify_callback_signature(
    secret: str | None,
    raw_body: str | bytes | bytearray | None,
    header_value: str | None,
) -> bool:
    """Timing-safe check of `X-Callback-Signature: sha256=<hex>` vs raw body."""
    return _verify_hmac_header(secret, raw_body, header_value)


def callback_timestamp_ok(
    header_value: str | None,
    *,
    now: float | None = None,
    skew_seconds: int = CALLBACK_SKEW_SECONDS,
) -> bool:
    """True when timestamp omitted, or |now - ts| <= skew. False if unparseable/skewed."""
    raw = str(header_value or "").strip()
    if not raw:
        return True
    try:
        ts = int(raw)
    except (TypeError, ValueError):
        return False
    now_s = int(time.time() if now is None else now)
    try:
        window = int(skew_seconds)
    except (TypeError, ValueError):
        window = CALLBACK_SKEW_SECONDS
    if window < 0:
        window = CALLBACK_SKEW_SECONDS
    return abs(now_s - ts) <= window


def callback_auth_status(
    secret: str | None,
    raw_body: str | bytes | bytearray | None,
    headers: Mapping[str, str] | None,
    *,
    method: str = "POST",
    now: float | None = None,
    skew_seconds: int = CALLBACK_SKEW_SECONDS,
) -> tuple[int, str | None]:
    """Inbound decide auth. Returns (200, None) or (401, reason). Never returns the secret.

    GET (and non-POST) always 200 — IM card button URLs are unsigned.
    Missing/empty secret → 200 (unsigned POST still allowed).
    POST + secret: require `X-Callback-Signature`; optional `X-Callback-Timestamp`.
    """
    if str(method or "GET").upper() != "POST":
        return 200, None
    key = parse_callback_secret(secret)
    if not key:
        return 200, None
    sig = _header_value(headers, CALLBACK_SIGNATURE_HEADER)
    if not sig:
        return 401, "missing_signature"
    if not verify_callback_signature(key, raw_body, sig):
        return 401, "bad_signature"
    ts_raw = _header_value(headers, CALLBACK_TIMESTAMP_HEADER)
    if ts_raw and not callback_timestamp_ok(
        ts_raw, now=now, skew_seconds=skew_seconds
    ):
        return 401, "timestamp_skew"
    return 200, None


def verify_inbound_callback(
    secret: str | None,
    raw_body: str | bytes | bytearray | None,
    headers: Mapping[str, str] | None,
    *,
    method: str = "POST",
    now: float | None = None,
    skew_seconds: int = CALLBACK_SKEW_SECONDS,
) -> None:
    """Raise VerifyError on 401. No-op when secret unset or method is GET."""
    status, reason = callback_auth_status(
        secret,
        raw_body,
        headers,
        method=method,
        now=now,
        skew_seconds=skew_seconds,
    )
    if status == 200:
        return
    raise VerifyError(reason or "unauthorized")
