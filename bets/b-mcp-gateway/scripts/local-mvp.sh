#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PORT="${PORT:-8787}"
UPSTREAM_PORT="${UPSTREAM_PORT:-8790}"
WH_PORT="${WH_PORT:-8792}"
WH_OUT="$ROOT/data/webhook-last.json"
WH_HDR="$ROOT/data/webhook-last.headers.json"
AUDIT="$ROOT/data/audit.jsonl"
POLICY_SRC="$ROOT/config/policy.json"
POLICY="$ROOT/data/policy.mvp.json"
rm -f "$AUDIT" "$WH_OUT" "$WH_HDR"
mkdir -p "$ROOT/data"
unset LOG_FORMAT || true
unset AUDIT_MAX_EVENTS || true
unset MCP_SESSION_TTL_SEC || true

ACME_KEY="ten_acme_dev"
REST_KEY="ten_restricted_dev"
IPLOCK_KEY="ten_iplock_dev"
ADMIN="admin-dev-token"

node src/cli.js smoke

# Start mock HTTP upstream + webhook receiver, then materialize MVP policy.
node mock-upstream.js --port "$UPSTREAM_PORT" >"$ROOT/data/mock-upstream.log" 2>&1 &
UP_PID=$!
node mock-webhook-receiver.js --port "$WH_PORT" --out "$WH_OUT" --headers-out "$WH_HDR" >"$ROOT/data/mock-webhook.log" 2>&1 &
WH_PID=$!

node --input-type=module -e '
import fs from "node:fs";
const src = process.argv[1];
const dst = process.argv[2];
const upPort = process.argv[3];
const whPort = process.argv[4];
const p = JSON.parse(fs.readFileSync(src, "utf8"));
p.upstream = { type: "http", baseUrl: "http://127.0.0.1:" + upPort, timeoutMs: 30000, breaker: { enabled: false } };
// local-mvp uses a small limit so Content-Length/chunk 413 proves stay fast;
// product default remains 1048576 (see config/policy.json + DEFAULT_MAX_BODY_BYTES).
p.maxBodyBytes = 1024;
const extra = ["upstreamPing", "upstreamEcho"];
p.allow = Array.from(new Set([...(p.allow || []), ...extra]));
for (const t of p.tenants || []) {
  if (t.id === "acme") {
    t.allow = Array.from(new Set([...(t.allow || []), ...extra]));
  }
}
// expose upstream tools in local catalog too (optional; merge also pulls live list)
p.tools = [
  ...(p.tools || []),
  {
    name: "upstreamPing",
    description: "Proxied to mock upstream",
    inputSchema: { type: "object", properties: { note: { type: "string" } } },
  },
];
// Audit webhook fan-out → local mock receiver (OSS 1 retry on 5xx/timeout; backoff/queues = paid)
p.webhooks = [
  { url: "http://127.0.0.1:" + whPort + "/hook", events: ["tool_call", "deny"] },
];
p.webhooksRedact = true;
// local-mvp CORS: explicit allowlist (default policy.cors.origins=[] denies all)
p.cors = {
  origins: ["http://localhost:3000"],
  methods: ["GET", "POST", "DELETE", "OPTIONS"],
  headers: ["Content-Type", "Authorization", "X-Api-Key", "X-Admin-Token", "X-Request-Id", "MCP-Protocol-Version", "Mcp-Session-Id"],
};
fs.writeFileSync(dst, JSON.stringify(p, null, 2) + "\n");
' "$POLICY_SRC" "$POLICY" "$UPSTREAM_PORT" "$WH_PORT"

node src/cli.js serve --port "$PORT" --config "$POLICY" --audit "$AUDIT" >"$ROOT/data/server.log" 2>&1 &
PID=$!
cleanup() {
  kill "$PID" 2>/dev/null || true
  kill "$UP_PID" 2>/dev/null || true
  kill "$WH_PID" 2>/dev/null || true
  wait "$PID" 2>/dev/null || true
  wait "$UP_PID" 2>/dev/null || true
  wait "$WH_PID" 2>/dev/null || true
}
trap cleanup EXIT

for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$UPSTREAM_PORT/health" >/dev/null \
     && curl -sf "http://127.0.0.1:$WH_PORT/health" >/dev/null \
     && curl -sf "http://127.0.0.1:$PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
done

HEALTH="$(curl -sf "http://127.0.0.1:$PORT/health")"
echo "health=$HEALTH"
echo "$HEALTH" | grep -q '"ok":true'
echo "$HEALTH" | grep -q '"connected":true'
echo "$HEALTH" | grep -q 'upstreamPing'
# breaker disabled in main local-mvp policy — snapshot omitted; ok:true unchanged
echo "$HEALTH" > /tmp/b-health-main.json
node --input-type=module -e '
import fs from "node:fs";
const h = JSON.parse(fs.readFileSync("/tmp/b-health-main.json", "utf8"));
if (h.ok !== true) { console.error("main /health ok !== true", h); process.exit(1); }
if (Object.prototype.hasOwnProperty.call(h, "breaker")) {
  console.error("main /health should omit breaker when disabled", h.breaker);
  process.exit(1);
}
console.log("health_ok_breaker_omitted");
'

# GET /ready (breaker disabled): 200 {ok:true}, no breaker snapshot
READY_MAIN="$(curl -s -o /tmp/b-ready-main.json -w '%{http_code}' "http://127.0.0.1:$PORT/ready")"
echo "ready_main_status=$READY_MAIN body=$(cat /tmp/b-ready-main.json)"
test "$READY_MAIN" = "200"
node --input-type=module -e '
import fs from "node:fs";
const r = JSON.parse(fs.readFileSync("/tmp/b-ready-main.json", "utf8"));
if (r.ok !== true) { console.error("main /ready ok !== true", r); process.exit(1); }
if (r.reason) { console.error("main /ready should omit reason when ready", r); process.exit(1); }
if (Object.prototype.hasOwnProperty.call(r, "breaker")) {
  console.error("main /ready should omit breaker when disabled", r.breaker);
  process.exit(1);
}
console.log("ready_ok_breaker_omitted");
'

# X-Request-Id: omitted → generated UUID echoed on every response
curl -s -o /tmp/b-health-rid.json -D /tmp/b-health-rid.h "http://127.0.0.1:$PORT/health" >/dev/null
grep -qiE '^x-request-id:' /tmp/b-health-rid.h
GEN_RID="$(tr -d '\r' < /tmp/b-health-rid.h | awk 'BEGIN{IGNORECASE=1} /^x-request-id:/{print $2; exit}')"
echo "generated_request_id=$GEN_RID"
echo "$GEN_RID" | grep -qE '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
echo "request_id_generated_ok"

# OpenAPI document served from file
curl -sf "http://127.0.0.1:$PORT/openapi.json" -o "$ROOT/data/openapi.json"
test -s "$ROOT/data/openapi.json"
grep -q '"openapi"' "$ROOT/data/openapi.json"
node --input-type=module -e '
import fs from "node:fs";
const spec = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
const paths = Object.keys(spec.paths || {});
for (const p of ["/health","/ready","/tools/list","/tools/call","/mcp","/audit","/audit/export","/admin/reload","/admin/tenants","/admin/tenants/{tenantId}","/admin/sessions","/admin/sessions/{id}","/admin/config","/admin/webhooks","/admin/tenants/{tenantId}/rotate","/admin/tenants/rotate","/admin/audit.csv","/admin/audit.md","/admin/audit.html","/admin/audit"]) {
  if (!paths.includes(p)) { console.error("missing path", p); process.exit(1); }
}
if ((spec.paths["/mcp"] || {}).post?.operationId !== "mcpJsonRpc") {
  console.error("openapi /mcp POST missing mcpJsonRpc");
  process.exit(1);
}
if ((spec.paths["/mcp"] || {}).get?.operationId !== "mcpStreamableGet") {
  console.error("openapi /mcp GET missing mcpStreamableGet");
  process.exit(1);
}
if (!(spec.paths["/mcp"] || {}).get?.responses?.["405"]) {
  console.error("openapi /mcp GET missing 405");
  process.exit(1);
}
if ((spec.paths["/mcp"] || {}).delete?.operationId !== "mcpSessionDelete") {
  console.error("openapi /mcp DELETE missing mcpSessionDelete");
  process.exit(1);
}
if (!(spec.paths["/mcp"] || {}).delete?.responses?.["204"]) {
  console.error("openapi /mcp DELETE missing 204");
  process.exit(1);
}
if (!(spec.paths["/mcp"] || {}).delete?.responses?.["400"]) {
  console.error("openapi /mcp DELETE missing 400 session_id_required");
  process.exit(1);
}
if (!(spec.paths["/mcp"] || {}).delete?.responses?.["404"]) {
  console.error("openapi /mcp DELETE missing 404 session_not_found");
  process.exit(1);
}
if (!/Streamable HTTP|POST JSON-RPC|no SSE/i.test(String(spec.paths["/mcp"]?.post?.description || ""))) {
  console.error("openapi /mcp POST missing Streamable HTTP POST-only note");
  process.exit(1);
}
if (!(spec.paths["/mcp"] || {}).post?.responses?.["404"]) {
  console.error("openapi /mcp POST missing 404 session_expired");
  process.exit(1);
}
const mcpDesc = String(spec.paths["/mcp"]?.post?.description || "") + " " + String(spec.info?.description || "");
if (!/session_expired/i.test(mcpDesc) || !/3600/i.test(mcpDesc)) {
  console.error("openapi missing session TTL / session_expired note");
  process.exit(1);
}
if ((spec.paths["/admin/tenants/{tenantId}/rotate"] || {}).post?.operationId !== "adminRotateTenantToken") {
  console.error("openapi rotate missing adminRotateTenantToken");
  process.exit(1);
}
if ((spec.paths["/admin/sessions"] || {}).get?.operationId !== "adminListSessions") {
  console.error("openapi /admin/sessions missing adminListSessions");
  process.exit(1);
}
if ((spec.paths["/admin/config"] || {}).get?.operationId !== "adminGetConfig") {
  console.error("openapi /admin/config missing adminGetConfig");
  process.exit(1);
}
if ((spec.paths["/admin/tenants/{tenantId}"] || {}).get?.operationId !== "adminGetTenant") {
  console.error("openapi /admin/tenants/{tenantId} missing adminGetTenant");
  process.exit(1);
}
if (!(spec.paths["/admin/tenants/{tenantId}"] || {}).get?.responses?.["404"]) {
  console.error("openapi /admin/tenants/{tenantId} GET missing 404");
  process.exit(1);
}
if (!(spec.paths["/admin/tenants/{tenantId}"] || {}).get?.responses?.["401"]) {
  console.error("openapi /admin/tenants/{tenantId} GET missing 401");
  process.exit(1);
}
if ((spec.paths["/admin/sessions/{id}"] || {}).delete?.operationId !== "adminDeleteSession") {
  console.error("openapi /admin/sessions/{id} missing adminDeleteSession");
  process.exit(1);
}
if (!(spec.paths["/admin/sessions/{id}"] || {}).delete?.responses?.["204"]) {
  console.error("openapi /admin/sessions/{id} DELETE missing 204");
  process.exit(1);
}
if (!(spec.paths["/admin/sessions/{id}"] || {}).delete?.responses?.["404"]) {
  console.error("openapi /admin/sessions/{id} DELETE missing 404");
  process.exit(1);
}
if (!(spec.paths["/admin/sessions/{id}"] || {}).delete?.responses?.["401"]) {
  console.error("openapi /admin/sessions/{id} DELETE missing 401");
  process.exit(1);
}
if (!spec.components?.schemas?.SessionInventory || !spec.components?.schemas?.SessionInventoryRow) {
  console.error("openapi missing SessionInventory schemas");
  process.exit(1);
}
if (!spec.components?.schemas?.AdminRuntimeConfig) {
  console.error("openapi missing AdminRuntimeConfig schema");
  process.exit(1);
}
if ((spec.paths["/admin/webhooks"] || {}).get?.operationId !== "adminListWebhooks") {
  console.error("openapi /admin/webhooks missing adminListWebhooks");
  process.exit(1);
}
if (!(spec.paths["/admin/webhooks"] || {}).get?.responses?.["401"]) {
  console.error("openapi /admin/webhooks GET missing 401");
  process.exit(1);
}
if (!spec.components?.schemas?.WebhookInventory || !spec.components?.schemas?.WebhookInventoryRow) {
  console.error("openapi missing WebhookInventory schemas");
  process.exit(1);
}

if (!spec.components?.schemas?.TenantDetail) {
  console.error("openapi missing TenantDetail schema");
  process.exit(1);
}
if (!spec.components?.schemas?.TenantRotateResponse) {
  console.error("openapi missing TenantRotateResponse");
  process.exit(1);
}
if ((spec.paths["/admin/audit.csv"] || {}).get?.operationId !== "getAdminAuditCsv") {
  console.error("openapi /admin/audit.csv missing getAdminAuditCsv");
  process.exit(1);
}
if ((spec.paths["/admin/audit"] || {}).get?.operationId !== "getAdminAudit") {
  console.error("openapi /admin/audit missing getAdminAudit");
  process.exit(1);
}
if ((spec.paths["/admin/audit.md"] || {}).get?.operationId !== "getAdminAuditMd") {
  console.error("openapi /admin/audit.md missing getAdminAuditMd");
  process.exit(1);
}
if ((spec.paths["/admin/audit.html"] || {}).get?.operationId !== "getAdminAuditHtml") {
  console.error("openapi /admin/audit.html missing getAdminAuditHtml");
  process.exit(1);
}
const schemes = spec.components?.securitySchemes || {};
if (!schemes.ApiKeyAuth || !schemes.BearerAuth) {
  console.error("missing ApiKeyAuth/BearerAuth", Object.keys(schemes));
  process.exit(1);
}
const desc = String(spec.info?.description || "");
if (!/cors/i.test(desc)) {
  console.error("openapi info.description missing CORS note");
  process.exit(1);
}
if (!spec.components?.schemas?.CorsConfig) {
  console.error("openapi missing components.schemas.CorsConfig");
  process.exit(1);
}
const corsDesc = String(spec.components.schemas.CorsConfig.description || "");
if (!/Retry-After/i.test(corsDesc) || !/X-Request-Id/i.test(corsDesc) || !/expose/i.test(corsDesc)) {
  console.error("openapi CorsConfig missing Retry-After / X-Request-Id expose note");
  process.exit(1);
}
if (!spec.components?.schemas?.UpstreamConfig) {
  console.error("openapi missing components.schemas.UpstreamConfig");
  process.exit(1);
}
const call504 = spec.paths?.["/tools/call"]?.post?.responses?.["504"];
if (!call504) {
  console.error("openapi /tools/call missing 504");
  process.exit(1);
}
if (!spec.components?.responses?.UpstreamTimeout) {
  console.error("openapi missing components.responses.UpstreamTimeout");
  process.exit(1);
}
const call503 = spec.paths?.["/tools/call"]?.post?.responses?.["503"];
if (!call503) {
  console.error("openapi /tools/call missing 503");
  process.exit(1);
}
if (!spec.components?.responses?.CircuitOpen) {
  console.error("openapi missing components.responses.CircuitOpen");
  process.exit(1);
}
const coHeaders = spec.components.responses.CircuitOpen.headers || {};
if (!coHeaders["Retry-After"]) {
  console.error("openapi CircuitOpen missing Retry-After header", coHeaders);
  process.exit(1);
}
if (!spec.components?.headers?.RetryAfter) {
  console.error("openapi missing components.headers.RetryAfter");
  process.exit(1);
}
const breaker = spec.components?.schemas?.UpstreamConfig?.properties?.breaker;
if (!breaker) {
  console.error("openapi UpstreamConfig missing breaker");
  process.exit(1);
}
if (!spec.components?.schemas?.Health) {
  console.error("openapi missing components.schemas.Health");
  process.exit(1);
}
if (!spec.components?.schemas?.Ready) {
  console.error("openapi missing components.schemas.Ready");
  process.exit(1);
}
if (!spec.components?.schemas?.CircuitBreakerSnapshot) {
  console.error("openapi missing components.schemas.CircuitBreakerSnapshot");
  process.exit(1);
}
const healthBreaker = spec.components.schemas.Health.properties?.breaker;
if (!healthBreaker) {
  console.error("openapi Health schema missing breaker");
  process.exit(1);
}
const snap = spec.components.schemas.CircuitBreakerSnapshot;
const states = snap.properties?.state?.enum || [];
for (const s of ["closed", "open", "half_open"]) {
  if (!states.includes(s)) {
    console.error("openapi CircuitBreakerSnapshot missing state", s, states);
    process.exit(1);
  }
}
if (!snap.properties?.failures || !snap.properties?.openUntil) {
  console.error("openapi CircuitBreakerSnapshot missing failures/openUntil");
  process.exit(1);
}
const healthRef = spec.paths?.["/health"]?.get?.responses?.["200"]?.content?.["application/json"]?.schema?.$ref || "";
if (!/Health/.test(healthRef)) {
  console.error("openapi /health 200 schema should $ref Health", healthRef);
  process.exit(1);
}
const ready200 = spec.paths?.["/ready"]?.get?.responses?.["200"];
const ready503 = spec.paths?.["/ready"]?.get?.responses?.["503"];
if (!ready200 || !ready503) {
  console.error("openapi /ready missing 200/503");
  process.exit(1);
}
const ready200Ref = ready200.content?.["application/json"]?.schema?.$ref || "";
const ready503Ref = ready503.content?.["application/json"]?.schema?.$ref || "";
if (!/Ready/.test(ready200Ref) || !/Ready/.test(ready503Ref)) {
  console.error("openapi /ready 200/503 should $ref Ready", ready200Ref, ready503Ref);
  process.exit(1);
}
if (spec.paths["/ready"].get.operationId !== "getReady") {
  console.error("openapi /ready missing operationId getReady");
  process.exit(1);
}
if (!ready503.headers?.["Retry-After"]) {
  console.error("openapi /ready 503 missing Retry-After header");
  process.exit(1);
}
const readyBreaker = spec.components.schemas.Ready.properties?.breaker;
if (!readyBreaker) {
  console.error("openapi Ready schema missing breaker");
  process.exit(1);
}
const readyReasons = spec.components.schemas.Ready.properties?.reason?.enum || [];
if (!readyReasons.includes("circuit_open") || !readyReasons.includes("shutting_down")) {
  console.error("openapi Ready.reason enum missing circuit_open/shutting_down", readyReasons);
  process.exit(1);
}
if (!spec.components.schemas.Health.properties?.shuttingDown) {
  console.error("openapi Health schema missing shuttingDown");
  process.exit(1);
}
if (!/timeoutMs|upstream_timeout/i.test(desc)) {
  console.error("openapi info.description missing upstream timeout note");
  process.exit(1);
}
if (!/circuit_open|breaker/i.test(desc)) {
  console.error("openapi info.description missing circuit breaker note");
  process.exit(1);
}
if (!/Retry-After/i.test(desc)) {
  console.error("openapi info.description missing Retry-After note");
  process.exit(1);
}
if (!/health.*breaker|breaker: \{ state/i.test(desc)) {
  console.error("openapi info.description missing GET /health breaker snapshot note");
  process.exit(1);
}
if (!/GET \/ready|\/ready/i.test(desc) || !/circuit_open/.test(desc)) {
  console.error("openapi info.description missing GET /ready readiness note");
  process.exit(1);
}
if (!/X-Request-Id|requestId/i.test(desc)) {
  console.error("openapi info.description missing X-Request-Id note");
  process.exit(1);
}
if (!/Streamable HTTP/i.test(desc) || !/MCP-Protocol-Version/i.test(desc) || !/405/i.test(desc)) {
  console.error("openapi info.description missing Streamable HTTP / MCP-Protocol-Version / 405 note");
  process.exit(1);
}
if (!/gzip/i.test(desc)) {
  console.error("openapi info.description missing gzip export note");
  process.exit(1);
}
const exportParams = spec.paths?.["/audit/export"]?.get?.parameters || [];
if (!exportParams.some((q) => q && q.name === "gzip")) {
  console.error("openapi /audit/export missing gzip query param");
  process.exit(1);
}
const enc = spec.paths?.["/audit/export"]?.get?.responses?.["200"]?.headers?.["Content-Encoding"];
if (!enc) {
  console.error("openapi /audit/export 200 missing Content-Encoding header");
  process.exit(1);
}
if (!spec.components?.parameters?.XRequestId) {
  console.error("openapi missing components.parameters.XRequestId");
  process.exit(1);
}
if (!spec.components?.headers?.XRequestId) {
  console.error("openapi missing components.headers.XRequestId");
  process.exit(1);
}
if (!spec.components?.schemas?.AuditEvent) {
  console.error("openapi missing components.schemas.AuditEvent");
  process.exit(1);
}
if (!spec.components?.schemas?.AuditWebhook) {
  console.error("openapi missing components.schemas.AuditWebhook");
  process.exit(1);
}
if (!/X-Webhook-Signature|HMAC-SHA256|webhooks\[\]/.test(desc)) {
  console.error("openapi info.description missing webhook HMAC note");
  process.exit(1);
}
if (!/X-Webhook-Timestamp/.test(desc)) {
  console.error("openapi info.description missing webhook timestamp note");
  process.exit(1);
}
if (!/retry/i.test(desc) || !/50ms/.test(desc)) {
  console.error("openapi info.description missing webhook 1-retry note");
  process.exit(1);
}
console.log("openapi_paths_ok", paths.length);
' "$ROOT/data/openapi.json"

# CORS: local-mvp policy cors.origins=["http://localhost:3000"]
# OPTIONS preflight allowed origin → 204 + ACAO; evil origin → 403 cors_denied
CORS_OK="$(curl -s -o /tmp/b-cors-ok -D /tmp/b-cors-ok.h -w '%{http_code}' \
  -X OPTIONS "http://127.0.0.1:$PORT/health" \
  -H 'Origin: http://localhost:3000' \
  -H 'Access-Control-Request-Method: GET')"
echo "cors_preflight_ok_status=$CORS_OK"
test "$CORS_OK" = "204"
grep -qiE '^access-control-allow-origin:[[:space:]]*http://localhost:3000' /tmp/b-cors-ok.h
grep -qiE '^access-control-allow-methods:' /tmp/b-cors-ok.h
grep -qiE '^access-control-allow-methods:.*DELETE' /tmp/b-cors-ok.h
grep -qiE '^access-control-allow-headers:' /tmp/b-cors-ok.h
grep -qiE '^access-control-expose-headers:.*retry-after' /tmp/b-cors-ok.h
grep -qiE '^access-control-expose-headers:.*x-request-id' /tmp/b-cors-ok.h

