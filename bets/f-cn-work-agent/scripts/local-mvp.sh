#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH=src
PORT="${PORT:-8790}"
AUDIT="$ROOT/data/audit.jsonl"
rm -f "$AUDIT"
mkdir -p "$ROOT/data"

python3 -m cn_work_agent smoke

echo "==> config.example.json"
test -f config.example.json
python3 -c "import json; from pathlib import Path; from cn_work_agent.cli import _load_serve_config; cfg=json.loads(Path('config.example.json').read_text()); assert cfg.get('platforms'); _load_serve_config('config.example.json'); print('config.example.json ok', ','.join(cfg['platforms']))"


export FEISHU_VERIFY_TOKEN="mvp-token"
export FEISHU_ENCRYPT_KEY="mvp-encrypt"
export DINGTALK_TOKEN="mvp-dt-token"
export DINGTALK_SECRET="mvp-dt-secret"
export WECOM_TOKEN="mvp-wc-token"
# Default deny CORS / no outbound approval webhook on main serve.
unset CORS_ORIGINS || true
unset APPROVAL_WEBHOOK_URL || true
unset APPROVAL_WEBHOOK_SECRET || true
unset FEISHU_CALLBACK_SECRET || true
unset DINGTALK_CALLBACK_SECRET || true
unset WECOM_CALLBACK_SECRET || true
unset APPROVAL_CALLBACK_SECRET || true
unset APPROVALS_MAX || true

python3 -m cn_work_agent serve --port "$PORT" --audit "$AUDIT" >"$ROOT/data/server.log" 2>&1 &
PID=$!
RL_PID=""
TTL_PID=""
CORS_PID=""
WH_PID=""
WH_SERVE_PID=""
HMAC_PID=""
HMAC_WH_PID=""
WATCH_PID=""
CB_PID=""
CAP_PID=""
cleanup() {
  if [[ -n "${RL_PID:-}" ]]; then kill "$RL_PID" 2>/dev/null || true; wait "$RL_PID" 2>/dev/null || true; fi
  if [[ -n "${TTL_PID:-}" ]]; then kill "$TTL_PID" 2>/dev/null || true; wait "$TTL_PID" 2>/dev/null || true; fi
  if [[ -n "${CORS_PID:-}" ]]; then kill "$CORS_PID" 2>/dev/null || true; wait "$CORS_PID" 2>/dev/null || true; fi
  if [[ -n "${WH_PID:-}" ]]; then kill "$WH_PID" 2>/dev/null || true; wait "$WH_PID" 2>/dev/null || true; fi
  if [[ -n "${WH_SERVE_PID:-}" ]]; then kill "$WH_SERVE_PID" 2>/dev/null || true; wait "$WH_SERVE_PID" 2>/dev/null || true; fi
  if [[ -n "${HMAC_PID:-}" ]]; then kill "$HMAC_PID" 2>/dev/null || true; wait "$HMAC_PID" 2>/dev/null || true; fi
  if [[ -n "${HMAC_WH_PID:-}" ]]; then kill "$HMAC_WH_PID" 2>/dev/null || true; wait "$HMAC_WH_PID" 2>/dev/null || true; fi
  if [[ -n "${WATCH_PID:-}" ]]; then kill "$WATCH_PID" 2>/dev/null || true; wait "$WATCH_PID" 2>/dev/null || true; fi
  if [[ -n "${CB_PID:-}" ]]; then kill "$CB_PID" 2>/dev/null || true; wait "$CB_PID" 2>/dev/null || true; fi
  if [[ -n "${CAP_PID:-}" ]]; then kill "$CAP_PID" 2>/dev/null || true; wait "$CAP_PID" 2>/dev/null || true; fi
  kill "$PID" 2>/dev/null || true
  wait "$PID" 2>/dev/null || true
}
trap cleanup EXIT

for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
done

HEALTH="$(curl -sf "http://127.0.0.1:$PORT/health")"
echo "health=$HEALTH"
echo "$HEALTH" | grep -q '"ok": true\|"ok":true'
echo "$HEALTH" | grep -q feishu
echo "$HEALTH" | grep -q dingtalk
echo "$HEALTH" | grep -q wecom
echo "$HEALTH" | grep -q enabled

echo "==> GET /ready (always 200 {ok:true, service} — stateless, no circuit/queue)"
READY="$(curl -s -o /tmp/f-ready.json -D /tmp/f-ready.h -w '%{http_code}' "http://127.0.0.1:$PORT/ready")"
echo "ready_status=$READY body=$(cat /tmp/f-ready.json)"
test "$READY" = "200"
grep -Eq '"ok"[[:space:]]*:[[:space:]]*true' /tmp/f-ready.json
grep -q cn-work-agent /tmp/f-ready.json
grep -qiE '^x-request-id:' /tmp/f-ready.h
RID_READY="mvp-ready-rid-f1"
curl -s -o /tmp/f-ready-custom.json -D /tmp/f-ready-custom.h \
  "http://127.0.0.1:$PORT/ready" -H "X-Request-Id: $RID_READY" >/dev/null
grep -qiE "^x-request-id:[[:space:]]*${RID_READY}" /tmp/f-ready-custom.h
echo "ready_ok"

echo "==> GET /v1/platforms (ids, no secrets)"
PLAT_CODE="$(curl -s -o /tmp/f-platforms.json -D /tmp/f-platforms.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/v1/platforms" -H "X-Request-Id: mvp-platforms-rid")"
echo "platforms_status=$PLAT_CODE body=$(cat /tmp/f-platforms.json)"
test "$PLAT_CODE" = "200"
grep -qiE "^x-request-id:[[:space:]]*mvp-platforms-rid" /tmp/f-platforms.h
python3 - <<'PYPLAT'
import json
from pathlib import Path
body = json.loads(Path("/tmp/f-platforms.json").read_text(encoding="utf-8"))
assert body.get("ok") is True, body
plats = body.get("platforms") or []
ids = [p.get("id") for p in plats]
assert "feishu" in ids and "dingtalk" in ids and "wecom" in ids, ids
blob = json.dumps(body)
for needle in (
    "mvp-token",
    "mvp-encrypt",
    "mvp-dt-token",
    "mvp-dt-secret",
    "mvp-wc-token",
    "callbackSecret",
    "encrypt_key",
    "verify_token",
):
    assert needle not in blob, needle
print("platforms_ok", ids)
PYPLAT
echo "platforms_ok"

echo "==> GET /v1/config (redacted; no secrets)"
CFG_CODE="$(curl -s -o /tmp/f-config.json -D /tmp/f-config.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/v1/config" -H "X-Request-Id: mvp-config-rid")"
echo "config_status=$CFG_CODE body=$(cat /tmp/f-config.json)"
test "$CFG_CODE" = "200"
grep -qiE "^x-request-id:[[:space:]]*mvp-config-rid" /tmp/f-config.h
python3 - <<'PYCFG'
import json
from pathlib import Path
body = json.loads(Path("/tmp/f-config.json").read_text(encoding="utf-8"))
assert body.get("ok") is True, body
plats = body.get("platforms") or []
ids = [p.get("id") for p in plats]
ttl = body.get("approvalTtlSec")
assert ids or ttl is not None, body
assert "rateLimit" in body and "cors" in body and "approvalsMax" in body, body
assert "webhooks" in body, body
assert "hasUrl" in (body.get("webhooks") or {}), body
assert "hasSecret" in (body.get("webhooks") or {}), body
blob = json.dumps(body)
for needle in (
    "mvp-token",
    "mvp-encrypt",
    "mvp-dt-token",
    "mvp-dt-secret",
    "mvp-wc-token",
    "callbackSecret",
    "encrypt_key",
    "verify_token",
    "FEISHU_VERIFY_TOKEN",
    "APPROVAL_WEBHOOK_SECRET",
    "Authorization",
):
    assert needle not in blob, needle
print("config_ok", ids, "ttl", ttl, "approvalsMax", body.get("approvalsMax"))
PYCFG
echo "config_ok"

echo "==> X-Request-Id omitted → generated UUID echoed on every response"
curl -s -o /tmp/f-health-rid.json -D /tmp/f-health-rid.h "http://127.0.0.1:$PORT/health" >/dev/null
grep -qiE '^x-request-id:' /tmp/f-health-rid.h
GEN_RID="$(tr -d '\r' < /tmp/f-health-rid.h | awk 'tolower($0) ~ /^x-request-id:/{print $2; exit}')"
echo "generated_request_id=$GEN_RID"
echo "$GEN_RID" | grep -qE '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
echo "request_id_generated_ok"

echo "==> X-Request-Id custom id echoed on /health"
RID_HEALTH="mvp-health-rid-f1"
curl -s -o /tmp/f-health-custom.json -D /tmp/f-health-custom.h \
  "http://127.0.0.1:$PORT/health" -H "X-Request-Id: $RID_HEALTH" >/dev/null
grep -qiE "^x-request-id:[[:space:]]*${RID_HEALTH}" /tmp/f-health-custom.h
echo "request_id_health_custom_ok"

echo "==> GET /openapi.json (file-backed spec)"
mkdir -p "$ROOT/data"
curl -s -o "$ROOT/data/openapi.json" -D "$ROOT/data/openapi.h" "http://127.0.0.1:$PORT/openapi.json"
test -s "$ROOT/data/openapi.json"
grep -q '"openapi"' "$ROOT/data/openapi.json"
grep -qiE '^x-request-id:' "$ROOT/data/openapi.h"
python3 - <<'OPENAPI_PY'
import json
from pathlib import Path
spec = json.loads(Path("data/openapi.json").read_text(encoding="utf-8"))
assert str(spec.get("openapi") or "").startswith("3."), spec.get("openapi")
paths = spec.get("paths") or {}
need = [
    "/health",
    "/ready",
    "/metrics",
    "/webhook/feishu",
    "/webhook/dingtalk",
    "/webhook/wecom",
    "/approvals",
    "/approvals/{id}",
    "/approvals/{id}/decide",
    "/v1/approvals.csv",
    "/v1/approvals.md",
    "/v1/approvals.html",
    "/v1/approvals",
    "/v1/approvals/{id}/card",
    "/v1/platforms",
    "/v1/config",
]
missing = [p for p in need if p not in paths]
assert not missing, missing
assert "get" in (paths.get("/health") or {})
assert "get" in (paths.get("/ready") or {})
assert ((paths.get("/ready") or {}).get("get") or {}).get("operationId") == "getReady"
assert "get" in (paths.get("/metrics") or {})
assert ((paths.get("/metrics") or {}).get("get") or {}).get("operationId") == "getMetrics"
assert "post" in (paths.get("/webhook/feishu") or {})
assert "post" in (paths.get("/webhook/dingtalk") or {})
assert "get" in (paths.get("/webhook/wecom") or {}) and "post" in (paths.get("/webhook/wecom") or {})
assert "get" in (paths.get("/approvals") or {})
assert "get" in (paths.get("/approvals/{id}") or {})
assert "post" in (paths.get("/approvals/{id}/decide") or {})
assert "get" in (paths.get("/approvals/{id}/decide") or {})
assert "401" in (((paths.get("/approvals/{id}/decide") or {}).get("post") or {}).get("responses") or {})
assert ((paths.get("/v1/approvals.csv") or {}).get("get") or {}).get("operationId") == "getApprovalsCsv"
assert ((paths.get("/v1/approvals.md") or {}).get("get") or {}).get("operationId") == "getApprovalsMd"
assert ((paths.get("/v1/approvals.html") or {}).get("get") or {}).get("operationId") == "getApprovalsHtml"
assert ((paths.get("/v1/approvals") or {}).get("get") or {}).get("operationId") == "getApprovals"
assert ((paths.get("/v1/approvals/{id}/card") or {}).get("get") or {}).get("operationId") == "getApprovalCard"
assert ((paths.get("/v1/platforms") or {}).get("get") or {}).get("operationId") == "getPlatforms"
assert ((paths.get("/v1/config") or {}).get("get") or {}).get("operationId") == "getConfig"
schemas = (spec.get("components") or {}).get("schemas") or {}
assert "RuntimeConfig" in schemas, sorted(schemas)
for path in ("/webhook/feishu", "/webhook/dingtalk", "/webhook/wecom"):
    post = ((paths.get(path) or {}).get("post") or {}).get("responses") or {}
    for code in ("401", "429"):
        assert code in post, (path, code, sorted(post))
    assert "403" in post, (path, "403 CORS", sorted(post))
