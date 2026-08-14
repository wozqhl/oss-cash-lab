# Prometheus alerting rules (B–F)

Plain Prometheus `groups` for `prometheus --rule.file` / Grafana Mimir, plus a Prometheus Operator **PrometheusRule** wrapping the same groups. Completes metrics → ServiceMonitor → Grafana → alerts. **No live Prometheus** in this repo or in `make smoke` — copy the YAML into your own Prometheus.

## Load (vanilla Prometheus / Mimir)

[`rules.yaml`](./rules.yaml) is a top-level `groups:` file (not a Kubernetes object).

```yaml
# prometheus.yml
rule_files:
  - /path/to/oss-cash-lab/deploy/prometheus/rules.yaml
```

```bash
prometheus --config.file=prometheus.yml --rule.file=deploy/prometheus/rules.yaml
```

Grafana Mimir / Cortex: upload the same `groups` as a ruler config.

## Operator (PrometheusRule CRD)

[`deploy/k8s/prometheusrule.yaml`](../k8s/prometheusrule.yaml) wraps **the same groups** as `monitoring.coreos.com/v1` `PrometheusRule`.

**Requires** Prometheus Operator CRDs. Apply **after** the CRDs exist (ServiceMonitors scrape `/metrics`; this file only defines alerts):

```bash
kubectl apply -f deploy/k8s/servicemonitor.yaml
kubectl apply -f deploy/k8s/prometheusrule.yaml
```

Kept out of [`kustomization.yaml`](../k8s/kustomization.yaml) (like `servicemonitor.yaml`) so `kubectl apply -k deploy/k8s` still works without the CRDs.

## Alerts (real names)

Few, actionable rules. `for: 5m` except `McpGatewayCircuitOpen` (`for: 1m`, counter jump). PromQL uses the same B–F names as Grafana.

| Alert | PromQL | for | notes |
|-------|--------|-----|-------|
| `McpGatewayCircuitOpen` | `increase(circuit_open_total[5m]) > 0` | 1m | B circuit opened |
| `McpGatewayRateLimited` | `rate(rate_limited_total[5m]) > 0.1` | 5m | raise to `> 1` if noisy |
| `AgentCiQueueBacklog` | `agent_ci_queue_depth > 5` | 5m | C in-memory queue |
| `AgentCiRunFailures` | `rate(agent_ci_runs_failed_total[5m]) > 0` | 5m | C failed runs |
| `AiBomForbiddenLicense` | `ai_bom_forbidden_licenses > 0` | 5m | D license gate |
| `AiBomPolicyHits` | `ai_bom_policy_hits > 0` | 5m | D policy |
| `OtelAiCostHigh` | `otel_ai_cost_total_usd > 50` | 5m | **example** 50 USD threshold — tune |
| `CnWorkApprovalsStuck` | `cn_work_agent_approvals_pending > 10` | 5m | F pending approvals |

Sources: `bets/b-mcp-gateway/src/metrics.js`, `bets/c-agent-ci/src/agent_ci/metrics.py`, `bets/d-ai-bom/src/ai_bom/metrics.py`, `bets/e-otel-ai-cost/src/metrics.js`, `bets/f-cn-work-agent/src/cn_work_agent/metrics.py`.

Dashboard: [`deploy/grafana/`](../grafana/). Scrape: [`deploy/k8s/servicemonitor.yaml`](../k8s/servicemonitor.yaml). Hosted Grafana Alerting / SLO burn = paid later.

## Prove (no Prometheus)

```bash
make check-prom-rules   # also hooked from make smoke
# or: bash scripts/check-prometheus-rules.sh
```

`scripts/check-prometheus-rules.py` loads YAML (PyYAML or the same stdlib subset parser as `check-k8s`), requires ≥6 alerts with `alert` / `expr` / `for` / `labels.severity` / `annotations.summary`, and every PromQL `expr` to name a metric that appears in those bet source files (same strip `by ()` / `increase()` / `rate()` technique as `check-grafana.py`). It does **not** start Prometheus. `prometheusrule.yaml` is also YAML-parsed by `make check-k8s` (kind `PrometheusRule`; not listed in kustomize).
