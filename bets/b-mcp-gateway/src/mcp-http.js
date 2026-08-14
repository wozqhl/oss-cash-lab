/** Minimal Streamable HTTP helpers for MCP clients (POST JSON-RPC; no SSE). */

import { randomUUID } from "node:crypto";

/** Spec version this MVP advertises. Echo client YYYY-MM-DD when provided. */
export const MCP_PROTOCOL_VERSION = "2025-03-26";
export const MCP_PROTOCOL_VERSION_HEADER = "mcp-protocol-version";
export const MCP_SESSION_ID_HEADER = "mcp-session-id";
export const MCP_SERVER_INFO = { name: "mcp-gateway", version: "0.1.0" };

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export function isUuid(value) {
  return typeof value === "string" && UUID_RE.test(value);
}

export function sanitizeHeaderValue(raw, maxLen = 128) {
  if (raw == null || raw === "") return null;
  let s = Array.isArray(raw) ? String(raw[0] ?? "") : String(raw);
  s = s.replace(/[\r\n\0]/g, "").trim();
  if (!s) return null;
  if (s.length > maxLen) s = s.slice(0, maxLen);
  return s;
}

/** Strip a trailing slash except for `/`. */
export function normalizeMcpPath(pathname) {
  const raw = String(pathname || "");
  if (raw.length > 1 && raw.endsWith("/")) return raw.slice(0, -1);
  return raw || "/";
}

/** GET 405 Allow: POST, DELETE. Streamable HTTP lives on `/mcp` (not `/mcp/tools/*`). */
export function isMcpStreamablePath(pathname) {
  return normalizeMcpPath(pathname) === "/mcp";
}

/** POST JSON-RPC: `/mcp` and alias `/`. Does not shadow `/mcp/tools/list`. */
export function isMcpJsonRpcPostPath(pathname) {
  const p = normalizeMcpPath(pathname);
  return p === "/mcp" || p === "/";
}

/** Echo client `MCP-Protocol-Version` when it looks like YYYY-MM-DD; else default. */
export function resolveProtocolVersion(req) {
  const incoming = sanitizeHeaderValue(
    req?.headers?.[MCP_PROTOCOL_VERSION_HEADER],
    32
  );
  if (incoming && DATE_RE.test(incoming)) return incoming;
  return MCP_PROTOCOL_VERSION;
}

/**
 * Session id: echo when present; assign UUID on initialize if missing.
 * Subsequent calls may omit it (backward compatible with REST local-mvp).
 */
export function resolveSessionId(req, { assignIfMissing = false } = {}) {
  const incoming = sanitizeHeaderValue(
    req?.headers?.[MCP_SESSION_ID_HEADER],
    128
  );
  if (incoming) return incoming;
  if (assignIfMissing) return randomUUID();
  return null;
}

export function mcpResponseHeaders({ protocolVersion, sessionId } = {}) {
  const headers = {
    [MCP_PROTOCOL_VERSION_HEADER]: protocolVersion || MCP_PROTOCOL_VERSION,
  };
  if (sessionId) headers[MCP_SESSION_ID_HEADER] = sessionId;
  return headers;
}

export function rpcResult(id, result) {
  return { jsonrpc: "2.0", id: id ?? null, result };
}

export function rpcError(id, code, message, data) {
  const error = { code, message: String(message || "error") };
  if (data !== undefined) error.data = data;
  return { jsonrpc: "2.0", id: id ?? null, error };
}

export function isJsonRpcNotification(msg) {
  if (!msg || typeof msg !== "object" || Array.isArray(msg)) return false;
  return !Object.prototype.hasOwnProperty.call(msg, "id");
}

export function initializeResult({ protocolVersion, sessionId } = {}) {
  return {
    protocolVersion: protocolVersion || MCP_PROTOCOL_VERSION,
    capabilities: { tools: { listChanged: false } },
    serverInfo: { ...MCP_SERVER_INFO },
    sessionId: sessionId || null,
  };
}

/** Default unused-session TTL (seconds). `0` = no time expiry (ids still generated). */
export const DEFAULT_SESSION_TTL_SEC = 3600;
export const ENV_SESSION_TTL_SEC = "MCP_SESSION_TTL_SEC";
/** In-memory last-seen map cap. Over cap, drop oldest. `0` = unlimited. */
export const DEFAULT_SESSION_MAX_IDS = 10000;
export const SESSION_EXPIRED = "session_expired";
export const SESSION_NOT_FOUND = "session_not_found";
export const SESSION_ID_REQUIRED = "session_id_required";
/** GET 405 Allow header (POST JSON-RPC + DELETE terminate; no SSE). */
export const MCP_ALLOW_METHODS = "POST, DELETE";
/** Admin GET /admin/sessions array cap (newest-by-lastSeen). Full live count is still `count`. */
export const ADMIN_SESSION_LIST_LIMIT = 100;

/** CLI `--session-ttl` wins when provided; else env MCP_SESSION_TTL_SEC; else 3600. `0` = no expiry. */
export function resolveSessionTtlSec(raw, env = process.env) {
  const source = raw == null || raw === "" ? env?.[ENV_SESSION_TTL_SEC] : raw;
  if (source == null || source === "") return DEFAULT_SESSION_TTL_SEC;
  const n = Number(source);
  if (!Number.isFinite(n) || n < 0) return DEFAULT_SESSION_TTL_SEC;
  return Math.floor(n);
}