get_wc = ((paths.get("/webhook/wecom") or {}).get("get") or {}).get("responses") or {}
assert "401" in get_wc and "429" in get_wc, get_wc
params = (spec.get("components") or {}).get("parameters") or {}
headers = (spec.get("components") or {}).get("headers") or {}
responses = (spec.get("components") or {}).get("responses") or {}
assert "XRequestId" in params, params
assert "XRequestId" in headers, headers
assert "CorsDenied" in responses, responses
desc = str((spec.get("info") or {}).get("description") or "")
assert "X-Request-Id" in desc or "requestId" in desc, "missing X-Request-Id note"
assert "401" in desc and "429" in desc and ("403" in desc or "cors_denied" in desc)
assert "GET /metrics" in desc, "missing GET /metrics note"
assert "cn_work_agent_approvals_pending" in desc, "missing pending metric note"
assert "cn_work_agent_approvals_decided_total" in desc, "missing decided metric note"
assert "APPROVAL_WEBHOOK_URL" in desc or "webhook-url" in desc, "missing webhook note"
assert "APPROVAL_WEBHOOK_SECRET" in desc or "webhook-secret" in desc, "missing webhook secret note"
assert "X-Webhook-Signature" in desc, "missing HMAC signature note"
assert "X-Webhook-Timestamp" in desc, "missing webhook timestamp note"
assert "X-Callback-Signature" in desc, "missing inbound callback signature note"
assert "X-Callback-Timestamp" in desc, "missing inbound callback timestamp note"
assert "callbackSecret" in desc, "missing callbackSecret note"
assert "--watch" in desc, "missing serve --watch note"
assert "APPROVALS_MAX" in desc or "approvals-max" in desc or "--approvals-max" in desc, "missing approvals-max note"
assert "GET /v1/config" in desc, "missing GET /v1/config note"
schemas = (spec.get("components") or {}).get("schemas") or {}
assert "ApprovalDecisionWebhook" in schemas, sorted(schemas)
assert "RuntimeConfig" in schemas, sorted(schemas)

def _status_enum(path):
    for prm in (((paths.get(path) or {}).get("get") or {}).get("parameters") or []):
        if prm.get("name") == "status":
            return list((prm.get("schema") or {}).get("enum") or [])
    return []

want_status = ["pending", "approved", "rejected", "expired"]
assert _status_enum("/v1/approvals") == want_status, _status_enum("/v1/approvals")
assert _status_enum("/v1/approvals.csv") == want_status, _status_enum("/v1/approvals.csv")
print("openapi_paths_ok", len(paths))
OPENAPI_PY

echo "==> default deny CORS (main serve has no CORS_ORIGINS / --cors-origins)"
DEF_GET="$(curl -s -o /tmp/f-def-cors.json -D /tmp/f-def-cors.h -w "%{http_code}" \
  "http://127.0.0.1:$PORT/health" -H "Origin: http://localhost:3000")"
echo "default_cors_get_status=$DEF_GET"
test "$DEF_GET" = "200"
if grep -qiE "^access-control-allow-origin:" /tmp/f-def-cors.h; then
  echo "default serve must not send ACAO"
  cat /tmp/f-def-cors.h
  exit 1
fi
DEF_OPT="$(curl -s -o /tmp/f-def-opt.json -D /tmp/f-def-opt.h -w "%{http_code}" \
  -X OPTIONS "http://127.0.0.1:$PORT/health" -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: GET" \
  -H "X-Request-Id: mvp-opt-rid-404")"
echo "default_cors_options_status=$DEF_OPT"
test "$DEF_OPT" = "404"
if grep -qiE "^access-control-allow-origin:" /tmp/f-def-opt.h; then
  echo "default OPTIONS must not send ACAO"
  cat /tmp/f-def-opt.h
  exit 1
fi
grep -qiE "^x-request-id:[[:space:]]*mvp-opt-rid-404" /tmp/f-def-opt.h

# ---------- rate limit (isolated server; keep main auth/approvals at default limit) ----------
RL_PORT="${RL_PORT:-$((PORT + 17))}"
RL_AUDIT="$ROOT/data/rl-audit.jsonl"
rm -f "$RL_AUDIT"
echo "==> [rate-limit] isolated serve on :$RL_PORT with RATE_LIMIT_PER_MINUTE=2"
RATE_LIMIT_PER_MINUTE=2 \
  FEISHU_VERIFY_TOKEN="$FEISHU_VERIFY_TOKEN" \
  FEISHU_ENCRYPT_KEY="$FEISHU_ENCRYPT_KEY" \
  DINGTALK_TOKEN="$DINGTALK_TOKEN" \
  DINGTALK_SECRET="$DINGTALK_SECRET" \
  WECOM_TOKEN="$WECOM_TOKEN" \
  python3 -m cn_work_agent serve --port "$RL_PORT" --audit "$RL_AUDIT" >"$ROOT/data/rl-server.log" 2>&1 &
RL_PID=$!
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$RL_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
done
RL_HEALTH="$(curl -sf "http://127.0.0.1:$RL_PORT/health")"
echo "rl_health=$RL_HEALTH"
echo "$RL_HEALTH" | grep -q '"ok": true\|"ok":true'
echo "$RL_HEALTH" | grep -Eq '"rate_limit_per_minute"[[:space:]]*:[[:space:]]*2'

# First two hits under limit (401 without auth still counts toward window)
for i in 1 2; do
  CODE="$(curl -s -o "/tmp/f-rl-$i.json" -w '%{http_code}' -X POST "http://127.0.0.1:$RL_PORT/webhook/feishu" \
    -H 'content-type: application/json' \
    -d '{"text":"ping","token":"wrong"}')"
  echo "rl_hit_$i status=$CODE body=$(cat /tmp/f-rl-$i.json)"
  test "$CODE" = "401"
done

RL_HEADERS="$(mktemp)"
RL_BODY="/tmp/f-rl-429.json"
RL_CODE="$(curl -s -D "$RL_HEADERS" -o "$RL_BODY" -w '%{http_code}' -X POST "http://127.0.0.1:$RL_PORT/webhook/feishu" \
  -H 'content-type: application/json' \
  -H "X-Request-Id: mvp-rl-rid-429" \
  -d '{"text":"ping","token":"wrong"}')"
echo "rl_hit_3 status=$RL_CODE body=$(cat "$RL_BODY")"
echo "rl_headers:"; cat "$RL_HEADERS"
test "$RL_CODE" = "429"
grep -qi '^Retry-After:' "$RL_HEADERS"
grep -qiE '^x-request-id:[[:space:]]*mvp-rl-rid-429' "$RL_HEADERS"
grep -Eq '"error"[[:space:]]*:[[:space:]]*"rate_limited"' "$RL_BODY"
grep -Eq '"limit"[[:space:]]*:[[:space:]]*2' "$RL_BODY"
test -f "$RL_AUDIT"
grep -q 'rate_limited' "$RL_AUDIT"
kill "$RL_PID" 2>/dev/null || true
wait "$RL_PID" 2>/dev/null || true
RL_PID=""
rm -f "$RL_HEADERS"
echo "==> [rate-limit] 429 + Retry-After OK (isolated); main server unchanged for auth/approvals"

# ---------- Feishu ----------
echo "==> [feishu] bad token -> 401"
printf '%s' '{"type":"url_verification","challenge":"nope","token":"wrong"}' > /tmp/f-bad-token-body.json
BAD_TOKEN="$(curl -s -o /tmp/f-bad-token.json -D /tmp/f-bad-token.h -w '%{http_code}' -X POST "http://127.0.0.1:$PORT/webhook/feishu" \
  -H 'content-type: application/json' \
  -H "X-Request-Id: mvp-4xx-rid-401" \
  --data-binary @/tmp/f-bad-token-body.json)"
echo "feishu_bad_token_status=$BAD_TOKEN body=$(cat /tmp/f-bad-token.json)"
test "$BAD_TOKEN" = "401"
grep -qiE '^x-request-id:[[:space:]]*mvp-4xx-rid-401' /tmp/f-bad-token.h

echo "==> [feishu] good token + signature"
printf '%s' '{"type":"url_verification","challenge":"tok-xyz","token":"mvp-token"}' > /tmp/f-good-chal.json
export FEISHU_TS=1710000000 FEISHU_NONCE=nonce-mvp
mapfile -t SIG_LINES < <(python3 scripts/sign_feishu.py "$(cat /tmp/f-good-chal.json)")
TS="${SIG_LINES[0]}"
NONCE="${SIG_LINES[1]}"
SIG="${SIG_LINES[2]}"
CH="$(curl -sf -X POST "http://127.0.0.1:$PORT/webhook/feishu" \
  -H 'content-type: application/json' \
  -H "X-Lark-Request-Timestamp: $TS" \
  -H "X-Lark-Request-Nonce: $NONCE" \
  -H "X-Lark-Signature: $SIG" \
  --data-binary @/tmp/f-good-chal.json)"
echo "feishu_challenge=$CH"
echo "$CH" | grep -q tok-xyz

printf '%s' '{"text":"digest hello-mvp","token":"mvp-token"}' > /tmp/f-good-msg.json
export FEISHU_TS=1710000001 FEISHU_NONCE=nonce-mvp-2
mapfile -t SIG_LINES2 < <(python3 scripts/sign_feishu.py "$(cat /tmp/f-good-msg.json)")
TS2="${SIG_LINES2[0]}"
NONCE2="${SIG_LINES2[1]}"
SIG2="${SIG_LINES2[2]}"
RESP="$(curl -sf -X POST "http://127.0.0.1:$PORT/webhook/feishu" \
  -H 'content-type: application/json' \
  -H "X-Lark-Request-Timestamp: $TS2" \
  -H "X-Lark-Request-Nonce: $NONCE2" \
  -H "X-Lark-Signature: $SIG2" \
  --data-binary @/tmp/f-good-msg.json)"
echo "feishu_resp=$RESP"
echo "$RESP" | grep -q ack
echo "$RESP" | grep -q digest=
echo "$RESP" | grep -q feishu

# ---------- DingTalk ----------
echo "==> [dingtalk] bad token -> 401"
printf '%s' '{"text":{"content":"ping"},"token":"wrong"}' > /tmp/f-dt-bad.json
BAD_DT="$(curl -s -o /tmp/f-dt-bad-out.json -w '%{http_code}' -X POST "http://127.0.0.1:$PORT/webhook/dingtalk" \
  -H 'content-type: application/json' \
  --data-binary @/tmp/f-dt-bad.json)"
