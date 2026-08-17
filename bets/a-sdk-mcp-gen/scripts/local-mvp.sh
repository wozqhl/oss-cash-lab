#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

node src/cli.js smoke

rm -rf out/petstore out/petstore-yaml out/petstore-ts-only out/petstore-go-only out/petstore-java-only out/petstore-rust-only out/petstore-csharp-only out/petstore-kotlin-only out/petstore-swift-only out/petstore-ruby-only out/petstore-php-only out/petstore-baseline out/petstore-breaking out/petstore-breaking-gen out/petstore-restored out/petstore-restored-gen out/petstore-watch out/petstore-watch-spec.json out/watch.log out/petstore-mutated.openapi.json out/petstore-dry-run out/dry-run.json out/dry-run-ts.json out/petstore-dry-run-keep out/mcp-list.json out/mcp-list-py.json out/mcp-list-go.json out/petstore-pkg out/dry-run-pkg.json out/mcp-list-pkg.json out/openapi-3.1-mini out/mcp-list-31.json out/mcp-list-31-py.json out/mcp-list-31-go.json out/petstore-url out/dry-run-url.json out/mcp-list-url.json out/mcp-list-url-py.json out/mcp-list-url-go.json out/url-http.log out/petstore-url-auth out/petstore-url-envhdr out/dry-run-url-auth.json out/url-auth.out out/url-auth.err out/url-noauth.err out/hdr-nourl.err out/url-auth-http.log out/petstore-no-mcp out/petstore-no-mcp-dry out/dry-run-no-mcp.json out/petstore-watch-url out/watch-url.log out/url-watch-http.log out/petstore-zip out/dry-run-zip.json out/petstore-no-license out/petstore-no-license-dry out/dry-run-no-license.json out/petstore-no-gitignore out/petstore-no-gitignore-dry out/dry-run-no-gitignore.json
echo "==> generate --dry-run (no writes; default langs include client.ts)"
rm -rf out/petstore-dry-run out/dry-run.json out/dry-run-ts.json out/petstore-dry-run-keep
mkdir -p out
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-dry-run --dry-run > out/dry-run.json
if [ -e out/petstore-dry-run ]; then
  echo "dry-run must not create --out dir" >&2
  ls -la out/petstore-dry-run >&2 || true
  exit 1
fi
node -e '
const j = require("./out/dry-run.json");
if (!Array.isArray(j.files)) { console.error("dry-run missing files[]", j); process.exit(1); }
const need = ["client.ts","package.json","client.py","client.go","Client.java","client.rs","Client.cs","Client.kt","Client.swift","client.rb","Client.php","mcp-tools.json","mcp-server.mjs","mcp_server.py","mcp_server.go","mcp.json","README.md","LICENSE","NOTICE",".gitignore","checksums.sha256"];
for (const n of need) {
  if (!j.files.includes(n)) { console.error("dry-run files missing", n, j.files); process.exit(1); }
}
if (!Array.isArray(j.langs) || !j.langs.includes("ts") || !j.langs.includes("python") || !j.langs.includes("php")) {
  console.error("dry-run langs should be default set", j.langs); process.exit(1);
}
if (typeof j.operations !== "number" || typeof j.tools !== "number") {
  console.error("dry-run operations/tools should be counts", j); process.exit(1);
}
if (j.operations < 1 || j.tools < 1) {
  console.error("dry-run operations/tools empty", j); process.exit(1);
}
if (j.packageName !== "client") { console.error("dry-run default packageName", j.packageName); process.exit(1); }
if (j.files.includes("sdk.tgz") || j.files.includes("sdk.zip")) { console.error("dry-run without --zip must not list archive", j.files); process.exit(1); }
console.log("dry-run default files ok ops="+j.operations+" tools="+j.tools+" nfiles="+j.files.length+" packageName="+j.packageName);
'
# existing dir with a marker must stay unchanged
mkdir -p out/petstore-dry-run-keep
printf 'keep\n' > out/petstore-dry-run-keep/keep.txt
KEEP_BEFORE=$(cksum out/petstore-dry-run-keep/keep.txt)
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-dry-run-keep --dry-run >/dev/null
KEEP_AFTER=$(cksum out/petstore-dry-run-keep/keep.txt)
if [ "$KEEP_BEFORE" != "$KEEP_AFTER" ]; then
  echo "dry-run mutated existing keep.txt" >&2
  exit 1
fi
if [ -f out/petstore-dry-run-keep/client.ts ] || [ -f out/petstore-dry-run-keep/mcp-tools.json ] || [ -f out/petstore-dry-run-keep/mcp-server.mjs ] || [ -f out/petstore-dry-run-keep/mcp_server.py ] || [ -f out/petstore-dry-run-keep/mcp_server.go ] || [ -f out/petstore-dry-run-keep/mcp.json ] || [ -f out/petstore-dry-run-keep/LICENSE ] || [ -f out/petstore-dry-run-keep/NOTICE ] || [ -f out/petstore-dry-run-keep/.gitignore ] || [ -f out/petstore-dry-run-keep/checksums.sha256 ]; then
  echo "dry-run wrote files into existing --out" >&2
  ls -la out/petstore-dry-run-keep >&2
  exit 1
fi
test "$(ls -A out/petstore-dry-run-keep)" = "keep.txt"
# --lang ts plan lists client.ts not other clients
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-dry-run --lang ts --dry-run > out/dry-run-ts.json
if [ -e out/petstore-dry-run ]; then
  echo "dry-run --lang ts must not create --out dir" >&2
  exit 1
fi
node -e '
const j = require("./out/dry-run-ts.json");
if (!j.files.includes("client.ts") || !j.files.includes("package.json")) { console.error("ts dry-run missing client.ts/package.json", j.files); process.exit(1); }
for (const n of ["client.py","client.go","Client.java","client.rs","Client.cs","Client.kt","Client.swift","client.rb","Client.php"]) {
  if (j.files.includes(n)) { console.error("ts dry-run should not list", n, j.files); process.exit(1); }
}
if (!j.files.includes("mcp-tools.json") || !j.files.includes("mcp-server.mjs") || !j.files.includes("mcp_server.py") || !j.files.includes("mcp_server.go") || !j.files.includes("mcp.json") || !j.files.includes("LICENSE") || !j.files.includes("NOTICE") || !j.files.includes(".gitignore") || !j.files.includes("checksums.sha256")) {
  console.error("ts dry-run missing shared artifacts", j.files); process.exit(1);
}
console.log("dry-run --lang ts files ok");
'
echo "dry-run OK (empty/unchanged + default langs include client.ts)"

node src/cli.js generate examples/petstore.openapi.json --out out/petstore

test -f out/petstore/client.ts
test -f out/petstore/package.json
test -f out/petstore/client.py
test -f out/petstore/client.go
test -f out/petstore/Client.java
test -f out/petstore/client.rs
test -f out/petstore/Client.cs
test -f out/petstore/Client.kt
test -f out/petstore/Client.swift
test -f out/petstore/client.rb
test -f out/petstore/Client.php
test -f out/petstore/mcp-tools.json
test -f out/petstore/mcp-server.mjs
test -f out/petstore/mcp_server.py
test -f out/petstore/mcp_server.go
test -f out/petstore/mcp.json
test -f out/petstore/README.md
test -f out/petstore/LICENSE
test -f out/petstore/NOTICE
test -f out/petstore/.gitignore
grep -q 'Apache' out/petstore/LICENSE
grep -q 'client' out/petstore/NOTICE
grep -q 'Apache License, Version 2.0' out/petstore/NOTICE
grep -F 'node_modules' out/petstore/.gitignore
grep -F '__pycache__/' out/petstore/.gitignore
grep -F '*.pyc' out/petstore/.gitignore
grep -F '.DS_Store' out/petstore/.gitignore
grep -F '*.egg-info/' out/petstore/.gitignore
test -f out/petstore/checksums.sha256
test ! -f out/petstore/sdk.tgz
test ! -f out/petstore/sdk.zip

echo "==> checksums.sha256 (verify OK / tweak fail / regenerate restore)"
node src/cli.js verify-checksums --out out/petstore
# only existing candidates listed
grep -q 'client.ts' out/petstore/checksums.sha256
grep -q 'package.json' out/petstore/checksums.sha256
grep -q 'client.py' out/petstore/checksums.sha256
grep -q 'client.go' out/petstore/checksums.sha256
grep -q 'Client.java' out/petstore/checksums.sha256
grep -q 'client.rs' out/petstore/checksums.sha256
grep -q 'Client.cs' out/petstore/checksums.sha256
grep -q 'Client.kt' out/petstore/checksums.sha256
grep -q 'Client.swift' out/petstore/checksums.sha256
grep -q 'client.rb' out/petstore/checksums.sha256
grep -q 'Client.php' out/petstore/checksums.sha256
grep -q 'mcp-tools.json' out/petstore/checksums.sha256
grep -q 'mcp-server.mjs' out/petstore/checksums.sha256
grep -q 'mcp_server.py' out/petstore/checksums.sha256
grep -q 'mcp_server.go' out/petstore/checksums.sha256
grep -q 'mcp.json' out/petstore/checksums.sha256
grep -q 'README.md' out/petstore/checksums.sha256
grep -q 'LICENSE' out/petstore/checksums.sha256
grep -q 'NOTICE' out/petstore/checksums.sha256
grep -F '.gitignore' out/petstore/checksums.sha256
# tweak one generated file → verify must fail
printf '\n// checksum-tweak\n' >> out/petstore/client.ts
set +e
node src/cli.js verify-checksums --out out/petstore
TWEAK_RC=$?
set -e
if [ "$TWEAK_RC" -eq 0 ]; then
  echo "expected verify-checksums to fail after tweaking client.ts" >&2
  exit 1
fi
echo "verify_checksums_tweak_rc=$TWEAK_RC (expected non-zero)"
# regenerate restores matching checksums
node src/cli.js generate examples/petstore.openapi.json --out out/petstore
node src/cli.js verify-checksums --out out/petstore
echo "checksums OK (match, fail on tweak, restore)"

echo "==> generate --dry-run leaves existing out/petstore unchanged"
node src/cli.js verify-checksums --out out/petstore
node src/cli.js generate examples/petstore.openapi.json --out out/petstore --dry-run >/dev/null
node src/cli.js verify-checksums --out out/petstore
echo "dry-run unchanged checksums OK"

OPS=$(node -e 'const s=require("./examples/petstore.openapi.json"); let n=0; for (const p of Object.values(s.paths||{})) for (const m of ["get","post","put","patch","delete"]) if (p[m]) n++; console.log(n)')
TOOLS=$(node -e 'const t=require("./out/petstore/mcp-tools.json"); console.log(t.tools.length)')
echo "ops=$OPS tools=$TOOLS"
test "$OPS" = "$TOOLS"
grep -q 'listPets' out/petstore/client.ts
grep -q 'createPet' out/petstore/client.ts
grep -q 'getPet' out/petstore/client.ts
grep -q 'deletePet' out/petstore/client.ts
grep -q 'function retryDelayMs' out/petstore/client.ts
grep -q '429' out/petstore/client.ts
grep -q 'Retry-After' out/petstore/client.ts
grep -q 'def _retry_delay_s' out/petstore/client.py
grep -q '429' out/petstore/client.py
grep -q 'func retryDelay' out/petstore/client.go
grep -q '429' out/petstore/client.go

echo "==> mcp-server.mjs stdio JSON-RPC tools/list"
if grep -q '@modelcontextprotocol/sdk' out/petstore/mcp-server.mjs; then
  echo "mcp-server.mjs must not depend on @modelcontextprotocol/sdk" >&2
  exit 1
