#!/usr/bin/env bash
# Shared helpers for local IM approval demos (Feishu / DingTalk / WeCom).
# Source from demo-*-approval.sh. No vendor network. Mock tokens only.
# Expects: ROOT, PYTHONPATH=src, cwd=$ROOT.

_DEMO_PID=""

demo_approval_usage() {
  cat <<'EOF'
Usage: demo-*-approval.sh [--platform feishu|dingtalk|wecom|all]

Local 请假 + 用印 approval loop. Mock verify tokens, no Feishu / DingTalk / WeCom network.

  (no args / --platform feishu)   Feishu interactive card
  --platform dingtalk             DingTalk actionCard
  --platform wecom                WeCom textcard
  --platform all                  run all three, isolated

Env: PORT (default 8793/8794/8795 per platform).
EOF
}

demo_approval_cleanup() {
  if [[ -n "${_DEMO_PID:-}" ]]; then
    kill "$_DEMO_PID" 2>/dev/null || true
    wait "$_DEMO_PID" 2>/dev/null || true
    _DEMO_PID=""
  fi
}

demo_approval_port() {
  local plat="$1"
  if [[ -n "${PORT:-}" ]]; then
    echo "$PORT"
    return
  fi
  case "$plat" in
    feishu) echo 8793 ;;
    dingtalk) echo 8794 ;;
    wecom) echo 8795 ;;
    *) echo 8793 ;;
  esac
}

demo_approval_write_config() {
  local plat="$1"
  local cfg="$2"
  python3 - "$plat" "$cfg" <<'PY'
import json
import sys
from pathlib import Path

plat, cfg = sys.argv[1], Path(sys.argv[2])
ex = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
ex["feishu"] = {"verify_token": "demo-feishu-token", "encrypt_key": "demo-feishu-encrypt"}
ex["dingtalk"] = {"token": "demo-dt-token", "secret": "demo-dt-secret"}
ex["wecom"] = {"token": "demo-wc-token"}
ex["platforms"] = [plat]
cfg.parent.mkdir(parents=True, exist_ok=True)
cfg.write_text(json.dumps(ex, indent=2) + "\n", encoding="utf-8")
print(f"wrote {cfg} ({plat}-only, example-shaped tokens)")
PY
}

demo_approval_post() {
  local plat="$1"
  local body_file="$2"
  local ts="$3"
  local nonce="${4:-}"
  local port="$5"
  case "$plat" in
    feishu)
      export FEISHU_ENCRYPT_KEY=demo-feishu-encrypt
      export FEISHU_TS="$ts" FEISHU_NONCE="$nonce"
      mapfile -t SIG < <(python3 scripts/sign_feishu.py "$(cat "$body_file")")
      curl -sf -X POST "http://127.0.0.1:${port}/webhook/feishu" \
        -H 'content-type: application/json' \
        -H "X-Lark-Request-Timestamp: ${SIG[0]}" \
        -H "X-Lark-Request-Nonce: ${SIG[1]}" \
        -H "X-Lark-Signature: ${SIG[2]}" \
        --data-binary @"$body_file"
      ;;
    dingtalk)
      export DINGTALK_SECRET=demo-dt-secret
      export DINGTALK_TS="$ts"
      mapfile -t SIG < <(python3 scripts/sign_dingtalk.py)
      curl -sf -X POST "http://127.0.0.1:${port}/webhook/dingtalk" \
        -H 'content-type: application/json' \
        -H "X-DingTalk-Timestamp: ${SIG[0]}" \
        -H "X-DingTalk-Sign: ${SIG[1]}" \
        --data-binary @"$body_file"
      ;;
    wecom)
      export WECOM_TOKEN=demo-wc-token
      export WECOM_TS="$ts" WECOM_NONCE="$nonce"
      mapfile -t SIG < <(python3 scripts/sign_wecom.py "$(cat "$body_file")")
      curl -sf -X POST \
        "http://127.0.0.1:${port}/webhook/wecom?msg_signature=${SIG[2]}&timestamp=${SIG[0]}&nonce=${SIG[1]}" \
        -H 'content-type: application/json' \
        --data-binary @"$body_file"
      ;;
    *)
      echo "unknown platform for post: $plat" >&2
      return 2
      ;;
  esac
}

