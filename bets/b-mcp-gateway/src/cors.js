/** CORS allowlist: preflight OPTIONS + ACAO on GET/POST/DELETE. Default: disabled (no extra CORS). */

export const DEFAULT_CORS_METHODS = ["GET", "POST", "DELETE", "OPTIONS"];
export const DEFAULT_CORS_HEADERS = [
  "Content-Type",
  "Authorization",
  "X-Api-Key",
  "X-Admin-Token",
  "X-Request-Id",
  "MCP-Protocol-Version",
  "Mcp-Session-Id",
];
export const DEFAULT_CORS_EXPOSE_HEADERS = [
  "X-Audit-Count",
  "X-Audit-Redacted",
  "Content-Disposition",
  "Retry-After",
  "X-Request-Id",
  "MCP-Protocol-Version",
  "Mcp-Session-Id",
];

/**
 * Parse policy.cors. Missing / empty origins => disabled (null).
 * origins: ["*"] allows any Origin; otherwise exact-match list.
 */
export function normalizeCors(policy) {
  const raw = policy?.cors;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const origins = Array.isArray(raw.origins)
    ? raw.origins.map((o) => String(o).trim()).filter(Boolean)
    : [];
  if (origins.length === 0) return null;
  const methods =
    Array.isArray(raw.methods) && raw.methods.length
      ? raw.methods.map((m) => String(m).trim().toUpperCase()).filter(Boolean)
      : DEFAULT_CORS_METHODS.slice();
  const headers =
    Array.isArray(raw.headers) && raw.headers.length
      ? raw.headers.map((h) => String(h).trim()).filter(Boolean)
      : DEFAULT_CORS_HEADERS.slice();
  const expose =
    Array.isArray(raw.exposeHeaders) && raw.exposeHeaders.length
      ? raw.exposeHeaders.map((h) => String(h).trim()).filter(Boolean)
      : DEFAULT_CORS_EXPOSE_HEADERS.slice();
  return {
    origins,
    methods,
    headers,
    expose,
    allowAny: origins.includes("*"),
  };
}

export function requestOrigin(req) {
  const raw = req?.headers?.origin;
  if (raw == null || raw === "") return null;
  const s = Array.isArray(raw) ? String(raw[0]) : String(raw);
  const t = s.trim();
  return t || null;
}

export function originAllowed(origin, cors) {
  if (!cors) return false;
  if (cors.allowAny) return true;
  if (!origin) return false;
  return cors.origins.includes(origin);
}

export function acaoValue(origin, cors) {
  if (!cors) return null;
  if (cors.allowAny) return "*";
  if (origin && cors.origins.includes(origin)) return origin;
  return null;
}

/** Headers to merge onto a real (non-preflight) response when Origin matches. */
export function corsResponseHeaders(req, policy) {
  const cors = normalizeCors(policy);
  if (!cors) return {};
  const origin = requestOrigin(req);
  const acao = acaoValue(origin, cors);
  if (!acao) return {};
  const headers = {
    "access-control-allow-origin": acao,
  };
  if (acao !== "*") headers.vary = "Origin";
  if (cors.expose && cors.expose.length) {
    headers["access-control-expose-headers"] = cors.expose.join(", ");
  }
  return headers;
}

/**
 * OPTIONS preflight.
 * Returns null when CORS is disabled (caller 404s as usual).
 * Allowed origin → { status: 204, headers, body: null }.
 * Explicit list + origin not allowed → { status: 403, headers: {}, body }.
 */
export function handlePreflight(req, policy) {
  const cors = normalizeCors(policy);
  if (!cors) return null;
  const origin = requestOrigin(req);
  if (!originAllowed(origin, cors)) {
    return {
      status: 403,
      headers: {},
      body: { error: "forbidden", reason: "cors_denied" },
    };
  }
  const acao = cors.allowAny ? "*" : origin;
  const headers = {
    "access-control-allow-origin": acao,
    "access-control-allow-methods": cors.methods.join(", "),
    "access-control-allow-headers": cors.headers.join(", "),
    "access-control-max-age": "600",
  };
  if (acao !== "*") headers.vary = "Origin";
  if (cors.expose && cors.expose.length) {
    headers["access-control-expose-headers"] = cors.expose.join(", ");
  }
  return { status: 204, headers, body: null };
}