fi
grep -q 'listPets' out/petstore/mcp-server.mjs
grep -q 'tools/list' out/petstore/mcp-server.mjs
grep -q 'MCP_BASE_URL' out/petstore/mcp-server.mjs
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | node out/petstore/mcp-server.mjs > out/mcp-list.json
node -e '
const fs = require("fs");
const raw = fs.readFileSync("out/mcp-list.json", "utf8").trim();
const line = raw.split(/\n/).filter(Boolean).pop();
const msg = JSON.parse(line);
const names = (msg.result && msg.result.tools || []).map((t) => t.name);
for (const n of ["listPets", "createPet", "getPet", "deletePet"]) {
  if (!names.includes(n)) {
    console.error("mcp tools/list missing", n, names);
    process.exit(1);
  }
}
console.log("mcp tools/list ok " + names.join(","));
'
echo "mcp-server.mjs stdio OK"

echo "==> mcp.json client config snippet"
node -e '
const fs = require("fs");
const j = JSON.parse(fs.readFileSync("out/petstore/mcp.json", "utf8"));
if (!j.mcpServers || typeof j.mcpServers !== "object") {
  console.error("mcp.json missing mcpServers", j);
  process.exit(1);
}
const nodeEntry = Object.values(j.mcpServers).find((e) => e && e.command === "node");
if (!nodeEntry) {
  console.error("mcp.json missing command node", j);
  process.exit(1);
}
if (!Array.isArray(nodeEntry.args) || !nodeEntry.args.some((a) => String(a).includes("mcp-server.mjs"))) {
  console.error("mcp.json node args missing mcp-server.mjs", nodeEntry);
  process.exit(1);
}
if (!nodeEntry.args.includes("./mcp-server.mjs")) {
  console.error("mcp.json args should be relative ./mcp-server.mjs", nodeEntry.args);
  process.exit(1);
}
if (!nodeEntry.env || !nodeEntry.env.MCP_BASE_URL) {
  console.error("mcp.json missing env MCP_BASE_URL", nodeEntry);
  process.exit(1);
}
const py = Object.values(j.mcpServers).find((e) => e && e.command === "python3");
if (!py || !Array.isArray(py.args) || !py.args.includes("./mcp_server.py")) {
  console.error("mcp.json missing python3 ./mcp_server.py", j);
  process.exit(1);
}
if (!j.mcpServers.petstore) {
  console.error("mcp.json key should be petstore from title", Object.keys(j.mcpServers));
  process.exit(1);
}
console.log("mcp.json ok keys=" + Object.keys(j.mcpServers).join(","));
'
echo "mcp.json OK"

echo "==> mcp_server.py stdio JSON-RPC tools/list"
if grep -qE 'import requests|from requests' out/petstore/mcp_server.py; then
  echo "mcp_server.py must be requests-free (stdlib urllib only)" >&2
  exit 1
fi
head -n 1 out/petstore/mcp_server.py | grep -q '#!/usr/bin/env python3'
grep -q 'listPets' out/petstore/mcp_server.py
grep -q 'tools/list' out/petstore/mcp_server.py
grep -q 'MCP_BASE_URL' out/petstore/mcp_server.py
grep -q 'urllib.request' out/petstore/mcp_server.py
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile out/petstore/mcp_server.py
rm -rf out/petstore/__pycache__
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | python3 out/petstore/mcp_server.py > out/mcp-list-py.json
node -e '
const fs = require("fs");
const raw = fs.readFileSync("out/mcp-list-py.json", "utf8").trim();
const line = raw.split(/\n/).filter(Boolean).pop();
const msg = JSON.parse(line);
const names = (msg.result && msg.result.tools || []).map((t) => t.name);
for (const n of ["listPets", "createPet", "getPet", "deletePet"]) {
  if (!names.includes(n)) {
    console.error("mcp py tools/list missing", n, names);
    process.exit(1);
  }
}
const jsRaw = fs.readFileSync("out/mcp-list.json", "utf8").trim();
const jsLine = jsRaw.split(/\n/).filter(Boolean).pop();
const jsMsg = JSON.parse(jsLine);
const jsNames = (jsMsg.result && jsMsg.result.tools || []).map((t) => t.name);
if (JSON.stringify(names) !== JSON.stringify(jsNames)) {
  console.error("mcp py tools/list names mismatch js", names, jsNames);
  process.exit(1);
}
console.log("mcp py tools/list ok " + names.join(","));
'
echo "mcp_server.py stdio OK"

echo "==> mcp_server.go stdio JSON-RPC tools/list"
test -f out/petstore/mcp_server.go
grep -q 'package main' out/petstore/mcp_server.go
grep -q 'net/http' out/petstore/mcp_server.go
grep -q 'encoding/json' out/petstore/mcp_server.go
grep -q 'listPets' out/petstore/mcp_server.go
grep -q 'tools/list' out/petstore/mcp_server.go
grep -q 'initialize' out/petstore/mcp_server.go
grep -q 'tools/call' out/petstore/mcp_server.go
grep -q 'MCP_BASE_URL' out/petstore/mcp_server.go
if command -v go >/dev/null 2>&1; then
  printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | go run out/petstore/mcp_server.go > out/mcp-list-go.json
  node -e '
const fs = require("fs");
const raw = fs.readFileSync("out/mcp-list-go.json", "utf8").trim();
const line = raw.split(/\n/).filter(Boolean).pop();
const msg = JSON.parse(line);
const names = (msg.result && msg.result.tools || []).map((t) => t.name);
for (const n of ["listPets", "createPet", "getPet", "deletePet"]) {
  if (!names.includes(n)) {
    console.error("mcp go tools/list missing", n, names);
    process.exit(1);
  }
}
const jsRaw = fs.readFileSync("out/mcp-list.json", "utf8").trim();
const jsLine = jsRaw.split(/\n/).filter(Boolean).pop();
const jsMsg = JSON.parse(jsLine);
const jsNames = (jsMsg.result && jsMsg.result.tools || []).map((t) => t.name);
if (JSON.stringify(names) !== JSON.stringify(jsNames)) {
  console.error("mcp go tools/list names mismatch js", names, jsNames);
  process.exit(1);
}
console.log("mcp go tools/list ok " + names.join(","));
'
  echo "mcp_server.go stdio OK (go run)"
else
  echo "go toolchain not installed — skipped go run mcp_server.go (file exists + tools/list strings OK)"
fi


echo "==> python client"
python3 -m py_compile out/petstore/client.py
PY_FUNCS=$(python3 - <<'PY'
import ast, pathlib
src = pathlib.Path("out/petstore/client.py").read_text()
tree = ast.parse(src)
ops = {"listPets", "createPet", "getPet", "deletePet"}
# count Client methods that match operation ids
found = set()
for node in tree.body:
    if isinstance(node, ast.ClassDef) and node.name == "Client":
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name in ops:
                found.add(item.name)
print(len(found))
if found != ops:
    raise SystemExit(f"missing ops in client.py: {ops - found}")
PY
)
echo "py_funcs=$PY_FUNCS"
test "$PY_FUNCS" = "$OPS"
grep -q 'listPets' out/petstore/client.py
grep -q 'urllib.request' out/petstore/client.py
grep -vq 'import requests' out/petstore/client.py || true
# ensure requests-free
if grep -q 'import requests' out/petstore/client.py; then
  echo "client.py must be requests-free" >&2
  exit 1
fi

echo "==> go client"
test -f out/petstore/client.go
grep -q 'package client' out/petstore/client.go
grep -q 'net/http' out/petstore/client.go
grep -q 'func (c \*Client) ListPets' out/petstore/client.go
grep -q 'func (c \*Client) CreatePet' out/petstore/client.go
grep -q 'func (c \*Client) GetPet' out/petstore/client.go
grep -q 'func (c \*Client) DeletePet' out/petstore/client.go
# lightweight validity: package + brace balance + exported ops
python3 - <<'PY'
from pathlib import Path
import re
src = Path("out/petstore/client.go").read_text()
if "package client" not in src:
    raise SystemExit("client.go missing package client")
if "net/http" not in src:
    raise SystemExit("client.go missing net/http")
for name in ("ListPets", "CreatePet", "GetPet", "DeletePet"):
    if f"func (c *Client) {name}" not in src:
        raise SystemExit(f"client.go missing exported method {name}")
# strip strings/raw comments roughly then count braces
stripped = re.sub(r"`[^`]*`", "", src)
stripped = re.sub(r'"([^"\\]|\\.)*"', '""', stripped)
stripped = re.sub(r"//.*?$", "", stripped, flags=re.M)
stripped = re.sub(r"/\*.*?\*/", "", stripped, flags=re.S)
if stripped.count("{") != stripped.count("}"):
    raise SystemExit(
        f"client.go brace imbalance: {{={stripped.count('{')} }}={stripped.count('}')}"
    )
if stripped.count("(") != stripped.count(")"):
    raise SystemExit(
        f"client.go paren imbalance: (= {stripped.count('(')} )={stripped.count(')')}"
    )
print("go_syntax_heuristic_ok")
PY
if command -v go >/dev/null 2>&1; then
  echo "go toolchain present — gofmt -e + go vet"
  gofmt -e out/petstore/client.go >/dev/null
  TMPGO=$(mktemp -d)
  cp out/petstore/client.go "$TMPGO/client.go"
  (
    cd "$TMPGO"
    go mod init example.com/sdkmcpgen/client >/dev/null 2>&1
    go vet .
  )
  rm -rf "$TMPGO"
  echo "go_vet_ok"
else
  echo "go toolchain not installed — skipped gofmt/go vet (file exists + heuristic OK)"
fi


echo "==> java client"
test -f out/petstore/Client.java
grep -q 'package client' out/petstore/Client.java
grep -q 'HttpURLConnection' out/petstore/Client.java
grep -q 'public class Client' out/petstore/Client.java
grep -q 'public Object listPets' out/petstore/Client.java
grep -q 'public Object createPet' out/petstore/Client.java
grep -q 'public Object getPet' out/petstore/Client.java
grep -q 'public Object deletePet' out/petstore/Client.java
python3 - <<'JAVAPY'
from pathlib import Path
import re
src = Path("out/petstore/Client.java").read_text()
if "package client" not in src:
    raise SystemExit("Client.java missing package client")
if "HttpURLConnection" not in src:
    raise SystemExit("Client.java missing HttpURLConnection")
if "public class Client" not in src:
    raise SystemExit("Client.java missing public class Client")
for name in ("listPets", "createPet", "getPet", "deletePet"):
    if f"public Object {name}" not in src:
        raise SystemExit(f"Client.java missing public method {name}")
# char literals first so '"' does not start a fake string
stripped = re.sub(r"'([^'\\]|\\.)'", "''", src)
stripped = re.sub(r'"([^"\\]|\\.)*"', '""', stripped)
stripped = re.sub(r"//.*?$", "", stripped, flags=re.M)
stripped = re.sub(r"/\*.*?\*/", "", stripped, flags=re.S)
if stripped.count("{") != stripped.count("}"):
    raise SystemExit(
        f"Client.java brace imbalance: {{={stripped.count('{')} }}={stripped.count('}')}"
    )
if stripped.count("(") != stripped.count(")"):
    raise SystemExit(
        f"Client.java paren imbalance: (= {stripped.count('(')} )={stripped.count(')')}"
    )
print("java_syntax_heuristic_ok")
JAVAPY
if command -v javac >/dev/null 2>&1; then
  echo "javac present — compile Client.java"
  TMPJAVA=$(mktemp -d)
  cp out/petstore/Client.java "$TMPJAVA/Client.java"
  (
    cd "$TMPJAVA"
    javac Client.java
  )
  rm -rf "$TMPJAVA"
  echo "javac_ok"
else
  echo "javac not installed — skipped compile (file exists + heuristic OK)"
fi


