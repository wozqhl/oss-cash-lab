#!/usr/bin/env bash
# File-based A -> B integration:
#   A generate petstore OpenAPI -> mcp-tools.json
#   merge into B policy (tools + allowlist)
#   prove via B /tools/list that generated tools appear
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
A="$ROOT/bets/a-sdk-mcp-gen"
B="$ROOT/bets/b-mcp-gateway"
OUT="$ROOT/out/wire-a-to-b"
PORT="${PORT:-18787}"
SPEC="${SPEC:-$A/examples/petstore.openapi.yaml}"

rm -rf "$OUT"
mkdir -p "$OUT/a-out" "$OUT/b-config" "$OUT/data"

echo "==> [A] generate from $SPEC"
(cd "$A" && node src/cli.js generate "$SPEC" --out "$OUT/a-out")
test -f "$OUT/a-out/mcp-tools.json"

echo "==> merge into B policy"
node --input-type=module -e '
import fs from "node:fs";
const toolsDoc = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
const base = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const genTools = toolsDoc.tools || [];
const byName = new Map((base.tools || []).map((t) => [t.name, t]));
for (const t of genTools) byName.set(t.name, t);
const tools = [...byName.values()];
const allow = new Set(base.allow || []);
for (const t of genTools) {
  if (t.name !== "deletePet") allow.add(t.name);
}
const deny = new Set(base.deny || []);
deny.add("deletePet");
const tenants = (base.tenants || []).map((t) => {
  const tAllow = new Set(t.allow || [...allow]);
  for (const tool of genTools) {
    if (tool.name !== "deletePet") tAllow.add(tool.name);
  }
  const tDeny = new Set(t.deny || []);
  tDeny.add("deletePet");
  return { ...t, allow: [...tAllow], deny: [...tDeny] };
});
const policy = {
  ...base,
  allow: [...allow],
  deny: [...deny],
  tools,
  tenants,
  source: "wire-a-to-b",
};
fs.writeFileSync(process.argv[3], JSON.stringify(policy, null, 2) + "\n");
console.log(JSON.stringify({ tools: tools.length, allow: policy.allow, generated: genTools.map((t) => t.name) }));
' "$OUT/a-out/mcp-tools.json" "$B/config/policy.json" "$OUT/b-config/policy.json"

echo "==> [B] serve wired policy on :$PORT"
(cd "$B" && node src/cli.js serve --port "$PORT" --config "$OUT/b-config/policy.json" --audit "$OUT/data/audit.jsonl") >"$OUT/data/server.log" 2>&1 &
PID=$!
cleanup() { kill "$PID" 2>/dev/null || true; wait "$PID" 2>/dev/null || true; }
trap cleanup EXIT

for i in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null; then break; fi
  sleep 0.1
done

# Prefer first tenant apiKey from wired policy when present (paid multi-tenant sketch)
API_KEY="$(node --input-type=module -e 'import fs from "node:fs"; const p=JSON.parse(fs.readFileSync(process.argv[1],"utf8")); const t=(p.tenants||[])[0]; process.stdout.write(t&&t.apiKey?t.apiKey:"");' "$OUT/b-config/policy.json")"
AUTH_ARGS=()
if [ -n "$API_KEY" ]; then
  AUTH_ARGS=(-H "Authorization: Bearer $API_KEY")
fi

LIST="$(curl -sf -X POST "http://127.0.0.1:$PORT/tools/list" -H 'content-type: application/json' "${AUTH_ARGS[@]}" -d '{}')"
echo "list=$LIST"
echo "$LIST" | grep -q '"name":"listPets"'
echo "$LIST" | grep -q '"name":"getPet"'
echo "$LIST" | grep -q '"name":"createPet"'
if echo "$LIST" | grep -q '"name":"deletePet"'; then
  echo "deletePet should stay denied/hidden"
  exit 1
fi

# call one generated tool through gateway (upstream mock is fine)
CALL="$(curl -sf -X POST "http://127.0.0.1:$PORT/tools/call" -H 'content-type: application/json' "${AUTH_ARGS[@]}" -d '{"name":"listPets","arguments":{}}')"
echo "call=$CALL"
echo "$CALL" | grep -q '"ok":true'

echo "wire-a-to-b OK — generated tools visible in B /tools/list"
