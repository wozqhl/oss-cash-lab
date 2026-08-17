# Changelog · A · sdk-mcp-gen

Bet-local notes. Portfolio root CHANGELOG is updated separately.

The format is based on Keep a Changelog.

## [Unreleased]

### Added

- Generated TypeScript / Python / Go clients add iterate* helpers for GET ops with page / pageSize / offset / limit / cursor / starting_after query params. Follows next / next_cursor / nextPageToken or increments page until empty/short. Cap 1000. Existing operation / MCP tool names unchanged. Not a Stainless pager.
- Generated TypeScript / Python / Go clients retry 429, 5xx, and network throws (max 2 retries / 3 attempts, ~100ms exponential backoff, honor Retry-After when under 30s). Stdlib only. Public method / MCP tool names unchanged.
- Composite GitHub Action at action.yml (spec path and/or url, output dir, optional langs).
  Consumers: uses wozqhl/oss-cash-lab/bets/a-sdk-mcp-gen@main. Fails on CLI error. Not the drift-check example.
- Copy-paste workflow examples/github-actions/sdk-mcp-gen-generate.yml plus upload-artifact@v4.
- docs/vs-stainless.md: honest comparison vs OpenAPI Generator, Speakeasy, Stainless hosted (wound down after Anthropic acquisition, May 2026). One reproduce command.
- Publish-ready package.json fields (repository, bugs, homepage, files, keywords). PUBLISH.md for npm pack + official publisher steps for io.github.wozqhl/sdk-mcp-gen. No registry upload from this tree. No mcpName / live server.json on this generator package (it is not a stdio MCP server). Generated-example pointer: petstore mcp-server.mjs / mcp.json.
