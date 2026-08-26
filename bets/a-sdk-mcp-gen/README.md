# A · sdk-mcp-gen

> OpenAPI -> SDK + MCP generator · Status: local-mvp · Phase 2

Docs: [vs Stainless / Speakeasy / OpenAPI Generator](./docs/vs-stainless.md) · [PUBLISH.md](./PUBLISH.md) · [CHANGELOG](./CHANGELOG.md) · [ROADMAP](./ROADMAP.md)

`npm pack` is the local proof the tarball is installable (smoke prints `pack-ok`); publish is still manual.
`registry-pack` writes a local listing payload for generated mcp-server.mjs (smoke prints `registry-pack-ok`); never POSTs; human still publishes.

## Thesis / 立意

Turn existing OpenAPI into TypeScript + Python + Go + Java + Rust + C# + Kotlin + Swift + Ruby + PHP SDK stubs + MCP tool registry + stdio MCP servers (Node + Python + Go).
Lower the cost of wiring legacy APIs into agents.

把已有 OpenAPI 变成 TS/Python/Go/Java/Rust/C#/Kotlin/Swift/Ruby/PHP SDK、MCP tools，以及 stdio MCP server（Node `mcp-server.mjs` + Python `mcp_server.py` + Go `mcp_server.go`）。

## Who pays / 谁付钱

- Platform engineering
- ISVs exposing APIs to agent ecosystems

## OSS vs Paid

| OSS | Paid |
|-----|------|
| OpenAPI 3.x -> TS + Python + Go + Java + Rust + C# + Kotlin + Swift + Ruby + PHP SDK + MCP stubs + stdio MCP servers (Node + Python + Go) | More langs, enterprise templates |
| CLI generate / demo (--lang ts,python,go,java,rust,csharp,kotlin,swift,ruby,php) | Private registry, publish to B gateway, SLA |

## 2-week MVP checklist

