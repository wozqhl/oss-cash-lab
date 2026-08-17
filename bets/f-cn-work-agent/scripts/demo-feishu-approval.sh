#!/usr/bin/env bash
# Local Feishu approval demo (请假 + 用印). No real Feishu network.
# Mock verify via scripts/sign_feishu.py + config.example.json tokens.
# Also: --platform dingtalk|wecom|all (same leave/seal path, no vendor network).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH=src
# shellcheck source=demo-approval-lib.sh
source "$ROOT/scripts/demo-approval-lib.sh"
demo_approval_main feishu "$@"
