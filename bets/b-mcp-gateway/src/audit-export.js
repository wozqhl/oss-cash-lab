/** Read JSONL audit logs and export as JSON pack, CSV, admin Markdown, or admin HTML (stdlib only). */

import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import zlib from "node:zlib";

const CSV_COLUMNS = [
  "ts",
  "tenantId",
  "tool",
  "allow",
  "reason",
  "via",
  "arguments",
  "result",
  "argumentKeysHash",
  "requestId",
];

/** SIEM/admin CSV: metadata only — never arguments, result, headers, or tokens. */
const ADMIN_CSV_COLUMNS = [
  "ts",
  "tenantId",
  "tool",
  "allow",
  "reason",
  "via",
  "requestId",
];

/** Parse common truthy/falsey query or CLI strings. Returns null if unset/unknown. */
export function parseBoolFlag(value) {
  if (value === null || value === undefined || value === "") return null;
  if (value === true || value === false) return value;
  const s = String(value).trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(s)) return true;
  if (["0", "false", "no", "off"].includes(s)) return false;
  return null;
}

/** Resolve whether to redact: explicit flag wins, else policy.export.redactDefault. */
export function resolveRedact({ flag, policy } = {}) {
  const parsed = parseBoolFlag(flag);
  if (parsed !== null) return parsed;
  return Boolean(policy?.export?.redactDefault);
}

/** Whether JSONL writes should store redacted arguments/result (default false). */
export function resolveRedactOnWrite(policy) {
  return Boolean(policy?.audit?.redactOnWrite);
}

/** In-memory audit ring default. Generous so demos never drop; 0 = unlimited (dangerous). */
export const DEFAULT_AUDIT_MAX_EVENTS = 10000;
export const ENV_AUDIT_MAX_EVENTS = "AUDIT_MAX_EVENTS";

/** CLI `--audit-max` wins when provided; else env AUDIT_MAX_EVENTS; else 10000. `0` = unlimited. */
export function resolveAuditMaxEvents(raw, env = process.env) {
  const source = raw == null || raw === "" ? env?.[ENV_AUDIT_MAX_EVENTS] : raw;
  if (source == null || source === "") return DEFAULT_AUDIT_MAX_EVENTS;
  const n = Number(source);
  if (!Number.isFinite(n) || n < 0) return DEFAULT_AUDIT_MAX_EVENTS;
  return Math.floor(n);
}

/**
 * Push one event onto an in-memory ring buffer.
 * When maxEvents > 0 and length exceeds it, drop oldest. maxEvents 0 = unlimited.
 * Mutates `events` when it is an array; webhook fan-out is the caller's job.
 */
export function pushAuditEvent(events, event, maxEvents = DEFAULT_AUDIT_MAX_EVENTS) {
  const buf = Array.isArray(events) ? events : [];
  if (event != null) buf.push(event);
  const max =
    typeof maxEvents === "number" && Number.isFinite(maxEvents)
      ? Math.floor(maxEvents)
      : DEFAULT_AUDIT_MAX_EVENTS;
  if (max > 0 && buf.length > max) {
    buf.splice(0, buf.length - max);
  }
  return buf;
}

function parseBoundMs(value, code) {
  if (value == null || value === "") return null;
  const ms = Date.parse(String(value));
  if (Number.isNaN(ms)) {
    const err = new Error(code);
    err.code = code;
    throw err;
  }
  return ms;
}

