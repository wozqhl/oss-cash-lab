#!/usr/bin/env bash
# Petstore SDK+MCP demo: generate into out/demo, print key files, exit 0.
# Runnable: bash scripts/demo.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

OUT="${DEMO_OUT:-$ROOT/out/demo}"
rm -rf "$OUT"
mkdir -p "$(dirname "$OUT")"

echo "==> generate petstore SDK+MCP -> $OUT"
node src/cli.js generate examples/petstore.openapi.json --out "$OUT"

# Tiny assertion: generate wrote the three files a human came to see.
for f in client.ts mcp-server.mjs mcp.json; do
  if [ ! -s "$OUT/$f" ]; then
    echo "demo: generate did not write $OUT/$f" >&2
    exit 1
  fi
done

for f in client.ts mcp-server.mjs mcp.json; do
  echo
  echo "======== $f ========"
  cat "$OUT/$f"
  echo
done

echo "demo ok: $OUT (client.ts, mcp-server.mjs, mcp.json)"
