#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
echo "==> [A] a-sdk-mcp-gen local-mvp"
(cd "$ROOT/bets/a-sdk-mcp-gen" && bash scripts/local-mvp.sh)
echo "==> [B] b-mcp-gateway local-mvp"
(cd "$ROOT/bets/b-mcp-gateway" && bash scripts/local-mvp.sh)
echo "==> [C] c-agent-ci local-mvp"
(cd "$ROOT/bets/c-agent-ci" && bash scripts/local-mvp.sh)
echo "==> [D] d-ai-bom local-mvp"
(cd "$ROOT/bets/d-ai-bom" && bash scripts/local-mvp.sh)
echo "==> [E] e-otel-ai-cost local-mvp"
(cd "$ROOT/bets/e-otel-ai-cost" && bash scripts/local-mvp.sh)
echo "==> [F] f-cn-work-agent local-mvp"
(cd "$ROOT/bets/f-cn-work-agent" && bash scripts/local-mvp.sh)
echo "==> [A->B] wire-a-to-b"
bash "$ROOT/scripts/wire-a-to-b.sh"
echo "==> [A->B] dogfood-a-b (A generate from B OpenAPI)"
bash "$ROOT/scripts/generate-gateway-sdk.sh"
echo "==> [A->C] dogfood-a-c (A generate from C OpenAPI)"
bash "$ROOT/scripts/generate-runner-sdk.sh"
echo "==> [A->D] dogfood-a-d (A generate from D OpenAPI)"
bash "$ROOT/scripts/generate-bom-sdk.sh"
echo "==> [A->E] dogfood-a-e (A generate from E OpenAPI)"
bash "$ROOT/scripts/generate-cost-sdk.sh"
echo "==> [A->F] dogfood-a-f (A generate from F OpenAPI)"
bash "$ROOT/scripts/generate-agent-sdk.sh"
echo
echo "All local-mvp checks finished."
