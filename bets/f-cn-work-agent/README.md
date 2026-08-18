# F · cn-work-agent

> 飞书 / 钉钉 / 企微 **审批适配器**（挂在 Dify / n8n 前面）· **Status: local-mvp 0.1.0** · Phase 3

## 给信息化

这不是 Dify 替代品。本仓库是 **私有化部署的 IM 审批适配器**：飞书 / 钉钉 / 企微 webhook → 本地审批单 → 卡片 / 决定 HTTP，再把结果交给后面的 Dify 或 n8n。买家是政企信息化 / IT，不是 GitHub star。

**诚实边界：** 当前是 **0.1.0 本地 MVP**。**不是**等保认证产品。SSO、等保测评支持、厂商正式 SDK 属于付费项。无客户案例。

三分钟本地演示（请假 + 用印，无真实飞书 / 钉钉 / 企微网络）：

```bash
cd bets/f-cn-work-agent
bash scripts/demo-feishu-approval.sh                 # 飞书 interactive card
bash scripts/demo-dingtalk-approval.sh               # 钉钉 actionCard
bash scripts/demo-wecom-approval.sh                  # 企微 textcard
# 或：bash scripts/demo-feishu-approval.sh --platform dingtalk|wecom|all
```

私有化 / 等保 / 与 Dify 的前后关系：[docs/cn-onprem.md](./docs/cn-onprem.md)。内网 ask/reply 手册：[docs/intranet-demo.md](./docs/intranet-demo.md)。

## Thesis / 立意

CN office IM is the default enterprise agent entry. Ship on-prem webhook → intent → local tools, with local mock connectors for three platforms (no vendor SDKs).

企微/钉钉/飞书是企业 Agent 默认入口；私有化优先，本地 mock 三平台 webhook 形状，共享意图路由。

## Who pays / 谁付钱

- Gov / enterprise IT & digital transformation
- 政企 IT / 数字化部门

## OSS vs Paid

| OSS | Paid |
|-----|------|
| Multi-IM webhook shapes + rule router (local mock) | Real vendor SDKs, SSO, SLA |
| Local tool hooks + simple approval JSONL (`data/approvals.jsonl`) + **audit CSV** (`GET /v1/approvals.csv`) + **Markdown list** (`GET /v1/approvals.md`) + **HTML list** (`GET /v1/approvals.html`) + **native IM cards** (`GET /v1/approvals/{id}/card`) | Vendor approval sync, multi-approver, compliance packs, real Feishu/DingTalk/WeCom send APIs |
| In-memory webhook rate limit (IP + platform; env/config) | Redis/distributed limits, WAF, abuse analytics |
| Approval TTL auto-reject (`APPROVAL_TTL_SECONDS`) | Multi-approver SLA, reminder fans, compliance holds |
| Optional CORS (`CORS_ORIGINS` / `cors.origins`; default deny; allow/expose `Retry-After` + `X-Request-Id`) | Managed browser gateway, custom ACAO policies |
| `X-Request-Id` echo + `requestId` on approvals/audit | Distributed tracing / SIEM correlation |
| OpenAPI 3 (`GET /openapi.json`) + A dogfood SDK stubs | Hosted connector SDKs / vendor-shaped clients |
| Prometheus `GET /metrics` (pending / decided_total / webhooks_total) | Hosted Grafana / fleet dashboards |
| Optional approval-decision webhook (`APPROVAL_WEBHOOK_URL`) + simple HMAC-SHA256 (`X-Webhook-Signature`) + `X-Webhook-Timestamp` + **1 retry** on 5xx/timeout | Webhook exponential backoff / queues, HMAC key rotation, timestamp replay window enforcement |
| Optional Dify / n8n **sample** forward (`APPROVAL_FORWARD_URL` / `--forward-url`; `{event,approval_id,status,tenant\|app,title}`; 1 retry; no secrets in body; optional HMAC `APPROVAL_FORWARD_SECRET` → `X-Webhook-Signature`; **example wiring, not a Dify plugin**) | Vendor Dify/n8n plugins, embedded orchestration, queue/backoff |
| Optional inbound IM decide HMAC (`callbackSecret` → `X-Callback-Signature`; POST only; GET cards unsigned) | Real Feishu/DingTalk/WeCom card-callback adapters, key rotation, signed card URLs |
| Serve `--watch` (config mtime poll ~300ms; reload CORS/TTL/webhook/rate-limit/approvals-max; env wins if already set) | Hosted config sync / remote policy |
| Decided-approvals cap (`--approvals-max` / `APPROVALS_MAX` default 2000; drop oldest decided; pending kept) | Persistent audit archive, SIEM retention |
| `GET /v1/platforms` inventory (`id`, `enabled`, `hasCallbackSecret`; no tokens/secrets) | Vendor connector catalog / live IM status |
| `GET /v1/config` redacted runtime snapshot (TTL / rate-limit / CORS origins / approvals-max / webhook booleans / platforms; **never** secrets) | Admin-token config dump / secret-bearing debug |