echo "==> rust client"
test -f out/petstore/client.rs
grep -q 'pub struct Client' out/petstore/client.rs
grep -q 'TcpStream' out/petstore/client.rs
grep -q 'pub fn list_pets' out/petstore/client.rs
grep -q 'pub fn create_pet' out/petstore/client.rs
grep -q 'pub fn get_pet' out/petstore/client.rs
grep -q 'pub fn delete_pet' out/petstore/client.rs
python3 - <<'RUSTPY'
from pathlib import Path
import re
src = Path("out/petstore/client.rs").read_text()
if "pub struct Client" not in src:
    raise SystemExit("client.rs missing pub struct Client")
if "TcpStream" not in src:
    raise SystemExit("client.rs missing TcpStream")
for name in ("list_pets", "create_pet", "get_pet", "delete_pet"):
    if f"pub fn {name}" not in src:
        raise SystemExit(f"client.rs missing pub fn {name}")
# char/byte literals first so '"' does not start a fake string
stripped = re.sub(r"b?'([^'\\]|\\.)'", "''", src)
stripped = re.sub(r'"([^"\\]|\\.)*"', '""', stripped)
stripped = re.sub(r"//.*?$", "", stripped, flags=re.M)
if stripped.count("{") != stripped.count("}"):
    raise SystemExit(
        f"client.rs brace imbalance: {{={stripped.count('{')} }}={stripped.count('}')}"
    )
if stripped.count("(") != stripped.count(")"):
    raise SystemExit(
        f"client.rs paren imbalance: (= {stripped.count('(')} )={stripped.count(')')}"
    )
print("rust_syntax_heuristic_ok")
RUSTPY
if command -v rustc >/dev/null 2>&1; then
  echo "rustc present — rustc --crate-type lib client.rs"
  TMPRS=$(mktemp -d)
  cp out/petstore/client.rs "$TMPRS/client.rs"
  (
    cd "$TMPRS"
    rustc --crate-type lib client.rs
  )
  rm -rf "$TMPRS"
  echo "rustc_ok"
else
  echo "rustc not installed — skipped compile (file exists + heuristic OK)"
fi



echo "==> csharp client"
test -f out/petstore/Client.cs
grep -q 'namespace Client' out/petstore/Client.cs
grep -q 'HttpClient' out/petstore/Client.cs
grep -q 'public class Client' out/petstore/Client.cs
grep -q 'public object ListPets' out/petstore/Client.cs
grep -q 'public object CreatePet' out/petstore/Client.cs
grep -q 'public object GetPet' out/petstore/Client.cs
grep -q 'public object DeletePet' out/petstore/Client.cs
python3 - <<'CSPY'
from pathlib import Path
import re
src = Path("out/petstore/Client.cs").read_text()
if "namespace Client" not in src:
    raise SystemExit("Client.cs missing namespace Client")
if "HttpClient" not in src:
    raise SystemExit("Client.cs missing HttpClient")
if "public class Client" not in src:
    raise SystemExit("Client.cs missing public class Client")
for name in ("ListPets", "CreatePet", "GetPet", "DeletePet"):
    if f"public object {name}" not in src:
        raise SystemExit(f"Client.cs missing public method {name}")
# char literals first so '"' does not start a fake string (same care as Java)
stripped = re.sub(r"'([^'\\]|\\.)'", "''", src)
stripped = re.sub(r'"([^"\\]|\\.)*"', '""', stripped)
stripped = re.sub(r"//.*?$", "", stripped, flags=re.M)
stripped = re.sub(r"/\*.*?\*/", "", stripped, flags=re.S)
if stripped.count("{") != stripped.count("}"):
    raise SystemExit(
        f"Client.cs brace imbalance: {{={stripped.count('{')} }}={stripped.count('}')}"
    )
if stripped.count("(") != stripped.count(")"):
    raise SystemExit(
        f"Client.cs paren imbalance: (= {stripped.count('(')} )={stripped.count(')')}"
    )
print("csharp_syntax_heuristic_ok")
CSPY
if command -v dotnet >/dev/null 2>&1; then
  echo "dotnet present — compile Client.cs"
  TMPCS=$(mktemp -d)
  cp out/petstore/Client.cs "$TMPCS/Client.cs"
  cat > "$TMPCS/GenClient.csproj" << 'EOF'
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net6.0</TargetFramework>
    <OutputType>Library</OutputType>
    <ImplicitUsings>disable</ImplicitUsings>
    <Nullable>disable</Nullable>
  </PropertyGroup>
</Project>
EOF
  (
    cd "$TMPCS"
    DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 dotnet build -nologo -v q
  )
  rm -rf "$TMPCS"
  echo "dotnet_ok"
elif command -v csc >/dev/null 2>&1; then
  echo "csc present — compile Client.cs"
  TMPCS=$(mktemp -d)
  cp out/petstore/Client.cs "$TMPCS/Client.cs"
  (
    cd "$TMPCS"
    csc /nologo /t:library /out:Client.dll Client.cs
  )
  rm -rf "$TMPCS"
  echo "csc_ok"
else
  echo "dotnet/csc not installed — skipped compile (file exists + heuristic OK)"
fi



echo "==> kotlin client"
test -f out/petstore/Client.kt
grep -q 'package client' out/petstore/Client.kt
grep -q 'HttpURLConnection' out/petstore/Client.kt
grep -q 'class Client' out/petstore/Client.kt
grep -q 'fun listPets' out/petstore/Client.kt
grep -q 'fun createPet' out/petstore/Client.kt
grep -q 'fun getPet' out/petstore/Client.kt
grep -q 'fun deletePet' out/petstore/Client.kt
if grep -qiE 'okhttp3|OkHttp|import[[:space:]]+okhttp' out/petstore/Client.kt; then
  echo "Client.kt must be okhttp-free" >&2
  exit 1
fi
python3 - <<'KTPY'
from pathlib import Path
import re
src = Path("out/petstore/Client.kt").read_text()
if "package client" not in src:
    raise SystemExit("Client.kt missing package client")
if "HttpURLConnection" not in src:
    raise SystemExit("Client.kt missing HttpURLConnection")
if "class Client" not in src:
    raise SystemExit("Client.kt missing class Client")
if any(x in src for x in ("okhttp3", "OkHttp", "import okhttp")):
    raise SystemExit("Client.kt must be okhttp-free")
for name in ("listPets", "createPet", "getPet", "deletePet"):
    if f"fun {name}" not in src:
        raise SystemExit(f"Client.kt missing fun {name}")
# char literals first so '"' does not start a fake string (same care as Java)
stripped = re.sub(r"'([^'\\]|\\.)'", "''", src)
stripped = re.sub(r'"([^"\\]|\\.)*"', '""', stripped)
stripped = re.sub(r"//.*?$", "", stripped, flags=re.M)
stripped = re.sub(r"/\*.*?\*/", "", stripped, flags=re.S)
if stripped.count("{") != stripped.count("}"):
    raise SystemExit(
        f"Client.kt brace imbalance: {{={stripped.count('{')} }}={stripped.count('}')}"
    )
if stripped.count("(") != stripped.count(")"):
    raise SystemExit(
        f"Client.kt paren imbalance: (= {stripped.count('(')} )={stripped.count(')')}"
    )
print("kotlin_syntax_heuristic_ok")
KTPY
if command -v kotlinc >/dev/null 2>&1; then
  echo "kotlinc present — compile Client.kt"
  TMPKT=$(mktemp -d)
  cp out/petstore/Client.kt "$TMPKT/Client.kt"
  (
    cd "$TMPKT"
    kotlinc Client.kt
  )
  rm -rf "$TMPKT"
  echo "kotlinc_ok"
else
  echo "kotlinc not installed — skipped compile (file exists + heuristic OK)"
fi



echo "==> swift client"
test -f out/petstore/Client.swift
grep -q 'import Foundation' out/petstore/Client.swift
grep -q 'URLSession' out/petstore/Client.swift
grep -qE 'class Client|struct Client' out/petstore/Client.swift
grep -q 'func listPets' out/petstore/Client.swift
grep -q 'func createPet' out/petstore/Client.swift
grep -q 'func getPet' out/petstore/Client.swift
grep -q 'func deletePet' out/petstore/Client.swift
if grep -qiE 'Alamofire|import[[:space:]]+Alamofire' out/petstore/Client.swift; then
  echo "Client.swift must be Alamofire-free" >&2
  exit 1
fi
python3 - <<'SWPY'
from pathlib import Path
import re
src = Path("out/petstore/Client.swift").read_text()
if "import Foundation" not in src:
    raise SystemExit("Client.swift missing import Foundation")
if "URLSession" not in src:
    raise SystemExit("Client.swift missing URLSession")
if "class Client" not in src and "struct Client" not in src:
    raise SystemExit("Client.swift missing class Client / struct Client")
if any(x.lower() in src.lower() for x in ("Alamofire", "import Alamofire")):
    raise SystemExit("Client.swift must be Alamofire-free")
for name in ("listPets", "createPet", "getPet", "deletePet"):
    if f"func {name}" not in src:
        raise SystemExit(f"Client.swift missing func {name}")
# strip strings then comments (same care as Kotlin/Java)
stripped = re.sub(r'"([^"\\]|\\.)*"', '""', src)
stripped = re.sub(r"//.*?$", "", stripped, flags=re.M)
stripped = re.sub(r"/\*.*?\*/", "", stripped, flags=re.S)
if stripped.count("{") != stripped.count("}"):
    raise SystemExit(
        f"Client.swift brace imbalance: {{={stripped.count('{')} }}={stripped.count('}')}"
    )
if stripped.count("(") != stripped.count(")"):
    raise SystemExit(
        f"Client.swift paren imbalance: (= {stripped.count('(')} )={stripped.count(')')}"
    )
print("swift_syntax_heuristic_ok")
SWPY
if command -v swiftc >/dev/null 2>&1; then
  echo "swiftc present — typecheck Client.swift"
  TMPSW=$(mktemp -d)
  cp out/petstore/Client.swift "$TMPSW/Client.swift"
  (
    cd "$TMPSW"
    swiftc -typecheck Client.swift
  )
  rm -rf "$TMPSW"
  echo "swiftc_ok"
else
  echo "swiftc not installed — skipped compile (file exists + heuristic OK)"
fi


echo "==> ruby client"
test -f out/petstore/client.rb
grep -q 'require "net/http"' out/petstore/client.rb
grep -q 'Net::HTTP' out/petstore/client.rb
grep -q 'class Client' out/petstore/client.rb
grep -q 'def list_pets' out/petstore/client.rb
grep -q 'def create_pet' out/petstore/client.rb
grep -q 'def get_pet' out/petstore/client.rb
grep -q 'def delete_pet' out/petstore/client.rb
if grep -qiE 'httparty|faraday|rest-client' out/petstore/client.rb; then
  echo "client.rb must be gem-free (stdlib Net::HTTP only)" >&2
  exit 1
fi
python3 - <<'RBPY'
from pathlib import Path
import re
src = Path("out/petstore/client.rb").read_text()
if 'require "net/http"' not in src:
    raise SystemExit("client.rb missing require net/http")
if "Net::HTTP" not in src:
    raise SystemExit("client.rb missing Net::HTTP")
if "class Client" not in src:
    raise SystemExit("client.rb missing class Client")
if any(x.lower() in src.lower() for x in ("httparty", "faraday", "rest-client")):
    raise SystemExit("client.rb must be gem-free")
for name in ("list_pets", "create_pet", "get_pet", "delete_pet"):
    if f"def {name}" not in src:
        raise SystemExit(f"client.rb missing def {name}")
# strip strings then comments (Ruby # comments; keep shebang-less)
stripped = re.sub(r'"([^"\\]|\\.)*"', '""', src)
stripped = re.sub(r"'([^'\\]|\\.)*'", "''", stripped)
stripped = re.sub(r"#.*?$", "", stripped, flags=re.M)
if stripped.count("{") != stripped.count("}"):
    raise SystemExit(
        f"client.rb brace imbalance: {{={stripped.count('{')} }}={stripped.count('}')}"
    )
