# Roadmap · D ai-bom

Bet-local. Portfolio root `ROADMAP.md` is separate and is not updated here.

## Now (local-mvp)

- Directory scan → internal AI-BOM + **CycloneDX 1.7** JSON/XML (ML-BOM fields the scanner already has) + SPDX 2.3 + **SPDX 3.0.1** JSON + SARIF 2.1.0.
- License-policy CI gate: `--gate-licenses` / `--strict` + `policies/default.json`; pass/fail CRA fixtures.
- Advisory-match CI gate: `--advisories` / `--gate-vulns` against a local fixture (recorded versionRange operators evaluated) (`ADV-FIXTURE-*`). Article 14 inventory+match; not NVD.
- Offline OSV/GHSA to local fixture converter (`convert-advisories --from-osv`). No live NVD/OSV client.
- CRA orientation in `docs/cra.md` (not a conformity claim). BSI “either format” is honest: CycloneDX 1.7 **or** SPDX 3.0.1.
- Local evidence pack: `evidence-pack --dir DIR --out OUTDIR` (CycloneDX 1.7 + SPDX 3.0.1 + MANIFEST + `pack.json` with gate codes). Article 14 orientation, not a conformity claim.
- CRA window clock in `pack.json` `clock` (and MANIFEST / zip): days-until / days-overdue vs 2026-09-11 and 2027-12-11 from observed advisory hits. Calendar/evidence helper, not a CRA compliance certificate. 日历/证据辅助，不是 CRA 合格证书。
- Richer ML-BOM only when observed: sha256 of model files + on-disk model-card name/description/license URL. SPDX 3.0.1 `software_File` + package `contains` file when a real hashed file was scanned. No invented datasets, metrics, files, or hashes.
- Richer SPDX 3 AI profile only when observed: `ai_AIPackage` + `profileConformance` includes `ai` only when a model/model-file had path+sha256 and/or model-card fields. Text-only model name mentions stay `software_Package`. No invented metrics, trainedOn/testedOn, or energy.

## Next (still OSS)

- Keep SPDX 3 AI graph honest: still no invented datasets, metrics, hyperparameters, or security/CVE profile.
- Keep the GitHub Actions consumer example (`ai-bom-sarif.yml`) as copy-paste, not a live gate on this repo.
- Keep converter offline: dump the feed you trust, then `convert-advisories`. No live NVD/OSV client in smoke.

## Paid later (not this tree)

- Managed policy packs, hosted inventory, signed auditor packs, webhook queues / key rotation.
