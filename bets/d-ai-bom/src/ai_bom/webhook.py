"""Optional policy-hit webhook (fire-and-forget; stdlib urllib).

OSS: best-effort POST after scan when forbidden patterns or forbidden licenses
would fail --strict. Optional simple HMAC-SHA256 (`--webhook-secret` /
AI_BOM_WEBHOOK_SECRET) → `X-Webhook-Signature: sha256=<hex>` of the raw JSON
body. Always sends `X-Webhook-Timestamp: <unix-seconds>` (HMAC still body-only).
OSS: one retry after ~50ms on 5xx or network/timeout (first-try success
= no retry; 4xx do not retry). Exponential backoff / queues = paid.
Key rotation / timestamp replay window enforcement = paid later.
"""
from __future__ import annotations

import hashlib
import hmac
import time
import json
import os
import urllib.error
import urllib.request
from typing import Any, Mapping

ENV_WEBHOOK_URL = "AI_BOM_WEBHOOK_URL"
ENV_WEBHOOK_SECRET = "AI_BOM_WEBHOOK_SECRET"
DEFAULT_TIMEOUT_S = 0.75
DEFAULT_RETRY_DELAY_S = 0.05
USER_AGENT = "ai-bom-webhook/0.1.0"
SIGNATURE_HEADER = "X-Webhook-Signature"
TIMESTAMP_HEADER = "X-Webhook-Timestamp"


def webhook_unix_seconds(now: float | None = None) -> int:
    """Floor unix seconds. Optional `now` (epoch seconds) for tests."""
    tval = time.time() if now is None else float(now)
    return int(tval)


def parse_webhook_url(raw: str | None) -> str | None:
    if raw is None:
        return None
    url = str(raw).strip()
    return url or None


