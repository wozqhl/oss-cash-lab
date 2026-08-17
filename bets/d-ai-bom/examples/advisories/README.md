# Local advisory fixtures

Offline known-issue vs scanned-components list for `scan --advisories` / `--gate-vulns`.

This is a **fixture format**, not a CVE database. Shipped IDs are `ADV-FIXTURE-*` placeholders. The CLI does **not** fetch NVD, OSV, or GitHub Advisory.

| File | Against `examples/sample-app` | Expected |
|------|-------------------------------|----------|
| `sample.json` | planted hits (`ADV-FIXTURE-1` / `2` / `3`) | `--gate-vulns` exit **1** |
| `clean.json` | no identity match (wrong name, or same name + other version) | `--gate-vulns` exit **0** |

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
| `component.version` | no | If set, scanned component version must equal it |
| `severity` | no | Informational (`high` / `medium` / `low`) |
| `summary` | no | Human note — do not invent a CVE here |

Match is **AND** of every identity field the advisory specifies. No version-range matching. No CPE. No NVD completeness claim.

## Pointing this at OSV / GitHub Advisory later

Honest split: **fixture now, feed later**.

1. Export or dump the feed you already trust (OSV, GitHub Advisory / GHSA, or a vendor mirror) **offline**.
2. Convert each record into this schema: `id` from the OSV/GHSA id; `component.name` / `purl` / `version` from `affected[].package` (exact versions you care about). Version **ranges** are out of scope for this gate — pin exact versions or omit version to match the package identity only.
3. Point the same CLI at the converted file:

```bash
python3 -m ai_bom scan . --advisories path/to/osv-or-ghsa-export.json --gate-vulns
```

This repository does not ship a converter or a live client. Do not treat a green `--gate-vulns` as "no CVEs on the internet."

CRA Article 14 (11 Sep 2026) is a 24h reporting clock that needs inventory + a match against known issues. Full SBOM duty is 11 Dec 2027. See [`docs/cra.md`](../../docs/cra.md).