CORS_POST_PF="$(curl -s -o /tmp/b-cors-post -D /tmp/b-cors-post.h -w '%{http_code}' \
  -X OPTIONS "http://127.0.0.1:$PORT/tools/list" \
  -H 'Origin: http://localhost:3000' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: authorization,content-type')"
echo "cors_preflight_post_status=$CORS_POST_PF"
test "$CORS_POST_PF" = "204"
grep -qiE '^access-control-allow-origin:[[:space:]]*http://localhost:3000' /tmp/b-cors-post.h

CORS_EVIL="$(curl -s -o /tmp/b-cors-evil.json -D /tmp/b-cors-evil.h -w '%{http_code}' \
  -X OPTIONS "http://127.0.0.1:$PORT/health" \
  -H 'Origin: http://evil.example' \
  -H 'Access-Control-Request-Method: GET')"
echo "cors_preflight_evil_status=$CORS_EVIL body=$(cat /tmp/b-cors-evil.json)"
test "$CORS_EVIL" = "403"
grep -q 'cors_denied' /tmp/b-cors-evil.json
if grep -qiE '^access-control-allow-origin:[[:space:]]*http://evil.example' /tmp/b-cors-evil.h; then
  echo "evil origin must not receive ACAO"
  exit 1
fi

# GET/POST include ACAO when Origin matches
HEALTH_CORS="$(curl -s -o /tmp/b-health-cors.json -D /tmp/b-health-cors.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/health" -H 'Origin: http://localhost:3000')"
echo "cors_get_health_status=$HEALTH_CORS"
test "$HEALTH_CORS" = "200"
grep -qiE '^access-control-allow-origin:[[:space:]]*http://localhost:3000' /tmp/b-health-cors.h
grep -qiE '^access-control-expose-headers:.*retry-after' /tmp/b-health-cors.h
grep -qiE '^access-control-expose-headers:.*x-request-id' /tmp/b-health-cors.h

LIST_CORS="$(curl -s -o /tmp/b-list-cors.json -D /tmp/b-list-cors.h -w '%{http_code}' \
  -X POST "http://127.0.0.1:$PORT/tools/list" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -H 'Origin: http://localhost:3000' -d '{}')"
echo "cors_post_list_status=$LIST_CORS"
test "$LIST_CORS" = "200"
grep -qiE '^access-control-allow-origin:[[:space:]]*http://localhost:3000' /tmp/b-list-cors.h

# disallowed Origin on GET: request succeeds, no ACAO
HEALTH_EVIL="$(curl -s -o /tmp/b-health-evil.json -D /tmp/b-health-evil.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/health" -H 'Origin: http://evil.example')"
echo "cors_get_evil_status=$HEALTH_EVIL"
test "$HEALTH_EVIL" = "200"
if grep -qiE '^access-control-allow-origin:' /tmp/b-health-evil.h; then
  echo "disallowed origin should not get ACAO"
  cat /tmp/b-health-evil.h
  exit 1
fi
echo "cors_ok"

# GET /admin/tenants — admin token required; never leak raw apiKey
TENANTS_UNAUTH="$(curl -s -o /tmp/b-tenants-unauth.json -w '%{http_code}' \
  "http://127.0.0.1:$PORT/admin/tenants")"
echo "admin_tenants_unauth_status=$TENANTS_UNAUTH body=$(cat /tmp/b-tenants-unauth.json)"
test "$TENANTS_UNAUTH" = "401"
grep -q 'unauthorized_admin' /tmp/b-tenants-unauth.json

TENANTS_BAD="$(curl -s -o /tmp/b-tenants-bad.json -w '%{http_code}' \
  "http://127.0.0.1:$PORT/admin/tenants" -H "X-Admin-Token: wrong")"
echo "admin_tenants_bad_status=$TENANTS_BAD body=$(cat /tmp/b-tenants-bad.json)"
test "$TENANTS_BAD" = "401"

TENANTS_JSON="$(curl -sf "http://127.0.0.1:$PORT/admin/tenants" -H "X-Admin-Token: $ADMIN")"
echo "admin_tenants=$TENANTS_JSON"
echo "$TENANTS_JSON" | grep -q '"ok":true'
# must not contain raw keys from policy
if echo "$TENANTS_JSON" | grep -qE 'ten_acme_dev|ten_restricted_dev|ten_iplock_dev'; then
  echo "admin/tenants leaked raw apiKey"
  exit 1
fi
if echo "$TENANTS_JSON" | grep -qE '"apiKey"[[:space:]]*:'; then
  echo "admin/tenants must not include apiKey field (use apiKeyMasked)"
  exit 1
fi
node --input-type=module -e '
const body = JSON.parse(process.argv[1]);
if (!Array.isArray(body.tenants) || body.tenants.length < 3) {
  console.error("expected >=3 tenants", body);
  process.exit(1);
}
const byId = Object.fromEntries(body.tenants.map((t) => [t.id, t]));
for (const id of ["acme", "restricted", "ip-locked"]) {
  if (!byId[id]) { console.error("missing tenant", id); process.exit(1); }
}
const acme = byId.acme;
for (const k of ["id","allowCount","denyCount","rateLimit","hasIpAllowlist","maxBodyBytes"]) {
  if (!(k in acme)) { console.error("missing field", k, acme); process.exit(1); }
}
if (acme.rateLimit !== 120) { console.error("acme rateLimit", acme.rateLimit); process.exit(1); }
if (acme.hasIpAllowlist !== true) { console.error("acme hasIpAllowlist"); process.exit(1); }
if (typeof acme.allowCount !== "number" || acme.allowCount < 4) {
  console.error("acme allowCount", acme.allowCount); process.exit(1);
}
if (typeof acme.denyCount !== "number" || acme.denyCount < 1) {
  console.error("acme denyCount", acme.denyCount); process.exit(1);
}
if (acme.maxBodyBytes !== 1024) { console.error("acme maxBodyBytes (mvp global override)", acme.maxBodyBytes); process.exit(1); }
if (typeof acme.apiKeyMasked !== "string" || !acme.apiKeyMasked.endsWith("_dev")) {
  console.error("acme apiKeyMasked should end with last4 _dev", acme.apiKeyMasked); process.exit(1);
}
if (acme.apiKeyMasked.includes("ten_acme")) {
  console.error("apiKeyMasked still exposes prefix", acme.apiKeyMasked); process.exit(1);
}
const rest = byId.restricted;
if (rest.hasIpAllowlist !== false) { console.error("restricted hasIpAllowlist"); process.exit(1); }
if (rest.maxBodyBytes !== 65536) { console.error("restricted maxBodyBytes", rest.maxBodyBytes); process.exit(1); }
if (rest.rateLimit !== 30) { console.error("restricted rateLimit", rest.rateLimit); process.exit(1); }
const locked = byId["ip-locked"];
if (locked.hasIpAllowlist !== true) { console.error("ip-locked hasIpAllowlist"); process.exit(1); }
console.log("admin_tenants_ok", body.tenants.map((t) => t.id).join(","));
' "$TENANTS_JSON"

# GET /admin/tenants/{id} — one tenant, no secrets
TENANT_UNAUTH="$(curl -s -o /tmp/b-tenant-unauth.json -w '%{http_code}'   "http://127.0.0.1:$PORT/admin/tenants/acme")"
echo "admin_tenant_unauth_status=$TENANT_UNAUTH body=$(cat /tmp/b-tenant-unauth.json)"
test "$TENANT_UNAUTH" = "401"
grep -q 'unauthorized_admin' /tmp/b-tenant-unauth.json
if grep -qE 'ten_acme_dev|ten_restricted_dev|admin-dev-token' /tmp/b-tenant-unauth.json; then
  echo "admin/tenants/{id} 401 leaked secret"
  exit 1
fi

TENANT_JSON_CODE="$(curl -s -o /tmp/b-tenant.json -D /tmp/b-tenant.h -w '%{http_code}'   "http://127.0.0.1:$PORT/admin/tenants/acme" -H "X-Admin-Token: $ADMIN" -H "X-Request-Id: mvp-admin-tenant" -H "Origin: http://localhost:3000")"
echo "admin_tenant_status=$TENANT_JSON_CODE"
test "$TENANT_JSON_CODE" = "200"
grep -qiE '^x-request-id:[[:space:]]*mvp-admin-tenant' /tmp/b-tenant.h
grep -qiE '^access-control-allow-origin:[[:space:]]*http://localhost:3000' /tmp/b-tenant.h
if grep -qE 'ten_acme_dev|ten_restricted_dev|ten_iplock_dev|admin-dev-token' /tmp/b-tenant.json; then
  echo "admin/tenants/{id} leaked fixture apiKey"
  cat /tmp/b-tenant.json
  exit 1
fi
node --input-type=module -e '
const body = JSON.parse(process.argv[1]);
if (body.ok !== true || body.id !== "acme") { console.error("admin/tenants/{id} ok/id", body); process.exit(1); }
if (body.hasApiKey !== true) { console.error("hasApiKey", body); process.exit(1); }
if (body.hasPreviousApiKey !== false) { console.error("hasPreviousApiKey", body); process.exit(1); }
if (body.previousApiKeyExpiresAt !== null) { console.error("previousApiKeyExpiresAt", body); process.exit(1); }
if (!Array.isArray(body.allow) || body.allow.length < 4) { console.error("allow", body.allow); process.exit(1); }
if (!Array.isArray(body.deny) || body.deny.length < 1) { console.error("deny", body.deny); process.exit(1); }
if (body.rateLimit !== 120) { console.error("rateLimit", body.rateLimit); process.exit(1); }
if (body.hasIpAllowlist !== true) { console.error("hasIpAllowlist", body); process.exit(1); }
if (Object.prototype.hasOwnProperty.call(body, "apiKey") || Object.prototype.hasOwnProperty.call(body, "previousApiKey")) {
  console.error("secret field present", body); process.exit(1);
}
const dump = JSON.stringify(body);
if (/ten_acme_dev|ten_restricted_dev|ten_iplock_dev|admin-dev-token/.test(dump)) {
  console.error("leaked fixture apiKey", dump); process.exit(1);
}
console.log("admin_tenant_ok", body.id);
' "$(cat /tmp/b-tenant.json)"

TENANT_MISS="$(curl -s -o /tmp/b-tenant-miss.json -w '%{http_code}'   "http://127.0.0.1:$PORT/admin/tenants/no-such-tenant" -H "X-Admin-Token: $ADMIN")"
echo "admin_tenant_unknown_status=$TENANT_MISS body=$(cat /tmp/b-tenant-miss.json)"
test "$TENANT_MISS" = "404"
grep -q 'tenant_not_found' /tmp/b-tenant-miss.json
if grep -qE 'ten_acme_dev|admin-dev-token' /tmp/b-tenant-miss.json; then
  echo "admin/tenants/{id} 404 leaked secret"
  exit 1
fi

TENANT_CORS_PF="$(curl -s -o /tmp/b-tenant-cors -D /tmp/b-tenant-cors.h -w '%{http_code}'   -X OPTIONS "http://127.0.0.1:$PORT/admin/tenants/acme"   -H "Origin: http://localhost:3000"   -H "Access-Control-Request-Method: GET"   -H "Access-Control-Request-Headers: x-admin-token,x-request-id")"
echo "admin_tenant_cors_preflight_status=$TENANT_CORS_PF"
test "$TENANT_CORS_PF" = "204"
grep -qiE '^access-control-allow-origin:[[:space:]]*http://localhost:3000' /tmp/b-tenant-cors.h

# unknown / missing key -> 401
MISS="$(curl -s -o /tmp/b-miss.json -w '%{http_code}' -X POST "http://127.0.0.1:$PORT/tools/list" \
  -H 'content-type: application/json' -d '{}')"
echo "missing_key_status=$MISS body=$(cat /tmp/b-miss.json)"
test "$MISS" = "401"

BAD="$(curl -s -o /tmp/b-bad.json -w '%{http_code}' -X POST "http://127.0.0.1:$PORT/tools/list" \
  -H 'content-type: application/json' -H 'X-Api-Key: nope' -d '{}')"
echo "bad_key_status=$BAD body=$(cat /tmp/b-bad.json)"
test "$BAD" = "401"

LIST="$(curl -sf -X POST "http://127.0.0.1:$PORT/tools/list" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" -d '{}')"
echo "list=$LIST"
echo "$LIST" | grep -q '"name":"echo"'
echo "$LIST" | grep -q '"tenantId":"acme"'
echo "$LIST" | grep -q '"name":"upstreamPing"'
echo "$LIST" | grep -q '"upstreamConnected":true'
if echo "$LIST" | grep -q '"name":"deletePet"'; then
  echo "deny tool leaked in list"
  exit 1
fi

# GET /admin/config — redacted runtime config; admin token; never secrets
CFG_UNAUTH="$(curl -s -o /tmp/b-admin-cfg-unauth.json -w '%{http_code}' \
  "http://127.0.0.1:$PORT/admin/config")"
echo "admin_config_unauth_status=$CFG_UNAUTH body=$(cat /tmp/b-admin-cfg-unauth.json)"
test "$CFG_UNAUTH" = "401"
grep -q 'unauthorized_admin' /tmp/b-admin-cfg-unauth.json
if grep -qE 'ten_acme_dev|ten_restricted_dev|admin-dev-token|sk-|Bearer' /tmp/b-admin-cfg-unauth.json; then
  echo "admin/config 401 leaked secret"
  exit 1
fi

CFG_JSON="$(curl -s -o /tmp/b-admin-cfg.json -D /tmp/b-admin-cfg.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/admin/config" -H "X-Admin-Token: $ADMIN" -H "X-Request-Id: mvp-admin-cfg" -H "Origin: http://localhost:3000")"
echo "admin_config_status=$CFG_JSON"
test "$CFG_JSON" = "200"
grep -qiE '^x-request-id:[[:space:]]*mvp-admin-cfg' /tmp/b-admin-cfg.h
grep -qiE '^access-control-allow-origin:[[:space:]]*http://localhost:3000' /tmp/b-admin-cfg.h
node --input-type=module -e '
const body = JSON.parse(process.argv[1]);
if (body.ok !== true) { console.error("admin/config ok", body); process.exit(1); }
if (typeof body.sessionTtlSec !== "number") { console.error("missing sessionTtlSec", body); process.exit(1); }
if (body.sessionTtlSec !== 3600) { console.error("unexpected sessionTtlSec", body.sessionTtlSec); process.exit(1); }
if (body.sessionCap !== 10000) { console.error("unexpected sessionCap", body.sessionCap); process.exit(1); }
if (typeof body.auditMax !== "number" || typeof body.rotateGraceSec !== "number") {
  console.error("missing auditMax/rotateGraceSec", body); process.exit(1);
}
if (body.tenants?.count !== 3) { console.error("tenant count", body.tenants); process.exit(1); }
if (body.webhooks?.count !== 1 || body.webhooks?.destinations?.[0]?.hasWebhookSecret !== false) {
  console.error("webhooks", body.webhooks); process.exit(1);
}
if (!Array.isArray(body.cors?.origins) || body.cors.origins[0] !== "http://localhost:3000") {
  console.error("cors.origins", body.cors); process.exit(1);
}
if (typeof body.upstream?.timeoutMs !== "number" || !body.upstream?.breaker) {
  console.error("upstream", body.upstream); process.exit(1);
}
if (body.rateLimit?.perMinute == null) { console.error("rateLimit", body.rateLimit); process.exit(1); }
const dump = JSON.stringify(body);
if (Object.prototype.hasOwnProperty.call(body, "apiKey") || /"apiKey"\s*:/.test(dump)) {
  console.error("admin/config includes apiKey"); process.exit(1);
}
if (/ten_acme_dev|ten_restricted_dev|admin-dev-token|sk-|Bearer/i.test(dump)) {
  console.error("admin/config leaked secret", dump); process.exit(1);
}
console.log("admin_config_ok");
' "$(cat /tmp/b-admin-cfg.json)"

CFG_CORS_PF="$(curl -s -o /tmp/b-admin-cfg-cors -D /tmp/b-admin-cfg-cors.h -w '%{http_code}' \
  -X OPTIONS "http://127.0.0.1:$PORT/admin/config" \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: GET" \
  -H "Access-Control-Request-Headers: x-admin-token,x-request-id")"
echo "admin_config_cors_preflight_status=$CFG_CORS_PF"
test "$CFG_CORS_PF" = "204"
grep -qiE '^access-control-allow-origin:[[:space:]]*http://localhost:3000' /tmp/b-admin-cfg-cors.h


# GET /admin/webhooks — redacted outbound webhook inventory; admin token; never urls/secrets
HOOK_UNAUTH="$(curl -s -o /tmp/b-admin-hooks-unauth.json -w '%{http_code}' \
  "http://127.0.0.1:$PORT/admin/webhooks")"
echo "admin_webhooks_unauth_status=$HOOK_UNAUTH body=$(cat /tmp/b-admin-hooks-unauth.json)"
test "$HOOK_UNAUTH" = "401"
grep -q 'unauthorized_admin' /tmp/b-admin-hooks-unauth.json
if grep -qE 'ten_acme_dev|ten_restricted_dev|admin-dev-token|sk-|Bearer|whsec_' /tmp/b-admin-hooks-unauth.json; then
  echo "admin/webhooks 401 leaked secret"
  exit 1
fi

HOOK_TENANT="$(curl -s -o /tmp/b-admin-hooks-tenant.json -w '%{http_code}' \
  "http://127.0.0.1:$PORT/admin/webhooks" -H "Authorization: Bearer $ACME_KEY")"
echo "admin_webhooks_tenant_status=$HOOK_TENANT"
test "$HOOK_TENANT" = "401"
grep -q 'unauthorized_admin' /tmp/b-admin-hooks-tenant.json

HOOK_JSON="$(curl -s -o /tmp/b-admin-hooks.json -D /tmp/b-admin-hooks.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/admin/webhooks" -H "X-Admin-Token: $ADMIN" -H "X-Request-Id: mvp-admin-hooks" -H "Origin: http://localhost:3000")"
echo "admin_webhooks_status=$HOOK_JSON"
test "$HOOK_JSON" = "200"
grep -qiE '^x-request-id:[[:space:]]*mvp-admin-hooks' /tmp/b-admin-hooks.h
grep -qiE '^access-control-allow-origin:[[:space:]]*http://localhost:3000' /tmp/b-admin-hooks.h
node --input-type=module -e '
const body = JSON.parse(process.argv[1]);
if (body.ok !== true) { console.error("admin/webhooks ok", body); process.exit(1); }
if (typeof body.count !== "number" || body.count < 1) { console.error("admin/webhooks count", body); process.exit(1); }
if (!Array.isArray(body.webhooks) || body.webhooks.length < 1) { console.error("admin/webhooks list", body); process.exit(1); }
const row = body.webhooks[0];
if (row.hasUrl !== true || typeof row.hasSecret !== "boolean") { console.error("hasUrl/hasSecret", row); process.exit(1); }
if (!Array.isArray(row.events)) { console.error("events", row); process.exit(1); }
if (row.id == null) { console.error("missing id", row); process.exit(1); }
if (Object.prototype.hasOwnProperty.call(row, "url") || Object.prototype.hasOwnProperty.call(row, "secret")) {
  console.error("admin/webhooks includes url/secret"); process.exit(1);
}
const dump = JSON.stringify(body);
if (/"url"\s*:/.test(dump) || /"secret"\s*:/.test(dump)) {
  console.error("admin/webhooks leaked url/secret key"); process.exit(1);
}
if (/ten_acme_dev|ten_restricted_dev|admin-dev-token|sk-|Bearer|whsec_/i.test(dump)) {
  console.error("admin/webhooks leaked secret", dump); process.exit(1);
}
if (/127\.0\.0\.1:\d+\/hook/.test(dump)) {
  console.error("admin/webhooks leaked webhook url", dump); process.exit(1);
}
console.log("admin_webhooks_ok");
' "$(cat /tmp/b-admin-hooks.json)"

HOOK_CORS_PF="$(curl -s -o /tmp/b-admin-hooks-cors -D /tmp/b-admin-hooks-cors.h -w '%{http_code}' \
  -X OPTIONS "http://127.0.0.1:$PORT/admin/webhooks" \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: GET" \
  -H "Access-Control-Request-Headers: x-admin-token,x-request-id")"
echo "admin_webhooks_cors_preflight_status=$HOOK_CORS_PF"
test "$HOOK_CORS_PF" = "204"
grep -qiE '^access-control-allow-origin:[[:space:]]*http://localhost:3000' /tmp/b-admin-hooks-cors.h

# GET /admin/sessions — admin token; empty before any initialize (tombstones not listed)
SESS_UNAUTH="$(curl -s -o /tmp/b-admin-sess-unauth.json -w '%{http_code}' \
  "http://127.0.0.1:$PORT/admin/sessions")"
echo "admin_sessions_unauth_status=$SESS_UNAUTH body=$(cat /tmp/b-admin-sess-unauth.json)"
test "$SESS_UNAUTH" = "401"
grep -q 'unauthorized_admin' /tmp/b-admin-sess-unauth.json
if grep -qE 'ten_acme_dev|ten_restricted_dev|admin-dev-token' /tmp/b-admin-sess-unauth.json; then
  echo "admin/sessions 401 leaked secret"
  exit 1
fi

SESS_EMPTY="$(curl -s -o /tmp/b-admin-sess-empty.json -D /tmp/b-admin-sess-empty.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/admin/sessions" -H "X-Admin-Token: $ADMIN" -H "X-Request-Id: mvp-admin-sess-empty")"
echo "admin_sessions_empty_status=$SESS_EMPTY"
test "$SESS_EMPTY" = "200"
grep -qiE '^x-request-id:[[:space:]]*mvp-admin-sess-empty' /tmp/b-admin-sess-empty.h
node --input-type=module -e '
const body = JSON.parse(process.argv[1]);
if (body.ok !== true || body.count !== 0 || !Array.isArray(body.sessions) || body.sessions.length !== 0) {
  console.error("expected empty sessions", body);
  process.exit(1);
}
if (typeof body.ttlSec !== "number" || typeof body.cap !== "number") {
  console.error("missing ttlSec/cap", body);
  process.exit(1);
}
if (body.ttlSec !== 3600 || body.cap !== 10000) {
  console.error("unexpected ttlSec/cap", body.ttlSec, body.cap);
  process.exit(1);
}
const dump = JSON.stringify(body);
if (/ten_acme_dev|ten_restricted_dev|admin-dev-token|authorization/i.test(dump)) {
  console.error("admin/sessions empty leaked secret");
  process.exit(1);
}
console.log("admin_sessions_empty_ok");
' "$(cat /tmp/b-admin-sess-empty.json)"