def resolve_webhook_url(
    cli_value: str | None,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """CLI `--webhook-url` wins when provided (including empty); else env."""
    if cli_value is not None:
        return parse_webhook_url(cli_value)
    environ = env if env is not None else os.environ
    return parse_webhook_url(environ.get(ENV_WEBHOOK_URL, ""))


def parse_webhook_secret(raw: str | None) -> str | None:
    if raw is None:
        return None
    secret = str(raw).strip()
    return secret or None


def resolve_webhook_secret(
    cli_value: str | None,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """CLI `--webhook-secret` wins when provided (including empty); else env."""
    if cli_value is not None:
        return parse_webhook_secret(cli_value)
    environ = env if env is not None else os.environ
    return parse_webhook_secret(environ.get(ENV_WEBHOOK_SECRET, ""))


def _raw_bytes(raw_body: str | bytes | bytearray | None) -> bytes:
    if raw_body is None:
        return b""
    if isinstance(raw_body, (bytes, bytearray)):
        return bytes(raw_body)
    return str(raw_body).encode("utf-8")


def sign_webhook_body(secret: str, raw_body: str | bytes | bytearray | None) -> str:
    """HMAC-SHA256 of the raw POST body → `sha256=<hex>`."""
    key = str(secret).encode("utf-8")
    digest = hmac.new(key, _raw_bytes(raw_body), hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_webhook_signature(
    secret: str | None,
    raw_body: str | bytes | bytearray | None,
    header_value: str | None,
) -> bool:
    """Timing-safe check of `X-Webhook-Signature: sha256=<hex>` vs raw body.

    Hex compared case-insensitively. Missing/empty secret or header → False.
    """
    key = parse_webhook_secret(secret)
    if not key:
        return False
    got = str(header_value or "").strip()
    if not got:
        return False
    expected = sign_webhook_body(key, raw_body)
    a = expected.encode("utf-8")
    b = got.lower().encode("utf-8")
    if len(a) != len(b):
        return False
    return hmac.compare_digest(a, b)


def should_retry_webhook(
    *,
    status: int | None = None,
    error: BaseException | None = None,
) -> bool:
    """OSS: 5xx or thrown network/timeout → retry once. 2xx / 4xx → no retry."""
    if error is not None:
        return True
    if status is None:
        return False
    try:
        n = int(status)
    except (TypeError, ValueError):
        return False
    return 500 <= n <= 599


def _drain_body(resp: Any) -> None:
    try:
        read = getattr(resp, "read", None)
        if callable(read):
            read()
    except Exception:
        pass


def _http_status(resp: Any) -> int:
    code = getattr(resp, "status", None)
    if code is None:
        code = getattr(resp, "code", None)
    try:
        return int(code)
    except (TypeError, ValueError):
        return 0


def _post_once(
    url: str,
    data: bytes,
    headers: Mapping[str, str],
    timeout: float,
    urlopen_fn: Any = None,
) -> int:
    opener = urlopen_fn if callable(urlopen_fn) else urllib.request.urlopen
    req = urllib.request.Request(url, data=data, method="POST", headers=dict(headers))
    try:
        resp = opener(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        _drain_body(e)
        try:
            return int(e.code)
        except (TypeError, ValueError):
            return 0
    if hasattr(resp, "__enter__") and hasattr(resp, "__exit__"):
        with resp as r:
            _drain_body(r)
            return _http_status(r)
    _drain_body(resp)
    return _http_status(resp)


def _retry_delay_s(retry_delay: float | None) -> float:
    if isinstance(retry_delay, (int, float)) and retry_delay >= 0:
        return float(retry_delay)
    return DEFAULT_RETRY_DELAY_S


def should_notify_policy_hit(bom: Mapping[str, Any] | None) -> bool:
    """True when forbidden pattern hits or forbidden licenses would fail --strict."""
    if not bom:
        return False
    summary = bom.get("summary") or {}
    if not isinstance(summary, dict):
        return False
    forbidden = summary.get("forbidden") or []
    forbidden_licenses = summary.get("forbiddenLicenses") or []
    return bool(forbidden or forbidden_licenses)


def build_webhook_payload(bom: Mapping[str, Any] | None) -> dict[str, Any]:
    rec = bom if isinstance(bom, dict) else {}
    summary = rec.get("summary") if isinstance(rec.get("summary"), dict) else {}
    hits = summary.get("policyHits", 0)
    try:
        hits = int(hits)
    except (TypeError, ValueError):
        hits = 0
    licenses = summary.get("forbiddenLicenses") or []
    if not isinstance(licenses, list):
        licenses = []
    return {
        "ok": False,
        "policyHits": hits,
        "forbiddenLicenses": licenses,
        "summary": summary,
    }


def post_policy_webhook(
    url: str,
    payload: Mapping[str, Any],
    *,
    timeout: float = DEFAULT_TIMEOUT_S,
    secret: str | None = None,
    urlopen: Any = None,
    sleep: Any = None,
    retry_delay: float | None = None,
) -> None:
    """POST JSON. Swallows all errors. Intended for fire-and-forget.

    Always sends `X-Webhook-Timestamp: <unix-seconds>` (fresh on every attempt).
    When `secret` is set, includes `X-Webhook-Signature: sha256=<hex>` HMAC-SHA256
    of the raw body (body only; timestamp is an extra header). Simple HMAC is OSS.
    OSS retries once after ~50ms on 5xx or network/timeout (success on first try
    = no retry; 4xx do not retry). Exponential backoff / queues = paid.
    """
    try:
        if not url:
            return
        data = json.dumps(payload, default=str).encode("utf-8")
        key = parse_webhook_secret(secret)
        ms = timeout if isinstance(timeout, (int, float)) and timeout > 0 else DEFAULT_TIMEOUT_S
        delay = _retry_delay_s(retry_delay)
        sleeper = sleep if callable(sleep) else time.sleep

        def headers_for_attempt() -> dict[str, str]:
            headers = {
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            }
            headers[TIMESTAMP_HEADER] = str(webhook_unix_seconds())
            if key:
                headers[SIGNATURE_HEADER] = sign_webhook_body(key, data)
            return headers

        try:
            status = _post_once(url, data, headers_for_attempt(), ms, urlopen)
            if not should_retry_webhook(status=status):
                return
        except Exception as err:
            if not should_retry_webhook(error=err):
                return
        sleeper(delay)
        try:
            _post_once(url, data, headers_for_attempt(), ms, urlopen)
        except Exception:
            return
    except Exception:
        return


def notify_policy_hit(
    url: str | None,
    bom: Mapping[str, Any] | None,
    *,
    timeout: float = DEFAULT_TIMEOUT_S,
    secret: str | None = None,
    urlopen: Any = None,
    sleep: Any = None,
    retry_delay: float | None = None,
) -> bool:
    """POST on forbidden hits / forbidden licenses. Never raises. Short timeout.

    Await the attempt so a CLI exit does not kill the request; errors swallowed.
    Returns True if a POST was attempted without an unexpected raise.
    When `secret` is set, POST includes X-Webhook-Signature HMAC of the raw body.
    """
    try:
        if not url or not should_notify_policy_hit(bom):
            return False
        payload = build_webhook_payload(bom)
        post_policy_webhook(
            url,
            payload,
            timeout=timeout,
            secret=secret,
            urlopen=urlopen,
            sleep=sleep,
            retry_delay=retry_delay,
        )
        return True
    except Exception:
        return False
