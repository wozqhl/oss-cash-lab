# ROADMAP · 90-Day Portfolio Plan

> 中文为主 · Owner: wozqhl · 2026-08-12

## 原则 / Principles

1. **先收钱，再铺面** — prioritize B (gateway) + C (eval CI) with clear buyers.
2. **并行但限额** — max 2 MVP sprints + 1 scaffold warmup.
3. **OSS 引流 / Paid 关卡** — core open; SSO/audit/quota/on-prem paid.
4. **可演示 > 可扩展** — first 6 weeks optimize for pilot demos.

---

## Phase 1 — Weeks 1–2: B + C MVP parallel

### B · MCP Gateway (TypeScript)
- [x] Local stdio/HTTP MCP proxy (tools/list + tools/call)
- [x] Real upstream HTTP/stdio proxy + mock-upstream merge/filter
- [x] Static allow/deny + simple rate-limit
- [x] JSONL audit log
- [x] `mcp-gateway smoke` + sample config
- [x] README: who pays (platform / security / AI platform)

### C · Agent CI (Python)
- [x] Fixture-driven deterministic eval runner
- [x] Fixed seed / mock LLM; pass/fail + JUnit XML
- [x] CI-friendly exit codes
- [x] `agent-ci run --suite demo`
- [x] README: who pays (eng productivity / agent product)

**Exit:** `make smoke` green; 5-min demo each; 3 pilot contacts each (offline).

---

## Phase 2 — Weeks 3–6: paid pilot + A/D

### B/C paid pilot packaging
- [x] B: API-key tenant sketch, hot policy reload, audit query API
- [x] B admin tenant API token rotation (`POST /admin/tenants/{id}/rotate`; admin-only; grace default 60s / `TOKEN_ROTATE_GRACE_SEC` / `--rotate-grace-sec`; both keys during grace; audit `token_rotated` no secrets; file-backed persist; smoke + isolated local-mvp; stack-demo OpenAPI only)
- [x] B Streamable HTTP MVP (`POST /mcp` JSON-RPC initialize/tools/list/tools/call + session/protocol headers; `GET /mcp` 405 Allow: POST, DELETE; not full SSE; REST `/tools/*` unchanged)
- [x] B Streamable HTTP session TTL (`--session-ttl` / `MCP_SESSION_TTL_SEC` default 3600s; `0` = no expiry; in-memory last-seen cap 10000 drop oldest; expired `Mcp-Session-Id` → 404 `{error:session_expired}`; missing still allowed; unknown ids tracked; REST `/tools/*` unchanged; smoke + isolated local-mvp)
- [x] B Streamable HTTP session terminate (`DELETE /mcp` + `Mcp-Session-Id`; 204; missing 400 `session_id_required`; unknown/expired 404 `session_not_found`; no admin token; GET 405 Allow: POST, DELETE; CORS methods include DELETE; REST `/tools/*` unchanged; OpenAPI `mcpSessionDelete`; smoke + isolated local-mvp + stack-demo OpenAPI/400)
- [x] B admin session inventory (`GET /admin/sessions`; same admin token; live in-memory sessions `{ok,ttlSec,cap,count,sessions[{id,ageMs,ttlRemainingMs,lastSeen}]}`; cap 100 newest; tombstones omitted; no secrets; OpenAPI `adminListSessions`; smoke + isolated local-mvp + CORS OPTIONS; stack-demo OpenAPI + 401)
- [x] B admin session force-drop (`DELETE /admin/sessions/{id}`; same admin token; id in path, no `Mcp-Session-Id`; 204; unknown/expired 404 `session_not_found`; unauth 401; client `DELETE /mcp` unchanged; OpenAPI `adminDeleteSession`; smoke + isolated local-mvp + CORS OPTIONS DELETE; stack-demo OpenAPI + unauth 401)
- [x] B admin runtime config (`GET /admin/config`; same admin token; redacted `{ok,sessionTtlSec,sessionCap,auditMax,rotateGraceSec,rateLimit,cors.origins,upstream.timeoutMs/breaker,tenants.count,webhooks.count+hasWebhookSecret}`; never apiKey/secrets; OpenAPI `adminGetConfig`; smoke helper + 401/200; local-mvp curl; stack-demo OpenAPI + 401)
- [x] B admin single tenant (`GET /admin/tenants/{id}`; same admin token; `{ok,id,hasApiKey,hasPreviousApiKey,previousApiKeyExpiresAt,allow,deny,rateLimit}`; never apiKey/previousApiKey values; 404 `tenant_not_found`; OpenAPI `adminGetTenant`; smoke helper + 401/200/404; local-mvp curl; stack-demo OpenAPI + 401)
- [x] B admin webhook inventory (`GET /admin/webhooks`; same admin token; redacted `{ok,count,webhooks[{id,events,hasUrl,hasSecret}]}`; never url/secret; empty `{ok:true,count:0,webhooks:[]}`; OpenAPI `adminListWebhooks`; smoke helper + 401/200; local-mvp curl; stack-demo OpenAPI + 401)
- [x] B HTTP MCP client config example (`examples/mcp/gateway.mcp.json`; Cursor/Claude `url` → `:8787/mcp` + Bearer placeholder; POST-only not SSE; parse-only `scripts/check-mcp-examples.sh` on smoke; no live Cursor)
- [x] B: `serve --watch` config mtime poll reload (300ms; same path as SIGHUP / POST /admin/reload; logs `regenerated`; local-mvp isolated copy prove)
- [x] B: audit export packs (`GET /audit/export` JSON/CSV + offline `export-audit` CLI)
- [x] B: gzip audit export (`?gzip=1` / `Accept-Encoding: gzip` / CLI `--gzip`; `Content-Encoding: gzip`; `.json.gz` / `.csv.gz`)
- [x] B admin SIEM audit CSV (`GET /admin/audit.csv` / `GET /admin/audit?format=csv|json`; columns `ts,tenantId,tool,allow,reason,via,requestId`; no bodies/tokens; admin token; empty header-only; gzip JSON stays on `/audit/export`)
- [x] B admin SIEM audit Markdown (`GET /admin/audit.md` / `GET /admin/audit?format=md`; same admin gate + columns as CSV; `text/markdown`; `# Audit` GFM table; empty heading+header; CLI `--format md`; smoke + local-mvp 200/401; stack-demo OpenAPI only)
- [x] B admin SIEM audit HTML (`GET /admin/audit.html` / `GET /admin/audit?format=html`; same admin gate + columns as CSV; `text/html`; self-contained no CDN; escaped text; deny/allow distinct; empty heading+no events; CLI `--format html` stdout; smoke + local-mvp 200/401; stack-demo OpenAPI `getAdminAuditHtml` + unauth 401)
- [x] B in-memory audit ring (`--audit-max` / `AUDIT_MAX_EVENTS` default 10000; `0` = unlimited/dangerous; drop oldest; live HTTP/export/admin CSV see retained window; webhook fan-out kept; gauges `audit_events`/`audit_retained`; smoke + isolated local-mvp)
- [x] B audit webhook HMAC (`webhooks[].secret` → `X-Webhook-Signature: sha256=<hex>` HMAC-SHA256 of raw body; mock receiver optional verify; simple HMAC OSS; key rotation / timestamp replay = paid later)
- [x] B outbound webhook timestamp (`X-Webhook-Timestamp: <unix-seconds>` on every POST; HMAC still body-only; replay window enforcement = paid later)
- [x] B audit webhook 1 retry (5xx/network/timeout → one POST retry after ~50ms; 4xx/success no retry; optional `webhook_retries_total`; exponential backoff / queues = paid)
- [x] B: OpenAPI 3 spec + `/openapi.json` + Prometheus `/metrics` counters
- [x] B: `upstream.timeoutMs` (default 5000) HTTP/stdio abort → 504 `upstream_timeout`
- [x] B: `upstream.breaker` (`failureThreshold` 3 / `openMs` 2000; omit to disable) consecutive timeout/5xx/connect → 503 `circuit_open` (half-open probe)
- [x] B: GET /health circuit snapshot (`breaker: { state, failures, openUntil }` when enabled; omitted when disabled; isolated local-mvp open → half_open → closed)
- [x] B: GET /ready readiness (200 `{ok:true}` when disabled/closed/half_open; 503 `{ok:false, reason:circuit_open}` when open; breaker snapshot when enabled; `/health` liveness unchanged; compose stays on `/health`)
- [x] B/C/D/E/F graceful SIGTERM/SIGINT drain (`/ready` 503 `shutting_down`; `/health` 200 `shuttingDown`; drain 5s / `--drain-ms` / `SHUTDOWN_DRAIN_MS` cap 30s; isolated local-mvp TERM prove on B+C)
- [x] B/C/D/E/F JSON access logs (`--log-json` / `LOG_FORMAT=json`; default off; skip probes; isolated local-mvp B+C)
- [x] B: 503 circuit_open Retry-After (remaining seconds until openUntil, min 1; OpenAPI 503 headers; isolated local-mvp; health snapshot unchanged)
- [x] B: CORS (`cors.origins` `*` or list; default deny; OPTIONS 204/403 `cors_denied`; GET/POST ACAO; default expose Retry-After + X-Request-Id; local-mvp localhost:3000 vs evil.example)
- [x] C: private suite import, baseline diff report, hosted runner design + local `serve` stub
- [x] C: GitHub Check Run adapter skeleton (`report-check` local JSON + mock receiver; token post paid later)
- [x] C DeepEval-shaped JSON adapter (`from-deepeval`; fixture-only; not full compatibility)
- [x] C JUnit XML export (`run --format junit`; `GET /v1/runs/{id}/junit.xml` + `GET /v1/runs/junit.xml`; escaped XML; smoke fake pass+fail `&amp;`; local-mvp curl 200)
- [x] C TAP13 export (`run --format tap`; `GET /v1/runs/{id}/tap.txt` alias `/tap` + `GET /v1/runs/tap.txt`; empty → `1..0`; `#` escaped; gate → `not ok`; smoke + local-mvp curl 200 + stack-demo empty aggregate)
- [x] C Markdown run report (`run --format md`; `GET /v1/runs/{id}/report.md` alias `/md` + `GET /v1/runs/report.md`; `text/markdown`; empty → heading + no rows; `|` escaped; `$GITHUB_STEP_SUMMARY`; smoke + local-mvp curl 200 + stack-demo empty/OpenAPI)
- [x] C GitHub Actions workflow-command annotations (`run --format gha` / `annotations`; `GET /v1/runs/{id}/annotations.txt` alias `/annotations` + `GET /v1/runs/annotations.txt`; `::error title=<suite>/<case>`; gate `title=gate`; pass-only empty; no GitHub required; smoke + local-mvp + stack-demo OpenAPI)
- [x] C HTML run report (`run --format html`; `GET /v1/runs/{id}/report.html` alias `/html` + `GET /v1/runs/report.html`; `text/html`; self-contained no CDN; empty → heading + no runs; names escaped; fail rows red; smoke + local-mvp curl 200 + stack-demo empty/OpenAPI `getRunHtml`)
- [x] C run-vs-run baseline diff (`GET /v1/runs/{id}/diff?against=`; CLI `diff --from/--to`; case identity `suite/name`; `{ok,from,to,added,removed,regressed,fixed,unchanged}`; incomplete **409** `run_not_done`; distinct from `--diff-baseline`; smoke extra-fail + identical; local-mvp POST two + curl 200; stack-demo OpenAPI `getRunDiff`)
- [x] C run-vs-run baseline diff Markdown (`GET /v1/runs/{id}/diff.md?against=` / `?format=md`; CLI `diff --from/--to --format md`; `text/markdown`; heading + counts + GFM tables; `|` escaped; empty “no changes”; same 404/409/400; OpenAPI `getRunDiffMd`; JSON unchanged; smoke extra-fail `regressed`/`demo/flaky` + identical “no changes”; local-mvp curl 200 `text/markdown`; stack-demo OpenAPI)
- [x] C run-vs-run baseline diff HTML (`GET /v1/runs/{id}/diff.html?against=` / `?format=html`; CLI `diff --from/--to --format html`; `text/html`; self-contained no CDN; tables for added/removed/regressed/fixed; names escaped; regressed rows red; empty “no changes”; same 404/409/400; OpenAPI `getRunDiffHtml`; JSON/MD unchanged; smoke extra-fail `<table` + `flaky` escaped + identical “no changes”; local-mvp curl 200 `text/html`; stack-demo OpenAPI)
- [x] C quality gate (`run --fail-under N`; POST `failUnder`; score = passed/total×100; status `failed` + `error: below_threshold`; JUnit failures≥1 / synthetic case; webhook score+gate; smoke + local-mvp)
- [x] C GitHub Actions JUnit example (`examples/github-actions/agent-ci-junit.yml`; `python3 -m agent_ci run --suite fixtures/demo --junit junit.xml` + `actions/upload-artifact@v4`; optional `diff --from/--to --format md >> $GITHUB_STEP_SUMMARY`; parse-only smoke hook; not a live workflow here)
- [x] C: CORS (`serve --cors-origins` / `AGENT_CI_CORS_ORIGINS`; default deny; OPTIONS 204/403 `cors_denied`; GET/POST ACAO; default expose Retry-After + X-Request-Id; isolated local-mvp localhost:3000 vs evil.example)
- [x] C HTTP rate limit (`--rate-limit` / `RATE_LIMIT_PER_MINUTE` default 120; IP sliding window; 429 `{ok:false, reason:rate_limited}` + Retry-After; skip /health /ready /metrics; isolated local-mvp)
- [x] C: `X-Request-Id` (incoming or generated UUID; echo every response incl 4xx/OPTIONS; `requestId` on run records / GET / list; CORS allow/expose; local-mvp custom-id proof)
- [x] C: run-complete webhook (`serve --webhook-url` / `AGENT_CI_WEBHOOK_URL`; fire-and-forget POST `{runId,status,summary,requestId,conclusion}` after done|error; local-mvp mock receiver; OSS 1 retry on 5xx/timeout; exponential backoff / queues / key rotation / timestamp replay = paid later)
- [x] C run-complete webhook HMAC (`--webhook-secret` / `AGENT_CI_WEBHOOK_SECRET` → `X-Webhook-Signature: sha256=<hex>` HMAC-SHA256 of raw body; mock receiver optional verify; simple HMAC OSS; key rotation / timestamp replay = paid later)
- [x] C outbound webhook timestamp (`X-Webhook-Timestamp: <unix-seconds>` on every POST; HMAC still body-only; replay window enforcement = paid later)
- [x] C run-complete webhook 1 retry (5xx/network/timeout → one POST retry after ~50ms; 4xx/success no retry; exponential backoff / queues = paid)
- [x] C: OpenAPI 3 (`openapi/runner.openapi.json` + `GET /openapi.json`; Bearer + `X-Request-Id`; 202/429/401/404; `/metrics`; outbound `RunCompleteWebhook` + HMAC note; local-mvp curl asserts)
- [x] C: GET /ready readiness (200 `{ok:true, queue}` when POST would enqueue; 503 `{ok:false, reason:queue_full}` + Retry-After when at capacity; `/health` liveness unchanged; compose stays on `/health`)
- [x] C graceful SIGTERM/SIGINT drain (`/ready` 503 `shutting_down`; stop new queue jobs; isolated local-mvp TERM prove)
- [x] C: Prometheus `GET /metrics` (`agent_ci_queue_depth`, `agent_ci_running`, `agent_ci_runs_completed_total`, `agent_ci_runs_failed_total`; CORS same as other GET; local-mvp curl after a completed run asserts names)
- [x] Dogfood A on C OpenAPI (`make dogfood-a-c` / `scripts/generate-runner-sdk.sh`)
- [x] C `serve --watch` fixtures max-mtime poll (400ms; logs `regenerated`; `/health` `watch.generation`; local-mvp isolated mkdir-suite prove)
- [x] C finished-run history cap (`--runs-max` / `RUNS_MAX` default 1000; `0` = unlimited; drop oldest done|failed|error; in-flight queue uncapped; list/junit/tap/md/html/annotations aggregates see retained window; GET by id 404 if dropped; smoke + isolated local-mvp `--runs-max 2`)
- [x] C GET /v1/config redacted runtime config (public like /v1/suites; allowlist queue.max/depth, failUnder, cors.origins, rateLimit.perMinute, runsMax, webhooks.hasUrl/hasSecret, suitesCount; never URL/secret/tokens/fixtures; OpenAPI `getConfig`; smoke + local-mvp + stack-demo)
- [x] C GET /v1/suites/{name} suite detail (`{ok,id,name,cases:[{name}]}`; no fixture dump; 404 `suite_not_found`; OpenAPI `getSuite`; smoke + local-mvp + stack-demo)
- [x] C GET /v1/runs/{id}/cases lightweight inventory (`{ok, runId, status, count, cases:[{suite, name, status, durationMs?}]}`; optional `?status=`; cap 500 + `truncated`; empty/in-flight 200; 404 unknown id; never prompts/expected/actual/secrets; OpenAPI `listRunCases`; smoke + local-mvp + stack-demo)
- [x] Pricing anchors in B/C READMEs (draft)
- [x] Pilot contract outline (`docs/pilot-contract-outline.md`)

