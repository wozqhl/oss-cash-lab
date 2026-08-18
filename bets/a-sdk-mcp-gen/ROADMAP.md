# ROADMAP · A · sdk-mcp-gen

Bet-local. Portfolio root ROADMAP is updated separately.

## Shipped here

- [x] Composite Action (action.yml; spec and/or URL, output, optional langs; runs existing CLI)
- [x] Example workflow + artifact upload (examples/github-actions/sdk-mcp-gen-generate.yml)
- [x] docs/vs-stainless.md (Stainless hosted wound down May 2026; Speakeasy + Fern/Postman remain; no fake numbers)
- [x] Publish-ready package.json + PUBLISH.md (checklist for io.github.wozqhl/sdk-mcp-gen; do not upload from this tree)
- [x] Drift-check example remains CHECK only (examples/github-actions/sdk-mcp-gen-check.yml)
- [x] Generated TS / Python / Go clients retry transient HTTP (429 / 5xx / network; max 2 retries; Retry-After <30s)
- [x] Generated TS / Python / Go iterate* page helpers (page/cursor; cap 1000; existing names unchanged)
- [x] Generated TS / Python / Go request timeout (default 10s; constructor / SDK_TIMEOUT_MS / SDK_TIMEOUT_SEC; per attempt so retry still works)
- [x] Generated TS / Python / Go + MCP servers send OpenAPI auth per operation `security` (http bearer, apiKey header/query; env SDK_* / MCP_*; optional attach-if-set; unsecured ops omit credentials; oauth2 / openIdConnect skipped)
- [x] Demo script in README (`scripts/demo.sh` generates petstore SDK+MCP into out/demo and prints client.ts / mcp-server.mjs / mcp.json)
- [x] Generated Java / Kotlin / C# clients: per-attempt timeout + 429/5xx/network retry (Retry-After <30s) + per-op bearer/apiKey auth (same policy as TS/Python/Go)
- [x] Generated Java / Kotlin / C# iterate* page helpers (page/cursor; cap 1000; existing names unchanged)

- [x] Generated Rust / PHP / Swift / Ruby clients: per-attempt timeout + 429/5xx/network retry (Retry-After <30s) + per-op bearer/apiKey auth (same policy as TS/Python/Go/Java; Rust http:// TcpStream, no TLS)

- [x] Generated clients send default User-Agent `sdk-mcp-gen/0.1.0` (or package name) unless already set, plus `X-Request-Id` new per HTTP attempt (pin via constructor / `SDK_REQUEST_ID`)

- [x] Generated clients send Idempotency-Key on POST/PUT/PATCH/DELETE when unset (new key per logical call; retries reuse; pin via constructor / `SDK_IDEMPOTENCY_KEY`)

## Still open

- [ ] Human upload of @oss-cash-lab/sdk-mcp-gen (needs org / access)
- [ ] Human MCP Registry listing of a generated server under io.github.wozqhl/sdk-mcp-gen (wrap mcp-server.mjs; do not list this CLI as stdio)
- [ ] Copy action.yml into a standalone repo if this bet is extracted
