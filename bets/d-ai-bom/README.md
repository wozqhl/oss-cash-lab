# D · ai-bom

> AI-BOM scanner (models / tools / lineage) · **Status: local-mvp** · Phase 2 · [CHANGELOG](./CHANGELOG.md) · [ROADMAP](./ROADMAP.md) · [CRA notes](./docs/cra.md)

## Thesis / 立意

Software SBOM must extend to models, prompts, and MCP tool dependencies for compliance and inventory.

把模型/提示词/MCP 依赖做成可扫描的 AI-BOM。

## Who pays / 谁付钱

- Security compliance / procurement
- 安全合规 / 采购

## OSS vs Paid

| OSS | Paid (Pro wedge) |
|-----|------------------|
| Directory scan + CycloneDX-like JSON BOM + **CycloneDX 1.7 JSON/XML / SPDX 2.3 JSON/XML / SPDX 3.0.1 JSON / SARIF 2.1.0 / Markdown summary / GHA annotations / HTML summary** (`--format`, `GET /v1/bom?format=`) | Policy packs, CI `--strict` gates, inventory DB |
| Built-in pickle heuristic | Managed packs (forbidden + required disclosures), SSO |
| `--evidence` DRAFT markdown sketch | Signed auditor packs, continuous inventory |
| `--sarif` / `--format sarif` / `GET /v1/bom?format=sarif` SARIF 2.1.0 for code scanning | Managed alert routing / inventory DB |
| `--format gha` / `GET /v1/bom?format=gha` GitHub Actions `::error`/`::notice` log annotations | Managed alert routing / inventory DB |
| `--format html` / `GET /v1/bom?format=html` self-contained HTML BOM summary (no CDN; policy hits red) | Hosted inventory dashboard |
| SPDX license fields on package components (`package.json` / `pyproject` / `requirements.txt`) | License inventory DB / enrichment |
| Policy `forbiddenLicenseIds` (GPL/AGPL/SSPL) + `--strict` / `--gate-licenses` | Managed license allow/deny packs |
| Local advisory fixture match (`--advisories` + `--gate-vulns`; `ADV-FIXTURE-*`; offline) + `convert-advisories --from-osv` | Hosted OSV/GHSA feed / NVD completeness |
| `.aibomignore` / `--ignore` path filters | Managed path policies / inventory scopes |
| `.aibom-exceptions.json` / `--exceptions` license waivers (reason + optional expiry) | Managed exception workflow / approval trail |
| Local `serve` HTTP (`/health` `/ready` `/bom.json` `/v1/bom?format=json\|cyclonedx\|cyclonedx-xml\|spdx\|spdx-xml\|spdx3\|sarif\|md\|gha\|html` `/v1/bom.xml` `/v1/bom.spdx.xml` `/v1/bom.sarif` `/v1/bom.md` `/v1/bom.gha.txt` `/v1/bom.html` **`/v1/policy`** **`/v1/config`** **`/v1/components`** **`/v1/exceptions`** `/evidence.md` `/` `/openapi.json` `/metrics`; optional `--cors-origins` / `AI_BOM_CORS_ORIGINS`; HTTP rate-limit `--rate-limit` / `RATE_LIMIT_PER_MINUTE`; `X-Request-Id` echo; optional `--watch` dir mtime poll rescan) | **Hosted inventory** / fleet dashboard |
| OpenAPI 3 (`openapi/bom.openapi.json`, `GET /openapi.json`; `X-Request-Id`) + Prometheus `GET /metrics` + A dogfood SDK stubs | Hosted inventory APIs / signed BOM feeds |
| Policy-hit webhook (`scan --webhook-url` / `AI_BOM_WEBHOOK_URL`; fire-and-forget, **1 retry** on 5xx/timeout) + **simple HMAC-SHA256** (`--webhook-secret` / `AI_BOM_WEBHOOK_SECRET`) | **Webhook exponential backoff / queues** / **key rotation / timestamp replay protection** / reliable delivery |

**OSS one-liner:** scan a repo for models/prompts/MCP into a lite BOM + fire-and-forget policy-hit webhook + simple HMAC + 1 retry.  
**Paid one-liner:** policy packs + compliance evidence export + **hosted inventory** for auditors/CI gates; webhook exponential backoff / queues / key rotation / timestamp replay.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Scan OK (no `--strict` violations) |
| 1 | `--strict`: forbidden hits, disclosure gaps, and/or forbidden licenses; `--gate-licenses`: forbidden licenses only; `--gate-vulns`: local advisory fixture hits |
| 2 | Usage / IO / policy parse error |

## 2-week MVP checklist / 2周MVP清单

