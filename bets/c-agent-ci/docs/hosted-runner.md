# Hosted Runner / 托管运行器设计

> Agent CI for: hosted eval runners + pricing wedge

## Local stub (this repo)

A **local-only** HTTP skeleton implements the spirit of hosted runs without cloud:

```bash
PYTHONPATH=src python3 -m agent_ci serve --port 8791 --concurrency 1 --max-queue 16
# optional: --watch  (poll fixtures/ ~400ms; GET /health watch.generation)
# optional browser CORS: --cors-origins http://localhost:3000
# or AGENT_CI_CORS_ORIGINS=http://localhost:3000
# optional run-complete webhook: --webhook-url http://127.0.0.1:8810/hook
# or AGENT_CI_WEBHOOK_URL=http://127.0.0.1:8810/hook
# optional HMAC: --webhook-secret whsec_local_mvp
# or AGENT_CI_WEBHOOK_SECRET=whsec_local_mvp
```

| Method | Path | Behavior |
|--------|------|----------|
| GET | `/health` | Liveness JSON (always **200**) + local `queue` snapshot: concurrency / maxQueue / queued / running. With `serve --watch`, also `watch: { generation }` (omitted otherwise) |
| GET | `/ready` | Readiness: **200** `{ok:true, queue}` when POST would enqueue; **503** `{ok:false, reason:"queue_full"}` + `Retry-After` when at capacity; **503** `{ok:false, reason:"shutting_down"}` on SIGTERM/SIGINT. Does not consume a queue slot. Compose/stack-demo stay on `/health` |
| GET | `/openapi.json` | File-backed OpenAPI 3 (`openapi/runner.openapi.json`; Bearer + `X-Request-Id`; 202/429/401/404/503; `/metrics`; `/ready`) |
| GET | `/metrics` | Prometheus text: gauges `agent_ci_queue_depth`, `agent_ci_running`; counters `agent_ci_runs_completed_total`, `agent_ci_runs_failed_total` (CORS + `X-Request-Id` same as other GET) |
| GET | `/v1/suites` | List available dirs under `fixtures/` as `{name,path,caseCount}` (`caseCount` = `*.json` cassettes) |
| GET | `/v1/suites/{name}` | One suite `{ok,id,name,path,caseCount,cases:[{name}]}` (names only; **never** cassette dump); **404** `suite_not_found` |
| GET | `/v1/config` | Redacted runtime config `{ok, queue.max/queued/running, failUnder, cors.origins, rateLimit.perMinute, runsMax, webhooks.hasUrl/hasSecret, suitesCount}`. Public like `/v1/suites` (no Bearer). **Never** webhook URL, secret, Bearer tokens, or fixture contents |
| POST | `/v1/runs` | Enqueue suite path or embedded `cases`; optional `baseline` / `delayMs` / **`failUnder`**; **202** `{runId,status}` (`queued` or `running`); **429** + `Retry-After` when queue full. Incoming `X-Request-Id` (or generated UUID) stored as `requestId` on the run record. Quality gate: score = passed/total×100 (0 if total=0); `score < failUnder` → status **`failed`**, `error: "below_threshold"` |
| GET | `/v1/runs` | List retained runs (in-memory history, incl. in-flight) as `{runId,status,createdAt,summary.{passed,failed,total},requestId?}`; `?limit=` default **20** (exact path only — does not shadow `/{id}`). History cap `--runs-max` / `RUNS_MAX` |
| GET | `/v1/runs/{id}` | Load run (`status`: `queued` → `running` → `done` \| `failed` \| `error`; includes pass/fail/`score` when done or failed; `gate` when `failUnder` was set; includes `requestId`). **404** if dropped from finished history |
| GET | `/v1/runs/{id}/diff` | Compare this completed run (**to**) vs `?against={otherId}` (**from**) by case identity `suite/name` → `{ok,from,to,added,removed,regressed,fixed,unchanged}`. Missing → **404**. Incomplete → **409** `{error:"run_not_done"}`. Distinct from POST `baseline` / `--diff-baseline`. `?format=md` → same Markdown as `/diff.md`. `?format=html` → same HTML as `/diff.html` |
| GET | `/v1/runs/{id}/diff.md` | Markdown for the same run-vs-run diff (`text/markdown; charset=utf-8`; heading + counts + GFM tables; `|` escaped; empty → heading + “no changes”). Same 404/409/400 as JSON. Append to GitHub Actions `$GITHUB_STEP_SUMMARY` |
| GET | `/v1/runs/{id}/diff.html` | Self-contained HTML for the same run-vs-run diff (`text/html; charset=utf-8`; heading + counts + tables; names escaped; regressed rows red; empty → heading + “no changes”; no CDN). Same 404/409/400 as JSON (errors stay JSON). Open in a browser tab |
| GET | `/v1/runs/{id}/junit` | JUnit XML artifact (`{id}.junit.xml`); 404 if missing / not finished |
| GET | `/v1/runs/{id}/junit.xml` | Same JUnit XML as `/junit` (`application/xml`; Actions/Jenkins/GitLab) |
| GET | `/v1/runs/junit.xml` | JUnit XML for retained completed runs (`done`\|`failed`\|`error`); empty → `<testsuite tests="0">`; gate fail → `failures>=1` (synthetic `below_threshold` if all cases passed) |
| GET | `/v1/runs/{id}/tap.txt` | TAP version 13 for one completed run (`text/plain; charset=utf-8`); alias `/tap`; 404 if missing / not finished |
| GET | `/v1/runs/{id}/tap` | Same TAP13 as `/tap.txt` |
| GET | `/v1/runs/tap.txt` | TAP13 for retained completed runs (`done`\|`failed`\|`error`); empty → `1..0`; gate fail → a `not ok` line (synthetic `below_threshold` if all cases passed); `#` in names escaped |
| GET | `/v1/runs/{id}/report.md` | Markdown run report (`text/markdown; charset=utf-8`); alias `/md`; 404 if missing / not finished. Append to GitHub Actions `$GITHUB_STEP_SUMMARY` |
| GET | `/v1/runs/{id}/md` | Same Markdown as `/report.md` |
| GET | `/v1/runs/report.md` | Markdown for retained completed runs (`done`\|`failed`\|`error`); empty → heading + no data rows; gate fail → a `fail` row (synthetic `below_threshold` if all cases passed); pipe characters in names escaped |
| GET | `/v1/runs/{id}/report.html` | Self-contained HTML run report (`text/html; charset=utf-8`); alias `/html`; 404 if missing / not finished. No CDN. Fail status is red. Names escaped |
| GET | `/v1/runs/{id}/html` | Same HTML as `/report.html` |
| GET | `/v1/runs/report.html` | HTML for retained completed runs (`done`\|`failed`\|`error`); empty → heading + “no runs”; gate fail → a `fail` row (synthetic `below_threshold` if all cases passed); names escaped |
| GET | `/v1/runs/{id}/annotations.txt` | GitHub Actions workflow commands (`text/plain; charset=utf-8`); alias `/annotations`; 404 if missing / not finished. Fail → `::error title=<suite>/<case>::<message>`. Pass-only → empty. Does not require GitHub |
| GET | `/v1/runs/{id}/annotations` | Same GHA commands as `/annotations.txt` |
| GET | `/v1/runs/annotations.txt` | GHA commands for retained completed runs (`done`\|`failed`\|`error`); empty / all-pass → empty body (no `::error`); gate fail → `::error title=gate::score N < failUnder M` |
| POST | `/v1/check-runs` | **Local mock** Check Run receiver — stores body to `data/check-run-posted.json` (202) |
| OPTIONS | any path | CORS preflight when `--cors-origins` / `AGENT_CI_CORS_ORIGINS` is set: allowed Origin → **204** + ACAO; explicit-list miss → **403** `cors_denied`. Disabled (default) → **404**, no extra CORS headers. **Every** response (incl 4xx/OPTIONS) echoes `X-Request-Id` |

