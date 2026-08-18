# Local advisory fixtures

Offline known-issue vs scanned-components list for `scan --advisories` / `--gate-vulns`.

This is a **fixture format**, not a CVE database. Shipped IDs are `ADV-FIXTURE-*` placeholders. The CLI does **not** fetch NVD, OSV, or GitHub Advisory.

| File | Against `examples/sample-app` | Expected |
|------|-------------------------------|----------|
| `sample.json` | planted hits (`ADV-FIXTURE-1` / `2` / `3`) | `--gate-vulns` exit **1** |
| `clean.json` | no identity match (wrong name, or same name + other version) | `--gate-vulns` exit **0** |
| `range-in.json` | sample-app 0.0.1 inside >=0.0.1,<0.1.0 | `--gate-vulns` exit **1** |
| `range-out.json` | sample-app 0.0.1 outside >=9.0.0,<10.0.0 | `--gate-vulns` exit **0** |
| `range-skip.json` | unparseable range | skip, no invented hit |

## How to run

From `bets/d-ai-bom`:

```bash
export PYTHONPATH=src

# planted hit
python3 -m ai_bom scan examples/sample-app \
  --advisories examples/advisories/sample.json --gate-vulns
echo exit=$?   # 1

# clean file
python3 -m ai_bom scan examples/sample-app \
  --advisories examples/advisories/clean.json --gate-vulns
echo exit=$?   # 0
```

No network. A missing `--advisories` with `--gate-vulns` is a usage error (exit 2).

## Schema

JSON object (`schema`: `ai-bom-advisories/v1`) with an `advisories` array. Each entry:

| Field | Required | Notes |
|-------|----------|--------|
| `id` | yes | Fixture id (`ADV-FIXTURE-*`) or, later, a real GHSA/OSV id from **your** feed |
| `component.name` | name **or** purl | Case-insensitive exact |
| `component.purl` | name **or** purl | Package-URL identity; versioned advisory does not match an unversioned component |
| `component.version` | no | If set, scanned component version must equal it (exact versions[] match unchanged) |
| `component.versionRange` | no | Operators >= > < <= = and comma/AND; unparseable = skip |
| `severity` | no | Informational (`high` / `medium` / `low`) |
| `summary` | no | Human note — do not invent a CVE here |

Match is **AND** of every identity field the advisory specifies, plus recorded versionRange operators (>= > < <= = and comma/AND). Unparseable ranges are skipped (no invented hit). No CPE. No NVD completeness claim.

## Offline OSV / GitHub Advisory converter

Honest split: **dump the feed you trust, convert locally, no fetch**.

1. Export or dump OSV or GitHub Advisory JSON **offline**.
2. Convert into this schema (IDs stay `OSV-*` / `GHSA-*`; unmappable records are skipped and counted):

```bash
python3 -m ai_bom convert-advisories --from-osv examples/advisories/osv-sample.json --out /tmp/from-osv.json
python3 -m ai_bom convert-advisories --from-ghsa examples/advisories/ghsa-sample.json --out /tmp/from-ghsa.json
```

| File | Against `examples/sample-app` | Expected after convert |
|------|-------------------------------|------------------------|
| `osv-sample.json` | `openai` (PyPI; unversioned in sample-app, so a recorded range does not invent a hit) | `--gate-vulns` exit **0** |
| same file vs `examples/cra-fixtures/license-pass` | no openai | `--gate-vulns` exit **0** |
| `ghsa-sample.json` | same `openai` identity; id stays `GHSA-*` | convert keeps `GHSA-xxxx-xxxx-samp` |

3. Point the same CLI at the converted file:

```bash
python3 -m ai_bom scan examples/sample-app --advisories /tmp/from-osv.json --gate-vulns
python3 -m ai_bom scan examples/cra-fixtures/license-pass --advisories /tmp/from-osv.json --gate-vulns
```

The converter copies package name / ecosystem / exact versions when present. Version **ranges** are recorded (`component.versionRange` + summary note) and the gate evaluates those operators. Unparseable ranges are skipped (no invented hit). Exact versions stay pinned from the source `versions[]` list. It does not invent CVSS or affected versions. This CLI does not fetch osv.dev or api.github.com. Do not treat a green `--gate-vulns` as "no CVEs on the internet."

CRA Article 14 (11 Sep 2026) is a 24h reporting clock that needs inventory + a match against known issues. Full SBOM duty is 11 Dec 2027. See [`docs/cra.md`](../../docs/cra.md).
