#!/usr/bin/env bash
# Buyer-facing CRA Article 14 calendar clock demo (not a certificate).
# From bets/d-ai-bom: bash scripts/demo-cra-clock.sh
# 日历/证据辅助，不是 CRA 合格证书 / calendar helper, not a CRA compliance certificate.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${PYTHONPATH:-src}"

banner() {
  echo ""
  echo "════════════════════════════════════════════════════════════"
  echo "  AI-BOM · CRA Article 14 calendar clock (buyer demo)"
  echo "  日历/证据辅助，不是 CRA 合格证书"
  echo "  Calendar/evidence helper — NOT a CRA compliance certificate"
  echo "  Window: Article 14-style reporting → 2026-09-11"
  echo "════════════════════════════════════════════════════════════"
  echo ""
}

banner

echo "==> clock --format text (as-of today UTC)"
python3 -m ai_bom clock --format text
echo ""

echo "==> clock --format md (ticket paste; calendar helper only)"
python3 -m ai_bom clock --format md --as-of 2026-09-08 | head -n 12
echo ""

SAMPLE_DIR="examples/sample-app"
SAMPLE_ADV="examples/advisories/sample.json"
if [[ -d "$SAMPLE_DIR" && -f "$SAMPLE_ADV" ]]; then
  echo "==> clock with sample-app + local advisories fixture (optional)"
  python3 -m ai_bom clock --format text --dir "$SAMPLE_DIR" --advisories "$SAMPLE_ADV"
  echo ""
fi

echo "—— What to show a buyer / 给买家看什么 ——"
echo "1. Paste examples/github-actions/ai-bom-clock.yml into consumer CI"
echo "   (clock --format gha → ::notice / ::warning; never ::error; exit 0)."
echo "2. evidence-pack --dir DIR --out OUTDIR [--zip] for an auditor zip"
echo "   (pack.json clock + CycloneDX/SPDX/OpenVEX — inventory helper only)."
echo "3. Countdown to 2026-09-11 is a calendar offset, not a conformity gate."
echo "4. Never say compliant / certified / 合格 / 认证 — this is not a certificate."
echo "5. Optional: ai-bom clock --format gha  for live CI annotations."
echo "6. Optional: ai-bom clock --format md / --format ics for ticket paste or calendar subscribe."
echo ""
echo "demo-cra-clock done (calendar helper only)."
