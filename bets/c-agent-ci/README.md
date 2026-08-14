# C · agent-ci

> Deterministic agent CI eval · **Status: local-mvp** · **Phase 1**

## Thesis

Agent quality needs CI gates. Fixture-driven, seeded, mock-LLM evals with JUnit / TAP13 / Markdown / HTML / GitHub Actions annotation output.

## Who pays / 谁付钱

- Eng productivity / Agent product teams
- 工程效率与 Agent 产品团队（回归门禁 + 托管 runner seats）

## OSS vs Paid （draft anchors）

| Tier | Contents | Anchor (draft) |
|------|----------|----------------|
| OSS free | Local runner, demo suite, JUnit, TAP13, Markdown (`GITHUB_STEP_SUMMARY`), self-contained HTML report (`--format html`), GitHub Actions `::error` annotations (`--format gha`), cassette compare, dir/zip import, baseline diff CLI (`--diff-baseline` + **run-vs-run** `diff --from/--to` / `GET /v1/runs/{id}/diff` + Markdown `--format md` / `GET /v1/runs/{id}/diff.md` + HTML `--format html` / `GET /v1/runs/{id}/diff.html`), **local Check Run JSON payload**, **local run-complete webhook** (fire-and-forget, **1 retry** on 5xx/timeout) + **simple HMAC-SHA256** (`--webhook-secret`) | $0 |
| Paid pilot | Private suite hosting, baseline gate in CI, hosted runner seats + **autoscaling**, **real GitHub Checks token posting**, **webhook exponential backoff / queues**, **HMAC key rotation / timestamp replay window enforcement** | ~$29/seat/mo draft |
| Enterprise | VPC / on-prem runners, SSO, audit export, parallel shards | contract |

> Pricing anchors are **draft placeholders** for pilot talks — not public SKUs yet.
> See docs/hosted-runner.md for hosted design.

## Quick start

```bash
PYTHONPATH=src python3 -m agent_ci smoke
PYTHONPATH=src python3 -m agent_ci run --suite fixtures/demo --save-baseline out/baseline.json
PYTHONPATH=src python3 -m agent_ci run --suite fixtures/demo --format junit > out/junit.xml
PYTHONPATH=src python3 -m agent_ci run --suite fixtures/demo --format tap > out/results.tap
PYTHONPATH=src python3 -m agent_ci run --suite fixtures/demo --format md > out/report.md
PYTHONPATH=src python3 -m agent_ci run --suite fixtures/demo --format html > out/report.html
PYTHONPATH=src python3 -m agent_ci run --suite fixtures/demo --format gha
# GitHub Actions job summary:
# PYTHONPATH=src python3 -m agent_ci run --suite fixtures/demo --format md >> "$GITHUB_STEP_SUMMARY"
# GitHub Actions log annotations:
# PYTHONPATH=src python3 -m agent_ci run --suite fixtures/demo --format gha
PYTHONPATH=src python3 -m agent_ci run --suite fixtures/demo --fail-under 80
PYTHONPATH=src python3 -m agent_ci run --suite fixtures/demo --diff-baseline out/baseline.json
PYTHONPATH=src python3 -m agent_ci diff --from out/run-a.json --to out/run-b.json
PYTHONPATH=src python3 -m agent_ci diff --from out/run-a.json --to out/run-b.json --format md
PYTHONPATH=src python3 -m agent_ci diff --from out/run-a.json --to out/run-b.json --format html
# GitHub Actions job summary (run-vs-run):
# PYTHONPATH=src python3 -m agent_ci diff --from out/run-a.json --to out/run-b.json --format md >> "$GITHUB_STEP_SUMMARY"
PYTHONPATH=src python3 -m agent_ci import-suite --from fixtures/demo --to fixtures/private-demo
# zip path:
# PYTHONPATH=src python3 -m agent_ci import-suite --from out/demo-suite.zip --to fixtures/from-zip
```

## Local hosted-runner stub