SESS_CORS_PF="$(curl -s -o /tmp/b-admin-sess-cors -D /tmp/b-admin-sess-cors.h -w '%{http_code}' \
  -X OPTIONS "http://127.0.0.1:$PORT/admin/sessions" \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: GET" \
  -H "Access-Control-Request-Headers: x-admin-token,x-request-id")"
echo "admin_sessions_cors_preflight_status=$SESS_CORS_PF"
test "$SESS_CORS_PF" = "204"
grep -qiE '^access-control-allow-origin:[[:space:]]*http://localhost:3000' /tmp/b-admin-sess-cors.h
grep -qiE '^access-control-allow-methods:' /tmp/b-admin-sess-cors.h
grep -qiE '^access-control-allow-headers:' /tmp/b-admin-sess-cors.h

# Streamable HTTP MVP: GET /mcp 405 Allow: POST, DELETE (no SSE hang); POST JSON-RPC initialize + tools/list
GET_MCP="$(curl -s -o /tmp/b-mcp-get.json -D /tmp/b-mcp-get.h -w '%{http_code}' --max-time 2   "http://127.0.0.1:$PORT/mcp")"
echo "mcp_get_status=$GET_MCP body=$(cat /tmp/b-mcp-get.json)"
test "$GET_MCP" = "405"
grep -qiE '^allow:[[:space:]]*POST' /tmp/b-mcp-get.h
grep -qiE '^allow:.*DELETE' /tmp/b-mcp-get.h
grep -qiE '^mcp-protocol-version:' /tmp/b-mcp-get.h
grep -q 'method_not_allowed' /tmp/b-mcp-get.json

INIT_MCP="$(curl -s -o /tmp/b-mcp-init.json -D /tmp/b-mcp-init.h -w '%{http_code}' --max-time 2   -X POST "http://127.0.0.1:$PORT/mcp"   -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY"   -H 'MCP-Protocol-Version: 2025-03-26'   -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"local-mvp","version":"0"}}}' )"
echo "mcp_init_status=$INIT_MCP"
test "$INIT_MCP" = "200"
grep -qiE '^mcp-protocol-version:[[:space:]]*2025-03-26' /tmp/b-mcp-init.h
grep -qiE '^mcp-session-id:' /tmp/b-mcp-init.h
INIT_SID="$(tr -d '\r' < /tmp/b-mcp-init.h | awk 'BEGIN{IGNORECASE=1} /^mcp-session-id:/{print $2; exit}')"
echo "mcp_session_id=$INIT_SID"
echo "$INIT_SID" | grep -qE '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
grep -q '"protocolVersion"' /tmp/b-mcp-init.json
grep -q '2025-03-26' /tmp/b-mcp-init.json

SESS_ONE="$(curl -s -o /tmp/b-admin-sess-one.json -D /tmp/b-admin-sess-one.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/admin/sessions" -H "X-Admin-Token: $ADMIN" -H "Origin: http://localhost:3000")"
echo "admin_sessions_one_status=$SESS_ONE"
test "$SESS_ONE" = "200"
grep -qiE '^access-control-allow-origin:[[:space:]]*http://localhost:3000' /tmp/b-admin-sess-one.h
node --input-type=module -e '
const body = JSON.parse(process.argv[1]);
const sid = process.argv[2];
if (body.ok !== true || body.count !== 1 || !Array.isArray(body.sessions) || body.sessions.length !== 1) {
  console.error("expected count 1", body);
  process.exit(1);
}
const row = body.sessions[0];
if (row.id !== sid || typeof row.ageMs !== "number" || row.ttlRemainingMs == null || !row.lastSeen) {
  console.error("session row mismatch", row, sid);
  process.exit(1);
}
const dump = JSON.stringify(body);
if (/ten_acme_dev|admin-dev-token|authorization/i.test(dump)) {
  console.error("admin/sessions leaked secret");
  process.exit(1);
}
console.log("admin_sessions_one_ok", sid);
' "$(cat /tmp/b-admin-sess-one.json)" "$INIT_SID"

RPC_LIST="$(curl -sf --max-time 2 -X POST "http://127.0.0.1:$PORT/mcp"   -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY"   -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}')"
echo "mcp_rpc_list=$RPC_LIST"
echo "$RPC_LIST" | grep -q '"name":"echo"'
echo "$RPC_LIST" | grep -q '"jsonrpc":"2.0"'

DEL_MISS="$(curl -s -o /tmp/b-mcp-del-miss.json -w '%{http_code}' --max-time 2 -X DELETE "http://127.0.0.1:$PORT/mcp")"
echo "mcp_delete_missing_status=$DEL_MISS body=$(cat /tmp/b-mcp-del-miss.json)"
test "$DEL_MISS" = "400"
grep -q '"error":"session_id_required"' /tmp/b-mcp-del-miss.json

DEL_OK="$(curl -s -o /tmp/b-mcp-del-ok -D /tmp/b-mcp-del-ok.h -w '%{http_code}' --max-time 2 \
  -X DELETE "http://127.0.0.1:$PORT/mcp" -H "Mcp-Session-Id: $INIT_SID")"
echo "mcp_delete_status=$DEL_OK"
test "$DEL_OK" = "204"
test ! -s /tmp/b-mcp-del-ok

DEL_POST="$(curl -s -o /tmp/b-mcp-del-post.json -w '%{http_code}' --max-time 2 \
  -X POST "http://127.0.0.1:$PORT/mcp" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -H "Mcp-Session-Id: $INIT_SID" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/list","params":{}}')"
echo "mcp_post_after_delete_status=$DEL_POST body=$(cat /tmp/b-mcp-del-post.json)"
test "$DEL_POST" = "404"
grep -q '"error":"session_not_found"' /tmp/b-mcp-del-post.json

DEL_AGAIN="$(curl -s -o /tmp/b-mcp-del-again.json -w '%{http_code}' --max-time 2 \
  -X DELETE "http://127.0.0.1:$PORT/mcp" -H "Mcp-Session-Id: $INIT_SID")"
echo "mcp_delete_again_status=$DEL_AGAIN"
test "$DEL_AGAIN" = "404"
grep -q '"error":"session_not_found"' /tmp/b-mcp-del-again.json
echo "streamable_http_delete_ok"

SESS_GONE="$(curl -s -o /tmp/b-admin-sess-gone.json -w '%{http_code}' \
  "http://127.0.0.1:$PORT/admin/sessions" -H "X-Admin-Token: $ADMIN")"
echo "admin_sessions_gone_status=$SESS_GONE"
test "$SESS_GONE" = "200"
node --input-type=module -e '
const body = JSON.parse(process.argv[1]);
const sid = process.argv[2];
if (body.ok !== true || body.count !== 0) {
  console.error("expected count 0 after DELETE", body);
  process.exit(1);
}
if ((body.sessions || []).some((s) => s.id === sid)) {
  console.error("deleted id still listed", body, sid);
  process.exit(1);
}
console.log("admin_sessions_gone_ok");
' "$(cat /tmp/b-admin-sess-gone.json)" "$INIT_SID"

# Admin DELETE /admin/sessions/{id} on a fresh session (client DELETE /mcp unchanged above)
INIT_ADM="$(curl -s -o /tmp/b-mcp-init-adm.json -D /tmp/b-mcp-init-adm.h -w '%{http_code}' --max-time 2   -X POST "http://127.0.0.1:$PORT/mcp"   -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY"   -H 'MCP-Protocol-Version: 2025-03-26'   -d '{"jsonrpc":"2.0","id":10,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"local-mvp-admin","version":"0"}}}' )"
echo "mcp_init_admin_status=$INIT_ADM"
test "$INIT_ADM" = "200"
ADM_SID="$(tr -d '\r' < /tmp/b-mcp-init-adm.h | awk 'BEGIN{IGNORECASE=1} /^mcp-session-id:/{print $2; exit}')"
echo "$ADM_SID" | grep -qE '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'

ADM_DEL_UNAUTH="$(curl -s -o /tmp/b-admin-del-unauth.json -w '%{http_code}' --max-time 2 -X DELETE "http://127.0.0.1:$PORT/admin/sessions/$ADM_SID")"
echo "admin_delete_unauth_status=$ADM_DEL_UNAUTH body=$(cat /tmp/b-admin-del-unauth.json)"
test "$ADM_DEL_UNAUTH" = "401"
grep -q 'unauthorized_admin' /tmp/b-admin-del-unauth.json
if grep -qE 'ten_acme_dev|ten_restricted_dev|admin-dev-token' /tmp/b-admin-del-unauth.json; then
  echo "admin DELETE /admin/sessions/{id} 401 leaked secret"
  exit 1
fi

ADM_DEL_CORS="$(curl -s -o /tmp/b-admin-del-cors -D /tmp/b-admin-del-cors.h -w '%{http_code}' \
  -X OPTIONS "http://127.0.0.1:$PORT/admin/sessions/$ADM_SID" \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: DELETE" \
  -H "Access-Control-Request-Headers: x-admin-token,x-request-id")"
echo "admin_delete_cors_preflight_status=$ADM_DEL_CORS"
test "$ADM_DEL_CORS" = "204"
grep -qiE '^access-control-allow-origin:[[:space:]]*http://localhost:3000' /tmp/b-admin-del-cors.h
grep -qiE '^access-control-allow-methods:.*DELETE' /tmp/b-admin-del-cors.h

ADM_DEL_OK="$(curl -s -o /tmp/b-admin-del-ok -D /tmp/b-admin-del-ok.h -w '%{http_code}' --max-time 2 \
  -X DELETE "http://127.0.0.1:$PORT/admin/sessions/$ADM_SID" -H "X-Admin-Token: $ADMIN" -H "X-Request-Id: mvp-admin-del" -H "Origin: http://localhost:3000")"
echo "admin_delete_status=$ADM_DEL_OK"
test "$ADM_DEL_OK" = "204"
test ! -s /tmp/b-admin-del-ok
grep -qiE '^x-request-id:[[:space:]]*mvp-admin-del' /tmp/b-admin-del-ok.h
grep -qiE '^access-control-allow-origin:[[:space:]]*http://localhost:3000' /tmp/b-admin-del-ok.h

ADM_DEL_POST="$(curl -s -o /tmp/b-admin-del-post.json -w '%{http_code}' --max-time 2 \
  -X POST "http://127.0.0.1:$PORT/mcp" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -H "Mcp-Session-Id: $ADM_SID" \
  -d '{"jsonrpc":"2.0","id":11,"method":"tools/list","params":{}}')"
echo "mcp_post_after_admin_delete_status=$ADM_DEL_POST body=$(cat /tmp/b-admin-del-post.json)"
test "$ADM_DEL_POST" = "404"
grep -q '"error":"session_not_found"' /tmp/b-admin-del-post.json

ADM_DEL_AGAIN="$(curl -s -o /tmp/b-admin-del-again.json -w '%{http_code}' --max-time 2 \
  -X DELETE "http://127.0.0.1:$PORT/admin/sessions/$ADM_SID" -H "X-Admin-Token: $ADMIN")"
echo "admin_delete_again_status=$ADM_DEL_AGAIN"
test "$ADM_DEL_AGAIN" = "404"
grep -q '"error":"session_not_found"' /tmp/b-admin-del-again.json

ADM_DEL_MISS="$(curl -s -o /tmp/b-admin-del-miss.json -w '%{http_code}' --max-time 2 \
  -X DELETE "http://127.0.0.1:$PORT/admin/sessions" -H "X-Admin-Token: $ADMIN")"
echo "admin_delete_missing_id_status=$ADM_DEL_MISS"
test "$ADM_DEL_MISS" = "404"
echo "admin_session_delete_ok"

# restricted tenant cannot see digest / upstreamPing
RLIST="$(curl -sf -X POST "http://127.0.0.1:$PORT/tools/list" \
  -H 'content-type: application/json' -H "X-Api-Key: $REST_KEY" -d '{}')"
echo "restricted_list=$RLIST"
echo "$RLIST" | grep -q '"name":"echo"'
if echo "$RLIST" | grep -q '"name":"digest"'; then
  echo "restricted tenant should not see digest"
  exit 1
fi
if echo "$RLIST" | grep -q '"name":"upstreamPing"'; then
  echo "restricted tenant should not see upstreamPing"
  exit 1
fi

DENY="$(curl -s -o /tmp/b-deny.json -w '%{http_code}' -X POST "http://127.0.0.1:$PORT/tools/call" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -d '{"name":"deletePet","arguments":{"id":"1"}}')"
echo "deny_status=$DENY body=$(cat /tmp/b-deny.json)"
test "$DENY" = "403"
grep -q '"tenantId":"acme"' /tmp/b-deny.json

# Webhook fan-out: deny event should land on mock receiver (poll briefly; fire-and-forget)
WH_DENY_OK=0
for i in $(seq 1 40); do
  if test -f "$WH_OUT" && grep -q '"type":"deny"' "$WH_OUT" 2>/dev/null; then
    WH_DENY_OK=1
    break
  fi
  sleep 0.05
done
test "$WH_DENY_OK" = "1"
grep -q '"tool":"deletePet"' "$WH_OUT"
grep -q '"source":"mcp-gateway"' "$WH_OUT"
echo "webhook_deny_ok"

ALLOW="$(curl -sf -X POST "http://127.0.0.1:$PORT/tools/call" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -d '{"name":"echo","arguments":{"message":"hello-mvp"}}')"
echo "allow=$ALLOW"
echo "$ALLOW" | grep -q '"ok":true'
echo "$ALLOW" | grep -q 'hello-mvp'
echo "$ALLOW" | grep -q '"tenantId":"acme"'
echo "$ALLOW" | grep -q '"via":"builtin"'

# Webhook fan-out: tool_call for allowed echo
WH_ALLOW_OK=0
for i in $(seq 1 40); do
  if test -f "$WH_OUT" && grep -q '"type":"tool_call"' "$WH_OUT" 2>/dev/null \
     && grep -q '"tool":"echo"' "$WH_OUT" 2>/dev/null; then
    WH_ALLOW_OK=1
    break
  fi
  sleep 0.05
done
test "$WH_ALLOW_OK" = "1"
grep -q '"redacted":true' "$WH_OUT"
# webhooksRedact default true → arguments/result masked even if disk JSONL keeps them
grep -q '\[REDACTED\]' "$WH_OUT"
if grep -q 'hello-mvp' "$WH_OUT"; then
  echo "webhook payload leaked unredacted message"
  exit 1
fi
echo "webhook_tool_call_ok"

# X-Webhook-Timestamp on unsigned fan-out (HMAC still body-only; replay window = paid)
test -f "$WH_HDR"
node --input-type=module -e '
import fs from "node:fs";
const meta = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));

const raw = meta.timestamp ?? (meta.headers && (meta.headers["x-webhook-timestamp"] || meta.headers["X-Webhook-Timestamp"]));
const ts = Number(String(raw || "").trim());
if (!Number.isFinite(ts) || ts <= 0) {
  console.error("missing X-Webhook-Timestamp", meta);
  process.exit(1);
}
const now = Math.floor(Date.now() / 1000);
if (Math.abs(now - ts) > 120) {
  console.error("timestamp not now", { ts, now });
  process.exit(1);
}

console.log("webhook_timestamp_ok", ts);
' "$WH_HDR"
echo "webhook_timestamp_ok"

# X-Request-Id: custom id echoed on response + audit JSONL + webhook payload
RID="mvp-req-id-a1b2c3d4"
RID_STATUS="$(curl -s -o /tmp/b-rid.json -D /tmp/b-rid.h -w '%{http_code}' \
  -X POST "http://127.0.0.1:$PORT/tools/call" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -H "X-Request-Id: $RID" \
  -d '{"name":"echo","arguments":{"message":"rid-proof"}}')"
echo "request_id_call_status=$RID_STATUS"
test "$RID_STATUS" = "200"
grep -q '"ok":true' /tmp/b-rid.json
grep -qiE "^x-request-id:[[:space:]]*${RID}" /tmp/b-rid.h
grep -q "$RID" "$AUDIT"
grep -q '"requestId"' "$AUDIT"
node --input-type=module -e '
import fs from "node:fs";
const rid = process.argv[1];
const lines = fs.readFileSync(process.argv[2], "utf8").split("\n").filter(Boolean);
const hit = lines.map((l) => JSON.parse(l)).find((e) => e.requestId === rid);
if (!hit) { console.error("audit JSONL missing requestId", rid); process.exit(1); }
if (hit.tool !== "echo") { console.error("rid audit line tool", hit.tool); process.exit(1); }
console.log("audit_jsonl_requestId_ok", hit.tool);
' "$RID" "$AUDIT"
WH_RID_OK=0
for i in $(seq 1 40); do
  if test -f "$WH_OUT" && grep -q "$RID" "$WH_OUT" 2>/dev/null; then
    WH_RID_OK=1
    break
  fi
  sleep 0.05
done
test "$WH_RID_OK" = "1"
grep -q '"requestId"' "$WH_OUT"
echo "request_id_custom_ok"

# Request body size limit (maxBodyBytes): Content-Length early reject + chunked stream count
BODY_CL="$(node --input-type=module -e '
import http from "node:http";
const port = Number(process.argv[1]);
const key = process.argv[2];
const body = JSON.stringify({ name: "echo", arguments: { message: "x".repeat(2000) } });
const req = http.request(
  {
    host: "127.0.0.1",
    port,
    method: "POST",
    path: "/tools/call",
    headers: {
      "content-type": "application/json",
      authorization: "Bearer " + key,
      "content-length": String(Buffer.byteLength(body)),
      connection: "close",
    },
  },
  (res) => {
    let b = "";
    res.on("data", (c) => (b += c));
    res.on("end", () => {
      process.stdout.write(String(res.statusCode) + " " + b);
      process.exit(res.statusCode === 413 ? 0 : 1);
    });
  }
);
req.on("error", (e) => { console.error(e); process.exit(2); });
req.end(body);
' "$PORT" "$ACME_KEY")" || true
echo "body_content_length_over=$BODY_CL"
echo "$BODY_CL" | grep -q '^413 '
echo "$BODY_CL" | grep -q '"error":"payload_too_large"'

BODY_CHUNK="$(node --input-type=module -e '
import http from "node:http";
const port = Number(process.argv[1]);
const key = process.argv[2];
const req = http.request(
  {
    host: "127.0.0.1",
    port,
    method: "POST",
    path: "/tools/call",
    headers: {
      "content-type": "application/json",
      authorization: "Bearer " + key,
      connection: "close",
    },
  },
  (res) => {
    let b = "";
    res.on("data", (c) => (b += c));
    res.on("end", () => {
      process.stdout.write(String(res.statusCode) + " " + b);
      process.exit(res.statusCode === 413 ? 0 : 1);
    });
  }
);
req.on("error", (e) => { console.error(e); process.exit(2); });
// No Content-Length: Node sends Transfer-Encoding: chunked. Body > maxBodyBytes (1024).
const pad = "x".repeat(1500);
req.end(JSON.stringify({ name: "echo", arguments: { message: pad } }));
' "$PORT" "$ACME_KEY")" || true
echo "body_chunked_over=$BODY_CHUNK"
echo "$BODY_CHUNK" | grep -q '^413 '
echo "$BODY_CHUNK" | grep -q '"error":"payload_too_large"'

# Normal-sized call still works after 413s
BODY_OK="$(curl -sf -X POST "http://127.0.0.1:$PORT/tools/call" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -d '{"name":"echo","arguments":{"message":"body-ok"}}')"
echo "body_ok=$BODY_OK"
echo "$BODY_OK" | grep -q '"ok":true'
echo "$BODY_OK" | grep -q 'body-ok'
echo "body_limit_ok"

# Per-tenant IP allowlist: acme allows loopback (127.0.0.1 / ::1 / 10.0.0.0/8)
# stack-demo also binds loopback — keep 127.0.0.1 in allowlist when set.
IP_OK="$(curl -sf -X POST "http://127.0.0.1:$PORT/tools/list"   -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" -d '{}')"
echo "ip_allow_loopback=$IP_OK"
echo "$IP_OK" | grep -q '"tenantId":"acme"'

# Spoofed X-Forwarded-For outside acme allowlist → 403 ip_denied
IP_XFF_DENY="$(curl -s -o /tmp/b-ip-xff.json -w '%{http_code}' -X POST "http://127.0.0.1:$PORT/tools/list"   -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY"   -H 'X-Forwarded-For: 9.9.9.9' -d '{}')"
echo "ip_xff_deny_status=$IP_XFF_DENY body=$(cat /tmp/b-ip-xff.json)"
test "$IP_XFF_DENY" = "403"
grep -q '"error":"forbidden"' /tmp/b-ip-xff.json
grep -q '"reason":"ip_denied"' /tmp/b-ip-xff.json

# Explicit tenant allowlist 1.2.3.4 + XFF 9.9.9.9 → 403
IP_LOCK_DENY="$(curl -s -o /tmp/b-ip-lock.json -w '%{http_code}' -X POST "http://127.0.0.1:$PORT/tools/list"   -H 'content-type: application/json' -H "X-Api-Key: $IPLOCK_KEY"   -H 'X-Forwarded-For: 9.9.9.9' -d '{}')"
echo "ip_lock_deny_status=$IP_LOCK_DENY body=$(cat /tmp/b-ip-lock.json)"
test "$IP_LOCK_DENY" = "403"
grep -q '"reason":"ip_denied"' /tmp/b-ip-lock.json

# Same locked tenant with XFF 1.2.3.4 succeeds
IP_LOCK_OK="$(curl -sf -X POST "http://127.0.0.1:$PORT/tools/list"   -H 'content-type: application/json' -H "X-Api-Key: $IPLOCK_KEY"   -H 'X-Forwarded-For: 1.2.3.4' -d '{}')"
echo "ip_lock_ok=$IP_LOCK_OK"
echo "$IP_LOCK_OK" | grep -q '"tenantId":"ip-locked"'
echo "ip_allowlist_ok"

