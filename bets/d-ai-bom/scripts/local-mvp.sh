#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH=src
unset AI_BOM_WEBHOOK_URL || true
unset AI_BOM_WEBHOOK_SECRET || true
unset AI_BOM_EXCEPTIONS || true

python3 -m ai_bom smoke

rm -f out/bom.json out/evidence.md out/bom.sarif
mkdir -p out

test -f examples/sample-app/package.json
grep -q '"license": "MIT"' examples/sample-app/package.json
echo "==> scan with policy + evidence + sarif"
python3 -m ai_bom scan examples/sample-app \
  --policy policies/default.json \
  --out out/bom.json \
  --evidence out/evidence.md \
  --sarif out/bom.sarif
test -f out/bom.json
test -f out/evidence.md
test -f out/bom.sarif
python3 scripts/check_bom.py

# evidence pack checks
grep -q "DRAFT" out/evidence.md
grep -Eqi "policy hit|禁止模式|pickle" out/evidence.md
grep -q "Exit guidance" out/evidence.md
python3 - <<"PY"
import json
from pathlib import Path
bom = json.loads(Path("out/bom.json").read_text())
assert bom["metadata"].get("policy", {}).get("name") == "default"
hits = bom["summary"].get("policyHits", 0)
assert hits >= 1, bom["summary"]
forbidden = bom["summary"].get("forbidden") or []
assert any("pickle" in (h.get("pattern") or "") for h in forbidden), forbidden
ev = Path("out/evidence.md").read_text()
assert "AI-BOM Compliance Evidence" in ev
assert "组件" in ev or "组件摘要" in ev
print("evidence + policy hit ok", hits)
# SPDX license fields
assert any(
    (e.get("license") or {}).get("id") == "MIT"
    for c in bom.get("components") or []
    for e in (c.get("licenses") or [])
), "bom.json must include MIT from sample-app/package.json"
assert "MIT" in Path("out/bom.json").read_text()
assert (bom.get("summary") or {}).get("licenses", {}).get("MIT", 0) >= 1
assert "License summary" in ev or "许可证摘要" in ev
print("license SPDX ok", bom["summary"].get("licenses"))
PY

echo "==> scan --format spdx (SPDX 2.3 JSON)"
python3 -m ai_bom scan examples/sample-app \
  --policy policies/default.json \
  --format spdx \
  --out out/bom.spdx.json
test -f out/bom.spdx.json
python3 - <<"PYSPDX"
import json
from pathlib import Path
doc = json.loads(Path("out/bom.spdx.json").read_text())
assert doc.get("spdxVersion") == "SPDX-2.3", doc.get("spdxVersion")
assert isinstance(doc.get("packages"), list) and doc["packages"], "packages"
assert isinstance(doc.get("documentNamespace"), str) and doc["documentNamespace"]
assert "summary" not in doc
print("cli --format spdx ok", doc["spdxVersion"], "packages=", len(doc["packages"]))
PYSPDX

echo "==> scan --format spdx3 (SPDX 3.0.1 JSON)"
python3 -m ai_bom scan examples/sample-app \
  --policy policies/default.json \
  --format spdx3 \
  --out out/bom.spdx3.json
test -f out/bom.spdx3.json
python3 - <<"PYSPDX3"
import json
from pathlib import Path
doc = json.loads(Path("out/bom.spdx3.json").read_text())
ci = doc.get("creationInfo") or {}
assert ci.get("specVersion") == "3.0.1", ci
assert doc.get("type") == "SpdxDocument", doc.get("type")
assert isinstance(doc.get("spdxId"), str) and doc["spdxId"]
assert isinstance(doc.get("name"), str) and doc["name"]
elems = [e for e in (doc.get("element") or []) if isinstance(e, dict)]
pkgs = [e for e in elems if str(e.get("type") or "").endswith("Package")]
assert pkgs, "expected software_Package elements"
assert any("LicenseExpression" in str(e.get("type") or "") for e in elems)
assert "summary" not in doc
print("cli --format spdx3 ok", ci["specVersion"], "packages=", len(pkgs))
PYSPDX3

echo "==> scan --format cyclonedx (CycloneDX 1.7 JSON)"
python3 -m ai_bom scan examples/sample-app \
  --policy policies/default.json \
  --format cyclonedx \
  --out out/bom.cdx.json
test -f out/bom.cdx.json
python3 - <<"PYCDXJSON"
import json
from pathlib import Path
cdx = json.loads(Path("out/bom.cdx.json").read_text())
assert cdx.get("bomFormat") == "CycloneDX", cdx.get("bomFormat")
assert cdx.get("specVersion") == "1.7", cdx.get("specVersion")
assert "summary" not in cdx
ml = [c for c in (cdx.get("components") or []) if c.get("type") == "machine-learning-model"]
assert ml, "expected machine-learning-model components"
assert any(
    any(p.get("name") == "aibom:format" and p.get("value") == "gguf"
        for p in ((c.get("modelCard") or {}).get("properties") or []))
    for c in ml
), "expected gguf modelCard from scan data"
assert any(isinstance(c.get("licenses"), list) and c["licenses"] for c in ml)
print("cli --format cyclonedx ok", cdx["specVersion"], "ml=", len(ml))
PYCDXJSON

echo "==> scan --format cyclonedx-xml (CycloneDX 1.7 XML)"
python3 -m ai_bom scan examples/sample-app \
  --policy policies/default.json \
  --format cyclonedx-xml \
  --out out/bom.cdx.xml
test -f out/bom.cdx.xml
python3 - <<"PYCDXXML"
from pathlib import Path
xml = Path("out/bom.cdx.xml").read_text()
assert xml.lstrip().startswith("<bom"), xml[:80]
assert 'xmlns="http://cyclonedx.org/schema/bom/1.7"' in xml
assert "ai-bom-sample-app" in xml or "gpt-4o-mini" in xml, xml[:400]
assert "<components" in xml
print("cli --format cyclonedx-xml ok")
PYCDXXML

echo "==> scan --format spdx-xml (SPDX 2.3 XML)"
python3 -m ai_bom scan examples/sample-app \
  --policy policies/default.json \
  --format spdx-xml \
  --out out/bom.spdx.xml
test -f out/bom.spdx.xml
python3 - <<"PYSPDXXML"
from pathlib import Path
xml = Path("out/bom.spdx.xml").read_text()
assert xml.lstrip().startswith("<SpdxDocument"), xml[:80]
assert "SPDX-2.3" in xml
assert "<packages" in xml
assert "<licenseConcluded" in xml
assert "ai-bom-sample-app" in xml or "gpt-4o-mini" in xml, xml[:400]
print("cli --format spdx-xml ok")
PYSPDXXML

echo "==> scan --format md (human/Slack Markdown summary)"
python3 -m ai_bom scan examples/sample-app \
  --policy policies/default.json \
  --format md \
  --out out/bom.md
test -f out/bom.md
python3 - <<"PYMD"
from pathlib import Path
md = Path("out/bom.md").read_text()
assert md.lstrip().startswith("# "), md[:80]
assert "# AI-BOM" in md
assert "policyHits" in md
assert "MIT" in md or "gpt-4o-mini" in md or "pickle" in md, md[:600]
print("cli --format md ok")
PYMD

echo "==> scan --format html (self-contained HTML BOM summary)"
python3 -m ai_bom scan examples/sample-app \
  --policy policies/default.json \
  --format html \
  --out out/bom.html
test -f out/bom.html
python3 - <<"PYHTML"
from pathlib import Path
html = Path("out/bom.html").read_text()
assert "<table" in html or "AI-BOM" in html, html[:400]
assert "AI-BOM" in html
assert "<h1" in html
assert "pickle" in html or "MIT" in html or "gpt-4o-mini" in html or "Policy hits" in html, html[:800]
print("cli --format html ok")
PYHTML

echo "==> scan --format gha (GitHub Actions workflow commands)"
python3 -m ai_bom scan examples/sample-app \
  --policy policies/default.json \
  --format gha \
  --out out/bom.gha.txt
test -f out/bom.gha.txt
python3 - <<"PYGHA"
from pathlib import Path
gha = Path("out/bom.gha.txt").read_text()
assert "::error" in gha, gha[:400]
assert "title=" in gha
assert "pickle.load" in gha or "pickle" in gha, gha[:600]
print("cli --format gha ok")
PYGHA

echo "==> cli policy (active gate JSON; GPL-3.0 from default pack)"
python3 -m ai_bom policy examples/sample-app --policy policies/default.json > out/cli-policy.json
test -s out/cli-policy.json
python3 - <<"PYPOLCLI"
import json
from pathlib import Path
d = json.loads(Path("out/cli-policy.json").read_text())
assert d.get("ok") is True, d
assert "GPL-3.0" in (d.get("forbiddenLicenseIds") or []), d
assert "pickle.load" in (d.get("forbiddenPatterns") or []), d
assert isinstance(d.get("exceptionsCount"), int)
assert isinstance(d.get("ignoreFile"), bool)
raw = Path("out/cli-policy.json").read_text()
assert r"\bpickle" not in raw
assert "vendor approved" not in raw
print("cli policy ok", {"ids": len(d["forbiddenLicenseIds"]), "patterns": d.get("forbiddenPatterns")})
PYPOLCLI

echo "==> scan --format sarif (SARIF 2.1.0; --sarif PATH still independent)"
python3 -m ai_bom scan examples/sample-app \
  --policy policies/default.json \
  --format sarif \
  --out out/bom.format.sarif
test -f out/bom.format.sarif
python3 - <<"PYFMT"
import json
from pathlib import Path
doc = json.loads(Path("out/bom.format.sarif").read_text())
assert doc.get("version") == "2.1.0", doc.get("version")
assert isinstance(doc.get("runs"), list) and doc["runs"]
schema = str(doc.get("$schema") or "")
assert "sarif" in schema.lower() or doc.get("version") == "2.1.0", schema
print("cli --format sarif ok", doc["version"], "runs=", len(doc["runs"]))
PYFMT

echo "==> SARIF 2.1.0 checks"
python3 - <<"PY"
import json
from pathlib import Path
sarif = json.loads(Path("out/bom.sarif").read_text())
assert sarif.get("version") == "2.1.0", sarif.get("version")
schema = sarif.get("$schema") or ""
assert "sarif" in schema.lower() or sarif.get("version") == "2.1.0", schema
runs = sarif.get("runs") or []
assert runs, "runs empty"
results = runs[0].get("results") or []
assert results, "results must be non-empty on sample-app with pickle"
assert any(r.get("ruleId") == "pickle.load" for r in results), [r.get("ruleId") for r in results]
pickle_hits = [r for r in results if r.get("ruleId") == "pickle.load"]
loc = (pickle_hits[0].get("locations") or [{}])[0]
phys = loc.get("physicalLocation") or {}
uri = (phys.get("artifactLocation") or {}).get("uri") or ""
assert uri.endswith("app.py") or "app.py" in uri, uri
region = phys.get("region") or {}
assert isinstance(region.get("startLine"), int) and region["startLine"] > 0, region
rules = ((runs[0].get("tool") or {}).get("driver") or {}).get("rules") or []
assert any(r.get("id") == "pickle.load" for r in rules), rules
print("sarif ok", "results=", len(results), "schema=", schema[:60])
PY

echo "==> strict with policy (expect exit 1)"
set +e
python3 -m ai_bom scan examples/sample-app --policy policies/default.json --strict >/tmp/d-strict.out 2>&1
code=$?
set -e
if [ "$code" -eq 0 ]; then
  echo "strict mode should fail on pickle.load"
  cat /tmp/d-strict.out
  exit 1
fi
if [ "$code" -ne 1 ]; then
  echo "expected exit 1, got $code"
  cat /tmp/d-strict.out
  exit 1
fi
grep -qi pickle /tmp/d-strict.out

# built-in fallback still works without --policy
set +e
python3 -m ai_bom scan examples/sample-app --strict >/tmp/d-strict-builtin.out 2>&1
code=$?
set -e
[ "$code" -eq 1 ]
grep -qi pickle /tmp/d-strict-builtin.out


echo "==> .aibomignore + --ignore (vendor pickle skipped; root pickle still flags)"
IGNORE_TMP="$(mktemp -d)"
mkdir -p "$IGNORE_TMP/vendor"
cat > "$IGNORE_TMP/vendor/secret.py" <<"PY"
import pickle
pickle.loads(b"ignored-under-vendor")
PY
cat > "$IGNORE_TMP/root_bad.py" <<"PY"
import pickle
pickle.loads(b"should-flag")
PY
printf "vendor/\n" > "$IGNORE_TMP/.aibomignore"
python3 -m ai_bom scan "$IGNORE_TMP" --out "$IGNORE_TMP/bom.json" >/tmp/d-ignore.out
BOM_JSON="$IGNORE_TMP/bom.json" python3 - <<"PY"
import json, os
from pathlib import Path
bom = json.loads(Path(os.environ["BOM_JSON"]).read_text())
forbidden = bom["summary"].get("forbidden") or []
paths = [(h.get("path") or "").replace("\\", "/") for h in forbidden]
assert not any("/vendor/" in p or p.endswith("vendor/secret.py") for p in paths), paths
assert any("root_bad.py" in p for p in paths), paths
assert any("pickle" in (h.get("pattern") or "") for h in forbidden), forbidden
print("aibomignore ok: vendor skipped, root_bad flagged", paths)
PY
rm -rf "$IGNORE_TMP"