- [x] Scan dir for model IDs, prompts, MCP deps
- [x] CycloneDX-like JSON (lite schema)
- [x] CycloneDX 1.7 + SPDX 2.3 JSON export (`scan --format cyclonedx|spdx|json`; `GET /v1/bom?format=`; default json unchanged)
- [x] SPDX 3.0.1 JSON export (`scan --format spdx3`; `GET /v1/bom?format=spdx3`; compact `spdxId`/`name`/`creationInfo.specVersion=3.0.1` + packages/licenses + `software_File`/`contains` when a hashed file was scanned + `ai_AIPackage`/`profileConformance` `ai` only when model path+sha256 or model-card fields were observed; SPDX 2.3 `spdx`/`spdx-xml` unchanged)
- [x] CycloneDX 1.7 XML export (`scan --format cyclonedx-xml`; `GET /v1/bom?format=cyclonedx-xml` / `GET /v1/bom.xml`; same component/license/policy-hit model; `cyclonedx` stays JSON)
- [x] CycloneDX 1.7 ML-BOM fields from existing scan data (`machine-learning-model` + `modelCard` format/path; prompts as `data`; licenses; no invented schema)
- [x] `--gate-licenses` CI license-policy gate (exit 1 on `forbiddenLicenseIds` only) + `examples/cra-fixtures/license-pass` / `license-fail`
- [x] `--advisories` / `--gate-vulns` offline advisory-match gate (Article 14 inventory+match) + `convert-advisories --from-osv` + `examples/advisories/sample.json` / `clean.json` / `osv-sample.json`
- [x] CRA orientation [`docs/cra.md`](./docs/cra.md) (Article 14 11 Sep 2026 reporting vs Dec 2027 SBOM; no certification claim)
- [x] Local evidence pack (`evidence-pack --dir DIR --out OUTDIR`) — CycloneDX 1.7 + SPDX 3.0.1 + MANIFEST + `pack.json` (license/advisory gate codes + window clock); not a CRA declaration
- [x] CRA window clock (`pack.json` `clock` / `--as-of`) — days-until / days-overdue vs 2026-09-11 and 2027-12-11 from observed `--gate-vulns` hits; calendar/evidence helper, **not** a CRA compliance certificate / 日历/证据辅助，**不是** CRA 合格证书
- [x] SPDX 2.3 XML export (`scan --format spdx-xml`; `GET /v1/bom?format=spdx-xml` / `GET /v1/bom.spdx.xml`; same packages/`licenseConcluded` as JSON; `spdx` stays JSON)
- [x] Markdown BOM summary (`scan --format md`; `GET /v1/bom?format=md` / `GET /v1/bom.md`; `text/markdown`; human/Slack; not an SBOM spec)
- [x] GitHub Actions workflow-command annotations (`scan --format gha`; `GET /v1/bom?format=gha` / `GET /v1/bom.gha.txt`; `text/plain`; `::error` / waived `::notice`; clean empty)
- [x] HTML BOM summary (`scan --format html`; `GET /v1/bom?format=html` / `GET /v1/bom.html`; `text/html`; self-contained no CDN; policy hits / forbidden licenses red; empty heading+zeros)
- [x] `GET /v1/policy` active license/policy gate JSON (`forbiddenLicenseIds`, `forbiddenPatterns` ids, `exceptionsCount`, `ignoreFile`; 200 empty lists if no policy file; no file dump / secrets)
- [x] `GET /v1/config` redacted runtime knobs (`ok`, `rateLimit.perMinute`, `cors.origins`, `watch`, `scanPathBase` basename only, `hasPolicyFile`, `webhooks.hasUrl`/`hasSecret`; never webhook URL/secret, full policy JSON, or exception contents)
- [x] `GET /v1/components` lightweight inventory (`{ok, count, components:[{name, version, license, path}]}`; path relative/basename only; empty 200; optional `?license=`; cap 500 + `truncated`; CORS + X-Request-Id; OpenAPI `listComponents`)
- [x] `GET /v1/exceptions` redacted waiver inventory (`{ok, count, exceptions:[{component, license, expiresAt, expired}]}`; count=full; cap 500 + `truncated`; empty 200; optional `?expired=`; no sidecar dump / secrets; OpenAPI `listExceptions`)
- [x] HTTP SARIF 2.1.0 (`GET /v1/bom?format=sarif` / `GET /v1/bom.sarif`; same `to_sarif` as CLI `--sarif`; `--format sarif` alias)
- [x] `ai-bom scan ./path`
- [x] Policy pack `policies/default.json` + `--strict`
- [x] Compliance `--evidence` DRAFT (EN/中文)
- [x] `--sarif` SARIF 2.1.0 (forbidden hits + disclosure notes)
- [x] SPDX / CycloneDX `licenses[]` from `package.json` / `pyproject.toml` / `requirements.txt`
- [x] Policy `forbiddenLicenseIds` (GPL-3.0 / AGPL-3.0 / SSPL-1.0 + variants) → policy hit; `--strict` exits 1
- [x] `.aibomignore` + CLI `--ignore` (skip vendor/deps paths)
- [x] License exceptions sidecar `.aibom-exceptions.json` / `--exceptions` (component+license waiver, reason, optional expiry)
- [x] Demo fixture + local-mvp
- [x] Local `serve` HTTP snapshot (`--port 8793`; hosted inventory = paid)
- [x] `GET /ready` always 200 `{ok:true, service}` + same snapshot as `/health` (no circuit/queue; Compose stays on `/health`)
- [x] Serve CORS (`--cors-origins` CSV / `AI_BOM_CORS_ORIGINS`; default deny; OPTIONS 204/403 `cors_denied`; GET ACAO; allow/expose `Retry-After` + `X-Request-Id`)
- [x] HTTP rate limit (`--rate-limit` / `RATE_LIMIT_PER_MINUTE` default 120; IP sliding window; 429 + `Retry-After`; skip `/health` `/ready` `/metrics`)
- [x] `X-Request-Id` (incoming or generated UUID; echo every response incl 4xx/OPTIONS)
- [x] OpenAPI 3 (`openapi/bom.openapi.json` + `GET /openapi.json`; `/ready` `getReady`; 403 CORS notes; `X-Request-Id`)
- [x] Prometheus `GET /metrics` (`ai_bom_component_count`, `ai_bom_policy_hits`, `ai_bom_forbidden_licenses`; CORS same as other GET)
- [x] Policy-hit webhook (`scan --webhook-url` / `AI_BOM_WEBHOOK_URL`; POST `{ok:false,policyHits,forbiddenLicenses,summary}` on forbidden hits / forbidden licenses; OSS 1 retry on 5xx/timeout; exponential backoff / queues / key rotation / timestamp replay = paid later)
- [x] Policy-hit webhook HMAC (`--webhook-secret` / `AI_BOM_WEBHOOK_SECRET` → `X-Webhook-Signature: sha256=<hex>` HMAC-SHA256 of raw body; mock receiver optional `--secret` verify; simple HMAC OSS; key rotation / timestamp replay = paid later)
- [x] Policy-hit webhook timestamp (`X-Webhook-Timestamp: <unix-seconds>` on every POST; HMAC still body-only; replay window enforcement = paid later)
- [x] Serve `--watch` (poll `--path` dir max mtime ~500ms; rescan snapshot for `/bom.json` `/health` `/metrics` `/`; local-mvp isolated temp-dir prove)

