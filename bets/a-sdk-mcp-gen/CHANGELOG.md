# Changelog · A · sdk-mcp-gen

Bet-local notes. Portfolio root CHANGELOG is updated separately.

The format is based on Keep a Changelog.

## [Unreleased]

### Added

- Generated stdio MCP servers send User-Agent / X-Request-Id / Idempotency-Key on tools/call upstream HTTP. Smoke prints mcp-id-ok.

- Generated TS / Python / Go / Java (plus other langs) clients send `Idempotency-Key` on POST/PUT/PATCH/DELETE when unset. New key per logical call (retries reuse). Constructor / env `SDK_IDEMPOTENCY_KEY` pins a test key. Smoke prints idem-ok.

- Generated TS / Python / Go / Java (plus Kotlin / C# / Rust / PHP / Swift / Ruby) clients send default User-Agent `sdk-mcp-gen/0.1.0` (or package name) unless already set, and `X-Request-Id` new per HTTP attempt (constructor / env `SDK_REQUEST_ID` pins a test id). Smoke prints ua-ok / request-id-ok.

- Generated Rust / PHP / Swift / Ruby clients retry 429 / 5xx / network (Retry-After <30s), apply a per-attempt timeout (default 10s; SDK_TIMEOUT_MS / SDK_TIMEOUT_SEC), and send per-operation OpenAPI auth (http bearer, apiKey header/query). Stdlib only. Public method names unchanged. Rust stays TcpStream http:// (no TLS). Smoke prints rust-auth-ok, php-auth-ok.
- Generated Java / Kotlin / C# clients add iterate* helpers for GET ops with page / pageSize / offset / limit / cursor / starting_after. Follows next / next_cursor / nextPageToken or increments page until empty/short. Cap 1000. Existing operation / MCP tool names unchanged. Not a Stainless pager. Smoke prints java-page-ok.
- Generated Java / Kotlin / C# clients retry 429 / 5xx / network (Retry-After <30s), apply a per-attempt timeout (default 10s; SDK_TIMEOUT_MS / SDK_TIMEOUT_SEC), and send per-operation OpenAPI auth (http bearer, apiKey header/query). Stdlib only. Public method names unchanged.
- Demo script: `scripts/demo.sh` generates the petstore SDK+MCP into `out/demo` and prints `client.ts`, `mcp-server.mjs`, `mcp.json`.
- Generated TypeScript / Python / Go clients and stdio MCP servers send OpenAPI auth per operation `security` (http bearer, apiKey header/query; optional attach-if-set; unsecured ops omit credentials even when the client has a token). Constructor bearerToken / apiKey or env SDK_BEARER_TOKEN / SDK_API_KEY (MCP also MCP_*). oauth2 / openIdConnect skipped. Values never logged. Smoke prints auth-ok, auth-op-ok.
- Smoke runs `npm pack` in a temp dir (`pack-ok`); local proof the tarball lists `package/src/cli.js`. Publish still manual.

- Generated TypeScript / Python / Go clients apply a per-attempt request timeout (default 10s; AbortController / urllib timeout / context.WithTimeout). Override via constructor option (`timeoutMs` / `timeout` / `Client.Timeout`) or env `SDK_TIMEOUT_MS` / `SDK_TIMEOUT_SEC`. Stdlib only. Public method / MCP tool names unchanged. Retry still applies per attempt.
- Generated TypeScript / Python / Go clients add iterate* helpers for GET ops with page / pageSize / offset / limit / cursor / starting_after query params. Follows next / next_cursor / nextPageToken or increments page until empty/short. Cap 1000. Existing operation / MCP tool names unchanged. Not a Stainless pager.
- Generated TypeScript / Python / Go clients retry 429, 5xx, and network throws (max 2 retries / 3 attempts, ~100ms exponential backoff, honor Retry-After when under 30s). Stdlib only. Public method / MCP tool names unchanged.
- Composite GitHub Action at action.yml (spec path and/or url, output dir, optional langs).
  Consumers: uses wozqhl/oss-cash-lab/bets/a-sdk-mcp-gen@main. Fails on CLI error. Not the drift-check example.
- Copy-paste workflow examples/github-actions/sdk-mcp-gen-generate.yml plus upload-artifact@v4.
- docs/vs-stainless.md: honest comparison vs OpenAPI Generator, Speakeasy, Stainless hosted (wound down after Anthropic acquisition, May 2026). One reproduce command.
- Publish-ready package.json fields (repository, bugs, homepage, files, keywords). PUBLISH.md for npm pack + official publisher steps for io.github.wozqhl/sdk-mcp-gen. No registry upload from this tree. No mcpName / live server.json on this generator package (it is not a stdio MCP server). Generated-example pointer: petstore mcp-server.mjs / mcp.json.