```bash
PYTHONPATH=src python3 -m agent_ci serve --port 8791 --concurrency 1 --max-queue 16
# optional: --watch   # poll fixtures/ max mtime ~400ms; GET /health watch.generation
# GET  /health                 # liveness (always 200) + local queue snapshot (+ watch when --watch)
# GET  /ready                  # readiness: 200 {ok:true, queue} or 503 queue_full/shutting_down
# GET  /openapi.json           # file-backed OpenAPI 3 (openapi/runner.openapi.json)
# GET  /metrics                # Prometheus text (queue_depth / running / completed_total / failed_total)
# GET  /v1/suites               # list fixtures/* suite dirs {name,path,caseCount}
# GET  /v1/suites/{name}        # one suite {ok,id,name,cases:[{name}]} (404 suite_not_found; no fixture dump)
# GET  /v1/config               # redacted runtime config (queue/cors/rateLimit/runsMax/webhook booleans; no secrets)
# POST /v1/runs  {"suite":"fixtures/demo"}  → 202 {runId,status=queued|running}
# POST /v1/runs  {"suite":"fixtures/demo","failUnder":80}  # quality gate; score < N → status failed
# GET  /v1/runs                 # list retained runs (?limit= default 20; history cap --runs-max)
# GET  /v1/runs/{runId}         # poll until status=done|failed|error (404 if dropped)
# GET  /v1/runs/{runId}/cases   # lightweight inventory {ok,runId,status,count,cases[{suite,name,status}]}; ?status=; cap 500
# GET  /v1/runs/{runId}/diff?against={otherId}  # both completed; 409 if not done
# GET  /v1/runs/{runId}/diff.md?against={otherId}  # Markdown (alias ?format=md; GITHUB_STEP_SUMMARY)
# GET  /v1/runs/{runId}/diff.html?against={otherId}  # HTML (alias ?format=html; local demo browser tab)
# GET  /v1/runs/{runId}/junit   # JUnit XML artifact (after done)
# GET  /v1/runs/{runId}/junit.xml
# GET  /v1/runs/junit.xml       # retained completed runs (empty → tests="0")
# GET  /v1/runs/{runId}/tap.txt # TAP version 13 (alias /tap)
# GET  /v1/runs/tap.txt         # retained completed runs (empty → 1..0)
# GET  /v1/runs/{runId}/report.md  # Markdown (alias /md; GITHUB_STEP_SUMMARY)
# GET  /v1/runs/report.md          # retained completed runs (empty → heading + no rows)
# GET  /v1/runs/{runId}/report.html  # self-contained HTML (alias /html; no CDN)
# GET  /v1/runs/report.html          # retained completed runs (empty → heading + no runs)
# GET  /v1/runs/{runId}/annotations.txt  # GHA ::error (alias /annotations)
# GET  /v1/runs/annotations.txt          # retained completed runs (pass-only → empty)
# POST /v1/check-runs           # local mock Check Run receiver
# queue full → 429 + Retry-After
# CORS (optional): --cors-origins http://localhost:3000  or  AGENT_CI_CORS_ORIGINS
# rate-limit (optional): --rate-limit 120  or  RATE_LIMIT_PER_MINUTE / RATE_LIMIT_RPM (0 = unlimited)
# runs history cap: --runs-max 1000  or  RUNS_MAX (default 1000; 0 = unlimited; drop oldest finished)
# X-Request-Id: optional; echoed on every response (UUID if omitted); stored on run records
# Webhook (optional): --webhook-url http://127.0.0.1:8810/hook  or  AGENT_CI_WEBHOOK_URL
# HMAC (optional): --webhook-secret whsec_local_mvp  or  AGENT_CI_WEBHOOK_SECRET
```

