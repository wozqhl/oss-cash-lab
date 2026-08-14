/** Static allow/deny policy + tiny rate limit for MCP tool calls. */
import crypto from "node:crypto";


export function evaluatePolicy(policy, toolName) {
  const deny = new Set(policy?.deny || []);
  const allow = policy?.allow ? new Set(policy.allow) : null;
  if (deny.has(toolName)) return { allow: false, reason: "denied" };
  if (allow && !allow.has(toolName)) return { allow: false, reason: "not-in-allowlist" };
  return { allow: true, reason: "ok" };
}

/** Default max request body size (1 MiB). */
export const DEFAULT_MAX_BODY_BYTES = 1_048_576;

/** Resolve maxBodyBytes: tenant override > global > default. */
export function resolveMaxBodyBytes(globalPolicy, tenant) {
  const cand = [tenant?.maxBodyBytes, globalPolicy?.maxBodyBytes];
  for (const v of cand) {
    if (typeof v === "number" && Number.isFinite(v) && v > 0) return Math.floor(v);
    if (typeof v === "string" && v.trim() !== "") {
      const n = Number(v);
      if (Number.isFinite(n) && n > 0) return Math.floor(n);
    }
  }
  return DEFAULT_MAX_BODY_BYTES;
}

/** Merge tenant overrides onto global policy for allow/deny/rateLimit/maxBodyBytes. */
export function effectivePolicy(globalPolicy, tenant) {
  if (!tenant) {
    const base = globalPolicy || { allow: [], deny: [] };
    return {
      ...base,
      rateLimitPerMinute: base.rateLimitPerMinute ?? 60,
      maxBodyBytes: resolveMaxBodyBytes(globalPolicy, null),
    };
  }
  return {
    allow: tenant.allow ?? globalPolicy?.allow,
    deny: tenant.deny ?? globalPolicy?.deny,
    rateLimitPerMinute:
      tenant.rateLimitPerMinute ?? globalPolicy?.rateLimitPerMinute ?? 60,
    maxBodyBytes: resolveMaxBodyBytes(globalPolicy, tenant),
  };
}


/** Mask API key for admin listing: show only last 4 chars (never raw key). */
export function maskApiKey(apiKey) {
  if (typeof apiKey !== "string" || apiKey.length === 0) return null;
  if (apiKey.length <= 4) return "****";
  return `${"*".repeat(Math.min(8, apiKey.length - 4))}${apiKey.slice(-4)}`;
}

/**
 * Admin-safe tenant summaries: counts + limits, never raw apiKey.
 * Fields: id, allowCount, denyCount, rateLimit, hasIpAllowlist, maxBodyBytes, apiKeyMasked.
 */
export function summarizeTenantsForAdmin(globalPolicy) {
  const tenants = Array.isArray(globalPolicy?.tenants) ? globalPolicy.tenants : [];
  return tenants
    .filter((t) => t && typeof t.id === "string" && t.id)
    .map((tenant) => {
      const pol = effectivePolicy(globalPolicy, tenant);
      const allow = Array.isArray(pol.allow) ? pol.allow : [];
      const deny = Array.isArray(pol.deny) ? pol.deny : [];
      const list = Array.isArray(tenant.ipAllowlist) ? tenant.ipAllowlist : [];
      return {
        id: tenant.id,
        allowCount: allow.length,
        denyCount: deny.length,
        rateLimit: pol.rateLimitPerMinute ?? 60,
        hasIpAllowlist: list.length > 0,
        maxBodyBytes: pol.maxBodyBytes ?? DEFAULT_MAX_BODY_BYTES,
        apiKeyMasked: maskApiKey(tenant.apiKey),
      };
    });
}

/** Keys that must never appear on GET /admin/tenants/{id} (exact, case-insensitive). */
export const FORBIDDEN_ADMIN_TENANT_KEYS = [
  "apiKey",
  "previousApiKey",
  "adminToken",
  "secret",
  "token",
  "Authorization",
  "authorization",
  "webhookSecret",
];

const FORBIDDEN_TENANT_KEY_SET = new Set(
  FORBIDDEN_ADMIN_TENANT_KEYS.map((k) => k.toLowerCase())
);

/** Fixture / shape needles that must be absent from the JSON dump. */
export const ADMIN_TENANT_SECRET_NEEDLES = [
  "ten_acme_dev",
  "ten_restricted_dev",
  "ten_iplock_dev",
  "ten_acme_mcp",
  "ten_acme_old_rotate",
  "old_secret_token_rotate",
  "sk-secret-smoke",
  "admin-dev-token",
  "sk-",
  "Bearer",
  "whsec_",
  "hunter2",
];

/**
 * Admin-safe single tenant for GET /admin/tenants/{id}.
 * Builds a new object from known-safe fields only (never spreads tenant / policy).
 * Never includes apiKey / previousApiKey values.
 * Unknown id → { ok:false, error:"tenant_not_found" }.
 */
