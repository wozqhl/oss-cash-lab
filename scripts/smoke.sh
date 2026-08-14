#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "==> [A] a-sdk-mcp-gen"
(cd "$ROOT/bets/a-sdk-mcp-gen" && npm run smoke --silent)
echo "==> [B] b-mcp-gateway"
(cd "$ROOT/bets/b-mcp-gateway" && npm run smoke --silent)
echo "==> [C] c-agent-ci"
(cd "$ROOT/bets/c-agent-ci" && PYTHONPATH=src python3 -m agent_ci smoke)
echo "==> [D] d-ai-bom"
(cd "$ROOT/bets/d-ai-bom" && PYTHONPATH=src python3 -m ai_bom smoke)
echo "==> [E] e-otel-ai-cost"
(cd "$ROOT/bets/e-otel-ai-cost" && npm run smoke --silent)
echo "==> [F] f-cn-work-agent"
(cd "$ROOT/bets/f-cn-work-agent" && PYTHONPATH=src python3 -m cn_work_agent smoke)
echo "==> [k8s] deploy/k8s manifests"
bash "$ROOT/scripts/check-k8s.sh"
echo "==> [helm] deploy/helm chart"
bash "$ROOT/scripts/check-helm.sh"
echo "==> [dockerfiles] bets B–F"
bash "$ROOT/scripts/check-dockerfiles.sh"
echo "==> [gha-examples] examples/github-actions"
bash "$ROOT/scripts/check-gha-examples.sh"
echo "==> [mcp-examples] examples/mcp HTTP client config"
bash "$ROOT/scripts/check-mcp-examples.sh"
echo "==> [grafana] deploy/grafana dashboards"
bash "$ROOT/scripts/check-grafana.sh"
echo "==> [prom-rules] deploy/prometheus + prometheusrule.yaml"
bash "$ROOT/scripts/check-prometheus-rules.sh"
echo "==> [oss-hygiene] NOTICE + .editorconfig + SECURITY.md + CODE_OF_CONDUCT.md"
bash "$ROOT/scripts/check-oss-hygiene.sh"
echo
echo "All smoke tests finished."
