# Changelog · B · mcp-gateway

Bet-local notes. Portfolio root CHANGELOG is updated separately.

The format is based on Keep a Changelog.

## [Unreleased]

### Fixed

- `scripts/local-mvp.sh`: the mock upstream no longer defaults to fixed port **8790**, which collides with other listeners on shared/CI hosts (e.g. `sand-egress-tun`; F cn-work-agent also serves on 8790) and left `GET /health` with `upstream.connected:false` / `fetch failed`. The script now auto-picks a free ephemeral port (override with `UPSTREAM_PORT=...`) and wires the same value into the mock upstream, the gateway `upstream.baseUrl`, and the startup health waits; the wait loop now fails fast with the mock-upstream log if the upstream process dies (e.g. `EADDRINUSE`). `mock-upstream.js` logs its actual bound port so `--port 0` works standalone. Health assertions unchanged.

### Added

- 429 `Retry-After` on rate-limited `POST /tools/call` (and Streamable HTTP `tools/call`). Remaining seconds until the oldest hit leaves the 60s window, min 1. Same header as 503 `circuit_open`. OpenAPI `RateLimited`. GET `/audit` already filtered by tenant/tool/since/until — no second audit filter.
- Conservative stdlib payload redactor (`src/redact.js`): emails, Bearer tokens, `sk-`/`ghp_`-like prefixes, long hex/base64-ish secrets. Policy `redact: { enabled, fields, upstream }`. Default: audit JSONL + webhook payloads redacted; upstream `tools/call` body not mutated unless `redact.upstream=true`. Regex only — not Microsoft Presidio.
- docs/vs-gateways.md comparison matrix vs microsoft/mcp-gateway, agentgateway, IBM ContextForge, AWS AgentCore.
- README callout: not microsoft/mcp-gateway. Suggested public name oss-mcp-gateway.

### Documented

- GET /admin/audit tenant query filter (already in server.js). Admin token, empty 200 for unknown tenant, no secret leakage. OpenAPI plus smoke.
