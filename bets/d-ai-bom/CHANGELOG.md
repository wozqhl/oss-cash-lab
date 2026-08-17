# Changelog · D ai-bom

Bet-local notes. Portfolio root `CHANGELOG.md` is separate and is not updated here.

## Unreleased

### CycloneDX 1.7 + ML-BOM

- `--format cyclonedx` / `cyclonedx-xml` (and `GET /v1/bom?format=`) now emit **CycloneDX 1.7** (`specVersion=1.7`, XML xmlns `bom/1.7`).
- Model / model-file components keep `machine-learning-model` and gain a `modelCard` only from existing scan fields (`aibom:format`, `aibom:sourcePath` basename). Prompts stay `data` with a name-only `data[]` entry. No invented architecture, datasets, or metrics.
- Internal AI-BOM JSON `specVersion` is 1.7 for consistency; custom `summary` is still not a conformance document.

### License-policy CI gate

- `scan --gate-licenses` exits **1** on `forbiddenLicenseIds` matches (same `policies/default.json` pack). Does not fail on pickle / disclosure gaps (`--strict` still does).
- Fixtures: `examples/cra-fixtures/license-pass` (MIT, exit 0) and `examples/cra-fixtures/license-fail` (planted GPL-3.0, exit 1).
- Consumer workflow `examples/github-actions/ai-bom-sarif.yml` keeps the existing `--sarif` upload and adds a live `--gate-licenses` step on sample-app.

### Docs

- `docs/cra.md` — Article 14 (11 Sep 2026) vs essential requirements (11 Dec 2027); what is emitted; what is **not** claimed. Official CRA + CycloneDX ML-BOM guide links. No certification language.