echo "dingtalk_bad_status=$BAD_DT body=$(cat /tmp/f-dt-bad-out.json)"
test "$BAD_DT" = "401"

echo "==> [dingtalk] good token + sign"
printf '%s' '{"text":{"content":"digest hello-dt"},"token":"mvp-dt-token"}' > /tmp/f-dt-good.json
export DINGTALK_TS=1710000100
mapfile -t DT_LINES < <(python3 scripts/sign_dingtalk.py)
DT_TS="${DT_LINES[0]}"
DT_SIG="${DT_LINES[1]}"
DT_RESP="$(curl -sf -X POST "http://127.0.0.1:$PORT/webhook/dingtalk" \
  -H 'content-type: application/json' \
  -H "X-DingTalk-Timestamp: $DT_TS" \
  -H "X-DingTalk-Sign: $DT_SIG" \
  --data-binary @/tmp/f-dt-good.json)"
echo "dingtalk_resp=$DT_RESP"
echo "$DT_RESP" | grep -q ack
echo "$DT_RESP" | grep -q digest=
echo "$DT_RESP" | grep -q dingtalk
echo "$DT_RESP" | grep -q '"msgtype": "text\|"msgtype":"text'

# ---------- WeCom ----------
echo "==> [wecom] bad signature -> 401"
BAD_WC="$(curl -s -o /tmp/f-wc-bad-out.json -w '%{http_code}' \
  "http://127.0.0.1:$PORT/webhook/wecom?msg_signature=deadbeef&timestamp=1710000200&nonce=wnonce&echostr=echo-nope")"
echo "wecom_bad_status=$BAD_WC body=$(cat /tmp/f-wc-bad-out.json)"
test "$BAD_WC" = "401"

echo "==> [wecom] good URL verification (echostr)"
export WECOM_TS=1710000200 WECOM_NONCE=wnonce-mvp
mapfile -t WC_LINES < <(python3 scripts/sign_wecom.py "echo-mvp-ok")
WC_TS="${WC_LINES[0]}"
WC_NONCE="${WC_LINES[1]}"
WC_SIG="${WC_LINES[2]}"
WC_ECHO="$(curl -sf \
  "http://127.0.0.1:$PORT/webhook/wecom?msg_signature=${WC_SIG}&timestamp=${WC_TS}&nonce=${WC_NONCE}&echostr=echo-mvp-ok")"
echo "wecom_echo=$WC_ECHO"
test "$WC_ECHO" = "echo-mvp-ok"

echo "==> [wecom] good message POST"
printf '%s' '{"Content":"digest hello-wc"}' > /tmp/f-wc-msg.json
BODY_WC="$(cat /tmp/f-wc-msg.json)"
export WECOM_TS=1710000201 WECOM_NONCE=wnonce-mvp-2
mapfile -t WC_LINES2 < <(python3 scripts/sign_wecom.py "$BODY_WC")
WC_TS2="${WC_LINES2[0]}"
WC_NONCE2="${WC_LINES2[1]}"
WC_SIG2="${WC_LINES2[2]}"
WC_RESP="$(curl -sf -X POST \
  "http://127.0.0.1:$PORT/webhook/wecom?msg_signature=${WC_SIG2}&timestamp=${WC_TS2}&nonce=${WC_NONCE2}" \
  -H 'content-type: application/json' \
  --data-binary @/tmp/f-wc-msg.json)"
echo "wecom_resp=$WC_RESP"
echo "$WC_RESP" | grep -q ack
echo "$WC_RESP" | grep -q digest=
echo "$WC_RESP" | grep -q wecom

# ---------- simple approval flow ----------
APPROVALS="$ROOT/data/approvals.jsonl"
rm -f "$APPROVALS"
echo "==> [approval] feishu message creates pending approval"
printf '%s' '{"text":"请审批采购申请 laptop","token":"mvp-token"}' > /tmp/f-appr-msg.json
export FEISHU_TS=1710000300 FEISHU_NONCE=nonce-appr
mapfile -t SIG_APPR < <(python3 scripts/sign_feishu.py "$(cat /tmp/f-appr-msg.json)")
RID_APPR="mvp-appr-rid-a1b2"
APPR_RESP="$(curl -sf -D /tmp/f-appr.h -X POST "http://127.0.0.1:$PORT/webhook/feishu"   -H 'content-type: application/json'   -H "X-Lark-Request-Timestamp: ${SIG_APPR[0]}"   -H "X-Lark-Request-Nonce: ${SIG_APPR[1]}"   -H "X-Lark-Signature: ${SIG_APPR[2]}"   -H "X-Request-Id: $RID_APPR"   --data-binary @/tmp/f-appr-msg.json)"
echo "approval_create_resp=$APPR_RESP"
echo "$APPR_RESP" | grep -q '"intent": "approval\|"intent":"approval'
echo "$APPR_RESP" | grep -q approval_id
echo "$APPR_RESP" | grep -q decide_hint
echo "$APPR_RESP" | grep -q pending
grep -qiE "^x-request-id:[[:space:]]*${RID_APPR}" /tmp/f-appr.h
APPR_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["approval_id"])' <<<"$APPR_RESP")"
echo "approval_id=$APPR_ID"
test -n "$APPR_ID"
test -f "$APPROVALS"
grep -q "$APPR_ID" "$APPROVALS"
grep -q pending "$APPROVALS"
python3 -c 'import json,sys; from pathlib import Path; rid=sys.argv[1]; aid=sys.argv[2]; rows=[json.loads(l) for l in Path(sys.argv[3]).read_text().splitlines() if l.strip()]; rec=next(r for r in rows if r.get("id")==aid); assert rec.get("requestId")==rid, rec; print("approval_stored_requestId_ok")' "$RID_APPR" "$APPR_ID" "$APPROVALS"
grep -q "$RID_APPR" "$AUDIT"

echo "==> [approval] GET /v1/approvals/{id}/card?platform=feishu"
CARD_CODE="$(curl -s -o /tmp/f-appr-card.json -D /tmp/f-appr-card.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/v1/approvals/${APPR_ID}/card?platform=feishu")"
echo "approval_card_status=$CARD_CODE body=$(cat /tmp/f-appr-card.json)"
test "$CARD_CODE" = "200"
grep -qiE '^content-type:[[:space:]]*application/json' /tmp/f-appr-card.h
python3 - <<'PYCARD'
import json
from pathlib import Path
card = json.loads(Path("/tmp/f-appr-card.json").read_text(encoding="utf-8"))
assert isinstance(card, dict) and card, card
inner = card.get("card") if isinstance(card.get("card"), dict) else card
assert "header" in inner or "elements" in inner or "msg_type" in card, card
blob = json.dumps(card)
assert "sk-" not in blob
print("approval_card_ok", sorted(card)[:6])
PYCARD
echo "approval_card_ok"

echo "==> [approval] GET /approvals lists pending"
LIST="$(curl -sf "http://127.0.0.1:$PORT/approvals")"
echo "approvals_list=$LIST"
echo "$LIST" | grep -q "$APPR_ID"
echo "$LIST" | grep -q pending
echo "$LIST" | grep -q "$RID_APPR"

echo "==> [approval] GET /v1/approvals?status=pending (after create)"
PEND_CODE="$(curl -s -o /tmp/f-appr-pend.json -w '%{http_code}' "http://127.0.0.1:$PORT/v1/approvals?status=pending")"
echo "approvals_status_pending=$PEND_CODE body=$(cat /tmp/f-appr-pend.json)"
test "$PEND_CODE" = "200"
grep -q "$APPR_ID" /tmp/f-appr-pend.json
grep -q pending /tmp/f-appr-pend.json

echo "==> GET /metrics (Prometheus text; pending after create)"
curl -s -o "$ROOT/data/metrics-pending.txt" -D "$ROOT/data/metrics-pending.h"   "http://127.0.0.1:$PORT/metrics" -H "X-Request-Id: mvp-metrics-rid-pending"
test -s "$ROOT/data/metrics-pending.txt"
grep -qiE "^x-request-id:[[:space:]]*mvp-metrics-rid-pending" "$ROOT/data/metrics-pending.h"
grep -q 'cn_work_agent_approvals_pending' "$ROOT/data/metrics-pending.txt"
grep -q 'cn_work_agent_approvals_decided_total' "$ROOT/data/metrics-pending.txt"
grep -q 'cn_work_agent_webhooks_total' "$ROOT/data/metrics-pending.txt"
python3 - <<'PYMETRICS_PENDING'
from pathlib import Path
text = Path("data/metrics-pending.txt").read_text(encoding="utf-8")
vals = {}
for line in text.splitlines():
    if not line or line.startswith("#"):
        continue
    parts = line.split()
    if len(parts) >= 2 and "{" not in parts[0]:
        vals[parts[0]] = float(parts[1])
assert "cn_work_agent_approvals_pending" in vals, text
assert "cn_work_agent_approvals_decided_total" in vals, text
assert "cn_work_agent_webhooks_total" in vals, text
assert vals["cn_work_agent_approvals_pending"] >= 1, vals
print("metrics_pending_ok", vals)
PYMETRICS_PENDING
echo "metrics_pending_ok"

echo "==> [approval] POST decide approve"
DECIDE="$(curl -sf -X POST "http://127.0.0.1:$PORT/approvals/${APPR_ID}/decide"   -H 'content-type: application/json'   -d '{"decision":"approve","note":"mvp-ok"}')"
echo "approval_decide=$DECIDE"
echo "$DECIDE" | grep -q '"ok": true\|"ok":true'
echo "$DECIDE" | grep -q approved
grep -q approved "$APPROVALS"
grep -q 'approval_decide' "$AUDIT"
grep -q "$APPR_ID" "$AUDIT"

echo "==> [approval] GET /v1/approvals?status= after decide"
PEND2_CODE="$(curl -s -o /tmp/f-appr-pend2.json -w '%{http_code}' "http://127.0.0.1:$PORT/v1/approvals?status=pending")"
echo "approvals_status_pending_after=$PEND2_CODE body=$(cat /tmp/f-appr-pend2.json)"
test "$PEND2_CODE" = "200"
if grep -q "$APPR_ID" /tmp/f-appr-pend2.json; then
  echo "decided id still listed under ?status=pending"
  exit 1
fi
OK_CODE="$(curl -s -o /tmp/f-appr-ok.json -w '%{http_code}' "http://127.0.0.1:$PORT/v1/approvals?status=approved")"
echo "approvals_status_approved=$OK_CODE body=$(cat /tmp/f-appr-ok.json)"
test "$OK_CODE" = "200"
grep -q "$APPR_ID" /tmp/f-appr-ok.json
UNK_CODE="$(curl -s -o /tmp/f-appr-unk.json -w '%{http_code}' "http://127.0.0.1:$PORT/v1/approvals?status=nope")"
echo "approvals_status_unknown=$UNK_CODE body=$(cat /tmp/f-appr-unk.json)"
test "$UNK_CODE" = "200"
python3 -c 'import json; d=json.load(open("/tmp/f-appr-unk.json")); assert d.get("ok") is True and d.get("count")==0 and d.get("approvals")==[], d'