IGNORE_TMP2="$(mktemp -d)"
mkdir -p "$IGNORE_TMP2/node_modules"
cat > "$IGNORE_TMP2/node_modules/x.py" <<"PY"
import pickle
pickle.loads(b"skip-me")
PY
cat > "$IGNORE_TMP2/keep.py" <<"PY"
import pickle
pickle.loads(b"flag-me")
PY
python3 -m ai_bom scan "$IGNORE_TMP2" --ignore "node_modules,dist,.git" --out "$IGNORE_TMP2/bom.json" >/tmp/d-ignore-cli.out
BOM_JSON="$IGNORE_TMP2/bom.json" python3 - <<"PY"
import json, os
from pathlib import Path
bom = json.loads(Path(os.environ["BOM_JSON"]).read_text())
forbidden = bom["summary"].get("forbidden") or []
paths = [(h.get("path") or "").replace("\\", "/") for h in forbidden]
assert not any("node_modules" in p for p in paths), paths
assert any("keep.py" in p for p in paths), paths
print("cli --ignore ok", paths)
PY
rm -rf "$IGNORE_TMP2"


echo "==> MIT sample-app has no forbidden-license hits"
python3 - <<"PY"
import json
from pathlib import Path
bom = json.loads(Path("out/bom.json").read_text())
fl = bom["summary"].get("forbiddenLicenses") or []
assert fl == [], fl
assert (bom.get("summary") or {}).get("licenses", {}).get("MIT", 0) >= 1
ev = Path("out/evidence.md").read_text()
assert "Forbidden license" in ev or "禁止许可证" in ev
sarif = json.loads(Path("out/bom.sarif").read_text())
results = (sarif.get("runs") or [{}])[0].get("results") or []
assert not any(str(r.get("ruleId") or "").startswith("license/") for r in results), [r.get("ruleId") for r in results]
print("MIT sample-app license gate OK (no forbiddenLicense hits)")
PY

echo "==> CRA fixtures: license-pass gate 0; license-fail gate 1"
python3 -m ai_bom scan examples/cra-fixtures/license-pass \
  --policy policies/default.json --gate-licenses >/tmp/d-cra-pass.out
echo "cra_pass_gate=$?"
set +e
python3 -m ai_bom scan examples/sample-app \
  --policy policies/default.json --gate-licenses >/tmp/d-cra-sample-gate.out 2>&1
sample_gate=$?
set -e
if [ "$sample_gate" -ne 0 ]; then
  echo "expected exit 0 for sample-app --gate-licenses (MIT), got $sample_gate"
  cat /tmp/d-cra-sample-gate.out
  exit 1
fi
python3 -m ai_bom scan examples/cra-fixtures/license-pass \
  --policy policies/default.json --strict >/tmp/d-cra-pass-strict.out
echo "cra_pass_strict=$?"
set +e
python3 -m ai_bom scan examples/cra-fixtures/license-fail \
  --policy policies/default.json --gate-licenses >/tmp/d-cra-fail.out 2>&1
fail_gate=$?
python3 -m ai_bom scan examples/cra-fixtures/license-fail \
  --policy policies/default.json --strict \
  --out /tmp/d-cra-fail-bom.json \
  --evidence /tmp/d-cra-fail-evidence.md \
  --sarif /tmp/d-cra-fail.sarif >/tmp/d-cra-fail-strict.out 2>&1
fail_strict=$?
set -e
if [ "$fail_gate" -ne 1 ]; then
  echo "expected exit 1 for license-fail --gate-licenses, got $fail_gate"
  cat /tmp/d-cra-fail.out
  exit 1
fi
if [ "$fail_strict" -ne 1 ]; then
  echo "expected exit 1 for license-fail --strict, got $fail_strict"
  cat /tmp/d-cra-fail-strict.out
  exit 1
fi
grep -Eqi "GPL-3\.0|forbidden license|gate-licenses" /tmp/d-cra-fail.out
python3 - <<"PYCRA"
import json
from pathlib import Path
bom = json.loads(Path("/tmp/d-cra-fail-bom.json").read_text())
fl = bom["summary"].get("forbiddenLicenses") or []
assert any(h.get("licenseId") == "GPL-3.0" for h in fl), fl
assert bom["summary"].get("policyHits", 0) >= 1
ev = Path("/tmp/d-cra-fail-evidence.md").read_text()
assert "GPL-3.0" in ev
sarif = json.loads(Path("/tmp/d-cra-fail.sarif").read_text())
results = (sarif.get("runs") or [{}])[0].get("results") or []
assert any(r.get("ruleId") == "license/GPL-3.0" for r in results), [r.get("ruleId") for r in results]
print("CRA fixtures ok: pass gate 0, fail gate 1, GPL-3.0 in BOM/SARIF")
PYCRA

echo "==> advisory fixtures: planted hit gate 1; clean file gate 0"
set +e
python3 -m ai_bom scan examples/sample-app \
  --advisories examples/advisories/sample.json --gate-vulns >/tmp/d-adv-hit.out 2>&1
hit_gate=$?
python3 -m ai_bom scan examples/sample-app \
  --advisories examples/advisories/clean.json --gate-vulns >/tmp/d-adv-clean.out 2>&1
clean_gate=$?
python3 -m ai_bom scan examples/sample-app --gate-vulns >/tmp/d-adv-miss.out 2>&1
miss_gate=$?
set -e
if [ "$hit_gate" -ne 1 ]; then
  echo "expected exit 1 for sample.json --gate-vulns, got $hit_gate"
  cat /tmp/d-adv-hit.out
  exit 1
fi
if [ "$clean_gate" -ne 0 ]; then
  echo "expected exit 0 for clean.json --gate-vulns, got $clean_gate"
  cat /tmp/d-adv-clean.out
  exit 1
fi
if [ "$miss_gate" -ne 2 ]; then
  echo "expected exit 2 for --gate-vulns without --advisories, got $miss_gate"
  cat /tmp/d-adv-miss.out
  exit 1
fi
grep -q "ADV-FIXTURE-1" /tmp/d-adv-hit.out
grep -Eqi "gate-vulns|advisory" /tmp/d-adv-hit.out
python3 -m ai_bom scan examples/sample-app \
  --advisories examples/advisories/sample.json \
  --out /tmp/d-adv-hit-bom.json >/tmp/d-adv-hit-scan.out
python3 - <<"PYADV"
import json
from pathlib import Path
bom = json.loads(Path("/tmp/d-adv-hit-bom.json").read_text())
hits = (bom.get("summary") or {}).get("advisoryHits") or []
assert any(h.get("id") == "ADV-FIXTURE-1" for h in hits), hits
assert (bom.get("summary") or {}).get("advisoryHitCount", 0) >= 1
print("advisory fixtures ok: planted hit 1, clean 0, missing-file-flag 2")
PYADV

echo "==> convert-advisories --from-osv (offline; range match, not identity-only)"
python3 -m ai_bom convert-advisories --from-osv examples/advisories/osv-sample.json --out /tmp/d-osv-converted.json
test -f /tmp/d-osv-converted.json
python3 - <<"PYOSV"
import json
from pathlib import Path
doc = json.loads(Path("/tmp/d-osv-converted.json").read_text())
assert doc.get("schema") == "ai-bom-advisories/v1", doc.get("schema")
ids = [a.get("id") for a in (doc.get("advisories") or [])]
assert any(str(i).startswith("OSV-") for i in ids), ids
assert not any(str(i).startswith("ADV-FIXTURE-") for i in ids), ids
assert any((a.get("component") or {}).get("name") == "openai" for a in (doc.get("advisories") or [])), doc
rngs = [(a.get("component") or {}).get("versionRange") or "" for a in (doc.get("advisories") or [])]
assert any((">" in r or "<" in r or "=" in r) for r in rngs), rngs
print("osv convert schema ok", ids, rngs)
PYOSV
RANGE_TMP="$(mktemp -d)"
mkdir -p "$RANGE_TMP/in" "$RANGE_TMP/out"
printf "%s\n" "[project]" "name = \"openai\"" "version = \"1.2.3\"" > "$RANGE_TMP/in/pyproject.toml"
printf "%s\n" "[project]" "name = \"openai\"" "version = \"9.9.9\"" > "$RANGE_TMP/out/pyproject.toml"
set +e
python3 -m ai_bom scan "$RANGE_TMP/in" --advisories /tmp/d-osv-converted.json --gate-vulns >/tmp/d-osv-hit.out 2>&1
osv_hit=$?
python3 -m ai_bom scan "$RANGE_TMP/out" --advisories /tmp/d-osv-converted.json --gate-vulns >/tmp/d-osv-miss.out 2>&1
osv_miss=$?
python3 -m ai_bom scan examples/cra-fixtures/license-pass --advisories /tmp/d-osv-converted.json --gate-vulns >/tmp/d-osv-clean.out 2>&1
osv_clean=$?
python3 -m ai_bom scan examples/sample-app --advisories examples/advisories/range-in.json --gate-vulns >/tmp/d-range-in.out 2>&1
range_in=$?
python3 -m ai_bom scan examples/sample-app --advisories examples/advisories/range-out.json --gate-vulns >/tmp/d-range-out.out 2>&1
range_out=$?
set -e
if [ "$osv_hit" -ne 1 ]; then
  echo "expected exit 1 for converted OSV --gate-vulns on in-range version, got $osv_hit"
  cat /tmp/d-osv-hit.out
  exit 1
fi
if [ "$osv_miss" -ne 0 ]; then
  echo "expected exit 0 for converted OSV --gate-vulns on out-of-range version, got $osv_miss"
  cat /tmp/d-osv-miss.out
  exit 1
fi
if [ "$osv_clean" -ne 0 ]; then
  echo "expected exit 0 for converted OSV --gate-vulns on clean tree, got $osv_clean"
  cat /tmp/d-osv-clean.out
  exit 1
fi
if [ "$range_in" -ne 1 ]; then
  echo "expected exit 1 for range-in.json --gate-vulns, got $range_in"
  cat /tmp/d-range-in.out
  exit 1
fi
if [ "$range_out" -ne 0 ]; then
  echo "expected exit 0 for range-out.json --gate-vulns, got $range_out"
  cat /tmp/d-range-out.out
  exit 1
fi
grep -q "OSV-" /tmp/d-osv-hit.out
echo "osv-convert-ok"
echo "range-ok"

echo "==> observed ML-BOM hashes + on-disk model card (no invented fields)"
OBS_TMP="$(mktemp -d)"
NEG_TMP="$(mktemp -d)"
mkdir -p "$OBS_TMP/models"
printf 'tiny-weights\n' > "$OBS_TMP/models/tiny.gguf"
cat > "$OBS_TMP/models/model-card.md" <<'CARD'
# Observed Tiny Model

A fixture description only.

