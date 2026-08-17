#!/usr/bin/env bash
# Local Feishu approval demo (请假 + 用印). No real Feishu network.
# Mock verify via scripts/sign_feishu.py + config.example.json tokens.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH=src

PORT="${PORT:-8793}"
AUDIT="$ROOT/data/feishu-appr-audit.jsonl"
CFG="$ROOT/data/feishu-appr-config.json"
LOG="$ROOT/data/feishu-appr-server.log"
APPROVALS="$ROOT/data/feishu-appr-approvals.jsonl"
mkdir -p "$ROOT/data"
rm -f "$AUDIT" "$LOG" "$APPROVALS"

python3 - <<'PY'
import json
from pathlib import Path
ex = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
ex["feishu"] = {"verify_token": "demo-feishu-token", "encrypt_key": "demo-feishu-encrypt"}
ex["dingtalk"] = {"token": "demo-dt-token", "secret": "demo-dt-secret"}
ex["wecom"] = {"token": "demo-wc-token"}
ex["platforms"] = ["feishu"]
Path("data/feishu-appr-config.json").write_text(json.dumps(ex, indent=2) + "\n", encoding="utf-8")
print("wrote data/feishu-appr-config.json (feishu-only, example-shaped tokens)")
PY

unset FEISHU_VERIFY_TOKEN FEISHU_ENCRYPT_KEY DINGTALK_TOKEN DINGTALK_SECRET WECOM_TOKEN || true
unset FEISHU_CALLBACK_SECRET APPROVAL_CALLBACK_SECRET APPROVAL_WEBHOOK_URL || true

python3 -m cn_work_agent serve \
  --config "$CFG" \
  --port "$PORT" \
  --audit "$AUDIT" \
  --approvals "$APPROVALS" \
  --platform feishu \
  >"$LOG" 2>&1 &
PID=$!
cleanup() { kill "$PID" 2>/dev/null || true; wait "$PID" 2>/dev/null || true; }
trap cleanup EXIT

for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
done

HEALTH="$(curl -sf "http://127.0.0.1:$PORT/health")"
echo "==> health"
echo "$HEALTH"
echo "$HEALTH" | grep -qE '"ok":\s*true|"ok":true'
echo "$HEALTH" | grep -q feishu

export FEISHU_ENCRYPT_KEY=demo-feishu-encrypt

post_feishu() {
  local body_file="$1"
  local ts="$2"
  local nonce="$3"
  export FEISHU_TS="$ts" FEISHU_NONCE="$nonce"
  mapfile -t SIG < <(python3 scripts/sign_feishu.py "$(cat "$body_file")")
  curl -sf -X POST "http://127.0.0.1:$PORT/webhook/feishu" \
    -H 'content-type: application/json' \
    -H "X-Lark-Request-Timestamp: ${SIG[0]}" \
    -H "X-Lark-Request-Nonce: ${SIG[1]}" \
    -H "X-Lark-Signature: ${SIG[2]}" \
    --data-binary @"$body_file"
}

echo
echo "==> [1] 创建请假审批 (Feishu mock webhook, no vendor network)"
printf '%s' '{"text":"请审批请假 明天一天","token":"demo-feishu-token"}' > /tmp/f-leave.json
LEAVE_RESP="$(post_feishu /tmp/f-leave.json 1710002001 demo-leave-n1)"
echo "leave_create=$LEAVE_RESP"
echo "$LEAVE_RESP" | grep -q approval
echo "$LEAVE_RESP" | grep -q pending
LEAVE_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["approval_id"])' <<<"$LEAVE_RESP")"
echo "leave_id=$LEAVE_ID"
test -n "$LEAVE_ID"

