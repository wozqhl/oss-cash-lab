#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const PORT = Number(process.env.STDIO_PORT || 8788);
const ACME_KEY = "ten_acme_dev";
const POLICY_SRC = path.join(ROOT, "config/policy.json");
const POLICY = path.join(ROOT, "data/policy.stdio.json");
const AUDIT = path.join(ROOT, "data/audit.stdio.jsonl");
const LOG = path.join(ROOT, "data/server.stdio.log");

fs.mkdirSync(path.join(ROOT, "data"), { recursive: true });
for (const f of [AUDIT, LOG]) { try { fs.unlinkSync(f); } catch {} }

const policy = JSON.parse(fs.readFileSync(POLICY_SRC, "utf8"));
policy.upstream = {
  type: "stdio",
  command: "node",
  args: [path.join(ROOT, "mock-upstream.js"), "--stdio"],
  timeoutMs: 30000, // generous: do not collide with isolated timeout prove
  breaker: { enabled: false }, // do not collide with isolated breaker prove
};
const extra = ["upstreamPing", "upstreamEcho"];
policy.allow = Array.from(new Set([...(policy.allow || []), ...extra]));
for (const t of policy.tenants || []) {
  if (t.id === "acme") {
    t.allow = Array.from(new Set([...(t.allow || []), ...extra]));
  }
}
policy.tools = [
  ...(policy.tools || []),
  {
    name: "upstreamPing",
    description: "Proxied to mock upstream via stdio",
    inputSchema: { type: "object", properties: { note: { type: "string" } } },
  },
];
fs.writeFileSync(POLICY, JSON.stringify(policy, null, 2) + "\n");

const logFd = fs.openSync(LOG, "w");
const child = spawn(
  process.execPath,
  ["src/cli.js", "serve", "--port", String(PORT), "--config", POLICY, "--audit", AUDIT],
  { cwd: ROOT, stdio: ["ignore", logFd, logFd], env: process.env }
);

let cleaned = false;
async function cleanup() {
  if (cleaned) return;
  cleaned = true;
  if (!child.killed && child.exitCode == null) {
    child.kill("SIGTERM");
    await new Promise((resolve) => {
      const t = setTimeout(() => {
        try { child.kill("SIGKILL"); } catch {}
        resolve();
      }, 3000);
      child.once("exit", () => { clearTimeout(t); resolve(); });
    });
  }
  try { fs.closeSync(logFd); } catch {}
}
process.on("exit", () => {
  if (!cleaned && child.exitCode == null) {
    try { child.kill("SIGKILL"); } catch {}
  }
});

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitHealth() {
  for (let i = 0; i < 50; i++) {
    try {
      const res = await fetch("http://127.0.0.1:" + PORT + "/health");
      if (res.ok) return await res.json();
    } catch {}
    await sleep(100);
  }
  throw new Error("gateway_health_timeout");
}
function mustInclude(hay, needle, label) {
  if (!String(hay).includes(needle)) throw new Error(label + " missing " + needle);
}

try {
  await new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("spawn", resolve);
  });
  const health = await waitHealth();
  console.log("stdio_health=" + JSON.stringify(health));
  if (!health.ok) throw new Error("health_not_ok");
  if (!health.upstream || health.upstream.type !== "stdio") throw new Error("upstream_type_not_stdio");
  if (!health.upstream.connected) throw new Error("upstream_not_connected: " + health.upstream.error);
  if (!(health.upstream.tools || []).includes("upstreamPing")) throw new Error("upstreamPing_missing_in_health");
  const listRes = await fetch("http://127.0.0.1:" + PORT + "/tools/list", {
    method: "POST",
    headers: { "content-type": "application/json", Authorization: "Bearer " + ACME_KEY },
    body: "{}",
  });
  const list = await listRes.json();
  console.log("stdio_list=" + JSON.stringify(list));
  mustInclude(JSON.stringify(list), "\"name\":\"upstreamPing\"", "list");
  if (list.upstreamConnected !== true) throw new Error("list_upstreamConnected_false");
  const callRes = await fetch("http://127.0.0.1:" + PORT + "/tools/call", {
    method: "POST",
    headers: { "content-type": "application/json", Authorization: "Bearer " + ACME_KEY },
    body: JSON.stringify({ name: "upstreamPing", arguments: { note: "via-stdio" } }),
  });
  const proxy = await callRes.json();
  console.log("stdio_proxy=" + JSON.stringify(proxy));
  if (!callRes.ok || !proxy.ok) throw new Error("proxy_failed: " + JSON.stringify(proxy));
  if (proxy.via !== "upstream") throw new Error("via_not_upstream");
  const blob = JSON.stringify(proxy);
  mustInclude(blob, "mock-upstream", "proxy.source");
  mustInclude(blob, "via-stdio", "proxy.note");
  const audit = fs.readFileSync(AUDIT, "utf8");
  mustInclude(audit, "\"tool\":\"upstreamPing\"", "audit.tool");
  mustInclude(audit, "\"via\":\"upstream\"", "audit.via");
  console.log("b-mcp-gateway stdio upstream prove OK");
  await cleanup();
  process.exit(0);
} catch (err) {
  console.error("stdio prove failed:", err?.message || err);
  await cleanup();
  process.exit(1);
}