## 2-week MVP checklist / 2周MVP清单

- [x] One IM connector (Feishu preferred)
- [x] Multi-IM local mocks: Feishu + DingTalk + WeCom
- [x] Webhook → shared intent route → local tool (+ per-platform verify)
- [x] Config-driven (config.example.json + serve --config)
- [x] Demo: ask one question → one reply (intranet runbook)
- [x] README with intranet runbook (`docs/intranet-demo.md`)
- [x] Simple approval flow (intent → `data/approvals.jsonl` → GET/decide HTTP)
- [x] Native IM approval cards (Feishu interactive / DingTalk actionCard / WeCom textcard; `GET /v1/approvals/{id}/card?platform=`; mock-only, no tokens)
- [x] Approval audit CSV (`export --format csv`; `GET /v1/approvals.csv` / `GET /v1/approvals?format=csv`; columns `id,platform,status,createdAt,decidedAt,reason`; empty → header only)
- [x] Approval Markdown list (`export --format md`; `GET /v1/approvals.md` / `GET /v1/approvals?format=md`; `text/markdown`; GFM table, same columns as CSV; `|` escaped; empty → heading + header row only; paste into Feishu/WeCom docs)
- [x] Approval HTML list (`export --format html`; `GET /v1/approvals.html` / `GET /v1/approvals?format=html`; `text/html`; self-contained no CDN; columns id/platform/status/title/created/decided/reason; pending vs decided/expired styled; empty → heading + “no approvals”; names escaped)
- [x] Webhook rate limit (`RATE_LIMIT_PER_MINUTE` default 60; 429 + `Retry-After`)
- [x] Approval TTL auto-reject (`APPROVAL_TTL_SECONDS` default 86400 → `rejected`/`expired`)
- [x] Optional CORS (`CORS_ORIGINS` / `cors.origins`; default deny; OPTIONS 204/403)
- [x] `X-Request-Id` (incoming or generated UUID; echo every response incl 4xx/OPTIONS/429; `requestId` on approvals + audit)
- [x] OpenAPI 3 (`openapi/agent.openapi.json` + `GET /openapi.json`; `/ready` `getReady`; webhook 401/429; 403 CORS notes; `X-Request-Id`; `/metrics`; `/v1/approvals.csv` `getApprovalsCsv`; `/v1/approvals.md` `getApprovalsMd`; `/v1/approvals.html` `getApprovalsHtml`)
- [x] `GET /ready` 200 `{ok:true, service}` + same snapshot as `/health` when healthy; 503 `shutting_down` on SIGTERM/SIGINT (not rate-limited; Compose stays on `/health`)
- [x] Prometheus `GET /metrics` (`cn_work_agent_approvals_pending`, `cn_work_agent_approvals_decided_total`, `cn_work_agent_webhooks_total`; CORS same as other GET)
- [x] Approval-decision webhook (`APPROVAL_WEBHOOK_URL` / `--webhook-url`; optional HMAC `--webhook-secret`)
- [x] Dify / n8n sample forward (`APPROVAL_FORWARD_URL` / `--forward-url`; fire-and-forget `{event,approval_id,status,tenant|app,title}` on approved/rejected; 1 retry; optional HMAC `APPROVAL_FORWARD_SECRET` → `X-Webhook-Signature`; example wiring, not a plugin)
- [x] Inbound IM decide HMAC (`callbackSecret` / `FEISHU_CALLBACK_SECRET`; POST `X-Callback-Signature`; GET unsigned for demo cards)
- [x] Serve `--watch` (poll `--config` mtime ~300ms; reload CORS/TTL/webhook url+secret/rate-limit/approvals-max; env wins if already set; local-mvp isolated copy prove)
- [x] Decided-approvals cap (`--approvals-max` / `APPROVALS_MAX` default 2000; `0` = unlimited; drop oldest approved/rejected/expired; pending kept; GET by id 404; smoke + isolated local-mvp `--approvals-max 2`)
- [x] `GET /v1/platforms` IM inventory (`{ok,count,platforms:[{id,enabled,hasCallbackSecret}]}`; known three + config extras; no secrets; CORS + `X-Request-Id`; not rate-limited harder than other GETs)
- [x] `GET /v1/config` redacted runtime config (`approvalTtlSec`, `rateLimit`, `cors.origins`, `approvalsMax`, `webhooks.hasUrl`/`hasSecret`, platforms; public GET, no admin token; never secrets; CORS + `X-Request-Id`; optional CLI `config`)
- [x] `GET /v1/approvals?status=pending|approved|rejected|expired` (CSV/MD/HTML share the list helper; unknown/empty → 200 empty list; omit → unfiltered)