- **Quality gate (OSS):** `run --fail-under N` (0–100). Score = `passed/total * 100` (0 if total=0). If `score < N`, CLI exits **1** even when the process did not crash. Default omit = today's exit (0 if all cases pass, 1 if any fail). HTTP: optional POST `/v1/runs` body `failUnder`. Completed JSON always includes `score` (0–100); when `failUnder` is set, also `gate: {failUnder, passed}`. Gate fail → status **`failed`**, `error: "below_threshold"` (JUnit `failures>=1`; synthetic `<failure message="below_threshold">` if every case passed but score is still below — e.g. `failUnder: 101` on a perfect suite). Omit `failUnder` = status `done` as today. Webhook run-complete payload includes `score` + `gate` when present (HMAC still signs the raw body). Queue / rate-limit / watch / ready / junit.xml / tap.txt / report.md / report.html / annotations.txt otherwise unchanged.
- **OSS CLI** stays free/offline (`smoke` / `run` / `import-suite`).
- **Local queue (OSS):** in-memory `queued→running→done|failed|error`; `--concurrency` / `--max-queue`.
- **Finished-run history cap (OSS):** `--runs-max` / env `RUNS_MAX` default **1000** completed (`done`|`failed`|`error`) runs in memory. Over cap, drop oldest finished. **Does not cap** the in-flight queue (`--max-queue`). `0` = unlimited. `GET /v1/runs`, `GET /v1/runs/junit.xml`, `GET /v1/runs/tap.txt`, `GET /v1/runs/report.md`, `GET /v1/runs/report.html`, and `GET /v1/runs/annotations.txt` only see retained history; `GET /v1/runs/{id}` → **404** if dropped. Webhook already fired at complete (not affected). local-mvp isolated `--runs-max 2`: POST 3 quick demo runs → list length 2, oldest 404, queue still 202. Main demo / stack-demo keep default 1000 so listed runs stay. Fail-under / rate-limit / watch unchanged.
- **Hosted autoscaling** = paid later.
- **API key** (`Bearer demo`) sketches the paid hosted-seat wedge; bad keys → 401.
- **CORS:** `--cors-origins` CSV or `AGENT_CI_CORS_ORIGINS` (`*` allowed). Empty/omit = **deny extra CORS** (no ACAO; OPTIONS 404). Explicit list: allowed Origin OPTIONS → **204** + ACAO; unlisted (e.g. `http://evil.example`) → **403** `cors_denied`. Matching GET/POST include `Access-Control-Allow-Origin`. Default allow/expose headers include `X-Request-Id`; default expose also includes **`Retry-After`** (GET/POST/OPTIONS ACEH).
- **HTTP rate limit:** `--rate-limit` / env `RATE_LIMIT_PER_MINUTE` (alias `RATE_LIMIT_RPM`) default **120**/min per client IP (`X-Forwarded-For` first hop, else socket). In-memory sliding window. Exceed → **429** `{ok:false, reason:"rate_limited"}` + `Retry-After`. **`GET /health`**, **`GET /ready`**, **`GET /metrics`** are not limited. Distinct from queue-full 429 `{error:"queue_full"}`. `0` disables. CLI flag wins over env. local-mvp isolated prove uses `--rate-limit 2` (third `GET /v1/suites` is 429; `/health` stays 200). Main serve / stack-demo keep the generous default so POST `/v1/runs` never 429 from the limiter.
- **X-Request-Id:** optional correlation header. Echoed on **every** response (including 4xx / OPTIONS). If omitted/empty, the stub generates a UUID (max 128 chars; CR/LF stripped). Same value stored as `requestId` on POST `/v1/runs` records, `GET /v1/runs/{id}`, and list rows. local-mvp sends a custom id and asserts the response header + stored run.
- **Run-complete webhook (OSS):** `--webhook-url` or env `AGENT_CI_WEBHOOK_URL`. After a run reaches `done`|`failed`|`error`, fire-and-forget POST JSON `{runId,status,summary,requestId,conclusion}` plus `score` and `gate` when present (short timeout ~750ms; webhook errors **never fail** the run). Empty/omit = disabled. Optional **HMAC (OSS):** `--webhook-secret` or env `AGENT_CI_WEBHOOK_SECRET`. When set, POST includes `X-Webhook-Signature: sha256=<hex>` — HMAC-SHA256 of the **raw JSON body**. Omit / empty secret → unsigned (existing prove). **Every** outbound POST also sends `X-Webhook-Timestamp: <unix-seconds>` (HMAC still body-only). On **5xx** or **network/timeout**, retry the POST **once** after ~50ms (success on first try = no retry; **4xx do not retry**). Simple HMAC + **1 retry** is OSS. local-mvp mock receiver (`mock-webhook-receiver.py`) writes the last body (optional `--secret` verifies HMAC; `--headers-out` persists signature + timestamp); unsigned prove stays and asserts timestamp present/roughly now; isolated signed receiver asserts header + HMAC (body) + timestamp. Smoke unit-tests 200/4xx = no retry and 5xx/network = one retry. **Exponential backoff / queues, key rotation / timestamp replay window enforcement = paid later**.
- **Serve `--watch`:** `serve --watch` polls `fixtures/` max mtime every 400ms and logs `regenerated` (suiteCount + generation). `GET /v1/suites` still live-reads disk (new dirs appear without a cache). `GET /health` includes `watch: { generation }` (starts at 0; increments on change; omitted when `--watch` is off). local-mvp isolated prove (mkdir a suite dir → list includes it + generation bumps → kill, no hang). Main serve / stack-demo unchanged (no `--watch`). Queue / webhook / CORS otherwise unchanged.
- **GET /ready (readiness):** 200 `{ok:true, queue}` when POST `/v1/runs` would still enqueue; 503 `{ok:false, reason:"queue_full"}` + `Retry-After` when at capacity (queued+running such that POST would 429). On **SIGTERM/SIGINT**, **503** `{ok:false, reason:"shutting_down"}` wins (new queue jobs are not started). Snapshot only — does not consume a queue slot. Liveness **`GET /health` stays 200** even when the queue is full (`shuttingDown: true` while draining). Compose/stack-demo healthchecks stay on `/health`. Isolated local-mvp (`--max-queue 1 --concurrency 1`): fill queue → `/health` 200 + `/ready` 503; after drain → `/ready` 200. Isolated SIGTERM: `--drain-ms 200` → `kill -TERM` → `/ready` 503 `shutting_down` + `/health` 200 `shuttingDown` → exit within the window.
- **Graceful shutdown:** SIGTERM/SIGINT always on (no extra flags). `/ready` → 503 `shutting_down`; `/health` stays 200 with `shuttingDown: true`; stop new queue jobs; drain default **5s** (`--drain-ms` / `SHUTDOWN_DRAIN_MS`, cap 30s); log `shutting down` then `exit`. Watch poller stops immediately so `make local-mvp` does not hang.
- **Prometheus `GET /metrics`:** gauges `agent_ci_queue_depth`, `agent_ci_running` and counters `agent_ci_runs_completed_total` (status=done), `agent_ci_runs_failed_total` (status=error). Text 0.0.4. CORS: matching Origin GET includes ACAO (same as other GET). local-mvp curl after a completed run asserts metric names.
- **JSON access logs (opt-in):** `--log-json` or env `LOG_FORMAT=json` (env wins if CLI omitted) — one stdout JSON line per completed app request `{ts,level:info,msg:http,service,method,path,status,durationMs,requestId}` (optional `bytesOut`/`remote`); skips `/health` `/ready` `/metrics` and OPTIONS; `requestId` matches `X-Request-Id`. Default **off**.
- **JUnit XML (OSS):** `run --format junit` prints GitHub Actions / Jenkins / GitLab-ingestible XML (also `run --junit PATH`). HTTP: `GET /v1/runs/{id}/junit.xml` (one completed run) and `GET /v1/runs/junit.xml` (retained completed history; empty → valid `<testsuite tests="0">`). `Content-Type: application/xml`. Reuses the run record (`summary.cases` / pass/fail/error / quality gate); XML-escaped (`& < > "`). Quality-gate fail → `failures>=1` (synthetic `below_threshold` case if all cases passed). Existing JSON run APIs and `GET /v1/runs/{id}/junit` unchanged.
- **TAP13 (OSS):** `run --format tap` prints TAP version 13 (`ok` / `not ok` + `#` diagnostics). HTTP: `GET /v1/runs/{id}/tap.txt` (alias `/tap`) and `GET /v1/runs/tap.txt` (retained completed history; empty → `1..0`). `Content-Type: text/plain; charset=utf-8`. Same CaseResult / run record as JUnit; `#` in names escaped so the plan stays `1..N`. Quality-gate fail → a `not ok` line (synthetic `below_threshold` if all cases passed). JUnit / fail-under / queue / webhook / rate-limit unchanged.
- **Markdown report (OSS):** `run --format md` prints a GitHub-flavored Markdown table for humans and GitHub Actions `$GITHUB_STEP_SUMMARY` (`# agent-ci: <suite>` + **Status** / **Score** / **Gate** + `| case | status | time |`). HTTP: `GET /v1/runs/{id}/report.md` (alias `/md`) and `GET /v1/runs/report.md` (retained completed history; empty → heading + no data rows). `Content-Type: text/markdown; charset=utf-8`. `|` in names escaped. Quality-gate fail → a `fail` row (synthetic `below_threshold` if all cases passed). Append in Actions: `python3 -m agent_ci run --suite fixtures/demo --format md >> "$GITHUB_STEP_SUMMARY"`. JUnit / TAP / fail-under / queue / webhook / rate-limit / runs-max unchanged.
- **HTML run report (OSS):** `run --format html` prints a self-contained HTML table for the local 5-min demo (`<h1>agent-ci: <suite></h1>` + Status / Score / Gate + suite/case/status/time/message; fail status red via inline CSS). No CDN / external CSS/JS. HTTP: `GET /v1/runs/{id}/report.html` (alias `/html`) and `GET /v1/runs/report.html` (retained completed history; empty → heading + “no runs”). `Content-Type: text/html; charset=utf-8`. Names escaped (`& < > "`). Quality-gate fail → a `fail` row (synthetic `below_threshold` if all cases passed). JUnit / TAP / Markdown / GHA / fail-under / queue / webhook / rate-limit / runs-max unchanged.
- **Run-vs-run baseline diff (OSS):** `diff --from a.json --to b.json` prints JSON `{ok,from,to,added,removed,regressed,fixed,unchanged}` comparing two completed run records by case identity `suite/name` (`regressed` = pass→fail, `fixed` = fail→pass). HTTP: `GET /v1/runs/{id}/diff?against={otherId}` (path id = **to**, `against` = **from** / last green). Both must be `done`|`failed`|`error`. Missing run → **404**. Incomplete (`queued`/`running`) → **409** `{error:"run_not_done"}`. Empty both → empty arrays and `unchanged` 0. CORS + `X-Request-Id` same as other GET. Distinct from `--diff-baseline` / POST `baseline` (trajectory/score vs a saved snapshot). Does not change fail-under scoring. smoke: extra-fail → `regressed`; identical → empty diffs. local-mvp: POST two runs + curl 200. stack-demo: OpenAPI `getRunDiff` (empty server may 404 on fake ids).
- **Run-vs-run baseline diff Markdown (OSS):** `diff --from a.json --to b.json --format md` prints GitHub-flavored Markdown for `$GITHUB_STEP_SUMMARY` (heading + counts + GFM tables for added/removed/regressed/fixed; `|` escaped; empty → heading + “no changes”). Default `--format json` unchanged. HTTP: `GET /v1/runs/{id}/diff.md?against={otherId}` (alias `GET /v1/runs/{id}/diff?against=&format=md`). `Content-Type: text/markdown; charset=utf-8`. Same 404/409/400 as JSON (error bodies stay JSON). CORS + `X-Request-Id`. OpenAPI `getRunDiffMd`. smoke: extra-fail md contains `regressed` / `demo/flaky`; identical contains “no changes”. local-mvp: curl `diff.md` 200 `text/markdown` after two POSTs. stack-demo: OpenAPI path. JSON path unchanged.
- **Run-vs-run baseline diff HTML (OSS):** `diff --from a.json --to b.json --format html` prints a self-contained HTML table for the local 5-min demo (heading + counts + tables for added/removed/regressed/fixed; names escaped; regressed rows red via inline CSS; empty → heading + “no changes”). No CDN. HTTP: `GET /v1/runs/{id}/diff.html?against={otherId}` (alias `GET /v1/runs/{id}/diff?against=&format=html`). `Content-Type: text/html; charset=utf-8`. Same 404/409/400 as JSON (error bodies stay JSON). CORS + `X-Request-Id`. OpenAPI `getRunDiffHtml`. smoke: extra-fail html has `<table` + `flaky` escaped; identical contains “no changes”. local-mvp: curl `diff.html` 200 `text/html` after two POSTs. stack-demo: OpenAPI path. JSON / Markdown paths unchanged.
- **GitHub Actions annotations (OSS):** `run --format gha` (alias `--format annotations`) prints workflow commands to stdout so failed cases show up in GHA logs (`::error title=<suite>/<case>::<message>`). Pass-only → no `::error` (empty stdout). Quality-gate fail → `::error title=gate::score N < failUnder M`. HTTP: `GET /v1/runs/{id}/annotations.txt` (alias `/annotations`) and `GET /v1/runs/annotations.txt` (retained completed history; empty / all-pass → empty body). `Content-Type: text/plain; charset=utf-8`. Same CaseResult / run record as JUnit/TAP/Markdown; `%` / CR / LF escaped. Does **not** require GitHub. One-liner: `python3 -m agent_ci run --suite fixtures/demo --format gha`. JUnit / TAP / Markdown / fail-under / queue / webhook / rate-limit / runs-max unchanged.
- **GET /v1/config (redacted runtime config):** public GET like `/v1/suites` (no Bearer). Allowlist `{ok, queue:{max,queued,running}, failUnder, rateLimit:{perMinute}, cors:{origins}, runsMax, webhooks:{hasUrl,hasSecret}, suitesCount}`. **Never** webhook URL, webhook secret, Bearer tokens, or fixture file contents. `failUnder` is null (no serve-level default). CORS + `X-Request-Id`. smoke: 200 + planted secret absent; local-mvp curl 200 + isolated HMAC secret not leaked; stack-demo curl 200 + OpenAPI `getConfig`.
- **GET /v1/suites/{name} (suite detail):** `{ok, id, name, path, caseCount, cases:[{name}]}` (cassette **names only** — never prompt/trajectory/fixture dump). Empty → `cases:[]`. Unknown → **404** `suite_not_found`. OpenAPI `getSuite` / `SuiteDetail`. smoke helper + HTTP; local-mvp curl 200 + 404; stack-demo OpenAPI + 404.
- **GET /v1/runs/{id}/cases (case inventory):** public GET like `/v1/runs/{id}`. `{ok, runId, status, count, cases:[{suite, name, status, durationMs?}]}`. Optional `?status=passed|failed|error|skipped` (unknown → empty 200). Cap **500** original order + `truncated`. Empty / in-flight → **200** `cases:[]`. Unknown id → **404** `run_not_found`. **Never** prompts, expected/actual, output, API keys, Authorization. OpenAPI `listRunCases`. smoke helper + HTTP 404/200; local-mvp curl 200 + 404; stack-demo OpenAPI + 404.
- **OpenAPI:** [`openapi/runner.openapi.json`](./openapi/runner.openapi.json) documents `/health`, **`/ready`**, `/metrics`, **`GET /v1/config`** (`getConfig`; redacted queue/cors/rate-limit/runs-max/webhook booleans; no secrets), `/v1/runs` (GET list + POST), `/v1/runs/{id}`, `/v1/runs/{id}/junit`, **`/v1/runs/{id}/junit.xml`**, **`/v1/runs/junit.xml`**, **`/v1/runs/{id}/tap`**, **`/v1/runs/{id}/tap.txt`**, **`/v1/runs/tap.txt`**, **`/v1/runs/{id}/md`**, **`/v1/runs/{id}/report.md`**, **`/v1/runs/report.md`**, **`/v1/runs/{id}/html`**, **`/v1/runs/{id}/report.html`**, **`/v1/runs/report.html`**, **`/v1/runs/{id}/annotations`**, **`/v1/runs/{id}/annotations.txt`**, **`/v1/runs/annotations.txt`**, **`/v1/runs/{id}/diff`**, **`/v1/runs/{id}/diff.md`**, **`/v1/runs/{id}/diff.html`**, **`/v1/runs/{id}/cases`** (`listRunCases`), `/v1/check-runs`, `/v1/suites`, `/v1/suites/{name}` (`getSuite` / `SuiteDetail`; case names, no fixture dump) with Bearer auth, `X-Request-Id`, 202/429/401/404/503, sliding-window **429** `rate_limited` (`RateLimited`; skip probes), outbound `RunCompleteWebhook` (`--webhook-url` / `AGENT_CI_WEBHOOK_URL`; optional `--webhook-secret` / `AGENT_CI_WEBHOOK_SECRET` → `X-Webhook-Signature: sha256=<hex>` HMAC), and optional `WatchSnapshot` on `/health` when `serve --watch`. Live serve: `GET /openapi.json`. **Dogfood A→C**: portfolio `make dogfood-a-c` (A reads this OpenAPI; output under `sdk/generated/`, gitignored; hooked from `make local-mvp`).
- See [docs/hosted-runner.md](./docs/hosted-runner.md).

