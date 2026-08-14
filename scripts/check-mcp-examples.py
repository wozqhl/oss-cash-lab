#!/usr/bin/env python3
"""Parse-only check for examples/mcp HTTP MCP client config (no Cursor, no B).

JSON must parse, have mcpServers, url with 8787 and /mcp, Bearer placeholder,
no stdio command, no SSE, no real-looking secrets (sk-live). README must
mention POST-only / GET 405 / make stack-demo.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SECRET_RE = re.compile(
    r"sk-live|sk-ant-|github_pat_|AKIA[0-9A-Z]{16}"
    r"|BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY|xox[baprs]-",
    re.I,
)
PLACEHOLDER_RE = re.compile(
    r"^Bearer\s+(\$\{(?:env:)?[A-Z][A-Z0-9_]*\}|change-me)$"
)

README_NEEDLES = (
    "mcpServers",
    "http://127.0.0.1:8787/mcp",
    "make stack-demo",
    "GET /mcp",
    "405",
    "sk-live",
    "MCP_GATEWAY_TOKEN",
)


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def check_secrets(text: str, label: str) -> None:
    m = SECRET_RE.search(text)
    if m:
        fail(f"{label}: real-looking secret pattern {m.group(0)!r}")


def check_entry(name: str, entry: dict) -> None:
    if not isinstance(entry, dict):
        fail(f"mcpServers[{name!r}] must be an object")
    if "command" in entry:
        fail(f"mcpServers[{name!r}] is HTTP; must not set command (stdio is A)")
    typ = entry.get("type")
    if typ is not None:
        t = str(typ).lower()
        if t in ("sse", "event-stream"):
            fail(f"mcpServers[{name!r}] type {typ!r} is SSE; B GET /mcp is 405")
        if t not in ("http", "streamable-http", "streamable_http"):
            fail(f"mcpServers[{name!r}] type {typ!r} must be http if set")
    url = entry.get('url')
    if not isinstance(url, str) or not url.strip():
        fail(f"mcpServers[{name!r}] missing url")
    if "8787" not in url:
        fail(f"mcpServers[{name!r}] url must include port 8787: {url!r}")
    if "/mcp" not in url:
        fail(f"mcpServers[{name!r}] url must include /mcp: {url!r}")
    if "/sse" in url.lower():
        fail(f"mcpServers[{name!r}] url must not be an SSE path: {url!r}")
    headers = entry.get("headers")
    if not isinstance(headers, dict) or not headers:
        fail(f"mcpServers[{name!r}] missing headers")
    auth = headers.get("Authorization") or headers.get("authorization")
    if not isinstance(auth, str):
        fail(f"mcpServers[{name!r}] missing Authorization header")
    if not PLACEHOLDER_RE.match(auth.strip()):
        fail(
            f"mcpServers[{name!r}] Authorization must be Bearer placeholder "
            f"(${{env:NAME}} / ${{NAME}} / change-me), got {auth!r}"
        )


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
    examples = root / "examples" / "mcp"
    cfg = examples / "gateway.mcp.json"
    readme = examples / "README.md"
    if not cfg.is_file():
        fail(f"missing {cfg}")
    if not readme.is_file():
        fail(f"missing {readme}")

    raw = cfg.read_text(encoding="utf-8")
    check_secrets(raw, str(cfg.relative_to(root)))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        fail(f"{cfg.name}: JSON.parse failed: {e}")
    if not isinstance(data, dict):
        fail(f"{cfg.name}: expected object")
    servers = data.get("mcpServers")
    if not isinstance(servers, dict) or not servers:
        fail(f"{cfg.name}: missing non-empty mcpServers")
    if "oss-cash-lab-gateway" not in servers:
        fail(f"{cfg.name}: missing mcpServers.oss-cash-lab-gateway")
    for name, entry in servers.items():
        check_entry(name, entry)
        print(f"  ok {cfg.name}  {name}  url={entry.get('url')}")

    md = readme.read_text(encoding="utf-8")
    check_secrets(md.replace("sk-live", ""), str(readme.relative_to(root)))
    for needle in README_NEEDLES:
        if needle not in md:
            fail(f"examples/mcp/README.md missing {needle!r}")
    lower = md.lower()
    if "sse" not in lower:
        fail("examples/mcp/README.md must say B is not SSE")
    if "stdio" not in lower:
        fail("examples/mcp/README.md must contrast stdio vs url")
    print("  ok README.md  needles + POST-only/no-SSE")
    print("mcp examples ok")


if __name__ == "__main__":
    main()
