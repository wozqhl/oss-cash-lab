/** Upstream MCP clients (HTTP / stdio) + built-in local tools. */
import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import readline from "node:readline";

const PETS = [
  { id: "1", name: "Rex", tag: "dog" },
  { id: "2", name: "Mimi", tag: "cat" },
];

export const BUILTIN_TOOL_NAMES = new Set(["echo", "digest", "listPets", "getPet"]);

/** Default abort window for HTTP fetch and stdio RPC (ms). */
export const DEFAULT_UPSTREAM_TIMEOUT_MS = 5000;

export class UpstreamTimeoutError extends Error {
  constructor(message = "upstream_timeout") {
    super(message);
    this.name = "UpstreamTimeoutError";
    this.code = "upstream_timeout";
  }
}

/** Resolve `upstream.timeoutMs` (positive int) or default 5000. */
export function resolveUpstreamTimeoutMs(config = {}) {
  const v = config?.timeoutMs;
  if (typeof v === "number" && Number.isFinite(v) && v > 0) return Math.floor(v);
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    if (Number.isFinite(n) && n > 0) return Math.floor(n);
  }
  return DEFAULT_UPSTREAM_TIMEOUT_MS;
}

export function isUpstreamTimeoutError(err) {
  if (!err) return false;
  if (err instanceof UpstreamTimeoutError) return true;
  if (err.code === "upstream_timeout" || err.message === "upstream_timeout") return true;
  if (err.name === "AbortError" || err.name === "TimeoutError") return true;
  if (err.code === "ABORT_ERR") return true;
  if (err.cause && isUpstreamTimeoutError(err.cause)) return true;
  return false;
}


export function isUpstreamConnectError(err) {
  if (!err) return false;
  if (isUpstreamTimeoutError(err)) return false;
  const code = err.code || err.errno;
  const CONNECT_CODES = new Set([
    "ECONNREFUSED",
    "ENOTFOUND",
    "ECONNRESET",
    "EPIPE",
    "ENETUNREACH",
    "EHOSTUNREACH",
    "EAI_AGAIN",
    "UND_ERR_CONNECT_TIMEOUT",
    "UND_ERR_SOCKET",
    "UND_ERR_CONNECT",
  ]);
  if (CONNECT_CODES.has(code)) return true;
  const msg = String(err.message || err);
  if (/upstream_stdio_(not_running|exited)/.test(msg)) return true;
  if (/fetch failed|ECONNREFUSED|ENOTFOUND|ECONNRESET/i.test(msg)) return true;
  if (err.cause && isUpstreamConnectError(err.cause)) return true;
  return false;
}

/** HTTP 5xx from upstream callTool result (not thrown). */
export function isUpstream5xxResult(result) {
  if (!result || typeof result !== "object") return false;
  const st = result.upstreamStatus;
  if (typeof st === "number" && st >= 500 && st <= 599) return true;
  const err = String(result.error || "");
  const m = err.match(/upstream_http_call_failed:(\d+)/);
  if (m) {
    const n = Number(m[1]);
    if (n >= 500 && n <= 599) return true;
  }
  return false;
}

/** Timeout, connect, or 5xx — counts as a circuit-breaker failure. */
export function isUpstreamFailure(errOrResult) {
  if (!errOrResult) return false;
  if (isUpstreamTimeoutError(errOrResult)) return true;
  if (isUpstreamConnectError(errOrResult)) return true;
  if (isUpstream5xxResult(errOrResult)) return true;
  return false;
}

export async function callBuiltin(name, args = {}) {
  switch (name) {
    case "echo":
      return { ok: true, echo: args };
    case "digest": {
      const text = String(args.text ?? "");
      const hash = createHash("sha256").update(text).digest("hex").slice(0, 12);
      return {
        ok: true,
        length: text.length,
        preview: text.slice(0, 80),
        digest: hash,
      };
    }
    case "listPets":
      return { ok: true, pets: PETS };
    case "getPet": {
      const pet = PETS.find((p) => p.id === String(args.id ?? ""));
      if (!pet) return { ok: false, error: "not_found" };
      return { ok: true, pet };
    }
    default:
      return { ok: false, error: `unknown_upstream_tool:${name}` };
  }
}

/** Back-compat alias used by older call sites. */
export async function callUpstream(name, args = {}) {
  return callBuiltin(name, args);
}

function joinUrl(baseUrl, path) {
  const base = String(baseUrl || "").replace(/\/+$/, "");
  const p = path.startsWith("/") ? path : `/${path}`;
  return base + p;
}

