# Changelog · D ai-bom

Bet-local notes. Portfolio root `CHANGELOG.md` is separate and is not updated here.

## Unreleased

### CRA clock CLI

- `clock --as-of YYYY-MM-DD` prints the same `ai-bom-cra-clock/v1` windows as `evidence-pack` without writing a zip. Optional `--advisories FILE --dir DIR` runs the existing offline fixture match. `--format json` (default) or `text`. Exit 0 even when a window is overdue (not a conformity gate). Calendar/evidence helper, not a CRA compliance certificate. 日历/证据辅助，不是 CRA 合格证书。 Smoke: `clock-cli-ok`.

### OpenVEX 0.2.0 (observed fixture matches)

- `scan --advisories FILE --vex out.json` and `evidence-pack` `vex.json` emit OpenVEX 0.2.0 from observed local-fixture matches (products the scanner actually saw). Status is derived: `affected` on a real match; `not_affected` only with a justification the fixture recorded (otherwise `under_investigation` when versionRange excludes the observed version); `fixed` only when the fixture records `fixedVersion`. Timestamp, author, stable `@id`. Not a CRA conformity claim. 中文: 可利用性声明辅助，不是符合性主张。 Smoke: `vex-ok`.


### CRA window clock (calendar helper)

- `evidence-pack` writes `pack.json` (listed in the zip + MANIFEST) with a `clock` section: `daysUntil` / `daysOverdue` vs **2026-09-11** (Article 14-style reporting) and **2027-12-11** (SBOM calendar). Observed `--gate-vulns` / `convert-advisories` hits inherit those same dates. Optional `--as-of YYYY-MM-DD` freezes the calendar. **EN:** calendar/evidence helper, not a CRA compliance certificate. **中文:** 日历/证据辅助，不是 CRA 合格证书。No invented CVE scores or conformity claims. Smoke: `cra-clock-ok`.

### SPDX 3 AI profile (observed only)

- `--format spdx3` emits `ai_AIPackage` (with `software_primaryPurpose=model`) and adds `ai` to `profileConformance` only when a model/model-file component had observed path+sha256 and/or model-card name/description/license URL. Text-only model mentions stay `software_Package` without an AI profile claim. No invented metrics, trainedOn/testedOn, hyperparameters, or energy.

### Evidence pack (Article 14 orientation)

- `evidence-pack --dir DIR --out OUTDIR` (optional `--zip`) writes CycloneDX 1.7 JSON + SPDX 3.0.1 JSON + MANIFEST.md (files, license/advisory gate exit codes, timestamp). Inventory+match evidence, not a CRA declaration. No invented CVEs, scores, or compliant badges. Defaults: `policies/default.json` + `examples/advisories/sample.json`.

### SPDX 3.0.1 file elements (observed only)

- `--format spdx3` emits `software_File` + package `contains` + file `verifiedUsing` sha256 only when the scan hashed a real file (e.g. `.gguf`). Text-only model names stay packages. No invented files or hashes.

### Observed ML-BOM fields (hashes + on-disk model cards)

- CycloneDX 1.7 / SPDX 2.3 / SPDX 3.0.1 include sha256 and declared model-card name/description/license URL only when the scan observes them. No invented datasets, accuracy, or training metrics.

### OSV/GHSA converter (offline)

- `convert-advisories --from-osv FILE --out OUT.json` maps OSV (and GHSA when the shape is close) into the existing `ai-bom-advisories/v1` fixture. IDs stay `OSV-*` / `GHSA-*`. Skip unmappable records and print converted/skipped counts. Does not invent CVSS or affected versions. Sample: `examples/advisories/osv-sample.json`. No live NVD/OSV client.

### Advisory-match gate (Article 14 inventory+match)

- `scan --advisories <file> --gate-vulns` matches scanned component name/purl/version and recorded versionRange operators against a **local** JSON fixture and exits **1** on hits. Offline only — no NVD/OSV/GitHub Advisory fetch.
- Fixtures: `examples/advisories/sample.json` (planted `ADV-FIXTURE-*` hits on sample-app → exit 1) and `examples/advisories/clean.json` (no match → exit 0). IDs are placeholders, not real CVEs.
- Honest path: `convert-advisories --from-osv` writes the same schema; point `--advisories` at the export. Not a CVE database; not NVD completeness.

### SPDX 3.0.1 JSON

- `--format spdx3` / `GET /v1/bom?format=spdx3` (alias `spdx-3`) emits compact **SPDX 3.0.1** JSON (`creationInfo.specVersion=3.0.1`, `spdxId`, `name`, `element` of `software_Package` + license expressions). Existing `spdx` / `spdx-xml` stay **SPDX 2.3**.
- Filled from scan data only. Omitted (not invented): unobserved files/hashes, trainedOn/testedOn datasets, AI metrics, security/CVE profile, ExpandedLicensing, CBOM. AI profile only when observed.

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