License: https://example.com/observed-license
CARD
printf '%s\n' 'MODEL = "gpt-4o-mini"' > "$NEG_TMP/app.py"
python3 -m ai_bom scan "$OBS_TMP" --format cyclonedx --out "$OBS_TMP/bom.cdx.json"
python3 -m ai_bom scan "$OBS_TMP" --format spdx --out "$OBS_TMP/bom.spdx.json"
python3 -m ai_bom scan "$OBS_TMP" --format spdx3 --out "$OBS_TMP/bom.spdx3.json"
python3 -m ai_bom scan "$NEG_TMP" --format cyclonedx --out "$NEG_TMP/bom.cdx.json"
python3 -m ai_bom scan "$NEG_TMP" --format spdx3 --out "$NEG_TMP/bom.spdx3.json"
OBS_TMP="$OBS_TMP" NEG_TMP="$NEG_TMP" python3 - <<"PYMLBOM"
import hashlib, json, os
from pathlib import Path
obs = Path(os.environ["OBS_TMP"])
neg = Path(os.environ["NEG_TMP"])
want = hashlib.sha256((obs / "models" / "tiny.gguf").read_bytes()).hexdigest()
cdx = json.loads((obs / "bom.cdx.json").read_text())
assert cdx.get("specVersion") == "1.7", cdx.get("specVersion")
ml = [c for c in (cdx.get("components") or []) if c.get("type") == "machine-learning-model"]
assert ml, "expected ML component"
hashed = [c for c in ml if any(
    (h.get("alg") == "SHA-256" and h.get("content") == want)
    for h in (c.get("hashes") or [])
)]
assert hashed, (want, ml)
card_ok = any(
    any(p.get("name") == "aibom:cardName" and p.get("value") == "Observed Tiny Model"
        for p in ((c.get("modelCard") or {}).get("properties") or []))
    or c.get("description") == "A fixture description only."
    for c in ml
)
assert card_ok, ml
assert any(
    (e.get("license") or {}).get("url") == "https://example.com/observed-license"
    for c in ml for e in (c.get("licenses") or [])
) or any(
    any(p.get("name") == "aibom:licenseUrl" and "example.com/observed-license" in str(p.get("value") or "")
        for p in ((c.get("modelCard") or {}).get("properties") or []))
    for c in ml
), ml
blob = json.dumps(cdx)
assert "accuracy" not in blob.lower() or "Observed Tiny Model" in blob
assert "datasets" not in blob
assert "quantitativeAnalysis" not in blob
spdx = json.loads((obs / "bom.spdx.json").read_text())
assert any(
    any(ck.get("algorithm") == "SHA256" and ck.get("checksumValue") == want
        for ck in (pkg.get("checksums") or []))
    for pkg in (spdx.get("packages") or [])
), spdx.get("packages")
spdx3 = json.loads((obs / "bom.spdx3.json").read_text())
assert (spdx3.get("creationInfo") or {}).get("specVersion") == "3.0.1"
elems = [e for e in (spdx3.get("element") or []) if isinstance(e, dict)]
assert any(
    any(h.get("algorithm") == "sha256" and h.get("hashValue") == want
        for h in (e.get("verifiedUsing") or []))
    for e in elems
), "spdx3 missing observed hash"
neg_cdx = json.loads((neg / "bom.cdx.json").read_text())
neg_ml = [c for c in (neg_cdx.get("components") or []) if c.get("type") == "machine-learning-model"]
assert neg_ml, "negative fixture still has a mentioned model"
assert not any(c.get("hashes") for c in neg_ml), neg_ml
assert not any(
    any(p.get("name") in {"aibom:cardName", "aibom:cardDescription", "aibom:licenseUrl"}
        for p in ((c.get("modelCard") or {}).get("properties") or []))
    for c in neg_ml
), neg_ml
neg_spdx3 = json.loads((neg / "bom.spdx3.json").read_text())
neg_elems = [e for e in (neg_spdx3.get("element") or []) if isinstance(e, dict)]
assert not any(e.get("verifiedUsing") for e in neg_elems), "negative must not invent hashes"
ai_pkgs = [e for e in elems if e.get("type") == "ai_AIPackage"]
assert ai_pkgs, "spdx3 missing ai_AIPackage for observed model"
assert "ai" in (spdx3.get("profileConformance") or []), spdx3.get("profileConformance")
assert any(e.get("software_primaryPurpose") == "model" for e in ai_pkgs)
assert not any(e.get("type") == "ai_AIPackage" for e in neg_elems)
assert "ai" not in (neg_spdx3.get("profileConformance") or [])
assert not any(
    e.get("type") == "Relationship" and e.get("relationshipType") in {"trainedOn", "testedOn"}
    for e in elems
), "invented trainedOn/testedOn"
for e in elems:
    for key in e:
        assert key not in {"ai_metric", "ai_hyperparameter", "ai_energyConsumption"}
print("mlbom-obs-ok", {"sha256": want[:12] + "…", "ml": len(ml), "ai": len(ai_pkgs)})
print("spdx3-ai-ok")
PYMLBOM
rm -rf "$OBS_TMP" "$NEG_TMP"
echo "mlbom-obs-ok"
echo "spdx3-ai-ok"

echo "==> evidence-pack (CycloneDX 1.7 + SPDX 3.0.1 + OpenVEX 0.2.0 + MANIFEST + pack.json clock; not a CRA certificate)"
PACK_TMP="$(mktemp -d)"
python3 -m ai_bom evidence-pack --dir examples/sample-app --out "$PACK_TMP/sample"   --policy policies/default.json --advisories examples/advisories/sample.json --as-of 2026-08-26 --zip "$PACK_TMP/sample.zip"
test -f "$PACK_TMP/sample/bom.cdx.json"
test -f "$PACK_TMP/sample/bom.spdx3.json"
test -f "$PACK_TMP/sample/MANIFEST.md"
test -f "$PACK_TMP/sample/pack.json"
test -f "$PACK_TMP/sample/vex.json"
python3 -m ai_bom evidence-pack --dir examples/cra-fixtures/license-pass --out "$PACK_TMP/pass"   --policy policies/default.json --advisories examples/advisories/clean.json
python3 -m ai_bom evidence-pack --dir examples/cra-fixtures/license-fail --out "$PACK_TMP/fail"   --policy policies/default.json --advisories examples/advisories/clean.json
test -f "$PACK_TMP/pass/bom.cdx.json" && test -f "$PACK_TMP/pass/bom.spdx3.json" && test -f "$PACK_TMP/pass/vex.json" && test -f "$PACK_TMP/pass/MANIFEST.md" && test -f "$PACK_TMP/pass/pack.json"
test -f "$PACK_TMP/fail/bom.cdx.json" && test -f "$PACK_TMP/fail/bom.spdx3.json" && test -f "$PACK_TMP/fail/vex.json" && test -f "$PACK_TMP/fail/MANIFEST.md" && test -f "$PACK_TMP/fail/pack.json"
PACK_TMP="$PACK_TMP" python3 - <<"PYPACK"
import json, os, zipfile
from pathlib import Path
root = Path(os.environ["PACK_TMP"])
cdx = json.loads((root / "sample" / "bom.cdx.json").read_text())
spdx3 = json.loads((root / "sample" / "bom.spdx3.json").read_text())
man = (root / "sample" / "MANIFEST.md").read_text()
pack = json.loads((root / "sample" / "pack.json").read_text())
assert cdx.get("bomFormat") == "CycloneDX" and cdx.get("specVersion") == "1.7", cdx.get("specVersion")
assert (spdx3.get("creationInfo") or {}).get("specVersion") == "3.0.1", spdx3.get("creationInfo")
vex = json.loads((root / "sample" / "vex.json").read_text())
assert vex.get("@context") == "https://openvex.dev/ns/v0.2.0", vex.get("@context")
assert vex.get("author") and vex.get("timestamp") and vex.get("@id")
assert isinstance(vex.get("statements"), list) and vex["statements"]
assert "vex.json" in (pack.get("files") or [])
assert "exploitability statement helper" in man.lower()

assert "not a CRA declaration" in man
assert "compliant" not in man.lower()
assert "certified" not in man.lower()
fail_man = (root / "fail" / "MANIFEST.md").read_text()
pass_man = (root / "pass" / "MANIFEST.md").read_text()
assert "| license (`--gate-licenses`) | 1 |" in fail_man, fail_man
assert "| license (`--gate-licenses`) | 0 |" in pass_man, pass_man
clock = pack.get("clock") or {}
assert clock.get("schema") == "ai-bom-cra-clock/v1", clock.get("schema")
assert clock.get("kind") == "calendar-helper", clock.get("kind")
assert clock.get("asOf") == "2026-08-26", clock.get("asOf")
a14 = (clock.get("windows") or {}).get("article14Reporting") or {}
assert a14.get("date") == "2026-09-11", a14
assert a14.get("daysUntil") == 16, a14
assert a14.get("daysOverdue") == 0, a14
sbom = (clock.get("windows") or {}).get("sbom") or {}
assert sbom.get("date") == "2027-12-11", sbom
assert isinstance(sbom.get("daysUntil"), int), sbom
vulns = clock.get("observedVulns") or []
fixture = next((v for v in vulns if str(v.get("id") or "").startswith("ADV-FIXTURE-")), None)
assert fixture, vulns
fw = (fixture.get("windows") or {}).get("article14Reporting") or {}
assert fw.get("daysUntil") == 16, fixture
assert "calendar/evidence helper" in (clock.get("disclaimerEn") or "").lower()
assert "日历/证据辅助" in (clock.get("disclaimerZh") or "")
assert "合格证书" in (clock.get("disclaimerZh") or "")
assert "calendar/evidence helper" in man.lower()
assert "日历/证据辅助" in man
blob = json.dumps(pack, ensure_ascii=False).lower()
assert "compliant" not in blob and "certified" not in blob
with zipfile.ZipFile(root / "sample.zip") as zf:
    names = set(zf.namelist())
assert {"bom.cdx.json", "bom.spdx3.json", "vex.json", "MANIFEST.md", "pack.json"} <= names, names
print("evidence-pack artifacts ok")
print("cra-clock fields ok")
PYPACK
rm -rf "$PACK_TMP"
echo "evidence-pack-ok"
echo "evidence-zip-ok"
echo "cra-clock-ok"
echo "vex-ok"

echo "==> temp package.json GPL-3.0 -> strict fails + evidence/sarif license hits"
LIC_TMP="$(mktemp -d)"
cat > "$LIC_TMP/package.json" <<'JSON'
{
  "name": "gpl-fixture",
  "version": "0.0.1",
  "license": "GPL-3.0"
}
JSON
cat > "$LIC_TMP/app.py" <<'APP'
MODEL = "gpt-4o-mini"
APP
mkdir -p "$LIC_TMP/out"
set +e
python3 -m ai_bom scan "$LIC_TMP" \
  --policy policies/default.json \
  --strict \
  --out "$LIC_TMP/out/bom.json" \
  --evidence "$LIC_TMP/out/evidence.md" \
  --sarif "$LIC_TMP/out/bom.sarif" >/tmp/d-lic-strict.out 2>&1
code=$?
set -e
if [ "$code" -ne 1 ]; then
  echo "expected exit 1 for GPL-3.0, got $code"
  cat /tmp/d-lic-strict.out
  exit 1
fi
grep -Eqi 'GPL-3\.0|forbidden license' /tmp/d-lic-strict.out
BOM_JSON="$LIC_TMP/out/bom.json" EV="$LIC_TMP/out/evidence.md" SARIF="$LIC_TMP/out/bom.sarif" python3 - <<"PY"
import json, os
from pathlib import Path
bom = json.loads(Path(os.environ["BOM_JSON"]).read_text())
fl = bom["summary"].get("forbiddenLicenses") or []
assert any(h.get("licenseId") == "GPL-3.0" for h in fl), fl
assert bom["summary"].get("policyHits", 0) >= 1
ev = Path(os.environ["EV"]).read_text()
assert "GPL-3.0" in ev
assert "Forbidden license" in ev or "禁止许可证" in ev
sarif = json.loads(Path(os.environ["SARIF"]).read_text())
results = (sarif.get("runs") or [{}])[0].get("results") or []
assert any(r.get("ruleId") == "license/GPL-3.0" for r in results), [r.get("ruleId") for r in results]
print("GPL-3.0 strict + evidence/sarif license hits OK", fl)
PY
python3 -m ai_bom scan "$LIC_TMP" --policy policies/default.json --format html --out "$LIC_TMP/out/bom.html" >/tmp/d-lic-html.out
HTML_LIC="$LIC_TMP/out/bom.html" python3 - <<"PYLICHTML"
import os
from pathlib import Path
html = Path(os.environ["HTML_LIC"]).read_text()
assert "<table" in html
assert "GPL-3.0" in html
assert "fail" in html
print("cli --format html forbidden license ok")
PYLICHTML
rm -rf "$LIC_TMP"


echo "==> license exceptions sidecar (waive GPL; expired still fails; HTTP waived)"
EXC_TMP="$(mktemp -d)"
cat > "$EXC_TMP/package.json" <<'JSON'
{
  "name": "leftpad",
  "version": "0.0.1",
  "license": "GPL-3.0"
}
JSON
printf '%s\n' 'MODEL = "gpt-4o-mini"' > "$EXC_TMP/app.py"
mkdir -p "$EXC_TMP/out"
set +e
python3 -m ai_bom scan "$EXC_TMP" --policy policies/default.json --strict \
  --out "$EXC_TMP/out/bom-noexc.json" >/tmp/d-exc-strict.out 2>&1
code=$?
set -e
if [ "$code" -ne 1 ]; then
  echo "expected exit 1 without exceptions, got $code"
  cat /tmp/d-exc-strict.out
  rm -rf "$EXC_TMP"
  exit 1
fi
cat > "$EXC_TMP/.aibom-exceptions.json" <<'JSON'
{
  "exceptions": [
    {
      "component": "leftpad",
      "license": "GPL-3.0",
      "reason": "vendor approved 2026-Q3",
      "expires": "2099-12-31"
    }
  ]
}
JSON
python3 -m ai_bom scan "$EXC_TMP" --policy policies/default.json --strict \
  --out "$EXC_TMP/out/bom-waived.json" --evidence "$EXC_TMP/out/evidence.md" \
  --sarif "$EXC_TMP/out/bom.sarif" >/tmp/d-exc-waive.out
BOM_JSON="$EXC_TMP/out/bom-waived.json" EV="$EXC_TMP/out/evidence.md" SARIF="$EXC_TMP/out/bom.sarif" python3 - <<'PY'
import json, os
from pathlib import Path
bom = json.loads(Path(os.environ["BOM_JSON"]).read_text())
assert not (bom["summary"].get("forbiddenLicenses") or []), bom["summary"]
waived = bom["summary"].get("waived") or []
assert any(w.get("component") == "leftpad" and w.get("license") == "GPL-3.0" for w in waived), waived
assert (bom["summary"].get("policyHits") or 0) == 0, bom["summary"]
ev = Path(os.environ["EV"]).read_text()
assert "leftpad" in ev and ("Waived" in ev or "已豁免" in ev)
sarif = json.loads(Path(os.environ["SARIF"]).read_text())
results = (sarif.get("runs") or [{}])[0].get("results") or []
assert any(r.get("suppressions") or (r.get("properties") or {}).get("waived") for r in results), [r.get("ruleId") for r in results]
print("exceptions waive + strict 0 + evidence/sarif OK", waived)
PY