## Platforms (local mock)

| Route | Auth env | Notes |
|-------|----------|-------|
| `POST /webhook/feishu` | `FEISHU_VERIFY_TOKEN`, `FEISHU_ENCRYPT_KEY` | URL verification `challenge`; Lark-style signature headers |
| `POST /webhook/dingtalk` | `DINGTALK_TOKEN`, `DINGTALK_SECRET` | Callback JSON `text.content`; `X-DingTalk-Timestamp` + `X-DingTalk-Sign` |
| `GET/POST /webhook/wecom` | `WECOM_TOKEN` | GET `echostr` URL verify; POST message; `msg_signature` = sha1(sort(token,ts,nonce,encrypt)) |

Shared intents: `ping` / `help` / `digest <text>` / `approve request`|`审批` / echo. Inbound normalized to a common event; outbound ack shape differs per platform.

`GET /health` lists `platforms` / `enabled` / `rate_limit_per_minute` / `approval_ttl_seconds` / `approvals_max` (id strings only). **`GET /v1/platforms`** is the product inventory: `{ok, count, platforms:[{id, enabled, hasCallbackSecret}]}` for feishu / dingtalk / wecom plus extras already in config `platforms`. **Never** returns `callbackSecret`, tokens, or encrypt keys. CORS + `X-Request-Id`. Not rate-limited (same as other GETs besides `/webhook/*`). Optional CLI `platforms`. **`GET /v1/config`** is a public redacted runtime snapshot for intranet-pilot debugging (no admin token): `{ok, approvalTtlSec, rateLimit:{perMinute}, cors:{origins}, approvalsMax, webhooks:{hasUrl,hasSecret}, platforms}`. **Never** webhook URL (query tokens), webhook secret, `callbackSecret`, `FEISHU_*` tokens, or `Authorization`. Optional CLI `config`. **`GET /ready`** is **200** `{ok:true, service}` plus the same snapshot fields when healthy; **503** `{ok:false, reason:"shutting_down"}` on SIGTERM/SIGINT (liveness `/health` stays 200 with `shuttingDown: true`). Compose/stack-demo healthchecks stay on `/health`. Every response (including 4xx / OPTIONS / 429) echoes **`X-Request-Id`** (incoming header or generated UUID). Optional **`serve --watch`** polls `--config` mtime (~300ms) and reloads CORS origins, TTL, webhook url/secret, rate limits, and approvals-max from file (see precedence below).

`GET /metrics` Prometheus text (0.0.4): gauge `cn_work_agent_approvals_pending` (JSONL pending count; scrape does **not** run expire_due) and counters `cn_work_agent_approvals_decided_total` (approve/reject/TTL expire, process lifetime), `cn_work_agent_webhooks_total` (outbound decision webhook attempts, process lifetime). CORS: matching Origin GET includes ACAO (same as other GET). `/health`, `/ready`, `/metrics`, `/openapi.json`, `/v1/platforms`, `/v1/config`, `/approvals`, `/v1/approvals.csv`, `/v1/approvals.md`, and `/v1/approvals.html` are not rate-limited.

