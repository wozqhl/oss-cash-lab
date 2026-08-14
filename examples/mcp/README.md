# MCP client config · B gateway (HTTP JSON-RPC)

Paste-ready **client** snippet so Cursor / Claude Desktop / Claude Code talk to **bet B** over Streamable HTTP — not stdio.

Last-mile demo: **client → B `:8787/mcp` → mock upstream**. This repo does **not** enable a live Cursor connection. Copy the JSON into your own MCP servers config; do not commit real tokens.

A's generated `mcp.json` uses `mcpServers.*.command` (stdio child process). **This file uses `url`.** B speaks HTTP JSON-RPC to MCP **clients**; B's own upstreams may still be HTTP or stdio (`upstream.type`). The client does not spawn `node mcp-server.mjs`.

## Config shape

[`gateway.mcp.json`](./gateway.mcp.json):

```json
{
  "mcpServers": {
    "oss-cash-lab-gateway": {
      "url": "http://127.0.0.1:8787/mcp",
      "headers": {
        "Authorization": "Bearer ${env:MCP_GATEWAY_TOKEN}"
      }
    }
  }
}
```

Verified keys (Cursor remote MCP, 2026): top-level `mcpServers`; remote servers use **`url`** + optional **`headers`**. Presence of `url` means HTTP (not `command`). Cursor interpolates `${env:NAME}` in `url` and `headers`. Some Claude clients use `${MCP_GATEWAY_TOKEN}` instead — swap the placeholder if interpolation differs. Optional `"type": "http"` if a client requires it. **Do not** set `"type": "sse"`.

B also accepts `X-Api-Key` (same tenant key). Bearer is enough.

## POST-only (no SSE)

B Streamable HTTP MVP is POST JSON-RPC on /mcp (alias POST /) plus DELETE /mcp to terminate a session. GET /mcp returns 405 Allow: POST, DELETE. There is no hanging text/event-stream. Clients that probe SSE on GET will fail; they must POST initialize / tools/list / tools/call. DELETE with Mcp-Session-Id returns 204 (missing header 400).

## Start B (plus mock upstream)

Gateway listen port 8787. Default policy.json has tenants but no upstream. For the last-mile demo, run the portfolio stack or the B CLI with an upstream pointed at mock-upstream port 8788.

Use make stack-demo (or scripts/local-stack.sh). That materializes policy with upstream.type=http at mock-upstream 8788 and listens on 8787.

From bets/b-mcp-gateway the package start script uses port 8787 and config/policy.json. Isolated B without upstream still exposes local tools (echo, digest) on POST /mcp.

B CLI (from bets/b-mcp-gateway): `node src/cli.js serve --port 8787 --config config/policy.json`. Mock upstream: `node mock-upstream.js --port 8788`.

Health check: http://127.0.0.1:8787/health. Prove: GET /mcp is 405 Allow: POST, DELETE (not SSE).

## Tenant token

Set MCP_GATEWAY_TOKEN from an example tenant apiKey in bets/b-mcp-gateway/config/policy.json (or policy.compose.json / stack-demo materialized policy). Tenant acme is ten_acme_dev (loopback ipAllowlist includes 127.0.0.1).

    export MCP_GATEWAY_TOKEN=ten_acme_dev

The committed JSON keeps ${env:MCP_GATEWAY_TOKEN} (or locally change-me) — not a live secret. Do not paste sk-live keys. Unknown key returns 401. Same header as REST: Authorization Bearer or X-Api-Key.

## Where to put it

Merge mcpServers into your MCP servers config JSON:

- Cursor: .cursor/mcp.json (project) or ~/.cursor/mcp.json (user)
- Claude Desktop / Claude Code: the same mcpServers object in that product MCP config file

Do not follow invented Settings click-paths; the file is the source of truth.

## Prove

scripts/check-mcp-examples.sh (hooked from make smoke / make check-mcp-examples): JSON.parse; has mcpServers; url contains 8787 and /mcp; no command on the HTTP entry; no SSE type; no real-looking secrets (sk-live). Does not start Cursor or B.