**CORS (optional, default deny):** `--cors-origins` CSV or env `AGENT_CI_CORS_ORIGINS`. Empty/omit = no extra CORS headers (existing curls unchanged). `*` allows any Origin. GET/POST include `Access-Control-Allow-Origin` when `Origin` matches. Default allow/expose headers include `X-Request-Id`; default expose also includes **`Retry-After`** (GET/POST/OPTIONS ACEH). local-mvp isolated prove uses `http://localhost:3000` vs `http://evil.example` (ACEH includes `retry-after`, case-insensitive).

**X-Request-Id:** optional. Echoed on every response (generated UUID if omitted). Same value stored as `requestId` on POST `/v1/runs` records and returned by `GET /v1/runs/{id}` and list rows.

**Quality gate (OSS):** optional POST body `failUnder` (number, typically 0–100). Score = `passed/total * 100` (0 if total=0). Completed JSON always includes `score`. When `failUnder` is set, also `gate: {failUnder, passed}`. If `score < failUnder`, status is **`failed`** with `error: "below_threshold"` (JUnit `failures>=1` / TAP `not ok` / Markdown `fail` / GHA `::error title=gate`; synthetic case if all cases passed). Omit = status `done` as today. CLI: `run --fail-under N` (0–100; default no gate). `run --format gha` prints `::error` workflow commands (no GitHub required). Queue / rate-limit / watch / ready otherwise unchanged.

**Run-complete webhook (OSS):** `--webhook-url` or `AGENT_CI_WEBHOOK_URL`. After a run reaches `done`|`failed`|`error`, fire-and-forget POST JSON `{runId,status,summary,requestId,conclusion}` plus `score` and `gate` when present (short timeout; never fails the run). Optional **HMAC (OSS):** `--webhook-secret` / `AGENT_CI_WEBHOOK_SECRET` → `X-Webhook-Signature: sha256=<hex>` of the raw JSON body. On 5xx or network/timeout, retry once after ~50ms (4xx/success no retry). Simple HMAC + **1 retry** is OSS; **exponential backoff / queues, key rotation / timestamp replay protection = paid later.**

