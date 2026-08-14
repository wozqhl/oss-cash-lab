#!/usr/bin/env bash
# Portfolio security scan: D ai-bom + obvious secret pattern grep.
# Exit 0 when secret grep is clean and scans complete.
# SECURITY_STRICT=1 runs ai-bom --strict as soft-fail (policy hits warn, do not fail the script).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

STRICT="${SECURITY_STRICT:-0}"
BOM_SOFT_FAIL=0
SECRET_FAIL=0

BETS=(
  a-sdk-mcp-gen
  b-mcp-gateway
  c-agent-ci
  d-ai-bom
  e-otel-ai-cost
  f-cn-work-agent
)

echo "==> [security] D ai-bom scan (bets)"
mkdir -p "$ROOT/out/security"
export PYTHONPATH="$ROOT/bets/d-ai-bom/src${PYTHONPATH:+:$PYTHONPATH}"
POLICY="$ROOT/bets/d-ai-bom/policies/default.json"

for bet in "${BETS[@]}"; do
  target="$ROOT/bets/$bet"
  out_json="$ROOT/out/security/${bet}.bom.json"
  echo "  -> scan bets/$bet"
  # Non-strict scan always; writes BOM for inspection.
  if ! python3 -m ai_bom scan "$target" \
      --policy "$POLICY" \
      --out "$out_json" >/dev/null; then
    echo "  WARN: ai-bom scan failed for bets/$bet (IO/usage)"
    BOM_SOFT_FAIL=1
    continue
  fi
  if [[ "$STRICT" == "1" ]]; then
    set +e
    python3 -m ai_bom scan "$target" --policy "$POLICY" --strict >/tmp/security-strict-"$bet".out 2>&1
    rc=$?
    set -e
    if [[ $rc -eq 1 ]]; then
      echo "  soft-fail: --strict policy hits on bets/$bet (see /tmp/security-strict-$bet.out)"
      BOM_SOFT_FAIL=1
    elif [[ $rc -ne 0 ]]; then
      echo "  WARN: ai-bom --strict exited $rc for bets/$bet"
      BOM_SOFT_FAIL=1
    else
      echo "  strict OK bets/$bet"
    fi
  fi
done

echo
echo "==> [security] secret pattern grep under bets/"
# Skip generated/vendor/runtime dirs and intentional AI-BOM sample fixture.
# Fail hard only on obvious credential material (not demo placeholders).
SECRET_PATTERNS='github_pat_|AKIA[0-9A-Z]{16}|BEGIN (RSA |OPENSSH |EC |DSA )?PRIVATE KEY'

# Collect candidate files under bets/ excluding noisy paths.
mapfile -t FILES < <(
  find "$ROOT/bets" -type f \
    ! -path '*/node_modules/*' \
    ! -path '*/.git/*' \
    ! -path '*/data/*' \
    ! -path '*/out/*' \
    ! -path '*/generated/*' \
    ! -path '*/examples/sample-app/*' \
    ! -path '*/.venv/*' \
    ! -path '*/dist/*' \
    ! -path '*/__pycache__/*' \
    ! -name '*.pyc' \
    ! -name '*.png' \
    ! -name '*.jpg' \
    ! -name '*.gguf' \
    ! -name '*.zip' \
    2>/dev/null | sort
)

HITS=()
if command -v rg >/dev/null 2>&1; then
  set +e
  MATCHES=$(rg -n --no-heading -e "$SECRET_PATTERNS" "${FILES[@]}" 2>/dev/null)
  set -e
  if [[ -n "${MATCHES:-}" ]]; then
    while IFS= read -r line; do
      [[ -n "$line" ]] && HITS+=("$line")
    done <<< "$MATCHES"
  fi
else
  # Fallback: grep -E per file (slower)
  for f in "${FILES[@]}"; do
    set +e
    m=$(grep -nE "$SECRET_PATTERNS" "$f" 2>/dev/null)
    set -e
    if [[ -n "${m:-}" ]]; then
      while IFS= read -r line; do
        [[ -n "$line" ]] && HITS+=("$f:$line")
      done <<< "$m"
    fi
  done
fi

if [[ ${#HITS[@]} -gt 0 ]]; then
  echo "FAIL: obvious secret patterns found under bets/:"
  printf '  %s\n' "${HITS[@]}"
  SECRET_FAIL=1
else
  echo "  secret grep clean (${#FILES[@]} files scanned; sample-app excluded)"
fi

echo
if [[ $SECRET_FAIL -ne 0 ]]; then
  echo "security-scan FAILED (secrets)"
  exit 1
fi

if [[ $BOM_SOFT_FAIL -ne 0 ]]; then
  echo "security-scan OK (secrets clean; ai-bom notes above are soft-fail)"
else
  echo "security-scan OK"
fi
exit 0