# Prometheus metrics after a tool call
curl -sf "http://127.0.0.1:$PORT/metrics" -o "$ROOT/data/metrics.txt"
test -s "$ROOT/data/metrics.txt"
grep -q 'tool_calls_total' "$ROOT/data/metrics.txt"
grep -q 'rate_limited_total' "$ROOT/data/metrics.txt"
grep -q 'ip_denied_total' "$ROOT/data/metrics.txt"
grep -q 'body_too_large_total' "$ROOT/data/metrics.txt"
grep -q 'upstream_timeout_total' "$ROOT/data/metrics.txt"
grep -q 'circuit_open_total' "$ROOT/data/metrics.txt"
grep -q 'webhook_retries_total' "$ROOT/data/metrics.txt"
grep -q 'http_requests_total' "$ROOT/data/metrics.txt"
# at least one IP deny was recorded above
node --input-type=module -e '
import fs from "node:fs";
const t = fs.readFileSync(process.argv[1], "utf8");
const m = t.match(/^ip_denied_total (\d+)$/m);
if (!m || Number(m[1]) < 1) { console.error("ip_denied_total expected >=1", m); process.exit(1); }
console.log("ip_denied_total=" + m[1]);
const b = t.match(/^body_too_large_total (\d+)$/m);
if (!b || Number(b[1]) < 1) { console.error("body_too_large_total expected >=1", b); process.exit(1); }
console.log("body_too_large_total=" + b[1]);
' "$ROOT/data/metrics.txt"
# label order is decision,tenant,tool (sorted) — assert echo/allow sample exists
grep -E 'tool_calls_total\{[^}]*tool="echo"[^}]*decision="allow"|tool_calls_total\{[^}]*decision="allow"[^}]*tool="echo"' "$ROOT/data/metrics.txt" >/dev/null   || { echo "tool_calls_total missing echo/allow"; cat "$ROOT/data/metrics.txt"; exit 1; }
echo "metrics_ok"

# Proxied upstream call must return mock-upstream payload
PROXY="$(curl -sf -X POST "http://127.0.0.1:$PORT/tools/call" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -d '{"name":"upstreamPing","arguments":{"note":"via-gateway"}}')"
echo "proxy=$PROXY"
echo "$PROXY" | grep -q '"ok":true'
echo "$PROXY" | grep -q '"via":"upstream"'
echo "$PROXY" | grep -q '"source":"mock-upstream"'
echo "$PROXY" | grep -q 'via-gateway'

# restricted denied for digest
RDENY="$(curl -s -o /tmp/b-rdeny.json -w '%{http_code}' -X POST "http://127.0.0.1:$PORT/tools/call" \
  -H 'content-type: application/json' -H "X-Api-Key: $REST_KEY" \
  -d '{"name":"digest","arguments":{"text":"x"}}')"
echo "restricted_deny_status=$RDENY body=$(cat /tmp/b-rdeny.json)"
test "$RDENY" = "403"

test -f "$AUDIT"
grep -q '"tool":"deletePet"' "$AUDIT"
grep -q '"tool":"echo"' "$AUDIT"
grep -q '"tool":"upstreamPing"' "$AUDIT"
grep -q '"via":"upstream"' "$AUDIT"
grep -q '"tenantId":"acme"' "$AUDIT"
grep -q '"allow":false' "$AUDIT"
grep -q '"allow":true' "$AUDIT"

# audit query API
AUDIT_JSON="$(curl -sf "http://127.0.0.1:$PORT/audit?tenant=acme&limit=10" \
  -H "Authorization: Bearer $ACME_KEY")"
echo "audit_query=$AUDIT_JSON"
echo "$AUDIT_JSON" | grep -q '"ok":true'
echo "$AUDIT_JSON" | grep -q '"tenantId":"acme"'
echo "$AUDIT_JSON" | grep -q '"requestId"'
echo "$AUDIT_JSON" | grep -q "$RID"

AUDIT_TOOL="$(curl -sf "http://127.0.0.1:$PORT/audit?tool=echo&limit=5" \
  -H "X-Admin-Token: $ADMIN")"
echo "audit_tool=$AUDIT_TOOL"
echo "$AUDIT_TOOL" | grep -q '"tool":"echo"'

# audit export endpoint (paid wedge pack) — tenant key
EXPORT_JSON_HTTP="$(curl -sf "http://127.0.0.1:$PORT/audit/export?tenant=acme&format=json" \
  -H "Authorization: Bearer $ACME_KEY" -o "$ROOT/data/export.http.json" -w '%{http_code}')"
echo "export_http_json_status=$EXPORT_JSON_HTTP"
test "$EXPORT_JSON_HTTP" = "200"
test -s "$ROOT/data/export.http.json"
grep -q '"ok":true' "$ROOT/data/export.http.json"
grep -q '"tenantId":"acme"' "$ROOT/data/export.http.json"
grep -q '"format":"json"' "$ROOT/data/export.http.json"
grep -q '"requestId"' "$ROOT/data/export.http.json"
grep -q "$RID" "$ROOT/data/export.http.json"

EXPORT_CSV_HTTP="$(curl -sf "http://127.0.0.1:$PORT/audit/export?format=csv" \
  -H "X-Admin-Token: $ADMIN" -o "$ROOT/data/export.http.csv" -w '%{http_code}')"
echo "export_http_csv_status=$EXPORT_CSV_HTTP"
test "$EXPORT_CSV_HTTP" = "200"
test -s "$ROOT/data/export.http.csv"
grep -q 'ts,tenantId,tool,allow,reason,via,arguments,result,argumentKeysHash' "$ROOT/data/export.http.csv"
grep -q 'requestId' "$ROOT/data/export.http.csv"
grep -q "$RID" "$ROOT/data/export.http.csv"
grep -q 'acme' "$ROOT/data/export.http.csv"

# CLI offline export (no server required) — non-empty out file
mkdir -p "$ROOT/out"
CLI_EXPORT="$(node src/cli.js export-audit --config "$POLICY" --audit "$AUDIT" \
  --out "$ROOT/out/audit.json" --format json --tenant acme)"
echo "cli_export=$CLI_EXPORT"
echo "$CLI_EXPORT" | grep -q '"ok":true'
test -s "$ROOT/out/audit.json"
# pretty-printed JSON has spaces after ':' — validate with node
node --input-type=module -e '
import fs from "node:fs";
const p = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
if (!p.ok || !p.count || p.count < 1 || !Array.isArray(p.events) || p.events.length < 1) {
  console.error("CLI export empty or invalid", { ok: p.ok, count: p.count, n: p.events?.length });
  process.exit(1);
}
if (!p.events.some((e) => e.tenantId === "acme")) {
  console.error("CLI export missing acme tenant events");
  process.exit(1);
}
if (!p.events.some((e) => e.requestId === process.argv[2])) {
  console.error("CLI export missing requestId", process.argv[2]);
  process.exit(1);
}
console.log("cli_export_file_ok count=" + p.count);
' "$ROOT/out/audit.json" "$RID"

CLI_CSV="$(node src/cli.js export-audit --config "$POLICY" --audit "$AUDIT" \
  --out "$ROOT/out/audit.csv" --format csv)"
echo "cli_csv=$CLI_CSV"
test -s "$ROOT/out/audit.csv"
grep -q 'ts,tenantId,tool' "$ROOT/out/audit.csv"

# gzip audit export (HTTP gzip=1 + Accept-Encoding; CLI --gzip). Uncompressed proofs above stay intact.
EXPORT_GZIP_HTTP="$(curl -s -o "$ROOT/data/export.http.json.gz" -D /tmp/b-export-gz.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/audit/export?tenant=acme&format=json&gzip=1" \
  -H "Authorization: Bearer $ACME_KEY")"
echo "export_gzip_http_json_status=$EXPORT_GZIP_HTTP"
test "$EXPORT_GZIP_HTTP" = "200"
test -s "$ROOT/data/export.http.json.gz"
grep -qiE '^content-encoding:[[:space:]]*gzip' /tmp/b-export-gz.h
grep -qiE 'content-disposition:.*\.json\.gz' /tmp/b-export-gz.h
gzip -t "$ROOT/data/export.http.json.gz"
node --input-type=module -e '
import fs from "node:fs";
import zlib from "node:zlib";
const buf = fs.readFileSync(process.argv[1]);
const p = JSON.parse(zlib.gunzipSync(buf).toString("utf8"));
if (!p.ok || p.format !== "json" || !Array.isArray(p.events) || p.events.length < 1) {
  console.error("gzip HTTP JSON export invalid", { ok: p.ok, format: p.format, n: p.events?.length });
  process.exit(1);
}
if (!p.events.some((e) => e.tenantId === "acme")) {
  console.error("gzip HTTP JSON missing acme");
  process.exit(1);
}
if (!p.events.some((e) => e.requestId === process.argv[2])) {
  console.error("gzip HTTP JSON missing requestId", process.argv[2]);
  process.exit(1);
}
console.log("export_gzip_http_json_ok count=" + p.count);
' "$ROOT/data/export.http.json.gz" "$RID"

# Accept-Encoding: gzip for CSV (no --compressed so curl keeps gzip bytes)
EXPORT_GZIP_CSV="$(curl -s -o "$ROOT/data/export.http.csv.gz" -D /tmp/b-export-csv-gz.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/audit/export?format=csv" \
  -H "X-Admin-Token: $ADMIN" \
  -H "Accept-Encoding: gzip")"
echo "export_gzip_http_csv_status=$EXPORT_GZIP_CSV"
test "$EXPORT_GZIP_CSV" = "200"
test -s "$ROOT/data/export.http.csv.gz"
grep -qiE '^content-encoding:[[:space:]]*gzip' /tmp/b-export-csv-gz.h
grep -qiE 'content-disposition:.*\.csv\.gz' /tmp/b-export-csv-gz.h
gzip -t "$ROOT/data/export.http.csv.gz"
node --input-type=module -e '
import fs from "node:fs";
import zlib from "node:zlib";
const csv = zlib.gunzipSync(fs.readFileSync(process.argv[1])).toString("utf8");
if (!csv.includes("ts,tenantId,tool,allow,reason,via,arguments,result,argumentKeysHash")) {
  console.error("gzip CSV missing header", csv.slice(0, 200));
  process.exit(1);
}
if (!csv.includes("requestId") || !csv.includes(process.argv[2]) || !csv.includes("acme")) {
  console.error("gzip CSV missing requestId/acme");
  process.exit(1);
}
console.log("export_gzip_http_csv_ok");
' "$ROOT/data/export.http.csv.gz" "$RID"

# gzip=0 wins over Accept-Encoding: gzip — uncompressed JSON (existing proofs stay valid)
EXPORT_NOGZIP="$(curl -s -o "$ROOT/data/export.nogzip.json" -D /tmp/b-export-nogzip.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/audit/export?tenant=acme&format=json&gzip=0" \
  -H "Authorization: Bearer $ACME_KEY" \
  -H "Accept-Encoding: gzip")"
echo "export_nogzip_status=$EXPORT_NOGZIP"
test "$EXPORT_NOGZIP" = "200"
if grep -qiE '^content-encoding:[[:space:]]*gzip' /tmp/b-export-nogzip.h; then
  echo "gzip=0 must not set Content-Encoding: gzip"
  cat /tmp/b-export-nogzip.h
  exit 1
fi
grep -q '"ok":true' "$ROOT/data/export.nogzip.json"
grep -q '"format":"json"' "$ROOT/data/export.nogzip.json"
grep -q "$RID" "$ROOT/data/export.nogzip.json"

CLI_GZIP="$(node src/cli.js export-audit --config "$POLICY" --audit "$AUDIT" \
  --out "$ROOT/out/audit.json.gz" --format json --tenant acme --gzip)"
echo "cli_gzip=$CLI_GZIP"
echo "$CLI_GZIP" | grep -q '"ok":true'
echo "$CLI_GZIP" | grep -q '"gzip":true'
test -s "$ROOT/out/audit.json.gz"
gzip -t "$ROOT/out/audit.json.gz"
node --input-type=module -e '
import fs from "node:fs";
import zlib from "node:zlib";
const p = JSON.parse(zlib.gunzipSync(fs.readFileSync(process.argv[1])).toString("utf8"));
if (!p.ok || !p.count || p.count < 1 || !Array.isArray(p.events) || p.events.length < 1) {
  console.error("CLI gzip export empty or invalid", { ok: p.ok, count: p.count, n: p.events?.length });
  process.exit(1);
}
if (!p.events.some((e) => e.tenantId === "acme")) {
  console.error("CLI gzip export missing acme tenant events");
  process.exit(1);
}
if (!p.events.some((e) => e.requestId === process.argv[2])) {
  console.error("CLI gzip export missing requestId", process.argv[2]);
  process.exit(1);
}
console.log("cli_gzip_file_ok count=" + p.count);
' "$ROOT/out/audit.json.gz" "$RID"
echo "audit_export_gzip_ok"

# PII-safe export: echo a secret-like arg, redact must strip it; unredacted may keep it
SECRET='sk_live_mvp_secret_9f3a2c'
SECRET_ECHO="$(curl -sf -X POST "http://127.0.0.1:$PORT/tools/call" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -d "{\"name\":\"echo\",\"arguments\":{\"message\":\"$SECRET\",\"token\":\"$SECRET\"}}")"
echo "secret_echo=$SECRET_ECHO"
echo "$SECRET_ECHO" | grep -q '"ok":true'
grep -q "$SECRET" "$AUDIT"

EXPORT_REDACT_HTTP="$(curl -sf "http://127.0.0.1:$PORT/audit/export?tenant=acme&format=json&redact=1" \
  -H "Authorization: Bearer $ACME_KEY" -o "$ROOT/data/export.redact.json" -w '%{http_code}')"
echo "export_redact_http_status=$EXPORT_REDACT_HTTP"
test "$EXPORT_REDACT_HTTP" = "200"
grep -q '"redacted":true' "$ROOT/data/export.redact.json"
grep -q '\[REDACTED\]' "$ROOT/data/export.redact.json"
if grep -q "$SECRET" "$ROOT/data/export.redact.json"; then
  echo "redacted HTTP export still contains secret"
  exit 1
fi
grep -q 'argumentKeysHash' "$ROOT/data/export.redact.json"

EXPORT_PLAIN_HTTP="$(curl -sf "http://127.0.0.1:$PORT/audit/export?tenant=acme&format=json&redact=0" \
  -H "Authorization: Bearer $ACME_KEY" -o "$ROOT/data/export.plain.json" -w '%{http_code}')"
echo "export_plain_http_status=$EXPORT_PLAIN_HTTP"
test "$EXPORT_PLAIN_HTTP" = "200"
grep -q '"redacted":false' "$ROOT/data/export.plain.json"
grep -q "$SECRET" "$ROOT/data/export.plain.json"

# since= filter (far-future => empty pack)
FUTURE="2099-01-01T00:00:00.000Z"
EXPORT_SINCE="$(curl -sf "http://127.0.0.1:$PORT/audit/export?format=json&since=$FUTURE&redact=1" \
  -H "X-Admin-Token: $ADMIN" -o "$ROOT/data/export.since.json" -w '%{http_code}')"
echo "export_since_status=$EXPORT_SINCE"
test "$EXPORT_SINCE" = "200"
node --input-type=module -e '
import fs from "node:fs";
const p = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
if (!p.ok || p.count !== 0 || (p.events && p.events.length !== 0)) {
  console.error("since=future should yield empty export", p);
  process.exit(1);
}
console.log("export_since_empty_ok");
' "$ROOT/data/export.since.json"

# Admin SIEM CSV: GET /admin/audit.csv (admin-only; no args/tokens). Gzip JSON stays on /audit/export.
ADMIN_CSV_UNAUTH="$(curl -s -o /tmp/b-admin-audit-unauth.json -w '%{http_code}' \
  "http://127.0.0.1:$PORT/admin/audit.csv")"
echo "admin_audit_csv_unauth_status=$ADMIN_CSV_UNAUTH body=$(cat /tmp/b-admin-audit-unauth.json)"
test "$ADMIN_CSV_UNAUTH" = "401"
grep -q 'unauthorized_admin' /tmp/b-admin-audit-unauth.json

ADMIN_CSV_TENANT="$(curl -s -o /tmp/b-admin-audit-tenant.json -w '%{http_code}' \
  "http://127.0.0.1:$PORT/admin/audit.csv" -H "Authorization: Bearer $ACME_KEY")"
echo "admin_audit_csv_tenant_status=$ADMIN_CSV_TENANT body=$(cat /tmp/b-admin-audit-tenant.json)"
test "$ADMIN_CSV_TENANT" = "401"

ADMIN_CSV_HTTP="$(curl -s -o "$ROOT/data/admin.audit.csv" -D /tmp/b-admin-audit.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/admin/audit.csv" -H "X-Admin-Token: $ADMIN" -H "X-Request-Id: mvp-admin-csv-1")"
echo "admin_audit_csv_status=$ADMIN_CSV_HTTP"
test "$ADMIN_CSV_HTTP" = "200"
grep -qiE '^content-type:[[:space:]]*text/csv' /tmp/b-admin-audit.h
grep -qiE '^x-request-id:[[:space:]]*mvp-admin-csv-1' /tmp/b-admin-audit.h
ADMIN_CSV_HEAD="$(head -n 1 "$ROOT/data/admin.audit.csv" | tr -d '\r')"
test "$ADMIN_CSV_HEAD" = "ts,tenantId,tool,allow,reason,via,requestId"
grep -q "$RID" "$ROOT/data/admin.audit.csv"
grep -q 'acme' "$ROOT/data/admin.audit.csv"
grep -q 'true' "$ROOT/data/admin.audit.csv"
grep -q 'false' "$ROOT/data/admin.audit.csv"
if grep -q "$SECRET" "$ROOT/data/admin.audit.csv"; then
  echo "admin audit csv leaked secret"
  exit 1
fi
if grep -qE 'arguments|sk_live' "$ROOT/data/admin.audit.csv"; then
  echo "admin audit csv leaked arguments column or secret prefix"
  exit 1
fi

ADMIN_CSV_FMT="$(curl -sf "http://127.0.0.1:$PORT/admin/audit?format=csv" \
  -H "X-Admin-Token: $ADMIN")"
echo "$ADMIN_CSV_FMT" | grep -q 'ts,tenantId,tool,allow,reason,via,requestId'
if echo "$ADMIN_CSV_FMT" | grep -q "$SECRET"; then
  echo "admin audit ?format=csv leaked secret"
  exit 1
fi

ADMIN_CSV_JSON="$(curl -sf "http://127.0.0.1:$PORT/admin/audit?format=json" \
  -H "X-Admin-Token: $ADMIN")"
echo "$ADMIN_CSV_JSON" | grep -q '"format":"json"'
echo "$ADMIN_CSV_JSON" | grep -q '"ok":true'

ADMIN_CSV_BAD="$(curl -s -o /tmp/b-admin-audit-bad.json -w '%{http_code}' \
  "http://127.0.0.1:$PORT/admin/audit?format=nope" -H "X-Admin-Token: $ADMIN")"
test "$ADMIN_CSV_BAD" = "400"
grep -q 'unsupported_format' /tmp/b-admin-audit-bad.json

ADMIN_CSV_EMPTY="$(curl -sf "http://127.0.0.1:$PORT/admin/audit.csv?since=$FUTURE" \
  -H "X-Admin-Token: $ADMIN")"
ADMIN_CSV_EMPTY_TRIM="$(printf '%s' "$ADMIN_CSV_EMPTY" | tr -d '\r' | sed -e 's/[[:space:]]*$//')"
test "$ADMIN_CSV_EMPTY_TRIM" = "ts,tenantId,tool,allow,reason,via,requestId"

ADMIN_CSV_CORS="$(curl -s -o /tmp/b-admin-csv-cors.csv -D /tmp/b-admin-csv-cors.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/admin/audit.csv" \
  -H "X-Admin-Token: $ADMIN" -H "Origin: http://localhost:3000")"
echo "admin_audit_csv_cors_status=$ADMIN_CSV_CORS"
test "$ADMIN_CSV_CORS" = "200"
grep -qiE '^access-control-allow-origin:[[:space:]]*http://localhost:3000' /tmp/b-admin-csv-cors.h
echo "admin_audit_csv_ok"

# Admin SIEM Markdown: GET /admin/audit.md (admin-only; same columns as CSV; no args/tokens).
ADMIN_MD_UNAUTH="$(curl -s -o /tmp/b-admin-audit-md-unauth.json -w '%{http_code}' \
  "http://127.0.0.1:$PORT/admin/audit.md")"
echo "admin_audit_md_unauth_status=$ADMIN_MD_UNAUTH body=$(cat /tmp/b-admin-audit-md-unauth.json)"
test "$ADMIN_MD_UNAUTH" = "401"
grep -q 'unauthorized_admin' /tmp/b-admin-audit-md-unauth.json

ADMIN_MD_TENANT="$(curl -s -o /tmp/b-admin-audit-md-tenant.json -w '%{http_code}' \
  "http://127.0.0.1:$PORT/admin/audit.md" -H "Authorization: Bearer $ACME_KEY")"
echo "admin_audit_md_tenant_status=$ADMIN_MD_TENANT body=$(cat /tmp/b-admin-audit-md-tenant.json)"
test "$ADMIN_MD_TENANT" = "401"

ADMIN_MD_HTTP="$(curl -s -o "$ROOT/data/admin.audit.md" -D /tmp/b-admin-audit-md.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/admin/audit.md" -H "X-Admin-Token: $ADMIN" -H "X-Request-Id: mvp-admin-md-1")"
echo "admin_audit_md_status=$ADMIN_MD_HTTP"
test "$ADMIN_MD_HTTP" = "200"
grep -qiE '^content-type:[[:space:]]*text/markdown' /tmp/b-admin-audit-md.h
grep -qiE '^x-request-id:[[:space:]]*mvp-admin-md-1' /tmp/b-admin-audit-md.h
ADMIN_MD_HEAD="$(head -n 1 "$ROOT/data/admin.audit.md" | tr -d '\r')"
test "$ADMIN_MD_HEAD" = "# Audit"
grep -q '| ts | tenantId | tool | allow | reason | via | requestId |' "$ROOT/data/admin.audit.md"
grep -q "$RID" "$ROOT/data/admin.audit.md"
grep -q 'acme' "$ROOT/data/admin.audit.md"
grep -q 'true' "$ROOT/data/admin.audit.md"
grep -q 'false' "$ROOT/data/admin.audit.md"
if grep -q "$SECRET" "$ROOT/data/admin.audit.md"; then
  echo "admin audit md leaked secret"
  exit 1
