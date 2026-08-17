#!/usr/bin/env node
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import http from "node:http";
import { spawnSync, spawn } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";
import {
  listOperations,
  toMcpTools,
  generateTsClient,
  generatePyClient,
  generateGoClient,
  generateJavaClient,
  generateRustClient,
  generateCsharpClient,
  generateKotlinClient,
  generateSwiftClient,
  generateRubyClient,
  generatePhpClient,
  generateReadmeSnippet,
  generateMcpServer,
  generateMcpServerPy,
  generateMcpServerGo,
  generatePackageJson,
  resolvePackageName,
  splitPkg,
  DEFAULT_PACKAGE_NAME,
  MCP_SERVER_FILE,
  MCP_SERVER_PY_FILE,
  MCP_SERVER_GO_FILE,
  MCP_CONFIG_FILE,
  generateMcpClientConfig,
  isSupportedOpenApiVersion,
  unwrapNullUnion,
  schemaExample,
  paginationInfo,
  iterateHelperName,
} from "./openapi.js";
import { loadOpenApiSpec } from "./yaml.js";
import { fetchOpenApiText, parseFetchHeaderLines, redactSecretsInText, pollRemoteOpenApi, specWatchStateFromFetch, remoteSpecChange, hashSpecBody } from "./fetch-spec.js";
import { runCheck } from "./check.js";
import { writeChecksumManifest, runVerifyChecksums, CHECKSUMS_FILE } from "./checksums.js";
import { writeSdkArchive, plannedArchiveName, ARCHIVE_TGZ, ARCHIVE_ZIP } from "./archive.js";
import { writeLicenseArtifacts, removeLicenseArtifacts, LICENSE_FILE, NOTICE_FILE } from "./license.js";
import { writeGitignoreArtifact, removeGitignoreArtifact, GITIGNORE_FILE } from "./gitignore.js";

const VERSION = "0.1.0";
const DEFAULT_LANGS = ["ts", "python", "go", "java", "rust", "csharp", "kotlin", "swift", "ruby", "php"];

const demoSpec = {
  openapi: "3.0.0",
  info: { title: "Demo API", version: "1.0.0" },
  paths: {
    "/pets": {
      get: { operationId: "listPets", summary: "List all pets" },
      post: { operationId: "createPet", summary: "Create a pet" },
    },
    "/pets/{id}": {
      get: { operationId: "getPet", summary: "Get pet by id" },
    },
  },
};

function printHelp() {
  console.log(`sdk-mcp-gen v${VERSION}
Usage:
  sdk-mcp-gen --version
  sdk-mcp-gen smoke
  sdk-mcp-gen demo
  sdk-mcp-gen generate <openapi.json|yaml> --out <dir> [--lang ts,python,go,java,rust,csharp,kotlin,swift,ruby,php] [--base-url <url>] [--mcp] [--check-baseline <dir>] [--package-name <name>] [--watch] [--watch-interval-ms <n>] [--dry-run] [--zip] [--no-license] [--no-gitignore]
  sdk-mcp-gen generate --url <http(s)|file URL> --out <dir> [same flags]
                          OpenAPI 3.0.x and 3.1.x (paths only; 3.1 webhooks ignored).
                          File path and --url are XOR (both set → error). --watch works with file or --url.
                          Repeatable --header 'Name: value' (http/https --url only; env SDK_FETCH_HEADER).
  sdk-mcp-gen check --out <dir> --baseline <dir> [--no-clients]
  sdk-mcp-gen verify-checksums --out <dir>

Options:
  --lang <list>           Comma-separated languages to emit (default: ts,python,go,java,rust,csharp,kotlin,swift,ruby,php).
                          Aliases: py -> python, golang -> go, rs -> rust, cs / c# -> csharp, kt -> kotlin, rb -> ruby.
                          Always writes mcp-tools.json + README. LICENSE + NOTICE unless --no-license. .gitignore unless --no-gitignore. MCP servers + mcp.json unless --no-mcp.
  --mcp                   Include stdio MCP servers + mcp.json client snippet. Default on.
  --no-mcp                Skip MCP servers (mcp-server.mjs / mcp_server.py / mcp_server.go) and mcp.json.
  --base-url <url>        Baked default HTTP backend for mcp-server.mjs / mcp_server.py / mcp_server.go (runtime env MCP_BASE_URL wins).
  --check-baseline <dir>  After generate, run breaking check vs baseline dir (exit 1 if tools removed/renamed).
                          Works without --watch (one-shot exit). With --watch, re-checks after each regenerate without exiting.
  --watch                 Poll the spec and regenerate on change; print "regenerated" lines.
                          File: mtime every 200ms. --url: ETag / If-None-Match (304 skip) or body hash, default 2000ms.
  --watch-interval-ms <n> Poll interval in ms (min 50). Default 200 (file) or 2000 (--url).
  --package-name <name>   Company module path (alias --package; env SDK_PACKAGE_NAME). Default: client.
  --url <url>             Fetch OpenAPI from http://, https://, or file:// (timeout 10s, max 2MB, ≤3 redirects).
                          XOR with a file operand. Non-2xx → exit 1. --dry-run still lists outputs after a successful fetch.
                          --watch may poll --url (default 2s). Link-local 169.254.169.254 is blocked.
  --header <Name: value>  Extra HTTP header for --url fetch (repeatable). http(s) only; not sent to file://.
                          Error if used without --url. Optional env SDK_FETCH_HEADER (single Name: value).
                          Values are never printed; --dry-run may list header names only.
  --dry-run               Print planned {files, operations, tools, langs, packageName} JSON; write nothing to --out.
  --zip                   After checksums, pack --out into sdk.tgz (tar -czf) or sdk.zip (store-only fallback).
                          Archive is not listed in checksums.sha256. --dry-run lists the archive name.
  --license               Write LICENSE + NOTICE (Apache-2.0). Default on. Always overwritten on generate.
  --no-license            Skip LICENSE and NOTICE (omit from dry-run files + checksums; unlink leftovers).
  --gitignore             Write .gitignore (default on). Always overwritten on generate.
  --no-gitignore          Skip .gitignore (omit from dry-run files + checksums; unlink leftovers).
  --no-clients            With check: only compare mcp-tools.json names (skip client exports).

verify-checksums:
  Reads checksums.sha256 written by generate; exits 0 if all listed files match, 1 if missing/mismatch.
`);
}

function normalizeLang(raw) {
  const v = String(raw || "").trim().toLowerCase();
  if (v === "py" || v === "python") return "python";
  if (v === "ts" || v === "typescript") return "ts";
  if (v === "go" || v === "golang") return "go";
  if (v === "java") return "java";
  if (v === "rs" || v === "rust") return "rust";
  if (v === "cs" || v === "csharp" || v === "c#") return "csharp";
  if (v === "kt" || v === "kotlin") return "kotlin";
  if (v === "swift") return "swift";
  if (v === "rb" || v === "ruby") return "ruby";
  if (v === "php") return "php";
  return v;
}

function parseLangs(raw) {
  if (raw == null || raw === "") return [...DEFAULT_LANGS];
  const parts = String(raw)
    .split(",")
    .map((s) => normalizeLang(s))
    .filter(Boolean);
  const out = [];
  for (const p of parts) {
    if ((p === "ts" || p === "python" || p === "go" || p === "java" || p === "rust" || p === "csharp" || p === "kotlin" || p === "swift" || p === "ruby" || p === "php") && !out.includes(p)) out.push(p);
  }
  if (!out.length) {
    console.error("invalid --lang; use ts, python, go, java, rust, csharp, kotlin, swift, ruby, and/or php");
    process.exit(2);
  }
  return out;
}

const WATCH_POLL_MS = 200;
const WATCH_URL_POLL_MS = 2000;

function resolveWatchIntervalMs(raw, urlMode) {
  const fallback = urlMode ? WATCH_URL_POLL_MS : WATCH_POLL_MS;
  if (raw == null || String(raw).trim() === "") return fallback;
  const n = Number(String(raw).trim());
  if (!Number.isFinite(n) || n < 50) {
    console.error("invalid --watch-interval-ms; use an integer >= 50");
    process.exit(2);
  }
  return Math.floor(n);
}

function parseGenerateArgs(argv) {
  let input = null;
  let url = null;
  let headerLines = [];
  let out = null;
  let langRaw = null;
  let checkBaseline = null;
  let watch = false;
  let watchIntervalRaw = null;
  let dryRun = false;
  let zip = false;
  let baseUrl = "";
  let packageName = null;
  let mcp = true;
  let license = true;
  let gitignore = true;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--out" || a === "-o") out = argv[++i];
    else if (a === "--lang" || a === "-l") langRaw = argv[++i];
    else if (a.startsWith("--lang=")) langRaw = a.slice("--lang=".length);
    else if (a === "--check-baseline") checkBaseline = argv[++i];
    else if (a.startsWith("--check-baseline=")) checkBaseline = a.slice("--check-baseline=".length);
    else if (a === "--watch") watch = true;
    else if (a === "--watch-interval-ms") watchIntervalRaw = argv[++i];
    else if (a.startsWith("--watch-interval-ms=")) watchIntervalRaw = a.slice("--watch-interval-ms=".length);
    else if (a === "--dry-run") dryRun = true;
    else if (a === "--zip") zip = true;
    else if (a === "--mcp") mcp = true;
    else if (a === "--no-mcp") mcp = false;
    else if (a === "--license") license = true;
    else if (a === "--no-license") license = false;
    else if (a === "--gitignore") gitignore = true;
    else if (a === "--no-gitignore") gitignore = false;
    else if (a === "--base-url") baseUrl = argv[++i] || "";
    else if (a.startsWith("--base-url=")) baseUrl = a.slice("--base-url=".length);
    else if (a === "--package-name" || a === "--package") packageName = argv[++i];
    else if (a.startsWith("--package-name=")) packageName = a.slice("--package-name=".length);
    else if (a.startsWith("--package=")) packageName = a.slice("--package=".length);
    else if (a === "--url") url = argv[++i];
    else if (a.startsWith("--url=")) url = a.slice("--url=".length);
    else if (a === "--header") headerLines.push(argv[++i]);
    else if (a.startsWith("--header=")) headerLines.push(a.slice("--header=".length));
    else if (!a.startsWith("-") && !input) input = a;
  }
  // Convenience: with --check-baseline and no --out, generate into a temp dir.
  // --dry-run never creates dirs (including that temp).
  if (out == null) {
    out = !dryRun && checkBaseline
      ? fs.mkdtempSync(path.join(os.tmpdir(), "sdk-mcp-gen-check-"))
      : "out/generated";
  }
  if (packageName == null || String(packageName).trim() === "") {
    const envName = process.env.SDK_PACKAGE_NAME;
    if (envName && String(envName).trim()) packageName = String(envName).trim();
  }
  return { input, url, out, langs: parseLangs(langRaw), checkBaseline, watch, watchIntervalRaw, dryRun, zip, baseUrl, packageName, headerLines, mcp, license, gitignore };
}

/** Filenames generate would write for langs (same order as generateToDir). */
function listPlannedFiles(langs, { mcp = true, zip = false, license = true, gitignore = true } = {}) {
  const files = [];
  if (langs.includes("ts")) { files.push("client.ts"); files.push("package.json"); }
  if (langs.includes("python")) files.push("client.py");
  if (langs.includes("go")) files.push("client.go");
  if (langs.includes("java")) files.push("Client.java");
  if (langs.includes("rust")) files.push("client.rs");
  if (langs.includes("csharp")) files.push("Client.cs");
  if (langs.includes("kotlin")) files.push("Client.kt");
  if (langs.includes("swift")) files.push("Client.swift");
  if (langs.includes("ruby")) files.push("client.rb");
  if (langs.includes("php")) files.push("Client.php");
  files.push("mcp-tools.json");
  if (mcp) {
    files.push(MCP_SERVER_FILE);
    files.push(MCP_SERVER_PY_FILE);
    files.push(MCP_SERVER_GO_FILE);
    files.push(MCP_CONFIG_FILE);
  }
  files.push("README.md");
  if (license) {
    files.push(LICENSE_FILE);
    files.push(NOTICE_FILE);
  }
  if (gitignore) files.push(GITIGNORE_FILE);
  files.push(CHECKSUMS_FILE);
  if (zip) files.push(plannedArchiveName());
  return files;
}

function plannedGenerateSummary(spec, langs, packageName, { mcp = true, zip = false, license = true, gitignore = true } = {}) {
  const resolvedName = resolvePackageName(spec, packageName);
  const ops = listOperations(spec);
  const tools = toMcpTools(ops);
  return {
    files: listPlannedFiles(langs, { mcp, zip, license, gitignore }),
    operations: ops.length,
    tools: tools.length,
    langs,
    packageName: resolvedName,
  };
}

function parseCheckArgs(argv) {
  let out = null;
  let baseline = null;
  let checkClients = true;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--out" || a === "-o") out = argv[++i];
    else if (a === "--baseline" || a === "-b") baseline = argv[++i];
    else if (a.startsWith("--baseline=")) baseline = a.slice("--baseline=".length);
    else if (a === "--no-clients") checkClients = false;
    else if (a.startsWith("--out=")) out = a.slice("--out=".length);
  }
  return { out, baseline, checkClients };
}

