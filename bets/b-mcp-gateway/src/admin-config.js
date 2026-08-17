/** Admin-safe runtime config snapshot. Allowlist only — never copy policy/secrets. */

import { normalizeCors } from "./cors.js";
import { normalizeWebhooks } from "./webhooks.js";
import { resolveBreakerConfig } from "./breaker.js";
import { resolveUpstreamTimeoutMs } from "./upstream.js";
import { resolveAuditMaxEvents, DEFAULT_AUDIT_MAX_EVENTS } from "./audit-export.js";
import {
  resolveSessionTtlSec,
  DEFAULT_SESSION_TTL_SEC,
  DEFAULT_SESSION_MAX_IDS,
} from "./mcp-http.js";
import { resolveRotateGraceSec, DEFAULT_TOKEN_ROTATE_GRACE_SEC } from "./policy.js";
import { resolveRedactConfig } from "./redact.js";

/** Keys that must never appear on GET /admin/config (case-insensitive). */
export const FORBIDDEN_ADMIN_CONFIG_KEYS = [
  "apiKey",
  "previousApiKey",
  "previousApiKeyExpiresAt",
  "adminToken",
  "secret",
  "Authorization",
  "authorization",
  "token",
  "headers",
  "webhookSecret",
];

const FORBIDDEN_KEY_SET = new Set(
  FORBIDDEN_ADMIN_CONFIG_KEYS.map((k) => k.toLowerCase())
);

/** Fixture / shape needles that must be absent from the JSON dump. */
export const ADMIN_CONFIG_SECRET_NEEDLES = [
  "sk-",
  "Bearer",
  "ten_acme_dev",
  "ten_restricted_dev",
  "ten_iplock_dev",
  "ten_acme_mcp",
  "admin-dev-token",
  "whsec_",
  "hunter2",
];

function finiteNonNeg(v, fallback) {
  const n = Number(v);
  if (!Number.isFinite(n) || n < 0) return fallback;
  return Math.floor(n);
}

function corsOriginsForAdmin(policy) {
  const cors = normalizeCors(policy);
  if (!cors) return [];
  if (cors.allowAny) return "*";
  return Array.isArray(cors.origins) ? cors.origins.slice() : [];
}

function tenantCount(policy) {
  const tenants = Array.isArray(policy?.tenants) ? policy.tenants : [];
  return tenants.filter((t) => t && typeof t.id === "string" && t.id).length;
}

function webhookDestinations(policy) {
  const hooks = normalizeWebhooks(policy);
  return hooks.map((h) => ({
    hasWebhookSecret: Boolean(h && h.secret),
  }));
}

function breakerForAdmin(policy, breaker) {
  const cfg = resolveBreakerConfig(policy?.upstream || {});
  const out = {
    enabled: Boolean(cfg.enabled),
    failureThreshold: cfg.failureThreshold,
    openMs: cfg.openMs,
  };
  if (breaker && typeof breaker.snapshot === "function") {
    const snap = breaker.snapshot();
    if (snap && typeof snap.state === "string") out.state = snap.state;
  } else if (breaker && typeof breaker.healthSnapshot === "function") {
    const snap = breaker.healthSnapshot();
    if (snap && typeof snap.state === "string") out.state = snap.state;
  } else {
    out.state = cfg.enabled ? "closed" : "closed";
  }
  return out;
}

function rateLimitForAdmin(policy) {
  const raw = policy?.rateLimitPerMinute;
  if (raw == null || raw === "") return { perMinute: 60 };
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 0) return { perMinute: 60 };
  return { perMinute: Math.floor(n) };
}

/**
 * Redacted runtime config for GET /admin/config.
 * Builds a new object from known-safe fields only (never spreads policy).
 */
export function summarizeConfigForAdmin({
  policy,
  sessionTtlSec,
  sessionCap,
  auditMax,
  rotateGraceSec,
  breaker,
} = {}) {
  const pol = policy && typeof policy === "object" && !Array.isArray(policy) ? policy : {};
  const up = pol.upstream && typeof pol.upstream === "object" ? pol.upstream : null;
  const dests = webhookDestinations(pol);
  const upstream = {
    timeoutMs: resolveUpstreamTimeoutMs(up || {}),
    breaker: breakerForAdmin(pol, breaker),
  };
  if (up && typeof up.type === "string" && up.type) {
    upstream.type = up.type;
  } else if (up && (up.baseUrl || up.url)) {
    upstream.type = "http";
  }
  const redact = resolveRedactConfig(pol);
  return {
    ok: true,
    sessionTtlSec: finiteNonNeg(sessionTtlSec, resolveSessionTtlSec()),
    sessionCap: finiteNonNeg(sessionCap, DEFAULT_SESSION_MAX_IDS),
    auditMax: finiteNonNeg(auditMax, resolveAuditMaxEvents()),
    rotateGraceSec: finiteNonNeg(rotateGraceSec, resolveRotateGraceSec()),
    rateLimit: rateLimitForAdmin(pol),
    cors: { origins: corsOriginsForAdmin(pol) },
    upstream,
    tenants: { count: tenantCount(pol) },
    webhooks: { count: dests.length, destinations: dests },
    redact: {
      enabled: Boolean(redact.enabled),
      upstream: Boolean(redact.upstream),
      fields: Array.isArray(redact.fields) ? redact.fields.slice() : ["*"],
    },
  };
}

