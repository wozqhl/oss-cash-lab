"""Local HTTP server for Feishu / DingTalk / WeCom mock webhooks."""
from __future__ import annotations

import json
import signal
import sys
import time
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from cn_work_agent.approvals import (
    DEFAULT_APPROVALS_MAX,
    approval_counts,
    decide_approval,
    expire_due,
    format_approvals_csv,
    format_approvals_html,
    format_approvals_md,
    get_approval,
    list_approvals,
    resolve_approval_ttl,
    resolve_approvals_max,
)
from cn_work_agent.cards import (
    CARD_PLATFORMS,
    build_im_card,
    normalize_card_platform,
)
from cn_work_agent.metrics import (
    CONTENT_TYPE as METRICS_CONTENT_TYPE,
    Metrics,
    render_metrics,
)
from cn_work_agent.webhook import (
    notify_approval_decision,
    notify_approval_decisions,
    parse_webhook_secret,
    parse_webhook_url,
    resolve_webhook_secret,
    resolve_webhook_url,
    should_notify,
)
from cn_work_agent.cors import (
    cors_response_headers,
    handle_preflight,
    normalize_cors,
    request_origin,
    resolve_cors_origins,
)
from cn_work_agent.rate_limit import (
    SlidingWindowRateLimiter,
    client_ip_from_handler,
    rate_limit_key,
    resolve_rate_limits,
)
from cn_work_agent.request_id import REQUEST_ID_HEADER, resolve_request_id
from cn_work_agent.access_log import emit_access_log, mark_access_start
from cn_work_agent.router import handle_platform
from cn_work_agent.verify import (
    PLATFORMS,
    VerifyError,
    callback_auth_status,
    enabled_platforms,
    list_platforms,
    parse_query,
    resolve_callback_secret,
    verify_platform,
)
from cn_work_agent.runtime_config import summarize_runtime_config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _metrics(server: Any) -> Metrics | None:
    m = getattr(server, "metrics", None)
    return m if isinstance(m, Metrics) else None


def _record_decided(server: Any, n: int) -> None:
    m = _metrics(server)
    if m is not None:
        m.add_decided(n)


def _notify_approval(server: Any, rec: dict[str, Any] | None) -> None:
    """Fire-and-forget approval-decision webhook; never raises."""
    if not rec:
        return
    url = getattr(server, "webhook_url", None)
    secret = getattr(server, "webhook_secret", None)
    if url and should_notify(rec):
        m = _metrics(server)
        if m is not None:
            m.add_webhooks(1)
    notify_approval_decision(url, rec, secret=secret)


def _notify_approvals(server: Any, records: list[dict[str, Any]] | None) -> None:
    if not records:
        return
    url = getattr(server, "webhook_url", None)
    secret = getattr(server, "webhook_secret", None)
    if url:
        n = sum(1 for r in records if should_notify(r))
        m = _metrics(server)
        if m is not None and n:
            m.add_webhooks(n)
    notify_approval_decisions(url, records, secret=secret)


def _expire_due_and_notify(server: Any) -> None:
    """Expire pending approvals and POST decision webhook for each newly expired row."""
    approvals_path = getattr(server, "approvals_path", "data/approvals.jsonl")
    ttl = getattr(server, "approval_ttl_seconds", None)
    cap = getattr(server, "approvals_max", DEFAULT_APPROVALS_MAX)
    expired = expire_due(approvals_path, ttl_seconds=ttl, approvals_max=cap)
    if expired:
        _record_decided(server, len(expired))
    _notify_approvals(server, expired)


DEFAULT_OPENAPI_PATH = Path(__file__).resolve().parents[2] / "openapi" / "agent.openapi.json"
# Poll interval for `serve --watch` (config file mtime).
WATCH_POLL_MS = 300
DEFAULT_SHUTDOWN_DRAIN_MS = 5000
MAX_SHUTDOWN_DRAIN_MS = 30000


def resolve_drain_ms(raw: Any = None, env: dict[str, str] | None = None) -> int:
    """CLI `--drain-ms`, else env SHUTDOWN_DRAIN_MS, else 5s. Cap 30s."""
    import os

    source = raw
    if source is None or source == "":
        environ = env if env is not None else os.environ
        source = environ.get("SHUTDOWN_DRAIN_MS")
    try:
        n = int(source)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = DEFAULT_SHUTDOWN_DRAIN_MS
    if n < 0:
        n = DEFAULT_SHUTDOWN_DRAIN_MS
    return min(MAX_SHUTDOWN_DRAIN_MS, n)


def begin_shutdown(server: Any) -> None:
    server.shutting_down = True
    stop = getattr(server, "watch_stop", None)
    if stop is not None:
        stop.set()


