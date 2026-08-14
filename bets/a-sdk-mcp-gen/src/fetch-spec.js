/** Fetch an OpenAPI document from http(s) or file:// (no extra deps).
 * Timeout 10s (total, including redirects), max body 2MB, follow ≤3 redirects.
 * Rejects non-http(s)/file schemes. Blocks 169.254.169.254 (and IPv4-mapped).
 * Optional extra HTTP headers (opts.headers) are sent on http(s) only — never file://.
 * Header values are redacted in SpecFetchError messages (Authorization / Bearer).
 * Conditional GET: opts.ifNoneMatch / opts.ifModifiedSince → HTTP 304 notModified (no body).
 * Watch fingerprint: ETag, Last-Modified, SHA-256 body hash.
 */
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const SPEC_FETCH_TIMEOUT_MS = 10_000;
export const SPEC_FETCH_MAX_BYTES = 2 * 1024 * 1024;
export const SPEC_FETCH_MAX_REDIRECTS = 3;

const BLOCKED_HOSTS = new Set(["169.254.169.254", "::ffff:169.254.169.254"]);

const SENSITIVE_HEADER_NAMES = new Set(["authorization", "proxy-authorization", "cookie", "set-cookie"]);

/** Redact Authorization / Bearer values so errors never echo secrets. */
export function redactSecretsInText(text) {
  let s = String(text ?? "");
  s = s.replace(/Bearer\s+\S+/gi, "Bearer [redacted]");
  s = s.replace(/(Authorization\s*:\s*)([^\r\n]+)/gi, "$1[redacted]");
  s = s.replace(/(Proxy-Authorization\s*:\s*)([^\r\n]+)/gi, "$1[redacted]");
  return s;
}

export class SpecFetchError extends Error {
  constructor(message, { status, code } = {}) {
    super(redactSecretsInText(message));
    this.name = "SpecFetchError";
    this.status = status;
    this.code = code;
  }
}

/**
 * Parse a single `Name: value` header line (CLI --header / SDK_FETCH_HEADER).
 * Rejects CR/LF (header injection). Does not include the value in thrown messages.
 * @returns {{ name: string, value: string }}
 */
export function parseFetchHeader(raw) {
  const s = String(raw ?? "");
  if (s.includes("\r") || s.includes("\n")) {
    throw new SpecFetchError("invalid fetch header: CR/LF not allowed");
  }
  const idx = s.indexOf(":");
  if (idx <= 0) {
    throw new SpecFetchError("invalid fetch header: expected Name: value");
  }
  const name = s.slice(0, idx).trim();
  const value = s.slice(idx + 1).trim();
  if (!name || /[^\x21-\x7E]/.test(name) || /[\s:]/.test(name)) {
    throw new SpecFetchError("invalid fetch header name");
  }
  return { name, value };
}

/**
 * @param {string[]} lines
 * @returns {{ headers: Record<string, string>, names: string[] }}
 */
export function parseFetchHeaderLines(lines) {
  const headers = {};
  const seen = new Map();
  for (const line of lines || []) {
    if (line == null || String(line).trim() === "") continue;
    const { name, value } = parseFetchHeader(line);
    const key = name.toLowerCase();
    if (seen.has(key)) delete headers[seen.get(key)];
    seen.set(key, name);
    headers[name] = value;
  }
  return { headers, names: [...seen.values()] };
}

/** SHA-256 hex of an OpenAPI body (utf8). Used when the remote has no ETag. */
export function hashSpecBody(text) {
  return crypto.createHash("sha256").update(String(text ?? ""), "utf8").digest("hex");
}

/**
 * @param {{ etag?: string|null, lastModified?: string|null, hash?: string|null, text?: string|null, notModified?: boolean }} fetched
 * @returns {{ etag: string|null, lastModified: string|null, hash: string|null }}
 */
export function specWatchStateFromFetch(fetched) {
  const f = fetched || {};
  const hash = f.hash || (f.text != null && !f.notModified ? hashSpecBody(f.text) : null);
  return {
    etag: f.etag || null,
    lastModified: f.lastModified || null,
    hash: hash || null,
  };
}

/**
 * Decide whether a poll should regenerate.
 * 304 / same ETag / same body hash → "skip". Missing prev (first poll) → "regen" if a body is present.
 * @param {{ etag?: string|null, lastModified?: string|null, hash?: string|null }|null} prev
 * @param {{ notModified?: boolean, etag?: string|null, hash?: string|null, text?: string|null }} fetched
 * @returns {"skip"|"regen"}
 */
export function remoteSpecChange(prev, fetched) {
  if (!fetched) return "skip";
  if (fetched.notModified) return "skip";
  if (prev && prev.etag && fetched.etag && prev.etag === fetched.etag) return "skip";
  const nextHash = fetched.hash || (fetched.text != null ? hashSpecBody(fetched.text) : null);
  if (prev && prev.hash && nextHash && prev.hash === nextHash) return "skip";
  if (fetched.text == null && !nextHash) return "skip";
  return "regen";
}