/** Filter an in-memory (or JSONL-parsed) event list. Same tenant/tool/limit/since/until as readAuditEvents. */
export function filterAuditEvents(events, { tenant, tool, limit, since, until } = {}) {
  let filtered = Array.isArray(events) ? events : [];
  if (tenant) filtered = filtered.filter((e) => e.tenantId === tenant);
  if (tool) filtered = filtered.filter((e) => e.tool === tool);
  if (since != null && since !== "") {
    const sinceMs = parseBoundMs(since, "invalid_since");
    filtered = filtered.filter((e) => {
      if (!e?.ts) return false;
      const t = Date.parse(e.ts);
      return !Number.isNaN(t) && t >= sinceMs;
    });
  }
  if (until != null && until !== "") {
    const untilMs = parseBoundMs(until, "invalid_until");
    filtered = filtered.filter((e) => {
      if (!e?.ts) return false;
      const t = Date.parse(e.ts);
      return !Number.isNaN(t) && t <= untilMs;
    });
  }
  if (limit != null && limit !== "") {
    const n = Math.max(0, Math.min(Number(limit) || 0, 1_000_000));
    if (n > 0) filtered = filtered.slice(-n);
  }
  return filtered;
}

export function readAuditEvents(auditPath, { tenant, tool, limit, since, until } = {}) {
  if (!auditPath || !fs.existsSync(auditPath)) return [];
  const lines = fs.readFileSync(auditPath, "utf8").split("\n").filter(Boolean);
  const events = [];
  for (const line of lines) {
    try {
      events.push(JSON.parse(line));
    } catch {
      /* skip bad lines */
    }
  }
  return filterAuditEvents(events, { tenant, tool, limit, since, until });
}

/** Load JSONL into a ring (last maxEvents). Used to seed the live buffer on serve start. */
export function loadAuditRing(auditPath, maxEvents = DEFAULT_AUDIT_MAX_EVENTS) {
  const all = readAuditEvents(auditPath);
  const max =
    typeof maxEvents === "number" && Number.isFinite(maxEvents)
      ? Math.floor(maxEvents)
      : DEFAULT_AUDIT_MAX_EVENTS;
  if (max > 0 && all.length > max) return all.slice(-max);
  return all;
}

function hashArgumentKeys(args) {
  if (!args || typeof args !== "object" || Array.isArray(args)) return null;
  const keys = Object.keys(args).sort();
  if (!keys.length) return crypto.createHash("sha256").update("").digest("hex");
  return crypto.createHash("sha256").update(keys.join("\0")).digest("hex");
}

/** Strip/mask sensitive payload fields; keep tool, decision, tenantId, ts, reason, via. */
export function redactEvent(event) {
  if (!event || typeof event !== "object") return event;
  const out = { ...event };
  const args = out.arguments ?? out.args;
  if ("arguments" in out || "args" in out) {
    const keysHash = hashArgumentKeys(args);
    if (keysHash) out.argumentKeysHash = keysHash;
    out.arguments = "[REDACTED]";
    delete out.args;
  }
  if ("result" in out) {
    out.result = "[REDACTED]";
  }
  return out;
}

export function redactEvents(events) {
  return (events || []).map(redactEvent);
}

