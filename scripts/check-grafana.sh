#!/usr/bin/env bash
# Parse-only check for deploy/grafana dashboard JSON (no Grafana process).
# Asserts Grafana 9/10 shape, panels>=5, Prometheus datasource template,
# and every PromQL expr names a metric that appears in B-F bet source.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/scripts/check-grafana.py" "$ROOT"