echo "==> [approval] GET /v1/approvals.csv (audit CSV after decide)"
CSV_CODE="$(curl -s -o /tmp/f-appr.csv -D /tmp/f-appr-csv.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/v1/approvals.csv" -H "X-Request-Id: mvp-csv-rid-f1")"
echo "approvals_csv_status=$CSV_CODE"
test "$CSV_CODE" = "200"
grep -qiE '^content-type:[[:space:]]*text/csv' /tmp/f-appr-csv.h
grep -qiE '^x-request-id:[[:space:]]*mvp-csv-rid-f1' /tmp/f-appr-csv.h
head -n 1 /tmp/f-appr.csv | grep -qx 'id,platform,status,createdAt,decidedAt,reason'
grep -q "$APPR_ID" /tmp/f-appr.csv
grep -q approved /tmp/f-appr.csv
CSV_Q="$(curl -sf "http://127.0.0.1:$PORT/v1/approvals?format=csv")"
echo "$CSV_Q" | grep -q 'id,platform,status,createdAt,decidedAt,reason'
echo "$CSV_Q" | grep -q "$APPR_ID"
CSV_JSON="$(curl -sf "http://127.0.0.1:$PORT/v1/approvals")"
echo "$CSV_JSON" | grep -q "$APPR_ID"
CSV_BAD="$(curl -s -o /tmp/f-appr-csv-bad.json -w '%{http_code}' "http://127.0.0.1:$PORT/v1/approvals?format=nope")"
echo "approvals_csv_bad_status=$CSV_BAD body=$(cat /tmp/f-appr-csv-bad.json)"
test "$CSV_BAD" = "400"
grep -q bad_format /tmp/f-appr-csv-bad.json
EXPORT_CSV="$(python3 -m cn_work_agent export --approvals "$APPROVALS" --format csv)"
grep -q 'id,platform,status,createdAt,decidedAt,reason' <<<"$EXPORT_CSV"
grep -q "$APPR_ID" <<<"$EXPORT_CSV"
echo "approvals_csv_ok"

echo "==> [approval] GET /v1/approvals.md (Markdown after decide)"
MD_CODE="$(curl -s -o /tmp/f-appr.md -D /tmp/f-appr-md.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/v1/approvals.md" -H "X-Request-Id: mvp-md-rid-f1")"
echo "approvals_md_status=$MD_CODE"
test "$MD_CODE" = "200"
grep -qiE '^content-type:[[:space:]]*text/markdown' /tmp/f-appr-md.h
grep -qiE '^x-request-id:[[:space:]]*mvp-md-rid-f1' /tmp/f-appr-md.h
grep -q '^# ' /tmp/f-appr.md
grep -q '|' /tmp/f-appr.md
grep -q "$APPR_ID" /tmp/f-appr.md
grep -q approved /tmp/f-appr.md
MD_Q="$(curl -sf "http://127.0.0.1:$PORT/v1/approvals?format=md")"
echo "$MD_Q" | grep -q '^# '
echo "$MD_Q" | grep -q "$APPR_ID"
EXPORT_MD="$(python3 -m cn_work_agent export --approvals "$APPROVALS" --format md)"
grep -q '^# ' <<<"$EXPORT_MD"
grep -q "$APPR_ID" <<<"$EXPORT_MD"
echo "approvals_md_ok"

echo "==> [approval] GET /v1/approvals.html (HTML after create+decide)"
HTML_CODE="$(curl -s -o /tmp/f-appr.html -D /tmp/f-appr-html.h -w '%{http_code}' \
  "http://127.0.0.1:$PORT/v1/approvals.html" -H "X-Request-Id: mvp-html-rid-f1")"
echo "approvals_html_status=$HTML_CODE"
test "$HTML_CODE" = "200"
grep -qiE '^content-type:[[:space:]]*text/html' /tmp/f-appr-html.h
grep -qiE '^x-request-id:[[:space:]]*mvp-html-rid-f1' /tmp/f-appr-html.h
grep -q '<table' /tmp/f-appr.html
grep -q '<h1' /tmp/f-appr.html
grep -q "$APPR_ID" /tmp/f-appr.html
grep -q approved /tmp/f-appr.html
HTML_Q="$(curl -sf "http://127.0.0.1:$PORT/v1/approvals?format=html")"
echo "$HTML_Q" | grep -q '<table'
echo "$HTML_Q" | grep -q "$APPR_ID"
EXPORT_HTML="$(python3 -m cn_work_agent export --approvals "$APPROVALS" --format html)"
grep -q '<table' <<<"$EXPORT_HTML"
grep -q "$APPR_ID" <<<"$EXPORT_HTML"
echo "approvals_html_ok"

echo "==> GET /metrics (Prometheus text; decided after approve)"
curl -s -o "$ROOT/data/metrics.txt" -D "$ROOT/data/metrics.h"   "http://127.0.0.1:$PORT/metrics" -H "X-Request-Id: mvp-metrics-rid"
test -s "$ROOT/data/metrics.txt"
grep -qiE "^x-request-id:[[:space:]]*mvp-metrics-rid" "$ROOT/data/metrics.h"
grep -q 'cn_work_agent_approvals_pending' "$ROOT/data/metrics.txt"
grep -q 'cn_work_agent_approvals_decided_total' "$ROOT/data/metrics.txt"
grep -q 'cn_work_agent_webhooks_total' "$ROOT/data/metrics.txt"
python3 - <<'PYMETRICS'
from pathlib import Path
text = Path("data/metrics.txt").read_text(encoding="utf-8")
vals = {}
for line in text.splitlines():
    if not line or line.startswith("#"):
        continue
    parts = line.split()
    if len(parts) >= 2 and "{" not in parts[0]:
        vals[parts[0]] = float(parts[1])
assert "cn_work_agent_approvals_pending" in vals, text
assert "cn_work_agent_approvals_decided_total" in vals, text
assert "cn_work_agent_webhooks_total" in vals, text
assert vals["cn_work_agent_approvals_decided_total"] >= 1, vals
print("metrics_names_ok", vals)
PYMETRICS
echo "metrics_names_ok"

# ---------- approval TTL expiry (isolated serve; keep main approvals at default TTL) ----------
TTL_PORT="${TTL_PORT:-$((PORT + 18))}"
TTL_AUDIT="$ROOT/data/ttl-audit.jsonl"
TTL_APPROVALS="$ROOT/data/ttl-approvals.jsonl"
rm -f "$TTL_AUDIT" "$TTL_APPROVALS"
echo "==> [approval-ttl] isolated serve on :$TTL_PORT with APPROVAL_TTL_SECONDS=1"
APPROVAL_TTL_SECONDS=1 \
  FEISHU_VERIFY_TOKEN="$FEISHU_VERIFY_TOKEN" \
  FEISHU_ENCRYPT_KEY="$FEISHU_ENCRYPT_KEY" \
  DINGTALK_TOKEN="$DINGTALK_TOKEN" \
  DINGTALK_SECRET="$DINGTALK_SECRET" \
  WECOM_TOKEN="$WECOM_TOKEN" \
  python3 -m cn_work_agent serve --port "$TTL_PORT" --audit "$TTL_AUDIT" --approvals "$TTL_APPROVALS" >"$ROOT/data/ttl-server.log" 2>&1 &
TTL_PID=$!
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$TTL_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
done
TTL_HEALTH="$(curl -sf "http://127.0.0.1:$TTL_PORT/health")"
echo "ttl_health=$TTL_HEALTH"
echo "$TTL_HEALTH" | grep -q '"ok": true\|"ok":true'
echo "$TTL_HEALTH" | grep -Eq '"approval_ttl_seconds"[[:space:]]*:[[:space:]]*1'

printf '%s' '{"text":"请审批 TTL expiry test","token":"mvp-token"}' > /tmp/f-ttl-appr.json
export FEISHU_TS=1710000400 FEISHU_NONCE=nonce-ttl
mapfile -t SIG_TTL < <(python3 scripts/sign_feishu.py "$(cat /tmp/f-ttl-appr.json)")
TTL_CREATE="$(curl -sf -X POST "http://127.0.0.1:$TTL_PORT/webhook/feishu" \
  -H 'content-type: application/json' \
  -H "X-Lark-Request-Timestamp: ${SIG_TTL[0]}" \
  -H "X-Lark-Request-Nonce: ${SIG_TTL[1]}" \
  -H "X-Lark-Signature: ${SIG_TTL[2]}" \
  --data-binary @/tmp/f-ttl-appr.json)"
echo "ttl_create=$TTL_CREATE"
TTL_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["approval_id"])' <<<"$TTL_CREATE")"
echo "ttl_approval_id=$TTL_ID"
test -n "$TTL_ID"
echo "==> [approval-ttl] sleep 2s for expiry"
sleep 2
TTL_LIST="$(curl -sf "http://127.0.0.1:$TTL_PORT/approvals")"
echo "ttl_list=$TTL_LIST"
echo "$TTL_LIST" | grep -q "$TTL_ID"
echo "$TTL_LIST" | grep -q rejected
echo "$TTL_LIST" | grep -q expired
TTL_GET="$(curl -sf "http://127.0.0.1:$TTL_PORT/approvals/${TTL_ID}")"
echo "ttl_get=$TTL_GET"
echo "$TTL_GET" | grep -q rejected
echo "$TTL_GET" | grep -q expired
TTL_DECIDE_CODE="$(curl -s -o /tmp/f-ttl-decide.json -w '%{http_code}' -X POST "http://127.0.0.1:$TTL_PORT/approvals/${TTL_ID}/decide" \
  -H 'content-type: application/json' \
  -d '{"decision":"approve","note":"too-late"}')"
echo "ttl_decide_status=$TTL_DECIDE_CODE body=$(cat /tmp/f-ttl-decide.json)"
test "$TTL_DECIDE_CODE" = "400"
grep -Eq 'expired|not pending' /tmp/f-ttl-decide.json
grep -q '"status": "rejected"\|"status":"rejected"' "$TTL_APPROVALS" || grep -q rejected "$TTL_APPROVALS"
grep -q expired "$TTL_APPROVALS"
kill "$TTL_PID" 2>/dev/null || true
wait "$TTL_PID" 2>/dev/null || true
TTL_PID=""
echo "==> [approval-ttl] expire→rejected/expired + cannot approve OK (isolated)"

# ---------- CORS (isolated serve; keep main webhook/auth/approvals/rate-limit default deny) ----------
CORS_PORT="${CORS_PORT:-$((PORT + 19))}"
CORS_AUDIT="$ROOT/data/cors-audit.jsonl"
rm -f "$CORS_AUDIT"
echo "==> [cors] isolated serve on :$CORS_PORT with CORS_ORIGINS=http://localhost:3000"
CORS_ORIGINS="http://localhost:3000" \
  FEISHU_VERIFY_TOKEN="$FEISHU_VERIFY_TOKEN" \
  FEISHU_ENCRYPT_KEY="$FEISHU_ENCRYPT_KEY" \
  DINGTALK_TOKEN="$DINGTALK_TOKEN" \
  DINGTALK_SECRET="$DINGTALK_SECRET" \
  WECOM_TOKEN="$WECOM_TOKEN" \
  python3 -m cn_work_agent serve --port "$CORS_PORT" --audit "$CORS_AUDIT" >"$ROOT/data/cors-server.log" 2>&1 &
CORS_PID=$!
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$CORS_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
done
CORS_HEALTH="$(curl -sf "http://127.0.0.1:$CORS_PORT/health")"
echo "cors_health=$CORS_HEALTH"
echo "$CORS_HEALTH" | grep -q '"ok": true\|"ok":true'

CORS_OK="$(curl -s -o /tmp/f-cors-ok -D /tmp/f-cors-ok.h -w "%{http_code}" \
  -X OPTIONS "http://127.0.0.1:$CORS_PORT/health" \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: GET" \
  -H "X-Request-Id: mvp-cors-opt-204")"
