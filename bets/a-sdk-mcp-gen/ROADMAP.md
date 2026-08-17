# ROADMAP · A · sdk-mcp-gen

Bet-local. Portfolio root ROADMAP is updated separately.

## Shipped here

- [x] Composite Action (action.yml; spec and/or URL, output, optional langs; runs existing CLI)
- [x] Example workflow + artifact upload (examples/github-actions/sdk-mcp-gen-generate.yml)
- [x] docs/vs-stainless.md (Stainless hosted wound down May 2026; Speakeasy + Fern/Postman remain; no fake numbers)
- [x] Publish-ready package.json + PUBLISH.md (checklist for io.github.wozqhl/sdk-mcp-gen; do not upload from this tree)
- [x] Drift-check example remains CHECK only (examples/github-actions/sdk-mcp-gen-check.yml)
- [x] Generated TS / Python / Go clients retry transient HTTP (429 / 5xx / network; max 2 retries; Retry-After <30s)

## Still open

- [ ] Demo script in README (MVP checklist leftover)
- [ ] Human upload of @oss-cash-lab/sdk-mcp-gen (needs org / access)
- [ ] Human MCP Registry listing of a generated server under io.github.wozqhl/sdk-mcp-gen (wrap mcp-server.mjs; do not list this CLI as stdio)
- [ ] Copy action.yml into a standalone repo if this bet is extracted
