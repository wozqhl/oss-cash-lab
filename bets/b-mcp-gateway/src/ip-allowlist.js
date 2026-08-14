/** Per-tenant client IP allowlist: exact IPv4/IPv6 + simple IPv4 CIDR (/8,/16,/24). */

/** Normalize Node remoteAddress / XFF hop to a comparable IP string. */
export function normalizeIp(raw) {
  if (raw == null) return null;
  let s = String(raw).trim();
  if (!s) return null;
  // strip surrounding brackets for IPv6 literals like [::1]
  if (s.startsWith("[") && s.includes("]")) {
    s = s.slice(1, s.indexOf("]"));
  }
  // strip :port for IPv4 host:port (not for bare IPv6)
  if (/^\d{1,3}(\.\d{1,3}){3}:\d+$/.test(s)) {
    s = s.slice(0, s.lastIndexOf(":"));
  }
  // IPv4-mapped IPv6
  if (s.toLowerCase().startsWith("::ffff:")) {
    s = s.slice(7);
  }
  return s;
}

/** Client IP: first X-Forwarded-For hop, else socket remoteAddress. */
export function clientIpFromReq(req) {
  const xff = req?.headers?.["x-forwarded-for"];
  if (xff) {
    const raw = Array.isArray(xff) ? xff[0] : String(xff);
    const first = raw.split(",")[0];
    const n = normalizeIp(first);
    if (n) return n;
  }
  const remote =
    req?.socket?.remoteAddress ||
    req?.connection?.remoteAddress ||
    null;
  return normalizeIp(remote);
}

function ipv4ToInt(ip) {
  const parts = ip.split(".");
  if (parts.length !== 4) return null;
  let n = 0;
  for (const p of parts) {
    if (!/^\d{1,3}$/.test(p)) return null;
    const v = Number(p);
    if (v < 0 || v > 255) return null;
    n = (n << 8) + v;
  }
  return n >>> 0;
}

function isIpv4(ip) {
  return /^\d{1,3}(\.\d{1,3}){3}$/.test(ip);
}

function isIpv6(ip) {
  // loose: contains ':' and not IPv4
  return typeof ip === "string" && ip.includes(":") && !isIpv4(ip);
}

function cidrMaskBits(prefix) {
  if (prefix === 8 || prefix === 16 || prefix === 24) return prefix;
  return null;
}

/** True if entry (exact or IPv4 CIDR) matches ip. */
export function matchAllowlistEntry(ip, entry) {
  const needle = normalizeIp(ip);
  const rule = String(entry || "").trim();
  if (!needle || !rule) return false;

  if (rule.includes("/")) {
    const [netRaw, prefRaw] = rule.split("/");
    const net = normalizeIp(netRaw);
    const pref = Number(prefRaw);
    const bits = cidrMaskBits(pref);
    if (!net || bits == null || !isIpv4(needle) || !isIpv4(net)) return false;
    const ipInt = ipv4ToInt(needle);
    const netInt = ipv4ToInt(net);
    if (ipInt == null || netInt == null) return false;
    const mask = bits === 0 ? 0 : ((0xffffffff << (32 - bits)) >>> 0);
    return (ipInt & mask) === (netInt & mask);
  }

  const want = normalizeIp(rule);
  if (!want) return false;
  // exact match (IPv4 or IPv6); compare case-insensitive for IPv6 hex
  if (isIpv6(needle) || isIpv6(want)) {
    return needle.toLowerCase() === want.toLowerCase();
  }
  return needle === want;
}

/**
 * If allowlist is a non-empty array, require ip to match an entry.
 * Missing / null / empty allowlist => allow (no restriction).
 */
export function ipAllowed(ip, allowlist) {
  if (!Array.isArray(allowlist) || allowlist.length === 0) return true;
  if (!ip) return false;
  return allowlist.some((entry) => matchAllowlistEntry(ip, entry));
}

/** Enforce tenant.ipAllowlist; returns error body or null if ok. */
export function checkTenantIpAllowlist(req, tenant) {
  if (!tenant) return null;
  const list = tenant.ipAllowlist;
  if (!Array.isArray(list) || list.length === 0) return null;
  const ip = clientIpFromReq(req);
  if (ipAllowed(ip, list)) return null;
  return {
    status: 403,
    body: { error: "forbidden", reason: "ip_denied" },
  };
}