echo "cors_preflight_ok_status=$CORS_OK"
test "$CORS_OK" = "204"
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" /tmp/f-cors-ok.h
grep -qiE "^access-control-allow-methods:" /tmp/f-cors-ok.h
grep -qiE "^access-control-allow-headers:" /tmp/f-cors-ok.h
grep -qiE "^access-control-allow-headers:.*x-request-id" /tmp/f-cors-ok.h
grep -qiE "^access-control-expose-headers:.*retry-after" /tmp/f-cors-ok.h
grep -qiE "^access-control-expose-headers:.*x-request-id" /tmp/f-cors-ok.h
grep -qiE "^x-request-id:[[:space:]]*mvp-cors-opt-204" /tmp/f-cors-ok.h

CORS_POST_PF="$(curl -s -o /tmp/f-cors-post -D /tmp/f-cors-post.h -w "%{http_code}" \
  -X OPTIONS "http://127.0.0.1:$CORS_PORT/webhook/feishu" \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type,x-lark-signature,x-request-id")"
echo "cors_preflight_post_status=$CORS_POST_PF"
test "$CORS_POST_PF" = "204"
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" /tmp/f-cors-post.h
grep -qiE "^access-control-expose-headers:.*retry-after" /tmp/f-cors-post.h
grep -qiE "^access-control-expose-headers:.*x-request-id" /tmp/f-cors-post.h

CORS_EVIL="$(curl -s -o /tmp/f-cors-evil.json -D /tmp/f-cors-evil.h -w "%{http_code}" \
  -X OPTIONS "http://127.0.0.1:$CORS_PORT/health" \
  -H "Origin: http://evil.example" \
  -H "Access-Control-Request-Method: GET" \
  -H "X-Request-Id: mvp-cors-opt-403")"
echo "cors_preflight_evil_status=$CORS_EVIL body=$(cat /tmp/f-cors-evil.json)"
test "$CORS_EVIL" = "403"
grep -q "cors_denied" /tmp/f-cors-evil.json
if grep -qiE "^access-control-allow-origin:[[:space:]]*http://evil.example" /tmp/f-cors-evil.h; then
  echo "evil origin must not receive ACAO"
  exit 1
fi
if grep -qiE "^access-control-expose-headers:" /tmp/f-cors-evil.h; then
  echo "evil origin must not receive ACEH"
  exit 1
fi
grep -qiE "^x-request-id:[[:space:]]*mvp-cors-opt-403" /tmp/f-cors-evil.h

HEALTH_CORS="$(curl -s -o /tmp/f-health-cors.json -D /tmp/f-health-cors.h -w "%{http_code}" \
  "http://127.0.0.1:$CORS_PORT/health" -H "Origin: http://localhost:3000")"
echo "cors_get_health_status=$HEALTH_CORS"
test "$HEALTH_CORS" = "200"
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" /tmp/f-health-cors.h
grep -qiE "^access-control-expose-headers:.*retry-after" /tmp/f-health-cors.h
grep -qiE "^access-control-expose-headers:.*x-request-id" /tmp/f-health-cors.h
grep -qiE "^x-request-id:" /tmp/f-health-cors.h

OPENAPI_CORS="$(curl -s -o /tmp/f-openapi-cors.json -D /tmp/f-openapi-cors.h -w "%{http_code}" \
  "http://127.0.0.1:$CORS_PORT/openapi.json" -H "Origin: http://localhost:3000")"
echo "cors_get_openapi_status=$OPENAPI_CORS"
test "$OPENAPI_CORS" = "200"
grep -q '"openapi"' /tmp/f-openapi-cors.json
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" /tmp/f-openapi-cors.h
grep -qiE "^x-request-id:" /tmp/f-openapi-cors.h

APPR_CORS="$(curl -s -o /tmp/f-appr-cors.json -D /tmp/f-appr-cors.h -w "%{http_code}" \
  "http://127.0.0.1:$CORS_PORT/approvals" -H "Origin: http://localhost:3000")"
echo "cors_get_approvals_status=$APPR_CORS"
test "$APPR_CORS" = "200"
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" /tmp/f-appr-cors.h

CSV_CORS="$(curl -s -o /tmp/f-csv-cors.csv -D /tmp/f-csv-cors.h -w "%{http_code}" \
  "http://127.0.0.1:$CORS_PORT/v1/approvals.csv" -H "Origin: http://localhost:3000" -H "X-Request-Id: mvp-cors-csv-rid")"
echo "cors_get_approvals_csv_status=$CSV_CORS"
test "$CSV_CORS" = "200"
grep -q 'id,platform,status,createdAt,decidedAt,reason' /tmp/f-csv-cors.csv
grep -qiE "^content-type:[[:space:]]*text/csv" /tmp/f-csv-cors.h
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" /tmp/f-csv-cors.h
grep -qiE "^x-request-id:[[:space:]]*mvp-cors-csv-rid" /tmp/f-csv-cors.h

MD_CORS="$(curl -s -o /tmp/f-md-cors.md -D /tmp/f-md-cors.h -w "%{http_code}" \
  "http://127.0.0.1:$CORS_PORT/v1/approvals.md" -H "Origin: http://localhost:3000" -H "X-Request-Id: mvp-cors-md-rid")"
echo "cors_get_approvals_md_status=$MD_CORS"
test "$MD_CORS" = "200"
grep -q '^# ' /tmp/f-md-cors.md
grep -qiE "^content-type:[[:space:]]*text/markdown" /tmp/f-md-cors.h
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" /tmp/f-md-cors.h
grep -qiE "^x-request-id:[[:space:]]*mvp-cors-md-rid" /tmp/f-md-cors.h

HTML_CORS="$(curl -s -o /tmp/f-html-cors.html -D /tmp/f-html-cors.h -w "%{http_code}" \
  "http://127.0.0.1:$CORS_PORT/v1/approvals.html" -H "Origin: http://localhost:3000" -H "X-Request-Id: mvp-cors-html-rid")"
echo "cors_get_approvals_html_status=$HTML_CORS"
test "$HTML_CORS" = "200"
grep -q '<table\|<h1\|no approvals' /tmp/f-html-cors.html
grep -qiE "^content-type:[[:space:]]*text/html" /tmp/f-html-cors.h
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" /tmp/f-html-cors.h
grep -qiE "^x-request-id:[[:space:]]*mvp-cors-html-rid" /tmp/f-html-cors.h

METRICS_CORS="$(curl -s -o /tmp/f-metrics-cors.txt -D /tmp/f-metrics-cors.h -w "%{http_code}" \
  "http://127.0.0.1:$CORS_PORT/metrics" -H "Origin: http://localhost:3000" -H "X-Request-Id: mvp-cors-metrics-rid")"
echo "cors_get_metrics_status=$METRICS_CORS"
test "$METRICS_CORS" = "200"
grep -q 'cn_work_agent_approvals_pending' /tmp/f-metrics-cors.txt
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" /tmp/f-metrics-cors.h
grep -qiE "^access-control-expose-headers:.*retry-after" /tmp/f-metrics-cors.h
grep -qiE "^access-control-expose-headers:.*x-request-id" /tmp/f-metrics-cors.h
grep -qiE "^x-request-id:[[:space:]]*mvp-cors-metrics-rid" /tmp/f-metrics-cors.h

POST_CORS="$(curl -s -o /tmp/f-post-cors.json -D /tmp/f-post-cors.h -w "%{http_code}" \
  -X POST "http://127.0.0.1:$CORS_PORT/webhook/feishu" \
  -H "content-type: application/json" \
  -H "Origin: http://localhost:3000" \
  -H "X-Request-Id: mvp-cors-post-rid" \
  -d '{"text":"ping","token":"wrong"}')"
echo "cors_post_webhook_status=$POST_CORS"
test "$POST_CORS" = "401"
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" /tmp/f-post-cors.h
grep -qiE "^access-control-expose-headers:.*retry-after" /tmp/f-post-cors.h
grep -qiE "^access-control-expose-headers:.*x-request-id" /tmp/f-post-cors.h
grep -qiE "^x-request-id:[[:space:]]*mvp-cors-post-rid" /tmp/f-post-cors.h

HEALTH_EVIL="$(curl -s -o /tmp/f-health-evil.json -D /tmp/f-health-evil.h -w "%{http_code}" \
  "http://127.0.0.1:$CORS_PORT/health" -H "Origin: http://evil.example")"
echo "cors_get_evil_status=$HEALTH_EVIL"
test "$HEALTH_EVIL" = "200"
if grep -qiE "^access-control-allow-origin:" /tmp/f-health-evil.h; then
  echo "disallowed origin should not get ACAO"
  cat /tmp/f-health-evil.h
  exit 1
fi
if grep -qiE "^access-control-expose-headers:" /tmp/f-health-evil.h; then
  echo "disallowed origin should not get ACEH"
  cat /tmp/f-health-evil.h
  exit 1
fi

kill "$CORS_PID" 2>/dev/null || true
wait "$CORS_PID" 2>/dev/null || true
CORS_PID=""
echo "==> [cors] allow localhost:3000 / deny evil.example OK (isolated); main server default deny"

# ---------- approval-decision webhook (isolated; keep main serve without webhook) ----------
WH_PORT="${WH_PORT:-$((PORT + 20))}"
WH_SERVE_PORT="${WH_SERVE_PORT:-$((PORT + 21))}"
WH_OUT="$ROOT/data/webhook-last.json"
WH_HDR="$ROOT/data/webhook-last.headers.json"
WH_LOG="$ROOT/data/mock-webhook.log"
WH_SERVE_LOG="$ROOT/data/wh-server.log"
WH_AUDIT="$ROOT/data/wh-audit.jsonl"
WH_APPROVALS="$ROOT/data/wh-approvals.jsonl"
rm -f "$WH_OUT" "$WH_HDR" "$WH_AUDIT" "$WH_APPROVALS"
mkdir -p "$ROOT/data"
echo "==> [webhook] mock receiver :$WH_PORT + isolated serve :$WH_SERVE_PORT"
python3 "$ROOT/mock-webhook-receiver.py" --port "$WH_PORT" --out "$WH_OUT" --headers-out "$WH_HDR" >"$WH_LOG" 2>&1 &
WH_PID=$!
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$WH_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 50 ]; then
    echo "mock webhook receiver did not become healthy"
    cat "$WH_LOG" || true
    exit 1
  fi
done
APPROVAL_WEBHOOK_URL="http://127.0.0.1:${WH_PORT}/hook" \
  FEISHU_VERIFY_TOKEN="$FEISHU_VERIFY_TOKEN" \
  FEISHU_ENCRYPT_KEY="$FEISHU_ENCRYPT_KEY" \
  DINGTALK_TOKEN="$DINGTALK_TOKEN" \
  DINGTALK_SECRET="$DINGTALK_SECRET" \
  WECOM_TOKEN="$WECOM_TOKEN" \
  python3 -m cn_work_agent serve --port "$WH_SERVE_PORT" --audit "$WH_AUDIT" --approvals "$WH_APPROVALS" >"$WH_SERVE_LOG" 2>&1 &
WH_SERVE_PID=$!
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$WH_SERVE_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 50 ]; then
    echo "webhook serve did not become healthy"
    cat "$WH_SERVE_LOG" || true
    exit 1
  fi