if stripped.count("(") != stripped.count(")"):
    raise SystemExit(
        f"client.rb paren imbalance: (= {stripped.count('(')} )={stripped.count(')')}"
    )
print("ruby_syntax_heuristic_ok")
RBPY
if command -v ruby >/dev/null 2>&1; then
  echo "ruby present — ruby -c client.rb"
  ruby -c out/petstore/client.rb
  echo "ruby_c_ok"
else
  echo "ruby not installed — skipped ruby -c (file exists + heuristic OK)"
fi




echo "==> php client"
test -f out/petstore/Client.php
grep -q 'class Client' out/petstore/Client.php
grep -q 'fopen' out/petstore/Client.php
grep -q 'stream_context_create' out/petstore/Client.php
grep -q 'public function listPets' out/petstore/Client.php
grep -q 'public function createPet' out/petstore/Client.php
grep -q 'public function getPet' out/petstore/Client.php
grep -q 'public function deletePet' out/petstore/Client.php
if grep -qiE 'curl_init|curl_exec|curl_setopt' out/petstore/Client.php; then
  echo "Client.php must be curl-extension-free (stdlib fopen/stream only)" >&2
  exit 1
fi
python3 - <<'PHPPY'
from pathlib import Path
import re
src = Path("out/petstore/Client.php").read_text()
if "class Client" not in src:
    raise SystemExit("Client.php missing class Client")
if "fopen" not in src:
    raise SystemExit("Client.php missing fopen")
if "stream_context_create" not in src:
    raise SystemExit("Client.php missing stream_context_create")
if any(x in src for x in ("curl_init", "curl_exec", "curl_setopt")):
    raise SystemExit("Client.php must be curl-extension-free")
for name in ("listPets", "createPet", "getPet", "deletePet"):
    if f"public function {name}" not in src:
        raise SystemExit(f"Client.php missing public function {name}")
stripped = re.sub(r"'([^'\\]|\\.)*'", "''", src)
stripped = re.sub(r'"([^"\\]|\\.)*"', '""', stripped)
stripped = re.sub(r"//.*?$", "", stripped, flags=re.M)
stripped = re.sub(r"#.*?$", "", stripped, flags=re.M)
stripped = re.sub(r"/\*.*?\*/", "", stripped, flags=re.S)
if stripped.count("{") != stripped.count("}"):
    raise SystemExit(
        f"Client.php brace imbalance: {{={stripped.count('{')} }}={stripped.count('}')}"
    )
if stripped.count("(") != stripped.count(")"):
    raise SystemExit(
        f"Client.php paren imbalance: (= {stripped.count('(')} )={stripped.count(')')}"
    )
print("php_syntax_heuristic_ok")
PHPPY
if command -v php >/dev/null 2>&1; then
  echo "php present — php -l Client.php"
  php -l out/petstore/Client.php
  echo "php_l_ok"
else
  echo "php not installed — skipped php -l (file exists + heuristic OK)"
fi


echo "==> --lang ts only"
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-ts-only --lang ts
test -f out/petstore-ts-only/client.ts
test -f out/petstore-ts-only/package.json
test ! -f out/petstore-ts-only/client.py
test ! -f out/petstore-ts-only/client.go
test ! -f out/petstore-ts-only/Client.java
test ! -f out/petstore-ts-only/client.rs
test ! -f out/petstore-ts-only/Client.cs
test ! -f out/petstore-ts-only/Client.kt
test ! -f out/petstore-ts-only/Client.swift
test ! -f out/petstore-ts-only/client.rb
test ! -f out/petstore-ts-only/Client.php
test -f out/petstore-ts-only/mcp-tools.json
test -f out/petstore-ts-only/mcp-server.mjs
test -f out/petstore-ts-only/mcp_server.py
test -f out/petstore-ts-only/mcp_server.go
test -f out/petstore-ts-only/checksums.sha256
grep -q 'client.ts' out/petstore-ts-only/checksums.sha256
grep -q 'package.json' out/petstore-ts-only/checksums.sha256
if grep -q 'client.py' out/petstore-ts-only/checksums.sha256; then
  echo "ts-only checksums should not list client.py" >&2
  exit 1
fi
if grep -q 'client.go' out/petstore-ts-only/checksums.sha256; then
  echo "ts-only checksums should not list client.go" >&2
  exit 1
fi
if grep -q 'Client.java' out/petstore-ts-only/checksums.sha256; then
  echo "ts-only checksums should not list Client.java" >&2
  exit 1
fi
if grep -q 'client.rs' out/petstore-ts-only/checksums.sha256; then
  echo "ts-only checksums should not list client.rs" >&2
  exit 1
fi
if grep -q 'Client.cs' out/petstore-ts-only/checksums.sha256; then
  echo "ts-only checksums should not list Client.cs" >&2
  exit 1
fi
if grep -q 'Client.kt' out/petstore-ts-only/checksums.sha256; then
  echo "ts-only checksums should not list Client.kt" >&2
  exit 1
fi
if grep -q 'Client.swift' out/petstore-ts-only/checksums.sha256; then
  echo "ts-only checksums should not list Client.swift" >&2
  exit 1
fi
if grep -q 'client.rb' out/petstore-ts-only/checksums.sha256; then
  echo "ts-only checksums should not list client.rb" >&2
  exit 1
fi
if grep -q 'Client.php' out/petstore-ts-only/checksums.sha256; then
  echo "ts-only checksums should not list Client.php" >&2
  exit 1
fi
node src/cli.js verify-checksums --out out/petstore-ts-only

echo "==> --lang go only"
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-go-only --lang go
test -f out/petstore-go-only/client.go
test ! -f out/petstore-go-only/client.ts
test ! -f out/petstore-go-only/package.json
test ! -f out/petstore-go-only/client.py
test ! -f out/petstore-go-only/Client.java
test ! -f out/petstore-go-only/client.rs
test ! -f out/petstore-go-only/Client.cs
test ! -f out/petstore-go-only/Client.kt
test ! -f out/petstore-go-only/Client.swift
test ! -f out/petstore-go-only/client.rb
test ! -f out/petstore-go-only/Client.php
test -f out/petstore-go-only/mcp-tools.json
test -f out/petstore-go-only/mcp-server.mjs
test -f out/petstore-go-only/mcp_server.py
test -f out/petstore-go-only/mcp_server.go
grep -q 'package client' out/petstore-go-only/client.go

echo "==> --lang java only"
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-java-only --lang java
test -f out/petstore-java-only/Client.java
test ! -f out/petstore-java-only/client.ts
test ! -f out/petstore-java-only/client.py
test ! -f out/petstore-java-only/client.go
test ! -f out/petstore-java-only/client.rs
test ! -f out/petstore-java-only/Client.cs
test ! -f out/petstore-java-only/Client.kt
test ! -f out/petstore-java-only/Client.swift
test ! -f out/petstore-java-only/client.rb
test ! -f out/petstore-java-only/Client.php
test -f out/petstore-java-only/mcp-tools.json
test -f out/petstore-java-only/mcp-server.mjs
test -f out/petstore-java-only/mcp_server.py
test -f out/petstore-java-only/mcp_server.go
grep -q 'package client' out/petstore-java-only/Client.java
grep -q 'HttpURLConnection' out/petstore-java-only/Client.java
grep -q 'Client.java' out/petstore-java-only/checksums.sha256
if grep -q 'client.ts' out/petstore-java-only/checksums.sha256; then
  echo "java-only checksums should not list client.ts" >&2
  exit 1
fi
node src/cli.js verify-checksums --out out/petstore-java-only


echo "==> --lang rust / rs only"
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-rust-only --lang rust
test -f out/petstore-rust-only/client.rs
test ! -f out/petstore-rust-only/client.ts
test ! -f out/petstore-rust-only/client.py
test ! -f out/petstore-rust-only/client.go
test ! -f out/petstore-rust-only/Client.java
test ! -f out/petstore-rust-only/Client.cs
test ! -f out/petstore-rust-only/Client.kt
test ! -f out/petstore-rust-only/Client.swift
test ! -f out/petstore-rust-only/client.rb
test ! -f out/petstore-rust-only/Client.php
test -f out/petstore-rust-only/mcp-tools.json
test -f out/petstore-rust-only/mcp-server.mjs
test -f out/petstore-rust-only/mcp_server.py
test -f out/petstore-rust-only/mcp_server.go
grep -q 'pub struct Client' out/petstore-rust-only/client.rs
grep -q 'TcpStream' out/petstore-rust-only/client.rs
grep -q 'pub fn list_pets' out/petstore-rust-only/client.rs
grep -q 'client.rs' out/petstore-rust-only/checksums.sha256
if grep -q 'client.ts' out/petstore-rust-only/checksums.sha256; then
  echo "rust-only checksums should not list client.ts" >&2
  exit 1
fi
node src/cli.js verify-checksums --out out/petstore-rust-only
# alias --lang rs
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-rust-only --lang rs
test -f out/petstore-rust-only/client.rs
test ! -f out/petstore-rust-only/client.ts


echo "==> --lang csharp / cs / c# only"
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-csharp-only --lang csharp
test -f out/petstore-csharp-only/Client.cs
test ! -f out/petstore-csharp-only/client.ts
test ! -f out/petstore-csharp-only/client.py
test ! -f out/petstore-csharp-only/client.go
test ! -f out/petstore-csharp-only/Client.java
test ! -f out/petstore-csharp-only/client.rs
test ! -f out/petstore-csharp-only/Client.kt
test ! -f out/petstore-csharp-only/Client.swift
test ! -f out/petstore-csharp-only/client.rb
test ! -f out/petstore-csharp-only/Client.php
test -f out/petstore-csharp-only/mcp-tools.json
test -f out/petstore-csharp-only/mcp-server.mjs
test -f out/petstore-csharp-only/mcp_server.py
test -f out/petstore-csharp-only/mcp_server.go
grep -q 'namespace Client' out/petstore-csharp-only/Client.cs
grep -q 'HttpClient' out/petstore-csharp-only/Client.cs
grep -q 'public object ListPets' out/petstore-csharp-only/Client.cs
grep -q 'Client.cs' out/petstore-csharp-only/checksums.sha256
if grep -q 'client.ts' out/petstore-csharp-only/checksums.sha256; then
  echo "csharp-only checksums should not list client.ts" >&2
  exit 1
fi
node src/cli.js verify-checksums --out out/petstore-csharp-only
# alias --lang cs
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-csharp-only --lang cs
test -f out/petstore-csharp-only/Client.cs
test ! -f out/petstore-csharp-only/client.ts
# alias --lang c#
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-csharp-only --lang 'c#'
test -f out/petstore-csharp-only/Client.cs
test ! -f out/petstore-csharp-only/client.ts


echo "==> --lang kotlin / kt only"
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-kotlin-only --lang kotlin
test -f out/petstore-kotlin-only/Client.kt
test ! -f out/petstore-kotlin-only/client.ts
test ! -f out/petstore-kotlin-only/client.py
test ! -f out/petstore-kotlin-only/client.go
test ! -f out/petstore-kotlin-only/Client.java
test ! -f out/petstore-kotlin-only/client.rs
test ! -f out/petstore-kotlin-only/Client.cs
test ! -f out/petstore-kotlin-only/Client.swift
test ! -f out/petstore-kotlin-only/client.rb
test ! -f out/petstore-kotlin-only/Client.php
test -f out/petstore-kotlin-only/mcp-tools.json
test -f out/petstore-kotlin-only/mcp-server.mjs
test -f out/petstore-kotlin-only/mcp_server.py
test -f out/petstore-kotlin-only/mcp_server.go
grep -q 'package client' out/petstore-kotlin-only/Client.kt
grep -q 'HttpURLConnection' out/petstore-kotlin-only/Client.kt
grep -q 'fun listPets' out/petstore-kotlin-only/Client.kt
grep -q 'Client.kt' out/petstore-kotlin-only/checksums.sha256
if grep -q 'client.ts' out/petstore-kotlin-only/checksums.sha256; then
  echo "kotlin-only checksums should not list client.ts" >&2
  exit 1