fi
if grep -q "$ADMIN" "$ROOT/data/admin.audit.md"; then
  echo "admin audit md leaked admin token"
  exit 1
fi
if grep -qE 'arguments|sk_live' "$ROOT/data/admin.audit.md"; then
  echo "admin audit md leaked arguments column or secret prefix"
  exit 1
fi

ADMIN_MD_FMT="$(curl -sf "http://127.0.0.1:$PORT/admin/audit?format=md" \
  -H "X-Admin-Token: $ADMIN")"
echo "$ADMIN_MD_FMT" | grep -q '# Audit'
echo "$ADMIN_MD_FMT" | grep -q '| ts | tenantId | tool | allow | reason | via | requestId |'
if echo "$ADMIN_MD_FMT" | grep -q "$SECRET"; then
  echo "admin audit ?format=md leaked secret"
  exit 1
fi
if echo "$ADMIN_MD_FMT" | grep -q "$ADMIN"; then
  echo "admin audit ?format=md leaked admin token"
  exit 1
fi

ADMIN_MD_EMPTY="$(curl -sf "http://127.0.0.1:$PORT/admin/audit.md?since=$FUTURE" \
  -H "X-Admin-Token: $ADMIN")"
echo "$ADMIN_MD_EMPTY" | grep -q '# Audit'
echo "$ADMIN_MD_EMPTY" | grep -q '| ts | tenantId | tool | allow | reason | via | requestId |'
ADMIN_MD_EMPTY_ROWS="$(printf '%s\n' "$ADMIN_MD_EMPTY" | grep -cE '^\| 20' || true)"
test "$ADMIN_MD_EMPTY_ROWS" = "0"

ADMIN_MD_CORS="$(curl -s -o /tmp/b-admin-md-cors.md -D /tmp/b-admin-md-cors.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/admin/audit.md" \
  -H "X-Admin-Token: $ADMIN" -H "Origin: http://localhost:3000")"
echo "admin_audit_md_cors_status=$ADMIN_MD_CORS"
test "$ADMIN_MD_CORS" = "200"
grep -qiE '^access-control-allow-origin:[[:space:]]*http://localhost:3000' /tmp/b-admin-md-cors.h
echo "admin_audit_md_ok"

# Admin SIEM HTML: GET /admin/audit.html (admin-only; same columns as CSV; no args/tokens).
ADMIN_HTML_UNAUTH="$(curl -s -o /tmp/b-admin-audit-html-unauth.json -w '%{http_code}' \
  "http://127.0.0.1:$PORT/admin/audit.html")"
echo "admin_audit_html_unauth_status=$ADMIN_HTML_UNAUTH body=$(cat /tmp/b-admin-audit-html-unauth.json)"
test "$ADMIN_HTML_UNAUTH" = "401"
grep -q 'unauthorized_admin' /tmp/b-admin-audit-html-unauth.json

ADMIN_HTML_TENANT="$(curl -s -o /tmp/b-admin-audit-html-tenant.json -w '%{http_code}' \
  "http://127.0.0.1:$PORT/admin/audit.html" -H "Authorization: Bearer $ACME_KEY")"
echo "admin_audit_html_tenant_status=$ADMIN_HTML_TENANT body=$(cat /tmp/b-admin-audit-html-tenant.json)"
test "$ADMIN_HTML_TENANT" = "401"

ADMIN_HTML_HTTP="$(curl -s -o "$ROOT/data/admin.audit.html" -D /tmp/b-admin-audit-html.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/admin/audit.html" -H "X-Admin-Token: $ADMIN" -H "X-Request-Id: mvp-admin-html-1")"
echo "admin_audit_html_status=$ADMIN_HTML_HTTP"
test "$ADMIN_HTML_HTTP" = "200"
grep -qiE '^content-type:[[:space:]]*text/html' /tmp/b-admin-audit-html.h
grep -qiE '^x-request-id:[[:space:]]*mvp-admin-html-1' /tmp/b-admin-audit-html.h
grep -q '<table' "$ROOT/data/admin.audit.html"
grep -q '<h1>Audit</h1>' "$ROOT/data/admin.audit.html"
grep -q "$RID" "$ROOT/data/admin.audit.html"
grep -q 'acme' "$ROOT/data/admin.audit.html"
grep -q 'true' "$ROOT/data/admin.audit.html"
grep -q 'false' "$ROOT/data/admin.audit.html"
if grep -q "$SECRET" "$ROOT/data/admin.audit.html"; then
  echo "admin audit html leaked secret"
  exit 1
fi
if grep -q "$ADMIN" "$ROOT/data/admin.audit.html"; then
  echo "admin audit html leaked admin token"
  exit 1
fi
if grep -qE 'arguments|sk_live' "$ROOT/data/admin.audit.html"; then
  echo "admin audit html leaked arguments column or secret prefix"
  exit 1
fi
if grep -q 'Authorization:' "$ROOT/data/admin.audit.html"; then
  echo "admin audit html leaked Authorization"
  exit 1
fi

ADMIN_HTML_FMT="$(curl -sf "http://127.0.0.1:$PORT/admin/audit?format=html" \
  -H "X-Admin-Token: $ADMIN")"
echo "$ADMIN_HTML_FMT" | grep -q '<table'
echo "$ADMIN_HTML_FMT" | grep -q '<h1>Audit</h1>'
if echo "$ADMIN_HTML_FMT" | grep -q "$SECRET"; then
  echo "admin audit ?format=html leaked secret"
  exit 1
fi
if echo "$ADMIN_HTML_FMT" | grep -q "$ADMIN"; then
  echo "admin audit ?format=html leaked admin token"
  exit 1
fi

ADMIN_HTML_EMPTY="$(curl -sf "http://127.0.0.1:$PORT/admin/audit.html?since=$FUTURE" \
  -H "X-Admin-Token: $ADMIN")"
echo "$ADMIN_HTML_EMPTY" | grep -q '<h1>Audit</h1>'
echo "$ADMIN_HTML_EMPTY" | grep -q '<table'
echo "$ADMIN_HTML_EMPTY" | grep -q 'no events'

ADMIN_HTML_CORS="$(curl -s -o /tmp/b-admin-html-cors.html -D /tmp/b-admin-html-cors.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/admin/audit.html" \
  -H "X-Admin-Token: $ADMIN" -H "Origin: http://localhost:3000")"
echo "admin_audit_html_cors_status=$ADMIN_HTML_CORS"
test "$ADMIN_HTML_CORS" = "200"
grep -qiE '^access-control-allow-origin:[[:space:]]*http://localhost:3000' /tmp/b-admin-html-cors.h
echo "admin_audit_html_ok"

CLI_HTML="$(node src/cli.js export-audit --config "$POLICY" --audit "$AUDIT" --format html)"
echo "$CLI_HTML" | grep -q '<table'
echo "$CLI_HTML" | grep -q '<h1>Audit</h1>'
if echo "$CLI_HTML" | grep -q "$SECRET"; then
  echo "CLI --format html leaked secret"
  exit 1
fi
if echo "$CLI_HTML" | grep -q "$ADMIN"; then
  echo "CLI --format html leaked admin token"
  exit 1
fi

CLI_MD="$(node src/cli.js export-audit --config "$POLICY" --audit "$AUDIT" \
  --out "$ROOT/out/audit.md" --format md)"
echo "cli_md=$CLI_MD"
echo "$CLI_MD" | grep -q '"format":"md"'
test -s "$ROOT/out/audit.md"
grep -q '# Audit' "$ROOT/out/audit.md"
grep -q '| ts | tenantId | tool | allow | reason | via | requestId |' "$ROOT/out/audit.md"
if grep -q "$SECRET" "$ROOT/out/audit.md"; then
  echo "CLI --format md leaked secret"
  exit 1
fi

CLI_REDACT="$(node src/cli.js export-audit --config "$POLICY" --audit "$AUDIT" \
  --out "$ROOT/out/audit.redact.json" --format json --tenant acme --redact)"
echo "cli_redact=$CLI_REDACT"
echo "$CLI_REDACT" | grep -q '"redacted":true'
test -s "$ROOT/out/audit.redact.json"
if grep -q "$SECRET" "$ROOT/out/audit.redact.json"; then
  echo "CLI --redact export still contains secret"
  exit 1
fi
grep -q '\[REDACTED\]' "$ROOT/out/audit.redact.json"

CLI_PLAIN="$(node src/cli.js export-audit --config "$POLICY" --audit "$AUDIT" \
  --out "$ROOT/out/audit.plain.json" --format json --tenant acme --no-redact)"
echo "cli_plain=$CLI_PLAIN"
echo "$CLI_PLAIN" | grep -q '"redacted":false'
grep -q "$SECRET" "$ROOT/out/audit.plain.json"

# GET /audit respects same redact rules as export
AUDIT_REDACT_Q="$(curl -sf "http://127.0.0.1:$PORT/audit?tenant=acme&limit=20&redact=1" \
  -H "Authorization: Bearer $ACME_KEY")"
echo "audit_redact_query=$AUDIT_REDACT_Q"
echo "$AUDIT_REDACT_Q" | grep -q '"ok":true'
echo "$AUDIT_REDACT_Q" | grep -q '"redacted":true'
echo "$AUDIT_REDACT_Q" | grep -q '\[REDACTED\]'
if echo "$AUDIT_REDACT_Q" | grep -q "$SECRET"; then
  echo "GET /audit?redact=1 still contains secret"
  exit 1
fi
echo "$AUDIT_REDACT_Q" | grep -q 'argumentKeysHash'

AUDIT_PLAIN_Q="$(curl -sf "http://127.0.0.1:$PORT/audit?tenant=acme&limit=20&redact=0" \
  -H "Authorization: Bearer $ACME_KEY")"
echo "audit_plain_query=$AUDIT_PLAIN_Q"
echo "$AUDIT_PLAIN_Q" | grep -q '"redacted":false'
echo "$AUDIT_PLAIN_Q" | grep -q "$SECRET"

# until= filter (far-past => empty pack); CLI --until likewise
PAST="2000-01-01T00:00:00.000Z"
EXPORT_UNTIL="$(curl -sf "http://127.0.0.1:$PORT/audit/export?format=json&until=$PAST&redact=1" \
  -H "X-Admin-Token: $ADMIN" -o "$ROOT/data/export.until.json" -w '%{http_code}')"
echo "export_until_status=$EXPORT_UNTIL"
test "$EXPORT_UNTIL" = "200"
node --input-type=module -e '
import fs from "node:fs";
const p = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
if (!p.ok || p.count !== 0 || (p.events && p.events.length !== 0)) {
  console.error("until=past should yield empty export", p);
  process.exit(1);
}
if (p.until !== process.argv[2]) {
  console.error("until meta missing", p.until);
  process.exit(1);
}
console.log("export_until_empty_ok");
' "$ROOT/data/export.until.json" "$PAST"

AUDIT_UNTIL_Q="$(curl -sf "http://127.0.0.1:$PORT/audit?until=$PAST&limit=20&redact=1" \
  -H "X-Admin-Token: $ADMIN")"
echo "audit_until_query=$AUDIT_UNTIL_Q"
echo "$AUDIT_UNTIL_Q" | grep -q '"ok":true'
echo "$AUDIT_UNTIL_Q" | grep -q '"count":0'

CLI_UNTIL="$(node src/cli.js export-audit --config "$POLICY" --audit "$AUDIT" \
  --out "$ROOT/out/audit.until.json" --format json --until "$PAST" --redact)"
echo "cli_until=$CLI_UNTIL"
echo "$CLI_UNTIL" | grep -q '"ok":true'
node --input-type=module -e '
import fs from "node:fs";
const p = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
if (!p.ok || p.count !== 0) {
  console.error("CLI --until past should be empty", p);
  process.exit(1);
}
console.log("cli_until_empty_ok");
' "$ROOT/out/audit.until.json"

# Dedicated prove: audit.redactOnWrite=true stores redacted JSONL on disk
ROW_PORT="${ROW_PORT:-8788}"
ROW_AUDIT="$ROOT/data/audit.redact-on-write.jsonl"
ROW_POLICY="$ROOT/data/policy.redact-on-write.json"
ROW_SECRET='sk_live_rowrite_secret_7b1e'
rm -f "$ROW_AUDIT"
node --input-type=module -e '
import fs from "node:fs";
const p = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
p.audit = { ...(p.audit || {}), redactOnWrite: true };
p.export = { ...(p.export || {}), redactDefault: false };
fs.writeFileSync(process.argv[2], JSON.stringify(p, null, 2) + "\n");
' "$POLICY" "$ROW_POLICY"
node src/cli.js serve --port "$ROW_PORT" --config "$ROW_POLICY" --audit "$ROW_AUDIT" >"$ROOT/data/server.rowrite.log" 2>&1 &
ROW_PID=$!
row_cleanup() { kill "$ROW_PID" 2>/dev/null || true; wait "$ROW_PID" 2>/dev/null || true; }
# extend existing EXIT trap: call row_cleanup then previous cleanup
trap 'row_cleanup; cleanup' EXIT
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$ROW_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
done
ROW_ECHO="$(curl -sf -X POST "http://127.0.0.1:$ROW_PORT/tools/call" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -d "{\"name\":\"echo\",\"arguments\":{\"message\":\"$ROW_SECRET\",\"token\":\"$ROW_SECRET\"}}")"
echo "rowrite_echo=$ROW_ECHO"
echo "$ROW_ECHO" | grep -q '"ok":true'
# live API response still returns the secret (redact is disk-only)
echo "$ROW_ECHO" | grep -q "$ROW_SECRET"
test -f "$ROW_AUDIT"
if grep -q "$ROW_SECRET" "$ROW_AUDIT"; then
  echo "redactOnWrite audit file still contains secret"
  exit 1
fi
grep -q '\[REDACTED\]' "$ROW_AUDIT"
grep -q 'argumentKeysHash' "$ROW_AUDIT"
grep -q '"tool":"echo"' "$ROW_AUDIT"
echo "redact_on_write_ok"
row_cleanup
trap cleanup EXIT

# hot reload: temporarily deny echo for acme via policy edit + POST /admin/reload
cp "$POLICY" "$ROOT/data/policy.before.json"
node --input-type=module -e '
import fs from "node:fs";
const p = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
const t = p.tenants.find((x) => x.id === "acme");
t.deny = Array.from(new Set([...(t.deny || []), "echo"]));
t.allow = (t.allow || []).filter((n) => n !== "echo");
fs.writeFileSync(process.argv[1], JSON.stringify(p, null, 2) + "\n");
' "$POLICY"

RELOAD="$(curl -sf -X POST "http://127.0.0.1:$PORT/admin/reload" -H "X-Admin-Token: $ADMIN")"
echo "reload=$RELOAD"
echo "$RELOAD" | grep -q '"reloaded":true'
echo "$RELOAD" | grep -q 'upstreamPing'

RELOAD_DENY="$(curl -s -o /tmp/b-reload-deny.json -w '%{http_code}' -X POST "http://127.0.0.1:$PORT/tools/call" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -d '{"name":"echo","arguments":{"message":"after-reload"}}')"
echo "reload_deny_status=$RELOAD_DENY body=$(cat /tmp/b-reload-deny.json)"
test "$RELOAD_DENY" = "403"

# restore policy + SIGHUP reload
cp "$ROOT/data/policy.before.json" "$POLICY"
kill -HUP "$PID"
sleep 0.3
RECOVER="$(curl -sf -X POST "http://127.0.0.1:$PORT/tools/call" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -d '{"name":"echo","arguments":{"message":"after-sighup"}}')"
echo "recover=$RECOVER"
echo "$RECOVER" | grep -q '"ok":true'

# Still can proxy after SIGHUP
PROXY2="$(curl -sf -X POST "http://127.0.0.1:$PORT/tools/call" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -d '{"name":"upstreamEcho","arguments":{"message":"still-proxied"}}')"
echo "proxy2=$PROXY2"
echo "$PROXY2" | grep -q '"via":"upstream"'
echo "$PROXY2" | grep -q 'still-proxied'
echo "$PROXY2" | grep -q '"source":"mock-upstream"'

# Isolated upstream timeout prove: delay mock > tiny timeoutMs → 504.
# Main HTTP/stdio proxy uses timeoutMs=30000 so this does not collide.
TO_UP_PORT="${TO_UP_PORT:-8793}"
TO_GW_PORT="${TO_GW_PORT:-8794}"
TO_AUDIT="$ROOT/data/audit.timeout.jsonl"
TO_POLICY="$ROOT/data/policy.timeout.json"
TO_LOG="$ROOT/data/server.timeout.log"
TO_UP_LOG="$ROOT/data/mock-upstream.timeout.log"
rm -f "$TO_AUDIT"
node --input-type=module -e '
import fs from "node:fs";
const p = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
p.upstream = { type: "http", baseUrl: "http://127.0.0.1:" + process.argv[2], timeoutMs: 250, breaker: { enabled: false } };
p.webhooks = [];
fs.writeFileSync(process.argv[3], JSON.stringify(p, null, 2) + "\n");
' "$POLICY" "$TO_UP_PORT" "$TO_POLICY"
node mock-upstream.js --port "$TO_UP_PORT" --delay-ms 1500 >"$TO_UP_LOG" 2>&1 &
TO_UP_PID=$!
TO_GW_PID=""
to_cleanup() {
  if [ -n "${TO_GW_PID:-}" ]; then
    kill "$TO_GW_PID" 2>/dev/null || true
    wait "$TO_GW_PID" 2>/dev/null || true
  fi
  kill "$TO_UP_PID" 2>/dev/null || true
  wait "$TO_UP_PID" 2>/dev/null || true
}
trap 'to_cleanup; cleanup' EXIT
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$TO_UP_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
done
node src/cli.js serve --port "$TO_GW_PORT" --config "$TO_POLICY" --audit "$TO_AUDIT" >"$TO_LOG" 2>&1 &
TO_GW_PID=$!
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$TO_GW_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
done
TO_HEALTH="$(curl -sf "http://127.0.0.1:$TO_GW_PORT/health")"
echo "timeout_health=$TO_HEALTH"
echo "$TO_HEALTH" | grep -q '"connected":true'
echo "$TO_HEALTH" | grep -q 'upstreamPing'
TO_STATUS="$(curl -s -o /tmp/b-upstream-timeout.json -w '%{http_code}' --max-time 5 \
  -X POST "http://127.0.0.1:$TO_GW_PORT/tools/call" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -d '{"name":"upstreamPing","arguments":{"note":"should-timeout"}}')"
echo "upstream_timeout_status=$TO_STATUS body=$(cat /tmp/b-upstream-timeout.json)"
test "$TO_STATUS" = "504"
grep -q '"error":"upstream_timeout"' /tmp/b-upstream-timeout.json
test -f "$TO_AUDIT"
grep -q '"reason":"upstream_timeout"' "$TO_AUDIT"
grep -q '"tool":"upstreamPing"' "$TO_AUDIT"
curl -sf "http://127.0.0.1:$TO_GW_PORT/metrics" -o "$ROOT/data/metrics.timeout.txt"
grep -q 'upstream_timeout_total' "$ROOT/data/metrics.timeout.txt"
node --input-type=module -e '
import fs from "node:fs";
const t = fs.readFileSync(process.argv[1], "utf8");
const m = t.match(/^upstream_timeout_total (\d+)$/m);
if (!m || Number(m[1]) < 1) { console.error("upstream_timeout_total expected >=1", m); process.exit(1); }
console.log("upstream_timeout_total=" + m[1]);
' "$ROOT/data/metrics.timeout.txt"
echo "upstream_timeout_ok"
to_cleanup
trap cleanup EXIT


# Isolated upstream circuit breaker prove: delay mock + low timeoutMs + failureThreshold 1.
# After open, next tools/call is 503 quickly (no upstream). After openMs, half-open probe
# against a fast mock succeeds. Existing timeout/proxy proves keep breaker disabled.
CB_UP_PORT="${CB_UP_PORT:-8795}"
CB_GW_PORT="${CB_GW_PORT:-8796}"
CB_AUDIT="$ROOT/data/audit.breaker.jsonl"
CB_POLICY="$ROOT/data/policy.breaker.json"
CB_LOG="$ROOT/data/server.breaker.log"
CB_UP_LOG="$ROOT/data/mock-upstream.breaker.log"
CB_UP_FAST_LOG="$ROOT/data/mock-upstream.breaker-fast.log"
rm -f "$CB_AUDIT"
node --input-type=module -e '
import fs from "node:fs";
const p = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
p.upstream = {
  type: "http",
  baseUrl: "http://127.0.0.1:" + process.argv[2],
  timeoutMs: 200,
  breaker: { failureThreshold: 1, openMs: 800 },
};
p.webhooks = [];
fs.writeFileSync(process.argv[3], JSON.stringify(p, null, 2) + "\n");
' "$POLICY" "$CB_UP_PORT" "$CB_POLICY"
node mock-upstream.js --port "$CB_UP_PORT" --delay-ms 1500 >"$CB_UP_LOG" 2>&1 &
CB_UP_PID=$!
CB_GW_PID=""
cb_cleanup() {
  if [ -n "${CB_GW_PID:-}" ]; then
    kill "$CB_GW_PID" 2>/dev/null || true
    wait "$CB_GW_PID" 2>/dev/null || true
  fi
  kill "$CB_UP_PID" 2>/dev/null || true
  wait "$CB_UP_PID" 2>/dev/null || true
}
trap 'cb_cleanup; cleanup' EXIT
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$CB_UP_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
done
node src/cli.js serve --port "$CB_GW_PORT" --config "$CB_POLICY" --audit "$CB_AUDIT" >"$CB_LOG" 2>&1 &
CB_GW_PID=$!
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$CB_GW_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
done
CB_HEALTH="$(curl -sf "http://127.0.0.1:$CB_GW_PORT/health")"
echo "breaker_health=$CB_HEALTH"
echo "$CB_HEALTH" | grep -q '"ok":true'
echo "$CB_HEALTH" | grep -q '"connected":true'
echo "$CB_HEALTH" | grep -q 'upstreamPing'
echo "$CB_HEALTH" > /tmp/b-breaker-health-closed.json
node --input-type=module -e '
import fs from "node:fs";
const h = JSON.parse(fs.readFileSync("/tmp/b-breaker-health-closed.json", "utf8"));
if (h.ok !== true) { console.error("breaker /health ok", h); process.exit(1); }
if (!h.breaker) { console.error("breaker /health missing breaker when enabled", h); process.exit(1); }
if (h.breaker.state !== "closed") { console.error("expected closed", h.breaker); process.exit(1); }
if (h.breaker.failures !== 0) { console.error("expected failures 0", h.breaker); process.exit(1); }
if (h.breaker.openUntil != null) { console.error("expected openUntil null when closed", h.breaker); process.exit(1); }
const keys = Object.keys(h.breaker).sort();
if (keys.join(",") !== "failures,openUntil,state") {
  console.error("breaker snapshot extra/missing keys (no secrets)", keys);
  process.exit(1);
}
console.log("breaker_health_closed_ok");
'
# GET /ready while closed — 200 {ok:true} + breaker snapshot
CB_R_CLOSED="$(curl -s -o /tmp/b-breaker-ready-closed.json -w '%{http_code}' "http://127.0.0.1:$CB_GW_PORT/ready")"
echo "breaker_ready_closed_status=$CB_R_CLOSED body=$(cat /tmp/b-breaker-ready-closed.json)"
test "$CB_R_CLOSED" = "200"
node --input-type=module -e '
import fs from "node:fs";
const r = JSON.parse(fs.readFileSync("/tmp/b-breaker-ready-closed.json", "utf8"));
if (r.ok !== true) { console.error("closed /ready ok", r); process.exit(1); }
if (r.reason) { console.error("closed /ready should omit reason", r); process.exit(1); }
if (!r.breaker || r.breaker.state !== "closed") { console.error("expected ready closed", r.breaker); process.exit(1); }
console.log("breaker_ready_closed_ok");
'
# 1) timeout failure opens circuit (threshold 1)
CB_TO_STATUS="$(curl -s -o /tmp/b-breaker-timeout.json -w '%{http_code}' --max-time 5 \
  -X POST "http://127.0.0.1:$CB_GW_PORT/tools/call" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -d '{"name":"upstreamPing","arguments":{"note":"open-breaker"}}')"
