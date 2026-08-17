# B · mcp-gateway

> Enterprise MCP gateway (policy / audit / multi-tenant) · **Status: local-mvp** · **Phase 1**

> **Not [microsoft/mcp-gateway](https://github.com/microsoft/mcp-gateway).**
> This is the oss-cash-lab Node policy/audit gateway (`@oss-cash-lab/mcp-gateway`).
> Microsoft's repo is a Kubernetes + Entra reverse proxy (~785 stars). Same short name; different product.
> Comparison: [`docs/vs-gateways.md`](./docs/vs-gateways.md).
> If this bet is extracted, prefer a public name like `oss-mcp-gateway` (or `cash-mcp-gateway`). Do not rename this directory.

## Who pays / 谁付钱

- Platform / Security / AI platform teams
- 平台工程、安全、AI 平台团队（SSO / 审计出口 / 多租户配额）

## OSS vs Paid （draft anchors）

| Tier | Contents | Anchor (draft) |
|------|----------|----------------|
| OSS free | 核心网关：static allow/deny, rate-limit, JSONL audit, HTTP/stdio upstream proxy, **best-effort audit webhooks** (fire-and-forget, **1 retry** on 5xx/timeout) + **simple HMAC-SHA256** (`webhooks[].secret`) | $0 |
| Paid pilot | multi-tenant API key, audit query API, **audit export packs** (`GET /audit/export` + `export-audit` CLI → JSON/CSV, optional **gzip**), hot reload, SSO-ready hooks, **webhook exponential backoff / queues**, **HMAC key rotation / timestamp replay window enforcement** | ~$499/mo draft |
| Enterprise | on-prem, SSO/SAML, quota packs, compliance export, SLA | contract |

> Pricing anchors are **draft placeholders** for pilot talks — not public SKUs yet.

## Upstream proxy

Config:

```json
{
  "upstream": {
    "type": "http",
    "baseUrl": "http://127.0.0.1:8790",
    "timeoutMs": 5000,
    "breaker": { "failureThreshold": 3, "openMs": 2000 }
  }
}
```

or stdio:

```json
{
  "upstream": { "type": "stdio", "command": "node", "args": ["mock-upstream.js", "--stdio"], "timeoutMs": 5000 }
}
```

When set, gateway merges upstream `/tools/list` (tenant-filtered) and proxies `/tools/call`.
Ship `mock-upstream.js` for local proof (`source: mock-upstream`).

**Timeout:** `upstream.timeoutMs` (default **5000**). HTTP `fetch` (AbortController) and stdio pending RPC abort after the window. `POST /tools/call` timeout → **504** `{error:"upstream_timeout"}`; audit `reason=upstream_timeout`; Prometheus `upstream_timeout_total`. Happy-path local-mvp / stack-demo use a generous timeout; an isolated delay mock (`mock-upstream.js --delay-ms`) proves 504.

**Circuit breaker:** optional `upstream.breaker: { failureThreshold: 3, openMs: 2000 }` (defaults when the object is present). Omitted, `enabled: false`, or `failureThreshold: 0` disables — existing timeout/proxy proves keep it off. Counts `upstream_timeout` and 5xx/connect errors as consecutive failures. After the threshold, the circuit **opens**: further `POST /tools/call` to that upstream return **503** `{error:"circuit_open"}` **without calling upstream** until `openMs` elapses (half-open: one probe; success closes, failure re-opens). **503 includes `Retry-After`** (remaining seconds until `openUntil`, min 1). Audit `reason=circuit_open`; Prometheus `circuit_open_total`. When enabled, **`GET /health`** includes `breaker: { state: "closed"|"open"|"half_open", failures, openUntil }` (`openUntil` is ISO-8601 while open, otherwise `null`; **no secrets**). The field is omitted when the breaker is disabled so stack-demo `/health` `{ok:true}` is unchanged. **`GET /ready`** is readiness: 200 `{ok:true}` when the breaker is disabled or `closed`/`half_open`; 503 `{ok:false, reason:"circuit_open"}` when `state` is `open` (includes the same `breaker` snapshot when enabled; `Retry-After` on 503). On **SIGTERM/SIGINT**, `/ready` immediately returns **503** `{ok:false, reason:"shutting_down"}` (wins over healthy 200); **`GET /health` stays 200** with `shuttingDown: true` while draining. Liveness **`GET /health` stays 200 `{ok:true}` even if the circuit is open**. Compose/stack-demo healthchecks stay on `/health` (do not switch to `/ready`). Isolated local-mvp: delay mock + low `timeoutMs` + `failureThreshold: 1` → 504 then fast 503 + `Retry-After` ≥ 1 + health `state:open` + **`/ready` 503**; after `openMs` health `half_open`; fast mock probe 200 + health `closed` + **`/ready` 200**.

## Quick start

```bash
npm run smoke
npm run local-mvp
# optional standalone upstream:
node mock-upstream.js --port 8790
```

Container (k8s placeholder; images not published; skip if no Docker): `docker build -t ghcr.io/wozqhl/b-mcp-gateway:dev bets/b-mcp-gateway` (`node:20-alpine`, EXPOSE **8787**, `serve --host 0.0.0.0`).

Auth: Bearer or X-Api-Key; unknown key -> 401  
`X-Request-Id`: optional correlation header. Echoed on **every** response. If omitted/empty, the gateway generates a UUID (max 128 chars; CR/LF stripped). The same value is stored as `requestId` on audit JSONL events and webhook payloads.  
CORS: optional `cors: { origins, methods, headers }`. Default omitted/empty `origins` = **no** CORS headers. `origins: ["*"]` or an explicit list; local-mvp uses `["http://localhost:3000"]`. OPTIONS preflight: allowed Origin → **204** + ACAO/ACAM/ACAH (default methods include **DELETE**); unlisted Origin (explicit list) → **403** `{error:"forbidden",reason:"cors_denied"}`. Matching GET/POST/DELETE include `Access-Control-Allow-Origin`. Default allow-headers include `X-Request-Id`, `MCP-Protocol-Version`, `Mcp-Session-Id`; default expose (`Access-Control-Expose-Headers`) includes `Retry-After`, `X-Request-Id`, `MCP-Protocol-Version`, `Mcp-Session-Id`.  
Optional per-tenant `ipAllowlist`: exact IPv4/IPv6 or IPv4 CIDR `/8`/`/16`/`/24` (IPv6 exact only). Client IP = `X-Forwarded-For` first hop or socket `remoteAddress`; mismatch → `403 {"error":"forbidden","reason":"ip_denied"}`.  
Body size: global `maxBodyBytes` (default **1048576**); optional per-tenant override. POST `/tools/call` over limit → `413 {"error":"payload_too_large"}` **before** JSON parse (Content-Length early reject or stream/count bytes).  
OpenAPI: `GET /openapi.json` (spec file `openapi/gateway.openapi.json`; ApiKey + Bearer schemes; **`POST /mcp`** Streamable HTTP JSON-RPC MVP + session TTL **3600s** / **404** `session_expired` + **`DELETE /mcp`** (`mcpSessionDelete`, **204** / **400** `session_id_required` / **404** `session_not_found`) + **`GET /mcp` 405** `Allow: POST, DELETE`; notes `ipAllowlist`, `maxBodyBytes`, `ip_denied_total`, `body_too_large_total`, `upstream.timeoutMs` / `504 upstream_timeout` / `upstream_timeout_total`, `upstream.breaker` / **503** `circuit_open` / **`Retry-After`** / `circuit_open_total` / **`GET /health` `breaker` snapshot** (`Health` / `CircuitBreakerSnapshot`: `state` `closed|open|half_open`, `failures`, `openUntil`) / **`GET /ready`** (`Ready`: 200 `{ok:true}` or 503 `{ok:false, reason:"circuit_open"|"shutting_down"}`), optional `cors` / `CorsConfig`, **`X-Request-Id`** / `requestId` on `AuditEvent`, **gzip** `?gzip=1` / `Accept-Encoding: gzip`, outbound **audit webhooks** / optional **`X-Webhook-Signature`** HMAC / **`X-Webhook-Timestamp`** / OSS **1 retry** / `AuditWebhook`, **`POST /admin/tenants/{tenantId}/rotate`** / `TenantRotateResponse`, **`GET /admin/audit.csv`** / **`GET /admin/audit.md`** / **`GET /admin/audit.html`**, **`GET /admin/sessions`** (`adminListSessions`), **`DELETE /admin/sessions/{id}`** (`adminDeleteSession`), **`GET /admin/config`** (`adminGetConfig`), **`GET /admin/webhooks`** (`adminListWebhooks`), **`GET /admin/tenants/{tenantId}`** (`adminGetTenant`))  
Metrics: `GET /metrics` — Prometheus text (`tool_calls_total{tool,decision,tenant}`, `rate_limited_total`, `ip_denied_total`, `body_too_large_total`, `upstream_timeout_total`, `circuit_open_total`, `webhook_retries_total`, `http_requests_total{path,status}`, gauges `audit_events` / `audit_retained`)  
JSON access logs (opt-in): `--log-json` or env `LOG_FORMAT=json` (env wins if CLI omitted) — one stdout JSON line per completed app request `{ts,level:info,msg:http,service,method,path,status,durationMs,requestId}` (optional `bytesOut`/`remote`); skips `/health` `/ready` `/metrics` and OPTIONS; `requestId` matches `X-Request-Id`. Default **off**.  
Audit query: `GET /audit?tenant=&limit=&tool=&since=&until=&redact=` (events include `requestId`; live window = in-memory ring)  
Export (paid wedge): `GET /audit/export?tenant=&format=json|csv&redact=1&since=ISO&until=ISO&gzip=1` (tenant key **or** admin token; JSON events + CSV column `requestId`; optional gzip; same retained window)  
Admin SIEM CSV/Markdown/HTML: `GET /admin/audit.csv` + `GET /admin/audit.md` + `GET /admin/audit.html` + `GET /admin/audit?format=csv|json|md|html` (admin token **only**; **not public**; CSV `text/csv` / Markdown `text/markdown` / HTML `text/html`; columns `ts,tenantId,tool,allow,reason,via,requestId`; **no** args/headers/tokens/bodies; empty CSV → header only 200; empty Markdown → `# Audit` + header 200; empty HTML → heading + “no events” 200; optional `?tenant=` filters the retained window (unknown tenant → empty 200); gzip JSON stays on `/audit/export`; counts match the ring)  
In-memory audit cap: default **10000** (`--audit-max` / `AUDIT_MAX_EVENTS`). Over cap, drop oldest. `0` = unlimited (**dangerous**, process can grow forever). Webhook fan-out still posts every new event. JSONL on disk still appends; live HTTP/export reads the ring.
Offline pack: `node src/cli.js export-audit --config config/policy.json --out out/audit.json --format json|csv|md|html [--redact] [--since ISO] [--until ISO] [--gzip]` (reads JSONL file, not the live ring; `--format md` / `--format html` are SIEM-safe admin columns, no args/tokens; HTML prints to stdout when `--out` is omitted)  
Reload: SIGHUP or POST `/admin/reload`; optional **`serve --watch`** polls config mtime every **300ms** (same reload path; logs `regenerated`)  
Graceful shutdown: SIGTERM/SIGINT → `/ready` 503 `shutting_down`, `/health` 200 `shuttingDown: true`, drain (default **5s**, `--drain-ms` / `SHUTDOWN_DRAIN_MS`, cap 30s), log `shutting down` then `exit`  
Admin tenants: `GET /admin/tenants` (X-Admin-Token / Bearer admin) → `{id,allowCount,denyCount,rateLimit,hasIpAllowlist,maxBodyBytes,apiKeyMasked}` (**never** raw `apiKey`; masked last 4) · missing/invalid token → `401`  
Admin tenant: `GET /admin/tenants/{id}` (same admin token) → `{ok,id,hasApiKey,hasPreviousApiKey,previousApiKeyExpiresAt,allow,deny,rateLimit,hasIpAllowlist,maxBodyBytes}` (**never** `apiKey` / `previousApiKey` values) · unknown id → `404` `{error:tenant_not_found}` · missing/invalid token → `401`  
Admin sessions: `GET /admin/sessions` (same admin token) → `{ok, ttlSec, cap, count, sessions:[{id, ageMs, ttlRemainingMs, lastSeen}]}` live in-memory Streamable HTTP sessions (newest **100**; `truncated: true` when more; tombstones omitted; **no** secrets/keys/headers) · missing/invalid token → `401`  
Admin session drop: `DELETE /admin/sessions/{id}` (same admin token; id in the path, **no** `Mcp-Session-Id` header) → **204**; unknown/expired/already gone → **404** `{error:"session_not_found"}` (idempotent); unauth → **401**. Client `DELETE /mcp` unchanged.  
Admin config: `GET /admin/config` (same admin token) → `{ok, sessionTtlSec, sessionCap, auditMax, rotateGraceSec, rateLimit, cors.origins, upstream.timeoutMs/breaker, tenants.count, webhooks.count + hasWebhookSecret}` redacted runtime config (**never** apiKey / secrets / admin token / Authorization / `--header` values) · missing/invalid token → `401`  
Admin webhooks: `GET /admin/webhooks` (same admin token) → `{ok, count, webhooks:[{id, events, hasUrl, hasSecret}]}` redacted outbound webhook inventory (**never** url / secret / apiKey / admin token) · empty → `{ok:true, count:0, webhooks:[]}` · missing/invalid token → `401`  
Admin rotate: `POST /admin/tenants/{id}/rotate` (same admin auth) → `{ok:true, tenantId, token, previousTokenExpiresAt?}` — **new token shown once**. Previous key valid for grace (default **60s**, `--rotate-grace-sec` / `TOKEN_ROTATE_GRACE_SEC`) then 401. Unknown tenant → `404`. Audit `type=token_rotated` (**no** raw tokens in JSONL/CSV/logs/metrics).  


### Streamable HTTP MVP (POST JSON-RPC, not full SSE)

Current MCP clients speak Streamable HTTP. This gateway adds a **minimal** surface — **POST JSON-RPC + session headers**, not a full spec SSE rewrite.

- **Path:** `POST /mcp` (alias `POST /`). Existing REST `POST /tools/list` and `POST /tools/call` (and `/mcp/tools/*` aliases) stay unchanged.
- **Auth:** same tenant API key as `/tools/*` (`Authorization: Bearer` or `X-Api-Key`).
- **JSON-RPC methods:** `initialize`, `tools/list`, `tools/call` (plus `ping`). `tools/call` uses the same policy / rate-limit / circuit breaker / audit path as REST.
- **`MCP-Protocol-Version`:** echoed on Streamable HTTP responses. Default **`2025-03-26`**. Client `YYYY-MM-DD` is echoed when sent.
- **`Mcp-Session-Id`:** UUID assigned on `initialize` if the client omitted it (also in the initialize result `sessionId`). Later `tools/list` / `tools/call` **may omit** the session (backward compatible with local-mvp curls that do not send it). When present, it is echoed.
- **Session TTL:** unused sessions expire after **3600s** by default (`--session-ttl` / `MCP_SESSION_TTL_SEC`). `0` = no time expiry (ids are still generated). In-memory last-seen map (cap **10000**, drop oldest). POST with an **expired** `Mcp-Session-Id` → **404** `{error:"session_expired"}` so clients re-initialize. Missing session still **200**. Unknown (fresh) ids are accepted and tracked. REST `/tools/*` ignores session.
- **GET `/mcp`:** **405** with `Allow: POST, DELETE` (no hanging `text/event-stream`).
- **DELETE `/mcp`:** terminate the session. `Mcp-Session-Id` is the capability (**no** admin token). Success → **204** No Content. Missing header → **400** `{error:"session_id_required"}`. Unknown / expired / already gone → **404** `{error:"session_not_found"}` (idempotent). POST with that id afterwards → **404**. TTL still applies independently. REST `/tools/*` unchanged.
- **Ops inventory:** `GET /admin/sessions` (admin token, same as `GET /admin/tenants`) lists live sessions so you do not need to grep logs. Tombstones are omitted. Array capped at 100 newest-by-lastSeen.
- **Ops kill:** `DELETE /admin/sessions/{id}` (same admin token; id in the path, **no** `Mcp-Session-Id` header) force-drops a session when the client is gone (**204**; unknown/expired **404** `session_not_found`; unauth **401**). Client `DELETE /mcp` with `Mcp-Session-Id` stays the capability path.
- Notifications (`notifications/*`) return **202** empty. JSON-RPC batches are not supported (**400**).

```bash
# initialize — response headers include MCP-Protocol-Version + Mcp-Session-Id
curl -sD- -X POST http://127.0.0.1:8787/mcp \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -H 'MCP-Protocol-Version: 2025-03-26' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"demo"}}}'

# tools/list without session still 200
curl -sf -X POST http://127.0.0.1:8787/mcp \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'

# expired Mcp-Session-Id → 404 {error:"session_expired"} (re-initialize)
# curl -sD- -X POST http://127.0.0.1:8787/mcp -H "Mcp-Session-Id: $OLD_SID" ...

# terminate session (204; missing header → 400 session_id_required)
curl -sD- -o /dev/null -X DELETE http://127.0.0.1:8787/mcp -H "Mcp-Session-Id: $SID"

# admin force-drop when the client is gone (204; unknown/expired → 404 session_not_found)
curl -sD- -o /dev/null -X DELETE "http://127.0.0.1:8787/admin/sessions/$SID" -H "X-Admin-Token: $ADMIN"
```

Paste-ready **client** snippet (Cursor / Claude HTTP MCP, not stdio): [`examples/mcp/gateway.mcp.json`](../../examples/mcp/gateway.mcp.json) — `url` `http://127.0.0.1:8787/mcp` + Bearer `${env:MCP_GATEWAY_TOKEN}`. B `/mcp` is **POST JSON-RPC + DELETE session** (`GET` 405 `Allow: POST, DELETE`; no SSE). See [`examples/mcp/README.md`](../../examples/mcp/README.md). This repo does not enable a live Cursor connection.

### Audit export packs（paid wedge note）

Pilot delivery often needs a downloadable audit pack for security review:

- **HTTP**: `GET /audit/export?format=json|csv` — attachment download; tenant API key scopes to that tenant; admin token can export all / filter `tenant=`. Optional `?since=` / `?until=` (ISO-8601) and `?redact=1|true`.
- **Gzip**: `?gzip=1` or request header `Accept-Encoding: gzip` returns a gzipped body with `Content-Encoding: gzip` and `Content-Disposition` filename `.json.gz` / `.csv.gz`. Explicit `gzip=0` disables compression even if Accept-Encoding includes gzip. Uncompressed JSON/CSV remains the default.
- **CLI (offline)**: `export-audit` reads local JSONL (`--audit` or default `data/audit.jsonl`) without a running server — useful for air-gapped handoff. Flags: `--redact` / `--no-redact`, `--since`, `--until`, `--gzip` (e.g. `--out out/audit.json.gz`).
- **PII-safe packs**: with `redact`, `arguments`/`result` become `[REDACTED]` (tool, decision, tenantId, ts, reason kept; argument key presence hashed). Set `export.redactDefault: true` in policy for paid-safe defaults. Same `?redact=` / `export.redactDefault` rules apply to `GET /audit`.
- **Admin SIEM CSV**: `GET /admin/audit.csv` (and `GET /admin/audit?format=csv`) is **admin-token only** — not tenant-key public. Columns `ts,tenantId,tool,allow,reason,via,requestId` (no `arguments`/`result`/tokens). Empty → header only **200**. Unauthenticated → **401**. Uncompressed; gzip JSON/CSV packs stay on `GET /audit/export`.
- **Admin SIEM Markdown**: `GET /admin/audit.md` (and `GET /admin/audit?format=md`) is the same admin gate and columns as CSV (`text/markdown`; `# Audit` + GFM table; `|` escaped). Empty → heading + header row only **200**. Unauthenticated → **401**. CLI `export-audit --format md` writes the same table from JSONL (does not include args/tokens; `--format csv` remains the full pack).
- **Admin SIEM HTML**: `GET /admin/audit.html` (and `GET /admin/audit?format=html`) is the same admin gate and columns as CSV (`text/html`; self-contained table, no CDN; all text escaped; deny vs allow rows distinct). Empty → heading + “no events” + header **200**. Unauthenticated → **401**. CLI `export-audit --format html` prints the same table from JSONL to stdout (does not include args/tokens). Gzip stays on JSON/CSV `/audit/export`.
- **In-memory cap**: live HTTP query/export/admin CSV/Markdown/HTML see a ring buffer (default **10000**, `--audit-max` / `AUDIT_MAX_EVENTS`; `0` = unlimited, dangerous). Over cap, oldest events drop from the retained window (counts match). Webhook fan-out is **not** dropped for new events. Offline CLI still reads the JSONL file.
- Packs are the Pro/pilot differentiator vs OSS JSONL-on-disk alone.

### Audit webhook fan-out（OSS best-effort · paid for reliability）

Optional policy config posts each audit event to HTTP endpoints after JSONL write:

```json
{
  "webhooks": [
    { "url": "http://127.0.0.1:8792/hook", "events": ["tool_call", "deny"], "secret": "whsec_local_mvp" }
  ],
  "webhooksRedact": true
}
```

- **Events**: `tool_call` (allow) and `deny` (`allow:false`, including rate-limit). Omit `events` → both.
- **Delivery**: fire-and-forget POST JSON (`type`, `source`, `redacted`, `requestId`, `event`); `X-Request-Id` header when present; short timeout (~750ms); **webhook errors never fail** `/tools/call`. The in-memory audit cap drops **retained history** only — every new event still fans out.
- **Retry (OSS)**: on **5xx** or **network/timeout**, retry the POST **once** after ~50ms. Success on the first try = no retry. **4xx do not retry**. Optional Prometheus `webhook_retries_total`.
- **HMAC (OSS)**: optional per-hook `secret`. When set, POST includes `X-Webhook-Signature: sha256=<hex>` — HMAC-SHA256 of the **raw JSON body**. Omit / empty `secret` → unsigned (existing fan-out). Simple HMAC is OSS.
- **Timestamp (OSS)**: every outbound POST includes `X-Webhook-Timestamp: <unix-seconds>`. HMAC still signs the raw body only (timestamp is an extra header). **Replay window enforcement = paid later**.
- **Redaction**: `webhooksRedact` defaults **true** (prefer redacted payloads). Also forced when `audit.redactOnWrite` or `export.redactDefault` is true. Uses the same `[REDACTED]` / `argumentKeysHash` rules as export.
- **Paid note**: OSS is best-effort with **1 retry** (no DLQ, no exponential backoff). Optional simple HMAC + timestamp header. **Exponential backoff / queues, key rotation, and timestamp replay window enforcement = paid / pilot**.

Local prove: `mock-webhook-receiver.js` writes the last POST body to a file (optional `--secret` verifies HMAC; `--headers-out` persists `X-Webhook-Signature` + `X-Webhook-Timestamp`; `--fail-once` returns 500 then 200). `scripts/local-mvp.sh` asserts unsigned `tool_call` + `deny` receipts **and** timestamp present/roughly now, plus an isolated signed receiver (`secret` set → signature header present + HMAC matches body + timestamp independent), plus an isolated `--fail-once` receiver (2 POSTs, body delivered, `webhook_retries_total` ≥ 1). Smoke unit-tests 200/4xx = no retry and 5xx/network = one retry.


### Serve `--watch` (config mtime poll)

`node src/cli.js serve --config policy.json --watch` polls the config file mtime every **300ms** (`fs.stat` + `setInterval`) and reloads policy via the **same** `reloadPolicyAndUpstream` path as **SIGHUP** and `POST /admin/reload`.

- Prints `watching <path> (poll 300ms)` at start and `regenerated {tenants,allow,deny,upstreamTools}` on a successful reload.
- Parse/reload errors keep the previous in-memory policy (mtime advances only after success).
- Main serve / stack-demo / Compose stay **off** (`watch=off`); local-mvp proves on an isolated copy (curl `tools/list` → add an allow tool → list/`GET /admin/tenants` reflect the change → kill, no hang). Existing SIGHUP / `/admin/reload` proves are unchanged.

### Graceful shutdown (SIGTERM/SIGINT)

Always on (no extra flags). Default serve / stack-demo / Compose unchanged.

1. Flip an internal `shuttingDown` flag; log `shutting down`.
2. **`GET /ready`** → **503** `{ok:false, reason:"shutting_down"}` so kubelet/Compose stop sending traffic (wins over healthy 200; also wins over `circuit_open`).
3. **`GET /health`** stays **200** `{ok:true, shuttingDown: true}` so liveness does not kill the pod while draining. Field omitted when not shutting down (stack-demo `/health` unchanged).
4. Skip new upstream `tools/call` proxies (503 `shutting_down`). Watch poller stops immediately.
5. After the drain window (default **5s**, `--drain-ms` or env `SHUTDOWN_DRAIN_MS`, cap **30s**) close the HTTP server and log `exit`.

Isolated local-mvp: start on a temp port with `--drain-ms 200` → `kill -TERM` → `/ready` 503 + `/health` 200 `shuttingDown` → process exits within the window (no hang).

### Admin tenant inventory (`GET /admin/tenants`)

Ops-facing list of configured tenants (admin token required):

- **Auth**: `X-Admin-Token` or Bearer matching `adminToken`. Missing/invalid → `401 {"error":"unauthorized_admin"}`.
- **Response**: `{ ok, tenants: [{ id, allowCount, denyCount, rateLimit, hasIpAllowlist, maxBodyBytes, apiKeyMasked }] }`.
- **Secrets**: raw `apiKey` is **never** returned; `apiKeyMasked` shows only the last 4 characters.
- Proven in `scripts/local-mvp.sh` (401 without token + field assertions).

### Admin single tenant (`GET /admin/tenants/{id}`)

Ops-facing **one** tenant (complements the list + rotate). Same admin token. **No secrets.**

- **Auth**: same as `GET /admin/tenants` — `X-Admin-Token` or Bearer matching `adminToken`. Missing/invalid → `401 {"error":"unauthorized_admin"}`.
- **200**: `{ ok, id, hasApiKey, hasPreviousApiKey, previousApiKeyExpiresAt, allow, deny, rateLimit, hasIpAllowlist, maxBodyBytes }`. `allow` / `deny` are the effective tool lists (tenant override or global). `rateLimit` is effective `rateLimitPerMinute`.
- **Secrets**: **never** `apiKey` or `previousApiKey` values — booleans + `previousApiKeyExpiresAt` (ISO-8601 or `null`) only.
- **404**: unknown id `{error:"tenant_not_found"}`.
- CORS + `X-Request-Id` like other admin GET.
- Proven in smoke (helper JSON.parse + planted `apiKey` must fail; in-process 401 / 200 / 404) and `scripts/local-mvp.sh` (curl 200 + OpenAPI `adminGetTenant` + 401 unauth + 404 unknown). Stack-demo checks the OpenAPI path and unauthenticated 401 (does not send an admin token).

### Admin session inventory (`GET /admin/sessions`)

Ops-facing list of **live** in-memory Streamable HTTP sessions (pairs with session TTL + `DELETE /mcp` + `DELETE /admin/sessions/{id}`):

- **Auth**: same as `GET /admin/tenants` — `X-Admin-Token` or Bearer matching `adminToken`. Missing/invalid → `401 {"error":"unauthorized_admin"}`.
- **Response**: `{ ok, ttlSec, cap, count, sessions: [{ id, ageMs, ttlRemainingMs, lastSeen }] }`. Optional `dropped` (tombstone count). `ttlSec` is the configured TTL (`0` = no expiry → `ttlRemainingMs` may be `null`).
- **Cap**: `sessions` is at most **100** newest-by-lastSeen. `count` is the full live size; `truncated: true` when more exist.
- **Tombstones**: deleted/expired ids are **not** listed. Client terminate stays on `DELETE /mcp` (session id is the capability). Admin force-drop is `DELETE /admin/sessions/{id}`.
- **Secrets**: **never** API keys, Authorization headers, or other secrets. Session id only.
- CORS + `X-Request-Id` like other admin GET.
- Proven in smoke (in-process 401 / empty / init / DELETE) and `scripts/local-mvp.sh` (main + isolated serve, CORS OPTIONS). Stack-demo checks the OpenAPI path and unauthenticated 401 (does not send an admin token).

### Admin session force-drop (`DELETE /admin/sessions/{id}`)

Ops kill when the MCP client is gone (no `Mcp-Session-Id` to send). Same admin token as other `/admin/*`.

- **Route**: `DELETE /admin/sessions/{id}`. Id is in the **path** — **does not** require `Mcp-Session-Id`. Client `DELETE /mcp` with `Mcp-Session-Id` stays the capability path.
- **Auth**: `X-Admin-Token` or Bearer matching `adminToken`. Missing/invalid → `401 {"error":"unauthorized_admin"}`.
- **204**: session tombstoned (No Content). Subsequent `POST /mcp` with that id → **404** `{error:"session_not_found"}`.
- **404**: unknown / expired / already gone `{error:"session_not_found"}` (idempotent). Missing id (`DELETE /admin/sessions`) → **404** (router-style).
- **Audit**: optional `type=session_deleted` with `via: admin` (**no** raw session id or tokens).
- CORS: Allow-Methods include **DELETE** when CORS is enabled. `X-Request-Id` like other admin routes.
- Proven in smoke (initialize → admin DELETE 204 → POST same id 404; second DELETE 404; unauth 401) and `scripts/local-mvp.sh` (main + isolated serve, CORS OPTIONS DELETE). Stack-demo checks OpenAPI `adminDeleteSession` and unauthenticated DELETE 401 (does not send an admin token).

### Admin runtime config (`GET /admin/config`)

Ops-facing **redacted** snapshot of runtime knobs for pilot debugging (TTL, CORS, breaker, rate-limit, session cap) **without secrets**:

- **Auth**: same as `GET /admin/tenants` — `X-Admin-Token` or Bearer matching `adminToken`. Missing/invalid → `401 {"error":"unauthorized_admin"}`.
- **Response**: `{ ok, sessionTtlSec, sessionCap, auditMax, rotateGraceSec, rateLimit: { perMinute }, cors: { origins }, upstream: { timeoutMs, breaker }, tenants: { count }, webhooks: { count, destinations: [{ hasWebhookSecret }] } }`.
- **CORS origins**: explicit list, or `*` when any Origin is allowed. Empty list when CORS is disabled.
- **Secrets**: **never** `apiKey`, `previousApiKey`, webhook secrets, admin token, `Authorization`, `--header` values, or tenant tokens. Tenant **count** only (not keys). Webhook dests expose `hasWebhookSecret` boolean only.
- CORS + `X-Request-Id` like other admin GET.
- Proven in smoke (helper JSON.parse + planted `apiKey` must fail; in-process 401 / 200) and `scripts/local-mvp.sh` (curl 200 + OpenAPI `adminGetConfig` + 401 unauth). Stack-demo checks the OpenAPI path and unauthenticated 401 (does not send an admin token).


### Admin webhook inventory (`GET /admin/webhooks`)

Ops-facing **redacted** list of configured outbound audit webhooks (**no URLs or secrets**):

- **Auth**: same as `GET /admin/tenants` — `X-Admin-Token` or Bearer matching `adminToken`. Missing/invalid → `401 {"error":"unauthorized_admin"}`. Tenant API keys are **not** accepted.
- **Response**: `{ ok, count, webhooks: [{ id, events, hasUrl, hasSecret }] }`. `id` is the configured id when present, otherwise the 0-based source index. `events` is the configured list (or `[]`).
- **Secrets**: **never** `url`, `secret`, apiKey, admin token, Authorization, `--header` values, or tenant tokens. Booleans only for destination/HMAC.
- Empty / omitted `webhooks` → `{ok:true, count:0, webhooks:[]}`.
- CORS + `X-Request-Id` like other admin GET.
- Proven in smoke (helper JSON.parse + planted `url`/`secret` must fail; in-process 401 / empty 200 / one-hook 200) and `scripts/local-mvp.sh` (curl 200 + OpenAPI `adminListWebhooks` + 401 unauth). Stack-demo checks the OpenAPI path and unauthenticated 401 (does not send an admin token).

### Admin tenant API token rotation (`POST /admin/tenants/{id}/rotate`)

Enterprise MCP gateways must rotate keys without downtime. Same admin auth as `GET /admin/tenants`.

- **Route**: `POST /admin/tenants/{id}/rotate` or `POST /admin/tenants/rotate` with body `{tenantId}` (or `{id}`).
- **Auth**: `X-Admin-Token` or Bearer matching `adminToken`. Missing/invalid → `401 {"error":"unauthorized_admin"}`.
- **200**: `{ ok: true, tenantId, token, previousTokenExpiresAt? }`. The **new token is shown once**. Treat `token` as a secret.
- **Grace**: the previous key stays valid until `previousTokenExpiresAt` (default **60 seconds**). Set `--rotate-grace-sec` or env `TOKEN_ROTATE_GRACE_SEC`. `0` = old key rejected immediately. During grace **both** keys work; after grace only the new key.
- **404**: unknown tenant `{error:"unknown_tenant"}`.
- **Audit**: JSONL `{type:"token_rotated", tenantId, requestId, previousTokenExpiresAt?}` — **never** raw tokens. Admin SIEM CSV / access logs / metrics labels also omit the secret.
- **Persist**: file-backed `--config` writes the new `apiKey` (and `previousApiKey` / `previousApiKeyExpiresAt` during grace) the same way existing keys are stored (plaintext in policy JSON). In-memory-only (no config path) keeps rotation + grace in process until restart / reload — MVP OK.
- Isolated local-mvp (`--rotate-grace-sec 0` on a temp port) proves 200 + new token can call `/tools/list` + old token 401 + unauth 401 + audit/CSV have no new token string. Main serve / stack-demo do **not** rotate the demo `acme` key.

### Admin audit CSV (`GET /admin/audit.csv`), Markdown (`GET /admin/audit.md`), and HTML (`GET /admin/audit.html`)

SIEM / spreadsheet / ops-doc archive of MCP tool-call audit (admin token required; **must not be public**):

- **Auth**: same as `GET /admin/tenants` — `X-Admin-Token` or Bearer matching `adminToken`. Missing/invalid → `401 {"error":"unauthorized_admin"}`. Tenant API keys are **not** accepted (use `GET /audit/export?format=csv` for tenant-scoped packs).
- **CSV**: `Content-Type: text/csv; charset=utf-8`. Columns `ts,tenantId,tool,allow,reason,via,requestId`. **Never** includes raw args, headers, tokens, or bodies. Empty log → header only, **200**.
- **Markdown**: `Content-Type: text/markdown; charset=utf-8`. Heading `# Audit` plus a GFM table with the **same columns** (`|` escaped). Empty log → heading + header row only, **200**. Paste into Feishu/WeCom/Slack docs.
- **HTML**: `Content-Type: text/html; charset=utf-8`. Self-contained local demo page (inline CSS, no CDN). Same columns; all text escaped (`& < > " '`). Deny vs allow rows are visually distinct. Empty log → heading + “no events” + header row, **200**. **Never** includes API keys, `Authorization`, args, or bodies.
- **Tenant filter**: `?tenant=` on `GET /admin/audit` (and `.csv` / `.md` / `.html`) keeps events whose `tenantId` equals the value. Omit to list all retained events. Unknown tenant → empty **200** (JSON `count: 0`; CSV header only; Markdown heading + header; HTML “no events”). Same admin gate. Tenant API keys still **401**.
- **Secrets**: admin token and tenant API keys never appear in the body. CSV/MD/HTML never include args/tokens. Proven in smoke (401 unauth, empty unknown tenant, no key leakage).
- **Alias**: `GET /admin/audit?format=csv` (same CSV body). `GET /admin/audit?format=md` (same Markdown body). `GET /admin/audit?format=html` (same HTML body). `GET /admin/audit?format=json` (default) returns an uncompressed JSON pack — gzip stays on `GET /audit/export` (`?gzip=1` / `Accept-Encoding: gzip`).
- CORS + `X-Request-Id` same as other admin GET.
- Proven in `scripts/local-mvp.sh` (401 unauthenticated + 200 `text/html` after a tool call + secret/token not present). Stack-demo checks the OpenAPI path (`getAdminAuditHtml` / `format=html`) and unauth 401 (does not send an admin token).

### OpenAPI + metrics

- Spec source: [`openapi/gateway.openapi.json`](./openapi/gateway.openapi.json) documents `/health`, **`/ready`**, `/tools/list`, `/tools/call`, **`POST /mcp`** (`mcpJsonRpc`; Streamable HTTP JSON-RPC MVP; session TTL 3600s / 404 `session_expired`) + **`GET /mcp` 405** (`mcpStreamableGet`; no SSE), `/audit`, `/audit/export`, `/admin/reload`, `/admin/tenants`, **`GET /admin/tenants/{tenantId}`** (`adminGetTenant`), **`GET /admin/sessions`** (`adminListSessions`), **`DELETE /admin/sessions/{id}`** (`adminDeleteSession`), **`GET /admin/config`** (`adminGetConfig`), **`GET /admin/webhooks`** (`adminListWebhooks`), **`POST /admin/tenants/{tenantId}/rotate`** (`adminRotateTenantToken`; alias `POST /admin/tenants/rotate`), **`/admin/audit.csv`** (`getAdminAuditCsv`), **`/admin/audit.md`** (`getAdminAuditMd`), **`/admin/audit.html`** (`getAdminAuditHtml`), **`/admin/audit`** (`getAdminAudit`, `?format=json|csv|md|html`) with `ApiKeyAuth` (`X-Api-Key`), `BearerAuth`, and `AdminToken`, plus optional tenant `ipAllowlist` / `ip_denied_total`, `maxBodyBytes` / `413 payload_too_large`, `body_too_large_total`, **`upstream.timeoutMs`** (default 5000) / **504** `upstream_timeout` / `upstream_timeout_total`, **`upstream.breaker`** (`failureThreshold` 3 / `openMs` 2000; omit to disable) / **503** `circuit_open` / `circuit_open_total` (`UpstreamConfig`), **`GET /health` circuit snapshot** (`Health` / `CircuitBreakerSnapshot`: when enabled, `breaker: { state: closed|open|half_open, failures, openUntil }`; omitted when disabled; **no secrets**), **`GET /ready`** (`Ready`: 200 `{ok:true}` when disabled or `closed`/`half_open`; 503 `{ok:false, reason:"circuit_open"}` when open; same `breaker` snapshot when enabled), optional **`cors`** (`CorsConfig`: `origins` `["*"]` or list, `methods`, `headers`; default deny; default expose `Retry-After` + `X-Request-Id`), **`X-Request-Id`** (optional request header, echoed on every response; omitted → generated UUID; `requestId` on `AuditEvent` / webhooks), **gzip audit export** (`?gzip=1` or `Accept-Encoding: gzip` → `Content-Encoding: gzip`, filename `.json.gz` / `.csv.gz`), and outbound **audit webhooks** (`AuditWebhook` / `WebhookEndpoint`; optional `secret` → `X-Webhook-Signature: sha256=<hex>` HMAC-SHA256 of the raw body; always `X-Webhook-Timestamp`; OSS **1 retry** on 5xx/network/timeout after ~50ms; simple HMAC OSS; exponential backoff / queues, key rotation / timestamp replay window enforcement = paid later). `GET /admin/tenants` returns allow/deny counts + limits with `apiKeyMasked` only (no raw keys). `GET /admin/tenants/{tenantId}` (`adminGetTenant`) returns one tenant with `hasApiKey` / `hasPreviousApiKey` / `allow` / `deny` / `rateLimit` — **never** raw keys; unknown id → `404` `tenant_not_found`. `POST /admin/tenants/{tenantId}/rotate` returns the new key once (`TenantRotateResponse`); audit `token_rotated` never includes secrets.
- Live serve: `GET /openapi.json` loads that file; `GET /metrics` exposes in-memory Prometheus counters (process lifetime; resets on restart), including `ip_denied_total`, `body_too_large_total`, `upstream_timeout_total`, `circuit_open_total`, and `webhook_retries_total`.
- **Dogfood A→B**: regenerate gateway clients with portfolio `make dogfood-a-b` (A reads this OpenAPI; output under `sdk/generated/`, gitignored).



### X-Request-Id

Optional request header for log/audit correlation:

- Incoming `X-Request-Id` is echoed on **every** HTTP response (including 4xx/5xx and OPTIONS).
- If omitted or empty, the gateway generates a UUID (`crypto.randomUUID()`). Values are trimmed, CR/LF stripped, and capped at 128 characters.
- The resolved id is stored as `requestId` on JSONL audit events (so `GET /audit`, `GET /audit/export` JSON/CSV including gzip packs, `GET /admin/audit.csv` / `GET /admin/audit.md` / `GET /admin/audit.html`, and CLI `export-audit` include it) and on webhook payloads (`requestId` + `event.requestId`).
- local-mvp sends a custom id, asserts the response header, and checks the audit line.

### CORS

Optional policy field (browser callers). **Default: deny** — omit `cors` or set `origins: []` and the gateway sends **no** CORS headers (OPTIONS 404).

```json
{
  "cors": {
    "origins": ["http://localhost:3000"],
    "methods": ["GET", "POST", "OPTIONS"],
    "headers": ["Content-Type", "Authorization", "X-Api-Key", "X-Admin-Token", "X-Request-Id", "MCP-Protocol-Version", "Mcp-Session-Id"]
  }
}
```

- `origins: ["*"]` allows any Origin (`Access-Control-Allow-Origin: *`).
- Explicit list: OPTIONS preflight with a listed `Origin` → **204** + ACAO / Allow-Methods / Allow-Headers; unlisted Origin (e.g. `http://evil.example`) → **403** `{error:"forbidden",reason:"cors_denied"}` (no ACAO).
- GET/POST: when `Origin` matches, responses include `Access-Control-Allow-Origin` (and `Vary: Origin` when reflecting). Mismatch: request is processed as usual **without** ACAO.
- `methods` / `headers` optional; defaults shown above.
- Default expose headers (`Access-Control-Expose-Headers`) include **`Retry-After`**, **`X-Request-Id`**, **`MCP-Protocol-Version`**, and **`Mcp-Session-Id`** (GET + OPTIONS). Allowlist/deny unchanged.
- local-mvp sets `origins: ["http://localhost:3000"]` and proves allowed vs evil preflight (GET/OPTIONS ACEH includes `retry-after`, case-insensitive).

### Request body size limit (`maxBodyBytes`)

```json
{
  "maxBodyBytes": 1048576,
  "tenants": [
    {
      "id": "restricted",
      "apiKey": "ten_restricted_dev",
      "maxBodyBytes": 65536
    }
  ]
}
```

- Default when omitted: **1048576** (1 MiB).
- Per-tenant `maxBodyBytes` overrides the global value when set (positive integer).
- Enforced on `POST /tools/call` (and `/mcp/tools/call`) **before** `JSON.parse`: reject when `Content-Length` exceeds the limit, or when streamed/chunked bytes exceed the limit.
- Over limit → `413 {"error":"payload_too_large"}`; counter `body_too_large_total`.

### Per-tenant IP allowlist

Optional tenant field:

```json
{
  "id": "acme",
  "apiKey": "ten_acme_dev",
  "ipAllowlist": ["127.0.0.1", "::1", "10.0.0.0/8"]
}
```

- Absent / empty → no IP gate.
- IPv4: exact or CIDR with prefix **`/8`**, **`/16`**, or **`/24`** only.
- IPv6: exact match only (IPv4-mapped `::ffff:x.x.x.x` normalized to IPv4).
- Client IP preference: first `X-Forwarded-For` hop, else socket `remoteAddress`.
- **stack-demo / local-mvp** talk to the gateway on **loopback** (`127.0.0.1`); if you set `ipAllowlist`, include loopback (or a matching CIDR) so demos keep working.

### Disk vs export redaction modes

Two independent switches (do not confuse):

| Mode | Config / flag | When it applies | Default |
|------|---------------|-----------------|--------|
| **Export / query redaction** | `?redact=` / `--redact` / `--no-redact`, else `export.redactDefault` | `GET /audit`, `GET /audit/export`, CLI `export-audit` — transforms events **on read** | `false` (local-mvp keeps unredacted export tests) |
| **Redact-on-write** | `audit.redactOnWrite: true` | JSONL append at call time — disk never stores raw `arguments`/`result` (keeps `argumentKeysHash`) | `false` |
| **Webhook redaction** | `webhooksRedact` (default **true**); also if `redactOnWrite` / `export.redactDefault` | Audit webhook POST payload | `true` |

Use **export redaction** when operators need full local JSONL for debugging but must hand PII-safe packs to security. Use **redact-on-write** when disk itself must not retain secrets (stricter retention). Webhooks prefer redacted payloads by default (`webhooksRedact: true`). Live `/tools/call` responses are never redacted by these modes.