/**
 * @param {{ etag?: string|null, lastModified?: string|null, hash?: string|null }|null} prev
 * @param {object} fetched
 */
export function nextWatchState(prev, fetched) {
  if (fetched && fetched.notModified) {
    return {
      etag: fetched.etag || (prev && prev.etag) || null,
      lastModified: fetched.lastModified || (prev && prev.lastModified) || null,
      hash: (prev && prev.hash) || null,
    };
  }
  return specWatchStateFromFetch(fetched);
}

/**
 * One remote poll: send If-None-Match / If-Modified-Since from prev, then classify skip vs regen.
 * @param {string} urlString
 * @param {{ headers?: Record<string,string>, prev?: object, timeoutMs?: number }} [opts]
 */
export async function pollRemoteOpenApi(urlString, opts = {}) {
  const prev = opts.prev || null;
  const fetchOpts = {
    headers: opts.headers && typeof opts.headers === "object" ? opts.headers : {},
  };
  if (opts.timeoutMs != null) fetchOpts.timeoutMs = opts.timeoutMs;
  if (prev && prev.etag) fetchOpts.ifNoneMatch = prev.etag;
  if (prev && prev.lastModified) fetchOpts.ifModifiedSince = prev.lastModified;
  const fetched = await fetchOpenApiText(urlString, fetchOpts);
  const change = remoteSpecChange(prev, fetched);
  const next = nextWatchState(prev, fetched);
  return { fetched, change, next };
}

export function isSensitiveHeaderName(name) {
  return SENSITIVE_HEADER_NAMES.has(String(name || "").toLowerCase());
}

function hostnameOf(url) {
  return String(url.hostname || "").replace(/^\[|\]$/g, "").toLowerCase();
}

export function isBlockedSpecHost(hostname) {
  const host = String(hostname || "").replace(/^\[|\]$/g, "").toLowerCase();
  if (BLOCKED_HOSTS.has(host)) return true;
  if (host.startsWith("::ffff:") && BLOCKED_HOSTS.has(host.slice("::ffff:".length))) return true;
  return false;
}

function assertAllowedUrl(url) {
  const host = hostnameOf(url);
  if (isBlockedSpecHost(host)) {
    throw new SpecFetchError(`fetch OpenAPI refused: blocked host ${host}`);
  }
}

function filenameFromUrl(url) {
  try {
    const p = decodeURIComponent(url.pathname || "");
    const base = path.basename(p);
    return base || url.href;
  } catch {
    return url.href;
  }
}

function readFileUrl(url, maxBytes) {
  let filePath;
  try {
    filePath = fileURLToPath(url);
  } catch (err) {
    throw new SpecFetchError(`invalid file url: ${url.href}: ${err.message || err}`);
  }
  let st;
  try {
    st = fs.statSync(filePath);
  } catch (err) {
    throw new SpecFetchError(`cannot read ${filePath}: ${err.message || err}`);
  }
  if (st.size > maxBytes) {
    throw new SpecFetchError(`fetch OpenAPI failed: body exceeds ${maxBytes} bytes`);
  }
  const text = fs.readFileSync(filePath, "utf8");
  return {
    text,
    url: url.href,
    filename: filePath,
    etag: null,
    lastModified: st.mtime.toUTCString(),
    hash: hashSpecBody(text),
    notModified: false,
    status: 200,
  };
}

async function readBodyLimited(res, maxBytes) {
  if (!res.body || typeof res.body.getReader !== "function") {
    const buf = Buffer.from(await res.arrayBuffer());
    if (buf.length > maxBytes) {
      throw new SpecFetchError(`fetch OpenAPI failed: body exceeds ${maxBytes} bytes`);
    }
    return buf;
  }
  const reader = res.body.getReader();
  const chunks = [];
  let n = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const len = value ? value.byteLength : 0;
    n += len;
    if (n > maxBytes) {
      try {
        await reader.cancel();
      } catch {
        /* ignore */
      }
      throw new SpecFetchError(`fetch OpenAPI failed: body exceeds ${maxBytes} bytes`);
    }
    chunks.push(Buffer.from(value));
  }
  return chunks.length ? Buffer.concat(chunks) : Buffer.alloc(0);
}

async function cancelBody(res) {
  if (res && res.body && typeof res.body.cancel === "function") {
    try {
      await res.body.cancel();
    } catch {
      /* ignore */
    }
  }
}

function requestHeaders(extraHeaders, cond = {}) {
  const headers = new Headers();
  headers.set("accept", "application/json, application/yaml, text/yaml, text/plain, */*");
  if (extraHeaders && typeof extraHeaders === "object") {
    for (const [k, v] of Object.entries(extraHeaders)) {
      if (v == null) continue;
      headers.set(k, String(v));
    }
  }
  // Conditional validators win over caller extras so --watch polls are consistent.
  if (cond.ifNoneMatch) headers.set("if-none-match", String(cond.ifNoneMatch));
  if (cond.ifModifiedSince) headers.set("if-modified-since", String(cond.ifModifiedSince));
  return headers;
}

