/** Breaking-change check: mcp-tools.json names (+ optional client exports). */
import fs from "node:fs";
import path from "node:path";
import { toGoExported, toJavaIdent, toRustIdent, toCsharpIdent, toKotlinIdent, toSwiftIdent, toRubyIdent, toPhpIdent } from "./openapi.js";

export function loadToolNames(dir) {
  const file = path.join(dir, "mcp-tools.json");
  if (!fs.existsSync(file)) {
    throw new Error(`missing ${file}`);
  }
  const data = JSON.parse(fs.readFileSync(file, "utf8"));
  const tools = Array.isArray(data?.tools) ? data.tools : [];
  const names = [];
  for (const t of tools) {
    if (t && typeof t.name === "string" && t.name) names.push(t.name);
  }
  return names;
}

function extractTsExports(src) {
  const names = new Set();
  // async function opName( inside createClient
  for (const m of src.matchAll(/async\s+function\s*\*?\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(/g)) {
    if (m[1] !== "request") names.add(m[1]);
  }
  return names;
}

function extractPyExports(src) {
  const names = new Set();
  // def opName(self ...
  for (const m of src.matchAll(/^\s+def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(/gm)) {
    if (m[1] !== "__init__") names.add(m[1]);
  }
  return names;
}

function extractGoExports(src) {
  const names = new Set();
  for (const m of src.matchAll(/func\s+\(\s*c\s+\*Client\s*\)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(/g)) {
    names.add(m[1]);
  }
  return names;
}

function extractJavaExports(src) {
  const names = new Set();
  for (const m of src.matchAll(/public\s+Object\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(/g)) {
    names.add(m[1]);
  }
  return names;
}

function extractRustExports(src) {
  const names = new Set();
  for (const m of src.matchAll(/pub\s+fn\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:<[^>]*>)?\s*\(/g)) {
    if (m[1] !== "new") names.add(m[1]);
  }
  return names;
}

function extractCsharpExports(src) {
  const names = new Set();
  for (const m of src.matchAll(/public\s+object\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(/g)) {
    names.add(m[1]);
  }
  return names;
}

function extractKotlinExports(src) {
  const names = new Set();
  // default-visibility fun (helpers are private fun)
  for (const m of src.matchAll(/^\s*fun\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(/gm)) {
    names.add(m[1]);
  }
  return names;
}

function extractSwiftExports(src) {
  const names = new Set();
  // public func (helpers are private func; skip init)
  for (const m of src.matchAll(/public\s+func\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(/g)) {
    names.add(m[1]);
  }
  return names;
}

function extractRubyExports(src) {
  const names = new Set();
  // public instance methods (helpers after `private`; skip initialize)
  const publicPart = String(src).split(/\n\s*private\b/)[0];
  for (const m of publicPart.matchAll(/^\s+def\s+([A-Za-z_][A-Za-z0-9_?!]*)\s*(?:\(|$)/gm)) {
    if (m[1] !== "initialize") names.add(m[1]);
  }
  return names;
}

function extractPhpExports(src) {
  const names = new Set();
  for (const m of src.matchAll(/public\s+function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(/g)) {
    if (m[1] !== "__construct") names.add(m[1]);
  }
  return names;
}

export function loadClientExports(dir) {
  const result = {};
  const tsPath = path.join(dir, "client.ts");
  const pyPath = path.join(dir, "client.py");
  const goPath = path.join(dir, "client.go");
  const javaPath = path.join(dir, "Client.java");
  const rustPath = path.join(dir, "client.rs");
  const csPath = path.join(dir, "Client.cs");
  const ktPath = path.join(dir, "Client.kt");
  const swiftPath = path.join(dir, "Client.swift");
  const rubyPath = path.join(dir, "client.rb");
  const phpPath = path.join(dir, "Client.php");
  if (fs.existsSync(tsPath)) result.ts = extractTsExports(fs.readFileSync(tsPath, "utf8"));
  if (fs.existsSync(pyPath)) result.python = extractPyExports(fs.readFileSync(pyPath, "utf8"));
  if (fs.existsSync(goPath)) result.go = extractGoExports(fs.readFileSync(goPath, "utf8"));
  if (fs.existsSync(javaPath)) result.java = extractJavaExports(fs.readFileSync(javaPath, "utf8"));
  if (fs.existsSync(rustPath)) result.rust = extractRustExports(fs.readFileSync(rustPath, "utf8"));
  if (fs.existsSync(csPath)) result.csharp = extractCsharpExports(fs.readFileSync(csPath, "utf8"));
  if (fs.existsSync(ktPath)) result.kotlin = extractKotlinExports(fs.readFileSync(ktPath, "utf8"));
  if (fs.existsSync(swiftPath)) result.swift = extractSwiftExports(fs.readFileSync(swiftPath, "utf8"));
  if (fs.existsSync(rubyPath)) result.ruby = extractRubyExports(fs.readFileSync(rubyPath, "utf8"));
  if (fs.existsSync(phpPath)) result.php = extractPhpExports(fs.readFileSync(phpPath, "utf8"));
  return result;
}

function setDiff(a, b) {
  const bs = new Set(b);
  return [...a].filter((x) => !bs.has(x)).sort();
}

/**
 * Compare generated out vs baseline.
 * Breaking = baseline tool names missing from out (removed or renamed).
 * Added tools are OK.
 * When clientsPresent and checkClients, also require out clients still export
 * every baseline tool (Go uses PascalCase via toGoExported; Java via toJavaIdent; Rust snake_case via toRustIdent; C# PascalCase via toCsharpIdent; Kotlin via toKotlinIdent; Swift via toSwiftIdent; Ruby snake_case via toRubyIdent; PHP camelCase via toPhpIdent).
 */
export function compareBreaking(outDir, baselineDir, { checkClients = true } = {}) {
  const baselineTools = loadToolNames(baselineDir);
  const outTools = loadToolNames(outDir);
  const removed = setDiff(baselineTools, outTools);
  const added = setDiff(outTools, baselineTools);

  const clients = { baseline: loadClientExports(baselineDir), out: loadClientExports(outDir) };
  const clientRemoved = {};
  let clientsChecked = false;

  if (checkClients) {
    for (const lang of ["ts", "python", "go", "java", "rust", "csharp", "kotlin", "swift", "ruby", "php"]) {
      const baseSet = clients.baseline[lang];
      const outSet = clients.out[lang];
      if (!baseSet || !outSet) continue;
      clientsChecked = true;
      // Prefer tool-name coverage: each baseline tool must map to an out export.
      const missing = [];
      for (const tool of baselineTools) {
        const exportName =
          lang === "go"
            ? toGoExported(tool)
            : lang === "java"
              ? toJavaIdent(tool)
              : lang === "rust"
                ? toRustIdent(tool)
                : lang === "csharp"
                  ? toCsharpIdent(tool)
                  : lang === "kotlin"
                    ? toKotlinIdent(tool)
                    : lang === "swift"
                      ? toSwiftIdent(tool)
                      : lang === "ruby"
                        ? toRubyIdent(tool)
                        : lang === "php"
                          ? toPhpIdent(tool)
                          : tool;
        if (!outSet.has(exportName)) missing.push(exportName);
      }
      // Also surface exports that vanished vs baseline client (rename/remove).
      const vanished = setDiff([...baseSet], [...outSet]);
      const all = [...new Set([...missing, ...vanished])].sort();
      if (all.length) clientRemoved[lang] = all;
    }
  }

  const breaking =
    removed.length > 0 || Object.keys(clientRemoved).some((k) => clientRemoved[k].length > 0);

  return {
    baselineTools,
    outTools,
    removed,
    added,
    clientsChecked,
    clientRemoved,
    breaking,
  };
}

export function printCheckDiff(result, { outDir, baselineDir }) {
  console.log(`check: out=${outDir}`);
  console.log(`check: baseline=${baselineDir}`);
  console.log(`tools: baseline=${result.baselineTools.length} out=${result.outTools.length}`);
  if (result.removed.length) {
    console.log(`REMOVED tools (${result.removed.length}):`);
    for (const n of result.removed) console.log(`  - ${n}`);
  } else {
    console.log("REMOVED tools: (none)");
  }
  if (result.added.length) {
    console.log(`ADDED tools (${result.added.length}) — OK:`);
    for (const n of result.added) console.log(`  + ${n}`);
  } else {
    console.log("ADDED tools: (none)");
  }
  if (result.removed.length && result.added.length) {
    console.log("note: removed+added may indicate renames (treated as breaking)");
  }
  if (result.clientsChecked) {
    const langs = Object.keys(result.clientRemoved);
    if (!langs.length) {
      console.log("client exports: OK (no removals vs baseline tools)");
    } else {
      for (const lang of langs) {
        const miss = result.clientRemoved[lang];
        if (!miss?.length) continue;
        console.log(`REMOVED ${lang} client exports (${miss.length}):`);
        for (const n of miss) console.log(`  - ${n}`);
      }
    }
  } else {
    console.log("client exports: skipped (no overlapping client.* in both dirs)");
  }
  if (result.breaking) {
    console.log("RESULT: BREAKING (exit 1)");
  } else {
    console.log("RESULT: OK");
  }
}

/** GHA workflow-command data escape: % \r \n */
function ghaEscapeData(text) {
  const s = text == null ? "" : String(text);
  return s.replace(/%/g, "%25").replace(/\r/g, "%0D").replace(/\n/g, "%0A");
}

/** GHA property escape: data + : in title */
function ghaEscapeProperty(text) {
  return ghaEscapeData(text).replace(/:/g, "%3A");
}

function ghaErrorLine(title, message) {
  return `::error title=${ghaEscapeProperty(title)}::${ghaEscapeData(message)}`;
}

/**
 * GitHub Actions workflow commands for OpenAPI drift (align with C/D/E).
 * REMOVED tools → `::error title=tool/<name>::removed or renamed vs baseline`
 * Missing client exports → `::error title=<lang>/<export>::missing client export vs baseline`
 * ADDED tools are OK (no error). No breaking → empty stdout (no notice).
 */
export function formatCheckGha(result) {
  const lines = [];
  for (const name of result.removed || []) {
    lines.push(ghaErrorLine(`tool/${name}`, "removed or renamed vs baseline"));
  }
  const clientRemoved = result.clientRemoved || {};
  for (const lang of Object.keys(clientRemoved).sort()) {
    for (const exp of clientRemoved[lang] || []) {
      lines.push(ghaErrorLine(`${lang}/${exp}`, "missing client export vs baseline"));
    }
  }
  if (!lines.length) return "";
  return lines.join("\n") + "\n";
}

function mdEscapePipe(text) {
  return String(text == null ? "" : text).replace(/\\/g, "\\\\").replace(/\|/g, "\\|");
}

function mdBacktickName(name) {
  // GFM list item with backticks; escape | inside the name for table-ish safety
  return "`" + mdEscapePipe(name).replace(/`/g, "\\`") + "`";
}

/**
 * Markdown summary for $GITHUB_STEP_SUMMARY / tickets (text/markdown plain text).
 * Always includes heading + clear empty states.
 */
export function formatCheckMd(result) {
  const lines = [];
  lines.push("# SDK MCP Gen drift check");
  lines.push("");
  const baseN = result.baselineTools?.length ?? 0;
  const outN = result.outTools?.length ?? 0;
  lines.push(
    `Tools: baseline=${baseN} out=${outN} · Breaking: ${result.breaking ? "yes" : "no"}`
  );
  lines.push("");
  if (!result.breaking) {
    lines.push("No breaking changes.");
    lines.push("");
  }
  lines.push("## REMOVED tools");
  if (result.removed?.length) {
    for (const n of result.removed) lines.push(`- ${mdBacktickName(n)}`);
  } else {
    lines.push("- (none)");
  }
  lines.push("");
  lines.push("## ADDED tools");
  if (result.added?.length) {
    for (const n of result.added) lines.push(`- ${mdBacktickName(n)}`);
  } else {
    lines.push("- (none)");
    lines.push("");
    lines.push("Added: (none)");
  }
  lines.push("");
  lines.push("## Missing client exports");
  const clientRemoved = result.clientRemoved || {};
  const langs = Object.keys(clientRemoved).filter((k) => clientRemoved[k]?.length).sort();
  if (!langs.length) {
    lines.push("- (none)");
  } else {
    for (const lang of langs) {
      for (const exp of clientRemoved[lang]) {
        lines.push(`- ${mdBacktickName(`${lang}/${exp}`)}`);
      }
    }
  }
  lines.push("");
  return lines.join("\n");
}

/** HTML escape for text/attributes: & < > " ' */
function htmlEscape(text) {
  return String(text == null ? "" : text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * Self-contained HTML drift report (align C/D: inline CSS, no CDN).
 * REMOVED / missing export rows use class fail (red). Empty lists → (none).
 */
export function formatCheckHtml(result) {
  const title = "SDK MCP Gen drift check";
  const baseN = result.baselineTools?.length ?? 0;
  const outN = result.outTools?.length ?? 0;
  const breaking = !!result.breaking;
  const style =
    "body{font-family:ui-sans-serif,system-ui,sans-serif;margin:2rem;color:#111;max-width:52rem}" +
    "h1{font-size:1.25rem}" +
    "h2{font-size:1.05rem;margin-top:1.5rem}" +
    "table{border-collapse:collapse;margin:1rem 0;min-width:28rem}" +
    "th,td{border:1px solid #ddd;padding:.4rem .6rem;text-align:left}" +
    "th{background:#f5f5f5}" +
    ".fail{color:#b00020;font-weight:700}" +
    ".meta{color:#555;font-size:.9rem}" +
    "code{background:#f4f4f4;padding:0.1rem 0.3rem}";

  function toolRows(names, fail) {
    if (!names?.length) {
      return '<tr><td class="meta">(none)</td></tr>';
    }
    return names
      .map((n) => {
        const cls = fail ? ' class="fail"' : "";
        return `<tr${cls}><td><code>${htmlEscape(n)}</code></td></tr>`;
      })
      .join("\n");
  }

  const clientRemoved = result.clientRemoved || {};
  const missRows = [];
  for (const lang of Object.keys(clientRemoved).sort()) {
    for (const exp of clientRemoved[lang] || []) {
      missRows.push(
        `<tr class="fail"><td><code>${htmlEscape(lang)}</code></td><td><code>${htmlEscape(exp)}</code></td></tr>`
      );
    }
  }
  const missingBody = missRows.length
    ? missRows.join("\n")
    : '<tr><td colspan="2" class="meta">(none)</td></tr>';

  const notice = breaking
    ? ""
    : "<p><strong>No breaking changes.</strong></p>\n";

  return (
    "<!DOCTYPE html>\n" +
    '<html lang="en">\n' +
    "<head>\n" +
    '<meta charset="utf-8"/>\n' +
    '<meta name="viewport" content="width=device-width, initial-scale=1"/>\n' +
    `<title>${htmlEscape(title)}</title>\n` +
    `<style>${style}</style>\n` +
    "</head>\n" +
    "<body>\n" +
    `<h1>${htmlEscape(title)}</h1>\n` +
    `<p class="meta">Tools: baseline=${baseN} out=${outN} · Breaking: ${breaking ? "yes" : "no"}</p>\n` +
    notice +
    "<h2>REMOVED tools</h2>\n" +
    "<table>\n<thead><tr><th>tool</th></tr></thead>\n<tbody>\n" +
    toolRows(result.removed, true) +
    "\n</tbody>\n</table>\n" +
    "<h2>ADDED tools</h2>\n" +
    "<table>\n<thead><tr><th>tool</th></tr></thead>\n<tbody>\n" +
    toolRows(result.added, false) +
    "\n</tbody>\n</table>\n" +
    "<h2>Missing client exports</h2>\n" +
    "<table>\n<thead><tr><th>lang</th><th>export</th></tr></thead>\n<tbody>\n" +
    missingBody +
    "\n</tbody>\n</table>\n" +
    "</body>\n" +
    "</html>\n"
  );
}


const SARIF_SCHEMA =
  "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json";

const CHECK_SARIF_TOOL_VERSION = "0.1.0";

/**
 * SARIF 2.1.0 JSON for OpenAPI/MCP drift (align D to_sarif / GitHub code scanning).
 * REMOVED tools → rule tool-removed (error). Missing client exports → client-export-missing (error).
 * ADDED tools are OK (no results). No breaking → results: []. Pretty-print + trailing newline.
 * Omit physicalLocation (no real file path for tool names).
 */
export function formatCheckSarif(result) {
  const rules = [
    {
      id: "tool-removed",
      name: "tool-removed",
      shortDescription: { text: "Tool removed or renamed vs baseline" },
      fullDescription: {
        text: "An MCP tool present in the baseline is missing from the out dir (removed or renamed).",
      },
      defaultConfiguration: { level: "error" },
    },
    {
      id: "client-export-missing",
      name: "client-export-missing",
      shortDescription: { text: "Client export missing vs baseline" },
      fullDescription: {
        text: "A generated client export expected from baseline tools is missing in the out dir.",
      },
      defaultConfiguration: { level: "error" },
    },
  ];
  const ruleIndex = { "tool-removed": 0, "client-export-missing": 1 };
  const results = [];

  for (const name of result.removed || []) {
    const tool = String(name == null ? "" : name);
    results.push({
      ruleId: "tool-removed",
      ruleIndex: ruleIndex["tool-removed"],
      level: "error",
      message: {
        text: `Tool "${tool}" removed or renamed vs baseline`,
      },
    });
  }

  const clientRemoved = result.clientRemoved || {};
  for (const lang of Object.keys(clientRemoved).sort()) {
    for (const exp of clientRemoved[lang] || []) {
      const exportName = String(exp == null ? "" : exp);
      results.push({
        ruleId: "client-export-missing",
        ruleIndex: ruleIndex["client-export-missing"],
        level: "error",
        message: {
          text: `Missing ${lang} client export "${exportName}" vs baseline`,
        },
      });
    }
  }

  const doc = {
    $schema: SARIF_SCHEMA,
    version: "2.1.0",
    runs: [
      {
        tool: {
          driver: {
            name: "sdk-mcp-gen",
            version: CHECK_SARIF_TOOL_VERSION,
            informationUri:
              "https://github.com/wozqhl/oss-cash-lab/tree/main/bets/a-sdk-mcp-gen",
            rules,
          },
        },
        results,
      },
    ],
  };
  return JSON.stringify(doc, null, 2) + "\n";
}

/**
 * Machine-readable OpenAPI/MCP drift report for CI scripts / jq.
 * ADDED tools are listed but do not set breaking/ok (same as other formats).
 * Omits full baselineTools/outTools name lists — counts + removed/added/clientRemoved only.
 */
export function formatCheckJson(result) {
  const breaking = !!result.breaking;
  const removed = [...(result.removed || [])].map((n) => String(n == null ? "" : n)).sort();
  const added = [...(result.added || [])].map((n) => String(n == null ? "" : n)).sort();
  const clientRemoved = {};
  const cr = result.clientRemoved || {};
  for (const lang of Object.keys(cr).sort()) {
    const miss = [...(cr[lang] || [])].map((n) => String(n == null ? "" : n)).sort();
    if (miss.length) clientRemoved[lang] = miss;
  }
  const doc = {
    ok: !breaking,
    breaking,
    tool: "sdk-mcp-gen",
    check: "openapi-mcp-drift",
    baselineToolCount: Array.isArray(result.baselineTools) ? result.baselineTools.length : 0,
    outToolCount: Array.isArray(result.outTools) ? result.outTools.length : 0,
    removed,
    added,
    clientsChecked: !!result.clientsChecked,
    clientRemoved,
  };
  return JSON.stringify(doc, null, 2) + "\n";
}


/**
 * JUnit XML for OpenAPI/MCP drift (align C agent-ci; GitHub Actions / Jenkins / GitLab ingest).
 * REMOVED tools → testcase classname="tool" with failure.
 * Missing client exports → testcase classname="<lang>" with failure.
 * ADDED tools omitted (not failures). No breaking → empty suite tests="0" (no fake pass case).
 */
export function formatCheckJunit(result) {
  const cases = [];
  for (const name of result.removed || []) {
    cases.push({
      classname: "tool",
      name: String(name == null ? "" : name),
      message: "removed or renamed vs baseline",
    });
  }
  const clientRemoved = result.clientRemoved || {};
  for (const lang of Object.keys(clientRemoved).sort()) {
    for (const exp of clientRemoved[lang] || []) {
      cases.push({
        classname: String(lang),
        name: String(exp == null ? "" : exp),
        message: "missing client export vs baseline",
      });
    }
  }
  const n = cases.length;
  const lines = [
    `<testsuite name="sdk-mcp-gen-drift" tests="${n}" failures="${n}" errors="0" time="0">`,
  ];
  for (const c of cases) {
    const cn = htmlEscape(c.classname);
    const nm = htmlEscape(c.name);
    const msg = htmlEscape(c.message);
    lines.push(`  <testcase classname="${cn}" name="${nm}" time="0">`);
    lines.push(`    <failure message="${msg}">${msg}</failure>`);
    lines.push("  </testcase>");
  }
  lines.push("</testsuite>");
  return lines.join("\n") + "\n";
}

/** Escape TAP description so `#` cannot start a comment; flatten newlines. */
function tapEscape(text) {
  let s = text == null ? "" : String(text);
  s = s.replace(/\r\n/g, " ").replace(/\n/g, " ").replace(/\r/g, " ");
  return s.replace(/#/g, "\\#");
}

/**
 * TAP version 13 for OpenAPI/MCP drift (align C agent-ci).
 * REMOVED tools → `not ok N - tool/<name>` + `#` diagnostic.
 * Missing client exports → `not ok N - <lang>/<export>` + `#` diagnostic.
 * ADDED tools omitted (not failures). No breaking → `1..0` (empty suite).
 * `#` in names escaped so they cannot start TAP comments.
 */
export function formatCheckTap(result) {
  const cases = [];
  for (const name of result.removed || []) {
    cases.push({
      desc: `tool/${String(name == null ? "" : name)}`,
      message: "removed or renamed vs baseline",
    });
  }
  const clientRemoved = result.clientRemoved || {};
  for (const lang of Object.keys(clientRemoved).sort()) {
    for (const exp of clientRemoved[lang] || []) {
      cases.push({
        desc: `${lang}/${String(exp == null ? "" : exp)}`,
        message: "missing client export vs baseline",
      });
    }
  }
  const n = cases.length;
  const lines = ["TAP version 13", `1..${n}`];
  for (let i = 0; i < n; i++) {
    const c = cases[i];
    lines.push(`not ok ${i + 1} - ${tapEscape(c.desc)}`);
    lines.push(`# ${tapEscape(c.message)}`);
  }
  return lines.join("\n") + "\n";
}

/** Normalize check --format; annotations → gha. Returns null if invalid. */
export function normalizeCheckFormat(raw) {
  if (raw == null || raw === "") return "text";
  const v = String(raw).trim().toLowerCase();
  if (v === "text") return "text";
  if (v === "gha" || v === "annotations") return "gha";
  if (v === "md" || v === "markdown") return "md";
  if (v === "html") return "html";
  if (v === "sarif") return "sarif";
  if (v === "json") return "json";
  if (v === "junit") return "junit";
  if (v === "tap") return "tap";
  return null;
}

export const CHECK_FORMATS_HELP = "text|gha|md|html|sarif|json|junit|tap (gha alias: annotations)";

export function runCheck(outDir, baselineDir, opts = {}) {
  const absOut = path.resolve(outDir);
  const absBase = path.resolve(baselineDir);
  const format = normalizeCheckFormat(opts.format) || "text";
  const result = compareBreaking(absOut, absBase, opts);
  if (format === "gha") {
    const out = formatCheckGha(result);
    if (out) process.stdout.write(out);
  } else if (format === "md") {
    process.stdout.write(formatCheckMd(result));
  } else if (format === "html") {
    process.stdout.write(formatCheckHtml(result));
  } else if (format === "sarif") {
    process.stdout.write(formatCheckSarif(result));
  } else if (format === "json") {
    process.stdout.write(formatCheckJson(result));
  } else if (format === "junit") {
    process.stdout.write(formatCheckJunit(result));
  } else if (format === "tap") {
    process.stdout.write(formatCheckTap(result));
  } else {
    printCheckDiff(result, { outDir: absOut, baselineDir: absBase });
  }
  return result.breaking ? 1 : 0;
}
