# Changelog · D ai-bom

Bet-local notes. Portfolio root `CHANGELOG.md` is separate and is not updated here.

## Unreleased

### Serve CRA calendar clock

- Local `serve` exposes `GET /clock.json` / `GET /clock` (JSON), `/clock.md`, `/clock.html`, `/clock.ics`, and `GET /v1/clock?format=json|md|html|ics|gha|text` (same bodies as CLI clock formats; bad format → 400 `bad_format`). Optional `?as-of=YYYY-MM-DD` (UTC; invalid → 400 `bad_as_of`; default today UTC). Observed vulns default empty (same as bare `ai-bom clock`); buyers still use CLI `--advisories` / evidence-pack for matched counts. Listen banner + index nav + OpenAPI document the paths with honest "calendar helper, not a CRA certificate" / 日历辅助 wording. Calendar/evidence helper, not a CRA compliance certificate. 日历/证据辅助，不是 CRA 合格证书。 Smoke: `serve-clock-ok`.

### Evidence-pack CLOCK.html + CLOCK.ics

- `evidence-pack` now also writes `CLOCK.html` and `CLOCK.ics` (same bodies as `clock --format html|ics`) alongside `CLOCK.md`. Listed in `pack.json` `files`, MANIFEST, outdir, and zip. Calendar/evidence helper, not a CRA compliance certificate. 日历/证据辅助，不是 CRA 合格证书。 Smoke: `evidence-pack-ok` / `cra-clock-ok` (+ `clock-pack-html-ics-ok`).

### CRA clock md/html/ics + CLOCK.md in evidence-pack

- `clock --format md` prints bilingual Markdown (disclaimer first, asOf, article14/sbom daysUntil/daysOverdue/status table, notes) for ticket/Slack/PR paste. Plain markdown, no HTML. Same body is written as evidence-pack `CLOCK.md` (outdir + zip; listed in `pack.json` `files` and MANIFEST).
- `clock --format html` prints self-contained HTML (no CDN; near/due/overdue rows class=warn). Same body is written as evidence-pack `CLOCK.html`.
- `clock --format ics` prints RFC 5545 VCALENDAR with two all-day VEVENTs (VALUE=DATE) for Article 14 reporting start and SBOM essential-requirements start. Stable UIDs `ai-bom-cra-article14@wozqhl` / `ai-bom-cra-sbom@wozqhl`. SUMMARY/DESCRIPTION say calendar helper, not certificate. Same body is written as evidence-pack `CLOCK.ics`.
- Exit 0 even when overdue. Calendar/evidence helper, not a CRA compliance certificate. 日历/证据辅助，不是 CRA 合格证书。 Smoke: `clock-cli-ok` / `evidence-pack-ok` / `cra-clock-ok`.

### Buyer CRA Article 14 clock demo

- `scripts/demo-cra-clock.sh`: bilingual banner (日历/证据辅助，不是 CRA 合格证书) + `clock --format text` (today UTC) + optional sample-app advisories + 3–5 buyer talking points (paste `ai-bom-clock.yml`, evidence-pack zip, never say compliant). Calendar helper, not a CRA certificate. README 30s + `docs/cra.md` buyer-demo subsection. Smoke: `demo-cra-clock-ok` (+ `clock-cli-ok` / `cra-clock-ok`).

### CRA clock GHA annotations

- `clock --format gha` prints GitHub Actions workflow commands: bilingual disclaimer `::notice`, article14 `::notice` (daysUntil>7) or `::warning` (≤7 / due / overdue), sbom `::notice`, and optional observedVulnCount fixture notice. Never `::error`; exit 0 even when overdue. Calendar/evidence helper, not a CRA compliance certificate. 日历/证据辅助，不是 CRA 合格证书。 Copy-paste `examples/github-actions/ai-bom-clock.yml`. Smoke stays `clock-cli-ok`.

### CRA clock CLI

- `clock --as-of YYYY-MM-DD` prints the same `ai-bom-cra-clock/v1` windows as `evidence-pack` without writing a zip. Optional `--advisories FILE --dir DIR` runs the existing offline fixture match. `--format json` (default), `text`, `gha`, `md`, `html`, or `ics`. Exit 0 even when a window is overdue (not a conformity gate). Calendar/evidence helper, not a CRA compliance certificate. 日历/证据辅助，不是 CRA 合格证书。 Smoke: `clock-cli-ok`.
- README 30-second clock: from the bet directory, `python3 -m pip install -e .` then `ai-bom clock --format text` (default as-of = today UTC). `python3 -m ai_bom` is equivalent. Optional `--as-of` / `--dir` / `--advisories` stay below the copy-paste. Calendar/evidence helper, not a CRA certificate. 日历/证据辅助，不是 CRA 合格证书。

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
