#!/usr/bin/env bash
# Start B + mock-upstream + C + D + E + F without Docker; prove with curls; cleanup.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/out/stack-demo"
mkdir -p "$OUT" "$OUT/runs"
rm -f "$OUT"/*.pid "$OUT"/*.log "$OUT"/audit.jsonl "$OUT"/policy.local.json 2>/dev/null || true

GW_PORT="${GW_PORT:-8787}"
UP_PORT="${UP_PORT:-8788}"
CI_PORT="${CI_PORT:-8791}"
F_PORT="${F_PORT:-8790}"
E_PORT="${E_PORT:-8792}"
D_PORT="${D_PORT:-8793}"
ACME_KEY="ten_acme_dev"

PIDS=()
cleanup() {
  local pid
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  for pid in "${PIDS[@]:-}"; do
    wait "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT

echo "==> materialize local policy (tenants + upstream @ 127.0.0.1:${UP_PORT}; gateway loopback — ipAllowlist must allow 127.0.0.1)"
node --input-type=module -e '
import fs from "node:fs";
const src = process.argv[1];
const dst = process.argv[2];
const upPort = process.argv[3];
const p = JSON.parse(fs.readFileSync(src, "utf8"));
p.upstream = { type: "http", baseUrl: "http://127.0.0.1:" + upPort, timeoutMs: 30000, breaker: { enabled: false } };
fs.writeFileSync(dst, JSON.stringify(p, null, 2) + "\n");
' "$ROOT/bets/b-mcp-gateway/config/policy.compose.json" "$OUT/policy.local.json" "$UP_PORT"

echo "==> mock-upstream :${UP_PORT}"
(
  cd "$ROOT/bets/b-mcp-gateway"
  node mock-upstream.js --host 127.0.0.1 --port "$UP_PORT"
) >"$OUT/mock-upstream.log" 2>&1 &
PIDS+=($!)

echo "==> mcp-gateway :${GW_PORT}"
(
  cd "$ROOT/bets/b-mcp-gateway"
  node src/cli.js serve --host 127.0.0.1 --port "$GW_PORT" \
    --config "$OUT/policy.local.json" --audit "$OUT/gateway-audit.jsonl"
) >"$OUT/mcp-gateway.log" 2>&1 &
PIDS+=($!)

echo "==> agent-ci :${CI_PORT}"
(
  cd "$ROOT/bets/c-agent-ci"
  PYTHONPATH=src python3 -m agent_ci serve --host 127.0.0.1 --port "$CI_PORT" \
    --runs-dir "$OUT/runs"
) >"$OUT/agent-ci.log" 2>&1 &
PIDS+=($!)

echo "==> cn-work-agent :${F_PORT}"
(
  cd "$ROOT/bets/f-cn-work-agent"
  export FEISHU_VERIFY_TOKEN=mvp-token
  export FEISHU_ENCRYPT_KEY=mvp-encrypt
  export DINGTALK_TOKEN=mvp-dt-token
  export DINGTALK_SECRET=mvp-dt-secret
  export WECOM_TOKEN=mvp-wc-token
  PYTHONPATH=src python3 -m cn_work_agent serve --host 127.0.0.1 --port "$F_PORT" \
    --config config.example.json --audit "$OUT/cn-work-audit.jsonl"
) >"$OUT/cn-work-agent.log" 2>&1 &
PIDS+=($!)

echo "==> otel-ai-cost :${E_PORT}"
(
  cd "$ROOT/bets/e-otel-ai-cost"
  node src/cli.js serve --host 127.0.0.1 --port "$E_PORT" \
    --in examples/spans.json
) >"$OUT/otel-ai-cost.log" 2>&1 &
PIDS+=($!)

echo "==> ai-bom :${D_PORT}"
(
  cd "$ROOT/bets/d-ai-bom"
  PYTHONPATH=src python3 -m ai_bom serve --host 127.0.0.1 --port "$D_PORT" \
    --path examples/sample-app --policy policies/default.json
) >"$OUT/ai-bom.log" 2>&1 &
PIDS+=($!)

wait_health() {
  local name="$1" url="$2"
  local i
  for i in $(seq 1 80); do
    if curl -sf "$url" >/dev/null; then
      echo "ready $name $url"
      return 0
    fi
    sleep 0.15
  done
  echo "TIMEOUT waiting for $name ($url)" >&2
  echo "---- logs ----" >&2
  cat "$OUT/mock-upstream.log" >&2 || true
  cat "$OUT/mcp-gateway.log" >&2 || true
  cat "$OUT/agent-ci.log" >&2 || true
  cat "$OUT/cn-work-agent.log" >&2 || true
  cat "$OUT/otel-ai-cost.log" >&2 || true
  cat "$OUT/ai-bom.log" >&2 || true
  return 1
}

wait_health mock-upstream "http://127.0.0.1:${UP_PORT}/health"
wait_health mcp-gateway "http://127.0.0.1:${GW_PORT}/health"
wait_health agent-ci "http://127.0.0.1:${CI_PORT}/health"
wait_health cn-work-agent "http://127.0.0.1:${F_PORT}/health"
wait_health otel-ai-cost "http://127.0.0.1:${E_PORT}/health"
wait_health ai-bom "http://127.0.0.1:${D_PORT}/health"

echo "==> curl proofs"
UP_H="$(curl -sf "http://127.0.0.1:${UP_PORT}/health")"
echo "mock-upstream=$UP_H"
grep -q '"ok":true\|"ok": true' <<<"$UP_H"
grep -q mock-upstream <<<"$UP_H"

GW_H="$(curl -sf "http://127.0.0.1:${GW_PORT}/health")"
echo "mcp-gateway=$GW_H"
grep -q '"ok":true\|"ok": true' <<<"$GW_H"
grep -q mcp-gateway <<<"$GW_H"
grep -q acme <<<"$GW_H"
grep -q '"connected":true\|"connected": true' <<<"$GW_H"
grep -q upstreamPing <<<"$GW_H"
# breaker disabled in stack-demo — /ready stays 200 (compose healthcheck remains /health)
GW_R="$(curl -sf "http://127.0.0.1:${GW_PORT}/ready")"
echo "mcp-gateway-ready=$GW_R"
grep -q '"ok":true\|"ok": true' <<<"$GW_R"

# OpenAPI: rotate path present. Do not rotate the demo tenant (later curls use ACME_KEY).
GW_OA="$(curl -sf "http://127.0.0.1:${GW_PORT}/openapi.json")"
grep -q '"openapi"' <<<"$GW_OA"
grep -q '/admin/tenants/{tenantId}/rotate' <<<"$GW_OA"
grep -q 'adminRotateTenantToken' <<<"$GW_OA"
# Admin SIEM Markdown/HTML paths are documented; unauth HTML → 401 (do not send admin token).
grep -q '/admin/audit.md' <<<"$GW_OA"
grep -q 'getAdminAuditMd' <<<"$GW_OA"
grep -q '/admin/audit.csv' <<<"$GW_OA"
grep -q '/admin/audit.html' <<<"$GW_OA"
grep -q 'getAdminAuditHtml' <<<"$GW_OA"
grep -q 'format=html' <<<"$GW_OA"
GW_AUDIT_HTML_UNAUTH="$(curl -s -o /tmp/b-stack-audit-html.json -w '%{http_code}' --max-time 2 "http://127.0.0.1:${GW_PORT}/admin/audit.html")"
echo "mcp-gateway-admin-audit-html-unauth=$GW_AUDIT_HTML_UNAUTH $(cat /tmp/b-stack-audit-html.json)"
test "$GW_AUDIT_HTML_UNAUTH" = "401"
grep -q 'unauthorized_admin' /tmp/b-stack-audit-html.json
if grep -qE 'ten_acme_dev|admin-dev-token' /tmp/b-stack-audit-html.json; then
  echo "stack-demo /admin/audit.html 401 leaked secret"
  cat /tmp/b-stack-audit-html.json
  exit 1
fi
grep -q '/mcp' <<<"$GW_OA"
grep -q 'session_expired' <<<"$GW_OA"
grep -q 'mcpSessionDelete' <<<"$GW_OA"
grep -q 'session_id_required' <<<"$GW_OA"
grep -q 'session_not_found' <<<"$GW_OA"
grep -q '/admin/sessions' <<<"$GW_OA"
grep -q 'adminListSessions' <<<"$GW_OA"
grep -q '/admin/config' <<<"$GW_OA"
grep -q 'adminGetConfig' <<<"$GW_OA"
grep -q '/admin/tenants/{tenantId}' <<<"$GW_OA"
grep -q 'adminGetTenant' <<<"$GW_OA"
grep -q '/admin/sessions/{id}' <<<"$GW_OA"
grep -q 'adminDeleteSession' <<<"$GW_OA"
grep -q '/admin/webhooks' <<<"$GW_OA"
grep -q 'adminListWebhooks' <<<"$GW_OA"

# GET /admin/sessions without admin → 401 (do not send admin token; must not leak secrets)
GW_SESS_UNAUTH="$(curl -s -o /tmp/b-stack-sessions.json -w '%{http_code}' --max-time 2 "http://127.0.0.1:${GW_PORT}/admin/sessions")"
echo "mcp-gateway-admin-sessions-unauth=$GW_SESS_UNAUTH $(cat /tmp/b-stack-sessions.json)"
test "$GW_SESS_UNAUTH" = "401"
grep -q 'unauthorized_admin' /tmp/b-stack-sessions.json
if grep -qE 'ten_acme_dev|admin-dev-token' /tmp/b-stack-sessions.json; then
  echo "stack-demo /admin/sessions 401 leaked secret"
  cat /tmp/b-stack-sessions.json
  exit 1
fi

# GET /admin/config without admin → 401 (do not send admin token; must not leak secrets)
GW_CFG_UNAUTH="$(curl -s -o /tmp/b-stack-config.json -w '%{http_code}' --max-time 2 "http://127.0.0.1:${GW_PORT}/admin/config")"
echo "mcp-gateway-admin-config-unauth=$GW_CFG_UNAUTH $(cat /tmp/b-stack-config.json)"
test "$GW_CFG_UNAUTH" = "401"
grep -q 'unauthorized_admin' /tmp/b-stack-config.json
if grep -qE 'ten_acme_dev|admin-dev-token|sk-|Bearer' /tmp/b-stack-config.json; then
  echo "stack-demo /admin/config 401 leaked secret"
  cat /tmp/b-stack-config.json
  exit 1
fi

# GET /admin/tenants/{id} without admin → 401 (do not send admin token; must not leak secrets)
GW_TEN_UNAUTH="$(curl -s -o /tmp/b-stack-tenant.json -w '%{http_code}' --max-time 2 "http://127.0.0.1:${GW_PORT}/admin/tenants/acme")"
echo "mcp-gateway-admin-tenant-unauth=$GW_TEN_UNAUTH $(cat /tmp/b-stack-tenant.json)"
test "$GW_TEN_UNAUTH" = "401"
grep -q 'unauthorized_admin' /tmp/b-stack-tenant.json
if grep -qE 'ten_acme_dev|admin-dev-token|sk-|Bearer' /tmp/b-stack-tenant.json; then
  echo "stack-demo /admin/tenants/{id} 401 leaked secret"
  cat /tmp/b-stack-tenant.json
  exit 1
fi


# GET /admin/webhooks without admin → 401 (do not send admin token; must not leak secrets)
GW_HOOK_UNAUTH="$(curl -s -o /tmp/b-stack-webhooks.json -w '%{http_code}' --max-time 2 "http://127.0.0.1:${GW_PORT}/admin/webhooks")"
echo "mcp-gateway-admin-webhooks-unauth=$GW_HOOK_UNAUTH $(cat /tmp/b-stack-webhooks.json)"
test "$GW_HOOK_UNAUTH" = "401"
grep -q 'unauthorized_admin' /tmp/b-stack-webhooks.json
if grep -qE 'ten_acme_dev|admin-dev-token|sk-|Bearer|whsec_' /tmp/b-stack-webhooks.json; then
  echo "stack-demo /admin/webhooks 401 leaked secret"
  cat /tmp/b-stack-webhooks.json
  exit 1
fi

# DELETE /admin/sessions/{id} without admin → 401 (do not send admin token; dummy id; must not leak secrets)
GW_ADM_DEL_UNAUTH="$(curl -s -o /tmp/b-stack-admin-del.json -w '%{http_code}' --max-time 2 -X DELETE "http://127.0.0.1:${GW_PORT}/admin/sessions/00000000-0000-4000-8000-000000000000")"
echo "mcp-gateway-admin-delete-unauth=$GW_ADM_DEL_UNAUTH $(cat /tmp/b-stack-admin-del.json)"
test "$GW_ADM_DEL_UNAUTH" = "401"
grep -q 'unauthorized_admin' /tmp/b-stack-admin-del.json
if grep -qE 'ten_acme_dev|admin-dev-token|sk-|Bearer' /tmp/b-stack-admin-del.json; then
  echo "stack-demo DELETE /admin/sessions/{id} 401 leaked secret"
  cat /tmp/b-stack-admin-del.json
  exit 1
fi

# DELETE /mcp without session → 400 (session id is the capability; do not send tenant key)
GW_DEL_MISS="$(curl -s -o /tmp/b-stack-del-miss.json -w '%{http_code}' --max-time 2 -X DELETE "http://127.0.0.1:${GW_PORT}/mcp")"
echo "mcp-gateway-delete-missing=$GW_DEL_MISS $(cat /tmp/b-stack-del-miss.json)"
test "$GW_DEL_MISS" = "400"
grep -q '"error":"session_id_required"' /tmp/b-stack-del-miss.json

CI_H="$(curl -sf "http://127.0.0.1:${CI_PORT}/health")"
echo "agent-ci=$CI_H"
grep -q '"ok":true\|"ok": true\|"ok": true' <<<"$CI_H"
grep -q agent-ci <<<"$CI_H"
# queue empty in stack-demo — /ready stays 200 (compose healthcheck remains /health)
CI_R="$(curl -sf "http://127.0.0.1:${CI_PORT}/ready")"
echo "agent-ci-ready=$CI_R"
grep -q '"ok":true\|"ok": true' <<<"$CI_R"
CI_OA="$(curl -sf "http://127.0.0.1:${CI_PORT}/openapi.json")"
grep -q '"openapi"' <<<"$CI_OA"
grep -q '/ready' <<<"$CI_OA"
grep -q '/metrics' <<<"$CI_OA"
CI_M="$(curl -sf "http://127.0.0.1:${CI_PORT}/metrics")"
grep -q 'agent_ci_queue_depth' <<<"$CI_M"
grep -q 'agent_ci_running' <<<"$CI_M"
grep -q 'agent_ci_runs_completed_total' <<<"$CI_M"
grep -q 'agent_ci_runs_failed_total' <<<"$CI_M"
grep -q '/v1/runs/junit.xml' <<<"$CI_OA"
CI_JUNIT="$(curl -sf "http://127.0.0.1:${CI_PORT}/v1/runs/junit.xml")"
grep -q '<testsuite' <<<"$CI_JUNIT"
grep -q '/v1/runs/tap.txt' <<<"$CI_OA"
CI_TAP="$(curl -sf "http://127.0.0.1:${CI_PORT}/v1/runs/tap.txt")"
grep -q 'TAP version 13' <<<"$CI_TAP"
grep -q '1\.\.' <<<"$CI_TAP"
grep -q '/v1/runs/report.md' <<<"$CI_OA"
CI_MD="$(curl -sf "http://127.0.0.1:${CI_PORT}/v1/runs/report.md")"
grep -q '# ' <<<"$CI_MD"
grep -q '/v1/runs/report.html' <<<"$CI_OA"
grep -q 'getRunHtml' <<<"$CI_OA"
CI_HTML="$(curl -sf "http://127.0.0.1:${CI_PORT}/v1/runs/report.html")"
grep -q '<h1\|<table\|no runs' <<<"$CI_HTML"
grep -q '/v1/runs/annotations.txt' <<<"$CI_OA"
grep -q '/v1/runs/{id}/diff' <<<"$CI_OA"
grep -q 'getRunDiff' <<<"$CI_OA"
grep -q '/v1/runs/{id}/diff.md' <<<"$CI_OA"
grep -q 'getRunDiffMd' <<<"$CI_OA"
grep -q '/v1/runs/{id}/diff.html' <<<"$CI_OA"
grep -q 'getRunDiffHtml' <<<"$CI_OA"
grep -q '/v1/config' <<<"$CI_OA"
grep -q 'getConfig' <<<"$CI_OA"
grep -q '/v1/runs/{id}/cases' <<<"$CI_OA"
grep -q 'listRunCases' <<<"$CI_OA"
grep -q '/v1/suites/{name}' <<<"$CI_OA"
grep -q 'getSuite' <<<"$CI_OA"
grep -q 'SuiteDetail' <<<"$CI_OA"
CI_CASES_404="$(curl -s -o /tmp/c-stack-cases.json -w '%{http_code}' "http://127.0.0.1:${CI_PORT}/v1/runs/deadbeefdead/cases")"
echo "agent-ci-cases-404=$CI_CASES_404 $(cat /tmp/c-stack-cases.json)"
test "$CI_CASES_404" = "404"
grep -q 'run_not_found' /tmp/c-stack-cases.json
CI_SUITE_404="$(curl -s -o /tmp/c-stack-suite.json -w '%{http_code}' "http://127.0.0.1:${CI_PORT}/v1/suites/no-such-suite-xyz")"
echo "agent-ci-suite-404=$CI_SUITE_404 $(cat /tmp/c-stack-suite.json)"
test "$CI_SUITE_404" = "404"
grep -q 'suite_not_found' /tmp/c-stack-suite.json
CI_CFG="$(curl -sf "http://127.0.0.1:${CI_PORT}/v1/config")"
echo "agent-ci-config=$CI_CFG"
grep -q '"ok":true\|"ok": true' <<<"$CI_CFG"
grep -q 'queue\|cors\|rateLimit' <<<"$CI_CFG"
if grep -qE 'whsec_|AGENT_CI_WEBHOOK_SECRET|webhookUrl|webhookSecret' <<<"$CI_CFG"; then
  echo "stack-demo /v1/config leaked webhook secret/url key"
  echo "$CI_CFG"
  exit 1
fi
CI_ANN="$(curl -sf "http://127.0.0.1:${CI_PORT}/v1/runs/annotations.txt")"
# empty / no ::error is valid (no completed fails yet)
if grep -q '::error' <<<"$CI_ANN"; then
  echo "stack-demo empty annotations unexpectedly contain ::error"
  echo "$CI_ANN"
  exit 1
fi

F_H="$(curl -sf "http://127.0.0.1:${F_PORT}/health")"
echo "cn-work-agent=$F_H"
grep -q '"ok":true\|"ok": true' <<<"$F_H"
grep -q feishu <<<"$F_H"
# snapshot/stateless — /ready always 200 (compose healthcheck remains /health)
F_R="$(curl -sf "http://127.0.0.1:${F_PORT}/ready")"
echo "cn-work-agent-ready=$F_R"
grep -q '"ok":true\|"ok": true' <<<"$F_R"
F_OA="$(curl -sf "http://127.0.0.1:${F_PORT}/openapi.json")"
grep -q '"openapi"' <<<"$F_OA"
grep -q '/ready' <<<"$F_OA"
grep -q '/metrics' <<<"$F_OA"
grep -q '/v1/approvals.csv' <<<"$F_OA"
grep -q '/v1/approvals.md' <<<"$F_OA"
grep -q '/v1/approvals.html' <<<"$F_OA"
grep -q 'getApprovalsHtml' <<<"$F_OA"
grep -q 'format=html' <<<"$F_OA"
grep -q '/v1/approvals/{id}/card' <<<"$F_OA"
grep -q '/v1/platforms' <<<"$F_OA"
grep -q 'getPlatforms' <<<"$F_OA"
grep -q '/v1/config' <<<"$F_OA"
grep -q 'getConfig' <<<"$F_OA"
printf '%s' "$F_OA" > /tmp/f-stack-oa.json
python3 -c '
import json
from pathlib import Path
spec=json.loads(Path("/tmp/f-stack-oa.json").read_text())
params=((spec.get("paths") or {}).get("/v1/approvals") or {}).get("get") or {}
enums=[]
for p in params.get("parameters") or []:
    if p.get("name")=="status":
        enums=list((p.get("schema") or {}).get("enum") or [])
assert enums==["pending","approved","rejected","expired"], enums
print("stack-demo f approvals status query ok", enums)
'
F_PEND="$(curl -s -o /tmp/f-stack-pend.json -w '%{http_code}' "http://127.0.0.1:${F_PORT}/v1/approvals?status=pending")"
echo "cn-work-agent-approvals-pending=$F_PEND"
test "$F_PEND" = "200"
python3 -c '
import json
from pathlib import Path
d=json.loads(Path("/tmp/f-stack-pend.json").read_text())
assert d.get("ok") is True, d
assert isinstance(d.get("approvals"), list), d
assert d.get("count")==len(d.get("approvals") or []), d
print("stack-demo f approvals status=pending ok", {"count":d.get("count")})
'
F_PLAT="$(curl -sf "http://127.0.0.1:${F_PORT}/v1/platforms")"
echo "cn-work-agent-platforms=$F_PLAT"
grep -q '"ok":true\|"ok": true' <<<"$F_PLAT"
grep -q feishu <<<"$F_PLAT"
grep -q dingtalk <<<"$F_PLAT"
grep -q wecom <<<"$F_PLAT"
F_CFG="$(curl -sf "http://127.0.0.1:${F_PORT}/v1/config")"
echo "cn-work-agent-config=$F_CFG"
grep -q '"ok":true\|"ok": true' <<<"$F_CFG"
grep -q 'approvalTtlSec\|rateLimit\|approvalsMax\|platforms' <<<"$F_CFG"
F_CSV="$(curl -sf "http://127.0.0.1:${F_PORT}/v1/approvals.csv")"
F_MD="$(curl -sf "http://127.0.0.1:${F_PORT}/v1/approvals.md")"
F_HTML="$(curl -s -o /tmp/f-stack-appr.html -D /tmp/f-stack-appr-html.h -w '%{http_code}' "http://127.0.0.1:${F_PORT}/v1/approvals.html")"
echo "cn-work-agent-html=$F_HTML"
test "$F_HTML" = "200"
grep -qiE '^content-type:.*text/html' /tmp/f-stack-appr-html.h
grep -q '<h1\|<table\|no approvals' /tmp/f-stack-appr.html
F_CARD_404="$(curl -s -o /tmp/f-stack-card-404.json -w '%{http_code}' "http://127.0.0.1:${F_PORT}/v1/approvals/appr_missing/card?platform=feishu")"
echo "cn-work-agent-card-404=$F_CARD_404"
test "$F_CARD_404" = "404"
grep -q 'id,platform,status,createdAt,decidedAt,reason' <<<"$F_CSV"
grep -q '# ' <<<"$F_MD"
grep -q '|' <<<"$F_MD"
F_M="$(curl -sf "http://127.0.0.1:${F_PORT}/metrics")"
grep -q 'cn_work_agent_approvals_pending' <<<"$F_M"
grep -q 'cn_work_agent_approvals_decided_total' <<<"$F_M"
grep -q 'cn_work_agent_webhooks_total' <<<"$F_M"

E_H="$(curl -sf "http://127.0.0.1:${E_PORT}/health")"
echo "otel-ai-cost=$E_H"
grep -q '"ok":true\|"ok": true' <<<"$E_H"
grep -q otel-ai-cost <<<"$E_H"
# snapshot/stateless — /ready always 200 (compose healthcheck remains /health)
E_R="$(curl -sf "http://127.0.0.1:${E_PORT}/ready")"
echo "otel-ai-cost-ready=$E_R"
grep -q '"ok":true\|"ok": true' <<<"$E_R"
E_OA="$(curl -sf "http://127.0.0.1:${E_PORT}/openapi.json")"
grep -q '"openapi"' <<<"$E_OA"
grep -q '/ready' <<<"$E_OA"
grep -q '/report.json' <<<"$E_OA"
grep -q '/v1/costs.csv' <<<"$E_OA"
grep -q '/v1/costs.md' <<<"$E_OA"
grep -q '/v1/costs.gha.txt' <<<"$E_OA"
grep -q 'getCostsGha' <<<"$E_OA"
grep -q '/v1/budgets' <<<"$E_OA"
grep -q 'getBudgets' <<<"$E_OA"
grep -q '/v1/models' <<<"$E_OA"
grep -q 'getModels' <<<"$E_OA"
grep -q '/v1/config' <<<"$E_OA"
grep -q 'getConfig' <<<"$E_OA"
grep -q '/v1/spans' <<<"$E_OA"
grep -q 'listSpans' <<<"$E_OA"
grep -q '/v1/tenants' <<<"$E_OA"
grep -q 'listTenants' <<<"$E_OA"
grep -q '/metrics' <<<"$E_OA"
grep -q '/v1/traces' <<<"$E_OA"
E_CSV="$(curl -sf "http://127.0.0.1:${E_PORT}/v1/costs.csv")"
grep -q 'date,model,spanCount,usd' <<<"$E_CSV"
E_MD="$(curl -sf "http://127.0.0.1:${E_PORT}/v1/costs.md")"
grep -q '# ' <<<"$E_MD"
grep -q 'totalUsd' <<<"$E_MD"
E_GHA="$(curl -sf "http://127.0.0.1:${E_PORT}/v1/costs.gha.txt")"
if grep -q '::error' <<<"$E_GHA"; then
  echo "stack-demo E gha must be empty (no tenant/global budget)"
  echo "$E_GHA"
  exit 1
fi
E_BUDGETS="$(curl -s -o /tmp/e-stack-budgets.json -w '%{http_code}' "http://127.0.0.1:${E_PORT}/v1/budgets")"
echo "otel-ai-cost-budgets=$E_BUDGETS $(cat /tmp/e-stack-budgets.json)"
test "$E_BUDGETS" = "200"
grep -q '"ok":true\|"ok": true' /tmp/e-stack-budgets.json
grep -q '"globalUsd": null\|"globalUsd":null' /tmp/e-stack-budgets.json
grep -q '"tenants": {\|"tenants":{\|"tenants": {}\|"tenants":{}' /tmp/e-stack-budgets.json
python3 -c '
import json
d=json.load(open("/tmp/e-stack-budgets.json"))
assert d.get("ok") is True
assert d.get("globalUsd") is None
assert isinstance(d.get("tenants"), dict) and d["tenants"]=={}
assert "token" not in d and "secret" not in d
print("stack-demo empty budgets ok", d)
'
E_MODELS="$(curl -s -o /tmp/e-stack-models.json -w '%{http_code}' "http://127.0.0.1:${E_PORT}/v1/models")"
echo "otel-ai-cost-models=$E_MODELS $(cat /tmp/e-stack-models.json)"
test "$E_MODELS" = "200"
grep -q '"ok":true\|"ok": true' /tmp/e-stack-models.json
grep -q '"models"' /tmp/e-stack-models.json
python3 -c '
import json
d=json.load(open("/tmp/e-stack-models.json"))
assert d.get("ok") is True
assert isinstance(d.get("models"), list) and len(d["models"])>=1
ids=[m.get("id") for m in d["models"]]
assert any(i in ids for i in ("gpt-4o","gpt-4o-mini","claude-sonnet")), ids
assert "token" not in d and "secret" not in d
s=json.dumps(d)
assert "sk-" not in s
print("stack-demo models catalog ok", {"count":len(d["models"]),"ids":ids,"pack":d.get("pack")})
'
E_CFG="$(curl -s -o /tmp/e-stack-config.json -w '%{http_code}' "http://127.0.0.1:${E_PORT}/v1/config")"
echo "otel-ai-cost-config=$E_CFG $(cat /tmp/e-stack-config.json)"
test "$E_CFG" = "200"
grep -q '"ok":true\|"ok": true' /tmp/e-stack-config.json
python3 -c '
import json
d=json.load(open("/tmp/e-stack-config.json"))
assert d.get("ok") is True
assert d.get("spanCap") is not None or (d.get("cors") or {}).get("origins") is not None
assert "rateLimit" in d
assert "webhooks" in d
assert "hasUrl" in (d.get("webhooks") or {})
assert "hasSecret" in (d.get("webhooks") or {})
blob=json.dumps(d)
for n in ("webhookUrl","webhookSecret","webhook_url","webhook_secret","Authorization","sk-"):
    assert n not in blob, n
assert "token" not in d and "secret" not in d
print("stack-demo config ok", {"spanCap":d.get("spanCap"),"hasUrl":(d.get("webhooks") or {}).get("hasUrl")})
'
E_SPANS="$(curl -s -o /tmp/e-stack-spans.json -w '%{http_code}' "http://127.0.0.1:${E_PORT}/v1/spans")"
echo "otel-ai-cost-spans=$E_SPANS"
test "$E_SPANS" = "200"
grep -q '"ok":true\|"ok": true' /tmp/e-stack-spans.json
python3 -c '
import json
d=json.load(open("/tmp/e-stack-spans.json"))
assert d.get("ok") is True
assert isinstance(d.get("spans"), list)
assert isinstance(d.get("count"), int) and d["count"]>=0
assert d["count"]==0 or (d["spans"] and d["spans"][0].get("model"))
blob=json.dumps(d)
for n in ("SECRET_PROMPT","gen_ai.prompt","gen_ai.completion","Authorization","secret user question"):
    assert n not in blob, n
print("stack-demo spans ok", {"count":d.get("count"),"n":len(d.get("spans") or []),"truncated":d.get("truncated")})
'
E_TENANTS="$(curl -s -o /tmp/e-stack-tenants.json -w '%{http_code}' "http://127.0.0.1:${E_PORT}/v1/tenants")"
echo "otel-ai-cost-tenants=$E_TENANTS"
test "$E_TENANTS" = "200"
grep -q '"ok":true\|"ok": true' /tmp/e-stack-tenants.json
python3 -c '
import json
d=json.load(open("/tmp/e-stack-tenants.json"))
assert d.get("ok") is True
assert isinstance(d.get("tenants"), list)
assert isinstance(d.get("count"), int) and d["count"]>=0
assert d["count"]==0 or any((t.get("id") in ("acme","_")) and isinstance(t.get("usd"), (int,float)) for t in d["tenants"])
blob=json.dumps(d)
for n in ("SECRET_PROMPT","gen_ai.prompt","gen_ai.completion","Authorization","secret user question"):
    assert n not in blob, n
print("stack-demo tenants ok", {"count":d.get("count"),"n":len(d.get("tenants") or []),"truncated":d.get("truncated")})
'
E_M="$(curl -sf "http://127.0.0.1:${E_PORT}/metrics")"
grep -q 'otel_ai_cost_total_usd' <<<"$E_M"
grep -q 'otel_ai_cost_by_model_usd' <<<"$E_M"
grep -q 'otel_ai_cost_span_count' <<<"$E_M"

D_H="$(curl -sf "http://127.0.0.1:${D_PORT}/health")"
echo "ai-bom=$D_H"
grep -q '"ok":true\|"ok": true' <<<"$D_H"
grep -q ai-bom <<<"$D_H"
# snapshot/stateless — /ready always 200 (compose healthcheck remains /health)
D_R="$(curl -sf "http://127.0.0.1:${D_PORT}/ready")"
echo "ai-bom-ready=$D_R"
grep -q '"ok":true\|"ok": true' <<<"$D_R"
D_BOM="$(curl -sf "http://127.0.0.1:${D_PORT}/bom.json")"
grep -q MIT <<<"$D_BOM"
D_OA="$(curl -sf "http://127.0.0.1:${D_PORT}/openapi.json")"
grep -q '"openapi"' <<<"$D_OA"
grep -q '/ready' <<<"$D_OA"
grep -q '/bom.json' <<<"$D_OA"
grep -q '/metrics' <<<"$D_OA"
D_SARIF="$(curl -sf "http://127.0.0.1:${D_PORT}/v1/bom?format=sarif")"
grep -q '"version"' <<<"$D_SARIF"
grep -q '2.1.0' <<<"$D_SARIF"
grep -q '"runs"' <<<"$D_SARIF"
D_CDX_XML="$(curl -sf "http://127.0.0.1:${D_PORT}/v1/bom?format=cyclonedx-xml")"
grep -q '<bom' <<<"$D_CDX_XML"
grep -q 'cyclonedx.org/schema/bom/1.5' <<<"$D_CDX_XML"
D_SPDX_XML="$(curl -sf "http://127.0.0.1:${D_PORT}/v1/bom?format=spdx-xml")"
grep -q '<SpdxDocument' <<<"$D_SPDX_XML"
grep -q 'SPDX-2.3' <<<"$D_SPDX_XML"
D_MD="$(curl -sf "http://127.0.0.1:${D_PORT}/v1/bom.md")"
grep -q '# ' <<<"$D_MD"
grep -q 'policyHits' <<<"$D_MD"
grep -q '/v1/bom.md' <<<"$D_OA"
D_HTML="$(curl -s -o /tmp/d-stack-bom.html -D /tmp/d-stack-bom-html.h -w '%{http_code}' "http://127.0.0.1:${D_PORT}/v1/bom.html")"
echo "ai-bom-html=$D_HTML"
test "$D_HTML" = "200"
grep -qiE '^content-type:.*text/html' /tmp/d-stack-bom-html.h
grep -q '<table' /tmp/d-stack-bom.html
grep -q 'AI-BOM' /tmp/d-stack-bom.html
grep -q '/v1/bom.html' <<<"$D_OA"
grep -q 'getBomHtml' <<<"$D_OA"
grep -q 'format=html' <<<"$D_OA"
D_GHA="$(curl -sf "http://127.0.0.1:${D_PORT}/v1/bom?format=gha")"
grep -q '::error' <<<"$D_GHA"
grep -q '/v1/bom.gha.txt' <<<"$D_OA"
grep -q '/v1/policy' <<<"$D_OA"
D_POL="$(curl -sf "http://127.0.0.1:${D_PORT}/v1/policy")"
echo "ai-bom-policy=$D_POL"
grep -q '"ok":true\|"ok": true' <<<"$D_POL"
grep -q 'GPL-3.0' <<<"$D_POL"
grep -q 'forbiddenLicenseIds' <<<"$D_POL"
grep -q '/v1/config' <<<"$D_OA"
grep -q 'getConfig' <<<"$D_OA"
D_CFG="$(curl -s -o /tmp/d-stack-config.json -w '%{http_code}' "http://127.0.0.1:${D_PORT}/v1/config")"
echo "ai-bom-config=$D_CFG"
test "$D_CFG" = "200"
python3 -c '
import json
from pathlib import Path
d=json.loads(Path("/tmp/d-stack-config.json").read_text())
assert d.get("ok") is True, d
assert (d.get("cors") or {}).get("origins") is not None or "perMinute" in (d.get("rateLimit") or {}), d
assert "hasUrl" in (d.get("webhooks") or {}), d
assert "hasSecret" in (d.get("webhooks") or {}), d
blob=json.dumps(d)
assert "webhookUrl" not in blob and "webhookSecret" not in blob
assert "whsec_" not in blob
print("stack-demo d config ok", {"rateLimit":d.get("rateLimit"),"hasUrl":(d.get("webhooks") or {}).get("hasUrl")})
'
grep -q '/v1/components' <<<"$D_OA"
grep -q 'listComponents' <<<"$D_OA"
D_COMP="$(curl -s -o /tmp/d-stack-components.json -w '%{http_code}' "http://127.0.0.1:${D_PORT}/v1/components")"
echo "ai-bom-components=$D_COMP"
test "$D_COMP" = "200"
python3 -c '
import json
from pathlib import Path
d=json.loads(Path("/tmp/d-stack-components.json").read_text())
assert d.get("ok") is True, d
assert isinstance(d.get("count"), int) and d.get("count") == len(d.get("components") or []), d
names=[c.get("name") for c in (d.get("components") or [])]
assert "ai-bom-sample-app" in names or "gpt-4o-mini" in names, names
for c in d.get("components") or []:
    assert not str(c.get("path") or "").startswith("/"), c
print("stack-demo d components ok", {"count":d.get("count"),"names":names[:6]})
'
grep -q '/v1/exceptions' <<<"$D_OA"
grep -q 'listExceptions' <<<"$D_OA"
D_EXC="$(curl -s -o /tmp/d-stack-exceptions.json -w '%{http_code}' "http://127.0.0.1:${D_PORT}/v1/exceptions")"
echo "ai-bom-exceptions=$D_EXC"
test "$D_EXC" = "200"
python3 -c '
import json
from pathlib import Path
d=json.loads(Path("/tmp/d-stack-exceptions.json").read_text())
assert d.get("ok") is True, d
assert isinstance(d.get("count"), int), d
assert isinstance(d.get("exceptions"), list), d
blob=json.dumps(d)
assert "webhookUrl" not in blob and "webhookSecret" not in blob
assert "sk-" not in blob and "Authorization" not in blob
print("stack-demo d exceptions ok", {"count":d.get("count")})
'
D_M="$(curl -sf "http://127.0.0.1:${D_PORT}/metrics")"
grep -q 'ai_bom_component_count' <<<"$D_M"
grep -q 'ai_bom_policy_hits' <<<"$D_M"
grep -q 'ai_bom_forbidden_licenses' <<<"$D_M"

LIST="$(curl -sf -X POST "http://127.0.0.1:${GW_PORT}/tools/list" \
  -H 'content-type: application/json' \
  -H "Authorization: Bearer ${ACME_KEY}" \
  -d '{}')"
echo "tools/list=$LIST"
grep -q '"name":"echo"' <<<"$LIST"
grep -q '"name":"upstreamPing"' <<<"$LIST"
grep -q '"tenantId":"acme"' <<<"$LIST"

PROXY="$(curl -sf -X POST "http://127.0.0.1:${GW_PORT}/tools/call" \
  -H 'content-type: application/json' \
  -H "Authorization: Bearer ${ACME_KEY}" \
  -d '{"name":"upstreamPing","arguments":{"note":"stack-demo"}}')"
echo "tools/call upstreamPing=$PROXY"
grep -q '"via":"upstream"' <<<"$PROXY"
grep -q '"source":"mock-upstream"' <<<"$PROXY"
grep -q stack-demo <<<"$PROXY"

echo
echo "local-stack OK (ports gateway=${GW_PORT} upstream=${UP_PORT} agent-ci=${CI_PORT} cn-work=${F_PORT} otel-ai-cost=${E_PORT} ai-bom=${D_PORT})"