function parseVerifyChecksumsArgs(argv) {
  let out = null;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--out" || a === "-o") out = argv[++i];
    else if (a.startsWith("--out=")) out = a.slice("--out=".length);
  }
  return { out };
}

function readSpec(filePath) {
  const absIn = path.resolve(filePath);
  const text = fs.readFileSync(absIn, "utf8");
  return loadOpenApiSpec(text, absIn);
}

function generateToDir(spec, absOut, langs, opts = {}) {
  const ops = listOperations(spec);
  const tools = toMcpTools(ops);
  fs.mkdirSync(absOut, { recursive: true });
  const title = spec.info?.title || "API";
  const baseUrl = opts.baseUrl || spec?.servers?.[0]?.url || "";
  const packageName = resolvePackageName(spec, opts.packageName);
  const pkgOpts = { packageName };
  const pkg = splitPkg(packageName);
  const files = [];
  if (langs.includes("ts")) {
    fs.writeFileSync(path.join(absOut, "client.ts"), generateTsClient(ops, title, pkgOpts));
    files.push("client.ts");
    fs.writeFileSync(path.join(absOut, "package.json"), generatePackageJson(title, packageName));
    files.push("package.json");
  }
  if (langs.includes("python")) {
    fs.writeFileSync(path.join(absOut, "client.py"), generatePyClient(ops, title, pkgOpts));
    files.push("client.py");
    if (pkg.customized) {
      const pyDir = path.join(absOut, pkg.ident);
      fs.mkdirSync(pyDir, { recursive: true });
      fs.writeFileSync(path.join(pyDir, "__init__.py"), generatePyClient(ops, title, pkgOpts));
    }
  }
  if (langs.includes("go")) {
    fs.writeFileSync(path.join(absOut, "client.go"), generateGoClient(ops, title, pkgOpts));
    files.push("client.go");
    if (pkg.customized) {
      fs.writeFileSync(path.join(absOut, "go.mod"), "module " + pkg.modPath + "\n\ngo 1.21\n");
    }
  }
  if (langs.includes("java")) {
    fs.writeFileSync(path.join(absOut, "Client.java"), generateJavaClient(ops, title, pkgOpts));
    files.push("Client.java");
  }
  if (langs.includes("rust")) {
    fs.writeFileSync(path.join(absOut, "client.rs"), generateRustClient(ops, title, pkgOpts));
    files.push("client.rs");
  }
  if (langs.includes("csharp")) {
    fs.writeFileSync(path.join(absOut, "Client.cs"), generateCsharpClient(ops, title, pkgOpts));
    files.push("Client.cs");
  }
  if (langs.includes("kotlin")) {
    fs.writeFileSync(path.join(absOut, "Client.kt"), generateKotlinClient(ops, title, pkgOpts));
    files.push("Client.kt");
  }
  if (langs.includes("swift")) {
    fs.writeFileSync(path.join(absOut, "Client.swift"), generateSwiftClient(ops, title, pkgOpts));
    files.push("Client.swift");
  }
  if (langs.includes("ruby")) {
    fs.writeFileSync(path.join(absOut, "client.rb"), generateRubyClient(ops, title, pkgOpts));
    files.push("client.rb");
  }
  if (langs.includes("php")) {
    fs.writeFileSync(path.join(absOut, "Client.php"), generatePhpClient(ops, title, pkgOpts));
    files.push("Client.php");
  }
  fs.writeFileSync(path.join(absOut, "mcp-tools.json"), JSON.stringify({ tools }, null, 2) + "\n");
  files.push("mcp-tools.json");
  const mcp = opts.mcp !== false;
  let mcpConfig = null;
  if (mcp) {
    fs.writeFileSync(path.join(absOut, MCP_SERVER_FILE), generateMcpServer(ops, title, { baseUrl }));
    files.push(MCP_SERVER_FILE);
    fs.writeFileSync(path.join(absOut, MCP_SERVER_PY_FILE), generateMcpServerPy(ops, title, { baseUrl }));
    files.push(MCP_SERVER_PY_FILE);
    fs.writeFileSync(path.join(absOut, MCP_SERVER_GO_FILE), generateMcpServerGo(ops, title, { baseUrl }));
    files.push(MCP_SERVER_GO_FILE);
    mcpConfig = generateMcpClientConfig(spec, {
      packageName,
      baseUrl,
      includeJs: true,
      includePy: true,
      includeGo: true,
    });
    fs.writeFileSync(path.join(absOut, MCP_CONFIG_FILE), JSON.stringify(mcpConfig, null, 2) + "\n");
    files.push(MCP_CONFIG_FILE);
  }
  const license = opts.license !== false;
  fs.writeFileSync(path.join(absOut, "README.md"), generateReadmeSnippet(ops, absOut, langs, packageName, { mcp, mcpConfig, license, gitignore: opts.gitignore !== false }));
  files.push("README.md");
  if (license) {
    writeLicenseArtifacts(absOut, spec, packageName);
    files.push(LICENSE_FILE);
    files.push(NOTICE_FILE);
  } else {
    removeLicenseArtifacts(absOut);
  }
  const gitignore = opts.gitignore !== false;
  if (gitignore) {
    writeGitignoreArtifact(absOut);
    files.push(GITIGNORE_FILE);
  } else {
    removeGitignoreArtifact(absOut);
  }
  writeChecksumManifest(absOut);
  files.push(CHECKSUMS_FILE);
  if (opts.zip) {
    files.push(writeSdkArchive(absOut));
  }
  return { ops, tools, files };
}

function maybeCheckBaseline(absOut, checkBaseline, { exitOnFail }) {
  if (!checkBaseline) return 0;
  const code = runCheck(absOut, checkBaseline, { checkClients: true });
  if (code !== 0) {
    console.error(`check-baseline failed (exit ${code})`);
    if (exitOnFail) process.exit(code);
  }
  return code;
}

/** Line-buffered-ish stdout for --watch (redirected logs must appear promptly). */
function watchLog(line) {
  const s = String(line).endsWith("\n") ? String(line) : `${line}\n`;
  try {
    fs.writeSync(1, s);
  } catch {
    console.log(String(line).replace(/\n$/, ""));
  }
}

function startWatch(inputPath, absOut, langs, checkBaseline, baseUrl, packageName, mcp = true, intervalMs = WATCH_POLL_MS, zip = false, license = true, gitignore = true) {
  const absIn = path.resolve(inputPath);
  const pollMs = intervalMs == null ? WATCH_POLL_MS : intervalMs;
  let lastMtimeMs;
  try {
    lastMtimeMs = fs.statSync(absIn).mtimeMs;
  } catch (err) {
    console.error(`watch: cannot stat ${absIn}: ${err.message || err}`);
    process.exit(1);
  }
  watchLog(`watching ${absIn} (poll ${pollMs}ms) -> ${absOut}`);
  setInterval(() => {
    try {
      const st = fs.statSync(absIn);
      if (!(st.mtimeMs > lastMtimeMs)) return;
      lastMtimeMs = st.mtimeMs;
      const spec = readSpec(absIn);
      const { ops, tools, files } = generateToDir(spec, absOut, langs, { baseUrl, packageName, mcp, zip, license, gitignore });
      watchLog(
        `regenerated ${JSON.stringify({ out: absOut, operations: ops.length, tools: tools.length, langs, files })}`,
      );
      maybeCheckBaseline(absOut, checkBaseline, { exitOnFail: false });
    } catch (err) {
      console.error(`watch regenerate error: ${err.message || err}`);
    }
  }, pollMs);
}

function watchErr(line) {
  const s = String(line).endsWith("\n") ? String(line) : `${line}\n`;
  try {
    fs.writeSync(2, s);
  } catch {
    console.error(String(line).replace(/\n$/, ""));
  }
}

function startUrlWatch(urlString, extraHeaders, absOut, langs, checkBaseline, baseUrl, packageName, mcp, intervalMs, initialState, zip = false, license = true, gitignore = true) {
  const pollMs = intervalMs == null ? WATCH_URL_POLL_MS : intervalMs;
  let prev = initialState || null;
  let inflight = false;
  let fetchErrorLogged = false;
  watchLog(`watching ${urlString} (poll ${pollMs}ms) -> ${absOut}`);
  setInterval(() => {
    if (inflight) return;
    inflight = true;
    (async () => {
      try {
        const { fetched, change, next } = await pollRemoteOpenApi(urlString, {
          headers: extraHeaders,
          prev,
          timeoutMs: 10_000,
        });
        prev = next;
        if (change !== "regen") {
          fetchErrorLogged = false;
          return;
        }
        if (!fetched || fetched.notModified || fetched.text == null || fetched.text === "") {
          fetchErrorLogged = false;
          return;
        }
        const spec = loadOpenApiSpec(fetched.text, fetched.filename);
        const { ops, tools, files } = generateToDir(spec, absOut, langs, { baseUrl, packageName, mcp, zip, license, gitignore });
        watchLog(
          `regenerated ${JSON.stringify({ out: absOut, operations: ops.length, tools: tools.length, langs, files })}`,
        );
        maybeCheckBaseline(absOut, checkBaseline, { exitOnFail: false });
        fetchErrorLogged = false;
      } catch (err) {
        const msg = redactSecretsInText(err && err.message ? err.message : String(err));
        if (!fetchErrorLogged) {
          watchErr(`watch fetch error: ${msg} (keeping previous generation)`);
          fetchErrorLogged = true;
        }
      } finally {
        inflight = false;
      }
    })();
  }, pollMs);
}

const SMOKE_FETCH_TOKEN = "test-token";
const SMOKE_FETCH_AUTH = "Bearer " + SMOKE_FETCH_TOKEN;

function smokeChildEnv(extra = {}) {
  const env = { ...process.env, ...extra };
  if (!Object.prototype.hasOwnProperty.call(extra, "SDK_FETCH_HEADER")) delete env.SDK_FETCH_HEADER;
  return env;
}

/** Async spawn so an in-process HTTP server can still accept connections (spawnSync blocks the loop). */
function spawnCliAsync(args, env, timeoutMs = 8000) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, args, { env });
    let stdout = "";
    let stderr = "";
    let done = false;
    const finish = (result) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      resolve(result);
    };
    const timer = setTimeout(() => {
      try { child.kill("SIGKILL"); } catch { /* ignore */ }
    }, timeoutMs);
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (d) => { stdout += d; });
    child.stderr.on("data", (d) => { stderr += d; });
    child.on("error", (error) => finish({ status: 1, stdout, stderr, error }));
    child.on("close", (status) => finish({ status, stdout, stderr }));
  });
}

function assertNoTokenLeak(label, ...parts) {
  const blob = parts.map((p) => (p == null ? "" : String(p))).join("\n");
  if (blob.includes(SMOKE_FETCH_TOKEN)) {
    console.error(label, "leaked fetch token");
    process.exit(1);
  }
}

function listenAuthSpecServer(specText) {
  const expected = SMOKE_FETCH_AUTH;
  const server = http.createServer((req, res) => {
    const auth = String(req.headers.authorization || "");
    if (auth !== expected) {
      res.writeHead(401, { "content-type": "text/plain" });
      res.end("unauthorized");
      return;
    }
    res.writeHead(200, { "content-type": "application/json" });
    res.end(specText);
  });
  return new Promise((resolve, reject) => {
    server.listen(0, "127.0.0.1", () => {
      const addr = server.address();
      resolve({ server, url: `http://127.0.0.1:${addr.port}/openapi.json` });
    });
    server.on("error", reject);
  });
}

