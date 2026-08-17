# mcp-gateway vs other MCP gateways

Honest comparison of **this** Node policy/audit gateway (oss-cash-lab bet B,
package `@oss-cash-lab/mcp-gateway`) against category incumbents.

Columns are only features **this tree actually ships**. No SSO, OPA, WASM,
Entra, K8s control plane, or full-spec SSE are claimed here — those are
incumbent surfaces, not ours.

Sources are dated; products move. Star counts are search-collision context,
not a capability score.

## Name collision

The public short name `mcp-gateway` already belongs to
[microsoft/mcp-gateway](https://github.com/microsoft/mcp-gateway)
(~785 stars as of 17 Aug 2026): a **.NET / Kubernetes** reverse proxy with
**Entra ID** app-role auth and adapter lifecycle.

This repo is **not** that project. It is a single-process **Node 18+**
gateway: static allow/deny, tenant API keys, JSONL audit, Streamable HTTP
**MVP** (`POST /mcp` JSON-RPC, `GET /mcp` 405 — no SSE).

A 0-star repo named `wozqhl/mcp-gateway` loses every search to Microsoft.
If this bet is extracted, prefer a public name such as **`oss-mcp-gateway`**
(or `cash-mcp-gateway`). Do **not** rename this directory or the GitHub
portfolio repo from this note.

## What each product is

| | This repo (`@oss-cash-lab/mcp-gateway`) | microsoft/mcp-gateway | agentgateway (LF / AAIF) | IBM ContextForge (`IBM/mcp-context-forge`) | AWS Bedrock AgentCore Gateway |
|---|---|---|---|---|---|
| What it is | Local Node policy + audit proxy in front of HTTP/stdio MCP tools. | K8s reverse proxy + control plane for MCP server adapters/tools. | Rust data plane for MCP, A2A, LLM, HTTP/gRPC. AAIF-hosted. | Python registry/proxy that federates MCP, A2A, REST/gRPC. | Fully managed AWS entry point for agents to tools / models / other agents. |
| Runs where | `node src/cli.js serve` (stdlib only). Dockerfile is a placeholder. | Kubernetes (local k8s or AKS). .NET 8. | Bare metal / VM / container / Kubernetes. | PyPI / Docker / Compose / Helm. Redis/Postgres for scale. | AWS-managed. No self-host binary. |
| Auth we can compare | Static per-tenant `apiKey` (Bearer / `X-Api-Key`) + admin token. Rotate with grace. **Not SSO.** | Entra ID bearer + app roles (`mcp.admin`, `requiredRoles`). | JWT, API keys, RBAC, external auth (their docs). | JWT / Basic / user-scoped OAuth (their docs). | IAM + OAuth (AWS docs). |
| License | Apache-2.0 | MIT | Apache-2.0 | Apache-2.0 | Not OSS (managed service) |

## Feature matrix (only columns this code can claim)

Legend: **Yes** = this tree implements it. For others: **Yes (their shape)**
when public docs describe an equivalent; **—** when not in the public docs
we read (do not treat "—" as a proof they lack it).

| | This repo | microsoft/mcp-gateway | agentgateway | IBM ContextForge | AWS AgentCore Gateway |
|---|---|---|---|---|---|
| **Streamable HTTP** | **MVP only.** `POST /mcp` JSON-RPC (`initialize`, `tools/list`, `tools/call`, `ping`) + `Mcp-Session-Id` / `MCP-Protocol-Version`. `GET /mcp` is **405** `Allow: POST, DELETE`. **No SSE.** | Yes — `POST /adapters/{name}/mcp` and `POST /mcp` documented as Streamable HTTP. | Yes — MCP including newer spec versions (their docs). | Yes — streamable-HTTP plus SSE / WS / stdio (their docs). | Yes — multiple MCP versions, including 2026-07-28 (AWS docs). |
| **Tenant tokens** | Yes — `tenants[].apiKey`. Admin `POST /admin/tenants/{id}/rotate`. Not IdP-issued. | Entra tokens + app roles. Not static tenant API keys. | JWT / API key / RBAC (their docs). | JWT / Basic / OAuth (their docs). | IAM + OAuth (AWS docs). |
| **Audit export** | Yes — JSONL ring; `GET /audit` / `GET /audit/export` JSON or CSV (+ gzip); admin SIEM `GET /admin/audit` JSON/CSV/MD/HTML; CLI `export-audit`. | Adapter/tool **pod logs** (`GET /adapters/{name}/logs`). Azure deploy wires Application Insights. Not a SIEM CSV/JSON pack like ours. | Metrics, tracing, access logs (their docs). Not this pack format. | Admin UI log viewer with filter / search / export (their docs). | Managed observability (CloudWatch etc.). Not a local JSONL pack. |
| **Allow / deny** | Yes — static tool `allow` / `deny` lists, per-tenant override. | Entra RBAC on adapters/tools (creator / `requiredRoles` / `mcp.admin`). Not a tool-name allowlist. | Tool-level policy, RBAC, CEL (their docs). | Auth + plugins; not this static list. | IAM + optional interceptor Lambda. |
| **Rate limit** | Yes — `rateLimitPerMinute` global + per-tenant. | — (not in the public README we read) | Yes (their docs). | Yes (their docs). | — (not called out as this knob in the pages we read) |
| **Circuit breaker** | Yes — `upstream.breaker` consecutive-failure closed to open to half-open. 503 `circuit_open` + `Retry-After`. | — | Resiliency is a project goal; not this exact breaker. | Retries documented; not this breaker. | — |
| **Admin webhooks** | Outbound **audit** fan-out (`policy.webhooks[]`): fire-and-forget, **1 retry**, optional HMAC. `GET /admin/webhooks` is a redacted inventory (**no** URLs/secrets). Not inbound admin-event webhooks. | — | — | Admin UI; not this outbound audit fan-out. | — |
| **OSS license** | Apache-2.0 | MIT | Apache-2.0 | Apache-2.0 | No (managed AWS) |

## What this gateway is not

- Not a drop-in for `microsoft/mcp-gateway`. They deploy MCP servers on Kubernetes and authenticate with Entra. We do not.
- Not agentgateway. They are a high-performance unified data plane (MCP + A2A + LLM + HTTP/gRPC) under AAIF. We are a small Node policy proxy.
- Not IBM ContextForge. They federate many servers with an Admin UI, plugins, and OTel. We proxy one HTTP or stdio upstream plus builtin tools.
- Not AWS AgentCore Gateway. That is a managed cloud service.
- **No SSO / SAML / Entra, no OPA, no WASM plugins.** Those appear on paid-later notes in the B README only.

## When to use which

- Need a **local, no-IdP** MCP front door with tenant keys, static allow/deny, JSONL/SIEM audit, and a tiny Streamable HTTP client surface: this CLI.
- Need **K8s adapter lifecycle + Entra**: microsoft/mcp-gateway.
- Need a **shared AI/MCP/A2A/LLM proxy** at mesh scale: agentgateway.
- Need a **self-hosted registry + federation + Admin UI**: IBM ContextForge.
- Already on AWS and want a **managed** MCP/tool gateway: AgentCore Gateway.


## Reproduce (this tree)

From this bet directory with Node 18+:

    npm run smoke
    npm run local-mvp

Expect admin audit tenant filter: 401 without admin token, empty 200 for unknown tenant, no API keys in the body.

Sources (read 17 Aug 2026):
- microsoft/mcp-gateway README and microsoft.github.io/mcp-gateway
- agentgateway GitHub plus agentgateway.dev standalone intro and AAIF join post
- IBM/mcp-context-forge GitHub plus ibm.github.io/mcp-context-forge/latest
- AWS Bedrock AgentCore gateway.html in the AgentCore developer guide
