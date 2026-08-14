#!/usr/bin/env bash
# Parse-only check for Prometheus alerting rules (no Prometheus process).
# Loads deploy/prometheus/rules.yaml + deploy/k8s/prometheusrule.yaml,
# requires >=6 alerts, and every PromQL expr names a metric in B-F bet source.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/scripts/check-prometheus-rules.py" "$ROOT"