async function smokeUrlAuthHeaders(cliPath, mini31Path, tmp) {
  const red = redactSecretsInText("Authorization: Bearer " + SMOKE_FETCH_TOKEN);
  if (red.includes(SMOKE_FETCH_TOKEN)) {
    console.error("smoke redactSecretsInText leaked token");
    process.exit(1);
  }
  try {
    parseFetchHeaderLines(["X-Foo: bar\r\nX-Injected: 1"]);
    console.error("smoke should reject CR/LF in --header");
    process.exit(1);
  } catch (err) {
    if (!/CR\/LF|invalid fetch header/i.test(err && err.message ? err.message : "")) {
      console.error("smoke CR/LF header message", err && err.message);
      process.exit(1);
    }
    assertNoTokenLeak("smoke CR/LF header", err && err.message);
  }

  const specText = fs.readFileSync(mini31Path, "utf8");
  const { server, url } = await listenAuthSpecServer(specText);
  try {
    let noHdrThrew = false;
    try {
      await fetchOpenApiText(url);
    } catch (err) {
      noHdrThrew = true;
      if (err.status !== 401) {
        console.error("smoke auth fetch without header should 401", err && err.message, err && err.status);
        process.exit(1);
      }
      assertNoTokenLeak("smoke auth fetch 401", err && err.message);
    }
    if (!noHdrThrew) {
      console.error("smoke auth fetch without header should fail");
      process.exit(1);
    }
    const okBody = await fetchOpenApiText(url, { headers: { Authorization: SMOKE_FETCH_AUTH } });
    if (!okBody.text || !okBody.text.includes("openapi")) {
      console.error("smoke auth fetch with header missing spec");
      process.exit(1);
    }

    const noHdr = await spawnCliAsync(
      [cliPath, "generate", "--url", url, "--out", path.join(tmp, "url-nohdr"), "--lang", "ts"],
      smokeChildEnv(),
    );
    if (noHdr.status === 0) {
      console.error("smoke generate --url without --header should fail");
      process.exit(1);
    }
    const noHdrMsg = String(noHdr.stderr || "") + String(noHdr.stdout || "");
    if (!/HTTP 401/.test(noHdrMsg)) {
      console.error("smoke generate --url without --header expected HTTP 401");
      process.exit(1);
    }
    assertNoTokenLeak("smoke generate no header", noHdr.stdout, noHdr.stderr);

    const hdrLine = "Authorization: " + SMOKE_FETCH_AUTH;
    const withHdr = await spawnCliAsync(
      [cliPath, "generate", "--url", url, "--out", path.join(tmp, "url-hdr"), "--lang", "ts", "--header", hdrLine],
      smokeChildEnv(),
    );
    if (withHdr.error || withHdr.status !== 0) {
      console.error("smoke generate --url --header failed", withHdr.status);
      process.exit(1);
    }
    assertNoTokenLeak("smoke generate --header", withHdr.stdout, withHdr.stderr);
    if (!fs.existsSync(path.join(tmp, "url-hdr", "client.ts"))) {
      console.error("smoke generate --url --header missing client.ts");
      process.exit(1);
    }

    const dryHdr = await spawnCliAsync(
      [cliPath, "generate", "--url", url, "--out", path.join(tmp, "url-hdr-dry"), "--lang", "ts", "--dry-run", "--header", hdrLine],
      smokeChildEnv(),
    );
    if (dryHdr.error || dryHdr.status !== 0) {
      console.error("smoke --url --header dry-run failed", dryHdr.status);
      process.exit(1);
    }
    assertNoTokenLeak("smoke dry-run --header", dryHdr.stdout, dryHdr.stderr);
    if (fs.existsSync(path.join(tmp, "url-hdr-dry"))) {
      console.error("smoke --url --header dry-run must not create out");
      process.exit(1);
    }
    let dryPlan;
    try {
      dryPlan = JSON.parse(String(dryHdr.stdout || "").trim().split(/\n/).filter(Boolean).pop());
    } catch {
      console.error("smoke --url --header dry-run not JSON");
      process.exit(1);
    }
    const names = dryPlan.headerNames || [];
    if (!names.includes("Authorization")) {
      console.error("smoke dry-run should list header name Authorization", names);
      process.exit(1);
    }
    if (JSON.stringify(dryPlan).includes(SMOKE_FETCH_TOKEN) || names.some((n) => String(n).includes(SMOKE_FETCH_TOKEN))) {
      console.error("smoke dry-run JSON leaked token");
      process.exit(1);
    }

    const envHdr = await spawnCliAsync(
      [cliPath, "generate", "--url", url, "--out", path.join(tmp, "url-envhdr"), "--lang", "ts"],
      smokeChildEnv({ SDK_FETCH_HEADER: hdrLine }),
    );
    if (envHdr.error || envHdr.status !== 0) {
      console.error("smoke SDK_FETCH_HEADER generate failed", envHdr.status);
      process.exit(1);
    }
    assertNoTokenLeak("smoke SDK_FETCH_HEADER", envHdr.stdout, envHdr.stderr);

    const noUrl = spawnSync(
      process.execPath,
      [cliPath, "generate", mini31Path, "--out", path.join(tmp, "hdr-nourl"), "--lang", "ts", "--header", hdrLine],
      { encoding: "utf8", timeout: 8000, env: smokeChildEnv() },
    );
    if (noUrl.status !== 2) {
      console.error("smoke --header without --url should exit 2", noUrl.status);
      process.exit(1);
    }
    assertNoTokenLeak("smoke --header without --url", noUrl.stdout, noUrl.stderr);

    const xorHdr = spawnSync(
      process.execPath,
      [cliPath, "generate", mini31Path, "--url", url, "--out", path.join(tmp, "xor-hdr"), "--header", hdrLine],
      { encoding: "utf8", timeout: 8000, env: smokeChildEnv() },
    );
    if (xorHdr.status === 0) {
      console.error("smoke path + --url + --header should fail XOR");
      process.exit(1);
    }
    if (xorHdr.status !== 2) {
      console.error("smoke XOR url+file should exit 2", xorHdr.status);
      process.exit(1);
    }
    assertNoTokenLeak("smoke xor header", xorHdr.stdout, xorHdr.stderr);
  } finally {
    await new Promise((resolve) => server.close(() => resolve()));
  }
}


function listenEtagSpecServer(specText, { etag = '"v1"' } = {}) {
  let body = String(specText);
  let currentEtag = etag;
  const server = http.createServer((req, res) => {
    const inm = String(req.headers["if-none-match"] || "");
    if (currentEtag && inm && inm === currentEtag) {
      res.writeHead(304, { etag: currentEtag });
      res.end();
      return;
    }
    const headers = { "content-type": "application/json" };
    if (currentEtag) headers.etag = currentEtag;
    res.writeHead(200, headers);
    res.end(body);
  });
  server.setSpec = (nextText, nextEtag) => {
    body = String(nextText);
    currentEtag = nextEtag == null ? currentEtag : nextEtag;
  };
  return new Promise((resolve, reject) => {
    server.listen(0, "127.0.0.1", () => {
      const addr = server.address();
      resolve({ server, url: `http://127.0.0.1:${addr.port}/openapi.json` });
    });
    server.on("error", reject);
  });
}

function listenHashSpecServer(specText) {
  let body = String(specText);
  const server = http.createServer((req, res) => {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(body);
  });
  server.setSpec = (nextText) => {
    body = String(nextText);
  };
  return new Promise((resolve, reject) => {
    server.listen(0, "127.0.0.1", () => {
      const addr = server.address();
      resolve({ server, url: `http://127.0.0.1:${addr.port}/openapi.json` });
    });
    server.on("error", reject);
  });
}

async function smokeUrlWatch(cliPath, mini31Path, tmp) {
  const specText = fs.readFileSync(mini31Path, "utf8");
  const mutated = (() => {
    const j = JSON.parse(specText);
    j.info = { ...(j.info || {}), description: "watch-hash-change" };
    return JSON.stringify(j);
  })();
  if (hashSpecBody(specText) === hashSpecBody(mutated)) {
    console.error("smoke url-watch mutated spec should change hash");
    process.exit(1);
  }
  if (remoteSpecChange({ hash: hashSpecBody(specText) }, { hash: hashSpecBody(specText), text: specText }) !== "skip") {
    console.error("smoke url-watch same hash should skip");
    process.exit(1);
  }
  if (remoteSpecChange({ hash: hashSpecBody(specText) }, { hash: hashSpecBody(mutated), text: mutated }) !== "regen") {
    console.error("smoke url-watch hash change should regen");
    process.exit(1);
  }
  if (remoteSpecChange({ etag: '"v1"', hash: "abc" }, { notModified: true }) !== "skip") {
    console.error("smoke url-watch 304 should skip");
    process.exit(1);
  }

  const { server: etagServer, url: etagUrl } = await listenEtagSpecServer(specText, { etag: '"v1"' });
  try {
    const first = await pollRemoteOpenApi(etagUrl);
    if (first.change !== "regen" || first.fetched.notModified || first.fetched.etag !== '"v1"') {
      console.error("smoke url-watch first etag fetch", first.fetched && first.fetched.etag, first.change);
      process.exit(1);
    }
    const second = await pollRemoteOpenApi(etagUrl, { prev: first.next });
    if (second.change !== "skip" || !second.fetched.notModified || second.fetched.status !== 304) {
      console.error("smoke url-watch expected 304 skip", second.fetched && second.fetched.status, second.change);
      process.exit(1);
    }
    etagServer.setSpec(mutated, '"v2"');
    const third = await pollRemoteOpenApi(etagUrl, { prev: second.next });
    if (third.change !== "regen" || third.fetched.notModified || third.fetched.etag !== '"v2"') {
      console.error("smoke url-watch etag change should regen", third.fetched && third.fetched.etag, third.change);
      process.exit(1);
    }
    if (third.next.hash === first.next.hash) {
      console.error("smoke url-watch etag change hash should differ");
      process.exit(1);
    }
  } finally {
    await new Promise((resolve) => etagServer.close(() => resolve()));
  }

  const { server: hashServer, url: hashUrl } = await listenHashSpecServer(specText);
  try {
    const h1 = await pollRemoteOpenApi(hashUrl);
    if (h1.change !== "regen" || !h1.next.hash) {
      console.error("smoke url-watch hash first poll", h1.change);
      process.exit(1);
    }
    const h2 = await pollRemoteOpenApi(hashUrl, { prev: h1.next });
    if (h2.change !== "skip") {
      console.error("smoke url-watch same body hash should skip", h2.change);
      process.exit(1);
    }
    hashServer.setSpec(mutated);
    const h3 = await pollRemoteOpenApi(hashUrl, { prev: h2.next });
    if (h3.change !== "regen") {
      console.error("smoke url-watch body hash change should regen", h3.change);
      process.exit(1);
    }
    if (h3.next.hash === h1.next.hash) {
      console.error("smoke url-watch hash after mutate should differ");
      process.exit(1);
    }
  } finally {
    await new Promise((resolve) => hashServer.close(() => resolve()));
  }

  // --header still applies to polls; secrets not logged; 304 skip then mutate regen (in-process server)
  const token = SMOKE_FETCH_TOKEN;
  const auth = "Bearer " + token;
  let body = specText;
  let etag = '"auth-v1"';
  const authServer = http.createServer((req, res) => {
    const got = String(req.headers.authorization || "");
    if (got !== auth) {
      res.writeHead(401, { "content-type": "text/plain" });
      res.end("unauthorized");
      return;
    }
    const inm = String(req.headers["if-none-match"] || "");
    if (etag && inm && inm === etag) {
      res.writeHead(304, { etag });
      res.end();
      return;
    }
    res.writeHead(200, { "content-type": "application/json", etag });
    res.end(body);
  });
  await new Promise((resolve, reject) => {
    authServer.listen(0, "127.0.0.1", resolve);
    authServer.on("error", reject);
  });
  try {
    const addr = authServer.address();
    const authUrl = `http://127.0.0.1:${addr.port}/openapi.json`;
    const hdrs = { Authorization: auth };
    const a1 = await pollRemoteOpenApi(authUrl, { headers: hdrs });
    if (a1.change !== "regen" || a1.fetched.status === 401) {
      console.error("smoke url-watch auth first poll failed", a1.fetched && a1.fetched.status);
      process.exit(1);
    }
    const a2 = await pollRemoteOpenApi(authUrl, { headers: hdrs, prev: a1.next });
    if (a2.change !== "skip" || !a2.fetched.notModified) {
      console.error("smoke url-watch auth 304 should skip");
      process.exit(1);
    }
    body = mutated;
    etag = '"auth-v2"';
    const a3 = await pollRemoteOpenApi(authUrl, { headers: hdrs, prev: a2.next });
    if (a3.change !== "regen") {
      console.error("smoke url-watch auth hash/etag change should regen");
      process.exit(1);
    }
    try {
      await pollRemoteOpenApi(authUrl);
      console.error("smoke url-watch poll without header should 401");
      process.exit(1);
    } catch (err) {
      if (err.status !== 401) {
        console.error("smoke url-watch missing header expected 401", err && err.message, err && err.status);
        process.exit(1);
      }
      assertNoTokenLeak("smoke url-watch 401", err && err.message);
    }
  } finally {
    await new Promise((resolve) => authServer.close(() => resolve()));
  }

  // fetch failure: poll throws; caller keeps previous (no crash)
  try {
    await pollRemoteOpenApi("http://127.0.0.1:9/openapi.json", { timeoutMs: 500 });
    console.error("smoke url-watch dead port should throw");
    process.exit(1);
  } catch (err) {
    const msg = redactSecretsInText(err && err.message ? err.message : String(err));
    if (!/fetch OpenAPI failed|timed out|ECONNREFUSED/i.test(msg)) {
      console.error("smoke url-watch dead port message", msg);
      process.exit(1);
    }
    assertNoTokenLeak("smoke url-watch dead port", msg);
  }
}