## Quick start

```bash
PYTHONPATH=src python3 -m ai_bom smoke
PYTHONPATH=src python3 -m ai_bom scan examples/sample-app \
  --policy policies/default.json \
  --out out/bom.json \
  --evidence out/evidence.md \
  --sarif out/bom.sarif
# enterprise ingest formats (json remains default internal model):
PYTHONPATH=src python3 -m ai_bom scan examples/sample-app --format cyclonedx --out out/bom.cdx.json
PYTHONPATH=src python3 -m ai_bom scan examples/sample-app --format cyclonedx-xml --out out/bom.cdx.xml
PYTHONPATH=src python3 -m ai_bom scan examples/sample-app --format spdx --out out/bom.spdx.json
PYTHONPATH=src python3 -m ai_bom scan examples/sample-app --format spdx3 --out out/bom.spdx3.json
PYTHONPATH=src python3 -m ai_bom scan examples/sample-app --format spdx-xml --out out/bom.spdx.xml
PYTHONPATH=src python3 -m ai_bom scan examples/sample-app --format sarif --out out/bom.format.sarif
PYTHONPATH=src python3 -m ai_bom scan examples/sample-app --format md --out out/bom.md
PYTHONPATH=src python3 -m ai_bom scan examples/sample-app --format html --out out/bom.html
# CI gate (all policy hits; sample-app fails on pickle):
PYTHONPATH=src python3 -m ai_bom scan examples/sample-app --policy policies/default.json --strict; echo exit=$?
# CI license-only gate (sample-app MIT → 0; planted GPL fixture → 1):
PYTHONPATH=src python3 -m ai_bom scan examples/sample-app --policy policies/default.json --gate-licenses; echo exit=$?
PYTHONPATH=src python3 -m ai_bom scan examples/cra-fixtures/license-pass --policy policies/default.json --gate-licenses; echo exit=$?
PYTHONPATH=src python3 -m ai_bom scan examples/cra-fixtures/license-fail --policy policies/default.json --gate-licenses; echo exit=$?
# Article 14 inventory+match (local fixture; not NVD — planted hit → 1, clean file → 0):
PYTHONPATH=src python3 -m ai_bom scan examples/sample-app --advisories examples/advisories/sample.json --gate-vulns; echo exit=$?
PYTHONPATH=src python3 -m ai_bom scan examples/sample-app --advisories examples/advisories/clean.json --gate-vulns; echo exit=$?
# Offline OSV/GHSA → same fixture schema (no fetch):
PYTHONPATH=src python3 -m ai_bom convert-advisories --from-osv examples/advisories/osv-sample.json --out out/from-osv.json
# Article 14 evidence pack (inventory+match + calendar clock; not a CRA certificate):
PYTHONPATH=src python3 -m ai_bom evidence-pack --dir examples/sample-app --out out/cra-pack
# optional: --zip out/cra-pack.zip  --as-of 2026-08-26
# pack.json clock is a calendar/evidence helper, not a CRA compliance certificate
# pack.json 的 clock 是日历/证据辅助，不是 CRA 合格证书
PYTHONPATH=src python3 -m ai_bom scan examples/sample-app --advisories out/from-osv.json --gate-vulns; echo exit=$?
PYTHONPATH=src python3 -m ai_bom scan examples/cra-fixtures/license-pass --advisories out/from-osv.json --gate-vulns; echo exit=$?
# active license/policy gate (ids/counts only):
PYTHONPATH=src python3 -m ai_bom policy examples/sample-app --policy policies/default.json
# optional policy-hit webhook (OSS 1 retry; exponential backoff / queues / key rotation / timestamp replay = paid later):
PYTHONPATH=src python3 -m ai_bom scan examples/sample-app --policy policies/default.json \
  --webhook-url http://127.0.0.1:8816/hook   # fire-and-forget POST on forbidden hits / forbidden licenses
# or: AI_BOM_WEBHOOK_URL=http://127.0.0.1:8816/hook
# optional HMAC (OSS): --webhook-secret whsec_local_mvp  or  AI_BOM_WEBHOOK_SECRET
#   → X-Webhook-Signature: sha256=<hex> of the raw JSON body
# Skip vendor/deps (also reads scan-root .aibomignore):
PYTHONPATH=src python3 -m ai_bom scan . --ignore "node_modules,dist,.git"
# License waivers (also reads scan-root .aibom-exceptions.json; env AI_BOM_EXCEPTIONS):
PYTHONPATH=src python3 -m ai_bom scan . --policy policies/default.json --exceptions ./waivers.json --strict
# Local BOM HTTP (hosted inventory = paid later):
PYTHONPATH=src python3 -m ai_bom serve --path examples/sample-app --port 8793 --host 127.0.0.1
# optional: --watch  poll --path dir max mtime (~500ms) and rescan snapshot (/bom.json, /health, /metrics, /)
# optional CORS: --cors-origins http://localhost:3000  or  AI_BOM_CORS_ORIGINS
#   empty/omit = deny extra CORS (no ACAO; OPTIONS 404)
#   explicit list: OPTIONS allowed Origin → 204 + ACAO; unlisted (e.g. http://evil.example) → 403 cors_denied
#   matching GET includes Access-Control-Allow-Origin (`*` allowed)
#   default allow/expose headers include Retry-After + X-Request-Id
# optional HTTP rate limit: --rate-limit 120  or  RATE_LIMIT_PER_MINUTE / RATE_LIMIT_RPM (default 120; 0 = unlimited)
#   per client IP (X-Forwarded-For first hop); exceed → 429 {ok:false, reason:rate_limited} + Retry-After
#   /health /ready /metrics are not limited
# optional: curl -H 'X-Request-Id: my-id' (echoed on every response)
# optional JSON access logs: --log-json or LOG_FORMAT=json (default off; skips /health /ready /metrics)
# curl http://127.0.0.1:8793/health
# curl http://127.0.0.1:8793/ready
# curl http://127.0.0.1:8793/bom.json
# curl 'http://127.0.0.1:8793/v1/bom?format=cyclonedx'
# curl 'http://127.0.0.1:8793/v1/bom?format=cyclonedx-xml'
# curl http://127.0.0.1:8793/v1/bom.xml
# curl 'http://127.0.0.1:8793/v1/bom?format=spdx'
# curl 'http://127.0.0.1:8793/v1/bom?format=spdx3'
# curl 'http://127.0.0.1:8793/v1/bom?format=spdx-xml'
# curl http://127.0.0.1:8793/v1/bom.spdx.xml
# curl 'http://127.0.0.1:8793/v1/bom?format=sarif'
# curl http://127.0.0.1:8793/v1/bom.sarif
# curl 'http://127.0.0.1:8793/v1/bom?format=md'
# curl http://127.0.0.1:8793/v1/bom.md
# curl 'http://127.0.0.1:8793/v1/bom?format=gha'
# curl http://127.0.0.1:8793/v1/bom.gha.txt
# curl 'http://127.0.0.1:8793/v1/bom?format=html'
# curl http://127.0.0.1:8793/v1/bom.html
# curl http://127.0.0.1:8793/v1/policy
# curl http://127.0.0.1:8793/v1/config
# curl http://127.0.0.1:8793/v1/components
# curl 'http://127.0.0.1:8793/v1/components?license=MIT'
# curl http://127.0.0.1:8793/v1/exceptions
# curl 'http://127.0.0.1:8793/v1/exceptions?expired=false'
# curl http://127.0.0.1:8793/evidence.md
# curl http://127.0.0.1:8793/
# curl http://127.0.0.1:8793/openapi.json
# curl http://127.0.0.1:8793/metrics
# portfolio stack: make stack-demo (port 8793; default deny CORS so curls unchanged)
```


