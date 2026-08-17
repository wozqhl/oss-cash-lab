# Changelog · B · mcp-gateway

Bet-local notes. Portfolio root CHANGELOG is updated separately.

The format is based on Keep a Changelog.

## [Unreleased]

### Added

- Conservative stdlib payload redactor (`src/redact.js`): emails, Bearer tokens, `sk-`/`ghp_`-like prefixes, long hex/base64-ish secrets. Policy `redact: { enabled, fields, upstream }`. Default: audit JSONL + webhook payloads redacted; upstream `tools/call` body not mutated unless `redact.upstream=true`. Regex only — not Microsoft Presidio.
- docs/vs-gateways.md comparison matrix vs microsoft/mcp-gateway, agentgateway, IBM ContextForge, AWS AgentCore.
- README callout: not microsoft/mcp-gateway. Suggested public name oss-mcp-gateway.

### Documented

- GET /admin/audit tenant query filter (already in server.js). Admin token, empty 200 for unknown tenant, no secret leakage. OpenAPI plus smoke.
