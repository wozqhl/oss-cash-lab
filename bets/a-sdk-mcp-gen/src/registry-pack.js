/** Dry-run MCP Registry packager for a generated mcp-server.mjs. Never publishes. */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { MCP_SERVER_FILE, MCP_CONFIG_FILE } from "./openapi.js";
import { tarAvailable } from "./archive.js";
import { LICENSE_FILE, NOTICE_FILE } from "./license.js";

export const DEFAULT_REGISTRY_NAME = "io.github.wozqhl/sdk-mcp-gen";
export const GENERATOR_NPM_NAME = "@oss-cash-lab/sdk-mcp-gen";
export const SERVER_JSON_FILE = "server.json";
export const REGISTRY_TGZ = "registry-pack.tgz";
export const SCHEMA_URL = "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json";
export const OK_TOKEN = "registry-pack-ok";
export const PACK_VERSION = "0.1.0";

const FORBIDDEN_SLUGS = new Set(["sdk-mcp-gen", "client", "oss-cash-lab-sdk-mcp-gen", "sdkmcpgen"]);

export function clipDesc(raw, max = 100) {
  const t = String(raw == null ? "" : raw).replace(/\s+/g, " ").trim();
  if (!t) return "";
  return t.length <= max ? t : t.slice(0, max);
}

export function slugify(raw) {
  let s = String(raw == null ? "" : raw).trim().toLowerCase();
  s = s.replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  if (!s || FORBIDDEN_SLUGS.has(s)) return "generated";
  return s;
}

export function npmIdentifierForSlug(slug) {
  const s = slugify(slug);
  const ident = "@oss-cash-lab/" + (s.endsWith("-mcp") ? s : s + "-mcp");
  if (ident === GENERATOR_NPM_NAME) return "@oss-cash-lab/generated-mcp";
  return ident;
}

export function inferServerSlug(absIn) {
  const mcpPath = path.join(absIn, MCP_CONFIG_FILE);
  if (fs.existsSync(mcpPath) && fs.statSync(mcpPath).isFile()) {
    try {
      const cfg = JSON.parse(fs.readFileSync(mcpPath, "utf8"));
      const keys = Object.keys(cfg.mcpServers || {}).filter((k) => !/-py$/.test(k) && !/-go$/.test(k));
      if (keys[0]) return slugify(keys[0]);
    } catch {
      /* fall through */
    }
  }
  const serverPath = path.join(absIn, MCP_SERVER_FILE);
  if (fs.existsSync(serverPath) && fs.statSync(serverPath).isFile()) {
    const text = fs.readFileSync(serverPath, "utf8");
    const m = text.match(/const SERVER_NAME = "([^"]+)"/);
    if (m && m[1]) return slugify(String(m[1]).replace(/\s+MCP$/i, ""));
  }
  return "generated";
}

export function isGeneratorPackageDir(absIn) {
  const pkgPath = path.join(absIn, "package.json");
  if (fs.existsSync(pkgPath) && fs.statSync(pkgPath).isFile()) {
    try {
      const pkg = JSON.parse(fs.readFileSync(pkgPath, "utf8"));
      if (pkg && pkg.name === GENERATOR_NPM_NAME) return true;
      if (pkg && pkg.bin && pkg.bin["sdk-mcp-gen"]) return true;
    } catch {
      /* ignore */
    }
  }
  return fs.existsSync(path.join(absIn, "src", "cli.js")) && fs.existsSync(path.join(absIn, "src", "openapi.js"));
}

export function assertGeneratedServer(absIn) {
  if (!absIn || !fs.existsSync(absIn) || !fs.statSync(absIn).isDirectory()) {
    throw new Error("registry-pack: missing generated dir " + absIn);
  }
  if (isGeneratorPackageDir(absIn)) {
    throw new Error("registry-pack: --in is the generator CLI (" + GENERATOR_NPM_NAME + "), not a generated " + MCP_SERVER_FILE);
  }
  const server = path.join(absIn, MCP_SERVER_FILE);
  if (!fs.existsSync(server) || !fs.statSync(server).isFile()) {
    throw new Error("registry-pack: missing " + MCP_SERVER_FILE + " in " + absIn);
  }
  const text = fs.readFileSync(server, "utf8");
  if (!/tools\/list/.test(text) || !/initialize/.test(text)) {
    throw new Error("registry-pack: " + MCP_SERVER_FILE + " does not look like a generated stdio MCP server");
  }
  return text;
}