## Local HTTP serve / 本地 BOM 服务

`ai-bom serve --path examples/sample-app --port 8793 --host 127.0.0.1` scans once at start (stdlib `http.server`) and serves a snapshot (optional `--watch` rescans that snapshot when scan-root max mtime changes):

| Path | Body |
|------|------|
| `GET /health` | `{ok, service: ai-bom, componentCount, policyHits, licenses}` |
| `GET /ready` | **200** `{ok:true, service}` plus the same snapshot as `/health` when healthy; **503** `{ok:false, reason:"shutting_down"}` on SIGTERM/SIGINT. Compose/stack-demo healthchecks stay on `/health`. |
| `GET /bom.json` | Internal AI-BOM JSON (CycloneDX-like + `summary`; unchanged) |
| `GET /v1/bom?format=json\|cyclonedx\|cyclonedx-xml\|spdx\|spdx-xml\|spdx3\|sarif\|md\|gha\|html` | Default **json** = same as `/bom.json`. `cyclonedx` = CycloneDX 1.7 JSON (`bomFormat`+`specVersion`). `cyclonedx-xml` = CycloneDX 1.7 XML (`bom` xmlns 1.7; alias `cdx-xml`). `spdx` = SPDX 2.3 JSON (`spdxVersion`+`packages`). `spdx-xml` = SPDX 2.3 XML (`SpdxDocument` + `spdxVersion` SPDX-2.3; alias `spdxxml`). `spdx3` = SPDX 3.0.1 JSON (`creationInfo.specVersion` 3.0.1 + `element` packages/licenses; alias `spdx-3`). `sarif` = SARIF 2.1.0 (`version`+`runs`; same as CLI `--sarif`). `md` = human/Slack Markdown summary (`# AI-BOM` + counts; alias `markdown`). `gha` = GitHub Actions workflow commands (`::error` / waived `::notice`; alias `annotations`; clean → empty). `html` = self-contained HTML BOM summary (`text/html`; component count + licenses + policy hits red; no CDN). Unknown format → 400. |
| `GET /v1/bom.xml` | Alias for `?format=cyclonedx-xml` (`application/vnd.cyclonedx+xml`). |
| `GET /v1/bom.spdx.xml` | Alias for `?format=spdx-xml` (`application/spdx+xml`). |
| `GET /v1/bom.sarif` | Alias for `?format=sarif` (`application/sarif+json`). |
| `GET /v1/bom.md` | Alias for `?format=md` (`text/markdown`; not an SBOM spec). |
| `GET /v1/bom.gha.txt` | Alias for `?format=gha` (`text/plain`; `::error` / waived `::notice`; clean → empty 200). |
| `GET /v1/bom.html` | Alias for `?format=html` (`text/html`; self-contained; policy hits red; empty heading still 200). |
| `GET /v1/policy` | Active license/policy gate: `{ok, forbiddenLicenseIds, forbiddenPatterns, exceptionsCount, ignoreFile}`. **200** even if no policy file (empty lists). Pattern **ids** only; exception **count** only; never dumps file contents, regexes, reasons, or secrets. |
| `GET /v1/config` | Redacted runtime knobs: `{ok, rateLimit.perMinute, cors.origins, watch, scanPathBase, hasPolicyFile, webhooks.hasUrl/hasSecret}`. **Never** webhook URL/secret, full policy JSON (that is `/v1/policy`), exception contents, or a full host scan path (`scanPathBase` is basename only). CORS + `X-Request-Id`. |
| `GET /v1/components` | Lightweight inventory from the last scan: `{ok, count, components:[{name, version, license, path}]}`. `path` is relative to the scan root or a basename — **never** an absolute host path. Empty scan → **200** `{ok:true, count:0, components:[]}`. Optional `?license=` (case-insensitive exact). Cap **500** with `truncated:true`. Not CycloneDX/SPDX. CORS + `X-Request-Id`. |
| `GET /v1/exceptions` | Redacted license-exception / waiver inventory: `{ok, count, exceptions:[{component, license, expiresAt, expired}]}`. `count` is the full waiver count; array cap **500** original file order (`truncated:true` when more). Empty / no sidecar → **200** `{ok:true, count:0, exceptions:[]}`. Optional `?expired=true|false` (unknown → empty list 200). Never sidecar path, full policy JSON, webhook URL/secret, or raw file dump. CORS + `X-Request-Id`. |
| `GET /evidence.md` | Bilingual DRAFT evidence markdown |
| `GET /` | HTML summary: component count, license summary, policy hits (same formatter as `/v1/bom.html`) |
| `GET /openapi.json` | File-backed OpenAPI 3 (`openapi/bom.openapi.json`) |
| `GET /metrics` | Prometheus text: gauges `ai_bom_component_count`, `ai_bom_policy_hits`, `ai_bom_forbidden_licenses` |