### A · SDK + MCP Gen (TypeScript) scaffold→MVP
- [x] OpenAPI 3.x → minimal TS + Python + Go + Java + Rust + C# + Kotlin + Swift + Ruby + PHP SDK stubs + MCP tool registry + stdio MCP servers (`mcp-server.mjs` + `mcp_server.py` + `mcp_server.go`)
- [x] `sdk-mcp-gen generate ./petstore.yaml --out ./out` (JSON + YAML subset)
- [x] Wire output behind B gateway (`scripts/wire-a-to-b.sh`)
- [x] Dogfood A on B OpenAPI (`make dogfood-a-b` / `scripts/generate-gateway-sdk.sh`)
- [x] A breaking check (`check --out/--baseline`, `generate --check-baseline`; local-mvp mutate/restore)
- [x] A GitHub Actions OpenAPI drift example (`examples/github-actions/sdk-mcp-gen-check.yml`; petstore generate twice + `--check-baseline`; not a live workflow here)
- [x] A `generate --watch` mtime poll regenerate (200ms; local-mvp brief background proof)
- [x] A `generate --watch --url` remote poll (ETag 304 / body hash; default 2s; `--watch-interval-ms`; smoke + isolated http.server; file watch unchanged)
- [x] A checksum manifest (`checksums.sha256` + `verify-checksums --out`; local-mvp tweak/restore)
- [x] A `generate --dry-run` (JSON `{files, operations, tools, langs}`; no writes; local-mvp empty/unchanged)
- [x] A stdio MCP server gen (`mcp-server.mjs`; JSON-RPC initialize / tools/list / tools/call; `--base-url` / `MCP_BASE_URL`; checksums + dry-run + watch; smoke/local-mvp tools/list prove)
- [x] A Python stdio MCP server gen (`mcp_server.py`; same JSON-RPC + tool names as JS; stdlib urllib; checksums + dry-run + watch; smoke/local-mvp tools/list prove)
- [x] A Go stdio MCP server gen (`mcp_server.go`; package main; same JSON-RPC + tool names as JS; stdlib net/http; checksums + dry-run + watch; smoke/local-mvp tools/list prove if go on PATH)
- [x] A `generate --package-name` (alias `--package`; env `SDK_PACKAGE_NAME`; default `client`; TS package.json + Python module + Go package + Java/Kotlin/C#/Ruby/PHP; dry-run prints packageName; mcp-server names unchanged including `mcp_server.go` package main)
- [x] A OpenAPI 3.1.x (`openapi: 3.1.0` / 3.1.x; type `[string,"null"]` → string optional; `examples` vs `example`; `$ref`; ignore `webhooks`; petstore 3.0 unchanged; `examples/openapi-3.1-mini.json` smoke + local-mvp)
- [x] A `generate --url` (http/https/file; 10s / 2MB / ≤3 redirects; XOR file path; non-2xx exit 1; dry-run after fetch; smoke file:// + isolated http.server; petstore file path unchanged)
- [x] A `generate --url --header` (repeatable; env `SDK_FETCH_HEADER`; http(s) only; error without `--url`; not sent to `file://`; redact Authorization; smoke + isolated local-mvp auth loopback)
- [x] A `generate --watch --url` (ETag / If-None-Match 304 skip; body hash fallback; default 2s; `--watch-interval-ms`; `--header` on polls; fetch errors log once; smoke 304/hash; isolated http.server prove; file watch 200ms unchanged)
- [x] A MCP client config snippet (`mcp.json`; paste into MCP servers config JSON; relative `./mcp-server.mjs`; `--dry-run` lists it; checksums include it; `--no-mcp` skips; smoke + local-mvp JSON parse; no Cursor required)
- [x] A `generate --zip` (`sdk.tgz` via tar or store-only `sdk.zip`; after checksums; dry-run lists name; checksums omit archive; smoke + local-mvp listing includes mcp-server.mjs or mcp.json; default generate unchanged)
- [x] A generated Apache-2.0 `LICENSE` + `NOTICE` (default on; always overwrite; `--no-license` skips; checksums + dry-run + zip; independent of `--no-mcp`; smoke + local-mvp)
- [x] A generated `.gitignore` (default on; always overwrite; `--no-gitignore` skips; checksums + dry-run + zip; independent of `--no-mcp` / `--no-license`; smoke + local-mvp)
- [x] A GitHub Actions OpenAPI drift example (`examples/github-actions/sdk-mcp-gen-check.yml`; `generate --out sdk-new --check-baseline sdk`; exit 1 on removed/renamed tools; parse-only smoke hook + petstore generate twice; not a live workflow here)

- [x] A generated Rust / PHP / Swift / Ruby timeout + 429/5xx retry + per-op bearer/apiKey auth (same policy as TS/Python/Go/Java; Rust TcpStream http://)
- [x] A generated clients default User-Agent `sdk-mcp-gen/0.1.0` (or package name) unless already set + `X-Request-Id` per HTTP attempt (`SDK_REQUEST_ID` pin; smoke ua-ok / request-id-ok)
- [x] A generated clients send Idempotency-Key on POST/PUT/PATCH/DELETE when unset (retries reuse; SDK_IDEMPOTENCY_KEY pin; smoke idem-ok)
- [x] A generated stdio MCP servers send User-Agent + X-Request-Id + Idempotency-Key on tools/call (smoke mcp-id-ok)
- [x] A generated stdio MCP servers retry 429 / 5xx / network on tools/call (max 2 retries; Idempotency-Key reused; smoke mcp-retry-ok)
- [x] A generated stdio MCP servers apply a per-attempt 10s timeout on tools/call (MCP_TIMEOUT_MS / MCP_TIMEOUT_SEC or SDK_TIMEOUT_*; smoke mcp-timeout-ok)
- [x] A `registry-pack` dry-run for generated `mcp-server.mjs` (local server.json + wrapper tarball; smoke registry-pack-ok; never POSTs)
### D · AI-BOM (Python) scaffold→MVP
- [x] Scan dir for model IDs, prompts, MCP deps
- [x] CycloneDX-like JSON
- [x] `ai-bom scan ./path`
- [x] Policy pack (`policies/default.json`) + `--strict` exit codes
- [x] Compliance `--evidence` DRAFT (EN/中文) for auditors
- [x] `--sarif` SARIF 2.1.0 for GitHub code scanning
- [x] SPDX license fields on BOM components (`package.json` / `pyproject` / `requirements`)
- [x] `.aibomignore` + `--ignore` path filters
- [x] License exceptions sidecar `.aibom-exceptions.json` / `--exceptions` (component+license waiver, reason, optional expiry; expired still fails)
- [x] Local BOM HTTP server (`serve --port 8793`, stdlib http.server; GET /health /ready /bom.json /evidence.md / /metrics; hosted inventory = paid later)
- [x] D GET /ready readiness (always 200 `{ok:true, service}` + same snapshot as `/health`; no circuit/queue; `/health` liveness unchanged; compose stays on `/health`)
- [x] D graceful SIGTERM/SIGINT drain (`/ready` 503 `shutting_down`; `/health` 200 `shuttingDown`)
- [x] CORS (`serve --cors-origins` / `AI_BOM_CORS_ORIGINS`; default deny; OPTIONS 204/403 `cors_denied`; GET ACAO; default expose Retry-After + X-Request-Id; isolated local-mvp localhost:3000 vs evil.example)
- [x] D HTTP rate limit (`--rate-limit` / `RATE_LIMIT_PER_MINUTE` default 120; IP sliding window; 429 `{ok:false, reason:rate_limited}` + Retry-After; skip /health /ready /metrics; isolated local-mvp)
- [x] `X-Request-Id` (incoming or generated UUID; echo every response incl 4xx/OPTIONS; CORS allow/expose; local-mvp custom-id proof on `/health` + `/openapi.json`)
- [x] OpenAPI 3 (`openapi/bom.openapi.json` + `GET /openapi.json`; `/ready` `getReady`; `X-Request-Id`; 403 CORS notes; local-mvp curl asserts)
- [x] Prometheus `GET /metrics` (`ai_bom_component_count`, `ai_bom_policy_hits`, `ai_bom_forbidden_licenses`; CORS same as other GET; local-mvp curl asserts names)
- [x] Dogfood A on D OpenAPI (`make dogfood-a-d` / `scripts/generate-bom-sdk.sh`)
- [x] Policy-hit webhook (`scan --webhook-url` / `AI_BOM_WEBHOOK_URL`; fire-and-forget POST `{ok:false,policyHits,forbiddenLicenses,summary}` on forbidden hits / forbidden licenses; local-mvp mock receiver; OSS 1 retry on 5xx/timeout; exponential backoff / queues / key rotation / timestamp replay = paid later)
- [x] D policy-hit webhook HMAC (`--webhook-secret` / `AI_BOM_WEBHOOK_SECRET` → `X-Webhook-Signature: sha256=<hex>` HMAC-SHA256 of raw body; mock receiver optional verify; simple HMAC OSS; key rotation / timestamp replay = paid later)
- [x] D outbound webhook timestamp (`X-Webhook-Timestamp: <unix-seconds>` on every POST; HMAC still body-only; replay window enforcement = paid later)
- [x] D policy-hit webhook 1 retry (5xx/network/timeout → one POST retry after ~50ms; 4xx/success no retry; exponential backoff / queues = paid)
- [x] D `serve --watch` dir max-mtime poll rescan (500ms; snapshot for /bom.json /health /metrics / /; local-mvp isolated temp-dir prove)
- [x] D CycloneDX 1.5 + SPDX 2.3 JSON export (`scan --format cyclonedx|spdx|json`; `GET /v1/bom?format=`; default internal json unchanged; local-mvp CLI spdx + HTTP cyclonedx)
- [x] D HTTP SARIF 2.1.0 (`GET /v1/bom?format=sarif` / `GET /v1/bom.sarif`; same `to_sarif` as CLI `--sarif`; `--format sarif` alias; local-mvp HTTP 200)
- [x] D CycloneDX 1.5 XML export (`scan --format cyclonedx-xml`; `GET /v1/bom?format=cyclonedx-xml` / `GET /v1/bom.xml`; same model as JSON; `cyclonedx` stays JSON; local-mvp HTTP 200)
- [x] D SPDX 2.3 XML export (`scan --format spdx-xml`; `GET /v1/bom?format=spdx-xml` / `GET /v1/bom.spdx.xml`; same packages/`licenseConcluded` as JSON; `spdx` stays JSON; local-mvp HTTP 200)
- [x] D Markdown BOM summary (`scan --format md`; `GET /v1/bom?format=md` / `GET /v1/bom.md`; `text/markdown`; human/Slack; empty heading+zeros; not an SBOM spec; local-mvp HTTP 200)
- [x] D GitHub Actions workflow-command annotations (`scan --format gha` / `annotations`; `GET /v1/bom?format=gha` / `GET /v1/bom.gha.txt`; `::error title=<component>::<license or rule>`; waived `::notice`; clean empty; no GitHub required; smoke + local-mvp + GHA example one-liner)
- [x] D HTML BOM summary (`scan --format html`; `GET /v1/bom?format=html` / `GET /v1/bom.html`; `text/html`; self-contained no CDN; empty → heading + zeros; names escaped; policy hits / forbidden licenses red; smoke + local-mvp curl 200 + stack-demo OpenAPI `getBomHtml`)
- [x] D GET /v1/policy active license/policy gate (`{ok, forbiddenLicenseIds, forbiddenPatterns, exceptionsCount, ignoreFile}`; 200 empty lists if no policy file; no file dump / secrets; CORS + X-Request-Id; OpenAPI `getPolicy`; smoke + local-mvp + stack-demo)
- [x] D GET /v1/config redacted runtime knobs (public like /v1/policy; allowlist ok, rateLimit.perMinute, cors.origins, watch, scanPathBase basename only, hasPolicyFile, webhooks.hasUrl/hasSecret; never webhook URL/secret, full policy JSON, or exception contents; OpenAPI `getConfig`; smoke + local-mvp isolated + stack-demo)
- [x] D GET /v1/components lightweight inventory (`{ok, count, components:[{name, version, license, path}]}`; path relative/basename only; empty 200; optional `?license=`; cap 500 + `truncated`; CORS + X-Request-Id; OpenAPI `listComponents`; smoke helper + HTTP; local-mvp curl 200; stack-demo curl 200 + OpenAPI)
- [x] D GET /v1/exceptions redacted waiver inventory (`{ok, count, exceptions:[{component, license, expiresAt, expired}]}`; count=full; cap 500 + `truncated`; empty 200; optional `?expired=`; no sidecar dump / secrets; OpenAPI `listExceptions`; smoke + local-mvp + stack-demo)
- [x] D evidence-pack CRA window clock (`pack.json` `clock` + zip + `--as-of`; daysUntil/daysOverdue vs 2026-09-11 and 2027-12-11 from observed advisory hits; calendar/evidence helper, not a CRA certificate; 日历/证据辅助，不是 CRA 合格证书; smoke `cra-clock-ok`)

**Exit:** >=1 paid verbal intent on B or C; A/D smoke + demo.

---

## Phase 3 — Weeks 7–12: E cost demo + F one connector

### E · OTel AI Cost (TypeScript)
- [x] Estimate token cost from OTel span attrs (configurable price table)
- [x] `otel-ai-cost report --in spans.json`
- [x] stdout table + self-contained HTML (`--html`)
- [x] Policy pack (`policies/redact-basic.json`) for filter redact/sample
- [x] `route` multi-sink sketch (kept vs dropped)
- [x] Local cost alert thresholds (`policies/budget.json`, `report --budget` / `check-budget`, exit 1)
- [x] Budget-breach webhook (`report --budget --webhook-url` / `OTEL_AI_COST_WEBHOOK_URL`; fire-and-forget POST `{ok:false,breaches,totalUsd}` on breach only; OSS 1 retry on 5xx/timeout; exponential backoff / queues / key rotation / timestamp replay = paid later)
- [x] E budget-breach webhook HMAC (`--webhook-secret` / `OTEL_AI_COST_WEBHOOK_SECRET` → `X-Webhook-Signature: sha256=<hex>` HMAC-SHA256 of raw body; mock receiver optional verify; simple HMAC OSS; key rotation / timestamp replay = paid later)
- [x] E outbound webhook timestamp (`X-Webhook-Timestamp: <unix-seconds>` on every POST; HMAC still body-only; replay window enforcement = paid later)
- [x] E budget-breach webhook 1 retry (5xx/network/timeout → one POST retry after ~50ms; 4xx/success no retry; exponential backoff / queues = paid)
- [x] UTC daily cost rollup (`report --group-by day`, `--out` JSON, HTML by-day section)
- [x] Finance CSV export (`report --format csv`; `GET /v1/costs.csv` / `GET /v1/costs?format=csv`; columns `date,model,spanCount,usd,tenant`; empty → header only)
- [x] E Markdown cost report (`report --format md`; `GET /v1/costs.md` / `GET /v1/costs?format=md`; `text/markdown`; empty → heading + zeros; `|` escaped; Slack / email / `$GITHUB_STEP_SUMMARY`)
- [x] E GitHub Actions workflow-command annotations (`report --format gha` / `annotations`; `GET /v1/costs.gha.txt` / `GET /v1/costs?format=gha`; `::error title=budget` / `title=tenant/<id>`; no breach empty; no GitHub required; smoke + isolated local-mvp)
- [x] E GitHub Actions budget-annotation example (`examples/github-actions/otel-ai-cost-gha.yml`; `node src/cli.js report --in examples/spans.json --format gha`; parse-only smoke hook; not a live workflow here)
- [x] E `GET /v1/budgets` configured thresholds (not spend; `{ok:true, globalUsd, tenants}`; missing → null / {}; no secrets; smoke helper acme=10 + isolated local-mvp + stack-demo empty 200)
- [x] E `GET /v1/models` pricing catalog (rates, not spend; `{ok:true, models:[{id, inputPerMTok, outputPerMTok}], defaultModel, pack}`; built-in table; no secrets; smoke helper + HTTP; local-mvp curl 200; stack-demo curl 200 + OpenAPI `getModels`)
- [x] E GET /v1/config redacted runtime config (public like /v1/budgets; allowlist spanCap/spansMax, cors.origins, rateLimit.perMinute, pack, hasGlobalBudget, tenantBudgetCount, webhooks.hasUrl/hasSecret; never URL/secret/tokens/price table; OpenAPI `getConfig`; smoke + local-mvp + stack-demo)
- [x] E `GET /v1/spans` recent span summaries (`{ok, count, spans:[{id, model, tenant, inputTokens, outputTokens, usd, ts}]}`; no prompts/secrets; cap 100 newest + `truncated`; `count` = full retained size; empty 200; OpenAPI `listSpans`; smoke + local-mvp + stack-demo)
- [x] E `GET /v1/tenants` per-tenant spend rollup (`{ok, count, tenants:[{id, spanCount, usd}]}`; missing → `_`; optional `budgetUsd`; cap 100 + `truncated`; empty 200; OpenAPI `listTenants`; smoke + local-mvp + stack-demo)
- [x] E `GET /v1/tenants.csv` chargeback-lite CSV (`tenant,spend_usd,budget_usd,remaining_usd,denied_count`; alias `?format=csv`; OpenAPI `getTenantsCsv`; smoke + local-mvp `export-ok`)
- [x] E optional calendar-day spend window (`BUDGET_PERIOD=day` / `--budget-period day`; remaining/deny reset at UTC midnight; default off; smoke `period-ok`)
- [x] E local HTML remaining-by-tenant table (`GET /` / `--html` when `--tenant-budget`; same remaining as CSV/metrics; period label; Grafana remaining panel already existed; smoke `remain-dash-ok`)
- [x] Tenant cost attribution (span attr `tenant`; JSON `byTenant`; CSV `tenant` last; missing → `_`)
- [x] Local report server (`serve --port 8792`, stdlib http; GET /health /ready / /report.json /v1/costs.csv /v1/costs.md /v1/costs.gha.txt /metrics; hosted dashboard = paid later)
- [x] E `serve --watch` mtime poll reload (200ms; snapshot for / /report.json /v1/costs.csv /v1/costs.md /metrics /health; local-mvp isolated temp-copy prove)
- [x] E OTLP JSON ingest (`POST /v1/traces` / alias `/v1/otlp/v1/traces`; merge into store; optional `INGEST_TOKEN`; 400/401/413; JSON only; smoke + isolated local-mvp)
- [x] E in-memory span cap (`--span-max` / `SPAN_MAX` default 50000; `0` = unlimited; drop oldest; watch reload replaces store then caps; smoke + isolated `--span-max 2`)
- [x] E GET /ready readiness (always 200 `{ok:true, service}` + same snapshot as `/health`; no circuit/queue; `/health` liveness unchanged; compose stays on `/health`)
- [x] E graceful SIGTERM/SIGINT drain (`/ready` 503 `shutting_down`; `/health` 200 `shuttingDown`)
- [x] CORS (`serve --cors-origins` / `OTEL_AI_COST_CORS_ORIGINS`; default deny; OPTIONS 204/403 `cors_denied`; GET ACAO; default expose Retry-After + X-Request-Id; isolated local-mvp localhost:3000 vs evil.example)
- [x] E HTTP rate limit (`--rate-limit` / `RATE_LIMIT_PER_MINUTE` default 120; IP sliding window; 429 `{ok:false, reason:rate_limited}` + Retry-After; skip /health /ready /metrics; isolated local-mvp)
- [x] `X-Request-Id` (incoming or generated UUID; echo every response incl 4xx/OPTIONS; CORS allow/expose; local-mvp custom-id proof on `/health` + `/openapi.json`)
- [x] OpenAPI 3 (`openapi/cost.openapi.json` + `GET /openapi.json`; `/ready` `getReady`; `/v1/costs.csv` `getCostsCsv`; `/v1/costs.md` `getCostsMd`; `/v1/costs.gha.txt` `getCostsGha`; `/v1/budgets` `getBudgets`; `/v1/models` `getModels`; `/v1/config` `getConfig`; `/v1/spans` `listSpans`; `/v1/tenants` `listTenants`; `X-Request-Id`; 403 CORS notes; local-mvp curl asserts)
- [x] Prometheus `GET /metrics` (`otel_ai_cost_total_usd`, `otel_ai_cost_by_model_usd{model}`, `otel_ai_cost_span_count`; CORS same as other GET; local-mvp curl asserts names)
- [x] Dogfood A on E OpenAPI (`make dogfood-a-e` / `scripts/generate-cost-sdk.sh`)

### F · CN Work Agent (Python)
- [x] One IM only (prefer Feishu, or WeCom per pilot)
- [x] Multi-IM local mocks: Feishu + DingTalk + WeCom webhook shapes
- [x] On-prem: Webhook → shared intent route → local MCP/tools
- [x] Per-platform verify (Feishu token/sig, DingTalk token/sign, WeCom echostr/msg_signature)
- [x] Config-driven, no mandatory public cloud (config.example.json + --config)
- [x] Intranet demo runbook (`bets/f-cn-work-agent/docs/intranet-demo.md`)
- [x] `scripts/demo-ask-reply.sh` (config → health → one ask/reply per IM)
- [x] Simple approval flow: intent `审批`/`approve request` → `data/approvals.jsonl`; `GET /approvals` + `POST /approvals/{id}/decide`
- [x] Approval audit CSV export (`export --format csv`; `GET /v1/approvals.csv` / `GET /v1/approvals?format=csv`; columns `id,platform,status,createdAt,decidedAt,reason`; empty → header only)
- [x] Approval Markdown list (`export --format md`; `GET /v1/approvals.md` / `GET /v1/approvals?format=md`; `text/markdown`; GFM table, same columns as CSV; `|` escaped; empty → heading + header row only; Feishu/WeCom docs)
- [x] Approval HTML list (`export --format html`; `GET /v1/approvals.html` / `GET /v1/approvals?format=html`; `text/html`; self-contained no CDN; empty → heading + “no approvals”; names escaped; pending vs decided/expired styled; smoke + local-mvp curl 200 + stack-demo OpenAPI `getApprovalsHtml`)
- [x] Webhook rate limit (`RATE_LIMIT_PER_MINUTE` default 60; IP+platform sliding window; 429 + Retry-After)
- [x] Approval TTL auto-reject (`APPROVAL_TTL_SECONDS` default 86400; expire_due on list/get/decide + serve loop)
- [x] CORS (`CORS_ORIGINS` / `cors.origins`; default deny; OPTIONS 204/403 `cors_denied`; GET/POST ACAO; default expose Retry-After + X-Request-Id; isolated local-mvp localhost:3000 vs evil.example)
- [x] `X-Request-Id` (incoming or generated UUID; echo every response incl 4xx/OPTIONS/429; `requestId` on approvals + audit; CORS allow/expose; local-mvp custom-id proof)
- [x] OpenAPI 3 (`openapi/agent.openapi.json` + `GET /openapi.json`; `/ready` `getReady`; `X-Request-Id`; webhook 401/429; 403 CORS notes; `/metrics`; `/v1/approvals.csv` `getApprovalsCsv`; `/v1/approvals.md` `getApprovalsMd`; `/v1/approvals.html` `getApprovalsHtml`; outbound `ApprovalDecisionWebhook` + HMAC note; local-mvp curl asserts)
- [x] F GET /ready readiness (always 200 `{ok:true, service}` + same snapshot as `/health`; no circuit/queue; not rate-limited; `/health` liveness unchanged; compose stays on `/health`)
- [x] F graceful SIGTERM/SIGINT drain (`/ready` 503 `shutting_down`; `/health` 200 `shuttingDown`)
- [x] Prometheus `GET /metrics` (`cn_work_agent_approvals_pending`, `cn_work_agent_approvals_decided_total`, `cn_work_agent_webhooks_total`; CORS same as other GET; local-mvp curl after create/decide asserts names)
- [x] Dogfood A on F OpenAPI (`make dogfood-a-f` / `scripts/generate-agent-sdk.sh`)
- [x] Approval-decision webhook (`serve --webhook-url` / `APPROVAL_WEBHOOK_URL`; fire-and-forget POST `{id,status,decision,reason,requestId}` on decide/expire; local-mvp mock receiver; OSS 1 retry on 5xx/timeout; exponential backoff / queues / key rotation / timestamp replay = paid later)
- [x] F approval-decision webhook HMAC (`--webhook-secret` / `APPROVAL_WEBHOOK_SECRET` → `X-Webhook-Signature: sha256=<hex>` HMAC-SHA256 of raw body; mock receiver optional verify; simple HMAC OSS; key rotation / timestamp replay = paid later)
- [x] F outbound webhook timestamp (`X-Webhook-Timestamp: <unix-seconds>` on every POST; HMAC still body-only; replay window enforcement = paid later)
- [x] F approval-decision webhook 1 retry (5xx/network/timeout → one POST retry after ~50ms; 4xx/success no retry; exponential backoff / queues = paid)
- [x] F `serve --watch` config mtime poll reload (300ms; CORS/TTL/webhook url+secret/rate-limit; env wins if already set; logs `regenerated`; local-mvp isolated copy prove)
- [x] F inbound IM callback HMAC (`callbackSecret` / `FEISHU_CALLBACK_SECRET` → POST `X-Callback-Signature: sha256=<hex>` of raw body; optional `X-Callback-Timestamp` 300s skew; GET decide unsigned for cards; default off; 401 no secret leak; isolated local-mvp)
- [x] F decided-approvals cap (`--approvals-max` / `APPROVALS_MAX` default 2000; `0` = unlimited; drop oldest approved/rejected/expired; pending kept; GET by id 404; smoke + isolated local-mvp `--approvals-max 2`)
- [x] F `GET /v1/platforms` IM inventory (`{id,enabled,hasCallbackSecret}`; no secrets; CORS + X-Request-Id; smoke + local-mvp curl 200 + ids; stack-demo curl 200)
- [x] F `GET /v1/config` redacted runtime config (`approvalTtlSec` / `rateLimit` / `cors.origins` / `approvalsMax` / `webhooks.hasUrl|hasSecret` / platforms; public GET, no admin token; never secrets; CORS + X-Request-Id; smoke + local-mvp curl 200 + OpenAPI; stack-demo curl 200)
- [x] F `GET /v1/approvals?status=` (`pending`/`approved`/`rejected`/`expired`; CSV/MD/HTML share helper; unknown/empty → 200 empty; omit unfiltered; OpenAPI enum; smoke + local-mvp + stack-demo)
- [x] F Dify / n8n sample approval forward (`APPROVAL_FORWARD_URL` / `--forward-url`; `{event,approval_id,status,tenant|app,title}` on approved/rejected; 1 retry; no secrets; example wiring, not a plugin; smoke `forward-ok`)
- [x] F Dify / n8n sample approval forward (`APPROVAL_FORWARD_URL` / `--forward-url`; `{event,approval_id,status,tenant|app,title}` on approved/rejected; 1 retry; no secrets; example wiring, not a plugin; smoke `forward-ok`)


**Exit:** E cost demo; F one ask/reply on intranet; portfolio kill/double/hold review.

---

## Kill / Double-down (week 12)

| Signal | Action |
|--------|--------|
| No pilot talks in 6 weeks | Kill or freeze |
| Intent but hard to build | Shrink scope, double sales |
| Cold OSS, hot pilots | Cut community, ship |
| Narrative crushed by giants | Verticalize (industry/region/compliance) |

```
W1-W2   B MVP + C MVP
W3-W4   B/C pilot pack + A scaffold
W5-W6   A MVP + D MVP
W7-W8   E demo
W9-W12  F one connector + review
```

---

## Local iteration status (2026-08-14)

- [x] All six bets: `make smoke` + `make local-mvp`
- [x] A YAML OpenAPI + petstore example
- [x] A OpenAPI 3.1 mini (`examples/openapi-3.1-mini.json`; 3.1.x accepted; type unions / examples / $ref; webhooks ignored; petstore 3.0.3 unchanged)
- [x] A `generate --url` (http/https/file://; 10s timeout, 2MB, ≤3 redirects; XOR file path; smoke file:// + local-mvp python http.server; petstore file path unchanged)
- [x] A `generate --url --header` (repeatable `Name: value`; env `SDK_FETCH_HEADER`; http(s) only; error without `--url`; not sent to `file://`; values never printed; smoke + local-mvp 401/200 with `test-token`)
- [x] A `generate --watch --url` (ETag/304 skip + body hash; default 2s; `--watch-interval-ms`; `--header` on polls; log-once fetch errors; smoke + isolated http.server; file watch unchanged)
- [x] A MCP client config snippet (`mcp.json` paste into MCP servers config JSON; relative args; `--no-mcp`; smoke + local-mvp JSON parse)
- [x] A `generate --zip` (sdk.tgz / sdk.zip SDK drop; checksums first; dry-run lists name; smoke + local-mvp)
- [x] A generated Apache-2.0 `LICENSE` + `NOTICE` (default on; `--no-license`; checksums + dry-run + zip; smoke + local-mvp)
- [x] A generated `.gitignore` (default on; `--no-gitignore`; checksums + dry-run + zip; independent of `--no-mcp` / `--no-license`; smoke + local-mvp)
- [x] A `registry-pack` dry-run (generated mcp-server.mjs listing payload; smoke registry-pack-ok; not a submitted listing)
- [x] A GitHub Actions OpenAPI drift example (`examples/github-actions/sdk-mcp-gen-check.yml`; `generate --check-baseline`; parse-only smoke; not a live workflow here)
- [x] A→B file wiring script + portfolio local-mvp hook
- [x] Dogfood A→B OpenAPI SDK generate (`make dogfood-a-b`, gitignore `sdk/generated/`)
- [x] Dogfood A→C OpenAPI SDK generate (`make dogfood-a-c`, gitignore `bets/c-agent-ci/sdk/generated/`)
- [x] E HTML cost report
- [x] F Feishu token/signature verify (401 on bad)
- [x] Paid pilot packaging for B/C (tenant/audit/reload + import/baseline/hosted doc)
- [x] B real upstream HTTP/stdio proxy + `mock-upstream.js` (local-mvp proves HTTP + stdio proxied payload)
- [x] B/C draft pricing anchors in READMEs
- [x] C zip import path exercised in local-mvp
- [x] Pilot contract outline (`docs/pilot-contract-outline.md`)
- [x] Multi-IM F (Feishu + DingTalk + WeCom local webhook mocks)
- [x] Multi-lang A (TS + Python + Go + Java + Rust + C# + Kotlin + Swift + Ruby + PHP client via lang flag; default ts,python,go,java,rust,csharp,kotlin,swift,ruby,php)
- [x] F intranet demo runbook + `demo-ask-reply.sh` (optional `make demo-f`)
- [x] D policy pack + evidence export (Pro wedge)
- [x] D SARIF 2.1.0 output (`--sarif`) + upload-sarif snippet
- [x] D GitHub Actions SARIF example (`examples/github-actions/ai-bom-sarif.yml`; `--sarif ai-bom.sarif` + `github/codeql-action/upload-sarif@v3`; code scanning required on consumer; not a gate here)
- [x] D SPDX `licenses[]` in BOM + evidence license counts
- [x] D CycloneDX 1.5 + SPDX 2.3 document export (`--format` / `GET /v1/bom?format=`; json default unchanged)
- [x] D HTTP SARIF 2.1.0 (`GET /v1/bom?format=sarif` / `/v1/bom.sarif`; same builder as `--sarif`; `--format sarif` alias)
- [x] D CycloneDX 1.5 XML (`--format cyclonedx-xml` / `GET /v1/bom?format=cyclonedx-xml` / `/v1/bom.xml`; json cyclonedx unchanged)
- [x] D SPDX 2.3 XML (`--format spdx-xml` / `GET /v1/bom?format=spdx-xml` / `/v1/bom.spdx.xml`; json spdx unchanged)
- [x] D Markdown BOM summary (`--format md` / `GET /v1/bom?format=md` / `/v1/bom.md`; text/markdown; human/Slack; not an SBOM spec)
- [x] D GitHub Actions workflow-command annotations (`--format gha` / `GET /v1/bom?format=gha` / `/v1/bom.gha.txt`; text/plain; `::error` / waived `::notice`; clean empty)
- [x] D HTML BOM summary (`--format html` / `GET /v1/bom?format=html` / `/v1/bom.html`; text/html; self-contained no CDN; empty heading + zeros; local-mvp curl 200 + stack-demo OpenAPI `getBomHtml`)
- [x] D GET /v1/policy (`forbiddenLicenseIds` / `forbiddenPatterns` ids / `exceptionsCount` / `ignoreFile`; 200 empty if no policy; no file dump)
- [x] D GET /v1/config redacted runtime knobs (`rateLimit` / `cors.origins` / `watch` / `scanPathBase` / `hasPolicyFile` / webhook booleans; never secrets; OpenAPI `getConfig`)
- [x] D GET /v1/components lightweight inventory (`name` / `version` / `license` / `path`; relative/basename; empty 200; `?license=`; cap 500; OpenAPI `listComponents`)
- [x] D GET /v1/exceptions redacted waiver inventory (`component` / `license` / `expiresAt` / `expired`; count=full; cap 500; empty 200; `?expired=`; OpenAPI `listExceptions`)
- [x] D `.aibomignore` + CLI `--ignore`
- [x] D license exceptions sidecar (`.aibom-exceptions.json` / `--exceptions`; waived vs expired; HTTP `?exceptions=skip`)
- [x] D local BOM HTTP server (`serve --port 8793`; GET /health /ready /bom.json /evidence.md HTML /metrics; hosted inventory paid later)
- [x] D GET /ready readiness (always 200 `{ok:true, service}` + same snapshot as `/health`; no circuit/queue; compose stays on `/health`)
- [x] D policy-hit webhook (`scan --webhook-url` / `AI_BOM_WEBHOOK_URL`; fire-and-forget POST `{ok:false,policyHits,forbiddenLicenses,summary}` on forbidden hits / forbidden licenses; local-mvp mock receiver; OSS 1 retry on 5xx/timeout; exponential backoff / queues / key rotation / timestamp replay = paid later)
- [x] D policy-hit webhook HMAC (`--webhook-secret` / `AI_BOM_WEBHOOK_SECRET` → `X-Webhook-Signature: sha256=<hex>` HMAC-SHA256 of raw body; mock receiver optional verify; simple HMAC OSS; key rotation / timestamp replay = paid later)
- [x] D outbound webhook timestamp (`X-Webhook-Timestamp: <unix-seconds>` on every POST; HMAC still body-only; replay window enforcement = paid later)
- [x] D policy-hit webhook 1 retry (5xx/network/timeout → one POST retry after ~50ms; 4xx/success no retry; exponential backoff / queues = paid)
- [x] D OpenAPI (`openapi/bom.openapi.json` + `GET /openapi.json`; `/ready` `getReady`; 403 CORS notes; local-mvp asserts)
- [x] D Prometheus `GET /metrics` (`ai_bom_component_count`, `ai_bom_policy_hits`, `ai_bom_forbidden_licenses`; CORS same as other GET; local-mvp asserts names)
- [x] E redact policy pack + route multi-sink (Pro wedge)
- [x] E local budget thresholds (`--budget` / `check-budget`; alerting + HMAC key rotation / timestamp replay paid later)
- [x] E budget-breach webhook HMAC (`--webhook-secret` / `OTEL_AI_COST_WEBHOOK_SECRET` → `X-Webhook-Signature: sha256=<hex>` HMAC-SHA256 of raw body; mock receiver optional verify; simple HMAC OSS; key rotation / timestamp replay = paid later)
- [x] E outbound webhook timestamp (`X-Webhook-Timestamp: <unix-seconds>` on every POST; HMAC still body-only; replay window enforcement = paid later)
- [x] E budget-breach webhook 1 retry (5xx/network/timeout → one POST retry after ~50ms; 4xx/success no retry; exponential backoff / queues = paid)
- [x] E UTC daily cost rollup (`--group-by day` / `--out` JSON / HTML day section; local-mvp)
- [x] E finance CSV export (`report --format csv` / `GET /v1/costs.csv`; daily-by-model totals; local-mvp)
- [x] E per-tenant budget (`--tenant-budget acme=10,other=5` / `OTEL_AI_COST_TENANT_BUDGETS`; JSON `budgetBreaches`; webhook includes `tenant`; `_` not gated unless explicit; global `--budget` independent; smoke + isolated local-mvp)
- [x] E `GET /v1/budgets` configured thresholds (`{ok:true, globalUsd, tenants}`; not spend; missing → null / {}; no secrets; smoke + isolated `--tenant-budget` + stack-demo empty 200)
- [x] E `GET /v1/models` pricing catalog (`{ok:true, models:[{id, inputPerMTok, outputPerMTok}], defaultModel, pack}`; rates not spend; built-in table; no secrets; smoke + local-mvp curl 200 + stack-demo OpenAPI `getModels`)
- [x] E GET /v1/config redacted runtime config (spanCap / cors / rateLimit / pack / hasGlobalBudget / tenantBudgetCount / webhook booleans; never secrets; OpenAPI `getConfig`; smoke + local-mvp + stack-demo)
- [x] E `GET /v1/spans` recent span summaries (`{ok, count, spans:[{id, model, tenant, inputTokens, outputTokens, usd, ts}]}`; no prompts/secrets; cap 100 newest; OpenAPI `listSpans`; smoke + local-mvp + stack-demo)
- [x] E `GET /v1/tenants` per-tenant spend rollup (`{ok, count, tenants:[{id, spanCount, usd}]}`; missing → `_`; optional `budgetUsd`; cap 100; OpenAPI `listTenants`; smoke + local-mvp + stack-demo)
- [x] E GitHub Actions `::error` annotations (`--format gha` / `GET /v1/costs.gha.txt` / `?format=gha`; text/plain; global `title=budget`; tenant `title=tenant/<id>`; no breach empty; smoke + isolated local-mvp)
- [x] E GitHub Actions budget-annotation example (`examples/github-actions/otel-ai-cost-gha.yml`; `--format gha` + `$GITHUB_STEP_SUMMARY` md + upload-artifact costs.md; parse-only smoke; not a live workflow here)
- [x] E local report server (`serve --port 8792`; GET /health /ready / HTML+SVG /report.json /v1/costs.csv /metrics; hosted dashboard paid later)
- [x] E `serve --watch` mtime poll reload (200ms; local-mvp isolated temp-copy prove)
- [x] E OTLP JSON ingest (`POST /v1/traces`; optional INGEST_TOKEN; JSON only; isolated prove)
- [x] E in-memory span cap (default 50000; `--span-max` / `SPAN_MAX`; drop oldest; watch reload replaces store then caps; smoke + isolated `--span-max 2`; main demo 6 spans unchanged)
- [x] E GET /ready readiness (always 200 `{ok:true, service}` + same snapshot as `/health`; no circuit/queue; compose stays on `/health`)
- [x] C local hosted-runner stub (`serve` HTTP API + Bearer demo seat sketch)
- [x] B audit export packs for pilot delivery (HTTP + offline CLI; local-mvp proves non-empty)
- [x] B admin SIEM audit CSV (`GET /admin/audit.csv`; admin-only; no args/tokens; smoke helper + local-mvp 200/401)
- [x] B admin SIEM audit Markdown (`GET /admin/audit.md` / `?format=md`; same columns as CSV; admin-only; empty heading+header; CLI `--format md`; smoke helper + in-process 401; local-mvp 200/401; stack-demo OpenAPI only)
- [x] B in-memory audit ring cap (default 10000; `--audit-max` / `AUDIT_MAX_EVENTS`; drop oldest; live export/admin CSV window; webhooks not dropped; smoke + isolated `--audit-max 2`)
- [x] B audit export redaction (`?redact=` / `--redact`, `export.redactDefault`, optional `?since=`)
- [x] B audit redaction gaps: GET /audit redact parity, `audit.redactOnWrite`, `until=` on export/query, disk vs export docs
- [x] A Go client.go (stdlib net/http, package client); local-mvp gofmt/vet or heuristic
- [x] A Java Client.java (stdlib HttpURLConnection, package client); local-mvp javac or heuristic; --lang ts does not emit Java
- [x] A Rust client.rs (stdlib TcpStream HTTP/1.1, http:// only); local-mvp rustc or heuristic; --lang ts does not emit Rust
- [x] A C# Client.cs (stdlib HttpClient, namespace Client, PascalCase methods); local-mvp dotnet/csc or heuristic; --lang ts does not emit C#; aliases cs / c#; dogfood A→B/C/D/E/F stay ts,python,go
- [x] A Kotlin Client.kt (stdlib HttpURLConnection, class Client, one fun per op, okhttp-free); local-mvp kotlinc or heuristic (char/string aware); --lang ts does not emit Kotlin; alias kt; dogfood A→B/C/D/E/F stay ts,python,go
- [x] A Swift Client.swift (Foundation URLSession, class Client, one public func per op, Alamofire-free, single file / no SPM); local-mvp swiftc -typecheck or heuristic; --lang ts does not emit Swift; dogfood A→B/C/D/E/F stay ts,python,go
- [x] A Ruby client.rb (stdlib Net::HTTP, class Client, one snake_case method per op, gem-free); local-mvp ruby -c or heuristic; --lang ts does not emit Ruby; alias rb; dogfood A→B/C/D/E/F stay ts,python,go
- [x] A PHP Client.php (stdlib fopen/stream wrappers, class Client, one camelCase method per op, curl-extension-free); local-mvp php -l or heuristic; --lang ts does not emit PHP; dogfood A→B/C/D/E/F stay ts,python,go
- [x] A `--package-name` company module path (default `client`; isolated acme_pets prove; petstore default names unchanged)
- [x] A OpenAPI 3.1.x (accept 3.1.0/3.1.x; type unions → string optional; examples vs example; $ref; ignore webhooks; petstore 3.0 unchanged; mini fixture smoke + local-mvp)
- [x] A `generate --url` (http/https/file; 10s / 2MB / ≤3 redirects; XOR with file operand; non-2xx exit 1; dry-run after fetch; `--watch --url` polls remote; 169.254.169.254 blocked; smoke file:// + isolated http.server; default petstore file path unchanged)
- [x] A `generate --url --header` (repeatable; `SDK_FETCH_HEADER`; http(s) only; error without `--url`; not sent to `file://`; redact Authorization in errors; dry-run names only; smoke + isolated local-mvp)
- [x] A stdio MCP server (`mcp-server.mjs`; Node, no extra deps; JSON-RPC initialize / tools/list / tools/call matching B stdio upstream; `--base-url` / `MCP_BASE_URL`; dry-run + watch + checksums; smoke/local-mvp one-shot tools/list)
- [x] A Go stdio MCP server (`mcp_server.go`; package main; stdlib net/http; same JSON-RPC + tool names as JS/Python; generate does not require go; smoke/local-mvp go run tools/list when go on PATH)
- [x] B OpenAPI (`openapi/gateway.openapi.json` + `GET /openapi.json`) + Prometheus `GET /metrics` (`tool_calls_total`, `rate_limited_total`, `http_requests_total`); local-mvp asserts
- [x] F simple approval flow (JSONL + HTTP list/decide; local-mvp create→list→approve)
- [x] F native IM approval cards (`GET /v1/approvals/{id}/card`; Feishu interactive / DingTalk actionCard / WeCom textcard; mock-only; smoke + local-mvp + stack-demo 404)
- [x] F approval audit CSV (`export --format csv` / `GET /v1/approvals.csv`; createdAt/decidedAt; TTL auto-rejects; local-mvp curl after decide)
- [x] F approval Markdown list (`export --format md` / `GET /v1/approvals.md` / `?format=md`; text/markdown; same columns as CSV; `|` escaped; empty heading + header; local-mvp curl 200; stack-demo empty/OpenAPI)
- [x] F approval HTML list (`export --format html` / `GET /v1/approvals.html` / `?format=html`; text/html; self-contained no CDN; empty heading + no approvals; escaped title; pending vs decided/expired styled; local-mvp curl 200; stack-demo empty/OpenAPI `getApprovalsHtml`)
- [x] F webhook rate limit (`RATE_LIMIT_PER_MINUTE`; isolated local-mvp 429 proof)
- [x] D HTTP rate limit (`--rate-limit` / `RATE_LIMIT_PER_MINUTE` default 120; isolated local-mvp 429 proof)
- [x] E HTTP rate limit (`--rate-limit` / `RATE_LIMIT_PER_MINUTE` default 120; isolated local-mvp 429 proof)
- [x] C HTTP rate limit (`--rate-limit` / `RATE_LIMIT_PER_MINUTE` default 120; isolated local-mvp 429 proof)
- [x] F approval TTL auto-reject (`APPROVAL_TTL_SECONDS`; expire→rejected/expired; local-mvp TTL=1)
- [x] C GitHub Check Run adapter skeleton (local payload + mock POST; real token posting = paid/hosted later)
- [x] C JUnit XML export (`run --format junit`; `GET /v1/runs/{id}/junit.xml` + `GET /v1/runs/junit.xml`; Actions/Jenkins/GitLab ingest; local-mvp curl 200)
- [x] C TAP13 export (`run --format tap`; `GET /v1/runs/{id}/tap.txt` + `GET /v1/runs/tap.txt`; text/plain; empty `1..0`; local-mvp curl 200)
- [x] C Markdown run report (`run --format md`; `GET /v1/runs/{id}/report.md` + `GET /v1/runs/report.md`; text/markdown; empty heading + no rows; `$GITHUB_STEP_SUMMARY`; local-mvp curl 200)
- [x] C HTML run report (`run --format html`; `GET /v1/runs/{id}/report.html` + `GET /v1/runs/report.html`; text/html; self-contained no CDN; empty heading + no runs; local-mvp curl 200)
- [x] C run-vs-run baseline diff (`GET /v1/runs/{id}/diff?against=`; CLI `diff --from/--to`; `suite/name`; 409 `run_not_done`; smoke + local-mvp curl 200; stack-demo OpenAPI)
- [x] C run-vs-run baseline diff Markdown (`GET /v1/runs/{id}/diff.md` / `?format=md`; CLI `--format md`; `text/markdown`; empty “no changes”; OpenAPI `getRunDiffMd`; JSON unchanged; smoke + local-mvp curl 200; stack-demo OpenAPI)
- [x] C run-vs-run baseline diff HTML (`GET /v1/runs/{id}/diff.html` / `?format=html`; CLI `--format html`; `text/html`; self-contained no CDN; empty “no changes”; OpenAPI `getRunDiffHtml`; JSON/MD unchanged; smoke + local-mvp curl 200; stack-demo OpenAPI)
- [x] C GET /v1/runs/{id}/cases lightweight inventory (`{ok, runId, status, count, cases[{suite,name,status}]}`; `?status=`; cap 500; OpenAPI `listRunCases`; smoke + local-mvp + stack-demo)
- [x] C quality gate (`run --fail-under N`; POST `/v1/runs` `failUnder`; score = passed/total×100; status `failed` + `below_threshold`; JUnit synthetic case; webhook score+gate; smoke + local-mvp)
- [x] C GitHub Actions JUnit example (`examples/github-actions/agent-ci-junit.yml`; upload-artifact; optional run-vs-run `diff --from/--to --format md >> $GITHUB_STEP_SUMMARY`; not a live workflow here)
- [x] C local in-memory run queue (`serve --concurrency` / `--max-queue`; queued→running→done; 429 when full; hosted autoscaling = paid later)
- [x] B per-tenant IP allowlist (`ipAllowlist` exact/CIDR; XFF or socket; 403 `ip_denied`; `ip_denied_total`; local-mvp + stack-demo loopback note)
- [x] A breaking check (`check --out/--baseline`, `generate --check-baseline`; local-mvp mutate/restore)
- [x] A `generate --watch` mtime poll regenerate (200ms; local-mvp brief background proof)
- [x] A `generate --watch --url` remote poll (ETag 304 / body hash; default 2s; `--watch-interval-ms`; smoke + isolated http.server; file watch unchanged)
- [x] A `generate --zip` (`sdk.tgz` or store-only `sdk.zip`; after checksums; dry-run lists name; smoke + local-mvp archive lists mcp.json / mcp-server.mjs; default generate no archive)
- [x] A generated Apache-2.0 `LICENSE` + `NOTICE` (default on; always overwrite; `--no-license` skips; checksums + dry-run + zip; `--no-mcp` still writes; smoke + local-mvp)
- [x] A generated `.gitignore` (default on; always overwrite; `--no-gitignore` skips; checksums + dry-run + zip; `--no-mcp` / `--no-license` still write; smoke + local-mvp)
- [x] B CORS (`cors.origins` `*` or list; default deny; OPTIONS 204/403; GET/POST ACAO; default expose Retry-After + X-Request-Id; local-mvp localhost:3000 vs evil.example)
- [x] C CORS (`serve --cors-origins` / `AGENT_CI_CORS_ORIGINS`; default deny; OPTIONS 204/403; GET/POST ACAO; default expose Retry-After + X-Request-Id; isolated local-mvp localhost:3000 vs evil.example)
- [x] B upstream timeout (`upstream.timeoutMs` default 5000; HTTP/stdio abort; 504 `upstream_timeout`; `upstream_timeout_total`; isolated local-mvp delay mock)
- [x] B upstream circuit breaker (`upstream.breaker` failureThreshold 3 / openMs 2000; omit disables; 503 `circuit_open`; `circuit_open_total`; isolated local-mvp delay mock + threshold 1)
- [x] B GET /health circuit snapshot (`breaker: { state: closed|open|half_open, failures, openUntil }` when enabled; no secrets; omitted when disabled; isolated local-mvp open → half_open → closed)
- [x] B GET /ready readiness (200 when disabled/closed/half_open; 503 `{ok:false, reason:circuit_open}` when open; `/health` stays 200; isolated local-mvp open → `/ready` 503, recovery → `/ready` 200)
- [x] B/C/D/E/F graceful SIGTERM/SIGINT HTTP drain (`/ready` 503 `shutting_down`; `/health` 200 `shuttingDown`; `--drain-ms` / `SHUTDOWN_DRAIN_MS`; isolated local-mvp TERM prove)
- [x] Minimal k8s manifests for B/C/D/E/F (`deploy/k8s/`; Deployment+Service; `/health` liveness + `/ready` readiness; `terminationGracePeriodSeconds: 10`; parse-only smoke hook; images not published)
- [x] Thin Helm chart for B–F (`deploy/helm/oss-cash-lab/`; Deployment+Service; same images/ports as k8s; optional NetworkPolicy default off; optional PDB via pdb.enabled default false (maxUnavailable: 1 when on); optional HPA via hpa.enabled default false (CPU 70%, min 1 / max 4 when on; needs metrics-server); optional Ingress via ingress.enabled default false (class nginx, five hosts when on; needs ingress controller); optional LimitRange via limitRange.enabled default true (type Container, defaultRequest 50m/64Mi; does not change explicit resources); optional ResourceQuota via resourceQuota.enabled default false (shared-ns safe); optional securityContext via securityContext.enabled default true (restricted-ish PSS); `templates/NOTES.txt` after helm install (port-forward + /health; ingress hosts when enabled; placeholder images); no Prometheus Operator CRDs; parse-only `scripts/check-helm.sh` on smoke; skip `helm template` if helm missing; kustomize stays default apply)
- [x] Prometheus Operator ServiceMonitors for B–F `/metrics` (`deploy/k8s/servicemonitor.yaml`; one per bet; `port: http` path `/metrics` 30s; parse-only smoke; CRDs not required to prove)
- [x] Kubernetes NetworkPolicy for B–F (`deploy/k8s/networkpolicy.yaml`; one per bet; Ingress+Egress; same-ns + prometheus scrape + kube-system; egress DNS 53 + HTTPS 443; listed in kustomize; parse-only smoke; no cluster; CNI/kubelet-probe warning)
- [x] Kubernetes PodDisruptionBudget for B–F (`deploy/k8s/pdb.yaml`; one per bet; policy/v1; maxUnavailable: 1 so replica=1 can drain; listed in kustomize; Helm pdb.enabled default false; parse-only smoke; no cluster; HA needs replicaCount>=2 + minAvailable 1)
- [x] Kubernetes HorizontalPodAutoscaler for B–F (`deploy/k8s/hpa.yaml`; one per bet; autoscaling/v2; CPU 70% min 1 / max 4; listed in kustomize; needs metrics-server to scale (idle without it); Helm hpa.enabled default false; parse-only smoke; replicaCount stays 1)
- [x] Kubernetes Ingress for B–F (`deploy/k8s/ingress.yaml`; one Ingress; networking.k8s.io/v1; five host rules Prefix `/`; class nginx; listed in kustomize; needs ingress-nginx or similar (idle without it); TLS omitted; Helm ingress.enabled default false; parse-only smoke)
- [x] Kubernetes LimitRange (`deploy/k8s/limitrange.yaml`; one LimitRange; v1; type Container; defaultRequest 50m/64Mi + default 500m/256Mi; listed in kustomize; Helm limitRange.enabled default true; parse-only smoke; does not change explicit Deployment resources)
- [x] Kubernetes ResourceQuota (`deploy/k8s/resourcequota.yaml`; one ResourceQuota; v1; hard pods 24 / requests 2 CPU 2Gi / limits 12 CPU 6Gi / services 10; listed in kustomize; Helm resourceQuota.enabled default false; parse-only smoke; pairs with LimitRange + HPA maxReplicas 4)
- [x] Kubernetes securityContext on B–F Deployments (pod+container; runAsNonRoot; runAsUser 1000 node / 65532 python; drop ALL; readOnlyRootFilesystem + emptyDir /tmp; B/C/F emptyDir /app/data; Helm securityContext.enabled default true; parse-only smoke)
- [x] Grafana dashboard JSON for B–F metrics (`deploy/grafana/oss-cash-lab.json`; Grafana 9/10 import; five rows; real Prom names; parse-only `scripts/check-grafana.sh` on smoke; no live Grafana)
- [x] Prometheus alerting rules for B–F metrics (`deploy/prometheus/rules.yaml` + `deploy/k8s/prometheusrule.yaml`; same groups; real Prom names; parse-only `scripts/check-prometheus-rules.py` on smoke; no Prometheus process; not in kustomize)
- [x] Honest B–F Dockerfiles (`bets/<bet>/Dockerfile` + `.dockerignore`; `node:20-alpine` / `python:3.12-alpine`; EXPOSE CLI ports; CMD `serve --host 0.0.0.0`; parse-only `scripts/check-dockerfiles.sh` on smoke; skip docker build if no docker)
- [x] B–F image HEALTHCHECK (`HEALTHCHECK` → `GET /health` on EXPOSE port via busybox `wget`; interval/timeout; not `/ready`; parse-only `scripts/check-dockerfiles.sh`; A skipped)
- [x] B/C/D/E/F JSON access logs (`serve --log-json` / `LOG_FORMAT=json`; default off; skip /health /ready /metrics; `requestId` matches X-Request-Id; isolated local-mvp B+C; smoke format helper)
- [x] F CORS (`CORS_ORIGINS` / `cors.origins`; default deny; OPTIONS 204/403; GET/POST ACAO; default expose Retry-After + X-Request-Id; isolated local-mvp localhost:3000 vs evil.example)
- [x] F `X-Request-Id` (incoming or generated UUID; echo every response incl 4xx/OPTIONS/429; `requestId` on approvals + audit; CORS allow/expose; local-mvp custom-id proof)
- [x] B `X-Request-Id` (incoming or generated UUID; echo every response; `requestId` on audit JSONL / GET /audit / export / webhooks; local-mvp custom-id proof)
- [x] B `serve --watch` config mtime poll reload (300ms; same path as SIGHUP / POST /admin/reload; logs `regenerated`; local-mvp isolated copy prove)
- [x] B admin tenant API token rotation (`POST /admin/tenants/{id}/rotate` + body alias; grace 60s; `token_rotated` audit; no secret leak; isolated local-mvp grace=0)
- [x] B Streamable HTTP MVP (`POST /mcp` JSON-RPC + `Mcp-Session-Id` / `MCP-Protocol-Version`; GET 405 Allow: POST, DELETE; no SSE; smoke + local-mvp)
- [x] B Streamable HTTP session TTL (default 3600s; `--session-ttl` / `MCP_SESSION_TTL_SEC`; `0` = no expiry; 404 `session_expired`; cap 10000; smoke + isolated `--session-ttl 1`/`0`; stack-demo default)
- [x] B Streamable HTTP session terminate (`DELETE /mcp`; 204 / 400 `session_id_required` / 404 `session_not_found`; GET 405 Allow: POST, DELETE; CORS DELETE; OpenAPI `mcpSessionDelete`; smoke + isolated local-mvp + stack-demo)
- [x] B admin session inventory (`GET /admin/sessions`; admin-only; live sessions; cap 100 newest; no secrets; OpenAPI `adminListSessions`; smoke + isolated local-mvp + stack-demo 401)
- [x] B admin runtime config (`GET /admin/config`; admin-only; redacted TTL/CORS/breaker/rate-limit/session cap; never secrets; OpenAPI `adminGetConfig`; smoke + local-mvp + stack-demo 401)
- [x] B admin single tenant (`GET /admin/tenants/{id}`; admin-only; no secrets; 404 `tenant_not_found`; OpenAPI `adminGetTenant`; smoke + local-mvp + stack-demo 401)
- [x] B admin webhook inventory (`GET /admin/webhooks`; admin-only; redacted id/events/hasUrl/hasSecret; never url/secret; OpenAPI `adminListWebhooks`; smoke + local-mvp + stack-demo 401)
- [x] B HTTP MCP client config example (`examples/mcp/gateway.mcp.json`; `url` `:8787/mcp`; POST-only not SSE; parse-only smoke; no live Cursor)
- [x] B audit webhook HMAC (`webhooks[].secret` → `X-Webhook-Signature: sha256=<hex>` HMAC-SHA256 of raw body; mock receiver optional verify; simple HMAC OSS; key rotation / timestamp replay = paid later)
- [x] B outbound webhook timestamp (`X-Webhook-Timestamp: <unix-seconds>` on every POST; HMAC still body-only; replay window enforcement = paid later)
- [x] B audit webhook 1 retry (5xx/network/timeout → one POST retry after ~50ms; 4xx/success no retry; optional `webhook_retries_total`; exponential backoff / queues = paid)
- [x] C `X-Request-Id` (incoming or generated UUID; echo every response incl 4xx/OPTIONS; `requestId` on POST /v1/runs records + GET /v1/runs/{id} + list rows; CORS allow/expose; local-mvp custom-id proof)
- [x] C run-complete webhook (`--webhook-url` / `AGENT_CI_WEBHOOK_URL`; fire-and-forget POST after done|error; local-mvp mock receiver; OSS 1 retry on 5xx/timeout; exponential backoff / queues / key rotation / timestamp replay = paid later)
- [x] C run-complete webhook HMAC (`--webhook-secret` / `AGENT_CI_WEBHOOK_SECRET` → `X-Webhook-Signature: sha256=<hex>` HMAC-SHA256 of raw body; mock receiver optional verify; simple HMAC OSS; key rotation / timestamp replay = paid later)
- [x] C outbound webhook timestamp (`X-Webhook-Timestamp: <unix-seconds>` on every POST; HMAC still body-only; replay window enforcement = paid later)
- [x] C OpenAPI (`openapi/runner.openapi.json` + `GET /openapi.json`; Bearer + `X-Request-Id`; 202/429/401/404; `/metrics`; outbound `RunCompleteWebhook` + HMAC note; local-mvp asserts)
- [x] C GET /ready readiness (200 `{ok:true, queue}` when POST would enqueue; 503 `{ok:false, reason:queue_full}` + Retry-After when at capacity; `/health` stays 200; isolated local-mvp fill → `/ready` 503, drain → `/ready` 200)
- [x] C Prometheus `GET /metrics` (`agent_ci_queue_depth`, `agent_ci_running`, `agent_ci_runs_completed_total`, `agent_ci_runs_failed_total`; CORS same as other GET; local-mvp curl after a completed run asserts names)
- [x] Dogfood A→C OpenAPI SDK generate (`make dogfood-a-c`, gitignore `sdk/generated/`)
- [x] C `serve --watch` fixtures max-mtime poll (400ms; logs `regenerated`; `/health` `watch.generation`; local-mvp isolated mkdir-suite prove)
- [x] F OpenAPI (`openapi/agent.openapi.json` + `GET /openapi.json`; `/ready` `getReady`; `GET /v1/platforms` `getPlatforms`; `GET /v1/config` `getConfig`; `X-Request-Id`; webhook 401/429; 403 CORS notes; `/metrics`; `/v1/approvals.csv`; `/v1/approvals.md`; local-mvp asserts)
- [x] F GET /ready readiness (always 200 `{ok:true, service}` + same snapshot as `/health`; no circuit/queue; compose stays on `/health`)
- [x] F Prometheus `GET /metrics` (`cn_work_agent_approvals_pending`, `cn_work_agent_approvals_decided_total`, `cn_work_agent_webhooks_total`; CORS same as other GET; local-mvp curl after create/decide asserts names)
- [x] Dogfood A→F OpenAPI SDK generate (`make dogfood-a-f`, gitignore `bets/f-cn-work-agent/sdk/generated/`)
- [x] F approval-decision webhook (`--webhook-url` / `APPROVAL_WEBHOOK_URL`; fire-and-forget POST after decide/expire; local-mvp mock receiver; OSS 1 retry on 5xx/timeout; exponential backoff / queues / key rotation / timestamp replay = paid later)
- [x] F approval-decision webhook HMAC (`--webhook-secret` / `APPROVAL_WEBHOOK_SECRET` → `X-Webhook-Signature: sha256=<hex>` HMAC-SHA256 of raw body; mock receiver optional verify; simple HMAC OSS; key rotation / timestamp replay = paid later)
- [x] F outbound webhook timestamp (`X-Webhook-Timestamp: <unix-seconds>` on every POST; HMAC still body-only; replay window enforcement = paid later)
- [x] F approval-decision webhook 1 retry (5xx/network/timeout → one POST retry after ~50ms; 4xx/success no retry; exponential backoff / queues = paid)
- [x] F `serve --watch` config mtime poll reload (300ms; CORS/TTL/webhook url+secret/rate-limit; env wins if already set; logs `regenerated`; local-mvp isolated copy prove)
- [x] F inbound IM callback HMAC (`callbackSecret` / `FEISHU_CALLBACK_SECRET` → POST `X-Callback-Signature: sha256=<hex>` of raw body; optional `X-Callback-Timestamp` 300s skew; GET decide unsigned for cards; default off; 401 no secret leak; isolated local-mvp)
- [x] F decided-approvals cap (`--approvals-max` / `APPROVALS_MAX` default 2000; `0` = unlimited; drop oldest approved/rejected/expired; pending kept; GET by id 404; smoke + isolated local-mvp `--approvals-max 2`)
- [x] F `GET /v1/platforms` IM inventory (`{id,enabled,hasCallbackSecret}`; no secrets; CORS + X-Request-Id; smoke + local-mvp curl 200 + ids; stack-demo curl 200)
- [x] F `GET /v1/config` redacted runtime config (`approvalTtlSec` / `rateLimit` / `cors.origins` / `approvalsMax` / `webhooks.hasUrl|hasSecret` / platforms; public GET, no admin token; never secrets; CORS + X-Request-Id; smoke + local-mvp curl 200 + OpenAPI; stack-demo curl 200)
- [x] F `GET /v1/approvals?status=` (`pending`/`approved`/`rejected`/`expired`; CSV/MD/HTML share helper; unknown/empty → 200 empty; omit unfiltered; OpenAPI enum; smoke + local-mvp + stack-demo)

- [x] E OpenAPI (`openapi/cost.openapi.json` + `GET /openapi.json`; `/v1/costs.csv`; `/v1/budgets` `getBudgets`; `/v1/models` `getModels`; `/v1/config` `getConfig`; `/v1/spans` `listSpans`; `/v1/tenants` `listTenants`; `POST /v1/traces`; 403 CORS notes; local-mvp asserts)
- [x] E Prometheus `GET /metrics` (`otel_ai_cost_total_usd`, `otel_ai_cost_by_model_usd{model}`, `otel_ai_cost_span_count`; CORS same as other GET; local-mvp asserts names)
- [x] Dogfood A→E OpenAPI SDK generate (`make dogfood-a-e`, gitignore `bets/e-otel-ai-cost/sdk/generated/`)

## Local portfolio stack demo

- [x] `docker-compose.yml` + Dockerfiles (B gateway / mock-upstream / C serve / D serve / E serve / F serve; alpine bases + EXPOSE ports + `serve --host 0.0.0.0`; `make check-dockerfiles` parse-only)
- [x] `make stack-demo` → `scripts/local-stack.sh` (no Docker)
- [x] `scripts/compose-smoke.sh` (compose or skip)
- [x] `docs/stack-demo.md`（中文）
- [x] Minimal k8s manifests (`deploy/k8s/` B/C/D/E/F Deployment+Service; placeholder images not published; `/health` + `/ready` probes + 10s grace; parse-only `scripts/check-k8s.sh` on `make smoke`; no cluster)
- [x] Thin Helm chart (`deploy/helm/oss-cash-lab/`; B–F HTTP; `templates/NOTES.txt` port-forward + /health; `helm template` if helm on PATH else parse-only; not the default apply path)
- [x] Prometheus Operator ServiceMonitors (`deploy/k8s/servicemonitor.yaml`; B–F `/metrics`; CRDs `monitoring.coreos.com/v1` documented, not applied in smoke)
- [x] Kubernetes NetworkPolicy (`deploy/k8s/networkpolicy.yaml`; B–F; Ingress+Egress; same-ns + prometheus + kube-system; egress 53/443; in kustomize; parse-only smoke; CNI must support NetworkPolicy)
- [x] Kubernetes PodDisruptionBudget (`deploy/k8s/pdb.yaml`; B–F; policy/v1; maxUnavailable: 1; in kustomize; Helm pdb.enabled default false; parse-only smoke; replica=1 drain vs minAvailable trap)
- [x] Kubernetes HorizontalPodAutoscaler (`deploy/k8s/hpa.yaml`; B–F; autoscaling/v2; CPU 70% min 1 / max 4; in kustomize; needs metrics-server; Helm hpa.enabled default false; parse-only smoke; replica=1 unchanged without metrics)
- [x] Kubernetes Ingress (`deploy/k8s/ingress.yaml`; one Ingress; five hosts Prefix `/`; class nginx; in kustomize; needs ingress controller; TLS omitted; Helm ingress.enabled default false; parse-only smoke)
- [x] Kubernetes LimitRange (`deploy/k8s/limitrange.yaml`; one LimitRange; v1; type Container; defaultRequest 50m/64Mi; in kustomize; Helm limitRange.enabled default true; parse-only smoke; does not change explicit Deployment resources)
- [x] Kubernetes ResourceQuota (`deploy/k8s/resourcequota.yaml`; one ResourceQuota; v1; hard pods 24 / requests 2 CPU 2Gi / limits 12 CPU 6Gi / services 10; in kustomize; Helm resourceQuota.enabled default false; parse-only smoke; pairs with LimitRange + HPA max 4)
- [x] Kubernetes securityContext (`deploy/k8s/` B–F Deployments; pod+container; runAsNonRoot; runAsUser 1000 node / 65532 python; drop ALL; readOnlyRootFilesystem + emptyDir /tmp; Helm securityContext.enabled default true; parse-only smoke)
- [x] Grafana dashboard JSON (`deploy/grafana/oss-cash-lab.json`; Grafana 9/10; B–F rows; `${DS_PROMETHEUS}`; parse-only smoke; no live Grafana)
- [x] Prometheus alerting rules (`deploy/prometheus/rules.yaml` + `deploy/k8s/prometheusrule.yaml`; PrometheusRule CRD after Operator CRDs; parse-only smoke; no Prometheus)
- [x] Honest Dockerfiles for those images (`docker build -t ghcr.io/wozqhl/<bet>:dev bets/<bet>`; parse-only `scripts/check-dockerfiles.sh`; skip build if no docker)
- [x] Image HEALTHCHECK on B–F Dockerfiles (`GET /health` on EXPOSE port via busybox `wget`; interval/timeout; not `/ready`; parse-only `scripts/check-dockerfiles.sh`; A skipped)
- [x] Copy-paste GitHub Actions examples (`examples/github-actions/` A OpenAPI drift + C JUnit + run-vs-run Markdown diff + D SARIF + E GHA annotations; parse-only `scripts/check-gha-examples.sh` on `make smoke`; not live `.github/workflows/`)
- [x] Copy-paste MCP client config for B gateway (`examples/mcp/gateway.mcp.json`; Cursor/Claude HTTP `url` → `:8787/mcp`; POST-only not SSE; parse-only `scripts/check-mcp-examples.sh` on `make smoke`; no live Cursor)
- [x] OSS hygiene NOTICE + `.editorconfig` (+ `.gitattributes` LF) + `SECURITY.md` + `CODE_OF_CONDUCT.md`; Apache-2.0 already in LICENSE; smoke `scripts/check-oss-hygiene.sh` (no restyle)
- [x] SECURITY.md vulnerability disclosure (中文为主; GitHub Security Advisories when published under wozqhl; local-mvp 0.1.x only; no invented email; smoke hygiene assert)
- [x] CODE_OF_CONDUCT.md (Contributor Covenant 2.1; 中文为主 + short EN; pledge / standards / scope / warning→ban; A–F portfolio; no invented email — private maintainer contact, no public issue for harassment; smoke hygiene assert)