export function summarizeTenantForAdmin(globalPolicy, tenantId) {
  const tenants = Array.isArray(globalPolicy?.tenants) ? globalPolicy.tenants : [];
  const id = tenantId == null ? "" : String(tenantId);
  if (!id) return { ok: false, error: "tenant_not_found" };
  const tenant = tenants.find((t) => t && t.id === id);
  if (!tenant) return { ok: false, error: "tenant_not_found" };
  const pol = effectivePolicy(globalPolicy, tenant);
  const allow = Array.isArray(pol.allow) ? pol.allow.slice() : [];
  const deny = Array.isArray(pol.deny) ? pol.deny.slice() : [];
  const list = Array.isArray(tenant.ipAllowlist) ? tenant.ipAllowlist : [];
  const hasApiKey = typeof tenant.apiKey === "string" && tenant.apiKey.length > 0;
  const hasPreviousApiKey =
    typeof tenant.previousApiKey === "string" && tenant.previousApiKey.length > 0;
  let previousApiKeyExpiresAt = null;
  if (typeof tenant.previousApiKeyExpiresAt === "string" && tenant.previousApiKeyExpiresAt) {
    previousApiKeyExpiresAt = tenant.previousApiKeyExpiresAt;
  }
  return {
    ok: true,
    id: tenant.id,
    hasApiKey,
    hasPreviousApiKey,
    previousApiKeyExpiresAt,
    allow,
    deny,
    rateLimit: pol.rateLimitPerMinute ?? 60,
    hasIpAllowlist: list.length > 0,
    maxBodyBytes: pol.maxBodyBytes ?? DEFAULT_MAX_BODY_BYTES,
  };
}

/** Walk JSON keys; return paths whose names are forbidden on GET /admin/tenants/{id}. */
export function collectForbiddenAdminTenantKeys(value, path = "$") {
  const hits = [];
  function walk(v, pth) {
    if (v == null) return;
    if (Array.isArray(v)) {
      v.forEach((item, i) => walk(item, `${pth}[${i}]`));
      return;
    }
    if (typeof v === "object") {
      for (const [k, child] of Object.entries(v)) {
        if (FORBIDDEN_TENANT_KEY_SET.has(String(k).toLowerCase())) hits.push(`${pth}.${k}`);
        walk(child, `${pth}.${k}`);
      }
    }
  }
  walk(value, path);
  return hits;
}

export function adminTenantLeakNeedles(payload) {
  const dump = JSON.stringify(payload);
  return ADMIN_TENANT_SECRET_NEEDLES.filter((n) => dump.includes(n));
}

/**
 * True when payload has no forbidden keys and no secret needles.
 * Used by smoke so adding apiKey to this JSON later fails the build.
 */
export function assertAdminTenantSafe(payload) {
  const keys = collectForbiddenAdminTenantKeys(payload);
  const leaks = adminTenantLeakNeedles(payload);
  return { ok: keys.length === 0 && leaks.length === 0, keys, leaks };
}

/** Default dual-token grace after admin rotate (seconds). */
export const DEFAULT_TOKEN_ROTATE_GRACE_SEC = 60;
export const ENV_TOKEN_ROTATE_GRACE_SEC = "TOKEN_ROTATE_GRACE_SEC";

/** CLI `--rotate-grace-sec` wins when provided; else env TOKEN_ROTATE_GRACE_SEC; else 60. */
export function resolveRotateGraceSec(raw, env = process.env) {
  const source = raw == null || raw === "" ? env?.[ENV_TOKEN_ROTATE_GRACE_SEC] : raw;
  const n = Number(source);
  if (!Number.isFinite(n) || n < 0) return DEFAULT_TOKEN_ROTATE_GRACE_SEC;
  return Math.floor(n);
}

/** True when tenant.previousApiKey is still inside its grace window. */
export function previousApiKeyValid(tenant, now = Date.now()) {
  if (!tenant || typeof tenant.previousApiKey !== "string" || !tenant.previousApiKey) {
    return false;
  }
  const exp = Date.parse(tenant.previousApiKeyExpiresAt || "");
  if (!Number.isFinite(exp)) return false;
  return now < exp;
}

export function findTenantByApiKey(policy, apiKey, now = Date.now()) {
  const tenants = Array.isArray(policy?.tenants) ? policy.tenants : [];
  if (!apiKey) return null;
  for (const t of tenants) {
    if (!t) continue;
    if (t.apiKey === apiKey) return t;
    if (t.previousApiKey === apiKey && previousApiKeyValid(t, now)) return t;
  }
  return null;
}

/** Opaque tenant API key: `ten_<id>_<48 hex>`. Never log the return value. */
export function generateTenantApiKey(tenantId, { randomBytes = crypto.randomBytes } = {}) {
  const safe = String(tenantId || "t").replace(/[^a-zA-Z0-9_-]/g, "") || "t";
  const hex = randomBytes(24).toString("hex");
  return `ten_${safe}_${hex}`;
}

/**
 * Rotate tenant.apiKey in-place (same tenants[] store).
 * During graceSec > 0 the previous key remains valid until previousApiKeyExpiresAt.
 * File persist is the caller's job (same plaintext apiKey field as existing keys).
 */