echo "breaker_open_via_timeout_status=$CB_TO_STATUS body=$(cat /tmp/b-breaker-timeout.json)"
test "$CB_TO_STATUS" = "504"
grep -q '"error":"upstream_timeout"' /tmp/b-breaker-timeout.json
# 2) next call is 503 quickly — must not wait for delay/timeout
CB_OPEN_TIMING="$(curl -s -o /tmp/b-breaker-open.json -D /tmp/b-breaker-open.h -w '%{http_code} %{time_total}' --max-time 2 \
  -X POST "http://127.0.0.1:$CB_GW_PORT/tools/call" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -d '{"name":"upstreamPing","arguments":{"note":"should-circuit-open"}}')"
echo "breaker_open_timing=$CB_OPEN_TIMING body=$(cat /tmp/b-breaker-open.json)"
CB_OPEN_STATUS="$(echo "$CB_OPEN_TIMING" | awk '{print $1}')"
CB_OPEN_SECS="$(echo "$CB_OPEN_TIMING" | awk '{print $2}')"
test "$CB_OPEN_STATUS" = "503"
grep -q '"error":"circuit_open"' /tmp/b-breaker-open.json
grep -qiE '^retry-after:' /tmp/b-breaker-open.h
node --input-type=module -e '
import fs from "node:fs";
const raw = fs.readFileSync("/tmp/b-breaker-open.h", "utf8");
const line = raw.split(/\r?\n/).find((l) => /^retry-after:/i.test(l));
if (!line) { console.error("missing Retry-After header", raw); process.exit(1); }
const v = line.replace(/^retry-after:/i, "").trim();
const n = Number(v);
if (!/^[0-9]+$/.test(v) || !Number.isInteger(n) || n < 1) {
  console.error("Retry-After must be integer >=1", JSON.stringify(v));
  process.exit(1);
}
console.log("circuit_open_retry_after_ok", n);
'
node --input-type=module -e '
const secs = Number(process.argv[1]);
if (!Number.isFinite(secs) || secs >= 0.5) {
  console.error("circuit_open should be fast, time_total=" + process.argv[1]);
  process.exit(1);
}
console.log("circuit_open_fast_ok time_total=" + process.argv[1]);
' "$CB_OPEN_SECS"
test -f "$CB_AUDIT"
grep -q '"reason":"circuit_open"' "$CB_AUDIT"
grep -q '"reason":"upstream_timeout"' "$CB_AUDIT"
curl -sf "http://127.0.0.1:$CB_GW_PORT/metrics" -o "$ROOT/data/metrics.breaker.txt"
grep -q 'circuit_open_total' "$ROOT/data/metrics.breaker.txt"
node --input-type=module -e '
import fs from "node:fs";
const t = fs.readFileSync(process.argv[1], "utf8");
const m = t.match(/^circuit_open_total (\d+)$/m);
if (!m || Number(m[1]) < 1) { console.error("circuit_open_total expected >=1", m); process.exit(1); }
console.log("circuit_open_total=" + m[1]);
' "$ROOT/data/metrics.breaker.txt"
# 2b) GET /health while open — state open, failures>=1, openUntil ISO in the future
CB_H_OPEN="$(curl -sf "http://127.0.0.1:$CB_GW_PORT/health")"
echo "breaker_health_open=$CB_H_OPEN"
echo "$CB_H_OPEN" | grep -q '"ok":true'
echo "$CB_H_OPEN" > /tmp/b-breaker-health-open.json
node --input-type=module -e '
import fs from "node:fs";
const h = JSON.parse(fs.readFileSync("/tmp/b-breaker-health-open.json", "utf8"));
if (h.ok !== true) { console.error("open /health ok", h); process.exit(1); }
if (!h.breaker || h.breaker.state !== "open") { console.error("expected state open", h.breaker); process.exit(1); }
if (typeof h.breaker.failures !== "number" || h.breaker.failures < 1) {
  console.error("expected failures>=1", h.breaker); process.exit(1);
}
const until = Date.parse(h.breaker.openUntil);
if (!Number.isFinite(until)) { console.error("openUntil not ISO date-time", h.breaker); process.exit(1); }
if (until <= Date.now() - 2000) { console.error("openUntil should be in the future", h.breaker); process.exit(1); }
const keys = Object.keys(h.breaker).sort();
if (keys.join(",") !== "failures,openUntil,state") {
  console.error("breaker snapshot extra/missing keys (no secrets)", keys);
  process.exit(1);
}
console.log("breaker_health_open_ok openUntil=" + h.breaker.openUntil);
'
# 2c) GET /ready while open — 503 {ok:false, reason:circuit_open}; /health stays 200
CB_R_OPEN="$(curl -s -o /tmp/b-breaker-ready-open.json -D /tmp/b-breaker-ready-open.h -w '%{http_code}' "http://127.0.0.1:$CB_GW_PORT/ready")"
echo "breaker_ready_open_status=$CB_R_OPEN body=$(cat /tmp/b-breaker-ready-open.json)"
test "$CB_R_OPEN" = "503"
grep -qiE '^retry-after:' /tmp/b-breaker-ready-open.h
node --input-type=module -e '
import fs from "node:fs";
const r = JSON.parse(fs.readFileSync("/tmp/b-breaker-ready-open.json", "utf8"));
if (r.ok !== false) { console.error("open /ready ok should be false", r); process.exit(1); }
if (r.reason !== "circuit_open") { console.error("open /ready reason", r); process.exit(1); }
if (!r.breaker || r.breaker.state !== "open") { console.error("open /ready breaker", r.breaker); process.exit(1); }
const keys = Object.keys(r.breaker).sort();
if (keys.join(",") !== "failures,openUntil,state") {
  console.error("ready breaker snapshot extra/missing keys (no secrets)", keys);
  process.exit(1);
}
console.log("breaker_ready_open_503_ok");
'
# liveness unchanged: /health still 200 after /ready 503
CB_H_STILL="$(curl -s -o /tmp/b-breaker-health-still.json -w '%{http_code}' "http://127.0.0.1:$CB_GW_PORT/health")"
echo "breaker_health_still_status=$CB_H_STILL"
test "$CB_H_STILL" = "200"
node --input-type=module -e '
import fs from "node:fs";
const h = JSON.parse(fs.readFileSync("/tmp/b-breaker-health-still.json", "utf8"));
if (h.ok !== true) { console.error("/health must stay 200 ok:true while circuit open", h); process.exit(1); }
console.log("breaker_health_liveness_ok_while_ready_503");
'
# 3) half-open: replace delay mock with a fast one so the probe succeeds
kill "$CB_UP_PID" 2>/dev/null || true
wait "$CB_UP_PID" 2>/dev/null || true
node mock-upstream.js --port "$CB_UP_PORT" >"$CB_UP_FAST_LOG" 2>&1 &
CB_UP_PID=$!
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$CB_UP_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
done
# wait past openMs (800) so GET /health transitions to half_open, then probe
sleep 0.9
CB_H_HALF="$(curl -sf "http://127.0.0.1:$CB_GW_PORT/health")"
echo "breaker_health_half_open=$CB_H_HALF"
echo "$CB_H_HALF" | grep -q '"ok":true'
echo "$CB_H_HALF" > /tmp/b-breaker-health-half.json
node --input-type=module -e '
import fs from "node:fs";
const h = JSON.parse(fs.readFileSync("/tmp/b-breaker-health-half.json", "utf8"));
if (h.ok !== true) { console.error("half_open /health ok", h); process.exit(1); }
if (!h.breaker || h.breaker.state !== "half_open") {
  console.error("expected state half_open after openMs", h.breaker); process.exit(1);
}
if (h.breaker.openUntil != null) { console.error("openUntil should be null when half_open", h.breaker); process.exit(1); }
console.log("breaker_health_half_open_ok");
'
# GET /ready while half_open — 200 {ok:true} (probe not consumed)
CB_R_HALF="$(curl -s -o /tmp/b-breaker-ready-half.json -w '%{http_code}' "http://127.0.0.1:$CB_GW_PORT/ready")"
echo "breaker_ready_half_open_status=$CB_R_HALF body=$(cat /tmp/b-breaker-ready-half.json)"
test "$CB_R_HALF" = "200"
node --input-type=module -e '
import fs from "node:fs";
const r = JSON.parse(fs.readFileSync("/tmp/b-breaker-ready-half.json", "utf8"));
if (r.ok !== true) { console.error("half_open /ready ok", r); process.exit(1); }
if (r.reason) { console.error("half_open /ready should omit reason", r); process.exit(1); }
if (!r.breaker || r.breaker.state !== "half_open") { console.error("expected ready half_open", r.breaker); process.exit(1); }
console.log("breaker_ready_half_open_ok");
'
CB_PROBE="$(curl -s -o /tmp/b-breaker-probe.json -w '%{http_code}' --max-time 5 \
  -X POST "http://127.0.0.1:$CB_GW_PORT/tools/call" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -d '{"name":"upstreamPing","arguments":{"note":"half-open-probe"}}')"
echo "breaker_probe_status=$CB_PROBE body=$(cat /tmp/b-breaker-probe.json)"
test "$CB_PROBE" = "200"
grep -q '"ok":true' /tmp/b-breaker-probe.json
grep -q '"via":"upstream"' /tmp/b-breaker-probe.json
grep -q '"source":"mock-upstream"' /tmp/b-breaker-probe.json
grep -q 'half-open-probe' /tmp/b-breaker-probe.json
# after successful probe, GET /health shows closed
CB_H_REC="$(curl -sf "http://127.0.0.1:$CB_GW_PORT/health")"
echo "breaker_health_recovered=$CB_H_REC"
echo "$CB_H_REC" | grep -q '"ok":true'
echo "$CB_H_REC" > /tmp/b-breaker-health-recovered.json
node --input-type=module -e '
import fs from "node:fs";
const h = JSON.parse(fs.readFileSync("/tmp/b-breaker-health-recovered.json", "utf8"));
if (h.ok !== true) { console.error("recovered /health ok", h); process.exit(1); }
if (!h.breaker || h.breaker.state !== "closed") {
  console.error("expected state closed after probe success", h.breaker); process.exit(1);
}
if (h.breaker.failures !== 0) { console.error("expected failures 0 after close", h.breaker); process.exit(1); }
if (h.breaker.openUntil != null) { console.error("openUntil should be null when closed", h.breaker); process.exit(1); }
console.log("breaker_health_closed_after_probe_ok");
'
# after recovery, GET /ready 200 {ok:true}
CB_R_REC="$(curl -s -o /tmp/b-breaker-ready-recovered.json -w '%{http_code}' "http://127.0.0.1:$CB_GW_PORT/ready")"
echo "breaker_ready_recovered_status=$CB_R_REC body=$(cat /tmp/b-breaker-ready-recovered.json)"
test "$CB_R_REC" = "200"
node --input-type=module -e '
import fs from "node:fs";
const r = JSON.parse(fs.readFileSync("/tmp/b-breaker-ready-recovered.json", "utf8"));
if (r.ok !== true) { console.error("recovered /ready ok", r); process.exit(1); }
if (r.reason) { console.error("recovered /ready should omit reason", r); process.exit(1); }
if (!r.breaker || r.breaker.state !== "closed") { console.error("expected ready closed after probe", r.breaker); process.exit(1); }
console.log("breaker_ready_closed_after_probe_ok");
'
echo "upstream_circuit_breaker_ok"
cb_cleanup
trap cleanup EXIT


# Isolated webhook HMAC prove: optional webhooks[].secret → X-Webhook-Signature.
# Main unsigned fan-out/redact proofs above stay intact (no secret on that receiver).
HMAC_WH_PORT="${HMAC_WH_PORT:-8797}"
HMAC_GW_PORT="${HMAC_GW_PORT:-8798}"
HMAC_SECRET="whsec_local_mvp"
HMAC_AUDIT="$ROOT/data/audit.hmac.jsonl"
HMAC_POLICY="$ROOT/data/policy.hmac.json"
HMAC_OUT="$ROOT/data/webhook-hmac-last.json"
HMAC_HDR="$ROOT/data/webhook-hmac-last.headers.json"
HMAC_LOG="$ROOT/data/server.hmac.log"
HMAC_WH_LOG="$ROOT/data/mock-webhook.hmac.log"
rm -f "$HMAC_AUDIT" "$HMAC_OUT" "$HMAC_HDR"
node --input-type=module -e '
import fs from "node:fs";
const p = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
delete p.upstream;
p.webhooks = [
  {
    url: "http://127.0.0.1:" + process.argv[2] + "/hook",
    events: ["tool_call", "deny"],
    secret: process.argv[3],
  },
];
p.webhooksRedact = true;
fs.writeFileSync(process.argv[4], JSON.stringify(p, null, 2) + "\n");
' "$POLICY" "$HMAC_WH_PORT" "$HMAC_SECRET" "$HMAC_POLICY"
node mock-webhook-receiver.js --port "$HMAC_WH_PORT" --out "$HMAC_OUT" --headers-out "$HMAC_HDR" --secret "$HMAC_SECRET" >"$HMAC_WH_LOG" 2>&1 &
HMAC_WH_PID=$!
HMAC_GW_PID=""
hmac_cleanup() {
  if [ -n "${HMAC_GW_PID:-}" ]; then
    kill "$HMAC_GW_PID" 2>/dev/null || true
    wait "$HMAC_GW_PID" 2>/dev/null || true
  fi
  kill "$HMAC_WH_PID" 2>/dev/null || true
  wait "$HMAC_WH_PID" 2>/dev/null || true
}
trap 'hmac_cleanup; cleanup' EXIT
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$HMAC_WH_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
done
node src/cli.js serve --port "$HMAC_GW_PORT" --config "$HMAC_POLICY" --audit "$HMAC_AUDIT" >"$HMAC_LOG" 2>&1 &
HMAC_GW_PID=$!
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$HMAC_GW_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
done
HMAC_ECHO="$(curl -sf -X POST "http://127.0.0.1:$HMAC_GW_PORT/tools/call" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -d '{"name":"echo","arguments":{"message":"hmac-proof"}}')"
echo "hmac_echo=$HMAC_ECHO"
echo "$HMAC_ECHO" | grep -q '"ok":true'
HMAC_OK=0
for i in $(seq 1 40); do
  if test -f "$HMAC_OUT" && grep -q '"type":"tool_call"' "$HMAC_OUT" 2>/dev/null \
     && test -f "$HMAC_HDR" && grep -q 'sha256=' "$HMAC_HDR" 2>/dev/null; then
    HMAC_OK=1
    break
  fi
  sleep 0.05
done
test "$HMAC_OK" = "1"
grep -q '"tool":"echo"' "$HMAC_OUT"
grep -q '"source":"mcp-gateway"' "$HMAC_OUT"
grep -q '"redacted":true' "$HMAC_OUT"
# signature header present when secret configured
grep -qi 'sha256=' "$HMAC_HDR"
grep -q '"verified": true' "$HMAC_HDR"
node --input-type=module -e '
import fs from "node:fs";
import { signWebhookBody, verifyWebhookSignature } from "./src/webhooks.js";
const secret = process.argv[1];
const body = fs.readFileSync(process.argv[2], "utf8");
const meta = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const sig = String(meta.signature || "");
if (!sig.toLowerCase().startsWith("sha256=")) {
  console.error("missing X-Webhook-Signature sha256= prefix", meta);
  process.exit(1);
}
const expected = signWebhookBody(secret, body);
if (sig.toLowerCase() !== expected) {
  console.error("HMAC mismatch", { got: sig, expected });
  process.exit(1);
}
if (!verifyWebhookSignature(secret, body, sig)) {
  console.error("verifyWebhookSignature failed");
  process.exit(1);
}
if (meta.verified !== true) {
  console.error("receiver verified flag", meta.verified);
  process.exit(1);
}
if (body.includes("hmac-proof")) {
  console.error("hmac webhook leaked unredacted message");
  process.exit(1);
}

const raw = meta.timestamp ?? (meta.headers && (meta.headers["x-webhook-timestamp"] || meta.headers["X-Webhook-Timestamp"]));
const ts = Number(String(raw || "").trim());
if (!Number.isFinite(ts) || ts <= 0) {
  console.error("missing X-Webhook-Timestamp", meta);
  process.exit(1);
}
const now = Math.floor(Date.now() / 1000);
if (Math.abs(now - ts) > 120) {
  console.error("timestamp not now", { ts, now });
  process.exit(1);
}

console.log("webhook_hmac_ok", expected.slice(0, 18) + "…", "ts=" + ts);
' "$HMAC_SECRET" "$HMAC_OUT" "$HMAC_HDR"
echo "webhook_hmac_ok"
hmac_cleanup
trap cleanup EXIT

# Isolated webhook 1-retry prove: mock returns 500 once then 200.
# Unsigned fan-out above stays first-try 200 (no retry). HMAC prove unchanged.
RETRY_WH_PORT="${RETRY_WH_PORT:-8785}"
RETRY_GW_PORT="${RETRY_GW_PORT:-8786}"
RETRY_AUDIT="$ROOT/data/audit.retry.jsonl"
RETRY_POLICY="$ROOT/data/policy.retry.json"
RETRY_OUT="$ROOT/data/webhook-retry-last.json"
RETRY_LOG="$ROOT/data/server.retry.log"
RETRY_WH_LOG="$ROOT/data/mock-webhook.retry.log"
rm -f "$RETRY_AUDIT" "$RETRY_OUT"
node --input-type=module -e '
import fs from "node:fs";
const p = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
delete p.upstream;
p.webhooks = [
  {
    url: "http://127.0.0.1:" + process.argv[2] + "/hook",
    events: ["tool_call", "deny"],
  },
];
p.webhooksRedact = true;
fs.writeFileSync(process.argv[3], JSON.stringify(p, null, 2) + "\n");
' "$POLICY" "$RETRY_WH_PORT" "$RETRY_POLICY"
node mock-webhook-receiver.js --port "$RETRY_WH_PORT" --fail-once --out "$RETRY_OUT" >"$RETRY_WH_LOG" 2>&1 &
RETRY_WH_PID=$!
RETRY_GW_PID=""
retry_cleanup() {
  if [ -n "${RETRY_GW_PID:-}" ]; then
    kill "$RETRY_GW_PID" 2>/dev/null || true
    wait "$RETRY_GW_PID" 2>/dev/null || true
  fi
  kill "$RETRY_WH_PID" 2>/dev/null || true
  wait "$RETRY_WH_PID" 2>/dev/null || true
}
trap 'retry_cleanup; cleanup' EXIT
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$RETRY_WH_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
done
node src/cli.js serve --port "$RETRY_GW_PORT" --config "$RETRY_POLICY" --audit "$RETRY_AUDIT" >"$RETRY_LOG" 2>&1 &
RETRY_GW_PID=$!
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$RETRY_GW_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
done
RETRY_ECHO="$(curl -sf -X POST "http://127.0.0.1:$RETRY_GW_PORT/tools/call" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -d '{"name":"echo","arguments":{"message":"retry-proof"}}')"
echo "retry_echo=$RETRY_ECHO"
echo "$RETRY_ECHO" | grep -q '"ok":true'
RETRY_OK=0
for i in $(seq 1 40); do
  if test -f "$RETRY_OUT" && grep -q '"type":"tool_call"' "$RETRY_OUT" 2>/dev/null; then
    RETRY_OK=1
    break
  fi
  sleep 0.05
done
test "$RETRY_OK" = "1"
grep -q '"tool":"echo"' "$RETRY_OUT"
grep -q '"source":"mcp-gateway"' "$RETRY_OUT"
grep -q '"redacted":true' "$RETRY_OUT"
grep -q '\[REDACTED\]' "$RETRY_OUT"
if grep -q 'retry-proof' "$RETRY_OUT"; then
  echo "retry webhook leaked unredacted message"
  exit 1