fi
if grep -qiE 'okhttp3|OkHttp|import[[:space:]]+okhttp' out/petstore-kotlin-only/Client.kt; then
  echo "Client.kt must be okhttp-free" >&2
  exit 1
fi
node src/cli.js verify-checksums --out out/petstore-kotlin-only
# alias --lang kt
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-kotlin-only --lang kt
test -f out/petstore-kotlin-only/Client.kt
test ! -f out/petstore-kotlin-only/client.ts


echo "==> --lang swift only"
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-swift-only --lang swift
test -f out/petstore-swift-only/Client.swift
test ! -f out/petstore-swift-only/client.ts
test ! -f out/petstore-swift-only/client.py
test ! -f out/petstore-swift-only/client.go
test ! -f out/petstore-swift-only/Client.java
test ! -f out/petstore-swift-only/client.rs
test ! -f out/petstore-swift-only/Client.cs
test ! -f out/petstore-swift-only/Client.kt
test ! -f out/petstore-swift-only/client.rb
test ! -f out/petstore-swift-only/Client.php
test -f out/petstore-swift-only/mcp-tools.json
test -f out/petstore-swift-only/mcp-server.mjs
test -f out/petstore-swift-only/mcp_server.py
test -f out/petstore-swift-only/mcp_server.go
grep -q 'import Foundation' out/petstore-swift-only/Client.swift
grep -q 'URLSession' out/petstore-swift-only/Client.swift
grep -qE 'class Client|struct Client' out/petstore-swift-only/Client.swift
grep -q 'func listPets' out/petstore-swift-only/Client.swift
grep -q 'Client.swift' out/petstore-swift-only/checksums.sha256
if grep -q 'client.ts' out/petstore-swift-only/checksums.sha256; then
  echo "swift-only checksums should not list client.ts" >&2
  exit 1
fi
if grep -qiE 'Alamofire|import[[:space:]]+Alamofire' out/petstore-swift-only/Client.swift; then
  echo "Client.swift must be Alamofire-free" >&2
  exit 1
fi
node src/cli.js verify-checksums --out out/petstore-swift-only

echo "==> --lang ruby / rb only"
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-ruby-only --lang ruby
test -f out/petstore-ruby-only/client.rb
test ! -f out/petstore-ruby-only/client.ts
test ! -f out/petstore-ruby-only/client.py
test ! -f out/petstore-ruby-only/client.go
test ! -f out/petstore-ruby-only/Client.java
test ! -f out/petstore-ruby-only/client.rs
test ! -f out/petstore-ruby-only/Client.cs
test ! -f out/petstore-ruby-only/Client.kt
test ! -f out/petstore-ruby-only/Client.swift
test ! -f out/petstore-ruby-only/Client.php
test -f out/petstore-ruby-only/mcp-tools.json
test -f out/petstore-ruby-only/mcp-server.mjs
test -f out/petstore-ruby-only/mcp_server.py
test -f out/petstore-ruby-only/mcp_server.go
grep -q 'require "net/http"' out/petstore-ruby-only/client.rb
grep -q 'Net::HTTP' out/petstore-ruby-only/client.rb
grep -q 'class Client' out/petstore-ruby-only/client.rb
grep -q 'def list_pets' out/petstore-ruby-only/client.rb
grep -q 'client.rb' out/petstore-ruby-only/checksums.sha256
if grep -q 'client.ts' out/petstore-ruby-only/checksums.sha256; then
  echo "ruby-only checksums should not list client.ts" >&2
  exit 1
fi
if grep -qiE 'httparty|faraday|rest-client' out/petstore-ruby-only/client.rb; then
  echo "client.rb must be gem-free (stdlib Net::HTTP only)" >&2
  exit 1
fi
node src/cli.js verify-checksums --out out/petstore-ruby-only
# alias --lang rb
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-ruby-only --lang rb
test -f out/petstore-ruby-only/client.rb
test ! -f out/petstore-ruby-only/client.ts


echo "==> --lang php only"
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-php-only --lang php
test -f out/petstore-php-only/Client.php
test ! -f out/petstore-php-only/client.ts
test ! -f out/petstore-php-only/client.py
test ! -f out/petstore-php-only/client.go
test ! -f out/petstore-php-only/Client.java
test ! -f out/petstore-php-only/client.rs
test ! -f out/petstore-php-only/Client.cs
test ! -f out/petstore-php-only/Client.kt
test ! -f out/petstore-php-only/Client.swift
test ! -f out/petstore-php-only/client.rb
test -f out/petstore-php-only/mcp-tools.json
test -f out/petstore-php-only/mcp-server.mjs
test -f out/petstore-php-only/mcp_server.py
test -f out/petstore-php-only/mcp_server.go
grep -q 'class Client' out/petstore-php-only/Client.php
grep -q 'fopen' out/petstore-php-only/Client.php
grep -q 'stream_context_create' out/petstore-php-only/Client.php
grep -q 'public function listPets' out/petstore-php-only/Client.php
grep -q 'Client.php' out/petstore-php-only/checksums.sha256
if grep -q 'client.ts' out/petstore-php-only/checksums.sha256; then
  echo "php-only checksums should not list client.ts" >&2
  exit 1
fi
if grep -qiE 'curl_init|curl_exec|curl_setopt' out/petstore-php-only/Client.php; then
  echo "Client.php must be curl-extension-free (stdlib fopen/stream only)" >&2
  exit 1
fi
node src/cli.js verify-checksums --out out/petstore-php-only

echo "==> yaml openapi"
node src/cli.js generate examples/petstore.openapi.yaml --out out/petstore-yaml
test -f out/petstore-yaml/mcp-tools.json
test -f out/petstore-yaml/mcp-server.mjs
test -f out/petstore-yaml/mcp_server.py
test -f out/petstore-yaml/mcp_server.go
test -f out/petstore-yaml/client.py
test -f out/petstore-yaml/client.go
test -f out/petstore-yaml/Client.java
test -f out/petstore-yaml/client.rs
test -f out/petstore-yaml/Client.cs
test -f out/petstore-yaml/Client.kt
test -f out/petstore-yaml/Client.swift
test -f out/petstore-yaml/client.rb
test -f out/petstore-yaml/Client.php
YTOOLS=$(node -e 'const t=require("./out/petstore-yaml/mcp-tools.json"); console.log(t.tools.length)')
echo "yaml_tools=$YTOOLS"
test "$YTOOLS" = "$TOOLS"
node -e 'const a=require("./out/petstore/mcp-tools.json"); const b=require("./out/petstore-yaml/mcp-tools.json"); const na=a.tools.map(t=>t.name).sort().join(","); const nb=b.tools.map(t=>t.name).sort().join(","); if(na!==nb){console.error(na,nb); process.exit(1)} console.log("json/yaml tool names match")'
python3 -m py_compile out/petstore-yaml/client.py
grep -q 'func (c \*Client) ListPets' out/petstore-yaml/client.go
grep -q 'pub fn list_pets' out/petstore-yaml/client.rs
grep -q 'public object ListPets' out/petstore-yaml/Client.cs
grep -q 'fun listPets' out/petstore-yaml/Client.kt
grep -q 'func listPets' out/petstore-yaml/Client.swift
grep -q 'def list_pets' out/petstore-yaml/client.rb
grep -q 'public function listPets' out/petstore-yaml/Client.php

echo "==> breaking check (baseline vs mutated OpenAPI)"
# baseline = current petstore generate output
rm -rf out/petstore-baseline out/petstore-breaking out/petstore-breaking-gen out/petstore-restored out/petstore-restored-gen out/petstore-mutated.openapi.json
mkdir -p out/petstore-baseline
cp -a out/petstore/. out/petstore-baseline/

# mutate a copy of openapi: remove deletePet operation
python3 - <<'PY'
import json, pathlib
src = pathlib.Path("examples/petstore.openapi.json")
spec = json.loads(src.read_text())
path_item = spec["paths"]["/pets/{petId}"]
assert "delete" in path_item, "fixture missing deletePet"
del path_item["delete"]
out = pathlib.Path("out/petstore-mutated.openapi.json")
out.write_text(json.dumps(spec, indent=2) + "\n")
print("wrote", out, "ops=", sum(1 for p in spec["paths"].values() for m in ("get","post","put","patch","delete") if m in p))
PY

# regenerate elsewhere — must FAIL vs baseline (deletePet removed)
set +e
node src/cli.js generate out/petstore-mutated.openapi.json --out out/petstore-breaking
BREAK_RC=$?
set -e
test "$BREAK_RC" = "0"
set +e
node src/cli.js check --out out/petstore-breaking --baseline out/petstore-baseline
CHECK_FAIL_RC=$?
set -e
if [ "$CHECK_FAIL_RC" -eq 0 ]; then
  echo "expected check to fail after removing deletePet" >&2
  exit 1
fi
echo "check_fail_rc=$CHECK_FAIL_RC (expected non-zero)"

# generate --check-baseline convenience must also fail
set +e
node src/cli.js generate out/petstore-mutated.openapi.json --out out/petstore-breaking-gen --check-baseline out/petstore-baseline
GEN_CHECK_RC=$?
set -e
if [ "$GEN_CHECK_RC" -eq 0 ]; then
  echo "expected generate --check-baseline to fail" >&2
  exit 1
fi
echo "generate_check_baseline_fail_rc=$GEN_CHECK_RC (expected non-zero)"

# restore path: regenerate from original openapi → check must PASS
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-restored
node src/cli.js check --out out/petstore-restored --baseline out/petstore-baseline
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-restored-gen --check-baseline out/petstore-baseline
echo "breaking check OK (fail on remove, pass on restore)"

echo "==> generate --watch (poll regenerate)"
rm -rf out/petstore-watch out/petstore-watch-spec.json out/watch.log
cp examples/petstore.openapi.json out/petstore-watch-spec.json

# Start watch briefly in background; must not hang local-mvp.
node src/cli.js generate out/petstore-watch-spec.json --out out/petstore-watch --lang ts --watch >out/watch.log 2>&1 &
WATCH_PID=$!
cleanup_watch() {
  if kill -0 "$WATCH_PID" 2>/dev/null; then
    kill "$WATCH_PID" 2>/dev/null || true
    wait "$WATCH_PID" 2>/dev/null || true
  fi
}
trap cleanup_watch EXIT

# Wait for initial generate to finish (JSON line in log), timeout 5s
INIT_OK=0
for _ in $(seq 1 25); do
  if grep -q '"out"' out/watch.log 2>/dev/null && test -f out/petstore-watch/mcp-tools.json; then
    INIT_OK=1
    break
  fi
  if ! kill -0 "$WATCH_PID" 2>/dev/null; then
    echo "watch process exited early" >&2
    cat out/watch.log >&2 || true
    exit 1
  fi
  sleep 0.2
done
if [ "$INIT_OK" != "1" ]; then
  echo "watch initial generate did not complete within 5s" >&2
  cat out/watch.log >&2 || true
  exit 1
fi

BEFORE_MTIME=$(stat -c %Y out/petstore-watch/mcp-tools.json)

# Dummy description change on watched OpenAPI (mtime bump)
python3 -c '
import json, pathlib, time, os
p = pathlib.Path("out/petstore-watch-spec.json")
spec = json.loads(p.read_text())
spec.setdefault("info", {})["description"] = "watch-dummy-%s" % time.time()
p.write_text(json.dumps(spec, indent=2) + "\n")
now = time.time() + 1
os.utime(p, (now, now))
print("touched", p)
'

