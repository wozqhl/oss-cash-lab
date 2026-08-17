#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import { fileURLToPath } from "node:url";
import {
  evaluatePolicy,
  RateLimiter,
  auditEvent,
  findTenantByApiKey,
  rotateTenantApiKey,
  tokenRotatedAuditEvent,
  matchAdminRotatePath,
  matchAdminGetTenantPath,
  summarizeTenantForAdmin,
  assertAdminTenantSafe,
  collectForbiddenAdminTenantKeys,
  resolveRotateGraceSec,
  DEFAULT_TOKEN_ROTATE_GRACE_SEC,
} from "./policy.js";
import { ipAllowed, matchAllowlistEntry } from "./ip-allowlist.js";
import {
  normalizeCors,
  originAllowed,
  acaoValue,
  handlePreflight,
  corsResponseHeaders,
  DEFAULT_CORS_HEADERS,
  DEFAULT_CORS_EXPOSE_HEADERS,
  DEFAULT_CORS_METHODS,
} from "./cors.js";
import {
  MCP_PROTOCOL_VERSION,
  MCP_PROTOCOL_VERSION_HEADER,
  MCP_SESSION_ID_HEADER,
  isMcpStreamablePath,
  isMcpJsonRpcPostPath,
  resolveProtocolVersion,
  resolveSessionId,
  mcpResponseHeaders,
  initializeResult,
  isUuid as isMcpUuid,
  createSessionStore,
  resolveSessionTtlSec,
  DEFAULT_SESSION_TTL_SEC,
  ENV_SESSION_TTL_SEC,
  DEFAULT_SESSION_MAX_IDS,
  ADMIN_SESSION_LIST_LIMIT,
  SESSION_EXPIRED,
  SESSION_NOT_FOUND,
  SESSION_ID_REQUIRED,
  MCP_ALLOW_METHODS,
  matchAdminSessionPath,
} from "./mcp-http.js";
import { resolveRequestId, sanitizeRequestId, isUuid } from "./request-id.js";
import { resolveLogJson, formatAccessLog, shouldSkipAccessLog } from "./access-log.js";
import {
  signWebhookBody,
  verifyWebhookSignature,
  webhookUnixSeconds,
  fanOutWebhooks,
  shouldRetryWebhook,
  TIMESTAMP_HEADER,
  SIGNATURE_HEADER,
  DEFAULT_RETRY_DELAY_MS,
} from "./webhooks.js";
import {
  createServer,
  startPolicyWatch,
  WATCH_POLL_MS,
  resolveDrainMs,
  DEFAULT_SHUTDOWN_DRAIN_MS,
  MAX_SHUTDOWN_DRAIN_MS,
} from "./server.js";
import {
  summarizeConfigForAdmin,
  assertAdminConfigSafe,
  collectForbiddenAdminConfigKeys,
  summarizeWebhooksForAdmin,
  assertAdminWebhooksSafe,
  collectForbiddenAdminWebhookKeys,
} from "./admin-config.js";
import { createMetrics } from "./metrics.js";
import {
  resolveUpstreamTimeoutMs,
  DEFAULT_UPSTREAM_TIMEOUT_MS,
} from "./upstream.js";
import {
  resolveBreakerConfig,
  createCircuitBreaker,
  DEFAULT_BREAKER_FAILURE_THRESHOLD,
  DEFAULT_BREAKER_OPEN_MS,
} from "./breaker.js";
import {
  readAuditEvents,
  eventsToCsv,
  eventsToAdminCsv,
  eventsToAdminMd,
  eventsToAdminHtml,
  ADMIN_CSV_COLUMNS,
  ADMIN_MD_HEADING,
  ADMIN_HTML_HEADING,
  eventsToJsonPack,
  normalizeExportFormat,
  resolveAuditPath,
  writeExportFile,
  resolveRedact,
  redactEvents,
  gzipBytes,
  wantsGzip,
  pushAuditEvent,
  resolveAuditMaxEvents,
  DEFAULT_AUDIT_MAX_EVENTS,
  ENV_AUDIT_MAX_EVENTS,
} from "./audit-export.js";

const VERSION = "0.1.0";
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");

const demoPolicy = {
  allow: ["listPets", "getPet"],
  deny: ["deletePet"],
  rateLimitPerMinute: 100,
};

function printHelp() {
  console.log(
    "mcp-gateway v" +
      VERSION +
      "\nUsage:\n  mcp-gateway --version\n  mcp-gateway smoke\n  mcp-gateway demo\n  mcp-gateway serve --port 8787 --host 127.0.0.1 --config config/policy.json [--watch] [--audit data/audit.jsonl] [--audit-max 10000] [--drain-ms 5000] [--rotate-grace-sec 60] [--session-ttl 3600] [--log-json]\n  mcp-gateway export-audit --config config/policy.json --out out/audit.json --format json|csv|md|html [--audit data/audit.jsonl] [--tenant acme] [--redact|--no-redact] [--since ISO] [--until ISO] [--gzip]\n"
  );
}

function parseExportArgs(argv) {
  let config = path.join(ROOT, "config/policy.json");
  let out = null;
  let format = "json";
  let audit = null;
  let tenant = null;
  let tool = null;
  let limit = null;
  let since = null;
  let until = null;
  let redact = null; // null = use config default
  let gzip = false;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--config" || a === "-c") config = argv[++i];
    else if (a === "--out" || a === "-o") out = argv[++i];
    else if (a === "--format" || a === "-f") format = argv[++i];
    else if (a === "--audit") audit = argv[++i];
    else if (a === "--tenant") tenant = argv[++i];
    else if (a === "--tool") tool = argv[++i];
    else if (a === "--limit") limit = argv[++i];
    else if (a === "--since") since = argv[++i];
    else if (a === "--until") until = argv[++i];
    else if (a === "--redact") redact = true;
    else if (a === "--no-redact") redact = false;
    else if (a === "--gzip") gzip = true;
    else if (a === "--no-gzip") gzip = false;
  }
  return { config, out, format, audit, tenant, tool, limit, since, until, redact, gzip };
}

function loadConfig(configPath) {
  const abs = path.isAbsolute(configPath)
    ? configPath
    : path.resolve(process.cwd(), configPath);
  const raw = fs.readFileSync(abs, "utf8");
  return { policy: JSON.parse(raw), abs };
}

function parseServeArgs(argv) {
  let port = 8787;
  let host = "127.0.0.1";
  let config = path.join(ROOT, "config/policy.json");
  let audit = path.join(process.cwd(), "data/audit.jsonl");
  let watch = false;
  let drainMs;
  let logJson;
  let rotateGraceSec;
  let auditMax;
  let sessionTtl;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--port" || a === "-p") port = Number(argv[++i]);
    else if (a === "--host") host = argv[++i];
    else if (a === "--config" || a === "-c") config = argv[++i];
    else if (a === "--audit") audit = argv[++i];
    else if (a === "--audit-max") auditMax = argv[++i];
    else if (a === "--watch") watch = true;
    else if (a === "--no-watch") watch = false;
    else if (a === "--drain-ms") drainMs = argv[++i];
    else if (a === "--rotate-grace-sec") rotateGraceSec = argv[++i];
    else if (a === "--session-ttl") sessionTtl = argv[++i];
    else if (a === "--log-json") logJson = true;
    else if (a === "--no-log-json") logJson = false;
  }
  return { port, host, config, audit, watch, drainMs, logJson, rotateGraceSec, auditMax, sessionTtl };
}