python3 -m ai_bom scan "$EXC_TMP" --policy policies/default.json \
  --format gha --out "$EXC_TMP/out/bom.gha.txt" >/tmp/d-exc-gha.out
GHA_W="$EXC_TMP/out/bom.gha.txt" python3 - <<'PYGHAW'
import os
from pathlib import Path
gha = Path(os.environ["GHA_W"]).read_text()
assert "::error" not in gha, gha
assert "::notice" in gha
assert "title=leftpad::" in gha
assert "waived" in gha
print("cli --format gha waived-only notice ok")
PYGHAW

cat > "$EXC_TMP/.aibom-exceptions.json" <<'JSON'
{
  "exceptions": [
    {
      "component": "leftpad",
      "license": "GPL-3.0",
      "reason": "old waiver",
      "expires": "2020-01-01"
    }
  ]
}
JSON
set +e
python3 -m ai_bom scan "$EXC_TMP" --policy policies/default.json --strict \
  --out "$EXC_TMP/out/bom-expired.json" >/tmp/d-exc-expired.out 2>&1
code=$?
set -e
if [ "$code" -ne 1 ]; then
  echo "expected exit 1 for expired exception, got $code"
  cat /tmp/d-exc-expired.out
  rm -rf "$EXC_TMP"
  exit 1
fi
BOM_JSON="$EXC_TMP/out/bom-expired.json" python3 - <<'PY'
import json, os
from pathlib import Path
bom = json.loads(Path(os.environ["BOM_JSON"]).read_text())
assert any(h.get("licenseId") == "GPL-3.0" for h in (bom["summary"].get("forbiddenLicenses") or [])), bom["summary"]
assert any(e.get("component") == "leftpad" for e in (bom["summary"].get("expiredExceptions") or [])), bom["summary"]
assert not (bom["summary"].get("waived") or []), bom["summary"]
print("expired exception still fails OK")
PY

cat > "$EXC_TMP/.aibom-exceptions.json" <<'JSON'
{
  "exceptions": [
    {
      "component": "leftpad",
      "license": "GPL-3.0",
      "reason": "vendor approved 2026-Q3",
      "expires": "2099-12-31"
    }
  ]
}
JSON
EXC_PORT="${EXC_PORT:-8828}"
EXC_LOG="$ROOT/out/exc-serve.log"
rm -f "$EXC_LOG"
unset AI_BOM_CORS_ORIGINS || true
unset AI_BOM_EXCEPTIONS || true
python3 -m ai_bom serve --path "$EXC_TMP" --port "$EXC_PORT" --host 127.0.0.1 \
  --policy policies/default.json >"$EXC_LOG" 2>&1 &
EXC_PID=$!
cleanup_exc() {
  if [ -n "${EXC_PID:-}" ] && kill -0 "$EXC_PID" 2>/dev/null; then
    kill "$EXC_PID" 2>/dev/null || true
    wait "$EXC_PID" 2>/dev/null || true
  fi
  rm -rf "$EXC_TMP"
}
trap cleanup_exc EXIT
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$EXC_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 50 ]; then
    echo "exceptions serve did not become healthy"
    cat "$EXC_LOG" || true
    exit 1
  fi
done
curl -sf "http://127.0.0.1:$EXC_PORT/bom.json" -o "$EXC_TMP/out/http-waived.json"
EXC_HTTP="$EXC_TMP/out/http-waived.json" python3 - <<'PY'
import json, os
from pathlib import Path
bom = json.loads(Path(os.environ["EXC_HTTP"]).read_text())
waived = bom["summary"].get("waived") or []
assert any(w.get("component") == "leftpad" for w in waived), bom["summary"]
assert not (bom["summary"].get("forbiddenLicenses") or []), bom["summary"]
print("http waived ok", waived)
PY
curl -sf "http://127.0.0.1:$EXC_PORT/v1/exceptions" -o "$EXC_TMP/out/http-exceptions.json"
EXC_HTTP="$EXC_TMP/out/http-exceptions.json" python3 - <<'PYEXC'
import json, os
from pathlib import Path
d = json.loads(Path(os.environ["EXC_HTTP"]).read_text())
assert d.get("ok") is True, d
assert isinstance(d.get("count"), int) and d.get("count") >= 1, d
assert any(e.get("component") == "leftpad" for e in (d.get("exceptions") or [])), d
left = next(e for e in d["exceptions"] if e.get("component") == "leftpad")
assert left.get("expired") is False, left
assert left.get("expiresAt") == "2099-12-31", left
print("http /v1/exceptions sidecar ok", {"count": d.get("count")})
PYEXC
curl -sf "http://127.0.0.1:$EXC_PORT/bom.json?exceptions=skip" -o "$EXC_TMP/out/http-skip.json"
EXC_HTTP="$EXC_TMP/out/http-skip.json" python3 - <<'PY'
import json, os
from pathlib import Path
bom = json.loads(Path(os.environ["EXC_HTTP"]).read_text())
assert any(h.get("licenseId") == "GPL-3.0" for h in (bom["summary"].get("forbiddenLicenses") or [])), bom["summary"]
assert not (bom["summary"].get("waived") or []), bom["summary"]
print("http exceptions skip ok")
PY
cleanup_exc
EXC_PID=""
trap - EXIT
echo "license exceptions sidecar OK"

echo "==> mock policy-hit webhook receiver"
WH_PORT="${WH_PORT:-8816}"
WH_OUT="$ROOT/out/webhook-last.json"
WH_HDR="$ROOT/out/webhook-last.headers.json"
WH_LOG="$ROOT/out/mock-webhook.log"
rm -f "$WH_OUT" "$WH_HDR" "$WH_LOG"
unset AI_BOM_WEBHOOK_URL || true
python3 mock-webhook-receiver.py --port "$WH_PORT" --out "$WH_OUT" --headers-out "$WH_HDR" >"$WH_LOG" 2>&1 &
WH_PID=$!
cleanup_wh() {
  if [ -n "${WH_PID:-}" ] && kill -0 "$WH_PID" 2>/dev/null; then
    kill "$WH_PID" 2>/dev/null || true
    wait "$WH_PID" 2>/dev/null || true
  fi
}
trap cleanup_wh EXIT
for i in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:$WH_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 40 ]; then
    echo "mock webhook receiver did not become healthy"
    cat "$WH_LOG" || true
    exit 1
  fi
done

echo "==> scan sample-app (pickle) + webhook POST"
rm -f "$WH_OUT"
python3 -m ai_bom scan examples/sample-app \
  --policy policies/default.json \
  --webhook-url "http://127.0.0.1:${WH_PORT}/hook" >/tmp/d-webhook-scan.out
WH_OK=0
for i in $(seq 1 40); do
  if test -f "$WH_OUT" && grep -q 'policyHits' "$WH_OUT" 2>/dev/null; then
    WH_OK=1
    break
  fi
  sleep 0.05
done
test "$WH_OK" = "1"
test -s "$WH_OUT"
python3 - <<"WHPY"
import json
from pathlib import Path
d = json.loads(Path("out/webhook-last.json").read_text())
assert d.get("ok") is False, d
assert isinstance(d.get("policyHits"), int) and d["policyHits"] >= 1, d
assert isinstance(d.get("forbiddenLicenses"), list), d
assert isinstance(d.get("summary"), dict), d
assert set(d) >= {"ok", "policyHits", "forbiddenLicenses", "summary"}
forbidden = (d.get("summary") or {}).get("forbidden") or []
assert any("pickle" in str(h.get("pattern") or "") for h in forbidden), forbidden
print("webhook_policy_hit_ok", {"policyHits": d["policyHits"], "forbidden": len(forbidden)})
WHPY
echo "sample-app pickle webhook ok"
echo "==> policy-hit webhook timestamp header (OSS; replay window = paid)"
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

echo "==> dead webhook never changes exit code"
set +e
python3 -m ai_bom scan examples/sample-app \
  --webhook-url "http://127.0.0.1:1/nope" >/tmp/d-webhook-dead.out 2>&1
ec=$?
set -e
if [ "$ec" -ne 0 ]; then
  echo "expected exit 0 when webhook is dead (no --strict), got $ec"
  cat /tmp/d-webhook-dead.out
  exit 1
fi
set +e
python3 -m ai_bom scan examples/sample-app --policy policies/default.json --strict \
  --webhook-url "http://127.0.0.1:1/nope" >/tmp/d-webhook-dead-strict.out 2>&1
ec=$?
set -e
if [ "$ec" -ne 1 ]; then
  echo "expected exit 1 on --strict even when webhook fails, got $ec"
  cat /tmp/d-webhook-dead-strict.out
  exit 1
fi
echo "dead webhook still original exit code ok"

echo "==> clean dir does not POST webhook"
CLEAN_TMP="$(mktemp -d)"
printf '%s\n' 'MODEL = "gpt-4o-mini"' > "$CLEAN_TMP/app.py"
rm -f "$WH_OUT"
python3 -m ai_bom scan "$CLEAN_TMP" \
  --policy policies/default.json \
  --webhook-url "http://127.0.0.1:${WH_PORT}/hook" >/tmp/d-webhook-clean.out
sleep 0.25
if [ -f "$WH_OUT" ]; then
  echo "clean scan must not POST webhook"
  cat "$WH_OUT"
  rm -rf "$CLEAN_TMP"
  exit 1
fi
rm -rf "$CLEAN_TMP"
echo "clean scan no webhook post ok"

cleanup_wh
WH_PID=""
trap - EXIT

echo "==> [hmac] isolated scan --webhook-secret (unsigned prove above stays intact)"
HMAC_WH_PORT="${HMAC_WH_PORT:-8817}"
HMAC_SECRET="whsec_local_mvp"
HMAC_OUT="$ROOT/out/webhook-hmac-last.json"
HMAC_HDR="$ROOT/out/webhook-hmac-last.headers.json"
HMAC_WH_LOG="$ROOT/out/mock-webhook.hmac.log"
rm -f "$HMAC_OUT" "$HMAC_HDR" "$HMAC_WH_LOG"
unset AI_BOM_WEBHOOK_URL || true
unset AI_BOM_WEBHOOK_SECRET || true
python3 mock-webhook-receiver.py --port "$HMAC_WH_PORT" --out "$HMAC_OUT" \
  --headers-out "$HMAC_HDR" --secret "$HMAC_SECRET" >"$HMAC_WH_LOG" 2>&1 &
HMAC_WH_PID=$!
cleanup_hmac() {
  if [ -n "${HMAC_WH_PID:-}" ] && kill -0 "$HMAC_WH_PID" 2>/dev/null; then
    kill "$HMAC_WH_PID" 2>/dev/null || true
    wait "$HMAC_WH_PID" 2>/dev/null || true
  fi
}
trap cleanup_hmac EXIT
for i in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:$HMAC_WH_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 40 ]; then
    echo "hmac mock webhook receiver did not become healthy"
    cat "$HMAC_WH_LOG" || true
    exit 1
  fi
done
python3 -m ai_bom scan examples/sample-app \
  --policy policies/default.json \
  --webhook-url "http://127.0.0.1:${HMAC_WH_PORT}/hook" \
  --webhook-secret "$HMAC_SECRET" >/tmp/d-webhook-hmac.out
HMAC_OK=0
for i in $(seq 1 40); do
  if test -f "$HMAC_OUT" && grep -q 'policyHits' "$HMAC_OUT" 2>/dev/null \
     && test -f "$HMAC_HDR" && grep -q 'sha256=' "$HMAC_HDR" 2>/dev/null; then
    HMAC_OK=1
    break
  fi
  sleep 0.05
done
test "$HMAC_OK" = "1"
test -s "$HMAC_OUT"
grep -qi 'sha256=' "$HMAC_HDR"
grep -q '"verified": true' "$HMAC_HDR"
python3 -c '
import json, sys
from pathlib import Path
from ai_bom.webhook import sign_webhook_body, verify_webhook_signature
secret, body_path, hdr_path = sys.argv[1:4]
body = Path(body_path).read_bytes()
meta = json.loads(Path(hdr_path).read_text(encoding="utf-8"))
sig = str(meta.get("signature") or "")
if not sig.lower().startswith("sha256="):
    raise SystemExit("missing X-Webhook-Signature sha256= prefix")
expected = sign_webhook_body(secret, body)
if sig.lower() != expected:
    raise SystemExit("HMAC mismatch got=%s expected=%s" % (sig, expected))
if not verify_webhook_signature(secret, body, sig):
    raise SystemExit("verify_webhook_signature failed")
if meta.get("verified") is not True:
    raise SystemExit("receiver verified flag %r" % (meta.get("verified"),))
d = json.loads(body.decode("utf-8"))
assert d.get("ok") is False, d
assert isinstance(d.get("policyHits"), int) and d["policyHits"] >= 1, d

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
' "$HMAC_SECRET" "$HMAC_OUT" "$HMAC_HDR"
echo "webhook_hmac_ok"
cleanup_hmac
HMAC_WH_PID=""
trap - EXIT