`GET /openapi.json` serves the file-backed OpenAPI 3 document ([`openapi/bom.openapi.json`](./openapi/bom.openapi.json)): `/health`, **`/ready`** (`getReady`), `/bom.json`, **`/v1/bom`** (`getBomV1`, `?format=` including `sarif`, `cyclonedx-xml`, `spdx-xml`, `spdx3`, `md`, `gha`, and `html`), **`/v1/bom.xml`** (`getBomXml`), **`/v1/bom.spdx.xml`** (`getBomSpdxXml`), **`/v1/bom.sarif`** (`getBomSarif`), **`/v1/bom.md`** (`getBomMd`), **`/v1/bom.gha.txt`** (`getBomGha`), **`/v1/bom.html`** (`getBomHtml`), **`/v1/policy`** (`getPolicy`), **`/v1/config`** (`getConfig`), **`/v1/components`** (`listComponents`), **`/v1/exceptions`** (`listExceptions`), `/evidence.md`, `/`, `/metrics`, plus `X-Request-Id` and **403** CORS notes. Portfolio dogfood: `make dogfood-a-d` (A generates TS/Python/Go clients under `sdk/generated/`, gitignored).

`--host` defaults to `127.0.0.1` (Compose uses `0.0.0.0`). Optional `--policy` / `--ignore` / `--exceptions` match `scan` (scan-root `.aibom-exceptions.json` auto-detected). Optional **`--watch`**: poll the `--path` directory max mtime (simple walk) every **500ms** and rescan the snapshot used by `GET /bom.json`, `GET /v1/bom`, `GET /v1/components`, `GET /health`, `GET /metrics`, `GET /` (and `GET /ready`). `GET /openapi.json` stays file-backed (not rebuilt from the scan). Scan errors keep the previous snapshot. Main serve / stack-demo omit `--watch` (one-shot snapshot). local-mvp isolated prove: temp dir → curl `componentCount` → add a file → wait for `regenerated` → higher count → kill (must not hang). Optional CORS: `--cors-origins` CSV or env `AI_BOM_CORS_ORIGINS` (`*` allowed). Empty/omit = **deny extra CORS** (no ACAO; OPTIONS 404). Explicit list: allowed Origin OPTIONS → **204** + ACAO; unlisted (e.g. `http://evil.example`) → **403** `cors_denied`. Matching GET includes `Access-Control-Allow-Origin`. Default allow/expose headers include **`Retry-After`** and **`X-Request-Id`** (GET/OPTIONS ACEH). local-mvp isolated prove uses `http://localhost:3000`; main serve / stack-demo default deny.

### HTTP rate limit

`serve --rate-limit N` or env **`RATE_LIMIT_PER_MINUTE`** (alias **`RATE_LIMIT_RPM`**). Default **120**/min per client IP (`X-Forwarded-For` first hop, else socket). In-memory sliding window (stdlib). Exceed → **429** `{ok:false, reason:"rate_limited"}` + header **`Retry-After`**. **`GET /health`**, **`GET /ready`**, **`GET /metrics`** are not limited (k8s probes / Prometheus). `0` disables. CLI flag wins over env. local-mvp isolated prove uses `--rate-limit 2` (third `/bom.json` is 429; `/health` stays 200). Main serve / stack-demo keep the generous default so curls never 429.

### X-Request-Id