# Wait for regenerate: log line or newer out files; poll 200ms, timeout 5s
REGEN_OK=0
for _ in $(seq 1 25); do
  if grep -q regenerated out/watch.log 2>/dev/null; then
    REGEN_OK=1
    break
  fi
  AFTER_MTIME=$(stat -c %Y out/petstore-watch/mcp-tools.json)
  if [ "$AFTER_MTIME" -gt "$BEFORE_MTIME" ]; then
    REGEN_OK=1
    break
  fi
  if ! kill -0 "$WATCH_PID" 2>/dev/null; then
    echo "watch process died before regenerate" >&2
    cat out/watch.log >&2 || true
    exit 1
  fi
  sleep 0.2
done

cleanup_watch
trap - EXIT

if [ "$REGEN_OK" != "1" ]; then
  echo "watch did not regenerate within 5s" >&2
  echo "--- watch.log ---" >&2
  cat out/watch.log >&2 || true
  exit 1
fi
if ! grep -q regenerated out/watch.log; then
  echo "watch regenerate detected via mtime but missing regenerated log line" >&2
  cat out/watch.log >&2 || true
  exit 1
fi
test -f out/petstore-watch/client.ts
test ! -f out/petstore-watch/Client.java
test ! -f out/petstore-watch/client.rs
test ! -f out/petstore-watch/Client.cs
test ! -f out/petstore-watch/Client.kt
test ! -f out/petstore-watch/Client.swift
test ! -f out/petstore-watch/client.rb
test ! -f out/petstore-watch/Client.php
test -f out/petstore-watch/mcp-tools.json
test -f out/petstore-watch/mcp-server.mjs
test -f out/petstore-watch/mcp_server.py
test -f out/petstore-watch/mcp_server.go
test -f out/petstore-watch/mcp.json
echo "watch regenerate OK"


echo "==> --package-name acme_pets (isolated; default petstore unchanged)"
rm -rf out/petstore-pkg out/dry-run-pkg.json out/mcp-list-pkg.json
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-pkg --package-name acme_pets --lang ts,python,go
grep -q acme_pets out/petstore-pkg/package.json
grep -q acme_pets out/petstore-pkg/client.py
grep -q 'package acme_pets' out/petstore-pkg/client.go
test -d out/petstore-pkg/acme_pets
test -f out/petstore-pkg/acme_pets/__init__.py
test -f out/petstore-pkg/mcp-server.mjs
test -f out/petstore-pkg/mcp_server.py
test -f out/petstore-pkg/mcp_server.go
grep -q 'package main' out/petstore-pkg/mcp_server.go
# default generate still historical names
grep -q 'package client' out/petstore/client.go
grep -q 'listPets' out/petstore/client.ts
grep -q 'class Client' out/petstore/client.py
grep -q '"name": "client"' out/petstore/package.json
# dry-run prints package name
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-pkg-dry --package-name acme_pets --dry-run > out/dry-run-pkg.json
if [ -e out/petstore-pkg-dry ]; then
  echo "dry-run --package-name must not create --out dir" >&2
  exit 1
fi
node -e '
const j = require("./out/dry-run-pkg.json");
if (j.packageName !== "acme_pets") { console.error("dry-run packageName", j); process.exit(1); }
console.log("dry-run packageName ok " + j.packageName);
'
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | node out/petstore-pkg/mcp-server.mjs > out/mcp-list-pkg.json
node -e '
const fs = require("fs");
const raw = fs.readFileSync("out/mcp-list-pkg.json", "utf8").trim();
const line = raw.split(/\n/).filter(Boolean).pop();
const msg = JSON.parse(line);
const names = (msg.result && msg.result.tools || []).map((t) => t.name);
if (!names.includes("listPets")) { console.error("pkg mcp tools/list missing listPets", names); process.exit(1); }
console.log("pkg mcp tools/list ok " + names.join(","));
'
echo "package-name OK (acme_pets isolated; default client/listPets unchanged)"

echo "==> OpenAPI 3.1 mini (isolated; petstore 3.0 unchanged)"
rm -rf out/openapi-3.1-mini out/mcp-list-31.json out/mcp-list-31-py.json
# petstore 3.0 fixtures must stay 3.0.3
grep -q '"openapi": "3.0.3"' examples/petstore.openapi.json
grep -q 'openapi: "3.0.3"' examples/petstore.openapi.yaml
node src/cli.js generate examples/openapi-3.1-mini.json --out out/openapi-3.1-mini --lang ts,python
test -f out/openapi-3.1-mini/client.ts
test -f out/openapi-3.1-mini/client.py
test -f out/openapi-3.1-mini/mcp-server.mjs
test -f out/openapi-3.1-mini/mcp_server.py
test -f out/openapi-3.1-mini/mcp_server.go
test -f out/openapi-3.1-mini/mcp.json
test -f out/openapi-3.1-mini/checksums.sha256
node -e '
const j = require("./out/openapi-3.1-mini/mcp.json");
if (!j.mcpServers || typeof j.mcpServers !== "object") { console.error("3.1 mcp.json", j); process.exit(1); }
const nodeEntry = Object.values(j.mcpServers).find((e) => e && e.command === "node");
if (!nodeEntry || !Array.isArray(nodeEntry.args) || !nodeEntry.args.some((a) => String(a).includes("mcp-server.mjs"))) {
  console.error("3.1 mcp.json missing node mcp-server.mjs", j);
  process.exit(1);
}
console.log("3.1 mcp.json ok keys=" + Object.keys(j.mcpServers).join(","));
'
grep -q 'listItems' out/openapi-3.1-mini/client.ts
grep -q 'def listItems' out/openapi-3.1-mini/client.py
# default petstore generate still historical 3.0 names
grep -q 'listPets' out/petstore/client.ts
grep -q 'package client' out/petstore/client.go
node src/cli.js verify-checksums --out out/petstore
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | node out/openapi-3.1-mini/mcp-server.mjs > out/mcp-list-31.json
node -e '
const fs = require("fs");
const raw = fs.readFileSync("out/mcp-list-31.json", "utf8").trim();
const line = raw.split(/\n/).filter(Boolean).pop();
const msg = JSON.parse(line);
const names = (msg.result && msg.result.tools || []).map((t) => t.name);
if (!names.includes("listItems")) { console.error("3.1 mcp tools/list missing listItems", names); process.exit(1); }
if (names.includes("itemChangedWebhook")) { console.error("3.1 mcp leaked webhook", names); process.exit(1); }
console.log("3.1 mcp tools/list ok " + names.join(","));
'
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | python3 out/openapi-3.1-mini/mcp_server.py > out/mcp-list-31-py.json
node -e '
const fs = require("fs");
const raw = fs.readFileSync("out/mcp-list-31-py.json", "utf8").trim();
const line = raw.split(/\n/).filter(Boolean).pop();
const msg = JSON.parse(line);
const names = (msg.result && msg.result.tools || []).map((t) => t.name);
if (!names.includes("listItems")) { console.error("3.1 mcp py tools/list missing listItems", names); process.exit(1); }
if (names.includes("itemChangedWebhook")) { console.error("3.1 mcp py leaked webhook", names); process.exit(1); }
console.log("3.1 mcp py tools/list ok " + names.join(","));
'
grep -q 'listItems' out/openapi-3.1-mini/mcp_server.go
grep -q 'tools/list' out/openapi-3.1-mini/mcp_server.go
if command -v go >/dev/null 2>&1; then
  printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | go run out/openapi-3.1-mini/mcp_server.go > out/mcp-list-31-go.json
  node -e '
const fs = require("fs");
const raw = fs.readFileSync("out/mcp-list-31-go.json", "utf8").trim();
const line = raw.split(/\n/).filter(Boolean).pop();
const msg = JSON.parse(line);
const names = (msg.result && msg.result.tools || []).map((t) => t.name);
if (!names.includes("listItems")) { console.error("3.1 mcp go tools/list missing listItems", names); process.exit(1); }
if (names.includes("itemChangedWebhook")) { console.error("3.1 mcp go leaked webhook", names); process.exit(1); }
console.log("3.1 mcp go tools/list ok " + names.join(","));
'
fi
echo "openapi-3.1 mini OK (ts+py clients; tools/list has listItems; petstore 3.0 unchanged)"

echo "==> generate --url (loopback http.server; default petstore file path unchanged)"
rm -rf out/petstore-url out/dry-run-url.json out/mcp-list-url.json out/mcp-list-url-py.json out/url-http.log
URL_DIR=$(mktemp -d)
cp examples/openapi-3.1-mini.json "$URL_DIR/openapi.json"
URL_PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')
python3 -m http.server "$URL_PORT" --bind 127.0.0.1 --directory "$URL_DIR" >out/url-http.log 2>&1 &
URL_PID=$!
cleanup_url() {
  if kill -0 "$URL_PID" 2>/dev/null; then
    kill "$URL_PID" 2>/dev/null || true
    wait "$URL_PID" 2>/dev/null || true
  fi
  rm -rf "$URL_DIR"
}
trap cleanup_url EXIT
URL_READY=0
for _ in $(seq 1 25); do
  if python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${URL_PORT}/openapi.json', timeout=0.4)" >/dev/null 2>&1; then
    URL_READY=1
    break
  fi
  if ! kill -0 "$URL_PID" 2>/dev/null; then
    echo "url http.server exited early" >&2
    cat out/url-http.log >&2 || true
    exit 1
  fi
  sleep 0.2
done
if [ "$URL_READY" != "1" ]; then
  echo "url http.server did not become ready" >&2
  cat out/url-http.log >&2 || true
  exit 1
fi
SPEC_URL="http://127.0.0.1:${URL_PORT}/openapi.json"
node src/cli.js generate --url "$SPEC_URL" --out out/petstore-url --lang ts,python --dry-run > out/dry-run-url.json
if [ -e out/petstore-url ]; then
  echo "url dry-run must not create --out dir" >&2
  exit 1
fi
node -e '
const j = require("./out/dry-run-url.json");
if (!Array.isArray(j.files) || !j.files.includes("client.ts") || !j.files.includes("mcp-server.mjs")) {
  console.error("url dry-run files", j);
  process.exit(1);
}
if (typeof j.operations !== "number" || j.operations < 1) {
  console.error("url dry-run operations", j);
  process.exit(1);
}
console.log("url dry-run ok ops="+j.operations+" tools="+j.tools);
'
node src/cli.js generate --url "$SPEC_URL" --out out/petstore-url --lang ts,python
test -f out/petstore-url/client.ts
test -f out/petstore-url/client.py
test -f out/petstore-url/mcp-server.mjs
test -f out/petstore-url/mcp_server.py
test -f out/petstore-url/mcp_server.go
grep -q 'listItems' out/petstore-url/client.ts
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | node out/petstore-url/mcp-server.mjs > out/mcp-list-url.json
node -e '
const fs = require("fs");
const raw = fs.readFileSync("out/mcp-list-url.json", "utf8").trim();
const line = raw.split(/\n/).filter(Boolean).pop();
const msg = JSON.parse(line);
const names = (msg.result && msg.result.tools || []).map((t) => t.name);
if (!names.includes("listItems")) { console.error("url mcp tools/list missing listItems", names); process.exit(1); }
console.log("url mcp tools/list ok " + names.join(","));
'
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | python3 out/petstore-url/mcp_server.py > out/mcp-list-url-py.json
node -e '
const fs = require("fs");
const raw = fs.readFileSync("out/mcp-list-url-py.json", "utf8").trim();
const line = raw.split(/\n/).filter(Boolean).pop();
const msg = JSON.parse(line);
const names = (msg.result && msg.result.tools || []).map((t) => t.name);
if (!names.includes("listItems")) { console.error("url mcp py tools/list missing listItems", names); process.exit(1); }
console.log("url mcp py tools/list ok " + names.join(","));
'
test -f out/petstore-url/mcp_server.go
grep -q 'listItems' out/petstore-url/mcp_server.go
if command -v go >/dev/null 2>&1; then
  printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | go run out/petstore-url/mcp_server.go > out/mcp-list-url-go.json
  node -e '