const cmd = process.argv[2] || "help";
if (cmd === "--version" || cmd === "-V") {
  console.log(VERSION);
} else if (cmd === "smoke") {
  const d1 = evaluatePolicy(demoPolicy, "listPets");
  const d2 = evaluatePolicy(demoPolicy, "deletePet");
  const d3 = evaluatePolicy(demoPolicy, "createPet");
  const rl = new RateLimiter(2);
  const ok1 = rl.check();
  const ok2 = rl.check();
  const ok3 = rl.check();
  if (!d1.allow || d2.allow || d3.allow || !ok1 || !ok2 || ok3) {
    console.error("smoke failed", { d1, d2, d3, ok1, ok2, ok3 });
    process.exit(1);
  }
  const ipOk =
    matchAllowlistEntry("10.1.2.3", "10.0.0.0/8") &&
    ipAllowed("127.0.0.1", ["127.0.0.1", "::1"]) &&
    !ipAllowed("9.9.9.9", ["1.2.3.4"]);
  if (!ipOk) {
    console.error("smoke failed ip allowlist");
    process.exit(1);
  }
  const corsPol = { cors: { origins: ["http://localhost:3000"] } };
  const cors = normalizeCors(corsPol);
  const star = normalizeCors({ cors: { origins: ["*"] } });
  const corsOk =
    cors &&
    originAllowed("http://localhost:3000", cors) &&
    !originAllowed("http://evil.example", cors) &&
    acaoValue("http://localhost:3000", cors) === "http://localhost:3000" &&
    acaoValue("http://evil.example", cors) === null &&
    handlePreflight({ headers: { origin: "http://localhost:3000" } }, corsPol)?.status === 204 &&
    handlePreflight({ headers: { origin: "http://evil.example" } }, corsPol)?.status === 403 &&
    handlePreflight({ headers: { origin: "http://localhost:3000" } }, {}) === null &&
    normalizeCors({ cors: { origins: [] } }) === null &&
    normalizeCors({}) === null &&
    star &&
    originAllowed("http://evil.example", star) &&
    acaoValue("http://evil.example", star) === "*" &&
    corsResponseHeaders({ headers: { origin: "http://localhost:3000" } }, corsPol)[
      "access-control-allow-origin"
    ] === "http://localhost:3000" &&
    !corsResponseHeaders({ headers: { origin: "http://evil.example" } }, corsPol)[
      "access-control-allow-origin"
    ] &&
    DEFAULT_CORS_EXPOSE_HEADERS.some((h) => /^retry-after$/i.test(h)) &&
    DEFAULT_CORS_EXPOSE_HEADERS.some((h) => /^x-request-id$/i.test(h)) &&
    /retry-after/i.test(
      corsResponseHeaders({ headers: { origin: "http://localhost:3000" } }, corsPol)[
        "access-control-expose-headers"
      ] || ""
    ) &&
    /x-request-id/i.test(
      corsResponseHeaders({ headers: { origin: "http://localhost:3000" } }, corsPol)[
        "access-control-expose-headers"
      ] || ""
    ) &&
    /retry-after/i.test(
      handlePreflight({ headers: { origin: "http://localhost:3000" } }, corsPol)?.headers?.[
        "access-control-expose-headers"
      ] || ""
    ) &&
    /x-request-id/i.test(
      handlePreflight({ headers: { origin: "http://localhost:3000" } }, corsPol)?.headers?.[
        "access-control-expose-headers"
      ] || ""
    ) &&
    !handlePreflight({ headers: { origin: "http://evil.example" } }, corsPol)?.headers?.[
      "access-control-expose-headers"
    ] &&
    !handlePreflight({ headers: { origin: "http://evil.example" } }, corsPol)?.headers?.[
      "access-control-allow-origin"
    ] &&
    DEFAULT_CORS_HEADERS.some((h) => /^mcp-protocol-version$/i.test(h)) &&
    DEFAULT_CORS_HEADERS.some((h) => /^mcp-session-id$/i.test(h)) &&
    DEFAULT_CORS_EXPOSE_HEADERS.some((h) => /^mcp-protocol-version$/i.test(h)) &&
    DEFAULT_CORS_EXPOSE_HEADERS.some((h) => /^mcp-session-id$/i.test(h)) &&
    DEFAULT_CORS_METHODS.includes("DELETE") &&
    DEFAULT_CORS_METHODS.includes("POST") &&
    /DELETE/i.test(
      handlePreflight({ headers: { origin: "http://localhost:3000" } }, corsPol)?.headers?.[
        "access-control-allow-methods"
      ] || ""
    );
  if (!corsOk) {
    console.error("smoke failed cors");
    process.exit(1);
  }
  const timeoutOk =
    DEFAULT_UPSTREAM_TIMEOUT_MS === 5000 &&
    resolveUpstreamTimeoutMs({}) === 5000 &&
    resolveUpstreamTimeoutMs({ timeoutMs: 200 }) === 200 &&
    resolveUpstreamTimeoutMs({ timeoutMs: "30000" }) === 30000 &&
    resolveUpstreamTimeoutMs({ timeoutMs: 0 }) === 5000 &&
    resolveUpstreamTimeoutMs({ timeoutMs: -1 }) === 5000;
  if (!timeoutOk) {
    console.error("smoke failed upstream.timeoutMs");
    process.exit(1);
  }
  const customRid = "mvp-req-id-a1b2c3d4";
  const ridOk =
    resolveRequestId({ headers: { "x-request-id": customRid } }) === customRid &&
    isUuid(resolveRequestId({ headers: {} })) &&
    isUuid(resolveRequestId({ headers: { "x-request-id": "  " } })) &&
    sanitizeRequestId("foo\r\nX-Injected: 1") === "fooX-Injected: 1" &&
    sanitizeRequestId("x".repeat(200)).length === 128 &&
    sanitizeRequestId("") === null;
  if (!ridOk) {
    console.error("smoke failed X-Request-Id resolve/sanitize");
    process.exit(1);
  }
  const accessLine = formatAccessLog({
    service: "mcp-gateway",
    method: "GET",
    path: "/openapi.json",
    status: 200,
    durationMs: 12,
    requestId: "test-log-1",
  });
  let accessObj;
  try {
    accessObj = JSON.parse(accessLine);
  } catch {
    accessObj = null;
  }
  const accessOk =
    accessObj &&
    accessObj.level === "info" &&
    accessObj.msg === "http" &&
    accessObj.service === "mcp-gateway" &&
    accessObj.method === "GET" &&
    accessObj.path === "/openapi.json" &&
    accessObj.status === 200 &&
    accessObj.requestId === "test-log-1" &&
    typeof accessObj.durationMs === "number" &&
    accessObj.durationMs === 12 &&
    accessLine.includes('"msg":"http"') &&
    shouldSkipAccessLog("GET", "/metrics") &&
    shouldSkipAccessLog("GET", "/health") &&
    shouldSkipAccessLog("GET", "/ready") &&
    shouldSkipAccessLog("OPTIONS", "/tools/list") &&
    !shouldSkipAccessLog("GET", "/openapi.json") &&
    resolveLogJson(undefined, {}) === false &&
    resolveLogJson(undefined, { LOG_FORMAT: "json" }) === true &&
    resolveLogJson(true, {}) === true &&
    resolveLogJson(false, { LOG_FORMAT: "json" }) === false;
  if (!accessOk) {
    console.error("smoke failed JSON access log format/resolve", accessLine);
    process.exit(1);
  }
  const hmacBody = '{"type":"tool_call"}';
  const hmacSig = signWebhookBody("whsec_smoke", hmacBody);
  const hmacOk =
    hmacSig.startsWith("sha256=") &&
    hmacSig.length === "sha256=".length + 64 &&
    verifyWebhookSignature("whsec_smoke", hmacBody, hmacSig) &&
    verifyWebhookSignature("whsec_smoke", hmacBody, hmacSig.toUpperCase()) &&
    !verifyWebhookSignature("whsec_other", hmacBody, hmacSig) &&
    !verifyWebhookSignature("whsec_smoke", hmacBody, null) &&
    !verifyWebhookSignature(null, hmacBody, hmacSig) &&
    !verifyWebhookSignature("whsec_smoke", "tampered", hmacSig);
  if (!hmacOk) {
    console.error("smoke failed webhook HMAC sign/verify", hmacSig);
    process.exit(1);
  }
  const tsNow = webhookUnixSeconds();
  const wall = Math.floor(Date.now() / 1000);
  const tsOk =
    TIMESTAMP_HEADER === "X-Webhook-Timestamp" &&
    Math.abs(wall - tsNow) <= 2 &&
    webhookUnixSeconds(1700000000900) === 1700000000;
  if (!tsOk) {
    console.error("smoke failed webhook timestamp", { tsNow, wall, TIMESTAMP_HEADER });
    process.exit(1);
  }
  const retryPolicyOk =
    DEFAULT_RETRY_DELAY_MS === 50 &&
    shouldRetryWebhook({ status: 500 }) &&
    shouldRetryWebhook({ status: 503 }) &&
    shouldRetryWebhook({ status: 599 }) &&
    shouldRetryWebhook({ error: new Error("network") }) &&
    !shouldRetryWebhook({ status: 200 }) &&
    !shouldRetryWebhook({ status: 204 }) &&
    !shouldRetryWebhook({ status: 400 }) &&
    !shouldRetryWebhook({ status: 404 }) &&
    !shouldRetryWebhook({ status: 429 }) &&
    !shouldRetryWebhook({});
  if (!retryPolicyOk) {
    console.error("smoke failed webhook shouldRetryWebhook policy");
    process.exit(1);
  }

  const retryPol = {
    webhooks: [{ url: "http://127.0.0.1:9/hook", events: ["tool_call"] }],
    webhooksRedact: true,
  };
  const retryEv = {
    allow: true,
    tool: "echo",
    arguments: { message: "retry-secret" },
    requestId: "rid-retry",
  };

  async function runFanOut(fetchFn, extra = {}) {
    const sleepCalls = [];
    const metrics = extra.metrics || createMetrics();
    await fanOutWebhooks(retryPol, retryEv, {
      fetchFn,
      sleepFn: async (ms) => {
        sleepCalls.push(ms);
      },
      retryDelayMs: extra.retryDelayMs ?? DEFAULT_RETRY_DELAY_MS,
      metrics,
    });
    return { sleepCalls, metrics };
  }

  {
    const calls = [];
    const fetchFn = async (_url, init) => {
      calls.push(init);
      return { status: 200 };
    };
    const { sleepCalls, metrics } = await runFanOut(fetchFn);
    const rendered = metrics.render();
    const m = rendered.match(/^webhook_retries_total (\d+)$/m);
    if (calls.length !== 1 || sleepCalls.length !== 0 || !m || Number(m[1]) !== 0) {
      console.error("smoke failed webhook no-retry on 200", { calls: calls.length, sleepCalls, m });
      process.exit(1);
    }
    if (String(calls[0].body || "").includes("retry-secret")) {
      console.error("smoke failed webhook redact on 200 fan-out");
      process.exit(1);
    }
  }
  {
    const calls = [];
    const fetchFn = async (_url, init) => {
      calls.push(init);
      return { status: 400 };
    };
    const { sleepCalls, metrics } = await runFanOut(fetchFn);
    const m = metrics.render().match(/^webhook_retries_total (\d+)$/m);
    if (calls.length !== 1 || sleepCalls.length !== 0 || !m || Number(m[1]) !== 0) {
      console.error("smoke failed webhook no-retry on 4xx", { calls: calls.length, sleepCalls, m });
      process.exit(1);
    }
  }
  {
    const calls = [];
    const fetchFn = async (_url, init) => {
      calls.push(init);
      if (calls.length === 1) return { status: 500 };
      return { status: 200 };
    };
    const { sleepCalls, metrics } = await runFanOut(fetchFn);
    const m = metrics.render().match(/^webhook_retries_total (\d+)$/m);
    if (
      calls.length !== 2 ||
      sleepCalls.length !== 1 ||
      sleepCalls[0] !== DEFAULT_RETRY_DELAY_MS ||
      !m ||
      Number(m[1]) !== 1
    ) {
      console.error("smoke failed webhook retry on 5xx", { calls: calls.length, sleepCalls, m });
      process.exit(1);
    }
    if (calls[0].body !== calls[1].body) {
      console.error("smoke failed webhook retry body mismatch");
      process.exit(1);
    }
  }
  {
    const calls = [];
    const fetchFn = async (_url, init) => {
      calls.push(init);
      if (calls.length === 1) throw new Error("ECONNRESET");
      return { status: 200 };
    };
    const { sleepCalls, metrics } = await runFanOut(fetchFn);
    const m = metrics.render().match(/^webhook_retries_total (\d+)$/m);
    if (calls.length !== 2 || sleepCalls.length !== 1 || !m || Number(m[1]) !== 1) {
      console.error("smoke failed webhook retry on network error", { calls: calls.length, sleepCalls, m });
      process.exit(1);
    }
  }
  {
    const hmacPol = {
      webhooks: [
        {
          url: "http://127.0.0.1:9/hook",
          events: ["tool_call"],
          secret: "whsec_retry",
        },
      ],
      webhooksRedact: true,
    };
    const calls = [];
    const fetchFn = async (_url, init) => {
      calls.push(init);
      if (calls.length === 1) return { status: 503 };
      return { status: 200 };
    };
    await fanOutWebhooks(hmacPol, retryEv, {
      fetchFn,
      sleepFn: async () => {},
      retryDelayMs: 0,
    });
    if (calls.length !== 2) {
      console.error("smoke failed webhook HMAC retry call count", calls.length);
      process.exit(1);
    }
    const sig0 = calls[0].headers?.[SIGNATURE_HEADER] || calls[0].headers?.["X-Webhook-Signature"];
    const sig1 = calls[1].headers?.[SIGNATURE_HEADER] || calls[1].headers?.["X-Webhook-Signature"];
    const expected = signWebhookBody("whsec_retry", calls[0].body);
    if (sig0 !== expected || sig1 !== expected) {
      console.error("smoke failed webhook HMAC retry signatures", { sig0, sig1, expected });
      process.exit(1);
    }
    const ts0 = calls[0].headers?.[TIMESTAMP_HEADER];
    const ts1 = calls[1].headers?.[TIMESTAMP_HEADER];
    if (!ts0 || !ts1) {
      console.error("smoke failed webhook timestamp on retry", { ts0, ts1 });
      process.exit(1);
    }
  }
  const gzipRound = gzipBytes('{"ok":true}');
  const gzipOk =
    wantsGzip({ gzipQuery: "1" }) &&
    wantsGzip({ gzipQuery: "true" }) &&
    wantsGzip({ acceptEncoding: "gzip, deflate" }) &&
    wantsGzip({ acceptEncoding: "x-gzip" }) &&
    wantsGzip({}) === false &&
    wantsGzip({ gzipQuery: "0", acceptEncoding: "gzip" }) === false &&
    zlib.gunzipSync(gzipRound).toString("utf8") === '{"ok":true}';
  if (!gzipOk) {
    console.error("smoke failed gzip export helpers");
    process.exit(1);
  }
  const adminOkEv = {
    ts: "2026-08-13T00:00:00.000Z",
    tenantId: "acme",
    tool: "echo",
    allow: true,
    reason: "ok",
    via: "builtin",
    arguments: { token: "sk-secret-smoke", password: "hunter2" },
    result: { Authorization: "Bearer sk-secret-smoke" },
    requestId: "rid-ok",
  };
  const adminErrEv = {
    ts: "2026-08-13T00:00:01.000Z",
    tenantId: "acme",
    tool: "deletePet",
    allow: false,
    reason: "denied",
    via: "builtin",
    arguments: { token: "sk-secret-smoke" },
    result: null,
    requestId: "rid-err",
  };
  const adminCsv = eventsToAdminCsv([adminOkEv, adminErrEv]);
  const adminHeader = (adminCsv.split("\n")[0] || "").trim();
  const adminLines = adminCsv.trimEnd().split(/\n/);
  const adminEmpty = eventsToAdminCsv([]);
  const adminEmptyHeader = adminEmpty.trimEnd();
  const packCsv = eventsToCsv([adminOkEv]);
  const adminCsvOk =
    adminHeader === ADMIN_CSV_COLUMNS.join(",") &&
    adminLines.length === 3 &&
    adminLines[1].includes("true") &&
    adminLines[2].includes("false") &&
    adminLines[1].includes("echo") &&
    adminLines[2].includes("deletePet") &&
    adminLines[1].includes("rid-ok") &&
    adminLines[2].includes("rid-err") &&
    !adminCsv.includes("sk-secret-smoke") &&
    !adminCsv.includes("hunter2") &&
    !adminCsv.includes("Bearer") &&
    !adminCsv.includes("arguments") &&
    !adminCsv.includes("result") &&
    !adminCsv.includes("password") &&
    adminEmptyHeader === ADMIN_CSV_COLUMNS.join(",") &&
    packCsv.includes("arguments") &&
    packCsv.includes("sk-secret-smoke");
  if (!adminCsvOk) {
    console.error("smoke failed admin/SIEM audit CSV helper", adminCsv);
    process.exit(1);
  }
  const adminMd = eventsToAdminMd([adminOkEv, adminErrEv]);
  const adminMdLines = adminMd.trimEnd().split(/\n/);
  const adminMdEmpty = eventsToAdminMd([]);
  const adminMdEmptyLines = adminMdEmpty.trimEnd().split(/\n/);
  const adminMdOk =
    adminMdLines[0] === ADMIN_MD_HEADING &&
    adminMdLines[1] === "| ts | tenantId | tool | allow | reason | via | requestId |" &&
    adminMdLines[2] === "| --- | --- | --- | --- | --- | --- | --- |" &&
    adminMdLines.length === 5 &&
    adminMdLines[3].includes("true") &&
    adminMdLines[4].includes("false") &&
    adminMdLines[3].includes("echo") &&
    adminMdLines[4].includes("deletePet") &&
    adminMdLines[3].includes("rid-ok") &&
    adminMdLines[4].includes("rid-err") &&
    !adminMd.includes("sk-secret-smoke") &&
    !adminMd.includes("hunter2") &&
    !adminMd.includes("Bearer") &&
    !adminMd.includes("arguments") &&
    !adminMd.includes("result") &&
    !adminMd.includes("password") &&
    adminMdEmptyLines[0] === ADMIN_MD_HEADING &&
    adminMdEmptyLines[1] === "| ts | tenantId | tool | allow | reason | via | requestId |" &&
    adminMdEmptyLines.length === 3;
  if (!adminMdOk) {
    console.error("smoke failed admin/SIEM audit Markdown helper", adminMd);
    process.exit(1);
  }
  const htmlXssEv = {
    ...adminOkEv,
    reason: "ok <script>alert(1)</script> & amp",
  };
  const adminHtml = eventsToAdminHtml([htmlXssEv, adminErrEv]);
  const adminHtmlEmpty = eventsToAdminHtml([]);
  const adminHtmlOk =
    adminHtml.includes("<table") &&
    adminHtml.includes("<h1>" + ADMIN_HTML_HEADING + "</h1>") &&
    adminHtml.includes("Audit") &&
    adminHtml.includes("&lt;script&gt;") &&
    !adminHtml.includes("<script>") &&
    adminHtml.includes("&amp;") &&
    adminHtml.includes("echo") &&
    adminHtml.includes("deletePet") &&
    adminHtml.includes("rid-ok") &&
    adminHtml.includes("rid-err") &&
    adminHtml.includes('class="allow"') &&
    adminHtml.includes('class="deny"') &&
    !adminHtml.includes("sk-secret-smoke") &&
    !adminHtml.includes("hunter2") &&
    !adminHtml.includes("Bearer") &&
    !adminHtml.includes("arguments") &&
    !adminHtml.includes("password") &&
    adminHtmlEmpty.includes("<table") &&
    adminHtmlEmpty.includes("<h1>" + ADMIN_HTML_HEADING + "</h1>") &&
    adminHtmlEmpty.includes("no events") &&
    !adminHtmlEmpty.includes("rid-ok") &&
    adminHtmlEmpty.startsWith("<!");
  if (!adminHtmlOk) {
    console.error("smoke failed admin/SIEM audit HTML helper", adminHtml.slice(0, 800), adminHtmlEmpty.slice(0, 400));
    process.exit(1);
  }
  const ring = [];
  for (let i = 1; i <= 5; i++) {
    pushAuditEvent(
      ring,
      {
        ts: "2026-08-13T00:00:0" + i + ".000Z",
        tenantId: "acme",
        tool: "echo",
        allow: true,
        reason: "ok",
        via: "builtin",
        requestId: "rid-" + i,
      },
      3
    );
  }
  const ringCsv = eventsToAdminCsv(ring);
  const ringLines = ringCsv.trimEnd().split(/\n/);
  const ringOk =
    ring.length === 3 &&
    ring[0].requestId === "rid-3" &&
    ring[1].requestId === "rid-4" &&
    ring[2].requestId === "rid-5" &&
    ringLines.length === 4 &&
    ringLines[0] === ADMIN_CSV_COLUMNS.join(",") &&
    ringCsv.includes("rid-3") &&
    ringCsv.includes("rid-4") &&
    ringCsv.includes("rid-5") &&
    !ringCsv.includes("rid-1") &&
    !ringCsv.includes("rid-2");
  if (!ringOk) {
    console.error("smoke failed audit ring buffer cap", ring, ringCsv);
    process.exit(1);
  }
  const ringMd = eventsToAdminMd(ring);
  const ringMdLines = ringMd.trimEnd().split(/\n/);
  const ringMdOk =
    ringMdLines.length === 6 &&
    ringMdLines[0] === ADMIN_MD_HEADING &&
    ringMd.includes("rid-3") &&
    ringMd.includes("rid-4") &&
    ringMd.includes("rid-5") &&
    !ringMd.includes("rid-1") &&
    !ringMd.includes("rid-2");
  if (!ringMdOk) {
    console.error("smoke failed audit ring Markdown cap", ringMd);
    process.exit(1);
  }
  const adminMdTmp = path.join("/tmp", "b-admin-md-smoke-audit.jsonl");
  try { fs.unlinkSync(adminMdTmp); } catch { /* ignore */ }
  const gwAdminMd = createServer({
    policy: {
      adminToken: "admin-dev-token",
      allow: [],
      deny: [],
      tools: [],
    },
    auditPath: adminMdTmp,
  });
  await new Promise((resolve, reject) => {
    gwAdminMd.server.once("error", reject);
    gwAdminMd.server.listen(0, "127.0.0.1", resolve);
  });
  try {
    const mdPort = gwAdminMd.server.address().port;
    const mdBase = "http://127.0.0.1:" + mdPort;
    for (const path of [
      "/admin/audit.md",
      "/admin/audit?format=md",
      "/admin/audit.csv",
      "/admin/audit.html",
      "/admin/audit?format=html",
    ]) {
      const unauth = await fetch(mdBase + path);
      const unauthBody = await unauth.json();
      if (unauth.status !== 401 || unauthBody.error !== "unauthorized_admin") {
        console.error("smoke failed admin audit unauth", path, unauth.status, unauthBody);
        process.exit(1);
      }
    }
    const okMd = await fetch(mdBase + "/admin/audit.md", {
      headers: { "x-admin-token": "admin-dev-token" },
    });
    const okMdText = await okMd.text();
    const okCt = okMd.headers.get("content-type") || "";
    if (
      okMd.status !== 200 ||
      !okCt.includes("text/markdown") ||
      !okMdText.startsWith(ADMIN_MD_HEADING) ||
      !okMdText.includes("| ts | tenantId | tool | allow | reason | via | requestId |")
    ) {
      console.error("smoke failed admin audit.md empty 200", okMd.status, okCt, okMdText);
      process.exit(1);
    }
    const okHtml = await fetch(mdBase + "/admin/audit.html", {
      headers: { "x-admin-token": "admin-dev-token" },
    });
    const okHtmlText = await okHtml.text();
    const okHtmlCt = okHtml.headers.get("content-type") || "";
    if (
      okHtml.status !== 200 ||
      !okHtmlCt.includes("text/html") ||
      !okHtmlText.includes("<table") ||
      !okHtmlText.includes("<h1>" + ADMIN_HTML_HEADING + "</h1>") ||
      !okHtmlText.includes("no events")
    ) {
      console.error("smoke failed admin audit.html empty 200", okHtml.status, okHtmlCt, okHtmlText);
      process.exit(1);
    }
    const okHtmlFmt = await fetch(mdBase + "/admin/audit?format=html", {
      headers: { "x-admin-token": "admin-dev-token" },
    });
    const okHtmlFmtText = await okHtmlFmt.text();
    const okHtmlFmtCt = okHtmlFmt.headers.get("content-type") || "";
    if (
      okHtmlFmt.status !== 200 ||
      !okHtmlFmtCt.includes("text/html") ||
      !okHtmlFmtText.includes("<table")
    ) {
      console.error("smoke failed admin audit?format=html empty 200", okHtmlFmt.status, okHtmlFmtCt, okHtmlFmtText);
      process.exit(1);
    }
  } finally {
    try { await gwAdminMd.close(); } catch { /* ignore */ }
    try { fs.unlinkSync(adminMdTmp); } catch { /* ignore */ }
  }
  const adminHtmlTmp = path.join("/tmp", "b-admin-html-smoke-audit.jsonl");
  try { fs.unlinkSync(adminHtmlTmp); } catch { /* ignore */ }
  fs.writeFileSync(
    adminHtmlTmp,
    JSON.stringify({
      ts: "2026-08-13T00:00:00.000Z",
      tenantId: "acme",
      tool: "echo",
      allow: false,
      reason: "denied <script>alert(1)</script> & x",
      via: "builtin",
      arguments: { token: "sk-secret-smoke" },
      result: { Authorization: "Bearer sk-secret-smoke" },
      requestId: "rid-html",
    }) + "\n",
    "utf8"
  );
  const gwAdminHtml = createServer({
    policy: {
      adminToken: "admin-dev-token",
      allow: [],
      deny: [],
      tools: [],
    },
    auditPath: adminHtmlTmp,
  });
  await new Promise((resolve, reject) => {
    gwAdminHtml.server.once("error", reject);
    gwAdminHtml.server.listen(0, "127.0.0.1", resolve);
  });
  try {
    const htmlPort = gwAdminHtml.server.address().port;
    const htmlBase = "http://127.0.0.1:" + htmlPort;
    const htmlUnauth = await fetch(htmlBase + "/admin/audit.html");
    const htmlUnauthBody = await htmlUnauth.json();
    if (htmlUnauth.status !== 401 || htmlUnauthBody.error !== "unauthorized_admin") {
      console.error("smoke failed admin audit.html unauth", htmlUnauth.status, htmlUnauthBody);
      process.exit(1);
    }
    const htmlOk = await fetch(htmlBase + "/admin/audit.html", {
      headers: { "x-admin-token": "admin-dev-token" },
    });
    const htmlText = await htmlOk.text();
    const htmlCt = htmlOk.headers.get("content-type") || "";
    if (
      htmlOk.status !== 200 ||
      !htmlCt.includes("text/html") ||
      !htmlText.includes("<table") ||
      !htmlText.includes("&lt;script&gt;") ||
      htmlText.includes("<script>") ||
      !htmlText.includes("&amp;") ||
      !htmlText.includes("rid-html") ||
      htmlText.includes("sk-secret-smoke") ||
      htmlText.includes("admin-dev-token")
    ) {
      console.error("smoke failed admin audit.html 200 escaped", htmlOk.status, htmlCt, htmlText.slice(0, 800));
      process.exit(1);
    }
  } finally {
    try { await gwAdminHtml.close(); } catch { /* ignore */ }
    try { fs.unlinkSync(adminHtmlTmp); } catch { /* ignore */ }
  }
  const adminTenantTmp = path.join("/tmp", "b-admin-audit-tenant-smoke.jsonl");
  try { fs.unlinkSync(adminTenantTmp); } catch { /* ignore */ }
  fs.writeFileSync(
    adminTenantTmp,
    JSON.stringify({
      ts: "2026-08-13T00:00:00.000Z",
      tenantId: "acme",
      tool: "echo",
      allow: true,
      reason: "ok",
      via: "builtin",
      arguments: { token: "sk-secret-smoke" },
      result: { Authorization: "Bearer sk-secret-smoke" },
      requestId: "rid-acme",
    }) + "\n" + JSON.stringify({
      ts: "2026-08-13T00:00:01.000Z",
      tenantId: "restricted",
      tool: "echo",
      allow: true,
      reason: "ok",
      via: "builtin",
      arguments: { token: "sk-secret-smoke" },
      requestId: "rid-restricted",
    }) + "\n",
    "utf8"
  );
  const gwAdminTenant = createServer({
    policy: {
      adminToken: "admin-dev-token",
      allow: [],
      deny: [],
      tools: [],
      tenants: [
        { id: "acme", apiKey: "ten_acme_dev" },
        { id: "restricted", apiKey: "ten_restricted_dev" },
      ],
    },
    auditPath: adminTenantTmp,
  });
  await new Promise((resolve, reject) => {
    gwAdminTenant.server.once("error", reject);
    gwAdminTenant.server.listen(0, "127.0.0.1", resolve);
  });
  try {
    const tenantPort = gwAdminTenant.server.address().port;
    const tenantBase = "http://127.0.0.1:" + tenantPort;
    const unauth = await fetch(tenantBase + "/admin/audit?tenant=acme");
    const unauthBody = await unauth.json();
    if (unauth.status !== 401 || unauthBody.error !== "unauthorized_admin") {
      console.error("smoke failed admin audit?tenant= unauth", unauth.status, unauthBody);
      process.exit(1);
    }
    const tenantKey = await fetch(tenantBase + "/admin/audit?tenant=acme", {
      headers: { authorization: "Bearer ten_acme_dev" },
    });
    const tenantKeyBody = await tenantKey.json();
    if (tenantKey.status !== 401 || tenantKeyBody.error !== "unauthorized_admin") {
      console.error("smoke failed admin audit?tenant= tenant key", tenantKey.status, tenantKeyBody);
      process.exit(1);
    }
    const unknown = await fetch(tenantBase + "/admin/audit?tenant=no-such-tenant", {
      headers: { "x-admin-token": "admin-dev-token" },
    });
    const unknownBody = await unknown.json();
    const unknownDump = JSON.stringify(unknownBody);
    if (
      unknown.status !== 200 ||
      unknownBody.count !== 0 ||
      !Array.isArray(unknownBody.events) ||
      unknownBody.events.length !== 0 ||
      unknownDump.includes("sk-secret-smoke") ||
      unknownDump.includes("admin-dev-token") ||
      unknownDump.includes("ten_acme_dev")
    ) {
      console.error("smoke failed admin audit?tenant= unknown empty 200", unknown.status, unknownBody);
      process.exit(1);
    }
    const acme = await fetch(tenantBase + "/admin/audit?tenant=acme", {
      headers: { "x-admin-token": "admin-dev-token" },
    });
    const acmeBody = await acme.json();
    const acmeDump = JSON.stringify(acmeBody);
    const acmeTenants = (acmeBody.events || []).map((e) => e.tenantId);
    if (
      acme.status !== 200 ||
      acmeBody.count !== 1 ||
      acmeTenants.join(",") !== "acme" ||
      acmeDump.includes("rid-restricted") ||
      acmeDump.includes("admin-dev-token") ||
      acmeDump.includes("ten_acme_dev")
    ) {
      console.error("smoke failed admin audit?tenant=acme", acme.status, acmeBody);
      process.exit(1);
    }
    const acmeCsv = await fetch(tenantBase + "/admin/audit.csv?tenant=acme", {
      headers: { "x-admin-token": "admin-dev-token" },
    });
    const acmeCsvText = await acmeCsv.text();
    if (
      acmeCsv.status !== 200 ||
      !acmeCsvText.includes("rid-acme") ||
      acmeCsvText.includes("rid-restricted") ||
      acmeCsvText.includes("sk-secret-smoke") ||
      acmeCsvText.includes("admin-dev-token") ||
      acmeCsvText.includes("ten_acme_dev")
    ) {
      console.error("smoke failed admin audit.csv?tenant=acme", acmeCsv.status, acmeCsvText);
      process.exit(1);
    }
  } finally {
    try { await gwAdminTenant.close(); } catch { /* ignore */ }
    try { fs.unlinkSync(adminTenantTmp); } catch { /* ignore */ }
  }
  const unlim = [];
  for (let i = 0; i < 5; i++) pushAuditEvent(unlim, { i }, 0);
  if (unlim.length !== 5) {
    console.error("smoke failed audit-max 0 unlimited", unlim.length);
    process.exit(1);
  }
  const maxOk =
    DEFAULT_AUDIT_MAX_EVENTS === 10000 &&
    ENV_AUDIT_MAX_EVENTS === "AUDIT_MAX_EVENTS" &&
    resolveAuditMaxEvents(undefined, {}) === DEFAULT_AUDIT_MAX_EVENTS &&
    resolveAuditMaxEvents(2) === 2 &&
    resolveAuditMaxEvents("2") === 2 &&
    resolveAuditMaxEvents(0) === 0 &&
    resolveAuditMaxEvents("0") === 0 &&
    resolveAuditMaxEvents(-1) === DEFAULT_AUDIT_MAX_EVENTS &&
    resolveAuditMaxEvents("nope") === DEFAULT_AUDIT_MAX_EVENTS &&
    resolveAuditMaxEvents(undefined, { AUDIT_MAX_EVENTS: "7" }) === 7 &&
    resolveAuditMaxEvents("3", { AUDIT_MAX_EVENTS: "7" }) === 3;
  if (!maxOk) {
    console.error("smoke failed resolveAuditMaxEvents");
    process.exit(1);
  }
  if (WATCH_POLL_MS !== 300) {
    console.error("smoke failed WATCH_POLL_MS", WATCH_POLL_MS);
    process.exit(1);
  }
  const metrics = createMetrics();
  const rendered0 = metrics.render();
  if (!rendered0.includes("upstream_timeout_total")) {
    console.error("smoke failed metrics missing upstream_timeout_total");
    process.exit(1);
  }
  metrics.incUpstreamTimeout();
  const rendered1 = metrics.render();
  const m = rendered1.match(/^upstream_timeout_total (\d+)$/m);
  if (!m || Number(m[1]) !== 1) {
    console.error("smoke failed upstream_timeout_total increment", m);
    process.exit(1);
  }
  if (!rendered0.includes("circuit_open_total")) {
    console.error("smoke failed metrics missing circuit_open_total");
    process.exit(1);
  }
  metrics.incCircuitOpen();
  const rendered2 = metrics.render();
  const c = rendered2.match(/^circuit_open_total (\d+)$/m);
  if (!c || Number(c[1]) !== 1) {
    console.error("smoke failed circuit_open_total increment", c);
    process.exit(1);
  }
  if (!rendered0.includes("webhook_retries_total")) {
    console.error("smoke failed metrics missing webhook_retries_total");
    process.exit(1);
  }
  metrics.incWebhookRetry();
  const renderedWh = metrics.render();
  const wr = renderedWh.match(/^webhook_retries_total (\d+)$/m);
  if (!wr || Number(wr[1]) !== 1) {
    console.error("smoke failed webhook_retries_total increment", wr);
    process.exit(1);
  }
  if (!rendered0.includes("audit_events") || !rendered0.includes("audit_retained")) {
    console.error("smoke failed metrics missing audit_events/audit_retained");
    process.exit(1);
  }
  metrics.setAuditEvents(3);
  const renderedAudit = metrics.render();
  const ae = renderedAudit.match(/^audit_events (\d+)$/m);
  const ar = renderedAudit.match(/^audit_retained (\d+)$/m);
  if (!ae || Number(ae[1]) !== 3 || !ar || Number(ar[1]) !== 3) {
    console.error("smoke failed audit_events/audit_retained gauge", ae, ar);
    process.exit(1);
  }
  const brOff = resolveBreakerConfig({});
  const brOn = resolveBreakerConfig({ breaker: {} });
  const brCustom = resolveBreakerConfig({ breaker: { failureThreshold: 1, openMs: 500 } });
  const brDisabled = resolveBreakerConfig({ breaker: { enabled: false } });
  const brZero = resolveBreakerConfig({ breaker: { failureThreshold: 0 } });
  if (
    brOff.enabled ||
    !brOn.enabled ||
    brOn.failureThreshold !== DEFAULT_BREAKER_FAILURE_THRESHOLD ||
    brOn.openMs !== DEFAULT_BREAKER_OPEN_MS ||
    brCustom.failureThreshold !== 1 ||
    brCustom.openMs !== 500 ||
    brDisabled.enabled ||
    brZero.enabled
  ) {
    console.error("smoke failed breaker config", { brOff, brOn, brCustom, brDisabled, brZero });
    process.exit(1);
  }
  let t = 0;
  const br = createCircuitBreaker(
    { enabled: true, failureThreshold: 2, openMs: 100 },
    { now: () => t }
  );
  if (!br.allow() || br.snapshot().state !== "closed") {
    console.error("smoke failed breaker start closed", br.snapshot());
    process.exit(1);
  }
  br.recordFailure();
  if (br.snapshot().state !== "closed") {
    console.error("smoke failed breaker still closed after 1 fail", br.snapshot());
    process.exit(1);
  }
  br.recordFailure();
  if (br.snapshot().state !== "open" || br.allow()) {
    console.error("smoke failed breaker open after threshold", br.snapshot());
    process.exit(1);
  }
  t = 50;
  if (br.allow()) {
    console.error("smoke failed breaker still open before openMs", br.snapshot());
    process.exit(1);
  }
  if (typeof br.retryAfterSeconds !== "function" || br.retryAfterSeconds() < 1) {
    console.error("smoke failed breaker retryAfterSeconds", br.retryAfterSeconds?.());
    process.exit(1);
  }
  let tRa = 0;
  const brRa = createCircuitBreaker(
    { enabled: true, failureThreshold: 1, openMs: 2500 },
    { now: () => tRa }
  );
  brRa.recordFailure();
  if (brRa.retryAfterSeconds() !== 3) {
    console.error("smoke failed retryAfterSeconds at open (want 3)", brRa.retryAfterSeconds());
    process.exit(1);
  }
  tRa = 1600;
  if (brRa.retryAfterSeconds() !== 1) {
    console.error("smoke failed retryAfterSeconds remaining (want 1)", brRa.retryAfterSeconds());
    process.exit(1);
  }
  const hs = brRa.healthSnapshot();
  if (!hs || hs.state !== "open" || !hs.openUntil) {
    console.error("smoke failed healthSnapshot while open", hs);
    process.exit(1);
  }
  const hsKeys = Object.keys(hs).sort().join(",");
  if (hsKeys !== "failures,openUntil,state") {
    console.error("smoke failed healthSnapshot keys (no Retry-After/secrets)", hsKeys);
    process.exit(1);
  }
  const offReady = createCircuitBreaker({ enabled: false }).readyPayload();
  if (
    offReady.status !== 200 ||
    offReady.body.ok !== true ||
    Object.prototype.hasOwnProperty.call(offReady.body, "breaker") ||
    offReady.body.reason
  ) {
    console.error("smoke failed readyPayload disabled", offReady);
    process.exit(1);
  }
  const openReady = brRa.readyPayload();
  if (
    openReady.status !== 503 ||
    openReady.body.ok !== false ||
    openReady.body.reason !== "circuit_open" ||
    !openReady.body.breaker ||
    openReady.body.breaker.state !== "open"
  ) {
    console.error("smoke failed readyPayload open", openReady);
    process.exit(1);
  }
  t = 100;
  const halfReady = br.readyPayload();
  if (
    halfReady.status !== 200 ||
    halfReady.body.ok !== true ||
    halfReady.body.breaker?.state !== "half_open"
  ) {
    console.error("smoke failed readyPayload half_open", halfReady);
    process.exit(1);
  }
  if (!br.allow()) {
    console.error("smoke failed breaker half-open probe denied", br.snapshot());
    process.exit(1);
  }
  if (br.allow()) {
    console.error("smoke failed breaker half-open second probe allowed", br.snapshot());
    process.exit(1);
  }
  br.recordSuccess();
  if (br.snapshot().state !== "closed" || !br.allow()) {
    console.error("smoke failed breaker close after probe success", br.snapshot());
    process.exit(1);
  }
  const closedReady = br.readyPayload();
  if (
    closedReady.status !== 200 ||
    closedReady.body.ok !== true ||
    closedReady.body.breaker?.state !== "closed"
  ) {
    console.error("smoke failed readyPayload closed after probe", closedReady);
    process.exit(1);
  }
  const drainOk =
    resolveDrainMs(200) === 200 &&
    resolveDrainMs("200") === 200 &&
    resolveDrainMs(-1) === DEFAULT_SHUTDOWN_DRAIN_MS &&
    resolveDrainMs("nope") === DEFAULT_SHUTDOWN_DRAIN_MS &&
    resolveDrainMs(99999) === MAX_SHUTDOWN_DRAIN_MS &&
    resolveDrainMs(undefined, {}) === DEFAULT_SHUTDOWN_DRAIN_MS &&
    resolveDrainMs(undefined, { SHUTDOWN_DRAIN_MS: "250" }) === 250 &&
    resolveDrainMs("100", { SHUTDOWN_DRAIN_MS: "250" }) === 100;
  if (!drainOk) {
    console.error("smoke failed resolveDrainMs");
    process.exit(1);
  }
  const gwSd = createServer({ policy: { allow: [], deny: [], tools: [] } });
  await new Promise((resolve, reject) => {
    gwSd.server.once("error", reject);
    gwSd.server.listen(0, "127.0.0.1", resolve);
  });
  try {
    const sdPort = gwSd.server.address().port;
    const sdBase = "http://127.0.0.1:" + sdPort;
    const ready0 = await fetch(sdBase + "/ready");
    const ready0Body = await ready0.json();
    if (ready0.status !== 200 || ready0Body.ok !== true) {
      console.error("smoke failed ready before shutdown", ready0.status, ready0Body);
      process.exit(1);
    }
    const health0 = await fetch(sdBase + "/health");
    const health0Body = await health0.json();
    if (health0.status !== 200 || health0Body.ok !== true || health0Body.shuttingDown) {
      console.error("smoke failed health before shutdown", health0.status, health0Body);
      process.exit(1);
    }
    gwSd.beginShutdown();
    const ready1 = await fetch(sdBase + "/ready");
    const ready1Body = await ready1.json();
    if (
      ready1.status !== 503 ||
      ready1Body.ok !== false ||
      ready1Body.reason !== "shutting_down"
    ) {
      console.error("smoke failed ready shutting_down", ready1.status, ready1Body);
      process.exit(1);
    }
    const health1 = await fetch(sdBase + "/health");
    const health1Body = await health1.json();
    if (
      health1.status !== 200 ||
      health1Body.ok !== true ||
      health1Body.shuttingDown !== true
    ) {
      console.error("smoke failed health shuttingDown", health1.status, health1Body);
      process.exit(1);
    }
  } finally {
    try { await gwSd.close(); } catch { /* ignore */ }
  }
  const rotGraceOk =
    DEFAULT_TOKEN_ROTATE_GRACE_SEC === 60 &&
    resolveRotateGraceSec(undefined, {}) === 60 &&
    resolveRotateGraceSec(0) === 0 &&
    resolveRotateGraceSec("0") === 0 &&
    resolveRotateGraceSec(45) === 45 &&
    resolveRotateGraceSec("30") === 30 &&
    resolveRotateGraceSec(-1) === DEFAULT_TOKEN_ROTATE_GRACE_SEC &&
    resolveRotateGraceSec("nope") === DEFAULT_TOKEN_ROTATE_GRACE_SEC &&
    resolveRotateGraceSec(undefined, { TOKEN_ROTATE_GRACE_SEC: "15" }) === 15 &&
    resolveRotateGraceSec("10", { TOKEN_ROTATE_GRACE_SEC: "15" }) === 10;
  if (!rotGraceOk) {
    console.error("smoke failed resolveRotateGraceSec");
    process.exit(1);
  }
  const rotPathOk =
    matchAdminRotatePath("/admin/tenants/acme/rotate")?.tenantId === "acme" &&
    matchAdminRotatePath("/admin/tenants/ip-locked/rotate")?.tenantId === "ip-locked" &&
    matchAdminRotatePath("/admin/tenants/rotate")?.kind === "body" &&
    matchAdminRotatePath("/admin/tenants") == null &&
    matchAdminRotatePath("/admin/reload") == null;
  if (!rotPathOk) {
    console.error("smoke failed matchAdminRotatePath");
    process.exit(1);
  }
  const getTenantPathOk =
    matchAdminGetTenantPath("/admin/tenants/acme")?.tenantId === "acme" &&
    matchAdminGetTenantPath("/admin/tenants/ip-locked")?.tenantId === "ip-locked" &&
    matchAdminGetTenantPath("/admin/tenants/ip-locked/")?.tenantId === "ip-locked" &&
    matchAdminGetTenantPath("/admin/tenants/%61cme")?.tenantId === "acme" &&
    matchAdminGetTenantPath("/admin/tenants") == null &&
    matchAdminGetTenantPath("/admin/tenants/") == null &&
    matchAdminGetTenantPath("/admin/tenants/rotate") == null &&
    matchAdminGetTenantPath("/admin/tenants/acme/rotate") == null &&
    matchAdminGetTenantPath("/admin/reload") == null;
  if (!getTenantPathOk) {
    console.error("smoke failed matchAdminGetTenantPath");
    process.exit(1);
  }

  // GET /admin/tenants/{id} helper: allowlist payload; must fail if apiKey is ever added.
  const tenantPoison = {
    allow: ["echo", "digest"],
    deny: ["shell"],
    rateLimitPerMinute: 60,
    maxBodyBytes: 1048576,
    tenants: [
      {
        id: "acme",
        apiKey: "ten_acme_dev",
        previousApiKey: "sk-secret-smoke",
        previousApiKeyExpiresAt: "2099-01-01T00:00:00.000Z",
        allow: ["echo"],
        deny: ["digest", "shell"],
        rateLimitPerMinute: 120,
        ipAllowlist: ["127.0.0.1"],
      },
    ],
  };
  const tenantSnap = summarizeTenantForAdmin(tenantPoison, "acme");
  let tenantParsed;
  try {
    tenantParsed = JSON.parse(JSON.stringify(tenantSnap));
  } catch (err) {
    console.error("smoke failed admin tenant JSON.parse", err);
    process.exit(1);
  }
  const tenantSafe = assertAdminTenantSafe(tenantParsed);
  if (
    !tenantSafe.ok ||
    tenantParsed.ok !== true ||
    tenantParsed.id !== "acme" ||
    tenantParsed.hasApiKey !== true ||
    tenantParsed.hasPreviousApiKey !== true ||
    tenantParsed.previousApiKeyExpiresAt !== "2099-01-01T00:00:00.000Z" ||
    !Array.isArray(tenantParsed.allow) ||
    tenantParsed.allow[0] !== "echo" ||
    !Array.isArray(tenantParsed.deny) ||
    tenantParsed.rateLimit !== 120 ||
    tenantParsed.hasIpAllowlist !== true
  ) {
    console.error("smoke failed admin tenant helper shape", tenantParsed, tenantSafe);
    process.exit(1);
  }
  if (
    Object.prototype.hasOwnProperty.call(tenantParsed, "apiKey") ||
    Object.prototype.hasOwnProperty.call(tenantParsed, "previousApiKey") ||
    tenantSafe.keys.length
  ) {
    console.error("smoke failed admin tenant helper leaked key", tenantSafe.keys, tenantParsed);
    process.exit(1);
  }
  const tenantUnknown = summarizeTenantForAdmin(tenantPoison, "nope");
  if (tenantUnknown.ok || tenantUnknown.error !== "tenant_not_found") {
    console.error("smoke failed admin tenant helper unknown", tenantUnknown);
    process.exit(1);
  }
  const tenantPlanted = { ...tenantParsed, apiKey: "ten_acme_dev" };
  const tenantPlantedHits = collectForbiddenAdminTenantKeys(tenantPlanted);
  const tenantPlantedSafe = assertAdminTenantSafe(tenantPlanted);
  if (tenantPlantedSafe.ok || !tenantPlantedHits.some((h) => /\.apiKey$/i.test(h))) {
    console.error("smoke failed admin tenant guard would not catch apiKey", tenantPlantedHits, tenantPlantedSafe);
    process.exit(1);
  }
  const rotNow = 1_700_000_000_000;
  const rotPol = {
    tenants: [{ id: "acme", apiKey: "old_secret_token_rotate" }],
  };
  const rot = rotateTenantApiKey(rotPol, "acme", { graceSec: 60, now: rotNow });
  if (!rot.ok || rot.token === "old_secret_token_rotate" || rot.tenantId !== "acme") {
    console.error("smoke failed rotateTenantApiKey new token", rot);
    process.exit(1);
  }
  if (!rot.previousTokenExpiresAt) {
    console.error("smoke failed rotate previousTokenExpiresAt missing", rot);
    process.exit(1);
  }
  const inGrace = rotNow + 1_000;
  const afterGrace = rotNow + 60_000;
  if (!findTenantByApiKey(rotPol, rot.token, inGrace)) {
    console.error("smoke failed rotate: new token should work in grace");
    process.exit(1);
  }
  if (!findTenantByApiKey(rotPol, "old_secret_token_rotate", inGrace)) {
    console.error("smoke failed rotate: old token should work in grace");
    process.exit(1);
  }
  if (!findTenantByApiKey(rotPol, rot.token, afterGrace)) {
    console.error("smoke failed rotate: new token should work after grace");
    process.exit(1);
  }
  if (findTenantByApiKey(rotPol, "old_secret_token_rotate", afterGrace)) {
    console.error("smoke failed rotate: old token should be invalid after grace");
    process.exit(1);
  }
  const rotZeroPol = { tenants: [{ id: "acme", apiKey: "old_secret_token_rotate" }] };
  const rotZero = rotateTenantApiKey(rotZeroPol, "acme", { graceSec: 0, now: rotNow });
  if (findTenantByApiKey(rotZeroPol, "old_secret_token_rotate", rotNow)) {
    console.error("smoke failed rotate grace=0: old token still valid");
    process.exit(1);
  }
  if (!findTenantByApiKey(rotZeroPol, rotZero.token, rotNow)) {
    console.error("smoke failed rotate grace=0: new token invalid");
    process.exit(1);
  }
  const unknownRot = rotateTenantApiKey(rotPol, "no-such-tenant", { graceSec: 60, now: rotNow });
  if (unknownRot.ok || unknownRot.error?.code !== "unknown_tenant") {
    console.error("smoke failed rotate unknown tenant", unknownRot);
    process.exit(1);
  }
  const rotEv = tokenRotatedAuditEvent({
    tenantId: "acme",
    requestId: "rid-rotate",
    previousTokenExpiresAt: rot.previousTokenExpiresAt,
    now: rotNow,
  });
  const rotEvJson = JSON.stringify(rotEv);
  const rotCsv = eventsToAdminCsv([rotEv]);
  if (
    rotEv.type !== "token_rotated" ||
    rotEv.tenantId !== "acme" ||
    rotEvJson.includes(rot.token) ||
    rotEvJson.includes("old_secret_token_rotate") ||
    rotCsv.includes(rot.token) ||
    rotCsv.includes("old_secret_token_rotate") ||
    !rotCsv.includes("token_rotated") && rotEv.type !== "token_rotated"
  ) {
    console.error("smoke failed token_rotated audit (secret leak or missing type)", rotEv, rotCsv);
    process.exit(1);
  }
  if (rotEvJson.includes(rot.token) || rotCsv.includes(rot.token)) {
    console.error("smoke failed token_rotated audit leaked new token");
    process.exit(1);
  }
  const rotTmp = path.join("/tmp", "b-rotate-smoke-audit.jsonl");
  try { fs.unlinkSync(rotTmp); } catch { /* ignore */ }
  const gwRot = createServer({
    policy: {
      adminToken: "admin-dev-token",
      allow: ["echo"],
      deny: [],
      tenants: [{ id: "acme", apiKey: "ten_acme_old_rotate" }],
      tools: [{ name: "echo", description: "echo" }],
    },
    auditPath: rotTmp,
    rotateGraceSec: 0,
  });
  await new Promise((resolve, reject) => {
    gwRot.server.once("error", reject);
    gwRot.server.listen(0, "127.0.0.1", resolve);
  });
  try {
    const rotPort = gwRot.server.address().port;
    const rotBase = "http://127.0.0.1:" + rotPort;
    const unauth = await fetch(rotBase + "/admin/tenants/acme/rotate", { method: "POST" });
    const unauthBody = await unauth.json();
    if (unauth.status !== 401 || unauthBody.error !== "unauthorized_admin") {
      console.error("smoke failed rotate unauth", unauth.status, unauthBody);
      process.exit(1);
    }
    const missing = await fetch(rotBase + "/admin/tenants/nope/rotate", {
      method: "POST",
      headers: { "x-admin-token": "admin-dev-token" },
    });
    const missingBody = await missing.json();
    if (missing.status !== 404 || missingBody.error !== "unknown_tenant") {
      console.error("smoke failed rotate unknown", missing.status, missingBody);
      process.exit(1);
    }
    const okRot = await fetch(rotBase + "/admin/tenants/acme/rotate", {
      method: "POST",
      headers: { "x-admin-token": "admin-dev-token" },
    });
    const okBody = await okRot.json();
    if (okRot.status !== 200 || okBody.ok !== true || okBody.tenantId !== "acme" || !okBody.token) {
      console.error("smoke failed rotate 200", okRot.status, okBody);
      process.exit(1);
    }
    if (okBody.token === "ten_acme_old_rotate") {
      console.error("smoke failed rotate new token equals old");
      process.exit(1);
    }
    const newList = await fetch(rotBase + "/tools/list", {
      method: "POST",
      headers: { "content-type": "application/json", authorization: "Bearer " + okBody.token },
      body: "{}",
    });
    const newListBody = await newList.json();
    if (newList.status !== 200 || newListBody.tenantId !== "acme") {
      console.error("smoke failed rotate new token tools/list", newList.status, newListBody);
      process.exit(1);
    }
    const oldList = await fetch(rotBase + "/tools/list", {
      method: "POST",
      headers: { "content-type": "application/json", authorization: "Bearer ten_acme_old_rotate" },
      body: "{}",
    });
    if (oldList.status !== 401) {
      console.error("smoke failed rotate old token after grace=0", oldList.status, await oldList.text());
      process.exit(1);
    }
    const auditRaw = fs.readFileSync(rotTmp, "utf8");
    if (!auditRaw.includes("token_rotated") || auditRaw.includes(okBody.token) || auditRaw.includes("ten_acme_old_rotate")) {
      console.error("smoke failed rotate audit jsonl secret/type", auditRaw);
      process.exit(1);
    }
  } finally {
    try { await gwRot.close(); } catch { /* ignore */ }
    try { fs.unlinkSync(rotTmp); } catch { /* ignore */ }
  }


  const mcpHelperOk =
    MCP_PROTOCOL_VERSION === "2025-03-26" &&
    isMcpStreamablePath("/mcp") &&
    isMcpStreamablePath("/mcp/") &&
    !isMcpStreamablePath("/mcp/tools/list") &&
    !isMcpStreamablePath("/") &&
    isMcpJsonRpcPostPath("/mcp") &&
    isMcpJsonRpcPostPath("/") &&
    !isMcpJsonRpcPostPath("/mcp/tools/list") &&
    !isMcpJsonRpcPostPath("/tools/list") &&
    resolveProtocolVersion({ headers: {} }) === MCP_PROTOCOL_VERSION &&
    resolveProtocolVersion({ headers: { [MCP_PROTOCOL_VERSION_HEADER]: "2025-03-26" } }) ===
      "2025-03-26" &&
    resolveProtocolVersion({ headers: { [MCP_PROTOCOL_VERSION_HEADER]: "2024-11-05" } }) ===
      "2024-11-05" &&
    resolveProtocolVersion({ headers: { [MCP_PROTOCOL_VERSION_HEADER]: "nope" } }) ===
      MCP_PROTOCOL_VERSION &&
    resolveSessionId({ headers: {} }, { assignIfMissing: false }) === null &&
    isMcpUuid(resolveSessionId({ headers: {} }, { assignIfMissing: true })) &&
    resolveSessionId(
      { headers: { [MCP_SESSION_ID_HEADER]: "sess-client-1" } },
      { assignIfMissing: true }
    ) === "sess-client-1" &&
    mcpResponseHeaders({ protocolVersion: "2025-03-26", sessionId: "abc" })[
      MCP_SESSION_ID_HEADER
    ] === "abc" &&
    initializeResult({ protocolVersion: "2025-03-26", sessionId: "s1" }).sessionId === "s1" &&
    DEFAULT_SESSION_TTL_SEC === 3600 &&
    ENV_SESSION_TTL_SEC === "MCP_SESSION_TTL_SEC" &&
    DEFAULT_SESSION_MAX_IDS === 10000 &&
    ADMIN_SESSION_LIST_LIMIT === 100 &&
    SESSION_EXPIRED === "session_expired" &&
    SESSION_NOT_FOUND === "session_not_found" &&
    SESSION_ID_REQUIRED === "session_id_required" &&
    MCP_ALLOW_METHODS === "POST, DELETE" &&
    matchAdminSessionPath("/admin/sessions/abc-1")?.sessionId === "abc-1" &&
    matchAdminSessionPath("/admin/sessions/abc-1/")?.sessionId === "abc-1" &&
    matchAdminSessionPath("/admin/sessions/%61bc")?.sessionId === "abc" &&
    matchAdminSessionPath("/admin/sessions") === null &&
    matchAdminSessionPath("/admin/sessions/") === null &&
    matchAdminSessionPath("/admin/sessions/a/b") === null &&
    matchAdminSessionPath("/mcp") === null &&
    resolveSessionTtlSec(undefined, {}) === DEFAULT_SESSION_TTL_SEC &&
    resolveSessionTtlSec(0) === 0 &&
    resolveSessionTtlSec("0") === 0 &&
    resolveSessionTtlSec(1) === 1 &&
    resolveSessionTtlSec(-1) === DEFAULT_SESSION_TTL_SEC &&
    resolveSessionTtlSec("nope") === DEFAULT_SESSION_TTL_SEC &&
    resolveSessionTtlSec(undefined, { MCP_SESSION_TTL_SEC: "90" }) === 90 &&
    resolveSessionTtlSec("10", { MCP_SESSION_TTL_SEC: "90" }) === 10;
  if (!mcpHelperOk) {
    console.error("smoke failed streamable HTTP helpers");
    process.exit(1);
  }

  let tSess = 0;
  const stExp = createSessionStore({ ttlMs: 1, maxIds: 3, now: () => tSess });
  stExp.touch("s1");
  if (stExp.check("s1") !== "ok") {
    console.error("smoke failed session store fresh last-seen");
    process.exit(1);
  }
  tSess = 1;
  if (stExp.check("s1") !== "expired") {
    console.error("smoke failed session store ttl 1ms expire");
    process.exit(1);
  }
  if (stExp.check(null) !== "missing" || stExp.check("") !== "missing") {
    console.error("smoke failed session store missing header");
    process.exit(1);
  }
  if (stExp.check("fresh-unknown") !== "ok" || !stExp.lastSeen.has("fresh-unknown")) {
    console.error("smoke failed session store accept unknown id");
    process.exit(1);
  }
  let tKeep = 0;
  const stKeep = createSessionStore({ ttlMs: 0, now: () => tKeep });
  stKeep.touch("keep");
  tKeep = 1e9;
  if (stKeep.check("keep") !== "ok") {
    console.error("smoke failed session store ttl 0 no-expire");
    process.exit(1);
  }
  const stCap = createSessionStore({ ttlMs: 0, maxIds: 2, now: () => 0 });
  stCap.touch("a");
  stCap.touch("b");
  stCap.touch("c");
  if (stCap.lastSeen.has("a") || !stCap.lastSeen.has("b") || !stCap.lastSeen.has("c")) {
    console.error("smoke failed session store cap drop oldest", [...stCap.lastSeen.keys()]);
    process.exit(1);
  }
  const stDel = createSessionStore({ ttlMs: 0, now: () => 0 });
  stDel.touch("live");
  if (stDel.drop("live") !== "ok" || stDel.lastSeen.has("live") || !stDel.deleted.has("live")) {
    console.error("smoke failed session store drop live");
    process.exit(1);
  }
  if (stDel.drop("live") !== "not_found") {
    console.error("smoke failed session store drop idempotent");
    process.exit(1);
  }
  if (stDel.check("live") !== "not_found") {
    console.error("smoke failed session store check after drop");
    process.exit(1);
  }
  if (stDel.drop("") !== "missing" || stDel.drop(null) !== "missing") {
    console.error("smoke failed session store drop missing");
    process.exit(1);
  }
  if (stDel.drop("never-seen") !== "not_found") {
    console.error("smoke failed session store drop unknown");
    process.exit(1);
  }
  let tDropExp = 0;
  const stDropExp = createSessionStore({ ttlMs: 1, now: () => tDropExp });
  stDropExp.touch("e1");
  tDropExp = 1;
  if (stDropExp.drop("e1") !== "not_found") {
    console.error("smoke failed session store drop expired");
    process.exit(1);
  }

  const stListEmpty = createSessionStore({ ttlSec: 3600, now: () => 0 });
  const emptyInv = stListEmpty.list();
  if (
    emptyInv.ok !== true ||
    emptyInv.count !== 0 ||
    !Array.isArray(emptyInv.sessions) ||
    emptyInv.sessions.length !== 0 ||
    emptyInv.ttlSec !== 3600 ||
    emptyInv.cap !== DEFAULT_SESSION_MAX_IDS ||
    emptyInv.dropped !== 0 ||
    emptyInv.truncated
  ) {
    console.error("smoke failed session store list empty", emptyInv);
    process.exit(1);
  }
  let tList = 0;
  const stList = createSessionStore({ ttlMs: 0, now: () => tList });
  stList.touch("old");
  tList = 1;
  stList.touch("mid");
  tList = 2;
  stList.touch("new");
  const listed3 = stList.list({ limit: 2 });
  if (
    listed3.count !== 3 ||
    listed3.truncated !== true ||
    listed3.sessions.length !== 2 ||
    listed3.sessions[0].id !== "new" ||
    listed3.sessions[1].id !== "mid" ||
    listed3.sessions[0].ttlRemainingMs !== null ||
    listed3.dropped !== 0
  ) {
    console.error("smoke failed session store list truncate newest", listed3);
    process.exit(1);
  }
  if (stList.drop("mid") !== "ok") {
    console.error("smoke failed session store drop before list tombstone");
    process.exit(1);
  }
  const listedDrop = stList.list();
  if (
    listedDrop.count !== 2 ||
    listedDrop.dropped !== 1 ||
    listedDrop.sessions.some((s) => s.id === "mid") ||
    !listedDrop.sessions.some((s) => s.id === "new")
  ) {
    console.error("smoke failed session store list omits tombstone", listedDrop);
    process.exit(1);
  }
  let tListExp = 0;
  const stListExp = createSessionStore({ ttlMs: 1, now: () => tListExp });
  stListExp.touch("exp");
  tListExp = 1;
  const listedExp = stListExp.list();
  if (listedExp.count !== 0 || listedExp.sessions.length !== 0) {
    console.error("smoke failed session store list omits expired", listedExp);
    process.exit(1);
  }


  // GET /admin/config helper: allowlist payload; must fail if apiKey is ever added.
  const poisonedPolicy = {
    adminToken: "admin-dev-token",
    rateLimitPerMinute: 60,
    tenants: [
      {
        id: "acme",
        apiKey: "ten_acme_dev",
        previousApiKey: "sk-secret-smoke",
        previousApiKeyExpiresAt: "2099-01-01T00:00:00.000Z",
      },
    ],
    webhooks: [
      {
        url: "http://127.0.0.1:9/hook",
        events: ["tool_call"],
        secret: "whsec_super_secret",
      },
    ],
    cors: { origins: ["http://localhost:3000"] },
    upstream: {
      type: "http",
      baseUrl: "http://127.0.0.1:8790",
      timeoutMs: 5000,
      headers: { Authorization: "Bearer sk-secret-smoke" },
      breaker: { failureThreshold: 3, openMs: 2000 },
    },
  };
  const cfgSnap = summarizeConfigForAdmin({
    policy: poisonedPolicy,
    sessionTtlSec: 3600,
    sessionCap: 10000,
    auditMax: 10000,
    rotateGraceSec: 60,
  });
  let cfgParsed;
  try {
    cfgParsed = JSON.parse(JSON.stringify(cfgSnap));
  } catch (err) {
    console.error("smoke failed admin config JSON.parse", err);
    process.exit(1);
  }
  const cfgSafe = assertAdminConfigSafe(cfgParsed);
  if (
    !cfgSafe.ok ||
    cfgParsed.ok !== true ||
    cfgParsed.sessionTtlSec !== 3600 ||
    cfgParsed.sessionCap !== 10000 ||
    cfgParsed.auditMax !== 10000 ||
    cfgParsed.rotateGraceSec !== 60 ||
    cfgParsed.rateLimit?.perMinute !== 60 ||
    !Array.isArray(cfgParsed.cors?.origins) ||
    cfgParsed.cors.origins[0] !== "http://localhost:3000" ||
    cfgParsed.upstream?.timeoutMs !== 5000 ||
    cfgParsed.upstream?.breaker?.failureThreshold !== 3 ||
    cfgParsed.upstream?.breaker?.openMs !== 2000 ||
    cfgParsed.tenants?.count !== 1 ||
    cfgParsed.webhooks?.count !== 1 ||
    cfgParsed.webhooks?.destinations?.[0]?.hasWebhookSecret !== true
  ) {
    console.error("smoke failed admin config helper shape", cfgParsed, cfgSafe);
    process.exit(1);
  }
  if (Object.prototype.hasOwnProperty.call(cfgParsed, "apiKey") || cfgSafe.keys.length) {
    console.error("smoke failed admin config helper leaked key", cfgSafe.keys, cfgParsed);
    process.exit(1);
  }
  const planted = { ...cfgParsed, apiKey: "ten_acme_dev" };
  const plantedHits = collectForbiddenAdminConfigKeys(planted);
  const plantedSafe = assertAdminConfigSafe(planted);
  if (plantedSafe.ok || !plantedHits.some((h) => /\.apiKey$/i.test(h))) {
    console.error("smoke failed admin config guard would not catch apiKey", plantedHits, plantedSafe);
    process.exit(1);
  }


  // GET /admin/webhooks helper: allowlist payload; planted url/secret must fail.
  const hookEmpty = summarizeWebhooksForAdmin({});
  const hookEmptyArr = summarizeWebhooksForAdmin({ webhooks: [] });
  if (
    hookEmpty.ok !== true ||
    hookEmpty.count !== 0 ||
    !Array.isArray(hookEmpty.webhooks) ||
    hookEmpty.webhooks.length !== 0 ||
    hookEmptyArr.count !== 0 ||
    hookEmptyArr.webhooks.length !== 0
  ) {
    console.error("smoke failed admin webhooks helper empty", hookEmpty, hookEmptyArr);
    process.exit(1);
  }
  const hookSnap = summarizeWebhooksForAdmin(poisonedPolicy);
  let hookParsed;
  try {
    hookParsed = JSON.parse(JSON.stringify(hookSnap));
  } catch (err) {
    console.error("smoke failed admin webhooks JSON.parse", err);
    process.exit(1);
  }
  const hookSafe = assertAdminWebhooksSafe(hookParsed);
  const hookDump = JSON.stringify(hookParsed);
  if (
    !hookSafe.ok ||
    hookParsed.ok !== true ||
    hookParsed.count !== 1 ||
    !Array.isArray(hookParsed.webhooks) ||
    hookParsed.webhooks.length !== 1 ||
    hookParsed.webhooks[0].id !== 0 ||
    !Array.isArray(hookParsed.webhooks[0].events) ||
    hookParsed.webhooks[0].events[0] !== "tool_call" ||
    hookParsed.webhooks[0].hasUrl !== true ||
    hookParsed.webhooks[0].hasSecret !== true
  ) {
    console.error("smoke failed admin webhooks helper shape", hookParsed, hookSafe);
    process.exit(1);
  }
  if (
    hookDump.includes("http://127.0.0.1:9/hook") ||
    hookDump.includes("whsec_super_secret") ||
    Object.prototype.hasOwnProperty.call(hookParsed.webhooks[0], "url") ||
    Object.prototype.hasOwnProperty.call(hookParsed.webhooks[0], "secret") ||
    hookSafe.keys.length
  ) {
    console.error("smoke failed admin webhooks helper leaked url/secret", hookSafe.keys, hookParsed);
    process.exit(1);
  }
  const hookPlanted = {
    ...hookParsed,
    webhooks: [{ ...hookParsed.webhooks[0], url: "http://127.0.0.1:9/hook", secret: "whsec_super_secret" }],
  };
  const hookPlantedHits = collectForbiddenAdminWebhookKeys(hookPlanted);
  const hookPlantedSafe = assertAdminWebhooksSafe(hookPlanted);
  if (
    hookPlantedSafe.ok ||
    !hookPlantedHits.some((h) => /\.url$/i.test(h)) ||
    !hookPlantedHits.some((h) => /\.secret$/i.test(h))
  ) {
    console.error("smoke failed admin webhooks guard would not catch url/secret", hookPlantedHits, hookPlantedSafe);
    process.exit(1);
  }
  const hookNamed = summarizeWebhooksForAdmin({
    webhooks: [{ id: "ops-slack", url: "http://127.0.0.1:9/hook", events: ["deny"] }],
  });
  if (hookNamed.webhooks[0].id !== "ops-slack" || hookNamed.webhooks[0].hasSecret !== false) {
    console.error("smoke failed admin webhooks configured id", hookNamed);
    process.exit(1);
  }

  const cfgTmp = path.join("/tmp", "b-admin-config-smoke-audit.jsonl");
  try { fs.unlinkSync(cfgTmp); } catch { /* ignore */ }
  const cfgHttpPolicy = { ...poisonedPolicy };
  delete cfgHttpPolicy.upstream; // skip live connect (helper already covers upstream headers)
  const gwCfg = createServer({
    policy: cfgHttpPolicy,
    auditPath: cfgTmp,
    sessionTtlSec: 3600,
  });
  await new Promise((resolve, reject) => {
    gwCfg.server.once("error", reject);
    gwCfg.server.listen(0, "127.0.0.1", resolve);
  });
  try {
    const cfgPort = gwCfg.server.address().port;
    const cfgBase = "http://127.0.0.1:" + cfgPort;
    const cfgHttpUnauth = await fetch(cfgBase + "/admin/config");
    const cfgHttpUnauthBody = await cfgHttpUnauth.json();
    if (cfgHttpUnauth.status !== 401 || cfgHttpUnauthBody.error !== "unauthorized_admin") {
      console.error("smoke failed poisoned GET /admin/config unauth", cfgHttpUnauth.status, cfgHttpUnauthBody);
      process.exit(1);
    }
    const cfgHttp = await fetch(cfgBase + "/admin/config", {
      headers: { "x-admin-token": "admin-dev-token" },
    });
    const cfgHttpBody = await cfgHttp.json();
    const cfgHttpSafe = assertAdminConfigSafe(cfgHttpBody);
    if (
      cfgHttp.status !== 200 ||
      cfgHttpBody.ok !== true ||
      cfgHttpBody.sessionTtlSec !== 3600 ||
      cfgHttpBody.webhooks?.destinations?.[0]?.hasWebhookSecret !== true ||
      Object.prototype.hasOwnProperty.call(cfgHttpBody, "apiKey") ||
      !cfgHttpSafe.ok
    ) {
      console.error("smoke failed poisoned GET /admin/config", cfgHttp.status, cfgHttpBody, cfgHttpSafe);
      process.exit(1);
    }

    const hookHttpUnauth = await fetch(cfgBase + "/admin/webhooks");
    const hookHttpUnauthBody = await hookHttpUnauth.json();
    if (hookHttpUnauth.status !== 401 || hookHttpUnauthBody.error !== "unauthorized_admin") {
      console.error("smoke failed poisoned GET /admin/webhooks unauth", hookHttpUnauth.status, hookHttpUnauthBody);
      process.exit(1);
    }
    const hookHttpTenant = await fetch(cfgBase + "/admin/webhooks", {
      headers: { authorization: "Bearer ten_acme_dev" },
    });
    const hookHttpTenantBody = await hookHttpTenant.json();
    if (hookHttpTenant.status !== 401 || hookHttpTenantBody.error !== "unauthorized_admin") {
      console.error("smoke failed poisoned GET /admin/webhooks tenant key", hookHttpTenant.status, hookHttpTenantBody);
      process.exit(1);
    }
    const hookHttp = await fetch(cfgBase + "/admin/webhooks", {
      headers: { "x-admin-token": "admin-dev-token", "x-request-id": "smoke-admin-hooks-1" },
    });
    const hookHttpBody = await hookHttp.json();
    const hookHttpRid = hookHttp.headers.get("x-request-id");
    const hookHttpSafe = assertAdminWebhooksSafe(hookHttpBody);
    const hookHttpDump = JSON.stringify(hookHttpBody);
    if (
      hookHttp.status !== 200 ||
      hookHttpBody.ok !== true ||
      hookHttpBody.count < 1 ||
      hookHttpBody.webhooks?.[0]?.hasUrl !== true ||
      hookHttpBody.webhooks?.[0]?.hasSecret !== true ||
      hookHttpRid !== "smoke-admin-hooks-1" ||
      Object.prototype.hasOwnProperty.call(hookHttpBody.webhooks[0], "url") ||
      Object.prototype.hasOwnProperty.call(hookHttpBody.webhooks[0], "secret") ||
      hookHttpDump.includes("http://127.0.0.1:9/hook") ||
      hookHttpDump.includes("whsec_super_secret") ||
      !hookHttpSafe.ok
    ) {
      console.error("smoke failed poisoned GET /admin/webhooks", hookHttp.status, hookHttpBody, hookHttpSafe);
      process.exit(1);
    }
  } finally {
    try { await gwCfg.close(); } catch { /* ignore */ }
    try { fs.unlinkSync(cfgTmp); } catch { /* ignore */ }
  }

  const mcpTmp = path.join("/tmp", "b-mcp-http-smoke-audit.jsonl");
  try { fs.unlinkSync(mcpTmp); } catch { /* ignore */ }
  const gwMcp = createServer({
    policy: {
      adminToken: "admin-dev-token",
      allow: ["echo"],
      deny: [],
      tenants: [{ id: "acme", apiKey: "ten_acme_mcp" }],
      tools: [{ name: "echo", description: "echo" }],
    },
    auditPath: mcpTmp,
  });
  await new Promise((resolve, reject) => {
    gwMcp.server.once("error", reject);
    gwMcp.server.listen(0, "127.0.0.1", resolve);
  });
  try {
    const mcpPort = gwMcp.server.address().port;
    const mcpBase = "http://127.0.0.1:" + mcpPort;
    const auth = { "content-type": "application/json", authorization: "Bearer ten_acme_mcp" };


    const hookUnauth = await fetch(mcpBase + "/admin/webhooks");
    const hookUnauthBody = await hookUnauth.json();
    if (hookUnauth.status !== 401 || hookUnauthBody.error !== "unauthorized_admin") {
      console.error("smoke failed GET /admin/webhooks unauth", hookUnauth.status, hookUnauthBody);
      process.exit(1);
    }
    const hookUnauthDump = JSON.stringify(hookUnauthBody);
    if (hookUnauthDump.includes("ten_acme_mcp") || hookUnauthDump.includes("admin-dev-token")) {
      console.error("smoke failed GET /admin/webhooks 401 leaked secret");
      process.exit(1);
    }
    const hookTenant = await fetch(mcpBase + "/admin/webhooks", {
      headers: { authorization: "Bearer ten_acme_mcp" },
    });
    const hookTenantBody = await hookTenant.json();
    if (hookTenant.status !== 401 || hookTenantBody.error !== "unauthorized_admin") {
      console.error("smoke failed GET /admin/webhooks tenant key", hookTenant.status, hookTenantBody);
      process.exit(1);
    }
    const hookEmptyHttp = await fetch(mcpBase + "/admin/webhooks", {
      headers: { "x-admin-token": "admin-dev-token", "x-request-id": "smoke-admin-hooks-empty" },
    });
    const hookEmptyBody = await hookEmptyHttp.json();
    const hookEmptyRid = hookEmptyHttp.headers.get("x-request-id");
    const hookEmptySafe = assertAdminWebhooksSafe(hookEmptyBody);
    if (
      hookEmptyHttp.status !== 200 ||
      hookEmptyBody.ok !== true ||
      hookEmptyBody.count !== 0 ||
      !Array.isArray(hookEmptyBody.webhooks) ||
      hookEmptyBody.webhooks.length !== 0 ||
      hookEmptyRid !== "smoke-admin-hooks-empty" ||
      !hookEmptySafe.ok
    ) {
      console.error("smoke failed GET /admin/webhooks empty", hookEmptyHttp.status, hookEmptyRid, hookEmptyBody, hookEmptySafe);
      process.exit(1);
    }

    const sessUnauth = await fetch(mcpBase + "/admin/sessions");
    const sessUnauthBody = await sessUnauth.json();
    if (sessUnauth.status !== 401 || sessUnauthBody.error !== "unauthorized_admin") {
      console.error("smoke failed GET /admin/sessions unauth", sessUnauth.status, sessUnauthBody);
      process.exit(1);
    }
    const sessUnauthDump = JSON.stringify(sessUnauthBody);
    if (sessUnauthDump.includes("ten_acme_mcp") || sessUnauthDump.includes("admin-dev-token")) {
      console.error("smoke failed GET /admin/sessions 401 leaked secret");
      process.exit(1);
    }

    const cfgUnauth = await fetch(mcpBase + "/admin/config");
    const cfgUnauthBody = await cfgUnauth.json();
    if (cfgUnauth.status !== 401 || cfgUnauthBody.error !== "unauthorized_admin") {
      console.error("smoke failed GET /admin/config unauth", cfgUnauth.status, cfgUnauthBody);
      process.exit(1);
    }
    const cfgUnauthDump = JSON.stringify(cfgUnauthBody);
    if (cfgUnauthDump.includes("ten_acme_mcp") || cfgUnauthDump.includes("admin-dev-token")) {
      console.error("smoke failed GET /admin/config 401 leaked secret");
      process.exit(1);
    }
    const cfgOk = await fetch(mcpBase + "/admin/config", {
      headers: { "x-admin-token": "admin-dev-token", "x-request-id": "smoke-admin-cfg-1" },
    });
    const cfgOkBody = await cfgOk.json();
    const cfgOkRid = cfgOk.headers.get("x-request-id");
    const cfgOkSafe = assertAdminConfigSafe(cfgOkBody);
    if (
      cfgOk.status !== 200 ||
      cfgOkBody.ok !== true ||
      typeof cfgOkBody.sessionTtlSec !== "number" ||
      cfgOkBody.sessionTtlSec !== 3600 ||
      cfgOkBody.sessionCap !== 10000 ||
      cfgOkRid !== "smoke-admin-cfg-1" ||
      !cfgOkSafe.ok
    ) {
      console.error("smoke failed GET /admin/config 200", cfgOk.status, cfgOkRid, cfgOkBody, cfgOkSafe);
      process.exit(1);
    }
    if (Object.prototype.hasOwnProperty.call(cfgOkBody, "apiKey")) {
      console.error("smoke failed GET /admin/config includes apiKey", cfgOkBody);
      process.exit(1);
    }

    const tenUnauth = await fetch(mcpBase + "/admin/tenants/acme");
    const tenUnauthBody = await tenUnauth.json();
    if (tenUnauth.status !== 401 || tenUnauthBody.error !== "unauthorized_admin") {
      console.error("smoke failed GET /admin/tenants/{id} unauth", tenUnauth.status, tenUnauthBody);
      process.exit(1);
    }
    const tenUnauthDump = JSON.stringify(tenUnauthBody);
    if (tenUnauthDump.includes("ten_acme_mcp") || tenUnauthDump.includes("admin-dev-token")) {
      console.error("smoke failed GET /admin/tenants/{id} 401 leaked secret");
      process.exit(1);
    }
    const tenOk = await fetch(mcpBase + "/admin/tenants/acme", {
      headers: { "x-admin-token": "admin-dev-token", "x-request-id": "smoke-admin-tenant-1" },
    });
    const tenOkBody = await tenOk.json();
    const tenOkRid = tenOk.headers.get("x-request-id");
    const tenOkSafe = assertAdminTenantSafe(tenOkBody);
    if (
      tenOk.status !== 200 ||
      tenOkBody.ok !== true ||
      tenOkBody.id !== "acme" ||
      tenOkBody.hasApiKey !== true ||
      tenOkBody.hasPreviousApiKey !== false ||
      tenOkBody.previousApiKeyExpiresAt !== null ||
      !Array.isArray(tenOkBody.allow) ||
      tenOkRid !== "smoke-admin-tenant-1" ||
      !tenOkSafe.ok
    ) {
      console.error("smoke failed GET /admin/tenants/{id} 200", tenOk.status, tenOkRid, tenOkBody, tenOkSafe);
      process.exit(1);
    }
    if (
      Object.prototype.hasOwnProperty.call(tenOkBody, "apiKey") ||
      Object.prototype.hasOwnProperty.call(tenOkBody, "previousApiKey")
    ) {
      console.error("smoke failed GET /admin/tenants/{id} includes secret field", tenOkBody);
      process.exit(1);
    }
    const tenOkDump = JSON.stringify(tenOkBody);
    if (tenOkDump.includes("ten_acme_mcp") || tenOkDump.includes("admin-dev-token")) {
      console.error("smoke failed GET /admin/tenants/{id} 200 leaked fixture apiKey", tenOkDump);
      process.exit(1);
    }
    const tenMissing = await fetch(mcpBase + "/admin/tenants/no-such-tenant", {
      headers: { "x-admin-token": "admin-dev-token" },
    });
    const tenMissingBody = await tenMissing.json();
    if (tenMissing.status !== 404 || tenMissingBody.error !== "tenant_not_found") {
      console.error("smoke failed GET /admin/tenants/{id} 404", tenMissing.status, tenMissingBody);
      process.exit(1);
    }
    const tenMissingDump = JSON.stringify(tenMissingBody);
    if (tenMissingDump.includes("ten_acme_mcp") || tenMissingDump.includes("admin-dev-token")) {
      console.error("smoke failed GET /admin/tenants/{id} 404 leaked secret");
      process.exit(1);
    }

    const sessEmpty = await fetch(mcpBase + "/admin/sessions", {
      headers: { "x-admin-token": "admin-dev-token", "x-request-id": "smoke-admin-sess-1" },
    });
    const sessEmptyBody = await sessEmpty.json();
    const sessEmptyRid = sessEmpty.headers.get("x-request-id");
    if (
      sessEmpty.status !== 200 ||
      sessEmptyBody.ok !== true ||
      sessEmptyBody.count !== 0 ||
      !Array.isArray(sessEmptyBody.sessions) ||
      sessEmptyBody.sessions.length !== 0 ||
      sessEmptyBody.ttlSec !== 3600 ||
      sessEmptyBody.cap !== 10000 ||
      sessEmptyRid !== "smoke-admin-sess-1"
    ) {
      console.error("smoke failed GET /admin/sessions empty", sessEmpty.status, sessEmptyRid, sessEmptyBody);
      process.exit(1);
    }

    const getMcp = await fetch(mcpBase + "/mcp", { method: "GET" });
    const getBody = await getMcp.json();
    const getAllow = getMcp.headers.get("allow") || "";
    if (
      getMcp.status !== 405 ||
      !/POST/i.test(getAllow) ||
      !/DELETE/i.test(getAllow) ||
      getBody.error !== "method_not_allowed"
    ) {
      console.error("smoke failed GET /mcp 405", getMcp.status, getAllow, getBody);
      process.exit(1);
    }
    const getPv = getMcp.headers.get("mcp-protocol-version");
    if (getPv !== MCP_PROTOCOL_VERSION) {
      console.error("smoke failed GET /mcp protocol version header", getPv);
      process.exit(1);
    }

    const initRes = await fetch(mcpBase + "/mcp", {
      method: "POST",
      headers: { ...auth, "MCP-Protocol-Version": "2025-03-26" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "initialize",
        params: { protocolVersion: "2025-03-26", capabilities: {}, clientInfo: { name: "smoke" } },
      }),
    });
    const initBody = await initRes.json();
    const initSession =
      initRes.headers.get("mcp-session-id") || initBody?.result?.sessionId || "";
    const initPv = initRes.headers.get("mcp-protocol-version");
    if (
      initRes.status !== 200 ||
      initBody?.jsonrpc !== "2.0" ||
      !initBody?.result ||
      !isMcpUuid(String(initSession)) ||
      initPv !== "2025-03-26" ||
      initBody.result.protocolVersion !== "2025-03-26"
    ) {
      console.error("smoke failed POST /mcp initialize", initRes.status, initPv, initSession, initBody);
      process.exit(1);
    }

    const sessOne = await fetch(mcpBase + "/admin/sessions", {
      headers: { "x-admin-token": "admin-dev-token" },
    });
    const sessOneBody = await sessOne.json();
    const sessOneDump = JSON.stringify(sessOneBody);
    if (
      sessOne.status !== 200 ||
      sessOneBody.ok !== true ||
      sessOneBody.count !== 1 ||
      !Array.isArray(sessOneBody.sessions) ||
      sessOneBody.sessions.length !== 1 ||
      sessOneBody.sessions[0].id !== String(initSession) ||
      typeof sessOneBody.sessions[0].ageMs !== "number" ||
      typeof sessOneBody.sessions[0].ttlRemainingMs !== "number" ||
      !sessOneBody.sessions[0].lastSeen
    ) {
      console.error("smoke failed GET /admin/sessions count 1", sessOne.status, sessOneBody);
      process.exit(1);
    }
    if (
      sessOneDump.includes("ten_acme_mcp") ||
      sessOneDump.includes("admin-dev-token") ||
      /authorization/i.test(sessOneDump)
    ) {
      console.error("smoke failed GET /admin/sessions leaked secret");
      process.exit(1);
    }

    const listRpc = await fetch(mcpBase + "/mcp", {
      method: "POST",
      headers: auth,
      body: JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} }),
    });
    const listRpcBody = await listRpc.json();
    const listTools = listRpcBody?.result?.tools || [];
    if (
      listRpc.status !== 200 ||
      !Array.isArray(listTools) ||
      !listTools.some((t) => t.name === "echo")
    ) {
      console.error("smoke failed POST /mcp tools/list without session", listRpc.status, listRpcBody);
      process.exit(1);
    }

    const restList = await fetch(mcpBase + "/tools/list", {
      method: "POST",
      headers: auth,
      body: "{}",
    });
    const restListBody = await restList.json();
    if (restList.status !== 200 || restListBody.tenantId !== "acme") {
      console.error("smoke failed REST /tools/list still 200", restList.status, restListBody);
      process.exit(1);
    }

    const delMiss = await fetch(mcpBase + "/mcp", { method: "DELETE" });
    const delMissBody = await delMiss.json();
    if (delMiss.status !== 400 || delMissBody.error !== SESSION_ID_REQUIRED) {
      console.error("smoke failed DELETE /mcp missing session", delMiss.status, delMissBody);
      process.exit(1);
    }

    const delOk = await fetch(mcpBase + "/mcp", {
      method: "DELETE",
      headers: { "mcp-session-id": String(initSession) },
    });
    const delOkText = await delOk.text();
    if (delOk.status !== 204 || delOkText) {
      console.error("smoke failed DELETE /mcp 204", delOk.status, delOkText);
      process.exit(1);
    }

    const sessGone = await fetch(mcpBase + "/admin/sessions", {
      headers: { "x-admin-token": "admin-dev-token" },
    });
    const sessGoneBody = await sessGone.json();
    if (
      sessGone.status !== 200 ||
      sessGoneBody.ok !== true ||
      sessGoneBody.count !== 0 ||
      (sessGoneBody.sessions || []).some((s) => s.id === String(initSession))
    ) {
      console.error("smoke failed GET /admin/sessions after DELETE", sessGone.status, sessGoneBody);
      process.exit(1);
    }

    const afterDel = await fetch(mcpBase + "/mcp", {
      method: "POST",
      headers: { ...auth, "mcp-session-id": String(initSession) },
      body: JSON.stringify({ jsonrpc: "2.0", id: 3, method: "tools/list", params: {} }),
    });
    const afterDelBody = await afterDel.json();
    if (afterDel.status !== 404 || afterDelBody.error !== SESSION_NOT_FOUND) {
      console.error("smoke failed POST after DELETE 404", afterDel.status, afterDelBody);
      process.exit(1);
    }

    const delAgain = await fetch(mcpBase + "/mcp", {
      method: "DELETE",
      headers: { "mcp-session-id": String(initSession) },
    });
    const delAgainBody = await delAgain.json();
    if (delAgain.status !== 404 || delAgainBody.error !== SESSION_NOT_FOUND) {
      console.error("smoke failed DELETE idempotent 404", delAgain.status, delAgainBody);
      process.exit(1);
    }

    const delUnknown = await fetch(mcpBase + "/mcp", {
      method: "DELETE",
      headers: { "mcp-session-id": "never-seen-session-id" },
    });
    const delUnknownBody = await delUnknown.json();
    if (delUnknown.status !== 404 || delUnknownBody.error !== SESSION_NOT_FOUND) {
      console.error("smoke failed DELETE unknown 404", delUnknown.status, delUnknownBody);
      process.exit(1);
    }

    const restAfterDel = await fetch(mcpBase + "/tools/list", {
      method: "POST",
      headers: auth,
      body: "{}",
    });
    const restAfterDelBody = await restAfterDel.json();
    if (restAfterDel.status !== 200 || restAfterDelBody.tenantId !== "acme") {
      console.error("smoke failed REST /tools/list after DELETE", restAfterDel.status, restAfterDelBody);
      process.exit(1);
    }

    const auditRaw = fs.readFileSync(mcpTmp, "utf8");
    if (!auditRaw.includes("session_deleted") || auditRaw.includes(String(initSession))) {
      console.error("smoke failed session_deleted audit", auditRaw);
      process.exit(1);
    }

    // Admin DELETE /admin/sessions/{id} — ops kill; id in path; no Mcp-Session-Id header.
    const initAdmin = await fetch(mcpBase + "/mcp", {
      method: "POST",
      headers: { ...auth, "MCP-Protocol-Version": "2025-03-26" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 10,
        method: "initialize",
        params: { protocolVersion: "2025-03-26", capabilities: {}, clientInfo: { name: "smoke-admin" } },
      }),
    });
    const initAdminBody = await initAdmin.json();
    const adminSid =
      initAdmin.headers.get("mcp-session-id") || initAdminBody?.result?.sessionId || "";
    if (initAdmin.status !== 200 || !isMcpUuid(String(adminSid))) {
      console.error("smoke failed admin-delete initialize", initAdmin.status, initAdminBody);
      process.exit(1);
    }

    const adminDelUnauth = await fetch(mcpBase + "/admin/sessions/" + encodeURIComponent(String(adminSid)), {
      method: "DELETE",
    });
    const adminDelUnauthBody = await adminDelUnauth.json();
    if (adminDelUnauth.status !== 401 || adminDelUnauthBody.error !== "unauthorized_admin") {
      console.error("smoke failed DELETE /admin/sessions/{id} unauth", adminDelUnauth.status, adminDelUnauthBody);
      process.exit(1);
    }
    const adminDelUnauthDump = JSON.stringify(adminDelUnauthBody);
    if (adminDelUnauthDump.includes("ten_acme_mcp") || adminDelUnauthDump.includes("admin-dev-token")) {
      console.error("smoke failed DELETE /admin/sessions/{id} 401 leaked secret");
      process.exit(1);
    }

    const adminDelOk = await fetch(mcpBase + "/admin/sessions/" + encodeURIComponent(String(adminSid)), {
      method: "DELETE",
      headers: { "x-admin-token": "admin-dev-token", "x-request-id": "smoke-admin-del-1" },
    });
    const adminDelOkText = await adminDelOk.text();
    const adminDelOkRid = adminDelOk.headers.get("x-request-id");
    if (adminDelOk.status !== 204 || adminDelOkText || adminDelOkRid !== "smoke-admin-del-1") {
      console.error("smoke failed DELETE /admin/sessions/{id} 204", adminDelOk.status, adminDelOkRid, adminDelOkText);
      process.exit(1);
    }

    const afterAdminDel = await fetch(mcpBase + "/mcp", {
      method: "POST",
      headers: { ...auth, "mcp-session-id": String(adminSid) },
      body: JSON.stringify({ jsonrpc: "2.0", id: 11, method: "tools/list", params: {} }),
    });
    const afterAdminDelBody = await afterAdminDel.json();
    if (afterAdminDel.status !== 404 || afterAdminDelBody.error !== SESSION_NOT_FOUND) {
      console.error("smoke failed POST after admin DELETE 404", afterAdminDel.status, afterAdminDelBody);
      process.exit(1);
    }

    const adminDelAgain = await fetch(mcpBase + "/admin/sessions/" + encodeURIComponent(String(adminSid)), {
      method: "DELETE",
      headers: { "x-admin-token": "admin-dev-token" },
    });
    const adminDelAgainBody = await adminDelAgain.json();
    if (adminDelAgain.status !== 404 || adminDelAgainBody.error !== SESSION_NOT_FOUND) {
      console.error("smoke failed admin DELETE idempotent 404", adminDelAgain.status, adminDelAgainBody);
      process.exit(1);
    }

    const adminDelUnknown = await fetch(mcpBase + "/admin/sessions/never-seen-admin-session", {
      method: "DELETE",
      headers: { "x-admin-token": "admin-dev-token" },
    });
    const adminDelUnknownBody = await adminDelUnknown.json();
    if (adminDelUnknown.status !== 404 || adminDelUnknownBody.error !== SESSION_NOT_FOUND) {
      console.error("smoke failed admin DELETE unknown 404", adminDelUnknown.status, adminDelUnknownBody);
      process.exit(1);
    }

    const adminDelNoId = await fetch(mcpBase + "/admin/sessions", { method: "DELETE", headers: { "x-admin-token": "admin-dev-token" } });
    const adminDelNoIdBody = await adminDelNoId.json();
    if (adminDelNoId.status !== 404) {
      console.error("smoke failed admin DELETE missing id 404", adminDelNoId.status, adminDelNoIdBody);
      process.exit(1);
    }

    const auditAdmin = fs.readFileSync(mcpTmp, "utf8");
    if (!auditAdmin.includes('"via":"admin"') || auditAdmin.includes(String(adminSid))) {
      console.error("smoke failed session_deleted via admin audit", auditAdmin);
      process.exit(1);
    }
  } finally {
    try { await gwMcp.close(); } catch { /* ignore */ }
    try { fs.unlinkSync(mcpTmp); } catch { /* ignore */ }
  }

  const mcpTtlTmp = path.join("/tmp", "b-mcp-ttl-smoke-audit.jsonl");
  try { fs.unlinkSync(mcpTtlTmp); } catch { /* ignore */ }
  let tTtl = 10_000;
  const gwTtl = createServer({
    policy: {
      allow: ["echo"],
      deny: [],
      tenants: [{ id: "acme", apiKey: "ten_acme_ttl" }],
      tools: [{ name: "echo", description: "echo" }],
    },
    auditPath: mcpTtlTmp,
    sessionTtlSec: 1,
    now: () => tTtl,
  });
  await new Promise((resolve, reject) => {
    gwTtl.server.once("error", reject);
    gwTtl.server.listen(0, "127.0.0.1", resolve);
  });
  try {
    const ttlPort = gwTtl.server.address().port;
    const ttlBase = "http://127.0.0.1:" + ttlPort;
    const ttlAuth = { "content-type": "application/json", authorization: "Bearer ten_acme_ttl" };
    const initTtl = await fetch(ttlBase + "/mcp", {
      method: "POST",
      headers: ttlAuth,
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "initialize",
        params: { protocolVersion: "2025-03-26", capabilities: {}, clientInfo: { name: "ttl" } },
      }),
    });
    const initTtlBody = await initTtl.json();
    const ttlSid = initTtl.headers.get("mcp-session-id") || initTtlBody?.result?.sessionId || "";
    if (initTtl.status !== 200 || !ttlSid) {
      console.error("smoke failed ttl initialize", initTtl.status, initTtlBody);
      process.exit(1);
    }
    const liveList = await fetch(ttlBase + "/mcp", {
      method: "POST",
      headers: { ...ttlAuth, "mcp-session-id": ttlSid },
      body: JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} }),
    });
    const liveListBody = await liveList.json();
    if (liveList.status !== 200 || !Array.isArray(liveListBody?.result?.tools)) {
      console.error("smoke failed ttl live session tools/list", liveList.status, liveListBody);
      process.exit(1);
    }
    tTtl += 1000;
    const expList = await fetch(ttlBase + "/mcp", {
      method: "POST",
      headers: { ...ttlAuth, "mcp-session-id": ttlSid },
      body: JSON.stringify({ jsonrpc: "2.0", id: 3, method: "tools/list", params: {} }),
    });
    const expBody = await expList.json();
    if (expList.status !== 404 || expBody.error !== SESSION_EXPIRED) {
      console.error("smoke failed ttl expired 404 session_expired", expList.status, expBody);
      process.exit(1);
    }
    const missList = await fetch(ttlBase + "/mcp", {
      method: "POST",
      headers: ttlAuth,
      body: JSON.stringify({ jsonrpc: "2.0", id: 4, method: "tools/list", params: {} }),
    });
    const missBody = await missList.json();
    if (missList.status !== 200 || !Array.isArray(missBody?.result?.tools)) {
      console.error("smoke failed ttl missing session still 200", missList.status, missBody);
      process.exit(1);
    }
    const restTtl = await fetch(ttlBase + "/tools/list", {
      method: "POST",
      headers: ttlAuth,
      body: "{}",
    });
    const restTtlBody = await restTtl.json();
    if (restTtl.status !== 200 || restTtlBody.tenantId !== "acme") {
      console.error("smoke failed ttl REST /tools/list 200", restTtl.status, restTtlBody);
      process.exit(1);
    }
    const minted = await fetch(ttlBase + "/mcp", {
      method: "POST",
      headers: { ...ttlAuth, "mcp-session-id": "client-minted-ttl-id" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 5, method: "tools/list", params: {} }),
    });
    const mintedBody = await minted.json();
    if (minted.status !== 200 || !Array.isArray(mintedBody?.result?.tools)) {
      console.error("smoke failed ttl unknown id accept", minted.status, mintedBody);
      process.exit(1);
    }
  } finally {
    try { await gwTtl.close(); } catch { /* ignore */ }
    try { fs.unlinkSync(mcpTtlTmp); } catch { /* ignore */ }
  }

  console.log("mcp-gateway " + VERSION + " smoke OK — policy+ratelimit+ipAllowlist+cors+upstreamTimeout+circuitBreaker+ready+requestId+gzipExport+webhook+hmac+timestamp+retry+watch+shutdown+accessLog+adminAuditCsv+adminAuditMd+adminAuditHtml+tokenRotate+streamableHttp+sessionTtl+sessionTerminate+adminSessions+adminSessionDelete+adminConfig+adminGetTenant+adminWebhooks+auditRing");
} else if (cmd === "demo") {
  for (const tool of ["listPets", "deletePet", "createPet"]) {
    const decision = evaluatePolicy(demoPolicy, tool);
    console.log(JSON.stringify(auditEvent(tool, decision, { tenantId: "demo" })));
  }
} else if (cmd === "serve") {
  const { port, host, config, audit, watch, drainMs, logJson, rotateGraceSec, auditMax, sessionTtl } = parseServeArgs(process.argv.slice(3));
  const { policy, abs } = loadConfig(config);
  const logJsonEnabled = resolveLogJson(logJson);
  const { server, auditPath, reloadPolicyAndUpstream, ready, getUpstreamState, close, beginShutdown } =
    createServer({
      policy,
      configPath: abs,
      auditPath: path.resolve(audit),
      logJson: logJsonEnabled,
      rotateGraceSec,
      auditMaxEvents: auditMax,
      sessionTtlSec: sessionTtl,
    });
  let shuttingDown = false;
  let watchTimer = null;
  async function shutdown() {
    if (shuttingDown) return;
    shuttingDown = true;
    beginShutdown();
    console.log("shutting down");
    if (watchTimer) {
      clearInterval(watchTimer);
      watchTimer = null;
    }
    const ms = resolveDrainMs(drainMs);
    await new Promise((r) => setTimeout(r, ms));
    try { await close(); } catch { /* ignore */ }
    console.log("exit");
    process.exit(0);
  }
  process.on("SIGINT", () => { shutdown(); });
  process.on("SIGTERM", () => { shutdown(); });
  process.on("SIGHUP", () => {
    reloadPolicyAndUpstream()
      .then((p) => {
        const up = getUpstreamState();
        console.log(
          "SIGHUP reloaded policy tenants=" +
            (Array.isArray(p.tenants) ? p.tenants.map((t) => t.id).join(",") : "") +
            " upstreamTools=" +
            (up.tools || []).map((t) => t.name).join(",")
        );
      })
      .catch((err) => {
        console.error("SIGHUP reload failed:", err?.message || err);
      });
  });
  Promise.resolve(ready)
    .catch(() => {})
    .then(() => {
      server.listen(port, host, () => {
        const up = getUpstreamState();
        console.log("mcp-gateway listening on http://" + host + ":" + port);
        console.log("config=" + abs);
        console.log("audit=" + auditPath);
        console.log("auditMax=" + resolveAuditMaxEvents(auditMax));
        console.log("sessionTtl=" + resolveSessionTtlSec(sessionTtl));
        if (policy.upstream) {
          console.log(
            "upstream type=" +
              (policy.upstream.type || "http") +
              " connected=" +
              Boolean(up.connected) +
              " tools=" +
              (up.tools || []).map((t) => t.name).join(",")
          );
          if (up.error) console.log("upstream_error=" + up.error);
        }
        console.log("watch=" + (watch ? "poll " + WATCH_POLL_MS + "ms" : "off"));
        console.log("logJson=" + (logJsonEnabled ? "on" : "off"));
        if (watch) {
          watchTimer = startPolicyWatch(abs, {
            reload: reloadPolicyAndUpstream,
            getUpstreamState,
          });
        }
      });
    });
} else if (cmd === "export-audit") {
  const args = parseExportArgs(process.argv.slice(3));
  let format;
  try {
    format = normalizeExportFormat(args.format);
  } catch {
    console.error("unsupported --format (use json|csv|md|html)");
    process.exit(1);
  }
  if (!args.out && format !== "html") {
    console.error("export-audit requires --out <path>");
    process.exit(1);
  }
  let policy = {};
  let configAbs = null;
  try {
    const loaded = loadConfig(args.config);
    policy = loaded.policy;
    configAbs = loaded.abs;
  } catch (err) {
    // offline: config optional if --audit provided
    if (!args.audit) {
      console.error("export-audit: cannot read --config and no --audit given:", err?.message || err);
      process.exit(1);
    }
  }
  const auditPath = resolveAuditPath({
    audit: args.audit,
    configPath: configAbs,
    policy,
    cwd: process.cwd(),
  });
  let events;
  try {
    events = readAuditEvents(auditPath, {
      tenant: args.tenant || undefined,
      tool: args.tool || undefined,
      limit: args.limit || undefined,
      since: args.since || undefined,
      until: args.until || undefined,
    });
  } catch (err) {
    if (err?.code === "invalid_since" || err?.message === "invalid_since") {
      console.error("export-audit: invalid --since (use ISO-8601 timestamp)");
      process.exit(1);
    }
    if (err?.code === "invalid_until" || err?.message === "invalid_until") {
      console.error("export-audit: invalid --until (use ISO-8601 timestamp)");
      process.exit(1);
    }
    throw err;
  }
  const doRedact = resolveRedact({ flag: args.redact, policy });
  if (doRedact) events = redactEvents(events);
  const body =
    format === "csv"
      ? eventsToCsv(events)
      : format === "md"
        ? eventsToAdminMd(events)
        : format === "html"
          ? eventsToAdminHtml(events)
          : eventsToJsonPack(events, {
              tenant: args.tenant || null,
              tool: args.tool || null,
              since: args.since || null,
              until: args.until || null,
              redacted: doRedact,
              source: "mcp-gateway-cli",
              auditPath,
            });
  const doGzip = format === "html" ? false : Boolean(args.gzip);
  if (format === "html" && !args.out) {
    const text = typeof body === "string" ? body : String(body);
    process.stdout.write(text.endsWith("\n") ? text : text + "\n");
  } else {
    const written = writeExportFile(args.out, body, format, { gzip: doGzip });
    console.log(
      JSON.stringify({
        ok: true,
        format,
        count: events.length,
        redacted: doRedact,
        gzip: doGzip,
        auditPath,
        out: written,
      })
    );
  }
} else {
  printHelp();
}
