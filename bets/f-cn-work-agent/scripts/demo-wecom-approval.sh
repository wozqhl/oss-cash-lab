#!/usr/bin/env bash
# Local WeCom approval demo (请假 + 用印). No real WeCom network.
# Reuses scripts/demo-approval-lib.sh + sign_wecom.py mock tokens.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH=src
# shellcheck source=demo-approval-lib.sh
source "$ROOT/scripts/demo-approval-lib.sh"
demo_approval_main wecom "$@"
