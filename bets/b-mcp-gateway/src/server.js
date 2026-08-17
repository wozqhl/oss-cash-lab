/** Minimal HTTP MCP gateway: health / ready / tools.list / tools.call / audit(+export) / admin reload+tenants+get-tenant+rotate+sessions+config+webhooks+session-delete / openapi / metrics */
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  evaluatePolicy,
  effectivePolicy,
  findTenantByApiKey,
  tenantsEnabled,
  TenantRateLimiters,
  auditEvent,
  resolveMaxBodyBytes,
  DEFAULT_MAX_BODY_BYTES,
  summarizeTenantsForAdmin,
  summarizeTenantForAdmin,
  rotateTenantApiKey,
  tokenRotatedAuditEvent,
  matchAdminRotatePath,
  matchAdminGetTenantPath,
  resolveRotateGraceSec,
} from "./policy.js";
import {
  callBuiltin,
  createUpstreamFromConfig,
  shouldProxyToUpstream,
  isUpstreamTimeoutError,
  isUpstreamFailure,
} from "./upstream.js";
import { createCircuitBreaker, resolveBreakerConfig } from "./breaker.js";
import {
  filterAuditEvents,
  eventsToCsv,
  eventsToAdminCsv,
  eventsToAdminMd,
  eventsToAdminHtml,
  eventsToJsonPack,
  normalizeExportFormat,
  resolveRedact,
  resolveRedactOnWrite,
  redactEvent,
  redactEvents,
  gzipBytes,
  gzipFilename,
  wantsGzip,
  pushAuditEvent,
  loadAuditRing,
  resolveAuditMaxEvents,
} from "./audit-export.js";
import { fanOutWebhooks } from "./webhooks.js";
import { createMetrics } from "./metrics.js";
import { checkTenantIpAllowlist } from "./ip-allowlist.js";
import { corsResponseHeaders, handlePreflight } from "./cors.js";
import { resolveRequestId, REQUEST_ID_HEADER } from "./request-id.js";
import { attachAccessLog } from "./access-log.js";
import {
  MCP_PROTOCOL_VERSION,
  isMcpStreamablePath,
  isMcpJsonRpcPostPath,
  resolveProtocolVersion,
  resolveSessionId,
  mcpResponseHeaders,
  rpcResult,
  rpcError,
  isJsonRpcNotification,
  initializeResult,
  createSessionStore,
  resolveSessionTtlSec,
  DEFAULT_SESSION_MAX_IDS,
  SESSION_EXPIRED,
  SESSION_NOT_FOUND,
  SESSION_ID_REQUIRED,
  MCP_ALLOW_METHODS,
  matchAdminSessionPath,
} from "./mcp-http.js";
import { summarizeConfigForAdmin, summarizeWebhooksForAdmin } from "./admin-config.js";
import {
  resolvePayloadRedact,
  resolveUpstreamRedact,
  redactAuditEvent,
  redactToolArgs,
} from "./redact.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_OPENAPI_PATH = path.resolve(__dirname, "../openapi/gateway.openapi.json");

function sendJson(res, status, body, extraHeaders = {}) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(payload),
    ...extraHeaders,
  });
  res.end(payload);
}

function payloadTooLargeError() {
  const err = new Error("payload_too_large");
  err.code = "payload_too_large";
  return err;
}

/**
 * Stream/count request body bytes; reject before JSON.parse when over maxBytes.
 * Honors Content-Length early when present; also enforces on chunked transfers.
 */
function readBody(req, maxBytes = DEFAULT_MAX_BODY_BYTES) {
  return new Promise((resolve, reject) => {
    const limit =
      typeof maxBytes === "number" && Number.isFinite(maxBytes) && maxBytes > 0
        ? Math.floor(maxBytes)
        : DEFAULT_MAX_BODY_BYTES;

    const clRaw = req.headers["content-length"];
    if (clRaw != null && clRaw !== "") {
      const cl = Number(Array.isArray(clRaw) ? clRaw[0] : clRaw);
      if (Number.isFinite(cl) && cl > limit) {
        req.resume();
        return reject(payloadTooLargeError());
      }
    }

    const chunks = [];
    let size = 0;
    let settled = false;

    const failTooLarge = () => {
      if (settled) return;
      settled = true;
      req.removeListener("data", onData);
      req.removeListener("end", onEnd);
      req.removeListener("error", onError);
      req.resume();
      reject(payloadTooLargeError());
    };

    const onData = (c) => {
      size += c.length;
      if (size > limit) {
        failTooLarge();
        return;
      }
      chunks.push(c);
    };
    const onEnd = () => {
      if (settled) return;
      settled = true;
      const raw = Buffer.concat(chunks).toString("utf8");
      if (!raw) return resolve({});
      try {
        resolve(JSON.parse(raw));
      } catch (err) {
        reject(err);
      }
    };
    const onError = (err) => {
      if (settled) return;
      settled = true;
      reject(err);
    };

    req.on("data", onData);
    req.on("end", onEnd);
    req.on("error", onError);
  });
}

function appendAudit(auditPath, event, policy, metrics, opts = {}) {
  let toWrite = event;
  // In-payload PII/secret redaction (default on). Clone — do not mutate the live event.
  if (resolvePayloadRedact(policy)) {
    toWrite = redactAuditEvent(toWrite, policy);
  }
  if (resolveRedactOnWrite(policy)) {
    toWrite = redactEvent(toWrite);
  }
  // Ring buffer first: cap retained history only. Webhook fan-out still sees every new event.
  if (Array.isArray(opts.events)) {
    pushAuditEvent(opts.events, toWrite, opts.maxEvents);
    if (metrics && typeof metrics.setAuditEvents === "function") {
      metrics.setAuditEvents(opts.events.length);
    }
  }
  fs.mkdirSync(path.dirname(auditPath), { recursive: true });
  fs.appendFileSync(auditPath, JSON.stringify(toWrite) + "\n", "utf8");
  // Fire-and-forget webhook fan-out from the original event (redact decided separately).
  // token_rotated is not a tool_call/deny — skip so we never POST secrets by accident.
  if (!opts.skipWebhooks) {
    fanOutWebhooks(policy, event, { metrics });
  }
}