`GET /openapi.json` serves the file-backed OpenAPI 3 document ([`openapi/agent.openapi.json`](./openapi/agent.openapi.json)): `/health`, **`/ready`** (`getReady`), **`GET /v1/platforms`** (`getPlatforms`; `{id,enabled,hasCallbackSecret}`; no secrets), **`GET /v1/config`** (`getConfig`; redacted TTL/rate-limit/CORS/approvals-max/webhook booleans/platforms; no secrets), `/metrics`, `/webhook/feishu`, `/webhook/dingtalk`, `/webhook/wecom`, `GET /approvals`, `GET /approvals/{id}`, `GET`+`POST /approvals/{id}/decide` (POST optional inbound HMAC `X-Callback-Signature`; GET unsigned), **`GET /v1/approvals.csv`** (`getApprovalsCsv`), **`GET /v1/approvals.md`** (`getApprovalsMd`), **`GET /v1/approvals.html`** (`getApprovalsHtml`), **`GET /v1/approvals`** (`getApprovals`, `?format=`), **`GET /v1/approvals/{id}/card`** (`getApprovalCard`, Feishu/DingTalk/WeCom card JSON), plus `X-Request-Id`, webhook **401/429**, decide POST **401**, **403** CORS notes, and outbound `ApprovalDecisionWebhook` (optional HMAC). Portfolio dogfood: `make dogfood-a-f` (A generates TS/Python/Go clients under `sdk/generated/`, gitignored).

### CORS (optional, default deny)

Browser callers: env **`CORS_ORIGINS`** CSV, config **`cors.origins`** list, or `serve --cors-origins`. Empty/omit = **deny extra CORS** (no ACAO; OPTIONS **404**). `*` allows any Origin. Default allow/expose headers include **`X-Request-Id`**; default expose also includes **`Retry-After`** (GET/POST/OPTIONS ACEH).

| Source | Default / notes |
|--------|-----------------|
| `CORS_ORIGINS` | CSV (`http://localhost:3000` or `*`); env wins over config when set (including empty) |
| `cors.origins` in config JSON | list or CSV string |
| `--cors-origins` | CLI wins when provided (including empty) |

Explicit list: OPTIONS preflight with a listed `Origin` → **204** + ACAO / Allow-Methods / Allow-Headers; unlisted Origin (e.g. `http://evil.example`) → **403** `{error:"forbidden",reason:"cors_denied"}` (no ACAO). Matching GET/POST include `Access-Control-Allow-Origin`. Default expose (`Access-Control-Expose-Headers`) includes **`Retry-After`** and **`X-Request-Id`**. local-mvp isolated prove uses `http://localhost:3000` vs `http://evil.example` (GET/OPTIONS ACEH includes `retry-after`, case-insensitive); main serve stays default deny.

```bash
CORS_ORIGINS=http://localhost:3000 PYTHONPATH=src python3 -m cn_work_agent serve --port 8809
# OPTIONS Origin http://localhost:3000 → 204 + ACAO
# OPTIONS Origin http://evil.example → 403 cors_denied
```

### Serve `--watch` (optional)

`serve --config config.json --watch` polls the config file mtime every **~300ms** and reloads **CORS origins**, **approval TTL**, **webhook url/secret**, **rate limits**, and **approvals-max** from the file. Parse errors keep the previous settings. Prints `regenerated` on success. Requires `--config`. Main serve / stack-demo omit `--watch` (one-shot at start). Platforms / in-memory rate-limit buckets / HMAC signing of the raw body are unchanged.

**Precedence** (highest first): CLI flags when provided (`--cors-origins`, `--webhook-url`, `--webhook-secret`, `--approvals-max`, including empty/`0`) → **env if already set** (`CORS_ORIGINS`, `APPROVAL_TTL_SECONDS`, `APPROVALS_MAX`, `RATE_LIMIT_*`, `APPROVAL_WEBHOOK_URL`, `APPROVAL_WEBHOOK_SECRET`, including empty) → config file (reloaded on watch). Platform tokens follow the same env-wins-if-already-set rule.

local-mvp isolated prove: copy config → curl `/health` TTL → change `approval_ttl_seconds` → wait → health shows new TTL → kill (must not hang).

```bash
PYTHONPATH=src python3 -m cn_work_agent serve --config config.example.json --watch --port 8814
# edit approval_ttl_seconds in the file → GET /health reflects the new TTL
```

### X-Request-Id