function resolveTtlMs({ ttlSec, ttlMs } = {}) {
  if (ttlMs != null && ttlMs !== "") {
    const n = Number(ttlMs);
    if (Number.isFinite(n) && n >= 0) return Math.floor(n);
  }
  if (ttlSec != null && ttlSec !== "") {
    const n = Number(ttlSec);
    if (Number.isFinite(n) && n >= 0) return Math.floor(n) * 1000;
  }
  return DEFAULT_SESSION_TTL_SEC * 1000;
}

/**
 * In-memory last-seen map for Streamable HTTP session ids.
 * ttl 0 = no time expiry (still generate/track ids). Cap drops oldest (LRU via re-insert).
 * Missing id → "missing" (compat). Unknown id → accept + track ("ok"). Expired → delete + "expired".
 * DELETE terminate tombstones the id so POST does not re-accept it as unknown (`not_found`).
 */
export function createSessionStore({
  ttlSec = DEFAULT_SESSION_TTL_SEC,
  ttlMs,
  maxIds = DEFAULT_SESSION_MAX_IDS,
  now = () => Date.now(),
} = {}) {
  const lastSeen = new Map();
  const deleted = new Map();
  const ttl = resolveTtlMs({ ttlSec, ttlMs });
  const max =
    typeof maxIds === "number" && Number.isFinite(maxIds) && maxIds >= 0
      ? Math.floor(maxIds)
      : DEFAULT_SESSION_MAX_IDS;

  function dropOldestFrom(map) {
    if (max <= 0) return;
    while (map.size > max) {
      const oldest = map.keys().next().value;
      map.delete(oldest);
    }
  }

  function dropOldest() {
    dropOldestFrom(lastSeen);
  }

  function touch(id) {
    if (id == null || id === "") return;
    const key = String(id);
    deleted.delete(key);
    lastSeen.delete(key);
    lastSeen.set(key, now());
    dropOldest();
  }

  /**
   * Terminate a session. Does not create unknown ids.
   * @returns {"ok"|"missing"|"not_found"}
   */
  function drop(id) {
    if (id == null || id === "") return "missing";
    const key = String(id);
    if (deleted.has(key)) return "not_found";
    const seen = lastSeen.get(key);
    if (seen == null) return "not_found";
    if (ttl > 0 && now() - seen >= ttl) {
      lastSeen.delete(key);
      return "not_found";
    }
    lastSeen.delete(key);
    deleted.delete(key);
    deleted.set(key, now());
    dropOldestFrom(deleted);
    return "ok";
  }

  /** @returns {"ok"|"missing"|"expired"|"not_found"} */
  function check(id) {
    if (id == null || id === "") return "missing";
    const key = String(id);
    if (deleted.has(key)) return "not_found";
    const seen = lastSeen.get(key);
    if (seen == null) {
      touch(key);
      return "ok";
    }
    if (ttl > 0 && now() - seen >= ttl) {
      lastSeen.delete(key);
      return "expired";
    }
    touch(key);
    return "ok";
  }

  /**
   * Live session inventory for GET /admin/sessions.
   * Omits tombstones (deleted) and expired ids (lazy-pruned). Caps `sessions` at `limit`
   * newest-by-lastSeen (default 100). `count` is the full live size; `truncated: true` when capped.
   * `dropped` is the current tombstone map size. No secrets / API keys / headers.
   * ttlSec 0 → ttlRemainingMs is null.
   */
  function list({ limit = ADMIN_SESSION_LIST_LIMIT } = {}) {
    const t = now();
    const capLimit =
      typeof limit === "number" && Number.isFinite(limit) && limit >= 0
        ? Math.floor(limit)
        : ADMIN_SESSION_LIST_LIMIT;
    const live = [];
    for (const [id, seen] of [...lastSeen.entries()]) {
      if (ttl > 0 && t - seen >= ttl) {
        lastSeen.delete(id);
        continue;
      }
      const ageMs = t - seen;
      live.push({
        id,
        ageMs,
        ttlRemainingMs: ttl > 0 ? Math.max(0, ttl - ageMs) : null,
        lastSeen: new Date(seen).toISOString(),
        _seen: seen,
      });
    }
    live.sort((a, b) => b._seen - a._seen || String(a.id).localeCompare(String(b.id)));
    const count = live.length;
    const truncated = capLimit > 0 && count > capLimit;
    const sliced = truncated ? live.slice(0, capLimit) : live;
    const sessions = sliced.map(({ _seen, ...row }) => row);
    const body = {
      ok: true,
      ttlSec: Math.floor(ttl / 1000),
      cap: max,
      count,
      sessions,
      dropped: deleted.size,
    };
    if (truncated) body.truncated = true;
    return body;
  }

  return { check, touch, drop, list, lastSeen, deleted, ttlMs: ttl, ttlSec: Math.floor(ttl / 1000), maxIds: max };
}

/**
 * DELETE /admin/sessions/{id} (path id; no Mcp-Session-Id header).
 * `/admin/sessions` (list) and `/admin/sessions/` (empty) do not match — Express-style 404.
 */
export function matchAdminSessionPath(pathname) {
  const p = String(pathname || "");
  const m = p.match(/^\/admin\/sessions\/([^/]+)\/?$/);
  if (!m) return null;
  let id = m[1];
  try {
    id = decodeURIComponent(id);
  } catch {
    /* keep raw */
  }
  if (!id) return null;
  return { sessionId: id };
}