demo_approval_write_leave_body() {
  local plat="$1"
  local out="$2"
  case "$plat" in
    feishu)
      printf '%s' '{"text":"请审批请假 明天一天","token":"demo-feishu-token"}' > "$out"
      ;;
    dingtalk)
      printf '%s' '{"text":{"content":"请审批请假 明天一天"},"token":"demo-dt-token"}' > "$out"
      ;;
    wecom)
      printf '%s' '{"Content":"请审批请假 明天一天"}' > "$out"
      ;;
  esac
}

demo_approval_write_seal_body() {
  local plat="$1"
  local out="$2"
  case "$plat" in
    feishu)
      printf '%s' '{"text":"请审批用印 合同盖章","token":"demo-feishu-token"}' > "$out"
      ;;
    dingtalk)
      printf '%s' '{"text":{"content":"请审批用印 合同盖章"},"token":"demo-dt-token"}' > "$out"
      ;;
    wecom)
      printf '%s' '{"Content":"请审批用印 合同盖章"}' > "$out"
      ;;
  esac
}

demo_approval_assert_card() {
  local plat="$1"
  local card="$2"
  local approval_id="$3"
  echo "$card" | python3 -m json.tool
  echo "$card" | grep -q "$approval_id"
  echo "$card" | grep -q Approve
  echo "$card" | grep -q Reject
  python3 -c 'import json,sys; c=json.loads(sys.argv[1]); assert "sk-" not in json.dumps(c)' "$card"
  case "$plat" in
    feishu)
      echo "$card" | grep -q interactive
      echo "$card" | grep -q header
      echo "$card" | grep -q elements
      ;;
    dingtalk)
      echo "$card" | grep -q actionCard
      echo "$card" | grep -qE '"msgtype":\s*"actionCard"|"msgtype":"actionCard"'
      echo "$card" | grep -q btns
      ;;
    wecom)
      echo "$card" | grep -q textcard
      echo "$card" | grep -qE '"msgtype":\s*"textcard"|"msgtype":"textcard"'
      echo "$card" | grep -q btntxt
      ;;
  esac
}

demo_approval_cn_name() {
  case "$1" in
    feishu) echo 飞书 ;;
    dingtalk) echo 钉钉 ;;
    wecom) echo 企微 ;;
    *) echo "$1" ;;
  esac
}

