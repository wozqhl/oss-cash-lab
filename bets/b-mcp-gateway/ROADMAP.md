# ROADMAP · B · mcp-gateway

Bet-local. Portfolio root ROADMAP is updated separately.

## Shipped here

- [x] Local Node MCP gateway: static allow/deny, tenant API keys, rate limit, JSONL audit, HTTP/stdio upstream, circuit breaker
- [x] Streamable HTTP MVP (POST /mcp JSON-RPC + session; GET /mcp 405; no SSE)
- [x] Audit export packs + admin SIEM CSV/Markdown/HTML
- [x] Outbound audit webhooks (fire-and-forget, 1 retry, optional HMAC)
- [x] GET /admin/audit tenant-scoped admin list (admin token; empty 200 for unknown tenant)
- [x] docs/vs-gateways.md vs Microsoft / agentgateway / ContextForge / AgentCore
- [x] README name-collision callout (not microsoft/mcp-gateway)

## Still open

- [ ] Public name if extracted (oss-mcp-gateway / cash-mcp-gateway) — do not rename this directory from the roadmap
- [ ] Full Streamable HTTP SSE (explicitly out of the current MVP)
- [ ] Webhook exponential backoff / queues / HMAC key rotation / replay window (paid later)
- [ ] SSO / SAML / Entra (not in this tree; Microsoft already owns that shape)

## Paid later (not this tree)

- Hosted control plane, quota packs, compliance export, SLA
- Do not add OPA/WASM just to match incumbents