Optional correlation header. Echoed on **every** response (including 4xx / OPTIONS / 429). If omitted/empty, the server generates a UUID (max 128 chars; CR/LF stripped). Same value stored as `requestId` on approval records (`data/approvals.jsonl`) and audit JSONL entries when the request creates/decides them. CORS allow/expose includes `X-Request-Id`. local-mvp sends a custom id on `/health`, `/metrics`, and webhook create and asserts the response header + stored approval.

JSON access logs (opt-in): `--log-json` or env `LOG_FORMAT=json` (env wins if CLI omitted) — one stdout JSON line per completed app request `{ts,level:info,msg:http,service,method,path,status,durationMs,requestId}`; skips `/health` `/ready` `/metrics` and OPTIONS. Default **off**.

```bash
curl -sD - http://127.0.0.1:8790/health -H 'X-Request-Id: mvp-health-rid-f1'
# → X-Request-Id: mvp-health-rid-f1
```

### Webhook rate limit

In-memory **sliding window** (60s) keyed by **client IP + platform** on `/webhook/*` (not `/health`, `/ready`, `/metrics`, `/openapi.json`, `/v1/platforms`, `/v1/config`, `/approvals`, `/v1/approvals.csv`, `/v1/approvals.md`, `/v1/approvals.html`, or `/v1/approvals/{id}/card`).

| Source | Default / notes |
|--------|-----------------|
| `RATE_LIMIT_PER_MINUTE` | **60** (env wins over config) |
| `rate_limit_per_minute` in config JSON | same global default |
| `RATE_LIMIT_FEISHU_PER_MINUTE` / `RATE_LIMIT_DINGTALK_PER_MINUTE` / `RATE_LIMIT_WECOM_PER_MINUTE` | optional per-platform override |
| `feishu.rate_limit_per_minute` (etc.) in config | optional per-platform override |
| `0` or negative | unlimited (disable) |

Exceed → **`429`** JSON `{"error":"rate_limited","limit":N,"retry_after":S}` + header **`Retry-After: S`**. `GET /health` reports `rate_limit_per_minute`.

```bash
RATE_LIMIT_PER_MINUTE=2 PYTHONPATH=src python3 -m cn_work_agent serve --port 8807
# third POST /webhook/feishu within a minute → 429
```

### Simple approval flow (local MVP)

When a message contains **审批** or **approve request**, the agent creates a pending record in `data/approvals.jsonl` (`id`, `status=pending`, `text`, `platform`) and the webhook ack includes `approval_id` + `decide_hint` (curl) plus a platform `card` (native IM payload).

| Method | Path | Notes |
|--------|------|-------|
| `GET` | `/approvals` | List pending/recent (`?status=pending\|approved\|rejected\|expired`, unknown/empty → 200 empty; `?limit=`, `?format=csv`, `md`, `html`, or `json`); runs `expire_due` first (decided cap applied) |
| `GET` | `/v1/approvals.csv` | Audit CSV (`text/csv`): `id,platform,status,createdAt,decidedAt,reason`; includes TTL auto-rejects; empty → header only (200); no `text`/tokens/HMAC |
| `GET` | `/v1/approvals.md` | Markdown list (`text/markdown`): `# Approvals` + GFM table, same columns as CSV; `|` escaped; empty → heading + header row only (200); paste into Feishu/WeCom docs; no `text`/tokens/HMAC |
| `GET` | `/v1/approvals.html` | HTML list (`text/html`): self-contained table (no CDN); columns id/platform/status/title/created/decided/reason; pending vs decided/expired styled; empty → heading + “no approvals” (200); all text escaped |
| `GET` | `/v1/approvals` | Same list + `?status=`; `?format=csv` → CSV, `?format=md` → Markdown, `?format=html` → HTML, `?format=json` or omit → JSON (same as `/approvals`); unknown format → 400 `bad_format` |
| `GET` | `/approvals/{id}` | Get one record (also expires due) |
| `GET` | `/v1/approvals/{id}/card` | Native IM POST body (`?platform=feishu` / `dingtalk` / `wecom`; omit → stored platform). Feishu interactive (`header`/`elements` + Approve/Reject buttons), DingTalk `actionCard`, WeCom `textcard`. No tokens. Unknown id → 404 |
| `GET` | `/approvals/{id}/decide` | Query `?decision=approve` or `reject` (optional `note`). **Unsigned** even when `callbackSecret` is set — OSS convenience for IM card buttons (URLs cannot carry HMAC). Production should use POST + signature |
| `POST` | `/approvals/{id}/decide` | Body `{"decision":"approve"|"reject","note":"..."}`; updates status + audit. When `callbackSecret` is set for the approval's platform: require `X-Callback-Signature: sha256=<hex>` of the raw body; optional `X-Callback-Timestamp` (skew > 300s → 401). Missing/bad signature → **401** (secret never leaked). Default **off** (unsigned POST 200) |

