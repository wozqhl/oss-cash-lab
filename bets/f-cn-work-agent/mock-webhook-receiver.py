#!/usr/bin/env python3
"""Tiny mock HTTP webhook receiver for F cn-work-agent local-mvp.

Writes the last POST body to --out (default data/webhook-last.json).
Optional --secret: verify X-Webhook-Signature HMAC-SHA256 of the raw body.
Optional --headers-out: persist last request headers (+ verified flag + timestamp).
Records X-Webhook-Timestamp when present (OSS; replay window = paid).

  python3 mock-webhook-receiver.py --port 8810 --out data/webhook-last.json
  python3 mock-webhook-receiver.py --port 8812 --secret whsec_local_mvp \
    --out data/webhook-hmac-last.json --headers-out data/webhook-hmac-last.headers.json
"""
from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

# Allow running from bet root without PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from cn_work_agent.webhook import SIGNATURE_HEADER, TIMESTAMP_HEADER, verify_webhook_signature  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(prog="mock-webhook-receiver")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8810)
    parser.add_argument("--out", default="data/webhook-last.json")
    parser.add_argument(
        "--headers-out",
        default=None,
        help="Write last request headers JSON (signature + verified). "
        "Default: <out>.headers.json when --secret is set.",
    )
    parser.add_argument(
        "--secret",
        default=None,
        help="HMAC-SHA256 key; verify X-Webhook-Signature of the raw body. "
        "Empty/omit = accept unsigned.",
    )
    args = parser.parse_args()
    out = Path(args.out)
    if not out.is_absolute():
        out = Path.cwd() / out
    out.parent.mkdir(parents=True, exist_ok=True)

    secret = str(args.secret).strip() if args.secret else None
    secret = secret or None

    headers_out = args.headers_out
    if headers_out:
        headers_abs = Path(headers_out)
        if not headers_abs.is_absolute():
            headers_abs = Path.cwd() / headers_abs
    elif secret:
        name = out.name
        if name.endswith(".json"):
            headers_abs = out.with_name(name[: -len(".json")] + ".headers.json")
        else:
            headers_abs = out.with_name(name + ".headers.json")
    else:
        headers_abs = None
    if headers_abs is not None:
        headers_abs.parent.mkdir(parents=True, exist_ok=True)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *a) -> None:  # noqa: A002
            print("%s - %s" % (self.address_string(), fmt % a), flush=True)

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/health":
                body = json.dumps({"ok": True, "service": "mock-webhook-receiver"}).encode(
                    "utf-8"
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            body = b'{"error":"not_found"}'
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length) if length else b""
            sig_header = self.headers.get(SIGNATURE_HEADER) or ""
            ts_header = self.headers.get(TIMESTAMP_HEADER) or ""
            verified = None
            if secret:
                verified = verify_webhook_signature(secret, raw, sig_header)
            try:
                out.write_bytes(raw if raw else b"")
                if headers_abs is not None:
                    meta = {
                        "signature": sig_header or None,
                        "timestamp": ts_header or None,
                        "verified": verified,
                        "headers": {k: v for k, v in self.headers.items()},
                    }
                    headers_abs.write_text(
                        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
                    )
            except OSError as e:
                msg = json.dumps({"ok": False, "error": str(e)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)
                return
            if secret and verified is False:
                deny = json.dumps(
                    {
                        "ok": False,
                        "error": "invalid_signature",
                        "received": True,
                        "verified": False,
                        "bytes": len(raw),
                    }
                ).encode("utf-8")
                self.send_response(401)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(deny)))
                self.end_headers()
                self.wfile.write(deny)
                return
            ack = json.dumps(
                {
                    "ok": True,
                    "received": True,
                    "bytes": len(raw),
                    "verified": verified,
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(ack)))
            self.end_headers()
            self.wfile.write(ack)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    extra = ""
    if secret:
        extra += " verify=hmac"
    if headers_abs is not None:
        extra += f" headers={headers_abs}"
    print(
        f"mock-webhook-receiver listening on http://{args.host}:{args.port} out={out}{extra}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
