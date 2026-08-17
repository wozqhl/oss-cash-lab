# Changelog · D ai-bom

Bet-local notes. Portfolio root `CHANGELOG.md` is separate and is not updated here.

## Unreleased

### Advisory-match gate (Article 14 inventory+match)

- `scan --advisories <file> --gate-vulns` matches scanned component name/purl/version against a **local** JSON fixture and exits **1** on hits. Offline only — no NVD/OSV/GitHub Advisory fetch.
- Fixtures: `examples/advisories/sample.json` (planted `ADV-FIXTURE-*` hits on sample-app → exit 1) and `examples/advisories/clean.json` (no match → exit 0). IDs are placeholders, not real CVEs.
- Honest later path: convert an OSV/GHSA export into the same schema and point `--advisories` at it. Not a CVE database; not NVD completeness.

### SPDX 3.0.1 JSON

- `--format spdx3` / `GET /v1/bom?format=spdx3` (alias `spdx-3`) emits compact **SPDX 3.0.1** JSON (`creationInfo.specVersion=3.0.1`, `spdxId`, `name`, `element` of `software_Package` + license expressions). Existing `spdx` / `spdx-xml` stay **SPDX 2.3**.
- Filled from scan data only. Omitted (not invented): files, hashes, contains/dependsOn graph, SPDX 3 AI/security profiles, ExpandedLicensing, CBOM.

### CycloneDX 1.7 + ML-BOM

- `--format cyclonedx` / `cyclonedx-xml` (and `GET /v1/bom?format=`) now emit **CycloneDX 1.7** (`specVersion=1.7`, XML xmlns `bom/1.7`).
- Model / model-file components keep `machine-learning-model` and gain a `modelCard` only from existing scan fields (`aibom:format`, `aibom:sourcePath` basename). Prompts stay `data` with a name-only `data[]` entry. No invented architecture, datasets, or metrics.
- Internal AI-BOM JSON `specVersion` is 1.7 for consistency; custom `summary` is still not a conformance document.

### License-policy CI gate

- `scan --gate-licenses` exits **1** on `forbiddenLicenseIds` matches (same `policies/default.json` pack). Does not fail on pickle / disclosure gaps (`--strict` still does).
- Fixtures: `examples/cra-fixtures/license-pass` (MIT, exit 0) and `examples/cra-fixtures/license-fail` (planted GPL-3.0, exit 1).
- Consumer workflow `examples/github-actions/ai-bom-sarif.yml` keeps the existing `--sarif` upload and adds a live `--gate-licenses` step on sample-app.

### Docs

- `docs/cra.md` — Article 14 (11 Sep 2026, 24h reporting) needs inventory+match; full SBOM 11 Dec 2027; fixture now / OSV-GHSA feed later. Official CRA + CycloneDX ML-BOM guide links. No certification language.