done
printf '%s' '{"text":"请审批 webhook payload test","token":"mvp-token"}' > /tmp/f-wh-appr.json
export FEISHU_TS=1710000500 FEISHU_NONCE=nonce-wh
mapfile -t SIG_WH < <(python3 scripts/sign_feishu.py "$(cat /tmp/f-wh-appr.json)")
RID_WH="mvp-wh-rid-f1"
WH_CREATE="$(curl -sf -D /tmp/f-wh-appr.h -X POST "http://127.0.0.1:$WH_SERVE_PORT/webhook/feishu" \
  -H 'content-type: application/json' \
  -H "X-Lark-Request-Timestamp: ${SIG_WH[0]}" \
  -H "X-Lark-Request-Nonce: ${SIG_WH[1]}" \
  -H "X-Lark-Signature: ${SIG_WH[2]}" \
  -H "X-Request-Id: $RID_WH" \
  --data-binary @/tmp/f-wh-appr.json)"
echo "wh_create=$WH_CREATE"
WH_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["approval_id"])' <<<"$WH_CREATE")"
echo "wh_approval_id=$WH_ID"
test -n "$WH_ID"
# create must NOT POST (pending)
if test -f "$WH_OUT" && grep -q "$WH_ID" "$WH_OUT" 2>/dev/null; then
  echo "webhook must not fire on create/pending"
  cat "$WH_OUT"
  exit 1
fi
WH_DECIDE="$(curl -sf -X POST "http://127.0.0.1:$WH_SERVE_PORT/approvals/${WH_ID}/decide" \
  -H 'content-type: application/json' \
  -d '{"decision":"approve","note":"webhook-ok"}')"
echo "wh_decide=$WH_DECIDE"
echo "$WH_DECIDE" | grep -q approved
WH_OK=0
for i in $(seq 1 40); do
  if test -f "$WH_OUT" && grep -q "$WH_ID" "$WH_OUT" 2>/dev/null; then
    WH_OK=1
    break
  fi
  sleep 0.05
done
test "$WH_OK" = "1"
test -s "$WH_OUT"
grep -q "$WH_ID" "$WH_OUT"
python3 -c 'import json,sys; from pathlib import Path; aid=sys.argv[1]; rid=sys.argv[2]; d=json.loads(Path(sys.argv[3]).read_text()); assert d.get("id")==aid, d; assert d.get("status")=="approved", d; assert d.get("decision")=="approve", d; assert d.get("reason") in (None,); assert d.get("requestId")==rid, d; assert set(d) >= {"id","status","decision","reason","requestId"}, d; print("webhook_ok", d.get("status"), d.get("decision"))' "$WH_ID" "$RID_WH" "$WH_OUT"
echo "webhook_approval_decide_ok"
echo "==> [webhook] GET /metrics webhooks_total after decide POST"
curl -s -o "$ROOT/data/wh-metrics.txt" "http://127.0.0.1:$WH_SERVE_PORT/metrics"
test -s "$ROOT/data/wh-metrics.txt"
grep -q 'cn_work_agent_webhooks_total' "$ROOT/data/wh-metrics.txt"
grep -q 'cn_work_agent_approvals_decided_total' "$ROOT/data/wh-metrics.txt"
python3 - <<'PYWHMETRICS'
from pathlib import Path
text = Path("data/wh-metrics.txt").read_text(encoding="utf-8")
vals = {}
for line in text.splitlines():
    if not line or line.startswith("#"):
        continue
    parts = line.split()
    if len(parts) >= 2 and "{" not in parts[0]:
        vals[parts[0]] = float(parts[1])
assert vals.get("cn_work_agent_webhooks_total", 0) >= 1, vals
assert vals.get("cn_work_agent_approvals_decided_total", 0) >= 1, vals
print("webhook_metrics_ok", vals)
PYWHMETRICS
echo "webhook_metrics_ok"
echo "==> approval-decision webhook timestamp header (OSS; replay window = paid)"
test -f "$WH_HDR"
python3 -c '
import json, sys, time
from pathlib import Path
meta = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))

raw = meta.get("timestamp")
if raw is None:
    headers = meta.get("headers") or {}
    raw = headers.get("X-Webhook-Timestamp") or headers.get("x-webhook-timestamp")
    if raw is None:
        for k, v in headers.items():
            if str(k).lower() == "x-webhook-timestamp":
                raw = v
                break
try:
    ts = int(str(raw or "").strip())
except (TypeError, ValueError):
    raise SystemExit("missing X-Webhook-Timestamp %r" % (meta,))
import time
now = int(time.time())
if abs(now - ts) > 120:
    raise SystemExit("timestamp not now ts=%s now=%s" % (ts, now))

print("webhook_timestamp_ok", ts)
' "$WH_HDR"
echo "webhook_timestamp_ok"
kill "$WH_SERVE_PID" 2>/dev/null || true
wait "$WH_SERVE_PID" 2>/dev/null || true
WH_SERVE_PID=""
kill "$WH_PID" 2>/dev/null || true
wait "$WH_PID" 2>/dev/null || true
WH_PID=""

echo "==> [hmac] isolated serve --webhook-secret (unsigned prove above stays intact)"
HMAC_PORT="${HMAC_PORT:-$((PORT + 23))}"
HMAC_WH_PORT="${HMAC_WH_PORT:-$((PORT + 22))}"
HMAC_SECRET="whsec_local_mvp"
HMAC_OUT="$ROOT/data/webhook-hmac-last.json"
HMAC_HDR="$ROOT/data/webhook-hmac-last.headers.json"
HMAC_LOG="$ROOT/data/hmac-serve.log"
HMAC_WH_LOG="$ROOT/data/mock-webhook.hmac.log"
HMAC_AUDIT="$ROOT/data/hmac-audit.jsonl"
HMAC_APPROVALS="$ROOT/data/hmac-approvals.jsonl"
rm -f "$HMAC_OUT" "$HMAC_HDR" "$HMAC_AUDIT" "$HMAC_APPROVALS"
mkdir -p "$ROOT/data"
python3 "$ROOT/mock-webhook-receiver.py" --port "$HMAC_WH_PORT" --out "$HMAC_OUT" \
  --headers-out "$HMAC_HDR" --secret "$HMAC_SECRET" >"$HMAC_WH_LOG" 2>&1 &
HMAC_WH_PID=$!
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$HMAC_WH_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 50 ]; then
    echo "hmac mock webhook receiver did not become healthy"
    cat "$HMAC_WH_LOG" || true
    exit 1
  fi
done
APPROVAL_WEBHOOK_URL="http://127.0.0.1:${HMAC_WH_PORT}/hook" \
  APPROVAL_WEBHOOK_SECRET="$HMAC_SECRET" \
  FEISHU_VERIFY_TOKEN="$FEISHU_VERIFY_TOKEN" \
  FEISHU_ENCRYPT_KEY="$FEISHU_ENCRYPT_KEY" \
  DINGTALK_TOKEN="$DINGTALK_TOKEN" \
  DINGTALK_SECRET="$DINGTALK_SECRET" \
  WECOM_TOKEN="$WECOM_TOKEN" \
  python3 -m cn_work_agent serve --port "$HMAC_PORT" --audit "$HMAC_AUDIT" --approvals "$HMAC_APPROVALS" >"$HMAC_LOG" 2>&1 &
HMAC_PID=$!
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$HMAC_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 50 ]; then
    echo "hmac serve did not become healthy"
    cat "$HMAC_LOG" || true
    exit 1
  fi
done
echo "==> [hmac] GET /v1/config must not leak webhook secret/url"
HMAC_CFG_CODE="$(curl -s -o /tmp/f-hmac-config.json -w '%{http_code}' \
  "http://127.0.0.1:$HMAC_PORT/v1/config")"
echo "hmac_config_status=$HMAC_CFG_CODE body=$(cat /tmp/f-hmac-config.json)"
test "$HMAC_CFG_CODE" = "200"
python3 - "$HMAC_SECRET" "$HMAC_WH_PORT" <<'PYHMACCFG'
import json, sys
from pathlib import Path
secret, port = sys.argv[1], sys.argv[2]
body = json.loads(Path("/tmp/f-hmac-config.json").read_text(encoding="utf-8"))
blob = json.dumps(body)
assert body.get("ok") is True, body
assert (body.get("webhooks") or {}).get("hasUrl") is True, body
assert (body.get("webhooks") or {}).get("hasSecret") is True, body
assert secret not in blob, blob
assert f"127.0.0.1:{port}" not in blob, blob
assert "whsec_" not in blob, blob
print("hmac_config_redacted_ok")
PYHMACCFG
printf '%s' '{"text":"请审批 hmac webhook test","token":"mvp-token"}' > /tmp/f-hmac-appr.json
export FEISHU_TS=1710000600 FEISHU_NONCE=nonce-hmac
mapfile -t SIG_HMAC < <(python3 scripts/sign_feishu.py "$(cat /tmp/f-hmac-appr.json)")
RID_HMAC="mvp-hmac-rid-f1"
HMAC_CREATE="$(curl -sf -X POST "http://127.0.0.1:$HMAC_PORT/webhook/feishu" \
  -H 'content-type: application/json' \
  -H "X-Lark-Request-Timestamp: ${SIG_HMAC[0]}" \
  -H "X-Lark-Request-Nonce: ${SIG_HMAC[1]}" \
  -H "X-Lark-Signature: ${SIG_HMAC[2]}" \
  -H "X-Request-Id: $RID_HMAC" \
  --data-binary @/tmp/f-hmac-appr.json)"
echo "hmac_create=$HMAC_CREATE"
HMAC_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["approval_id"])' <<<"$HMAC_CREATE")"
test -n "$HMAC_ID"
HMAC_DECIDE="$(curl -sf -X POST "http://127.0.0.1:$HMAC_PORT/approvals/${HMAC_ID}/decide" \
  -H 'content-type: application/json' \
  -d '{"decision":"reject","note":"hmac-ok"}')"
echo "hmac_decide=$HMAC_DECIDE"
echo "$HMAC_DECIDE" | grep -q rejected
HMAC_OK=0
for i in $(seq 1 40); do
  if test -f "$HMAC_OUT" && grep -q "$HMAC_ID" "$HMAC_OUT" 2>/dev/null \
     && test -f "$HMAC_HDR" && grep -q 'sha256=' "$HMAC_HDR" 2>/dev/null; then
    HMAC_OK=1
    break
  fi
  sleep 0.05
done
test "$HMAC_OK" = "1"
test -s "$HMAC_OUT"
grep -q "$HMAC_ID" "$HMAC_OUT"
grep -qi 'sha256=' "$HMAC_HDR"
grep -q '"verified": true' "$HMAC_HDR"
python3 -c '
import json, sys
from pathlib import Path
from cn_work_agent.webhook import sign_webhook_body, verify_webhook_signature
secret, body_path, hdr_path, aid, want = sys.argv[1:6]
body = Path(body_path).read_bytes()
meta = json.loads(Path(hdr_path).read_text(encoding="utf-8"))
sig = str(meta.get("signature") or "")
if not sig.lower().startswith("sha256="):
    raise SystemExit("missing X-Webhook-Signature sha256= prefix")
expected = sign_webhook_body(secret, body)
if sig.lower() != expected:
    raise SystemExit(f"HMAC mismatch got={sig} expected={expected}")
if not verify_webhook_signature(secret, body, sig):
    raise SystemExit("verify_webhook_signature failed")
if meta.get("verified") is not True:
    raise SystemExit("receiver verified flag %r" % (meta.get("verified"),))
