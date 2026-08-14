# GitHub Actions examples · A OpenAPI drift + C JUnit + run-vs-run diff + D SARIF + E GHA annotations

Copy-paste workflows so a consumer repo can drop **A (sdk-mcp-gen OpenAPI drift)**, **C (agent-ci JUnit + optional run-vs-run Markdown diff)**, **D (ai-bom SARIF)**, and **E (otel-ai-cost budget `::error`)** into CI.

These files live here on purpose. They are **not** required workflows on this portfolio (no live runner gate for OpenAPI drift / agent eval / run-vs-run diff / whole-monorepo BOM scan / cost budget). Keep [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) as the only push/PR gate. Do **not** enable GitHub code scanning on *this* repo from these examples.

Dependabot already watches `github-actions` at the repo root for `ci.yml`. Do not duplicate that config for these examples.

## Copy into a consumer repo

1. Copy a workflow YAML into **your** `.github/workflows/`.
2. Install or vendor the CLI (`pip install` / `PYTHONPATH=src` if you keep `src/`; A and E are `node src/cli.js`).
3. Adjust suite / scan / spans / OpenAPI paths if they are not the demo fixtures.
4. For D: enable **code scanning** on the consumer repo (Settings → Code security → Code scanning) or `upload-sarif` fails.

Optional: copy a composite action directory to `.github/actions/<name>/` and `uses: ./.github/actions/<name>`.

### This portfolio (monorepo) paths

If you run the same YAML against *this* tree, set `working-directory` and artifact/`sarif_file` paths:

| Example | `working-directory` | Output path |
|---------|---------------------|-------------|
| A drift | `bets/a-sdk-mcp-gen` | `sdk/` baseline + `sdk-new/` (exit 1 on removed/renamed tools) |
| C JUnit | `bets/c-agent-ci` | `bets/c-agent-ci/junit.xml` |
| D SARIF | `bets/d-ai-bom` | `bets/d-ai-bom/ai-bom.sarif` |
| E GHA | `bets/e-otel-ai-cost` | stdout `::error` + `bets/e-otel-ai-cost/costs.md` |

## Exact CLI (smoke + workflows)

`make smoke` runs these same commands against the demo fixtures (from the bet directory, with `PYTHONPATH=src` for C/D):

```bash
python3 -m agent_ci run --suite fixtures/demo --junit junit.xml
python3 -m agent_ci diff --from run-a.json --to run-b.json --format md
python3 -m ai_bom scan examples/sample-app --policy policies/default.json --sarif ai-bom.sarif
node src/cli.js report --in examples/spans.json --format gha
node src/cli.js report --in examples/spans.json --tenant-budget acme=0.0001 --format gha
node src/cli.js report --in examples/spans.json --format md --out costs.md
node src/cli.js generate examples/petstore.openapi.json --out sdk
node src/cli.js generate examples/petstore.openapi.json --out sdk-new --check-baseline sdk
node src/cli.js check --out sdk-new --baseline sdk
node src/cli.js generate examples/petstore.openapi.json --check-baseline sdk
```

Workflow `run:` lines prefix `PYTHONPATH=src` for C/D (no pip install). A and E are Node (no PYTHONPATH):

```bash
PYTHONPATH=src python3 -m agent_ci run --suite fixtures/demo --junit junit.xml
PYTHONPATH=src python3 -m agent_ci diff --from run-a.json --to run-b.json --format md >> "$GITHUB_STEP_SUMMARY"
PYTHONPATH=src python3 -m ai_bom scan examples/sample-app --policy policies/default.json --sarif ai-bom.sarif
node src/cli.js report --in examples/spans.json --format gha
node src/cli.js generate examples/petstore.openapi.json --out sdk
node src/cli.js generate examples/petstore.openapi.json --out sdk-new --check-baseline sdk
```

C also accepts stdout XML: `run --format junit` (same suite). Optional Markdown job summary: `run --format md >> "$GITHUB_STEP_SUMMARY"` (HTTP `GET /v1/runs/{id}/report.md` on serve). Optional run-vs-run Markdown diff: `diff --from run-a.json --to run-b.json --format md >> "$GITHUB_STEP_SUMMARY"` (two completed-run JSON dumps, same shape as `GET /v1/runs/{id}`; identical demo dumps → “no changes”, exit 0; HTTP `GET /v1/runs/{id}/diff.md?against=`). Optional log annotations: `run --format gha` (prints `::error title=<suite>/<case>::…` workflow commands; HTTP `GET /v1/runs/{id}/annotations.txt`). D GitHub upload uses **`--sarif PATH`** (this workflow). Optional elsewhere: `scan --format sarif` (same SARIF 2.1.0 to stdout/`--out`) and HTTP `GET /v1/bom?format=sarif` (or `/v1/bom.sarif`) on `serve` / stack-demo — not a substitute for `upload-sarif`. Optional D log annotations: `scan --format gha` (prints `::error title=<component>::<license or rule>`; HTTP `GET /v1/bom?format=gha` / `/v1/bom.gha.txt`).