demo_approval_run_one() {
  local plat="$1"
  local cn
  cn="$(demo_approval_cn_name "$plat")"
  local port
  port="$(demo_approval_port "$plat")"
  local prefix="${plat}-appr"
  local audit="$ROOT/data/${prefix}-audit.jsonl"
  local cfg="$ROOT/data/${prefix}-config.json"
  local log="$ROOT/data/${prefix}-server.log"
  local approvals="$ROOT/data/${prefix}-approvals.jsonl"
  local leave_body="/tmp/f-${plat}-leave.json"
  local seal_body="/tmp/f-${plat}-seal.json"

  mkdir -p "$ROOT/data"
  rm -f "$audit" "$log" "$approvals"
  demo_approval_write_config "$plat" "$cfg"

  unset FEISHU_VERIFY_TOKEN FEISHU_ENCRYPT_KEY DINGTALK_TOKEN DINGTALK_SECRET WECOM_TOKEN || true
  unset FEISHU_CALLBACK_SECRET DINGTALK_CALLBACK_SECRET WECOM_CALLBACK_SECRET || true
  unset APPROVAL_CALLBACK_SECRET APPROVAL_WEBHOOK_URL APPROVAL_WEBHOOK_SECRET || true

  demo_approval_cleanup
  python3 -m cn_work_agent serve \
    --config "$cfg" \
    --port "$port" \
    --audit "$audit" \
    --approvals "$approvals" \
    --platform "$plat" \
    >"$log" 2>&1 &
  _DEMO_PID=$!

  local ready=0
  local i
  for i in $(seq 1 50); do
    if curl -sf "http://127.0.0.1:${port}/health" >/dev/null; then
      ready=1
      break
    fi
    sleep 0.1
  done
  if [[ "$ready" != 1 ]]; then
    echo "server did not become healthy on port $port ($plat)" >&2
    if [[ -f "$log" ]]; then
      echo "---- server log ----" >&2
      cat "$log" >&2 || true
    fi
    return 1
  fi

  local health
  health="$(curl -sf "http://127.0.0.1:${port}/health")"
  echo "==> health ($plat)"
  echo "$health"
  echo "$health" | grep -qE '"ok":\s*true|"ok":true'
  echo "$health" | grep -q "$plat"

  echo
  echo "==> [1] 创建请假审批 ($cn mock webhook, no vendor network)"
  demo_approval_write_leave_body "$plat" "$leave_body"
  local leave_ts leave_nonce
  case "$plat" in
    feishu) leave_ts=1710002001; leave_nonce=demo-leave-n1 ;;
    dingtalk) leave_ts=1710002101; leave_nonce= ;;
    wecom) leave_ts=1710002201; leave_nonce=demo-leave-wn1 ;;
  esac
  local leave_resp
  leave_resp="$(demo_approval_post "$plat" "$leave_body" "$leave_ts" "$leave_nonce" "$port")"
  echo "leave_create=$leave_resp"
  echo "$leave_resp" | grep -q approval
  echo "$leave_resp" | grep -q pending
  local leave_id
  leave_id="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["approval_id"])' <<<"$leave_resp")"
  echo "leave_id=$leave_id"
  test -n "$leave_id"

  echo
  echo "==> [2] 渲染 ${cn} 卡片 (GET /v1/approvals/{id}/card?platform=${plat})"
  local card
  card="$(curl -sf "http://127.0.0.1:${port}/v1/approvals/${leave_id}/card?platform=${plat}")"
  demo_approval_assert_card "$plat" "$card" "$leave_id"

  echo
  echo "==> [3] 创建用印审批"
  demo_approval_write_seal_body "$plat" "$seal_body"
  local seal_ts seal_nonce
  case "$plat" in
    feishu) seal_ts=1710002002; seal_nonce=demo-seal-n1 ;;
    dingtalk) seal_ts=1710002102; seal_nonce= ;;
    wecom) seal_ts=1710002202; seal_nonce=demo-seal-wn1 ;;
  esac
  local seal_resp
  seal_resp="$(demo_approval_post "$plat" "$seal_body" "$seal_ts" "$seal_nonce" "$port")"
  echo "seal_create=$seal_resp"
  local seal_id
  seal_id="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["approval_id"])' <<<"$seal_resp")"
  echo "seal_id=$seal_id"
  test -n "$seal_id"

  echo
  echo "==> [4] GET /v1/approvals?status=pending (两单待批)"
  local pend
  pend="$(curl -sf "http://127.0.0.1:${port}/v1/approvals?status=pending")"
  echo "$pend" | python3 -m json.tool
  echo "$pend" | grep -q "$leave_id"
  echo "$pend" | grep -q "$seal_id"
  python3 -c 'import json,sys; d=json.loads(sys.argv[1]); assert d.get("ok") is True and d.get("count")==2, d' "$pend"

  echo
  echo "==> [5] 批准请假 POST /approvals/{id}/decide"
  local leave_decide
  leave_decide="$(curl -sf -X POST "http://127.0.0.1:${port}/approvals/${leave_id}/decide" \
    -H 'content-type: application/json' \
    -d '{"decision":"approve","note":"请假准假"}')"
  echo "leave_decide=$leave_decide"
  echo "$leave_decide" | grep -qE '"ok":\s*true|"ok":true'
  echo "$leave_decide" | grep -q approved

  echo
  echo "==> [6] 驳回用印"
  local seal_decide
  seal_decide="$(curl -sf -X POST "http://127.0.0.1:${port}/approvals/${seal_id}/decide" \
    -H 'content-type: application/json' \
    -d '{"decision":"reject","note":"用印材料不全"}')"
  echo "seal_decide=$seal_decide"
  echo "$seal_decide" | grep -qE '"ok":\s*true|"ok":true'
  echo "$seal_decide" | grep -q rejected

  echo
  echo "==> [7] GET /v1/approvals?status= 过滤"
  echo "--- ?status=pending (应为 0) ---"
  local pend2
  pend2="$(curl -sf "http://127.0.0.1:${port}/v1/approvals?status=pending")"
  echo "$pend2"
  python3 -c 'import json,sys; d=json.loads(sys.argv[1]); assert d.get("ok") is True and d.get("count")==0 and d.get("approvals")==[], d' "$pend2"

  echo "--- ?status=approved (请假) ---"
  local ok
  ok="$(curl -sf "http://127.0.0.1:${port}/v1/approvals?status=approved")"
  echo "$ok" | python3 -m json.tool
  echo "$ok" | grep -q "$leave_id"
  if echo "$ok" | grep -q "$seal_id"; then
    echo "rejected 用印 leaked into ?status=approved"
    return 1
  fi

  echo "--- ?status=rejected (用印) ---"
  local rej
  rej="$(curl -sf "http://127.0.0.1:${port}/v1/approvals?status=rejected")"
  echo "$rej" | python3 -m json.tool
  echo "$rej" | grep -q "$seal_id"
  if echo "$rej" | grep -q "$leave_id"; then
    echo "approved 请假 leaked into ?status=rejected"
    return 1
  fi

  demo_approval_cleanup
  echo
  echo "demo-${plat}-approval OK — 请假已批 / 用印已驳；无真实${cn}网络"
  echo "see docs/cn-onprem.md"
}

