# sdk-mcp-gen vs Stainless / Speakeasy / OpenAPI Generator

Honest comparison. No download counts, GitHub stars, or official-listing claims.
Sources are dated; products move.

## Why this note exists

Anthropic announced it acquired Stainless on **18 May 2026**.
Anthropic told TechCrunch it would **wind down hosted Stainless products, including the SDK generator**.
Customers keep the SDKs they already generated and may modify them.
Treat the **hosted** Stainless generator as unavailable for new work as of that announcement.
This repo does not claim a final shutdown calendar date or a deal price (those were not in Anthropic's own post).

Speakeasy remains a commercial OpenAPI-native generator.
Fern remains a product; Postman acquired Fern in **January 2026** (Fern / Postman coverage; Speakeasy also notes this).
OpenAPI Generator remains the self-hosted open-source baseline.

Official MCP Registry (metadata only, not artifacts): https://registry.modelcontextprotocol.io
This tree does **not** publish there.

## What each tool is

| | sdk-mcp-gen (this repo) | OpenAPI Generator | Speakeasy | Stainless (hosted) | Fern (Postman) |
|---|---|---|---|---|---|
| Runs where | Local CLI / composite GitHub Action. Node 18+, stdlib only. | Self-hosted CLI (Java). | Commercial CLI / platform. Speakeasy documents a standalone binary. | Hosted platform. Wound down after the May 2026 acquisition. | Commercial SDK + docs platform (Postman). |
| Input | OpenAPI 3.0.x / 3.1.x (paths; cheap 3.1 diffs; webhooks ignored). | OpenAPI (broad). | OpenAPI-native (their docs). | API spec to hosted generate. | OpenAPI and/or Fern IDL (vendor docs). |
| Output | Stub clients in 10 langs + mcp-tools.json + stdio MCP (mcp-server.mjs / mcp_server.py / mcp_server.go) + mcp.json. | Many language generators (widest OSS coverage). | Idiomatic SDKs; MCP is a Speakeasy product surface, not something this note scores. | Idiomatic SDKs + MCP tooling (historical). Existing generated SDKs stay with customers. | Idiomatic SDKs + API docs. |
| Deps in generated clients | Stdlib-only stubs (no SDK runtime, no retry/auth stack). | Varies by generator; often a language HTTP stack. | Vendor-documented runtime (not measured here). | Vendor-documented (historical). | Vendor-documented. |
| Cost model | Apache-2.0 in this portfolio. | Apache-2.0. You maintain templates/forks. | Commercial (see their pricing). | Hosted product wound down. | Commercial (see Postman/Fern). |
| CI | Composite Action runs generate (this bet). Separate example checks drift. | Typical openapi-generator-cli job. | Vendor GitHub Action / CLI. | Hosted pipeline (historical). | Vendor pipeline. |

## What this generator is not

- Not a drop-in Stainless replacement. Stainless sold idiomatic, maintained SDKs. This emits minimal stubs plus MCP wiring.
- Not OpenAPI Generator. We do not wrap their templates or claim their language count.
- Not a hosted service. No SLA, no private registry, no official MCP listing.
- Not a full JSON Schema 2020-12 / OpenAPI 3.1 rewrite. See the A README.

## When to use which

- Need a local, no-network generate that also emits stdio MCP for an existing OpenAPI: this CLI.
- Need 20+ languages or a long-lived template fork: OpenAPI Generator.
- Need commercial idiomatic SDKs after Stainless hosted went away: Speakeasy or Fern/Postman (evaluate them yourself).
- Already have Stainless-generated SDKs: you own that code; this tool will not migrate it.

## Reproduce (one command)

Run from the bet directory with Node 18 or newer.

    node src/cli.js generate examples/petstore.openapi.json --out out/petstore

Expect out/petstore/client.ts, mcp-server.mjs, mcp.json, and checksums.sha256.
Same command the composite Action runs (action.yml).

Sources:

- Anthropic acquires Stainless (18 May 2026): anthropic.com/news/anthropic-acquires-stainless
- TechCrunch coverage of the acquisition and hosted wind-down (18 May 2026)
- MCP Registry quickstart: modelcontextprotocol.io/registry/quickstart
- Speakeasy / Fern public comparison posts (2026). Pricing and language counts change; look them up.