function metaFromResponse(res, url) {
  return {
    etag: res && res.headers ? res.headers.get("etag") : null,
    lastModified: res && res.headers ? res.headers.get("last-modified") : null,
    filename: filenameFromUrl(url),
  };
}

/**
 * @param {string} urlString
 * @param {{ timeoutMs?: number, maxBytes?: number, maxRedirects?: number, headers?: Record<string, string>, ifNoneMatch?: string, ifModifiedSince?: string }} [opts]
 * @returns {Promise<{ text: string, url: string, filename: string, etag: string|null, lastModified: string|null, hash: string|null, notModified: boolean, status: number }>}
 */
export async function fetchOpenApiText(urlString, opts = {}) {
  const timeoutMs = opts.timeoutMs ?? SPEC_FETCH_TIMEOUT_MS;
  const maxBytes = opts.maxBytes ?? SPEC_FETCH_MAX_BYTES;
  const maxRedirects = opts.maxRedirects ?? SPEC_FETCH_MAX_REDIRECTS;
  const extraHeaders = opts.headers && typeof opts.headers === "object" ? opts.headers : {};
  const cond = {
    ifNoneMatch: opts.ifNoneMatch || "",
    ifModifiedSince: opts.ifModifiedSince || "",
  };

  let url;
  try {
    url = new URL(String(urlString || "").trim());
  } catch {
    throw new SpecFetchError(`invalid OpenAPI url: ${urlString}`);
  }

  if (url.protocol === "file:") {
    assertAllowedUrl(url);
    // Extra HTTP headers are not sent to file:// (ignored).
    return readFileUrl(url, maxBytes);
  }

  if (typeof fetch !== "function") {
    throw new SpecFetchError("fetch OpenAPI requires Node.js 18+");
  }

  const deadline = Date.now() + timeoutMs;
  let hops = 0;
  while (true) {
    assertAllowedUrl(url);
    if (url.protocol === "file:") {
      throw new SpecFetchError(`fetch OpenAPI refused: redirect to file url`);
    }
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      throw new SpecFetchError(
        `unsupported OpenAPI url scheme: ${url.protocol.replace(":", "")} (use http, https, or file)`,
      );
    }

    const remaining = deadline - Date.now();
    if (remaining <= 0) {
      throw new SpecFetchError(`fetch OpenAPI timed out after ${timeoutMs}ms`);
    }

    const ac = new AbortController();
    const timer = setTimeout(() => ac.abort(), remaining);
    let res;
    try {
      res = await fetch(url, {
        method: "GET",
        redirect: "manual",
        signal: ac.signal,
        headers: requestHeaders(extraHeaders, cond),
      });
    } catch (err) {
      const name = err && err.name;
      if (name === "AbortError" || (err && err.code === "ABORT_ERR")) {
        throw new SpecFetchError(`fetch OpenAPI timed out after ${timeoutMs}ms`);
      }
      throw new SpecFetchError(`fetch OpenAPI failed: ${err && err.message ? err.message : err}`);
    } finally {
      clearTimeout(timer);
    }

    if (res.status === 304) {
      await cancelBody(res);
      const meta = metaFromResponse(res, url);
      return {
        text: "",
        url: url.href,
        filename: meta.filename,
        etag: meta.etag,
        lastModified: meta.lastModified,
        hash: null,
        notModified: true,
        status: 304,
      };
    }

    if (res.status >= 300 && res.status < 400) {
      const loc = res.headers.get("location");
      await cancelBody(res);
      if (!loc) {
        throw new SpecFetchError(`fetch OpenAPI failed: HTTP ${res.status} (redirect without Location)`, {
          status: res.status,
        });
      }
      hops += 1;
      if (hops > maxRedirects) {
        throw new SpecFetchError(`fetch OpenAPI failed: too many redirects (max ${maxRedirects})`);
      }
      let next;
      try {
        next = new URL(loc, url);
      } catch {
        throw new SpecFetchError(`fetch OpenAPI failed: invalid redirect Location`);
      }
      url = next;
      continue;
    }

    if (res.status < 200 || res.status >= 300) {
      await cancelBody(res);
      throw new SpecFetchError(`fetch OpenAPI failed: HTTP ${res.status}`, { status: res.status });
    }

    const cl = res.headers.get("content-length");
    if (cl != null && cl !== "" && Number(cl) > maxBytes) {
      await cancelBody(res);
      throw new SpecFetchError(`fetch OpenAPI failed: body exceeds ${maxBytes} bytes`);
    }

    const buf = await readBodyLimited(res, maxBytes);
    const text = buf.toString("utf8");
    const meta = metaFromResponse(res, url);
    return {
      text,
      url: url.href,
      filename: meta.filename,
      etag: meta.etag,
      lastModified: meta.lastModified,
      hash: hashSpecBody(text),
      notModified: false,
      status: res.status,
    };
  }
}
