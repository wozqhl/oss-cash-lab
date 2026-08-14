#!/usr/bin/env bash
# Prove OSS hygiene files: NOTICE + .editorconfig + SECURITY.md + CODE_OF_CONDUCT.md
# (no restyle of the tree).
# Asserts files exist, NOTICE names the project, editorconfig has root + indent_size,
# SECURITY.md covers private vulnerability reporting,
# CODE_OF_CONDUCT.md is Contributor Covenant (or 行为准则) with enforcement / 执行.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

fail() { echo "FAIL: $*" >&2; exit 1; }

[[ -f "$ROOT/LICENSE" ]] || fail "LICENSE missing"
[[ -f "$ROOT/NOTICE" ]] || fail "NOTICE missing"
[[ -f "$ROOT/.editorconfig" ]] || fail ".editorconfig missing"
[[ -f "$ROOT/SECURITY.md" ]] || fail "SECURITY.md missing"
[[ -f "$ROOT/CODE_OF_CONDUCT.md" ]] || fail "CODE_OF_CONDUCT.md missing"

grep -q "oss-cash-lab" "$ROOT/NOTICE" || fail "NOTICE must contain project name oss-cash-lab"
grep -q "Licensed under the Apache License, Version 2.0" "$ROOT/NOTICE" \
  || fail "NOTICE must say Licensed under the Apache License, Version 2.0"
grep -q "2026" "$ROOT/NOTICE" || fail "NOTICE must include copyright year 2026"

grep -q "root = true" "$ROOT/.editorconfig" || fail ".editorconfig must have root = true"
grep -q "indent_size" "$ROOT/.editorconfig" || fail ".editorconfig must have indent_size"

if [[ -f "$ROOT/.gitattributes" ]]; then
  grep -q "eol=lf" "$ROOT/.gitattributes" || fail ".gitattributes present but missing eol=lf"
fi

if ! grep -q "Security Advisories" "$ROOT/SECURITY.md" && ! grep -qi "vulnerability" "$ROOT/SECURITY.md"; then
  fail "SECURITY.md must mention Security Advisories or vulnerability"
fi
if ! grep -qi "Apache" "$ROOT/SECURITY.md" && ! grep -qi "portfolio" "$ROOT/SECURITY.md"; then
  fail "SECURITY.md must mention Apache or portfolio"
fi

if ! grep -q "Contributor Covenant" "$ROOT/CODE_OF_CONDUCT.md" && ! grep -q "行为准则" "$ROOT/CODE_OF_CONDUCT.md"; then
  fail "CODE_OF_CONDUCT.md must mention Contributor Covenant or 行为准则"
fi
if ! grep -qi "enforcement" "$ROOT/CODE_OF_CONDUCT.md" && ! grep -q "执行" "$ROOT/CODE_OF_CONDUCT.md"; then
  fail "CODE_OF_CONDUCT.md must mention enforcement or 执行"
fi

echo "oss hygiene OK (NOTICE + .editorconfig + SECURITY.md + CODE_OF_CONDUCT.md)"