fi
RETRY_STATS="$(curl -sf "http://127.0.0.1:$RETRY_WH_PORT/stats")"
echo "retry_stats=$RETRY_STATS"
echo "$RETRY_STATS" | grep -q '"requests":2'
curl -sf "http://127.0.0.1:$RETRY_GW_PORT/metrics" -o "$ROOT/data/metrics.retry.txt"
grep -q 'webhook_retries_total' "$ROOT/data/metrics.retry.txt"
node --input-type=module -e '
import fs from "node:fs";
const t = fs.readFileSync(process.argv[1], "utf8");
const m = t.match(/^webhook_retries_total (\d+)$/m);
if (!m || Number(m[1]) < 1) {
  console.error("webhook_retries_total expected >=1 after fail-once", m, t);
  process.exit(1);
}
console.log("webhook_retries_total=" + m[1]);
' "$ROOT/data/metrics.retry.txt"
echo "webhook_retry_ok"
retry_cleanup
trap cleanup EXIT

# Isolated serve --watch prove: poll config mtime (~300ms) and reload policy
# (same path as SIGHUP / POST /admin/reload). Copy of policy — do not mutate
# the main mvp policy (existing SIGHUP/reload proves stay intact). Must not hang.
echo "==> [watch] isolated serve --watch (config mtime poll reload; must not hang)"
WATCH_PORT="${WATCH_PORT:-8784}"
WATCH_POLICY="$ROOT/data/policy.watch.json"
WATCH_AUDIT="$ROOT/data/audit.watch.jsonl"
WATCH_LOG="$ROOT/data/server.watch.log"
WATCH_BEFORE="$ROOT/data/watch-before-list.json"
WATCH_AFTER="$ROOT/data/watch-after-list.json"
WATCH_BEFORE_TENANTS="$ROOT/data/watch-before-tenants.json"
WATCH_AFTER_TENANTS="$ROOT/data/watch-after-tenants.json"
rm -f "$WATCH_AUDIT" "$WATCH_LOG" "$WATCH_BEFORE" "$WATCH_AFTER" "$WATCH_BEFORE_TENANTS" "$WATCH_AFTER_TENANTS"
cp "$POLICY_SRC" "$WATCH_POLICY"
node src/cli.js serve --port "$WATCH_PORT" --config "$WATCH_POLICY" --audit "$WATCH_AUDIT" --watch >"$WATCH_LOG" 2>&1 &
WATCH_PID=$!
watch_cleanup() {
  if [ -n "${WATCH_PID:-}" ] && kill -0 "$WATCH_PID" 2>/dev/null; then
    kill "$WATCH_PID" 2>/dev/null || true
    for i in $(seq 1 20); do
      if ! kill -0 "$WATCH_PID" 2>/dev/null; then
        break
      fi
      sleep 0.1
    done
    kill -9 "$WATCH_PID" 2>/dev/null || true
    wait "$WATCH_PID" 2>/dev/null || true
  fi
}
trap 'watch_cleanup; cleanup' EXIT
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$WATCH_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 50 ]; then
    echo "watch serve did not become healthy"
    cat "$WATCH_LOG" || true
    exit 1
  fi
  if ! kill -0 "$WATCH_PID" 2>/dev/null; then
    echo "watch serve exited early"
    cat "$WATCH_LOG" || true
    exit 1
  fi
done
grep -q "watch=poll 300ms" "$WATCH_LOG"
grep -q "watching" "$WATCH_LOG"

curl -sf -X POST "http://127.0.0.1:$WATCH_PORT/tools/list" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" -d '{}' \
  -o "$WATCH_BEFORE"
curl -sf "http://127.0.0.1:$WATCH_PORT/admin/tenants" -H "X-Admin-Token: $ADMIN" \
  -o "$WATCH_BEFORE_TENANTS"
if grep -q '"name":"watchDummy"' "$WATCH_BEFORE"; then
  echo "watchDummy must not be in tools/list before mutate"
  cat "$WATCH_BEFORE"
  exit 1
fi
echo "watch_before_list=$(cat "$WATCH_BEFORE")"
node --input-type=module -e '
import fs from "node:fs";
const tenants = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
const list = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
if (!tenants.ok || !Array.isArray(tenants.tenants)) {
  console.error("watch before tenants invalid", tenants);
  process.exit(1);
}
const acme = tenants.tenants.find((t) => t.id === "acme");
if (!acme || typeof acme.allowCount !== "number") {
  console.error("watch before missing acme allowCount", tenants);
  process.exit(1);
}
if (!Array.isArray(list.tools) || !list.tools.some((t) => t.name === "echo")) {
  console.error("watch before tools/list missing echo", list);
  process.exit(1);
}
fs.writeFileSync("/tmp/b-watch-before-allowCount", String(acme.allowCount));
console.log("watch_before_ok allowCount=" + acme.allowCount + " tools=" + list.tools.length);
' "$WATCH_BEFORE_TENANTS" "$WATCH_BEFORE"
BEFORE_ALLOW="$(cat /tmp/b-watch-before-allowCount)"

node --input-type=module -e '
import fs from "node:fs";
const p = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
const name = "watchDummy";
p.tools = [
  ...(p.tools || []),
  { name, description: "watch prove dummy", inputSchema: { type: "object", properties: {} } },
];
p.allow = Array.from(new Set([...(p.allow || []), name]));
for (const t of p.tenants || []) {
  if (t.id === "acme") {
    t.allow = Array.from(new Set([...(t.allow || []), name]));
  }
}
fs.writeFileSync(process.argv[1], JSON.stringify(p, null, 2) + "\n");
const now = Date.now() / 1000 + 1;
fs.utimesSync(process.argv[1], now, now);
console.log("watch_policy_mutated", name);
' "$WATCH_POLICY"

REGEN_OK=0
for _ in $(seq 1 25); do
  curl -sf -X POST "http://127.0.0.1:$WATCH_PORT/tools/list" \
    -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" -d '{}' \
    -o "$WATCH_AFTER" || true
  curl -sf "http://127.0.0.1:$WATCH_PORT/admin/tenants" -H "X-Admin-Token: $ADMIN" \
    -o "$WATCH_AFTER_TENANTS" || true
  if grep -q regenerated "$WATCH_LOG" 2>/dev/null; then
    curl -sf -X POST "http://127.0.0.1:$WATCH_PORT/tools/list" \
      -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" -d '{}' \
      -o "$WATCH_AFTER" || true
    curl -sf "http://127.0.0.1:$WATCH_PORT/admin/tenants" -H "X-Admin-Token: $ADMIN" \
      -o "$WATCH_AFTER_TENANTS" || true
    REGEN_OK=1
    break
  fi
  if test -s "$WATCH_AFTER" && grep -q '"name":"watchDummy"' "$WATCH_AFTER" 2>/dev/null; then
    REGEN_OK=1
    break
  fi
  if ! kill -0 "$WATCH_PID" 2>/dev/null; then
    echo "watch serve died before regenerate"
    cat "$WATCH_LOG" || true
    exit 1
  fi
  sleep 0.2
done

watch_cleanup
WATCH_PID=""
trap cleanup EXIT

if [ "$REGEN_OK" != "1" ]; then
  echo "watch did not regenerate within 5s"
  echo "--- server.watch.log ---"
  cat "$WATCH_LOG" || true
  exit 1
fi

test -s "$WATCH_AFTER"
test -s "$WATCH_AFTER_TENANTS"
grep -q '"name":"watchDummy"' "$WATCH_AFTER"
node --input-type=module -e '
import fs from "node:fs";
const beforeCount = Number(process.argv[1]);
const tenants = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const list = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const acme = (tenants.tenants || []).find((t) => t.id === "acme");
if (!acme) { console.error("watch after missing acme", tenants); process.exit(1); }
if (!(acme.allowCount > beforeCount)) {
  console.error("expected acme allowCount to increase", { beforeCount, after: acme.allowCount });
  process.exit(1);
}
if (!Array.isArray(list.tools) || !list.tools.some((t) => t.name === "watchDummy")) {
  console.error("watchDummy missing from tools/list after reload", list);
  process.exit(1);
}
console.log("watch_reload_ok", { beforeAllow: beforeCount, afterAllow: acme.allowCount, tools: list.tools.map((t) => t.name) });
' "$BEFORE_ALLOW" "$WATCH_AFTER_TENANTS" "$WATCH_AFTER"
if ! grep -q regenerated "$WATCH_LOG"; then
  echo "watch regenerate detected via HTTP but missing regenerated log line"
  cat "$WATCH_LOG" || true
  exit 1
fi
grep -q "watching" "$WATCH_LOG"
echo "watch regenerate OK"

echo "==> [shutdown] isolated SIGTERM drain (ready 503 shutting_down; health 200 shuttingDown; exit)"
SD_PORT="${SD_PORT:-8783}"
SD_AUDIT="$ROOT/data/audit.shutdown.jsonl"
SD_LOG="$ROOT/data/server.shutdown.log"
rm -f "$SD_AUDIT" "$SD_LOG"
node src/cli.js serve --port "$SD_PORT" --config "$POLICY" --audit "$SD_AUDIT" --drain-ms 800 >"$SD_LOG" 2>&1 &
SD_PID=$!
sd_cleanup() {
  if [ -n "${SD_PID:-}" ] && kill -0 "$SD_PID" 2>/dev/null; then
    kill -9 "$SD_PID" 2>/dev/null || true
    wait "$SD_PID" 2>/dev/null || true
  fi
}
trap 'sd_cleanup; cleanup' EXIT
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$SD_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 50 ]; then
    echo "shutdown serve did not become healthy"
    cat "$SD_LOG" || true
    exit 1
  fi
  if ! kill -0 "$SD_PID" 2>/dev/null; then
    echo "shutdown serve exited early"
    cat "$SD_LOG" || true
    exit 1
  fi
done
kill -TERM "$SD_PID"
SD_READY=""
SD_HEALTH=""
for i in $(seq 1 20); do
  SD_READY="$(curl -s -o /tmp/b-sd-ready.json -w '%{http_code}' "http://127.0.0.1:$SD_PORT/ready" || true)"
  SD_HEALTH="$(curl -s -o /tmp/b-sd-health.json -w '%{http_code}' "http://127.0.0.1:$SD_PORT/health" || true)"
  if [ "$SD_READY" = "503" ]; then
    break
  fi
  sleep 0.05
done
if [ "$SD_READY" != "503" ]; then
  echo "shutdown /ready expected 503 got $SD_READY"
  cat /tmp/b-sd-ready.json 2>/dev/null || true
  cat "$SD_LOG" || true
  exit 1
fi
if [ "$SD_HEALTH" != "200" ]; then
  echo "shutdown /health expected 200 got $SD_HEALTH"
  cat /tmp/b-sd-health.json 2>/dev/null || true
  exit 1
fi
node --input-type=module -e '
import fs from "node:fs";
const ready = JSON.parse(fs.readFileSync("/tmp/b-sd-ready.json", "utf8"));
const health = JSON.parse(fs.readFileSync("/tmp/b-sd-health.json", "utf8"));
if (ready.ok !== false || ready.reason !== "shutting_down") {
  console.error("shutdown ready payload", ready);
  process.exit(1);
}
if (health.ok !== true || health.shuttingDown !== true) {
  console.error("shutdown health payload", health);
  process.exit(1);
}
console.log("shutdown_http_ok", { ready: ready.reason, shuttingDown: health.shuttingDown });
'
for i in $(seq 1 30); do
  if ! kill -0 "$SD_PID" 2>/dev/null; then
    break
  fi
  sleep 0.1
done
if kill -0 "$SD_PID" 2>/dev/null; then
  echo "shutdown process did not exit within drain window"
  cat "$SD_LOG" || true
  exit 1
fi
wait "$SD_PID" 2>/dev/null || true
SD_PID=""
grep -q "shutting down" "$SD_LOG"
grep -q "exit" "$SD_LOG"
echo "shutdown SIGTERM OK"

echo "==> [access-log] default serve has no JSON access flood"
if grep -q '{"msg":"http"' "$ROOT/data/server.log"; then
  echo "default serve must not emit JSON access logs"
  grep '{"msg":"http"' "$ROOT/data/server.log" || true
  exit 1
fi

echo "==> [access-log] isolated serve --log-json (app path + X-Request-Id; skip probes)"
LOG_PORT="${LOG_PORT:-8782}"
LOG_AUDIT="$ROOT/data/audit.access.jsonl"
LOG_LOG="$ROOT/data/server.access.log"
rm -f "$LOG_AUDIT" "$LOG_LOG"
node src/cli.js serve --port "$LOG_PORT" --config "$POLICY" --audit "$LOG_AUDIT" --log-json --drain-ms 200 >"$LOG_LOG" 2>&1 &
LOG_PID=$!
log_cleanup() {
  if [ -n "${LOG_PID:-}" ] && kill -0 "$LOG_PID" 2>/dev/null; then
    kill "$LOG_PID" 2>/dev/null || true
    wait "$LOG_PID" 2>/dev/null || true
  fi
}
trap 'log_cleanup; sd_cleanup; cleanup' EXIT
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$LOG_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 50 ]; then
    echo "access-log serve did not become healthy"
    cat "$LOG_LOG" || true
    exit 1
  fi
  if ! kill -0 "$LOG_PID" 2>/dev/null; then
    echo "access-log serve exited early"
    cat "$LOG_LOG" || true
    exit 1
  fi
done
# probes must not emit access lines
curl -sf "http://127.0.0.1:$LOG_PORT/health" >/dev/null
curl -sf "http://127.0.0.1:$LOG_PORT/ready" >/dev/null
curl -sf "http://127.0.0.1:$LOG_PORT/metrics" >/dev/null
# app path
curl -sf -D /tmp/b-access.h -o /tmp/b-access.body \
  -H "X-Request-Id: test-log-1" \
  "http://127.0.0.1:$LOG_PORT/openapi.json" >/dev/null
grep -qiE '^x-request-id:[[:space:]]*test-log-1' /tmp/b-access.h
sleep 0.15
node --input-type=module -e '
import fs from "node:fs";
const needle = "\"msg\":\"http\"";
const log = fs.readFileSync(process.argv[1], "utf8");
const hits = [];
for (const l of log.split("\n")) {
  if (!l.includes(needle)) continue;
  try { hits.push(JSON.parse(l)); } catch { /* ignore */ }
}
const http = hits.filter((o) => o && o.msg === "http");
if (http.length !== 1) {
  console.error("expected exactly 1 http access line (probes skipped)", http, log);
  process.exit(1);
}
const rec = http[0];
if (
  rec.level !== "info" ||
  rec.service !== "mcp-gateway" ||
  rec.method !== "GET" ||
  rec.path !== "/openapi.json" ||
  rec.status !== 200 ||
  rec.requestId !== "test-log-1" ||
  typeof rec.durationMs !== "number"
) {
  console.error("access log fields", rec);
  process.exit(1);
}
console.log("access_log_ok", { requestId: rec.requestId, status: rec.status, durationMs: rec.durationMs, path: rec.path });
' "$LOG_LOG"
kill "$LOG_PID" 2>/dev/null || true
for i in $(seq 1 20); do
  if ! kill -0 "$LOG_PID" 2>/dev/null; then
    break
  fi
  sleep 0.1
done
kill -9 "$LOG_PID" 2>/dev/null || true
wait "$LOG_PID" 2>/dev/null || true
LOG_PID=""
echo "access-log JSON OK"

echo "==> [rotate] isolated admin tenant API token rotation (grace=0; do not touch main acme key)"
ROTATE_PORT="${ROTATE_PORT:-8781}"
ROTATE_POLICY="$ROOT/data/policy.rotate.json"
ROTATE_AUDIT="$ROOT/data/audit.rotate.jsonl"
ROTATE_LOG="$ROOT/data/server.rotate.log"
ROTATE_ADMIN_CSV="$ROOT/data/admin.rotate.csv"
rm -f "$ROTATE_AUDIT" "$ROTATE_LOG" "$ROTATE_ADMIN_CSV"
cp "$POLICY" "$ROTATE_POLICY"
node src/cli.js serve --port "$ROTATE_PORT" --config "$ROTATE_POLICY" --audit "$ROTATE_AUDIT" --rotate-grace-sec 0 --drain-ms 200 >"$ROTATE_LOG" 2>&1 &
ROTATE_PID=$!
rotate_cleanup() {
  if [ -n "${ROTATE_PID:-}" ] && kill -0 "$ROTATE_PID" 2>/dev/null; then
    kill "$ROTATE_PID" 2>/dev/null || true
    wait "$ROTATE_PID" 2>/dev/null || true
  fi
}
trap 'rotate_cleanup; log_cleanup; sd_cleanup; cleanup' EXIT
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$ROTATE_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 50 ]; then
    echo "rotate serve did not become healthy"
    cat "$ROTATE_LOG" || true
    exit 1
  fi
  if ! kill -0 "$ROTATE_PID" 2>/dev/null; then
    echo "rotate serve exited early"
    cat "$ROTATE_LOG" || true
    exit 1
  fi
done

ROTATE_UNAUTH="$(curl -s -o /tmp/b-rotate-unauth.json -w '%{http_code}' \
  -X POST "http://127.0.0.1:$ROTATE_PORT/admin/tenants/restricted/rotate")"
echo "rotate_unauth_status=$ROTATE_UNAUTH body=$(cat /tmp/b-rotate-unauth.json)"
test "$ROTATE_UNAUTH" = "401"
grep -q 'unauthorized_admin' /tmp/b-rotate-unauth.json

ROTATE_BAD="$(curl -s -o /tmp/b-rotate-bad.json -w '%{http_code}' \
  -X POST "http://127.0.0.1:$ROTATE_PORT/admin/tenants/restricted/rotate" \
  -H "X-Admin-Token: wrong")"
echo "rotate_bad_status=$ROTATE_BAD body=$(cat /tmp/b-rotate-bad.json)"
test "$ROTATE_BAD" = "401"

ROTATE_MISS="$(curl -s -o /tmp/b-rotate-miss.json -w '%{http_code}' \
  -X POST "http://127.0.0.1:$ROTATE_PORT/admin/tenants/no-such-tenant/rotate" \
  -H "X-Admin-Token: $ADMIN")"
echo "rotate_unknown_status=$ROTATE_MISS body=$(cat /tmp/b-rotate-miss.json)"
test "$ROTATE_MISS" = "404"
grep -q 'unknown_tenant' /tmp/b-rotate-miss.json

OLD_REST_KEY="ten_restricted_dev"
ROTATE_JSON="$(curl -sf -X POST "http://127.0.0.1:$ROTATE_PORT/admin/tenants/restricted/rotate" \
  -H "X-Admin-Token: $ADMIN")"
echo "rotate_restricted_ok=$(echo "$ROTATE_JSON" | node --input-type=module -e '
import fs from "node:fs";
const s = fs.readFileSync(0, "utf8");
const b = JSON.parse(s);
if (b.ok !== true || b.tenantId !== "restricted" || typeof b.token !== "string" || !b.token) {
  console.error("rotate 200 payload", b);
  process.exit(1);
}
if (b.token === process.argv[1]) {
  console.error("new token equals old");
  process.exit(1);
}
fs.writeFileSync("/tmp/b-rotate-new-token", b.token);
console.log("tenantId=" + b.tenantId + " tokenLen=" + b.token.length + " hasExpiry=" + Boolean(b.previousTokenExpiresAt));
' "$OLD_REST_KEY")"
NEW_REST_KEY="$(cat /tmp/b-rotate-new-token)"
test -n "$NEW_REST_KEY"
test "$NEW_REST_KEY" != "$OLD_REST_KEY"

NEW_LIST="$(curl -sf -X POST "http://127.0.0.1:$ROTATE_PORT/tools/list" \
  -H 'content-type: application/json' -H "Authorization: Bearer $NEW_REST_KEY" -d '{}')"
echo "rotate_new_token_list=$NEW_LIST"
echo "$NEW_LIST" | grep -q '"tenantId":"restricted"'

OLD_STATUS="$(curl -s -o /tmp/b-rotate-old.json -w '%{http_code}' \
  -X POST "http://127.0.0.1:$ROTATE_PORT/tools/list" \
  -H 'content-type: application/json' -H "Authorization: Bearer $OLD_REST_KEY" -d '{}')"
echo "rotate_old_token_status=$OLD_STATUS body=$(cat /tmp/b-rotate-old.json)"
test "$OLD_STATUS" = "401"

test -f "$ROTATE_AUDIT"
grep -q '"type":"token_rotated"' "$ROTATE_AUDIT"
if grep -F "$NEW_REST_KEY" "$ROTATE_AUDIT"; then
  echo "audit jsonl leaked new token"
  exit 1
fi
if grep -F "$NEW_REST_KEY" "$ROTATE_LOG"; then
  echo "server log leaked new token"
  exit 1
fi

curl -sf "http://127.0.0.1:$ROTATE_PORT/admin/audit.csv" -H "X-Admin-Token: $ADMIN" -o "$ROTATE_ADMIN_CSV"
if grep -F "$NEW_REST_KEY" "$ROTATE_ADMIN_CSV"; then
  echo "admin audit CSV leaked new token"
  cat "$ROTATE_ADMIN_CSV"
  exit 1
fi
grep -q 'ts,tenantId,tool,allow,reason,via,requestId' "$ROTATE_ADMIN_CSV"

# file-backed persist: new apiKey written to the isolated policy copy
node --input-type=module -e '
import fs from "node:fs";
const pol = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
const t = (pol.tenants || []).find((x) => x.id === "restricted");
if (!t || t.apiKey !== process.argv[2]) {
  console.error("expected persisted apiKey for restricted", t);
  process.exit(1);
}
console.log("rotate_persisted_ok");
' "$ROTATE_POLICY" "$NEW_REST_KEY"

# metrics path must not include the secret
ROTATE_METRICS="$(curl -sf "http://127.0.0.1:$ROTATE_PORT/metrics")"
if echo "$ROTATE_METRICS" | grep -F "$NEW_REST_KEY"; then
  echo "metrics leaked new token"
  exit 1
fi

rotate_cleanup
ROTATE_PID=""
trap 'log_cleanup; sd_cleanup; cleanup' EXIT
echo "rotate isolated OK"