/** Walk JSON keys; return paths whose names are forbidden. */
export function collectForbiddenAdminConfigKeys(value, path = "$") {
  const hits = [];
  function walk(v, p) {
    if (v == null) return;
    if (Array.isArray(v)) {
      v.forEach((item, i) => walk(item, `${p}[${i}]`));
      return;
    }
    if (typeof v === "object") {
      for (const [k, child] of Object.entries(v)) {
        if (FORBIDDEN_KEY_SET.has(String(k).toLowerCase())) hits.push(`${p}.${k}`);
        walk(child, `${p}.${k}`);
      }
    }
  }
  walk(value, path);
  return hits;
}

export function adminConfigLeakNeedles(payload) {
  const dump = JSON.stringify(payload);
  return ADMIN_CONFIG_SECRET_NEEDLES.filter((n) => dump.includes(n));
}

/**
 * True when payload has no forbidden keys and no secret needles.
 * Used by smoke so adding apiKey to this JSON later fails the build.
 */
export function assertAdminConfigSafe(payload) {
  const keys = collectForbiddenAdminConfigKeys(payload);
  const leaks = adminConfigLeakNeedles(payload);
  return { ok: keys.length === 0 && leaks.length === 0, keys, leaks };
}


/** Keys that must never appear on GET /admin/webhooks (case-insensitive). */
export const FORBIDDEN_ADMIN_WEBHOOK_KEYS = [
  "url",
  "secret",
  "apiKey",
  "previousApiKey",
  "previousApiKeyExpiresAt",
  "adminToken",
  "Authorization",
  "authorization",
  "token",
  "headers",
  "webhookSecret",
];

const FORBIDDEN_WEBHOOK_KEY_SET = new Set(
  FORBIDDEN_ADMIN_WEBHOOK_KEYS.map((k) => k.toLowerCase())
);

/** Fixture / shape needles that must be absent from the webhook inventory dump. */
export const ADMIN_WEBHOOK_SECRET_NEEDLES = ADMIN_CONFIG_SECRET_NEEDLES.slice();

function webhookIdForAdmin(raw, index) {
  if (typeof raw === "string" && raw.trim()) return raw.trim();
  if (typeof raw === "number" && Number.isFinite(raw)) return Math.floor(raw);
  return index;
}

function webhookHasUrl(w) {
  return typeof w?.url === "string" && w.url.trim().length > 0;
}

function webhookHasSecret(w) {
  return typeof w?.secret === "string" && w.secret.trim().length > 0;
}

/**
 * Admin-safe webhook inventory for GET /admin/webhooks.
 * Builds a new object from known-safe fields only (never spreads policy / hooks).
 * id = configured id if present, else 0-based source index.
 * events = configured list or [].
 * hasUrl / hasSecret = booleans only — never url/secret values.
 */
export function summarizeWebhooksForAdmin(policy) {
  const list = Array.isArray(policy?.webhooks) ? policy.webhooks : [];
  const webhooks = [];
  for (let i = 0; i < list.length; i++) {
    const w = list[i];
    if (!w || typeof w !== "object" || Array.isArray(w)) continue;
    const events = Array.isArray(w.events) ? w.events.map((e) => String(e)) : [];
    webhooks.push({
      id: webhookIdForAdmin(w.id, i),
      events,
      hasUrl: webhookHasUrl(w),
      hasSecret: webhookHasSecret(w),
    });
  }
  return { ok: true, count: webhooks.length, webhooks };
}

/** Walk JSON keys; return paths whose names are forbidden on GET /admin/webhooks. */
export function collectForbiddenAdminWebhookKeys(value, path = "$") {
  const hits = [];
  function walk(v, pth) {
    if (v == null) return;
    if (Array.isArray(v)) {
      v.forEach((item, i) => walk(item, `${pth}[${i}]`));
      return;
    }
    if (typeof v === "object") {
      for (const [k, child] of Object.entries(v)) {
        if (FORBIDDEN_WEBHOOK_KEY_SET.has(String(k).toLowerCase())) hits.push(`${pth}.${k}`);
        walk(child, `${pth}.${k}`);
      }
    }
  }
  walk(value, path);
  return hits;
}

export function adminWebhookLeakNeedles(payload) {
  const dump = JSON.stringify(payload);
  return ADMIN_WEBHOOK_SECRET_NEEDLES.filter((n) => dump.includes(n));
}

/**
 * True when payload has no forbidden keys and no secret needles.
 * Used by smoke so adding url/secret to this JSON later fails the build.
 */
export function assertAdminWebhooksSafe(payload) {
  const keys = collectForbiddenAdminWebhookKeys(payload);
  const leaks = adminWebhookLeakNeedles(payload);
  return { ok: keys.length === 0 && leaks.length === 0, keys, leaks };
}

export {
  DEFAULT_SESSION_TTL_SEC,
  DEFAULT_SESSION_MAX_IDS,
  DEFAULT_AUDIT_MAX_EVENTS,
  DEFAULT_TOKEN_ROTATE_GRACE_SEC,
};
