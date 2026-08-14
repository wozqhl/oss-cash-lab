/** Optional audit webhook fan-out (fire-and-forget; stdlib fetch).
 *
 * OSS: one retry after ~50ms on 5xx or network/timeout (first-try success
 * = no retry; 4xx do not retry). Exponential backoff / queues = paid.
 */

import crypto from "node:crypto";
import {
  parseBoolFlag,
  redactEvent,
  resolveRedactOnWrite,
} from "./audit-export.js";

const DEFAULT_TIMEOUT_MS = 750;
/** OSS: one retry after this delay on 5xx / network / timeout. */
const DEFAULT_RETRY_DELAY_MS = 50;
const DEFAULT_EVENTS = ["tool_call", "deny"];
/** Outbound HMAC header when webhooks[].secret is set. */
const SIGNATURE_HEADER = "X-Webhook-Signature";
/** Unix-seconds timestamp on every outbound POST (HMAC still signs body only). */
const TIMESTAMP_HEADER = "X-Webhook-Timestamp";

/** Floor unix seconds. Optional nowMs for tests. */
export function webhookUnixSeconds(nowMs = Date.now()) {
  const n = typeof nowMs === "number" && Number.isFinite(nowMs) ? nowMs : Date.now();
  return Math.floor(n / 1000);
}

function trimSecret(raw) {
  if (typeof raw !== "string") return null;
  const s = raw.trim();
  return s || null;
}

/** HMAC-SHA256 of the raw POST body → `sha256=<hex>`. */
export function signWebhookBody(secret, rawBody) {
  const key = String(secret);
  const raw = typeof rawBody === "string" ? rawBody : String(rawBody ?? "");
  const hex = crypto.createHmac("sha256", key).update(raw, "utf8").digest("hex");
  return `sha256=${hex}`;
}

/**
 * Timing-safe check of `X-Webhook-Signature: sha256=<hex>` vs raw body.
 * Hex compared case-insensitively. Missing/empty secret or header → false.
 */
export function verifyWebhookSignature(secret, rawBody, headerValue) {
  const key = trimSecret(secret);
  if (!key) return false;
  const got = String(headerValue || "").trim();
  if (!got) return false;
  const expected = signWebhookBody(key, rawBody);
  const a = Buffer.from(expected, "utf8");
  const b = Buffer.from(got.toLowerCase(), "utf8");
  if (a.length !== b.length) return false;
  return crypto.timingSafeEqual(a, b);
}

/** Normalize policy.webhooks → [{ url, events, secret|null }]. Invalid entries skipped. */
export function normalizeWebhooks(policy) {
  const list = Array.isArray(policy?.webhooks) ? policy.webhooks : [];
  const out = [];
  for (const w of list) {
    if (!w || typeof w.url !== "string") continue;
    const url = w.url.trim();
    if (!url) continue;
    const events =
      Array.isArray(w.events) && w.events.length
        ? w.events.map((e) => String(e))
        : [...DEFAULT_EVENTS];
    out.push({ url, events, secret: trimSecret(w.secret) });
  }
  return out;
}

/**
 * Prefer redacted webhook payloads.
 * - webhooksRedact defaults true
 * - redactOnWrite / export.redactDefault also force redact
 */
export function resolveWebhooksRedact(policy) {
  if (resolveRedactOnWrite(policy)) return true;
  if (Boolean(policy?.export?.redactDefault)) return true;
  const parsed = parseBoolFlag(policy?.webhooksRedact);
  if (parsed !== null) return parsed;
  return true;
}

/** Map audit row → webhook event type. */
export function webhookEventType(auditEv) {
  return auditEv?.allow === false ? "deny" : "tool_call";
}

export function buildWebhookPayload(auditEv, policy) {
  const type = webhookEventType(auditEv);
  let event = auditEv && typeof auditEv === "object" ? { ...auditEv } : auditEv;
  const redacted = resolveWebhooksRedact(policy);
  if (redacted) event = redactEvent(event);
  const requestId = event?.requestId ?? auditEv?.requestId ?? null;
  return {
    type,
    source: "mcp-gateway",
    deliveredAt: new Date().toISOString(),
    redacted,
    requestId,
    event,
  };
}

function defaultSleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * OSS retry policy: 5xx or thrown network/timeout → retry once.
 * 2xx / 4xx → no retry. Exponential backoff / queues = paid.
 */
export function shouldRetryWebhook({ status, error } = {}) {
  if (error) return true;
  const n = Number(status);
  return Number.isFinite(n) && n >= 500 && n <= 599;
}

async function postJson(url, body, timeoutMs, requestId, secret, fetchFn) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const headers = {
      "content-type": "application/json; charset=utf-8",
      "user-agent": "mcp-gateway-webhook/0.1.0",
    };
    if (requestId) headers["x-request-id"] = String(requestId);
    headers[TIMESTAMP_HEADER] = String(webhookUnixSeconds());
    if (secret) headers[SIGNATURE_HEADER] = signWebhookBody(secret, body);
    const doFetch = typeof fetchFn === "function" ? fetchFn : fetch;
    const res = await doFetch(url, {
      method: "POST",
      headers,
      body,
      signal: ctrl.signal,
    });
    const status = res && typeof res.status === "number" ? res.status : 0;
    return { status };
  } finally {
    clearTimeout(timer);
  }
}

async function postWithRetry(url, body, timeoutMs, requestId, secret, opts = {}) {
  const fetchFn = opts.fetchFn;
  const sleepFn = typeof opts.sleepFn === "function" ? opts.sleepFn : defaultSleep;
  const retryDelayMs =
    typeof opts.retryDelayMs === "number" && Number.isFinite(opts.retryDelayMs) && opts.retryDelayMs >= 0
      ? Math.floor(opts.retryDelayMs)
      : DEFAULT_RETRY_DELAY_MS;
  const bumpRetry = () => {
    if (opts.metrics && typeof opts.metrics.incWebhookRetry === "function") {
      opts.metrics.incWebhookRetry();
    }
  };

  let first;
  let firstErr = null;
  try {
    first = await postJson(url, body, timeoutMs, requestId, secret, fetchFn);
    if (!shouldRetryWebhook({ status: first.status })) return first;
  } catch (err) {
    firstErr = err;
    if (!shouldRetryWebhook({ error: err })) throw err;
  }

  bumpRetry();
  await sleepFn(retryDelayMs);
  try {
    return await postJson(url, body, timeoutMs, requestId, secret, fetchFn);
  } catch (err) {
    if (firstErr) throw firstErr;
    throw err;
  }
}

/**
 * After audit write: POST JSON to matching webhook urls.
 * Fire-and-forget — never throws; short timeout; webhook errors ignored.
 * Always sends X-Webhook-Timestamp: <unix-seconds> (OSS). When hook.secret
 * is set, POST also includes X-Webhook-Signature: sha256=<hex> of the raw
 * body (HMAC-SHA256). HMAC still signs the body only; timestamp is an extra
 * header. OSS retries once after ~50ms on 5xx or network/timeout (success
 * on first try = no retry; 4xx do not retry). Exponential backoff / queues,
 * key rotation, and timestamp replay window enforcement = paid later.
 */
export function fanOutWebhooks(policy, auditEv, opts = {}) {
  try {
    const hooks = normalizeWebhooks(policy);
    if (!hooks.length || !auditEv) return Promise.resolve([]);
    const type = webhookEventType(auditEv);
    const payload = buildWebhookPayload(auditEv, policy);
    const body = JSON.stringify(payload);
    const timeoutMs = opts.timeoutMs;
    const ms =
      typeof timeoutMs === "number" && Number.isFinite(timeoutMs) && timeoutMs > 0
        ? Math.floor(timeoutMs)
        : DEFAULT_TIMEOUT_MS;
    const jobs = [];
    for (const hook of hooks) {
      if (!hook.events.includes(type)) continue;
      jobs.push(
        postWithRetry(hook.url, body, ms, payload.requestId, hook.secret, opts).catch(() => {
          /* fire-and-forget */
        })
      );
    }
    return Promise.all(jobs);
  } catch {
    /* never fail the tool call */
    return Promise.resolve([]);
  }
}

export {
  DEFAULT_TIMEOUT_MS,
  DEFAULT_RETRY_DELAY_MS,
  DEFAULT_EVENTS,
  SIGNATURE_HEADER,
  TIMESTAMP_HEADER,
};