function csvEscape(value) {
  if (value === null || value === undefined) return "";
  const s =
    typeof value === "string"
      ? value
      : typeof value === "object"
        ? JSON.stringify(value)
        : String(value);
  if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

export function eventsToCsv(events, columns = CSV_COLUMNS) {
  const cols = Array.isArray(columns) && columns.length ? columns : CSV_COLUMNS;
  const rows = [cols.join(",")];
  for (const e of events || []) {
    rows.push(
      cols.map((col) => {
        if (col === "arguments") return csvEscape(e.arguments ?? e.args ?? null);
        if (col === "result") return csvEscape(e.result ?? null);
        if (col === "argumentKeysHash") return csvEscape(e.argumentKeysHash ?? "");
        if (col === "allow") {
          if (e.allow === true) return "true";
          if (e.allow === false) return "false";
          return "";
        }
        return csvEscape(e[col]);
      }).join(",")
    );
  }
  return rows.join("\n") + (rows.length ? "\n" : "");
}

/** Admin/SIEM CSV: header + rows, empty → header only. Never emits args/result/tokens. */
export function eventsToAdminCsv(events) {
  return eventsToCsv(events, ADMIN_CSV_COLUMNS);
}

export const ADMIN_MD_HEADING = "# Audit";

function mdEscapeCell(value) {
  if (value === null || value === undefined) return "";
  const s =
    typeof value === "string"
      ? value
      : typeof value === "object"
        ? JSON.stringify(value)
        : String(value);
  return s.replace(/\r\n/g, " ").replace(/\n/g, " ").replace(/\r/g, " ").replace(/\|/g, "\\|");
}

function adminCell(event, col) {
  if (col === "allow") {
    if (event?.allow === true) return "true";
    if (event?.allow === false) return "false";
    return "";
  }
  return event?.[col];
}

/** Admin/SIEM Markdown: `# Audit` + GFM table. Same columns as admin CSV. Empty → heading + header. Never args/result/tokens. */
export function eventsToAdminMd(events) {
  const cols = ADMIN_CSV_COLUMNS;
  const header = "| " + cols.join(" | ") + " |";
  const sep = "| " + cols.map(() => "---").join(" | ") + " |";
  const lines = [ADMIN_MD_HEADING, header, sep];
  for (const e of events || []) {
    lines.push("| " + cols.map((col) => mdEscapeCell(adminCell(e, col))).join(" | ") + " |");
  }
  return lines.join("\n") + "\n";
}

export const ADMIN_HTML_HEADING = "Audit";

/** Escape HTML text/attributes (`& < > " '`). Never used for raw bodies/tokens. */
function htmlEscape(value) {
  if (value === null || value === undefined) return "";
  const s =
    typeof value === "string"
      ? value
      : typeof value === "object"
        ? JSON.stringify(value)
        : String(value);
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#x27;");
}

const ADMIN_HTML_STYLE =
  "body{font-family:ui-sans-serif,system-ui,sans-serif;margin:2rem;color:#111;max-width:72rem}" +
  "h1{font-size:1.25rem}" +
  "table{border-collapse:collapse;margin:1rem 0;min-width:28rem}" +
  "th,td{border:1px solid #ddd;padding:.4rem .6rem;text-align:left}" +
  "th{background:#f5f5f5}" +
  ".allow{background:#f1faf3}" +
  ".allow td.decision{color:#0a7a28;font-weight:700}" +
  ".deny{background:#fdf2f2}" +
  ".deny td.decision{color:#b00020;font-weight:700}" +
  ".meta{color:#555;font-size:.9rem}";

function htmlRowClass(event) {
  if (event?.allow === true) return "allow";
  if (event?.allow === false) return "deny";
  return "";
}

/** Admin/SIEM HTML: `<h1>Audit</h1>` + table. Same columns as admin CSV. Empty → heading + “no events” + header. Never args/result/tokens. No CDN. */
export function eventsToAdminHtml(events) {
  const cols = ADMIN_CSV_COLUMNS;
  const items = Array.isArray(events) ? events : [];
  const rowHtml = [];
  for (const e of items) {
    const cls = htmlRowClass(e);
    const tds = cols
      .map((col) => {
        const cellClass = col === "allow" ? ' class="decision"' : "";
        return "<td" + cellClass + ">" + htmlEscape(adminCell(e, col)) + "</td>";
      })
      .join("");
    rowHtml.push("<tr" + (cls ? ' class="' + cls + '"' : "") + ">" + tds + "</tr>");
  }
  const tbody = rowHtml.length ? rowHtml.join("\n") + "\n" : "";
  const emptyNote = items.length === 0 ? "<p>no events</p>\n" : "";
  const n = items.length;
  return (
    "<!DOCTYPE html>\n" +
    '<html lang="en">\n' +
    "<head>\n" +
    '<meta charset="utf-8">\n' +
    "<title>Audit · local list</title>\n" +
    "<style>\n" +
    ADMIN_HTML_STYLE +
    "\n</style>\n" +
    "</head>\n" +
    "<body>\n" +
    "<h1>" +
    ADMIN_HTML_HEADING +
    "</h1>\n" +
    '<p class="meta">OSS local serve · SIEM-safe columns · self-contained HTML · no CDN</p>\n' +
    emptyNote +
    '<p class="meta">' +
    n +
    " row(s)</p>\n" +
    "<table>\n" +
    "<thead><tr>" +
    cols.map((c) => "<th>" + htmlEscape(c) + "</th>").join("") +
    "</tr></thead>\n" +
    "<tbody>\n" +
    tbody +
    "</tbody>\n" +
    "</table>\n" +
    '<p class="meta">Generated by mcp-gateway</p>\n' +
    "</body>\n" +
    "</html>\n"
  );
}

export function eventsToJsonPack(events, meta = {}) {
  return {
    ok: true,
    format: "json",
    count: events.length,
    exportedAt: new Date().toISOString(),
    ...meta,
    events,
  };
}

/** Default allowed: json | csv | md | html. Pass `allowed` to restrict (e.g. tenant `/audit/export` stays json|csv). */
export function normalizeExportFormat(format, allowed) {
  const f = String(format || "json").toLowerCase();
  const ok = Array.isArray(allowed) && allowed.length ? allowed : ["json", "csv", "md", "html"];
  if (ok.includes(f)) return f;
  throw new Error("unsupported_format");
}

export function resolveAuditPath({ audit, configPath, policy, cwd = process.cwd() } = {}) {
  if (audit) {
    return path.isAbsolute(audit) ? audit : path.resolve(cwd, audit);
  }
  if (policy?.auditPath) {
    const p = policy.auditPath;
    return path.isAbsolute(p) ? p : path.resolve(cwd, p);
  }
  if (configPath) {
    const beside = path.resolve(path.dirname(configPath), "../data/audit.jsonl");
    if (fs.existsSync(beside)) return beside;
  }
  return path.resolve(cwd, "data/audit.jsonl");
}

/** gzip-compress a string or Buffer (stdlib zlib). */
export function gzipBytes(input) {
  const buf = Buffer.isBuffer(input) ? input : Buffer.from(String(input), "utf8");
  return zlib.gzipSync(buf);
}

/**
 * Whether the audit export should be gzip-compressed.
 * Explicit gzip query/flag wins (gzip=0 disables even if Accept-Encoding: gzip).
 * Else Accept-Encoding containing gzip / x-gzip.
 */
export function wantsGzip({ gzipQuery, acceptEncoding } = {}) {
  const flagged = parseBoolFlag(gzipQuery);
  if (flagged === true) return true;
  if (flagged === false) return false;
  const ae = Array.isArray(acceptEncoding)
    ? acceptEncoding.join(",")
    : String(acceptEncoding || "");
  return /\b(?:x-)?gzip\b/i.test(ae);
}

/** Append .gz to a download filename when gzip is on (idempotent). */
export function gzipFilename(name, gzip) {
  const base = String(name || "audit.json");
  if (!gzip) return base;
  if (base.toLowerCase().endsWith(".gz")) return base;
  return base + ".gz";
}

export function writeExportFile(outPath, body, format, { gzip = false } = {}) {
  const abs = path.isAbsolute(outPath) ? outPath : path.resolve(process.cwd(), outPath);
  fs.mkdirSync(path.dirname(abs), { recursive: true });
  const text =
    format === "csv" || format === "md" || format === "html"
      ? body
      : typeof body === "string"
        ? body
        : JSON.stringify(body, null, 2) + "\n";
  // Gzip stays on JSON/CSV (and md if the caller asked). Do not gzip HTML.
  if (gzip && format !== "html") {
    fs.writeFileSync(abs, gzipBytes(text));
  } else {
    fs.writeFileSync(abs, text, "utf8");
  }
  return abs;
}

export { CSV_COLUMNS, ADMIN_CSV_COLUMNS };