echo "==> local BOM HTTP server (serve --port 8793; hosted inventory = paid later)"
PORT=8793
# Default deny CORS: do not pass --cors-origins; ignore leftover env.
unset AI_BOM_CORS_ORIGINS || true
unset RATE_LIMIT_PER_MINUTE RATE_LIMIT_RPM || true
SERVE_LOG="$ROOT/out/serve.log"
rm -f "$SERVE_LOG" out/serve-index.html out/serve-bom.json out/serve-health.json out/serve-evidence.md out/serve-metrics.txt
python3 -m ai_bom serve --path examples/sample-app --port "$PORT" --host 127.0.0.1 \
  --policy policies/default.json >"$SERVE_LOG" 2>&1 &
SERVE_PID=$!
CORS_PID=""
cleanup_serve() {
  if [ -n "${CORS_PID:-}" ] && kill -0 "$CORS_PID" 2>/dev/null; then
    kill "$CORS_PID" 2>/dev/null || true
    wait "$CORS_PID" 2>/dev/null || true
  fi
  if [ -n "${SERVE_PID:-}" ] && kill -0 "$SERVE_PID" 2>/dev/null; then
    kill "$SERVE_PID" 2>/dev/null || true
    wait "$SERVE_PID" 2>/dev/null || true
  fi
}
trap cleanup_serve EXIT

for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 50 ]; then
    echo "serve did not become healthy"
    cat "$SERVE_LOG" || true
    exit 1
  fi
done

curl -sf "http://127.0.0.1:$PORT/health" -o out/serve-health.json
grep -Eq '"ok"[[:space:]]*:[[:space:]]*true' out/serve-health.json
grep -q ai-bom out/serve-health.json

echo "==> GET /ready (always 200 {ok:true, service} — snapshot, no circuit/queue)"
READY="$(curl -s -o out/serve-ready.json -D out/serve-ready.h -w '%{http_code}' "http://127.0.0.1:$PORT/ready")"
echo "ready_status=$READY body=$(cat out/serve-ready.json)"
test "$READY" = "200"
grep -Eq '"ok"[[:space:]]*:[[:space:]]*true' out/serve-ready.json
grep -q ai-bom out/serve-ready.json
grep -qiE '^x-request-id:' out/serve-ready.h
RID_READY="mvp-ready-rid-d1"
curl -s -o /tmp/d-ready-custom.json -D /tmp/d-ready-custom.h   "http://127.0.0.1:$PORT/ready" -H "X-Request-Id: $RID_READY" >/dev/null
grep -qiE "^x-request-id:[[:space:]]*${RID_READY}" /tmp/d-ready-custom.h
echo "ready_ok"

echo "==> X-Request-Id omitted → generated UUID echoed on every response"
curl -s -o /tmp/d-health-rid.json -D /tmp/d-health-rid.h "http://127.0.0.1:$PORT/health" >/dev/null
grep -qiE '^x-request-id:' /tmp/d-health-rid.h
GEN_RID="$(tr -d '\r' < /tmp/d-health-rid.h | awk 'tolower($0) ~ /^x-request-id:/{print $2; exit}')"
echo "generated_request_id=$GEN_RID"
echo "$GEN_RID" | grep -qE '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
echo "request_id_generated_ok"

echo "==> X-Request-Id custom id echoed on /health"
RID_HEALTH="mvp-health-rid-d1"
curl -s -o /tmp/d-health-custom.json -D /tmp/d-health-custom.h \
  "http://127.0.0.1:$PORT/health" -H "X-Request-Id: $RID_HEALTH" >/dev/null
grep -qiE "^x-request-id:[[:space:]]*${RID_HEALTH}" /tmp/d-health-custom.h
echo "request_id_health_custom_ok"

echo "==> GET /metrics (Prometheus text)"
RID_METRICS="mvp-metrics-rid-d1"
curl -s -o out/serve-metrics.txt -D out/serve-metrics.h \
  "http://127.0.0.1:$PORT/metrics" -H "X-Request-Id: $RID_METRICS"
test -s out/serve-metrics.txt
grep -qiE "^x-request-id:[[:space:]]*${RID_METRICS}" out/serve-metrics.h
grep -q 'ai_bom_component_count' out/serve-metrics.txt
grep -q 'ai_bom_policy_hits' out/serve-metrics.txt
grep -q 'ai_bom_forbidden_licenses' out/serve-metrics.txt
grep -q '# TYPE ai_bom_component_count gauge' out/serve-metrics.txt
grep -q '# TYPE ai_bom_policy_hits gauge' out/serve-metrics.txt
grep -q '# TYPE ai_bom_forbidden_licenses gauge' out/serve-metrics.txt
echo "metrics_names_ok"
echo "request_id_metrics_custom_ok"

curl -sf "http://127.0.0.1:$PORT/" -o out/serve-index.html
grep -qi 'component' out/serve-index.html
grep -Eqi 'license|许可证' out/serve-index.html
grep -Eqi 'policy hit|policy hits' out/serve-index.html
grep -q 'hosted inventory' out/serve-index.html

curl -sf "http://127.0.0.1:$PORT/bom.json" -o out/serve-bom.json
grep -q MIT out/serve-bom.json
python3 - <<"PYBOM"
import json
from pathlib import Path
bom = json.loads(Path("out/serve-bom.json").read_text())
assert bom.get("bomFormat") == "CycloneDX"
assert any(
    (e.get("license") or {}).get("id") == "MIT"
    for c in bom.get("components") or []
    for e in (c.get("licenses") or [])
), "serve /bom.json must include MIT from sample-app/package.json"
assert (bom.get("summary") or {}).get("licenses", {}).get("MIT", 0) >= 1
print("serve bom.json MIT ok", bom["summary"].get("licenses"))
PYBOM

echo "==> GET /v1/bom?format=cyclonedx (CycloneDX 1.7)"
curl -sf "http://127.0.0.1:$PORT/v1/bom?format=cyclonedx" -o out/serve-bom-cdx.json
test -s out/serve-bom-cdx.json
python3 - <<"PYCDX"
import json
from pathlib import Path
cdx = json.loads(Path("out/serve-bom-cdx.json").read_text())
assert cdx.get("bomFormat") == "CycloneDX", cdx.get("bomFormat")
assert cdx.get("specVersion") == "1.7", cdx.get("specVersion")
assert "summary" not in cdx
assert any(p.get("name") == "aibom:policyHits" for p in (cdx.get("properties") or []))
assert any(
    (e.get("license") or {}).get("id") == "MIT"
    for c in cdx.get("components") or []
    for e in (c.get("licenses") or [])
), "cyclonedx components need MIT"
print("http cyclonedx ok", cdx["bomFormat"], cdx["specVersion"], "components=", len(cdx.get("components") or []))
PYCDX

echo "==> GET /v1/bom?format=spdx3 (SPDX 3.0.1)"
curl -sf "http://127.0.0.1:$PORT/v1/bom?format=spdx3" -o out/serve-bom-spdx3.json
test -s out/serve-bom-spdx3.json
python3 - <<"PYSPDX3HTTP"
import json
from pathlib import Path
doc = json.loads(Path("out/serve-bom-spdx3.json").read_text())
ci = doc.get("creationInfo") or {}
assert ci.get("specVersion") == "3.0.1", ci
assert doc.get("type") == "SpdxDocument"
assert doc.get("spdxId")
assert isinstance(doc.get("element"), list) and doc["element"]
print("http ?format=spdx3 ok", ci["specVersion"], "elements=", len(doc["element"]))
PYSPDX3HTTP
curl -sf "http://127.0.0.1:$PORT/v1/bom" -o out/serve-bom-v1.json
python3 - <<"PYV1"
import json
from pathlib import Path
bom = json.loads(Path("out/serve-bom-v1.json").read_text())
assert bom.get("summary") is not None, "default /v1/bom must stay internal json"
assert bom.get("bomFormat") == "CycloneDX"
print("http /v1/bom default json ok")
PYV1

echo "==> GET /v1/bom?format=cyclonedx-xml (CycloneDX 1.7 XML)"
CDX_XML_CODE="$(curl -s -o out/serve-bom-cdx.xml -D out/serve-bom-cdx-xml.h -w "%{http_code}" \
  "http://127.0.0.1:$PORT/v1/bom?format=cyclonedx-xml")"
echo "v1_bom_cdx_xml_status=$CDX_XML_CODE"
test "$CDX_XML_CODE" = "200"
grep -qiE '^content-type:.*xml' out/serve-bom-cdx-xml.h
python3 - <<"PYCDXHTTPXML"
from pathlib import Path
xml = Path("out/serve-bom-cdx.xml").read_text()
assert xml.lstrip().startswith("<bom"), xml[:80]
assert "http://cyclonedx.org/schema/bom/1.7" in xml
assert "<components" in xml
assert "ai-bom-sample-app" in xml or "gpt-4o-mini" in xml or "MIT" in xml
print("http ?format=cyclonedx-xml ok")
PYCDXHTTPXML
curl -sf "http://127.0.0.1:$PORT/v1/bom.xml" -o out/serve-bom-cdx-alias.xml
python3 - <<"PYCDXALIAS"
from pathlib import Path
xml = Path("out/serve-bom-cdx-alias.xml").read_text()
assert xml.lstrip().startswith("<bom"), xml[:80]
assert "bom/1.7" in xml
print("http /v1/bom.xml alias ok")
PYCDXALIAS

echo "==> GET /v1/bom?format=spdx-xml (SPDX 2.3 XML)"
SPDX_XML_CODE="$(curl -s -o out/serve-bom-spdx.xml -D out/serve-bom-spdx-xml.h -w "%{http_code}" \
  "http://127.0.0.1:$PORT/v1/bom?format=spdx-xml")"
echo "v1_bom_spdx_xml_status=$SPDX_XML_CODE"
test "$SPDX_XML_CODE" = "200"
grep -qiE '^content-type:.*xml' out/serve-bom-spdx-xml.h
python3 - <<"PYSPDXHTTPXML"
from pathlib import Path
xml = Path("out/serve-bom-spdx.xml").read_text()
assert xml.lstrip().startswith("<SpdxDocument"), xml[:80]
assert "SPDX-2.3" in xml
assert "<packages" in xml
assert "<licenseConcluded" in xml
assert "ai-bom-sample-app" in xml or "gpt-4o-mini" in xml or "MIT" in xml
print("http ?format=spdx-xml ok")
PYSPDXHTTPXML
curl -sf "http://127.0.0.1:$PORT/v1/bom.spdx.xml" -o out/serve-bom-spdx-alias.xml
python3 - <<"PYSPDXALIAS"
from pathlib import Path
xml = Path("out/serve-bom-spdx-alias.xml").read_text()
assert xml.lstrip().startswith("<SpdxDocument"), xml[:80]
assert "SPDX-2.3" in xml
print("http /v1/bom.spdx.xml alias ok")
PYSPDXALIAS

echo "==> GET /v1/bom.md and ?format=md (Markdown summary)"
MD_CODE="$(curl -s -o out/serve-bom.md -D out/serve-bom-md.h -w "%{http_code}" \
  "http://127.0.0.1:$PORT/v1/bom.md")"
echo "v1_bom_md_status=$MD_CODE"
test "$MD_CODE" = "200"
grep -qiE '^content-type:.*markdown' out/serve-bom-md.h
python3 - <<"PYMDHTTP"
from pathlib import Path
md = Path("out/serve-bom.md").read_text()
assert md.lstrip().startswith("# "), md[:80]
assert "# AI-BOM" in md
assert "policyHits" in md
assert "MIT" in md or "gpt-4o-mini" in md or "pickle" in md, md[:600]
print("http /v1/bom.md ok")
PYMDHTTP
MD_Q="$(curl -s -o out/serve-bom-md-q.md -D out/serve-bom-md-q.h -w "%{http_code}" \
  "http://127.0.0.1:$PORT/v1/bom?format=md")"
echo "v1_bom_md_query_status=$MD_Q"
test "$MD_Q" = "200"
grep -qiE '^content-type:.*markdown' out/serve-bom-md-q.h
python3 - <<"PYMDQ"
from pathlib import Path
md = Path("out/serve-bom-md-q.md").read_text()
assert md.lstrip().startswith("# "), md[:80]
assert "policyHits" in md
print("http ?format=md ok")
PYMDQ

echo "==> GET /v1/bom.gha.txt and ?format=gha (GHA annotations)"
GHA_CODE="$(curl -s -o out/serve-bom.gha.txt -D out/serve-bom-gha.h -w "%{http_code}" \
  "http://127.0.0.1:$PORT/v1/bom.gha.txt")"
echo "v1_bom_gha_status=$GHA_CODE"
[ "$GHA_CODE" = "200" ]
grep -qiE '^content-type:.*text/plain' out/serve-bom-gha.h
python3 - <<"PYGHAHTTP"
from pathlib import Path
gha = Path("out/serve-bom.gha.txt").read_text()
assert "::error" in gha, gha[:400]
assert "title=" in gha
print("http /v1/bom.gha.txt ok")
PYGHAHTTP
GHA_Q="$(curl -s -o out/serve-bom-gha-q.txt -D out/serve-bom-gha-q.h -w "%{http_code}" \
  "http://127.0.0.1:$PORT/v1/bom?format=gha")"