#### Approval TTL (auto-reject)

Pending approvals older than TTL are auto-rejected with `reason=expired` (status `rejected`). Expiry runs on list/get/decide and on a short periodic loop inside `serve`.

| Source | Default / notes |
|--------|-----------------|
| `APPROVAL_TTL_SECONDS` | **86400** (env wins over config) |
| `approval_ttl_seconds` in config JSON | same |
| `0` or negative | disable auto-expiry |
| CLI | `python3 -m cn_work_agent expire-approvals --approvals data/approvals.jsonl` |

```bash
# after serve is up (with verify headers as in local-mvp)
curl -s http://127.0.0.1:8790/approvals
curl -s http://127.0.0.1:8790/v1/approvals.csv
# header: id,platform,status,createdAt,decidedAt,reason  (empty store → header only)
curl -s http://127.0.0.1:8790/v1/approvals.md
# # Approvals + GFM table (empty store → heading + header row only)
curl -s http://127.0.0.1:8790/v1/approvals.html
# self-contained HTML table (empty store → heading + “no approvals”)
curl -s "http://127.0.0.1:8790/v1/approvals/appr_xxx/card?platform=feishu"
# Feishu interactive card JSON (header / elements); unknown id → 404
python3 -m cn_work_agent export --approvals data/approvals.jsonl --format csv
python3 -m cn_work_agent export --approvals data/approvals.jsonl --format md
python3 -m cn_work_agent export --approvals data/approvals.jsonl --format html
curl -s -X POST http://127.0.0.1:8790/approvals/appr_xxx/decide \
  -H 'content-type: application/json' \
  -d '{"decision":"approve","note":"ok"}'

# local-mvp uses APPROVAL_TTL_SECONDS=1 on an isolated port: create → sleep 2 → list/get show rejected/expired; decide approve → 400
APPROVAL_TTL_SECONDS=1 PYTHONPATH=src python3 -m cn_work_agent serve --port 8808 --approvals data/ttl-approvals.jsonl
```

#### Decided-approvals cap

JSONL `data/approvals.jsonl` (and therefore list / CSV / Markdown / HTML / cards) cannot grow forever. After decide or TTL expire, drop oldest **decided** (`approved` / `rejected` / `expired`) rows over the cap. **Pending** within TTL are never dropped. Webhook already fired at decide/expire (not affected). `GET /approvals/{id}` and `GET /v1/approvals/{id}/card` → **404** if dropped.

| Source | Default / notes |
|--------|-----------------|
| `--approvals-max` | CLI wins when provided |
| `APPROVALS_MAX` | env (wins over config when set, including `0`) |
| `approvals_max` in config JSON | same |
| default | **2000** |
| `0` | unlimited |

```bash
PYTHONPATH=src python3 -m cn_work_agent serve --port 8815 --approvals-max 2
# create+decide 3 → GET /approvals, /v1/approvals.csv, /v1/approvals.md, /v1/approvals.html have 2; oldest GET 404
```

### Approval-decision webhook (OSS)

When an approval is **decided** (`approve`/`reject`) or **TTL-expired**, optionally POST JSON `{id,status,decision,reason,requestId}` (fire-and-forget, ~750ms timeout; webhook errors **never fail** decide/expire). Empty/omit = disabled. **No POST on create** (pending).

| Source | Default / notes |
|--------|-----------------|
| `APPROVAL_WEBHOOK_URL` | env (wins over config when set, including empty) |
| `approval_webhook_url` in config JSON | same |
| `--webhook-url` | CLI wins when provided |
| `APPROVAL_WEBHOOK_SECRET` / `--webhook-secret` / `approval_webhook_secret` | optional HMAC |

