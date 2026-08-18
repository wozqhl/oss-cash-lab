"""Optional Dify / n8n-shaped approval forward (adapter only; no orchestration).

OSS sample wiring: when an approval becomes approved (also rejected / TTL
expired), fire-and-forget POST a small JSON to APPROVAL_FORWARD_URL /
`--forward-url` / config `approval_forward_url`.

Body shape (Dify / n8n webhook-trigger friendly):
  {event, approval_id, status, tenant|app, title}

No secrets / tokens / notes in the body. Optional HMAC-SHA256
(`APPROVAL_FORWARD_SECRET` / `--forward-secret` / `approval_forward_secret`)
→ `X-Webhook-Signature: sha256=<hex>` of the raw JSON body (same as B/E).
Default off (unsigned). Reuses the existing outbound POST + 1 retry
(~50ms on 5xx/timeout). This is example wiring, not a Dify plugin and
not an n8n node.
"""
from __future__ import annotations

import os
import threading
from typing import Any, Mapping

from cn_work_agent.webhook import (
    DEFAULT_RETRY_DELAY_S,
    DEFAULT_TIMEOUT_S,
    parse_webhook_secret,
    parse_webhook_url,
    post_approval_webhook,
)

ENV_FORWARD_URL = "APPROVAL_FORWARD_URL"
CONFIG_FORWARD_URL = "approval_forward_url"
ENV_FORWARD_SECRET = "APPROVAL_FORWARD_SECRET"
CONFIG_FORWARD_SECRET = "approval_forward_secret"
ENV_FORWARD_TENANT = "APPROVAL_FORWARD_TENANT"
ENV_FORWARD_APP = "APPROVAL_FORWARD_APP"
FORWARD_STATUSES = frozenset({"approved", "rejected"})
EVENT_PREFIX = "approval."
DEFAULT_TENANT = "cn-work-bot"
TITLE_MAX = 200


def parse_forward_url(raw: str | None) -> str | None:
    return parse_webhook_url(raw)


def resolve_forward_url(
    cli_value: str | None,
    env: Mapping[str, str] | None = None,
    config: Mapping[str, Any] | None = None,
) -> str | None:
    """CLI `--forward-url` wins when provided (including empty);
    else env `APPROVAL_FORWARD_URL` if set; else config `approval_forward_url`.
    """
    if cli_value is not None:
        return parse_forward_url(cli_value)
    environ = env if env is not None else os.environ
    if ENV_FORWARD_URL in environ:
        return parse_forward_url(environ.get(ENV_FORWARD_URL, ""))
    if config:
        return parse_forward_url(config.get(CONFIG_FORWARD_URL))
    return None


def parse_forward_secret(raw: str | None) -> str | None:
    return parse_webhook_secret(raw)


def resolve_forward_secret(
    cli_value: str | None,
    env: Mapping[str, str] | None = None,
    config: Mapping[str, Any] | None = None,
) -> str | None:
    """CLI `--forward-secret` wins when provided (including empty);
    else env `APPROVAL_FORWARD_SECRET` if set; else config `approval_forward_secret`.
    Default off (unsigned).
    """
    if cli_value is not None:
        return parse_forward_secret(cli_value)
    environ = env if env is not None else os.environ
    if ENV_FORWARD_SECRET in environ:
        return parse_forward_secret(environ.get(ENV_FORWARD_SECRET, ""))
    if config:
        return parse_forward_secret(config.get(CONFIG_FORWARD_SECRET))
    return None


def should_forward(record: Mapping[str, Any] | None) -> bool:
    """True when status is approved or rejected (includes TTL expired). Not pending."""
    if not record:
        return False
    return str(record.get("status") or "") in FORWARD_STATUSES


def _flatten_title(raw: Any) -> str:
    s = "" if raw is None else str(raw)
    s = s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ").strip()
    if len(s) > TITLE_MAX:
        return s[: TITLE_MAX - 1].rstrip() + "…"
    return s


def approval_forward_title(record: Mapping[str, Any] | None) -> str:
    """Human title from approval text/title. No notes/tokens."""
    r = record if isinstance(record, dict) else {}
    raw = r.get("text")
    if raw in (None, ""):
        raw = r.get("title") or r.get("summary") or ""
    return _flatten_title(raw)


