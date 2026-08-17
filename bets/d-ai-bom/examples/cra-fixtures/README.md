# CRA license-policy fixtures

Committed pass/fail trees for the CI license gate (`--gate-licenses` / `--strict` + `policies/default.json`).

| Tree | License | Expected |
|------|---------|----------|
| `license-pass/` | MIT | exit **0** |
| `license-fail/` | planted `GPL-3.0` | exit **1** |

## How to run

From `bets/d-ai-bom`:

```bash
export PYTHONPATH=src

# PASS (MIT, one model, no pickle)
python3 -m ai_bom scan examples/cra-fixtures/license-pass \
  --policy policies/default.json --gate-licenses
echo exit=$?   # 0

# FAIL (planted GPL-3.0)
python3 -m ai_bom scan examples/cra-fixtures/license-fail \
  --policy policies/default.json --gate-licenses
echo exit=$?   # 1

# Same gate via --strict (these fixtures have no pickle / disclosure gaps)
python3 -m ai_bom scan examples/cra-fixtures/license-pass \
  --policy policies/default.json --strict; echo pass_strict=$?
python3 -m ai_bom scan examples/cra-fixtures/license-fail \
  --policy policies/default.json --strict; echo fail_strict=$?
```

`--gate-licenses` fails **only** on `forbiddenLicenseIds` (GPL-3.0 / AGPL-3.0 / SSPL-1.0 + variants). `--strict` also fails on pickle / disclosure gaps (sample-app is `--strict` red because of `pickle.load`, but `--gate-licenses` green because of MIT).

See [`docs/cra.md`](../../docs/cra.md).