- [x] Parse OpenAPI 3.x paths + operations (3.0.x + 3.1.x; 3.1 type unions / examples / $ref; webhooks ignored)
- [x] `generate --url` fetches OpenAPI from http(s) or `file://` (10s timeout, 2MB max, ≤3 redirects; XOR with file path)
- [x] `generate --url --header` (repeatable `Name: value`; env `SDK_FETCH_HEADER`; http(s) only; error without `--url`; not sent to `file://`; values never printed)
- [x] Emit minimal TS client + MCP tool JSON
- [x] Emit stdio MCP servers (`mcp-server.mjs` Node + `mcp_server.py` Python 3 stdlib urllib + `mcp_server.go` Go 1.21+ stdlib net/http; JSON-RPC `initialize` / `tools/list` / `tools/call`)
- [x] Emit `mcp.json` client config snippet (paste into MCP servers config JSON; relative `./mcp-server.mjs`; `--no-mcp` skips)
- [x] Emit minimal Python sync client (client.py, stdlib urllib)
- [x] Emit minimal Go HTTP client (client.go, stdlib net/http, package client)
- [x] Emit minimal Java HTTP client (Client.java, stdlib HttpURLConnection, package client)
- [x] Emit minimal Rust HTTP/1.1 client (client.rs, stdlib TcpStream, http:// only)
- [x] Emit minimal C# HTTP client (Client.cs, stdlib HttpClient, namespace Client)
- [x] Emit minimal Kotlin HTTP client (Client.kt, stdlib HttpURLConnection, class Client, okhttp-free)
- [x] Emit minimal Swift HTTP client (Client.swift, Foundation URLSession, class Client, Alamofire-free)
- [x] Emit minimal Ruby HTTP client (client.rb, stdlib Net::HTTP, class Client, gem-free)
- [x] Emit minimal PHP HTTP client (Client.php, stdlib fopen/stream, class Client, curl-extension-free)
- [x] generate with optional --lang ts,python,go,java,rust,csharp,kotlin,swift,ruby,php (default all ten)
- [x] Petstore-like fixture demo
- [x] Breaking check: `check --out/--baseline` + `generate --check-baseline`
- [x] `generate --watch` polls OpenAPI mtime (200ms) and regenerates on change
- [x] `generate --watch --url` polls remote spec (ETag / If-None-Match 304 skip, else body hash; default 2s; `--watch-interval-ms`)
- [x] Generate writes `checksums.sha256`; `verify-checksums --out` (exit 0/1)
- [x] `generate --dry-run` prints planned `{files, operations, tools, langs}` JSON; writes nothing
- [x] `generate --zip` packs `--out` into `sdk.tgz` (tar -czf) or `sdk.zip` (store-only fallback) after checksums; dry-run lists the archive name; checksums omit the archive
- [x] `generate` writes Apache-2.0 `LICENSE` + `NOTICE` (default on; always overwritten; `--no-license` skips; checksums + dry-run + zip; independent of `--no-mcp`)
- [x] `generate` writes `.gitignore` (default on; always overwritten; `--no-gitignore` skips; checksums + dry-run + zip; independent of `--no-mcp` / `--no-license`)
- [x] Generated TS / Python / Go clients retry 429 / 5xx / network throws (max 2 retries, ~100ms exponential backoff, honor `Retry-After` <30s; stdlib only)
- [x] Generated TS / Python / Go clients add `iterate*` helpers for GET ops with `page` / `pageSize` / `offset` / `limit` / `cursor` / `starting_after` (follow `next` / `next_cursor` / `nextPageToken` or increment page until empty/short; cap 1000; existing method names unchanged; not a Stainless pager)
- [x] Generated TS / Python / Go clients apply a per-attempt request timeout (default 10s; AbortController / urllib timeout / context; override via constructor or env `SDK_TIMEOUT_MS` / `SDK_TIMEOUT_SEC`; stdlib only)
- [x] Generated TS / Python / Go clients + stdio MCP servers send auth from OpenAPI securitySchemes per operation `security` (http bearer, apiKey header/query; env SDK_BEARER_TOKEN / SDK_API_KEY / MCP_*; optional attach-if-set; ops without security omit credentials; oauth2 / openIdConnect skipped)
- [x] Generated Java / Kotlin / C# clients retry 429 / 5xx / network (Retry-After <30s), apply a per-attempt timeout (default 10s; timeoutMs / TimeoutMs or env SDK_TIMEOUT_MS / SDK_TIMEOUT_SEC), and send per-operation OpenAPI auth (http bearer, apiKey header/query; env SDK_*; unsecured ops omit credentials). Stdlib HttpURLConnection / HttpClient. Public method names unchanged.
- [x] Generated Java / Kotlin / C# clients add `iterate*` helpers for GET ops with `page` / `pageSize` / `offset` / `limit` / `cursor` / `starting_after` (follow `next` / `next_cursor` / `nextPageToken` or increment page until empty/short; cap 1000; existing method names unchanged; not a Stainless pager)
- [x] Generated Rust / PHP / Swift / Ruby clients retry 429 / 5xx / network (Retry-After <30s), apply a per-attempt timeout (default 10s; timeout_ms / timeoutMs or env SDK_TIMEOUT_MS / SDK_TIMEOUT_SEC), and send per-operation OpenAPI auth (http bearer, apiKey header/query; env SDK_*; unsecured ops omit credentials). Stdlib only. Public method names unchanged. Rust stays TcpStream http:// (no TLS); headers/timeout/retry attach on that stack.
- [x] Generated TS / Python / Go / Java (and Kotlin / C# / Rust / PHP / Swift / Ruby) clients send `Accept: application/json` unless already set. Smoke prints accept-ok.
- [x] Generated stdio MCP servers send `Accept: application/json` on tools/call upstream HTTP unless already set. Smoke prints mcp-accept-ok.
- [x] Generated TS / Python / Go / Java (and Kotlin / C# / Rust / PHP / Swift / Ruby) clients send default User-Agent `sdk-mcp-gen/0.1.0` (or `--package-name`) unless already set, plus `X-Request-Id` new per HTTP attempt (pin via constructor / env `SDK_REQUEST_ID`). Smoke prints ua-ok / request-id-ok.
- [x] Generated TS / Python / Go / Java (and other langs) clients send `Idempotency-Key` on POST/PUT/PATCH/DELETE when unset. New key per logical call (retries reuse). Pin via constructor / env `SDK_IDEMPOTENCY_KEY`. Smoke prints idem-ok.
- [x] Generated stdio MCP servers send the same identity headers on tools/call upstream HTTP (`User-Agent` sdk-mcp-gen/0.1.0 unless set, `X-Request-Id` per attempt, `Idempotency-Key` on POST/PUT/PATCH/DELETE). Smoke prints mcp-id-ok.
- [x] Generated stdio MCP servers retry 429 / 5xx / network on tools/call upstream HTTP (max 2 retries, ~100ms backoff, honor Retry-After <30s; Idempotency-Key reused). Smoke prints mcp-retry-ok.
- [x] Generated stdio MCP servers apply a per-attempt 10s timeout on tools/call upstream HTTP (AbortController / urllib timeout / context.WithTimeout; override MCP_TIMEOUT_MS / MCP_TIMEOUT_SEC or SDK_TIMEOUT_*). Smoke prints mcp-timeout-ok.
- [x] Generated TS / Python / Go clients throw typed `ApiError` after retries (400/401/403/404/409/422/429/5xx + timeout/network; 429 retry-after seconds when present; sent `X-Request-Id`; truncated body). Stdio MCP maps upstream failure to status + requestId (no auth headers). Smoke prints typed-errors-ok.
- [x] `registry-pack --in <generated-dir>` writes a local MCP Registry server.json + wrapper package + tarball layout for the generated mcp-server.mjs (not this CLI). Prints `registry-pack-ok`. Never POSTs. Human still publishes.
- [x] Demo script in README (`scripts/demo.sh`)

## Demo

Human-runnable petstore generate (no publish, no extra deps):

```
bash scripts/demo.sh
# or: npm run demo
```

Writes `out/demo` from the petstore fixture, prints `client.ts`, `mcp-server.mjs`, and `mcp.json`, then exits 0. Override the output dir with env DEMO_OUT.

## Quick start

```bash
node src/cli.js generate examples/petstore.openapi.json --out out/petstore
# optional company module path: --package-name acme_pets  (alias --package; env SDK_PACKAGE_NAME)
# default langs: ts,python,go,java,rust,csharp,kotlin,swift,ruby,php → clients + mcp-tools.json + mcp-server.mjs + mcp_server.py + mcp_server.go + mcp.json

# fetch a live spec (http/https or file://). XOR with a file operand — both set → error.
# node src/cli.js generate --url http://127.0.0.1:8787/openapi.json --out out/from-url
# private OpenAPI: repeatable --header (http/https only; env SDK_FETCH_HEADER). Values are never printed.
# node src/cli.js generate --url https://api.example/openapi.json --header "Authorization: Bearer $TOKEN" --out out/from-url
# node src/cli.js generate --url file://$PWD/examples/petstore.openapi.yaml --out out/from-file-url

node src/cli.js generate examples/petstore.openapi.yaml --out out/petstore-yaml --lang go

# plan only (JSON {files, operations, tools, langs}); writes nothing to --out
node src/cli.js generate examples/petstore.openapi.json --out out/petstore --dry-run

# pack --out into sdk.tgz (or sdk.zip if tar is missing) after checksums
node src/cli.js generate examples/petstore.openapi.json --out out/petstore --zip

# watch OpenAPI mtime (200ms poll); prints "regenerated" on each change
node src/cli.js generate examples/petstore.openapi.json --out out/petstore --watch

# watch a live spec (default 2s poll; ETag 304 skip / body hash). --header applies to polls.
# node src/cli.js generate --url http://127.0.0.1:8787/openapi.json --out out/from-url --watch
# node src/cli.js generate --url http://127.0.0.1:8787/openapi.json --out out/from-url --watch --watch-interval-ms 400
```

Outputs include TypeScript, Python, Go, Java, Rust, C#, Kotlin, Swift, Ruby, and PHP clients plus MCP tools JSON, stdio MCP servers (`mcp-server.mjs` + `mcp_server.py` + `mcp_server.go`), a paste-ready `mcp.json` client snippet, Apache-2.0 `LICENSE` + `NOTICE` (so the out dir is redistributable), a consumer `.gitignore` (`__pycache__/`, `*.pyc`, `node_modules/`, `.DS_Store`, `*.egg-info/`), and a `checksums.sha256` manifest (sha256 of existing `client.ts` / `package.json` / `client.py` / `client.go` / `Client.java` / `client.rs` / `Client.cs` / `Client.kt` / `Client.swift` / `client.rb` / `Client.php` / `mcp-tools.json` / `mcp-server.mjs` / `mcp_server.py` / `mcp_server.go` / `mcp.json` / `README.md` / `LICENSE` / `NOTICE` / `.gitignore`).

OpenAPI input: .json or .yaml/.yml (built-in YAML subset), **or** `--url` to fetch `http://` / `https://` / `file://` (Node 18+ `fetch`; timeout **10s**, max body **2MB**, follow ≤3 redirects; other schemes rejected; `169.254.169.254` blocked). File path and `--url` are **XOR** (both set → exit 2). Non-2xx → exit 1 with status. Repeatable `--header` / env `SDK_FETCH_HEADER` apply to http(s) `--url` only (error without `--url`; not sent to `file://`; values never printed). `--dry-run` still lists outputs after a successful fetch. `--watch` works with a local file **or** `--url`. **3.0.x and 3.1.x** accepted (paths only; not a full JSON Schema 2020-12 rewrite). Cheap 3.1 diffs: `type: [string, "null"]` → string optional; schema/media `examples` treated like `example`; local `$ref` still resolved; `webhooks` ignored. Petstore fixtures stay OpenAPI **3.0.3**. Mini 3.1 fixture: `examples/openapi-3.1-mini.json`.

```bash
node src/cli.js generate examples/openapi-3.1-mini.json --out out/openapi-3.1-mini --lang ts,python
# client.ts / client.py + mcp tools/list includes listItems (webhooks are not tools)
```

TypeScript note: generated `client.ts` uses Node 18+ `fetch` (injectable
`fetchImpl`) and retries 429 / 5xx / network throws (max 2 retries, ~100ms
exponential backoff, honor `Retry-After` when under 30s). Each attempt uses
`AbortController` (default 10s; override `createClient({ timeoutMs })` or env
`SDK_TIMEOUT_MS` / `SDK_TIMEOUT_SEC`). Default User-Agent `sdk-mcp-gen/0.1.0`
(or `--package-name`) unless already set; `X-Request-Id` is new per attempt
(`createClient({ requestId })` or env `SDK_REQUEST_ID` pins a fixed test id). `Idempotency-Key` is sent on POST/PUT/PATCH/DELETE when unset (new per logical call; retries reuse; pin via `createClient({ idempotencyKey })` or env `SDK_IDEMPOTENCY_KEY`). When the spec has http bearer or apiKey (header/query), pass `bearerToken` / `apiKey` or env `SDK_BEARER_TOKEN` / `SDK_API_KEY` (attached only on operations that declare that scheme; on every retry; values never logged). oauth2 / openIdConnect skipped. Stdlib only. Public
method names stay OpenAPI `operationId` (`listPets`, …). Pageable GET ops also
get an `iterate*` async iterator (petstore `listPets` → `iterateListPets`) that
follows a JSON next cursor (`next` / `next_cursor` / `nextPageToken`) or
increments `page` until an empty or short page. Cap 1000. Not a Stainless pager.

Go note: generated `client.go` uses `package client` and one exported method per
operation (`ListPets`, …). Same retry policy as the TypeScript client (429 / 5xx
/ network; max 2 retries; `Retry-After` <30s). Each attempt uses
`context.WithTimeout` (default 10s; override `Client.Timeout` or env
`SDK_TIMEOUT_MS` / `SDK_TIMEOUT_SEC`). Same OpenAPI auth as TypeScript (`Client.BearerToken` / `APIKey` or env; values never logged). Pageable GET ops also get
`Iterate*` which collects pages (`[]any`) with the same page/cursor policy as
TypeScript. local-mvp runs `gofmt -e` / `go vet` when the Go toolchain is
installed; otherwise it still requires a valid-looking `client.go`.

Python note: generated `client.py` is stdlib `urllib` only (no `requests`) and
uses the same retry policy as TypeScript (429 / 5xx / network; max 2 retries;
`Retry-After` <30s). Each attempt uses `urlopen(..., timeout=)` (default 10s;
override `Client(timeout=...)` / `create_client(timeout=...)` or env
`SDK_TIMEOUT_MS` / `SDK_TIMEOUT_SEC`). Same OpenAPI auth as TypeScript (`bearer_token` / `api_key` or env; values never logged). Public method names stay OpenAPI `operationId`. Pageable
GET ops also get `iterate*` generators with the same page/cursor policy as
TypeScript.

Java note: generated `Client.java` uses `package client` and one public method per
operation (`listPets`, …) via `java.net.HttpURLConnection` (stdlib only). Same retry (429 / 5xx / network; Retry-After <30s), per-attempt timeout (default 10s; `timeoutMs` / SDK_TIMEOUT_*), per-op bearer / apiKey auth, and `iterate*` page helpers (petstore `listPets` → `iterateListPets`; cap 1000) as TS/Python/Go. local-mvp
runs `javac` when present; otherwise a brace/heuristic check still requires a
valid-looking `Client.java`. `--lang ts` does not emit Java.

Rust note: generated `client.rs` is std-only (`std::net::TcpStream` HTTP/1.1 for
`http://` URLs; no TLS/https). One `pub fn` per operation in snake_case
(`list_pets`, …). Same retry (429 / 5xx / network; Retry-After <30s), per-attempt
timeout (default 10s; `timeout_ms` / SDK_TIMEOUT_*), and per-op bearer / apiKey
auth as TS/Python/Go/Java — attached on the TcpStream stack (no TLS). local-mvp
runs `rustc --crate-type lib` when present; otherwise a brace/heuristic check
still requires a valid-looking `client.rs`. `--lang ts` does not emit Rust.
Alias: `--lang rs`.

C# note: generated `Client.cs` uses classic `namespace Client` and one public
PascalCase method per operation (`ListPets`, …) via `System.Net.Http.HttpClient`
(stdlib only). Same retry / per-attempt timeout / per-op auth / `Iterate*` page helpers as Java (`TimeoutMs`, `BearerToken` / `APIKey`, env SDK_*). local-mvp runs `dotnet build` or `csc` when present; otherwise a
brace/heuristic check still requires a valid-looking `Client.cs` (char literals
stripped before strings, same care as Java). `--lang ts` does not emit C#.
Aliases: `--lang cs` / `--lang c#`.

Kotlin note: generated `Client.kt` uses `package client` and `class Client` with
one `fun` per OpenAPI operation (`listPets`, …) via `java.net.HttpURLConnection`
(JVM stdlib; okhttp-free, same HTTP stack as the Java client). Same retry / per-attempt timeout / per-op auth / `iterate*` page helpers as Java. local-mvp runs
`kotlinc` when present; otherwise a brace/heuristic check still requires a
valid-looking `Client.kt` (char literals stripped before strings, same care as
Java). `--lang ts` does not emit Kotlin. Alias: `--lang kt`.

Swift note: generated `Client.swift` is a single-file `public class Client`
(Foundation `URLSession`; Alamofire-free, no SPM). One `public func` per OpenAPI
operation (`listPets`, …). Same retry / per-attempt timeout / per-op auth as
TS/Python/Go/Java (`timeoutMs`, `bearerToken` / `apiKey`, env SDK_*). local-mvp
runs `swiftc -typecheck` when present; otherwise a brace/heuristic check still
requires a valid-looking `Client.swift`. `--lang ts` does not emit Swift.

Ruby note: generated `client.rb` is a single-file `class Client`
(stdlib `Net::HTTP`; gem-free, no httparty/faraday). One public method per
OpenAPI operation in snake_case (`list_pets`, …). Same retry / per-attempt
timeout / per-op auth as TS/Python/Go/Java (`timeout_ms`, `bearer_token` /
`api_key`, env SDK_*). local-mvp runs `ruby -c` when present; otherwise a
brace/heuristic check still requires a valid-looking `client.rb`. `--lang ts`
does not emit Ruby. Alias: `--lang rb`.

PHP note: generated `Client.php` is a single-file `class Client`
(stdlib `fopen` / stream wrappers; curl-extension-free). One public method per
OpenAPI operation in camelCase (`listPets`, …). Same retry / per-attempt
timeout / per-op auth as TS/Python/Go/Java (`timeoutMs`, `bearerToken` /
`apiKey`, env SDK_*). local-mvp runs `php -l` when present; otherwise a
brace/heuristic check still requires a valid-looking `Client.php`. `--lang ts`
does not emit PHP.

## Stdio MCP servers

`generate` always writes `mcp-server.mjs` (Node), `mcp_server.py` (Python 3), and `mcp_server.go` (Go, `package main`) next to each other, plus `mcp.json` (also listed by `--dry-run` and included in checksums / `--watch` regenerate). **`--no-mcp`** skips the servers and the snippet. **No extra deps** (no `@modelcontextprotocol/sdk`, no `requests`, no Go modules). Same newline JSON-RPC subset B's stdio upstream uses: `initialize`, `tools/list` (alias `list`), `tools/call` (alias `call`). Tool names match across JS / Python / Go (OpenAPI `operationId`). Generate does not require `go` on PATH.

Each tool `inputSchema` is a simplified object of string/number/boolean/object properties (arrays / oneOf / etc. are skipped). Handlers call the HTTP API (`fetch` in Node, stdlib `urllib` in Python, stdlib `net/http` in Go): path params substituted, GET/DELETE leftovers as query, POST/PUT/PATCH as JSON body.

```bash
node src/cli.js generate examples/petstore.openapi.json --out out/petstore --base-url http://localhost:8080 --mcp
MCP_BASE_URL=http://localhost:8080 node out/petstore/mcp-server.mjs
MCP_BASE_URL=http://localhost:8080 python3 out/petstore/mcp_server.py
MCP_BASE_URL=http://localhost:8080 go run out/petstore/mcp_server.go
# stdin (one line):
# {"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}
# stdout: {"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"listPets",...},...]}}
```

Runtime `MCP_BASE_URL` wins over the baked `--base-url` (or OpenAPI `servers[0].url`). Bearer / apiKey specs also read `MCP_BEARER_TOKEN` / `MCP_API_KEY` (fallback `SDK_*`) on upstream HTTP; values never logged. `tools/call` attaches the same identity headers as the SDK (`User-Agent` sdk-mcp-gen/0.1.0 unless set, `X-Request-Id` per attempt, `Idempotency-Key` on POST/PUT/PATCH/DELETE) and a per-attempt 10s timeout (`MCP_TIMEOUT_MS` / `MCP_TIMEOUT_SEC` or `SDK_TIMEOUT_*`). Compatible with B gateway `upstream.type=stdio` (`command: node`, `args: [mcp-server.mjs]` or `command: python3`, `args: [mcp_server.py]` or `command: go`, `args: [run, mcp_server.go]`).

Paste `mcp.json` into your **MCP servers config JSON** (Cursor / Claude Desktop / Claude Code). `args` are **relative** to the generate `--out` directory (`./mcp-server.mjs`). Server key is `--package-name` when set, otherwise the OpenAPI title slug. A second `…-py` entry uses `python3` + `./mcp_server.py`; `…-go` uses `go run ./mcp_server.go` when that file is generated. Default `env.MCP_BASE_URL` is `--base-url` or `http://127.0.0.1:8080`.

```json
{
  "mcpServers": {
    "petstore": {
      "command": "node",
      "args": ["./mcp-server.mjs"],
      "env": { "MCP_BASE_URL": "http://127.0.0.1:8080" }
    }
  }
}
```

## GitHub Action (generate)

Composite Action at [`action.yml`](./action.yml) so a consumer can:

    uses: wozqhl/oss-cash-lab/bets/a-sdk-mcp-gen@main
    with:
      spec: examples/petstore.openapi.json   # XOR with url
      output: sdk
      # langs: ts,python

It runs this CLI (Node 18+ must already be on the runner) and fails if the CLI exits non-zero.
Copy-paste workflow that uploads the tree: [`examples/github-actions/sdk-mcp-gen-generate.yml`](../../examples/github-actions/sdk-mcp-gen-generate.yml).
The older [`sdk-mcp-gen-check.yml`](../../examples/github-actions/sdk-mcp-gen-check.yml) is **CHECK only** (drift vs baseline), not generate-and-upload.

Try the same command locally (no Actions runner):

    node src/cli.js generate examples/petstore.openapi.json --out sdk

## Breaking check

Compare a newly generated tree against a saved baseline. **Removed or renamed** MCP tool names (and matching client exports) are breaking (exit 1); **added** tools are OK.

```bash
# save a baseline
node src/cli.js generate examples/petstore.openapi.json --out out/petstore
# leftover demo: scripts/demo.sh writes out/demo and prints client.ts, mcp-server.mjs, mcp.json

# optional company module path: --package-name acme_pets  (alias --package; env SDK_PACKAGE_NAME)

# after OpenAPI changes:
node src/cli.js check --out out/new --baseline out/petstore

# or generate + check in one step (omit --out to use a temp dir):
node src/cli.js generate examples/petstore.openapi.json --check-baseline out/petstore
node src/cli.js generate examples/petstore.openapi.json --out out/new --check-baseline out/petstore
```

Use `--no-clients` on `check` to compare only `mcp-tools.json` names.

`--check-baseline` is one-shot (no `--watch`): generate then exit with the check code.

**Copy-paste workflow:** portfolio [`examples/github-actions/sdk-mcp-gen-check.yml`](../../examples/github-actions/sdk-mcp-gen-check.yml) → consumer `.github/workflows/`. Typical consumer: commit a generated `sdk/`, then CI `node src/cli.js generate examples/petstore.openapi.json --out sdk-new --check-baseline sdk` (or omit `--out` for a temp dir: `generate … --check-baseline sdk`; or two-step `check --out NEW --baseline sdk`). Exit 1 fails the job (removed/renamed tools). Happy path on the petstore fixture: generate twice, second with `--check-baseline` against the first → exit 0. Optional composite: [`examples/github-actions/sdk-mcp-gen-check/action.yml`](../../examples/github-actions/sdk-mcp-gen-check/action.yml). See [`examples/github-actions/README.md`](../../examples/github-actions/README.md). Not a required workflow on this repo.

## Watch mode

```bash
node src/cli.js generate examples/petstore.openapi.json --out out/petstore --watch
node src/cli.js generate --url http://127.0.0.1:8787/openapi.json --out out/from-url --watch
```

**File:** polls OpenAPI mtime every **200ms** (stdlib `fs.stat` + `setInterval`). **`--url`:** polls every **2000ms** by default (override with `--watch-interval-ms`; min 50). Sends `If-None-Match` when the previous response had an ETag (**304** → no write). Otherwise compares a SHA-256 of the body (and `If-Modified-Since` when `Last-Modified` is present). Same `--header` / `SDK_FETCH_HEADER` values are sent on every poll (never logged). Fetch/parse errors log **once**, keep the previous generation, and do not crash. Unchanged 304 / same hash → no write. On change, regenerates into `--out` (including `checksums.sha256`) and prints a line containing `regenerated`. Stop with Ctrl-C. Each poll still uses the **10s** fetch timeout. Optional `--check-baseline` still works without `--watch` (with `--watch`, re-checks after each regenerate without exiting).

## Dry-run

`generate --dry-run` parses the OpenAPI spec and prints a JSON object `{files, operations, tools, langs, packageName}` (file names that would be written, including `mcp-server.mjs`, `mcp_server.py`, `mcp_server.go`, `mcp.json`, `LICENSE`, `NOTICE`, and `.gitignore`, operation/tool counts, selected langs). It does **not** mkdir or write `--out` (existing files stay unchanged). Combine with `--lang` to preview a subset. `--no-mcp` omits the servers and `mcp.json` from the plan. `--no-license` omits `LICENSE` and `NOTICE`. `--no-gitignore` omits `.gitignore`. `--zip` adds `sdk.tgz` or `sdk.zip` to `files`. `--watch` / `--check-baseline` are skipped because nothing is on disk. With `--url`, dry-run still **fetches** the spec first (same 10s / 2MB / ≤3 redirects; `--header` / `SDK_FETCH_HEADER` on http(s)), then prints the plan (header **names** only if extra headers were sent — never values).

```bash
node src/cli.js generate examples/petstore.openapi.json --out out/petstore --dry-run
# stdout: {"files":["client.ts","client.py",...,"mcp-server.mjs","mcp_server.py","mcp_server.go","mcp.json","LICENSE","NOTICE",".gitignore","checksums.sha256"],"operations":4,"tools":4,"langs":["ts",...]}
```

## Fetch URL

`generate --url <url>` loads the OpenAPI document from the network (or `file://`) instead of a local path. **XOR** with the file operand: `generate spec.yaml --url …` exits 2. Default petstore local-mvp still uses a file path.

```bash
node src/cli.js generate --url http://127.0.0.1:8787/openapi.json --out out/from-url
node src/cli.js generate --url https://api.example/openapi.json --header "Authorization: Bearer $TOKEN" --out out/from-url
node src/cli.js generate --url file://$PWD/examples/openapi-3.1-mini.json --out out/from-file-url --lang ts,python --dry-run
```

Limits: **10s** timeout (all hops), **2MB** max body, follow **≤3** redirects (`http`/`https` only; no `file://` after a redirect). Non-2xx → exit 1 (`fetch OpenAPI failed: HTTP 404`). Schemes other than `http` / `https` / `file` are rejected. Link-local metadata IP `169.254.169.254` is blocked (no fetch). No extra deps (Node 18+ `fetch`). `--watch --url` polls the same fetch path (default **2s**; `--watch-interval-ms`).

Private specs: `--header "Name: value"` (repeatable) and optional env `SDK_FETCH_HEADER` (single). **http(s) `--url` only** — `--header` without `--url` exits 2; extra headers are **not** sent to `file://`. Authorization values are redacted in errors. `--dry-run` may list header **names** only (never values).

## Package name

`generate --package-name NAME` (alias `--package`; env `SDK_PACKAGE_NAME`) sets the company module path. Default **`client`** so petstore still emits `package client` / `namespace Client` / `class Client` and `listPets`.

- TypeScript: `package.json` `"name"`
- Python: `__package_name__` in `client.py`; when not `client`, also `{name}/__init__.py`
- Go: `package NAME` and module path suffix (`example.com/NAME`); README import uses that path
- Java / Kotlin: `package NAME`
- C#: `namespace PascalName`
- Ruby: `# gem: NAME` comment
- PHP: `namespace PascalName` when customized

`--dry-run` JSON includes `packageName`. MCP servers stay `mcp-server.mjs` / `mcp_server.py` / `mcp_server.go` (`package main`, not the SDK package name). Checksums still hash file contents (including `package.json` when TS is emitted).

```bash
node src/cli.js generate examples/petstore.openapi.json --out out/acme --package-name acme_pets --lang ts,python,go
```

## Checksums

Every `generate` writes `checksums.sha256` in `--out` (GNU `sha256sum` style: `<hex>  <filename>`), covering only the artifacts that exist among `client.ts`, `package.json`, `client.py`, `client.go`, `Client.java`, `client.rs`, `Client.cs`, `Client.kt`, `Client.swift`, `client.rb`, `Client.php`, `mcp-tools.json`, `mcp-server.mjs`, `mcp_server.py`, `mcp_server.go`, `mcp.json`, `README.md`, `LICENSE`, `NOTICE`, `.gitignore` (so `--lang ts` omits Python/Go/Java/Rust/C#/Kotlin/Swift/Ruby/PHP clients; `--no-mcp` omits the servers and `mcp.json`; `--no-license` omits `LICENSE` and `NOTICE`; `--no-gitignore` omits `.gitignore`). `--zip` archives (`sdk.tgz` / `sdk.zip`) are written **after** the manifest and are **not** listed (avoids a circular hash).

```bash
node src/cli.js generate examples/petstore.openapi.json --out out/petstore
# leftover demo: scripts/demo.sh writes out/demo and prints client.ts, mcp-server.mjs, mcp.json

# optional company module path: --package-name acme_pets  (alias --package; env SDK_PACKAGE_NAME)
node src/cli.js verify-checksums --out out/petstore   # exit 0 if match
# tweak a file → exit 1; regenerate restores a matching manifest
```

`verify-checksums --out <dir>` exits **0** when every listed file matches, **1** if the manifest or a file is missing or any hash mismatches.

## SDK archive (`--zip`)

Use generate with the zip flag to emit sdk.tgz (or sdk.zip) after checksums.
Preferred name is sdk.tgz when tar is on PATH; otherwise sdk.zip (Node stdlib, no extra dep).
The checksum manifest is written first and does not list the archive; the archive includes checksums.sha256.
Dry-run with the flag lists the archive name and writes nothing. Default generate without the flag is unchanged.
Watch mode re-creates the archive on each regenerate.

Example: node src/cli.js generate examples/petstore.openapi.json --out out/petstore --zip
Then list with tar tzf out/petstore/sdk.tgz (mcp.json, mcp-server.mjs, LICENSE, NOTICE, .gitignore, checksums.sha256).

## License files (Apache-2.0)

Default `generate` copies Apache-2.0 `LICENSE` (portfolio root `LICENSE` when found, else a short Apache-2.0 stub) and writes a generated `NOTICE` naming `--package-name` (default `client`) plus “based on OpenAPI from …” when the spec title/url is known. Pointer to `LICENSE`. Fetch `--header` values are **never** copied into NOTICE.

These are **generated artifacts**: each generate **always overwrites** `LICENSE` and `NOTICE` in `--out`. `--no-license` skips both (they vanish from dry-run `files`, checksums, and leftover files on regenerate). `--no-mcp` still writes them (license is independent of MCP). `--zip` archives include them unless `--no-license`.

```bash
node src/cli.js generate examples/petstore.openapi.json --out out/petstore
# leftover demo: scripts/demo.sh writes out/demo and prints client.ts, mcp-server.mjs, mcp.json

# LICENSE contains Apache; NOTICE names package client
node src/cli.js generate examples/petstore.openapi.json --out out/nolic --no-license
```

## Generated `.gitignore`

Default `generate` writes a consumer `.gitignore` in `--out` so committing the SDK does not pick up `__pycache__/`, `*.pyc`, `node_modules/`, `.DS_Store`, or `*.egg-info/`. Always overwritten (generated artifact). `--no-gitignore` skips it (omit from dry-run `files` + checksums; leftover `.gitignore` unlinked on regenerate). Independent of `--no-mcp` and `--no-license`. `--zip` archives include it unless skipped.

```bash
node src/cli.js generate examples/petstore.openapi.json --out out/petstore
# leftover demo: scripts/demo.sh writes out/demo and prints client.ts, mcp-server.mjs, mcp.json

# .gitignore contains node_modules
node src/cli.js generate examples/petstore.openapi.json --out out/nogi --no-gitignore
```

## Registry pack (dry-run)

Turn a **generated** stdio MCP server (`mcp-server.mjs`) into a local MCP Registry listing payload and tarball layout. This is a checklist-made-machine: write files + print `registry-pack-ok`. A human still publishes.

Do **not** pass this generator CLI (`@oss-cash-lab/sdk-mcp-gen`). The listing names the generated server (example identifier `@oss-cash-lab/petstore-mcp`). Never POSTs to registry.googleapis.com, registry.modelcontextprotocol.io, or npm.

```
node src/cli.js generate examples/petstore.openapi.json --out out/petstore
node src/cli.js registry-pack --in out/petstore --out out/petstore-registry
```

Writes `server.json` (official 2025-12-11 schema), wrapper `package.json` (`mcpName` matches `server.json` name), copied `mcp-server.mjs`, and `registry-pack.tgz` (`package/` layout) when tar is on PATH.

把生成的 `mcp-server.mjs` 打成本地 Registry 清单 + 包布局；只写文件，不上传。

## Dogfood on B

Portfolio `make dogfood-a-b` runs this generator against `bets/b-mcp-gateway/openapi/gateway.openapi.json` (see `scripts/generate-gateway-sdk.sh`).