Optional **HMAC (OSS):** `--webhook-secret` or env `APPROVAL_WEBHOOK_SECRET`. When set, POST includes `X-Webhook-Signature: sha256=<hex>` — HMAC-SHA256 of the **raw JSON body**. Omit / empty secret → unsigned. **Every** outbound POST also sends `X-Webhook-Timestamp: <unix-seconds>` (HMAC still body-only). On **5xx** or **network/timeout**, retry the POST **once** after ~50ms (success on first try = no retry; **4xx do not retry**). Simple HMAC + **1 retry** is OSS. local-mvp mock receiver (`mock-webhook-receiver.py`) writes the last body (optional `--secret` verifies HMAC; `--headers-out` persists signature + timestamp); unsigned isolated prove stays and asserts timestamp present/roughly now; isolated signed receiver asserts header + HMAC (body) + timestamp. Smoke unit-tests 200/4xx = no retry and 5xx/network = one retry. **Exponential backoff / queues, key rotation / timestamp replay window enforcement = paid later**.

```bash
# unsigned
APPROVAL_WEBHOOK_URL=http://127.0.0.1:8810/hook PYTHONPATH=src python3 -m cn_work_agent serve --port 8811
# HMAC
APPROVAL_WEBHOOK_URL=http://127.0.0.1:8812/hook APPROVAL_WEBHOOK_SECRET=whsec_local_mvp \
  PYTHONPATH=src python3 -m cn_work_agent serve --port 8813
```

### Dify / n8n sample forward (OSS, adapter only)

When an approval is **approved** or **rejected** (including TTL-expired), optionally POST JSON `{event, approval_id, status, tenant|app, title}` to a Dify / n8n webhook URL. Fire-and-forget, ~750ms timeout, **1 retry** on 5xx/timeout (same as the decision webhook). **No POST while pending.** **No secrets** in the body. Empty/omit = disabled. This is **example wiring**, not a Dify plugin and not embedded orchestration.

| Source | Default / notes |
|--------|-----------------|
| `APPROVAL_FORWARD_URL` | env (wins over config when set, including empty) |
| `approval_forward_url` in config JSON | same |
| `--forward-url` | CLI wins when provided |
| `tenant` / `APPROVAL_FORWARD_TENANT` | optional; else `app` from `bot_name` |
| `APPROVAL_FORWARD_SECRET` / `--forward-secret` / `approval_forward_secret` | optional HMAC (`X-Webhook-Signature: sha256=<hex>` of raw body; default off; same as B/E) |

```bash
APPROVAL_FORWARD_URL=http://127.0.0.1:8816/webhook PYTHONPATH=src python3 -m cn_work_agent serve --port 8817
# smoke prints forward-ok; with APPROVAL_FORWARD_SECRET also forward-hmac-ok
```

### Inbound IM callback HMAC (OSS)

Approve/reject from WeCom/DingTalk/Feishu **cards** must not be forgeable. Optional per-platform secret in config (default **off** so local-mvp unsigned POST decide stays 200):

| Source | Notes |
|--------|-------|
| `feishu.callbackSecret` (also `callback_secret` / `verificationToken` / `appSecret`) | HMAC key for that platform |
| `platforms.feishu.callbackSecret` | same when `platforms` is an object |
| `FEISHU_CALLBACK_SECRET` / `DINGTALK_CALLBACK_SECRET` / `WECOM_CALLBACK_SECRET` | env wins if set (including empty) |
| `APPROVAL_CALLBACK_SECRET` | fallback for all platforms |

Does **not** reuse IM webhook `verify_token` / `encrypt_key` / DingTalk `secret` / WeCom `token` (those stay on `/webhook/*`).

When the secret is set for the approval's platform:

- **POST** `/approvals/{id}/decide` requires **`X-Callback-Signature: sha256=<hex>`** — HMAC-SHA256 of the **raw JSON body** (same style as outbound `X-Webhook-Signature`; timing-safe compare).
- Optional **`X-Callback-Timestamp: <unix-seconds>`** — reject if `|now - ts| > 300` (`timestamp_skew`). Timestamp is **not** part of the HMAC (body-only).
- Missing/bad signature → **401** `{error:"unauthorized",reason}`. The secret is never echoed.
- **GET** `/approvals/{id}/decide?decision=approve` stays unsigned (card button URLs). Documented OSS convenience; **production should POST + signature**. Feishu/DingTalk/WeCom adapters can copy `X-Callback-Signature` in production later.