function extractApiKey(req) {
  const auth = req.headers.authorization || "";
  if (typeof auth === "string" && auth.toLowerCase().startsWith("bearer ")) {
    return auth.slice(7).trim();
  }
  const x = req.headers["x-api-key"];
  if (!x) return null;
  return Array.isArray(x) ? String(x[0]) : String(x);
}

function extractAdminToken(req) {
  const x = req.headers["x-admin-token"];
  if (x) return Array.isArray(x) ? String(x[0]) : String(x);
  const auth = req.headers.authorization || "";
  if (typeof auth === "string" && auth.toLowerCase().startsWith("bearer ")) {
    return auth.slice(7).trim();
  }
  return null;
}

function mergeToolCatalog(localTools, upstreamTools) {
  const byName = new Map();
  for (const t of localTools || []) {
    if (t && t.name) byName.set(t.name, { ...t, source: t.source || "local" });
  }
  for (const t of upstreamTools || []) {
    if (t && t.name) {
      byName.set(t.name, { ...t, source: "upstream" });
    }
  }
  return Array.from(byName.values());
}

/** Poll interval for `serve --watch` (config file mtime). */
export const WATCH_POLL_MS = 300;

/** SIGTERM/SIGINT HTTP drain window (k8s/Compose). Cap 30s. */
export const DEFAULT_SHUTDOWN_DRAIN_MS = 5000;
export const MAX_SHUTDOWN_DRAIN_MS = 30000;

/** Resolve drain window: CLI/raw, else env SHUTDOWN_DRAIN_MS, else 5s. Cap 30s. */
export function resolveDrainMs(raw, env = process.env) {
  const source = raw == null || raw === "" ? env?.SHUTDOWN_DRAIN_MS : raw;
  const n = Number(source);
  if (!Number.isFinite(n) || n < 0) return DEFAULT_SHUTDOWN_DRAIN_MS;
  return Math.min(MAX_SHUTDOWN_DRAIN_MS, Math.floor(n));
}

/** Line-buffered-ish stdout for --watch (redirected logs must appear promptly). */
export function watchLog(line) {
  const s = String(line).endsWith("\n") ? String(line) : `${line}\n`;
  try {
    fs.writeSync(1, s);
  } catch {
    console.log(String(line).replace(/\n$/, ""));
  }
}

/**
 * Poll config file mtime and reload policy (same path as SIGHUP / POST /admin/reload).
 * Parse/reload errors keep the previous policy; mtime advances only after a successful reload.
 * Returns the interval handle (clear with clearInterval).
 */
export function startPolicyWatch(
  configPath,
  { reload, pollMs = WATCH_POLL_MS, log = watchLog, getUpstreamState } = {}
) {
  if (typeof reload !== "function") {
    throw new Error("startPolicyWatch requires reload()");
  }
  const abs = path.resolve(configPath);
  let lastMtimeMs;
  try {
    lastMtimeMs = fs.statSync(abs).mtimeMs;
  } catch (err) {
    console.error(`watch: cannot stat ${abs}: ${err.message || err}`);
    process.exit(1);
  }
  log(`watching ${abs} (poll ${pollMs}ms)`);
  let busy = false;
  return setInterval(() => {
    if (busy) return;
    let st;
    try {
      st = fs.statSync(abs);
      if (!(st.mtimeMs > lastMtimeMs)) return;
    } catch (err) {
      console.error(`watch: cannot stat ${abs}: ${err.message || err}`);
      return;
    }
    busy = true;
    Promise.resolve()
      .then(() => reload())
      .then((policy) => {
        lastMtimeMs = st.mtimeMs;
        const up = typeof getUpstreamState === "function" ? getUpstreamState() : {};
        const tools = Array.isArray(up.tools) ? up.tools : [];
        log(
          `regenerated ${JSON.stringify({
            tenants: Array.isArray(policy?.tenants) ? policy.tenants.map((t) => t.id) : [],
            allow: policy?.allow || [],
            deny: policy?.deny || [],
            upstreamTools: tools.map((t) => t.name),
          })}`
        );
      })
      .catch((err) => {
        console.error(`watch regenerate error: ${err.message || err}`);
      })
      .finally(() => {
        busy = false;
      });
  }, pollMs);
}