def _first_nonempty(*vals: Any) -> str | None:
    for v in vals:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return None


def resolve_forward_identity(
    record: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    config: Mapping[str, Any] | None = None,
) -> tuple[str, str]:
    """Return (kind, value) where kind is ``tenant`` or ``app``.

    Prefer explicit tenant (env / config / record), else app (env / config
    ``app`` / ``bot_name``), else default bot name as tenant.
    """
    rec = record if isinstance(record, dict) else {}
    cfg = config if isinstance(config, dict) else {}
    environ = env if env is not None else os.environ
    tenant = _first_nonempty(
        environ.get(ENV_FORWARD_TENANT) if ENV_FORWARD_TENANT in environ else None,
        cfg.get("tenant"),
        rec.get("tenant"),
    )
    if tenant:
        return "tenant", tenant
    app = _first_nonempty(
        environ.get(ENV_FORWARD_APP) if ENV_FORWARD_APP in environ else None,
        cfg.get("app"),
        cfg.get("bot_name"),
        rec.get("app"),
    )
    if app:
        return "app", app
    return "tenant", DEFAULT_TENANT


def build_forward_payload(
    record: Mapping[str, Any] | None,
    *,
    env: Mapping[str, str] | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Dify / n8n webhook-shaped JSON. Never includes secrets/notes/tokens."""
    rec = record if isinstance(record, dict) else {}
    status = str(rec.get("status") or "")
    event = f"{EVENT_PREFIX}{status}" if status else "approval.unknown"
    kind, ident = resolve_forward_identity(rec, env=env, config=config)
    payload: dict[str, Any] = {
        "event": event,
        "approval_id": rec.get("id"),
        "status": rec.get("status"),
        kind: ident,
        "title": approval_forward_title(rec),
    }
    return payload


def notify_approval_forward(
    url: str | None,
    record: Mapping[str, Any] | None,
    *,
    timeout: float = DEFAULT_TIMEOUT_S,
    wait: bool = False,
    urlopen: Any = None,
    sleep: Any = None,
    retry_delay: float | None = None,
    env: Mapping[str, str] | None = None,
    config: Mapping[str, Any] | None = None,
    secret: str | None = None,
) -> None:
    """Fire-and-forget Dify/n8n-shaped POST. Never raises. Never blocks decide.

    When `secret` is set, POST includes `X-Webhook-Signature: sha256=<hex>`
    HMAC-SHA256 of the raw JSON body (same header as B/E/F decision webhooks).
    Omit / empty = unsigned (default).
    """
    try:
        if not url or not should_forward(record):
            return
        payload = build_forward_payload(record, env=env, config=config)
        key = parse_forward_secret(secret)
        kwargs = {
            "timeout": timeout,
            "secret": key,
            "urlopen": urlopen,
            "sleep": sleep,
            "retry_delay": retry_delay if retry_delay is not None else DEFAULT_RETRY_DELAY_S,
        }
        if wait:
            post_approval_webhook(url, payload, **kwargs)
            return
        t = threading.Thread(
            target=post_approval_webhook,
            args=(url, payload),
            kwargs=kwargs,
            name="cn-work-agent-forward",
            daemon=True,
        )
        t.start()
    except Exception:
        return


def notify_approval_forwards(
    url: str | None,
    records: list[Mapping[str, Any]] | None,
    *,
    timeout: float = DEFAULT_TIMEOUT_S,
    wait: bool = False,
    urlopen: Any = None,
    sleep: Any = None,
    retry_delay: float | None = None,
    env: Mapping[str, str] | None = None,
    config: Mapping[str, Any] | None = None,
    secret: str | None = None,
) -> None:
    """Forward each decided/expired record. Never raises."""
    try:
        if not url or not records:
            return
        for rec in records:
            notify_approval_forward(
                url,
                rec,
                timeout=timeout,
                wait=wait,
                urlopen=urlopen,
                sleep=sleep,
                retry_delay=retry_delay,
                env=env,
                config=config,
                secret=secret,
            )
    except Exception:
        return
