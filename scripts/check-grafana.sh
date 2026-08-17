#!/usr/bin/env bash
# Parse-only check for deploy/grafana dashboard JSON (no Grafana process).
# Asserts Grafana 9/10 shape, panels>=5, Prometheus datasource template,
# and every PromQL expr names a metric that appears in B-F bet source.
# oss-cash-lab.json is the combined B-F portfolio; other *.json (e.g.
# e-otel-ai-cost.json) are dedicated bet dashboards (same parse checks,
# no 5-row / cross-bet deny requirements).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/scripts/check-grafana.py" "$ROOT"