```bash
# isolated (secret on): unsigned POST → 401; good HMAC → 200; GET still 200
PYTHONPATH=src python3 -c 'from cn_work_agent.webhook import sign_webhook_body; print(sign_webhook_body("cbsec_local_mvp", b"{\"decision\":\"approve\"}"))'
curl -s -X POST http://127.0.0.1:8790/approvals/appr_xxx/decide \
  -H 'content-type: application/json' \
  -H "X-Callback-Signature: sha256=…" \
  -d '{"decision":"approve"}'
```

## Quick start

```bash
PYTHONPATH=src python3 -m cn_work_agent smoke
PYTHONPATH=src python3 -m cn_work_agent platforms --config config.example.json
PYTHONPATH=src python3 -m cn_work_agent demo --text ping --platform feishu
PYTHONPATH=src python3 -m cn_work_agent demo --text "digest hi" --platform dingtalk

export FEISHU_VERIFY_TOKEN=mvp-token
export FEISHU_ENCRYPT_KEY=mvp-encrypt
export DINGTALK_TOKEN=mvp-dt-token
export DINGTALK_SECRET=mvp-dt-secret
export WECOM_TOKEN=mvp-wc-token
# optional: export RATE_LIMIT_PER_MINUTE=60
# optional: export APPROVAL_TTL_SECONDS=86400
# optional: export APPROVALS_MAX=2000  # 0 = unlimited; drop oldest decided
# optional: export CORS_ORIGINS=http://localhost:3000
# optional: curl -H 'X-Request-Id: my-id' (echoed on every response)
# optional: export APPROVAL_WEBHOOK_URL=http://127.0.0.1:8810/hook
# optional: export APPROVAL_WEBHOOK_SECRET=whsec_local_mvp  # X-Webhook-Signature HMAC
# optional: export APPROVAL_FORWARD_URL=http://127.0.0.1:8816/webhook  # Dify/n8n sample shape
# optional: feishu.callbackSecret / FEISHU_CALLBACK_SECRET  # POST decide X-Callback-Signature
# GET /openapi.json  # file-backed OpenAPI 3
# GET /metrics       # Prometheus text (pending / decided_total / webhooks_total)
# GET /v1/platforms  # IM inventory {id,enabled,hasCallbackSecret} (no secrets)
# GET /v1/config     # redacted runtime config (TTL/rate-limit/CORS/approvals-max/webhook booleans; no secrets)
# GET /v1/approvals.csv  # audit CSV (id,platform,status,createdAt,decidedAt,reason)
# GET /v1/approvals.md   # Markdown table for Feishu/WeCom docs
# GET /v1/approvals.html # self-contained HTML list (local demo)
PYTHONPATH=src python3 -m cn_work_agent serve --port 8790
# or load tokens/platforms from file:
# PYTHONPATH=src python3 -m cn_work_agent serve --config config.example.json
# optional: --watch  poll config mtime (~300ms) and reload CORS/TTL/webhook/rate-limit/approvals-max
# optional: --platform feishu --platform wecom
```

```bash
bash scripts/local-mvp.sh                 # hits all three platforms (good + bad auth)
bash scripts/demo-feishu-approval.sh      # 三分钟：飞书请假/用印（推荐给信息化）
bash scripts/demo-dingtalk-approval.sh    # 同上，钉钉 actionCard（无钉钉公网）
bash scripts/demo-wecom-approval.sh       # 同上，企微 textcard（无企微公网）
# bash scripts/demo-feishu-approval.sh --platform all
bash scripts/demo-ask-reply.sh            # config-driven ask/reply demo (optional)
```

内网手册（中文）：[docs/intranet-demo.md](./docs/intranet-demo.md) — 含 curl、审计日志与生产验签 **DRAFT** 差异说明。

Stdlib only. No real Feishu/DingTalk/WeCom SDKs.

Container (k8s placeholder; images not published; skip if no Docker): `docker build -t ghcr.io/wozqhl/f-cn-work-agent:dev bets/f-cn-work-agent` (`python:3.12-alpine`, EXPOSE **8790**, `python -m cn_work_agent serve --host 0.0.0.0`).
