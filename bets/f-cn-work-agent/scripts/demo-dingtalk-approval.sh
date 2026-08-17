#!/usr/bin/env bash
# Local DingTalk approval demo (请假 + 用印). No real DingTalk network.
# Reuses scripts/demo-approval-lib.sh + sign_dingtalk.py mock tokens.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH=src
# shellcheck source=demo-approval-lib.sh
source "$ROOT/scripts/demo-approval-lib.sh"
demo_approval_main dingtalk "$@"