def file_mtime(path: str | Path) -> float:
    """Config file mtime; 0.0 if missing/unreadable."""
    try:
        return float(Path(path).stat().st_mtime)
    except OSError:
        return 0.0


def watch_log(line: str) -> None:
    """Line-buffered-ish stdout for --watch (redirected logs must appear promptly)."""
    s = str(line)
    if not s.endswith("\n"):
        s += "\n"
    try:
        sys.stdout.write(s)
        sys.stdout.flush()
    except OSError:
        pass


def load_config_json(path: str | Path) -> dict[str, Any]:
    """Read and JSON-validate a serve config object."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config must be a JSON object")
    return data


def apply_platform_env(data: dict[str, Any] | None) -> None:
    """Apply platform secrets to env only when unset (env wins if already set)."""
    import os

    if not data:
        return
    feishu = data.get("feishu") or {}
    dingtalk = data.get("dingtalk") or {}
    wecom = data.get("wecom") or {}
    mapping = [
        ("FEISHU_VERIFY_TOKEN", feishu.get("verify_token") if isinstance(feishu, dict) else None),
        ("FEISHU_ENCRYPT_KEY", feishu.get("encrypt_key") if isinstance(feishu, dict) else None),
        ("DINGTALK_TOKEN", dingtalk.get("token") if isinstance(dingtalk, dict) else None),
        ("DINGTALK_SECRET", dingtalk.get("secret") if isinstance(dingtalk, dict) else None),
        ("WECOM_TOKEN", wecom.get("token") if isinstance(wecom, dict) else None),
    ]
    for env_name, val in mapping:
        if val and not os.environ.get(env_name):
            os.environ[env_name] = str(val)


def apply_runtime_settings(
    target: Any,
    cfg: dict[str, Any] | None,
    *,
    cors_origins_cli: str | None = None,
    webhook_url_cli: str | None = None,
    webhook_secret_cli: str | None = None,
    approvals_max_cli: Any = None,
) -> dict[str, Any]:
    """Reload CORS, TTL, webhook url/secret, rate limits, and approvals-max.

    Precedence (highest first): CLI flags when provided (including empty) ->
    env if already set (including empty) -> config file. Platforms / limiter
    buckets are not reset.
    """
    merged = dict(cfg or {"bot_name": "cn-work-bot"})
    existing = getattr(target, "config", None)
    if isinstance(existing, dict):
        for k in ("approvals_path", "base_url"):
            if k in existing:
                merged[k] = existing[k]
    merged.setdefault("bot_name", "cn-work-bot")
    target.config = merged

    cors_origins = resolve_cors_origins(cors_origins_cli, config=merged)
    target.cors = normalize_cors(cors_origins)
    target.approval_ttl_seconds = resolve_approval_ttl(merged)
    target.rate_limits = resolve_rate_limits(merged)
    cli_cap = approvals_max_cli
    if cli_cap is None:
        cli_cap = getattr(target, "approvals_max_cli", None)
    target.approvals_max = resolve_approvals_max(cli_cap, config=merged)
    url = resolve_webhook_url(webhook_url_cli, config=merged)
    secret = resolve_webhook_secret(webhook_secret_cli, config=merged)
    target.webhook_url = parse_webhook_url(url)
    target.webhook_secret = parse_webhook_secret(secret)
    return {
        "approval_ttl_seconds": getattr(target, "approval_ttl_seconds", None),
        "approvals_max": getattr(target, "approvals_max", DEFAULT_APPROVALS_MAX),
        "rate_limit_per_minute": (getattr(target, "rate_limits", None) or {}).get("_default"),
        "cors": list(cors_origins or []),
        "webhook": bool(getattr(target, "webhook_url", None)),
        "hmac": bool(getattr(target, "webhook_secret", None)),
    }


def start_config_watch(
    path: str | Path,
    *,
    reload: Callable[[], dict[str, Any]],
    poll_ms: int = WATCH_POLL_MS,
    log: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> tuple[threading.Thread, threading.Event]:
    """Poll config file mtime and reload CORS/TTL/webhook/rate-limits/approvals-max.

    Parse errors keep the previous settings; mtime advances only after a
    successful reload. Returns (daemon thread, stop event).
    """
    log = log or watch_log
    stop = stop_event or threading.Event()
    cfg_path = Path(path)
    last = file_mtime(cfg_path)
    try:
        shown = str(cfg_path.resolve())
    except OSError:
        shown = str(cfg_path)
    log(f"watching {shown} (poll {poll_ms}ms)")

    def loop() -> None:
        nonlocal last
        interval = max(int(poll_ms), 1) / 1000.0
        while not stop.wait(interval):
            try:
                now = file_mtime(cfg_path)
                if not (now > last):
                    continue
                snap = reload()
                last = now
                log("regenerated " + json.dumps(snap, ensure_ascii=False))
            except Exception as e:  # noqa: BLE001 — keep previous settings
                try:
                    sys.stderr.write(f"watch regenerate error: {e}\n")
                    sys.stderr.flush()
                except OSError:
                    pass

    t = threading.Thread(target=loop, name="cn-work-agent-watch", daemon=True)
    t.start()
    return t, stop



def resolve_openapi_path(root: Path | None = None) -> Path:
    """Bet-local OpenAPI file (package root / openapi/agent.openapi.json)."""
    if root is not None:
        alt = Path(root) / "openapi" / "agent.openapi.json"
        if alt.is_file():
            return alt.resolve()
    return DEFAULT_OPENAPI_PATH


def load_openapi_bytes(root: Path | None = None) -> bytes:
    """Read and JSON-validate the file-backed OpenAPI document."""
    path = resolve_openapi_path(root)
    raw = path.read_bytes()
    json.loads(raw.decode("utf-8"))
    return raw


_PATH_TO_PLATFORM = {
    "/webhook/feishu": "feishu",
    "/webhook": "feishu",  # back-compat
    "/webhook/dingtalk": "dingtalk",
    "/webhook/wecom": "wecom",
}


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "cn-work-agent/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[http] {self.address_string()} {fmt % args}")

    def handle_one_request(self) -> None:
        mark_access_start(self)
        super().handle_one_request()

    def _cors(self) -> dict[str, Any] | None:
        return getattr(self.server, "cors", None)

    def _cors_headers(self) -> dict[str, str]:
        origin = request_origin(self.headers)
        return cors_response_headers(origin, self._cors())

    def _resolve_request_id(self) -> str:
        cached = getattr(self, "_cached_request_id", None)
        if cached:
            return cached
        rid = resolve_request_id(self.headers)
        self._cached_request_id = rid
        return rid

    def _merge_response_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        # CORS first; extra (e.g. Retry-After) wins on collision; X-Request-Id last.
        merged = {**self._cors_headers()}
        if extra:
            merged.update(extra)
        merged[REQUEST_ID_HEADER] = self._resolve_request_id()
        return merged

    def _send_json(
        self,
        code: int,
        body: dict[str, Any],
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(raw)))
        for k, v in self._merge_response_headers(extra_headers).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)
        emit_access_log(self, service="cn-work-agent", status=code, bytes_out=len(raw))

    def _send_text(
        self,
        code: int,
        text: str,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        raw = text.encode("utf-8")
        self.send_response(code)
        self.send_header("content-type", "text/plain; charset=utf-8")
        self.send_header("content-length", str(len(raw)))
        for k, v in self._merge_response_headers(extra_headers).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)
        emit_access_log(self, service="cn-work-agent", status=code, bytes_out=len(raw))

    def _send_response(self, code: int, body: dict[str, Any] | str) -> None:
        if isinstance(body, str):
            self._send_text(code, body)
        else:
            self._send_json(code, body)

    def _send_raw(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        for k, v in self._merge_response_headers().items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)
        emit_access_log(self, service="cn-work-agent", status=code, bytes_out=len(body))

    def _read_raw(self) -> bytes:
        length = int(self.headers.get("content-length") or 0)
        return self.rfile.read(length) if length else b""

    def _audit(self, event: dict[str, Any]) -> None:
        rid = self._resolve_request_id()
        if rid and "requestId" not in event:
            event = {**event, "requestId": rid}
        path = Path(getattr(self.server, "audit_path"))  # type: ignore[attr-defined]
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _platforms(self) -> list[str]:
        return list(getattr(self.server, "platforms", list(PLATFORMS)))  # type: ignore[attr-defined]

    def _health_payload(self) -> dict[str, Any]:
        plats = self._platforms()
        limits = getattr(self.server, "rate_limits", {})  # type: ignore[attr-defined]
        ttl = getattr(self.server, "approval_ttl_seconds", None)
        cap = getattr(self.server, "approvals_max", DEFAULT_APPROVALS_MAX)
        return {
            "ok": True,
            "service": "cn-work-agent",
            "version": "0.1.0",
            "platforms": plats,
            "enabled": plats,
            "rate_limit_per_minute": limits.get("_default"),
            "approval_ttl_seconds": ttl,
            "approvals_max": cap,
        }

    def _platform_for_path(self, path: str) -> str | None:
        plat = _PATH_TO_PLATFORM.get(path)
        if plat is None:
            return None
        if plat not in self._platforms():
            return None
        return plat

    def _rate_limit_or_reject(self, path: str, platform: str) -> bool:
        """
        Apply webhook rate limit (IP + platform).

        Returns True if the request was rejected (429 already sent).
        """
        limits: dict[str, int | None] = getattr(self.server, "rate_limits", {})  # type: ignore[attr-defined]
        limiter: SlidingWindowRateLimiter | None = getattr(self.server, "rate_limiter", None)  # type: ignore[attr-defined]
        if limiter is None:
            return False
        limit = limits.get(platform, limits.get("_default"))
        if limit is None:
            return False
        ip = client_ip_from_handler(self)
        key = rate_limit_key(ip, platform)
        allowed, retry_after = limiter.check(key, limit)
        if allowed:
            return False
        self._audit(
            {
                "ts": _now(),
                "path": path,
                "platform": platform,
                "error": "rate_limited",
                "ip": ip,
                "limit": limit,
                "retry_after": retry_after,
            }
        )
        self._send_json(
            429,
            {
                "error": "rate_limited",
                "platform": platform,
                "limit": limit,
                "retry_after": retry_after,
            },
            extra_headers={"Retry-After": str(retry_after)},
        )
        return True

    def _reject_decide_callback(
        self,
        rec: dict[str, Any] | None,
        raw: bytes,
        method: str,
        path: str,
    ) -> bool:
        """POST decide HMAC when callbackSecret is set. True if 401 already sent.

        GET is never signed (IM card buttons). Missing secret → allow.
        401 body never includes the secret.
        """
        plat = None
        if rec:
            plat = rec.get("platform")
        config = getattr(self.server, "config", None) or {}
        secret = resolve_callback_secret(
            str(plat) if plat else None,
            config=config if isinstance(config, dict) else None,
        )
        status, reason = callback_auth_status(
            secret, raw, self.headers, method=method
        )
        if status == 200:
            return False
        self._audit(
            {
                "ts": _now(),
                "path": path,
                "event": "approval_decide",
                "error": "unauthorized",
                "reason": reason,
                "platform": plat,
            }
        )
        self._send_json(401, {"error": "unauthorized", "reason": reason})
        return True

    def _finish_decide(
        self,
        approval_id: str,
        decision: str,
        note: str,
        path: str,
        ttl: Any,
        approvals_path: str,
    ) -> None:
        try:
            rec = decide_approval(
                approvals_path,
                approval_id,
                str(decision or ""),
                note=str(note),
                ttl_seconds=ttl,
                approvals_max=getattr(self.server, "approvals_max", DEFAULT_APPROVALS_MAX),
            )
        except KeyError:
            self._send_json(404, {"error": "not_found", "id": approval_id})
            return
        except ValueError as err:
            self._send_json(400, {"error": "bad_request", "reason": str(err)})
            return
        self._audit({
            "ts": _now(),
            "path": path,
            "event": "approval_decide",
            "approval_id": approval_id,
            "decision": rec.get("decision"),
            "status": rec.get("status"),
            "note": rec.get("note"),
        })
        _record_decided(self.server, 1)
        _notify_approval(self.server, rec)
        self._send_json(200, {"ok": True, "approval": rec})

    def _send_approval_card(self, path: str, query: dict[str, str]) -> None:
        """GET /v1/approvals/{id}/card?platform=feishu|dingtalk|wecom — IM POST body."""
        parts = [p for p in path.split("/") if p]
        if len(parts) != 4 or parts[0] != "v1" or parts[1] != "approvals" or parts[3] != "card":
            self._send_json(404, {"error": "not_found", "path": path})
            return
        approval_id = parts[2]
        approvals_path = getattr(self.server, "approvals_path", "data/approvals.jsonl")
        ttl = getattr(self.server, "approval_ttl_seconds", None)
        _expire_due_and_notify(self.server)
        rec = get_approval(approvals_path, approval_id, ttl_seconds=ttl, approvals_max=getattr(self.server, "approvals_max", DEFAULT_APPROVALS_MAX))
        if rec is None:
            self._send_json(404, {"error": "not_found", "id": approval_id})
            return
        requested = (query.get("platform") or "").strip()
        plat = normalize_card_platform(requested) if requested else normalize_card_platform(
            rec.get("platform")
        )
        if plat is None:
            self._send_json(
                400,
                {
                    "error": "bad_platform",
                    "allowed": list(CARD_PLATFORMS),
                },
            )
            return
        config = getattr(self.server, "config", {}) or {}
        base_url = config.get("base_url") if isinstance(config, dict) else None
        try:
            card = build_im_card(rec, plat, base_url=str(base_url) if base_url else None)
        except ValueError as err:
            self._send_json(400, {"error": "bad_platform", "reason": str(err)})
            return
        self._send_json(200, card)

    def _parse_limit(self, query: dict[str, str], default: int | None) -> int | None:
        raw = query.get("limit")
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    def _send_approvals_export(
        self, query: dict[str, str], *, as_csv: bool = False, as_md: bool = False, as_html: bool = False
    ) -> None:
        """JSON list (GET /approvals, GET /v1/approvals) or audit CSV / Markdown / HTML."""
        fmt = (query.get("format") or "").strip().lower()
        if not as_csv and not as_md and not as_html and fmt and fmt not in ("csv", "json", "md", "html"):
            self._send_json(400, {"error": "bad_format", "allowed": ["csv", "json", "md", "html"]})
            return
        want_csv = as_csv or fmt == "csv"
        want_md = (not want_csv) and (as_md or fmt == "md")
        want_html = (not want_csv) and (not want_md) and (as_html or fmt == "html")
        approvals_path = getattr(self.server, "approvals_path", "data/approvals.jsonl")
        ttl = getattr(self.server, "approval_ttl_seconds", None)
        _expire_due_and_notify(self.server)
        # Omit status → unfiltered. Present (incl empty/unknown) → list helper (empty list, not 400).
        status = query.get("status")
        limit = self._parse_limit(query, None if (want_csv or want_md or want_html) else 50)
        rows = list_approvals(
            approvals_path,
            limit=limit,
            status=status,
            ttl_seconds=ttl,
            approvals_max=getattr(self.server, "approvals_max", DEFAULT_APPROVALS_MAX),
        )
        if want_csv:
            raw = format_approvals_csv(rows).encode("utf-8")
            self._send_raw(200, raw, "text/csv; charset=utf-8")
            return
        if want_md:
            raw = format_approvals_md(rows).encode("utf-8")
            self._send_raw(200, raw, "text/markdown; charset=utf-8")
            return
        if want_html:
            raw = format_approvals_html(rows).encode("utf-8")
            self._send_raw(200, raw, "text/html; charset=utf-8")
            return
        self._send_json(
            200,
            {
                "ok": True,
                "count": len(rows),
                "approvals": rows,
                "approval_ttl_seconds": ttl,
            },
        )

    def do_OPTIONS(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        origin = request_origin(self.headers)
        pf = handle_preflight(origin, self._cors())
        if pf is None:
            # CORS disabled: no extra CORS; same 404 as unknown methods/paths.
            self._send_json(404, {"error": "not_found", "path": path})
            return
        if pf["status"] == 204:
            self.send_response(204)
            for k, v in (pf.get("headers") or {}).items():
                self.send_header(k, v)
            self.send_header(REQUEST_ID_HEADER, self._resolve_request_id())
            self.end_headers()
            return
        self._send_json(
            int(pf["status"]),
            pf.get("body") or {"error": "forbidden"},
            extra_headers=pf.get("headers") or {},
        )

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_query(self.path)

        if path == "/health":
            payload = self._health_payload()
            if getattr(self.server, "shutting_down", False):
                payload["shuttingDown"] = True
            self._send_json(200, payload)
            return

        if path == "/ready":
            # Shutdown 503 wins over healthy 200. Stateless HTTP; no circuit/queue.
            if getattr(self.server, "shutting_down", False):
                self._send_json(503, {"ok": False, "reason": "shutting_down"})
                return
            self._send_json(200, self._health_payload())
            return

        if path == "/metrics":
            # Cheap scrape: JSONL pending count (no expire_due) + in-memory counters.
            approvals_path = getattr(self.server, "approvals_path", "data/approvals.jsonl")
            pending = approval_counts(approvals_path).get("pending", 0)
            m = _metrics(self.server)
            snap = m.snapshot(pending=pending) if m is not None else {
                "pending": pending,
                "decided": 0,
                "webhooks": 0,
            }
            body = render_metrics(snap).encode("utf-8")
            self._send_raw(200, body, METRICS_CONTENT_TYPE)
            return

        if path == "/openapi.json":
            try:
                raw = load_openapi_bytes()
            except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
                self._send_json(500, {"error": "openapi_unavailable", "detail": str(e)})
                return
            self._send_raw(200, raw, "application/json; charset=utf-8")
            return

        if path == "/v1/platforms":
            # Product inventory (not /health snapshot). CORS + X-Request-Id via _send_json.
            # Not rate-limited (same as other GETs besides /webhook/*).
            config = getattr(self.server, "config", None) or {}
            payload = list_platforms(
                config=config if isinstance(config, dict) else {},
                enabled=self._platforms(),
            )
            self._send_json(200, payload)
            return

        if path == "/v1/config":
            # Public redacted runtime config (no admin token). Allowlist only.
            # Never webhook URL (query tokens), secrets, FEISHU_* , Authorization.
            config = getattr(self.server, "config", None) or {}
            cors = getattr(self.server, "cors", None)
            origins = list((cors or {}).get("origins") or [])
            payload = summarize_runtime_config(
                approval_ttl_seconds=getattr(self.server, "approval_ttl_seconds", None),
                rate_limits=getattr(self.server, "rate_limits", None),
                cors_origins=origins,
                webhook_url=getattr(self.server, "webhook_url", None),
                webhook_secret=getattr(self.server, "webhook_secret", None),
                approvals_max=getattr(self.server, "approvals_max", DEFAULT_APPROVALS_MAX),
                config=config if isinstance(config, dict) else {},
                enabled=self._platforms(),
            )
            self._send_json(200, payload)
            return

        if path == "/v1/approvals.csv":
            self._send_approvals_export(query, as_csv=True)
            return
        if path == "/v1/approvals.md":
            self._send_approvals_export(query, as_md=True)
            return
        if path == "/v1/approvals.html":
            self._send_approvals_export(query, as_html=True)
            return
        if path.startswith("/v1/approvals/") and path.endswith("/card"):
            self._send_approval_card(path, query)
            return
        if path in ("/approvals", "/v1/approvals"):
            self._send_approvals_export(query, as_csv=False)
            return
        if path.startswith("/approvals/"):
            approvals_path = getattr(self.server, "approvals_path", "data/approvals.jsonl")
            ttl = getattr(self.server, "approval_ttl_seconds", None)
            # Always expire due before list/get (webhook on newly expired)
            _expire_due_and_notify(self.server)
            parts = [p for p in path.split("/") if p]
            # GET /approvals/{id}/decide?decision=approve|reject — unsigned (demo cards)
            if len(parts) == 3 and parts[0] == "approvals" and parts[2] == "decide":
                approval_id = parts[1]
                rec_now = get_approval(approvals_path, approval_id, ttl_seconds=ttl, approvals_max=getattr(self.server, "approvals_max", DEFAULT_APPROVALS_MAX))
                if self._reject_decide_callback(rec_now, b"", "GET", path):
                    return
                decision = query.get("decision") or ""
                note = query.get("note") or ""
                self._finish_decide(
                    approval_id, decision, note, path, ttl, approvals_path
                )
                return
            # GET /approvals/{id}
            if len(parts) == 2 and parts[0] == "approvals":
                approval_id = parts[1]
                rec = get_approval(approvals_path, approval_id, ttl_seconds=ttl, approvals_max=getattr(self.server, "approvals_max", DEFAULT_APPROVALS_MAX))
                if rec is None:
                    self._send_json(404, {"error": "not_found", "id": approval_id})
                    return
                self._send_json(200, {"ok": True, "approval": rec})
                return
            self._send_json(404, {"error": "not_found", "path": path})
            return

        # WeCom URL verification: GET with echostr
        plat = self._platform_for_path(path)
        if plat == "wecom" and query.get("echostr"):
            if self._rate_limit_or_reject(path, plat):
                return
            try:
                verify_platform(plat, self.headers, b"", {}, query=query)
            except VerifyError as err:
                self._audit({
                    "ts": _now(),
                    "path": path,
                    "platform": plat,
                    "error": "unauthorized",
                    "reason": err.reason,
                })
                self._send_json(401, {"error": "unauthorized", "reason": err.reason})
                return
            config = getattr(self.server, "config", {})  # type: ignore[attr-defined]
            response = handle_platform(
                plat, {}, config, query=query, request_id=self._resolve_request_id()
            )
            self._audit({
                "ts": _now(),
                "path": path,
                "platform": plat,
                "query": query,
                "response": response if isinstance(response, dict) else {"echostr": response},
            })
            # Prefer plain echostr for WeCom-like clients; also OK as JSON with echostr.
            if isinstance(response, dict) and "echostr" in response:
                self._send_text(200, str(response["echostr"]))
            else:
                self._send_response(200, response)
            return

        self._send_json(404, {"error": "not_found", "path": path})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_query(self.path)

        # POST /approvals/{id}/decide
        if path.startswith("/approvals/") and path.endswith("/decide"):
            parts = [p for p in path.split("/") if p]
            # approvals / {id} / decide
            if len(parts) == 3 and parts[0] == "approvals" and parts[2] == "decide":
                approval_id = parts[1]
                raw = self._read_raw()
                if not raw:
                    raw = b"{}"
                try:
                    body = json.loads(raw.decode("utf-8") or "{}")
                except json.JSONDecodeError:
                    self._send_json(400, {"error": "invalid_json"})
                    return
                if not isinstance(body, dict):
                    self._send_json(400, {"error": "invalid_json"})
                    return
                decision = body.get("decision")
                note = body.get("note") or ""
                approvals_path = getattr(self.server, "approvals_path", "data/approvals.jsonl")
                ttl = getattr(self.server, "approval_ttl_seconds", None)
                _expire_due_and_notify(self.server)
                rec_now = get_approval(approvals_path, approval_id, ttl_seconds=ttl, approvals_max=getattr(self.server, "approvals_max", DEFAULT_APPROVALS_MAX))
                if self._reject_decide_callback(rec_now, raw, "POST", path):
                    return
                self._finish_decide(
                    approval_id,
                    str(decision or ""),
                    str(note),
                    path,
                    ttl,
                    approvals_path,
                )
                return
            self._send_json(404, {"error": "not_found", "path": path})
            return

        plat = self._platform_for_path(path)
        if plat is None:
            self._send_json(404, {"error": "not_found", "path": path})
            return

        if self._rate_limit_or_reject(path, plat):
            return

        raw = self._read_raw()
        if not raw:
            raw = b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid_json"})
            return
        if not isinstance(payload, dict):
            self._send_json(400, {"error": "invalid_json"})
            return

        try:
            verify_platform(plat, self.headers, raw, payload, query=query)
        except VerifyError as err:
            self._audit({
                "ts": _now(),
                "path": path,
                "platform": plat,
                "error": "unauthorized",
                "reason": err.reason,
            })
            self._send_json(401, {"error": "unauthorized", "reason": err.reason})
            return

        config = getattr(self.server, "config", {})  # type: ignore[attr-defined]
        response = handle_platform(
            plat, payload, config, query=query, request_id=self._resolve_request_id()
        )
        self._audit({
            "ts": _now(),
            "path": path,
            "platform": plat,
            "payload": payload,
            "response": response if isinstance(response, (dict, list)) else {"body": response},
        })
        self._send_response(200, response)


def serve(
    host: str = "127.0.0.1",
    port: int = 8790,
    audit_path: str = "data/audit.jsonl",
    approvals_path: str = "data/approvals.jsonl",
    config: dict[str, Any] | None = None,
    platforms: list[str] | None = None,
    rate_limits: dict[str, int | None] | None = None,
    cors_origins: list[str] | None = None,
    webhook_url: str | None = None,
    webhook_secret: str | None = None,
    watch: bool = False,
    config_path: str | None = None,
    cors_origins_cli: str | None = None,
    webhook_url_cli: str | None = None,
    webhook_secret_cli: str | None = None,
    drain_ms: int | None = None,
    log_json: bool = False,
    approvals_max: Any = None,
):
    plats = enabled_platforms(platforms)
    httpd = ThreadingHTTPServer((host, port), GatewayHandler)
    httpd.daemon_threads = True
    httpd.allow_reuse_address = True
    httpd.shutting_down = False  # type: ignore[attr-defined]
    httpd.audit_path = str(Path(audit_path).resolve())  # type: ignore[attr-defined]
    httpd.approvals_path = str(Path(approvals_path).resolve())  # type: ignore[attr-defined]
    cfg = dict(config or {"bot_name": "cn-work-bot"})
    cfg.setdefault("approvals_path", httpd.approvals_path)  # type: ignore[attr-defined]
    cfg.setdefault("base_url", f"http://{host}:{port}")
    httpd.config = cfg  # type: ignore[attr-defined]
    httpd.platforms = plats  # type: ignore[attr-defined]
    limits = rate_limits if rate_limits is not None else resolve_rate_limits(cfg)
    httpd.rate_limits = limits  # type: ignore[attr-defined]
    httpd.rate_limiter = SlidingWindowRateLimiter()  # type: ignore[attr-defined]
    ttl = resolve_approval_ttl(cfg)
    httpd.approval_ttl_seconds = ttl  # type: ignore[attr-defined]
    httpd.approvals_max_cli = approvals_max  # type: ignore[attr-defined]
    cap = resolve_approvals_max(approvals_max, config=cfg)
    httpd.approvals_max = cap  # type: ignore[attr-defined]
    if cors_origins is None:
        cors_origins = resolve_cors_origins(cors_origins_cli, config=cfg)
    cors = normalize_cors(cors_origins)
    httpd.cors = cors  # type: ignore[attr-defined]
    httpd.webhook_url = parse_webhook_url(webhook_url)  # type: ignore[attr-defined]
    httpd.webhook_secret = parse_webhook_secret(webhook_secret)  # type: ignore[attr-defined]
    httpd.metrics = Metrics()  # type: ignore[attr-defined]
    httpd.config_path = str(Path(config_path).resolve()) if config_path else None  # type: ignore[attr-defined]
    httpd.cors_origins_cli = cors_origins_cli  # type: ignore[attr-defined]
    httpd.webhook_url_cli = webhook_url_cli  # type: ignore[attr-defined]
    httpd.webhook_secret_cli = webhook_secret_cli  # type: ignore[attr-defined]
    httpd.log_json = bool(log_json)  # type: ignore[attr-defined]
    stop = threading.Event()
    httpd.watch_stop = stop  # type: ignore[attr-defined]

    def _expire_loop() -> None:
        # Periodic expiry; interval scales with live TTL (min 1s, max 30s).
        while not stop.is_set():
            current_ttl = getattr(httpd, "approval_ttl_seconds", None)
            try:
                expired = expire_due(  # type: ignore[attr-defined]
                    httpd.approvals_path,
                    ttl_seconds=current_ttl,
                    approvals_max=getattr(httpd, "approvals_max", DEFAULT_APPROVALS_MAX),
                )
                if expired:
                    _record_decided(httpd, len(expired))
                _notify_approvals(httpd, expired)
            except Exception as exc:  # noqa: BLE001 — never kill serve on expire errors
                print(f"[approvals] expire_due error: {exc}")
            if current_ttl is None or current_ttl <= 0:
                interval = 30.0
            else:
                interval = float(min(30, max(1, current_ttl)))
            stop.wait(interval)

    expire_thread = threading.Thread(target=_expire_loop, name="approval-expire", daemon=True)
    expire_thread.start()
    if watch and not config_path:
        print("watch requires --config; ignoring --watch")
        watch = False

    def _reload_config() -> dict[str, Any]:
        data = load_config_json(str(config_path))
        apply_platform_env(data)
        return apply_runtime_settings(
            httpd,
            data,
            cors_origins_cli=cors_origins_cli,
            webhook_url_cli=webhook_url_cli,
            webhook_secret_cli=webhook_secret_cli,
            approvals_max_cli=getattr(httpd, "approvals_max_cli", None),
        )

    cors_note = ",".join(cors_origins) if cors_origins else "deny"
    hook_note = parse_webhook_url(webhook_url) or "off"
    hmac_note = "on" if parse_webhook_secret(webhook_secret) else "off"
    print(f"cn-work-agent listening on http://{host}:{port}")
    print(f"platforms={','.join(plats)}")
    print(f"rate_limit_per_minute={limits.get('_default')}")
    print(f"approval_ttl_seconds={ttl}")
    cap_note = "unlimited" if not cap else cap
    print(f"approvals_max={cap_note}")
    print(f"cors={cors_note}")
    print(f"webhook={hook_note}")
    print(f"hmac={hmac_note}")
    print(f"watch={'poll %dms' % WATCH_POLL_MS if watch else 'off'}")
    print("GET /health  GET /ready  GET /metrics  GET /openapi.json  GET /v1/platforms  GET /v1/config  GET /approvals  GET /v1/approvals.csv  GET /v1/approvals.md  GET /v1/approvals.html  GET /v1/approvals/{id}/card")
    print(f"audit={httpd.audit_path}")  # type: ignore[attr-defined]
    print(f"approvals={httpd.approvals_path}")  # type: ignore[attr-defined]
    try:
        sys.stdout.flush()
    except OSError:
        pass
    if watch:
        start_config_watch(config_path, reload=_reload_config, stop_event=stop)

    drain = resolve_drain_ms(drain_ms)
    started = threading.Event()

    def _begin(_signum=None, _frame=None):
        if started.is_set():
            return
        started.set()
        begin_shutdown(httpd)
        print("shutting down", flush=True)
        stop.set()

        def _later():
            time.sleep(drain / 1000.0)
            try:
                httpd.shutdown()
            except Exception:
                pass

        threading.Thread(target=_later, name="shutdown-drain", daemon=True).start()

    try:
        signal.signal(signal.SIGTERM, _begin)
        signal.signal(signal.SIGINT, _begin)
    except (ValueError, OSError):
        pass
    try:
        httpd.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        _begin()
    finally:
        stop.set()
        print("exit", flush=True)
        httpd.server_close()



def serve_in_thread(**kwargs):
    t = threading.Thread(target=serve, kwargs=kwargs, daemon=True)
    t.start()
    return t
