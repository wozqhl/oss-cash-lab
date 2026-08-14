#!/usr/bin/env bash
# Parse-only + cheap CLI prove for examples/github-actions (no GitHub runners).
# YAML: PyYAML yaml.safe_load when installed; otherwise the indent subset in
# scripts/check-k8s.py (no new product dependency).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/scripts/check-gha-examples.py" "$ROOT"