**GET /v1/config (OSS):** public redacted snapshot (no Bearer). Allowlist only — queue cap/depth, CORS origins, rate-limit, runs-max, webhook **booleans**, optional suites count. Never URL, secret, tokens, or fixture dumps. CORS + `X-Request-Id`.

**OpenAPI:** [`../openapi/runner.openapi.json`](../openapi/runner.openapi.json) is served at `GET /openapi.json` (includes `/ready` + `/metrics` + **`GET /v1/config`** `getConfig` + outbound `RunCompleteWebhook` + optional HMAC signature). Dogfood A→C: `make dogfood-a-c` → `sdk/generated/` (gitignored).

**Prometheus `GET /metrics`:** snapshot gauges `agent_ci_queue_depth` / `agent_ci_running` and counters `agent_ci_runs_completed_total` / `agent_ci_runs_failed_total` (process lifetime). CORS + `X-Request-Id` same as other GET. local-mvp curl after a completed run asserts metric names.


**Serve `--watch` (OSS):** poll `fixtures/` max mtime every ~400ms; log `regenerated`; bump `GET /health` `watch.generation`. `GET /v1/suites` still live-reads disk. Default off (stack-demo unchanged).

**Local run queue (OSS):** in-memory FIFO with `--concurrency N` (default 1) workers and `--max-queue` waiting depth (default 16). Each run goes `queued` → `running` → `done` (or `failed` on quality-gate miss, or `error`). Poll `GET /v1/runs/{id}`. Optional body `delayMs` (capped) is a local stub aid for demos/tests.

**Finished-run history cap (OSS):** `--runs-max` / env `RUNS_MAX` default **1000** completed (`done`|`failed`|`error`) runs. Over cap, drop oldest finished (in-flight queued/running are never dropped). `0` = unlimited. Live `GET /v1/runs`, `GET /v1/runs/junit.xml`, `GET /v1/runs/tap.txt`, `GET /v1/runs/report.md`, `GET /v1/runs/report.html`, and `GET /v1/runs/annotations.txt` only see the retained window; `GET /v1/runs/{id}` is **404** after drop. Run-complete webhook still fires at complete (before history trim). Distinct from `--max-queue`.

**Hosted autoscaling / multi-node pools = paid later** — this stub does not scale out.

Auth sketch (paid seats):

- No `Authorization` → allowed (OSS / local free path)
- `Authorization: Bearer demo` → allowed (paid-seat sketch)
- Any other Bearer token → **401**

Stdlib only. CLI (`smoke` / `run` / `import-suite` / `report-check`) still works fully offline.

### Check Run adapter / 检查运行适配器

`python -m agent_ci report-check --suite fixtures/demo --out out/check-run.json` writes a
GitHub Checks API-shaped payload locally (`conclusion` success/failure + `output.summary`/`text`).
Optional `--post-url http://127.0.0.1:8791/v1/check-runs` posts to the local mock receiver.
**Real GitHub token posting = paid/hosted later; local payload = OSS.**

This is **not** a real cloud control plane — no multi-tenant isolation, no encrypted private suite storage, no exponential-backoff/queued webhooks (OSS is best-effort with **1 retry** + simple HMAC; backoff/queues/rotation/replay = paid), no VM pool.

## Architecture / 架构 (target product)

1. Control plane: API accepts suite upload (zip) + baseline id + trigger.
2. Runner pool: ephemeral VM/container with agent-ci pre-installed.
3. Execution: import-suite -> run --diff-baseline -> JUnit + diff report artifacts.
4. Storage: private suites / baselines encrypted at rest; tenant isolated.
5. Callbacks: webhook / GitHub check run annotation.

## Pricing wedge / 定价切入点

| Tier | Includes |
|------|----------|
| OSS | Local runner CLI, demo suites, JUnit, TAP13, Markdown (`GITHUB_STEP_SUMMARY`), GHA `::error` annotations (`--format gha`), baseline diff CLI (free, offline) |
| Pro | Hosted runners, private suite storage, **autoscaling / multi-node pools**, parallel shards, SLA — **API key seats** |
| Enterprise | VPC, on-prem runner, SSO, audit export |

OSS core stays free (cassette runner + import/diff).
Hosted compute + private suite hosting is the paid wedge.
The local `serve` stub + Bearer `demo` key only **sketches** that wedge for demos/pilots.

Packaging hooks:
- agent_ci import-suite for private fixtures
- run --diff-baseline for CI regression gate
- `agent_ci serve` local stub for API-shaped demos (in-memory queue; hosted autoscaling = paid later; optional `--cors-origins` / `AGENT_CI_CORS_ORIGINS`; optional `--webhook-url` / `AGENT_CI_WEBHOOK_URL` fire-and-forget run-complete POST; optional `--webhook-secret` / `AGENT_CI_WEBHOOK_SECRET` HMAC; OSS 1 retry on 5xx/timeout; exponential backoff / queues / key rotation / timestamp replay = paid later)
- `agent_ci report-check` local Check Run JSON + mock POST (GitHub token post = paid later)
- real hosted runner removes local GPU/LLM operational burden

---

Doc status: local stub implemented; cloud control plane / runner pool still design-only.
