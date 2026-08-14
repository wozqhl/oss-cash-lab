"""Local OSS BOM HTTP server (stdlib http.server). Hosted inventory = paid later."""
from __future__ import annotations

import json
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from ai_bom import __version__
from ai_bom.cors import cors_response_headers, handle_preflight, normalize_cors, request_origin
from ai_bom.metrics import CONTENT_TYPE as METRICS_CONTENT_TYPE, render_metrics
from ai_bom.request_id import REQUEST_ID_HEADER, resolve_request_id
from ai_bom.access_log import emit_access_log, mark_access_start
from ai_bom.rate_limit import (
    SlidingWindowRateLimiter,
    client_ip_from_handler,
    resolve_rate_limit,
    skip_rate_limit,
)
from ai_bom.scanner import (
    bom_without_exceptions,
    build_policy_gate,
    collect_exceptions,
    dumps_bom,
    exceptions_json,
    exceptions_query_skips,
    list_components,
    load_policy,
    parse_ignore_arg,
    render_evidence,
    scan_path,
)
from ai_bom.export import FORMATS_HELP, content_type_for, dumps_export, normalize_format, to_html
from ai_bom.runtime_config import summarize_runtime_config
from ai_bom.webhook import parse_webhook_secret, parse_webhook_url, resolve_webhook_secret, resolve_webhook_url

DEFAULT_SERVE_PORT = 8793
DEFAULT_SERVE_HOST = "127.0.0.1"
DEFAULT_OPENAPI_PATH = Path(__file__).resolve().parents[2] / "openapi" / "bom.openapi.json"
# Poll interval for `serve --watch` (directory / walk max mtime).
WATCH_POLL_MS = 500
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


def resolve_openapi_path(root: Path | None = None) -> Path:
    """Bet-local OpenAPI file (package root / openapi/bom.openapi.json)."""
    if root is not None:
        alt = Path(root) / "openapi" / "bom.openapi.json"
        if alt.is_file():
            return alt.resolve()
    return DEFAULT_OPENAPI_PATH


def load_openapi_bytes(root: Path | None = None) -> bytes:
    """Read and JSON-validate the file-backed OpenAPI document."""
    path = resolve_openapi_path(root)
    raw = path.read_bytes()
    json.loads(raw.decode("utf-8"))
    return raw



def render_summary_html(bom: dict[str, Any], *, watch: bool = False) -> str:
    """Self-contained HTML: component count, license summary, policy hits.

    Same formatter as CLI `--format html` / `GET /v1/bom.html`, plus serve-index nav.
    """
    return to_html(bom, watch=watch, include_nav=True)


def build_snapshot(
    path: Path,
    policy: dict[str, Any] | None = None,
    ignore: list[str] | None = None,
    *,
    watch: bool = False,
    exceptions_path: str | None = None,
) -> dict[str, Any]:
    bom = scan_path(path, policy=policy, ignore=ignore, exceptions_path=exceptions_path)
    summary = bom.get("summary") or {}
    health = {
        "ok": True,
        "service": "ai-bom",
        "version": __version__,
        "path": str(path),
        "componentCount": len(bom.get("components") or []),
        "policyHits": summary.get("policyHits", 0),
        "licenses": summary.get("licenses") or {},
    }
    return {
        "bom": bom,
        "bom_text": dumps_bom(bom),
        "evidence": render_evidence(bom),
        "html": render_summary_html(bom, watch=watch),
        "health": health,
        "health_text": json.dumps(health, indent=2, ensure_ascii=False) + "\n",
        "metrics_text": render_metrics(bom),
    }


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


def walk_max_mtime(path: Path) -> float:
    """Directory mtime, or simple walk of max mtime under path (files + dirs)."""
    max_m = 0.0
    try:
        st = path.stat()
        max_m = float(st.st_mtime)
    except OSError:
        return max_m
    if not path.is_dir():
        return max_m
    try:
        for p in path.rglob("*"):
            try:
                m = float(p.stat().st_mtime)
            except OSError:
                continue
            if m > max_m:
                max_m = m
    except OSError:
        pass
    return max_m