export function createServer(options = {}) {
  const auditMaxEvents = resolveAuditMaxEvents(options.auditMaxEvents);
  const auditPath = options.auditPath || path.resolve("./data/audit.jsonl");
  const state = {
    policy: options.policy || { allow: [], deny: [], tools: [] },
    configPath: options.configPath || null,
    auditPath,
    auditMaxEvents,
    auditEvents: loadAuditRing(auditPath, auditMaxEvents),
    upstream: null,
    upstreamTools: [],
    upstreamToolNames: new Set(),
    upstreamError: null,
    breaker: createCircuitBreaker(resolveBreakerConfig(options.policy?.upstream)),
    shuttingDown: false,
    rotateGraceSec: resolveRotateGraceSec(options.rotateGraceSec),
    sessionTtlSec: resolveSessionTtlSec(options.sessionTtlSec),
    sessionCap:
      typeof options.sessionMaxIds === "number" &&
      Number.isFinite(options.sessionMaxIds) &&
      options.sessionMaxIds >= 0
        ? Math.floor(options.sessionMaxIds)
        : DEFAULT_SESSION_MAX_IDS,
  };
  const nowFn = typeof options.now === "function" ? options.now : () => Date.now();
  const sessions =
    options.sessions ||
    createSessionStore({
      ttlSec: state.sessionTtlSec,
      maxIds: options.sessionMaxIds,
      now: nowFn,
    });
  const limiters = new TenantRateLimiters();
  const metrics = createMetrics();
  metrics.setAuditEvents(state.auditEvents.length);

  function recordAudit(event, extra = {}) {
    appendAudit(state.auditPath, event, state.policy, metrics, {
      events: state.auditEvents,
      maxEvents: state.auditMaxEvents,
      ...extra,
    });
  }
  const openapiPath = options.openapiPath || DEFAULT_OPENAPI_PATH;
  const logJson = Boolean(options.logJson);

  function respondJson(res, status, body, metricPath, extraHeaders = {}) {
    metrics.incHttpRequest({ path: metricPath, status });
    sendJson(res, status, body, extraHeaders);
  }

  function respondText(res, status, body, contentType, metricPath) {
    metrics.incHttpRequest({ path: metricPath, status });
    const payload = typeof body === "string" ? body : String(body);
    res.writeHead(status, {
      "content-type": contentType,
      "content-length": Buffer.byteLength(payload),
    });
    res.end(payload);
  }

  async function connectUpstream(policy) {
    if (state.upstream && typeof state.upstream.close === "function") {
      try {
        await state.upstream.close();
      } catch {
        /* ignore */
      }
    }
    state.upstream = null;
    state.upstreamTools = [];
    state.upstreamToolNames = new Set();
    state.upstreamError = null;
    state.breaker = createCircuitBreaker(resolveBreakerConfig(policy?.upstream));
    if (!policy?.upstream) return;
    try {
      const client = createUpstreamFromConfig(policy.upstream);
      if (!client) return;
      state.upstream = client;
      const tools = await client.listTools();
      state.upstreamTools = tools;
      state.upstreamToolNames = new Set(tools.map((t) => t.name));
    } catch (err) {
      state.upstreamError = String(err?.message || err);
      state.upstream = null;
      state.upstreamTools = [];
      state.upstreamToolNames = new Set();
    }
  }

  function reloadPolicy() {
    if (!state.configPath) {
      throw new Error("no_config_path");
    }
    const raw = fs.readFileSync(state.configPath, "utf8");
    state.policy = JSON.parse(raw);
    limiters.clear();
    return state.policy;
  }

  async function reloadPolicyAndUpstream() {
    const policy = reloadPolicy();
    await connectUpstream(policy);
    return policy;
  }

  function resolveTenant(req) {
    if (!tenantsEnabled(state.policy)) {
      return { tenant: null, error: null };
    }
    const key = extractApiKey(req);
    if (!key) {
      return {
        tenant: null,
        error: { status: 401, body: { error: "missing_api_key" } },
      };
    }
    const tenant = findTenantByApiKey(state.policy, key);
    if (!tenant) {
      return {
        tenant: null,
        error: { status: 401, body: { error: "unknown_api_key" } },
      };
    }
    const ipErr = checkTenantIpAllowlist(req, tenant);
    if (ipErr) {
      metrics.incIpDenied();
      return { tenant: null, error: ipErr };
    }
    return { tenant, error: null };
  }

  function isAdmin(req) {
    const token = state.policy.adminToken;
    if (!token) return false;
    return extractAdminToken(req) === token;
  }

  async function listToolsForTenant(tenant) {
    const pol = effectivePolicy(state.policy, tenant);
    const decisionAllow = (name) => evaluatePolicy(pol, name).allow;
    const localCatalog = Array.isArray(state.policy.tools) ? state.policy.tools : [];
    if (state.upstream && !state.shuttingDown) {
      try {
        const tools = await state.upstream.listTools();
        state.upstreamTools = tools;
        state.upstreamToolNames = new Set(tools.map((t) => t.name));
        state.upstreamError = null;
      } catch (err) {
        state.upstreamError = String(err?.message || err);
      }
    }
    const catalog = mergeToolCatalog(localCatalog, state.upstreamTools);
    const tools = catalog.filter((t) => decisionAllow(t.name));
    return {
      tools,
      tenantId: tenant?.id || null,
      upstreamConnected: Boolean(state.upstream),
    };
  }

  async function executeToolCall({ tenant, name, args, requestId }) {
    const pol = effectivePolicy(state.policy, tenant);
    const tenantId = tenant?.id || null;
    const decision = evaluatePolicy(pol, name);
    if (!decision.allow) {
      metrics.incToolCall({
        tool: name,
        decision: "deny",
        tenant: tenantId,
      });
      const event = auditEvent(name, decision, {
        arguments: args,
        result: null,
        tenantId,
        requestId,
      });
      recordAudit(event);
      return {
        status: 403,
        body: { error: "denied", reason: decision.reason, tool: name, tenantId },
        extraHeaders: {},
      };
    }

    const limit = pol.rateLimitPerMinute ?? 60;
    const limiter = limiters.get(tenantId, limit);
    if (!limiter.check()) {
      metrics.incToolCall({
        tool: name,
        decision: "rate_limit",
        tenant: tenantId,
      });
      metrics.incRateLimited();
      const rateDecision = { allow: false, reason: "rate-limit" };
      const event = auditEvent(name, rateDecision, {
        arguments: args,
        result: null,
        tenantId,
        requestId,
      });
      recordAudit(event);
      return {
        status: 429,
        body: { error: "rate_limited", tool: name, tenantId },
        extraHeaders: {},
      };
    }

    let result;
    let via = "builtin";
    if (state.upstream && shouldProxyToUpstream(name, state.upstreamToolNames)) {
      via = "upstream";
      if (state.shuttingDown) {
        return {
          status: 503,
          body: { error: "shutting_down", tool: name, tenantId },
          extraHeaders: {},
        };
      }
      if (!state.breaker.allow()) {
        metrics.incToolCall({
          tool: name,
          decision: "circuit_open",
          tenant: tenantId,
        });
        metrics.incCircuitOpen();
        const circuitDecision = { allow: false, reason: "circuit_open" };
        const event = auditEvent(name, circuitDecision, {
          arguments: args,
          result: null,
          tenantId,
          via,
          requestId,
        });
        recordAudit(event);
        const retryAfter = Math.max(
          1,
          typeof state.breaker.retryAfterSeconds === "function"
            ? state.breaker.retryAfterSeconds()
            : 1
        );
        return {
          status: 503,
          body: { error: "circuit_open", tool: name, tenantId },
          extraHeaders: { "Retry-After": String(retryAfter) },
        };
      }
      try {
        const callArgs = resolveUpstreamRedact(state.policy)
          ? redactToolArgs(args, state.policy)
          : args;
        result = await state.upstream.callTool(name, callArgs);
        if (isUpstreamFailure(result)) {
          state.breaker.recordFailure();
        } else {
          state.breaker.recordSuccess();
        }
      } catch (err) {
        state.breaker.recordFailure();
        if (isUpstreamTimeoutError(err)) {
          metrics.incToolCall({
            tool: name,
            decision: "timeout",
            tenant: tenantId,
          });
          metrics.incUpstreamTimeout();
          const timeoutDecision = { allow: false, reason: "upstream_timeout" };
          const event = auditEvent(name, timeoutDecision, {
            arguments: args,
            result: null,
            tenantId,
            via,
            requestId,
          });
          recordAudit(event);
          return {
            status: 504,
            body: { error: "upstream_timeout", tool: name, tenantId },
            extraHeaders: {},
          };
        }
        throw err;
      }
    } else {
      result = await callBuiltin(name, args);
    }
    metrics.incToolCall({
      tool: name,
      decision: "allow",
      tenant: tenantId,
    });
    const event = auditEvent(name, decision, {
      arguments: args,
      result,
      tenantId,
      via,
      requestId,
    });
    recordAudit(event);
    return {
      status: 200,
      body: { ok: true, tool: name, result, tenantId, via },
      extraHeaders: {},
    };
  }

  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);
    const method = (req.method || "GET").toUpperCase();
    const requestId = resolveRequestId(req);
    // Always set so implicit writeHead still echoes X-Request-Id.
    res.setHeader(REQUEST_ID_HEADER, requestId);
    attachAccessLog(req, res, {
      enabled: logJson,
      service: "mcp-gateway",
      requestId,
      pathName: url.pathname,
    });

    // Inject ACAO (and expose headers) when Origin matches policy.cors.
    // Disallowed / disabled CORS → no extra headers. Explicit writeHead ACAO (preflight) wins.
    // X-Request-Id is always last so the resolved id is echoed on every response.
    const origWriteHead = res.writeHead.bind(res);
    res.writeHead = (statusCode, a, b) => {
      let reason;
      let headers;
      if (typeof a === "string") {
        reason = a;
        headers = b;
      } else {
        headers = a;
      }
      const cors = corsResponseHeaders(req, state.policy);
      const rid = { [REQUEST_ID_HEADER]: requestId };
      let merged;
      if (headers && typeof headers === "object" && !Array.isArray(headers)) {
        merged = { ...cors, ...headers, ...rid };
      } else {
        merged = { ...cors, ...rid };
      }
      if (reason !== undefined) return origWriteHead(statusCode, reason, merged);
      return origWriteHead(statusCode, merged);
    };

    try {
      if (method === "OPTIONS") {
        const pf = handlePreflight(req, state.policy);
        if (!pf) {
          return respondJson(res, 404, { error: "not_found", path: url.pathname }, url.pathname);
        }
        metrics.incHttpRequest({ path: url.pathname, status: pf.status });
        if (pf.status === 204) {
          res.writeHead(204, pf.headers);
          return res.end();
        }
        return sendJson(res, pf.status, pf.body, pf.headers);
      }

      if (method === "GET" && url.pathname === "/health") {
        const breakerSnap =
          typeof state.breaker.healthSnapshot === "function"
            ? state.breaker.healthSnapshot()
            : null;
        return respondJson(res, 200, {
          ok: true,
          service: "mcp-gateway",
          version: "0.1.0",
          tenants: tenantsEnabled(state.policy)
            ? state.policy.tenants.map((t) => t.id)
            : [],
          upstream: state.policy.upstream
            ? {
                type: state.policy.upstream.type || "http",
                connected: Boolean(state.upstream),
                tools: state.upstreamTools.map((t) => t.name),
                error: state.upstreamError,
              }
            : null,
          // Only when breaker is enabled — omit so stack-demo /health ok:true stays unchanged.
          ...(breakerSnap ? { breaker: breakerSnap } : {}),
          // Only while draining SIGTERM/SIGINT — omit otherwise (stack-demo /health unchanged).
          ...(state.shuttingDown ? { shuttingDown: true } : {}),
        }, "/health");
      }

      if (method === "GET" && url.pathname === "/ready") {
        // Shutdown 503 wins over healthy 200 and over circuit_open.
        if (state.shuttingDown) {
          return respondJson(res, 503, { ok: false, reason: "shutting_down" }, "/ready");
        }
        const ready =
          typeof state.breaker.readyPayload === "function"
            ? state.breaker.readyPayload()
            : { status: 200, body: { ok: true } };
        const extra = {};
        if (
          ready.status === 503 &&
          typeof state.breaker.retryAfterSeconds === "function"
        ) {
          extra["Retry-After"] = String(Math.max(1, state.breaker.retryAfterSeconds()));
        }
        return respondJson(res, ready.status, ready.body, "/ready", extra);
      }

      if (method === "GET" && url.pathname === "/openapi.json") {
        try {
          const raw = fs.readFileSync(openapiPath, "utf8");
          // validate JSON so we never serve corrupt bytes as 200
          JSON.parse(raw);
          return respondText(
            res,
            200,
            raw,
            "application/json; charset=utf-8",
            "/openapi.json"
          );
        } catch (err) {
          return respondJson(
            res,
            500,
            { error: "openapi_unavailable", message: String(err?.message || err) },
            "/openapi.json"
          );
        }
      }

      if (method === "GET" && url.pathname === "/metrics") {
        return respondText(
          res,
          200,
          metrics.render(),
          "text/plain; version=0.0.4; charset=utf-8",
          "/metrics"
        );
      }

      if (method === "POST" && url.pathname === "/admin/reload") {
        if (!isAdmin(req)) {
          return respondJson(res, 401, { error: "unauthorized_admin" }, "/admin/reload");
        }
        const policy = await reloadPolicyAndUpstream();
        return respondJson(res, 200, {
          ok: true,
          reloaded: true,
          tenants: Array.isArray(policy.tenants)
            ? policy.tenants.map((t) => t.id)
            : [],
          allow: policy.allow || [],
          deny: policy.deny || [],
          upstreamTools: state.upstreamTools.map((t) => t.name),
          upstreamError: state.upstreamError,
        }, "/admin/reload");
      }

      if (method === "GET" && url.pathname === "/admin/tenants") {
        if (!isAdmin(req)) {
          return respondJson(res, 401, { error: "unauthorized_admin" }, "/admin/tenants");
        }
        // Never include raw apiKey — summarizeTenantsForAdmin masks last 4 only.
        return respondJson(res, 200, {
          ok: true,
          tenants: summarizeTenantsForAdmin(state.policy),
        }, "/admin/tenants");
      }

      // Admin single-tenant GET (no secrets). Complements list + rotate.
      if (method === "GET") {
        const getTenant = matchAdminGetTenantPath(url.pathname);
        if (getTenant) {
          const metricPath = "/admin/tenants/{id}";
          if (!isAdmin(req)) {
            return respondJson(res, 401, { error: "unauthorized_admin" }, metricPath);
          }
          const summary = summarizeTenantForAdmin(state.policy, getTenant.tenantId);
          if (!summary.ok) {
            return respondJson(res, 404, { error: "tenant_not_found" }, metricPath);
          }
          return respondJson(res, 200, summary, metricPath);
        }
      }

      // Admin in-memory Streamable HTTP session inventory (no secrets / keys / headers).
      // Tombstones omitted. Array capped at 100 newest-by-lastSeen; `count` is the full live size.
      if (method === "GET" && url.pathname === "/admin/sessions") {
        if (!isAdmin(req)) {
          return respondJson(res, 401, { error: "unauthorized_admin" }, "/admin/sessions");
        }
        const inv = typeof sessions.list === "function" ? sessions.list() : {
          ok: true,
          ttlSec: state.sessionTtlSec,
          cap: 0,
          count: 0,
          sessions: [],
          dropped: 0,
        };
        const body = {
          ok: true,
          ttlSec: state.sessionTtlSec,
          cap: inv.cap,
          count: inv.count,
          sessions: Array.isArray(inv.sessions) ? inv.sessions : [],
        };
        if (inv.truncated) body.truncated = true;
        if (inv.dropped != null) body.dropped = inv.dropped;
        return respondJson(res, 200, body, "/admin/sessions");
      }

      // Admin redacted runtime config (TTL / CORS / breaker / rate-limit / session cap). Never secrets.
      if (method === "GET" && url.pathname === "/admin/config") {
        if (!isAdmin(req)) {
          return respondJson(res, 401, { error: "unauthorized_admin" }, "/admin/config");
        }
        const inv = typeof sessions.list === "function" ? sessions.list() : null;
        const sessionCap =
          inv && Number.isFinite(inv.cap) ? inv.cap : state.sessionCap;
        return respondJson(
          res,
          200,
          summarizeConfigForAdmin({
            policy: state.policy,
            sessionTtlSec: state.sessionTtlSec,
            sessionCap,
            auditMax: state.auditMaxEvents,
            rotateGraceSec: state.rotateGraceSec,
            breaker: state.breaker,
          }),
          "/admin/config"
        );
      }


      // Admin redacted webhook inventory (ids + events + hasUrl/hasSecret). Never urls/secrets.
      if (method === "GET" && url.pathname === "/admin/webhooks") {
        if (!isAdmin(req)) {
          return respondJson(res, 401, { error: "unauthorized_admin" }, "/admin/webhooks");
        }
        return respondJson(res, 200, summarizeWebhooksForAdmin(state.policy), "/admin/webhooks");
      }

      // Admin force-drop a Streamable HTTP session (ops kill). Id is in the path;
      // does not require Mcp-Session-Id. Client DELETE /mcp stays the capability path.
      if (method === "DELETE") {
        const dropMatch = matchAdminSessionPath(url.pathname);
        if (dropMatch) {
          const metricPath = "/admin/sessions/{id}";
          if (!isAdmin(req)) {
            return respondJson(res, 401, { error: "unauthorized_admin" }, metricPath);
          }
          const dropped = sessions.drop(dropMatch.sessionId);
          if (dropped !== "ok") {
            return respondJson(res, 404, { error: SESSION_NOT_FOUND }, metricPath);
          }
          recordAudit(
            {
              ts: new Date(nowFn()).toISOString(),
              type: "session_deleted",
              via: "admin",
              requestId,
            },
            { skipWebhooks: true }
          );
          metrics.incHttpRequest({ path: metricPath, status: 204 });
          res.writeHead(204, { "content-length": 0 });
          return res.end();
        }
      }

      // Admin tenant API token rotation (path or body). Same admin auth as GET /admin/tenants.
      if (method === "POST") {
        const rotateMatch = matchAdminRotatePath(url.pathname);
        if (rotateMatch) {
          const metricPath =
            rotateMatch.kind === "body"
              ? "/admin/tenants/rotate"
              : "/admin/tenants/{id}/rotate";
          if (!isAdmin(req)) {
            return respondJson(res, 401, { error: "unauthorized_admin" }, metricPath);
          }
          let tenantId = rotateMatch.tenantId;
          if (rotateMatch.kind === "body") {
            let body = {};
            try {
              body = await readBody(req, DEFAULT_MAX_BODY_BYTES);
            } catch (err) {
              if (err?.code === "payload_too_large" || err?.message === "payload_too_large") {
                return respondJson(res, 413, { error: "payload_too_large" }, metricPath);
              }
              throw err;
            }
            tenantId = body?.tenantId ?? body?.id ?? "";
          }
          const result = rotateTenantApiKey(state.policy, tenantId, {
            graceSec: state.rotateGraceSec,
          });
          if (!result.ok) {
            return respondJson(res, 404, { error: "unknown_tenant" }, metricPath);
          }
          if (state.configPath) {
            try {
              fs.writeFileSync(
                state.configPath,
                JSON.stringify(state.policy, null, 2) + "\n",
                "utf8"
              );
            } catch {
              /* in-memory rotation still holds until reload */
            }
          }
          const event = tokenRotatedAuditEvent({
            tenantId: result.tenantId,
            requestId,
            previousTokenExpiresAt: result.previousTokenExpiresAt,
          });
          recordAudit(event, { skipWebhooks: true });
          const payload = {
            ok: true,
            tenantId: result.tenantId,
            token: result.token,
          };
          if (result.previousTokenExpiresAt) {
            payload.previousTokenExpiresAt = result.previousTokenExpiresAt;
          }
          return respondJson(res, 200, payload, metricPath);
        }
      }

      // Admin SIEM CSV/JSON/Markdown/HTML: /admin/audit.csv, /admin/audit.md, /admin/audit.html, /admin/audit?format=
      // Admin token only (not tenant API key). Gzip JSON stays on /audit/export.
      if (
        method === "GET" &&
        (url.pathname === "/admin/audit.csv" ||
          url.pathname === "/admin/audit.md" ||
          url.pathname === "/admin/audit.html" ||
          url.pathname === "/admin/audit")
      ) {
        const metricPath = url.pathname;
        if (!isAdmin(req)) {
          return respondJson(res, 401, { error: "unauthorized_admin" }, metricPath);
        }
        let format;
        if (url.pathname === "/admin/audit.csv") {
          format = "csv";
        } else if (url.pathname === "/admin/audit.md") {
          format = "md";
        } else if (url.pathname === "/admin/audit.html") {
          format = "html";
        } else {
          try {
            format = normalizeExportFormat(url.searchParams.get("format") || "json");
          } catch {
            return respondJson(
              res,
              400,
              { error: "unsupported_format", allowed: ["json", "csv", "md", "html"] },
              metricPath
            );
          }
        }
        const qTenant = url.searchParams.get("tenant") || "";
        const qTool = url.searchParams.get("tool") || "";
        const qLimit = url.searchParams.get("limit") || "";
        const qSince = url.searchParams.get("since") || "";
        const qUntil = url.searchParams.get("until") || "";
        const qRedact = url.searchParams.get("redact");
        let events;
        try {
          events = filterAuditEvents(state.auditEvents, {
            tenant: qTenant || undefined,
            tool: qTool || undefined,
            limit: qLimit || undefined,
            since: qSince || undefined,
            until: qUntil || undefined,
          });
        } catch (err) {
          if (err?.code === "invalid_since" || err?.message === "invalid_since") {
            return respondJson(res, 400, { error: "invalid_since", hint: "use ISO-8601 timestamp" }, metricPath);
          }
          if (err?.code === "invalid_until" || err?.message === "invalid_until") {
            return respondJson(res, 400, { error: "invalid_until", hint: "use ISO-8601 timestamp" }, metricPath);
          }
          throw err;
        }
        if (format === "csv") {
          // Always SIEM-safe columns — never arguments/result/tokens, even if redact=0.
          const csv = eventsToAdminCsv(events);
          return respondText(res, 200, csv, "text/csv; charset=utf-8", metricPath);
        }
        if (format === "md") {
          const md = eventsToAdminMd(events);
          return respondText(res, 200, md, "text/markdown; charset=utf-8", metricPath);
        }
        if (format === "html") {
          const html = eventsToAdminHtml(events);
          return respondText(res, 200, html, "text/html; charset=utf-8", metricPath);
        }
        if (resolvePayloadRedact(state.policy)) {
          events = events.map((e) => redactAuditEvent(e, state.policy));
        }
        const doRedact = resolveRedact({ flag: qRedact, policy: state.policy });
        if (doRedact) events = redactEvents(events);
        return respondJson(
          res,
          200,
          eventsToJsonPack(events, {
            tenant: qTenant || null,
            tool: qTool || null,
            since: qSince || null,
            until: qUntil || null,
            redacted: doRedact,
            source: "mcp-gateway-admin",
          }),
          metricPath
        );
      }

      if (method === "GET" && url.pathname === "/audit") {
        const qTenant = url.searchParams.get("tenant") || "";
        const qTool = url.searchParams.get("tool") || "";
        const qLimit = url.searchParams.get("limit") || "50";
        const qSince = url.searchParams.get("since") || "";
        const qUntil = url.searchParams.get("until") || "";
        const qRedact = url.searchParams.get("redact");

        let filterTenant = qTenant || undefined;
        if (tenantsEnabled(state.policy)) {
          if (isAdmin(req)) {
            // admin may query any tenant filter
          } else {
            const { tenant, error } = resolveTenant(req);
            if (error) return respondJson(res, error.status, error.body, "/audit");
            filterTenant = tenant.id;
            if (qTenant && qTenant !== tenant.id) {
              return respondJson(res, 403, { error: "tenant_mismatch" }, "/audit");
            }
          }
        }

        let events;
        try {
          events = filterAuditEvents(state.auditEvents, {
            tenant: filterTenant,
            tool: qTool || undefined,
            limit: qLimit,
            since: qSince || undefined,
            until: qUntil || undefined,
          }).reverse();
        } catch (err) {
          if (err?.code === "invalid_since" || err?.message === "invalid_since") {
            return respondJson(res, 400, { error: "invalid_since", hint: "use ISO-8601 timestamp" }, "/audit");
          }
          if (err?.code === "invalid_until" || err?.message === "invalid_until") {
            return respondJson(res, 400, { error: "invalid_until", hint: "use ISO-8601 timestamp" }, "/audit");
          }
          throw err;
        }
        if (resolvePayloadRedact(state.policy)) {
          events = events.map((e) => redactAuditEvent(e, state.policy));
        }
        const doRedact = resolveRedact({ flag: qRedact, policy: state.policy });
        if (doRedact) events = redactEvents(events);
        return respondJson(res, 200, {
          ok: true,
          count: events.length,
          redacted: doRedact,
          events,
        }, "/audit");
      }

      if (method === "GET" && url.pathname === "/audit/export") {
        let format;
        try {
          format = normalizeExportFormat(url.searchParams.get("format") || "json", ["json", "csv"]);
        } catch {
          return respondJson(res, 400, { error: "unsupported_format", allowed: ["json", "csv"] }, "/audit/export");
        }
        const qTenant = url.searchParams.get("tenant") || "";
        const qTool = url.searchParams.get("tool") || "";
        const qLimit = url.searchParams.get("limit") || "";
        const qSince = url.searchParams.get("since") || "";
        const qUntil = url.searchParams.get("until") || "";
        const qRedact = url.searchParams.get("redact");

        let filterTenant = qTenant || undefined;
        // Auth: tenant API key OR admin token (same gate as /audit when tenants on).
        if (tenantsEnabled(state.policy)) {
          if (isAdmin(req)) {
            // admin may export any / all tenants
          } else {
            const { tenant, error } = resolveTenant(req);
            if (error) return respondJson(res, error.status, error.body, "/audit/export");
            filterTenant = tenant.id;
            if (qTenant && qTenant !== tenant.id) {
              return respondJson(res, 403, { error: "tenant_mismatch" }, "/audit/export");
            }
          }
        } else if (state.policy.adminToken && !isAdmin(req)) {
          return respondJson(res, 401, { error: "unauthorized_admin" }, "/audit/export");
        }

        let events;
        try {
          events = filterAuditEvents(state.auditEvents, {
            tenant: filterTenant,
            tool: qTool || undefined,
            limit: qLimit || undefined,
            since: qSince || undefined,
            until: qUntil || undefined,
          });
        } catch (err) {
          if (err?.code === "invalid_since" || err?.message === "invalid_since") {
            return respondJson(res, 400, { error: "invalid_since", hint: "use ISO-8601 timestamp" }, "/audit/export");
          }
          if (err?.code === "invalid_until" || err?.message === "invalid_until") {
            return respondJson(res, 400, { error: "invalid_until", hint: "use ISO-8601 timestamp" }, "/audit/export");
          }
          throw err;
        }
        if (resolvePayloadRedact(state.policy)) {
          events = events.map((e) => redactAuditEvent(e, state.policy));
        }
        const doRedact = resolveRedact({ flag: qRedact, policy: state.policy });
        if (doRedact) events = redactEvents(events);
        const doGzip = wantsGzip({
          gzipQuery: url.searchParams.get("gzip"),
          acceptEncoding: req.headers["accept-encoding"],
        });
        const stamp = new Date().toISOString().replace(/[:.]/g, "-");
        const tenantSlug = filterTenant || "all";
        if (format === "csv") {
          const csv = eventsToCsv(events);
          const filename = gzipFilename(`audit-${tenantSlug}-${stamp}.csv`, doGzip);
          metrics.incHttpRequest({ path: "/audit/export", status: 200 });
          const headers = {
            "content-type": "text/csv; charset=utf-8",
            "content-disposition": `attachment; filename="${filename}"`,
            "x-audit-count": String(events.length),
            "x-audit-redacted": doRedact ? "1" : "0",
          };
          if (doGzip) {
            const gz = gzipBytes(csv);
            headers["content-encoding"] = "gzip";
            headers["content-length"] = gz.length;
            res.writeHead(200, headers);
            return res.end(gz);
          }
          // stream in chunks for large packs
          const chunkSize = 64 * 1024;
          res.writeHead(200, headers);
          for (let i = 0; i < csv.length; i += chunkSize) {
            res.write(csv.slice(i, i + chunkSize));
          }
          return res.end();
        }
        const pack = eventsToJsonPack(events, {
          tenant: filterTenant || null,
          tool: qTool || null,
          since: qSince || null,
          until: qUntil || null,
          redacted: doRedact,
          source: "mcp-gateway",
        });
        const payload = JSON.stringify(pack);
        const filename = gzipFilename(`audit-${tenantSlug}-${stamp}.json`, doGzip);
        metrics.incHttpRequest({ path: "/audit/export", status: 200 });
        const headers = {
          "content-type": "application/json; charset=utf-8",
          "content-disposition": `attachment; filename="${filename}"`,
          "x-audit-count": String(events.length),
          "x-audit-redacted": doRedact ? "1" : "0",
        };
        if (doGzip) {
          const gz = gzipBytes(payload);
          headers["content-encoding"] = "gzip";
          headers["content-length"] = gz.length;
          res.writeHead(200, headers);
          return res.end(gz);
        }
        headers["content-length"] = Buffer.byteLength(payload);
        res.writeHead(200, headers);
        return res.end(payload);
      }

      if (
        method === "POST" &&
        (url.pathname === "/tools/list" || url.pathname === "/mcp/tools/list")
      ) {
        const metricPath = url.pathname;
        const { tenant, error } = resolveTenant(req);
        if (error) return respondJson(res, error.status, error.body, metricPath);
        const payload = await listToolsForTenant(tenant);
        return respondJson(res, 200, payload, metricPath);
      }

      if (
        method === "POST" &&
        (url.pathname === "/tools/call" || url.pathname === "/mcp/tools/call")
      ) {
        const metricPath = url.pathname;
        const { tenant, error } = resolveTenant(req);
        if (error) return respondJson(res, error.status, error.body, metricPath);
        const maxBody = resolveMaxBodyBytes(state.policy, tenant);
        let body;
        try {
          body = await readBody(req, maxBody);
        } catch (err) {
          if (err?.code === "payload_too_large" || err?.message === "payload_too_large") {
            metrics.incBodyTooLarge();
            metrics.incHttpRequest({ path: metricPath, status: 413 });
            const payload = JSON.stringify({ error: "payload_too_large" });
            res.writeHead(413, {
              "content-type": "application/json; charset=utf-8",
              "content-length": Buffer.byteLength(payload),
              connection: "close",
            });
            res.end(payload);
            try { req.destroy(); } catch { /* ignore */ }
            return;
          }
          throw err;
        }
        const name = body.name || body.tool || body.params?.name;
        const args = body.arguments ?? body.args ?? body.params?.arguments ?? {};
        if (!name) {
          return respondJson(res, 400, { error: "missing_tool_name" }, metricPath);
        }
        const out = await executeToolCall({ tenant, name, args, requestId });
        return respondJson(res, out.status, out.body, metricPath, out.extraHeaders);
      }


      // Streamable HTTP MVP: DELETE /mcp terminates a session (Mcp-Session-Id is the capability).
      if (method === "DELETE" && isMcpStreamablePath(url.pathname)) {
        const protocolVersion = resolveProtocolVersion(req);
        const sessionId = resolveSessionId(req, { assignIfMissing: false });
        const extra = mcpResponseHeaders({ protocolVersion });
        if (!sessionId) {
          return respondJson(
            res,
            400,
            { error: SESSION_ID_REQUIRED },
            "/mcp",
            extra
          );
        }
        const dropped = sessions.drop(sessionId);
        if (dropped !== "ok") {
          return respondJson(
            res,
            404,
            { error: SESSION_NOT_FOUND },
            "/mcp",
            extra
          );
        }
        recordAudit(
          {
            ts: new Date(nowFn()).toISOString(),
            type: "session_deleted",
            requestId,
          },
          { skipWebhooks: true }
        );
        metrics.incHttpRequest({ path: "/mcp", status: 204 });
        res.writeHead(204, { ...extra, "content-length": 0 });
        return res.end();
      }

      // Streamable HTTP MVP: POST JSON-RPC on /mcp (alias POST /). GET /mcp → 405 Allow: POST, DELETE (no SSE).
      if (isMcpStreamablePath(url.pathname) && method !== "POST") {
        const protocolVersion = resolveProtocolVersion(req);
        const sessionId = resolveSessionId(req, { assignIfMissing: false });
        const extra = {
          ...mcpResponseHeaders({ protocolVersion, sessionId }),
          Allow: MCP_ALLOW_METHODS,
        };
        return respondJson(
          res,
          405,
          {
            error: "method_not_allowed",
            hint: "Streamable HTTP MVP is POST JSON-RPC (initialize, tools/list, tools/call) or DELETE to terminate a session. No SSE.",
            protocolVersion: protocolVersion || MCP_PROTOCOL_VERSION,
          },
          url.pathname,
          extra
        );
      }

      if (method === "POST" && isMcpJsonRpcPostPath(url.pathname)) {
        const metricPath = url.pathname === "/" ? "/" : "/mcp";
        const protocolVersion = resolveProtocolVersion(req);
        let sessionId = resolveSessionId(req, { assignIfMissing: false });
        const mcpHeaders = () => mcpResponseHeaders({ protocolVersion, sessionId });
        const { tenant, error } = resolveTenant(req);
        if (error) {
          return respondJson(res, error.status, error.body, metricPath, mcpHeaders());
        }
        const maxBody = resolveMaxBodyBytes(state.policy, tenant);
        let body;
        try {
          body = await readBody(req, maxBody);
        } catch (err) {
          if (err?.code === "payload_too_large" || err?.message === "payload_too_large") {
            metrics.incBodyTooLarge();
            metrics.incHttpRequest({ path: metricPath, status: 413 });
            const payload = JSON.stringify({ error: "payload_too_large" });
            res.writeHead(413, {
              "content-type": "application/json; charset=utf-8",
              "content-length": Buffer.byteLength(payload),
              connection: "close",
              ...mcpHeaders(),
            });
            res.end(payload);
            try { req.destroy(); } catch { /* ignore */ }
            return;
          }
          throw err;
        }
        if (Array.isArray(body)) {
          return respondJson(
            res,
            400,
            rpcError(null, -32600, "batch_not_supported"),
            metricPath,
            mcpHeaders()
          );
        }
        if (!body || typeof body !== "object") {
          return respondJson(
            res,
            400,
            rpcError(null, -32700, "parse_error"),
            metricPath,
            mcpHeaders()
          );
        }
        const rpcId = Object.prototype.hasOwnProperty.call(body, "id") ? body.id : undefined;
        const rpcMethod = body.method || body.op;
        const notify = isJsonRpcNotification(body);
        if (sessionId) {
          const sessionStatus = sessions.check(sessionId);
          if (sessionStatus === "expired") {
            return respondJson(
              res,
              404,
              { error: SESSION_EXPIRED },
              metricPath,
              mcpResponseHeaders({ protocolVersion })
            );
          }
          if (sessionStatus === "not_found") {
            return respondJson(
              res,
              404,
              { error: SESSION_NOT_FOUND },
              metricPath,
              mcpResponseHeaders({ protocolVersion })
            );
          }
        }
        if (
          rpcMethod === "notifications/initialized" ||
          rpcMethod === "initialized" ||
          (typeof rpcMethod === "string" && rpcMethod.startsWith("notifications/"))
        ) {
          metrics.incHttpRequest({ path: metricPath, status: 202 });
          res.writeHead(202, { ...mcpHeaders(), "content-length": 0 });
          return res.end();
        }
        if (!rpcMethod) {
          return respondJson(
            res,
            400,
            rpcError(rpcId ?? null, -32600, "missing_method"),
            metricPath,
            mcpHeaders()
          );
        }
        if (rpcMethod === "initialize") {
          sessionId = resolveSessionId(req, { assignIfMissing: true });
          sessions.touch(sessionId);
          const result = initializeResult({ protocolVersion, sessionId });
          return respondJson(
            res,
            200,
            rpcResult(rpcId ?? null, result),
            metricPath,
            mcpHeaders()
          );
        }
        if (rpcMethod === "ping") {
          return respondJson(
            res,
            200,
            rpcResult(rpcId ?? null, {}),
            metricPath,
            mcpHeaders()
          );
        }
        if (rpcMethod === "tools/list" || rpcMethod === "list") {
          const payload = await listToolsForTenant(tenant);
          return respondJson(
            res,
            200,
            rpcResult(rpcId ?? null, payload),
            metricPath,
            mcpHeaders()
          );
        }
        if (rpcMethod === "tools/call" || rpcMethod === "call") {
          const params = body.params || {};
          const name = params.name || params.tool || body.name || body.tool;
          const args = params.arguments ?? params.args ?? body.arguments ?? body.args ?? {};
          if (!name) {
            return respondJson(
              res,
              400,
              rpcError(rpcId ?? null, -32602, "missing_tool_name"),
              metricPath,
              mcpHeaders()
            );
          }
          const out = await executeToolCall({ tenant, name, args, requestId });
          const extra = { ...mcpHeaders(), ...(out.extraHeaders || {}) };
          if (out.status === 200) {
            return respondJson(res, 200, rpcResult(rpcId ?? null, out.body), metricPath, extra);
          }
          return respondJson(
            res,
            out.status,
            rpcError(rpcId ?? null, -32000, out.body?.error || "error", out.body),
            metricPath,
            extra
          );
        }
        if (notify) {
          metrics.incHttpRequest({ path: metricPath, status: 202 });
          res.writeHead(202, { ...mcpHeaders(), "content-length": 0 });
          return res.end();
        }
        return respondJson(
          res,
          200,
          rpcError(rpcId ?? null, -32601, "unknown_method:" + rpcMethod),
          metricPath,
          mcpHeaders()
        );
      }

      return respondJson(res, 404, { error: "not_found", path: url.pathname }, url.pathname);
    } catch (err) {
      return respondJson(res, 500, {
        error: "internal_error",
        message: String(err?.message || err),
      }, "internal_error");
    }
  });

  // Kick off initial upstream connect (async; health reports status).
  const ready = connectUpstream(state.policy);

  return {
    server,
    auditPath: state.auditPath,
    auditMaxEvents: state.auditMaxEvents,
    getAuditEvents: () => state.auditEvents,
    metrics,
    reloadPolicy,
    reloadPolicyAndUpstream,
    getPolicy: () => state.policy,
    getUpstreamState: () => ({
      connected: Boolean(state.upstream),
      tools: state.upstreamTools,
      error: state.upstreamError,
    }),
    ready,
    sessionTtlSec: state.sessionTtlSec,
    beginShutdown() {
      state.shuttingDown = true;
    },
    isShuttingDown() {
      return Boolean(state.shuttingDown);
    },
    async close() {
      if (state.upstream && typeof state.upstream.close === "function") {
        await state.upstream.close();
      }
      await new Promise((resolve) => server.close(resolve));
    },
  };
}
