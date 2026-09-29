# Roadmap — E · otel-ai-cost

## Now (local-mvp)

- OTel-native tenant spend + budget deny from GenAI span attributes.
- Budget-breach webhook on HTTP ingest deny (once per denied request).
- Deny ingest when current spend + incoming cost would exceed the tenant budget (default; exact-on-budget allowed; `DENY_ON_WOULD_EXCEED=false` restores deny-only-after-over).
- Prometheus series for total / model / tenant / remaining / deny / tokens.
- Dedicated Grafana JSON plus the shared portfolio Total USD / Cost by model panels.
- Local OTLP demo (no Docker).
- Accept `gen_ai.cost.usd` on a span **if present** (finite number ≥ 0) as that span's incoming cost; missing/invalid keeps token × price. Draft name only — not a shipped OTel convention (see `docs/collector-contrib-issue.md`).
- Chargeback-lite CSV: `GET /v1/tenants.csv` from in-memory totals (`tenant,spend_usd,budget_usd,remaining_usd,denied_count`); hosted dashboard still paid later.
- Optional `BUDGET_PERIOD=day` / `--budget-period day` so tenant remaining and deny reset at UTC midnight (default off, cumulative).
- Local HTML dashboard remaining-by-tenant table (`GET /`) when `--tenant-budget` is set (same remaining as CSV/metrics; period label). Dedicated Grafana remaining panel already scrapes `otel_ai_cost_budget_remaining_usd` — no second series.
- [x] `report --format junit` JUnit XML budget gate (`GET /v1/costs.junit.xml` / `GET /v1/costs?format=junit`; single `otel-ai-cost-budget` suite; global/tenant failures; clean empty suite; `application/xml`; smoke `junit-ok`)
- [x] `report --format tap` TAP version 13 budget gate (`GET /v1/costs.tap.txt` / `GET /v1/costs?format=tap`; global/tenant `not ok`; clean → `1..0`; `#` escaped; `text/plain`; smoke `tap-ok`)
- [x] `GET /v1/costs.html` / `GET /v1/costs?format=html` versioned HTML export (same `formatHtml` as `GET /` / CLI; `text/html`; OpenAPI `getCostsHtml`; smoke `costs-html-ok`)

## Next (still OSS)

- Collector-contrib processor that *writes* cost/budget attributes (draft only; not filed). This repo already *reads* `gen_ai.cost.usd` if present.

## Paid later

- Hosted dashboard, anomaly alerts, chargeback.
- Webhook exponential backoff / queues / key rotation / timestamp replay.
- Multi-sink exporters, SSO, multi-tenant control plane.