echo
echo "==> [2] 渲染飞书 interactive card (GET /v1/approvals/{id}/card?platform=feishu)"
CARD="$(curl -sf "http://127.0.0.1:$PORT/v1/approvals/${LEAVE_ID}/card?platform=feishu")"
echo "$CARD" | python3 -m json.tool
echo "$CARD" | grep -q interactive
echo "$CARD" | grep -q header
echo "$CARD" | grep -q elements
echo "$CARD" | grep -q Approve
echo "$CARD" | grep -q Reject
echo "$CARD" | grep -q "$LEAVE_ID"
python3 -c 'import json,sys; c=json.loads(sys.argv[1]); assert "sk-" not in json.dumps(c)' "$CARD"

echo
echo "==> [3] 创建用印审批"
printf '%s' '{"text":"请审批用印 合同盖章","token":"demo-feishu-token"}' > /tmp/f-seal.json
SEAL_RESP="$(post_feishu /tmp/f-seal.json 1710002002 demo-seal-n1)"
echo "seal_create=$SEAL_RESP"
SEAL_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["approval_id"])' <<<"$SEAL_RESP")"
echo "seal_id=$SEAL_ID"
test -n "$SEAL_ID"

echo
echo "==> [4] GET /v1/approvals?status=pending (两单待批)"
PEND="$(curl -sf "http://127.0.0.1:$PORT/v1/approvals?status=pending")"
echo "$PEND" | python3 -m json.tool
echo "$PEND" | grep -q "$LEAVE_ID"
echo "$PEND" | grep -q "$SEAL_ID"
python3 -c 'import json,sys; d=json.loads(sys.argv[1]); assert d.get("ok") is True and d.get("count")==2, d' "$PEND"

echo
echo "==> [5] 批准请假 POST /approvals/{id}/decide"
LEAVE_DECIDE="$(curl -sf -X POST "http://127.0.0.1:$PORT/approvals/${LEAVE_ID}/decide" \
  -H 'content-type: application/json' \
  -d '{"decision":"approve","note":"请假准假"}')"
echo "leave_decide=$LEAVE_DECIDE"
echo "$LEAVE_DECIDE" | grep -qE '"ok":\s*true|"ok":true'
echo "$LEAVE_DECIDE" | grep -q approved

echo
echo "==> [6] 驳回用印"
SEAL_DECIDE="$(curl -sf -X POST "http://127.0.0.1:$PORT/approvals/${SEAL_ID}/decide" \
  -H 'content-type: application/json' \
  -d '{"decision":"reject","note":"用印材料不全"}')"
echo "seal_decide=$SEAL_DECIDE"
echo "$SEAL_DECIDE" | grep -qE '"ok":\s*true|"ok":true'
echo "$SEAL_DECIDE" | grep -q rejected

echo
echo "==> [7] GET /v1/approvals?status= 过滤"
echo "--- ?status=pending (应为 0) ---"
PEND2="$(curl -sf "http://127.0.0.1:$PORT/v1/approvals?status=pending")"
echo "$PEND2"
python3 -c 'import json,sys; d=json.loads(sys.argv[1]); assert d.get("ok") is True and d.get("count")==0 and d.get("approvals")==[], d' "$PEND2"

echo "--- ?status=approved (请假) ---"
OK="$(curl -sf "http://127.0.0.1:$PORT/v1/approvals?status=approved")"
echo "$OK" | python3 -m json.tool
echo "$OK" | grep -q "$LEAVE_ID"
if echo "$OK" | grep -q "$SEAL_ID"; then
  echo "rejected 用印 leaked into ?status=approved"
  exit 1
fi

echo "--- ?status=rejected (用印) ---"
REJ="$(curl -sf "http://127.0.0.1:$PORT/v1/approvals?status=rejected")"
echo "$REJ" | python3 -m json.tool
echo "$REJ" | grep -q "$SEAL_ID"
if echo "$REJ" | grep -q "$LEAVE_ID"; then
  echo "approved 请假 leaked into ?status=rejected"
  exit 1
fi

echo
echo "demo-feishu-approval OK — 请假已批 / 用印已驳；无真实飞书网络"
echo "see docs/cn-onprem.md"