export function rotateTenantApiKey(policy, tenantId, opts = {}) {
  const tenants = Array.isArray(policy?.tenants) ? policy.tenants : [];
  const id = tenantId == null ? "" : String(tenantId);
  if (!id) {
    const err = new Error("unknown_tenant");
    err.code = "unknown_tenant";
    return { ok: false, error: err };
  }
  const tenant = tenants.find((t) => t && t.id === id);
  if (!tenant) {
    const err = new Error("unknown_tenant");
    err.code = "unknown_tenant";
    return { ok: false, error: err };
  }
  const nowMs = Number.isFinite(opts.now) ? opts.now : Date.now();
  const graceSec = resolveRotateGraceSec(opts.graceSec, opts.env);
  const gen =
    typeof opts.generateKey === "function"
      ? opts.generateKey
      : (tid) => generateTenantApiKey(tid);
  const old = typeof tenant.apiKey === "string" ? tenant.apiKey : "";
  let token = gen(id);
  if (!token || token === old) token = generateTenantApiKey(id);
  if (token === old) token = generateTenantApiKey(id);
  tenant.apiKey = token;
  const expiresAt = new Date(nowMs + graceSec * 1000).toISOString();
  if (old && graceSec > 0) {
    tenant.previousApiKey = old;
    tenant.previousApiKeyExpiresAt = expiresAt;
  } else {
    delete tenant.previousApiKey;
    delete tenant.previousApiKeyExpiresAt;
  }
  const out = { ok: true, tenantId: id, token };
  if (old) out.previousTokenExpiresAt = expiresAt;
  return out;
}

/** Audit row for token rotation. Never include raw tokens/apiKeys. */
export function tokenRotatedAuditEvent({
  tenantId,
  requestId,
  previousTokenExpiresAt,
  now,
} = {}) {
  const ts = new Date(Number.isFinite(now) ? now : Date.now()).toISOString();
  const ev = {
    ts,
    type: "token_rotated",
    tenantId: tenantId || null,
  };
  if (requestId) ev.requestId = requestId;
  if (previousTokenExpiresAt) ev.previousTokenExpiresAt = previousTokenExpiresAt;
  return ev;
}

/**
 * POST /admin/tenants/{id}/rotate (path) or POST /admin/tenants/rotate (body {tenantId}).
 * Exact `/admin/tenants/rotate` is the body form — not tenantId "rotate".
 */
export function matchAdminRotatePath(pathname) {
  const p = String(pathname || "");
  if (p === "/admin/tenants/rotate" || p === "/admin/tenants/rotate/") {
    return { kind: "body", tenantId: null };
  }
  const m = p.match(/^\/admin\/tenants\/([^/]+)\/rotate\/?$/);
  if (!m) return null;
  let id = m[1];
  try {
    id = decodeURIComponent(id);
  } catch {
    /* keep raw */
  }
  if (!id) return null;
  return { kind: "path", tenantId: id };
}

/**
 * GET /admin/tenants/{id} — one tenant, no secrets.
 * List (`/admin/tenants`) and rotate (`…/rotate`) do not match.
 * Reserved id `rotate` is the body-form rotate path, not a tenant.
 */
export function matchAdminGetTenantPath(pathname) {
  const p = String(pathname || "");
  if (p === "/admin/tenants" || p === "/admin/tenants/") return null;
  if (matchAdminRotatePath(p)) return null;
  const m = p.match(/^\/admin\/tenants\/([^/]+)\/?$/);
  if (!m) return null;
  let id = m[1];
  try {
    id = decodeURIComponent(id);
  } catch {
    /* keep raw */
  }
  if (!id || id === "rotate") return null;
  return { tenantId: id };
}

export function tenantsEnabled(policy) {
  return Array.isArray(policy?.tenants) && policy.tenants.length > 0;
}

export class RateLimiter {
  constructor(limitPerMinute = 60) {
    this.limit = limitPerMinute;
    this.hits = [];
  }
  check(now = Date.now()) {
    const windowStart = now - 60_000;
    this.hits = this.hits.filter((t) => t >= windowStart);
    if (this.hits.length >= this.limit) return false;
    this.hits.push(now);
    return true;
  }
}

/** Per-tenant (or global) rate limiters keyed by tenant id. */
export class TenantRateLimiters {
  constructor() {
    this.map = new Map();
  }
  get(tenantId, limitPerMinute) {
    const id = tenantId || "_global";
    let rl = this.map.get(id);
    if (!rl || rl.limit !== limitPerMinute) {
      rl = new RateLimiter(limitPerMinute);
      this.map.set(id, rl);
    }
    return rl;
  }
  clear() {
    this.map.clear();
  }
}

export function auditEvent(toolName, decision, meta = {}) {
  const ev = {
    ts: new Date().toISOString(),
    tool: toolName,
    allow: decision.allow,
    reason: decision.reason,
    ...meta,
  };
  if (meta.tenantId !== undefined) ev.tenantId = meta.tenantId;
  return ev;
}
