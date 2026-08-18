/** Minimal OpenAPI helper: list ops + MCP tools + TS/Python/Go/Java/Rust/C#/Kotlin/Swift/Ruby/PHP client stubs.
 * OpenAPI 3.0.x and 3.1.x accepted (paths only; 3.1 `webhooks` ignored). Not a full JSON Schema 2020-12 rewrite.
 */
export function isSupportedOpenApiVersion(ver) {
  const s = String(ver || "").trim();
  return /^3\.(0|1)(\.[0-9]+)*$/.test(s);
}

function resolveLocalRef(spec, node) {
  if (!node || typeof node !== "object") return node;
  const ref = node.$ref;
  if (typeof ref === "string" && ref.startsWith("#/")) {
    let cur = spec;
    for (const part of ref.slice(2).split("/")) {
      const key = part.replace(/~1/g, "/").replace(/~0/g, "~");
      cur = cur?.[key];
      if (cur == null) return node;
    }
    return cur;
  }
  return node;
}

/** OAS 3.1 `type: [string, "null"]` (and similar) → scalar type + nullable (optional). */
export function unwrapNullUnion(schema) {
  if (!schema || typeof schema !== "object" || Array.isArray(schema)) return schema;
  const t = schema.type;
  if (!Array.isArray(t)) return schema;
  const hasNull = t.includes("null");
  const nonNull = t.filter((x) => x !== "null");
  const out = { ...schema };
  if (nonNull.length === 1) out.type = nonNull[0];
  else if (nonNull.length === 0) out.type = "string";
  else out.type = nonNull[0];
  if (hasNull) out.nullable = true;
  return out;
}

function isOptionalSchema(schema) {
  if (!schema || typeof schema !== "object") return false;
  if (schema.nullable) return true;
  if (Array.isArray(schema.type) && schema.type.includes("null")) return true;
  return false;
}

/** OAS 3.1 JSON Schema `examples` (array) or OAS media-type `examples` map vs 3.0 `example`. */
export function schemaExample(node) {
  if (!node || typeof node !== "object") return undefined;
  if (Object.prototype.hasOwnProperty.call(node, "example")) return node.example;
  const ex = node.examples;
  if (Array.isArray(ex) && ex.length) return ex[0];
  if (ex && typeof ex === "object") {
    const vals = Object.values(ex);
    if (!vals.length) return undefined;
    const first = vals[0];
    if (first && typeof first === "object" && Object.prototype.hasOwnProperty.call(first, "value")) {
      return first.value;
    }
    return first;
  }
  return undefined;
}

function decorateSchema(schema) {
  const unwrapped = unwrapNullUnion(schema);
  if (!unwrapped || typeof unwrapped !== "object") return unwrapped || { type: "string" };
  const ex = schemaExample(unwrapped);
  if (ex !== undefined && !Object.prototype.hasOwnProperty.call(unwrapped, "example")) {
    return { ...unwrapped, example: ex };
  }
  return unwrapped;
}


/** Parse one OpenAPI security scheme. Supports http bearer + apiKey header/query.
 * oauth2 / openIdConnect (and other types) are skipped — no fake tokens.
 */
export function parseSecurityScheme(name, scheme) {
  if (!scheme || typeof scheme !== "object") return { skip: true, name, type: "unknown", reason: "invalid" };
  const type = String(scheme.type || "").toLowerCase();
  if (type === "http") {
    const httpScheme = String(scheme.scheme || "").toLowerCase();
    if (httpScheme === "bearer") {
      return { scheme: { name, kind: "bearer" } };
    }
    return { skip: true, name, type: "http", reason: "unsupported http scheme: " + (httpScheme || "(empty)") };
  }
  if (type === "apikey") {
    const inn = String(scheme.in || "header").toLowerCase();
    const paramName = String(scheme.name || "").trim();
    if (!paramName) return { skip: true, name, type: "apiKey", reason: "missing name" };
    if (inn === "header" || inn === "query") {
      return { scheme: { name, kind: "apiKey", in: inn, paramName } };
    }
    return { skip: true, name, type: "apiKey", reason: "unsupported in: " + inn };
  }
  if (type === "oauth2" || type === "openidconnect") {
    return { skip: true, name, type, reason: "oauth2/openIdConnect skipped (no fake tokens)" };
  }
  return { skip: true, name, type: type || "unknown", reason: "unsupported" };
}

/** components.securitySchemes → supported (bearer / apiKey) + skipped (oauth2 / openIdConnect / …). */
export function listSecuritySchemes(spec) {
  const raw = spec?.components?.securitySchemes;
  const supported = [];
  const skipped = [];
  if (!raw || typeof raw !== "object") return { supported, skipped };
  for (const [name, node] of Object.entries(raw)) {
    const parsed = parseSecurityScheme(name, resolveLocalRef(spec, node));
    if (parsed.scheme) supported.push(parsed.scheme);
    else skipped.push({ name: parsed.name || name, type: parsed.type, reason: parsed.reason });
  }
  return { supported, skipped };
}

function schemeKey(s) {
  return String(s.kind || "") + "\\0" + String(s.in || "") + "\\0" + String(s.paramName || "") + "\\0" + String(s.name || "");
}

/** Resolve root or operation `security` against supported schemes. Empty / missing → []. */
export function resolveOpSecurity(spec, opNode) {
  const hasOp = opNode && typeof opNode === "object" && Object.prototype.hasOwnProperty.call(opNode, "security");
  const reqs = hasOp ? opNode.security : spec?.security;
  if (!Array.isArray(reqs)) return [];
  const schemes = [];
  const seen = new Set();
  for (const req of reqs) {
    if (!req || typeof req !== "object") continue;
    for (const name of Object.keys(req)) {
      const raw = spec?.components?.securitySchemes?.[name];
      const parsed = parseSecurityScheme(name, resolveLocalRef(spec, raw));
      if (!parsed.scheme) continue;
      const key = schemeKey(parsed.scheme);
      if (seen.has(key)) continue;
      seen.add(key);
      schemes.push(parsed.scheme);
    }
  }
  return schemes;
}

/** Unique supported schemes referenced by any operation (constructor / MCP env). */
export function collectClientAuth(ops) {
  const out = [];
  const seen = new Set();
  for (const op of ops || []) {
    for (const s of op.security || []) {
      if (!s || !s.kind) continue;
      const key = schemeKey(s);
      if (seen.has(key)) continue;
      seen.add(key);
      out.push(s);
    }
  }
  return out;
}

function authFlags(ops) {
  const schemes = collectClientAuth(ops);
  return {
    schemes,
    hasBearer: schemes.some((s) => s.kind === "bearer"),
    headerKeys: schemes.filter((s) => s.kind === "apiKey" && s.in === "header"),
    queryKeys: schemes.filter((s) => s.kind === "apiKey" && s.in === "query"),
    any: schemes.length > 0,
  };
}

/** Per-operation security (empty / missing / only {} → no attach). */
function opAuthFlags(op) {
  const schemes = Array.isArray(op?.security) ? op.security.filter((s) => s && s.kind) : [];
  return {
    schemes,
    hasBearer: schemes.some((s) => s.kind === "bearer"),
    headerKeys: schemes.filter((s) => s.kind === "apiKey" && s.in === "header"),
    queryKeys: schemes.filter((s) => s.kind === "apiKey" && s.in === "query"),
    any: schemes.length > 0,
  };
}

function compactToolSecurity(op) {
  return (op?.security || []).filter((s) => s && s.kind).map((s) => {
    if (s.kind === "bearer") return { kind: "bearer" };
    return { kind: s.kind, in: s.in || "", paramName: s.paramName || "" };
  });
}

function tsAuthSuffix(op, clientHasAuth) {
  if (!clientHasAuth) return "";
  const a = opAuthFlags(op);
  if (!a.any) return "";
  const parts = [];
  if (a.hasBearer) parts.push("bearer: true");
  if (a.headerKeys.length) parts.push("headers: " + JSON.stringify(a.headerKeys.map((s) => s.paramName)));
  if (a.queryKeys.length) parts.push("query: " + JSON.stringify(a.queryKeys.map((s) => s.paramName)));
  return ", { " + parts.join(", ") + " }";
}

function pyAuthSuffix(op, clientHasAuth) {
  if (!clientHasAuth) return "";
  const a = opAuthFlags(op);
  if (!a.any) return "";
  const parts = [];
  if (a.hasBearer) parts.push('"bearer": True');
  if (a.headerKeys.length) parts.push('"headers": ' + JSON.stringify(a.headerKeys.map((s) => s.paramName)));
  if (a.queryKeys.length) parts.push('"query": ' + JSON.stringify(a.queryKeys.map((s) => s.paramName)));
  return ", {" + parts.join(", ") + "}";
}

function goAuthSuffix(op, clientHasAuth) {
  if (!clientHasAuth) return "";
  const a = opAuthFlags(op);
  if (!a.any) return ", nil";
  const fields = [];
  if (a.hasBearer) fields.push("Bearer: true");
  if (a.headerKeys.length) {
    fields.push("Headers: []string{" + a.headerKeys.map((s) => JSON.stringify(s.paramName)).join(", ") + "}");
  }
  if (a.queryKeys.length) {
    fields.push("Query: []string{" + a.queryKeys.map((s) => JSON.stringify(s.paramName)).join(", ") + "}");
  }
  return ", &reqAuth{" + fields.join(", ") + "}";
}


function jvmAuthArgs(op, clientHasAuth) {
  if (!clientHasAuth) return "";
  const a = opAuthFlags(op);
  if (!a.any) return ", false, null, null";
  const bearer = a.hasBearer ? "true" : "false";
  const headers = a.headerKeys.length
    ? "new String[]{" + a.headerKeys.map((s) => JSON.stringify(s.paramName)).join(", ") + "}"
    : "null";
  const query = a.queryKeys.length
    ? "new String[]{" + a.queryKeys.map((s) => JSON.stringify(s.paramName)).join(", ") + "}"
    : "null";
  return ", " + bearer + ", " + headers + ", " + query;
}

function csharpAuthArgs(op, clientHasAuth) {
  if (!clientHasAuth) return "";
  const a = opAuthFlags(op);
  if (!a.any) return ", false, null, null";
  const bearer = a.hasBearer ? "true" : "false";
  const headers = a.headerKeys.length
    ? "new string[]{" + a.headerKeys.map((s) => JSON.stringify(s.paramName)).join(", ") + "}"
    : "null";
  const query = a.queryKeys.length
    ? "new string[]{" + a.queryKeys.map((s) => JSON.stringify(s.paramName)).join(", ") + "}"
    : "null";
  return ", " + bearer + ", " + headers + ", " + query;
}
function rustAuthArgs(op, clientHasAuth) {
  if (!clientHasAuth) return "";
  const a = opAuthFlags(op);
  if (!a.any) return ", false, &[], &[]";
  const bearer = a.hasBearer ? "true" : "false";
  const headers = a.headerKeys.length
    ? "&[" + a.headerKeys.map((s) => JSON.stringify(s.paramName)).join(", ") + "]"
    : "&[]";
  const query = a.queryKeys.length
    ? "&[" + a.queryKeys.map((s) => JSON.stringify(s.paramName)).join(", ") + "]"
    : "&[]";
  return ", " + bearer + ", " + headers + ", " + query;
}

function swiftAuthArgs(op, clientHasAuth) {
  if (!clientHasAuth) return "";
  const a = opAuthFlags(op);
  if (!a.any) return ", authBearer: false, authHeaders: nil, authQuery: nil";
  const bearer = a.hasBearer ? "true" : "false";
  const headers = a.headerKeys.length
    ? "[" + a.headerKeys.map((s) => JSON.stringify(s.paramName)).join(", ") + "]"
    : "nil";
  const query = a.queryKeys.length
    ? "[" + a.queryKeys.map((s) => JSON.stringify(s.paramName)).join(", ") + "]"
    : "nil";
  return ", authBearer: " + bearer + ", authHeaders: " + headers + ", authQuery: " + query;
}

function rubyAuthArgs(op, clientHasAuth) {
  if (!clientHasAuth) return "";
  const a = opAuthFlags(op);
  if (!a.any) return ", false, nil, nil";
  const bearer = a.hasBearer ? "true" : "false";
  const headers = a.headerKeys.length
    ? "[" + a.headerKeys.map((s) => JSON.stringify(s.paramName)).join(", ") + "]"
    : "nil";
  const query = a.queryKeys.length
    ? "[" + a.queryKeys.map((s) => JSON.stringify(s.paramName)).join(", ") + "]"
    : "nil";
  return ", " + bearer + ", " + headers + ", " + query;
}

function phpAuthArgs(op, clientHasAuth) {
  if (!clientHasAuth) return "";
  const a = opAuthFlags(op);
  if (!a.any) return ", false, null, null";
  const bearer = a.hasBearer ? "true" : "false";
  const headers = a.headerKeys.length
    ? "array(" + a.headerKeys.map((s) => JSON.stringify(s.paramName)).join(", ") + ")"
    : "null";
  const query = a.queryKeys.length
    ? "array(" + a.queryKeys.map((s) => JSON.stringify(s.paramName)).join(", ") + ")"
    : "null";
  return ", " + bearer + ", " + headers + ", " + query;
}


export function listOperations(spec) {
  // OpenAPI 3.1 `webhooks` is ignored — only `paths` become SDK methods / MCP tools.
  const paths = spec?.paths || {};
  const ops = [];
  for (const [path, item] of Object.entries(paths)) {
    for (const method of ["get", "post", "put", "patch", "delete"]) {
      if (item?.[method]) {
        const op = item[method];
        const parameters = [
          ...(item.parameters || []),
          ...(op.parameters || []),
        ].map((p) => resolveLocalRef(spec, p));
        const props = {};
        const required = [];
        for (const p of parameters) {
          if (!p?.name) continue;
          const raw = resolveLocalRef(spec, p.schema || { type: "string" });
          const schema = decorateSchema(raw);
          props[p.name] = schema;
          if (p.required && !isOptionalSchema(schema) && !isOptionalSchema(raw)) required.push(p.name);
        }
        const media =
          op.requestBody?.content?.["application/json"] ||
          op.requestBody?.content?.["application/*+json"] ||
          {};
        const bodyRaw = media.schema;
        const bodySchema = resolveLocalRef(spec, bodyRaw);
        if (bodySchema?.properties) {
          for (const [k, v] of Object.entries(bodySchema.properties)) {
            const raw = resolveLocalRef(spec, v);
            props[k] = decorateSchema(raw);
          }
          for (const r of bodySchema.required || []) {
            if (isOptionalSchema(props[r])) continue;
            if (!required.includes(r)) required.push(r);
          }
        }
        void schemaExample(media);
        ops.push({
          path,
          method: method.toUpperCase(),
          operationId: op.operationId || `${method}_${path.replace(/\W+/g, "_")}`,
          summary: op.summary || "",
          parameters,
          inputSchema: {
            type: "object",
            properties: props,
            ...(required.length ? { required } : {}),
          },
          security: resolveOpSecurity(spec, op),
        });
      }
    }
  }
  return ops;
}

export function toMcpTools(ops) {
  return ops.map((op) => ({
    name: op.operationId,
    description: op.summary || `${op.method} ${op.path}`,
    inputSchema: op.inputSchema || { type: "object", properties: {} },
  }));
}

/** Keep MCP inputSchema to string/number/boolean/object; skip array/oneOf/etc. */
export function simplifyJsonSchema(schema) {
  if (!schema || typeof schema !== "object") return { type: "string" };
  const s = unwrapNullUnion(schema);
  const t = s.type;
  if (t === "string") return { type: "string" };
  if (t === "number" || t === "integer") return { type: "number" };
  if (t === "boolean") return { type: "boolean" };
  if (t === "object" || (s.properties && typeof s.properties === "object")) {
    const properties = {};
    for (const [k, v] of Object.entries(s.properties || {})) {
      const simple = simplifyJsonSchema(v);
      if (simple) properties[k] = simple;
    }
    const out = { type: "object", properties };
    if (Array.isArray(s.required) && s.required.length) {
      const req = s.required.filter((n) => {
        if (!Object.prototype.hasOwnProperty.call(properties, n)) return false;
        const raw = s.properties?.[n];
        if (isOptionalSchema(raw) || isOptionalSchema(unwrapNullUnion(raw))) return false;
        return true;
      });
      if (req.length) out.required = req;
    }
    return out;
  }
  return null;
}

function simplifyInputSchema(inputSchema) {
  const base = inputSchema && typeof inputSchema === "object" ? inputSchema : { type: "object", properties: {} };
  const properties = {};
  for (const [k, v] of Object.entries(base.properties || {})) {
    const simple = simplifyJsonSchema(v);
    if (simple) properties[k] = simple;
  }
  const out = { type: "object", properties };
  if (Array.isArray(base.required) && base.required.length) {
    const req = base.required.filter((n) => {
      if (!Object.prototype.hasOwnProperty.call(properties, n)) return false;
      const raw = base.properties?.[n];
      if (isOptionalSchema(raw) || isOptionalSchema(unwrapNullUnion(raw))) return false;
      return true;
    });
    if (req.length) out.required = req;
  }
  return out;
}

export const MCP_SERVER_FILE = "mcp-server.mjs";
export const MCP_SERVER_PY_FILE = "mcp_server.py";
export const MCP_SERVER_GO_FILE = "mcp_server.go";
export const MCP_CONFIG_FILE = "mcp.json";
export const DEFAULT_MCP_BASE_URL = "http://127.0.0.1:8080";

/** Shared MCP tool records for JS + Python + Go stdio servers (same names / inputSchema / http). */
export function buildMcpServerTools(ops) {
  return (ops || []).map((op) => {
    const pathParams = [];
    const queryParams = [];
    for (const p of op.parameters || []) {
      if (!p?.name) continue;
      if (p.in === "path") pathParams.push(p.name);
      else if (p.in === "query") queryParams.push(p.name);
    }
    const re = /\{([^}]+)\}/g;
    let m;
    while ((m = re.exec(op.path || ""))) {
      if (!pathParams.includes(m[1])) pathParams.push(m[1]);
    }
    return {
      name: op.operationId,
      description: op.summary || `${op.method} ${op.path}`,
      inputSchema: simplifyInputSchema(op.inputSchema),
      http: {
        method: op.method,
        path: op.path,
        pathParams,
        queryParams,
      },
      security: compactToolSecurity(op),
    };
  });
}


/**
 * Stdio MCP server (Node, no extra deps). JSON-RPC 2.0 newline frames:
 * initialize, tools/list, tools/call — same subset B mock-upstream / stdio proxy uses.
 * Runtime HTTP backend: env MCP_BASE_URL (wins) or baked --base-url.
 */
export function generateMcpServer(ops, title = "API", { baseUrl = "" } = {}) {
  const tools = buildMcpServerTools(ops);
  const auth = authFlags(ops);
  const safeTitle = String(title || "API").replace(/\*\//g, "");
  const lines = [];
  lines.push("#!/usr/bin/env node");
  lines.push("/**");
  lines.push(" * Auto-generated by sdk-mcp-gen — do not edit by hand");
  lines.push(" * API: " + safeTitle);
  lines.push(" * Stdio MCP server (JSON-RPC 2.0, newline-delimited): initialize, tools/list, tools/call");
  lines.push(" * HTTP backend: env MCP_BASE_URL or baked --base-url");
  if (auth.any) {
    lines.push(" * Auth: env MCP_BEARER_TOKEN / SDK_BEARER_TOKEN and MCP_API_KEY / SDK_API_KEY (values never logged). oauth2 / openIdConnect skipped.");
  }
  lines.push(" * No extra deps (Node >= 18 fetch + readline). Compatible with B gateway stdio upstream.");
  lines.push(" */");
  lines.push('import readline from "node:readline";');
  lines.push("");
  lines.push('const VERSION = "0.1.0";');
  lines.push("const SERVER_NAME = " + JSON.stringify(safeTitle + " MCP") + ";");
  lines.push("const DEFAULT_BASE_URL = " + JSON.stringify(String(baseUrl || "")) + ";");
  lines.push("const TOOLS = " + JSON.stringify(tools, null, 2) + ";");
  lines.push("");
  lines.push("function publicTools() {");
  lines.push("  return TOOLS.map(({ name, description, inputSchema }) => ({ name, description, inputSchema }));");
  lines.push("}");
  lines.push("");
  lines.push("function baseUrl() {");
  lines.push("  const env = process.env.MCP_BASE_URL;");
  lines.push('  if (env && String(env).trim()) return String(env).trim().replace(/\\/$/, "");');
  lines.push('  return String(DEFAULT_BASE_URL || "").replace(/\\/$/, "");');
  lines.push("}");
  lines.push("");
  if (auth.any) {
    lines.push("function envAuth(mcpName, sdkName) {");
    lines.push("  const a = process.env[mcpName];");
    lines.push("  if (a && String(a).trim()) return String(a).trim();");
    lines.push("  const b = process.env[sdkName];");
    lines.push("  if (b && String(b).trim()) return String(b).trim();");
    lines.push('  return "";');
    lines.push("}");
    lines.push("");
    lines.push("function applyAuth(headers, url, security) {");
    lines.push("  const schemes = Array.isArray(security) ? security : [];");
    if (auth.hasBearer) {
      lines.push('  const bearer = envAuth("MCP_BEARER_TOKEN", "SDK_BEARER_TOKEN");');
      lines.push('  if (bearer && schemes.some((s) => s && s.kind === "bearer")) headers["authorization"] = "Bearer " + bearer;');
    }
    if (auth.headerKeys.length || auth.queryKeys.length) {
      lines.push('  const apiKey = envAuth("MCP_API_KEY", "SDK_API_KEY");');
      lines.push("  if (apiKey) {");
      lines.push("    for (const s of schemes) {");
      lines.push('      if (!s || s.kind !== "apiKey" || !s.paramName) continue;');
      lines.push('      if (s.in === "header") headers[s.paramName] = apiKey;');
      lines.push('      if (s.in === "query") url += (url.includes("?") ? "&" : "?") + encodeURIComponent(s.paramName) + "=" + encodeURIComponent(apiKey);');
      lines.push("    }");
      lines.push("  }");
    }
    lines.push("  return url;");
    lines.push("}");
    lines.push("");
  }
  lines.push("function applyPath(pathTpl, args) {");
  lines.push("  const used = new Set();");
  lines.push("  const path = String(pathTpl).replace(/\\{([^}]+)\\}/g, (_, k) => {");
  lines.push("    used.add(k);");
  lines.push("    const v = args[k];");
  lines.push('    return encodeURIComponent(v == null ? "" : String(v));');
  lines.push("  });");
  lines.push("  return { path, used };");
  lines.push("}");
  lines.push("");
  lines.push("async function invokeHttp(tool, args) {");
  lines.push("  const root = baseUrl();");
  lines.push("  if (!root) {");
  lines.push('    return { ok: false, error: "missing_base_url", hint: "set MCP_BASE_URL or generate --base-url" };');
  lines.push("  }");
  lines.push("  const a = args && typeof args === \"object\" ? args : {};");
  lines.push("  const { path, used } = applyPath(tool.http.path, a);");
  lines.push('  const method = String(tool.http.method || "GET").toUpperCase();');
  lines.push("  const pathParamSet = new Set([...(tool.http.pathParams || []), ...used]);");
  lines.push("  let url = root + path;");
  lines.push('  const isBodyMethod = method === "POST" || method === "PUT" || method === "PATCH";');
  lines.push("  if (!isBodyMethod) {");
  lines.push("    const q = new URLSearchParams();");
  lines.push("    for (const [k, v] of Object.entries(a)) {");
  lines.push("      if (pathParamSet.has(k)) continue;");
  lines.push("      if (v === undefined || v === null) continue;");
  lines.push("      q.set(k, String(v));");
  lines.push("    }");
  lines.push("    const qs = q.toString();");
  lines.push('    if (qs) url += "?" + qs;');
  lines.push("  }");
  if (auth.any) {
    lines.push("  const headers = {};");
    lines.push("  let urlWithAuth = url;");
    lines.push("  urlWithAuth = applyAuth(headers, url, tool.security);");
    lines.push("  url = urlWithAuth;");
  } else {
    lines.push("  const headers = {};");
  }
  lines.push("  let body;");
  lines.push("  if (isBodyMethod) {");
  lines.push("    const payload = {};");
  lines.push("    for (const [k, v] of Object.entries(a)) {");
  lines.push("      if (pathParamSet.has(k)) continue;");
  lines.push("      payload[k] = v;");
  lines.push("    }");
  lines.push("    body = JSON.stringify(payload);");
  lines.push('    headers["content-type"] = "application/json";');
  lines.push("  }");
  lines.push("  try {");
  lines.push("    const res = await fetch(url, { method, headers, body });");
  lines.push("    const text = await res.text();");
  lines.push("    let parsed = text;");
  lines.push("    if (text) {");
  lines.push("      try { parsed = JSON.parse(text); } catch { parsed = text; }");
  lines.push("    } else {");
  lines.push("      parsed = null;");
  lines.push("    }");
  lines.push("    return { ok: res.ok, status: res.status, body: parsed };");
  lines.push("  } catch (err) {");
  lines.push('    return { ok: false, error: "fetch_failed", message: String(err && err.message ? err.message : err) };');
  lines.push("  }");
  lines.push("}");
  lines.push("");
  lines.push("function rpcResult(id, result) {");
  lines.push("  return { jsonrpc: \"2.0\", id: id ?? null, result };");
  lines.push("}");
  lines.push("function rpcError(id, code, message) {");
  lines.push("  return { jsonrpc: \"2.0\", id: id ?? null, error: { code, message } };");
  lines.push("}");
  lines.push("");
  lines.push("async function handleRpc(msg) {");
  lines.push("  const id = Object.prototype.hasOwnProperty.call(msg, \"id\") ? msg.id : undefined;");
  lines.push("  const method = msg.method || msg.op;");
  lines.push("  const isNotification = id === undefined;");
  lines.push("  if (!method) return isNotification ? null : rpcError(id, -32600, \"missing_method\");");
  lines.push('  if (method === "notifications/initialized" || method === "initialized" || String(method).startsWith("notifications/")) {');
  lines.push("    return null;");
  lines.push("  }");
  lines.push('  if (method === "initialize") {');
  lines.push("    return rpcResult(id ?? null, {");
  lines.push('      protocolVersion: "2024-11-05",');
  lines.push("      capabilities: { tools: { listChanged: false } },");
  lines.push("      serverInfo: { name: SERVER_NAME, version: VERSION },");
  lines.push("    });");
  lines.push("  }");
  lines.push('  if (method === "tools/list" || method === "list") {');
  lines.push("    return rpcResult(id ?? null, { tools: publicTools() });");
  lines.push("  }");
  lines.push('  if (method === "tools/call" || method === "call") {');
  lines.push("    const params = msg.params || msg;");
  lines.push("    const name = params.name || params.tool;");
  lines.push("    const args = params.arguments ?? params.args ?? {};");
  lines.push("    if (!name) return rpcError(id ?? null, -32602, \"missing_tool_name\");");
  lines.push("    const tool = TOOLS.find((t) => t.name === name);");
  lines.push("    if (!tool) {");
  lines.push('      const result = { ok: false, error: "unknown_tool:" + name };');
  lines.push("      return rpcResult(id ?? null, { ok: false, tool: name, result });");
  lines.push("    }");
  lines.push("    const result = await invokeHttp(tool, args);");
  lines.push("    const statusOk = result.ok !== false;");
  lines.push("    return rpcResult(id ?? null, { ok: statusOk, tool: name, result });");
  lines.push("  }");
  lines.push('  if (method === "ping") {');
  lines.push("    return rpcResult(id ?? null, {});");
  lines.push("  }");
  lines.push("  return rpcError(id ?? null, -32601, \"unknown_method:\" + method);");
  lines.push("}");
  lines.push("");
  lines.push("let pending = 0;");
  lines.push("let closing = false;");
  lines.push("function maybeExit() {");
  lines.push("  if (closing && pending === 0) process.exit(0);");
  lines.push("}");
  lines.push("const rl = readline.createInterface({ input: process.stdin, terminal: false });");
  lines.push('rl.on("line", async (line) => {');
  lines.push("  const trimmed = String(line).trim();");
  lines.push("  if (!trimmed) return;");
  lines.push("  pending += 1;");
  lines.push("  rl.pause();");
  lines.push("  try {");
  lines.push("    let msg;");
  lines.push("    try {");
  lines.push("      msg = JSON.parse(trimmed);");
  lines.push("    } catch (err) {");
  lines.push('      process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id: null, error: { message: String(err) } }) + "\\n");');
  lines.push("      return;");
  lines.push("    }");
  lines.push("    const reply = await handleRpc(msg);");
  lines.push('    if (reply) process.stdout.write(JSON.stringify(reply) + "\\n");');
  lines.push("  } finally {");
  lines.push("    pending -= 1;");
  lines.push("    rl.resume();");
  lines.push("    maybeExit();");
  lines.push("  }");
  lines.push("});");
  lines.push('rl.on("close", () => {');
  lines.push("  closing = true;");
  lines.push("  maybeExit();");
  lines.push("});");
  lines.push('process.stderr.write("mcp-server stdio ready name=" + SERVER_NAME + "\\n");');
  lines.push("");
  return lines.join("\n");
}


function emitPyMcpAuth(auth) {
  const lines = [];
  lines.push("def _env_auth(mcp_name, sdk_name):");
  lines.push("    raw = os.environ.get(mcp_name)");
  lines.push("    if raw and str(raw).strip():");
  lines.push("        return str(raw).strip()");
  lines.push("    raw = os.environ.get(sdk_name)");
  lines.push("    if raw and str(raw).strip():");
  lines.push("        return str(raw).strip()");
  lines.push("    return \"\"");
  lines.push("");
  lines.push("");
  lines.push("def apply_auth(headers, url, security=None):");
  if (!auth.any) {
    lines.push("    return url");
    lines.push("");
    lines.push("");
    return lines.join("\n");
  }
  lines.push("    schemes = security if isinstance(security, list) else []");
  if (auth.hasBearer) {
    lines.push("    bearer = _env_auth(\"MCP_BEARER_TOKEN\", \"SDK_BEARER_TOKEN\")");
    lines.push("    if bearer and any(isinstance(s, dict) and s.get(\"kind\") == \"bearer\" for s in schemes):");
    lines.push("        headers[\"Authorization\"] = \"Bearer \" + bearer");
  }
  if (auth.headerKeys.length || auth.queryKeys.length) {
    lines.push("    api_key = _env_auth(\"MCP_API_KEY\", \"SDK_API_KEY\")");
    lines.push("    if api_key:");
    lines.push("        for s in schemes:");
    lines.push("            if not isinstance(s, dict) or s.get(\"kind\") != \"apiKey\":");
    lines.push("                continue");
    lines.push("            name = s.get(\"paramName\") or \"\"");
    lines.push("            inn = s.get(\"in\") or \"\"");
    lines.push("            if inn == \"header\" and name:");
    lines.push("                headers[name] = api_key");
    lines.push("            if inn == \"query\" and name:");
    lines.push("                url = url + (\"&\" if \"?\" in url else \"?\") + urllib.parse.quote(name, safe=\"\") + \"=\" + urllib.parse.quote(api_key, safe=\"\")");
  }
  lines.push("    return url");
  lines.push("");
  lines.push("");
  return lines.join("\n");
}

/**
 * Stdio MCP server (Python 3, stdlib only). Same JSON-RPC surface as generateMcpServer:
 * initialize, tools/list, tools/call — newline frames on stdin/stdout.
 * Runtime HTTP backend: env MCP_BASE_URL (wins) or baked --base-url (urllib).
 */
export function generateMcpServerPy(ops, title = "API", { baseUrl = "" } = {}) {
  const tools = buildMcpServerTools(ops);
  const auth = authFlags(ops);
  const pyAuthFns = emitPyMcpAuth(auth);
  const safeTitle = String(title || "API")
    .replace(/\r?\n/g, " ")
    .replace(/#/g, "")
    .replace(/`/g, "")
    .replace(/\$\{/g, "");
  const toolsJson = JSON.stringify(tools, null, 2);
  return `#!/usr/bin/env python3
# Auto-generated by sdk-mcp-gen — do not edit by hand
# API: ${safeTitle}
# Stdio MCP server (JSON-RPC 2.0, newline-delimited): initialize, tools/list, tools/call
# HTTP backend: env MCP_BASE_URL or baked --base-url
# Auth: env MCP_BEARER_TOKEN / SDK_BEARER_TOKEN and MCP_API_KEY / SDK_API_KEY (values never logged). oauth2 / openIdConnect skipped.
# Stdlib only (urllib). Compatible with B gateway stdio upstream.

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

VERSION = "0.1.0"
SERVER_NAME = ${JSON.stringify(safeTitle + " MCP")}
DEFAULT_BASE_URL = ${JSON.stringify(String(baseUrl || ""))}
TOOLS = json.loads(${JSON.stringify(toolsJson)})


def public_tools():
    out = []
    for t in TOOLS:
        out.append({
            "name": t.get("name"),
            "description": t.get("description"),
            "inputSchema": t.get("inputSchema"),
        })
    return out


def base_url():
    env = os.environ.get("MCP_BASE_URL")
    if env and str(env).strip():
        return str(env).strip().rstrip("/")
    return str(DEFAULT_BASE_URL or "").rstrip("/")


${pyAuthFns}def apply_path(path_tpl, args):
    used = set()

    def _sub(m):
        k = m.group(1)
        used.add(k)
        v = args.get(k)
        return urllib.parse.quote("" if v is None else str(v), safe="")

    path = re.sub(r"\\{([^}]+)\\}", _sub, str(path_tpl))
    return path, used


def invoke_http(tool, args):
    root = base_url()
    if not root:
        return {"ok": False, "error": "missing_base_url", "hint": "set MCP_BASE_URL or generate --base-url"}
    a = args if isinstance(args, dict) else {}
    path, used = apply_path((tool.get("http") or {}).get("path") or "", a)
    method = str((tool.get("http") or {}).get("method") or "GET").upper()
    path_param_set = set((tool.get("http") or {}).get("pathParams") or [])
    path_param_set.update(used)
    url = root + path
    is_body_method = method in ("POST", "PUT", "PATCH")
    if not is_body_method:
        q = []
        for k, v in a.items():
            if k in path_param_set:
                continue
            if v is None:
                continue
            q.append((k, str(v)))
        if q:
            url += "?" + urllib.parse.urlencode(q)
    data = None
    headers = {}
    url = apply_auth(headers, url, (tool or {}).get("security"))
    if is_body_method:
        payload = {}
        for k, v in a.items():
            if k in path_param_set:
                continue
            payload[k] = v
        data = json.dumps(payload).encode("utf-8")
        headers["content-type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        try:
            with urllib.request.urlopen(req) as res:
                raw = res.read()
                status = getattr(res, "status", None) or res.getcode()
                text = raw.decode("utf-8") if raw else ""
                ok = 200 <= int(status) < 300
        except urllib.error.HTTPError as e:
            raw = e.read() if e.fp else b""
            status = e.code
            text = raw.decode("utf-8") if raw else ""
            ok = False
        parsed = text
        if text:
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = text
        else:
            parsed = None
        return {"ok": ok, "status": status, "body": parsed}
    except Exception as err:
        return {"ok": False, "error": "fetch_failed", "message": str(err)}


def rpc_result(rpc_id, result):
    return {"jsonrpc": "2.0", "id": rpc_id if rpc_id is not None else None, "result": result}


def rpc_error(rpc_id, code, message):
    return {"jsonrpc": "2.0", "id": rpc_id if rpc_id is not None else None, "error": {"code": code, "message": message}}


def handle_rpc(msg):
    if not isinstance(msg, dict):
        return rpc_error(None, -32600, "missing_method")
    has_id = "id" in msg
    rpc_id = msg["id"] if has_id else None
    is_notification = not has_id
    method = msg.get("method") or msg.get("op")
    if not method:
        return None if is_notification else rpc_error(rpc_id, -32600, "missing_method")
    method_s = str(method)
    if method_s in ("notifications/initialized", "initialized") or method_s.startswith("notifications/"):
        return None
    if method_s == "initialize":
        return rpc_result(rpc_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": VERSION},
        })
    if method_s in ("tools/list", "list"):
        return rpc_result(rpc_id, {"tools": public_tools()})
    if method_s in ("tools/call", "call"):
        params = msg.get("params") if isinstance(msg.get("params"), dict) else msg
        name = params.get("name") or params.get("tool") if isinstance(params, dict) else None
        if isinstance(params, dict) and params.get("arguments") is not None:
            args = params.get("arguments")
        elif isinstance(params, dict) and params.get("args") is not None:
            args = params.get("args")
        else:
            args = {}
        if not name:
            return rpc_error(rpc_id, -32602, "missing_tool_name")
        tool = None
        for t in TOOLS:
            if t.get("name") == name:
                tool = t
                break
        if tool is None:
            result = {"ok": False, "error": "unknown_tool:" + str(name)}
            return rpc_result(rpc_id, {"ok": False, "tool": name, "result": result})
        result = invoke_http(tool, args)
        status_ok = result.get("ok") is not False
        return rpc_result(rpc_id, {"ok": status_ok, "tool": name, "result": result})
    if method_s == "ping":
        return rpc_result(rpc_id, {})
    return rpc_error(rpc_id, -32601, "unknown_method:" + method_s)


def main():
    sys.stderr.write("mcp-server py stdio ready name=" + SERVER_NAME + "\\n")
    sys.stderr.flush()
    for line in sys.stdin:
        trimmed = str(line).strip()
        if not trimmed:
            continue
        try:
            msg = json.loads(trimmed)
        except Exception as err:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"message": str(err)}}) + "\\n")
            sys.stdout.flush()
            continue
        reply = handle_rpc(msg)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
`;
}


function emitGoMcpAuth(auth) {
  const lines = [];
  lines.push("func envAuth(mcpName, sdkName string) string {");
  lines.push("\tv := strings.TrimSpace(os.Getenv(mcpName))");
  lines.push("\tif v != \"\" {");
  lines.push("\t\treturn v");
  lines.push("\t}");
  lines.push("\treturn strings.TrimSpace(os.Getenv(sdkName))");
  lines.push("}");
  lines.push("");
  lines.push("func applyAuth(req *http.Request, urlStr string, security []mcpAuthScheme) string {");
  if (!auth.any) {
    lines.push("\treturn urlStr");
    lines.push("}");
    lines.push("");
    return lines.join("\n");
  }
  if (auth.hasBearer) {
    lines.push("\tuseBearer := false");
    lines.push("\tfor _, s := range security {");
    lines.push("\t\tif s.Kind == \"bearer\" {");
    lines.push("\t\t\tuseBearer = true");
    lines.push("\t\t\tbreak");
    lines.push("\t\t}");
    lines.push("\t}");
    lines.push("\tif useBearer {");
    lines.push("\t\tif bearer := envAuth(\"MCP_BEARER_TOKEN\", \"SDK_BEARER_TOKEN\"); bearer != \"\" && req != nil {");
    lines.push("\t\t\treq.Header.Set(\"Authorization\", \"Bearer \"+bearer)");
    lines.push("\t\t}");
    lines.push("\t}");
  }
  if (auth.headerKeys.length || auth.queryKeys.length) {
    lines.push("\tkey := envAuth(\"MCP_API_KEY\", \"SDK_API_KEY\")");
    lines.push("\tif key != \"\" {");
    lines.push("\t\tfor _, s := range security {");
    lines.push("\t\t\tif s.Kind != \"apiKey\" || s.ParamName == \"\" {");
    lines.push("\t\t\t\tcontinue");
    lines.push("\t\t\t}");
    lines.push("\t\t\tif s.In == \"header\" && req != nil {");
    lines.push("\t\t\t\treq.Header.Set(s.ParamName, key)");
    lines.push("\t\t\t}");
    lines.push("\t\t\tif s.In == \"query\" {");
    lines.push("\t\t\t\tsep := \"?\"");
    lines.push("\t\t\t\tif strings.Contains(urlStr, \"?\") {");
    lines.push("\t\t\t\t\tsep = \"&\"");
    lines.push("\t\t\t\t}");
    lines.push("\t\t\t\turlStr = urlStr + sep + url.QueryEscape(s.ParamName) + \"=\" + url.QueryEscape(key)");
    lines.push("\t\t\t}");
    lines.push("\t\t}");
    lines.push("\t}");
  }
  lines.push("\treturn urlStr");
  lines.push("}");
  lines.push("");
  return lines.join("\n");
}

/**
 * Stdio MCP server (Go, stdlib only). Same JSON-RPC surface as generateMcpServer:
 * initialize, tools/list, tools/call — newline frames on stdin/stdout.
 * Runtime HTTP backend: env MCP_BASE_URL (wins) or baked --base-url (net/http).
 * package main so `go run mcp_server.go` works next to client.go (package client).
 */
export function generateMcpServerGo(ops, title = "API", { baseUrl = "" } = {}) {
  const tools = buildMcpServerTools(ops);
  const auth = authFlags(ops);
  const goAuthFns = emitGoMcpAuth(auth);
  const safeTitle = String(title || "API")
    .replace(/\r?\n/g, " ")
    .replace(/\*\//g, "* /");
  const toolsGoStr = JSON.stringify(JSON.stringify(tools, null, 2));
  const nameGo = JSON.stringify(safeTitle + " MCP");
  const baseGo = JSON.stringify(String(baseUrl || ""));
  return `// Auto-generated by sdk-mcp-gen — do not edit by hand
// API: ${safeTitle}
// Stdio MCP server (JSON-RPC 2.0, newline-delimited): initialize, tools/list, tools/call
// HTTP backend: env MCP_BASE_URL or baked --base-url
// Auth: env MCP_BEARER_TOKEN / SDK_BEARER_TOKEN and MCP_API_KEY / SDK_API_KEY (values never logged). oauth2 / openIdConnect skipped.
// Stdlib only (net/http). Compatible with B gateway stdio upstream.
// Run: go run mcp_server.go   (Go 1.21+; no extra modules)
package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
)

const version = "0.1.0"
const serverName = ${nameGo}

var defaultBaseURL = ${baseGo}
var toolsJSON = ${toolsGoStr}

type toolHTTP struct {
	Method      string   \`json:"method"\`
	Path        string   \`json:"path"\`
	PathParams  []string \`json:"pathParams"\`
	QueryParams []string \`json:"queryParams"\`
}

type mcpAuthScheme struct {
	Kind      string \`json:"kind"\`
	In        string \`json:"in,omitempty"\`
	ParamName string \`json:"paramName,omitempty"\`
}

type mcpTool struct {
	Name        string          \`json:"name"\`
	Description string          \`json:"description"\`
	InputSchema map[string]any  \`json:"inputSchema"\`
	HTTP        toolHTTP        \`json:"http"\`
	Security    []mcpAuthScheme \`json:"security"\`
}

var tools []mcpTool

func init() {
	if err := json.Unmarshal([]byte(toolsJSON), &tools); err != nil {
		panic(err)
	}
}

func publicTools() []map[string]any {
	out := make([]map[string]any, 0, len(tools))
	for _, t := range tools {
		out = append(out, map[string]any{
			"name":        t.Name,
			"description": t.Description,
			"inputSchema": t.InputSchema,
		})
	}
	return out
}

func baseURL() string {
	env := strings.TrimSpace(os.Getenv("MCP_BASE_URL"))
	if env != "" {
		return strings.TrimRight(env, "/")
	}
	return strings.TrimRight(defaultBaseURL, "/")
}

${goAuthFns}
func applyPath(pathTpl string, args map[string]any) (string, map[string]struct{}) {
	used := map[string]struct{}{}
	var b strings.Builder
	s := pathTpl
	for {
		start := strings.Index(s, "{")
		if start < 0 {
			b.WriteString(s)
			break
		}
		endRel := strings.Index(s[start:], "}")
		if endRel < 0 {
			b.WriteString(s)
			break
		}
		end := start + endRel
		b.WriteString(s[:start])
		key := s[start+1 : end]
		used[key] = struct{}{}
		val, ok := args[key]
		if ok && val != nil {
			b.WriteString(url.PathEscape(fmt.Sprint(val)))
		}
		s = s[end+1:]
	}
	return b.String(), used
}

func invokeHTTP(tool mcpTool, args map[string]any) map[string]any {
	root := baseURL()
	if root == "" {
		return map[string]any{"ok": false, "error": "missing_base_url", "hint": "set MCP_BASE_URL or generate --base-url"}
	}
	if args == nil {
		args = map[string]any{}
	}
	path, used := applyPath(tool.HTTP.Path, args)
	method := strings.ToUpper(tool.HTTP.Method)
	if method == "" {
		method = "GET"
	}
	pathParamSet := map[string]struct{}{}
	for _, k := range tool.HTTP.PathParams {
		pathParamSet[k] = struct{}{}
	}
	for k := range used {
		pathParamSet[k] = struct{}{}
	}
	urlStr := root + path
	isBody := method == "POST" || method == "PUT" || method == "PATCH"
	if !isBody {
		q := url.Values{}
		for k, v := range args {
			if _, skip := pathParamSet[k]; skip {
				continue
			}
			if v == nil {
				continue
			}
			q.Set(k, fmt.Sprint(v))
		}
		if enc := q.Encode(); enc != "" {
			urlStr += "?" + enc
		}
	}
	var body io.Reader
	if isBody {
		payload := map[string]any{}
		for k, v := range args {
			if _, skip := pathParamSet[k]; skip {
				continue
			}
			payload[k] = v
		}
		raw, err := json.Marshal(payload)
		if err != nil {
			return map[string]any{"ok": false, "error": "fetch_failed", "message": err.Error()}
		}
		body = bytes.NewReader(raw)
	}
	urlStr = applyAuth(nil, urlStr, tool.Security)
	req, err := http.NewRequest(method, urlStr, body)
	if err != nil {
		return map[string]any{"ok": false, "error": "fetch_failed", "message": err.Error()}
	}
	if isBody {
		req.Header.Set("Content-Type", "application/json")
	}
	_ = applyAuth(req, urlStr, tool.Security)
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		return map[string]any{"ok": false, "error": "fetch_failed", "message": err.Error()}
	}
	defer res.Body.Close()
	data, err := io.ReadAll(res.Body)
	if err != nil {
		return map[string]any{"ok": false, "error": "fetch_failed", "message": err.Error()}
	}
	var parsed any
	if len(data) == 0 {
		parsed = nil
	} else if err := json.Unmarshal(data, &parsed); err != nil {
		parsed = string(data)
	}
	ok := res.StatusCode >= 200 && res.StatusCode < 300
	return map[string]any{"ok": ok, "status": res.StatusCode, "body": parsed}
}

func rpcResult(rpcID any, result any) map[string]any {
	return map[string]any{"jsonrpc": "2.0", "id": rpcID, "result": result}
}

func rpcError(rpcID any, code int, message string) map[string]any {
	return map[string]any{"jsonrpc": "2.0", "id": rpcID, "error": map[string]any{"code": code, "message": message}}
}

func asString(v any) string {
	if v == nil {
		return ""
	}
	if s, ok := v.(string); ok {
		return s
	}
	return fmt.Sprint(v)
}

func handleRPC(msg map[string]any) any {
	if msg == nil {
		return rpcError(nil, -32600, "missing_method")
	}
	_, hasID := msg["id"]
	var rpcID any
	if hasID {
		rpcID = msg["id"]
	}
	isNotification := !hasID
	method := asString(msg["method"])
	if method == "" {
		method = asString(msg["op"])
	}
	if method == "" {
		if isNotification {
			return nil
		}
		return rpcError(rpcID, -32600, "missing_method")
	}
	if method == "notifications/initialized" || method == "initialized" || strings.HasPrefix(method, "notifications/") {
		return nil
	}
	if method == "initialize" {
		return rpcResult(rpcID, map[string]any{
			"protocolVersion": "2024-11-05",
			"capabilities":    map[string]any{"tools": map[string]any{"listChanged": false}},
			"serverInfo":      map[string]any{"name": serverName, "version": version},
		})
	}
	if method == "tools/list" || method == "list" {
		return rpcResult(rpcID, map[string]any{"tools": publicTools()})
	}
	if method == "tools/call" || method == "call" {
		params := msg
		if p, ok := msg["params"].(map[string]any); ok {
			params = p
		}
		name := asString(params["name"])
		if name == "" {
			name = asString(params["tool"])
		}
		var args map[string]any
		if a, ok := params["arguments"].(map[string]any); ok {
			args = a
		} else if a, ok := params["args"].(map[string]any); ok {
			args = a
		} else {
			args = map[string]any{}
		}
		if name == "" {
			return rpcError(rpcID, -32602, "missing_tool_name")
		}
		var tool *mcpTool
		for i := range tools {
			if tools[i].Name == name {
				tool = &tools[i]
				break
			}
		}
		if tool == nil {
			result := map[string]any{"ok": false, "error": "unknown_tool:" + name}
			return rpcResult(rpcID, map[string]any{"ok": false, "tool": name, "result": result})
		}
		result := invokeHTTP(*tool, args)
		statusOk := true
		if v, ok := result["ok"].(bool); ok && !v {
			statusOk = false
		}
		return rpcResult(rpcID, map[string]any{"ok": statusOk, "tool": name, "result": result})
	}
	if method == "ping" {
		return rpcResult(rpcID, map[string]any{})
	}
	return rpcError(rpcID, -32601, "unknown_method:"+method)
}

func main() {
	fmt.Fprintf(os.Stderr, "mcp-server go stdio ready name=%s\\n", serverName)
	sc := bufio.NewScanner(os.Stdin)
	buf := make([]byte, 0, 64*1024)
	sc.Buffer(buf, 4*1024*1024)
	enc := json.NewEncoder(os.Stdout)
	enc.SetEscapeHTML(false)
	for sc.Scan() {
		trimmed := strings.TrimSpace(sc.Text())
		if trimmed == "" {
			continue
		}
		var msg map[string]any
		if err := json.Unmarshal([]byte(trimmed), &msg); err != nil {
			_ = enc.Encode(map[string]any{
				"jsonrpc": "2.0",
				"id":      nil,
				"error":   map[string]any{"message": err.Error()},
			})
			continue
		}
		reply := handleRPC(msg)
		if reply != nil {
			_ = enc.Encode(reply)
		}
	}
}
`;
}


export const DEFAULT_PACKAGE_NAME = "client";

export const SDK_CLIENT_VERSION = "0.1.0";

/** Default User-Agent: sdk-mcp-gen/0.1.0, or {packageName}/0.1.0 when --package-name is set. */
function defaultUserAgent(opts) {
  const pkg = pkgFromOpts(opts);
  const name = pkg.customized ? pkg.ident : "sdk-mcp-gen";
  return name + "/" + SDK_CLIENT_VERSION;
}

const PACKAGE_IDENT_KEYWORDS = new Set([
  "break", "case", "chan", "class", "const", "continue", "def", "default", "defer",
  "else", "for", "from", "func", "go", "goto", "if", "import", "interface", "map",
  "module", "package", "range", "return", "select", "struct", "switch", "type", "var",
  "yield", "pass", "lambda", "with", "try", "except", "finally", "raise", "async",
  "await", "true", "false", "null", "none",
]);

function keepIdentChar(c) {
  return (c >= "a" && c <= "z") || (c >= "A" && c <= "Z") || (c >= "0" && c <= "9") || c === "_";
}

function keepNpmChar(c) {
  return keepIdentChar(c) || c === "-" || c === "." || c === "@";
}

function stripUnderscores(s) {
  while (s.charAt(0) === "_") s = s.slice(1);
  while (s.charAt(s.length - 1) === "_") s = s.slice(0, -1);
  return s;
}

/** Last path segment to snake ident (hyphens/dots to underscore). */
export function toIdentPackageName(raw) {
  let s = String(raw == null ? "" : raw).trim();
  if (!s) s = DEFAULT_PACKAGE_NAME;
  if (s.charAt(0) === "@") {
    const slash = s.indexOf("/");
    if (slash > 0) s = s.slice(slash + 1);
  }
  s = s.split("\\").join("/");
  const segs = s.split("/");
  s = segs[segs.length - 1] || s;
  let out = "";
  for (let i = 0; i < s.length; i++) {
    const c = s.charAt(i);
    out += keepIdentChar(c) ? c : "_";
  }
  out = stripUnderscores(out);
  if (!out) out = DEFAULT_PACKAGE_NAME;
  out = out.toLowerCase();
  if (out.charAt(0) >= "0" && out.charAt(0) <= "9") out = "pkg_" + out;
  if (PACKAGE_IDENT_KEYWORDS.has(out)) out = out + "_pkg";
  return out;
}

export function toPascalPackageName(raw) {
  const ident = toIdentPackageName(raw);
  const pascal = ident.split("_").filter(Boolean).map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join("");
  return pascal || "Client";
}

export function toNpmPackageName(raw) {
  return toIdentPackageName(raw);
}

export function slugFromTitle(title) {
  const t = String(title || "");
  let spaced = "";
  for (let i = 0; i < t.length; i++) {
    const c = t.charAt(i);
    const prev = i > 0 ? t.charAt(i - 1) : "";
    if (i > 0 && prev >= "a" && prev <= "z" && c >= "A" && c <= "Z") spaced += "_";
    spaced += c;
  }
  return toIdentPackageName(spaced);
}

export function resolvePackageName(_spec, override) {
  if (override != null && String(override).trim()) return String(override).trim();
  return DEFAULT_PACKAGE_NAME;
}

/** mcpServers key: customized --package-name ident, else OpenAPI title slug. */
export function mcpClientServerKey(spec, packageName) {
  const resolved = resolvePackageName(spec, packageName);
  const ident = toIdentPackageName(resolved);
  if (ident && ident !== DEFAULT_PACKAGE_NAME) return ident;
  const slug = slugFromTitle(spec?.info?.title || "");
  if (slug && slug !== DEFAULT_PACKAGE_NAME) return slug;
  return ident || "api";
}

function mcpEnvBlock(baseUrl) {
  const raw = String(baseUrl || "").trim().replace(/\/$/, "");
  return { MCP_BASE_URL: raw || DEFAULT_MCP_BASE_URL };
}

/**
 * Client MCP servers config JSON (paste into Cursor / Claude Desktop / Claude Code).
 * Relative args from the generate --out directory.
 */
export function generateMcpClientConfig(spec, opts = {}) {
  const includeJs = opts.includeJs !== false;
  const includePy = opts.includePy !== false;
  const includeGo = opts.includeGo !== false;
  const key = mcpClientServerKey(spec, opts.packageName);
  const mcpServers = {};
  if (includeJs) {
    mcpServers[key] = {
      command: "node",
      args: ["./" + MCP_SERVER_FILE],
      env: mcpEnvBlock(opts.baseUrl),
    };
  }
  if (includePy) {
    mcpServers[key + "-py"] = {
      command: "python3",
      args: ["./" + MCP_SERVER_PY_FILE],
      env: mcpEnvBlock(opts.baseUrl),
    };
  }
  if (includeGo) {
    mcpServers[key + "-go"] = {
      command: "go",
      args: ["run", "./" + MCP_SERVER_GO_FILE],
      env: mcpEnvBlock(opts.baseUrl),
    };
  }
  return { mcpServers };
}

function pkgFromOpts(opts) {
  const name = opts && typeof opts === "object" ? opts.packageName : undefined;
  return splitPkg(name || DEFAULT_PACKAGE_NAME);
}

export function splitPkg(raw) {
  const source = raw == null || !String(raw).trim() ? DEFAULT_PACKAGE_NAME : String(raw).trim();
  const ident = toIdentPackageName(source);
  const pascal = toPascalPackageName(ident);
  return { raw: source, ident, pascal, customized: ident !== DEFAULT_PACKAGE_NAME, modPath: ident === DEFAULT_PACKAGE_NAME ? "example.com/gen/client" : "example.com/" + ident };
}

export function generatePackageJson(title, packageName) {
  const parts = splitPkg(packageName || DEFAULT_PACKAGE_NAME);
  const desc = String(title || "API").split(/\s+/).join(" ").trim();
  const lines = [];
  lines.push("{");
  lines.push('  "name": ' + JSON.stringify(parts.ident) + ",");
  lines.push('  "version": "0.1.0",');
  lines.push('  "private": true,');
  lines.push('  "type": "module",');
  lines.push('  "description": ' + JSON.stringify("Auto-generated by sdk-mcp-gen — " + desc));
  lines.push("}");
  lines.push("");
  return lines.join("\n");
}

const PAGEABLE_QUERY = new Set(["page", "pagesize", "offset", "limit", "cursor", "starting_after"]);

/** GET ops with common page query params. Conservative — not a Stainless pager. */
export function paginationInfo(op) {
  if (!op || String(op.method || "").toUpperCase() !== "GET") return null;
  const found = {};
  for (const p of op.parameters || []) {
    if (!p?.name || String(p.in || "").toLowerCase() !== "query") continue;
    const raw = String(p.name);
    const key = raw.toLowerCase();
    if (!PAGEABLE_QUERY.has(key)) continue;
    if (key === "pagesize") found.pageSize = raw;
    else if (key === "starting_after") found.startingAfter = raw;
    else found[key] = raw;
  }
  if (!found.page && !found.pageSize && !found.offset && !found.limit && !found.cursor && !found.startingAfter) {
    return null;
  }
  const cursorParam = found.cursor || found.startingAfter || null;
  const sizeParam = found.limit || found.pageSize || null;
  const pageParam = found.page || null;
  const offsetParam = found.offset || null;
  let mode = "page";
  if (cursorParam && !pageParam && !offsetParam) mode = "cursor";
  else if (offsetParam && !pageParam) mode = "offset";
  return { ...found, cursorParam, sizeParam, pageParam, offsetParam, mode };
}

export function iterateHelperName(operationId) {
  const id = String(operationId || "Op").replace(/[^A-Za-z0-9_]/g, "_") || "Op";
  return "iterate" + id.charAt(0).toUpperCase() + id.slice(1);
}

function pageableOps(ops) {
  const out = [];
  for (const op of ops || []) {
    const info = paginationInfo(op);
    if (info) out.push({ op, info, iter: iterateHelperName(op.operationId) });
  }
  return out;
}

function emitTsPageRuntime(lines) {
  lines.push(`  // Page helper: GET page/pageSize/offset/limit/cursor/starting_after. Follow next/next_cursor/nextPageToken or increment page. Cap 1000. Not a Stainless pager.`);
  lines.push(`  function pageLen(data: unknown): number {`);
  lines.push(`    if (Array.isArray(data)) return data.length;`);
  lines.push(`    if (data && typeof data === "object") {`);
  lines.push(`      const o = data as { [k: string]: unknown };`);
  lines.push(`      for (const k of ["data", "items", "results"]) {`);
  lines.push(`        if (Array.isArray(o[k])) return (o[k] as unknown[]).length;`);
  lines.push(`      }`);
  lines.push(`    }`);
  lines.push(`    return -1;`);
  lines.push(`  }`);
  lines.push(`  function nextCursorOf(data: unknown): string | undefined {`);
  lines.push(`    if (!data || typeof data !== "object" || Array.isArray(data)) return undefined;`);
  lines.push(`    const o = data as { [k: string]: unknown };`);
  lines.push(`    for (const k of ["next", "next_cursor", "nextPageToken"]) {`);
  lines.push(`      const v = o[k];`);
  lines.push(`      if (typeof v === "string" && v) return v;`);
  lines.push(`    }`);
  lines.push(`    return undefined;`);
  lines.push(`  }`);
}

function emitTsIterate(lines, op, info, iterName) {
  const fn = op.operationId;
  const mode = info.mode;
  const sizeKey = info.sizeParam;
  const cursorKey = info.cursorParam || "cursor";
  const pageKey = info.pageParam || "page";
  const offsetKey = info.offsetParam || "offset";
  lines.push(`  async function* ${iterName}(args: Record<string, unknown> = {}) {`);
  lines.push(`    const state: Record<string, unknown> = { ...args };`);
  if (mode === "offset") {
    lines.push(`    let offset = Number(state[${JSON.stringify(offsetKey)}] ?? 0) || 0;`);
  } else if (mode === "page") {
    lines.push(`    let page = Number(state[${JSON.stringify(pageKey)}] ?? 1) || 1;`);
  }
  lines.push(`    for (let n = 0; n < 1000; n++) {`);
  lines.push(`      const callArgs: Record<string, unknown> = { ...state };`);
  if (mode === "offset") {
    lines.push(`      callArgs[${JSON.stringify(offsetKey)}] = offset;`);
  } else if (mode === "page") {
    lines.push(`      callArgs[${JSON.stringify(pageKey)}] = page;`);
  }
  lines.push(`      const data = await ${fn}(callArgs);`);
  lines.push(`      yield data;`);
  lines.push(`      const len = pageLen(data);`);
  if (sizeKey) {
    lines.push(`      const size = Number(callArgs[${JSON.stringify(sizeKey)}] ?? 0) || 0;`);
    lines.push(`      if (data == null || len === 0 || (size > 0 && len >= 0 && len < size)) break;`);
  } else {
    lines.push(`      if (data == null || len === 0) break;`);
  }
  lines.push(`      const cur = nextCursorOf(data);`);
  lines.push(`      if (cur && cur !== state[${JSON.stringify(cursorKey)}]) {`);
  lines.push(`        state[${JSON.stringify(cursorKey)}] = cur;`);
  lines.push(`        continue;`);
  lines.push(`      }`);
  if (mode === "cursor") {
    lines.push(`      break;`);
  } else if (mode === "offset") {
    lines.push(`      if (len < 0) break;`);
    if (sizeKey) {
      lines.push(`      const step = size > 0 ? size : len;`);
    } else {
      lines.push(`      const step = len;`);
    }
    lines.push(`      if (step <= 0) break;`);
    lines.push(`      offset += step;`);
  } else {
    lines.push(`      if (len < 0) break;`);
    lines.push(`      page += 1;`);
  }
  lines.push(`    }`);
  lines.push(`  }`);
}

export function generateTsClient(ops, title = "GeneratedClient", opts = {}) {
  const pkg = pkgFromOpts(opts);
  const pageable = pageableOps(ops);
  const auth = authFlags(ops);
  const lines = [];
  lines.push(`// Auto-generated by sdk-mcp-gen — do not edit by hand`);
  lines.push(`// API: ${title}`);
  lines.push(`// package: ${pkg.ident}`);
  lines.push(`export type Json = null | boolean | number | string | Json[] | { [k: string]: Json };`);
  const optFields = ["baseUrl?: string", "fetchImpl?: typeof fetch", "timeoutMs?: number", "userAgent?: string", "requestId?: string", "idempotencyKey?: string"];
  if (auth.hasBearer) optFields.push("bearerToken?: string");
  if (auth.headerKeys.length || auth.queryKeys.length) optFields.push("apiKey?: string");
  lines.push(`export interface ClientOptions { ${optFields.join("; ")} }`);
  lines.push(`// Retry transient HTTP failures (429 / 5xx / network throw): max 2 retries, ~100ms exponential backoff, honor Retry-After <30s.`);
  lines.push(`// Per-attempt request timeout (default 10s): AbortController. Override via ClientOptions.timeoutMs or env SDK_TIMEOUT_MS / SDK_TIMEOUT_SEC.`);
  lines.push(`// Default User-Agent ${JSON.stringify(defaultUserAgent(opts))} unless the caller already set User-Agent.`);
  lines.push(`// X-Request-Id: new id per HTTP attempt (retries get a new id). Pin via ClientOptions.requestId or env SDK_REQUEST_ID (tests).`);
  lines.push(`// Idempotency-Key: on POST/PUT/PATCH/DELETE when unset. New key per logical call (retries reuse). Pin via ClientOptions.idempotencyKey or env SDK_IDEMPOTENCY_KEY (tests).`);
  if (auth.any) {
    lines.push(`// Auth from OpenAPI securitySchemes (http bearer, apiKey header/query). oauth2 / openIdConnect skipped (no fake tokens).`);
    lines.push(`// Constructor bearerToken / apiKey or env SDK_BEARER_TOKEN / SDK_API_KEY. Attached per OpenAPI operation security on every attempt (survives retry). Ops without security omit credentials. Values never logged.`);
  }
  lines.push(`function sleep(ms: number): Promise<void> {`);
  lines.push(`  return new Promise((r) => setTimeout(r, ms));`);
  lines.push(`}`);
  lines.push(`function envTimeoutMs(): number {`);
  lines.push(`  const g = globalThis as { process?: { env?: { [k: string]: string | undefined } } };`);
  lines.push(`  const env = (g.process && g.process.env) ? g.process.env : {};`);
  lines.push(`  const ms = Number(env.SDK_TIMEOUT_MS);`);
  lines.push(`  if (Number.isFinite(ms) && ms > 0) return ms;`);
  lines.push(`  const sec = Number(env.SDK_TIMEOUT_SEC);`);
  lines.push(`  if (Number.isFinite(sec) && sec > 0) return Math.floor(sec * 1000);`);
  lines.push(`  return 10000;`);
  lines.push(`}`);
  lines.push(`function envRequestId(): string {`);
  lines.push(`  const g = globalThis as { process?: { env?: { [k: string]: string | undefined } } };`);
  lines.push(`  const env = (g.process && g.process.env) ? g.process.env : {};`);
  lines.push(`  const v = env.SDK_REQUEST_ID;`);
  lines.push(`  return v && String(v).trim() ? String(v).trim() : "";`);
  lines.push(`}`);
  lines.push(`function envIdempotencyKey(): string {`);
  lines.push(`  const g = globalThis as { process?: { env?: { [k: string]: string | undefined } } };`);
  lines.push(`  const env = (g.process && g.process.env) ? g.process.env : {};`);
  lines.push(`  const v = env.SDK_IDEMPOTENCY_KEY;`);
  lines.push(`  return v && String(v).trim() ? String(v).trim() : "";`);
  lines.push(`}`);
  lines.push(`function newRequestId(): string {`);
  lines.push(`  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;`);
  lines.push(`  if (c && typeof c.randomUUID === "function") return c.randomUUID();`);
  lines.push(`  return Date.now().toString(16) + "-" + Math.random().toString(16).slice(2);`);
  lines.push(`}`);
  lines.push(`function hasHeader(headers: { [k: string]: string }, name: string): boolean {`);
  lines.push(`  const want = name.toLowerCase();`);
  lines.push(`  for (const k of Object.keys(headers)) if (k.toLowerCase() === want) return true;`);
  lines.push(`  return false;`);
  lines.push(`}`);
  lines.push(`function applyIdentityHeaders(headers: { [k: string]: string }, userAgent: string, pinned: string, method: string, opIdem: string): void {`);
  lines.push(`  if (!hasHeader(headers, "user-agent") && userAgent) headers["user-agent"] = userAgent;`);
  lines.push(`  if (!hasHeader(headers, "x-request-id")) headers["x-request-id"] = pinned || newRequestId();`);
  lines.push(`  const m = String(method || "").toUpperCase();`);
  lines.push(`  if ((m === "POST" || m === "PUT" || m === "PATCH" || m === "DELETE") && opIdem && !hasHeader(headers, "idempotency-key")) headers["idempotency-key"] = opIdem;`);
  lines.push(`}`);
  if (auth.any) {
    lines.push(`function envAuthString(name: string): string {`);
    lines.push(`  const g = globalThis as { process?: { env?: { [k: string]: string | undefined } } };`);
    lines.push(`  const env = (g.process && g.process.env) ? g.process.env : {};`);
    lines.push(`  const v = env[name];`);
    lines.push(`  return v && String(v).trim() ? String(v).trim() : "";`);
    lines.push(`}`);
  }
  lines.push(`function retryDelayMs(res: { headers: { get(name: string): string | null } }, attempt: number): number {`);
  lines.push(`  const raw = res.headers.get("retry-after");`);
  lines.push(`  if (raw) {`);
  lines.push(`    const sec = Number(raw);`);
  lines.push(`    if (Number.isFinite(sec) && sec >= 0 && sec < 30) return Math.floor(sec * 1000);`);
  lines.push(`    const when = Date.parse(raw);`);
  lines.push(`    if (!Number.isNaN(when)) {`);
  lines.push(`      const delta = when - Date.now();`);
  lines.push(`      if (delta >= 0 && delta < 30000) return delta;`);
  lines.push(`    }`);
  lines.push(`  }`);
  lines.push(`  return 100 * Math.pow(2, attempt);`);
  lines.push(`}`);
  lines.push(`export function createClient(opts: ClientOptions = {}) {`);
  lines.push(`  const baseUrl = (opts.baseUrl || "").replace(/\\/$/, "");`);
  lines.push(`  const f = opts.fetchImpl || fetch;`);
  lines.push(`  const timeoutMs = opts.timeoutMs != null && Number.isFinite(Number(opts.timeoutMs)) && Number(opts.timeoutMs) > 0 ? Number(opts.timeoutMs) : envTimeoutMs();`);
  lines.push(`  const userAgent = (opts.userAgent != null && String(opts.userAgent).trim()) ? String(opts.userAgent).trim() : ${JSON.stringify(defaultUserAgent(opts))};`);
  lines.push(`  const pinnedRequestId = (opts.requestId != null && String(opts.requestId).trim()) ? String(opts.requestId).trim() : envRequestId();`);
  lines.push(`  const pinnedIdempotencyKey = (opts.idempotencyKey != null && String(opts.idempotencyKey).trim()) ? String(opts.idempotencyKey).trim() : envIdempotencyKey();`);
  if (auth.hasBearer) {
    lines.push(`  const bearerToken = (opts.bearerToken != null && String(opts.bearerToken).trim()) ? String(opts.bearerToken).trim() : envAuthString("SDK_BEARER_TOKEN");`);
  }
  if (auth.headerKeys.length || auth.queryKeys.length) {
    lines.push(`  const apiKey = (opts.apiKey != null && String(opts.apiKey).trim()) ? String(opts.apiKey).trim() : envAuthString("SDK_API_KEY");`);
  }
  const reqSig = auth.any
    ? `  async function request(method: string, path: string, body?: unknown, auth?: { bearer?: boolean; headers?: string[]; query?: string[] }) {`
    : `  async function request(method: string, path: string, body?: unknown) {`;
  lines.push(reqSig);
  lines.push(`    const mutating = method === "POST" || method === "PUT" || method === "PATCH" || method === "DELETE";`);
  lines.push(`    const opIdempotencyKey = mutating ? (pinnedIdempotencyKey || newRequestId()) : "";`);
  lines.push(`    const maxAttempts = 3;`);
  lines.push(`    for (let attempt = 0; attempt < maxAttempts; attempt++) {`);
  lines.push(`      const ac = new AbortController();`);
  lines.push(`      const timer = setTimeout(() => ac.abort(), timeoutMs);`);
  if (auth.any) {
    lines.push(`      const headers: { [k: string]: string } = {};`);
    lines.push(`      if (body) headers["content-type"] = "application/json";`);
    if (auth.hasBearer) {
      lines.push(`      if (auth && auth.bearer && bearerToken) headers["authorization"] = "Bearer " + bearerToken;`);
    }
    if (auth.headerKeys.length) {
      lines.push(`      if (auth && auth.headers && apiKey) {`);
      lines.push(`        for (const h of auth.headers) headers[h] = apiKey;`);
      lines.push(`      }`);
    }
    lines.push(`      let url = baseUrl + path;`);
    if (auth.queryKeys.length) {
      lines.push(`      if (auth && auth.query && apiKey) {`);
      lines.push(`        for (const q of auth.query) url += (url.includes("?") ? "&" : "?") + encodeURIComponent(q) + "=" + encodeURIComponent(apiKey);`);
      lines.push(`      }`);
    }
    lines.push(`      applyIdentityHeaders(headers, userAgent, pinnedRequestId, method, opIdempotencyKey);`);
    lines.push(`      const init = {`);
    lines.push(`        method,`);
    lines.push(`        headers: Object.keys(headers).length ? headers : undefined,`);
    lines.push(`        body: body ? JSON.stringify(body) : undefined,`);
    lines.push(`        signal: ac.signal,`);
    lines.push(`      };`);
    lines.push(`      let res;`);
    lines.push(`      try {`);
    lines.push(`        res = await f(url, init);`);
  } else {
    lines.push(`      const headers: { [k: string]: string } = {};`);
    lines.push(`      if (body) headers["content-type"] = "application/json";`);
    lines.push(`      applyIdentityHeaders(headers, userAgent, pinnedRequestId, method, opIdempotencyKey);`);
    lines.push(`      const init = {`);
    lines.push(`        method,`);
    lines.push(`        headers: Object.keys(headers).length ? headers : undefined,`);
    lines.push(`        body: body ? JSON.stringify(body) : undefined,`);
    lines.push(`        signal: ac.signal,`);
    lines.push(`      };`);
    lines.push(`      let res;`);
    lines.push(`      try {`);
    lines.push(`        res = await f(baseUrl + path, init);`);
  }
  lines.push(`      } catch (err) {`);
  lines.push(`        if (attempt >= maxAttempts - 1) throw err;`);
  lines.push(`        await sleep(100 * Math.pow(2, attempt));`);
  lines.push(`        continue;`);
  lines.push(`      } finally {`);
  lines.push(`        clearTimeout(timer);`);
  lines.push(`      }`);
  lines.push(`      if (res.ok) {`);
  lines.push(`        const text = await res.text();`);
  lines.push(`        return text ? JSON.parse(text) : null;`);
  lines.push(`      }`);
  lines.push(`      if ((res.status === 429 || res.status >= 500) && attempt < maxAttempts - 1) {`);
  lines.push(`        await sleep(retryDelayMs(res, attempt));`);
  lines.push(`        continue;`);
  lines.push(`      }`);
  lines.push(`      throw new Error(method + " " + path + " -> " + res.status);`);
  lines.push(`    }`);
  lines.push(`    throw new Error(method + " " + path + " -> network");`);
  lines.push(`  }`);
  if (pageable.length) emitTsPageRuntime(lines);
  for (const op of ops) {
    const fn = op.operationId;
    lines.push(`  async function ${fn}(args: Record<string, unknown> = {}) {`);
    lines.push(`    let path = ${JSON.stringify(op.path)};`);
    lines.push(`    path = path.replace(/\\{([^}]+)\\}/g, (_, k) => encodeURIComponent(String(args[k] ?? "")));`);
    if (op.method === "GET" || op.method === "DELETE") {
      lines.push(`    const q = new URLSearchParams();`);
      lines.push(`    for (const [k, v] of Object.entries(args)) {`);
      lines.push(`      if (path.includes("/" + encodeURIComponent(String(v)))) continue;`);
      lines.push(`      if (v !== undefined && v !== null) q.set(k, String(v));`);
      lines.push(`    }`);
      lines.push(`    const qs = q.toString();`);
      const authSuf = tsAuthSuffix(op, auth.any);
      lines.push(`    return request(${JSON.stringify(op.method)}, path + (qs ? "?" + qs : "")` + (authSuf ? ", undefined" + authSuf : "") + `);`);
    } else {
      lines.push(`    return request(${JSON.stringify(op.method)}, path, args` + tsAuthSuffix(op, auth.any) + `);`);
    }
    lines.push(`  }`);
    const hit = pageable.find((p) => p.op === op);
    if (hit) emitTsIterate(lines, op, hit.info, hit.iter);
  }
  lines.push(`  return {`);
  for (const op of ops) {
    lines.push(`    ${op.operationId},`);
  }
  for (const p of pageable) {
    lines.push(`    ${p.iter},`);
  }
  lines.push(`  };`);
  lines.push(`}`);
  lines.push("");
  return lines.join("\n");
}

function emitPyPageRuntime(lines) {
  lines.push(`# Page helper: GET page/pageSize/offset/limit/cursor/starting_after. Follow next/next_cursor/nextPageToken or increment page. Cap 1000.`);
  lines.push(`def _page_len(data: Any) -> int:`);
  lines.push(`    if isinstance(data, list):`);
  lines.push(`        return len(data)`);
  lines.push(`    if isinstance(data, dict):`);
  lines.push(`        for k in ("data", "items", "results"):`);
  lines.push(`            v = data.get(k)`);
  lines.push(`            if isinstance(v, list):`);
  lines.push(`                return len(v)`);
  lines.push(`    return -1`);
  lines.push(``);
  lines.push(`def _next_cursor(data: Any) -> Any:`);
  lines.push(`    if isinstance(data, dict):`);
  lines.push(`        for k in ("next", "next_cursor", "nextPageToken"):`);
  lines.push(`            v = data.get(k)`);
  lines.push(`            if isinstance(v, str) and v:`);
  lines.push(`                return v`);
  lines.push(`    return None`);
  lines.push(``);
  lines.push(`def _as_int(v: Any, default: int) -> int:`);
  lines.push(`    try:`);
  lines.push(`        if v is None:`);
  lines.push(`            return default`);
  lines.push(`        return int(v)`);
  lines.push(`    except (TypeError, ValueError):`);
  lines.push(`        return default`);
  lines.push(``);
}

function emitPyIterate(lines, op, info, iterName) {
  const fn = op.operationId;
  const mode = info.mode;
  const sizeKey = info.sizeParam;
  const cursorKey = info.cursorParam || "cursor";
  const pageKey = info.pageParam || "page";
  const offsetKey = info.offsetParam || "offset";
  const summary = `Auto pages ${fn} (page/cursor). Not a full pager.`.replace(/\\/g, "\\\\").replace(/"""/g, '\\"\\"\\"');
  lines.push(`    def ${iterName}(self, args: Optional[Mapping[str, Any]] = None) -> Any:`);
  lines.push(`        """${summary}"""`);
  lines.push(`        state: MutableMapping[str, Any] = dict(args or {})`);
  if (mode === "offset") {
    lines.push(`        offset = _as_int(state.get(${JSON.stringify(offsetKey)}), 0)`);
  } else if (mode === "page") {
    lines.push(`        page = _as_int(state.get(${JSON.stringify(pageKey)}), 1)`);
    lines.push(`        if page < 1:`);
    lines.push(`            page = 1`);
  }
  lines.push(`        n = 0`);
  lines.push(`        while n < 1000:`);
  lines.push(`            n += 1`);
  lines.push(`            call = dict(state)`);
  if (mode === "offset") {
    lines.push(`            call[${JSON.stringify(offsetKey)}] = offset`);
  } else if (mode === "page") {
    lines.push(`            call[${JSON.stringify(pageKey)}] = page`);
  }
  lines.push(`            data = self.${fn}(call)`);
  lines.push(`            yield data`);
  lines.push(`            ln = _page_len(data)`);
  if (sizeKey) {
    lines.push(`            size = _as_int(call.get(${JSON.stringify(sizeKey)}), 0)`);
    lines.push(`            if data is None or ln == 0 or (size > 0 and ln >= 0 and ln < size):`);
    lines.push(`                break`);
  } else {
    lines.push(`            if data is None or ln == 0:`);
    lines.push(`                break`);
  }
  lines.push(`            cur = _next_cursor(data)`);
  lines.push(`            if cur and cur != state.get(${JSON.stringify(cursorKey)}):`);
  lines.push(`                state[${JSON.stringify(cursorKey)}] = cur`);
  lines.push(`                continue`);
  if (mode === "cursor") {
    lines.push(`            break`);
  } else if (mode === "offset") {
    lines.push(`            if ln < 0:`);
    lines.push(`                break`);
    if (sizeKey) {
      lines.push(`            step = size if size > 0 else ln`);
    } else {
      lines.push(`            step = ln`);
    }
    lines.push(`            if step <= 0:`);
    lines.push(`                break`);
    lines.push(`            offset += step`);
  } else {
    lines.push(`            if ln < 0:`);
    lines.push(`                break`);
    lines.push(`            page += 1`);
  }
  lines.push(``);
}

/** Minimal sync Python client (stdlib urllib only — no requests). */
export function generatePyClient(ops, title = "GeneratedClient", opts = {}) {
  const pkg = pkgFromOpts(opts);
  const pageable = pageableOps(ops);
  const auth = authFlags(ops);
  const lines = [];
  lines.push(`# Auto-generated by sdk-mcp-gen — do not edit by hand`);
  lines.push(`# API: ${title}`);
  lines.push(`from __future__ import annotations`);
  lines.push(``);
  lines.push(`import json`);
  lines.push(`import os`);
  lines.push(`import re`);
  lines.push(`import time`);
  lines.push(`import urllib.error`);
  lines.push(`import urllib.parse`);
  lines.push(`import urllib.request`);
  lines.push(`import uuid`);
  lines.push(`from email.utils import parsedate_to_datetime`);
  lines.push(`from typing import Any, Mapping, MutableMapping, Optional`);
  lines.push(``);
  lines.push(`__package_name__ = ${JSON.stringify(pkg.ident)}`);
  lines.push(``);
  lines.push(`# Retry transient HTTP failures (429 / 5xx / network throw): max 2 retries, ~100ms exponential backoff, honor Retry-After <30s.`);
  lines.push(`# Per-attempt request timeout (default 10s): urllib timeout. Override via Client(timeout=...) or env SDK_TIMEOUT_MS / SDK_TIMEOUT_SEC.`);
  lines.push(`# Default User-Agent ${JSON.stringify(defaultUserAgent(opts))} unless the caller already set User-Agent.`);
  lines.push(`# X-Request-Id: new id per HTTP attempt (retries get a new id). Pin via Client(request_id=...) or env SDK_REQUEST_ID (tests).`);
  lines.push(`# Idempotency-Key: on POST/PUT/PATCH/DELETE when unset. New key per logical call (retries reuse). Pin via Client(idempotency_key=...) or env SDK_IDEMPOTENCY_KEY (tests).`);
  if (auth.any) {
    lines.push(`# Auth from OpenAPI securitySchemes (http bearer, apiKey header/query). oauth2 / openIdConnect skipped (no fake tokens).`);
    lines.push(`# Constructor bearer_token / api_key or env SDK_BEARER_TOKEN / SDK_API_KEY. Attached per OpenAPI operation security on every attempt. Ops without security omit credentials. Values never logged.`);
  }
  lines.push(`def _env_timeout_s() -> float:`);
  lines.push(`    raw_ms = os.environ.get("SDK_TIMEOUT_MS")`);
  lines.push(`    if raw_ms:`);
  lines.push(`        try:`);
  lines.push(`            ms = float(raw_ms)`);
  lines.push(`            if ms > 0:`);
  lines.push(`                return ms / 1000.0`);
  lines.push(`        except (TypeError, ValueError):`);
  lines.push(`            pass`);
  lines.push(`    raw_sec = os.environ.get("SDK_TIMEOUT_SEC")`);
  lines.push(`    if raw_sec:`);
  lines.push(`        try:`);
  lines.push(`            sec = float(raw_sec)`);
  lines.push(`            if sec > 0:`);
  lines.push(`                return sec`);
  lines.push(`        except (TypeError, ValueError):`);
  lines.push(`            pass`);
  lines.push(`    return 10.0`);
  lines.push(``);
  lines.push(`def _env_request_id() -> str:`);
  lines.push(`    raw = os.environ.get("SDK_REQUEST_ID")`);
  lines.push(`    if raw and str(raw).strip():`);
  lines.push(`        return str(raw).strip()`);
  lines.push(`    return ""`);
  lines.push(``);
  lines.push(`def _env_idempotency_key() -> str:`);
  lines.push(`    raw = os.environ.get("SDK_IDEMPOTENCY_KEY")`);
  lines.push(`    if raw and str(raw).strip():`);
  lines.push(`        return str(raw).strip()`);
  lines.push(`    return ""`);
  lines.push(``);
  lines.push(`def _new_request_id() -> str:`);
  lines.push(`    return str(uuid.uuid4())`);
  lines.push(``);
  lines.push(`def _has_header(headers: dict, name: str) -> bool:`);
  lines.push(`    want = name.lower()`);
  lines.push(`    return any(str(k).lower() == want for k in headers)`);
  lines.push(``);
  lines.push(`def _apply_identity(headers: dict, user_agent: str, pinned: str, method: str = "", op_idem: str = "") -> None:`);
  lines.push(`    if not _has_header(headers, "User-Agent") and user_agent:`);
  lines.push(`        headers["User-Agent"] = user_agent`);
  lines.push(`    if not _has_header(headers, "X-Request-Id"):`);
  lines.push(`        headers["X-Request-Id"] = pinned or _new_request_id()`);
  lines.push(`    m = str(method or "").upper()`);
  lines.push(`    if m in ("POST", "PUT", "PATCH", "DELETE") and op_idem and not _has_header(headers, "Idempotency-Key"):`);
  lines.push(`        headers["Idempotency-Key"] = op_idem`);
  lines.push(``);
  lines.push(`def _retry_delay_s(headers: Any, attempt: int) -> float:`);
  lines.push(`    raw = headers.get("Retry-After") if headers is not None else None`);
  lines.push(`    if raw:`);
  lines.push(`        try:`);
  lines.push(`            sec = float(str(raw).strip())`);
  lines.push(`            if 0 <= sec < 30:`);
  lines.push(`                return sec`);
  lines.push(`        except (TypeError, ValueError):`);
  lines.push(`            try:`);
  lines.push(`                when = parsedate_to_datetime(str(raw))`);
  lines.push(`                delta = when.timestamp() - time.time()`);
  lines.push(`                if 0 <= delta < 30:`);
  lines.push(`                    return delta`);
  lines.push(`            except (TypeError, ValueError, OverflowError, OSError):`);
  lines.push(`                pass`);
  lines.push(`    return 0.1 * (2 ** attempt)`);
  lines.push(``);
  if (auth.any) {
    lines.push(`def _env_auth(name: str) -> str:`);
    lines.push(`    raw = os.environ.get(name)`);
    lines.push(`    if raw and str(raw).strip():`);
    lines.push(`        return str(raw).strip()`);
    lines.push(`    return ""`);
    lines.push(``);
  }
  if (pageable.length) emitPyPageRuntime(lines);
  lines.push(`class Client:`);
  lines.push(`    """Sync HTTP client stub generated from OpenAPI."""`);
  lines.push(``);
  const initArgs = ["self", "base_url: str = \"\"", "opener: Any = None", "timeout: Any = None", "user_agent: Any = None", "request_id: Any = None", "idempotency_key: Any = None"];
  if (auth.hasBearer) initArgs.push("bearer_token: Any = None");
  if (auth.headerKeys.length || auth.queryKeys.length) initArgs.push("api_key: Any = None");
  lines.push(`    def __init__(${initArgs.join(", ")}) -> None:`);
  lines.push(`        self.base_url = (base_url or "").rstrip("/")`);
  lines.push(`        self._opener = opener`);
  lines.push(`        if timeout is not None:`);
  lines.push(`            try:`);
  lines.push(`                t = float(timeout)`);
  lines.push(`                self._timeout = t if t > 0 else _env_timeout_s()`);
  lines.push(`            except (TypeError, ValueError):`);
  lines.push(`                self._timeout = _env_timeout_s()`);
  lines.push(`        else:`);
  lines.push(`            self._timeout = _env_timeout_s()`);
  lines.push(`        if user_agent is not None and str(user_agent).strip():`);
  lines.push(`            self._user_agent = str(user_agent).strip()`);
  lines.push(`        else:`);
  lines.push(`            self._user_agent = ${JSON.stringify(defaultUserAgent(opts))}`);
  lines.push(`        if request_id is not None and str(request_id).strip():`);
  lines.push(`            self._request_id = str(request_id).strip()`);
  lines.push(`        else:`);
  lines.push(`            self._request_id = _env_request_id()`);
  lines.push(`        if idempotency_key is not None and str(idempotency_key).strip():`);
  lines.push(`            self._idempotency_key = str(idempotency_key).strip()`);
  lines.push(`        else:`);
  lines.push(`            self._idempotency_key = _env_idempotency_key()`);
  if (auth.hasBearer) {
    lines.push(`        if bearer_token is not None and str(bearer_token).strip():`);
    lines.push(`            self._bearer_token = str(bearer_token).strip()`);
    lines.push(`        else:`);
    lines.push(`            self._bearer_token = _env_auth("SDK_BEARER_TOKEN")`);
  }
  if (auth.headerKeys.length || auth.queryKeys.length) {
    lines.push(`        if api_key is not None and str(api_key).strip():`);
    lines.push(`            self._api_key = str(api_key).strip()`);
    lines.push(`        else:`);
    lines.push(`            self._api_key = _env_auth("SDK_API_KEY")`);
  }
  lines.push(``);
  lines.push(auth.any ? `    def _request(self, method: str, path: str, body: Any = None, auth: Any = None) -> Any:` : `    def _request(self, method: str, path: str, body: Any = None) -> Any:`);
  lines.push(`        url = self.base_url + path`);
  lines.push(`        data = None`);
  lines.push(`        headers: dict[str, str] = {}`);
  lines.push(`        if body is not None:`);
  lines.push(`            data = json.dumps(body).encode("utf-8")`);
  lines.push(`            headers["Content-Type"] = "application/json"`);
  lines.push(`        open_url = self._opener.open if self._opener is not None else urllib.request.urlopen`);
  lines.push(`        op_idem = ""`);
  lines.push(`        if str(method).upper() in ("POST", "PUT", "PATCH", "DELETE"):`);
  lines.push(`            op_idem = self._idempotency_key or _new_request_id()`);
  lines.push(`        last_err: Any = None`);
  lines.push(`        for attempt in range(3):`);
  if (auth.any) {
    lines.push(`            hdrs = dict(headers)`);
    if (auth.hasBearer) {
      lines.push(`            if auth and auth.get("bearer") and self._bearer_token:`);
      lines.push(`                hdrs["Authorization"] = "Bearer " + self._bearer_token`);
    }
    if (auth.headerKeys.length) {
      lines.push(`            if auth and self._api_key:`);
      lines.push(`                for h in (auth.get("headers") or []):`);
      lines.push(`                    hdrs[h] = self._api_key`);
    }
    lines.push(`            req_url = url`);
    if (auth.queryKeys.length) {
      lines.push(`            if auth and self._api_key:`);
      lines.push(`                for q in (auth.get("query") or []):`);
      lines.push(`                    req_url = req_url + ("&" if "?" in req_url else "?") + urllib.parse.quote(q, safe="") + "=" + urllib.parse.quote(self._api_key, safe="")`);
    }
    lines.push(`            _apply_identity(hdrs, self._user_agent, self._request_id, method, op_idem)`);
    lines.push(`            req = urllib.request.Request(req_url, data=data, headers=hdrs, method=method)`);
  } else {
    lines.push(`            hdrs = dict(headers)`);
    lines.push(`            _apply_identity(hdrs, self._user_agent, self._request_id, method, op_idem)`);
    lines.push(`            req = urllib.request.Request(url, data=data, headers=hdrs, method=method)`);
  }
  lines.push(`            try:`);
  lines.push(`                with open_url(req, timeout=self._timeout) as res:`);
  lines.push(`                    text = res.read().decode("utf-8")`);
  lines.push(`                    return json.loads(text) if text else None`);
  lines.push(`            except urllib.error.HTTPError as e:`);
  lines.push(`                last_err = e`);
  lines.push(`                code = e.code`);
  lines.push(`                hdrs = e.headers`);
  lines.push(`                try:`);
  lines.push(`                    e.close()`);
  lines.push(`                except Exception:`);
  lines.push(`                    pass`);
  lines.push(`                if (code == 429 or code >= 500) and attempt < 2:`);
  lines.push(`                    time.sleep(_retry_delay_s(hdrs, attempt))`);
  lines.push(`                    continue`);
  lines.push(`                raise RuntimeError(f"{method} {path} -> {code}") from e`);
  lines.push(`            except (urllib.error.URLError, TimeoutError, OSError) as e:`);
  lines.push(`                last_err = e`);
  lines.push(`                if attempt < 2:`);
  lines.push(`                    time.sleep(0.1 * (2 ** attempt))`);
  lines.push(`                    continue`);
  lines.push(`                raise`);
  lines.push(`        if last_err is not None:`);
  lines.push(`            raise last_err`);
  lines.push(`        raise RuntimeError(f"{method} {path} -> network")`);
  lines.push(``);
  for (const op of ops) {
    const fn = op.operationId;
    const summary = String(op.summary || "")
      .replace(/\\/g, "\\\\")
      .replace(/"""/g, '\\"\\"\\"');
    lines.push(`    def ${fn}(self, args: Optional[Mapping[str, Any]] = None) -> Any:`);
    if (summary) {
      lines.push(`        """${summary}"""`);
    }
    lines.push(`        args_map: MutableMapping[str, Any] = dict(args or {})`);
    lines.push(`        path = ${JSON.stringify(op.path)}`);
    lines.push(`        def _sub(m: Any) -> str:`);
    lines.push(`            key = m.group(1)`);
    lines.push(`            val = args_map.pop(key, "")`);
    lines.push(`            return urllib.parse.quote(str(val), safe="")`);
    lines.push(`        path = re.sub(r"\\{([^}]+)\\}", _sub, path)`);
    if (op.method === "GET" || op.method === "DELETE") {
      lines.push(`        q = {k: str(v) for k, v in args_map.items() if v is not None}`);
      lines.push(`        qs = urllib.parse.urlencode(q)`);
      const authSuf = pyAuthSuffix(op, auth.any);
      lines.push(`        return self._request(${JSON.stringify(op.method)}, path + ("?" + qs if qs else "")` + (authSuf ? ", None" + authSuf : "") + `)`);
    } else {
      lines.push(`        return self._request(${JSON.stringify(op.method)}, path, dict(args_map)` + pyAuthSuffix(op, auth.any) + `)`);
    }
    lines.push(``);
    const hit = pageable.find((p) => p.op === op);
    if (hit) emitPyIterate(lines, op, hit.info, hit.iter);
  }
  lines.push(``);
  const createArgs = ["base_url: str = \"\"", "opener: Any = None", "timeout: Any = None", "user_agent: Any = None", "request_id: Any = None", "idempotency_key: Any = None"];
  const createCall = ["base_url=base_url", "opener=opener", "timeout=timeout", "user_agent=user_agent", "request_id=request_id", "idempotency_key=idempotency_key"];
  if (auth.hasBearer) {
    createArgs.push("bearer_token: Any = None");
    createCall.push("bearer_token=bearer_token");
  }
  if (auth.headerKeys.length || auth.queryKeys.length) {
    createArgs.push("api_key: Any = None");
    createCall.push("api_key=api_key");
  }
  lines.push(`def create_client(${createArgs.join(", ")}) -> Client:`);
  lines.push(`    return Client(${createCall.join(", ")})`);
  lines.push(``);
  return lines.join("\n");
}


/** Capitalize first letter for Go exported identifiers. */
export function toGoExported(name) {
  const cleaned = String(name || "Op").replace(/[^a-zA-Z0-9_]/g, "_");
  if (!cleaned) return "Op";
  if (/^[0-9]/.test(cleaned)) return "Op" + cleaned;
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

function emitGoPageRuntime(lines) {
  lines.push(`// pageLen is the length of a list payload, or -1 if the shape is unknown.`);
  lines.push(`func pageLen(data any) int {`);
  lines.push(`\tswitch v := data.(type) {`);
  lines.push(`\tcase []any:`);
  lines.push(`\t\treturn len(v)`);
  lines.push(`\tcase map[string]any:`);
  lines.push(`\t\tfor _, k := range []string{"data", "items", "results"} {`);
  lines.push(`\t\t\tif arr, ok := v[k].([]any); ok {`);
  lines.push(`\t\t\t\treturn len(arr)`);
  lines.push(`\t\t\t}`);
  lines.push(`\t\t}`);
  lines.push(`\t}`);
  lines.push(`\treturn -1`);
  lines.push(`}`);
  lines.push(``);
  lines.push(`func nextCursorOf(data any) string {`);
  lines.push(`\tm, ok := data.(map[string]any)`);
  lines.push(`\tif !ok {`);
  lines.push(`\t\treturn ""`);
  lines.push(`\t}`);
  lines.push(`\tfor _, k := range []string{"next", "next_cursor", "nextPageToken"} {`);
  lines.push(`\t\tif s, ok := m[k].(string); ok && s != "" {`);
  lines.push(`\t\t\treturn s`);
  lines.push(`\t\t}`);
  lines.push(`\t}`);
  lines.push(`\treturn ""`);
  lines.push(`}`);
  lines.push(``);
  lines.push(`func asInt(v any) int {`);
  lines.push(`\tswitch n := v.(type) {`);
  lines.push(`\tcase int:`);
  lines.push(`\t\treturn n`);
  lines.push(`\tcase int64:`);
  lines.push(`\t\treturn int(n)`);
  lines.push(`\tcase float64:`);
  lines.push(`\t\treturn int(n)`);
  lines.push(`\tcase string:`);
  lines.push(`\t\ti, err := strconv.Atoi(n)`);
  lines.push(`\t\tif err == nil {`);
  lines.push(`\t\t\treturn i`);
  lines.push(`\t\t}`);
  lines.push(`\t}`);
  lines.push(`\treturn 0`);
  lines.push(`}`);
  lines.push(``);
  lines.push(`func cloneArgs(args map[string]any) map[string]any {`);
  lines.push(`\tout := map[string]any{}`);
  lines.push(`\tif args == nil {`);
  lines.push(`\t\treturn out`);
  lines.push(`\t}`);
  lines.push(`\tfor k, v := range args {`);
  lines.push(`\t\tout[k] = v`);
  lines.push(`\t}`);
  lines.push(`\treturn out`);
  lines.push(`}`);
  lines.push(``);
}

function emitGoIterate(lines, op, info, iterName) {
  const fn = toGoExported(op.operationId);
  const goIter = toGoExported(iterName);
  const mode = info.mode;
  const sizeKey = info.sizeParam;
  const cursorKey = info.cursorParam || "cursor";
  const pageKey = info.pageParam || "page";
  const offsetKey = info.offsetParam || "offset";
  const summary = `walks pages for ${op.operationId} (page/cursor; cap 1000). Not a full pager.`.replace(/\*\//g, "* /");
  lines.push(`// ${goIter} ${summary}`);
  lines.push(`func (c *Client) ${goIter}(args map[string]any) ([]any, error) {`);
  lines.push(`\tstate := cloneArgs(args)`);
  if (mode === "offset") {
    lines.push(`\toffset := asInt(state[${JSON.stringify(offsetKey)}])`);
  } else if (mode === "page") {
    lines.push(`\tpage := asInt(state[${JSON.stringify(pageKey)}])`);
    lines.push(`\tif page < 1 {`);
    lines.push(`\t\tpage = 1`);
    lines.push(`\t}`);
  }
  lines.push(`\tvar pages []any`);
  lines.push(`\tfor n := 0; n < 1000; n++ {`);
  lines.push(`\t\tcall := cloneArgs(state)`);
  if (mode === "offset") {
    lines.push(`\t\tcall[${JSON.stringify(offsetKey)}] = offset`);
  } else if (mode === "page") {
    lines.push(`\t\tcall[${JSON.stringify(pageKey)}] = page`);
  }
  lines.push(`\t\tdata, err := c.${fn}(call)`);
  lines.push(`\t\tif err != nil {`);
  lines.push(`\t\t\treturn pages, err`);
  lines.push(`\t\t}`);
  lines.push(`\t\tpages = append(pages, data)`);
  lines.push(`\t\tln := pageLen(data)`);
  if (sizeKey) {
    lines.push(`\t\tsize := asInt(call[${JSON.stringify(sizeKey)}])`);
    lines.push(`\t\tif data == nil || ln == 0 || (size > 0 && ln >= 0 && ln < size) {`);
    lines.push(`\t\t\tbreak`);
    lines.push(`\t\t}`);
  } else {
    lines.push(`\t\tif data == nil || ln == 0 {`);
    lines.push(`\t\t\tbreak`);
    lines.push(`\t\t}`);
  }
  lines.push(`\t\tcur := nextCursorOf(data)`);
  lines.push(`\t\tif prev, _ := state[${JSON.stringify(cursorKey)}].(string); cur != "" && cur != prev {`);
  lines.push(`\t\t\tstate[${JSON.stringify(cursorKey)}] = cur`);
  lines.push(`\t\t\tcontinue`);
  lines.push(`\t\t}`);
  if (mode === "cursor") {
    lines.push(`\t\tbreak`);
  } else if (mode === "offset") {
    lines.push(`\t\tif ln < 0 {`);
    lines.push(`\t\t\tbreak`);
    lines.push(`\t\t}`);
    if (sizeKey) {
      lines.push(`\t\tstep := ln`);
      lines.push(`\t\tif size > 0 {`);
      lines.push(`\t\t\tstep = size`);
      lines.push(`\t\t}`);
    } else {
      lines.push(`\t\tstep := ln`);
    }
    lines.push(`\t\tif step <= 0 {`);
    lines.push(`\t\t\tbreak`);
    lines.push(`\t\t}`);
    lines.push(`\t\toffset += step`);
  } else {
    lines.push(`\t\tif ln < 0 {`);
    lines.push(`\t\t\tbreak`);
    lines.push(`\t\t}`);
    lines.push(`\t\tpage++`);
  }
  lines.push(`\t}`);
  lines.push(`\treturn pages, nil`);
  lines.push(`}`);
  lines.push(``);
}

/** Minimal Go HTTP client stub (stdlib net/http only). package client. */
export function generateGoClient(ops, title = "GeneratedClient", opts = {}) {
  const pkg = pkgFromOpts(opts);
  const pageable = pageableOps(ops);
  const auth = authFlags(ops);
  const lines = [];
  lines.push(`// Auto-generated by sdk-mcp-gen — do not edit by hand`);
  lines.push(`// API: ${title}`);
  lines.push(`// module ${pkg.modPath}`);
  lines.push(`package ${pkg.ident}`);
  lines.push(``);
  lines.push(`import (`);
  lines.push(`\t"bytes"`);
  lines.push(`\t"context"`);
  lines.push(`\t"crypto/rand"`);
  lines.push(`\t"encoding/json"`);
  lines.push(`\t"fmt"`);
  lines.push(`\t"io"`);
  lines.push(`\t"net/http"`);
  lines.push(`\t"net/url"`);
  lines.push(`\t"os"`);
  lines.push(`\t"strconv"`);
  lines.push(`\t"strings"`);
  lines.push(`\t"time"`);
  lines.push(`)`);
  lines.push(``);
  lines.push(`// Client is a minimal sync HTTP client stub generated from OpenAPI.`);
  lines.push(`type Client struct {`);
  lines.push(`\tBaseURL    string`);
  lines.push(`\tHTTPClient *http.Client`);
  lines.push(`\tTimeout    time.Duration`);
  lines.push(`\tUserAgent  string`);
  lines.push(`\tRequestID  string`);
  lines.push(`\tIdempotencyKey string`);
  if (auth.hasBearer) {
    lines.push(`\tBearerToken string`);
  }
  if (auth.headerKeys.length || auth.queryKeys.length) {
    lines.push(`\tAPIKey string`);
  }
  lines.push(`}`);
  if (auth.any) {
    lines.push(``);
    lines.push(`type reqAuth struct {`);
    lines.push(`	Bearer  bool`);
    lines.push(`	Headers []string`);
    lines.push(`	Query   []string`);
    lines.push(`}`);
    lines.push(``);
    lines.push(`// Auth from OpenAPI securitySchemes (http bearer, apiKey header/query). oauth2 / openIdConnect skipped (no fake tokens).`);
    lines.push(`// Set BearerToken / APIKey or env SDK_BEARER_TOKEN / SDK_API_KEY. Attached per OpenAPI operation security on every attempt. Ops without security omit credentials. Values never logged.`);
    lines.push(`func envAuth(name string) string {`);
    lines.push(`\treturn strings.TrimSpace(os.Getenv(name))`);
    lines.push(`}`);
  }
  lines.push(``);
  lines.push(`// Default User-Agent ${JSON.stringify(defaultUserAgent(opts))} unless the caller already set User-Agent.`);
  lines.push(`// X-Request-Id: new id per HTTP attempt (retries get a new id). Pin via Client.RequestID or env SDK_REQUEST_ID (tests).`);
  lines.push(`// Idempotency-Key: on POST/PUT/PATCH/DELETE when unset. New key per logical call (retries reuse). Pin via Client.IdempotencyKey or env SDK_IDEMPOTENCY_KEY (tests).`);
  lines.push(`func envRequestID() string {`);
  lines.push(`\treturn strings.TrimSpace(os.Getenv("SDK_REQUEST_ID"))`);
  lines.push(`}`);
  lines.push(``);
  lines.push(`func envIdempotencyKey() string {`);
  lines.push(`\treturn strings.TrimSpace(os.Getenv("SDK_IDEMPOTENCY_KEY"))`);
  lines.push(`}`);
  lines.push(``);
  lines.push(`func newRequestID() string {`);
  lines.push(`\tvar b [16]byte`);
  lines.push(`\tif _, err := rand.Read(b[:]); err != nil {`);
  lines.push(`\t\treturn fmt.Sprintf("%d", time.Now().UnixNano())`);
  lines.push(`\t}`);
  lines.push(`\treturn fmt.Sprintf("%x", b[:])`);
  lines.push(`}`);
  lines.push(``);
  lines.push(`func applyIdentityHeaders(req *http.Request, userAgent, pinned, method, opIdem string) {`);
  lines.push(`\tif req.Header.Get("User-Agent") == "" && userAgent != "" {`);
  lines.push(`\t\treq.Header.Set("User-Agent", userAgent)`);
  lines.push(`\t}`);
  lines.push(`\tif req.Header.Get("X-Request-Id") == "" {`);
  lines.push(`\t\tid := pinned`);
  lines.push(`\t\tif id == "" {`);
  lines.push(`\t\t\tid = newRequestID()`);
  lines.push(`\t\t}`);
  lines.push(`\t\treq.Header.Set("X-Request-Id", id)`);
  lines.push(`\t}`);
  lines.push(`\tm := strings.ToUpper(method)`);
  lines.push(`\tif (m == "POST" || m == "PUT" || m == "PATCH" || m == "DELETE") && opIdem != "" && req.Header.Get("Idempotency-Key") == "" {`);
  lines.push(`\t\treq.Header.Set("Idempotency-Key", opIdem)`);
  lines.push(`\t}`);
  lines.push(`}`);
  lines.push(``);
  lines.push(`// envTimeout is the per-attempt request timeout (default 10s). Constructor Timeout or env SDK_TIMEOUT_MS / SDK_TIMEOUT_SEC.`);
  lines.push(`func envTimeout() time.Duration {`);
  lines.push(`\tif raw := os.Getenv("SDK_TIMEOUT_MS"); raw != "" {`);
  lines.push(`\t\tif ms, err := strconv.Atoi(raw); err == nil && ms > 0 {`);
  lines.push(`\t\t\treturn time.Duration(ms) * time.Millisecond`);
  lines.push(`\t\t}`);
  lines.push(`\t}`);
  lines.push(`\tif raw := os.Getenv("SDK_TIMEOUT_SEC"); raw != "" {`);
  lines.push(`\t\tif sec, err := strconv.Atoi(raw); err == nil && sec > 0 {`);
  lines.push(`\t\t\treturn time.Duration(sec) * time.Second`);
  lines.push(`\t\t}`);
  lines.push(`\t}`);
  lines.push(`\treturn 10 * time.Second`);
  lines.push(`}`);
  lines.push(``);
  lines.push(`// NewClient returns a Client with the given base URL.`);
  lines.push(`func NewClient(baseURL string) *Client {`);
  lines.push(`\tc := &Client{`);
  lines.push(`\t\tBaseURL:    strings.TrimRight(baseURL, "/"),`);
  lines.push(`\t\tHTTPClient: http.DefaultClient,`);
  lines.push(`\t\tTimeout:    envTimeout(),`);
  lines.push(`\t\tUserAgent:  ${JSON.stringify(defaultUserAgent(opts))},`);
  lines.push(`\t\tRequestID:  envRequestID(),`);
  lines.push(`\t\tIdempotencyKey: envIdempotencyKey(),`);
  lines.push(`\t}`);
  if (auth.hasBearer) {
    lines.push(`\tc.BearerToken = envAuth("SDK_BEARER_TOKEN")`);
  }
  if (auth.headerKeys.length || auth.queryKeys.length) {
    lines.push(`\tc.APIKey = envAuth("SDK_API_KEY")`);
  }
  lines.push(`\treturn c`);
  lines.push(`}`);
  lines.push(``);
  lines.push(`// retryDelay honors Retry-After when sane (<30s); else ~100ms exponential backoff.`);
  lines.push(`func retryDelay(res *http.Response, attempt int) time.Duration {`);
  lines.push(`\tif res != nil {`);
  lines.push(`\t\tif raw := res.Header.Get("Retry-After"); raw != "" {`);
  lines.push(`\t\t\tif sec, err := strconv.Atoi(raw); err == nil && sec >= 0 && sec < 30 {`);
  lines.push(`\t\t\t\treturn time.Duration(sec) * time.Second`);
  lines.push(`\t\t\t}`);
  lines.push(`\t\t\tif when, err := http.ParseTime(raw); err == nil {`);
  lines.push(`\t\t\t\td := time.Until(when)`);
  lines.push(`\t\t\t\tif d >= 0 && d < 30*time.Second {`);
  lines.push(`\t\t\t\t\treturn d`);
  lines.push(`\t\t\t\t}`);
  lines.push(`\t\t\t}`);
  lines.push(`\t\t}`);
  lines.push(`\t}`);
  lines.push(`\treturn time.Duration(100*(1<<attempt)) * time.Millisecond`);
  lines.push(`}`);
  lines.push(``);
  lines.push(auth.any ? `func (c *Client) request(method, path string, body any, auth *reqAuth) (any, error) {` : `func (c *Client) request(method, path string, body any) (any, error) {`);
  lines.push(`\thc := c.HTTPClient`);
  lines.push(`\tif hc == nil {`);
  lines.push(`\t\thc = http.DefaultClient`);
  lines.push(`\t}`);
  lines.push(`\ttimeout := c.Timeout`);
  lines.push(`\tif timeout <= 0 {`);
  lines.push(`\t\ttimeout = envTimeout()`);
  lines.push(`\t}`);
  lines.push(`\tvar payload []byte`);
  lines.push(`\tif body != nil {`);
  lines.push(`\t\tb, err := json.Marshal(body)`);
  lines.push(`\t\tif err != nil {`);
  lines.push(`\t\t\treturn nil, err`);
  lines.push(`\t\t}`);
  lines.push(`\t\tpayload = b`);
  lines.push(`\t}`);
  lines.push(`\topIdem := ""`);
  lines.push(`\tswitch strings.ToUpper(method) {`);
  lines.push(`\tcase "POST", "PUT", "PATCH", "DELETE":`);
  lines.push(`\t\topIdem = strings.TrimSpace(c.IdempotencyKey)`);
  lines.push(`\t\tif opIdem == "" {`);
  lines.push(`\t\t\topIdem = newRequestID()`);
  lines.push(`\t\t}`);
  lines.push(`\t}`);
  lines.push(`\tvar lastErr error`);
  lines.push(`\tfor attempt := 0; attempt < 3; attempt++ {`);
  lines.push(`\t\tvar rdr io.Reader`);
  lines.push(`\t\tif payload != nil {`);
  lines.push(`\t\t\trdr = bytes.NewReader(payload)`);
  lines.push(`\t\t}`);
  lines.push(`\t\tctx, cancel := context.WithTimeout(context.Background(), timeout)`);
  if (auth.any) {
    lines.push(`\t\treqURL := c.BaseURL + path`);
    if (auth.queryKeys.length) {
      lines.push(`\t\tif auth != nil && strings.TrimSpace(c.APIKey) != "" {`);
      lines.push(`\t\t\tkey := strings.TrimSpace(c.APIKey)`);
      lines.push(`\t\t\tfor _, q := range auth.Query {`);
      lines.push(`\t\t\t\tsep := "?"`);
      lines.push(`\t\t\t\tif strings.Contains(reqURL, "?") {`);
      lines.push(`\t\t\t\t\tsep = "&"`);
      lines.push(`\t\t\t\t}`);
      lines.push(`\t\t\t\treqURL = reqURL + sep + url.QueryEscape(q) + "=" + url.QueryEscape(key)`);
      lines.push(`\t\t\t}`);
      lines.push(`\t\t}`);
    }
    lines.push(`\t\treq, err := http.NewRequestWithContext(ctx, method, reqURL, rdr)`);
  } else {
    lines.push(`\t\treq, err := http.NewRequestWithContext(ctx, method, c.BaseURL+path, rdr)`);
  }
  lines.push(`\t\tif err != nil {`);
  lines.push(`\t\t\tcancel()`);
  lines.push(`\t\t\treturn nil, err`);
  lines.push(`\t\t}`);
  lines.push(`\t\tif payload != nil {`);
  lines.push(`\t\t\treq.Header.Set("Content-Type", "application/json")`);
  lines.push(`\t\t}`);
  if (auth.hasBearer) {
    lines.push(`\t\tif auth != nil && auth.Bearer {`);
    lines.push(`\t\t\tif tok := strings.TrimSpace(c.BearerToken); tok != "" {`);
    lines.push(`\t\t\t\treq.Header.Set("Authorization", "Bearer "+tok)`);
    lines.push(`\t\t\t}`);
    lines.push(`\t\t}`);
  }
  if (auth.headerKeys.length) {
    lines.push(`\t\tif auth != nil && strings.TrimSpace(c.APIKey) != "" {`);
    lines.push(`\t\t\tkey := strings.TrimSpace(c.APIKey)`);
    lines.push(`\t\t\tfor _, h := range auth.Headers {`);
    lines.push(`\t\t\t\treq.Header.Set(h, key)`);
    lines.push(`\t\t\t}`);
    lines.push(`\t\t}`);
  }
  lines.push(`\t\tua := strings.TrimSpace(c.UserAgent)`);
  lines.push(`\t\tif ua == "" {`);
  lines.push(`\t\t\tua = ${JSON.stringify(defaultUserAgent(opts))}`);
  lines.push(`\t\t}`);
  lines.push(`\t\tapplyIdentityHeaders(req, ua, strings.TrimSpace(c.RequestID), method, opIdem)`);
  lines.push(`\t\tres, err := hc.Do(req)`);
  lines.push(`\t\tif err != nil {`);
  lines.push(`\t\t\tcancel()`);
  lines.push(`\t\t\tlastErr = err`);
  lines.push(`\t\t\tif attempt < 2 {`);
  lines.push(`\t\t\t\ttime.Sleep(time.Duration(100*(1<<attempt)) * time.Millisecond)`);
  lines.push(`\t\t\t\tcontinue`);
  lines.push(`\t\t\t}`);
  lines.push(`\t\t\treturn nil, err`);
  lines.push(`\t\t}`);
  lines.push(`\t\tdata, err := io.ReadAll(res.Body)`);
  lines.push(`\t\tres.Body.Close()`);
  lines.push(`\t\tcancel()`);
  lines.push(`\t\tif err != nil {`);
  lines.push(`\t\t\tlastErr = err`);
  lines.push(`\t\t\tif attempt < 2 {`);
  lines.push(`\t\t\t\ttime.Sleep(time.Duration(100*(1<<attempt)) * time.Millisecond)`);
  lines.push(`\t\t\t\tcontinue`);
  lines.push(`\t\t\t}`);
  lines.push(`\t\t\treturn nil, err`);
  lines.push(`\t\t}`);
  lines.push(`\t\tif res.StatusCode < 200 || res.StatusCode >= 300 {`);
  lines.push(`\t\t\tif (res.StatusCode == 429 || res.StatusCode >= 500) && attempt < 2 {`);
  lines.push(`\t\t\t\ttime.Sleep(retryDelay(res, attempt))`);
  lines.push(`\t\t\t\tcontinue`);
  lines.push(`\t\t\t}`);
  lines.push(`\t\t\treturn nil, fmt.Errorf("%s %s -> %d", method, path, res.StatusCode)`);
  lines.push(`\t\t}`);
  lines.push(`\t\tif len(data) == 0 {`);
  lines.push(`\t\t\treturn nil, nil`);
  lines.push(`\t\t}`);
  lines.push(`\t\tvar out any`);
  lines.push(`\t\tif err := json.Unmarshal(data, &out); err != nil {`);
  lines.push(`\t\t\treturn nil, err`);
  lines.push(`\t\t}`);
  lines.push(`\t\treturn out, nil`);
  lines.push(`\t}`);
  lines.push(`\tif lastErr != nil {`);
  lines.push(`\t\treturn nil, lastErr`);
  lines.push(`\t}`);
  lines.push(`\treturn nil, fmt.Errorf("%s %s -> network", method, path)`);
  lines.push(`}`);
  lines.push(``);
  lines.push(`func expandPath(pathTpl string, args map[string]any) (string, map[string]any) {`);
  lines.push(`\trest := map[string]any{}`);
  lines.push(`\tfor k, v := range args {`);
  lines.push(`\t\trest[k] = v`);
  lines.push(`\t}`);
  lines.push(`\tout := pathTpl`);
  lines.push(`\tfor {`);
  lines.push(`\t\tstart := strings.Index(out, "{")`);
  lines.push(`\t\tif start < 0 {`);
  lines.push(`\t\t\tbreak`);
  lines.push(`\t\t}`);
  lines.push(`\t\tend := strings.Index(out[start:], "}")`);
  lines.push(`\t\tif end < 0 {`);
  lines.push(`\t\t\tbreak`);
  lines.push(`\t\t}`);
  lines.push(`\t\tend += start`);
  lines.push(`\t\tkey := out[start+1 : end]`);
  lines.push(`\t\tval, ok := rest[key]`);
  lines.push(`\t\tdelete(rest, key)`);
  lines.push(`\t\trepl := ""`);
  lines.push(`\t\tif ok && val != nil {`);
  lines.push(`\t\t\trepl = url.PathEscape(fmt.Sprint(val))`);
  lines.push(`\t\t}`);
  lines.push(`\t\tout = out[:start] + repl + out[end+1:]`);
  lines.push(`\t}`);
  lines.push(`\treturn out, rest`);
  lines.push(`}`);
  lines.push(``);
  if (pageable.length) emitGoPageRuntime(lines);

  for (const op of ops) {
    const fn = toGoExported(op.operationId);
    const summary = String(op.summary || `${op.method} ${op.path}`).replace(/\*\//g, "* /");
    lines.push(`// ${fn} ${summary} (operationId: ${op.operationId})`);
    lines.push(`func (c *Client) ${fn}(args map[string]any) (any, error) {`);
    lines.push(`\tif args == nil {`);
    lines.push(`\t\targs = map[string]any{}`);
    lines.push(`\t}`);
    lines.push(`\tpath, rest := expandPath(${JSON.stringify(op.path)}, args)`);
    if (op.method === "GET" || op.method === "DELETE") {
      lines.push(`\tq := url.Values{}`);
      lines.push(`\tfor k, v := range rest {`);
      lines.push(`\t\tif v == nil {`);
      lines.push(`\t\t\tcontinue`);
      lines.push(`\t\t}`);
      lines.push(`\t\tq.Set(k, fmt.Sprint(v))`);
      lines.push(`\t}`);
      lines.push(`\tif enc := q.Encode(); enc != "" {`);
      lines.push(`\t\tpath = path + "?" + enc`);
      lines.push(`\t}`);
      lines.push(`\treturn c.request(${JSON.stringify(op.method)}, path, nil` + goAuthSuffix(op, auth.any) + `)`);
    } else {
      lines.push(`\treturn c.request(${JSON.stringify(op.method)}, path, rest` + goAuthSuffix(op, auth.any) + `)`);
    }
    lines.push(`}`);
    lines.push(``);
    const hit = pageable.find((p) => p.op === op);
    if (hit) emitGoIterate(lines, op, hit.info, hit.iter);
  }

  return lines.join("\n");
}

/** Java identifier from operationId (camelCase; keywords suffixed). */
const JAVA_KEYWORDS = new Set([
  "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char", "class",
  "const", "continue", "default", "do", "double", "else", "enum", "extends", "final",
  "finally", "float", "for", "goto", "if", "implements", "import", "instanceof", "int",
  "interface", "long", "native", "new", "package", "private", "protected", "public",
  "return", "short", "static", "strictfp", "super", "switch", "synchronized", "this",
  "throw", "throws", "transient", "try", "void", "volatile", "while", "true", "false",
  "null", "var", "yield", "record", "sealed", "permits",
]);

export function toJavaIdent(name) {
  let cleaned = String(name || "op").replace(/[^a-zA-Z0-9_]/g, "_");
  if (!cleaned) return "op";
  if (/^[0-9]/.test(cleaned)) cleaned = "op" + cleaned;
  if (JAVA_KEYWORDS.has(cleaned)) return cleaned + "_";
  return cleaned;
}


function emitJavaPageRuntime(lines) {
  lines.push(`    // Page helper: GET page/pageSize/offset/limit/cursor/starting_after. Follow next/next_cursor/nextPageToken or increment page. Cap 1000. Not a Stainless pager.`);
  lines.push(`    private static void jsonSkipWs(char[] cs, int[] pos) {`);
  lines.push(`        while (pos[0] < cs.length) {`);
  lines.push(`            char c = cs[pos[0]];`);
  lines.push(`            if (c == ' ' || c == '\\n' || c == '\\r' || c == '\\t') {`);
  lines.push(`                pos[0] = pos[0] + 1;`);
  lines.push(`            } else {`);
  lines.push(`                break;`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private static Object jsonParse(String s) {`);
  lines.push(`        if (s == null) {`);
  lines.push(`            return null;`);
  lines.push(`        }`);
  lines.push(`        char[] cs = s.toCharArray();`);
  lines.push(`        int[] pos = new int[] { 0 };`);
  lines.push(`        Object v = jsonParseValue(cs, pos);`);
  lines.push(`        jsonSkipWs(cs, pos);`);
  lines.push(`        return v;`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private static Object jsonParseValue(char[] cs, int[] pos) {`);
  lines.push(`        jsonSkipWs(cs, pos);`);
  lines.push(`        if (pos[0] >= cs.length) {`);
  lines.push(`            throw new RuntimeException("json eof");`);
  lines.push(`        }`);
  lines.push(`        char c = cs[pos[0]];`);
  lines.push(`        if (c == '{') {`);
  lines.push(`            return jsonParseObject(cs, pos);`);
  lines.push(`        }`);
  lines.push(`        if (c == '[') {`);
  lines.push(`            return jsonParseArray(cs, pos);`);
  lines.push(`        }`);
  lines.push(`        if (c == '"') {`);
  lines.push(`            return jsonParseString(cs, pos);`);
  lines.push(`        }`);
  lines.push(`        if (c == 't' || c == 'f' || c == 'n') {`);
  lines.push(`            return jsonParseLiteral(cs, pos);`);
  lines.push(`        }`);
  lines.push(`        if (c == '-' || (c >= '0' && c <= '9')) {`);
  lines.push(`            return jsonParseNumber(cs, pos);`);
  lines.push(`        }`);
  lines.push(`        throw new RuntimeException("json value");`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private static Object jsonParseObject(char[] cs, int[] pos) {`);
  lines.push(`        pos[0] = pos[0] + 1;`);
  lines.push(`        Map<String, Object> m = new HashMap<String, Object>();`);
  lines.push(`        jsonSkipWs(cs, pos);`);
  lines.push(`        if (pos[0] < cs.length && cs[pos[0]] == '}') {`);
  lines.push(`            pos[0] = pos[0] + 1;`);
  lines.push(`            return m;`);
  lines.push(`        }`);
  lines.push(`        while (true) {`);
  lines.push(`            jsonSkipWs(cs, pos);`);
  lines.push(`            String key = jsonParseString(cs, pos);`);
  lines.push(`            jsonSkipWs(cs, pos);`);
  lines.push(`            if (pos[0] >= cs.length || cs[pos[0]] != ':') {`);
  lines.push(`                throw new RuntimeException("json colon");`);
  lines.push(`            }`);
  lines.push(`            pos[0] = pos[0] + 1;`);
  lines.push(`            m.put(key, jsonParseValue(cs, pos));`);
  lines.push(`            jsonSkipWs(cs, pos);`);
  lines.push(`            if (pos[0] >= cs.length) {`);
  lines.push(`                throw new RuntimeException("json object");`);
  lines.push(`            }`);
  lines.push(`            char c = cs[pos[0]];`);
  lines.push(`            pos[0] = pos[0] + 1;`);
  lines.push(`            if (c == '}') {`);
  lines.push(`                return m;`);
  lines.push(`            }`);
  lines.push(`            if (c != ',') {`);
  lines.push(`                throw new RuntimeException("json object");`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private static Object jsonParseArray(char[] cs, int[] pos) {`);
  lines.push(`        pos[0] = pos[0] + 1;`);
  lines.push(`        List<Object> a = new ArrayList<Object>();`);
  lines.push(`        jsonSkipWs(cs, pos);`);
  lines.push(`        if (pos[0] < cs.length && cs[pos[0]] == ']') {`);
  lines.push(`            pos[0] = pos[0] + 1;`);
  lines.push(`            return a;`);
  lines.push(`        }`);
  lines.push(`        while (true) {`);
  lines.push(`            a.add(jsonParseValue(cs, pos));`);
  lines.push(`            jsonSkipWs(cs, pos);`);
  lines.push(`            if (pos[0] >= cs.length) {`);
  lines.push(`                throw new RuntimeException("json array");`);
  lines.push(`            }`);
  lines.push(`            char c = cs[pos[0]];`);
  lines.push(`            pos[0] = pos[0] + 1;`);
  lines.push(`            if (c == ']') {`);
  lines.push(`                return a;`);
  lines.push(`            }`);
  lines.push(`            if (c != ',') {`);
  lines.push(`                throw new RuntimeException("json array");`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private static String jsonParseString(char[] cs, int[] pos) {`);
  lines.push(`        if (pos[0] >= cs.length || cs[pos[0]] != '"') {`);
  lines.push(`            throw new RuntimeException("json string");`);
  lines.push(`        }`);
  lines.push(`        pos[0] = pos[0] + 1;`);
  lines.push(`        StringBuilder sb = new StringBuilder();`);
  lines.push(`        while (pos[0] < cs.length) {`);
  lines.push(`            char c = cs[pos[0]];`);
  lines.push(`            pos[0] = pos[0] + 1;`);
  lines.push(`            if (c == '"') {`);
  lines.push(`                return sb.toString();`);
  lines.push(`            }`);
  lines.push(`            if (c == '\\\\') {`);
  lines.push(`                if (pos[0] >= cs.length) {`);
  lines.push(`                    throw new RuntimeException("json string");`);
  lines.push(`                }`);
  lines.push(`                char e = cs[pos[0]];`);
  lines.push(`                pos[0] = pos[0] + 1;`);
  lines.push(`                if (e == '"' || e == '\\\\' || e == '/') {`);
  lines.push(`                    sb.append(e);`);
  lines.push(`                } else if (e == 'b') {`);
  lines.push(`                    sb.append('\\b');`);
  lines.push(`                } else if (e == 'f') {`);
  lines.push(`                    sb.append('\\f');`);
  lines.push(`                } else if (e == 'n') {`);
  lines.push(`                    sb.append('\\n');`);
  lines.push(`                } else if (e == 'r') {`);
  lines.push(`                    sb.append('\\r');`);
  lines.push(`                } else if (e == 't') {`);
  lines.push(`                    sb.append('\\t');`);
  lines.push(`                } else if (e == 'u' && pos[0] + 4 <= cs.length) {`);
  lines.push(`                    String hex = new String(cs, pos[0], 4);`);
  lines.push(`                    pos[0] = pos[0] + 4;`);
  lines.push(`                    sb.append((char) Integer.parseInt(hex, 16));`);
  lines.push(`                } else {`);
  lines.push(`                    sb.append(e);`);
  lines.push(`                }`);
  lines.push(`            } else {`);
  lines.push(`                sb.append(c);`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        throw new RuntimeException("json string");`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private static Object jsonParseLiteral(char[] cs, int[] pos) {`);
  lines.push(`        if (pos[0] + 4 <= cs.length && cs[pos[0]] == 't' && cs[pos[0] + 1] == 'r' && cs[pos[0] + 2] == 'u' && cs[pos[0] + 3] == 'e') {`);
  lines.push(`            pos[0] = pos[0] + 4;`);
  lines.push(`            return Boolean.TRUE;`);
  lines.push(`        }`);
  lines.push(`        if (pos[0] + 5 <= cs.length && cs[pos[0]] == 'f' && cs[pos[0] + 1] == 'a' && cs[pos[0] + 2] == 'l' && cs[pos[0] + 3] == 's' && cs[pos[0] + 4] == 'e') {`);
  lines.push(`            pos[0] = pos[0] + 5;`);
  lines.push(`            return Boolean.FALSE;`);
  lines.push(`        }`);
  lines.push(`        if (pos[0] + 4 <= cs.length && cs[pos[0]] == 'n' && cs[pos[0] + 1] == 'u' && cs[pos[0] + 2] == 'l' && cs[pos[0] + 3] == 'l') {`);
  lines.push(`            pos[0] = pos[0] + 4;`);
  lines.push(`            return null;`);
  lines.push(`        }`);
  lines.push(`        throw new RuntimeException("json literal");`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private static Object jsonParseNumber(char[] cs, int[] pos) {`);
  lines.push(`        int start = pos[0];`);
  lines.push(`        if (cs[pos[0]] == '-') {`);
  lines.push(`            pos[0] = pos[0] + 1;`);
  lines.push(`        }`);
  lines.push(`        while (pos[0] < cs.length && cs[pos[0]] >= '0' && cs[pos[0]] <= '9') {`);
  lines.push(`            pos[0] = pos[0] + 1;`);
  lines.push(`        }`);
  lines.push(`        boolean frac = false;`);
  lines.push(`        if (pos[0] < cs.length && cs[pos[0]] == '.') {`);
  lines.push(`            frac = true;`);
  lines.push(`            pos[0] = pos[0] + 1;`);
  lines.push(`            while (pos[0] < cs.length && cs[pos[0]] >= '0' && cs[pos[0]] <= '9') {`);
  lines.push(`                pos[0] = pos[0] + 1;`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        if (pos[0] < cs.length && (cs[pos[0]] == 'e' || cs[pos[0]] == 'E')) {`);
  lines.push(`            frac = true;`);
  lines.push(`            pos[0] = pos[0] + 1;`);
  lines.push(`            if (pos[0] < cs.length && (cs[pos[0]] == '+' || cs[pos[0]] == '-')) {`);
  lines.push(`                pos[0] = pos[0] + 1;`);
  lines.push(`            }`);
  lines.push(`            while (pos[0] < cs.length && cs[pos[0]] >= '0' && cs[pos[0]] <= '9') {`);
  lines.push(`                pos[0] = pos[0] + 1;`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        String raw = new String(cs, start, pos[0] - start);`);
  lines.push(`        if (!frac) {`);
  lines.push(`            try {`);
  lines.push(`                return Long.valueOf(raw);`);
  lines.push(`            } catch (NumberFormatException ignored) {`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        return Double.valueOf(raw);`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private static Object asPageData(Object data) {`);
  lines.push(`        if (data instanceof String) {`);
  lines.push(`            String s = ((String) data).trim();`);
  lines.push(`            if (s.length() > 0 && (s.charAt(0) == '{' || s.charAt(0) == '[')) {`);
  lines.push(`                try {`);
  lines.push(`                    return jsonParse(s);`);
  lines.push(`                } catch (Exception ignored) {`);
  lines.push(`                    return data;`);
  lines.push(`                }`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        return data;`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private static int pageLen(Object data) {`);
  lines.push(`        if (data instanceof List) {`);
  lines.push(`            return ((List<?>) data).size();`);
  lines.push(`        }`);
  lines.push(`        if (data instanceof Map) {`);
  lines.push(`            Map<?, ?> m = (Map<?, ?>) data;`);
  lines.push(`            String[] keys = new String[] { "data", "items", "results" };`);
  lines.push(`            for (int i = 0; i < keys.length; i++) {`);
  lines.push(`                Object a = m.get(keys[i]);`);
  lines.push(`                if (a instanceof List) {`);
  lines.push(`                    return ((List<?>) a).size();`);
  lines.push(`                }`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        return -1;`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private static String nextCursorOf(Object data) {`);
  lines.push(`        if (!(data instanceof Map)) {`);
  lines.push(`            return null;`);
  lines.push(`        }`);
  lines.push(`        Map<?, ?> m = (Map<?, ?>) data;`);
  lines.push(`        String[] keys = new String[] { "next", "next_cursor", "nextPageToken" };`);
  lines.push(`        for (int i = 0; i < keys.length; i++) {`);
  lines.push(`            Object v = m.get(keys[i]);`);
  lines.push(`            if (v instanceof String && ((String) v).length() > 0) {`);
  lines.push(`                return (String) v;`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        return null;`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private static int asInt(Object v, int fallback) {`);
  lines.push(`        if (v == null) {`);
  lines.push(`            return fallback;`);
  lines.push(`        }`);
  lines.push(`        if (v instanceof Number) {`);
  lines.push(`            return ((Number) v).intValue();`);
  lines.push(`        }`);
  lines.push(`        try {`);
  lines.push(`            return Integer.parseInt(String.valueOf(v).trim());`);
  lines.push(`        } catch (Exception ignored) {`);
  lines.push(`            return fallback;`);
  lines.push(`        }`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private static Map<String, Object> cloneArgs(Map<String, Object> args) {`);
  lines.push(`        Map<String, Object> out = new HashMap<String, Object>();`);
  lines.push(`        if (args != null) {`);
  lines.push(`            out.putAll(args);`);
  lines.push(`        }`);
  lines.push(`        return out;`);
  lines.push(`    }`);
  lines.push(``);
}

function emitJavaIterate(lines, op, info, iterName) {
  const fn = toJavaIdent(op.operationId);
  const javaIter = toJavaIdent(iterName);
  const mode = info.mode;
  const sizeKey = info.sizeParam;
  const cursorKey = info.cursorParam || "cursor";
  const pageKey = info.pageParam || "page";
  const offsetKey = info.offsetParam || "offset";
  const summary = `walks pages for ${op.operationId} (page/cursor; cap 1000). Not a full pager.`.replace(/\*\//g, "* /");
  lines.push(`    /** ${javaIter} ${summary} */`);
  lines.push(`    public List<Object> ${javaIter}(Map<String, Object> args) throws Exception {`);
  lines.push(`        Map<String, Object> state = cloneArgs(args);`);
  if (mode === "offset") {
    lines.push(`        int offset = asInt(state.get(${JSON.stringify(offsetKey)}), 0);`);
  } else if (mode === "page") {
    lines.push(`        int page = asInt(state.get(${JSON.stringify(pageKey)}), 1);`);
    lines.push(`        if (page < 1) {`);
    lines.push(`            page = 1;`);
    lines.push(`        }`);
  }
  lines.push(`        List<Object> pages = new ArrayList<Object>();`);
  lines.push(`        for (int n = 0; n < 1000; n++) {`);
  lines.push(`            Map<String, Object> call = cloneArgs(state);`);
  if (mode === "offset") {
    lines.push(`            call.put(${JSON.stringify(offsetKey)}, Integer.valueOf(offset));`);
  } else if (mode === "page") {
    lines.push(`            call.put(${JSON.stringify(pageKey)}, Integer.valueOf(page));`);
  }
  lines.push(`            Object data = asPageData(this.${fn}(call));`);
  lines.push(`            pages.add(data);`);
  lines.push(`            int ln = pageLen(data);`);
  if (sizeKey) {
    lines.push(`            int size = asInt(call.get(${JSON.stringify(sizeKey)}), 0);`);
    lines.push(`            if (data == null || ln == 0 || (size > 0 && ln >= 0 && ln < size)) {`);
    lines.push(`                break;`);
    lines.push(`            }`);
  } else {
    lines.push(`            if (data == null || ln == 0) {`);
    lines.push(`                break;`);
    lines.push(`            }`);
  }
  lines.push(`            String cur = nextCursorOf(data);`);
  lines.push(`            Object prev = state.get(${JSON.stringify(cursorKey)});`);
  lines.push(`            if (cur != null && (prev == null || !cur.equals(String.valueOf(prev)))) {`);
  lines.push(`                state.put(${JSON.stringify(cursorKey)}, cur);`);
  lines.push(`                continue;`);
  lines.push(`            }`);
  if (mode === "cursor") {
    lines.push(`            break;`);
  } else if (mode === "offset") {
    lines.push(`            if (ln < 0) {`);
    lines.push(`                break;`);
    lines.push(`            }`);
    if (sizeKey) {
      lines.push(`            int step = size > 0 ? size : ln;`);
    } else {
      lines.push(`            int step = ln;`);
    }
    lines.push(`            if (step <= 0) {`);
    lines.push(`                break;`);
    lines.push(`            }`);
    lines.push(`            offset += step;`);
  } else {
    lines.push(`            if (ln < 0) {`);
    lines.push(`                break;`);
    lines.push(`            }`);
    lines.push(`            page += 1;`);
  }
  lines.push(`        }`);
  lines.push(`        return pages;`);
  lines.push(`    }`);
  lines.push(``);
}

/** Minimal Java HTTP client stub (stdlib java.net.HttpURLConnection). package client. */
export function generateJavaClient(ops, title = "GeneratedClient", opts = {}) {
  const pkg = pkgFromOpts(opts);
  const safeTitle = String(title || "GeneratedClient").replace(/\*\//g, "* /");
  const pageable = pageableOps(ops);
  const auth = authFlags(ops);
  const lines = [];
  lines.push(`// Auto-generated by sdk-mcp-gen — do not edit by hand`);
  lines.push(`// API: ${safeTitle}`);
  lines.push(`package ${pkg.ident};`);
  lines.push(``);
  lines.push(`import java.io.ByteArrayOutputStream;`);
  lines.push(`import java.io.InputStream;`);
  lines.push(`import java.io.OutputStream;`);
  lines.push(`import java.net.HttpURLConnection;`);
  lines.push(`import java.net.URL;`);
  lines.push(`import java.net.URLEncoder;`);
  lines.push(`import java.nio.charset.StandardCharsets;`);
  lines.push(`import java.util.HashMap;`);
  if (pageable.length) {
    lines.push(`import java.util.ArrayList;`);
    lines.push(`import java.util.List;`);
  }
  lines.push(`import java.util.Map;`);
  lines.push(`import java.util.StringJoiner;`);
  lines.push(`import java.util.UUID;`);
  lines.push(``);
  lines.push(`/** Minimal HTTP client stub generated from OpenAPI (java.net.HttpURLConnection). */`);
  lines.push(`// Retry transient HTTP failures (429 / 5xx / network throw): max 2 retries, ~100ms exponential backoff, honor Retry-After <30s.`);
  lines.push(`// Per-attempt request timeout (default 10s): connect + read timeout. Override via Client.timeoutMs or env SDK_TIMEOUT_MS / SDK_TIMEOUT_SEC.`);
  lines.push(`// Default User-Agent ${JSON.stringify(defaultUserAgent(opts))} unless the caller already set User-Agent.`);
  lines.push(`// X-Request-Id: new id per HTTP attempt (retries get a new id). Pin via Client.requestId or env SDK_REQUEST_ID (tests).`);
  lines.push(`// Idempotency-Key: on POST/PUT/PATCH/DELETE when unset. New key per logical call (retries reuse). Pin via Client.idempotencyKey or env SDK_IDEMPOTENCY_KEY (tests).`);
  if (auth.any) {
    lines.push(`// Auth from OpenAPI securitySchemes (http bearer, apiKey header/query). oauth2 / openIdConnect skipped (no fake tokens).`);
    lines.push(`// Set bearerToken / apiKey or env SDK_BEARER_TOKEN / SDK_API_KEY. Attached per OpenAPI operation security on every attempt. Ops without security omit credentials. Values never logged.`);
  }
  lines.push(`public class Client {`);
  lines.push(`    private final String baseUrl;`);
  lines.push(`    public int timeoutMs;`);
  lines.push(`    public String userAgent;`);
  lines.push(`    public String requestId;`);
  lines.push(`    public String idempotencyKey;`);
  if (auth.hasBearer) {
    lines.push(`    public String bearerToken;`);
  }
  if (auth.headerKeys.length || auth.queryKeys.length) {
    lines.push(`    public String apiKey;`);
  }
  lines.push(``);
  lines.push(`    public Client() {`);
  lines.push(`        this("");`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    public Client(String baseUrl) {`);
  lines.push(`        if (baseUrl == null) {`);
  lines.push(`            this.baseUrl = "";`);
  lines.push(`        } else {`);
  lines.push(`            int n = baseUrl.length();`);
  lines.push(`            while (n > 0 && baseUrl.charAt(n - 1) == '/') {`);
  lines.push(`                n--;`);
  lines.push(`            }`);
  lines.push(`            this.baseUrl = baseUrl.substring(0, n);`);
  lines.push(`        }`);
  lines.push(`        this.timeoutMs = envTimeoutMs();`);
  lines.push(`        this.userAgent = ${JSON.stringify(defaultUserAgent(opts))};`);
  lines.push(`        this.requestId = envRequestId();`);
  lines.push(`        this.idempotencyKey = envIdempotencyKey();`);
  if (auth.hasBearer) {
    lines.push(`        this.bearerToken = envAuth("SDK_BEARER_TOKEN");`);
  }
  if (auth.headerKeys.length || auth.queryKeys.length) {
    lines.push(`        this.apiKey = envAuth("SDK_API_KEY");`);
  }
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private static int envTimeoutMs() {`);
  lines.push(`        String rawMs = System.getenv("SDK_TIMEOUT_MS");`);
  lines.push(`        if (rawMs != null && rawMs.trim().length() > 0) {`);
  lines.push(`            try {`);
  lines.push(`                int ms = Integer.parseInt(rawMs.trim());`);
  lines.push(`                if (ms > 0) {`);
  lines.push(`                    return ms;`);
  lines.push(`                }`);
  lines.push(`            } catch (NumberFormatException ignored) {`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        String rawSec = System.getenv("SDK_TIMEOUT_SEC");`);
  lines.push(`        if (rawSec != null && rawSec.trim().length() > 0) {`);
  lines.push(`            try {`);
  lines.push(`                int sec = Integer.parseInt(rawSec.trim());`);
  lines.push(`                if (sec > 0) {`);
  lines.push(`                    return sec * 1000;`);
  lines.push(`                }`);
  lines.push(`            } catch (NumberFormatException ignored) {`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        return 10000;`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private static String envRequestId() {`);
  lines.push(`        String v = System.getenv("SDK_REQUEST_ID");`);
  lines.push(`        if (v == null) {`);
  lines.push(`            return "";`);
  lines.push(`        }`);
  lines.push(`        return v.trim();`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private static String envIdempotencyKey() {`);
  lines.push(`        String v = System.getenv("SDK_IDEMPOTENCY_KEY");`);
  lines.push(`        if (v == null) {`);
  lines.push(`            return "";`);
  lines.push(`        }`);
  lines.push(`        return v.trim();`);
  lines.push(`    }`);
  lines.push(``);
  if (auth.any) {
    lines.push(`    private static String envAuth(String name) {`);
    lines.push(`        String v = System.getenv(name);`);
    lines.push(`        if (v == null) {`);
    lines.push(`            return "";`);
    lines.push(`        }`);
    lines.push(`        String t = v.trim();`);
    lines.push(`        return t;`);
    lines.push(`    }`);
    lines.push(``);
  }
  lines.push(`    private static long retryDelayMs(HttpURLConnection conn, int attempt) {`);
  lines.push(`        String raw = conn == null ? null : conn.getHeaderField("Retry-After");`);
  lines.push(`        if (raw != null) {`);
  lines.push(`            raw = raw.trim();`);
  lines.push(`            try {`);
  lines.push(`                double sec = Double.parseDouble(raw);`);
  lines.push(`                if (sec >= 0 && sec < 30) {`);
  lines.push(`                    return (long) (sec * 1000.0);`);
  lines.push(`                }`);
  lines.push(`            } catch (NumberFormatException ignored) {`);
  lines.push(`                try {`);
  lines.push(`                    java.time.ZonedDateTime when = java.time.ZonedDateTime.parse(raw, java.time.format.DateTimeFormatter.RFC_1123_DATE_TIME);`);
  lines.push(`                    long delta = when.toInstant().toEpochMilli() - System.currentTimeMillis();`);
  lines.push(`                    if (delta >= 0 && delta < 30000) {`);
  lines.push(`                        return delta;`);
  lines.push(`                    }`);
  lines.push(`                } catch (Exception ignored2) {`);
  lines.push(`                }`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        return 100L * (1L << attempt);`);
  lines.push(`    }`);
  lines.push(``);
  const reqSig = auth.any
    ? `    private Object doRequest(String method, String path, Object body, boolean authBearer, String[] authHeaders, String[] authQuery) throws Exception {`
    : `    private Object doRequest(String method, String path, Object body) throws Exception {`;
  lines.push(reqSig);
  lines.push(`        int timeout = this.timeoutMs > 0 ? this.timeoutMs : envTimeoutMs();`);
  lines.push(`        String opIdem = "";`);
  lines.push(`        String mth = method == null ? "" : method.toUpperCase();`);
  lines.push(`        if (mth.equals("POST") || mth.equals("PUT") || mth.equals("PATCH") || mth.equals("DELETE")) {`);
  lines.push(`            opIdem = this.idempotencyKey != null && this.idempotencyKey.trim().length() > 0 ? this.idempotencyKey.trim() : envIdempotencyKey();`);
  lines.push(`            if (opIdem == null || opIdem.length() == 0) {`);
  lines.push(`                opIdem = UUID.randomUUID().toString();`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        Exception last = null;`);
  lines.push(`        for (int attempt = 0; attempt < 3; attempt++) {`);
  lines.push(`            HttpURLConnection conn = null;`);
  lines.push(`            try {`);
  lines.push(`                String reqPath = path;`);
  if (auth.queryKeys.length) {
    lines.push(`                if (authQuery != null && this.apiKey != null && this.apiKey.trim().length() > 0) {`);
    lines.push(`                    String key = this.apiKey.trim();`);
    lines.push(`                    for (int qi = 0; qi < authQuery.length; qi++) {`);
    lines.push(`                        String q = authQuery[qi];`);
    lines.push(`                        if (q == null || q.length() == 0) {`);
    lines.push(`                            continue;`);
    lines.push(`                        }`);
    lines.push(`                        reqPath = reqPath + (reqPath.indexOf('?') >= 0 ? "&" : "?") + urlEncode(q) + "=" + urlEncode(key);`);
    lines.push(`                    }`);
    lines.push(`                }`);
  }
  lines.push(`                URL url = new URL(this.baseUrl + reqPath);`);
  lines.push(`                conn = (HttpURLConnection) url.openConnection();`);
  lines.push(`                conn.setRequestMethod(method);`);
  lines.push(`                conn.setConnectTimeout(timeout);`);
  lines.push(`                conn.setReadTimeout(timeout);`);
  lines.push(`                conn.setUseCaches(false);`);
  lines.push(`                if (conn.getRequestProperty("User-Agent") == null) {`);
  lines.push(`                    String ua = this.userAgent != null && this.userAgent.trim().length() > 0 ? this.userAgent.trim() : ${JSON.stringify(defaultUserAgent(opts))};`);
  lines.push(`                    conn.setRequestProperty("User-Agent", ua);`);
  lines.push(`                }`);
  lines.push(`                if (conn.getRequestProperty("X-Request-Id") == null) {`);
  lines.push(`                    String rid = this.requestId != null && this.requestId.trim().length() > 0 ? this.requestId.trim() : envRequestId();`);
  lines.push(`                    if (rid == null || rid.length() == 0) {`);
  lines.push(`                        rid = UUID.randomUUID().toString();`);
  lines.push(`                    }`);
  lines.push(`                    conn.setRequestProperty("X-Request-Id", rid);`);
  lines.push(`                }`);
  lines.push(`                if (opIdem != null && opIdem.length() > 0 && conn.getRequestProperty("Idempotency-Key") == null) {`);
  lines.push(`                    conn.setRequestProperty("Idempotency-Key", opIdem);`);
  lines.push(`                }`);
  if (auth.hasBearer) {
    lines.push(`                if (authBearer && this.bearerToken != null && this.bearerToken.trim().length() > 0) {`);
    lines.push(`                    conn.setRequestProperty("Authorization", "Bearer " + this.bearerToken.trim());`);
    lines.push(`                }`);
  }
  if (auth.headerKeys.length) {
    lines.push(`                if (authHeaders != null && this.apiKey != null && this.apiKey.trim().length() > 0) {`);
    lines.push(`                    String key = this.apiKey.trim();`);
    lines.push(`                    for (int hi = 0; hi < authHeaders.length; hi++) {`);
    lines.push(`                        if (authHeaders[hi] != null && authHeaders[hi].length() > 0) {`);
    lines.push(`                            conn.setRequestProperty(authHeaders[hi], key);`);
    lines.push(`                        }`);
    lines.push(`                    }`);
    lines.push(`                }`);
  }
  lines.push(`                if (body != null) {`);
  lines.push(`                    byte[] bytes = jsonStringify(body).getBytes(StandardCharsets.UTF_8);`);
  lines.push(`                    conn.setDoOutput(true);`);
  lines.push(`                    conn.setRequestProperty("Content-Type", "application/json");`);
  lines.push(`                    OutputStream os = conn.getOutputStream();`);
  lines.push(`                    try {`);
  lines.push(`                        os.write(bytes);`);
  lines.push(`                    } finally {`);
  lines.push(`                        os.close();`);
  lines.push(`                    }`);
  lines.push(`                }`);
  lines.push(`                int code = conn.getResponseCode();`);
  lines.push(`                InputStream in = code >= 400 ? conn.getErrorStream() : conn.getInputStream();`);
  lines.push(`                String text = readAll(in);`);
  lines.push(`                if (code >= 200 && code < 300) {`);
  lines.push(`                    if (text == null || text.length() == 0) {`);
  lines.push(`                        return null;`);
  lines.push(`                    }`);
  lines.push(`                    return text;`);
  lines.push(`                }`);
  lines.push(`                if ((code == 429 || code >= 500) && attempt < 2) {`);
  lines.push(`                    Thread.sleep(retryDelayMs(conn, attempt));`);
  lines.push(`                    continue;`);
  lines.push(`                }`);
  lines.push(`                throw new RuntimeException(method + " " + path + " -> " + code);`);
  lines.push(`            } catch (RuntimeException e) {`);
  lines.push(`                throw e;`);
  lines.push(`            } catch (Exception e) {`);
  lines.push(`                last = e;`);
  lines.push(`                if (attempt >= 2) {`);
  lines.push(`                    throw e;`);
  lines.push(`                }`);
  lines.push(`                Thread.sleep(100L * (1L << attempt));`);
  lines.push(`            } finally {`);
  lines.push(`                if (conn != null) {`);
  lines.push(`                    conn.disconnect();`);
  lines.push(`                }`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        if (last != null) {`);
  lines.push(`            throw last;`);
  lines.push(`        }`);
  lines.push(`        throw new RuntimeException(method + " " + path + " -> network");`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private static String readAll(InputStream in) throws Exception {`);
  lines.push(`        if (in == null) {`);
  lines.push(`            return "";`);
  lines.push(`        }`);
  lines.push(`        ByteArrayOutputStream buf = new ByteArrayOutputStream();`);
  lines.push(`        byte[] tmp = new byte[4096];`);
  lines.push(`        int n;`);
  lines.push(`        while ((n = in.read(tmp)) >= 0) {`);
  lines.push(`            buf.write(tmp, 0, n);`);
  lines.push(`        }`);
  lines.push(`        in.close();`);
  lines.push(`        return new String(buf.toByteArray(), StandardCharsets.UTF_8);`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private static String urlEncode(String s) {`);
  lines.push(`        try {`);
  lines.push(`            return URLEncoder.encode(s, "UTF-8").replace("+", "%20");`);
  lines.push(`        } catch (java.io.UnsupportedEncodingException e) {`);
  lines.push(`            return s;`);
  lines.push(`        }`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private static String expandPath(String pathTpl, Map<String, Object> rest) {`);
  lines.push(`        String out = pathTpl;`);
  lines.push(`        while (true) {`);
  lines.push(`            int start = out.indexOf('{');`);
  lines.push(`            if (start < 0) {`);
  lines.push(`                break;`);
  lines.push(`            }`);
  lines.push(`            int end = out.indexOf('}', start);`);
  lines.push(`            if (end < 0) {`);
  lines.push(`                break;`);
  lines.push(`            }`);
  lines.push(`            String key = out.substring(start + 1, end);`);
  lines.push(`            Object val = rest.remove(key);`);
  lines.push(`            String repl = "";`);
  lines.push(`            if (val != null) {`);
  lines.push(`                repl = urlEncode(String.valueOf(val));`);
  lines.push(`            }`);
  lines.push(`            out = out.substring(0, start) + repl + out.substring(end + 1);`);
  lines.push(`        }`);
  lines.push(`        return out;`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private static String queryString(Map<String, Object> rest) {`);
  lines.push(`        StringJoiner j = new StringJoiner("&");`);
  lines.push(`        for (Map.Entry<String, Object> e : rest.entrySet()) {`);
  lines.push(`            if (e.getValue() == null) {`);
  lines.push(`                continue;`);
  lines.push(`            }`);
  lines.push(`            j.add(urlEncode(e.getKey()) + "=" + urlEncode(String.valueOf(e.getValue())));`);
  lines.push(`        }`);
  lines.push(`        String enc = j.toString();`);
  lines.push(`        return enc.isEmpty() ? "" : "?" + enc;`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private static String jsonStringify(Object v) {`);
  lines.push(`        if (v == null) {`);
  lines.push(`            return "null";`);
  lines.push(`        }`);
  lines.push(`        if (v instanceof Number || v instanceof Boolean) {`);
  lines.push(`            return String.valueOf(v);`);
  lines.push(`        }`);
  lines.push(`        if (v instanceof Map) {`);
  lines.push(`            StringJoiner j = new StringJoiner(",", "{", "}");`);
  lines.push(`            Map<?, ?> m = (Map<?, ?>) v;`);
  lines.push(`            for (Map.Entry<?, ?> e : m.entrySet()) {`);
  lines.push(`                j.add(jsonStringify(String.valueOf(e.getKey())) + ":" + jsonStringify(e.getValue()));`);
  lines.push(`            }`);
  lines.push(`            return j.toString();`);
  lines.push(`        }`);
  lines.push(`        if (v instanceof Iterable) {`);
  lines.push(`            StringJoiner j = new StringJoiner(",", "[", "]");`);
  lines.push(`            for (Object x : (Iterable<?>) v) {`);
  lines.push(`                j.add(jsonStringify(x));`);
  lines.push(`            }`);
  lines.push(`            return j.toString();`);
  lines.push(`        }`);
  lines.push(`        String s = String.valueOf(v);`);
  lines.push(`        StringBuilder sb = new StringBuilder("\\"");`);
  lines.push(`        for (int i = 0; i < s.length(); i++) {`);
  lines.push(`            char c = s.charAt(i);`);
  lines.push(`            if (c == '"') {`);
  lines.push(`                sb.append("\\\\\\"");`);
  lines.push(`            } else if (c == '\\\\') {`);
  lines.push(`                sb.append("\\\\\\\\");`);
  lines.push(`            } else if (c == '\\n') {`);
  lines.push(`                sb.append("\\\\n");`);
  lines.push(`            } else if (c == '\\r') {`);
  lines.push(`                sb.append("\\\\r");`);
  lines.push(`            } else if (c == '\\t') {`);
  lines.push(`                sb.append("\\\\t");`);
  lines.push(`            } else if (c < 0x20) {`);
  lines.push(`                sb.append(String.format("\\\\u%04x", (int) c));`);
  lines.push(`            } else {`);
  lines.push(`                sb.append(c);`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        sb.append("\\"");`);
  lines.push(`        return sb.toString();`);
  lines.push(`    }`);
  lines.push(``);

  if (pageable.length) emitJavaPageRuntime(lines);
  for (const op of ops) {
    const fn = toJavaIdent(op.operationId);
    const authSuf = jvmAuthArgs(op, auth.any);
    const summary = String(op.summary || `${op.method} ${op.path}`).replace(/\*\//g, "* /");
    lines.push(`    /** ${fn} ${summary} (operationId: ${op.operationId}) */`);
    lines.push(`    public Object ${fn}(Map<String, Object> args) throws Exception {`);
    lines.push(`        Map<String, Object> rest = new HashMap<String, Object>();`);
    lines.push(`        if (args != null) {`);
    lines.push(`            rest.putAll(args);`);
    lines.push(`        }`);
    lines.push(`        String path = expandPath(${JSON.stringify(op.path)}, rest);`);
    if (op.method === "GET" || op.method === "DELETE") {
      lines.push(`        return doRequest(${JSON.stringify(op.method)}, path + queryString(rest), null` + authSuf + `);`);
    } else {
      lines.push(`        return doRequest(${JSON.stringify(op.method)}, path, rest` + authSuf + `);`);
    }
    lines.push(`    }`);
    lines.push(``);
    const hit = pageable.find((p) => p.op === op);
    if (hit) emitJavaIterate(lines, op, hit.info, hit.iter);
  }

  lines.push(`}`);
  lines.push(``);
  return lines.join("\n");
}


/** Rust identifier from operationId (snake_case; keywords / `new` suffixed). */
const RUST_KEYWORDS = new Set([
  "as", "break", "const", "continue", "crate", "else", "enum", "extern", "false", "fn",
  "for", "if", "impl", "in", "let", "loop", "match", "mod", "move", "mut", "pub", "ref",
  "return", "self", "Self", "static", "struct", "super", "trait", "true", "type", "unsafe",
  "use", "where", "while", "async", "await", "dyn", "abstract", "become", "box", "do",
  "final", "macro", "override", "priv", "typeof", "unsized", "virtual", "yield", "try",
  "gen", "raw",
]);

export function toRustIdent(name) {
  let cleaned = String(name || "op").replace(/[^a-zA-Z0-9_]/g, "_");
  if (!cleaned) return "op";
  let snake = cleaned
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1_$2")
    .toLowerCase();
  snake = snake.replace(/_+/g, "_").replace(/^_+|_+$/g, "");
  if (!snake) return "op";
  if (/^[0-9]/.test(snake)) snake = "op_" + snake;
  if (RUST_KEYWORDS.has(snake) || snake === "new") return snake + "_";
  return snake;
}

/**
 * Minimal Rust HTTP client stub (stdlib only: std::net::TcpStream HTTP/1.1, http:// — no TLS).
 * Compiles with `rustc --crate-type lib client.rs`.
 */
export function generateRustClient(ops, title = "GeneratedClient", opts = {}) {
  const pkg = pkgFromOpts(opts);
  const safeTitle = String(title || "GeneratedClient").replace(/\*\//g, "* /");
  const auth = authFlags(ops);
  const lines = [];
  lines.push(`// Auto-generated by sdk-mcp-gen — do not edit by hand`);
  lines.push(`// API: ${safeTitle}`);
  lines.push(`// crate: ${pkg.ident}`);
  lines.push(`use std::collections::HashMap;`);
  lines.push(`use std::env;`);
  lines.push(`use std::io::{Read, Write};`);
  lines.push(`use std::net::{TcpStream, ToSocketAddrs};`);
  lines.push(`use std::thread;`);
  lines.push(`use std::time::Duration;`);
  lines.push(``);
  lines.push(`/// Minimal HTTP/1.1 client stub generated from OpenAPI (std::net::TcpStream; http:// only, no TLS).`);
  lines.push(`// Retry transient HTTP failures (429 / 5xx / network): max 2 retries, ~100ms exponential backoff, honor Retry-After <30s.`);
  lines.push(`// Per-attempt request timeout (default 10s): connect + read/write. Override via Client.timeout_ms or env SDK_TIMEOUT_MS / SDK_TIMEOUT_SEC.`);
  lines.push(`// Default User-Agent ${JSON.stringify(defaultUserAgent(opts))} unless already present. X-Request-Id new per attempt; pin via request_id or env SDK_REQUEST_ID.`);
  lines.push(`// Idempotency-Key on POST/PUT/PATCH/DELETE when unset; new per logical call (retries reuse). Pin via idempotency_key or env SDK_IDEMPOTENCY_KEY.`);
  if (auth.any) {
    lines.push(`// Auth from OpenAPI securitySchemes (http bearer, apiKey header/query). oauth2 / openIdConnect skipped (no fake tokens).`);
    lines.push(`// Set bearer_token / api_key or env SDK_BEARER_TOKEN / SDK_API_KEY. Attached per OpenAPI operation security on every attempt. Ops without security omit credentials. Values never logged.`);
  }
  lines.push(`pub struct Client {`);
  lines.push(`    pub base_url: String,`);
  lines.push(`    pub timeout_ms: u64,`);
  lines.push(`    pub user_agent: String,`);
  lines.push(`    pub request_id: String,`);
  lines.push(`    pub idempotency_key: String,`);
  if (auth.hasBearer) {
    lines.push(`    pub bearer_token: String,`);
  }
  if (auth.headerKeys.length || auth.queryKeys.length) {
    lines.push(`    pub api_key: String,`);
  }
  lines.push(`}`);
  lines.push(``);
  lines.push(`impl Client {`);
  lines.push(`    pub fn new(base: impl Into<String>) -> Self {`);
  lines.push(`        let mut base_url = base.into();`);
  lines.push(`        while base_url.ends_with('/') {`);
  lines.push(`            base_url.pop();`);
  lines.push(`        }`);
  lines.push(`        Self {`);
  lines.push(`            base_url,`);
  lines.push(`            timeout_ms: env_timeout_ms(),`);
  lines.push(`            user_agent: ${JSON.stringify(defaultUserAgent(opts))}.to_string(),`);
  lines.push(`            request_id: env_request_id(),`);
  lines.push(`            idempotency_key: env_idempotency_key(),`);
  if (auth.hasBearer) {
    lines.push(`            bearer_token: env_auth("SDK_BEARER_TOKEN"),`);
  }
  if (auth.headerKeys.length || auth.queryKeys.length) {
    lines.push(`            api_key: env_auth("SDK_API_KEY"),`);
  }
  lines.push(`        }`);
  lines.push(`    }`);
  lines.push(``);
  const reqSig = auth.any
    ? `    fn request(&self, method: &str, rel_path: &str, body: Option<&str>, auth_bearer: bool, auth_headers: &[&str], auth_query: &[&str]) -> Result<String, String> {`
    : `    fn request(&self, method: &str, rel_path: &str, body: Option<&str>) -> Result<String, String> {`;
  lines.push(reqSig);
  lines.push(`        let op_idem = {`);
  lines.push(`            let m = method.to_ascii_uppercase();`);
  lines.push(`            if m == "POST" || m == "PUT" || m == "PATCH" || m == "DELETE" {`);
  lines.push(`                let t = self.idempotency_key.trim();`);
  lines.push(`                if !t.is_empty() { t.to_string() } else { new_request_id() }`);
  lines.push(`            } else {`);
  lines.push(`                String::new()`);
  lines.push(`            }`);
  lines.push(`        };`);
  lines.push(`        let mut last = String::from("network");`);
  lines.push(`        for attempt in 0..3u32 {`);
  const onceCall = auth.any
    ? `            match self.request_once(method, rel_path, body, auth_bearer, auth_headers, auth_query, &op_idem) {`
    : `            match self.request_once(method, rel_path, body, &op_idem) {`;
  lines.push(onceCall);
  lines.push(`                Ok((code, retry_after, body_text)) => {`);
  lines.push(`                    if (200..300).contains(&code) {`);
  lines.push(`                        return Ok(body_text);`);
  lines.push(`                    }`);
  lines.push(`                    if (code == 429 || code >= 500) && attempt < 2 {`);
  lines.push(`                        sleep_ms(retry_delay_ms(retry_after.as_deref(), attempt));`);
  lines.push(`                        continue;`);
  lines.push(`                    }`);
  lines.push(`                    return Err(format!("{} {} -> {}", method, rel_path, code));`);
  lines.push(`                }`);
  lines.push(`                Err(e) => {`);
  lines.push(`                    last = e;`);
  lines.push(`                    if attempt >= 2 {`);
  lines.push(`                        return Err(last);`);
  lines.push(`                    }`);
  lines.push(`                    sleep_ms(100u64 * (1u64 << attempt));`);
  lines.push(`                }`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        Err(last)`);
  lines.push(`    }`);
  lines.push(``);
  const bearerP = auth.hasBearer ? "auth_bearer: bool" : "_auth_bearer: bool";
  const headersP = auth.headerKeys.length ? "auth_headers: &[&str]" : "_auth_headers: &[&str]";
  const queryP = auth.queryKeys.length ? "auth_query: &[&str]" : "_auth_query: &[&str]";
  const onceSig = auth.any
    ? `    fn request_once(&self, method: &str, rel_path: &str, body: Option<&str>, ${bearerP}, ${headersP}, ${queryP}, op_idem: &str) -> Result<(u16, Option<String>, String), String> {`
    : `    fn request_once(&self, method: &str, rel_path: &str, body: Option<&str>, op_idem: &str) -> Result<(u16, Option<String>, String), String> {`;
  lines.push(onceSig);
  lines.push(`        let timeout = Duration::from_millis(if self.timeout_ms > 0 {`);
  lines.push(`            self.timeout_ms`);
  lines.push(`        } else {`);
  lines.push(`            env_timeout_ms()`);
  lines.push(`        });`);
  lines.push(`        let (host, port, base_path) = parse_http_base(&self.base_url)?;`);
  lines.push(`        let mut path = if rel_path.starts_with('/') {`);
  lines.push(`            format!("{}{}", base_path, rel_path)`);
  lines.push(`        } else {`);
  lines.push(`            format!("{}/{}", base_path, rel_path)`);
  lines.push(`        };`);
  lines.push(`        if path.is_empty() {`);
  lines.push(`            path = "/".to_string();`);
  lines.push(`        }`);
  if (auth.queryKeys.length) {
    lines.push(`        let key = self.api_key.trim();`);
    lines.push(`        if !key.is_empty() {`);
    lines.push(`            for q in auth_query {`);
    lines.push(`                if q.is_empty() {`);
    lines.push(`                    continue;`);
    lines.push(`                }`);
    lines.push(`                let sep = if path.contains('?') { "&" } else { "?" };`);
    lines.push(`                path.push_str(sep);`);
    lines.push(`                path.push_str(&url_encode(q));`);
    lines.push(`                path.push('=');`);
    lines.push(`                path.push_str(&url_encode(key));`);
    lines.push(`            }`);
    lines.push(`        }`);
  }
  lines.push(`        let addr = if host.contains(':') {`);
  lines.push(`            format!("[{}]:{}", host, port)`);
  lines.push(`        } else {`);
  lines.push(`            format!("{}:{}", host, port)`);
  lines.push(`        };`);
  lines.push(`        let host_header = if host.contains(':') {`);
  lines.push(`            if port == 80 {`);
  lines.push(`                format!("[{}]", host)`);
  lines.push(`            } else {`);
  lines.push(`                format!("[{}]:{}", host, port)`);
  lines.push(`            }`);
  lines.push(`        } else if port == 80 {`);
  lines.push(`            host.clone()`);
  lines.push(`        } else {`);
  lines.push(`            format!("{}:{}", host, port)`);
  lines.push(`        };`);
  lines.push(`        let mut addrs = addr.to_socket_addrs().map_err(|e| e.to_string())?;`);
  lines.push(`        let sock = addrs.next().ok_or_else(|| format!("no address for {}", addr))?;`);
  lines.push(`        let mut stream = TcpStream::connect_timeout(&sock, timeout).map_err(|e| e.to_string())?;`);
  lines.push(`        stream.set_read_timeout(Some(timeout)).map_err(|e| e.to_string())?;`);
  lines.push(`        stream.set_write_timeout(Some(timeout)).map_err(|e| e.to_string())?;`);
  lines.push(`        let mut req = format!(`);
  lines.push(`            "{} {} HTTP/1.1\\r\\nHost: {}\\r\\nConnection: close\\r\\n",`);
  lines.push(`            method, path, host_header`);
  lines.push(`        );`);
  if (auth.hasBearer) {
    lines.push(`        if auth_bearer {`);
    lines.push(`            let tok = self.bearer_token.trim();`);
    lines.push(`            if !tok.is_empty() {`);
    lines.push(`                req.push_str("Authorization: Bearer ");`);
    lines.push(`                req.push_str(tok);`);
    lines.push(`                req.push_str("\\r\\n");`);
    lines.push(`            }`);
    lines.push(`        }`);
  }
  if (auth.headerKeys.length) {
    lines.push(`        let key = self.api_key.trim();`);
    lines.push(`        if !key.is_empty() {`);
    lines.push(`            for h in auth_headers {`);
    lines.push(`                if h.is_empty() {`);
    lines.push(`                    continue;`);
    lines.push(`                }`);
    lines.push(`                req.push_str(h);`);
    lines.push(`                req.push_str(": ");`);
    lines.push(`                req.push_str(key);`);
    lines.push(`                req.push_str("\\r\\n");`);
    lines.push(`            }`);
    lines.push(`        }`);
  }
  lines.push(`        let ua = {`);
  lines.push(`            let t = self.user_agent.trim();`);
  lines.push(`            if t.is_empty() { ${JSON.stringify(defaultUserAgent(opts))}.to_string() } else { t.to_string() }`);
  lines.push(`        };`);
  lines.push(`        if !req.to_ascii_lowercase().contains("user-agent:") {`);
  lines.push(`            req.push_str("User-Agent: ");`);
  lines.push(`            req.push_str(&ua);`);
  lines.push(`            req.push_str("\\r\\n");`);
  lines.push(`        }`);
  lines.push(`        let rid = {`);
  lines.push(`            let t = self.request_id.trim();`);
  lines.push(`            if !t.is_empty() { t.to_string() } else { new_request_id() }`);
  lines.push(`        };`);
  lines.push(`        if !req.to_ascii_lowercase().contains("x-request-id:") {`);
  lines.push(`            req.push_str("X-Request-Id: ");`);
  lines.push(`            req.push_str(&rid);`);
  lines.push(`            req.push_str("\\r\\n");`);
  lines.push(`        }`);
  lines.push(`        if !op_idem.is_empty() && !req.to_ascii_lowercase().contains("idempotency-key:") {`);
  lines.push(`            req.push_str("Idempotency-Key: ");`);
  lines.push(`            req.push_str(op_idem);`);
  lines.push(`            req.push_str("\\r\\n");`);
  lines.push(`        }`);
  lines.push(`        if let Some(b) = body {`);
  lines.push(`            req.push_str("Content-Type: application/json\\r\\n");`);
  lines.push(`            req.push_str(&format!("Content-Length: {}\\r\\n", b.len()));`);
  lines.push(`        }`);
  lines.push(`        req.push_str("\\r\\n");`);
  lines.push(`        if let Some(b) = body {`);
  lines.push(`            req.push_str(b);`);
  lines.push(`        }`);
  lines.push(`        stream.write_all(req.as_bytes()).map_err(|e| e.to_string())?;`);
  lines.push(`        let mut buf = Vec::new();`);
  lines.push(`        stream.read_to_end(&mut buf).map_err(|e| e.to_string())?;`);
  lines.push(`        let raw = String::from_utf8_lossy(&buf);`);
  lines.push(`        let (head, body_text) = match raw.find("\\r\\n\\r\\n") {`);
  lines.push(`            Some(i) => (&raw[..i], raw[i + 4..].to_string()),`);
  lines.push(`            None => return Err("invalid HTTP response".into()),`);
  lines.push(`        };`);
  lines.push(`        let status_line = head.lines().next().unwrap_or("");`);
  lines.push(`        let code: u16 = status_line`);
  lines.push(`            .split_whitespace()`);
  lines.push(`            .nth(1)`);
  lines.push(`            .unwrap_or("0")`);
  lines.push(`            .parse()`);
  lines.push(`            .unwrap_or(0);`);
  lines.push(`        let mut retry_after: Option<String> = None;`);
  lines.push(`        for line in head.lines().skip(1) {`);
  lines.push(`            let lower = line.to_ascii_lowercase();`);
  lines.push(`            if lower.starts_with("retry-after:") {`);
  lines.push(`                retry_after = Some(line[12..].trim().to_string());`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        Ok((code, retry_after, body_text))`);
  lines.push(`    }`);
  lines.push(``);

  for (const op of ops) {
    const fn = toRustIdent(op.operationId);
    const authSuf = rustAuthArgs(op, auth.any);
    const summary = String(op.summary || `${op.method} ${op.path}`)
      .replace(/\*\//g, "* /")
      .replace(/\r?\n/g, " ");
    lines.push(`    /// ${fn} ${summary} (operationId: ${op.operationId})`);
    lines.push(`    pub fn ${fn}(&self, args: HashMap<String, String>) -> Result<String, String> {`);
    lines.push(`        let mut rest = args;`);
    lines.push(`        let path = expand_path(${JSON.stringify(op.path)}, &mut rest);`);
    if (op.method === "GET" || op.method === "DELETE") {
      lines.push(`        self.request(${JSON.stringify(op.method)}, &(path + &query_string(&rest)), None` + authSuf + `)`);
    } else {
      lines.push(`        let body = json_object(&rest);`);
      lines.push(`        self.request(${JSON.stringify(op.method)}, &path, Some(&body)` + authSuf + `)`);
    }
    lines.push(`    }`);
    lines.push(``);
  }

  lines.push(`}`);
  lines.push(``);
  lines.push(`fn env_timeout_ms() -> u64 {`);
  lines.push(`    if let Ok(raw) = env::var("SDK_TIMEOUT_MS") {`);
  lines.push(`        let t = raw.trim();`);
  lines.push(`        if !t.is_empty() {`);
  lines.push(`            if let Ok(ms) = t.parse::<u64>() {`);
  lines.push(`                if ms > 0 {`);
  lines.push(`                    return ms;`);
  lines.push(`                }`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`    }`);
  lines.push(`    if let Ok(raw) = env::var("SDK_TIMEOUT_SEC") {`);
  lines.push(`        let t = raw.trim();`);
  lines.push(`        if !t.is_empty() {`);
  lines.push(`            if let Ok(sec) = t.parse::<u64>() {`);
  lines.push(`                if sec > 0 {`);
  lines.push(`                    return sec.saturating_mul(1000);`);
  lines.push(`                }`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`    }`);
  lines.push(`    10000`);
  lines.push(`}`);
  lines.push(``);
  lines.push(`fn env_request_id() -> String {`);
  lines.push(`    match env::var("SDK_REQUEST_ID") {`);
  lines.push(`        Ok(v) => v.trim().to_string(),`);
  lines.push(`        Err(_) => String::new(),`);
  lines.push(`    }`);
  lines.push(`}`);
  lines.push(``);
  lines.push(`fn env_idempotency_key() -> String {`);
  lines.push(`    match env::var("SDK_IDEMPOTENCY_KEY") {`);
  lines.push(`        Ok(v) => v.trim().to_string(),`);
  lines.push(`        Err(_) => String::new(),`);
  lines.push(`    }`);
  lines.push(`}`);
  lines.push(``);
  lines.push(`fn new_request_id() -> String {`);
  lines.push(`    use std::time::{SystemTime, UNIX_EPOCH};`);
  lines.push(`    let t = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0);`);
  lines.push(`    format!("{:x}", t)`);
  lines.push(`}`);
  lines.push(``);
  if (auth.any) {
    lines.push(`fn env_auth(name: &str) -> String {`);
    lines.push(`    match env::var(name) {`);
    lines.push(`        Ok(v) => v.trim().to_string(),`);
    lines.push(`        Err(_) => String::new(),`);
    lines.push(`    }`);
    lines.push(`}`);
    lines.push(``);
  }
  lines.push(`fn sleep_ms(ms: u64) {`);
  lines.push(`    thread::sleep(Duration::from_millis(ms));`);
  lines.push(`}`);
  lines.push(``);
  lines.push(`fn retry_delay_ms(retry_after: Option<&str>, attempt: u32) -> u64 {`);
  lines.push(`    if let Some(raw) = retry_after {`);
  lines.push(`        let t = raw.trim();`);
  lines.push(`        if let Ok(sec) = t.parse::<f64>() {`);
  lines.push(`            if sec >= 0.0 && sec < 30.0 {`);
  lines.push(`                return (sec * 1000.0) as u64;`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`    }`);
  lines.push(`    100u64 * (1u64 << attempt)`);
  lines.push(`}`);
  lines.push(``);
  lines.push(`fn parse_http_base(base: &str) -> Result<(String, u16, String), String> {`);
  lines.push(`    let s = base.trim();`);
  lines.push(`    if s.is_empty() {`);
  lines.push(`        return Err("empty base_url".into());`);
  lines.push(`    }`);
  lines.push(`    if s.starts_with("https://") {`);
  lines.push(`        return Err(`);
  lines.push(`            "https not supported (std::net::TcpStream HTTP/1.1 stub; use http://)".into(),`);
  lines.push(`        );`);
  lines.push(`    }`);
  lines.push(`    let rest = s`);
  lines.push(`        .strip_prefix("http://")`);
  lines.push(`        .ok_or_else(|| format!("unsupported base_url (need http://): {}", s))?;`);
  lines.push(`    let (authority, path) = match rest.find('/') {`);
  lines.push(`        Some(i) => (&rest[..i], rest[i..].trim_end_matches('/').to_string()),`);
  lines.push(`        None => (rest, String::new()),`);
  lines.push(`    };`);
  lines.push(`    if authority.is_empty() {`);
  lines.push(`        return Err("missing host".into());`);
  lines.push(`    }`);
  lines.push(`    let (host, port) = if authority.starts_with('[') {`);
  lines.push(`        match authority.find(']') {`);
  lines.push(`            Some(end) => {`);
  lines.push(`                let host = authority[1..end].to_string();`);
  lines.push(`                let port = if authority[end + 1..].starts_with(':') {`);
  lines.push(`                    authority[end + 2..]`);
  lines.push(`                        .parse::<u16>()`);
  lines.push(`                        .map_err(|e| e.to_string())?`);
  lines.push(`                } else {`);
  lines.push(`                    80`);
  lines.push(`                };`);
  lines.push(`                (host, port)`);
  lines.push(`            }`);
  lines.push(`            None => return Err("invalid IPv6 host".into()),`);
  lines.push(`        }`);
  lines.push(`    } else if let Some(i) = authority.rfind(':') {`);
  lines.push(`        let host = authority[..i].to_string();`);
  lines.push(`        let port = authority[i + 1..]`);
  lines.push(`            .parse::<u16>()`);
  lines.push(`            .map_err(|e| e.to_string())?;`);
  lines.push(`        (host, port)`);
  lines.push(`    } else {`);
  lines.push(`        (authority.to_string(), 80)`);
  lines.push(`    };`);
  lines.push(`    Ok((host, port, path))`);
  lines.push(`}`);
  lines.push(``);
  lines.push(`fn expand_path(path_tpl: &str, rest: &mut HashMap<String, String>) -> String {`);
  lines.push(`    let mut out = path_tpl.to_string();`);
  lines.push(`    loop {`);
  lines.push(`        let start = match out.find('{') {`);
  lines.push(`            Some(i) => i,`);
  lines.push(`            None => break,`);
  lines.push(`        };`);
  lines.push(`        let end = match out[start..].find('}') {`);
  lines.push(`            Some(i) => start + i,`);
  lines.push(`            None => break,`);
  lines.push(`        };`);
  lines.push(`        let key = out[start + 1..end].to_string();`);
  lines.push(`        let repl = match rest.remove(&key) {`);
  lines.push(`            Some(v) => url_encode(&v),`);
  lines.push(`            None => String::new(),`);
  lines.push(`        };`);
  lines.push(`        out = format!("{}{}{}", &out[..start], repl, &out[end + 1..]);`);
  lines.push(`    }`);
  lines.push(`    out`);
  lines.push(`}`);
  lines.push(``);
  lines.push(`fn query_string(rest: &HashMap<String, String>) -> String {`);
  lines.push(`    let mut parts: Vec<String> = Vec::new();`);
  lines.push(`    for (k, v) in rest {`);
  lines.push(`        parts.push(format!("{}={}", url_encode(k), url_encode(v)));`);
  lines.push(`    }`);
  lines.push(`    if parts.is_empty() {`);
  lines.push(`        String::new()`);
  lines.push(`    } else {`);
  lines.push(`        format!("?{}", parts.join("&"))`);
  lines.push(`    }`);
  lines.push(`}`);
  lines.push(``);
  lines.push(`fn url_encode(s: &str) -> String {`);
  lines.push(`    let mut out = String::new();`);
  lines.push(`    for b in s.bytes() {`);
  lines.push(`        match b {`);
  lines.push(`            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {`);
  lines.push(`                out.push(b as char);`);
  lines.push(`            }`);
  lines.push(`            _ => out.push_str(&format!("%{:02X}", b)),`);
  lines.push(`        }`);
  lines.push(`    }`);
  lines.push(`    out`);
  lines.push(`}`);
  lines.push(``);
  lines.push(`fn json_object(map: &HashMap<String, String>) -> String {`);
  lines.push(`    let mut first = true;`);
  lines.push(`    let mut out = String::from("{");`);
  lines.push(`    for (k, v) in map {`);
  lines.push(`        if !first {`);
  lines.push(`            out.push(',');`);
  lines.push(`        }`);
  lines.push(`        first = false;`);
  lines.push(`        out.push_str(&json_str(k));`);
  lines.push(`        out.push(':');`);
  lines.push(`        out.push_str(&json_str(v));`);
  lines.push(`    }`);
  lines.push(`    out.push('}');`);
  lines.push(`    out`);
  lines.push(`}`);
  lines.push(``);
  lines.push(`fn json_str(s: &str) -> String {`);
  lines.push(`    let mut inner = String::new();`);
  lines.push(`    for c in s.chars() {`);
  lines.push(`        let code = c as u32;`);
  lines.push(`        if c == '"' || c == '\\\\' || code < 0x20 {`);
  lines.push(`            inner.push_str(&format!("\\\\u{:04x}", code));`);
  lines.push(`        } else {`);
  lines.push(`            inner.push(c);`);
  lines.push(`        }`);
  lines.push(`    }`);
  lines.push("    format!(\"\\\"{}\\\"\", inner)");
  lines.push(`}`);
  lines.push(``);
  return lines.join("\n");
}

const CSHARP_KEYWORDS = new Set([
  "abstract", "as", "base", "bool", "break", "byte", "case", "catch", "char", "checked",
  "class", "const", "continue", "decimal", "default", "delegate", "do", "double", "else",
  "enum", "event", "explicit", "extern", "false", "finally", "fixed", "float", "for",
  "foreach", "goto", "if", "implicit", "in", "int", "interface", "internal", "is", "lock",
  "long", "namespace", "new", "null", "object", "operator", "out", "override", "params",
  "private", "protected", "public", "readonly", "ref", "return", "sbyte", "sealed",
  "sizeof", "stackalloc", "static", "string", "struct", "switch", "this", "throw", "true",
  "try", "typeof", "uint", "ulong", "unchecked", "unsafe", "ushort", "using", "virtual",
  "void", "volatile", "while", "add", "and", "alias", "ascending", "args", "async", "await",
  "by", "descending", "dynamic", "equals", "file", "from", "get", "global", "group", "init",
  "into", "join", "let", "managed", "nameof", "nint", "not", "notnull", "nuint", "on", "or",
  "orderby", "partial", "record", "remove", "required", "scoped", "select", "set",
  "unmanaged", "value", "var", "when", "where", "with", "yield",
]);

export function toCsharpIdent(name) {
  let cleaned = String(name || "Op").replace(/[^a-zA-Z0-9_]/g, "_");
  if (!cleaned) return "Op";
  if (/^[0-9]/.test(cleaned)) cleaned = "Op" + cleaned;
  const parts = cleaned.split("_").filter(Boolean);
  let ident = parts.map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join("");
  if (!ident) return "Op";
  if (CSHARP_KEYWORDS.has(ident) || ident === "Client") return ident + "_";
  return ident;
}


function emitCsharpPageRuntime(lines) {
  lines.push(`        // Page helper: GET page/pageSize/offset/limit/cursor/starting_after. Follow next/next_cursor/nextPageToken or increment page. Cap 1000. Not a Stainless pager.`);
  lines.push(`        private static void JsonSkipWs(char[] cs, int[] pos)`);
  lines.push(`        {`);
  lines.push(`            while (pos[0] < cs.Length)`);
  lines.push(`            {`);
  lines.push(`                char c = cs[pos[0]];`);
  lines.push(`                if (c == ' ' || c == '\\n' || c == '\\r' || c == '\\t')`);
  lines.push(`                {`);
  lines.push(`                    pos[0] = pos[0] + 1;`);
  lines.push(`                }`);
  lines.push(`                else`);
  lines.push(`                {`);
  lines.push(`                    break;`);
  lines.push(`                }`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(``);
  lines.push(`        private static object JsonParse(string s)`);
  lines.push(`        {`);
  lines.push(`            if (s == null)`);
  lines.push(`            {`);
  lines.push(`                return null;`);
  lines.push(`            }`);
  lines.push(`            char[] cs = s.ToCharArray();`);
  lines.push(`            int[] pos = new int[] { 0 };`);
  lines.push(`            object v = JsonParseValue(cs, pos);`);
  lines.push(`            JsonSkipWs(cs, pos);`);
  lines.push(`            return v;`);
  lines.push(`        }`);
  lines.push(``);
  lines.push(`        private static object JsonParseValue(char[] cs, int[] pos)`);
  lines.push(`        {`);
  lines.push(`            JsonSkipWs(cs, pos);`);
  lines.push(`            if (pos[0] >= cs.Length)`);
  lines.push(`            {`);
  lines.push(`                throw new Exception("json eof");`);
  lines.push(`            }`);
  lines.push(`            char c = cs[pos[0]];`);
  lines.push(`            if (c == '{')`);
  lines.push(`            {`);
  lines.push(`                return JsonParseObject(cs, pos);`);
  lines.push(`            }`);
  lines.push(`            if (c == '[')`);
  lines.push(`            {`);
  lines.push(`                return JsonParseArray(cs, pos);`);
  lines.push(`            }`);
  lines.push(`            if (c == '"')`);
  lines.push(`            {`);
  lines.push(`                return JsonParseString(cs, pos);`);
  lines.push(`            }`);
  lines.push(`            if (c == 't' || c == 'f' || c == 'n')`);
  lines.push(`            {`);
  lines.push(`                return JsonParseLiteral(cs, pos);`);
  lines.push(`            }`);
  lines.push(`            if (c == '-' || (c >= '0' && c <= '9'))`);
  lines.push(`            {`);
  lines.push(`                return JsonParseNumber(cs, pos);`);
  lines.push(`            }`);
  lines.push(`            throw new Exception("json value");`);
  lines.push(`        }`);
  lines.push(``);
  lines.push(`        private static object JsonParseObject(char[] cs, int[] pos)`);
  lines.push(`        {`);
  lines.push(`            pos[0] = pos[0] + 1;`);
  lines.push(`            Dictionary<string, object> m = new Dictionary<string, object>();`);
  lines.push(`            JsonSkipWs(cs, pos);`);
  lines.push(`            if (pos[0] < cs.Length && cs[pos[0]] == '}')`);
  lines.push(`            {`);
  lines.push(`                pos[0] = pos[0] + 1;`);
  lines.push(`                return m;`);
  lines.push(`            }`);
  lines.push(`            while (true)`);
  lines.push(`            {`);
  lines.push(`                JsonSkipWs(cs, pos);`);
  lines.push(`                string key = JsonParseString(cs, pos);`);
  lines.push(`                JsonSkipWs(cs, pos);`);
  lines.push(`                if (pos[0] >= cs.Length || cs[pos[0]] != ':')`);
  lines.push(`                {`);
  lines.push(`                    throw new Exception("json colon");`);
  lines.push(`                }`);
  lines.push(`                pos[0] = pos[0] + 1;`);
  lines.push(`                m[key] = JsonParseValue(cs, pos);`);
  lines.push(`                JsonSkipWs(cs, pos);`);
  lines.push(`                if (pos[0] >= cs.Length)`);
  lines.push(`                {`);
  lines.push(`                    throw new Exception("json object");`);
  lines.push(`                }`);
  lines.push(`                char c = cs[pos[0]];`);
  lines.push(`                pos[0] = pos[0] + 1;`);
  lines.push(`                if (c == '}')`);
  lines.push(`                {`);
  lines.push(`                    return m;`);
  lines.push(`                }`);
  lines.push(`                if (c != ',')`);
  lines.push(`                {`);
  lines.push(`                    throw new Exception("json object");`);
  lines.push(`                }`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(``);
  lines.push(`        private static object JsonParseArray(char[] cs, int[] pos)`);
  lines.push(`        {`);
  lines.push(`            pos[0] = pos[0] + 1;`);
  lines.push(`            List<object> a = new List<object>();`);
  lines.push(`            JsonSkipWs(cs, pos);`);
  lines.push(`            if (pos[0] < cs.Length && cs[pos[0]] == ']')`);
  lines.push(`            {`);
  lines.push(`                pos[0] = pos[0] + 1;`);
  lines.push(`                return a;`);
  lines.push(`            }`);
  lines.push(`            while (true)`);
  lines.push(`            {`);
  lines.push(`                a.Add(JsonParseValue(cs, pos));`);
  lines.push(`                JsonSkipWs(cs, pos);`);
  lines.push(`                if (pos[0] >= cs.Length)`);
  lines.push(`                {`);
  lines.push(`                    throw new Exception("json array");`);
  lines.push(`                }`);
  lines.push(`                char c = cs[pos[0]];`);
  lines.push(`                pos[0] = pos[0] + 1;`);
  lines.push(`                if (c == ']')`);
  lines.push(`                {`);
  lines.push(`                    return a;`);
  lines.push(`                }`);
  lines.push(`                if (c != ',')`);
  lines.push(`                {`);
  lines.push(`                    throw new Exception("json array");`);
  lines.push(`                }`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(``);
  lines.push(`        private static string JsonParseString(char[] cs, int[] pos)`);
  lines.push(`        {`);
  lines.push(`            if (pos[0] >= cs.Length || cs[pos[0]] != '"')`);
  lines.push(`            {`);
  lines.push(`                throw new Exception("json string");`);
  lines.push(`            }`);
  lines.push(`            pos[0] = pos[0] + 1;`);
  lines.push(`            StringBuilder sb = new StringBuilder();`);
  lines.push(`            while (pos[0] < cs.Length)`);
  lines.push(`            {`);
  lines.push(`                char c = cs[pos[0]];`);
  lines.push(`                pos[0] = pos[0] + 1;`);
  lines.push(`                if (c == '"')`);
  lines.push(`                {`);
  lines.push(`                    return sb.ToString();`);
  lines.push(`                }`);
  lines.push(`                if (c == '\\\\')`);
  lines.push(`                {`);
  lines.push(`                    if (pos[0] >= cs.Length)`);
  lines.push(`                    {`);
  lines.push(`                        throw new Exception("json string");`);
  lines.push(`                    }`);
  lines.push(`                    char e = cs[pos[0]];`);
  lines.push(`                    pos[0] = pos[0] + 1;`);
  lines.push(`                    if (e == '"' || e == '\\\\' || e == '/')`);
  lines.push(`                    {`);
  lines.push(`                        sb.Append(e);`);
  lines.push(`                    }`);
  lines.push(`                    else if (e == 'b')`);
  lines.push(`                    {`);
  lines.push(`                        sb.Append('\\b');`);
  lines.push(`                    }`);
  lines.push(`                    else if (e == 'f')`);
  lines.push(`                    {`);
  lines.push(`                        sb.Append('\\f');`);
  lines.push(`                    }`);
  lines.push(`                    else if (e == 'n')`);
  lines.push(`                    {`);
  lines.push(`                        sb.Append('\\n');`);
  lines.push(`                    }`);
  lines.push(`                    else if (e == 'r')`);
  lines.push(`                    {`);
  lines.push(`                        sb.Append('\\r');`);
  lines.push(`                    }`);
  lines.push(`                    else if (e == 't')`);
  lines.push(`                    {`);
  lines.push(`                        sb.Append('\\t');`);
  lines.push(`                    }`);
  lines.push(`                    else if (e == 'u' && pos[0] + 4 <= cs.Length)`);
  lines.push(`                    {`);
  lines.push(`                        string hex = new string(cs, pos[0], 4);`);
  lines.push(`                        pos[0] = pos[0] + 4;`);
  lines.push(`                        sb.Append((char) Convert.ToInt32(hex, 16));`);
  lines.push(`                    }`);
  lines.push(`                    else`);
  lines.push(`                    {`);
  lines.push(`                        sb.Append(e);`);
  lines.push(`                    }`);
  lines.push(`                }`);
  lines.push(`                else`);
  lines.push(`                {`);
  lines.push(`                    sb.Append(c);`);
  lines.push(`                }`);
  lines.push(`            }`);
  lines.push(`            throw new Exception("json string");`);
  lines.push(`        }`);
  lines.push(``);
  lines.push(`        private static object JsonParseLiteral(char[] cs, int[] pos)`);
  lines.push(`        {`);
  lines.push(`            if (pos[0] + 4 <= cs.Length && cs[pos[0]] == 't' && cs[pos[0] + 1] == 'r' && cs[pos[0] + 2] == 'u' && cs[pos[0] + 3] == 'e')`);
  lines.push(`            {`);
  lines.push(`                pos[0] = pos[0] + 4;`);
  lines.push(`                return true;`);
  lines.push(`            }`);
  lines.push(`            if (pos[0] + 5 <= cs.Length && cs[pos[0]] == 'f' && cs[pos[0] + 1] == 'a' && cs[pos[0] + 2] == 'l' && cs[pos[0] + 3] == 's' && cs[pos[0] + 4] == 'e')`);
  lines.push(`            {`);
  lines.push(`                pos[0] = pos[0] + 5;`);
  lines.push(`                return false;`);
  lines.push(`            }`);
  lines.push(`            if (pos[0] + 4 <= cs.Length && cs[pos[0]] == 'n' && cs[pos[0] + 1] == 'u' && cs[pos[0] + 2] == 'l' && cs[pos[0] + 3] == 'l')`);
  lines.push(`            {`);
  lines.push(`                pos[0] = pos[0] + 4;`);
  lines.push(`                return null;`);
  lines.push(`            }`);
  lines.push(`            throw new Exception("json literal");`);
  lines.push(`        }`);
  lines.push(``);
  lines.push(`        private static object JsonParseNumber(char[] cs, int[] pos)`);
  lines.push(`        {`);
  lines.push(`            int start = pos[0];`);
  lines.push(`            if (cs[pos[0]] == '-')`);
  lines.push(`            {`);
  lines.push(`                pos[0] = pos[0] + 1;`);
  lines.push(`            }`);
  lines.push(`            while (pos[0] < cs.Length && cs[pos[0]] >= '0' && cs[pos[0]] <= '9')`);
  lines.push(`            {`);
  lines.push(`                pos[0] = pos[0] + 1;`);
  lines.push(`            }`);
  lines.push(`            bool frac = false;`);
  lines.push(`            if (pos[0] < cs.Length && cs[pos[0]] == '.')`);
  lines.push(`            {`);
  lines.push(`                frac = true;`);
  lines.push(`                pos[0] = pos[0] + 1;`);
  lines.push(`                while (pos[0] < cs.Length && cs[pos[0]] >= '0' && cs[pos[0]] <= '9')`);
  lines.push(`                {`);
  lines.push(`                    pos[0] = pos[0] + 1;`);
  lines.push(`                }`);
  lines.push(`            }`);
  lines.push(`            if (pos[0] < cs.Length && (cs[pos[0]] == 'e' || cs[pos[0]] == 'E'))`);
  lines.push(`            {`);
  lines.push(`                frac = true;`);
  lines.push(`                pos[0] = pos[0] + 1;`);
  lines.push(`                if (pos[0] < cs.Length && (cs[pos[0]] == '+' || cs[pos[0]] == '-'))`);
  lines.push(`                {`);
  lines.push(`                    pos[0] = pos[0] + 1;`);
  lines.push(`                }`);
  lines.push(`                while (pos[0] < cs.Length && cs[pos[0]] >= '0' && cs[pos[0]] <= '9')`);
  lines.push(`                {`);
  lines.push(`                    pos[0] = pos[0] + 1;`);
  lines.push(`                }`);
  lines.push(`            }`);
  lines.push(`            string raw = new string(cs, start, pos[0] - start);`);
  lines.push(`            if (!frac)`);
  lines.push(`            {`);
  lines.push(`                long whole;`);
  lines.push(`                if (long.TryParse(raw, out whole))`);
  lines.push(`                {`);
  lines.push(`                    return whole;`);
  lines.push(`                }`);
  lines.push(`            }`);
  lines.push(`            return double.Parse(raw, System.Globalization.CultureInfo.InvariantCulture);`);
  lines.push(`        }`);
  lines.push(``);
  lines.push(`        private static object AsPageData(object data)`);
  lines.push(`        {`);
  lines.push(`            string s = data as string;`);
  lines.push(`            if (s != null)`);
  lines.push(`            {`);
  lines.push(`                s = s.Trim();`);
  lines.push(`                if (s.Length > 0 && (s[0] == '{' || s[0] == '['))`);
  lines.push(`                {`);
  lines.push(`                    try`);
  lines.push(`                    {`);
  lines.push(`                        return JsonParse(s);`);
  lines.push(`                    }`);
  lines.push(`                    catch (Exception)`);
  lines.push(`                    {`);
  lines.push(`                        return data;`);
  lines.push(`                    }`);
  lines.push(`                }`);
  lines.push(`            }`);
  lines.push(`            return data;`);
  lines.push(`        }`);
  lines.push(``);
  lines.push(`        private static int PageLen(object data)`);
  lines.push(`        {`);
  lines.push(`            IList list = data as IList;`);
  lines.push(`            if (list != null && !(data is string))`);
  lines.push(`            {`);
  lines.push(`                return list.Count;`);
  lines.push(`            }`);
  lines.push(`            IDictionary dict = data as IDictionary;`);
  lines.push(`            if (dict != null)`);
  lines.push(`            {`);
  lines.push(`                string[] keys = new string[] { "data", "items", "results" };`);
  lines.push(`                for (int i = 0; i < keys.Length; i++)`);
  lines.push(`                {`);
  lines.push(`                    if (dict.Contains(keys[i]))`);
  lines.push(`                    {`);
  lines.push(`                        IList a = dict[keys[i]] as IList;`);
  lines.push(`                        if (a != null)`);
  lines.push(`                        {`);
  lines.push(`                            return a.Count;`);
  lines.push(`                        }`);
  lines.push(`                    }`);
  lines.push(`                }`);
  lines.push(`            }`);
  lines.push(`            return -1;`);
  lines.push(`        }`);
  lines.push(``);
  lines.push(`        private static string NextCursorOf(object data)`);
  lines.push(`        {`);
  lines.push(`            IDictionary dict = data as IDictionary;`);
  lines.push(`            if (dict == null)`);
  lines.push(`            {`);
  lines.push(`                return null;`);
  lines.push(`            }`);
  lines.push(`            string[] keys = new string[] { "next", "next_cursor", "nextPageToken" };`);
  lines.push(`            for (int i = 0; i < keys.Length; i++)`);
  lines.push(`            {`);
  lines.push(`                if (dict.Contains(keys[i]))`);
  lines.push(`                {`);
  lines.push(`                    string v = dict[keys[i]] as string;`);
  lines.push(`                    if (v != null && v.Length > 0)`);
  lines.push(`                    {`);
  lines.push(`                        return v;`);
  lines.push(`                    }`);
  lines.push(`                }`);
  lines.push(`            }`);
  lines.push(`            return null;`);
  lines.push(`        }`);
  lines.push(``);
  lines.push(`        private static int AsInt(object v, int fallback)`);
  lines.push(`        {`);
  lines.push(`            if (v == null)`);
  lines.push(`            {`);
  lines.push(`                return fallback;`);
  lines.push(`            }`);
  lines.push(`            if (v is byte || v is sbyte || v is short || v is ushort || v is int || v is uint || v is long || v is ulong || v is float || v is double || v is decimal)`);
  lines.push(`            {`);
  lines.push(`                return Convert.ToInt32(v);`);
  lines.push(`            }`);
  lines.push(`            int parsed;`);
  lines.push(`            if (int.TryParse(Convert.ToString(v), out parsed))`);
  lines.push(`            {`);
  lines.push(`                return parsed;`);
  lines.push(`            }`);
  lines.push(`            return fallback;`);
  lines.push(`        }`);
  lines.push(``);
  lines.push(`        private static Dictionary<string, object> CloneArgs(Dictionary<string, object> args)`);
  lines.push(`        {`);
  lines.push(`            return args != null ? new Dictionary<string, object>(args) : new Dictionary<string, object>();`);
  lines.push(`        }`);
  lines.push(``);
}

function emitCsharpIterate(lines, op, info, iterName) {
  const fn = toCsharpIdent(op.operationId);
  const csIter = toCsharpIdent(iterName);
  const mode = info.mode;
  const sizeKey = info.sizeParam;
  const cursorKey = info.cursorParam || "cursor";
  const pageKey = info.pageParam || "page";
  const offsetKey = info.offsetParam || "offset";
  const summary = `walks pages for ${op.operationId} (page/cursor; cap 1000). Not a full pager.`.replace(/\*\//g, "* /").replace(/</g, "").replace(/>/g, "");
  lines.push(`        /// <summary>${csIter} ${summary}</summary>`);
  lines.push(`        public List<object> ${csIter}(Dictionary<string, object> args)`);
  lines.push(`        {`);
  lines.push(`            Dictionary<string, object> state = CloneArgs(args);`);
  if (mode === "offset") {
    lines.push(`            int offset = AsInt(state.ContainsKey(${JSON.stringify(offsetKey)}) ? state[${JSON.stringify(offsetKey)}] : null, 0);`);
  } else if (mode === "page") {
    lines.push(`            int page = AsInt(state.ContainsKey(${JSON.stringify(pageKey)}) ? state[${JSON.stringify(pageKey)}] : null, 1);`);
    lines.push(`            if (page < 1)`);
    lines.push(`            {`);
    lines.push(`                page = 1;`);
    lines.push(`            }`);
  }
  lines.push(`            List<object> pages = new List<object>();`);
  lines.push(`            for (int n = 0; n < 1000; n++)`);
  lines.push(`            {`);
  lines.push(`                Dictionary<string, object> call = CloneArgs(state);`);
  if (mode === "offset") {
    lines.push(`                call[${JSON.stringify(offsetKey)}] = offset;`);
  } else if (mode === "page") {
    lines.push(`                call[${JSON.stringify(pageKey)}] = page;`);
  }
  lines.push(`                object data = AsPageData(this.${fn}(call));`);
  lines.push(`                pages.Add(data);`);
  lines.push(`                int ln = PageLen(data);`);
  if (sizeKey) {
    lines.push(`                int size = AsInt(call.ContainsKey(${JSON.stringify(sizeKey)}) ? call[${JSON.stringify(sizeKey)}] : null, 0);`);
    lines.push(`                if (data == null || ln == 0 || (size > 0 && ln >= 0 && ln < size))`);
    lines.push(`                {`);
    lines.push(`                    break;`);
    lines.push(`                }`);
  } else {
    lines.push(`                if (data == null || ln == 0)`);
    lines.push(`                {`);
    lines.push(`                    break;`);
    lines.push(`                }`);
  }
  lines.push(`                string cur = NextCursorOf(data);`);
  lines.push(`                object prev = state.ContainsKey(${JSON.stringify(cursorKey)}) ? state[${JSON.stringify(cursorKey)}] : null;`);
  lines.push(`                if (cur != null && (prev == null || cur != Convert.ToString(prev)))`);
  lines.push(`                {`);
  lines.push(`                    state[${JSON.stringify(cursorKey)}] = cur;`);
  lines.push(`                    continue;`);
  lines.push(`                }`);
  if (mode === "cursor") {
    lines.push(`                break;`);
  } else if (mode === "offset") {
    lines.push(`                if (ln < 0)`);
    lines.push(`                {`);
    lines.push(`                    break;`);
    lines.push(`                }`);
    if (sizeKey) {
      lines.push(`                int step = size > 0 ? size : ln;`);
    } else {
      lines.push(`                int step = ln;`);
    }
    lines.push(`                if (step <= 0)`);
    lines.push(`                {`);
    lines.push(`                    break;`);
    lines.push(`                }`);
    lines.push(`                offset += step;`);
  } else {
    lines.push(`                if (ln < 0)`);
    lines.push(`                {`);
    lines.push(`                    break;`);
    lines.push(`                }`);
    lines.push(`                page += 1;`);
  }
  lines.push(`            }`);
  lines.push(`            return pages;`);
  lines.push(`        }`);
  lines.push(``);
}

/**
 * Minimal C# HTTP client stub (stdlib System.Net.Http.HttpClient).
 * Classic `namespace Client { public class Client }` for broader compile (csc / older lang versions).
 */
export function generateCsharpClient(ops, title = "GeneratedClient", opts = {}) {
  const pkg = pkgFromOpts(opts);
  const safeTitle = String(title || "GeneratedClient").replace(/\*\//g, "* /");
  const pageable = pageableOps(ops);
  const auth = authFlags(ops);
  const lines = [];
  lines.push(`// Auto-generated by sdk-mcp-gen — do not edit by hand`);
  lines.push(`// API: ${safeTitle}`);
  lines.push(`using System;`);
  lines.push(`using System.Collections;`);
  lines.push(`using System.Collections.Generic;`);
  lines.push(`using System.Net.Http;`);
  lines.push(`using System.Text;`);
  lines.push(`// Retry transient HTTP failures (429 / 5xx / network throw): max 2 retries, ~100ms exponential backoff, honor Retry-After <30s.`);
  lines.push(`// Per-attempt request timeout (default 10s): CancellationToken. Override via Client.TimeoutMs or env SDK_TIMEOUT_MS / SDK_TIMEOUT_SEC.`);
  lines.push(`// Default User-Agent ${JSON.stringify(defaultUserAgent(opts))} unless the caller already set User-Agent.`);
  lines.push(`// X-Request-Id: new id per HTTP attempt. Pin via Client.RequestId or env SDK_REQUEST_ID (tests).`);
  lines.push(`// Idempotency-Key: on POST/PUT/PATCH/DELETE when unset. New key per logical call (retries reuse). Pin via Client.IdempotencyKey or env SDK_IDEMPOTENCY_KEY (tests).`);
  if (auth.any) {
    lines.push(`// Auth from OpenAPI securitySchemes (http bearer, apiKey header/query). oauth2 / openIdConnect skipped (no fake tokens).`);
    lines.push(`// Set BearerToken / APIKey or env SDK_BEARER_TOKEN / SDK_API_KEY. Attached per OpenAPI operation security on every attempt. Ops without security omit credentials. Values never logged.`);
  }
  lines.push(``);
  lines.push(`namespace ${pkg.pascal}`);
  lines.push(`{`);
  lines.push(`    /// <summary>Minimal HTTP client stub generated from OpenAPI (System.Net.Http.HttpClient).</summary>`);
  lines.push(`    public class Client`);
  lines.push(`    {`);
  lines.push(`        private readonly string baseUrl;`);
  lines.push(`        private readonly HttpClient http;`);
  lines.push(`        public int TimeoutMs;`);
  lines.push(`        public string UserAgent;`);
  lines.push(`        public string RequestId;`);
  lines.push(`        public string IdempotencyKey;`);
  if (auth.hasBearer) {
    lines.push(`        public string BearerToken;`);
  }
  if (auth.headerKeys.length || auth.queryKeys.length) {
    lines.push(`        public string APIKey;`);
  }
  lines.push(``);
  lines.push(`        public Client() : this("", null)`);
  lines.push(`        {`);
  lines.push(`        }`);
  lines.push(``);
  lines.push(`        public Client(string baseUrl) : this(baseUrl, null)`);
  lines.push(`        {`);
  lines.push(`        }`);
  lines.push(``);
  lines.push(`        public Client(string baseUrl, HttpClient http)`);
  lines.push(`        {`);
  lines.push(`            if (baseUrl == null)`);
  lines.push(`            {`);
  lines.push(`                this.baseUrl = "";`);
  lines.push(`            }`);
  lines.push(`            else`);
  lines.push(`            {`);
  lines.push(`                this.baseUrl = baseUrl.TrimEnd('/');`);
  lines.push(`            }`);
  lines.push(`            this.http = http ?? new HttpClient();`);
  lines.push(`            this.TimeoutMs = EnvTimeoutMs();`);
  lines.push(`            this.UserAgent = ${JSON.stringify(defaultUserAgent(opts))};`);
  lines.push(`            this.RequestId = EnvRequestId();`);
  lines.push(`            this.IdempotencyKey = EnvIdempotencyKey();`);
  if (auth.hasBearer) {
    lines.push(`            this.BearerToken = EnvAuth("SDK_BEARER_TOKEN");`);
  }
  if (auth.headerKeys.length || auth.queryKeys.length) {
    lines.push(`            this.APIKey = EnvAuth("SDK_API_KEY");`);
  }
  lines.push(`        }`);
  lines.push(``);
  lines.push(`        private static int EnvTimeoutMs()`);
  lines.push(`        {`);
  lines.push(`            string rawMs = Environment.GetEnvironmentVariable("SDK_TIMEOUT_MS");`);
  lines.push(`            int parsedMs;`);
  lines.push(`            if (!string.IsNullOrWhiteSpace(rawMs) && int.TryParse(rawMs.Trim(), out parsedMs) && parsedMs > 0)`);
  lines.push(`            {`);
  lines.push(`                return parsedMs;`);
  lines.push(`            }`);
  lines.push(`            string rawSec = Environment.GetEnvironmentVariable("SDK_TIMEOUT_SEC");`);
  lines.push(`            int parsedSec;`);
  lines.push(`            if (!string.IsNullOrWhiteSpace(rawSec) && int.TryParse(rawSec.Trim(), out parsedSec) && parsedSec > 0)`);
  lines.push(`            {`);
  lines.push(`                return parsedSec * 1000;`);
  lines.push(`            }`);
  lines.push(`            return 10000;`);
  lines.push(`        }`);
  lines.push(``);
  lines.push(`        private static string EnvRequestId()`);
  lines.push(`        {`);
  lines.push(`            string v = Environment.GetEnvironmentVariable("SDK_REQUEST_ID");`);
  lines.push(`            return string.IsNullOrWhiteSpace(v) ? "" : v.Trim();`);
  lines.push(`        }`);
  lines.push(``);
  lines.push(`        private static string EnvIdempotencyKey()`);
  lines.push(`        {`);
  lines.push(`            string v = Environment.GetEnvironmentVariable("SDK_IDEMPOTENCY_KEY");`);
  lines.push(`            return string.IsNullOrWhiteSpace(v) ? "" : v.Trim();`);
  lines.push(`        }`);
  lines.push(``);
  if (auth.any) {
    lines.push(`        private static string EnvAuth(string name)`);
    lines.push(`        {`);
    lines.push(`            string v = Environment.GetEnvironmentVariable(name);`);
    lines.push(`            return string.IsNullOrWhiteSpace(v) ? "" : v.Trim();`);
    lines.push(`        }`);
    lines.push(``);
  }
  lines.push(`        private static int RetryDelayMs(HttpResponseMessage res, int attempt)`);
  lines.push(`        {`);
  lines.push(`            if (res != null && res.Headers.RetryAfter != null)`);
  lines.push(`            {`);
  lines.push(`                if (res.Headers.RetryAfter.Delta != null)`);
  lines.push(`                {`);
  lines.push(`                    double s = res.Headers.RetryAfter.Delta.Value.TotalSeconds;`);
  lines.push(`                    if (s >= 0 && s < 30)`);
  lines.push(`                    {`);
  lines.push(`                        return (int)(s * 1000.0);`);
  lines.push(`                    }`);
  lines.push(`                }`);
  lines.push(`                if (res.Headers.RetryAfter.Date != null)`);
  lines.push(`                {`);
  lines.push(`                    double delta = (res.Headers.RetryAfter.Date.Value - DateTimeOffset.UtcNow).TotalMilliseconds;`);
  lines.push(`                    if (delta >= 0 && delta < 30000)`);
  lines.push(`                    {`);
  lines.push(`                        return (int)delta;`);
  lines.push(`                    }`);
  lines.push(`                }`);
  lines.push(`            }`);
  lines.push(`            return 100 * (1 << attempt);`);
  lines.push(`        }`);
  lines.push(``);
  const reqSig = auth.any
    ? `        private object DoRequest(string method, string path, object body, bool authBearer, string[] authHeaders, string[] authQuery)`
    : `        private object DoRequest(string method, string path, object body)`;
  lines.push(reqSig);
  lines.push(`        {`);
  lines.push(`            int timeout = this.TimeoutMs > 0 ? this.TimeoutMs : EnvTimeoutMs();`);
  lines.push(`            string opIdem = "";`);
  lines.push(`            string mth = method == null ? "" : method.ToUpperInvariant();`);
  lines.push(`            if (mth == "POST" || mth == "PUT" || mth == "PATCH" || mth == "DELETE")`);
  lines.push(`            {`);
  lines.push(`                opIdem = string.IsNullOrWhiteSpace(this.IdempotencyKey) ? EnvIdempotencyKey() : this.IdempotencyKey.Trim();`);
  lines.push(`                if (string.IsNullOrWhiteSpace(opIdem))`);
  lines.push(`                {`);
  lines.push(`                    opIdem = Guid.NewGuid().ToString();`);
  lines.push(`                }`);
  lines.push(`            }`);
  lines.push(`            Exception last = null;`);
  lines.push(`            for (int attempt = 0; attempt < 3; attempt++)`);
  lines.push(`            {`);
  lines.push(`                string reqUrl = this.baseUrl + path;`);
  if (auth.queryKeys.length) {
    lines.push(`                if (authQuery != null && !string.IsNullOrWhiteSpace(this.APIKey))`);
    lines.push(`                {`);
    lines.push(`                    string key = this.APIKey.Trim();`);
    lines.push(`                    for (int qi = 0; qi < authQuery.Length; qi++)`);
    lines.push(`                    {`);
    lines.push(`                        if (string.IsNullOrEmpty(authQuery[qi]))`);
    lines.push(`                        {`);
    lines.push(`                            continue;`);
    lines.push(`                        }`);
    lines.push(`                        reqUrl = reqUrl + (reqUrl.IndexOf('?') >= 0 ? "&" : "?") + Uri.EscapeDataString(authQuery[qi]) + "=" + Uri.EscapeDataString(key);`);
    lines.push(`                    }`);
    lines.push(`                }`);
  }
  lines.push(`                HttpRequestMessage req = new HttpRequestMessage(new HttpMethod(method), reqUrl);`);
  lines.push(`                if (!req.Headers.Contains("User-Agent"))`);
  lines.push(`                {`);
  lines.push(`                    string ua = string.IsNullOrWhiteSpace(this.UserAgent) ? ${JSON.stringify(defaultUserAgent(opts))} : this.UserAgent.Trim();`);
  lines.push(`                    req.Headers.TryAddWithoutValidation("User-Agent", ua);`);
  lines.push(`                }`);
  lines.push(`                if (!req.Headers.Contains("X-Request-Id"))`);
  lines.push(`                {`);
  lines.push(`                    string rid = string.IsNullOrWhiteSpace(this.RequestId) ? EnvRequestId() : this.RequestId.Trim();`);
  lines.push(`                    if (string.IsNullOrWhiteSpace(rid))`);
  lines.push(`                    {`);
  lines.push(`                        rid = Guid.NewGuid().ToString();`);
  lines.push(`                    }`);
  lines.push(`                    req.Headers.TryAddWithoutValidation("X-Request-Id", rid);`);
  lines.push(`                }`);
  lines.push(`                if (!string.IsNullOrWhiteSpace(opIdem) && !req.Headers.Contains("Idempotency-Key"))`);
  lines.push(`                {`);
  lines.push(`                    req.Headers.TryAddWithoutValidation("Idempotency-Key", opIdem);`);
  lines.push(`                }`);
  if (auth.hasBearer) {
    lines.push(`                if (authBearer && !string.IsNullOrWhiteSpace(this.BearerToken))`);
    lines.push(`                {`);
    lines.push(`                    req.Headers.TryAddWithoutValidation("Authorization", "Bearer " + this.BearerToken.Trim());`);
    lines.push(`                }`);
  }
  if (auth.headerKeys.length) {
    lines.push(`                if (authHeaders != null && !string.IsNullOrWhiteSpace(this.APIKey))`);
    lines.push(`                {`);
    lines.push(`                    string key = this.APIKey.Trim();`);
    lines.push(`                    for (int hi = 0; hi < authHeaders.Length; hi++)`);
    lines.push(`                    {`);
    lines.push(`                        if (!string.IsNullOrEmpty(authHeaders[hi]))`);
    lines.push(`                        {`);
    lines.push(`                            req.Headers.TryAddWithoutValidation(authHeaders[hi], key);`);
    lines.push(`                        }`);
    lines.push(`                    }`);
    lines.push(`                }`);
  }
  lines.push(`                if (body != null)`);
  lines.push(`                {`);
  lines.push(`                    byte[] bytes = Encoding.UTF8.GetBytes(JsonStringify(body));`);
  lines.push(`                    req.Content = new ByteArrayContent(bytes);`);
  lines.push(`                    req.Content.Headers.TryAddWithoutValidation("Content-Type", "application/json");`);
  lines.push(`                }`);
  lines.push(`                try`);
  lines.push(`                {`);
  lines.push(`                    using (System.Threading.CancellationTokenSource cts = new System.Threading.CancellationTokenSource())`);
  lines.push(`                    {`);
  lines.push(`                        cts.CancelAfter(timeout);`);
  lines.push(`                        using (HttpResponseMessage res = this.http.SendAsync(req, cts.Token).GetAwaiter().GetResult())`);
  lines.push(`                        {`);
  lines.push(`                            string text = res.Content.ReadAsStringAsync().GetAwaiter().GetResult();`);
  lines.push(`                            int code = (int)res.StatusCode;`);
  lines.push(`                            if (code >= 200 && code < 300)`);
  lines.push(`                            {`);
  lines.push(`                                if (text == null || text.Length == 0)`);
  lines.push(`                                {`);
  lines.push(`                                    return null;`);
  lines.push(`                                }`);
  lines.push(`                                return text;`);
  lines.push(`                            }`);
  lines.push(`                            if ((code == 429 || code >= 500) && attempt < 2)`);
  lines.push(`                            {`);
  lines.push(`                                System.Threading.Thread.Sleep(RetryDelayMs(res, attempt));`);
  lines.push(`                                continue;`);
  lines.push(`                            }`);
  lines.push(`                            throw new Exception(method + " " + path + " -> " + code);`);
  lines.push(`                        }`);
  lines.push(`                    }`);
  lines.push(`                }`);
  lines.push(`                catch (Exception e)`);
  lines.push(`                {`);
  lines.push(`                    if (e.Message != null && e.Message.IndexOf(" -> ") >= 0 && !(e is System.Net.Http.HttpRequestException) && !(e is System.Threading.Tasks.TaskCanceledException) && !(e is OperationCanceledException))`);
  lines.push(`                    {`);
  lines.push(`                        throw;`);
  lines.push(`                    }`);
  lines.push(`                    last = e;`);
  lines.push(`                    if (attempt >= 2)`);
  lines.push(`                    {`);
  lines.push(`                        throw;`);
  lines.push(`                    }`);
  lines.push(`                    System.Threading.Thread.Sleep(100 * (1 << attempt));`);
  lines.push(`                }`);
  lines.push(`            }`);
  lines.push(`            if (last != null)`);
  lines.push(`            {`);
  lines.push(`                throw last;`);
  lines.push(`            }`);
  lines.push(`            throw new Exception(method + " " + path + " -> network");`);
  lines.push(`        }`);
  lines.push(``);
  lines.push(`        private static string UrlEncode(string s)`);
  lines.push(`        {`);
  lines.push(`            if (s == null)`);
  lines.push(`            {`);
  lines.push(`                return "";`);
  lines.push(`            }`);
  lines.push(`            return Uri.EscapeDataString(s);`);
  lines.push(`        }`);
  lines.push(``);
  lines.push(`        private static string ExpandPath(string pathTpl, Dictionary<string, object> rest)`);
  lines.push(`        {`);
  lines.push(`            string outPath = pathTpl;`);
  lines.push(`            while (true)`);
  lines.push(`            {`);
  lines.push(`                int start = outPath.IndexOf('{');`);
  lines.push(`                if (start < 0)`);
  lines.push(`                {`);
  lines.push(`                    break;`);
  lines.push(`                }`);
  lines.push(`                int end = outPath.IndexOf('}', start);`);
  lines.push(`                if (end < 0)`);
  lines.push(`                {`);
  lines.push(`                    break;`);
  lines.push(`                }`);
  lines.push(`                string key = outPath.Substring(start + 1, end - start - 1);`);
  lines.push(`                object val;`);
  lines.push(`                string repl = "";`);
  lines.push(`                if (rest.TryGetValue(key, out val))`);
  lines.push(`                {`);
  lines.push(`                    rest.Remove(key);`);
  lines.push(`                    if (val != null)`);
  lines.push(`                    {`);
  lines.push(`                        repl = UrlEncode(Convert.ToString(val));`);
  lines.push(`                    }`);
  lines.push(`                }`);
  lines.push(`                outPath = outPath.Substring(0, start) + repl + outPath.Substring(end + 1);`);
  lines.push(`            }`);
  lines.push(`            return outPath;`);
  lines.push(`        }`);
  lines.push(``);
  lines.push(`        private static string QueryString(Dictionary<string, object> rest)`);
  lines.push(`        {`);
  lines.push(`            StringBuilder jb = new StringBuilder();`);
  lines.push(`            foreach (KeyValuePair<string, object> e in rest)`);
  lines.push(`            {`);
  lines.push(`                if (e.Value == null)`);
  lines.push(`                {`);
  lines.push(`                    continue;`);
  lines.push(`                }`);
  lines.push(`                if (jb.Length > 0)`);
  lines.push(`                {`);
  lines.push(`                    jb.Append('&');`);
  lines.push(`                }`);
  lines.push(`                jb.Append(UrlEncode(e.Key));`);
  lines.push(`                jb.Append('=');`);
  lines.push(`                jb.Append(UrlEncode(Convert.ToString(e.Value)));`);
  lines.push(`            }`);
  lines.push(`            return jb.Length == 0 ? "" : "?" + jb.ToString();`);
  lines.push(`        }`);
  lines.push(``);
  lines.push(`        private static string JsonStringify(object v)`);
  lines.push(`        {`);
  lines.push(`            if (v == null)`);
  lines.push(`            {`);
  lines.push(`                return "null";`);
  lines.push(`            }`);
  lines.push(`            if (v is bool)`);
  lines.push(`            {`);
  lines.push(`                return ((bool)v) ? "true" : "false";`);
  lines.push(`            }`);
  lines.push(`            if (v is byte || v is sbyte || v is short || v is ushort || v is int || v is uint || v is long || v is ulong || v is float || v is double || v is decimal)`);
  lines.push(`            {`);
  lines.push(`                return Convert.ToString(v, System.Globalization.CultureInfo.InvariantCulture);`);
  lines.push(`            }`);
  lines.push(`            IDictionary dict = v as IDictionary;`);
  lines.push(`            if (dict != null)`);
  lines.push(`            {`);
  lines.push(`                StringBuilder jb = new StringBuilder();`);
  lines.push(`                jb.Append('{');`);
  lines.push(`                bool first = true;`);
  lines.push(`                foreach (DictionaryEntry e in dict)`);
  lines.push(`                {`);
  lines.push(`                    if (!first)`);
  lines.push(`                    {`);
  lines.push(`                        jb.Append(',');`);
  lines.push(`                    }`);
  lines.push(`                    first = false;`);
  lines.push(`                    jb.Append(JsonStringify(Convert.ToString(e.Key)));`);
  lines.push(`                    jb.Append(':');`);
  lines.push(`                    jb.Append(JsonStringify(e.Value));`);
  lines.push(`                }`);
  lines.push(`                jb.Append('}');`);
  lines.push(`                return jb.ToString();`);
  lines.push(`            }`);
  lines.push(`            IEnumerable seq = v as IEnumerable;`);
  lines.push(`            if (seq != null && !(v is string))`);
  lines.push(`            {`);
  lines.push(`                StringBuilder jb = new StringBuilder();`);
  lines.push(`                jb.Append('[');`);
  lines.push(`                bool first = true;`);
  lines.push(`                foreach (object x in seq)`);
  lines.push(`                {`);
  lines.push(`                    if (!first)`);
  lines.push(`                    {`);
  lines.push(`                        jb.Append(',');`);
  lines.push(`                    }`);
  lines.push(`                    first = false;`);
  lines.push(`                    jb.Append(JsonStringify(x));`);
  lines.push(`                }`);
  lines.push(`                jb.Append(']');`);
  lines.push(`                return jb.ToString();`);
  lines.push(`            }`);
  lines.push(`            string s = Convert.ToString(v);`);
  lines.push(`            StringBuilder sb = new StringBuilder();`);
  lines.push(`            sb.Append('"');`);
  lines.push(`            for (int i = 0; i < s.Length; i++)`);
  lines.push(`            {`);
  lines.push(`                char c = s[i];`);
  lines.push(`                if (c == '"')`);
  lines.push(`                {`);
  lines.push(`                    sb.Append("\\\\\\"");`);
  lines.push(`                }`);
  lines.push(`                else if (c == '\\\\')`);
  lines.push(`                {`);
  lines.push(`                    sb.Append("\\\\\\\\");`);
  lines.push(`                }`);
  lines.push(`                else if (c == '\\n')`);
  lines.push(`                {`);
  lines.push(`                    sb.Append("\\\\n");`);
  lines.push(`                }`);
  lines.push(`                else if (c == '\\r')`);
  lines.push(`                {`);
  lines.push(`                    sb.Append("\\\\r");`);
  lines.push(`                }`);
  lines.push(`                else if (c == '\\t')`);
  lines.push(`                {`);
  lines.push(`                    sb.Append("\\\\t");`);
  lines.push(`                }`);
  lines.push(`                else if (c < 0x20)`);
  lines.push(`                {`);
  lines.push(`                    sb.Append("\\\\u");`);
  lines.push(`                    sb.Append(((int)c).ToString("x4"));`);
  lines.push(`                }`);
  lines.push(`                else`);
  lines.push(`                {`);
  lines.push(`                    sb.Append(c);`);
  lines.push(`                }`);
  lines.push(`            }`);
  lines.push(`            sb.Append('"');`);
  lines.push(`            return sb.ToString();`);
  lines.push(`        }`);
  lines.push(``);

  if (pageable.length) emitCsharpPageRuntime(lines);
  for (const op of ops) {
    const fn = toCsharpIdent(op.operationId);
    const authSuf = csharpAuthArgs(op, auth.any);
    const summary = String(op.summary || `${op.method} ${op.path}`)
      .replace(/\*\//g, "* /")
      .replace(/</g, "")
      .replace(/>/g, "")
      .replace(/\r?\n/g, " ");
    lines.push(`        /// <summary>${fn} ${summary} (operationId: ${op.operationId})</summary>`);
    lines.push(`        public object ${fn}(Dictionary<string, object> args)`);
    lines.push(`        {`);
    lines.push(`            Dictionary<string, object> rest = args != null ? new Dictionary<string, object>(args) : new Dictionary<string, object>();`);
    lines.push(`            string path = ExpandPath(${JSON.stringify(op.path)}, rest);`);
    if (op.method === "GET" || op.method === "DELETE") {
      lines.push(`            return DoRequest(${JSON.stringify(op.method)}, path + QueryString(rest), null` + authSuf + `);`);
    } else {
      lines.push(`            return DoRequest(${JSON.stringify(op.method)}, path, rest` + authSuf + `);`);
    }
    lines.push(`        }`);
    lines.push(``);
    const hit = pageable.find((p) => p.op === op);
    if (hit) emitCsharpIterate(lines, op, hit.info, hit.iter);
  }

  lines.push(`    }`);
  lines.push(`}`);
  lines.push(``);
  return lines.join("\n");
}


/** Kotlin identifier from operationId (camelCase; keywords suffixed). */
const KOTLIN_KEYWORDS = new Set([
  "as", "break", "class", "continue", "do", "else", "false", "for", "fun", "if",
  "in", "interface", "is", "null", "object", "package", "return", "super", "this",
  "throw", "true", "try", "typealias", "typeof", "val", "var", "when", "while",
  "catch", "constructor", "delegate", "dynamic", "field", "file", "finally", "get",
  "import", "init", "param", "property", "receiver", "set", "setparam", "where",
  "actual", "abstract", "annotation", "companion", "const", "crossinline", "data",
  "enum", "expect", "external", "final", "infix", "inline", "inner", "internal",
  "lateinit", "noinline", "open", "operator", "out", "override", "private",
  "protected", "public", "reified", "sealed", "suspend", "tailrec", "value",
  "vararg", "it",
]);

export function toKotlinIdent(name) {
  let cleaned = String(name || "op").replace(/[^a-zA-Z0-9_]/g, "_");
  if (!cleaned) return "op";
  if (/^[0-9]/.test(cleaned)) cleaned = "op" + cleaned;
  if (KOTLIN_KEYWORDS.has(cleaned)) return cleaned + "_";
  return cleaned;
}


function emitKotlinPageRuntime(lines) {
  lines.push(`    // Page helper: GET page/pageSize/offset/limit/cursor/starting_after. Follow next/next_cursor/nextPageToken or increment page. Cap 1000. Not a Stainless pager.`);
  lines.push(`    private fun jsonSkipWs(cs: CharArray, pos: IntArray) {`);
  lines.push(`        while (pos[0] < cs.size) {`);
  lines.push(`            val c = cs[pos[0]]`);
  lines.push(`            if (c == ' ' || c == '\\n' || c == '\\r' || c == '\\t') {`);
  lines.push(`                pos[0] = pos[0] + 1`);
  lines.push(`            } else {`);
  lines.push(`                break`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private fun jsonParse(s: String?): Any? {`);
  lines.push(`        if (s == null) {`);
  lines.push(`            return null`);
  lines.push(`        }`);
  lines.push(`        val cs = s.toCharArray()`);
  lines.push(`        val pos = intArrayOf(0)`);
  lines.push(`        val v = jsonParseValue(cs, pos)`);
  lines.push(`        jsonSkipWs(cs, pos)`);
  lines.push(`        return v`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private fun jsonParseValue(cs: CharArray, pos: IntArray): Any? {`);
  lines.push(`        jsonSkipWs(cs, pos)`);
  lines.push(`        if (pos[0] >= cs.size) {`);
  lines.push(`            throw RuntimeException("json eof")`);
  lines.push(`        }`);
  lines.push(`        val c = cs[pos[0]]`);
  lines.push(`        if (c == '{') {`);
  lines.push(`            return jsonParseObject(cs, pos)`);
  lines.push(`        }`);
  lines.push(`        if (c == '[') {`);
  lines.push(`            return jsonParseArray(cs, pos)`);
  lines.push(`        }`);
  lines.push(`        if (c == '"') {`);
  lines.push(`            return jsonParseString(cs, pos)`);
  lines.push(`        }`);
  lines.push(`        if (c == 't' || c == 'f' || c == 'n') {`);
  lines.push(`            return jsonParseLiteral(cs, pos)`);
  lines.push(`        }`);
  lines.push(`        if (c == '-' || (c >= '0' && c <= '9')) {`);
  lines.push(`            return jsonParseNumber(cs, pos)`);
  lines.push(`        }`);
  lines.push(`        throw RuntimeException("json value")`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private fun jsonParseObject(cs: CharArray, pos: IntArray): Any? {`);
  lines.push(`        pos[0] = pos[0] + 1`);
  lines.push(`        val m = HashMap<String, Any?>()`);
  lines.push(`        jsonSkipWs(cs, pos)`);
  lines.push(`        if (pos[0] < cs.size && cs[pos[0]] == '}') {`);
  lines.push(`            pos[0] = pos[0] + 1`);
  lines.push(`            return m`);
  lines.push(`        }`);
  lines.push(`        while (true) {`);
  lines.push(`            jsonSkipWs(cs, pos)`);
  lines.push(`            val key = jsonParseString(cs, pos)`);
  lines.push(`            jsonSkipWs(cs, pos)`);
  lines.push(`            if (pos[0] >= cs.size || cs[pos[0]] != ':') {`);
  lines.push(`                throw RuntimeException("json colon")`);
  lines.push(`            }`);
  lines.push(`            pos[0] = pos[0] + 1`);
  lines.push(`            m.put(key, jsonParseValue(cs, pos))`);
  lines.push(`            jsonSkipWs(cs, pos)`);
  lines.push(`            if (pos[0] >= cs.size) {`);
  lines.push(`                throw RuntimeException("json object")`);
  lines.push(`            }`);
  lines.push(`            val c = cs[pos[0]]`);
  lines.push(`            pos[0] = pos[0] + 1`);
  lines.push(`            if (c == '}') {`);
  lines.push(`                return m`);
  lines.push(`            }`);
  lines.push(`            if (c != ',') {`);
  lines.push(`                throw RuntimeException("json object")`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private fun jsonParseArray(cs: CharArray, pos: IntArray): Any? {`);
  lines.push(`        pos[0] = pos[0] + 1`);
  lines.push(`        val a = ArrayList<Any?>()`);
  lines.push(`        jsonSkipWs(cs, pos)`);
  lines.push(`        if (pos[0] < cs.size && cs[pos[0]] == ']') {`);
  lines.push(`            pos[0] = pos[0] + 1`);
  lines.push(`            return a`);
  lines.push(`        }`);
  lines.push(`        while (true) {`);
  lines.push(`            a.add(jsonParseValue(cs, pos))`);
  lines.push(`            jsonSkipWs(cs, pos)`);
  lines.push(`            if (pos[0] >= cs.size) {`);
  lines.push(`                throw RuntimeException("json array")`);
  lines.push(`            }`);
  lines.push(`            val c = cs[pos[0]]`);
  lines.push(`            pos[0] = pos[0] + 1`);
  lines.push(`            if (c == ']') {`);
  lines.push(`                return a`);
  lines.push(`            }`);
  lines.push(`            if (c != ',') {`);
  lines.push(`                throw RuntimeException("json array")`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private fun jsonParseString(cs: CharArray, pos: IntArray): String {`);
  lines.push(`        if (pos[0] >= cs.size || cs[pos[0]] != '"') {`);
  lines.push(`            throw RuntimeException("json string")`);
  lines.push(`        }`);
  lines.push(`        pos[0] = pos[0] + 1`);
  lines.push(`        val sb = StringBuilder()`);
  lines.push(`        while (pos[0] < cs.size) {`);
  lines.push(`            val c = cs[pos[0]]`);
  lines.push(`            pos[0] = pos[0] + 1`);
  lines.push(`            if (c == '"') {`);
  lines.push(`                return sb.toString()`);
  lines.push(`            }`);
  lines.push(`            if (c == '\\\\') {`);
  lines.push(`                if (pos[0] >= cs.size) {`);
  lines.push(`                    throw RuntimeException("json string")`);
  lines.push(`                }`);
  lines.push(`                val e = cs[pos[0]]`);
  lines.push(`                pos[0] = pos[0] + 1`);
  lines.push(`                if (e == '"' || e == '\\\\' || e == '/') {`);
  lines.push(`                    sb.append(e)`);
  lines.push(`                } else if (e == 'b') {`);
  lines.push(`                    sb.append('\\b')`);
  lines.push(`                } else if (e == 'f') {`);
  lines.push(`                    sb.append('\\f')`);
  lines.push(`                } else if (e == 'n') {`);
  lines.push(`                    sb.append('\\n')`);
  lines.push(`                } else if (e == 'r') {`);
  lines.push(`                    sb.append('\\r')`);
  lines.push(`                } else if (e == 't') {`);
  lines.push(`                    sb.append('\\t')`);
  lines.push(`                } else if (e == 'u' && pos[0] + 4 <= cs.size) {`);
  lines.push(`                    val hex = String(cs, pos[0], 4)`);
  lines.push(`                    pos[0] = pos[0] + 4`);
  lines.push(`                    sb.append(Integer.parseInt(hex, 16).toChar())`);
  lines.push(`                } else {`);
  lines.push(`                    sb.append(e)`);
  lines.push(`                }`);
  lines.push(`            } else {`);
  lines.push(`                sb.append(c)`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        throw RuntimeException("json string")`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private fun jsonParseLiteral(cs: CharArray, pos: IntArray): Any? {`);
  lines.push(`        if (pos[0] + 4 <= cs.size && cs[pos[0]] == 't' && cs[pos[0] + 1] == 'r' && cs[pos[0] + 2] == 'u' && cs[pos[0] + 3] == 'e') {`);
  lines.push(`            pos[0] = pos[0] + 4`);
  lines.push(`            return true`);
  lines.push(`        }`);
  lines.push(`        if (pos[0] + 5 <= cs.size && cs[pos[0]] == 'f' && cs[pos[0] + 1] == 'a' && cs[pos[0] + 2] == 'l' && cs[pos[0] + 3] == 's' && cs[pos[0] + 4] == 'e') {`);
  lines.push(`            pos[0] = pos[0] + 5`);
  lines.push(`            return false`);
  lines.push(`        }`);
  lines.push(`        if (pos[0] + 4 <= cs.size && cs[pos[0]] == 'n' && cs[pos[0] + 1] == 'u' && cs[pos[0] + 2] == 'l' && cs[pos[0] + 3] == 'l') {`);
  lines.push(`            pos[0] = pos[0] + 4`);
  lines.push(`            return null`);
  lines.push(`        }`);
  lines.push(`        throw RuntimeException("json literal")`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private fun jsonParseNumber(cs: CharArray, pos: IntArray): Any? {`);
  lines.push(`        val start = pos[0]`);
  lines.push(`        if (cs[pos[0]] == '-') {`);
  lines.push(`            pos[0] = pos[0] + 1`);
  lines.push(`        }`);
  lines.push(`        while (pos[0] < cs.size && cs[pos[0]] >= '0' && cs[pos[0]] <= '9') {`);
  lines.push(`            pos[0] = pos[0] + 1`);
  lines.push(`        }`);
  lines.push(`        var frac = false`);
  lines.push(`        if (pos[0] < cs.size && cs[pos[0]] == '.') {`);
  lines.push(`            frac = true`);
  lines.push(`            pos[0] = pos[0] + 1`);
  lines.push(`            while (pos[0] < cs.size && cs[pos[0]] >= '0' && cs[pos[0]] <= '9') {`);
  lines.push(`                pos[0] = pos[0] + 1`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        if (pos[0] < cs.size && (cs[pos[0]] == 'e' || cs[pos[0]] == 'E')) {`);
  lines.push(`            frac = true`);
  lines.push(`            pos[0] = pos[0] + 1`);
  lines.push(`            if (pos[0] < cs.size && (cs[pos[0]] == '+' || cs[pos[0]] == '-')) {`);
  lines.push(`                pos[0] = pos[0] + 1`);
  lines.push(`            }`);
  lines.push(`            while (pos[0] < cs.size && cs[pos[0]] >= '0' && cs[pos[0]] <= '9') {`);
  lines.push(`                pos[0] = pos[0] + 1`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        val raw = String(cs, start, pos[0] - start)`);
  lines.push(`        if (!frac) {`);
  lines.push(`            try {`);
  lines.push(`                return raw.toLong()`);
  lines.push(`            } catch (ignored: NumberFormatException) {`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        return raw.toDouble()`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private fun asPageData(data: Any?): Any? {`);
  lines.push(`        if (data is String) {`);
  lines.push(`            val s = data.trim()`);
  lines.push(`            if (s.isNotEmpty() && (s[0] == '{' || s[0] == '[')) {`);
  lines.push(`                try {`);
  lines.push(`                    return jsonParse(s)`);
  lines.push(`                } catch (ignored: Exception) {`);
  lines.push(`                    return data`);
  lines.push(`                }`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        return data`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private fun pageLen(data: Any?): Int {`);
  lines.push(`        if (data is List<*>) {`);
  lines.push(`            return data.size`);
  lines.push(`        }`);
  lines.push(`        if (data is Map<*, *>) {`);
  lines.push(`            for (k in arrayOf("data", "items", "results")) {`);
  lines.push(`                val a = data[k]`);
  lines.push(`                if (a is List<*>) {`);
  lines.push(`                    return a.size`);
  lines.push(`                }`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        return -1`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private fun nextCursorOf(data: Any?): String? {`);
  lines.push(`        if (data !is Map<*, *>) {`);
  lines.push(`            return null`);
  lines.push(`        }`);
  lines.push(`        for (k in arrayOf("next", "next_cursor", "nextPageToken")) {`);
  lines.push(`            val v = data[k]`);
  lines.push(`            if (v is String && v.isNotEmpty()) {`);
  lines.push(`                return v`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        return null`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private fun asInt(v: Any?, fallback: Int): Int {`);
  lines.push(`        if (v == null) {`);
  lines.push(`            return fallback`);
  lines.push(`        }`);
  lines.push(`        if (v is Number) {`);
  lines.push(`            return v.toInt()`);
  lines.push(`        }`);
  lines.push(`        try {`);
  lines.push(`            return v.toString().trim().toInt()`);
  lines.push(`        } catch (ignored: Exception) {`);
  lines.push(`            return fallback`);
  lines.push(`        }`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private fun cloneArgs(args: Map<String, Any?>?): HashMap<String, Any?> {`);
  lines.push(`        val out = HashMap<String, Any?>()`);
  lines.push(`        if (args != null) {`);
  lines.push(`            out.putAll(args)`);
  lines.push(`        }`);
  lines.push(`        return out`);
  lines.push(`    }`);
  lines.push(``);
}

function emitKotlinIterate(lines, op, info, iterName) {
  const fn = toKotlinIdent(op.operationId);
  const ktIter = toKotlinIdent(iterName);
  const mode = info.mode;
  const sizeKey = info.sizeParam;
  const cursorKey = info.cursorParam || "cursor";
  const pageKey = info.pageParam || "page";
  const offsetKey = info.offsetParam || "offset";
  const summary = `walks pages for ${op.operationId} (page/cursor; cap 1000). Not a full pager.`.replace(/\*\//g, "* /");
  lines.push(`    /** ${ktIter} ${summary} */`);
  lines.push(`    fun ${ktIter}(args: Map<String, Any?>?): List<Any?> {`);
  lines.push(`        val state = cloneArgs(args)`);
  if (mode === "offset") {
    lines.push(`        var offset = asInt(state[${JSON.stringify(offsetKey)}], 0)`);
  } else if (mode === "page") {
    lines.push(`        var page = asInt(state[${JSON.stringify(pageKey)}], 1)`);
    lines.push(`        if (page < 1) {`);
    lines.push(`            page = 1`);
    lines.push(`        }`);
  }
  lines.push(`        val pages = ArrayList<Any?>()`);
  lines.push(`        var n = 0`);
  lines.push(`        while (n < 1000) {`);
  lines.push(`            n += 1`);
  lines.push(`            val call = cloneArgs(state)`);
  if (mode === "offset") {
    lines.push(`            call[${JSON.stringify(offsetKey)}] = offset`);
  } else if (mode === "page") {
    lines.push(`            call[${JSON.stringify(pageKey)}] = page`);
  }
  lines.push(`            val data = asPageData(this.${fn}(call))`);
  lines.push(`            pages.add(data)`);
  lines.push(`            val ln = pageLen(data)`);
  if (sizeKey) {
    lines.push(`            val size = asInt(call[${JSON.stringify(sizeKey)}], 0)`);
    lines.push(`            if (data == null || ln == 0 || (size > 0 && ln >= 0 && ln < size)) {`);
    lines.push(`                break`);
    lines.push(`            }`);
  } else {
    lines.push(`            if (data == null || ln == 0) {`);
    lines.push(`                break`);
    lines.push(`            }`);
  }
  lines.push(`            val cur = nextCursorOf(data)`);
  lines.push(`            val prev = state[${JSON.stringify(cursorKey)}]`);
  lines.push(`            if (cur != null && (prev == null || cur != prev.toString())) {`);
  lines.push(`                state[${JSON.stringify(cursorKey)}] = cur`);
  lines.push(`                continue`);
  lines.push(`            }`);
  if (mode === "cursor") {
    lines.push(`            break`);
  } else if (mode === "offset") {
    lines.push(`            if (ln < 0) {`);
    lines.push(`                break`);
    lines.push(`            }`);
    if (sizeKey) {
      lines.push(`            val step = if (size > 0) size else ln`);
    } else {
      lines.push(`            val step = ln`);
    }
    lines.push(`            if (step <= 0) {`);
    lines.push(`                break`);
    lines.push(`            }`);
    lines.push(`            offset += step`);
  } else {
    lines.push(`            if (ln < 0) {`);
    lines.push(`                break`);
    lines.push(`            }`);
    lines.push(`            page += 1`);
  }
  lines.push(`        }`);
  lines.push(`        return pages`);
  lines.push(`    }`);
  lines.push(``);
}

/**
 * Minimal Kotlin HTTP client stub (JVM stdlib java.net.HttpURLConnection).
 * Compiles with `kotlinc Client.kt` on the JVM (same HTTP stack as the Java client).
 */
export function generateKotlinClient(ops, title = "GeneratedClient", opts = {}) {
  const pkg = pkgFromOpts(opts);
  const safeTitle = String(title || "GeneratedClient").replace(/\*\//g, "* /");
  const pageable = pageableOps(ops);
  const auth = authFlags(ops);
  const lines = [];
  lines.push(`// Auto-generated by sdk-mcp-gen — do not edit by hand`);
  lines.push(`// API: ${safeTitle}`);
  lines.push(`package ${pkg.ident}`);
  lines.push(``);
  lines.push(`import java.io.ByteArrayOutputStream`);
  lines.push(`import java.io.InputStream`);
  lines.push(`import java.io.OutputStream`);
  lines.push(`import java.net.HttpURLConnection`);
  lines.push(`import java.net.URL`);
  lines.push(`import java.net.URLEncoder`);
  lines.push(`import java.nio.charset.StandardCharsets`);
  lines.push(`import java.util.HashMap`);
  if (pageable.length) {
    lines.push(`import java.util.ArrayList`);
  }
  lines.push(`import java.util.StringJoiner`);
  lines.push(``);
  lines.push(`/** Minimal HTTP client stub generated from OpenAPI (java.net.HttpURLConnection). */`);
  lines.push(`// Retry transient HTTP failures (429 / 5xx / network throw): max 2 retries, ~100ms exponential backoff, honor Retry-After <30s.`);
  lines.push(`// Per-attempt request timeout (default 10s): connect + read timeout. Override via timeoutMs or env SDK_TIMEOUT_MS / SDK_TIMEOUT_SEC.`);
  lines.push(`// Default User-Agent ${JSON.stringify(defaultUserAgent(opts))} unless the caller already set User-Agent.`);
  lines.push(`// X-Request-Id: new id per HTTP attempt. Pin via requestId or env SDK_REQUEST_ID (tests).`);
  lines.push(`// Idempotency-Key: on POST/PUT/PATCH/DELETE when unset. New key per logical call (retries reuse). Pin via idempotencyKey or env SDK_IDEMPOTENCY_KEY (tests).`);
  if (auth.any) {
    lines.push(`// Auth from OpenAPI securitySchemes (http bearer, apiKey header/query). oauth2 / openIdConnect skipped (no fake tokens).`);
    lines.push(`// Set bearerToken / apiKey or env SDK_BEARER_TOKEN / SDK_API_KEY. Attached per OpenAPI operation security on every attempt. Ops without security omit credentials. Values never logged.`);
  }
  lines.push(`class Client {`);
  lines.push(`    private val baseUrl: String`);
  lines.push(`    var timeoutMs: Int`);
  lines.push(`    var userAgent: String`);
  lines.push(`    var requestId: String`);
  lines.push(`    var idempotencyKey: String`);
  if (auth.hasBearer) {
    lines.push(`    var bearerToken: String`);
  }
  if (auth.headerKeys.length || auth.queryKeys.length) {
    lines.push(`    var apiKey: String`);
  }
  lines.push(``);
  lines.push(`    constructor() {`);
  lines.push(`        this.baseUrl = ""`);
  lines.push(`        this.timeoutMs = envTimeoutMs()`);
  lines.push(`        this.userAgent = ${JSON.stringify(defaultUserAgent(opts))}`);
  lines.push(`        this.requestId = envRequestId()`);
  lines.push(`        this.idempotencyKey = envIdempotencyKey()`);
  if (auth.hasBearer) {
    lines.push(`        this.bearerToken = envAuth("SDK_BEARER_TOKEN")`);
  }
  if (auth.headerKeys.length || auth.queryKeys.length) {
    lines.push(`        this.apiKey = envAuth("SDK_API_KEY")`);
  }
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    constructor(baseUrl: String?) {`);
  lines.push(`        if (baseUrl == null) {`);
  lines.push(`            this.baseUrl = ""`);
  lines.push(`        } else {`);
  lines.push(`            var n = baseUrl.length`);
  lines.push(`            while (n > 0 && baseUrl[n - 1] == '/') {`);
  lines.push(`                n -= 1`);
  lines.push(`            }`);
  lines.push(`            this.baseUrl = baseUrl.substring(0, n)`);
  lines.push(`        }`);
  lines.push(`        this.timeoutMs = envTimeoutMs()`);
  lines.push(`        this.userAgent = ${JSON.stringify(defaultUserAgent(opts))}`);
  lines.push(`        this.requestId = envRequestId()`);
  lines.push(`        this.idempotencyKey = envIdempotencyKey()`);
  if (auth.hasBearer) {
    lines.push(`        this.bearerToken = envAuth("SDK_BEARER_TOKEN")`);
  }
  if (auth.headerKeys.length || auth.queryKeys.length) {
    lines.push(`        this.apiKey = envAuth("SDK_API_KEY")`);
  }
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private fun envTimeoutMs(): Int {`);
  lines.push(`        val rawMs = System.getenv("SDK_TIMEOUT_MS")`);
  lines.push(`        if (rawMs != null && rawMs.trim().isNotEmpty()) {`);
  lines.push(`            try {`);
  lines.push(`                val ms = rawMs.trim().toInt()`);
  lines.push(`                if (ms > 0) {`);
  lines.push(`                    return ms`);
  lines.push(`                }`);
  lines.push(`            } catch (ignored: NumberFormatException) {`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        val rawSec = System.getenv("SDK_TIMEOUT_SEC")`);
  lines.push(`        if (rawSec != null && rawSec.trim().isNotEmpty()) {`);
  lines.push(`            try {`);
  lines.push(`                val sec = rawSec.trim().toInt()`);
  lines.push(`                if (sec > 0) {`);
  lines.push(`                    return sec * 1000`);
  lines.push(`                }`);
  lines.push(`            } catch (ignored: NumberFormatException) {`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        return 10000`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private fun envRequestId(): String {`);
  lines.push(`        val v = System.getenv("SDK_REQUEST_ID")`);
  lines.push(`        if (v == null) {`);
  lines.push(`            return ""`);
  lines.push(`        }`);
  lines.push(`        return v.trim()`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private fun envIdempotencyKey(): String {`);
  lines.push(`        val v = System.getenv("SDK_IDEMPOTENCY_KEY")`);
  lines.push(`        if (v == null) {`);
  lines.push(`            return ""`);
  lines.push(`        }`);
  lines.push(`        return v.trim()`);
  lines.push(`    }`);
  lines.push(``);
  if (auth.any) {
    lines.push(`    private fun envAuth(name: String): String {`);
    lines.push(`        val v = System.getenv(name)`);
    lines.push(`        if (v == null) {`);
    lines.push(`            return ""`);
    lines.push(`        }`);
    lines.push(`        return v.trim()`);
    lines.push(`    }`);
    lines.push(``);
  }
  lines.push(`    private fun retryDelayMs(conn: HttpURLConnection?, attempt: Int): Long {`);
  lines.push(`        var raw = if (conn == null) null else conn.getHeaderField("Retry-After")`);
  lines.push(`        if (raw != null) {`);
  lines.push(`            raw = raw.trim()`);
  lines.push(`            try {`);
  lines.push(`                val sec = raw.toDouble()`);
  lines.push(`                if (sec >= 0 && sec < 30) {`);
  lines.push(`                    return (sec * 1000.0).toLong()`);
  lines.push(`                }`);
  lines.push(`            } catch (ignored: NumberFormatException) {`);
  lines.push(`                try {`);
  lines.push(`                    val whenAt = java.time.ZonedDateTime.parse(raw, java.time.format.DateTimeFormatter.RFC_1123_DATE_TIME)`);
  lines.push(`                    val delta = whenAt.toInstant().toEpochMilli() - System.currentTimeMillis()`);
  lines.push(`                    if (delta >= 0 && delta < 30000) {`);
  lines.push(`                        return delta`);
  lines.push(`                    }`);
  lines.push(`                } catch (ignored2: Exception) {`);
  lines.push(`                }`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        return 100L * (1L shl attempt)`);
  lines.push(`    }`);
  lines.push(``);
  const reqSig = auth.any
    ? `    private fun doRequest(method: String, path: String, body: Any?, authBearer: Boolean, authHeaders: Array<String>?, authQuery: Array<String>?): Any? {`
    : `    private fun doRequest(method: String, path: String, body: Any?): Any? {`;
  lines.push(reqSig);
  lines.push(`        val timeout = if (this.timeoutMs > 0) this.timeoutMs else envTimeoutMs()`);
  lines.push(`        var opIdem = ""`);
  lines.push(`        val mth = if (method == null) "" else method.uppercase()`);
  lines.push(`        if (mth == "POST" || mth == "PUT" || mth == "PATCH" || mth == "DELETE") {`);
  lines.push(`            opIdem = if (this.idempotencyKey != null && this.idempotencyKey.trim().isNotEmpty()) this.idempotencyKey.trim() else envIdempotencyKey()`);
  lines.push(`            if (opIdem.isEmpty()) {`);
  lines.push(`                opIdem = java.util.UUID.randomUUID().toString()`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        var last: Exception? = null`);
  lines.push(`        var attempt = 0`);
  lines.push(`        while (attempt < 3) {`);
  lines.push(`            var conn: HttpURLConnection? = null`);
  lines.push(`            try {`);
  lines.push(`                var reqPath = path`);
  if (auth.queryKeys.length) {
    lines.push(`                val qNames = authQuery`);
    lines.push(`                val qKey = this.apiKey`);
    lines.push(`                if (qNames != null && qKey != null && qKey.trim().isNotEmpty()) {`);
    lines.push(`                    val key = qKey.trim()`);
    lines.push(`                    for (q in qNames) {`);
    lines.push(`                        if (q == null || q.isEmpty()) {`);
    lines.push(`                            continue`);
    lines.push(`                        }`);
    lines.push(`                        reqPath = reqPath + (if (reqPath.indexOf('?') >= 0) "&" else "?") + urlEncode(q) + "=" + urlEncode(key)`);
    lines.push(`                    }`);
    lines.push(`                }`);
  }
  lines.push(`                val url = URL(this.baseUrl + reqPath)`);
  lines.push(`                conn = url.openConnection() as HttpURLConnection`);
  lines.push(`                conn.requestMethod = method`);
  lines.push(`                conn.connectTimeout = timeout`);
  lines.push(`                conn.readTimeout = timeout`);
  lines.push(`                conn.useCaches = false`);
  lines.push(`                if (conn.getRequestProperty("User-Agent") == null) {`);
  lines.push(`                    val ua = if (this.userAgent != null && this.userAgent.trim().isNotEmpty()) this.userAgent.trim() else ${JSON.stringify(defaultUserAgent(opts))}`);
  lines.push(`                    conn.setRequestProperty("User-Agent", ua)`);
  lines.push(`                }`);
  lines.push(`                if (conn.getRequestProperty("X-Request-Id") == null) {`);
  lines.push(`                    var rid = if (this.requestId != null && this.requestId.trim().isNotEmpty()) this.requestId.trim() else envRequestId()`);
  lines.push(`                    if (rid.isEmpty()) {`);
  lines.push(`                        rid = java.util.UUID.randomUUID().toString()`);
  lines.push(`                    }`);
  lines.push(`                    conn.setRequestProperty("X-Request-Id", rid)`);
  lines.push(`                }`);
  lines.push(`                if (opIdem.isNotEmpty() && conn.getRequestProperty("Idempotency-Key") == null) {`);
  lines.push(`                    conn.setRequestProperty("Idempotency-Key", opIdem)`);
  lines.push(`                }`);
  if (auth.hasBearer) {
    lines.push(`                val tok = this.bearerToken`);
    lines.push(`                if (authBearer && tok != null && tok.trim().isNotEmpty()) {`);
    lines.push(`                    conn.setRequestProperty("Authorization", "Bearer " + tok.trim())`);
    lines.push(`                }`);
  }
  if (auth.headerKeys.length) {
    lines.push(`                val hNames = authHeaders`);
    lines.push(`                val hKey = this.apiKey`);
    lines.push(`                if (hNames != null && hKey != null && hKey.trim().isNotEmpty()) {`);
    lines.push(`                    val key = hKey.trim()`);
    lines.push(`                    for (h in hNames) {`);
    lines.push(`                        if (h != null && h.isNotEmpty()) {`);
    lines.push(`                            conn.setRequestProperty(h, key)`);
    lines.push(`                        }`);
    lines.push(`                    }`);
    lines.push(`                }`);
  }
  lines.push(`                if (body != null) {`);
  lines.push(`                    val bytes = jsonStringify(body).toByteArray(StandardCharsets.UTF_8)`);
  lines.push(`                    conn.doOutput = true`);
  lines.push(`                    conn.setRequestProperty("Content-Type", "application/json")`);
  lines.push(`                    val os: OutputStream = conn.outputStream`);
  lines.push(`                    try {`);
  lines.push(`                        os.write(bytes)`);
  lines.push(`                    } finally {`);
  lines.push(`                        os.close()`);
  lines.push(`                    }`);
  lines.push(`                }`);
  lines.push(`                val code = conn.responseCode`);
  lines.push(`                val stream: InputStream? = if (code >= 400) conn.errorStream else conn.inputStream`);
  lines.push(`                val text = readAll(stream)`);
  lines.push(`                if (code >= 200 && code < 300) {`);
  lines.push(`                    if (text == null || text.length == 0) {`);
  lines.push(`                        return null`);
  lines.push(`                    }`);
  lines.push(`                    return text`);
  lines.push(`                }`);
  lines.push(`                if ((code == 429 || code >= 500) && attempt < 2) {`);
  lines.push(`                    Thread.sleep(retryDelayMs(conn, attempt))`);
  lines.push(`                    attempt += 1`);
  lines.push(`                    continue`);
  lines.push(`                }`);
  lines.push(`                throw RuntimeException(method + " " + path + " -> " + code)`);
  lines.push(`            } catch (e: RuntimeException) {`);
  lines.push(`                throw e`);
  lines.push(`            } catch (e: Exception) {`);
  lines.push(`                last = e`);
  lines.push(`                if (attempt >= 2) {`);
  lines.push(`                    throw e`);
  lines.push(`                }`);
  lines.push(`                Thread.sleep(100L * (1L shl attempt))`);
  lines.push(`            } finally {`);
  lines.push(`                if (conn != null) {`);
  lines.push(`                    conn.disconnect()`);
  lines.push(`                }`);
  lines.push(`            }`);
  lines.push(`            attempt += 1`);
  lines.push(`        }`);
  lines.push(`        if (last != null) {`);
  lines.push(`            throw last`);
  lines.push(`        }`);
  lines.push(`        throw RuntimeException(method + " " + path + " -> network")`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private fun readAll(input: InputStream?): String {`);
  lines.push(`        if (input == null) {`);
  lines.push(`            return ""`);
  lines.push(`        }`);
  lines.push(`        val buf = ByteArrayOutputStream()`);
  lines.push(`        val tmp = ByteArray(4096)`);
  lines.push(`        while (true) {`);
  lines.push(`            val n = input.read(tmp)`);
  lines.push(`            if (n < 0) {`);
  lines.push(`                break`);
  lines.push(`            }`);
  lines.push(`            buf.write(tmp, 0, n)`);
  lines.push(`        }`);
  lines.push(`        input.close()`);
  lines.push(`        return String(buf.toByteArray(), StandardCharsets.UTF_8)`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private fun urlEncode(s: String): String {`);
  lines.push(`        return URLEncoder.encode(s, "UTF-8").replace("+", "%20")`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private fun expandPath(pathTpl: String, rest: HashMap<String, Any?>): String {`);
  lines.push(`        var out = pathTpl`);
  lines.push(`        while (true) {`);
  lines.push(`            val start = out.indexOf('{')`);
  lines.push(`            if (start < 0) {`);
  lines.push(`                break`);
  lines.push(`            }`);
  lines.push(`            val end = out.indexOf('}', start)`);
  lines.push(`            if (end < 0) {`);
  lines.push(`                break`);
  lines.push(`            }`);
  lines.push(`            val key = out.substring(start + 1, end)`);
  lines.push(`            val value = rest.remove(key)`);
  lines.push(`            var repl = ""`);
  lines.push(`            if (value != null) {`);
  lines.push(`                repl = urlEncode(value.toString())`);
  lines.push(`            }`);
  lines.push(`            out = out.substring(0, start) + repl + out.substring(end + 1)`);
  lines.push(`        }`);
  lines.push(`        return out`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private fun queryString(rest: HashMap<String, Any?>): String {`);
  lines.push(`        val j = StringJoiner("&")`);
  lines.push(`        for (e in rest.entries) {`);
  lines.push(`            val value = e.value`);
  lines.push(`            if (value == null) {`);
  lines.push(`                continue`);
  lines.push(`            }`);
  lines.push(`            j.add(urlEncode(e.key) + "=" + urlEncode(value.toString()))`);
  lines.push(`        }`);
  lines.push(`        val enc = j.toString()`);
  lines.push(`        return if (enc.isEmpty()) "" else "?" + enc`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private fun jsonStringify(v: Any?): String {`);
  lines.push(`        if (v == null) {`);
  lines.push(`            return "null"`);
  lines.push(`        }`);
  lines.push(`        if (v is Number || v is Boolean) {`);
  lines.push(`            return v.toString()`);
  lines.push(`        }`);
  lines.push(`        if (v is Map<*, *>) {`);
  lines.push(`            val j = StringJoiner(",", "{", "}")`);
  lines.push(`            for (e in v.entries) {`);
  lines.push(`                j.add(jsonStringify("" + e.key) + ":" + jsonStringify(e.value))`);
  lines.push(`            }`);
  lines.push(`            return j.toString()`);
  lines.push(`        }`);
  lines.push(`        if (v is Iterable<*> && v !is CharSequence) {`);
  lines.push(`            val j = StringJoiner(",", "[", "]")`);
  lines.push(`            for (x in v) {`);
  lines.push(`                j.add(jsonStringify(x))`);
  lines.push(`            }`);
  lines.push(`            return j.toString()`);
  lines.push(`        }`);
  lines.push(`        val s = v.toString()`);
  lines.push(`        val sb = StringBuilder("\\"");`);
  lines.push(`        var i = 0`);
  lines.push(`        while (i < s.length) {`);
  lines.push(`            val c = s[i]`);
  lines.push(`            if (c == '"') {`);
  lines.push(`                sb.append("\\\\\\"")`);
  lines.push(`            } else if (c == '\\\\') {`);
  lines.push(`                sb.append("\\\\\\\\")`);
  lines.push(`            } else if (c == '\\n') {`);
  lines.push(`                sb.append("\\\\n")`);
  lines.push(`            } else if (c == '\\r') {`);
  lines.push(`                sb.append("\\\\r")`);
  lines.push(`            } else if (c == '\\t') {`);
  lines.push(`                sb.append("\\\\t")`);
  lines.push(`            } else if (c.toInt() < 0x20) {`);
  lines.push(`                sb.append(String.format("\\\\u%04x", c.toInt()))`);
  lines.push(`            } else {`);
  lines.push(`                sb.append(c)`);
  lines.push(`            }`);
  lines.push(`            i += 1`);
  lines.push(`        }`);
  lines.push(`        sb.append("\\"")`);
  lines.push(`        return sb.toString()`);
  lines.push(`    }`);
  lines.push(``);

  if (pageable.length) emitKotlinPageRuntime(lines);
  for (const op of ops) {
    const fn = toKotlinIdent(op.operationId);
    const authSuf = jvmAuthArgs(op, auth.any);
    const summary = String(op.summary || `${op.method} ${op.path}`).replace(/\*\//g, "* /");
    lines.push(`    /** ${fn} ${summary} (operationId: ${op.operationId}) */`);
    lines.push(`    fun ${fn}(args: Map<String, Any?>?): Any? {`);
    lines.push(`        val rest = HashMap<String, Any?>()`);
    lines.push(`        if (args != null) {`);
    lines.push(`            rest.putAll(args)`);
    lines.push(`        }`);
    lines.push(`        val path = expandPath(${JSON.stringify(op.path)}, rest)`);
    if (op.method === "GET" || op.method === "DELETE") {
      lines.push(`        return doRequest(${JSON.stringify(op.method)}, path + queryString(rest), null` + authSuf + `)`);
    } else {
      lines.push(`        return doRequest(${JSON.stringify(op.method)}, path, rest` + authSuf + `)`);
    }
    lines.push(`    }`);
    lines.push(``);
    const hit = pageable.find((p) => p.op === op);
    if (hit) emitKotlinIterate(lines, op, hit.info, hit.iter);
  }

  lines.push(`}`);
  lines.push(``);
  return lines.join("\n");
}


/** Swift identifier from operationId (camelCase; keywords / init suffixed). */
const SWIFT_KEYWORDS = new Set([
  "associatedtype", "class", "deinit", "enum", "extension", "fileprivate", "func", "import",
  "init", "inout", "internal", "let", "open", "operator", "private", "protocol", "public",
  "rethrows", "static", "struct", "subscript", "typealias", "var", "break", "case", "continue",
  "default", "defer", "do", "else", "fallthrough", "for", "guard", "if", "in", "repeat",
  "return", "switch", "where", "while", "as", "Any", "catch", "false", "is", "nil", "super",
  "self", "Self", "throw", "throws", "true", "try", "associativity", "convenience", "dynamic",
  "didSet", "final", "get", "infix", "indirect", "lazy", "left", "mutating", "none",
  "nonmutating", "optional", "override", "postfix", "precedence", "prefix", "Protocol",
  "required", "right", "set", "Type", "unowned", "weak", "willSet", "actor", "async", "await",
  "borrowing", "consuming", "isolated", "nonisolated", "some", "package", "each", "macro",
  "discard",
]);

export function toSwiftIdent(name) {
  let cleaned = String(name || "op").replace(/[^a-zA-Z0-9_]/g, "_");
  if (!cleaned) return "op";
  if (/^[0-9]/.test(cleaned)) cleaned = "op" + cleaned;
  if (SWIFT_KEYWORDS.has(cleaned) || cleaned === "init") return cleaned + "_";
  return cleaned;
}

/**
 * Minimal Swift HTTP client stub (Foundation URLSession).
 * Single file: `swiftc -typecheck Client.swift` (no SPM / Alamofire).
 * `public class Client` with one public method per OpenAPI operation.
 */
export function generateSwiftClient(ops, title = "GeneratedClient", opts = {}) {
  const pkg = pkgFromOpts(opts);
  const safeTitle = String(title || "GeneratedClient").replace(/\*\//g, "* /");
  const auth = authFlags(ops);
  const lines = [];
  lines.push(`// Auto-generated by sdk-mcp-gen — do not edit by hand`);
  lines.push(`// API: ${safeTitle}`);
  lines.push(`// package: ${pkg.ident}`);
  lines.push(`import Foundation`);
  lines.push(`import Dispatch`);
  lines.push(``);
  lines.push(`/// Minimal HTTP client stub generated from OpenAPI (Foundation URLSession).`);
  lines.push(`// Retry transient HTTP failures (429 / 5xx / network): max 2 retries, ~100ms exponential backoff, honor Retry-After <30s.`);
  lines.push(`// Per-attempt request timeout (default 10s): URLRequest.timeoutInterval. Override via timeoutMs or env SDK_TIMEOUT_MS / SDK_TIMEOUT_SEC.`);
  lines.push(`// Default User-Agent ${JSON.stringify(defaultUserAgent(opts))} unless already set. X-Request-Id new per attempt; pin via requestId or env SDK_REQUEST_ID.`);
  lines.push(`// Idempotency-Key on POST/PUT/PATCH/DELETE when unset; new per logical call (retries reuse). Pin via idempotencyKey or env SDK_IDEMPOTENCY_KEY.`);
  if (auth.any) {
    lines.push(`// Auth from OpenAPI securitySchemes (http bearer, apiKey header/query). oauth2 / openIdConnect skipped (no fake tokens).`);
    lines.push(`// Set bearerToken / apiKey or env SDK_BEARER_TOKEN / SDK_API_KEY. Attached per OpenAPI operation security on every attempt. Ops without security omit credentials. Values never logged.`);
  }
  lines.push(`public class Client {`);
  lines.push(`    public let baseUrl: String`);
  lines.push(`    public let session: URLSession`);
  lines.push(`    public var timeoutMs: Int`);
  lines.push(`    public var userAgent: String`);
  lines.push(`    public var requestId: String`);
  lines.push(`    public var idempotencyKey: String`);
  if (auth.hasBearer) {
    lines.push(`    public var bearerToken: String`);
  }
  if (auth.headerKeys.length || auth.queryKeys.length) {
    lines.push(`    public var apiKey: String`);
  }
  lines.push(``);
  lines.push(`    public init(_ baseUrl: String = "", session: URLSession = URLSession.shared) {`);
  lines.push(`        var trimmed = baseUrl`);
  lines.push(`        while trimmed.hasSuffix("/") {`);
  lines.push(`            trimmed.removeLast()`);
  lines.push(`        }`);
  lines.push(`        self.baseUrl = trimmed`);
  lines.push(`        self.session = session`);
  lines.push(`        self.timeoutMs = Client.envTimeoutMs()`);
  lines.push(`        self.userAgent = ${JSON.stringify(defaultUserAgent(opts))}`);
  lines.push(`        self.requestId = Client.envRequestId()`);
  lines.push(`        self.idempotencyKey = Client.envIdempotencyKey()`);
  if (auth.hasBearer) {
    lines.push(`        self.bearerToken = Client.envAuth("SDK_BEARER_TOKEN")`);
  }
  if (auth.headerKeys.length || auth.queryKeys.length) {
    lines.push(`        self.apiKey = Client.envAuth("SDK_API_KEY")`);
  }
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private static func envTimeoutMs() -> Int {`);
  lines.push(`        if let raw = ProcessInfo.processInfo.environment["SDK_TIMEOUT_MS"] {`);
  lines.push(`            let t = raw.trimmingCharacters(in: .whitespacesAndNewlines)`);
  lines.push(`            if let ms = Int(t), ms > 0 {`);
  lines.push(`                return ms`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        if let raw = ProcessInfo.processInfo.environment["SDK_TIMEOUT_SEC"] {`);
  lines.push(`            let t = raw.trimmingCharacters(in: .whitespacesAndNewlines)`);
  lines.push(`            if let sec = Int(t), sec > 0 {`);
  lines.push(`                return sec * 1000`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        return 10000`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private static func envRequestId() -> String {`);
  lines.push(`        let v = ProcessInfo.processInfo.environment["SDK_REQUEST_ID"] ?? ""`);
  lines.push(`        return v.trimmingCharacters(in: .whitespacesAndNewlines)`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private static func envIdempotencyKey() -> String {`);
  lines.push(`        let v = ProcessInfo.processInfo.environment["SDK_IDEMPOTENCY_KEY"] ?? ""`);
  lines.push(`        return v.trimmingCharacters(in: .whitespacesAndNewlines)`);
  lines.push(`    }`);
  lines.push(``);
  if (auth.any) {
    lines.push(`    private static func envAuth(_ name: String) -> String {`);
    lines.push(`        let v = ProcessInfo.processInfo.environment[name] ?? ""`);
    lines.push(`        return v.trimmingCharacters(in: .whitespacesAndNewlines)`);
    lines.push(`    }`);
    lines.push(``);
  }
  lines.push(`    private static func retryDelayMs(_ response: URLResponse?, _ attempt: Int) -> Int {`);
  lines.push(`        if let http = response as? HTTPURLResponse {`);
  lines.push(`            if let raw = http.value(forHTTPHeaderField: "Retry-After") {`);
  lines.push(`                let t = raw.trimmingCharacters(in: .whitespacesAndNewlines)`);
  lines.push(`                if let sec = Double(t), sec >= 0, sec < 30 {`);
  lines.push(`                    return Int(sec * 1000.0)`);
  lines.push(`                }`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        return 100 * (1 << attempt)`);
  lines.push(`    }`);
  lines.push(``);
  const reqSig = auth.any
    ? `    private func doRequest(method: String, path: String, body: [String: Any]?, authBearer: Bool, authHeaders: [String]?, authQuery: [String]?) throws -> Any? {`
    : `    private func doRequest(method: String, path: String, body: [String: Any]?) throws -> Any? {`;
  lines.push(reqSig);
  lines.push(`        let timeout = self.timeoutMs > 0 ? self.timeoutMs : Client.envTimeoutMs()`);
  lines.push(`        var opIdem = ""`);
  lines.push(`        let mth = method.uppercased()`);
  lines.push(`        if mth == "POST" || mth == "PUT" || mth == "PATCH" || mth == "DELETE" {`);
  lines.push(`            opIdem = self.idempotencyKey.trimmingCharacters(in: .whitespacesAndNewlines)`);
  lines.push(`            if opIdem.isEmpty { opIdem = Client.envIdempotencyKey() }`);
  lines.push(`            if opIdem.isEmpty { opIdem = UUID().uuidString }`);
  lines.push(`        }`);
  lines.push(`        var lastError: Error?`);
  lines.push(`        for attempt in 0..<3 {`);
  lines.push(`            do {`);
  lines.push(`                var reqPath = path`);
  if (auth.queryKeys.length) {
    lines.push(`                if let authQuery = authQuery {`);
    lines.push(`                    let key = self.apiKey.trimmingCharacters(in: .whitespacesAndNewlines)`);
    lines.push(`                    if !key.isEmpty {`);
    lines.push(`                        for q in authQuery {`);
    lines.push(`                            if q.isEmpty { continue }`);
    lines.push(`                            reqPath += (reqPath.contains("?") ? "&" : "?") + urlEncode(q) + "=" + urlEncode(key)`);
    lines.push(`                        }`);
    lines.push(`                    }`);
    lines.push(`                }`);
  }
  lines.push(`                guard let url = URL(string: self.baseUrl + reqPath) else {`);
  lines.push(`                    throw NSError(domain: "Client", code: 1, userInfo: [NSLocalizedDescriptionKey: "invalid URL"])`);
  lines.push(`                }`);
  lines.push(`                var req = URLRequest(url: url)`);
  lines.push(`                req.httpMethod = method`);
  lines.push(`                req.timeoutInterval = TimeInterval(Double(timeout) / 1000.0)`);
  lines.push(`                if req.value(forHTTPHeaderField: "User-Agent") == nil {`);
  lines.push(`                    let ua = self.userAgent.trimmingCharacters(in: .whitespacesAndNewlines)`);
  lines.push(`                    req.setValue(ua.isEmpty ? ${JSON.stringify(defaultUserAgent(opts))} : ua, forHTTPHeaderField: "User-Agent")`);
  lines.push(`                }`);
  lines.push(`                if req.value(forHTTPHeaderField: "X-Request-Id") == nil {`);
  lines.push(`                    var rid = self.requestId.trimmingCharacters(in: .whitespacesAndNewlines)`);
  lines.push(`                    if rid.isEmpty { rid = Client.envRequestId() }`);
  lines.push(`                    if rid.isEmpty { rid = UUID().uuidString }`);
  lines.push(`                    req.setValue(rid, forHTTPHeaderField: "X-Request-Id")`);
  lines.push(`                }`);
  lines.push(`                if !opIdem.isEmpty && req.value(forHTTPHeaderField: "Idempotency-Key") == nil {`);
  lines.push(`                    req.setValue(opIdem, forHTTPHeaderField: "Idempotency-Key")`);
  lines.push(`                }`);
  if (auth.hasBearer) {
    lines.push(`                if authBearer {`);
    lines.push(`                    let tok = self.bearerToken.trimmingCharacters(in: .whitespacesAndNewlines)`);
    lines.push(`                    if !tok.isEmpty {`);
    lines.push(`                        req.setValue("Bearer " + tok, forHTTPHeaderField: "Authorization")`);
    lines.push(`                    }`);
    lines.push(`                }`);
  }
  if (auth.headerKeys.length) {
    lines.push(`                if let authHeaders = authHeaders {`);
    lines.push(`                    let key = self.apiKey.trimmingCharacters(in: .whitespacesAndNewlines)`);
    lines.push(`                    if !key.isEmpty {`);
    lines.push(`                        for h in authHeaders {`);
    lines.push(`                            if !h.isEmpty {`);
    lines.push(`                                req.setValue(key, forHTTPHeaderField: h)`);
    lines.push(`                            }`);
    lines.push(`                        }`);
    lines.push(`                    }`);
    lines.push(`                }`);
  }
  lines.push(`                if let body = body {`);
  lines.push(`                    req.httpBody = try JSONSerialization.data(withJSONObject: body, options: [])`);
  lines.push(`                    req.setValue("application/json", forHTTPHeaderField: "Content-Type")`);
  lines.push(`                }`);
  lines.push(`                var resultData: Data?`);
  lines.push(`                var resultResponse: URLResponse?`);
  lines.push(`                var resultError: Error?`);
  lines.push(`                let sem = DispatchSemaphore(value: 0)`);
  lines.push(`                let task = self.session.dataTask(with: req) { data, response, error in`);
  lines.push(`                    resultData = data`);
  lines.push(`                    resultResponse = response`);
  lines.push(`                    resultError = error`);
  lines.push(`                    sem.signal()`);
  lines.push(`                }`);
  lines.push(`                task.resume()`);
  lines.push(`                sem.wait()`);
  lines.push(`                if let resultError = resultError {`);
  lines.push(`                    throw resultError`);
  lines.push(`                }`);
  lines.push(`                let code = (resultResponse as? HTTPURLResponse)?.statusCode ?? 0`);
  lines.push(`                if code >= 200 && code < 300 {`);
  lines.push(`                    if let resultData = resultData, resultData.count > 0 {`);
  lines.push(`                        return try JSONSerialization.jsonObject(with: resultData, options: [])`);
  lines.push(`                    }`);
  lines.push(`                    return nil`);
  lines.push(`                }`);
  lines.push(`                if (code == 429 || code >= 500) && attempt < 2 {`);
  lines.push(`                    let delay = Client.retryDelayMs(resultResponse, attempt)`);
  lines.push(`                    Thread.sleep(forTimeInterval: Double(delay) / 1000.0)`);
  lines.push(`                    continue`);
  lines.push(`                }`);
  lines.push(`                throw NSError(domain: "Client", code: code, userInfo: [NSLocalizedDescriptionKey: method + " " + path + " -> " + String(code)])`);
  lines.push(`            } catch let e as NSError {`);
  lines.push(`                if e.domain == "Client" {`);
  lines.push(`                    throw e`);
  lines.push(`                }`);
  lines.push(`                lastError = e`);
  lines.push(`                if attempt >= 2 {`);
  lines.push(`                    throw e`);
  lines.push(`                }`);
  lines.push(`                Thread.sleep(forTimeInterval: Double(100 * (1 << attempt)) / 1000.0)`);
  lines.push(`            }`);
  lines.push(`        }`);
  lines.push(`        if let lastError = lastError {`);
  lines.push(`            throw lastError`);
  lines.push(`        }`);
  lines.push(`        throw NSError(domain: "Client", code: 0, userInfo: [NSLocalizedDescriptionKey: method + " " + path + " -> network"])`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private func urlEncode(_ s: String) -> String {`);
  lines.push(`        var allowed = CharacterSet.alphanumerics`);
  lines.push(`        allowed.insert(charactersIn: "-._~")`);
  lines.push(`        return s.addingPercentEncoding(withAllowedCharacters: allowed) ?? s`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private func expandPath(_ pathTpl: String, rest: inout [String: Any]) -> String {`);
  lines.push(`        var out = pathTpl`);
  lines.push(`        while true {`);
  lines.push(`            guard let startRange = out.range(of: "{") else { break }`);
  lines.push(`            guard let endRange = out.range(of: "}", range: startRange.upperBound..<out.endIndex) else { break }`);
  lines.push(`            let key = String(out[startRange.upperBound..<endRange.lowerBound])`);
  lines.push(`            let val = rest.removeValue(forKey: key)`);
  lines.push(`            var repl = ""`);
  lines.push(`            if let val = val {`);
  lines.push(`                repl = urlEncode(String(describing: val))`);
  lines.push(`            }`);
  lines.push(`            out.replaceSubrange(startRange.lowerBound..<endRange.upperBound, with: repl)`);
  lines.push(`        }`);
  lines.push(`        return out`);
  lines.push(`    }`);
  lines.push(``);
  lines.push(`    private func queryString(_ rest: [String: Any]) -> String {`);
  lines.push(`        var parts: [String] = []`);
  lines.push(`        for (k, v) in rest {`);
  lines.push(`            parts.append(urlEncode(k) + "=" + urlEncode(String(describing: v)))`);
  lines.push(`        }`);
  lines.push(`        if parts.isEmpty {`);
  lines.push(`            return ""`);
  lines.push(`        }`);
  lines.push(`        return "?" + parts.joined(separator: "&")`);
  lines.push(`    }`);
  lines.push(``);

  for (const op of ops) {
    const fn = toSwiftIdent(op.operationId);
    const authSuf = swiftAuthArgs(op, auth.any);
    const summary = String(op.summary || `${op.method} ${op.path}`)
      .replace(/\*\//g, "* /")
      .replace(/\r?\n/g, " ");
    lines.push(`    /// ${fn} ${summary} (operationId: ${op.operationId})`);
    lines.push(`    public func ${fn}(_ args: [String: Any]? = nil) throws -> Any? {`);
    lines.push(`        var rest: [String: Any] = args ?? [:]`);
    lines.push(`        let path = expandPath(${JSON.stringify(op.path)}, rest: &rest)`);
    if (op.method === "GET" || op.method === "DELETE") {
      lines.push(`        return try doRequest(method: ${JSON.stringify(op.method)}, path: path + queryString(rest), body: nil` + authSuf + `)`);
    } else {
      lines.push(`        return try doRequest(method: ${JSON.stringify(op.method)}, path: path, body: rest` + authSuf + `)`);
    }
    lines.push(`    }`);
    lines.push(``);
  }

  lines.push(`}`);
  lines.push(``);
  return lines.join("\n");
}

const RUBY_KEYWORDS = new Set([
  "BEGIN", "END", "alias", "and", "begin", "break", "case", "class", "def",
  "defined?", "do", "else", "elsif", "end", "ensure", "false", "for", "if",
  "in", "module", "next", "nil", "not", "or", "redo", "rescue", "retry",
  "return", "self", "super", "then", "true", "undef", "unless", "until",
  "when", "while", "yield", "__FILE__", "__LINE__", "__ENCODING__",
]);

export function toRubyIdent(name) {
  let cleaned = String(name || "op").replace(/[^a-zA-Z0-9_]/g, "_");
  if (!cleaned) return "op";
  let snake = cleaned
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1_$2")
    .toLowerCase();
  snake = snake.replace(/_+/g, "_").replace(/^_+|_+$/g, "");
  if (!snake) return "op";
  if (/^[0-9]/.test(snake)) snake = "op_" + snake;
  if (RUBY_KEYWORDS.has(snake) || snake === "initialize") return snake + "_";
  return snake;
}

/**
 * Minimal Ruby HTTP client stub (stdlib Net::HTTP).
 * Single file: `ruby -c client.rb` (no gems / httparty / faraday).
 * `class Client` with one public method per OpenAPI operation (snake_case).
 */
export function generateRubyClient(ops, title = "GeneratedClient", opts = {}) {
  const pkg = pkgFromOpts(opts);
  const safeTitle = String(title || "GeneratedClient").replace(/\r?\n/g, " ");
  const auth = authFlags(ops);
  const lines = [];
  lines.push(`# Auto-generated by sdk-mcp-gen — do not edit by hand`);
  lines.push(`# API: ${safeTitle}`);
  lines.push(`# gem: ${pkg.ident}`);
  lines.push(`require "net/http"`);
  lines.push(`require "uri"`);
  lines.push(`require "json"`);
  lines.push(`require "time"`);
  lines.push(`require "securerandom"`);
  lines.push(``);
  lines.push(`# Minimal HTTP client stub generated from OpenAPI (stdlib Net::HTTP).`);
  lines.push(`# Retry transient HTTP failures (429 / 5xx / network): max 2 retries, ~100ms exponential backoff, honor Retry-After <30s.`);
  lines.push(`# Per-attempt request timeout (default 10s): open/read timeout. Override via timeout_ms or env SDK_TIMEOUT_MS / SDK_TIMEOUT_SEC.`);
  lines.push(`# Default User-Agent ${JSON.stringify(defaultUserAgent(opts))} unless already set. X-Request-Id new per attempt; pin via request_id or env SDK_REQUEST_ID.`);
  lines.push(`# Idempotency-Key on POST/PUT/PATCH/DELETE when unset; new per logical call (retries reuse). Pin via idempotency_key or env SDK_IDEMPOTENCY_KEY.`);
  if (auth.any) {
    lines.push(`# Auth from OpenAPI securitySchemes (http bearer, apiKey header/query). oauth2 / openIdConnect skipped (no fake tokens).`);
    lines.push(`# Set bearer_token / api_key or env SDK_BEARER_TOKEN / SDK_API_KEY. Attached per OpenAPI operation security on every attempt. Ops without security omit credentials. Values never logged.`);
  }
  lines.push(`class Client`);
  lines.push(`  attr_accessor :timeout_ms`);
  lines.push(`  attr_accessor :user_agent`);
  lines.push(`  attr_accessor :request_id`);
  lines.push(`  attr_accessor :idempotency_key`);
  if (auth.hasBearer) {
    lines.push(`  attr_accessor :bearer_token`);
  }
  if (auth.headerKeys.length || auth.queryKeys.length) {
    lines.push(`  attr_accessor :api_key`);
  }
  lines.push(`  def initialize(base_url = "")`);
  lines.push(`    s = (base_url || "").to_s`);
  lines.push(`    s = s.sub(%r{/+\\z}, "")`);
  lines.push(`    @base_url = s`);
  lines.push(`    @timeout_ms = self.class.env_timeout_ms`);
  lines.push(`    @user_agent = ${JSON.stringify(defaultUserAgent(opts))}`);
  lines.push(`    @request_id = self.class.env_request_id`);
  lines.push(`    @idempotency_key = self.class.env_idempotency_key`);
  if (auth.hasBearer) {
    lines.push(`    @bearer_token = self.class.env_auth("SDK_BEARER_TOKEN")`);
  }
  if (auth.headerKeys.length || auth.queryKeys.length) {
    lines.push(`    @api_key = self.class.env_auth("SDK_API_KEY")`);
  }
  lines.push(`  end`);
  lines.push(``);

  for (const op of ops) {
    const fn = toRubyIdent(op.operationId);
    const authSuf = rubyAuthArgs(op, auth.any);
    const summary = String(op.summary || `${op.method} ${op.path}`)
      .replace(/\r?\n/g, " ")
      .replace(/#/g, "");
    lines.push(`  # ${fn} ${summary} (operationId: ${op.operationId})`);
    lines.push(`  def ${fn}(args = nil)`);
    lines.push(`    rest = {}`);
    lines.push(`    (args || {}).each { |k, v| rest[k.to_s] = v }`);
    lines.push(`    path = expand_path(${JSON.stringify(op.path)}, rest)`);
    if (op.method === "GET" || op.method === "DELETE") {
      lines.push(`    request(${JSON.stringify(op.method)}, path + query_string(rest), nil` + authSuf + `)`);
    } else {
      lines.push(`    request(${JSON.stringify(op.method)}, path, rest` + authSuf + `)`);
    }
    lines.push(`  end`);
    lines.push(``);
  }

  lines.push(`  private`);
  lines.push(``);
  lines.push(`  def self.env_timeout_ms`);
  lines.push(`    raw_ms = ENV["SDK_TIMEOUT_MS"]`);
  lines.push(`    if raw_ms && !raw_ms.to_s.strip.empty?`);
  lines.push(`      ms = raw_ms.to_s.strip.to_i`);
  lines.push(`      return ms if ms > 0`);
  lines.push(`    end`);
  lines.push(`    raw_sec = ENV["SDK_TIMEOUT_SEC"]`);
  lines.push(`    if raw_sec && !raw_sec.to_s.strip.empty?`);
  lines.push(`      sec = raw_sec.to_s.strip.to_i`);
  lines.push(`      return sec * 1000 if sec > 0`);
  lines.push(`    end`);
  lines.push(`    10000`);
  lines.push(`  end`);
  lines.push(``);
  lines.push(`  def self.env_request_id`);
  lines.push(`    v = ENV["SDK_REQUEST_ID"]`);
  lines.push(`    return "" if v.nil?`);
  lines.push(`    v.to_s.strip`);
  lines.push(`  end`);
  lines.push(``);
  lines.push(`  def self.env_idempotency_key`);
  lines.push(`    v = ENV["SDK_IDEMPOTENCY_KEY"]`);
  lines.push(`    return "" if v.nil?`);
  lines.push(`    v.to_s.strip`);
  lines.push(`  end`);
  lines.push(``);
  if (auth.any) {
    lines.push(`  def self.env_auth(name)`);
    lines.push(`    v = ENV[name]`);
    lines.push(`    return "" if v.nil?`);
    lines.push(`    v.to_s.strip`);
    lines.push(`  end`);
    lines.push(``);
  }
  lines.push(`  def retry_delay_s(res, attempt)`);
  lines.push(`    raw = res && res["Retry-After"]`);
  lines.push(`    if raw && !raw.to_s.strip.empty?`);
  lines.push(`      t = raw.to_s.strip`);
  lines.push(`      begin`);
  lines.push(`        sec = Float(t)`);
  lines.push(`        return sec if sec >= 0 && sec < 30`);
  lines.push(`      rescue ArgumentError`);
  lines.push(`        begin`);
  lines.push(`          when_t = Time.httpdate(t)`);
  lines.push(`          delta = when_t - Time.now`);
  lines.push(`          return delta if delta >= 0 && delta < 30`);
  lines.push(`        rescue ArgumentError`);
  lines.push(`        end`);
  lines.push(`      end`);
  lines.push(`    end`);
  lines.push(`    0.1 * (2 ** attempt)`);
  lines.push(`  end`);
  lines.push(``);
  const reqSig = auth.any
    ? `  def request(method, path, body = nil, auth_bearer = false, auth_headers = nil, auth_query = nil)`
    : `  def request(method, path, body = nil)`;
  lines.push(reqSig);
  lines.push(`    timeout = (@timeout_ms && @timeout_ms.to_i > 0) ? @timeout_ms.to_i : self.class.env_timeout_ms`);
  lines.push(`    timeout_s = timeout / 1000.0`);
  lines.push(`    op_idem = ""`);
  lines.push(`    mth = method.to_s.upcase`);
  lines.push(`    if ["POST", "PUT", "PATCH", "DELETE"].include?(mth)`);
  lines.push(`      op_idem = @idempotency_key.to_s.strip`);
  lines.push(`      op_idem = self.class.env_idempotency_key if op_idem.empty?`);
  lines.push(`      op_idem = SecureRandom.uuid if op_idem.empty?`);
  lines.push(`    end`);
  lines.push(`    last = nil`);
  lines.push(`    3.times do |attempt|`);
  lines.push(`      begin`);
  lines.push(`        req_path = path`);
  if (auth.queryKeys.length) {
    lines.push(`        if auth_query && @api_key && !@api_key.to_s.strip.empty?`);
    lines.push(`          key = @api_key.to_s.strip`);
    lines.push(`          auth_query.each do |q|`);
    lines.push(`            next if q.nil? || q.to_s.empty?`);
    lines.push(`            req_path = req_path + (req_path.include?("?") ? "&" : "?") + URI.encode_www_form_component(q.to_s) + "=" + URI.encode_www_form_component(key)`);
    lines.push(`          end`);
    lines.push(`        end`);
  }
  lines.push(`        uri = URI.parse(@base_url.to_s + req_path)`);
  lines.push(`        klass = {`);
  lines.push(`          "GET" => Net::HTTP::Get,`);
  lines.push(`          "POST" => Net::HTTP::Post,`);
  lines.push(`          "PUT" => Net::HTTP::Put,`);
  lines.push(`          "PATCH" => Net::HTTP::Patch,`);
  lines.push(`          "DELETE" => Net::HTTP::Delete,`);
  lines.push(`        }[method]`);
  lines.push(`        raise "unsupported HTTP method: " + method.to_s if klass.nil?`);
  lines.push(`        req = klass.new(uri.request_uri)`);
  lines.push(`        if req["User-Agent"].to_s.empty?`);
  lines.push(`          ua = @user_agent.to_s.strip`);
  lines.push(`          req["User-Agent"] = ua.empty? ? ${JSON.stringify(defaultUserAgent(opts))} : ua`);
  lines.push(`        end`);
  lines.push(`        if req["X-Request-Id"].to_s.empty?`);
  lines.push(`          rid = @request_id.to_s.strip`);
  lines.push(`          rid = self.class.env_request_id if rid.empty?`);
  lines.push(`          rid = SecureRandom.uuid if rid.empty?`);
  lines.push(`          req["X-Request-Id"] = rid`);
  lines.push(`        end`);
  lines.push(`        if !op_idem.to_s.empty? && req["Idempotency-Key"].to_s.empty?`);
  lines.push(`          req["Idempotency-Key"] = op_idem`);
  lines.push(`        end`);
  if (auth.hasBearer) {
    lines.push(`        if auth_bearer && @bearer_token && !@bearer_token.to_s.strip.empty?`);
    lines.push(`          req["Authorization"] = "Bearer " + @bearer_token.to_s.strip`);
    lines.push(`        end`);
  }
  if (auth.headerKeys.length) {
    lines.push(`        if auth_headers && @api_key && !@api_key.to_s.strip.empty?`);
    lines.push(`          key = @api_key.to_s.strip`);
    lines.push(`          auth_headers.each do |h|`);
    lines.push(`            req[h] = key if h && !h.to_s.empty?`);
    lines.push(`          end`);
    lines.push(`        end`);
  }
  lines.push(`        unless body.nil?`);
  lines.push(`          req.body = JSON.generate(body)`);
  lines.push(`          req["Content-Type"] = "application/json"`);
  lines.push(`        end`);
  lines.push(`        http = Net::HTTP.new(uri.host, uri.port)`);
  lines.push(`        http.use_ssl = (uri.scheme == "https")`);
  lines.push(`        http.open_timeout = timeout_s`);
  lines.push(`        http.read_timeout = timeout_s`);
  lines.push(`        res = http.request(req)`);
  lines.push(`        code = res.code.to_i`);
  lines.push(`        if code >= 200 && code < 300`);
  lines.push(`          text = res.body.to_s`);
  lines.push(`          return nil if text.empty?`);
  lines.push(`          return JSON.parse(text)`);
  lines.push(`        end`);
  lines.push(`        if (code == 429 || code >= 500) && attempt < 2`);
  lines.push(`          sleep(retry_delay_s(res, attempt))`);
  lines.push(`          next`);
  lines.push(`        end`);
  lines.push(`        raise method.to_s + " " + path.to_s + " -> " + code.to_s`);
  lines.push(`      rescue Timeout::Error, Errno::ECONNREFUSED, Errno::ECONNRESET, Errno::ETIMEDOUT, Errno::EHOSTUNREACH, SocketError, EOFError => e`);
  lines.push(`        last = e`);
  lines.push(`        raise e if attempt >= 2`);
  lines.push(`        sleep(0.1 * (2 ** attempt))`);
  lines.push(`      end`);
  lines.push(`    end`);
  lines.push(`    raise last if last`);
  lines.push(`    raise method.to_s + " " + path.to_s + " -> network"`);
  lines.push(`  end`);
  lines.push(``);
  lines.push(`  def expand_path(path_tpl, rest)`);
  lines.push(`    out = path_tpl.dup`);
  lines.push(`    loop do`);
  lines.push(`      start = out.index("{")`);
  lines.push(`      break unless start`);
  lines.push(`      finish = out.index("}", start)`);
  lines.push(`      break unless finish`);
  lines.push(`      key = out[start + 1...finish]`);
  lines.push(`      val = rest.delete(key)`);
  lines.push(`      repl = val.nil? ? "" : URI.encode_www_form_component(val.to_s)`);
  lines.push(`      out = out[0...start] + repl + out[finish + 1..-1]`);
  lines.push(`    end`);
  lines.push(`    out`);
  lines.push(`  end`);
  lines.push(``);
  lines.push(`  def query_string(rest)`);
  lines.push(`    parts = []`);
  lines.push(`    rest.each do |k, v|`);
  lines.push(`      next if v.nil?`);
  lines.push(`      parts << (URI.encode_www_form_component(k.to_s) + "=" + URI.encode_www_form_component(v.to_s))`);
  lines.push(`    end`);
  lines.push(`    parts.empty? ? "" : "?" + parts.join("&")`);
  lines.push(`  end`);
  lines.push(`end`);
  lines.push(``);
  return lines.join("\n");
}

const PHP_KEYWORDS = new Set([
  "abstract", "and", "array", "as", "break", "callable", "case", "catch", "class",
  "clone", "const", "continue", "declare", "default", "die", "do", "echo", "else",
  "elseif", "empty", "enddeclare", "endfor", "endforeach", "endif", "endswitch",
  "endwhile", "eval", "exit", "extends", "final", "finally", "fn", "for", "foreach",
  "function", "global", "goto", "if", "implements", "include", "include_once",
  "instanceof", "insteadof", "interface", "isset", "list", "match", "namespace",
  "new", "or", "print", "private", "protected", "public", "readonly", "require",
  "require_once", "return", "static", "switch", "throw", "trait", "try", "unset",
  "use", "var", "while", "xor", "yield", "true", "false", "null", "self", "parent",
  "__halt_compiler", "enum",
]);

export function toPhpIdent(name) {
  let cleaned = String(name || "op").replace(/[^a-zA-Z0-9_]/g, "_");
  if (!cleaned) return "op";
  if (cleaned.includes("_")) {
    cleaned = cleaned.replace(/_([a-zA-Z0-9])/g, (_, c) => c.toUpperCase());
  }
  if (/^[0-9]/.test(cleaned)) cleaned = "op" + cleaned;
  if (PHP_KEYWORDS.has(cleaned.toLowerCase()) || cleaned === "__construct") return cleaned + "_";
  return cleaned;
}

function phpQuote(s) {
  return "'" + String(s).replace(/\\/g, "\\\\").replace(/'/g, "\\'") + "'";
}

/**
 * Minimal PHP HTTP client stub (stdlib fopen / stream wrappers; curl-extension-free).
 * Single file: `php -l Client.php`.
 * `class Client` with one public method per OpenAPI operation (camelCase).
 */
export function generatePhpClient(ops, title = "GeneratedClient", opts = {}) {
  const pkg = pkgFromOpts(opts);
  const safeTitle = String(title || "GeneratedClient").replace(/\r?\n/g, " ").replace(/\*\//g, "* /");
  const auth = authFlags(ops);
  const lines = [];
  lines.push("<?php");
  lines.push("// Auto-generated by sdk-mcp-gen — do not edit by hand");
  lines.push("// API: " + safeTitle);
  if (pkg.customized) {
    lines.push("namespace " + pkg.pascal + ";");
  }
  lines.push("");
  lines.push("/**");
  lines.push(" * Minimal HTTP client stub generated from OpenAPI (stdlib fopen / stream wrappers; curl-extension-free).");
  lines.push(" * Retry 429 / 5xx / network (Retry-After <30s). Per-attempt timeout default 10s (timeoutMs / SDK_TIMEOUT_MS / SDK_TIMEOUT_SEC).");
  lines.push(" * Default User-Agent " + defaultUserAgent(opts) + " unless already set. X-Request-Id new per attempt; pin via requestId or env SDK_REQUEST_ID.");
  lines.push(" * Idempotency-Key on POST/PUT/PATCH/DELETE when unset; new per logical call (retries reuse). Pin via idempotencyKey or env SDK_IDEMPOTENCY_KEY.");
  if (auth.any) {
    lines.push(" * Auth: bearerToken / apiKey or env SDK_BEARER_TOKEN / SDK_API_KEY. Per-op security; unsecured ops omit credentials. Values never logged.");
  }
  lines.push(" */");
  lines.push("class Client {");
  lines.push("    private $baseUrl;");
  lines.push("    public $timeoutMs;");
  lines.push("    public $userAgent;");
  lines.push("    public $requestId;");
  lines.push("    public $idempotencyKey;");
  if (auth.hasBearer) {
    lines.push("    public $bearerToken;");
  }
  if (auth.headerKeys.length || auth.queryKeys.length) {
    lines.push("    public $apiKey;");
  }
  lines.push("");
  lines.push("    public function __construct($baseUrl = \"\") {");
  lines.push("        $s = $baseUrl === null ? \"\" : (string) $baseUrl;");
  lines.push("        $this->baseUrl = rtrim($s, \"/\");");
  lines.push("        $this->timeoutMs = self::envTimeoutMs();");
  lines.push("        $this->userAgent = " + JSON.stringify(defaultUserAgent(opts)) + ";");
  lines.push("        $this->requestId = self::envRequestId();");
  lines.push("        $this->idempotencyKey = self::envIdempotencyKey();");
  if (auth.hasBearer) {
    lines.push("        $this->bearerToken = self::envAuth(\"SDK_BEARER_TOKEN\");");
  }
  if (auth.headerKeys.length || auth.queryKeys.length) {
    lines.push("        $this->apiKey = self::envAuth(\"SDK_API_KEY\");");
  }
  lines.push("    }");
  lines.push("");
  lines.push("    private static function envTimeoutMs() {");
  lines.push("        $rawMs = getenv(\"SDK_TIMEOUT_MS\");");
  lines.push("        if ($rawMs !== false && trim((string) $rawMs) !== \"\") {");
  lines.push("            $ms = intval(trim((string) $rawMs));");
  lines.push("            if ($ms > 0) {");
  lines.push("                return $ms;");
  lines.push("            }");
  lines.push("        }");
  lines.push("        $rawSec = getenv(\"SDK_TIMEOUT_SEC\");");
  lines.push("        if ($rawSec !== false && trim((string) $rawSec) !== \"\") {");
  lines.push("            $sec = intval(trim((string) $rawSec));");
  lines.push("            if ($sec > 0) {");
  lines.push("                return $sec * 1000;");
  lines.push("            }");
  lines.push("        }");
  lines.push("        return 10000;");
  lines.push("    }");
  lines.push("");
  lines.push("    private static function envRequestId() {");
  lines.push("        $v = getenv(\"SDK_REQUEST_ID\");");
  lines.push("        if ($v === false) {");
  lines.push("            return \"\";");
  lines.push("        }");
  lines.push("        return trim((string) $v);");
  lines.push("    }");
  lines.push("");
  lines.push("    private static function envIdempotencyKey() {");
  lines.push("        $v = getenv(\"SDK_IDEMPOTENCY_KEY\");");
  lines.push("        if ($v === false) {");
  lines.push("            return \"\";");
  lines.push("        }");
  lines.push("        return trim((string) $v);");
  lines.push("    }");
  lines.push("");
  if (auth.any) {
    lines.push("    private static function envAuth($name) {");
    lines.push("        $v = getenv($name);");
    lines.push("        if ($v === false) {");
    lines.push("            return \"\";");
    lines.push("        }");
    lines.push("        return trim((string) $v);");
    lines.push("    }");
    lines.push("");
  }
  lines.push("    private static function retryDelayMs($wrapperData, $attempt) {");
  lines.push("        $raw = null;");
  lines.push("        if (is_array($wrapperData)) {");
  lines.push("            foreach ($wrapperData as $line) {");
  lines.push("                if (is_string($line) && stripos($line, \"Retry-After:\") === 0) {");
  lines.push("                    $raw = trim(substr($line, 12));");
  lines.push("                }");
  lines.push("            }");
  lines.push("        }");
  lines.push("        if ($raw !== null && $raw !== \"\") {");
  lines.push("            if (is_numeric($raw)) {");
  lines.push("                $sec = floatval($raw);");
  lines.push("                if ($sec >= 0 && $sec < 30) {");
  lines.push("                    return (int) ($sec * 1000);");
  lines.push("                }");
  lines.push("            }");
  lines.push("            $when = strtotime($raw);");
  lines.push("            if ($when !== false) {");
  lines.push("                $delta = ($when - time()) * 1000;");
  lines.push("                if ($delta >= 0 && $delta < 30000) {");
  lines.push("                    return (int) $delta;");
  lines.push("                }");
  lines.push("            }");
  lines.push("        }");
  lines.push("        return 100 * (1 << $attempt);");
  lines.push("    }");
  lines.push("");

  for (const op of ops) {
    const fn = toPhpIdent(op.operationId);
    const authSuf = phpAuthArgs(op, auth.any);
    const summary = String(op.summary || `${op.method} ${op.path}`)
      .replace(/\r?\n/g, " ")
      .replace(/\*\//g, "* /");
    lines.push("    /** " + fn + " " + summary + " (operationId: " + op.operationId + ") */");
    lines.push("    public function " + fn + "($args = null) {");
    lines.push("        $rest = array();");
    lines.push("        if (is_array($args)) {");
    lines.push("            foreach ($args as $k => $v) {");
    lines.push("                $rest[(string) $k] = $v;");
    lines.push("            }");
    lines.push("        }");
    lines.push("        $path = $this->expandPath(" + phpQuote(op.path) + ", $rest);");
    if (op.method === "GET" || op.method === "DELETE") {
      lines.push("        return $this->request(" + phpQuote(op.method) + ", $path . $this->queryString($rest), null" + authSuf + ");");
    } else {
      lines.push("        return $this->request(" + phpQuote(op.method) + ", $path, $rest" + authSuf + ");");
    }
    lines.push("    }");
    lines.push("");
  }

  const reqSig = auth.any
    ? "    private function request($method, $path, $body = null, $authBearer = false, $authHeaders = null, $authQuery = null) {"
    : "    private function request($method, $path, $body = null) {";
  lines.push(reqSig);
  lines.push("        $timeout = $this->timeoutMs > 0 ? $this->timeoutMs : self::envTimeoutMs();");
  lines.push("        $timeoutSec = $timeout / 1000.0;");
  lines.push("        $opIdem = \"\";");
  lines.push("        $mth = strtoupper((string) $method);");
  lines.push("        if ($mth === \"POST\" || $mth === \"PUT\" || $mth === \"PATCH\" || $mth === \"DELETE\") {");
  lines.push("            $opIdem = is_string($this->idempotencyKey) && trim($this->idempotencyKey) !== \"\" ? trim($this->idempotencyKey) : self::envIdempotencyKey();");
  lines.push("            if ($opIdem === \"\") {");
  lines.push("                $opIdem = function_exists(\"random_bytes\") ? bin2hex(random_bytes(16)) : uniqid(\"\", true);");
  lines.push("            }");
  lines.push("        }");
  lines.push("        $last = null;");
  lines.push("        for ($attempt = 0; $attempt < 3; $attempt++) {");
  lines.push("            $reqPath = $path;");
  if (auth.queryKeys.length) {
    lines.push("            if ($authQuery !== null && $this->apiKey !== null && trim((string) $this->apiKey) !== \"\") {");
    lines.push("                $key = trim((string) $this->apiKey);");
    lines.push("                foreach ($authQuery as $q) {");
    lines.push("                    if ($q === null || $q === \"\") {");
    lines.push("                        continue;");
    lines.push("                    }");
    lines.push("                    $reqPath = $reqPath . (strpos($reqPath, \"?\") !== false ? \"&\" : \"?\") . rawurlencode((string) $q) . \"=\" . rawurlencode($key);");
    lines.push("                }");
    lines.push("            }");
  }
  lines.push("            $url = $this->baseUrl . $reqPath;");
  lines.push("            $headers = \"\";");
  lines.push("            $content = \"\";");
  if (auth.hasBearer) {
    lines.push("            if ($authBearer && $this->bearerToken !== null && trim((string) $this->bearerToken) !== \"\") {");
    lines.push("                $headers .= \"Authorization: Bearer \" . trim((string) $this->bearerToken) . \"\\r\\n\";");
    lines.push("            }");
  }
  if (auth.headerKeys.length) {
    lines.push("            if ($authHeaders !== null && $this->apiKey !== null && trim((string) $this->apiKey) !== \"\") {");
    lines.push("                $key = trim((string) $this->apiKey);");
    lines.push("                foreach ($authHeaders as $h) {");
    lines.push("                    if ($h !== null && $h !== \"\") {");
    lines.push("                        $headers .= (string) $h . \": \" . $key . \"\\r\\n\";");
    lines.push("                    }");
    lines.push("                }");
    lines.push("            }");
  }
  lines.push("            if (stripos($headers, \"User-Agent:\") === false) {");
  lines.push("                $ua = is_string($this->userAgent) && trim($this->userAgent) !== \"\" ? trim($this->userAgent) : " + JSON.stringify(defaultUserAgent(opts)) + ";");
  lines.push("                $headers .= \"User-Agent: \" . $ua . \"\\r\\n\";");
  lines.push("            }");
  lines.push("            if (stripos($headers, \"X-Request-Id:\") === false) {");
  lines.push("                $rid = is_string($this->requestId) && trim($this->requestId) !== \"\" ? trim($this->requestId) : self::envRequestId();");
  lines.push("                if ($rid === \"\") {");
  lines.push("                    $rid = function_exists(\"random_bytes\") ? bin2hex(random_bytes(16)) : uniqid(\"\", true);");
  lines.push("                }");
  lines.push("                $headers .= \"X-Request-Id: \" . $rid . \"\\r\\n\";");
  lines.push("            }");
  lines.push("            if ($opIdem !== \"\" && stripos($headers, \"Idempotency-Key:\") === false) {");
  lines.push("                $headers .= \"Idempotency-Key: \" . $opIdem . \"\\r\\n\";");
  lines.push("            }");
  lines.push("            if ($body !== null) {");
  lines.push("                $content = json_encode($body);");
  lines.push("                $headers .= \"Content-Type: application/json\\r\\n\";");
  lines.push("            }");
  lines.push("            $opts = array(");
  lines.push("                \"http\" => array(");
  lines.push("                    \"method\" => strtoupper((string) $method),");
  lines.push("                    \"header\" => $headers,");
  lines.push("                    \"content\" => $content,");
  lines.push("                    \"ignore_errors\" => true,");
  lines.push("                    \"timeout\" => $timeoutSec,");
  lines.push("                    \"follow_location\" => 1,");
  lines.push("                ),");
  lines.push("            );");
  lines.push("            $ctx = stream_context_create($opts);");
  lines.push("            $fp = @fopen($url, \"rb\", false, $ctx);");
  lines.push("            if ($fp === false) {");
  lines.push("                $last = new Exception((string) $method . \" \" . (string) $path . \" -> open failed\");");
  lines.push("                if ($attempt >= 2) {");
  lines.push("                    throw $last;");
  lines.push("                }");
  lines.push("                usleep((100 * (1 << $attempt)) * 1000);");
  lines.push("                continue;");
  lines.push("            }");
  lines.push("            $meta = stream_get_meta_data($fp);");
  lines.push("            $text = stream_get_contents($fp);");
  lines.push("            fclose($fp);");
  lines.push("            $wrapper = isset($meta[\"wrapper_data\"]) && is_array($meta[\"wrapper_data\"]) ? $meta[\"wrapper_data\"] : array();");
  lines.push("            $code = 0;");
  lines.push("            foreach ($wrapper as $line) {");
  lines.push("                if (is_string($line) && strncmp($line, \"HTTP/\", 5) === 0) {");
  lines.push("                    $parts = explode(\" \", $line);");
  lines.push("                    if (isset($parts[1])) {");
  lines.push("                        $code = intval($parts[1]);");
  lines.push("                    }");
  lines.push("                }");
  lines.push("            }");
  lines.push("            if ($code >= 200 && $code < 300) {");
  lines.push("                if ($text === false || $text === \"\") {");
  lines.push("                    return null;");
  lines.push("                }");
  lines.push("                $decoded = json_decode($text, true);");
  lines.push("                if ($decoded === null && $text !== \"null\" && json_last_error() !== JSON_ERROR_NONE) {");
  lines.push("                    return $text;");
  lines.push("                }");
  lines.push("                return $decoded;");
  lines.push("            }");
  lines.push("            if (($code == 429 || $code >= 500) && $attempt < 2) {");
  lines.push("                usleep(self::retryDelayMs($wrapper, $attempt) * 1000);");
  lines.push("                continue;");
  lines.push("            }");
  lines.push("            throw new Exception((string) $method . \" \" . (string) $path . \" -> \" . (string) $code);");
  lines.push("        }");
  lines.push("        if ($last !== null) {");
  lines.push("            throw $last;");
  lines.push("        }");
  lines.push("        throw new Exception((string) $method . \" \" . (string) $path . \" -> network\");");
  lines.push("    }");
  lines.push("");
  lines.push("    private function expandPath($pathTpl, &$rest) {");
  lines.push("        $out = (string) $pathTpl;");
  lines.push("        while (true) {");
  lines.push("            $start = strpos($out, \"{\");");
  lines.push("            if ($start === false) {");
  lines.push("                break;");
  lines.push("            }");
  lines.push("            $finish = strpos($out, \"}\", $start);");
  lines.push("            if ($finish === false) {");
  lines.push("                break;");
  lines.push("            }");
  lines.push("            $key = substr($out, $start + 1, $finish - $start - 1);");
  lines.push("            $val = \"\";");
  lines.push("            if (array_key_exists($key, $rest)) {");
  lines.push("                $val = rawurlencode((string) $rest[$key]);");
  lines.push("                unset($rest[$key]);");
  lines.push("            }");
  lines.push("            $out = substr($out, 0, $start) . $val . substr($out, $finish + 1);");
  lines.push("        }");
  lines.push("        return $out;");
  lines.push("    }");
  lines.push("");
  lines.push("    private function queryString($rest) {");
  lines.push("        $parts = array();");
  lines.push("        foreach ($rest as $k => $v) {");
  lines.push("            if ($v === null) {");
  lines.push("                continue;");
  lines.push("            }");
  lines.push("            $parts[] = rawurlencode((string) $k) . \"=\" . rawurlencode((string) $v);");
  lines.push("        }");
  lines.push("        if (count($parts) === 0) {");
  lines.push("            return \"\";");
  lines.push("        }");
  lines.push("        return \"?\" . implode(\"&\", $parts);");
  lines.push("    }");
  lines.push("}");
  lines.push("");
  return lines.join("\n");
}

export function generateReadmeSnippet(ops, outDir, langs = ["ts", "python", "go", "java", "rust", "csharp", "kotlin", "swift", "ruby", "php"], packageName = DEFAULT_PACKAGE_NAME, opts = {}) {
  const pkg = splitPkg(packageName);
  const names = ops.map((o) => o.operationId).join(", ");
  const pageable = (ops || []).filter((o) => paginationInfo(o));
  const auth = authFlags(ops);
  const langSet = new Set(langs);
  const mcp = opts.mcp !== false;
  const mcpConfig = opts.mcpConfig;
  const files = [];
  if (langSet.has("ts")) { files.push(`- \`client.ts\` — TypeScript client stub`); files.push(`- \`package.json\` — package name \`${pkg.ident}\``); }
  if (langSet.has("python") || langSet.has("py")) {
    files.push(`- \`client.py\` — Python sync client stub (stdlib urllib)`);
  }
  if (langSet.has("go")) {
    files.push(`- \`client.go\` — Go HTTP client stub (stdlib net/http, package ${pkg.ident})`);
  }
  if (langSet.has("java")) {
    files.push(`- \`Client.java\` — Java HTTP client stub (stdlib HttpURLConnection, package ${pkg.ident}; 429/5xx retry, per-attempt timeout, per-op auth, iterate* page helpers)`);
  }
  if (langSet.has("rust") || langSet.has("rs")) {
    files.push(`- \`client.rs\` — Rust HTTP/1.1 client stub (stdlib TcpStream, http:// only; 429/5xx retry, per-attempt timeout, per-op auth)`);
  }
  if (langSet.has("csharp") || langSet.has("cs") || langSet.has("c#")) {
    files.push(`- \`Client.cs\` — C# HTTP client stub (stdlib HttpClient, namespace ${pkg.pascal}; 429/5xx retry, per-attempt timeout, per-op auth, iterate* page helpers)`);
  }
  if (langSet.has("kotlin") || langSet.has("kt")) {
    files.push(`- \`Client.kt\` — Kotlin HTTP client stub (stdlib HttpURLConnection, package ${pkg.ident}; 429/5xx retry, per-attempt timeout, per-op auth, iterate* page helpers)`);
  }
  if (langSet.has("swift")) {
    files.push(`- \`Client.swift\` — Swift HTTP client stub (Foundation URLSession, class Client; 429/5xx retry, per-attempt timeout, per-op auth)`);
  }
  if (langSet.has("ruby") || langSet.has("rb")) {
    files.push(`- \`client.rb\` — Ruby HTTP client stub (stdlib Net::HTTP, class Client; 429/5xx retry, per-attempt timeout, per-op auth)`);
  }
  if (langSet.has("php")) {
    files.push(`- \`Client.php\` — PHP HTTP client stub (stdlib fopen/stream, class Client; 429/5xx retry, per-attempt timeout, per-op auth)`);
  }
  files.push(`- \`mcp-tools.json\` — MCP tools list`);
  if (mcp) {
    files.push(`- \`mcp-server.mjs\` — stdio MCP server (JSON-RPC initialize / tools/list / tools/call; Node, no extra deps)`);
    files.push(`- \`mcp_server.py\` — stdio MCP server (same JSON-RPC; Python 3 stdlib urllib, no extra deps)`);
    files.push(`- \`mcp_server.go\` — stdio MCP server (same JSON-RPC; Go 1.21+ stdlib net/http, package main, no extra deps)`);
    files.push(`- \`mcp.json\` — MCP servers config JSON snippet (paste into Cursor / Claude Desktop / Claude Code)`);
  }
  if (opts.license !== false) {
    files.push(`- \`LICENSE\` — Apache License 2.0 (always overwritten on generate)`);
    files.push(`- \`NOTICE\` — attribution for package \`${pkg.ident}\``);
  }
  if (opts.gitignore !== false) {
    files.push(`- \`.gitignore\` — ignore __pycache__, node_modules, .DS_Store (always overwritten on generate)`);
  }
  const parts = [
    `# Generated SDK + MCP tools`,
    ``,
    `Package: ${pkg.ident}`,
    ``,
    `Operations (${ops.length}): ${names}`,
    ``,
    ...(pageable.length ? [`Page helpers: ${pageable.map((o) => iterateHelperName(o.operationId)).join(", ")} (page/cursor; cap 1000; not a full pager)`, ``] : []),
    ...(auth.any ? [`Auth: constructor bearerToken / apiKey (or bearer_token / api_key / Client.BearerToken / APIKey) or env SDK_BEARER_TOKEN / SDK_API_KEY, attached per OpenAPI operation security (optional schemes when creds are set; ops without security omit credentials). MCP servers read MCP_BEARER_TOKEN / MCP_API_KEY (same SDK_* fallback). oauth2 / openIdConnect skipped (no fake tokens). Values never logged.`, ``] : []),
    `Identity: default User-Agent ${defaultUserAgent({ packageName })} unless already set; X-Request-Id is new per HTTP attempt (pin via constructor requestId / request_id / RequestID or env SDK_REQUEST_ID). Idempotency-Key on POST/PUT/PATCH/DELETE when unset (new per logical call, retries reuse; pin via constructor idempotencyKey / idempotency_key / IdempotencyKey or env SDK_IDEMPOTENCY_KEY).`,
    ``,
    `Files:`,
    ...files,
    ``,
  ];
  if (langSet.has("ts")) {
    parts.push(
      `TypeScript example:`,
      ``,
      "```ts",
      `import { createClient } from "./client";`,
      `const client = createClient({ baseUrl: "http://localhost:8080" });`,
      ops[0] ? `await client.${ops[0].operationId}({});` : `// no ops`,
      "```",
      ``,
    );
  }
  if (langSet.has("python") || langSet.has("py")) {
    parts.push(
      `Python example:`,
      ``,
      "```python",
      `from client import create_client  # package: ${pkg.ident}`,
      `client = create_client(base_url="http://localhost:8080")`,
      ops[0] ? `client.${ops[0].operationId}({})` : `# no ops`,
      "```",
      ``,
    );
  }
  if (langSet.has("go")) {
    const goFn = ops[0] ? toGoExported(ops[0].operationId) : "Op";
    parts.push(
      `Go example:`,
      ``,
      "```go",
      `import "${pkg.modPath}"`,
      `c := ${pkg.ident}.NewClient("http://localhost:8080")`,
      ops[0] ? `c.${goFn}(map[string]any{})` : `// no ops`,
      "```",
      ``,
    );
  }
  if (langSet.has("java")) {
    const javaFn = ops[0] ? toJavaIdent(ops[0].operationId) : "op";
    parts.push(
      `Java example:`,
      ``,
      "```java",
      `import ${pkg.ident}.Client;`,
      `Client c = new Client("http://localhost:8080");`,
      ops[0] ? `c.${javaFn}(new java.util.HashMap<String, Object>());` : `// no ops`,
      "```",
      ``,
    );
  }
  if (langSet.has("rust") || langSet.has("rs")) {
    const rustFn = ops[0] ? toRustIdent(ops[0].operationId) : "op";
    parts.push(
      `Rust example:`,
      ``,
      "```rust",
      `let c = Client::new("http://localhost:8080");`,
      ops[0]
        ? `let _ = c.${rustFn}(std::collections::HashMap::new());`
        : `// no ops`,
      "```",
      ``,
    );
  }
  if (langSet.has("csharp") || langSet.has("cs") || langSet.has("c#")) {
    const csFn = ops[0] ? toCsharpIdent(ops[0].operationId) : "Op";
    parts.push(
      `C# example:`,
      ``,
      "```csharp",
      `var c = new ${pkg.pascal}.Client("http://localhost:8080");`,
      ops[0]
        ? `c.${csFn}(new System.Collections.Generic.Dictionary<string, object>());`
        : `// no ops`,
      "```",
      ``,
    );
  }
  if (langSet.has("kotlin") || langSet.has("kt")) {
    const ktFn = ops[0] ? toKotlinIdent(ops[0].operationId) : "op";
    parts.push(
      `Kotlin example:`,
      ``,
      "```kotlin",
      `val c = Client("http://localhost:8080")`,
      ops[0]
        ? `c.${ktFn}(hashMapOf())`
        : `// no ops`,
      "```",
      ``,
    );
  }
  if (langSet.has("swift")) {
    const swFn = ops[0] ? toSwiftIdent(ops[0].operationId) : "op";
    parts.push(
      `Swift example:`,
      ``,
      "```swift",
      `let c = Client("http://localhost:8080")`,
      ops[0]
        ? `_ = try c.${swFn}([:])`
        : `// no ops`,
      "```",
      ``,
    );
  }
  if (langSet.has("ruby") || langSet.has("rb")) {
    const rbFn = ops[0] ? toRubyIdent(ops[0].operationId) : "op";
    parts.push(
      `Ruby example:`,
      ``,
      "```ruby",
      `c = Client.new("http://localhost:8080")`,
      ops[0]
        ? `c.${rbFn}({})`
        : `# no ops`,
      "```",
      ``,
    );
  }
  if (langSet.has("php")) {
    const phpFn = ops[0] ? toPhpIdent(ops[0].operationId) : "op";
    parts.push(
      `PHP example:`,
      ``,
      "```php",
      `$c = new Client("http://localhost:8080");`,
      ops[0]
        ? `$c->${phpFn}([]);`
        : `// no ops`,
      "```",
      ``,
    );
  }
  if (mcp) {
    parts.push(
      `Stdio MCP server:`,
      ``,
      "```bash",
      `MCP_BASE_URL=http://localhost:8080 node mcp-server.mjs`,
      `MCP_BASE_URL=http://localhost:8080 python3 mcp_server.py`,
      `MCP_BASE_URL=http://localhost:8080 go run mcp_server.go`,
      `# newline JSON-RPC on stdin: {"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}`,
      "```",
      ``,
      `MCP servers config JSON (paste into Cursor / Claude Desktop / Claude Code).`,
      `Relative \`args\` (\`./mcp-server.mjs\`) are from this output directory. See \`mcp.json\`.`,
      ``,
      "```json",
      JSON.stringify(mcpConfig || { mcpServers: {} }, null, 2),
      "```",
      ``,
    );
  }
  if (opts.license !== false) {
    parts.push(
      `License: Apache-2.0. See \`LICENSE\` and \`NOTICE\` (overwritten on each generate).`,
      ``,
    );
  }
  if (opts.gitignore !== false) {
    parts.push(
      `A generated \`.gitignore\` excludes __pycache__, *.pyc, node_modules, .DS_Store, and *.egg-info (overwritten on each generate).`,
      ``,
    );
  }
  return parts.join("\n");
}