d = json.loads(body.decode("utf-8"))
assert d.get("id") == aid, d
assert d.get("requestId") == want, d
assert d.get("status") == "rejected", d
assert d.get("decision") == "reject", d
assert set(d) >= {"id", "status", "decision", "reason", "requestId"}, d

raw = meta.get("timestamp")
if raw is None:
    headers = meta.get("headers") or {}
    raw = headers.get("X-Webhook-Timestamp") or headers.get("x-webhook-timestamp")
    if raw is None:
        for k, v in headers.items():
            if str(k).lower() == "x-webhook-timestamp":
                raw = v
                break
try:
    ts = int(str(raw or "").strip())
except (TypeError, ValueError):
    raise SystemExit("missing X-Webhook-Timestamp %r" % (meta,))
import time
now = int(time.time())
if abs(now - ts) > 120:
    raise SystemExit("timestamp not now ts=%s now=%s" % (ts, now))

print("webhook_hmac_ok", expected[:18] + "…", "ts=" + str(ts))
' "$HMAC_SECRET" "$HMAC_OUT" "$HMAC_HDR" "$HMAC_ID" "$RID_HMAC"
echo "webhook_hmac_ok"
kill "$HMAC_PID" 2>/dev/null || true
wait "$HMAC_PID" 2>/dev/null || true
HMAC_PID=""
kill "$HMAC_WH_PID" 2>/dev/null || true
wait "$HMAC_WH_PID" 2>/dev/null || true
HMAC_WH_PID=""
echo "==> [webhook] unsigned create+decide payload + isolated HMAC OK; main server unchanged"

# ---------- inbound IM callback HMAC (isolated; main demo has no callbackSecret) ----------
CB_PORT="${CB_PORT:-$((PORT + 25))}"
CB_CFG="$ROOT/data/callback-config.json"
CB_LOG="$ROOT/data/callback-server.log"
CB_AUDIT="$ROOT/data/callback-audit.jsonl"
CB_APPROVALS="$ROOT/data/callback-approvals.jsonl"
CB_SECRET="cbsec_local_mvp"
rm -f "$CB_LOG" "$CB_AUDIT" "$CB_APPROVALS" "$CB_CFG"
mkdir -p "$ROOT/data"
python3 - <<'CBCFG'
import json
from datetime import datetime, timezone
from pathlib import Path
now = datetime.now(timezone.utc).isoformat()
cfg = {
    "bot_name": "cb-bot",
    "platforms": ["feishu", "dingtalk", "wecom"],
    "feishu": {"callbackSecret": "cbsec_local_mvp"},
    "approval_ttl_seconds": 86400,
}
Path("data/callback-config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
rows = []
for aid, text in (
    ("appr_cbunsign001", "callback unsigned"),
    ("appr_cbbad000001", "callback bad sig"),
    ("appr_cbgood00001", "callback good sig"),
    ("appr_cbget000001", "callback get decide"),
    ("appr_cbskew00001", "callback timestamp skew"),
):
    rows.append({
        "id": aid,
        "status": "pending",
        "text": text,
        "platform": "feishu",
        "created_at": now,
        "updated_at": now,
        "decision": None,
        "note": None,
        "reason": None,
    })
Path("data/callback-approvals.jsonl").write_text(
    "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
    encoding="utf-8",
)
print("callback_config_written")
CBCFG
echo "==> [callback] isolated serve --config with feishu.callbackSecret on :$CB_PORT"
unset FEISHU_CALLBACK_SECRET || true
unset DINGTALK_CALLBACK_SECRET || true
unset WECOM_CALLBACK_SECRET || true
unset APPROVAL_CALLBACK_SECRET || true
python3 -m cn_work_agent serve --port "$CB_PORT" --config "$CB_CFG" \
  --audit "$CB_AUDIT" --approvals "$CB_APPROVALS" \
  >"$CB_LOG" 2>&1 &
CB_PID=$!
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$CB_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 50 ]; then
    echo "callback serve did not become healthy"
    cat "$CB_LOG" || true
    exit 1
  fi
done
echo "==> [callback] GET /v1/config must not leak callbackSecret"
CB_CFG_CODE="$(curl -s -o /tmp/f-cb-config.json -w '%{http_code}' \
  "http://127.0.0.1:$CB_PORT/v1/config")"
echo "callback_config_status=$CB_CFG_CODE body=$(cat /tmp/f-cb-config.json)"
test "$CB_CFG_CODE" = "200"
python3 - "$CB_SECRET" <<'PYCBCFG'
import json, sys
from pathlib import Path
secret = sys.argv[1]
body = json.loads(Path("/tmp/f-cb-config.json").read_text(encoding="utf-8"))
blob = json.dumps(body)
assert body.get("ok") is True, body
plats = {r.get("id"): r for r in (body.get("platforms") or [])}
assert plats.get("feishu", {}).get("hasCallbackSecret") is True, body
assert secret not in blob, blob
assert "callbackSecret" not in blob, blob
print("callback_config_redacted_ok")
PYCBCFG

printf '%s' '{"decision":"approve","note":"unsigned"}' > /tmp/f-cb-unsigned.json
CB_UNSIG="$(curl -s -o /tmp/f-cb-unsigned-out.json -w '%{http_code}' -X POST \
  "http://127.0.0.1:$CB_PORT/approvals/appr_cbunsign001/decide" \
  -H 'content-type: application/json' \
  --data-binary @/tmp/f-cb-unsigned.json)"
echo "callback_unsigned_status=$CB_UNSIG body=$(cat /tmp/f-cb-unsigned-out.json)"
test "$CB_UNSIG" = "401"
grep -q unauthorized /tmp/f-cb-unsigned-out.json
grep -q missing_signature /tmp/f-cb-unsigned-out.json
if grep -q "$CB_SECRET" /tmp/f-cb-unsigned-out.json; then
  echo "401 must not leak callbackSecret"
  cat /tmp/f-cb-unsigned-out.json
  exit 1
fi
grep -q pending "$CB_APPROVALS"
grep -q appr_cbunsign001 "$CB_APPROVALS"

printf '%s' '{"decision":"approve","note":"bad"}' > /tmp/f-cb-bad.json
CB_BAD="$(curl -s -o /tmp/f-cb-bad-out.json -w '%{http_code}' -X POST \
  "http://127.0.0.1:$CB_PORT/approvals/appr_cbbad000001/decide" \
  -H 'content-type: application/json' \
  -H "X-Callback-Signature: sha256=deadbeef" \
  --data-binary @/tmp/f-cb-bad.json)"
echo "callback_bad_status=$CB_BAD body=$(cat /tmp/f-cb-bad-out.json)"
test "$CB_BAD" = "401"
grep -q unauthorized /tmp/f-cb-bad-out.json
grep -q bad_signature /tmp/f-cb-bad-out.json
if grep -q "$CB_SECRET" /tmp/f-cb-bad-out.json; then
  echo "401 must not leak callbackSecret"
  cat /tmp/f-cb-bad-out.json
  exit 1
fi

printf '%s' '{"decision":"approve","note":"good"}' > /tmp/f-cb-good.json
CB_SIG="$(python3 -c 'from pathlib import Path; from cn_work_agent.webhook import sign_webhook_body; print(sign_webhook_body("cbsec_local_mvp", Path("/tmp/f-cb-good.json").read_bytes()))')"
CB_TS="$(python3 -c 'import time; print(int(time.time()))')"
CB_GOOD="$(curl -s -o /tmp/f-cb-good-out.json -w '%{http_code}' -X POST \
  "http://127.0.0.1:$CB_PORT/approvals/appr_cbgood00001/decide" \
  -H 'content-type: application/json' \
  -H "X-Callback-Signature: $CB_SIG" \
  -H "X-Callback-Timestamp: $CB_TS" \
  --data-binary @/tmp/f-cb-good.json)"
echo "callback_good_status=$CB_GOOD body=$(cat /tmp/f-cb-good-out.json)"
test "$CB_GOOD" = "200"
grep -q approved /tmp/f-cb-good-out.json
grep -q appr_cbgood00001 /tmp/f-cb-good-out.json

CB_GET="$(curl -s -o /tmp/f-cb-get-out.json -w '%{http_code}' \
  "http://127.0.0.1:$CB_PORT/approvals/appr_cbget000001/decide?decision=approve")"
echo "callback_get_status=$CB_GET body=$(cat /tmp/f-cb-get-out.json)"
test "$CB_GET" = "200"
grep -q approved /tmp/f-cb-get-out.json

printf '%s' '{"decision":"reject","note":"skew"}' > /tmp/f-cb-skew.json
CB_SKEW_SIG="$(python3 -c 'from pathlib import Path; from cn_work_agent.webhook import sign_webhook_body; print(sign_webhook_body("cbsec_local_mvp", Path("/tmp/f-cb-skew.json").read_bytes()))')"
CB_SKEW="$(curl -s -o /tmp/f-cb-skew-out.json -w '%{http_code}' -X POST \
  "http://127.0.0.1:$CB_PORT/approvals/appr_cbskew00001/decide" \
  -H 'content-type: application/json' \
  -H "X-Callback-Signature: $CB_SKEW_SIG" \
  -H "X-Callback-Timestamp: 1000000000" \
  --data-binary @/tmp/f-cb-skew.json)"
echo "callback_skew_status=$CB_SKEW body=$(cat /tmp/f-cb-skew-out.json)"
test "$CB_SKEW" = "401"
grep -q timestamp_skew /tmp/f-cb-skew-out.json
if grep -q "$CB_SECRET" /tmp/f-cb-skew-out.json; then
  echo "401 must not leak callbackSecret"
  cat /tmp/f-cb-skew-out.json
  exit 1
fi

kill "$CB_PID" 2>/dev/null || true
wait "$CB_PID" 2>/dev/null || true
CB_PID=""
echo "==> [callback] isolated POST good 200 / bad+unsigned+skew 401 / GET unsigned 200; main serve unchanged"

# ---------- serve --watch (isolated config copy; keep main serve without --watch) ----------
WATCH_PORT="${WATCH_PORT:-$((PORT + 24))}"
WATCH_CFG="$ROOT/data/watch-config.json"
WATCH_LOG="$ROOT/data/watch-server.log"
WATCH_AUDIT="$ROOT/data/watch-audit.jsonl"
WATCH_APPROVALS="$ROOT/data/watch-approvals.jsonl"
WATCH_BEFORE="$ROOT/data/watch-before-health.json"
WATCH_AFTER="$ROOT/data/watch-after-health.json"
rm -f "$WATCH_LOG" "$WATCH_AUDIT" "$WATCH_APPROVALS" "$WATCH_CFG" "$WATCH_BEFORE" "$WATCH_AFTER"
mkdir -p "$ROOT/data"
python3 - <<'WATCHCFG'
import json
from pathlib import Path
src = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
src["approval_ttl_seconds"] = 86400
src["rate_limit_per_minute"] = 60
Path("data/watch-config.json").write_text(json.dumps(src, indent=2) + "\n", encoding="utf-8")
print("watch_config_written ttl=86400")
WATCHCFG
echo "==> [watch] isolated serve --config data/watch-config.json --watch on :$WATCH_PORT"
# Env wins if already set — unset so file TTL/CORS/webhook/rate-limit apply.
unset APPROVAL_TTL_SECONDS || true
unset RATE_LIMIT_PER_MINUTE || true
unset RATE_LIMIT_FEISHU_PER_MINUTE || true
unset RATE_LIMIT_DINGTALK_PER_MINUTE || true
unset RATE_LIMIT_WECOM_PER_MINUTE || true
unset CORS_ORIGINS || true
unset APPROVAL_WEBHOOK_URL || true
unset APPROVAL_WEBHOOK_SECRET || true
python3 -m cn_work_agent serve --port "$WATCH_PORT" --config "$WATCH_CFG" \
  --audit "$WATCH_AUDIT" --approvals "$WATCH_APPROVALS" --watch \
  >"$WATCH_LOG" 2>&1 &