function archiveListingHas(listing, name) {
  return String(listing).split(/\r?\n/).some((line) => {
    const parts = line.trim().split(/\s+/);
    const last = (parts[parts.length - 1] || "").replace(/^\.\//, "").replace(/\\/g, "/");
    return last === name || last.endsWith("/" + name);
  });
}

function listSdkArchive(archivePath) {
  if (archivePath.endsWith(".tgz") || archivePath.endsWith(".tar.gz")) {
    const tz = spawnSync("tar", ["tzf", archivePath], { encoding: "utf8", timeout: 8000 });
    if (tz.error || tz.status !== 0) {
      throw new Error("tar tzf failed: " + (tz.stderr || tz.error || tz.status));
    }
    return tz.stdout || "";
  }
  const uz = spawnSync("unzip", ["-l", archivePath], { encoding: "utf8", timeout: 8000 });
  if (uz.error || uz.status !== 0) {
    throw new Error("unzip -l failed: " + (uz.stderr || uz.error || uz.status));
  }
  return uz.stdout || "";
}

function smokeZip(cliPath, specPath, tmp) {
  const zipDryDir = path.join(tmp, "zip-dry");
  const dry = spawnSync(
    process.execPath,
    [cliPath, "generate", specPath, "--out", zipDryDir, "--lang", "ts", "--zip", "--dry-run"],
    { encoding: "utf8", timeout: 8000, env: { ...process.env } },
  );
  if (dry.error || dry.status !== 0) {
    console.error("smoke --zip dry-run failed", dry.status, dry.stderr, dry.error);
    process.exit(1);
  }
  if (fs.existsSync(zipDryDir)) {
    console.error("smoke --zip dry-run must not create out");
    process.exit(1);
  }
  let plan;
  try {
    plan = JSON.parse(String(dry.stdout || "").trim().split(/\n/).filter(Boolean).pop());
  } catch {
    console.error("smoke --zip dry-run not JSON", dry.stdout);
    process.exit(1);
  }
  const archName = plan.files && plan.files.includes(ARCHIVE_TGZ)
    ? ARCHIVE_TGZ
    : plan.files && plan.files.includes(ARCHIVE_ZIP)
      ? ARCHIVE_ZIP
      : null;
  if (!archName) {
    console.error("smoke --zip dry-run missing archive name", plan.files);
    process.exit(1);
  }
  if (!plan.files.includes("mcp-server.mjs") && !plan.files.includes("client.ts")) {
    console.error("smoke --zip dry-run missing client/mcp", plan.files);
    process.exit(1);
  }

  const zipDir = path.join(tmp, "zip-cli");
  const gen = spawnSync(
    process.execPath,
    [cliPath, "generate", specPath, "--out", zipDir, "--lang", "ts", "--zip"],
    { encoding: "utf8", timeout: 15000, env: { ...process.env } },
  );
  if (gen.error || gen.status !== 0) {
    console.error("smoke generate --zip failed", gen.status, gen.stderr, gen.error);
    process.exit(1);
  }
  const tgzPath = path.join(zipDir, ARCHIVE_TGZ);
  const zipPath = path.join(zipDir, ARCHIVE_ZIP);
  let archivePath = null;
  if (fs.existsSync(tgzPath)) archivePath = tgzPath;
  else if (fs.existsSync(zipPath)) archivePath = zipPath;
  if (!archivePath) {
    console.error("smoke --zip archive missing on disk");
    process.exit(1);
  }
  const manifest = fs.readFileSync(path.join(zipDir, CHECKSUMS_FILE), "utf8");
  if (manifest.includes(ARCHIVE_TGZ) || manifest.includes(ARCHIVE_ZIP)) {
    console.error("smoke checksums must not list archive");
    process.exit(1);
  }
  if (runVerifyChecksums(zipDir) !== 0) {
    console.error("smoke verify-checksums after --zip failed");
    process.exit(1);
  }
  let listing;
  try {
    listing = listSdkArchive(archivePath);
  } catch (err) {
    console.error("smoke archive list failed", err && err.message);
    process.exit(1);
  }
  if (!archiveListingHas(listing, MCP_SERVER_FILE) && !archiveListingHas(listing, "client.ts")) {
    console.error("smoke archive listing missing mcp-server.mjs or client.ts", listing);
    process.exit(1);
  }
  if (!archiveListingHas(listing, CHECKSUMS_FILE)) {
    console.error("smoke archive should include checksums.sha256", listing);
    process.exit(1);
  }
  if (!archiveListingHas(listing, LICENSE_FILE) || !archiveListingHas(listing, NOTICE_FILE)) {
    console.error("smoke archive should include LICENSE and NOTICE", listing);
    process.exit(1);
  }
  if (!archiveListingHas(listing, GITIGNORE_FILE)) {
    console.error("smoke archive should include .gitignore", listing);
    process.exit(1);
  }

  const plainDir = path.join(tmp, "zip-plain");
  const plain = spawnSync(
    process.execPath,
    [cliPath, "generate", specPath, "--out", plainDir, "--lang", "ts"],
    { encoding: "utf8", timeout: 8000, env: { ...process.env } },
  );
  if (plain.error || plain.status !== 0) {
    console.error("smoke generate without --zip failed", plain.status, plain.stderr);
    process.exit(1);
  }
  if (fs.existsSync(path.join(plainDir, ARCHIVE_TGZ)) || fs.existsSync(path.join(plainDir, ARCHIVE_ZIP))) {
    console.error("smoke generate without --zip must not write archive");
    process.exit(1);
  }

  const zipPlan = plannedGenerateSummary(demoSpec, ["ts"], undefined, { zip: true });
  if (!zipPlan.files.includes(ARCHIVE_TGZ) && !zipPlan.files.includes(ARCHIVE_ZIP)) {
    console.error("smoke planned --zip missing archive", zipPlan.files);
    process.exit(1);
  }
}

const cmd = process.argv[2] || "help";
if (cmd === "--version" || cmd === "-V") {
  console.log(VERSION);
} else if (cmd === "smoke") {
  const ops = listOperations(demoSpec);
  const tools = toMcpTools(ops);
  if (ops.length !== 3 || tools.length !== 3) {
    console.error("smoke failed", ops.length);
    process.exit(1);
  }
  // YAML subset self-check
  const yamlDemo = [
    "openapi: \"3.0.0\"",
    "info:",
    "  title: Demo",
    "  version: \"1.0.0\"",
    "paths:",
    "  /pets:",
    "    get:",
    "      operationId: listPets",
    "      summary: List all pets",
  ].join("\n");
  const y = loadOpenApiSpec(yamlDemo, "demo.yaml");
  if (!y.paths || !y.paths["/pets"] || !y.paths["/pets"].get) {
    console.error("smoke yaml subset failed", y);
    process.exit(1);
  }
  const ts = generateTsClient(ops, "Demo API");
  if (
    !ts.includes("listPets") ||
    !ts.includes("createPet") ||
    !ts.includes("getPet") ||
    !ts.includes("function retryDelayMs") ||
    !ts.includes("429") ||
    !ts.includes("Retry-After")
  ) {
    console.error("smoke ts client retry failed");
    process.exit(1);
  }
  if (!/return \{\s*listPets,/.test(ts) || /return \{[^}]*retryDelayMs/.test(ts)) {
    console.error("smoke ts public method names changed");
    process.exit(1);
  }
  if (ts.includes("iterateListPets")) {
    console.error("smoke demo ts should not emit iterateListPets without pageable query params");
    process.exit(1);
  }
  const py = generatePyClient(ops, "Demo API");
  if (!py.includes("def listPets") || !py.includes("urllib.request") || !py.includes("429") || !py.includes("def _retry_delay_s")) {
    console.error("smoke python client failed");
    process.exit(1);
  }
  const go = generateGoClient(ops, "Demo API");
  if (
    !go.includes("package client") ||
    !go.includes("net/http") ||
    !go.includes("func (c *Client) ListPets") ||
    !go.includes("func (c *Client) CreatePet") ||
    !go.includes("func retryDelay") ||
    !go.includes("429")
  ) {
    console.error("smoke go client failed");
    process.exit(1);
  }
  const java = generateJavaClient(ops, "Demo API");
  if (
    !java.includes("package client") ||
    !java.includes("HttpURLConnection") ||
    !java.includes("public class Client") ||
    !java.includes("public Object listPets") ||
    !java.includes("public Object createPet")
  ) {
    console.error("smoke java client failed");
    process.exit(1);
  }
  const rust = generateRustClient(ops, "Demo API");
  if (
    !rust.includes("pub struct Client") ||
    !rust.includes("TcpStream") ||
    !rust.includes("pub fn list_pets") ||
    !rust.includes("pub fn create_pet") ||
    !rust.includes("pub fn get_pet")
  ) {
    console.error("smoke rust client failed");
    process.exit(1);
  }
  const csharp = generateCsharpClient(ops, "Demo API");
  if (
    !csharp.includes("namespace Client") ||
    !csharp.includes("HttpClient") ||
    !csharp.includes("public class Client") ||
    !csharp.includes("public object ListPets") ||
    !csharp.includes("public object CreatePet") ||
    !csharp.includes("public object GetPet")
  ) {
    console.error("smoke csharp client failed");
    process.exit(1);
  }
  const kotlin = generateKotlinClient(ops, "Demo API");
  if (
    !kotlin.includes("package client") ||
    !kotlin.includes("HttpURLConnection") ||
    !kotlin.includes("class Client") ||
    !kotlin.includes("fun listPets") ||
    !kotlin.includes("fun createPet") ||
    !kotlin.includes("fun getPet") ||
    /okhttp3|\bOkHttp\b|import\s+okhttp/i.test(kotlin)
  ) {
    console.error("smoke kotlin client failed");
    process.exit(1);
  }
  const swift = generateSwiftClient(ops, "Demo API");
  if (
    !swift.includes("import Foundation") ||
    !swift.includes("URLSession") ||
    !(swift.includes("class Client") || swift.includes("struct Client")) ||
    !swift.includes("func listPets") ||
    !swift.includes("func createPet") ||
    !swift.includes("func getPet") ||
    /Alamofire|import\s+Alamofire/i.test(swift)
  ) {
    console.error("smoke swift client failed");
    process.exit(1);
  }
  const ruby = generateRubyClient(ops, "Demo API");
  if (
    !ruby.includes("require \"net/http\"") ||
    !ruby.includes("Net::HTTP") ||
    !ruby.includes("class Client") ||
    !ruby.includes("def list_pets") ||
    !ruby.includes("def create_pet") ||
    !ruby.includes("def get_pet") ||
    /httparty|faraday|rest-client|require\s+[\"']net\/http\/persistent/i.test(ruby)
  ) {
    console.error("smoke ruby client failed");
    process.exit(1);
  }
  const php = generatePhpClient(ops, "Demo API");
  if (
    !php.includes("class Client") ||
    !php.includes("fopen") ||
    !php.includes("stream_context_create") ||
    !php.includes("public function listPets") ||
    !php.includes("public function createPet") ||
    !php.includes("public function getPet") ||
    /curl_init|curl_exec|curl_setopt/i.test(php)
  ) {
    console.error("smoke php client failed");
    process.exit(1);
  }
  // breaking-check self-smoke: identical dirs OK; drop one tool -> fail
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "sdk-mcp-gen-smoke-check-"));
  try {
    const baseDir = path.join(tmp, "base");
    const badDir = path.join(tmp, "bad");
    generateToDir(demoSpec, baseDir, ["ts"]);
    const badTools = toMcpTools(listOperations(demoSpec)).filter((t) => t.name !== "getPet");
    fs.mkdirSync(badDir, { recursive: true });
    fs.writeFileSync(path.join(badDir, "mcp-tools.json"), JSON.stringify({ tools: badTools }, null, 2));
    const okCode = runCheck(baseDir, baseDir, { checkClients: false });
    if (okCode !== 0) {
      console.error("smoke check identical failed");
      process.exit(1);
    }
    const badCode = runCheck(badDir, baseDir, { checkClients: false });
    if (badCode === 0) {
      console.error("smoke check removal should fail");
      process.exit(1);
    }
    // checksum manifest: generate writes checksums.sha256; verify OK; tweak fails
    const sumDir = path.join(tmp, "sums");
    const sumResult = generateToDir(demoSpec, sumDir, ["ts", "python", "go", "java", "rust", "csharp", "kotlin", "swift", "ruby", "php"]);
    const generatedTs = fs.readFileSync(path.join(sumDir, "client.ts"), "utf8");
    if (!generatedTs.includes("function retryDelayMs") || !generatedTs.includes("429") || !generatedTs.includes("listPets")) {
      console.error("smoke generated client.ts missing retry helper / 429");
      process.exit(1);
    }
    if (!fs.existsSync(path.join(sumDir, CHECKSUMS_FILE))) {
      console.error("smoke checksums.sha256 missing after generate");
      process.exit(1);
    }
    if (fs.existsSync(path.join(sumDir, ARCHIVE_TGZ)) || fs.existsSync(path.join(sumDir, ARCHIVE_ZIP))) {
      console.error("smoke default generate must not write sdk.tgz/sdk.zip");
      process.exit(1);
    }
    const plannedAll = listPlannedFiles(["ts", "python", "go", "java", "rust", "csharp", "kotlin", "swift", "ruby", "php"]);
    if (JSON.stringify(sumResult.files) !== JSON.stringify(plannedAll)) {
      console.error("smoke planned files mismatch generate", sumResult.files, plannedAll);
      process.exit(1);
    }
    if (plannedAll.includes(ARCHIVE_TGZ) || plannedAll.includes(ARCHIVE_ZIP) || sumResult.files.includes(ARCHIVE_TGZ) || sumResult.files.includes(ARCHIVE_ZIP)) {
      console.error("smoke default planned files must omit archive", sumResult.files, plannedAll);
      process.exit(1);
    }
    const dryDir = path.join(tmp, "dry-out");
    if (fs.existsSync(dryDir)) {
      console.error("smoke dry-run dir should not exist yet");
      process.exit(1);
    }
    const dryPlan = plannedGenerateSummary(demoSpec, ["ts"]);
    if (!dryPlan.files.includes("client.ts") || dryPlan.files.includes("client.py")) {
      console.error("smoke dry-run ts plan should list client.ts not client.py", dryPlan.files);
      process.exit(1);
    }
    if (dryPlan.operations !== 3 || dryPlan.tools !== 3) {
      console.error("smoke dry-run ops/tools mismatch", dryPlan);
      process.exit(1);
    }
    if (fs.existsSync(dryDir)) {
      console.error("smoke dry-run must not create out dir");
      process.exit(1);
    }
    const sumOk = runVerifyChecksums(sumDir);
    if (sumOk !== 0) {
      console.error("smoke verify-checksums identical failed");
      process.exit(1);
    }
    fs.appendFileSync(path.join(sumDir, "client.ts"), "\n// tweak\n");
    const sumBad = runVerifyChecksums(sumDir);
    if (sumBad === 0) {
      console.error("smoke verify-checksums should fail after tweak");
      process.exit(1);
    }
    // stdio MCP server: file exists, checksum lists it, tools/list JSON-RPC returns op names
    const mcpPath = path.join(sumDir, MCP_SERVER_FILE);
    if (!fs.existsSync(mcpPath)) {
      console.error("smoke mcp-server.mjs missing after generate");
      process.exit(1);
    }
    const mcpSrc = fs.readFileSync(mcpPath, "utf8");
    if (/@modelcontextprotocol\/sdk/.test(mcpSrc)) {
      console.error("smoke mcp-server must not depend on @modelcontextprotocol/sdk");
      process.exit(1);
    }
    const manifest = fs.readFileSync(path.join(sumDir, CHECKSUMS_FILE), "utf8");
    if (!manifest.includes(MCP_SERVER_FILE)) {
      console.error("smoke checksums.sha256 missing mcp-server.mjs");
      process.exit(1);
    }
    if (!plannedAll.includes(MCP_SERVER_FILE) || !sumResult.files.includes(MCP_SERVER_FILE)) {
      console.error("smoke planned files missing mcp-server.mjs", sumResult.files, plannedAll);
      process.exit(1);
    }
    const dryAll = plannedGenerateSummary(demoSpec, ["ts", "python", "go", "java", "rust", "csharp", "kotlin", "swift", "ruby", "php"]);
    if (!dryAll.files.includes(MCP_SERVER_FILE)) {
      console.error("smoke dry-run plan missing mcp-server.mjs", dryAll.files);
      process.exit(1);
    }
    const licPath = path.join(sumDir, LICENSE_FILE);
    const noticePath = path.join(sumDir, NOTICE_FILE);
    if (!fs.existsSync(licPath) || !fs.existsSync(noticePath)) {
      console.error("smoke default generate missing LICENSE/NOTICE");
      process.exit(1);
    }
    const licBody = fs.readFileSync(licPath, "utf8");
    if (!/Apache/i.test(licBody)) {
      console.error("smoke LICENSE should contain Apache");
      process.exit(1);
    }
    const noticeBody = fs.readFileSync(noticePath, "utf8");
    if (!noticeBody.includes("client") || !/Apache License, Version 2\.0/.test(noticeBody)) {
      console.error("smoke NOTICE should name package client and Apache-2.0", noticeBody.slice(0, 400));
      process.exit(1);
    }
    if (!manifest.includes(LICENSE_FILE) || !manifest.includes(NOTICE_FILE)) {
      console.error("smoke checksums.sha256 missing LICENSE/NOTICE");
      process.exit(1);
    }
    if (!dryAll.files.includes(LICENSE_FILE) || !dryAll.files.includes(NOTICE_FILE)) {
      console.error("smoke dry-run plan missing LICENSE/NOTICE", dryAll.files);
      process.exit(1);
    }
    if (!plannedAll.includes(LICENSE_FILE) || !sumResult.files.includes(LICENSE_FILE)) {
      console.error("smoke planned files missing LICENSE", sumResult.files, plannedAll);
      process.exit(1);
    }
    const giPath = path.join(sumDir, GITIGNORE_FILE);
    if (!fs.existsSync(giPath)) {
      console.error("smoke default generate missing .gitignore");
      process.exit(1);
    }
    const giBody = fs.readFileSync(giPath, "utf8");
    if (!giBody.includes("node_modules") || !giBody.includes("__pycache__/") || !giBody.includes("*.pyc") || !giBody.includes(".DS_Store") || !giBody.includes("*.egg-info/")) {
      console.error("smoke .gitignore missing expected entries", giBody);
      process.exit(1);
    }
    if (!manifest.includes(GITIGNORE_FILE)) {
      console.error("smoke checksums.sha256 missing .gitignore");
      process.exit(1);
    }
    if (!dryAll.files.includes(GITIGNORE_FILE) || !dryPlan.files.includes(GITIGNORE_FILE)) {
      console.error("smoke dry-run plan missing .gitignore", dryAll.files, dryPlan.files);
      process.exit(1);
    }
    if (!plannedAll.includes(GITIGNORE_FILE) || !sumResult.files.includes(GITIGNORE_FILE)) {
      console.error("smoke planned files missing .gitignore", sumResult.files, plannedAll);
      process.exit(1);
    }
    if (!plannedAll.includes(MCP_CONFIG_FILE) || !sumResult.files.includes(MCP_CONFIG_FILE)) {
      console.error("smoke planned files missing mcp.json", sumResult.files, plannedAll);
      process.exit(1);
    }
    if (!dryAll.files.includes(MCP_CONFIG_FILE) || !dryPlan.files.includes(MCP_CONFIG_FILE)) {
      console.error("smoke dry-run plan missing mcp.json", dryAll.files, dryPlan.files);
      process.exit(1);
    }
    if (!manifest.includes(MCP_CONFIG_FILE)) {
      console.error("smoke checksums.sha256 missing mcp.json");
      process.exit(1);
    }
    const mcpJsonPath = path.join(sumDir, MCP_CONFIG_FILE);
    if (!fs.existsSync(mcpJsonPath)) {
      console.error("smoke mcp.json missing after generate");
      process.exit(1);
    }
    let mcpCfg;
    try {
      mcpCfg = JSON.parse(fs.readFileSync(mcpJsonPath, "utf8"));
    } catch {
      console.error("smoke mcp.json not JSON");
      process.exit(1);
    }
    const mcpServers = mcpCfg && mcpCfg.mcpServers ? mcpCfg.mcpServers : {};
    const nodeEntry = Object.values(mcpServers).find((e) => e && e.command === "node");
    if (!nodeEntry || !Array.isArray(nodeEntry.args) || !nodeEntry.args.some((a) => String(a).includes("mcp-server.mjs"))) {
      console.error("smoke mcp.json missing node mcp-server.mjs", mcpCfg);
      process.exit(1);
    }
    if (!nodeEntry.env || !nodeEntry.env.MCP_BASE_URL) {
      console.error("smoke mcp.json missing MCP_BASE_URL", nodeEntry);
      process.exit(1);
    }
    if (!mcpServers.demo_api || mcpServers.demo_api.command !== "node") {
      console.error("smoke mcp.json key should be demo_api from title", Object.keys(mcpServers));
      process.exit(1);
    }
    if (!mcpServers["demo_api-py"] || mcpServers["demo_api-py"].command !== "python3") {
      console.error("smoke mcp.json missing python3 entry", Object.keys(mcpServers));
      process.exit(1);
    }
    const rpc = JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list", params: {} }) + "\n";
    const spawned = spawnSync(process.execPath, [mcpPath], {
      input: rpc,
      encoding: "utf8",
      timeout: 8000,
      env: { ...process.env },
    });
    if (spawned.error || spawned.status !== 0) {
      console.error("smoke mcp tools/list spawn failed", spawned.status, spawned.stderr, spawned.error);
      process.exit(1);
    }
    const outLine = String(spawned.stdout || "").trim().split(/\n/).filter(Boolean).pop();
    let listed;
    try {
      listed = JSON.parse(outLine);
    } catch {
      console.error("smoke mcp tools/list not JSON", spawned.stdout, spawned.stderr);
      process.exit(1);
    }
    const listedNames = (listed?.result?.tools || []).map((x) => x.name);
    for (const n of ["listPets", "createPet", "getPet"]) {
      if (!listedNames.includes(n)) {
        console.error("smoke mcp tools/list missing", n, listedNames);
        process.exit(1);
      }
    }
    const initRpc = JSON.stringify({ jsonrpc: "2.0", id: 2, method: "initialize", params: {} }) + "\n";
    const initSpawn = spawnSync(process.execPath, [mcpPath], {
      input: initRpc,
      encoding: "utf8",
      timeout: 8000,
      env: { ...process.env },
    });
    if (initSpawn.error || initSpawn.status !== 0) {
      console.error("smoke mcp initialize spawn failed", initSpawn.status, initSpawn.stderr, initSpawn.error);
      process.exit(1);
    }
    const initLine = String(initSpawn.stdout || "").trim().split(/\n/).filter(Boolean).pop();
    let initMsg;
    try {
      initMsg = JSON.parse(initLine);
    } catch {
      console.error("smoke mcp initialize not JSON", initSpawn.stdout, initSpawn.stderr);
      process.exit(1);
    }
    if (!initMsg?.result?.serverInfo?.name) {
      console.error("smoke mcp initialize missing serverInfo", initMsg);
      process.exit(1);
    }
    // Python stdio MCP server: same tools/list names as JS
    const mcpPyPath = path.join(sumDir, MCP_SERVER_PY_FILE);
    if (!fs.existsSync(mcpPyPath)) {
      console.error("smoke mcp_server.py missing after generate");
      process.exit(1);
    }
    const mcpPySrc = fs.readFileSync(mcpPyPath, "utf8");
    if (!mcpPySrc.startsWith("#!/usr/bin/env python3")) {
      console.error("smoke mcp_server.py missing python3 shebang");
      process.exit(1);
    }
    if (/import requests|from requests/.test(mcpPySrc)) {
      console.error("smoke mcp_server.py must not import requests");
      process.exit(1);
    }
    if (!manifest.includes(MCP_SERVER_PY_FILE)) {
      console.error("smoke checksums.sha256 missing mcp_server.py");
      process.exit(1);
    }
    if (!plannedAll.includes(MCP_SERVER_PY_FILE) || !sumResult.files.includes(MCP_SERVER_PY_FILE)) {
      console.error("smoke planned files missing mcp_server.py", sumResult.files, plannedAll);
      process.exit(1);
    }
    if (!dryAll.files.includes(MCP_SERVER_PY_FILE)) {
      console.error("smoke dry-run plan missing mcp_server.py", dryAll.files);
      process.exit(1);
    }
    const pySpawned = spawnSync("python3", [mcpPyPath], {
      input: rpc,
      encoding: "utf8",
      timeout: 8000,
      env: { ...process.env },
    });
    if (pySpawned.error || pySpawned.status !== 0) {
      console.error("smoke mcp py tools/list spawn failed", pySpawned.status, pySpawned.stderr, pySpawned.error);
      process.exit(1);
    }
    const pyOutLine = String(pySpawned.stdout || "").trim().split(/\n/).filter(Boolean).pop();
    let pyListed;
    try {
      pyListed = JSON.parse(pyOutLine);
    } catch {
      console.error("smoke mcp py tools/list not JSON", pySpawned.stdout, pySpawned.stderr);
      process.exit(1);
    }
    const pyNames = (pyListed?.result?.tools || []).map((x) => x.name);
    if (JSON.stringify(pyNames) !== JSON.stringify(listedNames)) {
      console.error("smoke mcp py tools/list names mismatch js", pyNames, listedNames);
      process.exit(1);
    }
    for (const n of ["listPets", "createPet", "getPet"]) {
      if (!pyNames.includes(n)) {
        console.error("smoke mcp py tools/list missing", n, pyNames);
        process.exit(1);
      }
    }
    // Go stdio MCP server: always written; tools/list if `go` on PATH, else source strings
    const mcpGoPath = path.join(sumDir, MCP_SERVER_GO_FILE);
    if (!fs.existsSync(mcpGoPath)) {
      console.error("smoke mcp_server.go missing after generate");
      process.exit(1);
    }
    const mcpGoSrc = fs.readFileSync(mcpGoPath, "utf8");
    if (!mcpGoSrc.includes("package main")) {
      console.error("smoke mcp_server.go missing package main");
      process.exit(1);
    }
    if (!mcpGoSrc.includes("net/http") || !mcpGoSrc.includes("encoding/json")) {
      console.error("smoke mcp_server.go must use stdlib net/http + encoding/json");
      process.exit(1);
    }
    if (!mcpGoSrc.includes("tools/list") || !mcpGoSrc.includes("initialize") || !mcpGoSrc.includes("tools/call")) {
      console.error("smoke mcp_server.go missing JSON-RPC methods");
      process.exit(1);
    }
    if (!mcpGoSrc.includes("listPets") || !mcpGoSrc.includes("MCP_BASE_URL")) {
      console.error("smoke mcp_server.go missing listPets / MCP_BASE_URL");
      process.exit(1);
    }
    if (!manifest.includes(MCP_SERVER_GO_FILE)) {
      console.error("smoke checksums.sha256 missing mcp_server.go");
      process.exit(1);
    }
    if (!plannedAll.includes(MCP_SERVER_GO_FILE) || !sumResult.files.includes(MCP_SERVER_GO_FILE)) {
      console.error("smoke planned files missing mcp_server.go", sumResult.files, plannedAll);
      process.exit(1);
    }
    if (!dryAll.files.includes(MCP_SERVER_GO_FILE)) {
      console.error("smoke dry-run plan missing mcp_server.go", dryAll.files);
      process.exit(1);
    }
    const goVer = spawnSync("go", ["version"], { encoding: "utf8", timeout: 5000, env: { ...process.env } });
    const goOk = !goVer.error && goVer.status === 0;
    if (goOk) {
      const goSpawned = spawnSync("go", ["run", mcpGoPath], {
        input: rpc,
        encoding: "utf8",
        timeout: 30000,
        env: { ...process.env },
      });
      if (goSpawned.error || goSpawned.status !== 0) {
        console.error("smoke mcp go tools/list spawn failed", goSpawned.status, goSpawned.stderr, goSpawned.error);
        process.exit(1);
      }
      const goOutLine = String(goSpawned.stdout || "").trim().split(/\n/).filter(Boolean).pop();
      let goListed;
      try {
        goListed = JSON.parse(goOutLine);
      } catch {
        console.error("smoke mcp go tools/list not JSON", goSpawned.stdout, goSpawned.stderr);
        process.exit(1);
      }
      const goNames = (goListed?.result?.tools || []).map((x) => x.name);
      if (JSON.stringify(goNames) !== JSON.stringify(listedNames)) {
        console.error("smoke mcp go tools/list names mismatch js", goNames, listedNames);
        process.exit(1);
      }
      for (const n of ["listPets", "createPet", "getPet"]) {
        if (!goNames.includes(n)) {
          console.error("smoke mcp go tools/list missing", n, goNames);
          process.exit(1);
        }
      }
    }
    const pkgDir = path.join(tmp, "pkg");
    generateToDir(demoSpec, pkgDir, ["ts", "python", "go"], { packageName: "acme_pets" });
    const pkgJson = fs.readFileSync(path.join(pkgDir, "package.json"), "utf8");
    if (!pkgJson.includes("acme_pets")) {
      console.error("smoke package-name missing from package.json");
      process.exit(1);
    }
    const pyPkg = fs.readFileSync(path.join(pkgDir, "client.py"), "utf8");
    if (!pyPkg.includes("acme_pets")) {
      console.error("smoke package-name missing from client.py");
      process.exit(1);
    }
    const goPkg = fs.readFileSync(path.join(pkgDir, "client.go"), "utf8");
    if (!goPkg.includes("package acme_pets")) {
      console.error("smoke package-name missing from client.go");
      process.exit(1);
    }
    if (!fs.existsSync(path.join(pkgDir, MCP_SERVER_FILE)) || !fs.existsSync(path.join(pkgDir, MCP_SERVER_PY_FILE)) || !fs.existsSync(path.join(pkgDir, MCP_SERVER_GO_FILE))) {
      console.error("smoke package-name must still write mcp servers");
      process.exit(1);
    }
    const pkgCfg = JSON.parse(fs.readFileSync(path.join(pkgDir, MCP_CONFIG_FILE), "utf8"));
    if (!pkgCfg.mcpServers || !pkgCfg.mcpServers.acme_pets || pkgCfg.mcpServers.acme_pets.command !== "node") {
      console.error("smoke package-name mcp.json key should be acme_pets", pkgCfg);
      process.exit(1);
    }
    const pkgGoSrc = fs.readFileSync(path.join(pkgDir, MCP_SERVER_GO_FILE), "utf8");
    if (!pkgGoSrc.includes("package main") || pkgGoSrc.includes("package acme_pets")) {
      console.error("smoke package-name mcp_server.go must stay package main");
      process.exit(1);
    }
    const pkgRpc = JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list", params: {} }) + "\n";
    const pkgSpawn = spawnSync(process.execPath, [path.join(pkgDir, MCP_SERVER_FILE)], {
      input: pkgRpc, encoding: "utf8", timeout: 8000, env: { ...process.env },
    });
    if (pkgSpawn.error || pkgSpawn.status !== 0) {
      console.error("smoke pkg mcp tools/list spawn failed", pkgSpawn.status, pkgSpawn.stderr);
      process.exit(1);
    }
    const pkgLine = String(pkgSpawn.stdout || "").trim().split(/\n/).filter(Boolean).pop();
    const pkgListed = JSON.parse(pkgLine);
    const pkgNames = (pkgListed?.result?.tools || []).map((x) => x.name);
    if (!pkgNames.includes("listPets")) {
      console.error("smoke pkg mcp tools/list missing listPets", pkgNames);
      process.exit(1);
    }
    const defDir = path.join(tmp, "defpkg");
    generateToDir(demoSpec, defDir, ["ts", "python", "go"]);
    const goDef = fs.readFileSync(path.join(defDir, "client.go"), "utf8");
    if (!goDef.includes("package client") || !goDef.includes("func (c *Client) ListPets")) {
      console.error("smoke default package should stay client + ListPets");
      process.exit(1);
    }
    const tsDef = fs.readFileSync(path.join(defDir, "client.ts"), "utf8");
    if (!tsDef.includes("listPets")) {
      console.error("smoke default ts missing listPets");
      process.exit(1);
    }
    const dryPkg = plannedGenerateSummary(demoSpec, ["ts"], "acme_pets");
    if (dryPkg.packageName !== "acme_pets") {
      console.error("smoke dry-run packageName", dryPkg);
      process.exit(1);
    }
    const dryDef = plannedGenerateSummary(demoSpec, ["ts"]);
    if (dryDef.packageName !== "client") {
      console.error("smoke dry-run default packageName", dryDef);
      process.exit(1);
    }
    if (!dryDef.files.includes("package.json")) {
      console.error("smoke dry-run ts should list package.json", dryDef.files);
      process.exit(1);
    }

    // --no-mcp skips servers + mcp.json (clients + mcp-tools.json still written)
    const noMcpDir = path.join(tmp, "nomcp");
    const noMcpResult = generateToDir(demoSpec, noMcpDir, ["ts"], { mcp: false });
    if (fs.existsSync(path.join(noMcpDir, MCP_SERVER_FILE)) || fs.existsSync(path.join(noMcpDir, MCP_SERVER_PY_FILE)) || fs.existsSync(path.join(noMcpDir, MCP_SERVER_GO_FILE)) || fs.existsSync(path.join(noMcpDir, MCP_CONFIG_FILE))) {
      console.error("smoke --no-mcp must not write MCP servers or mcp.json");
      process.exit(1);
    }
    if (!fs.existsSync(path.join(noMcpDir, "client.ts")) || !fs.existsSync(path.join(noMcpDir, "mcp-tools.json"))) {
      console.error("smoke --no-mcp should still write clients + mcp-tools.json");
      process.exit(1);
    }
    if (noMcpResult.files.includes(MCP_CONFIG_FILE) || noMcpResult.files.includes(MCP_SERVER_FILE)) {
      console.error("smoke --no-mcp files list should omit MCP artifacts", noMcpResult.files);
      process.exit(1);
    }
    const noMcpPlan = plannedGenerateSummary(demoSpec, ["ts"], undefined, { mcp: false });
    if (noMcpPlan.files.includes(MCP_CONFIG_FILE) || noMcpPlan.files.includes(MCP_SERVER_FILE) || noMcpPlan.files.includes(MCP_SERVER_PY_FILE) || noMcpPlan.files.includes(MCP_SERVER_GO_FILE)) {
      console.error("smoke --no-mcp dry-run should omit MCP files", noMcpPlan.files);
      process.exit(1);
    }
    if (!noMcpPlan.files.includes("client.ts") || !noMcpPlan.files.includes("mcp-tools.json")) {
      console.error("smoke --no-mcp dry-run missing client/tools", noMcpPlan.files);
      process.exit(1);
    }
    if (!fs.existsSync(path.join(noMcpDir, LICENSE_FILE)) || !fs.existsSync(path.join(noMcpDir, NOTICE_FILE))) {
      console.error("smoke --no-mcp should still write LICENSE/NOTICE");
      process.exit(1);
    }
    if (!noMcpPlan.files.includes(LICENSE_FILE) || !noMcpPlan.files.includes(NOTICE_FILE) || !noMcpResult.files.includes(LICENSE_FILE)) {
      console.error("smoke --no-mcp files should include LICENSE/NOTICE", noMcpResult.files, noMcpPlan.files);
      process.exit(1);
    }
    if (!fs.existsSync(path.join(noMcpDir, GITIGNORE_FILE))) {
      console.error("smoke --no-mcp should still write .gitignore");
      process.exit(1);
    }
    if (!noMcpPlan.files.includes(GITIGNORE_FILE) || !noMcpResult.files.includes(GITIGNORE_FILE)) {
      console.error("smoke --no-mcp files should include .gitignore", noMcpResult.files, noMcpPlan.files);
      process.exit(1);
    }

    // --no-license skips LICENSE + NOTICE (independent of MCP)
    const noLicDir = path.join(tmp, "nolicense");
    const noLicResult = generateToDir(demoSpec, noLicDir, ["ts"], { license: false });
    if (fs.existsSync(path.join(noLicDir, LICENSE_FILE)) || fs.existsSync(path.join(noLicDir, NOTICE_FILE))) {
      console.error("smoke --no-license must not write LICENSE/NOTICE");
      process.exit(1);
    }
    if (noLicResult.files.includes(LICENSE_FILE) || noLicResult.files.includes(NOTICE_FILE)) {
      console.error("smoke --no-license files list should omit LICENSE/NOTICE", noLicResult.files);
      process.exit(1);
    }
    const noLicPlan = plannedGenerateSummary(demoSpec, ["ts"], undefined, { license: false });
    if (noLicPlan.files.includes(LICENSE_FILE) || noLicPlan.files.includes(NOTICE_FILE)) {
      console.error("smoke --no-license dry-run should omit LICENSE/NOTICE", noLicPlan.files);
      process.exit(1);
    }
    const noLicManifest = fs.readFileSync(path.join(noLicDir, CHECKSUMS_FILE), "utf8");
    if (noLicManifest.includes(LICENSE_FILE) || noLicManifest.includes(NOTICE_FILE)) {
      console.error("smoke --no-license checksums should omit LICENSE/NOTICE");
      process.exit(1);
    }
    if (!noLicPlan.files.includes("client.ts") || !fs.existsSync(path.join(noLicDir, "client.ts"))) {
      console.error("smoke --no-license should still write clients");
      process.exit(1);
    }
    if (!fs.existsSync(path.join(noLicDir, GITIGNORE_FILE)) || !noLicResult.files.includes(GITIGNORE_FILE) || !noLicPlan.files.includes(GITIGNORE_FILE)) {
      console.error("smoke --no-license should still write .gitignore");
      process.exit(1);
    }
    // leftover LICENSE/NOTICE from a prior generate vanish on --no-license regenerate
    generateToDir(demoSpec, noLicDir, ["ts"]);
    if (!fs.existsSync(path.join(noLicDir, LICENSE_FILE))) {
      console.error("smoke regenerate should restore LICENSE before --no-license");
      process.exit(1);
    }
    generateToDir(demoSpec, noLicDir, ["ts"], { license: false });
    if (fs.existsSync(path.join(noLicDir, LICENSE_FILE)) || fs.existsSync(path.join(noLicDir, NOTICE_FILE))) {
      console.error("smoke --no-license regenerate should unlink leftover LICENSE/NOTICE");
      process.exit(1);
    }

    // --no-gitignore skips .gitignore (independent of MCP and license)
    const noGiDir = path.join(tmp, "nogitignore");
    const noGiResult = generateToDir(demoSpec, noGiDir, ["ts"], { gitignore: false });
    if (fs.existsSync(path.join(noGiDir, GITIGNORE_FILE))) {
      console.error("smoke --no-gitignore must not write .gitignore");
      process.exit(1);
    }
    if (noGiResult.files.includes(GITIGNORE_FILE)) {
      console.error("smoke --no-gitignore files list should omit .gitignore", noGiResult.files);
      process.exit(1);
    }
    const noGiPlan = plannedGenerateSummary(demoSpec, ["ts"], undefined, { gitignore: false });
    if (noGiPlan.files.includes(GITIGNORE_FILE)) {
      console.error("smoke --no-gitignore dry-run should omit .gitignore", noGiPlan.files);
      process.exit(1);
    }
    const noGiManifest = fs.readFileSync(path.join(noGiDir, CHECKSUMS_FILE), "utf8");
    if (noGiManifest.includes(GITIGNORE_FILE)) {
      console.error("smoke --no-gitignore checksums should omit .gitignore");
      process.exit(1);
    }
    if (!fs.existsSync(path.join(noGiDir, LICENSE_FILE)) || !fs.existsSync(path.join(noGiDir, NOTICE_FILE))) {
      console.error("smoke --no-gitignore should still write LICENSE/NOTICE");
      process.exit(1);
    }
    if (!noGiPlan.files.includes(LICENSE_FILE) || !noGiResult.files.includes(LICENSE_FILE)) {
      console.error("smoke --no-gitignore files should include LICENSE", noGiResult.files, noGiPlan.files);
      process.exit(1);
    }
    if (!noGiPlan.files.includes("client.ts") || !fs.existsSync(path.join(noGiDir, "client.ts"))) {
      console.error("smoke --no-gitignore should still write clients");
      process.exit(1);
    }
    if (!fs.existsSync(path.join(noGiDir, MCP_SERVER_FILE))) {
      console.error("smoke --no-gitignore should still write MCP servers");
      process.exit(1);
    }
    generateToDir(demoSpec, noGiDir, ["ts"]);
    if (!fs.existsSync(path.join(noGiDir, GITIGNORE_FILE))) {
      console.error("smoke regenerate should restore .gitignore before --no-gitignore");
      process.exit(1);
    }
    generateToDir(demoSpec, noGiDir, ["ts"], { gitignore: false });
    if (fs.existsSync(path.join(noGiDir, GITIGNORE_FILE))) {
      console.error("smoke --no-gitignore regenerate should unlink leftover .gitignore");
      process.exit(1);
    }
    if (!fs.existsSync(path.join(noGiDir, LICENSE_FILE))) {
      console.error("smoke --no-gitignore regenerate should keep LICENSE");
      process.exit(1);
    }

    // petstore fixture: mcp.json paste snippet
    const petstorePath = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "examples", "petstore.openapi.json");
    if (!fs.existsSync(petstorePath)) {
      console.error("smoke missing examples/petstore.openapi.json");
      process.exit(1);
    }
    const petstoreSpec = readSpec(petstorePath);
    const petDir = path.join(tmp, "petstore-mcpjson");
    generateToDir(petstoreSpec, petDir, ["ts"]);
    const petCfgPath = path.join(petDir, MCP_CONFIG_FILE);
    if (!fs.existsSync(petCfgPath)) {
      console.error("smoke petstore mcp.json missing");
      process.exit(1);
    }
    const petCfg = JSON.parse(fs.readFileSync(petCfgPath, "utf8"));
    const petServers = petCfg.mcpServers || {};
    if (!petServers.petstore || petServers.petstore.command !== "node") {
      console.error("smoke petstore mcp.json missing petstore node entry", petCfg);
      process.exit(1);
    }
    if (!Array.isArray(petServers.petstore.args) || !petServers.petstore.args.includes("./mcp-server.mjs")) {
      console.error("smoke petstore mcp.json args should be relative ./mcp-server.mjs", petServers.petstore);
      process.exit(1);
    }

    // pageable petstore listPets (limit query) gets iterateListPets; existing names stay
    const petOps = listOperations(petstoreSpec);
    const listPetOp = petOps.find((o) => o.operationId === "listPets");
    const listInfo = paginationInfo(listPetOp);
    if (!listInfo || listInfo.limit !== "limit" || iterateHelperName("listPets") !== "iterateListPets") {
      console.error("smoke paginationInfo listPets", listInfo);
      process.exit(1);
    }
    if (paginationInfo(petOps.find((o) => o.operationId === "createPet"))) {
      console.error("smoke createPet should not be pageable");
      process.exit(1);
    }
    const petClients = path.join(tmp, "petstore-page");
    generateToDir(petstoreSpec, petClients, ["ts", "python", "go"]);
    const petTs = fs.readFileSync(path.join(petClients, "client.ts"), "utf8");
    if (!petTs.includes("async function listPets") || !petTs.includes("iterateListPets") || !petTs.includes("next_cursor") || !petTs.includes("nextPageToken")) {
      console.error("smoke petstore client.ts missing listPets / iterateListPets helper");
      process.exit(1);
    }
    if (!/return \{\s*listPets,/.test(petTs) || !petTs.includes("iterateListPets,")) {
      console.error("smoke petstore client.ts should keep listPets and export iterateListPets");
      process.exit(1);
    }
    const petPy = fs.readFileSync(path.join(petClients, "client.py"), "utf8");
    if (!petPy.includes("def listPets") || !petPy.includes("def iterateListPets") || !petPy.includes("def _page_len")) {
      console.error("smoke petstore client.py missing iterateListPets");
      process.exit(1);
    }
    const petGo = fs.readFileSync(path.join(petClients, "client.go"), "utf8");
    if (!petGo.includes("func (c *Client) ListPets") || !petGo.includes("func (c *Client) IterateListPets") || !petGo.includes("nextPageToken")) {
      console.error("smoke petstore client.go missing IterateListPets");
      process.exit(1);
    }
    const petToolNames = (JSON.parse(fs.readFileSync(path.join(petClients, "mcp-tools.json"), "utf8")).tools || []).map((t) => t.name);
    for (const n of ["listPets", "createPet", "getPet", "deletePet"]) {
      if (!petToolNames.includes(n)) {
        console.error("smoke petstore tools missing", n, petToolNames);
        process.exit(1);
      }
    }
    if (petToolNames.includes("iterateListPets")) {
      console.error("smoke iterate helper must not become an MCP tool", petToolNames);
      process.exit(1);
    }
    const petBase = path.join(tmp, "petstore-page-base");
    const petNew = path.join(tmp, "petstore-page-new");
    generateToDir(petstoreSpec, petBase, ["ts", "python", "go"]);
    generateToDir(petstoreSpec, petNew, ["ts", "python", "go"]);
    if (runCheck(petNew, petBase, { checkClients: true }) !== 0) {
      console.error("smoke petstore breaking check should stay green for existing names");
      process.exit(1);
    }
    const pagePy = path.join(petClients, "_page_smoke.py");
    fs.writeFileSync(pagePy, [
      "import json, urllib.parse",
      "from client import Client",
      "class FakeRes:",
      "    def __init__(self, body):",
      "        self._b = json.dumps(body).encode()",
      "    def read(self):",
      "        return self._b",
      "    def __enter__(self):",
      "        return self",
      "    def __exit__(self, *a):",
      "        return False",
      "class FakeOpener:",
      "    def open(self, req):",
      "        url = getattr(req, 'full_url', str(req))",
      "        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)",
      "        page = int((q.get('page') or ['1'])[0])",
      "        if page <= 1:",
      "            return FakeRes([{'id': 1}, {'id': 2}])",
      "        if page == 2:",
      "            return FakeRes([{'id': 3}])",
      "        return FakeRes([])",
      "c = Client('http://example.test', opener=FakeOpener())",
      "pages = list(c.iterateListPets({'limit': 2}))",
      "assert pages == [[{'id': 1}, {'id': 2}], [{'id': 3}]], pages",
      "print('page-iter-ok')",
      "",
    ].join("\n"));
    const pageRun = spawnSync("python3", [pagePy], { encoding: "utf8", timeout: 8000, cwd: petClients, env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" } });
    if (pageRun.error || pageRun.status !== 0 || !String(pageRun.stdout || "").includes("page-iter-ok")) {
      console.error("smoke petstore iterateListPets runtime failed", pageRun.status, pageRun.stdout, pageRun.stderr, pageRun.error);
      process.exit(1);
    }

    // cursor-mode fixture used only in smoke (does not change petstore tool names)
    const cursorSpec = {
      openapi: "3.0.3",
      info: { title: "Cursor API", version: "1.0.0" },
      paths: {
        "/items": {
          get: {
            operationId: "listItems",
            summary: "List items",
            parameters: [{ name: "cursor", in: "query", schema: { type: "string" } }],
            responses: { "200": { description: "ok" } },
          },
        },
      },
    };
    const curInfo = paginationInfo(listOperations(cursorSpec)[0]);
    if (!curInfo || curInfo.mode !== "cursor" || curInfo.cursor !== "cursor") {
      console.error("smoke cursor paginationInfo", curInfo);
      process.exit(1);
    }
    const curDir = path.join(tmp, "cursor-page");
    generateToDir(cursorSpec, curDir, ["ts", "python"]);
    const curTs = fs.readFileSync(path.join(curDir, "client.ts"), "utf8");
    if (!curTs.includes("async function listItems") || !curTs.includes("iterateListItems")) {
      console.error("smoke cursor client.ts missing iterateListItems");
      process.exit(1);
    }
    const curPy = path.join(curDir, "_cursor_smoke.py");
    fs.writeFileSync(curPy, [
      "import json, urllib.parse",
      "from client import Client",
      "class FakeRes:",
      "    def __init__(self, body):",
      "        self._b = json.dumps(body).encode()",
      "    def read(self):",
      "        return self._b",
      "    def __enter__(self):",
      "        return self",
      "    def __exit__(self, *a):",
      "        return False",
      "class FakeOpener:",
      "    def open(self, req):",
      "        url = getattr(req, 'full_url', str(req))",
      "        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)",
      "        cur = (q.get('cursor') or [''])[0]",
      "        if not cur:",
      "            return FakeRes({'data': [1, 2], 'next_cursor': 'abc'})",
      "        if cur == 'abc':",
      "            return FakeRes({'data': [3], 'next_cursor': ''})",
      "        return FakeRes({'data': []})",
      "c = Client('http://example.test', opener=FakeOpener())",
      "pages = list(c.iterateListItems({}))",
      "assert pages == [{'data': [1, 2], 'next_cursor': 'abc'}, {'data': [3], 'next_cursor': ''}], pages",
      "print('cursor-iter-ok')",
      "",
    ].join("\n"));
    const curRun = spawnSync("python3", [curPy], { encoding: "utf8", timeout: 8000, cwd: curDir, env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" } });
    if (curRun.error || curRun.status !== 0 || !String(curRun.stdout || "").includes("cursor-iter-ok")) {
      console.error("smoke cursor iterateListItems runtime failed", curRun.status, curRun.stdout, curRun.stderr, curRun.error);
      process.exit(1);
    }

    // OpenAPI 3.1 mini: accept 3.1.x, type unions, examples, $ref, ignore webhooks
    if (!isSupportedOpenApiVersion("3.1.0") || !isSupportedOpenApiVersion("3.1.1") || !isSupportedOpenApiVersion("3.0.3")) {
      console.error("smoke isSupportedOpenApiVersion 3.0/3.1");
      process.exit(1);
    }
    const mini31Path = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "examples", "openapi-3.1-mini.json");
    if (!fs.existsSync(mini31Path)) {
      console.error("smoke missing examples/openapi-3.1-mini.json");
      process.exit(1);
    }
    const mini31 = readSpec(mini31Path);
    if (!isSupportedOpenApiVersion(mini31.openapi) || !String(mini31.openapi).startsWith("3.1")) {
      console.error("smoke 3.1 version not accepted", mini31.openapi);
      process.exit(1);
    }
    const miniOps = listOperations(mini31);
    const miniNames = miniOps.map((o) => o.operationId);
    for (const n of ["listItems", "createItem", "getItem"]) {
      if (!miniNames.includes(n)) {
        console.error("smoke 3.1 missing op", n, miniNames);
        process.exit(1);
      }
    }
    if (miniNames.includes("itemChangedWebhook")) {
      console.error("smoke 3.1 webhooks must be ignored", miniNames);
      process.exit(1);
    }
    const createOp = miniOps.find((o) => o.operationId === "createItem");
    const tagSch = createOp?.inputSchema?.properties?.tag;
    const unTag = unwrapNullUnion(tagSch);
    if (!tagSch || unTag?.type !== "string") {
      console.error("smoke 3.1 type union should be string optional", tagSch);
      process.exit(1);
    }
    if ((createOp.inputSchema.required || []).includes("tag")) {
      console.error("smoke 3.1 nullable tag should not be required", createOp.inputSchema);
      process.exit(1);
    }
    if (!createOp.inputSchema.properties?.name) {
      console.error("smoke 3.1 $ref body should expose name", createOp.inputSchema);
      process.exit(1);
    }
    const qSch = miniOps.find((o) => o.operationId === "listItems")?.inputSchema?.properties?.q;
    const qEx = schemaExample(qSch);
    if (qEx !== "abc" && qSch?.example !== "abc") {
      console.error("smoke 3.1 examples vs example", qSch);
      process.exit(1);
    }
    const miniDir = path.join(tmp, "oa31");
    generateToDir(mini31, miniDir, ["ts", "python"]);
    if (!fs.existsSync(path.join(miniDir, "client.ts")) || !fs.existsSync(path.join(miniDir, "client.py"))) {
      console.error("smoke 3.1 missing ts/py client");
      process.exit(1);
    }
    const miniCfgPath = path.join(miniDir, MCP_CONFIG_FILE);
    if (!fs.existsSync(miniCfgPath)) {
      console.error("smoke 3.1 mcp.json missing");
      process.exit(1);
    }
    const miniCfg = JSON.parse(fs.readFileSync(miniCfgPath, "utf8"));
    const miniServers = miniCfg.mcpServers || {};
    const miniNode = Object.values(miniServers).find((e) => e && e.command === "node");
    if (!miniNode || !Array.isArray(miniNode.args) || !miniNode.args.some((a) => String(a).includes("mcp-server.mjs"))) {
      console.error("smoke 3.1 mcp.json missing node mcp-server.mjs", miniCfg);
      process.exit(1);
    }
    const ts31 = fs.readFileSync(path.join(miniDir, "client.ts"), "utf8");
    const py31 = fs.readFileSync(path.join(miniDir, "client.py"), "utf8");
    if (!ts31.includes("listItems") || !py31.includes("def listItems")) {
      console.error("smoke 3.1 clients missing listItems");
      process.exit(1);
    }
    const mcp31 = path.join(miniDir, MCP_SERVER_FILE);
    const rpc31 = JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list", params: {} }) + "\n";
    const spawn31 = spawnSync(process.execPath, [mcp31], {
      input: rpc31, encoding: "utf8", timeout: 8000, env: { ...process.env },
    });
    if (spawn31.error || spawn31.status !== 0) {
      console.error("smoke 3.1 mcp tools/list spawn failed", spawn31.status, spawn31.stderr, spawn31.error);
      process.exit(1);
    }
    const line31 = String(spawn31.stdout || "").trim().split(/\n/).filter(Boolean).pop();
    let listed31;
    try {
      listed31 = JSON.parse(line31);
    } catch {
      console.error("smoke 3.1 mcp tools/list not JSON", spawn31.stdout, spawn31.stderr);
      process.exit(1);
    }
    const names31 = (listed31?.result?.tools || []).map((x) => x.name);
    if (!names31.includes("listItems")) {
      console.error("smoke 3.1 mcp tools/list missing listItems", names31);
      process.exit(1);
    }
    if (names31.includes("itemChangedWebhook")) {
      console.error("smoke 3.1 mcp tools/list leaked webhook", names31);
      process.exit(1);
    }
    const pySpawn31 = spawnSync("python3", [path.join(miniDir, MCP_SERVER_PY_FILE)], {
      input: rpc31, encoding: "utf8", timeout: 8000, env: { ...process.env },
    });
    if (pySpawn31.error || pySpawn31.status !== 0) {
      console.error("smoke 3.1 mcp py tools/list spawn failed", pySpawn31.status, pySpawn31.stderr);
      process.exit(1);
    }
    const pyLine31 = String(pySpawn31.stdout || "").trim().split(/\n/).filter(Boolean).pop();
    const pyListed31 = JSON.parse(pyLine31);
    const pyNames31 = (pyListed31?.result?.tools || []).map((x) => x.name);
    if (!pyNames31.includes("listItems") || JSON.stringify(pyNames31) !== JSON.stringify(names31)) {
      console.error("smoke 3.1 mcp py tools/list mismatch", pyNames31, names31);
      process.exit(1);
    }
    const mcpGo31 = path.join(miniDir, MCP_SERVER_GO_FILE);
    if (!fs.existsSync(mcpGo31)) {
      console.error("smoke 3.1 mcp_server.go missing");
      process.exit(1);
    }
    const goSrc31 = fs.readFileSync(mcpGo31, "utf8");
    if (!goSrc31.includes("tools/list") || !goSrc31.includes("listItems")) {
      console.error("smoke 3.1 mcp_server.go missing tools/list or listItems");
      process.exit(1);
    }
    if (goOk) {
      const goSpawn31 = spawnSync("go", ["run", mcpGo31], {
        input: rpc31, encoding: "utf8", timeout: 30000, env: { ...process.env },
      });
      if (goSpawn31.error || goSpawn31.status !== 0) {
        console.error("smoke 3.1 mcp go tools/list spawn failed", goSpawn31.status, goSpawn31.stderr);
        process.exit(1);
      }
      const goLine31 = String(goSpawn31.stdout || "").trim().split(/\n/).filter(Boolean).pop();
      const goListed31 = JSON.parse(goLine31);
      const goNames31 = (goListed31?.result?.tools || []).map((x) => x.name);
      if (!goNames31.includes("listItems") || JSON.stringify(goNames31) !== JSON.stringify(names31)) {
        console.error("smoke 3.1 mcp go tools/list mismatch", goNames31, names31);
        process.exit(1);
      }
    }

    // generate --url file:// (no public internet); tools/list still has an operationId
    const cliPath = fileURLToPath(import.meta.url);
    const miniUrl = pathToFileURL(mini31Path).href;
    const urlOut = path.join(tmp, "from-url");
    const urlDry = spawnSync(process.execPath, [cliPath, "generate", "--url", miniUrl, "--out", urlOut, "--lang", "ts,python", "--dry-run"], {
      encoding: "utf8", timeout: 8000, env: { ...process.env },
    });
    if (urlDry.error || urlDry.status !== 0) {
      console.error("smoke --url file:// dry-run failed", urlDry.status, urlDry.stderr, urlDry.error);
      process.exit(1);
    }
    if (fs.existsSync(urlOut)) {
      console.error("smoke --url dry-run must not create out");
      process.exit(1);
    }
    let urlPlan;
    try {
      urlPlan = JSON.parse(String(urlDry.stdout || "").trim().split(/\n/).filter(Boolean).pop());
    } catch {
      console.error("smoke --url dry-run not JSON", urlDry.stdout);
      process.exit(1);
    }
    if (!urlPlan.files || !urlPlan.files.includes("client.ts") || urlPlan.operations < 1) {
      console.error("smoke --url dry-run plan", urlPlan);
      process.exit(1);
    }
    const urlGen = spawnSync(process.execPath, [cliPath, "generate", "--url", miniUrl, "--out", urlOut, "--lang", "ts,python"], {
      encoding: "utf8", timeout: 8000, env: { ...process.env },
    });
    if (urlGen.error || urlGen.status !== 0) {
      console.error("smoke --url file:// generate failed", urlGen.status, urlGen.stderr, urlGen.error);
      process.exit(1);
    }
    const urlMcp = path.join(urlOut, MCP_SERVER_FILE);
    const urlSpawn = spawnSync(process.execPath, [urlMcp], {
      input: rpc31, encoding: "utf8", timeout: 8000, env: { ...process.env },
    });
    if (urlSpawn.error || urlSpawn.status !== 0) {
      console.error("smoke --url mcp tools/list spawn failed", urlSpawn.status, urlSpawn.stderr, urlSpawn.error);
      process.exit(1);
    }
    const urlLine = String(urlSpawn.stdout || "").trim().split(/\n/).filter(Boolean).pop();
    let urlListed;
    try {
      urlListed = JSON.parse(urlLine);
    } catch {
      console.error("smoke --url mcp tools/list not JSON", urlSpawn.stdout, urlSpawn.stderr);
      process.exit(1);
    }
    const urlNames = (urlListed?.result?.tools || []).map((x) => x.name);
    if (!urlNames.includes("listItems")) {
      console.error("smoke --url tools/list missing listItems", urlNames);
      process.exit(1);
    }
    const xor = spawnSync(process.execPath, [cliPath, "generate", mini31Path, "--url", miniUrl, "--out", path.join(tmp, "xor")], {
      encoding: "utf8", timeout: 8000, env: { ...process.env },
    });
    if (xor.status === 0) {
      console.error("smoke generate path + --url should fail");
      process.exit(1);
    }
    const ftp = spawnSync(process.execPath, [cliPath, "generate", "--url", "ftp://127.0.0.1/openapi.json", "--out", path.join(tmp, "ftp")], {
      encoding: "utf8", timeout: 8000, env: { ...process.env },
    });
    if (ftp.status === 0) {
      console.error("smoke --url ftp:// should fail");
      process.exit(1);
    }
    const meta = spawnSync(process.execPath, [cliPath, "generate", "--url", "http://169.254.169.254/latest/meta-data/", "--out", path.join(tmp, "meta")], {
      encoding: "utf8", timeout: 3000, env: { ...process.env },
    });
    if (meta.status === 0) {
      console.error("smoke --url 169.254.169.254 should fail");
      process.exit(1);
    }
    const metaMsg = String(meta.stderr || "") + String(meta.stdout || "");
    if (!/blocked|refused|169\.254\.169\.254/i.test(metaMsg)) {
      console.error("smoke metadata block message", meta.status, meta.stderr, meta.stdout);
      process.exit(1);
    }

    await smokeUrlAuthHeaders(cliPath, mini31Path, tmp);
    await smokeUrlWatch(cliPath, mini31Path, tmp);
    smokeZip(cliPath, mini31Path, tmp);

  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
  console.log(`sdk-mcp-gen ${VERSION} smoke OK — ${ops.length} ops -> ${tools.length} MCP tools (yaml-ok, py-ok, go-ok, java-ok, rust-ok, csharp-ok, kotlin-ok, swift-ok, ruby-ok, php-ok, check-ok, checksums-ok, dry-run-ok, mcp-ok, mcp-py-ok, mcp-go-ok, mcp-json-ok, package-name-ok, openapi-3.1-ok, url-ok, url-header-ok, url-watch-ok, zip-ok, license-ok, gitignore-ok, page-ok)`);
} else if (cmd === "demo") {
  console.log(JSON.stringify({ operations: listOperations(demoSpec), mcpTools: toMcpTools(listOperations(demoSpec)) }, null, 2));
} else if (cmd === "check") {
  const { out, baseline, checkClients } = parseCheckArgs(process.argv.slice(3));
  if (!out || !baseline) {
    console.error("usage: sdk-mcp-gen check --out <dir> --baseline <dir> [--no-clients]");
    process.exit(2);
  }
  process.exit(runCheck(out, baseline, { checkClients }));
} else if (cmd === "verify-checksums") {
  const { out } = parseVerifyChecksumsArgs(process.argv.slice(3));
  if (!out) {
    console.error("usage: sdk-mcp-gen verify-checksums --out <dir>");
    process.exit(2);
  }
  process.exit(runVerifyChecksums(out));
} else if (cmd === "generate") {
  await runGenerate(process.argv.slice(3));
} else {
  printHelp();
}

function urlIsHttp(urlString) {
  try {
    const u = new URL(String(urlString || "").trim());
    return u.protocol === "http:" || u.protocol === "https:";
  } catch {
    return false;
  }
}

async function loadGenerateSpec(input, url, extraHeaders) {
  if (url) {
    const opts = extraHeaders && Object.keys(extraHeaders).length ? { headers: extraHeaders } : {};
    const fetched = await fetchOpenApiText(url, opts);
    if (fetched.notModified) {
      throw new Error("fetch OpenAPI failed: HTTP 304 (unexpected on first fetch)");
    }
    return { spec: loadOpenApiSpec(fetched.text, fetched.filename), fetched };
  }
  return { spec: readSpec(input), fetched: null };
}

async function runGenerate(argv) {
  const { input, url, out, langs, checkBaseline, watch, watchIntervalRaw, dryRun, zip, baseUrl, packageName, headerLines, mcp, license, gitignore } = parseGenerateArgs(argv);
  const urlTrim = url == null ? "" : String(url).trim();
  const cliHeaders = (headerLines || []).filter((h) => h != null && String(h).trim() !== "");
  if (urlTrim && input) {
    console.error("generate: use either an OpenAPI file path or --url, not both");
    process.exit(2);
  }
  if (!urlTrim && !input) {
    console.error("missing openapi input path (or --url)");
    process.exit(2);
  }
  if (cliHeaders.length && !urlTrim) {
    console.error("generate --header requires --url (http/https)");
    process.exit(2);
  }
  const intervalMs = resolveWatchIntervalMs(watchIntervalRaw, Boolean(urlTrim));
  const fetchLines = [];
  if (urlIsHttp(urlTrim)) {
    const envH = process.env.SDK_FETCH_HEADER;
    if (envH && String(envH).trim()) fetchLines.push(String(envH).trim());
    fetchLines.push(...cliHeaders.map(String));
  }
  let extraHeaders = {};
  let headerNames = [];
  try {
    const parsed = parseFetchHeaderLines(fetchLines);
    extraHeaders = parsed.headers;
    headerNames = parsed.names;
  } catch (err) {
    console.error(err && err.message ? redactSecretsInText(err.message) : err);
    process.exit(2);
  }
  let spec;
  let fetched = null;
  try {
    const loaded = await loadGenerateSpec(input, urlTrim || null, extraHeaders);
    spec = loaded.spec;
    fetched = loaded.fetched;
  } catch (err) {
    console.error(err && err.message ? redactSecretsInText(err.message) : err);
    process.exit(1);
  }
  if (dryRun) {
    // Plan only: no mkdir, no writes, no watch, no check-baseline (nothing on disk).
    // Never include header values (secrets). Names only when extra headers were sent.
    const plan = plannedGenerateSummary(spec, langs, packageName, { mcp, zip, license, gitignore });
    if (headerNames.length) plan.headerNames = headerNames;
    console.log(JSON.stringify(plan));
  } else {
    const absOut = path.resolve(out);
    const { ops, tools, files } = generateToDir(spec, absOut, langs, { baseUrl, packageName, mcp, zip, license, gitignore });
    const summary = JSON.stringify({ out: absOut, operations: ops.length, tools: tools.length, langs, files });
    if (watch) watchLog(summary);
    else console.log(summary);
    maybeCheckBaseline(absOut, checkBaseline, { exitOnFail: !watch });
    if (watch) {
      if (urlTrim) {
        const initialState = specWatchStateFromFetch(fetched || {});
        startUrlWatch(urlTrim, extraHeaders, absOut, langs, checkBaseline, baseUrl, packageName, mcp, intervalMs, initialState, zip, license, gitignore);
      } else {
        startWatch(input, absOut, langs, checkBaseline, baseUrl, packageName, mcp, intervalMs, zip, license, gitignore);
      }
    }
  }
}
