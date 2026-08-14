#!/usr/bin/env bash
# docker compose up + curl checks, or skip when Docker is unavailable.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

have_compose() {
  if ! command -v docker >/dev/null 2>&1; then
    return 1
  fi
  if docker compose version >/dev/null 2>&1; then
    return 0
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  else
    docker-compose "$@"
  fi
}

if ! have_compose; then
  echo "skip: docker compose not available on this box"
  echo "hint: use make stack-demo (scripts/local-stack.sh) instead"
  exit 0
fi

echo "==> docker compose up -d --build"
compose up -d --build

cleanup() {
  compose down --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

wait_health() {
  local name="$1" url="$2"
  local i
  for i in $(seq 1 90); do
    if curl -sf "$url" >/dev/null; then
      echo "ready $name $url"
      return 0
    fi
    sleep 0.5
  done
  echo "TIMEOUT waiting for $name ($url)" >&2
  compose ps >&2 || true
  compose logs >&2 || true
  return 1
}

wait_health mcp-gateway "http://127.0.0.1:8787/health"
wait_health agent-ci "http://127.0.0.1:8791/health"
wait_health cn-work-agent "http://127.0.0.1:8790/health"
wait_health otel-ai-cost "http://127.0.0.1:8792/health"
wait_health ai-bom "http://127.0.0.1:8793/health"

GW_H="$(curl -sf "http://127.0.0.1:8787/health")"
echo "mcp-gateway=$GW_H"
echo "$GW_H" | grep -q mcp-gateway
echo "$GW_H" | grep -q acme
echo "$GW_H" | grep -q '"connected":true\|"connected": true'

CI_H="$(curl -sf "http://127.0.0.1:8791/health")"
echo "agent-ci=$CI_H"
echo "$CI_H" | grep -q agent-ci

F_H="$(curl -sf "http://127.0.0.1:8790/health")"
echo "cn-work-agent=$F_H"
echo "$F_H" | grep -q feishu

E_H="$(curl -sf "http://127.0.0.1:8792/health")"
echo "otel-ai-cost=$E_H"
echo "$E_H" | grep -q otel-ai-cost

D_H="$(curl -sf "http://127.0.0.1:8793/health")"
echo "ai-bom=$D_H"
echo "$D_H" | grep -q ai-bom
D_BOM="$(curl -sf "http://127.0.0.1:8793/bom.json")"
echo "$D_BOM" | grep -q MIT

LIST="$(curl -sf -X POST "http://127.0.0.1:8787/tools/list" \
  -H 'content-type: application/json' \
  -H 'Authorization: Bearer ten_acme_dev' \
  -d '{}')"
echo "tools/list=$LIST"
echo "$LIST" | grep -q upstreamPing

PROXY="$(curl -sf -X POST "http://127.0.0.1:8787/tools/call" \
  -H 'content-type: application/json' \
  -H 'Authorization: Bearer ten_acme_dev' \
  -d '{"name":"upstreamPing","arguments":{"note":"compose-smoke"}}')"
echo "tools/call=$PROXY"
echo "$PROXY" | grep -q mock-upstream

echo
echo "compose-smoke OK"