const fs = require("fs");
const raw = fs.readFileSync("out/mcp-list-url-go.json", "utf8").trim();
const line = raw.split(/\n/).filter(Boolean).pop();
const msg = JSON.parse(line);
const names = (msg.result && msg.result.tools || []).map((t) => t.name);
if (!names.includes("listItems")) { console.error("url mcp go tools/list missing listItems", names); process.exit(1); }
console.log("url mcp go tools/list ok " + names.join(","));
'
fi
set +e
node src/cli.js generate examples/openapi-3.1-mini.json --url "$SPEC_URL" --out out/petstore-url-xor --lang ts >/dev/null 2>out/url-xor.err
XOR_RC=$?
node src/cli.js generate --url "http://127.0.0.1:${URL_PORT}/missing.json" --out out/petstore-url-404 --lang ts >/dev/null 2>out/url-404.err
MISS_RC=$?
set -e
if [ "$XOR_RC" -eq 0 ]; then
  echo "expected generate file + --url to fail (XOR)" >&2
  exit 1
fi
if [ "$MISS_RC" -eq 0 ]; then
  echo "expected generate --url 404 to fail" >&2
  exit 1
fi
if ! grep -q 'HTTP 404' out/url-404.err; then
  echo "expected HTTP 404 in --url missing fetch error" >&2
  cat out/url-404.err >&2
  exit 1
fi
# default petstore file path still historical names (no fetch)
grep -q 'listPets' out/petstore/client.ts
grep -q 'package client' out/petstore/client.go
node src/cli.js verify-checksums --out out/petstore
cleanup_url
trap - EXIT
echo "generate --url OK (loopback http.server; XOR; 404; petstore file path unchanged)"

echo "==> generate --url --header (auth loopback; names-only dry-run; petstore file path unchanged)"
rm -rf out/petstore-url-auth out/petstore-url-envhdr out/dry-run-url-auth.json out/url-auth.out out/url-auth.err out/url-noauth.err out/hdr-nourl.err out/url-auth-http.log
mkdir -p out
AUTH_PORT_FILE=$(mktemp)
export AUTH_SPEC="$ROOT/examples/openapi-3.1-mini.json"
export AUTH_PORT_FILE
python3 - <<'PY' >out/url-auth-http.log 2>&1 &
import http.server
import os
import socketserver

spec = open(os.environ["AUTH_SPEC"], "rb").read()
port_path = os.environ["AUTH_PORT_FILE"]
expected = "Bearer test-token"

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return
    def do_GET(self):
        auth = self.headers.get("Authorization") or ""
        if auth != expected:
            self.send_response(401)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"unauthorized")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(spec)

class S(socketserver.TCPServer):
    allow_reuse_address = True

httpd = S(("127.0.0.1", 0), H)
with open(port_path, "w") as f:
    f.write(str(httpd.server_address[1]))
httpd.serve_forever()
PY
AUTH_PID=$!
cleanup_auth() {
  if kill -0 "$AUTH_PID" 2>/dev/null; then
    kill "$AUTH_PID" 2>/dev/null || true
    wait "$AUTH_PID" 2>/dev/null || true
  fi
  rm -f "$AUTH_PORT_FILE"
}
trap cleanup_auth EXIT
AUTH_READY=0
for _ in $(seq 1 25); do
  if [ -s "$AUTH_PORT_FILE" ]; then
    AUTH_PORT=$(cat "$AUTH_PORT_FILE")
    if python3 -c "import urllib.request,sys; urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:%s/openapi.json'%sys.argv[1], headers={'Authorization':'Bearer test-token'}), timeout=0.4)" "$AUTH_PORT" >/dev/null 2>&1; then
      AUTH_READY=1
      break
    fi
  fi
  if ! kill -0 "$AUTH_PID" 2>/dev/null; then
    echo "auth url server exited early" >&2
    cat out/url-auth-http.log >&2 || true
    exit 1
  fi
  sleep 0.2
done
if [ "$AUTH_READY" != "1" ]; then
  echo "auth url server did not become ready" >&2
  cat out/url-auth-http.log >&2 || true
  exit 1
fi
AUTH_URL="http://127.0.0.1:${AUTH_PORT}/openapi.json"
AUTH_HDR="Authorization: Bearer test-token"
# success with --header (do not echo AUTH_HDR)
node src/cli.js generate --url "$AUTH_URL" --out out/petstore-url-auth --lang ts --header "$AUTH_HDR" > out/url-auth.out
test -f out/petstore-url-auth/client.ts
test -f out/petstore-url-auth/mcp-server.mjs
test -f out/petstore-url-auth/mcp_server.py
test -f out/petstore-url-auth/mcp_server.go
grep -q 'listItems' out/petstore-url-auth/client.ts
if grep -q 'test-token' out/url-auth.out; then
  echo "generate --url --header stdout leaked token" >&2
  exit 1
fi
node src/cli.js generate --url "$AUTH_URL" --out out/petstore-url-auth-dry --lang ts --dry-run --header "$AUTH_HDR" > out/dry-run-url-auth.json
if [ -e out/petstore-url-auth-dry ]; then
  echo "url --header dry-run must not create --out dir" >&2
  exit 1
fi
if grep -q 'test-token' out/dry-run-url-auth.json; then
  echo "dry-run JSON leaked token" >&2
  exit 1
fi
node -e '
const j = require("./out/dry-run-url-auth.json");
const names = j.headerNames || [];
if (!names.includes("Authorization")) { console.error("dry-run headerNames missing Authorization", names); process.exit(1); }
if (JSON.stringify(j).includes("test-token")) { console.error("dry-run JSON leaked token"); process.exit(1); }
if (typeof j.operations !== "number" || j.operations < 1) { console.error("url header dry-run operations", j); process.exit(1); }
console.log("url --header dry-run ok names="+names.join(","));
'
# without header → 401
set +e
node src/cli.js generate --url "$AUTH_URL" --out out/petstore-url-noauth --lang ts >/dev/null 2>out/url-noauth.err
NOAUTH_RC=$?
set -e
if [ "$NOAUTH_RC" -eq 0 ]; then
  echo "expected generate --url without --header to fail" >&2
  exit 1
fi
if ! grep -q 'HTTP 401' out/url-noauth.err; then
  echo "expected HTTP 401 in --url without header error" >&2
  sed "s/Bearer [^[:space:]]*/Bearer [redacted]/g" out/url-noauth.err >&2 || true
  exit 1
fi
if grep -q 'test-token' out/url-noauth.err; then
  echo "401 error leaked token" >&2
  exit 1
fi
# env SDK_FETCH_HEADER (single)
SDK_FETCH_HEADER="$AUTH_HDR" node src/cli.js generate --url "$AUTH_URL" --out out/petstore-url-envhdr --lang ts >/dev/null
test -f out/petstore-url-envhdr/client.ts
grep -q 'listItems' out/petstore-url-envhdr/client.ts
# --header without --url → exit 2
set +e
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-hdr-nourl --lang ts --header "$AUTH_HDR" >/dev/null 2>out/hdr-nourl.err
HDR_RC=$?
set -e
if [ "$HDR_RC" -ne 2 ]; then
  echo "expected --header without --url to exit 2 (got $HDR_RC)" >&2
  sed "s/Bearer [^[:space:]]*/Bearer [redacted]/g" out/hdr-nourl.err >&2 || true
  exit 1
fi
# XOR still 2 with --header present
set +e
node src/cli.js generate examples/openapi-3.1-mini.json --url "$AUTH_URL" --out out/petstore-url-xor-hdr --lang ts --header "$AUTH_HDR" >/dev/null 2>out/url-xor-hdr.err
XOR_HDR_RC=$?
set -e
if [ "$XOR_HDR_RC" -ne 2 ]; then
  echo "expected generate file + --url to exit 2 (got $XOR_HDR_RC)" >&2
  exit 1
fi
# default petstore file path still historical names (no fetch / no header)
grep -q 'listPets' out/petstore/client.ts
grep -q 'package client' out/petstore/client.go
node src/cli.js verify-checksums --out out/petstore
cleanup_auth
trap - EXIT
echo "generate --url --header OK (401 without; 200 with; XOR 2; file path unchanged)"


echo "==> generate --watch --url (loopback http.server; isolated; file watch unchanged)"
rm -rf out/petstore-watch-url out/watch-url.log out/url-watch-http.log
# file-watch petstore prove from earlier in this script must still be intact
test -f out/petstore-watch/client.ts
grep -q 'listPets' out/petstore-watch/client.ts
grep -q regenerated out/watch.log
test -f out/petstore-watch/mcp.json
test -f out/petstore-watch/mcp-server.mjs
test -f out/petstore-watch/mcp_server.py
test -f out/petstore-watch/mcp_server.go
URL_WATCH_DIR=$(mktemp -d)
cp examples/openapi-3.1-mini.json "$URL_WATCH_DIR/openapi.json"
URL_WATCH_PORT=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')
python3 -m http.server "$URL_WATCH_PORT" --bind 127.0.0.1 --directory "$URL_WATCH_DIR" >out/url-watch-http.log 2>&1 &
URL_WATCH_HTTP_PID=$!
URL_WATCH_CLI_PID=""
cleanup_url_watch() {
  if [ -n "${URL_WATCH_CLI_PID:-}" ] && kill -0 "$URL_WATCH_CLI_PID" 2>/dev/null; then
    kill "$URL_WATCH_CLI_PID" 2>/dev/null || true
    wait "$URL_WATCH_CLI_PID" 2>/dev/null || true
  fi
  if kill -0 "$URL_WATCH_HTTP_PID" 2>/dev/null; then
    kill "$URL_WATCH_HTTP_PID" 2>/dev/null || true
    wait "$URL_WATCH_HTTP_PID" 2>/dev/null || true
  fi
  rm -rf "$URL_WATCH_DIR"
}
trap cleanup_url_watch EXIT
URL_WATCH_READY=0
for _ in $(seq 1 25); do
  if python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${URL_WATCH_PORT}/openapi.json', timeout=0.4)" >/dev/null 2>&1; then
    URL_WATCH_READY=1
    break
  fi
  if ! kill -0 "$URL_WATCH_HTTP_PID" 2>/dev/null; then
    echo "url-watch http.server exited early" >&2
    cat out/url-watch-http.log >&2 || true
    exit 1
  fi
  sleep 0.2
done
if [ "$URL_WATCH_READY" != "1" ]; then
  echo "url-watch http.server did not become ready" >&2
  cat out/url-watch-http.log >&2 || true
  exit 1
fi
WATCH_URL="http://127.0.0.1:${URL_WATCH_PORT}/openapi.json"
# Isolated prove uses 400ms so local-mvp does not hang on the 2s default.
node src/cli.js generate --url "$WATCH_URL" --out out/petstore-watch-url --lang ts --watch --watch-interval-ms 400 >out/watch-url.log 2>&1 &
URL_WATCH_CLI_PID=$!
INIT_OK=0
for _ in $(seq 1 25); do
  if grep -q '"out"' out/watch-url.log 2>/dev/null && test -f out/petstore-watch-url/mcp-tools.json; then
    INIT_OK=1
    break
  fi
  if ! kill -0 "$URL_WATCH_CLI_PID" 2>/dev/null; then
    echo "url-watch process exited early" >&2
    cat out/watch-url.log >&2 || true
    exit 1
  fi
  sleep 0.2
done
if [ "$INIT_OK" != "1" ]; then
  echo "url-watch initial generate did not complete within 5s" >&2
  cat out/watch-url.log >&2 || true
  exit 1
