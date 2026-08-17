# Roadmap · D ai-bom

Bet-local. Portfolio root `ROADMAP.md` is separate and is not updated here.

## Now (local-mvp)

- Directory scan → internal AI-BOM + **CycloneDX 1.7** JSON/XML (ML-BOM fields the scanner already has) + SPDX 2.3 + SARIF 2.1.0.
- License-policy CI gate: `--gate-licenses` / `--strict` + `policies/default.json`; pass/fail CRA fixtures.
- CRA orientation in `docs/cra.md` (not a conformity claim).

## Next (still OSS)

- Richer ML-BOM only when the scan observes the field (hashes, declared model cards on disk). Do not invent datasets or metrics.
- SPDX 3.x exporter if a consumer needs BSI TR-03183-2’s SPDX 3.0.1+ reading (today: SPDX 2.3, honest).
- Keep the GitHub Actions consumer example (`ai-bom-sarif.yml`) as copy-paste, not a live gate on this repo.

## Paid later (not this tree)

- Managed policy packs, hosted inventory, signed auditor packs, webhook queues / key rotation.
