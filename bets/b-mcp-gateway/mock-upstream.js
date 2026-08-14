#!/usr/bin/env node
/**
 * Tiny mock MCP upstream for B gateway demos.
 * Modes:
 *   node mock-upstream.js --port 8788 --host 127.0.0.1   # REST /health /tools/list /tools/call
 *   node mock-upstream.js --stdio              # newline JSON-RPC-ish over stdin/stdout
 *   --delay-ms N   sleep N ms on tools/call only (list/health stay fast; timeout proves)
 */
import http from "node:http";
import readline from "node:readline";

const VERSION = "0.1.0";

const TOOLS = [
  {
    name: "upstreamPing",
    description: "Prove call was proxied to mock upstream",
    inputSchema: {
      type: "object",
      properties: {
        note: { type: "string" },
      },
    },
  },
  {
    name: "upstreamEcho",
    description: "Echo args with upstream marker",
    inputSchema: {
      type: "object",
      properties: {
        message: { type: "string" },
      },
    },
  },
];

function callTool(name, args = {}) {
  if (name === "upstreamPing") {
    return {
      ok: true,
      source: "mock-upstream",
      upstream: true,
      note: args.note ?? null,
      version: VERSION,
    };
  }
  if (name === "upstreamEcho") {
    return {
      ok: true,
      source: "mock-upstream",
      echo: args,
    };
  }
  return { ok: false, error: `unknown_tool:${name}` };
}

function sendJson(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(payload),
  });
  res.end(payload);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => {
      const raw = Buffer.concat(chunks).toString("utf8");
      if (!raw) return resolve({});
      try {
        resolve(JSON.parse(raw));
      } catch (err) {
        reject(err);
      }
    });
    req.on("error", reject);
  });
}

function handleRpc(msg) {
  const id = msg.id ?? null;
  const method = msg.method || msg.op;
  if (method === "tools/list" || method === "list") {
    return { jsonrpc: "2.0", id, result: { tools: TOOLS } };
  }
  if (method === "tools/call" || method === "call") {
    const params = msg.params || msg;
    const name = params.name || params.tool;
    const args = params.arguments ?? params.args ?? {};
    if (!name) {
      return { jsonrpc: "2.0", id, error: { code: -32602, message: "missing_tool_name" } };
    }
    const result = callTool(name, args);
    const statusOk = result.ok !== false;
    return {
      jsonrpc: "2.0",
      id,
      result: { ok: statusOk, tool: name, result },
    };
  }
  return { jsonrpc: "2.0", id, error: { code: -32601, message: `unknown_method:${method}` } };
}

function sleep(ms) {
  const n = Number(ms);
  if (!Number.isFinite(n) || n <= 0) return Promise.resolve();
  return new Promise((resolve) => setTimeout(resolve, Math.floor(n)));
}

function parseArgs(argv) {
  let port = 8790;
  let host = "127.0.0.1";
  let stdio = false;
  let delayMs = 0;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--stdio") stdio = true;
    else if (a === "--port" || a === "-p") port = Number(argv[++i]);
    else if (a === "--host") host = argv[++i];
    else if (a === "--delay-ms") delayMs = Number(argv[++i]);
  }
  return { port, host, stdio, delayMs };
}

const { port, host, stdio, delayMs } = parseArgs(process.argv.slice(2));

function isCallMethod(method) {
  return method === "tools/call" || method === "call";
}

if (stdio) {
  const rl = readline.createInterface({ input: process.stdin, terminal: false });
  rl.on("line", async (line) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    let msg;
    try {
      msg = JSON.parse(trimmed);
    } catch (err) {
      process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id: null, error: { message: String(err) } }) + "\n");
      return;
    }
    const method = msg.method || msg.op;
    if (isCallMethod(method) && delayMs > 0) await sleep(delayMs);
    process.stdout.write(JSON.stringify(handleRpc(msg)) + "\n");
  });
  process.stderr.write("mock-upstream stdio ready delayMs=" + delayMs + "\n");
} else {
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);
    const method = (req.method || "GET").toUpperCase();
    try {
      if (method === "GET" && url.pathname === "/health") {
        return sendJson(res, 200, { ok: true, service: "mock-upstream", version: VERSION });
      }
      if (method === "POST" && (url.pathname === "/tools/list" || url.pathname === "/mcp/tools/list")) {
        return sendJson(res, 200, { tools: TOOLS });
      }
      if (method === "POST" && (url.pathname === "/tools/call" || url.pathname === "/mcp/tools/call")) {
        const body = await readBody(req);
        const name = body.name || body.tool || body.params?.name;
        const args = body.arguments ?? body.args ?? body.params?.arguments ?? {};
        if (!name) return sendJson(res, 400, { error: "missing_tool_name" });
        if (delayMs > 0) await sleep(delayMs);
        const result = callTool(name, args);
        if (result.ok === false && String(result.error || "").startsWith("unknown_tool:")) {
          return sendJson(res, 404, { error: "unknown_tool", tool: name, result });
        }
        return sendJson(res, 200, { ok: true, tool: name, result });
      }
      return sendJson(res, 404, { error: "not_found", path: url.pathname });
    } catch (err) {
      return sendJson(res, 500, { error: "internal_error", message: String(err?.message || err) });
    }
  });
  server.listen(port, host, () => {
    console.log("mock-upstream listening on http://" + host + ":" + port + (delayMs > 0 ? " delayMs=" + delayMs : ""));
  });
}