demo_approval_parse_platform() {
  local default_plat="${1:-feishu}"
  shift || true
  local plat="$default_plat"
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --platform)
        plat="${2:?--platform needs feishu|dingtalk|wecom|all}"
        shift 2
        ;;
      --platform=*)
        plat="${1#*=}"
        shift
        ;;
      *)
        echo "unknown arg: $1" >&2
        demo_approval_usage >&2
        return 2
        ;;
    esac
  done
  case "$plat" in
    feishu|dingtalk|wecom|all)
      echo "$plat"
      ;;
    *)
      echo "unknown --platform: $plat (want feishu|dingtalk|wecom|all)" >&2
      return 2
      ;;
  esac
}

demo_approval_main() {
  local default_plat="${1:-feishu}"
  shift || true
  local arg
  for arg in "$@"; do
    if [[ "$arg" == "-h" || "$arg" == "--help" ]]; then
      demo_approval_usage
      return 0
    fi
  done
  local plat
  local parse_rc=0
  plat="$(demo_approval_parse_platform "$default_plat" "$@")" || parse_rc=$?
  if [[ "$parse_rc" != 0 ]]; then
    return "$parse_rc"
  fi

  trap demo_approval_cleanup EXIT

  if [[ "$plat" == all ]]; then
    local p
    for p in feishu dingtalk wecom; do
      echo
      echo "======== platform=$p ========"
      demo_approval_run_one "$p"
    done
    echo
    echo "demo-approval OK — feishu + dingtalk + wecom；无厂商公网"
    echo "see docs/cn-onprem.md"
    return 0
  fi
  demo_approval_run_one "$plat"
}