E happy path (`--format gha`, no `--budget`) prints nothing and exits 0. Tight `--tenant-budget acme=0.0001` prints `::error title=tenant/acme::` and still exits 0. Tight `--budget policies/budget.json` prints `::error title=budget::` and **exits 1** (job fails; annotations still show in the log). Optional Markdown: `report --format md >> "$GITHUB_STEP_SUMMARY"` and `--out costs.md` for `upload-artifact`. HTTP: `GET /v1/costs.gha.txt` / `GET /v1/costs?format=gha`.

## A · OpenAPI drift

[`sdk-mcp-gen-check.yml`](./sdk-mcp-gen-check.yml)

Typical consumer:

1. Commit a generated `sdk/` as the baseline (or generate it once in CI).
2. On each PR, regenerate from the current OpenAPI and compare:
   - One-shot: `node src/cli.js generate examples/petstore.openapi.json --out sdk-new --check-baseline sdk`
   - Compact (omit `--out` → temp dir vs committed `sdk/`): `node src/cli.js generate examples/petstore.openapi.json --check-baseline sdk`
   - Two-step: generate into NEW, then `node src/cli.js check --out sdk-new --baseline sdk`
   - Same-dir self-check (not a drift gate): `generate --out sdk --check-baseline sdk` overwrites then compares to itself (always OK).
3. Fail the job on exit 1 (removed/renamed tools). Added tools are OK.

This job (petstore fixture, happy path): `node src/cli.js generate examples/petstore.openapi.json --out sdk` then `node src/cli.js generate examples/petstore.openapi.json --out sdk-new --check-baseline sdk` → exit 0.

Thin composite: [`sdk-mcp-gen-check/action.yml`](./sdk-mcp-gen-check/action.yml) (run CLI `generate --check-baseline`).

## C · JUnit

[`agent-ci-junit.yml`](./agent-ci-junit.yml)

1. `python3 -m agent_ci run --suite fixtures/demo --junit junit.xml`
2. `actions/upload-artifact@v4` the XML (`if-no-files-found: error`)

That is the simplest green path. Optional (commented in the YAML): `EnricoMi/publish-unit-test-results` to publish a check — review that action as supply chain before enabling. Prefer the artifact over third-party reporters (`dorny/test-reporter` is intentionally not used). Optional one-liner for log annotations: `python3 -m agent_ci run --suite fixtures/demo --format gha`.

Optional run-vs-run Markdown job summary (commented in the YAML; two completed-run JSON dumps, same shape as `GET /v1/runs/{id}`):

```bash
PYTHONPATH=src python3 -m agent_ci diff --from run-a.json --to run-b.json --format md >> "$GITHUB_STEP_SUMMARY"
```

Happy path on demo fixtures: two identical dumps → “no changes” (exit 0). Do not add a second failing suite in the default job (would fail the example). To compare vs last green, download a previous artifact as `--from` (`actions/download-artifact`) and dump the current run as `--to`.

Thin composite: [`agent-ci-junit/action.yml`](./agent-ci-junit/action.yml) (run CLI + `junit-path` output).

## D · SARIF

[`ai-bom-sarif.yml`](./ai-bom-sarif.yml)

1. `python3 -m ai_bom scan examples/sample-app --policy policies/default.json --sarif ai-bom.sarif`
2. `github/codeql-action/upload-sarif@v3` with `sarif_file: ai-bom.sarif`

**Code scanning must be enabled** on the consumer repo or the upload step fails. Permissions: `security-events: write` (+ `contents: read`, `actions: read`).

Optional (not this workflow): `serve` HTTP `GET /v1/bom?format=sarif` returns the same SARIF 2.1.0 document for stack-demo without writing a file. Optional one-liner for log annotations: `python3 -m ai_bom scan examples/sample-app --policy policies/default.json --format gha`.

Thin composite: [`ai-bom-sarif/action.yml`](./ai-bom-sarif/action.yml) (run CLI + `sarif-path` output).

## E · GHA budget annotations

[`otel-ai-cost-gha.yml`](./otel-ai-cost-gha.yml)

1. `node src/cli.js report --in examples/spans.json --format gha` (stdout workflow commands; empty / exit 0 with no `--budget`)
2. `node src/cli.js report --in examples/spans.json --format md >> "$GITHUB_STEP_SUMMARY"`
3. `node src/cli.js report --in examples/spans.json --format md --out costs.md` then `actions/upload-artifact@v4`

That is the simplest green path. Commented in the YAML: `--budget policies/budget.json` (exit 1 + `::error title=budget::`) and `--tenant-budget acme=0.0001` (`::error title=tenant/acme::`, exit 0). Fixture: E [`examples/spans.json`](../../bets/e-otel-ai-cost/examples/spans.json) (one span `tenant=acme`).

Thin composite: [`otel-ai-cost-gha/action.yml`](./otel-ai-cost-gha/action.yml) (run CLI `--format gha`).

## Prove

`scripts/check-gha-examples.sh` (hooked from `make smoke`): YAML `safe_load` (PyYAML) or the same indent subset as k8s manifests; workflows have `on` + `jobs`; composites have `name` + `runs`; README contains the exact CLI strings above; demo fixture CLI writes JUnit / SARIF 2.1.0 / E `::error` (tenant-budget) + empty happy-path gha + `costs.md`; C `diff --from/--to --format md` on two identical demo dumps → “no changes” (exit 0); A petstore generate twice (`--check-baseline` against the first, exit 0) plus `check --out NEW --baseline sdk`.