async function fetchJson(url, { method = "POST", body, timeoutMs } = {}) {
  const ms = resolveUpstreamTimeoutMs({ timeoutMs });
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), ms);
  try {
    const res = await fetch(url, {
      method,
      headers: { "content-type": "application/json" },
      body,
      signal: ctrl.signal,
    });
    const parsed = await res.json().catch(() => ({}));
    return { res, body: parsed };
  } catch (err) {
    if (isUpstreamTimeoutError(err)) throw new UpstreamTimeoutError();
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export function createHttpUpstream(config = {}) {
  const baseUrl = config.baseUrl || config.url;
  if (!baseUrl) throw new Error("upstream.http.baseUrl_required");
  const timeoutMs = resolveUpstreamTimeoutMs(config);
  let cachedTools = null;

  return {
    type: "http",
    timeoutMs,
    async listTools() {
      const { res, body } = await fetchJson(joinUrl(baseUrl, "/tools/list"), {
        method: "POST",
        body: "{}",
        timeoutMs,
      });
      if (!res.ok) {
        throw new Error(`upstream_http_list_failed:${res.status}`);
      }
      const tools = Array.isArray(body.tools) ? body.tools : [];
      cachedTools = tools;
      return tools;
    },
    async callTool(name, args = {}) {
      const { res, body } = await fetchJson(joinUrl(baseUrl, "/tools/call"), {
        method: "POST",
        body: JSON.stringify({ name, arguments: args }),
        timeoutMs,
      });
      if (!res.ok) {
        return {
          ok: false,
          error: body.error || `upstream_http_call_failed:${res.status}`,
          upstreamStatus: res.status,
          result: body.result ?? body,
        };
      }
      return body.result ?? body;
    },
    getCachedTools() {
      return cachedTools;
    },
    async close() {
      cachedTools = null;
    },
  };
}

export function createStdioUpstream(config = {}) {
  const command = config.command;
  if (!command) throw new Error("upstream.stdio.command_required");
  const args = Array.isArray(config.args) ? config.args : [];
  const timeoutMs = resolveUpstreamTimeoutMs(config);
  const child = spawn(command, args, {
    stdio: ["pipe", "pipe", "pipe"],
    env: process.env,
  });
  const rl = readline.createInterface({ input: child.stdout, terminal: false });
  let nextId = 1;
  const pending = new Map();
  let cachedTools = null;

  rl.on("line", (line) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    let msg;
    try {
      msg = JSON.parse(trimmed);
    } catch {
      return;
    }
    const id = msg.id;
    const waiter = pending.get(id);
    if (!waiter) return;
    pending.delete(id);
    if (msg.error) waiter.reject(new Error(msg.error.message || JSON.stringify(msg.error)));
    else waiter.resolve(msg.result);
  });

  child.stderr.on("data", () => {
    /* ignore banner / logs */
  });

  child.on("exit", (code) => {
    for (const [, waiter] of pending) {
      waiter.reject(new Error(`upstream_stdio_exited:${code}`));
    }
    pending.clear();
  });

  function request(method, params = {}) {
    const id = nextId++;
    const payload = JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n";
    return new Promise((resolve, reject) => {
      if (child.killed || child.exitCode != null) {
        reject(new Error("upstream_stdio_not_running"));
        return;
      }
      let settled = false;
      const timer = setTimeout(() => {
        if (settled) return;
        settled = true;
        pending.delete(id);
        reject(new UpstreamTimeoutError());
      }, timeoutMs);
      const finish = (fn, value) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        fn(value);
      };
      pending.set(id, {
        resolve: (v) => finish(resolve, v),
        reject: (e) => finish(reject, e),
      });
      child.stdin.write(payload, (err) => {
        if (err) {
          pending.delete(id);
          finish(reject, err);
        }
      });
    });
  }

  return {
    type: "stdio",
    timeoutMs,
    async listTools() {
      const result = await request("tools/list", {});
      const tools = Array.isArray(result?.tools) ? result.tools : [];
      cachedTools = tools;
      return tools;
    },
    async callTool(name, args = {}) {
      const result = await request("tools/call", { name, arguments: args });
      return result?.result ?? result;
    },
    getCachedTools() {
      return cachedTools;
    },
    async close() {
      try {
        child.stdin.end();
      } catch {
        /* ignore */
      }
      child.kill("SIGTERM");
      cachedTools = null;
    },
  };
}

export function createUpstreamFromConfig(upstreamConfig) {
  if (!upstreamConfig || typeof upstreamConfig !== "object") return null;
  const type = upstreamConfig.type || (upstreamConfig.baseUrl ? "http" : null);
  if (!type) return null;
  if (type === "http") return createHttpUpstream(upstreamConfig);
  if (type === "stdio") return createStdioUpstream(upstreamConfig);
  throw new Error(`unsupported_upstream_type:${type}`);
}

/**
 * Decide whether a tool call should go to configured upstream.
 * Built-ins stay local unless forceUpstream / tool marked upstream-only.
 */
export function shouldProxyToUpstream(name, upstreamToolNames) {
  if (upstreamToolNames && upstreamToolNames.has(name)) return true;
  if (BUILTIN_TOOL_NAMES.has(name)) return false;
  return Boolean(upstreamToolNames && upstreamToolNames.size);
}
