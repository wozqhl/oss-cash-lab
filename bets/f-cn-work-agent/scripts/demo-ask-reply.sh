#!/usr/bin/env bash
# Tiny intranet demo: serve --config (example tokens) → one ask/reply per platform → cleanup.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH=src

PORT="${PORT:-8792}"
AUDIT="$ROOT/data/demo-audit.jsonl"
CFG="$ROOT/data/demo-config.json"
LOG="$ROOT/data/demo-server.log"
mkdir -p "$ROOT/data"
rm -f "$AUDIT" "$LOG"

# Example-shaped config with known test tokens (env cleared so --config wins).
python3 - <<'PY'
import json
from pathlib import Path
ex = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
ex["feishu"] = {"verify_token": "demo-feishu-token", "encrypt_key": "demo-feishu-encrypt"}
ex["dingtalk"] = {"token": "demo-dt-token", "secret": "demo-dt-secret"}
ex["wecom"] = {"token": "demo-wc-token"}
ex["platforms"] = ["feishu", "dingtalk", "wecom"]
Path("data/demo-config.json").write_text(json.dumps(ex, indent=2) + "\n", encoding="utf-8")
print("wrote data/demo-config.json from config.example.json shape")
PY

unset FEISHU_VERIFY_TOKEN FEISHU_ENCRYPT_KEY DINGTALK_TOKEN DINGTALK_SECRET WECOM_TOKEN || true

python3 -m cn_work_agent serve --config "$CFG" --port "$PORT" --audit "$AUDIT" >"$LOG" 2>&1 &
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
echo "$HEALTH" | grep -q dingtalk
echo "$HEALTH" | grep -q wecom

export FEISHU_ENCRYPT_KEY=demo-feishu-encrypt
export DINGTALK_SECRET=demo-dt-secret
export WECOM_TOKEN=demo-wc-token

echo "==> [feishu] ask/reply"
printf '%s' '{"text":"digest demo-feishu","token":"demo-feishu-token"}' > /tmp/f-demo-fs.json
export FEISHU_TS=1710001001 FEISHU_NONCE=demo-fs-n1
mapfile -t SIG_FS < <(python3 scripts/sign_feishu.py "$(cat /tmp/f-demo-fs.json)")
FS_RESP="$(curl -sf -X POST "http://127.0.0.1:$PORT/webhook/feishu" \
  -H 'content-type: application/json' \
  -H "X-Lark-Request-Timestamp: ${SIG_FS[0]}" \
  -H "X-Lark-Request-Nonce: ${SIG_FS[1]}" \
  -H "X-Lark-Signature: ${SIG_FS[2]}" \
  --data-binary @/tmp/f-demo-fs.json)"
echo "feishu_reply=$FS_RESP"
echo "$FS_RESP" | grep -q ack
echo "$FS_RESP" | grep -q digest=
echo "$FS_RESP" | grep -q feishu

echo "==> [dingtalk] ask/reply"
printf '%s' '{"text":{"content":"digest demo-dt"},"token":"demo-dt-token"}' > /tmp/f-demo-dt.json
export DINGTALK_TS=1710001100
mapfile -t SIG_DT < <(python3 scripts/sign_dingtalk.py)
DT_RESP="$(curl -sf -X POST "http://127.0.0.1:$PORT/webhook/dingtalk" \
  -H 'content-type: application/json' \
  -H "X-DingTalk-Timestamp: ${SIG_DT[0]}" \
  -H "X-DingTalk-Sign: ${SIG_DT[1]}" \
  --data-binary @/tmp/f-demo-dt.json)"
echo "dingtalk_reply=$DT_RESP"
echo "$DT_RESP" | grep -q ack
echo "$DT_RESP" | grep -q digest=
echo "$DT_RESP" | grep -q dingtalk

echo "==> [wecom] ask/reply"
printf '%s' '{"Content":"digest demo-wc"}' > /tmp/f-demo-wc.json
export WECOM_TS=1710001201 WECOM_NONCE=demo-wc-n1
mapfile -t SIG_WC < <(python3 scripts/sign_wecom.py "$(cat /tmp/f-demo-wc.json)")
WC_RESP="$(curl -sf -X POST \
  "http://127.0.0.1:$PORT/webhook/wecom?msg_signature=${SIG_WC[2]}&timestamp=${SIG_WC[0]}&nonce=${SIG_WC[1]}" \
  -H 'content-type: application/json' \
  --data-binary @/tmp/f-demo-wc.json)"
echo "wecom_reply=$WC_RESP"
echo "$WC_RESP" | grep -q ack
echo "$WC_RESP" | grep -q digest=
echo "$WC_RESP" | grep -q wecom

echo "==> audit (tail)"
test -f "$AUDIT"
tail -n 5 "$AUDIT" || true
grep -q 'demo-feishu' "$AUDIT"
grep -q 'demo-dt' "$AUDIT"
grep -q 'demo-wc' "$AUDIT"

echo
echo "demo-ask-reply OK — see docs/intranet-demo.md"