echo "v1_bom_gha_query_status=$GHA_Q"
[ "$GHA_Q" = "200" ]
grep -qiE '^content-type:.*text/plain' out/serve-bom-gha-q.h
python3 - <<"PYGHAQ"
from pathlib import Path
gha = Path("out/serve-bom-gha-q.txt").read_text()
assert "::error" in gha
print("http ?format=gha ok")
PYGHAQ

echo "==> GET /v1/bom.html and ?format=html (HTML BOM summary)"
HTML_CODE="$(curl -s -o out/serve-bom.html -D out/serve-bom-html.h -w "%{http_code}" \
  "http://127.0.0.1:$PORT/v1/bom.html")"
echo "v1_bom_html_status=$HTML_CODE"
test "$HTML_CODE" = "200"
grep -qiE '^content-type:.*text/html' out/serve-bom-html.h
python3 - <<"PYHTMLHTTP"
from pathlib import Path
html = Path("out/serve-bom.html").read_text()
assert "<table" in html or "AI-BOM" in html, html[:400]
assert "AI-BOM" in html
assert "<h1" in html
assert "pickle" in html or "MIT" in html or "gpt-4o-mini" in html or "Policy hits" in html, html[:800]
print("http /v1/bom.html ok")
PYHTMLHTTP
HTML_Q="$(curl -s -o out/serve-bom-html-q.html -D out/serve-bom-html-q.h -w "%{http_code}" \
  "http://127.0.0.1:$PORT/v1/bom?format=html")"
echo "v1_bom_html_query_status=$HTML_Q"
test "$HTML_Q" = "200"
grep -qiE '^content-type:.*text/html' out/serve-bom-html-q.h
python3 - <<"PYHTMLQ"
from pathlib import Path
html = Path("out/serve-bom-html-q.html").read_text()
assert "<h1" in html
assert "AI-BOM" in html
print("http ?format=html ok")
PYHTMLQ

echo "==> GET /v1/policy (active license/policy gate; no file dump)"
POL_CODE="$(curl -s -o out/serve-policy.json -D out/serve-policy.h -w "%{http_code}"   "http://127.0.0.1:$PORT/v1/policy" -H "X-Request-Id: mvp-policy-rid-d1")"
echo "v1_policy_status=$POL_CODE"
test "$POL_CODE" = "200"
grep -qiE "^x-request-id:[[:space:]]*mvp-policy-rid-d1" out/serve-policy.h
python3 - <<"PYPOLHTTP"
import json
from pathlib import Path
d = json.loads(Path("out/serve-policy.json").read_text())
assert d.get("ok") is True, d
ids = d.get("forbiddenLicenseIds") or []
assert "GPL-3.0" in ids, ids
assert "pickle.load" in (d.get("forbiddenPatterns") or []), d
assert isinstance(d.get("exceptionsCount"), int)
assert isinstance(d.get("ignoreFile"), bool)
raw = Path("out/serve-policy.json").read_text()
assert r"\bpickle" not in raw
assert "vendor approved" not in raw
print("http /v1/policy ok", {"ids": len(ids), "exceptionsCount": d.get("exceptionsCount"), "ignoreFile": d.get("ignoreFile")})
PYPOLHTTP

echo "==> GET /v1/config (redacted knobs; no secrets)"
CFG_CODE="$(curl -s -o out/serve-config.json -D out/serve-config.h -w "%{http_code}"   "http://127.0.0.1:$PORT/v1/config" -H "X-Request-Id: mvp-config-rid-d1")"
echo "v1_config_status=$CFG_CODE"
test "$CFG_CODE" = "200"
grep -qiE "^x-request-id:[[:space:]]*mvp-config-rid-d1" out/serve-config.h
grep -qiE "^content-type:[[:space:]]*application/json" out/serve-config.h
python3 - <<"PYCFGHTTP"
import json
from pathlib import Path
d = json.loads(Path("out/serve-config.json").read_text())
assert d.get("ok") is True, d
cors = (d.get("cors") or {})
rl = (d.get("rateLimit") or {})
assert cors.get("origins") is not None or "perMinute" in rl, d
assert "hasUrl" in (d.get("webhooks") or {}), d
assert "hasSecret" in (d.get("webhooks") or {}), d
assert isinstance(d.get("watch"), bool), d
assert isinstance(d.get("hasPolicyFile"), bool), d
assert d.get("hasPolicyFile") is True, d
if d.get("scanPathBase") is not None:
    assert "/" not in str(d.get("scanPathBase")) and "\\" not in str(d.get("scanPathBase")), d
raw = Path("out/serve-config.json").read_text()
for n in ("webhookUrl", "webhookSecret", "webhook_url", "webhook_secret", "Authorization", "whsec_", "sk-"):
    assert n not in raw, n
print("serve /v1/config ok", {"rateLimit": rl, "cors": cors, "hasUrl": (d.get("webhooks") or {}).get("hasUrl"), "hasSecret": (d.get("webhooks") or {}).get("hasSecret"), "scanPathBase": d.get("scanPathBase")})
PYCFGHTTP

echo "==> GET /v1/components (lightweight inventory)"
COMP_CODE="$(curl -s -o out/serve-components.json -D out/serve-components.h -w "%{http_code}"   "http://127.0.0.1:$PORT/v1/components" -H "X-Request-Id: mvp-components-rid-d1")"
echo "v1_components_status=$COMP_CODE"
test "$COMP_CODE" = "200"
grep -qiE "^x-request-id:[[:space:]]*mvp-components-rid-d1" out/serve-components.h
grep -qiE "^content-type:[[:space:]]*application/json" out/serve-components.h
python3 - <<"PYCOMPHTTP"
import json
from pathlib import Path
d = json.loads(Path("out/serve-components.json").read_text())
bom = json.loads(Path("out/serve-bom.json").read_text()) if Path("out/serve-bom.json").is_file() else json.loads(Path("out/bom.json").read_text())
assert d.get("ok") is True, d
assert isinstance(d.get("count"), int) and d.get("count") == len(d.get("components") or []), d
assert d.get("count") == len(bom.get("components") or []), (d.get("count"), len(bom.get("components") or []))
names = [c.get("name") for c in (d.get("components") or [])]
assert "ai-bom-sample-app" in names or "gpt-4o-mini" in names, names
for c in d.get("components") or []:
    path = str(c.get("path") or "")
    assert not path.startswith("/"), path
    assert "name" in c and "version" in c and "license" in c and "path" in c, c
raw = Path("out/serve-components.json").read_text()
assert "/home/" not in raw and "/Users/" not in raw
print("http /v1/components ok", {"count": d.get("count"), "names": names[:6]})
PYCOMPHTTP

echo "==> GET /v1/exceptions (redacted waiver inventory)"
EXC_CODE="$(curl -s -o out/serve-exceptions.json -D out/serve-exceptions.h -w "%{http_code}"   "http://127.0.0.1:$PORT/v1/exceptions" -H "X-Request-Id: mvp-exceptions-rid-d1")"
echo "v1_exceptions_status=$EXC_CODE"
test "$EXC_CODE" = "200"
grep -qiE "^x-request-id:[[:space:]]*mvp-exceptions-rid-d1" out/serve-exceptions.h
grep -qiE "^content-type:[[:space:]]*application/json" out/serve-exceptions.h
python3 - <<"PYEXCHTTP"
import json
from pathlib import Path
d = json.loads(Path("out/serve-exceptions.json").read_text())
assert d.get("ok") is True, d
assert isinstance(d.get("count"), int), d
assert isinstance(d.get("exceptions"), list), d
assert d.get("count") == len(d.get("exceptions") or []) or d.get("truncated") is True, d
raw = Path("out/serve-exceptions.json").read_text()
for n in ("sk-", "Bearer ", "webhookUrl", "webhookSecret", "Authorization", ".aibom-exceptions.json"):
    assert n not in raw, n
print("http /v1/exceptions ok", {"count": d.get("count")})
PYEXCHTTP

echo "==> GET /v1/bom?format=sarif (SARIF 2.1.0)"
SARIF_CODE="$(curl -s -o out/serve-bom-sarif.json -D out/serve-bom-sarif.h -w "%{http_code}" \
  "http://127.0.0.1:$PORT/v1/bom?format=sarif")"
echo "v1_bom_sarif_status=$SARIF_CODE"
test "$SARIF_CODE" = "200"
python3 - <<"PYSARIF"
import json
from pathlib import Path
doc = json.loads(Path("out/serve-bom-sarif.json").read_text())
assert doc.get("version") == "2.1.0", doc.get("version")
assert isinstance(doc.get("runs"), list) and doc["runs"], "runs"
schema = str(doc.get("$schema") or "")
assert "sarif" in schema.lower() or doc.get("version") == "2.1.0", schema
print("http ?format=sarif ok", doc["version"], "runs=", len(doc["runs"]))
PYSARIF
curl -sf "http://127.0.0.1:$PORT/v1/bom.sarif" -o out/serve-bom-sarif-alias.json
python3 - <<"PYALIAS"
import json
from pathlib import Path
doc = json.loads(Path("out/serve-bom-sarif-alias.json").read_text())
assert doc.get("version") == "2.1.0", doc.get("version")
assert isinstance(doc.get("runs"), list) and doc["runs"]
print("http /v1/bom.sarif alias ok")
PYALIAS
BAD="$(curl -s -o out/serve-bom-bad.json -w "%{http_code}" "http://127.0.0.1:$PORT/v1/bom?format=xml")"
echo "v1_bom_bad_format_status=$BAD"
test "$BAD" = "400"
grep -q bad_format out/serve-bom-bad.json

curl -sf "http://127.0.0.1:$PORT/evidence.md" -o out/serve-evidence.md
grep -q "DRAFT" out/serve-evidence.md
grep -q "AI-BOM Compliance Evidence" out/serve-evidence.md

echo "==> GET /openapi.json (file-backed spec)"
RID_OA="mvp-oa-rid-d1"
curl -s -o out/serve-openapi.json -D out/serve-openapi.h \
  "http://127.0.0.1:$PORT/openapi.json" -H "X-Request-Id: $RID_OA"
test -s out/serve-openapi.json
grep -q '"openapi"' out/serve-openapi.json
grep -qiE "^x-request-id:[[:space:]]*${RID_OA}" out/serve-openapi.h
echo "request_id_openapi_custom_ok"
python3 - <<"OPENAPI_PY"
import json
from pathlib import Path
spec = json.loads(Path("out/serve-openapi.json").read_text(encoding="utf-8"))
assert str(spec.get("openapi") or "").startswith("3."), spec.get("openapi")
paths = spec.get("paths") or {}
need = ["/health", "/ready", "/bom.json", "/v1/bom", "/v1/bom.sarif", "/v1/bom.xml", "/v1/bom.spdx.xml", "/v1/bom.md", "/v1/bom.gha.txt", "/v1/bom.html", "/v1/policy", "/v1/config", "/v1/components", "/v1/exceptions", "/evidence.md", "/", "/metrics", "/openapi.json"]
missing = [p for p in need if p not in paths]
assert not missing, missing
assert "get" in (paths.get("/health") or {})
assert "get" in (paths.get("/ready") or {})
assert ((paths.get("/ready") or {}).get("get") or {}).get("operationId") == "getReady"
assert "get" in (paths.get("/bom.json") or {})
assert "get" in (paths.get("/v1/bom") or {})
assert ((paths.get("/v1/bom") or {}).get("get") or {}).get("operationId") == "getBomV1"
assert "get" in (paths.get("/v1/bom.sarif") or {})
assert ((paths.get("/v1/bom.sarif") or {}).get("get") or {}).get("operationId") == "getBomSarif"
assert "get" in (paths.get("/v1/bom.xml") or {})
assert ((paths.get("/v1/bom.xml") or {}).get("get") or {}).get("operationId") == "getBomXml"
assert "get" in (paths.get("/v1/bom.spdx.xml") or {})
assert ((paths.get("/v1/bom.spdx.xml") or {}).get("get") or {}).get("operationId") == "getBomSpdxXml"
assert "get" in (paths.get("/v1/bom.md") or {})
assert ((paths.get("/v1/bom.md") or {}).get("get") or {}).get("operationId") == "getBomMd"
assert "get" in (paths.get("/v1/bom.gha.txt") or {})
assert ((paths.get("/v1/bom.gha.txt") or {}).get("get") or {}).get("operationId") == "getBomGha"
assert "get" in (paths.get("/v1/bom.html") or {})
assert ((paths.get("/v1/bom.html") or {}).get("get") or {}).get("operationId") == "getBomHtml"
assert "get" in (paths.get("/v1/policy") or {})
assert ((paths.get("/v1/policy") or {}).get("get") or {}).get("operationId") == "getPolicy"
assert "get" in (paths.get("/v1/config") or {})
assert ((paths.get("/v1/config") or {}).get("get") or {}).get("operationId") == "getConfig"
assert "RuntimeConfig" in ((spec.get("components") or {}).get("schemas") or {})
assert "get" in (paths.get("/v1/components") or {})
assert ((paths.get("/v1/components") or {}).get("get") or {}).get("operationId") == "listComponents"
assert "ComponentInventory" in ((spec.get("components") or {}).get("schemas") or {})
assert "get" in (paths.get("/v1/exceptions") or {})
assert ((paths.get("/v1/exceptions") or {}).get("get") or {}).get("operationId") == "listExceptions"
assert "ExceptionInventory" in ((spec.get("components") or {}).get("schemas") or {})
params = (spec.get("components") or {}).get("parameters") or {}
assert "BomFormat" in params, params
enum = ((params.get("BomFormat") or {}).get("schema") or {}).get("enum") or []
assert "sarif" in enum and "json" in enum and "cyclonedx" in enum and "cyclonedx-xml" in enum and "spdx" in enum and "spdx-xml" in enum and "spdx3" in enum and "md" in enum and "gha" in enum and "html" in enum, enum
assert "get" in (paths.get("/evidence.md") or {})
assert "get" in (paths.get("/") or {})
assert "get" in (paths.get("/metrics") or {})
assert "get" in (paths.get("/openapi.json") or {})
assert ((paths.get("/metrics") or {}).get("get") or {}).get("operationId") == "getMetrics"
for path in ("/health", "/ready", "/bom.json", "/v1/bom", "/v1/bom.sarif", "/v1/bom.xml", "/v1/bom.spdx.xml", "/v1/bom.md", "/v1/bom.gha.txt", "/v1/bom.html", "/v1/policy", "/v1/config", "/v1/components", "/v1/exceptions", "/evidence.md", "/", "/metrics"):
    get = ((paths.get(path) or {}).get("get") or {}).get("responses") or {}
    assert "403" in get, (path, "403 CORS", sorted(get))