fi
test -f out/petstore-watch-url/client.ts
test -f out/petstore-watch-url/mcp.json
test -f out/petstore-watch-url/mcp-server.mjs
test -f out/petstore-watch-url/mcp_server.py
test -f out/petstore-watch-url/mcp_server.go
test -f out/petstore-watch-url/checksums.sha256
grep -q 'listItems' out/petstore-watch-url/client.ts
node src/cli.js verify-checksums --out out/petstore-watch-url
BEFORE_MTIME=$(stat -c %Y out/petstore-watch-url/mcp-tools.json)
python3 -c '
import json, pathlib, time, os
p = pathlib.Path("'"$URL_WATCH_DIR"'/openapi.json")
spec = json.loads(p.read_text())
spec.setdefault("info", {})["description"] = "url-watch-dummy-%s" % time.time()
p.write_text(json.dumps(spec, indent=2) + "\n")
now = time.time() + 1
os.utime(p, (now, now))
print("touched", p)
'
REGEN_OK=0
for _ in $(seq 1 40); do
  if grep -q regenerated out/watch-url.log 2>/dev/null; then
    REGEN_OK=1
    break
  fi
  if ! kill -0 "$URL_WATCH_CLI_PID" 2>/dev/null; then
    echo "url-watch process died before regenerate" >&2
    cat out/watch-url.log >&2 || true
    exit 1
  fi
  sleep 0.2
done
cleanup_url_watch
trap - EXIT
if [ "$REGEN_OK" != "1" ]; then
  echo "url-watch did not regenerate within ~8s" >&2
  echo "--- watch-url.log ---" >&2
  cat out/watch-url.log >&2 || true
  exit 1
fi
if ! grep -q regenerated out/watch-url.log; then
  echo "url-watch missing regenerated log line" >&2
  cat out/watch-url.log >&2 || true
  exit 1
fi
if grep -qiE 'authorization:|Bearer test-token|test-token' out/watch-url.log; then
  echo "url-watch log leaked a secret" >&2
  exit 1
fi
test -f out/petstore-watch-url/client.ts
test -f out/petstore-watch-url/mcp.json
test -f out/petstore-watch-url/checksums.sha256
node src/cli.js verify-checksums --out out/petstore-watch-url
AFTER_MTIME=$(stat -c %Y out/petstore-watch-url/mcp-tools.json)
if [ "$AFTER_MTIME" -lt "$BEFORE_MTIME" ]; then
  echo "url-watch regenerate should rewrite out files" >&2
  exit 1
fi
# file watch petstore prove unchanged
test -f out/petstore-watch/client.ts
grep -q 'listPets' out/petstore-watch/client.ts
grep -q regenerated out/watch.log
grep -q 'listPets' out/petstore/client.ts
grep -q 'package client' out/petstore/client.go
node src/cli.js verify-checksums --out out/petstore
echo "watch --url regenerate OK (http.server; file watch petstore unchanged)"

echo "==> --no-mcp skips servers and mcp.json"
rm -rf out/petstore-no-mcp out/petstore-no-mcp-dry out/dry-run-no-mcp.json
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-no-mcp --lang ts --no-mcp
test -f out/petstore-no-mcp/client.ts
test -f out/petstore-no-mcp/mcp-tools.json
test ! -f out/petstore-no-mcp/mcp-server.mjs
test ! -f out/petstore-no-mcp/mcp_server.py
test ! -f out/petstore-no-mcp/mcp_server.go
test ! -f out/petstore-no-mcp/mcp.json
test -f out/petstore-no-mcp/LICENSE
test -f out/petstore-no-mcp/NOTICE
test -f out/petstore-no-mcp/.gitignore
grep -q 'Apache' out/petstore-no-mcp/LICENSE
grep -q 'client' out/petstore-no-mcp/NOTICE
grep -q 'node_modules' out/petstore-no-mcp/.gitignore
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-no-mcp-dry --lang ts --no-mcp --dry-run > out/dry-run-no-mcp.json
if [ -e out/petstore-no-mcp-dry ]; then
  echo "--no-mcp dry-run must not create --out dir" >&2
  exit 1
fi
node -e '
const j = require("./out/dry-run-no-mcp.json");
for (const n of ["mcp-server.mjs","mcp_server.py","mcp_server.go","mcp.json"]) {
  if (j.files.includes(n)) { console.error("--no-mcp dry-run should not list", n, j.files); process.exit(1); }
}
if (!j.files.includes("client.ts") || !j.files.includes("mcp-tools.json")) {
  console.error("--no-mcp dry-run missing client/tools", j.files); process.exit(1);
}
if (!j.files.includes("LICENSE") || !j.files.includes("NOTICE")) {
  console.error("--no-mcp dry-run missing LICENSE/NOTICE", j.files); process.exit(1);
}
if (!j.files.includes(".gitignore")) {
  console.error("--no-mcp dry-run missing .gitignore", j.files); process.exit(1);
}
console.log("--no-mcp dry-run files ok");
'
# default petstore generate still has mcp.json
test -f out/petstore/mcp.json
node src/cli.js verify-checksums --out out/petstore
echo "--no-mcp OK (servers+snippet skipped; default petstore unchanged)"

echo "==> generate --zip (sdk.tgz after checksums; lists mcp.json)"
rm -rf out/petstore-zip out/dry-run-zip.json
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-zip --zip --dry-run > out/dry-run-zip.json
if [ -e out/petstore-zip ]; then
  echo "--zip dry-run must not create --out dir" >&2
  exit 1
fi
node -e '
const j = require("./out/dry-run-zip.json");
if (!j.files.includes("sdk.tgz") && !j.files.includes("sdk.zip")) {
  console.error("--zip dry-run missing archive name", j.files);
  process.exit(1);
}
if (!j.files.includes("mcp.json") || !j.files.includes("checksums.sha256") || !j.files.includes("mcp-server.mjs") || !j.files.includes("LICENSE") || !j.files.includes("NOTICE") || !j.files.includes(".gitignore")) {
  console.error("--zip dry-run missing mcp.json/checksums/mcp-server/LICENSE/.gitignore", j.files);
  process.exit(1);
}
console.log("dry-run --zip archive", j.files.includes("sdk.tgz") ? "sdk.tgz" : "sdk.zip");
'
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-zip --zip
if [ -f out/petstore-zip/sdk.tgz ]; then
  tar tzf out/petstore-zip/sdk.tgz | grep -E '(^|/|\./)mcp\.json$' >/dev/null
  tar tzf out/petstore-zip/sdk.tgz | grep -E '(^|/|\./)checksums\.sha256$' >/dev/null
  tar tzf out/petstore-zip/sdk.tgz | grep -E '(^|/|\./)LICENSE$' >/dev/null
  tar tzf out/petstore-zip/sdk.tgz | grep -E '(^|/|\./)NOTICE$' >/dev/null
  tar tzf out/petstore-zip/sdk.tgz | grep -E '(^|/|\./)\.gitignore$' >/dev/null
  if tar tzf out/petstore-zip/sdk.tgz | grep -E '(^|/|\./)sdk\.tgz$'; then
    echo "archive must not include itself" >&2
    exit 1
  fi
elif [ -f out/petstore-zip/sdk.zip ]; then
  unzip -l out/petstore-zip/sdk.zip | grep -E 'mcp\.json' >/dev/null
  unzip -l out/petstore-zip/sdk.zip | grep -E 'checksums\.sha256' >/dev/null
  unzip -l out/petstore-zip/sdk.zip | grep -E 'LICENSE' >/dev/null
  unzip -l out/petstore-zip/sdk.zip | grep -E 'NOTICE' >/dev/null
  unzip -l out/petstore-zip/sdk.zip | grep -E '\.gitignore' >/dev/null
else
  echo "missing sdk.tgz/sdk.zip after --zip" >&2
  ls -la out/petstore-zip >&2 || true
  exit 1
fi
if grep -E 'sdk\.(tgz|zip)' out/petstore-zip/checksums.sha256; then
  echo "checksums.sha256 must not list the archive" >&2
  exit 1
fi
node src/cli.js verify-checksums --out out/petstore-zip
test ! -f out/petstore/sdk.tgz
test ! -f out/petstore/sdk.zip
echo "--zip OK (archive lists mcp.json; checksums omit archive; default generate unchanged)"

echo "==> --no-license skips LICENSE and NOTICE"
rm -rf out/petstore-no-license out/petstore-no-license-dry out/dry-run-no-license.json out/petstore-no-gitignore out/petstore-no-gitignore-dry out/dry-run-no-gitignore.json
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-no-license --lang ts --no-license
test -f out/petstore-no-license/client.ts
test ! -f out/petstore-no-license/LICENSE
test ! -f out/petstore-no-license/NOTICE
if grep -q 'LICENSE' out/petstore-no-license/checksums.sha256; then
  echo "--no-license checksums should not list LICENSE" >&2
  exit 1
fi
if grep -q 'NOTICE' out/petstore-no-license/checksums.sha256; then
  echo "--no-license checksums should not list NOTICE" >&2
  exit 1
fi
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-no-license-dry --lang ts --no-license --dry-run > out/dry-run-no-license.json
if [ -e out/petstore-no-license-dry ]; then
  echo "--no-license dry-run must not create --out dir" >&2
  exit 1
fi
node -e '
const j = require("./out/dry-run-no-license.json");
if (j.files.includes("LICENSE") || j.files.includes("NOTICE")) {
  console.error("--no-license dry-run should not list LICENSE/NOTICE", j.files); process.exit(1);
}
if (!j.files.includes("client.ts") || !j.files.includes("checksums.sha256")) {
  console.error("--no-license dry-run missing client/checksums", j.files); process.exit(1);
}
console.log("--no-license dry-run files ok");
'
# default petstore still has LICENSE/NOTICE
test -f out/petstore/LICENSE
test -f out/petstore/NOTICE
test -f out/petstore/.gitignore
# --no-license still writes .gitignore
test -f out/petstore-no-license/.gitignore
grep -q 'node_modules' out/petstore-no-license/.gitignore
node src/cli.js verify-checksums --out out/petstore
echo "--no-license OK (LICENSE/NOTICE skipped; default petstore unchanged)"

echo "==> --no-gitignore skips .gitignore"
rm -rf out/petstore-no-gitignore out/petstore-no-gitignore-dry out/dry-run-no-gitignore.json
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-no-gitignore --lang ts --no-gitignore
test -f out/petstore-no-gitignore/client.ts
test -f out/petstore-no-gitignore/LICENSE
test -f out/petstore-no-gitignore/NOTICE
test ! -f out/petstore-no-gitignore/.gitignore
if grep -F '.gitignore' out/petstore-no-gitignore/checksums.sha256; then
  echo "--no-gitignore checksums should not list .gitignore" >&2
  exit 1
fi
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-no-gitignore-dry --lang ts --no-gitignore --dry-run > out/dry-run-no-gitignore.json
if [ -e out/petstore-no-gitignore-dry ]; then
  echo "--no-gitignore dry-run must not create --out dir" >&2
  exit 1
fi
node -e '
const j = require("./out/dry-run-no-gitignore.json");
if (j.files.includes(".gitignore")) {
  console.error("--no-gitignore dry-run should not list .gitignore", j.files); process.exit(1);
}
if (!j.files.includes("client.ts") || !j.files.includes("LICENSE") || !j.files.includes("checksums.sha256")) {
  console.error("--no-gitignore dry-run missing client/LICENSE/checksums", j.files); process.exit(1);
}
console.log("--no-gitignore dry-run files ok");
'
# leftover .gitignore from a prior generate vanish on --no-gitignore regenerate
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-no-gitignore --lang ts
test -f out/petstore-no-gitignore/.gitignore
node src/cli.js generate examples/petstore.openapi.json --out out/petstore-no-gitignore --lang ts --no-gitignore
test ! -f out/petstore-no-gitignore/.gitignore
test -f out/petstore-no-gitignore/LICENSE
# default petstore still has .gitignore
test -f out/petstore/.gitignore
grep -q 'node_modules' out/petstore/.gitignore
node src/cli.js verify-checksums --out out/petstore
echo "--no-gitignore OK (.gitignore skipped; default petstore unchanged)"

echo "a-sdk-mcp-gen local-mvp OK"