Optional correlation header. Echoed on **every** response (including 4xx / OPTIONS). If omitted/empty, the server generates a UUID (max 128 chars; CR/LF stripped). CORS allow/expose includes `X-Request-Id`. local-mvp sends a custom id on `/health`, `/openapi.json`, and `/metrics` and asserts the response header.

```bash
curl -sD - http://127.0.0.1:8793/health -H 'X-Request-Id: mvp-health-rid-d1'
# → X-Request-Id: mvp-health-rid-d1
```

**Hosted inventory = paid later**; this local serve is OSS.

Container (k8s placeholder; images not published; skip if no Docker): `docker build -t ghcr.io/wozqhl/d-ai-bom:dev bets/d-ai-bom` (`python:3.12-alpine`, EXPOSE **8793**, `python -m ai_bom serve --host 0.0.0.0`).

## Ignore paths / `.aibomignore`

Skip noisy trees while scanning (venv, vendor, build output):

1. **Scan-root `.aibomignore`** — gitignore-like lines (`#` comments, blank lines ignored):
   - **exact prefix**: `vendor/` skips `vendor/**`
   - **`*` glob / suffix**: `*.pyc` matches basename or relative path
   - **directory names**: `node_modules` matches any path segment of that name
2. **CLI** `--ignore "node_modules,dist,.git"` — comma-separated patterns, merged with `.aibomignore`

Ignored files are omitted from components and policy hits (local-mvp proves a pickle under `vendor/` is silent while a root pickle still flags).

## License exceptions / waivers

Enterprises rarely have a pure allow/deny list. Per-repo **named component + license** waivers live in a sidecar so the org policy pack stays the standard:

```json
{
  "exceptions": [
    {"component": "leftpad", "license": "GPL-3.0", "reason": "vendor approved 2026-Q3", "expires": "2026-12-31"}
  ]
}
```

1. **Scan-root `.aibom-exceptions.json`** — auto-detected like `.aibomignore`
2. **CLI** `--exceptions PATH` or env `AI_BOM_EXCEPTIONS` — extra file, merged (CLI/env first on match). Empty flag disables the extra file; sidecar still applies.
3. Match **component name** (exact, or glob when the pattern has `*`/`?`) **AND** SPDX license id
4. Required fields: `component`, `license`, `reason`. Optional `expires` (`YYYY-MM-DD`, UTC date). Missing/invalid entries are **skipped with a warning** (scan does not crash). Bad JSON → warning + empty exceptions (HTTP **does not 500**)
5. **Expired** (`expires` < today UTC) → **not** applied; the hit still counts; `summary.expiredExceptions[]`
6. **Applied** → component is **not** a forbidden-license / `--strict` failure. `summary.waived: [{component, license, reason}]`. Scan exit **0** if only waived hits remain
7. CycloneDX `properties` `aibom:waived`; SARIF `level: note` + `suppressions` (`kind: external`)
8. HTTP: scan-root sidecar applies automatically. Query `?exceptions=` / `?exceptions=skip` reconstructs un-waived hits (no arbitrary path from query)

This does **not** replace `.aibomignore` (path skips). Reasons are recorded in the BOM; do not put secrets in the file.

## Licenses / SPDX

Manifest scans attach CycloneDX-like `licenses` on components:

| Source | Behavior |
|--------|----------|
| `package.json` `license` (string or `{type}`) | SPDX `id` when it looks like an id (e.g. `MIT`); `expression` for `AND`/`OR`/`WITH`; else `name` |
| `pyproject.toml` `[project].license` / `license-expression` | Same mapping (`license = { text = "Apache-2.0" }` → id) |
| `requirements.txt` lines | `{"license": {"id": "NOASSERTION"}}` (no registry lookup) |
| Other components (models / prompts / MCP) | `{"license": {"name": "UNKNOWN"}}` |

`summary.licenses` counts ids/names; `--evidence` includes a **License summary / 许可证摘要** section. Sample app ships `package.json` with `"license": "MIT"` so `out/bom.json` contains MIT.

## CycloneDX 1.7 + SPDX 2.3 / SPDX 3.0.1 export

The scan result is still the **internal AI-BOM JSON** (default `--format json` / `GET /v1/bom` / `GET /bom.json`): CycloneDX-like `bomFormat` + `specVersion` plus custom `summary` (policy hits, license counts). Compliance teams ingest standard documents, so exporters map that model without new deps:

| Format | CLI | HTTP | jq |
|--------|-----|------|----|
| Internal JSON (default) | `scan --format json` (or omit) | `GET /v1/bom` / `GET /v1/bom?format=json` / `GET /bom.json` | `.summary` |
| CycloneDX 1.7 JSON | `scan --format cyclonedx` | `GET /v1/bom?format=cyclonedx` | `.bomFormat` `.specVersion` |
| CycloneDX 1.7 XML | `scan --format cyclonedx-xml` (alias `cdx-xml`) | `GET /v1/bom?format=cyclonedx-xml` / `GET /v1/bom.xml` | `<bom xmlns="http://cyclonedx.org/schema/bom/1.7">` |
| SPDX 2.3 JSON | `scan --format spdx` | `GET /v1/bom?format=spdx` | `.spdxVersion` |
| SPDX 2.3 XML | `scan --format spdx-xml` (alias `spdxxml`) | `GET /v1/bom?format=spdx-xml` / `GET /v1/bom.spdx.xml` | `<SpdxDocument>` `SPDX-2.3` |
| SPDX 3.0.1 JSON | `scan --format spdx3` (alias `spdx-3`) | `GET /v1/bom?format=spdx3` | `.creationInfo.specVersion` `.spdxId` `.element` |
| SARIF 2.1.0 | `scan --format sarif` or `--sarif PATH` | `GET /v1/bom?format=sarif` / `GET /v1/bom.sarif` | `.version` `.runs` |
| Markdown summary | `scan --format md` (alias `markdown`) | `GET /v1/bom?format=md` / `GET /v1/bom.md` | `# AI-BOM` `policyHits` |
| GHA annotations | `scan --format gha` (alias `annotations`) | `GET /v1/bom?format=gha` / `GET /v1/bom.gha.txt` | `::error title=<component>` |
| HTML summary | `scan --format html` | `GET /v1/bom?format=html` / `GET /v1/bom.html` | `<h1>` `<table` policy hits red |