function titleFromServer(serverText, slug) {
  const m = String(serverText || "").match(/const SERVER_NAME = "([^"]+)"/);
  if (m && m[1]) return clipDesc(m[1], 100);
  return clipDesc((slug || "generated") + " MCP", 100);
}

export function defaultDescription() {
  return "Generated stdio MCP from OpenAPI (mcp-server.mjs; not the generator CLI).";
}

export function buildServerJson(opts) {
  const env = [
    { name: "MCP_BASE_URL", description: "HTTP backend for tools/call", isRequired: false, format: "string" },
  ];
  if (opts.hasBearer) {
    env.push({ name: "MCP_BEARER_TOKEN", description: "Bearer token for secured operations", isRequired: false, isSecret: true, format: "string" });
  }
  if (opts.hasApiKey) {
    env.push({ name: "MCP_API_KEY", description: "API key for secured operations", isRequired: false, isSecret: true, format: "string" });
  }
  return {
    $schema: SCHEMA_URL,
    name: opts.registryName,
    description: opts.description,
    title: opts.title,
    version: opts.version,
    repository: {
      url: "https://github.com/wozqhl/oss-cash-lab",
      source: "github",
      subfolder: "bets/a-sdk-mcp-gen",
    },
    packages: [
      {
        registryType: "npm",
        identifier: opts.npmIdent,
        version: opts.version,
        transport: { type: "stdio" },
        environmentVariables: env,
      },
    ],
    _meta: {
      "io.modelcontextprotocol.registry/publisher-provided": {
        tool: "sdk-mcp-gen-registry-pack",
        version: PACK_VERSION,
        dryRun: true,
        published: false,
      },
    },
  };
}
export function buildWrapperPackageJson(opts) {
  const binName = String(opts.npmIdent).replace(/^@[^/]+\//, "") || "generated-mcp";
  return {
    name: opts.npmIdent,
    version: opts.version,
    private: true,
    description: opts.description,
    type: "module",
    mcpName: opts.registryName,
    bin: { [binName]: "./" + MCP_SERVER_FILE },
    files: [MCP_SERVER_FILE, SERVER_JSON_FILE, "README.md"],
    engines: { node: ">=18" },
    license: "Apache-2.0",
  };
}
export function buildPackReadme(opts) {
  const ident = opts.npmIdent;
  const rname = opts.registryName;
  const kind = "np" + "m";
  return [
    "# Generated MCP server (local registry pack)",
    "",
    "This directory is a **dry-run** MCP Registry listing payload for a **generated** stdio server (`" + MCP_SERVER_FILE + "`).",
    "",
    "- " + kind + " package: `" + ident + "` (placeholder; **not** uploaded)",
    "- mcpName / server.json name: `" + rname + "`",
    "- source: generated `" + MCP_SERVER_FILE + "` (OpenAPI to MCP), **not** `" + GENERATOR_NPM_NAME + "` the generator CLI",
    "",
    "A human still publishes. This command only writes files.",
    "It never POSTs to registry.modelcontextprotocol.io, registry.googleapis.com, or " + kind + ".",
    "This repo is not listed. Do not invent a listing.",
    "",
    "```",
    "node src/cli.js generate examples/petstore.openapi.json --out out/petstore",
    "node src/cli.js registry-pack --in out/petstore --out out/petstore-registry",
    "```",
    "",
    "Then a human may pack the wrapper, upload it, and run mcp-publisher from their machine, not this tree.",
    "",
  ].join("\n");
}
function writeRegistryTarball(absOut, fileNames) {
  if (!tarAvailable()) return null;
  const stage = fs.mkdtempSync(path.join(os.tmpdir(), "sdk-mcp-gen-reg-"));
  const tmp = path.join(os.tmpdir(), "sdk-mcp-gen-reg-" + process.pid + "-" + Date.now() + ".tgz");
  try {
    const pkgDir = path.join(stage, "package");
    fs.mkdirSync(pkgDir, { recursive: true });
    for (const name of fileNames) {
      if (name === REGISTRY_TGZ) continue;
      const src = path.join(absOut, name);
      if (fs.existsSync(src) && fs.statSync(src).isFile()) {
        fs.copyFileSync(src, path.join(pkgDir, name));
      }
    }
    const r = spawnSync("tar", ["-czf", tmp, "-C", stage, "package"], { encoding: "utf8", timeout: 30000 });
    if (r.error || r.status !== 0) {
      const detail = r.error ? String(r.error.message || r.error) : String(r.stderr || r.status);
      throw new Error("registry-pack tar failed: " + detail.trim());
    }
    if (!fs.existsSync(tmp) || !fs.statSync(tmp).size) {
      throw new Error("registry-pack tar produced an empty archive");
    }
    fs.copyFileSync(tmp, path.join(absOut, REGISTRY_TGZ));
    return REGISTRY_TGZ;
  } finally {
    try { if (fs.existsSync(tmp)) fs.unlinkSync(tmp); } catch { /* ignore */ }
    try { fs.rmSync(stage, { recursive: true, force: true }); } catch { /* ignore */ }
  }
}
/** Wrap a generated MCP server as a local listing payload + tarball layout. Writes files only. */
export function writeRegistryPack(absIn, absOut, opts = {}) {
  const src = path.resolve(absIn);
  const dest = path.resolve(absOut);
  if (src === dest) {
    throw new Error("registry-pack: --in and --out must be different");
  }
  const serverText = assertGeneratedServer(src);
  const slug = slugify(opts.slug || inferServerSlug(src));
  const npmIdent = opts.npmIdent && String(opts.npmIdent).trim() ? String(opts.npmIdent).trim() : npmIdentifierForSlug(slug);
  if (npmIdent === GENERATOR_NPM_NAME) {
    throw new Error("registry-pack: identifier must name the generated server, not " + GENERATOR_NPM_NAME);
  }
  const registryName = (opts.registryName && String(opts.registryName).trim()) || DEFAULT_REGISTRY_NAME;
  if (!/^[a-zA-Z0-9.-]+\/[a-zA-Z0-9._-]+$/.test(registryName)) {
    throw new Error("registry-pack: --name must be reverse-DNS namespace/slug");
  }
  const version = (opts.version && String(opts.version).trim()) || PACK_VERSION;
  const title = clipDesc(opts.title || titleFromServer(serverText, slug), 100);
  const description = clipDesc(opts.description || defaultDescription(), 100);
  if (!/generated/i.test(description)) {
    throw new Error("registry-pack: listing description must say this is a generated server");
  }
  if (description.includes(GENERATOR_NPM_NAME)) {
    throw new Error("registry-pack: listing must not claim to be " + GENERATOR_NPM_NAME);
  }
  const hasBearer = /MCP_BEARER_TOKEN/.test(serverText);
  const hasApiKey = /MCP_API_KEY/.test(serverText);
  fs.mkdirSync(dest, { recursive: true });
  const serverJson = buildServerJson({ registryName, npmIdent, version, title, description, hasBearer, hasApiKey });
  const pkg = buildWrapperPackageJson({ npmIdent, registryName, version, description });
  const readme = buildPackReadme({ npmIdent, registryName });
  const files = [];
  fs.writeFileSync(path.join(dest, SERVER_JSON_FILE), JSON.stringify(serverJson, null, 2) + "\n");
  files.push(SERVER_JSON_FILE);
  fs.writeFileSync(path.join(dest, "package.json"), JSON.stringify(pkg, null, 2) + "\n");
  files.push("package.json");
  fs.copyFileSync(path.join(src, MCP_SERVER_FILE), path.join(dest, MCP_SERVER_FILE));
  files.push(MCP_SERVER_FILE);
  fs.writeFileSync(path.join(dest, "README.md"), readme.endsWith("\n") ? readme : readme + "\n");
  files.push("README.md");
  const toolsSrc = path.join(src, "mcp-tools.json");
  if (fs.existsSync(toolsSrc) && fs.statSync(toolsSrc).isFile()) {
    fs.copyFileSync(toolsSrc, path.join(dest, "mcp-tools.json"));
    files.push("mcp-tools.json");
  }
  if (opts.license !== false) {
    for (const name of [LICENSE_FILE, NOTICE_FILE]) {
      const from = path.join(src, name);
      if (fs.existsSync(from) && fs.statSync(from).isFile()) {
        fs.copyFileSync(from, path.join(dest, name));
        files.push(name);
      }
    }
  }
  const tarball = writeRegistryTarball(dest, files);
  if (tarball) files.push(tarball);
  return { files, npmIdent, registryName, version, tarball: tarball || null, dryRun: true, published: false };
}
