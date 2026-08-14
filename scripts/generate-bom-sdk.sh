#!/usr/bin/env bash
# Dogfood A on D: generate TS/Python/Go clients from D ai-bom OpenAPI.
# Output is regenerated (not committed) under bets/d-ai-bom/sdk/generated/.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
A="$ROOT/bets/a-sdk-mcp-gen"
SPEC="${SPEC:-$ROOT/bets/d-ai-bom/openapi/bom.openapi.json}"
OUT="${OUT:-$ROOT/bets/d-ai-bom/sdk/generated}"
LANGS="${LANGS:-ts,python,go}"

if [ ! -f "$SPEC" ]; then
  echo "missing D OpenAPI: $SPEC" >&2
  exit 1
fi
if [ ! -f "$A/src/cli.js" ]; then
  echo "missing A CLI: $A/src/cli.js" >&2
  exit 1
fi

# Require operationIds on every path operation (A falls back, but dogfood wants real ids)
node --input-type=module -e '
import fs from "node:fs";
const spec = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
const missing = [];
let total = 0;
for (const [p, item] of Object.entries(spec.paths || {})) {
  for (const m of ["get", "post", "put", "patch", "delete"]) {
    const op = item?.[m];
    if (!op) continue;
    total++;
    if (!op.operationId) missing.push(`${m.toUpperCase()} ${p}`);
  }
}
if (!total) {
  console.error("D OpenAPI has zero path operations");
  process.exit(1);
}
if (missing.length) {
  console.error("D OpenAPI missing operationId:", missing.join(", "));
  process.exit(1);
}
console.log(JSON.stringify({ openapi_ops: total, operationIds_ok: true }));
' "$SPEC"

rm -rf "$OUT"
mkdir -p "$OUT"

echo "==> [A] generate from D OpenAPI -> $OUT (--lang $LANGS)"
(cd "$A" && node src/cli.js generate "$SPEC" --out "$OUT" --lang "$LANGS")

test -f "$OUT/client.ts"
test -f "$OUT/client.py"
test -f "$OUT/client.go"
test -f "$OUT/mcp-tools.json"

# Assert tool/ops count > 0 and clients mention BOM ops
node --input-type=module -e '
import fs from "node:fs";
import path from "node:path";
const out = process.argv[1];
const toolsDoc = JSON.parse(fs.readFileSync(path.join(out, "mcp-tools.json"), "utf8"));
const tools = toolsDoc.tools || [];
if (!tools.length) {
  console.error("mcp-tools.json has zero tools");
  process.exit(1);
}
const names = new Set(tools.map((t) => t.name));
for (const need of ["getHealth", "getBom", "getEvidence", "getIndex", "getMetrics", "getOpenApi"]) {
  if (!names.has(need)) {
    console.error("missing expected op/tool:", need, "have:", [...names].join(","));
    process.exit(1);
  }
}
const ts = fs.readFileSync(path.join(out, "client.ts"), "utf8");
const py = fs.readFileSync(path.join(out, "client.py"), "utf8");
const go = fs.readFileSync(path.join(out, "client.go"), "utf8");
for (const [label, src, needle] of [
  ["client.ts", ts, "getBom"],
  ["client.py", py, "getBom"],
  ["client.go", go, "GetBom"],
]) {
  if (!src.includes(needle)) {
    console.error(label, "missing", needle);
    process.exit(1);
  }
}
if (!go.includes("package client") || !go.includes("net/http")) {
  console.error("client.go missing package client / net/http");
  process.exit(1);
}
console.log(JSON.stringify({
  out,
  tools: tools.length,
  ops: tools.length,
  sample: [...names].slice(0, 5),
}));
' "$OUT"

# Python syntax check (stdlib client; no bytecode litter)
PYTHONDONTWRITEBYTECODE=1 python3 -c 'import py_compile,sys; py_compile.compile(sys.argv[1], doraise=True)' "$OUT/client.py"
rm -rf "$OUT/__pycache__"

echo "dogfood-a-d OK — A clients from D OpenAPI (tools>0) at $OUT"