CycloneDX 1.7 keeps component `name` / `version` / `purl` or `type` and `licenses[]`. Models use `machine-learning-model` + `modelCard` properties the scanner already has (`aibom:format`, `aibom:sourcePath` basename) plus **observed** sha256 / on-disk model-card name/description/license URL when present; prompts use `data` (name only, no file dump). No invented architecture / datasets / metrics. Policy hits are **not** `vulnerabilities` — they go on the BOM `properties` array (`aibom:policyHits`, optional `aibom:forbiddenLicenses`). XML reuses that same model (`--format cyclonedx-xml`; names with `&` are escaped). SPDX JSON (`--format spdx`) packages use `licenseConcluded` from those licenses; SPDX XML (`--format spdx-xml`) reuses that same document (`<SpdxDocument>`, `spdxVersion` SPDX-2.3; names with `&` are escaped). SPDX 3 (`--format spdx3`) is a compact 3.0.1 JSON document (`spdxId`, `name`, `creationInfo.specVersion=3.0.1`, `element` of `software_Package` / observed `ai_AIPackage` + `simplelicensing_LicenseExpression` + license relationships). Existing `spdx` / `spdx-xml` consumers stay on 2.3. Omitted unless observed (never invented): hashes, on-disk model-card fields, `ai_AIPackage` / `profileConformance` `ai`. Still omitted: unobserved files graph, trainedOn/testedOn datasets, AI metrics, security/CVE profile, ExpandedLicensing, CBOM. Document `documentNamespace` is stable per scan root; forbidden-license hits are `hasExtractedLicensingInfos` (honest policy notes, not CVEs). Unknown `--format` on HTTP → **400** `{error:"bad_format"}` (`xml` is not a format). `--format gha` / `GET /v1/bom.gha.txt` prints GitHub Actions workflow commands (`text/plain`; `::error title=<component>::<license or rule>` for policy hits / forbidden licenses; waived `::notice title=<component>::waived <reason>`; clean scan → empty stdout / empty body **200**, no `::error`; alias `annotations`). Does not require GitHub. `--format md` / `GET /v1/bom.md` is a **human/Slack Markdown summary** (`text/markdown`; `# AI-BOM` + **components** / **policyHits** / **waived** + license / policy-hit / waived tables; `|` escaped; empty → heading + zeros 200). It is **not** another SBOM spec and never dumps file contents or secrets. `--format html` / `GET /v1/bom.html` is a **self-contained HTML BOM summary** (`text/html`; heading + component count + license table + policy hits / forbidden licenses in red if any; names escaped with stdlib `html.escape`; no CDN; empty → heading + zeros 200). `GET /` keeps the same formatter plus serve-index nav. `--sarif PATH` is unchanged (side file; same `to_sarif` builder as `--format sarif` / HTTP). `--evidence` / `--strict` / webhook still use the internal model.

### Forbidden license gate / 禁止许可证门禁

`policies/default.json` lists `forbiddenLicenseIds` (GPL-3.0 / AGPL-3.0 / SSPL-1.0 and common SPDX variants such as `GPL-3.0-only`, `GPL-3.0-or-later`, `AGPL-3.0+`). On scan:

- components whose CycloneDX `licenses[].license.id` (or SPDX expression tokens) match → `summary.forbiddenLicenses[]` policy hits
- `summary.policyHits` includes these hits
- `--strict` exits **1**
- `--gate-licenses` exits **1** on forbidden licenses only (CI-friendly; pickle / disclosure gaps do not fail)
- `--evidence` lists **Forbidden licenses / 禁止许可证**
- `--sarif` emits `ruleId` = `license/<SPDX-ID>` results

MIT (and other non-forbidden ids) on the sample-app stay clean for this license gate (`--gate-licenses` exit 0; `--strict` still fails sample-app on `pickle.load`). Committed fixtures: [`examples/cra-fixtures/license-pass`](./examples/cra-fixtures/license-pass) (MIT, exit 0) and [`examples/cra-fixtures/license-fail`](./examples/cra-fixtures/license-fail) (planted `GPL-3.0`, exit 1). A matching `.aibom-exceptions.json` waiver (component+license+reason, unexpired) removes that hit (`summary.waived`); an expired waiver still fails and is listed in `summary.expiredExceptions`.

CRA dates / honesty limits: [`docs/cra.md`](./docs/cra.md). How to run the fixtures: [`examples/cra-fixtures/README.md`](./examples/cra-fixtures/README.md).

### Advisory match gate / 本地咨询对照门禁

Article 14 (11 Sep 2026) is a **24h reporting clock**. It needs inventory + a match against issues you already know — not a full NVD mirror (that remains out of scope). `scan --advisories FILE --gate-vulns`:

- FILE is a local JSON fixture (`examples/advisories/sample.json`). IDs are `ADV-FIXTURE-*` placeholders, not real CVE matches against the internet.
- Match is **AND** of the identity fields the advisory specifies (component `name` / `purl` / `version`). Versioned advisory does not match an unversioned component. Recorded versionRange operators are evaluated; unparseable ranges are skipped. No CPE, no network.
- Planted hit on sample-app → exit **1**. `examples/advisories/clean.json` (wrong name, or same name + other version) → exit **0**.
- `--gate-vulns` without `--advisories` is a usage error (exit 2).
- Hits land on `summary.advisoryHits` / `advisoryHitCount` (does not change `policyHits`). `--evidence` lists them when present.

Offline feed: `convert-advisories --from-osv` (GHSA when the shape is close) writes this schema; point `--advisories` at the file. This CLI does not fetch osv.dev or api.github.com. See [`examples/advisories/README.md`](./examples/advisories/README.md).

`GET /v1/policy` (and CLI `ai-bom policy`) returns the **active gate**, not scan hits: `{ok, forbiddenLicenseIds, forbiddenPatterns, exceptionsCount, ignoreFile}`. Pattern field is **ids** only (no regex). Exception field is a **count** (no reasons). Missing policy file → **200** with empty lists. Does not dump policy / ignore / exceptions file contents or secrets.

`GET /v1/components` is a **lightweight inventory table** from the last scan: `{ok, count, components:[{name, version, license, path}]}`. `path` is relative to the scan root when possible, otherwise the basename — never an absolute host path. Empty scan → **200** `{ok:true, count:0, components:[]}`. Optional `?license=` is a case-insensitive exact match. The list is capped at **500** (`truncated: true` when more match). This is **not** CycloneDX/SPDX (`GET /v1/bom` exporters are unchanged). CORS + `X-Request-Id`.

`GET /v1/exceptions` is a **redacted waiver inventory** from the sidecar: `{ok, count, exceptions:[{component, license, expiresAt, expired}]}`. `count` is the full waiver count (array cap 500). Empty / no file → **200** empty list. Optional `?expired=`. Never dumps the sidecar or secrets.


## SARIF / GitHub code scanning

`ai-bom scan … --sarif out/bom.sarif` writes **SARIF 2.1.0** JSON (same builder as `scan --format sarif` and `GET /v1/bom?format=sarif`):

- `version` = `2.1.0` and `$schema` pointing at the OASIS SARIF schema
- one `runs[]` entry with `tool.driver.name` = `ai-bom`
- `results[]` for each **forbidden policy hit** (`ruleId`, `message`, `locations` with file + `startLine` when known)
- disclosure gaps as `warning` / `kind: review` results (optional notes)
- empty scan → valid log with empty `results` (HTTP **200**)

HTTP (stack-demo / `serve`, no CLI file): `GET /v1/bom?format=sarif` or `GET /v1/bom.sarif` (`application/sarif+json`). GitHub Actions examples still use **`--sarif PATH`** for `upload-sarif`. Optional log annotations (no GitHub API): `scan --format gha` or `GET /v1/bom?format=gha` / `GET /v1/bom.gha.txt` (`::error` / waived `::notice`).

Upload with GitHub’s official action (paths relative to the scan root / repo root work best):

```yaml
- name: AI-BOM SARIF
  working-directory: bets/d-ai-bom
  run: |
    PYTHONPATH=src python3 -m ai_bom scan examples/sample-app \
      --policy policies/default.json \
      --sarif out/bom.sarif

- name: Upload SARIF
  uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: bets/d-ai-bom/out/bom.sarif
    category: ai-bom
```

Copy-paste workflow: portfolio [`examples/github-actions/ai-bom-sarif.yml`](../../examples/github-actions/ai-bom-sarif.yml) → consumer `.github/workflows/` (`python3 -m ai_bom scan examples/sample-app --policy policies/default.json --sarif ai-bom.sarif` then `github/codeql-action/upload-sarif@v3`). **Code scanning must be enabled** on the consumer repo. Optional composite: [`examples/github-actions/ai-bom-sarif/action.yml`](../../examples/github-actions/ai-bom-sarif/action.yml). See [`examples/github-actions/README.md`](../../examples/github-actions/README.md). Not enabled on this repo (do not turn on code scanning from here). A commented optional job remains in `.github/workflows/ci.yml`.

## Policy-hit webhook / 策略命中 Webhook

`ai-bom scan … --webhook-url URL` or env `AI_BOM_WEBHOOK_URL`. When the scan has **forbidden pattern hits** or **forbidden licenses** (i.e. would fail `--strict` on those gates), fire-and-forget POST JSON `{ok:false, policyHits, forbiddenLicenses, summary}` (short timeout ~750ms; webhook errors **never change** the exit code). **Do not POST on a clean scan.** Empty/omit = disabled. CLI `--webhook-url` wins over env (including empty to disable). Optional **HMAC (OSS):** `--webhook-secret` or env `AI_BOM_WEBHOOK_SECRET`. When set, POST includes `X-Webhook-Signature: sha256=<hex>` — HMAC-SHA256 of the **raw JSON body**. Omit / empty secret → unsigned (existing prove). **Every** outbound POST also sends `X-Webhook-Timestamp: <unix-seconds>` (HMAC still body-only). On **5xx** or **network/timeout**, retry the POST **once** after ~50ms (success on first try = no retry; **4xx do not retry**). Simple HMAC + **1 retry** is OSS. local-mvp mock receiver (`mock-webhook-receiver.py`) writes the last body (optional `--secret` verifies HMAC; `--headers-out` persists signature + timestamp); unsigned prove stays and asserts timestamp present/roughly now; isolated signed receiver asserts header + HMAC (body) + timestamp. Smoke unit-tests 200/4xx = no retry and 5xx/network = one retry. **Exponential backoff / queues, key rotation / timestamp replay window enforcement = paid later**.