WATCH_PID=$!
cleanup_watch() {
  if [ -n "${WATCH_PID:-}" ] && kill -0 "$WATCH_PID" 2>/dev/null; then
    kill "$WATCH_PID" 2>/dev/null || true
    wait "$WATCH_PID" 2>/dev/null || true
  fi
}
trap 'cleanup_watch; cleanup' EXIT

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
curl -sf "http://127.0.0.1:$WATCH_PORT/health" -o "$WATCH_BEFORE"
BEFORE_TTL="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("approval_ttl_seconds"))' "$WATCH_BEFORE")"
echo "watch_before approval_ttl_seconds=$BEFORE_TTL"
test "$BEFORE_TTL" = "86400"

python3 - <<'WATCHMUT'
import json, os, time
from pathlib import Path
p = Path("data/watch-config.json")
data = json.loads(p.read_text(encoding="utf-8"))
data["approval_ttl_seconds"] = 120
p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
now = time.time() + 1
os.utime(p, (now, now))
print("watch_config_mutated ttl=120")
WATCHMUT

REGEN_OK=0
for _ in $(seq 1 25); do
  curl -sf "http://127.0.0.1:$WATCH_PORT/health" -o "$WATCH_AFTER" || true
  AFTER_TTL=""
  if test -s "$WATCH_AFTER"; then
    AFTER_TTL="$(python3 -c 'import json,sys
try:
  print(json.load(open(sys.argv[1])).get("approval_ttl_seconds",""))
except Exception:
  pass' "$WATCH_AFTER" || true)"
  fi
  if grep -q regenerated "$WATCH_LOG" 2>/dev/null; then
    curl -sf "http://127.0.0.1:$WATCH_PORT/health" -o "$WATCH_AFTER" || true
    REGEN_OK=1
    break
  fi
  if [ "$AFTER_TTL" = "120" ]; then
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

cleanup_watch
WATCH_PID=""
trap cleanup EXIT

if [ "$REGEN_OK" != "1" ]; then
  echo "watch did not regenerate within 5s"
  echo "--- watch-server.log ---"
  cat "$WATCH_LOG" || true
  exit 1
fi
test -s "$WATCH_AFTER"
AFTER_TTL="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("approval_ttl_seconds"))' "$WATCH_AFTER")"
echo "watch_after approval_ttl_seconds=$AFTER_TTL"
test "$AFTER_TTL" = "120"
if ! grep -q regenerated "$WATCH_LOG"; then
  echo "watch regenerate detected via HTTP but missing regenerated log line"
  cat "$WATCH_LOG" || true
  exit 1
fi
grep -q "watching" "$WATCH_LOG"
echo "watch regenerate OK"

# ---------- approvals-max (isolated; keep main demo default 2000) ----------
CAP_PORT="${CAP_PORT:-$((PORT + 26))}"
CAP_LOG="$ROOT/data/approvals-max-server.log"
CAP_AUDIT="$ROOT/data/approvals-max-audit.jsonl"
CAP_APPROVALS="$ROOT/data/approvals-max.jsonl"
rm -f "$CAP_LOG" "$CAP_AUDIT" "$CAP_APPROVALS" \
  data/approvals-max-1.json data/approvals-max-2.json data/approvals-max-3.json \
  data/approvals-max-list.json data/approvals-max.csv data/approvals-max-old.json
mkdir -p "$ROOT/data"
echo "==> [approvals-max] isolated serve --approvals-max 2 on :$CAP_PORT (create+decide 3; list/CSV 2; oldest 404)"
unset APPROVALS_MAX || true
python3 -m cn_work_agent serve --port "$CAP_PORT" --audit "$CAP_AUDIT" \
  --approvals "$CAP_APPROVALS" --approvals-max 2 >"$CAP_LOG" 2>&1 &
CAP_PID=$!
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$CAP_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 50 ]; then
    echo "approvals-max serve did not become healthy"
    cat "$CAP_LOG" || true
    exit 1
  fi
  if ! kill -0 "$CAP_PID" 2>/dev/null; then
    echo "approvals-max serve exited early"
    cat "$CAP_LOG" || true
    exit 1
  fi
done
grep -q "approvals_max=2" "$CAP_LOG"
CAP_HEALTH="$(curl -sf "http://127.0.0.1:$CAP_PORT/health")"
echo "cap_health=$CAP_HEALTH"
echo "$CAP_HEALTH" | grep -Eq '"approvals_max"[[:space:]]*:[[:space:]]*2'

post_cap() {
  local i="$1" out="$2"
  printf '%s' "{\"text\":\"请审批 cap-${i}\",\"token\":\"mvp-token\"}" > /tmp/f-cap-msg.json
  export FEISHU_TS="17100005${i}0" FEISHU_NONCE="nonce-cap-${i}"
  mapfile -t SIG_CAP < <(python3 scripts/sign_feishu.py "$(cat /tmp/f-cap-msg.json)")
  curl -sf -X POST "http://127.0.0.1:$CAP_PORT/webhook/feishu" \
    -H 'content-type: application/json' \
    -H "X-Lark-Request-Timestamp: ${SIG_CAP[0]}" \
    -H "X-Lark-Request-Nonce: ${SIG_CAP[1]}" \
    -H "X-Lark-Signature: ${SIG_CAP[2]}" \
    --data-binary @/tmp/f-cap-msg.json >"$out"
}

post_cap 1 data/approvals-max-1.json
post_cap 2 data/approvals-max-2.json
post_cap 3 data/approvals-max-3.json
CAP1="$(python3 -c 'import json; print(json.load(open("data/approvals-max-1.json"))["approval_id"])')"
CAP2="$(python3 -c 'import json; print(json.load(open("data/approvals-max-2.json"))["approval_id"])')"
CAP3="$(python3 -c 'import json; print(json.load(open("data/approvals-max-3.json"))["approval_id"])')"
test -n "$CAP1" && test -n "$CAP2" && test -n "$CAP3"
test "$CAP1" != "$CAP2" && test "$CAP2" != "$CAP3"

for aid in "$CAP1" "$CAP2" "$CAP3"; do
  curl -sf -X POST "http://127.0.0.1:$CAP_PORT/approvals/${aid}/decide" \
    -H 'content-type: application/json' \
    -d '{"decision":"approve","note":"cap"}' >/dev/null
done

LIST_CAP="$(curl -sf "http://127.0.0.1:$CAP_PORT/approvals?limit=10")"
echo "$LIST_CAP" | tee data/approvals-max-list.json
python3 - "$CAP1" "$CAP2" "$CAP3" <<'PYCAPLIST'
import json, sys
from pathlib import Path
old, mid, new = sys.argv[1], sys.argv[2], sys.argv[3]
data = json.loads(Path("data/approvals-max-list.json").read_text(encoding="utf-8"))
rows = data.get("approvals") or []
ids = [r.get("id") for r in rows]
assert data.get("count") == 2, data
assert len(rows) == 2, data
assert old not in ids, ids
assert mid in ids and new in ids, ids
print("approvals_max_list_ok", ids)
PYCAPLIST

CSV_CAP="$(curl -sf "http://127.0.0.1:$CAP_PORT/v1/approvals.csv")"
echo "$CSV_CAP" | tee data/approvals-max.csv
python3 - "$CAP1" "$CAP2" "$CAP3" <<'PYCAPCSV'
import csv, io, sys
from pathlib import Path
old, mid, new = sys.argv[1], sys.argv[2], sys.argv[3]
text = Path("data/approvals-max.csv").read_text(encoding="utf-8")
rows = list(csv.DictReader(io.StringIO(text)))
ids = [r.get("id") for r in rows]
assert text.startswith("id,platform,status,createdAt,decidedAt,reason"), text.split("\n", 1)[0]
assert len(rows) == 2, rows
assert old not in ids, ids
assert mid in ids and new in ids, ids
print("approvals_max_csv_ok", ids)
PYCAPCSV

MD_CAP="$(curl -sf "http://127.0.0.1:$CAP_PORT/v1/approvals.md")"
echo "$MD_CAP" | tee data/approvals-max.md
python3 - "$CAP1" "$CAP2" "$CAP3" <<'PYCAPMD'
import sys
from pathlib import Path
old, mid, new = sys.argv[1], sys.argv[2], sys.argv[3]
text = Path("data/approvals-max.md").read_text(encoding="utf-8")
assert text.startswith("# "), text[:40]
assert "|" in text
assert old not in text, text
assert mid in text and new in text, text
print("approvals_max_md_ok")
PYCAPMD

HTML_CAP="$(curl -sf "http://127.0.0.1:$CAP_PORT/v1/approvals.html")"
echo "$HTML_CAP" | tee data/approvals-max.html
python3 - "$CAP1" "$CAP2" "$CAP3" <<'PYCAPHTML'
import sys
from pathlib import Path
old, mid, new = sys.argv[1], sys.argv[2], sys.argv[3]
text = Path("data/approvals-max.html").read_text(encoding="utf-8")
assert "<table" in text, text[:80]
assert old not in text, text
assert mid in text and new in text, text
print("approvals_max_html_ok")
PYCAPHTML

set +e
OLD_CAP="$(curl -s -o data/approvals-max-old.json -w '%{http_code}' "http://127.0.0.1:$CAP_PORT/approvals/$CAP1")"
OLD_CARD="$(curl -s -o data/approvals-max-old-card.json -w '%{http_code}' "http://127.0.0.1:$CAP_PORT/v1/approvals/$CAP1/card?platform=feishu")"
set -e
echo "approvals_max_oldest_status=$OLD_CAP card=$OLD_CARD body=$(cat data/approvals-max-old.json)"
test "$OLD_CAP" = "404"
test "$OLD_CARD" = "404"
curl -sf "http://127.0.0.1:$CAP_PORT/approvals/$CAP3" >/dev/null
curl -sf "http://127.0.0.1:$CAP_PORT/v1/approvals/$CAP3/card?platform=feishu" >/dev/null

if [ -n "${CAP_PID:-}" ]; then
  kill "$CAP_PID" 2>/dev/null || true
  wait "$CAP_PID" 2>/dev/null || true
  CAP_PID=""
fi
grep -q "approvals_max=2000" "$ROOT/data/server.log"
echo "==> [approvals-max] list/CSV 2 / oldest 404 / card 404 OK (isolated); main serve default 2000 unchanged"

# ---------- audit ----------
test -f "$AUDIT"
grep -q 'digest hello-mvp' "$AUDIT"
grep -q 'tok-xyz' "$AUDIT"
grep -q 'unauthorized' "$AUDIT"
grep -q 'dingtalk' "$AUDIT"
grep -q 'wecom' "$AUDIT"
grep -q 'hello-dt' "$AUDIT"
grep -q 'hello-wc' "$AUDIT"

echo "f-cn-work-agent local-mvp OK (feishu+dingtalk+wecom+approvals+ttl+rate-limit+cors+request-id+openapi+metrics+decision-webhook+hmac+inbound-callback+watch+approvals-max+config)"
