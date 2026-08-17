# Roadmap · D ai-bom

Bet-local. Portfolio root `ROADMAP.md` is separate and is not updated here.

## Now (local-mvp)

- Directory scan → internal AI-BOM + **CycloneDX 1.7** JSON/XML (ML-BOM fields the scanner already has) + SPDX 2.3 + **SPDX 3.0.1** JSON + SARIF 2.1.0.
- License-policy CI gate: `--gate-licenses` / `--strict` + `policies/default.json`; pass/fail CRA fixtures.
- Advisory-match CI gate: `--advisories` / `--gate-vulns` against a local fixture (`ADV-FIXTURE-*`). Article 14 inventory+match; not NVD.
- CRA orientation in `docs/cra.md` (not a conformity claim). BSI “either format” is honest: CycloneDX 1.7 **or** SPDX 3.0.1.

## Next (still OSS)

- Richer ML-BOM only when the scan observes the field (hashes, declared model cards on disk). Do not invent datasets or metrics.
- Richer SPDX 3 graph only when the scan observes it (files, hashes, AI profile). Today: compact document + packages/licenses.
- Keep the GitHub Actions consumer example (`ai-bom-sarif.yml`) as copy-paste, not a live gate on this repo.
- Optional OSV / GitHub Advisory **export converter** into the local fixture schema (still offline; no live NVD client in smoke).

## Paid later (not this tree)

- Managed policy packs, hosted inventory, signed auditor packs, webhook queues / key rotation.