## GitHub Check Run adapter (local mock)

Formats suite results as a [GitHub Checks API](https://docs.github.com/en/rest/checks/runs) create-check-run shaped JSON payload — **local only** (stdlib, no network required).

```bash
PYTHONPATH=src python3 -m agent_ci report-check --suite fixtures/demo --out out/check-run.json
# Optional: POST to local mock receiver (prove "reporting" without GitHub):
PYTHONPATH=src python3 -m agent_ci serve --port 8791 &
PYTHONPATH=src python3 -m agent_ci report-check --suite fixtures/demo --out out/check-run.json \
  --post-url http://127.0.0.1:8791/v1/check-runs
# → data/check-run-posted.json
```

| Piece | Scope |
|-------|-------|
| Local payload (`name`, `conclusion` success/failure, `output.summary` / `output.text` from case list) | **OSS** |
| POST to local mock (`/v1/check-runs`) | **OSS** (demo) |
| Real GitHub token posting to `api.github.com` | **Paid / hosted later** |

## GitHub Actions (JUnit + job summary + annotations + run-vs-run diff)

Copy-paste: portfolio [`examples/github-actions/agent-ci-junit.yml`](../../examples/github-actions/agent-ci-junit.yml) → consumer `.github/workflows/`. Green path: `python3 -m agent_ci run --suite fixtures/demo --junit junit.xml` then `actions/upload-artifact@v4`. Optional run-vs-run Markdown job summary (commented in the YAML): `python3 -m agent_ci diff --from run-a.json --to run-b.json --format md >> "$GITHUB_STEP_SUMMARY"` (two identical demo dumps → “no changes”; download a previous artifact as `--from`). Optional composite: [`examples/github-actions/agent-ci-junit/action.yml`](../../examples/github-actions/agent-ci-junit/action.yml). See [`examples/github-actions/README.md`](../../examples/github-actions/README.md). Not a required workflow on this repo.

Optional Markdown job summary (`GITHUB_STEP_SUMMARY`):

```bash
PYTHONPATH=src python3 -m agent_ci run --suite fixtures/demo --format md >> "$GITHUB_STEP_SUMMARY"
# or after serve: curl -sf http://127.0.0.1:8791/v1/runs/$RUN_ID/report.md >> "$GITHUB_STEP_SUMMARY"
# run-vs-run diff (commented in the example YAML):
PYTHONPATH=src python3 -m agent_ci diff --from run-a.json --to run-b.json --format md >> "$GITHUB_STEP_SUMMARY"
# or: curl -sf "http://127.0.0.1:8791/v1/runs/$TO/diff.md?against=$FROM" >> "$GITHUB_STEP_SUMMARY"
```

Optional log annotations (workflow commands; no GitHub API):

```bash
PYTHONPATH=src python3 -m agent_ci run --suite fixtures/demo --format gha
```

Container (k8s placeholder; images not published; skip if no Docker): `docker build -t ghcr.io/wozqhl/c-agent-ci:dev bets/c-agent-ci` (`python:3.12-alpine`, EXPOSE **8791**, `python -m agent_ci serve --host 0.0.0.0`).

