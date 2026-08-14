# Grafana dashboards (B–F)

Importable **Grafana 9/10** JSON for the five HTTP bets' Prometheus `/metrics`. **No live Grafana** in this repo or in `make smoke` — copy the JSON into your own Grafana.

## Import

1. Grafana → **Dashboards** → **New** → **Import**.
2. Upload [`oss-cash-lab.json`](./oss-cash-lab.json) (or paste the file).
3. Pick a **Prometheus** datasource (uid `prometheus`, or the import variable `${DS_PROMETHEUS}`).
4. Save. Refresh is **30s** to match [`deploy/k8s/servicemonitor.yaml`](../k8s/servicemonitor.yaml).

The dashboard is one combined view with **five rows** (B / C / D / E / F) and ~10 graph panels (under ~15 including row headers). Metric names are the real counters/gauges from bet source — not invented `http_requests_total` clones.

## Panels (real names)

| Row | Panel | PromQL uses |
|-----|--------|-------------|
| B MCP Gateway | HTTP request rate | `http_requests_total` |
| B | Deny / error rate | `rate_limited_total`, `ip_denied_total`, `body_too_large_total`, `upstream_timeout_total` |
| B | Circuit open | `circuit_open_total` |
| C Agent CI | Queue depth | `agent_ci_queue_depth`, `agent_ci_running` |
| C | Run completion rate | `agent_ci_runs_completed_total`, `agent_ci_runs_failed_total` |
| D AI BOM | Policy hits | `ai_bom_policy_hits`, `ai_bom_forbidden_licenses` |
| D | Component count | `ai_bom_component_count` |
| E OTel AI cost | Total USD | `otel_ai_cost_total_usd` |
| E | Cost by model | `otel_ai_cost_by_model_usd` |
| F CN work agent | Pending approvals | `cn_work_agent_approvals_pending`, `cn_work_agent_approvals_decided_total`, `cn_work_agent_webhooks_total` |

Sources: `bets/b-mcp-gateway/src/metrics.js`, `bets/c-agent-ci/src/agent_ci/metrics.py`, `bets/d-ai-bom/src/ai_bom/metrics.py`, `bets/e-otel-ai-cost/src/metrics.js`, `bets/f-cn-work-agent/src/cn_work_agent/metrics.py`.

Scrape: optional Prometheus Operator ServiceMonitors in [`deploy/k8s/servicemonitor.yaml`](../k8s/servicemonitor.yaml) (`port: http`, `path: /metrics`, 30s). This box has **no cluster** and **no Grafana**.

## Prove (no Grafana)

```bash
make check-grafana   # also hooked from make smoke
# or: bash scripts/check-grafana.sh
```

`scripts/check-grafana.py` loads JSON, requires `panels` length ≥ 5, Grafana `schemaVersion` ~38, a Prometheus datasource template, and every PromQL `expr` to reference a metric name that appears in those bet source files. It does **not** start Grafana.

Prometheus alerting rules (same B–F names) live in [`deploy/prometheus/`](../prometheus/) and [`deploy/k8s/prometheusrule.yaml`](../k8s/prometheusrule.yaml). Hosted Grafana Alerting / SLO burn = paid later.