responses = (spec.get("components") or {}).get("responses") or {}
assert "CorsDenied" in responses, responses
assert "RateLimited" in responses, responses
assert "429" in (((paths.get("/bom.json") or {}).get("get") or {}).get("responses") or {}), "bom.json 429"
assert "429" in (((paths.get("/v1/bom") or {}).get("get") or {}).get("responses") or {}), "v1/bom 429"
params = (spec.get("components") or {}).get("parameters") or {}
headers = (spec.get("components") or {}).get("headers") or {}
assert "XRequestId" in params, params
assert "XRequestId" in headers, headers
desc = str((spec.get("info") or {}).get("description") or "")
assert "403" in desc or "cors_denied" in desc
assert "X-Request-Id" in desc or "requestId" in desc, "missing X-Request-Id note"
assert "Retry-After" in desc and "rate_limited" in desc, "missing rate-limit note"
assert ((paths.get("/health") or {}).get("get") or {}).get("operationId") == "getHealth"
assert ((paths.get("/ready") or {}).get("get") or {}).get("operationId") == "getReady"
assert ((paths.get("/bom.json") or {}).get("get") or {}).get("operationId") == "getBom"
assert ((paths.get("/metrics") or {}).get("get") or {}).get("operationId") == "getMetrics"
desc = str((spec.get("info") or {}).get("description") or "")
assert "GET /metrics" in desc or "/metrics" in desc
assert "ai_bom_component_count" in desc
print("openapi_paths_ok", len(paths))
OPENAPI_PY

echo "==> default deny CORS (main serve has no --cors-origins)"
DEF_GET="$(curl -s -o out/d-def-cors.json -D out/d-def-cors.h -w "%{http_code}" \
  "http://127.0.0.1:$PORT/health" -H "Origin: http://localhost:3000")"
echo "default_cors_get_status=$DEF_GET"
test "$DEF_GET" = "200"
if grep -qiE "^access-control-allow-origin:" out/d-def-cors.h; then
  echo "default serve must not send ACAO"
  cat out/d-def-cors.h
  exit 1
fi
DEF_OPT="$(curl -s -o out/d-def-opt.json -D out/d-def-opt.h -w "%{http_code}" \
  -X OPTIONS "http://127.0.0.1:$PORT/health" -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: GET" \
  -H "X-Request-Id: mvp-opt-rid-404")"
echo "default_cors_options_status=$DEF_OPT"
test "$DEF_OPT" = "404"
if grep -qiE "^access-control-allow-origin:" out/d-def-opt.h; then
  echo "default OPTIONS must not send ACAO"
  cat out/d-def-opt.h
  exit 1
fi
grep -q '"not_found"' out/d-def-opt.json
grep -qiE "^x-request-id:[[:space:]]*mvp-opt-rid-404" out/d-def-opt.h

echo "==> 4xx echoes custom X-Request-Id"
MISS="$(curl -s -o out/d-missing.json -D out/d-missing.h -w "%{http_code}" \
  "http://127.0.0.1:$PORT/no-such-path" -H "X-Request-Id: mvp-4xx-rid-404")"
echo "missing_path_status=$MISS"
test "$MISS" = "404"
grep -qiE "^x-request-id:[[:space:]]*mvp-4xx-rid-404" out/d-missing.h

cleanup_serve
SERVE_PID=""
echo "serve ok (default deny CORS)"

echo "==> [cors] isolated serve --cors-origins http://localhost:3000"
CORS_PORT="${CORS_PORT:-$((PORT + 17))}"
CORS_LOG="$ROOT/out/cors-serve.log"
rm -f "$CORS_LOG"
python3 -m ai_bom serve --path examples/sample-app --port "$CORS_PORT" --host 127.0.0.1 \
  --policy policies/default.json --cors-origins "http://localhost:3000" >"$CORS_LOG" 2>&1 &
CORS_PID=$!
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$CORS_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 50 ]; then
    echo "cors serve did not become healthy"
    cat "$CORS_LOG" || true
    exit 1
  fi
done

CORS_OK="$(curl -s -o out/d-cors-ok -D out/d-cors-ok.h -w "%{http_code}" \
  -X OPTIONS "http://127.0.0.1:$CORS_PORT/health" \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: GET" \
  -H "X-Request-Id: mvp-cors-opt-204")"
echo "cors_preflight_ok_status=$CORS_OK"
test "$CORS_OK" = "204"
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" out/d-cors-ok.h
grep -qiE "^access-control-allow-methods:" out/d-cors-ok.h
grep -qiE "^access-control-allow-headers:" out/d-cors-ok.h
grep -qiE "^access-control-allow-headers:.*x-request-id" out/d-cors-ok.h
grep -qiE "^access-control-expose-headers:.*retry-after" out/d-cors-ok.h
grep -qiE "^x-request-id:[[:space:]]*mvp-cors-opt-204" out/d-cors-ok.h

CORS_HTML_PF="$(curl -s -o out/d-cors-html-pf -D out/d-cors-html-pf.h -w "%{http_code}" \
  -X OPTIONS "http://127.0.0.1:$CORS_PORT/" \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: GET")"
echo "cors_preflight_html_status=$CORS_HTML_PF"
test "$CORS_HTML_PF" = "204"
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" out/d-cors-html-pf.h

CORS_BOM_PF="$(curl -s -o out/d-cors-bom-pf -D out/d-cors-bom-pf.h -w "%{http_code}" \
  -X OPTIONS "http://127.0.0.1:$CORS_PORT/bom.json" \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: GET")"
echo "cors_preflight_bom_status=$CORS_BOM_PF"
test "$CORS_BOM_PF" = "204"
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" out/d-cors-bom-pf.h

CORS_OA_PF="$(curl -s -o out/d-cors-oa-pf -D out/d-cors-oa-pf.h -w "%{http_code}" \
  -X OPTIONS "http://127.0.0.1:$CORS_PORT/openapi.json" \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: GET")"
echo "cors_preflight_openapi_status=$CORS_OA_PF"
test "$CORS_OA_PF" = "204"
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" out/d-cors-oa-pf.h

CORS_METRICS_PF="$(curl -s -o out/d-cors-metrics-pf -D out/d-cors-metrics-pf.h -w "%{http_code}" \
  -X OPTIONS "http://127.0.0.1:$CORS_PORT/metrics" \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: GET")"
echo "cors_preflight_metrics_status=$CORS_METRICS_PF"
test "$CORS_METRICS_PF" = "204"
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" out/d-cors-metrics-pf.h

CORS_EVIL="$(curl -s -o out/d-cors-evil.json -D out/d-cors-evil.h -w "%{http_code}" \
  -X OPTIONS "http://127.0.0.1:$CORS_PORT/health" \
  -H "Origin: http://evil.example" \
  -H "Access-Control-Request-Method: GET" \
  -H "X-Request-Id: mvp-cors-opt-403")"
echo "cors_preflight_evil_status=$CORS_EVIL body=$(cat out/d-cors-evil.json)"
test "$CORS_EVIL" = "403"
grep -q "cors_denied" out/d-cors-evil.json
if grep -qiE "^access-control-allow-origin:[[:space:]]*http://evil.example" out/d-cors-evil.h; then
  echo "evil origin must not receive ACAO"
  exit 1
fi
grep -qiE "^x-request-id:[[:space:]]*mvp-cors-opt-403" out/d-cors-evil.h

HEALTH_CORS="$(curl -s -o out/d-health-cors.json -D out/d-health-cors.h -w "%{http_code}" \
  "http://127.0.0.1:$CORS_PORT/health" -H "Origin: http://localhost:3000")"
echo "cors_get_health_status=$HEALTH_CORS"
test "$HEALTH_CORS" = "200"
grep -Eq '"ok"[[:space:]]*:[[:space:]]*true' out/d-health-cors.json
grep -q ai-bom out/d-health-cors.json
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" out/d-health-cors.h
grep -qiE "^access-control-expose-headers:.*x-request-id" out/d-health-cors.h
grep -qiE "^access-control-expose-headers:.*retry-after" out/d-health-cors.h
grep -qiE "^x-request-id:" out/d-health-cors.h

HTML_CORS="$(curl -s -o out/d-html-cors.html -D out/d-html-cors.h -w "%{http_code}" \
  "http://127.0.0.1:$CORS_PORT/" -H "Origin: http://localhost:3000")"
echo "cors_get_html_status=$HTML_CORS"
test "$HTML_CORS" = "200"
grep -qi 'component' out/d-html-cors.html
grep -Eqi 'license|许可证' out/d-html-cors.html
grep -Eqi 'policy hit|policy hits' out/d-html-cors.html
grep -q 'hosted inventory' out/d-html-cors.html
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" out/d-html-cors.h

BOM_CORS="$(curl -s -o out/d-bom-cors.json -D out/d-bom-cors.h -w "%{http_code}" \
  "http://127.0.0.1:$CORS_PORT/bom.json" -H "Origin: http://localhost:3000")"
echo "cors_get_bom_status=$BOM_CORS"
test "$BOM_CORS" = "200"
grep -q MIT out/d-bom-cors.json
python3 - <<"PYBOMCORS"
import json
from pathlib import Path
bom = json.loads(Path("out/d-bom-cors.json").read_text())
assert bom.get("bomFormat") == "CycloneDX"
assert any(
    (e.get("license") or {}).get("id") == "MIT"
    for c in bom.get("components") or []
    for e in (c.get("licenses") or [])
), "cors /bom.json must include MIT"
assert (bom.get("summary") or {}).get("licenses", {}).get("MIT", 0) >= 1
print("cors bom.json MIT ok", bom["summary"].get("licenses"))
PYBOMCORS
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" out/d-bom-cors.h

EV_CORS="$(curl -s -o out/d-evidence-cors.md -D out/d-evidence-cors.h -w "%{http_code}" \
  "http://127.0.0.1:$CORS_PORT/evidence.md" -H "Origin: http://localhost:3000")"
echo "cors_get_evidence_status=$EV_CORS"
test "$EV_CORS" = "200"
grep -q "DRAFT" out/d-evidence-cors.md
grep -q "AI-BOM Compliance Evidence" out/d-evidence-cors.md
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" out/d-evidence-cors.h

OPENAPI_CORS="$(curl -s -o out/d-openapi-cors.json -D out/d-openapi-cors.h -w "%{http_code}" \
  "http://127.0.0.1:$CORS_PORT/openapi.json" -H "Origin: http://localhost:3000")"
echo "cors_get_openapi_status=$OPENAPI_CORS"
test "$OPENAPI_CORS" = "200"
grep -q '"openapi"' out/d-openapi-cors.json
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" out/d-openapi-cors.h
grep -qiE "^x-request-id:" out/d-openapi-cors.h

METRICS_CORS="$(curl -s -o out/d-metrics-cors.txt -D out/d-metrics-cors.h -w "%{http_code}" \
  "http://127.0.0.1:$CORS_PORT/metrics" -H "Origin: http://localhost:3000" \
  -H "X-Request-Id: mvp-cors-metrics-rid")"
