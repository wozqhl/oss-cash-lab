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
  for (const m of src.matchAll(/async\s+function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(/g)) {
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

export function runCheck(outDir, baselineDir, opts = {}) {
  const absOut = path.resolve(outDir);
  const absBase = path.resolve(baselineDir);
  const result = compareBreaking(absOut, absBase, opts);
  printCheckDiff(result, { outDir: absOut, baselineDir: absBase });
  return result.breaking ? 1 : 0;
}