def start_path_watch(
    path: Path,
    *,
    reload: Callable[[], dict[str, Any]],
    poll_ms: int = WATCH_POLL_MS,
    log: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> tuple[threading.Thread, threading.Event]:
    """Poll scan-root max mtime and rescan the live snapshot.

    Scan errors keep the previous snapshot; mtime advances only after a successful reload.
    Returns (daemon thread, stop event).
    """
    log = log or watch_log
    stop = stop_event or threading.Event()
    last = walk_max_mtime(path)
    log(f"watching {path} (poll {poll_ms}ms)")

    def loop() -> None:
        nonlocal last
        interval = max(int(poll_ms), 1) / 1000.0
        while not stop.wait(interval):
            try:
                now = walk_max_mtime(path)
                if not (now > last):
                    continue
                snap = reload()
                last = now
                health = (snap or {}).get("health") or {}
                count = health.get("componentCount")
                log("regenerated " + json.dumps({"componentCount": count}))
            except Exception as e:
                try:
                    sys.stderr.write(f"watch regenerate error: {e}\n")
                    sys.stderr.flush()
                except OSError:
                    pass

    t = threading.Thread(target=loop, name="ai-bom-watch", daemon=True)
    t.start()
    return t, stop


class BomHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    snapshot: dict[str, Any]
    cors: dict[str, Any] | None
    scan_root: Path
    policy: dict[str, Any] | None
    ignore: list[str] | None
    exceptions_path: str | None
    watch: bool
    rate_limit: int | None
    rate_limiter: SlidingWindowRateLimiter
    webhook_url: str | None
    webhook_secret: str | None
    has_policy_file: bool

    def reload_snapshot(self) -> dict[str, Any]:
        """Rescan scan_root and swap the snapshot used by HTTP handlers."""
        snap = build_snapshot(
            self.scan_root,
            policy=self.policy,
            ignore=self.ignore,
            watch=self.watch,
            exceptions_path=getattr(self, "exceptions_path", None),
        )
        self.snapshot = snap
        return snap


def _handler_class() -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server: BomHTTPServer

        def log_message(self, fmt: str, *args: Any) -> None:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

        def handle_one_request(self) -> None:
            mark_access_start(self)
            super().handle_one_request()

        def _cors_headers(self) -> dict[str, str]:
            origin = request_origin(self.headers)
            return cors_response_headers(origin, self.server.cors)

        def _resolve_request_id(self) -> str:
            cached = getattr(self, "_cached_request_id", None)
            if cached:
                return cached
            rid = resolve_request_id(self.headers)
            self._cached_request_id = rid
            return rid

        def _merge_response_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
            # CORS first; extra wins on collision; X-Request-Id last.
            merged = {**self._cors_headers()}
            if extra:
                merged.update(extra)
            merged[REQUEST_ID_HEADER] = self._resolve_request_id()
            return merged

        def _bom_for_request(self, parsed) -> dict[str, Any]:
            """Snapshot BOM, or un-waived copy when `?exceptions=` skip."""
            bom = self.server.snapshot["bom"]
            qs = parse_qs(parsed.query)
            present = "exceptions" in qs
            raw = (qs.get("exceptions") or [""])[0]
            if exceptions_query_skips(raw, present=present):
                return bom_without_exceptions(bom)
            return bom

        def _rate_limit_or_reject(self, path: str) -> bool:
            """Apply per-IP sliding window. True if 429 already sent."""
            if skip_rate_limit(path):
                return False
            limiter: SlidingWindowRateLimiter | None = getattr(
                self.server, "rate_limiter", None
            )
            if limiter is None:
                return False
            limit = getattr(self.server, "rate_limit", None)
            ip = client_ip_from_handler(self)
            allowed, retry_after = limiter.check(ip, limit)
            if allowed:
                return False
            self._send_json(
                429,
                {"ok": False, "reason": "rate_limited"},
                extra_headers={"Retry-After": str(retry_after)},
            )
            return True

        def _send(
            self,
            status: int,
            body: str | bytes,
            content_type: str,
            *,
            head_only: bool = False,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            payload = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            extra = self._merge_response_headers(extra_headers)
            for k, v in extra.items():
                self.send_header(k, v)
            self.end_headers()
            if not head_only:
                self.wfile.write(payload)
            emit_access_log(self, service="ai-bom", status=status, bytes_out=len(payload))

        def _send_json(
            self,
            status: int,
            obj: dict[str, Any],
            *,
            head_only: bool = False,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            self._send(
                status,
                json.dumps(obj, indent=2, ensure_ascii=False) + "\n",
                "application/json; charset=utf-8",
                head_only=head_only,
                extra_headers=extra_headers,
            )

        def _dispatch(self, *, head_only: bool) -> None:
            parsed = urlparse(self.path or "/")
            path = parsed.path or "/"
            if self._rate_limit_or_reject(path):
                return
            snap = self.server.snapshot
            if path == "/health":
                if getattr(self.server, "shutting_down", False):
                    health = dict(snap["health"])
                    health["shuttingDown"] = True
                    self._send_json(200, health, head_only=head_only)
                else:
                    self._send(
                        200,
                        snap["health_text"],
                        "application/json; charset=utf-8",
                        head_only=head_only,
                    )
                return
            if path == "/ready":
                # Shutdown 503 wins over healthy 200. Snapshot service has no circuit/queue.
                if getattr(self.server, "shutting_down", False):
                    self._send_json(
                        503, {"ok": False, "reason": "shutting_down"}, head_only=head_only
                    )
                    return
                self._send(
                    200,
                    snap["health_text"],
                    "application/json; charset=utf-8",
                    head_only=head_only,
                )
                return
            if path == "/bom.json":
                bom = self._bom_for_request(parsed)
                body = snap["bom_text"] if bom is snap["bom"] else dumps_bom(bom)
                self._send(
                    200,
                    body,
                    "application/json; charset=utf-8",
                    head_only=head_only,
                )
                return
            if path == "/v1/bom.sarif":
                bom = self._bom_for_request(parsed)
                self._send(
                    200,
                    dumps_export(bom, "sarif"),
                    content_type_for("sarif"),
                    head_only=head_only,
                )
                return
            if path == "/v1/bom.xml":
                bom = self._bom_for_request(parsed)
                self._send(
                    200,
                    dumps_export(bom, "cyclonedx-xml"),
                    content_type_for("cyclonedx-xml"),
                    head_only=head_only,
                )
                return
            if path == "/v1/bom.spdx.xml":
                bom = self._bom_for_request(parsed)
                self._send(
                    200,
                    dumps_export(bom, "spdx-xml"),
                    content_type_for("spdx-xml"),
                    head_only=head_only,
                )
                return
            if path == "/v1/bom.md":
                bom = self._bom_for_request(parsed)
                self._send(
                    200,
                    dumps_export(bom, "md"),
                    content_type_for("md"),
                    head_only=head_only,
                )
                return
            if path == "/v1/bom.html":
                bom = self._bom_for_request(parsed)
                self._send(
                    200,
                    dumps_export(bom, "html"),
                    content_type_for("html"),
                    head_only=head_only,
                )
                return
            if path == "/v1/bom.gha.txt":
                bom = self._bom_for_request(parsed)
                self._send(
                    200,
                    dumps_export(bom, "gha"),
                    content_type_for("gha"),
                    head_only=head_only,
                )
                return
            if path == "/v1/bom":
                raw_fmt = (parse_qs(parsed.query).get("format") or ["json"])[0]
                fmt = normalize_format(raw_fmt)
                if fmt is None:
                    self._send_json(
                        400,
                        {
                            "error": "bad_format",
                            "detail": f"format must be {FORMATS_HELP}",
                        },
                        head_only=head_only,
                    )
                    return
                bom = self._bom_for_request(parsed)
                self._send(
                    200,
                    dumps_export(bom, fmt),
                    content_type_for(fmt),
                    head_only=head_only,
                )
                return
            if path == "/v1/policy":
                bom = snap.get("bom") or {}
                meta = bom.get("metadata") or {}
                gate = build_policy_gate(
                    getattr(self.server, "policy", None),
                    scan_root=getattr(self.server, "scan_root", None),
                    exceptions_path=getattr(self.server, "exceptions_path", None),
                    exceptions_count=meta.get("exceptionsCount"),
                )
                self._send_json(200, gate, head_only=head_only)
                return
            if path == "/v1/config":
                # Public redacted runtime knobs (not the policy dump). Allowlist only.
                # Never webhook URL/secret, full policy JSON, or exception contents.
                cors = getattr(self.server, "cors", None)
                if cors and cors.get("allow_any"):
                    origins = ["*"]
                else:
                    origins = list((cors or {}).get("origins") or [])
                payload = summarize_runtime_config(
                    rate_limit=getattr(self.server, "rate_limit", None),
                    cors_origins=origins,
                    watch=bool(getattr(self.server, "watch", False)),
                    scan_path=getattr(self.server, "scan_root", None),
                    has_policy_file=bool(getattr(self.server, "has_policy_file", False)),
                    webhook_url=getattr(self.server, "webhook_url", None),
                    webhook_secret=getattr(self.server, "webhook_secret", None),
                )
                self._send_json(200, payload, head_only=head_only)
                return
            if path == "/v1/components":
                # Lightweight inventory from the last scan (not CycloneDX/SPDX).
                qs = parse_qs(parsed.query)
                lic = (qs.get("license") or [""])[0]
                payload = list_components(
                    snap.get("bom") or {},
                    license=lic or None,
                    scan_root=getattr(self.server, "scan_root", None),
                )
                self._send_json(200, payload, head_only=head_only)
                return
            if path == "/v1/exceptions":
                # Public redacted waiver inventory (not the sidecar dump).
                qs = parse_qs(parsed.query)
                expired_raw = (qs.get("expired") or [None])[0] if "expired" in qs else None
                root = getattr(self.server, "scan_root", None)
                loaded = collect_exceptions(
                    Path(root) if root is not None else Path("."),
                    extra_path=getattr(self.server, "exceptions_path", None),
                    warn=False,
                )
                payload = exceptions_json(loaded, expired=expired_raw)
                self._send_json(200, payload, head_only=head_only)
                return
            if path == "/evidence.md":
                self._send(
                    200,
                    snap["evidence"],
                    "text/markdown; charset=utf-8",
                    head_only=head_only,
                )
                return
            if path in ("/", "/index.html"):
                self._send(
                    200,
                    snap["html"],
                    "text/html; charset=utf-8",
                    head_only=head_only,
                )
                return
            if path == "/metrics":
                self._send(
                    200,
                    snap["metrics_text"],
                    METRICS_CONTENT_TYPE,
                    head_only=head_only,
                )
                return
            if path == "/openapi.json":
                try:
                    raw = load_openapi_bytes()
                except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
                    self._send_json(
                        500,
                        {"error": "openapi_unavailable", "detail": str(e)},
                        head_only=head_only,
                    )
                    return
                self._send(
                    200,
                    raw,
                    "application/json; charset=utf-8",
                    head_only=head_only,
                )
                return
            self._send_json(404, {"error": "not_found", "path": path}, head_only=head_only)

        def do_OPTIONS(self) -> None:  # noqa: N802
            parsed = urlparse(self.path or "/")
            path = parsed.path or "/"
            origin = request_origin(self.headers)
            pf = handle_preflight(origin, self.server.cors)
            if pf is None:
                # CORS disabled: no extra CORS; same 404 as unknown paths.
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
            self._dispatch(head_only=False)

        def do_HEAD(self) -> None:  # noqa: N802
            self._dispatch(head_only=True)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path or "/")
            path = parsed.path or "/"
            if self._rate_limit_or_reject(path):
                return
            self._send_json(405, {"error": "method_not_allowed"})

    return Handler


def create_bom_server(
    path: Path,
    *,
    policy: dict[str, Any] | None = None,
    ignore: list[str] | None = None,
    exceptions_path: str | None = None,
    host: str = DEFAULT_SERVE_HOST,
    port: int = DEFAULT_SERVE_PORT,
    cors_origins: list[str] | None = None,
    watch: bool = False,
    log_json: bool = False,
    rate_limit: int | None | object = ...,
    webhook_url: str | None = None,
    webhook_secret: str | None = None,
) -> tuple[BomHTTPServer, dict[str, Any]]:
    snapshot = build_snapshot(
        path, policy=policy, ignore=ignore, watch=watch, exceptions_path=exceptions_path
    )
    httpd = BomHTTPServer((host, port), _handler_class())
    httpd.snapshot = snapshot
    httpd.cors = normalize_cors(cors_origins)
    httpd.scan_root = path
    httpd.policy = policy
    httpd.ignore = ignore
    httpd.exceptions_path = exceptions_path
    httpd.watch = watch
    httpd.shutting_down = False
    httpd.log_json = bool(log_json)
    if rate_limit is ...:
        httpd.rate_limit = resolve_rate_limit()
    else:
        httpd.rate_limit = rate_limit  # type: ignore[assignment]
    httpd.rate_limiter = SlidingWindowRateLimiter()
    httpd.webhook_url = parse_webhook_url(webhook_url)
    httpd.webhook_secret = parse_webhook_secret(webhook_secret)
    httpd.has_policy_file = policy is not None
    return httpd, snapshot


def serve_forever(
    *,
    path: Path,
    host: str = DEFAULT_SERVE_HOST,
    port: int = DEFAULT_SERVE_PORT,
    policy: dict[str, Any] | None = None,
    ignore: list[str] | None = None,
    exceptions_path: str | None = None,
    cors_origins: list[str] | None = None,
    watch: bool = False,
    drain_ms: int | None = None,
    log_json: bool = False,
    rate_limit: int | None | object = ...,
    webhook_url: str | None | object = ...,
    webhook_secret: str | None | object = ...,
) -> None:
    if webhook_url is ...:
        webhook_url = resolve_webhook_url(None)
    if webhook_secret is ...:
        webhook_secret = resolve_webhook_secret(None)
    httpd, _snap = create_bom_server(
        path,
        policy=policy,
        ignore=ignore,
        exceptions_path=exceptions_path,
        host=host,
        port=port,
        cors_origins=cors_origins,
        watch=watch,
        log_json=log_json,
        rate_limit=rate_limit,
        webhook_url=webhook_url,  # type: ignore[arg-type]
        webhook_secret=webhook_secret,  # type: ignore[arg-type]
    )
    cors_note = ",".join(cors_origins) if cors_origins else "deny"
    limit_note = httpd.rate_limit if httpd.rate_limit is not None else "unlimited"
    print(f"ai-bom listening on http://{host}:{port}")
    print(f"path={path}")
    print("GET /health  GET /ready  GET /  GET /bom.json  GET /v1/bom?format=json|cyclonedx|cyclonedx-xml|spdx|spdx-xml|sarif|md|gha|html  GET /v1/bom.xml  GET /v1/bom.spdx.xml  GET /v1/bom.sarif  GET /v1/bom.md  GET /v1/bom.gha.txt  GET /v1/bom.html  GET /v1/policy  GET /v1/config  GET /v1/components  GET /v1/exceptions  GET /evidence.md  GET /openapi.json  GET /metrics")
    print(f"cors={cors_note}")
    print(f"rate_limit_per_minute={limit_note}")
    print(f"watch={'poll %dms' % WATCH_POLL_MS if watch else 'off'}")
    print("hosted inventory = paid later (this local serve is OSS)")
    sys.stdout.flush()

    stop = threading.Event()
    httpd.watch_stop = stop
    if watch:
        start_path_watch(path, reload=httpd.reload_snapshot, stop_event=stop)

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
            import time

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


def load_serve_policy(policy_path: str | None) -> tuple[dict[str, Any] | None, str | None]:
    if not policy_path:
        return None, None
    try:
        return load_policy(Path(policy_path)), None
    except OSError as e:
        return None, f"policy IO error: {e}"
    except (ValueError, json.JSONDecodeError) as e:
        return None, f"policy parse error: {e}"


def parse_serve_ignore(ignore: str | None) -> list[str] | None:
    parsed = parse_ignore_arg(ignore)
    return parsed or None