echo "cors_get_metrics_status=$METRICS_CORS"
test "$METRICS_CORS" = "200"
grep -q 'ai_bom_component_count' out/d-metrics-cors.txt
grep -q 'ai_bom_policy_hits' out/d-metrics-cors.txt
grep -q 'ai_bom_forbidden_licenses' out/d-metrics-cors.txt
grep -qiE "^access-control-allow-origin:[[:space:]]*http://localhost:3000" out/d-metrics-cors.h
grep -qiE "^access-control-expose-headers:.*x-request-id" out/d-metrics-cors.h
grep -qiE "^x-request-id:[[:space:]]*mvp-cors-metrics-rid" out/d-metrics-cors.h

HEALTH_EVIL="$(curl -s -o out/d-health-evil.json -D out/d-health-evil.h -w "%{http_code}" \
  "http://127.0.0.1:$CORS_PORT/health" -H "Origin: http://evil.example")"
echo "cors_get_evil_status=$HEALTH_EVIL"
test "$HEALTH_EVIL" = "200"
if grep -qiE "^access-control-allow-origin:" out/d-health-evil.h; then
  echo "disallowed origin should not get ACAO"
  cat out/d-health-evil.h
  exit 1
fi

if [ -n "${CORS_PID:-}" ]; then
  kill "$CORS_PID" 2>/dev/null || true
  wait "$CORS_PID" 2>/dev/null || true
  CORS_PID=""
fi
trap - EXIT
echo "==> [cors] allow localhost:3000 / deny evil.example OK (isolated); main server default deny"

echo "==> [rate-limit] isolated serve --rate-limit 2 (third /bom.json is 429; /health still 200)"
RL_PORT="${RL_PORT:-$((PORT + 40))}"
RL_LOG="$ROOT/out/rl-serve.log"
rm -f "$RL_LOG" out/d-rl-1.json out/d-rl-2.json out/d-rl-3.json out/d-rl-3.h out/d-rl-health.json
unset AI_BOM_CORS_ORIGINS || true
unset RATE_LIMIT_PER_MINUTE RATE_LIMIT_RPM || true
python3 -m ai_bom serve --path examples/sample-app --port "$RL_PORT" --host 127.0.0.1 \
  --policy policies/default.json --rate-limit 2 >"$RL_LOG" 2>&1 &
RL_PID=$!
cleanup_rl() {
  if [ -n "${RL_PID:-}" ] && kill -0 "$RL_PID" 2>/dev/null; then
    kill "$RL_PID" 2>/dev/null || true
    wait "$RL_PID" 2>/dev/null || true
  fi
}
trap cleanup_rl EXIT
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$RL_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 50 ]; then
    echo "rate-limit serve did not become healthy"
    cat "$RL_LOG" || true
    exit 1
  fi
done
RL1="$(curl -s -o out/d-rl-1.json -w "%{http_code}" "http://127.0.0.1:$RL_PORT/bom.json")"
RL2="$(curl -s -o out/d-rl-2.json -w "%{http_code}" "http://127.0.0.1:$RL_PORT/bom.json")"
RL3="$(curl -s -o out/d-rl-3.json -D out/d-rl-3.h -w "%{http_code}" "http://127.0.0.1:$RL_PORT/bom.json" -H "X-Request-Id: mvp-rl-rid-429")"
echo "rl_hit_1=$RL1 rl_hit_2=$RL2 rl_hit_3=$RL3 body=$(cat out/d-rl-3.json)"
test "$RL1" = "200"
test "$RL2" = "200"
test "$RL3" = "429"
grep -qi '^Retry-After:' out/d-rl-3.h
grep -qiE '^x-request-id:[[:space:]]*mvp-rl-rid-429' out/d-rl-3.h
grep -Eq '"ok"[[:space:]]*:[[:space:]]*false' out/d-rl-3.json
grep -Eq '"reason"[[:space:]]*:[[:space:]]*"rate_limited"' out/d-rl-3.json
RL_HEALTH="$(curl -s -o out/d-rl-health.json -w "%{http_code}" "http://127.0.0.1:$RL_PORT/health")"
RL_READY="$(curl -s -o out/d-rl-ready.json -w "%{http_code}" "http://127.0.0.1:$RL_PORT/ready")"
RL_METRICS="$(curl -s -o out/d-rl-metrics.txt -w "%{http_code}" "http://127.0.0.1:$RL_PORT/metrics")"
echo "rl_health=$RL_HEALTH rl_ready=$RL_READY rl_metrics=$RL_METRICS"
test "$RL_HEALTH" = "200"
test "$RL_READY" = "200"
test "$RL_METRICS" = "200"
grep -Eq '"ok"[[:space:]]*:[[:space:]]*true' out/d-rl-health.json
cleanup_rl
RL_PID=""
trap - EXIT
echo "==> [rate-limit] 429 + Retry-After OK (isolated); probes excluded; main serve unchanged"

echo "==> [watch] isolated serve --watch (dir max-mtime poll rescan; must not hang)"
WATCH_PORT="${WATCH_PORT:-8823}"
WATCH_TMP="$(mktemp -d)"
WATCH_LOG="$ROOT/out/watch-serve.log"
rm -f "$WATCH_LOG" out/watch-before-health.json out/watch-after-health.json out/watch-after-bom.json out/watch-after-metrics.txt
printf '%s\n' 'MODEL = "gpt-4o-mini"' > "$WATCH_TMP/app.py"
unset AI_BOM_CORS_ORIGINS || true
python3 -m ai_bom serve --path "$WATCH_TMP" --port "$WATCH_PORT" --host 127.0.0.1 --watch >"$WATCH_LOG" 2>&1 &
WATCH_PID=$!
cleanup_watch() {
  if [ -n "${WATCH_PID:-}" ] && kill -0 "$WATCH_PID" 2>/dev/null; then
    kill "$WATCH_PID" 2>/dev/null || true
    wait "$WATCH_PID" 2>/dev/null || true
  fi
  rm -rf "$WATCH_TMP"
}
trap cleanup_watch EXIT

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

curl -sf "http://127.0.0.1:$WATCH_PORT/health" -o out/watch-before-health.json
BEFORE_COUNT="$(python3 -c 'import json; print(json.load(open("out/watch-before-health.json"))["componentCount"])')"
echo "watch_before componentCount=$BEFORE_COUNT"
test -n "$BEFORE_COUNT"
test "$BEFORE_COUNT" -ge 1

python3 -c '
import os, time
from pathlib import Path
p = Path("'"$WATCH_TMP"'") / "extra.py"
p.write_text("MODEL = \"claude-3-opus\"\n", encoding="utf-8")
now = time.time() + 1
os.utime(p, (now, now))
print("added", p)
'

REGEN_OK=0
for _ in $(seq 1 25); do
  curl -sf "http://127.0.0.1:$WATCH_PORT/health" -o out/watch-after-health.json || true
  AFTER_COUNT=""
  if test -s out/watch-after-health.json; then
    AFTER_COUNT="$(python3 -c 'import json,sys
try:
  print(json.load(open("out/watch-after-health.json")).get("componentCount",""))
except Exception:
  pass' || true)"
  fi
  if grep -q regenerated "$WATCH_LOG" 2>/dev/null; then
    curl -sf "http://127.0.0.1:$WATCH_PORT/health" -o out/watch-after-health.json || true
    curl -sf "http://127.0.0.1:$WATCH_PORT/bom.json" -o out/watch-after-bom.json || true
    curl -sf "http://127.0.0.1:$WATCH_PORT/metrics" -o out/watch-after-metrics.txt || true
    curl -sf "http://127.0.0.1:$WATCH_PORT/" -o out/watch-after.html || true
    REGEN_OK=1
    break
  fi
  if [ -n "$AFTER_COUNT" ] && [ "$AFTER_COUNT" -gt "$BEFORE_COUNT" ] 2>/dev/null; then
    curl -sf "http://127.0.0.1:$WATCH_PORT/bom.json" -o out/watch-after-bom.json || true
    curl -sf "http://127.0.0.1:$WATCH_PORT/metrics" -o out/watch-after-metrics.txt || true
    curl -sf "http://127.0.0.1:$WATCH_PORT/" -o out/watch-after.html || true
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
trap - EXIT

if [ "$REGEN_OK" != "1" ]; then
  echo "watch did not regenerate within 5s"
  echo "--- watch-serve.log ---"
  cat "$WATCH_LOG" || true
  exit 1
fi

test -s out/watch-after-health.json
AFTER_COUNT="$(python3 -c 'import json; print(json.load(open("out/watch-after-health.json"))["componentCount"])')"
echo "watch_after componentCount=$AFTER_COUNT"
export BEFORE_COUNT AFTER_COUNT
python3 -c '
import os, sys
b = int(os.environ["BEFORE_COUNT"])
a = int(os.environ["AFTER_COUNT"])
if not (a > b):
    print("expected componentCount to increase", {"before": b, "after": a}, file=sys.stderr)
    sys.exit(1)
print("watch_reload_ok", {"before": b, "after": a})
'
if ! grep -q regenerated "$WATCH_LOG"; then
  echo "watch regenerate detected via HTTP but missing regenerated log line"
  cat "$WATCH_LOG" || true
  exit 1
fi
grep -q "watching" "$WATCH_LOG"
if test -s out/watch-after-metrics.txt; then
  grep -q "ai_bom_component_count" out/watch-after-metrics.txt
fi
if test -s out/watch-after-bom.json; then
  grep -q "claude-3-opus" out/watch-after-bom.json
fi
echo "watch regenerate OK"

echo "==> [config] isolated serve --webhook-url/--webhook-secret (GET /v1/config 200; secret not leaked)"
CFG_ISO_PORT="${CFG_ISO_PORT:-8843}"
CFG_ISO_LOG="$ROOT/out/config-iso-serve.log"
CFG_ISO_SECRET="http_whsec_must_not_leak"
CFG_ISO_URL="http://127.0.0.1:9/hook?token=http_url_token_must_not_leak"
rm -f "$CFG_ISO_LOG" out/iso-config.json out/iso-config.h
unset AI_BOM_CORS_ORIGINS || true
unset AI_BOM_WEBHOOK_URL AI_BOM_WEBHOOK_SECRET || true
unset RATE_LIMIT_PER_MINUTE RATE_LIMIT_RPM || true
python3 -m ai_bom serve --path examples/sample-app --port "$CFG_ISO_PORT" --host 127.0.0.1 \
  --policy policies/default.json \
  --webhook-url "$CFG_ISO_URL" --webhook-secret "$CFG_ISO_SECRET" \
  --cors-origins "http://localhost:3000" \
  >"$CFG_ISO_LOG" 2>&1 &
CFG_ISO_PID=$!
cleanup_cfg_iso() {
  if [ -n "${CFG_ISO_PID:-}" ] && kill -0 "$CFG_ISO_PID" 2>/dev/null; then
    kill "$CFG_ISO_PID" 2>/dev/null || true
    wait "$CFG_ISO_PID" 2>/dev/null || true
  fi
}
trap cleanup_cfg_iso EXIT
for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$CFG_ISO_PORT/health" >/dev/null; then
    break
  fi
  sleep 0.1
  if [ "$i" -eq 50 ]; then
    echo "config isolate serve did not become healthy"
    cat "$CFG_ISO_LOG" || true
    exit 1
  fi
done
ISO_CFG="$(curl -s -o out/iso-config.json -D out/iso-config.h -w "%{http_code}" \
  "http://127.0.0.1:$CFG_ISO_PORT/v1/config" -H "X-Request-Id: mvp-config-iso-d1")"
echo "iso_config_status=$ISO_CFG"
test "$ISO_CFG" = "200"
grep -qiE "^content-type:[[:space:]]*application/json" out/iso-config.h
grep -qiE "^x-request-id:[[:space:]]*mvp-config-iso-d1" out/iso-config.h
CFG_ISO_SECRET="$CFG_ISO_SECRET" python3 - <<"PYISOCFG"
import json, os
from pathlib import Path
d = json.loads(Path("out/iso-config.json").read_text())
secret = os.environ["CFG_ISO_SECRET"]
assert d.get("ok") is True, d
assert (d.get("cors") or {}).get("origins") == ["http://localhost:3000"], d
assert (d.get("webhooks") or {}).get("hasUrl") is True, d
assert (d.get("webhooks") or {}).get("hasSecret") is True, d
assert d.get("hasPolicyFile") is True, d
blob = json.dumps(d, ensure_ascii=False)
for n in (secret, "http_url_token_must_not_leak", "127.0.0.1:9", "webhookUrl", "webhookSecret", "whsec_"):
    assert n not in blob, (n, d)
print("iso_config_redacted_ok", {"rateLimit": d.get("rateLimit"), "hasUrl": d["webhooks"]["hasUrl"], "hasSecret": d["webhooks"]["hasSecret"], "scanPathBase": d.get("scanPathBase")})
PYISOCFG
cleanup_cfg_iso
CFG_ISO_PID=""
trap - EXIT
echo "==> [config] isolated webhook not leaked OK"

echo "d-ai-bom local-mvp OK (scan+serve+cors+request-id+openapi+metrics+webhook+hmac+watch+cyclonedx+spdx+spdx3+cyclonedx-xml+spdx-xml+md+html+rate-limit+exceptions+policy+config+exceptionsList+advisories+osv-convert+mlbom-obs+spdx3-ai+evidence-pack+cra-clock+vex)"