echo "==> [audit-max] isolated in-memory ring buffer (--audit-max 2; drop oldest; admin CSV window)"
CAP_PORT="${CAP_PORT:-8780}"
CAP_POLICY="$ROOT/data/policy.auditmax.json"
CAP_AUDIT="$ROOT/data/audit.auditmax.jsonl"
CAP_LOG="$ROOT/data/server.auditmax.log"
CAP_CSV="$ROOT/data/admin.auditmax.csv"
rm -f "$CAP_AUDIT" "$CAP_LOG" "$CAP_CSV" "$ROOT/data/export.auditmax.csv"
cp "$POLICY_SRC" "$CAP_POLICY"
node src/cli.js serve --port "$CAP_PORT" --config "$CAP_POLICY" --audit "$CAP_AUDIT" --audit-max 2 --drain-ms 200 >"$CAP_LOG" 2>&1 &
CAP_PID=$!
cap_cleanup() {
  if [ -n "${CAP_PID:-}" ] && kill -0 "$CAP_PID" 2>/dev/null; then
    kill "$CAP_PID" 2>/dev/null || true
    wait "$CAP_PID" 2>/dev/null || true
  fi
}
trap 'cap_cleanup; rotate_cleanup; log_cleanup; sd_cleanup; cleanup' EXIT
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$CAP_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 50 ]; then
    echo "audit-max serve did not become healthy"
    cat "$CAP_LOG" || true
    exit 1
  fi
  if ! kill -0 "$CAP_PID" 2>/dev/null; then
    echo "audit-max serve exited early"
    cat "$CAP_LOG" || true
    exit 1
  fi
done

for n in 1 2 3; do
  curl -sf -X POST "http://127.0.0.1:$CAP_PORT/tools/call" \
    -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
    -H "X-Request-Id: cap-$n" \
    -d '{"name":"echo","arguments":{"message":"cap-'"$n"'"}}' >/dev/null
done

curl -sf "http://127.0.0.1:$CAP_PORT/admin/audit.csv" -H "X-Admin-Token: $ADMIN" -o "$CAP_CSV"
CAP_HEAD="$(head -n 1 "$CAP_CSV" | tr -d '\r')"
test "$CAP_HEAD" = "ts,tenantId,tool,allow,reason,via,requestId"
CAP_ROWS="$(tail -n +2 "$CAP_CSV" | sed '/^$/d' | wc -l | tr -d ' ')"
echo "audit_max_admin_csv_rows=$CAP_ROWS"
test "$CAP_ROWS" = "2"
grep -q 'cap-2' "$CAP_CSV"
grep -q 'cap-3' "$CAP_CSV"
if grep -q 'cap-1' "$CAP_CSV"; then
  echo "audit-max admin CSV still has oldest event cap-1"
  cat "$CAP_CSV"
  exit 1
fi

CAP_MD="$ROOT/data/admin.auditmax.md"
curl -sf "http://127.0.0.1:$CAP_PORT/admin/audit.md" -H "X-Admin-Token: $ADMIN" -o "$CAP_MD"
grep -q '# Audit' "$CAP_MD"
grep -q '| ts | tenantId | tool | allow | reason | via | requestId |' "$CAP_MD"
grep -q 'cap-2' "$CAP_MD"
grep -q 'cap-3' "$CAP_MD"
if grep -q 'cap-1' "$CAP_MD"; then
  echo "audit-max admin Markdown still has oldest event cap-1"
  cat "$CAP_MD"
  exit 1
fi

CAP_JSON="$(curl -sf "http://127.0.0.1:$CAP_PORT/admin/audit?format=json" -H "X-Admin-Token: $ADMIN")"
echo "$CAP_JSON" | grep -q '"count":2'
echo "$CAP_JSON" | grep -q 'cap-2'
echo "$CAP_JSON" | grep -q 'cap-3'
if echo "$CAP_JSON" | grep -q 'cap-1'; then
  echo "audit-max admin JSON still has oldest event cap-1"
  echo "$CAP_JSON"
  exit 1
fi

CAP_EXPORT_FILE="$ROOT/data/export.auditmax.csv"
curl -sf "http://127.0.0.1:$CAP_PORT/audit/export?format=csv" -H "X-Admin-Token: $ADMIN" -o "$CAP_EXPORT_FILE"
CAP_EXPORT_ROWS="$(tail -n +2 "$CAP_EXPORT_FILE" | sed '/^$/d' | wc -l | tr -d ' ')"
echo "audit_max_export_csv_rows=$CAP_EXPORT_ROWS"
test "$CAP_EXPORT_ROWS" = "2"
grep -q 'cap-2' "$CAP_EXPORT_FILE"
grep -q 'cap-3' "$CAP_EXPORT_FILE"
if grep -q 'cap-1' "$CAP_EXPORT_FILE"; then
  echo "audit-max export CSV still has oldest event cap-1"
  cat "$CAP_EXPORT_FILE"
  exit 1
fi

CAP_METRICS="$(curl -sf "http://127.0.0.1:$CAP_PORT/metrics")"
echo "$CAP_METRICS" | grep -qE '^audit_events 2$'
echo "$CAP_METRICS" | grep -qE '^audit_retained 2$'

cap_cleanup
CAP_PID=""
trap 'rotate_cleanup; log_cleanup; sd_cleanup; cleanup' EXIT
echo "audit-max isolated OK"

echo "==> [session-ttl] isolated Streamable HTTP session expiry (--session-ttl 1 then 0)"
TTL_PORT="${TTL_PORT:-8779}"
TTL_AUDIT="$ROOT/data/audit.session-ttl.jsonl"
TTL_LOG="$ROOT/data/server.session-ttl.log"
rm -f "$TTL_AUDIT" "$TTL_LOG"
node src/cli.js serve --port "$TTL_PORT" --config "$POLICY" --audit "$TTL_AUDIT" --session-ttl 1 --drain-ms 200 >"$TTL_LOG" 2>&1 &
TTL_PID=$!
ttl_cleanup() {
  if [ -n "${TTL_PID:-}" ] && kill -0 "$TTL_PID" 2>/dev/null; then
    kill "$TTL_PID" 2>/dev/null || true
    wait "$TTL_PID" 2>/dev/null || true
  fi
}
trap 'ttl_cleanup; cap_cleanup; rotate_cleanup; log_cleanup; sd_cleanup; cleanup' EXIT
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$TTL_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 50 ]; then
    echo "session-ttl serve did not become healthy"
    cat "$TTL_LOG" || true
    exit 1
  fi
  if ! kill -0 "$TTL_PID" 2>/dev/null; then
    echo "session-ttl serve exited early"
    cat "$TTL_LOG" || true
    exit 1
  fi
done

TTL_INIT="$(curl -s -o /tmp/b-ttl-init.json -D /tmp/b-ttl-init.h -w '%{http_code}' --max-time 2 \
  -X POST "http://127.0.0.1:$TTL_PORT/mcp" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"ttl"}}}')"
echo "ttl_init_status=$TTL_INIT"
test "$TTL_INIT" = "200"
TTL_SID="$(tr -d '\r' < /tmp/b-ttl-init.h | awk 'BEGIN{IGNORECASE=1} /^mcp-session-id:/{print $2; exit}')"
echo "ttl_session_id=$TTL_SID"
test -n "$TTL_SID"

TTL_GET="$(curl -s -o /tmp/b-ttl-get.json -D /tmp/b-ttl-get.h -w '%{http_code}' --max-time 2 "http://127.0.0.1:$TTL_PORT/mcp")"
test "$TTL_GET" = "405"
grep -qiE '^allow:.*DELETE' /tmp/b-ttl-get.h
grep -qiE '^allow:.*POST' /tmp/b-ttl-get.h

TTL_DEL_MISS="$(curl -s -o /tmp/b-ttl-del-miss.json -w '%{http_code}' --max-time 2 -X DELETE "http://127.0.0.1:$TTL_PORT/mcp")"
echo "ttl_delete_missing_status=$TTL_DEL_MISS"
test "$TTL_DEL_MISS" = "400"
grep -q '"error":"session_id_required"' /tmp/b-ttl-del-miss.json

TTL_DEL="$(curl -s -o /tmp/b-ttl-del -w '%{http_code}' --max-time 2 \
  -X DELETE "http://127.0.0.1:$TTL_PORT/mcp" -H "Mcp-Session-Id: $TTL_SID")"
echo "ttl_delete_status=$TTL_DEL"
test "$TTL_DEL" = "204"
test ! -s /tmp/b-ttl-del

TTL_DEL_POST="$(curl -s -o /tmp/b-ttl-del-post.json -w '%{http_code}' --max-time 2 \
  -X POST "http://127.0.0.1:$TTL_PORT/mcp" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -H "Mcp-Session-Id: $TTL_SID" \
  -d '{"jsonrpc":"2.0","id":9,"method":"tools/list","params":{}}')"
echo "ttl_post_after_delete_status=$TTL_DEL_POST body=$(cat /tmp/b-ttl-del-post.json)"
test "$TTL_DEL_POST" = "404"
grep -q '"error":"session_not_found"' /tmp/b-ttl-del-post.json

# Re-initialize so the existing TTL expiry proof still has a live session.
TTL_INIT="$(curl -s -o /tmp/b-ttl-init.json -D /tmp/b-ttl-init.h -w '%{http_code}' --max-time 2 \
  -X POST "http://127.0.0.1:$TTL_PORT/mcp" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -d '{"jsonrpc":"2.0","id":10,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"ttl"}}}')"
test "$TTL_INIT" = "200"
TTL_SID="$(tr -d '\r' < /tmp/b-ttl-init.h | awk 'BEGIN{IGNORECASE=1} /^mcp-session-id:/{print $2; exit}')"
echo "ttl_session_id_reinit=$TTL_SID"
test -n "$TTL_SID"

sleep 1.2

TTL_EXP="$(curl -s -o /tmp/b-ttl-exp.json -w '%{http_code}' --max-time 2 \
  -X POST "http://127.0.0.1:$TTL_PORT/mcp" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -H "Mcp-Session-Id: $TTL_SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}')"
echo "ttl_expired_status=$TTL_EXP body=$(cat /tmp/b-ttl-exp.json)"
test "$TTL_EXP" = "404"
grep -q '"error":"session_expired"' /tmp/b-ttl-exp.json

TTL_MISS="$(curl -s -o /tmp/b-ttl-miss.json -w '%{http_code}' --max-time 2 \
  -X POST "http://127.0.0.1:$TTL_PORT/mcp" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/list","params":{}}')"
echo "ttl_missing_status=$TTL_MISS"
test "$TTL_MISS" = "200"
grep -q '"name":"echo"' /tmp/b-ttl-miss.json

TTL_REST="$(curl -s -o /tmp/b-ttl-rest.json -w '%{http_code}' --max-time 2 \
  -X POST "http://127.0.0.1:$TTL_PORT/tools/list" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" -d '{}')"
echo "ttl_rest_status=$TTL_REST"
test "$TTL_REST" = "200"
grep -q '"tenantId":"acme"' /tmp/b-ttl-rest.json

ttl_cleanup
TTL_PID=""

TTL0_PORT="${TTL0_PORT:-8778}"
TTL0_AUDIT="$ROOT/data/audit.session-ttl0.jsonl"
TTL0_LOG="$ROOT/data/server.session-ttl0.log"
rm -f "$TTL0_AUDIT" "$TTL0_LOG"
node src/cli.js serve --port "$TTL0_PORT" --config "$POLICY" --audit "$TTL0_AUDIT" --session-ttl 0 --drain-ms 200 >"$TTL0_LOG" 2>&1 &
TTL_PID=$!
trap 'ttl_cleanup; cap_cleanup; rotate_cleanup; log_cleanup; sd_cleanup; cleanup' EXIT
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$TTL0_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 50 ]; then
    echo "session-ttl 0 serve did not become healthy"
    cat "$TTL0_LOG" || true
    exit 1
  fi
  if ! kill -0 "$TTL_PID" 2>/dev/null; then
    echo "session-ttl 0 serve exited early"
    cat "$TTL0_LOG" || true
    exit 1
  fi
done

TTL0_INIT="$(curl -s -o /tmp/b-ttl0-init.json -D /tmp/b-ttl0-init.h -w '%{http_code}' --max-time 2 \
  -X POST "http://127.0.0.1:$TTL0_PORT/mcp" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}')"
test "$TTL0_INIT" = "200"
TTL0_SID="$(tr -d '\r' < /tmp/b-ttl0-init.h | awk 'BEGIN{IGNORECASE=1} /^mcp-session-id:/{print $2; exit}')"
test -n "$TTL0_SID"
sleep 0.3
TTL0_LIVE="$(curl -s -o /tmp/b-ttl0-live.json -w '%{http_code}' --max-time 2 \
  -X POST "http://127.0.0.1:$TTL0_PORT/mcp" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -H "Mcp-Session-Id: $TTL0_SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}')"
echo "ttl0_live_status=$TTL0_LIVE"
test "$TTL0_LIVE" = "200"
grep -q '"name":"echo"' /tmp/b-ttl0-live.json

ttl_cleanup
TTL_PID=""
trap 'cap_cleanup; rotate_cleanup; log_cleanup; sd_cleanup; cleanup' EXIT
echo "session-ttl isolated OK"

echo "==> [admin-sessions] isolated GET /admin/sessions + DELETE /admin/sessions/{id} (401 / empty / init / DELETE / CORS OPTIONS)"
SESS_PORT="${SESS_PORT:-8777}"
SESS_AUDIT="$ROOT/data/audit.admin-sessions.jsonl"
SESS_LOG="$ROOT/data/server.admin-sessions.log"
rm -f "$SESS_AUDIT" "$SESS_LOG"
node src/cli.js serve --port "$SESS_PORT" --config "$POLICY" --audit "$SESS_AUDIT" --drain-ms 200 >"$SESS_LOG" 2>&1 &
SESS_PID=$!
sess_cleanup() {
  if [ -n "${SESS_PID:-}" ] && kill -0 "$SESS_PID" 2>/dev/null; then
    kill "$SESS_PID" 2>/dev/null || true
    wait "$SESS_PID" 2>/dev/null || true
  fi
}
trap 'sess_cleanup; ttl_cleanup; cap_cleanup; rotate_cleanup; log_cleanup; sd_cleanup; cleanup' EXIT
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$SESS_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 50 ]; then
    echo "admin-sessions serve did not become healthy"
    cat "$SESS_LOG" || true
    exit 1
  fi
  if ! kill -0 "$SESS_PID" 2>/dev/null; then
    echo "admin-sessions serve exited early"
    cat "$SESS_LOG" || true
    exit 1
  fi
done

ISO_UNAUTH="$(curl -s -o /tmp/b-iso-sess-unauth.json -w '%{http_code}' "http://127.0.0.1:$SESS_PORT/admin/sessions")"
echo "iso_admin_sessions_unauth=$ISO_UNAUTH"
test "$ISO_UNAUTH" = "401"
grep -q 'unauthorized_admin' /tmp/b-iso-sess-unauth.json
if grep -qE 'ten_acme_dev|admin-dev-token' /tmp/b-iso-sess-unauth.json; then
  echo "isolated admin/sessions 401 leaked secret"
  exit 1
fi

ISO_EMPTY="$(curl -sf "http://127.0.0.1:$SESS_PORT/admin/sessions" -H "X-Admin-Token: $ADMIN")"
echo "iso_admin_sessions_empty=$ISO_EMPTY"
echo "$ISO_EMPTY" | grep -q '"ok":true'
echo "$ISO_EMPTY" | grep -q '"count":0'
echo "$ISO_EMPTY" | grep -q '"sessions":\[\]'

ISO_CORS="$(curl -s -o /tmp/b-iso-sess-cors -D /tmp/b-iso-sess-cors.h -w '%{http_code}' \
  -X OPTIONS "http://127.0.0.1:$SESS_PORT/admin/sessions" \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: GET")"
echo "iso_admin_sessions_cors=$ISO_CORS"
test "$ISO_CORS" = "204"
grep -qiE '^access-control-allow-origin:[[:space:]]*http://localhost:3000' /tmp/b-iso-sess-cors.h

ISO_INIT="$(curl -s -o /tmp/b-iso-sess-init.json -D /tmp/b-iso-sess-init.h -w '%{http_code}' --max-time 2 \
  -X POST "http://127.0.0.1:$SESS_PORT/mcp" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}')"
test "$ISO_INIT" = "200"
ISO_SID="$(tr -d '\r' < /tmp/b-iso-sess-init.h | awk 'BEGIN{IGNORECASE=1} /^mcp-session-id:/{print $2; exit}')"
test -n "$ISO_SID"

ISO_ONE="$(curl -sf "http://127.0.0.1:$SESS_PORT/admin/sessions" -H "X-Admin-Token: $ADMIN")"
echo "$ISO_ONE" | grep -q '"ok":true'
echo "$ISO_ONE" | grep -q '"count":1'
echo "$ISO_ONE" | grep -q "$ISO_SID"

ISO_DEL="$(curl -s -o /tmp/b-iso-sess-del -w '%{http_code}' --max-time 2 \
  -X DELETE "http://127.0.0.1:$SESS_PORT/mcp" -H "Mcp-Session-Id: $ISO_SID")"
test "$ISO_DEL" = "204"

ISO_GONE="$(curl -sf "http://127.0.0.1:$SESS_PORT/admin/sessions" -H "X-Admin-Token: $ADMIN")"
echo "$ISO_GONE" | grep -q '"ok":true'
echo "$ISO_GONE" | grep -q '"count":0'
if echo "$ISO_GONE" | grep -q "$ISO_SID"; then
  echo "isolated admin/sessions still lists deleted id"
  echo "$ISO_GONE"
  exit 1
fi

ISO_INIT2="$(curl -s -o /tmp/b-iso-sess-init2.json -D /tmp/b-iso-sess-init2.h -w '%{http_code}' --max-time 2 \
  -X POST "http://127.0.0.1:$SESS_PORT/mcp" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -d '{"jsonrpc":"2.0","id":2,"method":"initialize","params":{}}')"
test "$ISO_INIT2" = "200"
ISO_SID2="$(tr -d '\r' < /tmp/b-iso-sess-init2.h | awk 'BEGIN{IGNORECASE=1} /^mcp-session-id:/{print $2; exit}')"
test -n "$ISO_SID2"

ISO_ADM_UNAUTH="$(curl -s -o /tmp/b-iso-adm-del-unauth.json -w '%{http_code}' --max-time 2 \
  -X DELETE "http://127.0.0.1:$SESS_PORT/admin/sessions/$ISO_SID2")"
echo "iso_admin_delete_unauth=$ISO_ADM_UNAUTH"
test "$ISO_ADM_UNAUTH" = "401"
grep -q 'unauthorized_admin' /tmp/b-iso-adm-del-unauth.json
if grep -qE 'ten_acme_dev|admin-dev-token' /tmp/b-iso-adm-del-unauth.json; then
  echo "isolated admin DELETE 401 leaked secret"
  exit 1
fi

ISO_ADM_CORS="$(curl -s -o /tmp/b-iso-adm-del-cors -D /tmp/b-iso-adm-del-cors.h -w '%{http_code}' \
  -X OPTIONS "http://127.0.0.1:$SESS_PORT/admin/sessions/$ISO_SID2" \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: DELETE")"
echo "iso_admin_delete_cors=$ISO_ADM_CORS"
test "$ISO_ADM_CORS" = "204"
grep -qiE '^access-control-allow-origin:[[:space:]]*http://localhost:3000' /tmp/b-iso-adm-del-cors.h
grep -qiE '^access-control-allow-methods:.*DELETE' /tmp/b-iso-adm-del-cors.h

ISO_ADM_OK="$(curl -s -o /tmp/b-iso-adm-del-ok -w '%{http_code}' --max-time 2 \
  -X DELETE "http://127.0.0.1:$SESS_PORT/admin/sessions/$ISO_SID2" -H "X-Admin-Token: $ADMIN")"
echo "iso_admin_delete_status=$ISO_ADM_OK"
test "$ISO_ADM_OK" = "204"
test ! -s /tmp/b-iso-adm-del-ok

ISO_ADM_POST="$(curl -s -o /tmp/b-iso-adm-del-post.json -w '%{http_code}' --max-time 2 \
  -X POST "http://127.0.0.1:$SESS_PORT/mcp" \
  -H 'content-type: application/json' -H "Authorization: Bearer $ACME_KEY" \
  -H "Mcp-Session-Id: $ISO_SID2" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/list","params":{}}')"
echo "iso_post_after_admin_delete=$ISO_ADM_POST"
test "$ISO_ADM_POST" = "404"
grep -q '"error":"session_not_found"' /tmp/b-iso-adm-del-post.json

ISO_ADM_AGAIN="$(curl -s -o /tmp/b-iso-adm-del-again.json -w '%{http_code}' --max-time 2 \
  -X DELETE "http://127.0.0.1:$SESS_PORT/admin/sessions/$ISO_SID2" -H "X-Admin-Token: $ADMIN")"
echo "iso_admin_delete_again=$ISO_ADM_AGAIN"
test "$ISO_ADM_AGAIN" = "404"
grep -q '"error":"session_not_found"' /tmp/b-iso-adm-del-again.json

ISO_ADM_UNKNOWN="$(curl -s -o /tmp/b-iso-adm-del-unknown.json -w '%{http_code}' --max-time 2 \
  -X DELETE "http://127.0.0.1:$SESS_PORT/admin/sessions/never-seen-admin-session" -H "X-Admin-Token: $ADMIN")"
echo "iso_admin_delete_unknown=$ISO_ADM_UNKNOWN"
test "$ISO_ADM_UNKNOWN" = "404"
grep -q '"error":"session_not_found"' /tmp/b-iso-adm-del-unknown.json

ISO_ADM_NOID="$(curl -s -o /tmp/b-iso-adm-del-noid.json -w '%{http_code}' --max-time 2 \
  -X DELETE "http://127.0.0.1:$SESS_PORT/admin/sessions" -H "X-Admin-Token: $ADMIN")"
echo "iso_admin_delete_missing_id=$ISO_ADM_NOID"
test "$ISO_ADM_NOID" = "404"

if grep -q "$ISO_SID2" "$SESS_AUDIT" 2>/dev/null; then
  echo "isolated admin DELETE dumped session id into audit"
  exit 1
fi
if ! grep -q 'session_deleted' "$SESS_AUDIT"; then
  echo "isolated admin DELETE missing session_deleted audit"
  cat "$SESS_AUDIT" || true
  exit 1
fi
grep -q '"via":"admin"' "$SESS_AUDIT"

sess_cleanup
SESS_PID=""
trap 'ttl_cleanup; cap_cleanup; rotate_cleanup; log_cleanup; sd_cleanup; cleanup' EXIT
echo "admin-sessions isolated OK"

echo "b-mcp-gateway local-mvp OK"

# stdio upstream prove (HTTP already covered above; generous timeoutMs)
node "$ROOT/scripts/stdio-mvp.mjs"
