/** Conservative stdlib regex redaction of PII/secrets inside tool-call payloads.
 *
 *  Market gap vs infra MCP gateways (routing/auth/obs): inspect arguments/result
 *  and mask emails, bearer tokens, sk-/ghp_-like prefixes, long hex/base64-ish
 *  secrets. Regex only — not Microsoft Presidio / NER.
 */

export const REDACTED = "[REDACTED]";

/** Default payload keys walked when `redact.fields` is `["*"]`. Metadata (ts, tool, requestId) is left alone. */
export const DEFAULT_PAYLOAD_KEYS = ["arguments", "args", "result"];

const EMAIL_RE = /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g;
const BEARER_RE = /\bBearer\s+[A-Za-z0-9._\-+=/]{8,}/gi;
/** OpenAI-ish, GitHub PAT, GitLab, Slack, AWS access-key prefixes. */
const PREFIX_RE =
  /\b(?:sk|ghp|github_pat|gho|ghu|ghs|ghr|glpat|xox[bpasr]|AKIA)[-_][A-Za-z0-9_\-]{8,}/g;
/** 32+ continuous hex (MD5+). UUID dashed form is not matched. */
const LONG_HEX_RE = /\b[0-9a-fA-F]{32,}\b/g;
/** Long base64-ish tokens (32+ of the alphabet). Filtered further in shouldRedactB64. */
const LONG_B64_RE = /\b[A-Za-z0-9+/]{32,}={0,2}\b/g;

function parseBool(value, defaultValue) {
  if (value === true || value === false) return value;
  if (value == null || value === "") return defaultValue;
  const s = String(value).trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(s)) return true;
  if (["0", "false", "no", "off"].includes(s)) return false;
  return defaultValue;
}

/**
 * Resolve `policy.redact`.
 * - enabled: default true (audit + webhooks)
 * - upstream: default false (do not mutate tools/call body sent upstream)
 * - fields: default ["*"] (walk arguments/args/result)
 */
export function resolveRedactConfig(policy) {
  const raw =
    policy && typeof policy.redact === "object" && !Array.isArray(policy.redact)
      ? policy.redact
      : {};
  const enabled = parseBool(raw.enabled, true);
  const upstream = parseBool(raw.upstream, false);
  const fields = Array.isArray(raw.fields) && raw.fields.length
    ? raw.fields.map((f) => String(f))
    : ["*"];
  return { enabled, upstream, fields };
}

/** In-payload redaction for audit/webhooks (default on). */
export function resolvePayloadRedact(policy) {
  return resolveRedactConfig(policy).enabled;
}

/** Mutate upstream tools/call arguments only when enabled AND upstream=true. */
export function resolveUpstreamRedact(policy) {
  const cfg = resolveRedactConfig(policy);
  return Boolean(cfg.enabled && cfg.upstream);
}

function shouldRedactB64(m) {
  if (typeof m !== "string" || m.length < 32) return false;
  const hasDigit = /\d/.test(m);
  const hasUpper = /[A-Z]/.test(m);
  const hasLower = /[a-z]/.test(m);
  const hasSym = /[+/=]/.test(m);
  const classes = [hasDigit, hasUpper, hasLower, hasSym].filter(Boolean).length;
  return classes >= 3 || (m.length >= 48 && classes >= 2);
}

/** Replace matched secret/PII spans in a string. Idempotent on `[REDACTED]`. */
export function redactString(input) {
  if (typeof input !== "string" || !input) return input;
  let s = input;
  s = s.replace(BEARER_RE, (m) => {
    const idx = m.search(/\s/);
    return idx === -1 ? REDACTED : `${m.slice(0, idx)} ${REDACTED}`;
  });
  s = s.replace(PREFIX_RE, REDACTED);
  s = s.replace(EMAIL_RE, REDACTED);
  s = s.replace(LONG_HEX_RE, REDACTED);
  s = s.replace(LONG_B64_RE, (m) => (shouldRedactB64(m) ? REDACTED : m));
  return s;
}

/** Deep-clone walk: redact strings, keep numbers/bools/structure. */
export function redactValue(value, seen = new WeakSet()) {
  if (value == null) return value;
  if (typeof value === "string") return redactString(value);
  if (typeof value !== "object") return value;
  if (seen.has(value)) return "[Cycle]";
  seen.add(value);
  if (Array.isArray(value)) return value.map((v) => redactValue(v, seen));
  const out = {};
  for (const [k, v] of Object.entries(value)) {
    out[k] = redactValue(v, seen);
  }
  return out;
}

function shouldWalkKey(key, fields) {
  if (!Array.isArray(fields) || !fields.length || fields.includes("*")) {
    return DEFAULT_PAYLOAD_KEYS.includes(key);
  }
  return fields.some((f) => f === key || f.startsWith(`${key}.`));
}

/** Clone an audit row and redact configured payload fields only. */
export function redactAuditEvent(event, policy) {
  if (!event || typeof event !== "object") return event;
  const cfg = resolveRedactConfig(policy);
  if (!cfg.enabled) return event;
  const out = { ...event };
  for (const key of Object.keys(out)) {
    if (shouldWalkKey(key, cfg.fields)) {
      out[key] = redactValue(out[key]);
    }
  }
  return out;
}

export function redactAuditEvents(events, policy) {
  if (!resolvePayloadRedact(policy)) return events || [];
  return (events || []).map((e) => redactAuditEvent(e, policy));
}

/** Redact tool-call arguments for optional upstream mutation. */
export function redactToolArgs(args, policy) {
  if (!resolvePayloadRedact(policy)) return args;
  return redactValue(args);
}

export {
  EMAIL_RE,
  BEARER_RE,
  PREFIX_RE,
  LONG_HEX_RE,
  LONG_B64_RE,
};
