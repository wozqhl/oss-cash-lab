/** Minimal JSON-compatible YAML subset loader (no deps).
 * Supports: JSON documents, block maps/lists, scalars, # comments, quoted strings.
 * Not a full YAML 1.2 engine — enough for typical OpenAPI petstore specs.
 * OpenAPI 3.0.x and 3.1.x documents are accepted (no JSON Schema 2020-12 rewrite).
 */
export function loadOpenApiSpec(text, filename = "") {
  const trimmed = String(text || "").replace(/^\uFEFF/, "").trim();
  if (!trimmed) throw new Error("empty OpenAPI document");
  // Fast path: JSON (also valid YAML)
  if (trimmed[0] === "{" || trimmed[0] === "[") {
    return JSON.parse(trimmed);
  }
  const lower = (filename || "").toLowerCase();
  const looksYaml = lower.endsWith(".yaml") || lower.endsWith(".yml") || /[\n\r].*:/.test(trimmed);
  if (!looksYaml) {
    return JSON.parse(trimmed);
  }
  return parseYamlSubset(trimmed);
}

function parseYamlSubset(src) {
  const lines = src.split(/\r?\n/);
  let i = 0;

  function stripComment(line) {
    let inSingle = false;
    let inDouble = false;
    for (let k = 0; k < line.length; k++) {
      const ch = line[k];
      if (ch === "'" && !inDouble) inSingle = !inSingle;
      else if (ch === '"' && !inSingle) inDouble = !inDouble;
      else if (ch === "#" && !inSingle && !inDouble) {
        if (k === 0 || /\s/.test(line[k - 1])) return line.slice(0, k).replace(/\s+$/, "");
      }
    }
    return line.replace(/\s+$/, "");
  }

  function indentOf(line) {
    const m = /^(\s*)/.exec(line);
    return m ? m[1].length : 0;
  }

  function parseScalar(raw) {
    const s = raw.trim();
    if (s === "" || s === "~" || s === "null") return null;
    if (s === "true") return true;
    if (s === "false") return false;
    if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) {
      return s.slice(1, -1);
    }
    if (/^-?\d+$/.test(s)) return Number(s);
    if (/^-?\d+\.\d+$/.test(s)) return Number(s);
    return s;
  }

  function peek() {
    while (i < lines.length) {
      const raw = lines[i];
      const cleaned = stripComment(raw);
      if (cleaned.trim() === "") {
        i++;
        continue;
      }
      return { raw: cleaned, indent: indentOf(cleaned), text: cleaned.trim() };
    }
    return null;
  }

  function parseBlock(minIndent) {
    const first = peek();
    if (!first) return null;
    if (first.text.startsWith("- ")) {
      const arr = [];
      while (true) {
        const cur = peek();
        if (!cur || cur.indent < minIndent) break;
        if (cur.indent !== first.indent || !cur.text.startsWith("- ")) break;
        i++;
        const rest = cur.text.slice(2);
        if (rest.includes(": ") || rest.endsWith(":")) {
          // inline map start on same line as list item
          const key = rest.endsWith(":") ? rest.slice(0, -1).trim() : rest.split(": ")[0].trim();
          const inlineVal = rest.endsWith(":") ? undefined : rest.split(": ").slice(1).join(": ").trim();
          const obj = {};
          if (inlineVal !== undefined && inlineVal !== "") {
            obj[key] = parseScalar(inlineVal);
          } else {
            const nxt = peek();
            if (nxt && nxt.indent > cur.indent) {
              obj[key] = parseBlock(nxt.indent);
            } else {
              obj[key] = null;
            }
          }
          // continue sibling keys at indent > list marker indent (typically +2)
          while (true) {
            const sib = peek();
            if (!sib || sib.indent <= cur.indent || sib.text.startsWith("- ")) break;
            if (!sib.text.includes(":") ) break;
            i++;
            const k = sib.text.endsWith(":")
              ? sib.text.slice(0, -1).trim()
              : sib.text.split(": ")[0].trim();
            const v = sib.text.endsWith(":")
              ? undefined
              : sib.text.split(": ").slice(1).join(": ").trim();
            if (v !== undefined && v !== "") {
              obj[k] = parseScalar(v);
            } else {
              const n2 = peek();
              if (n2 && n2.indent > sib.indent) obj[k] = parseBlock(n2.indent);
              else obj[k] = null;
            }
          }
          arr.push(obj);
        } else if (rest === "" || rest === "|" || rest === ">") {
          const nxt = peek();
          if (nxt && nxt.indent > cur.indent) arr.push(parseBlock(nxt.indent));
          else arr.push(null);
        } else {
          arr.push(parseScalar(rest));
        }
      }
      return arr;
    }

    // mapping
    const obj = {};
    const baseIndent = first.indent;
    while (true) {
      const cur = peek();
      if (!cur || cur.indent < minIndent) break;
      if (cur.indent !== baseIndent) break;
      if (cur.text.startsWith("- ")) break;
      if (!cur.text.includes(":")) {
        throw new Error("YAML subset: expected key: at line " + (i + 1) + ": " + cur.text);
      }
      i++;
      let key;
      let inline;
      if (cur.text.endsWith(":") && !cur.text.includes(": ")) {
        key = cur.text.slice(0, -1).trim();
        inline = undefined;
      } else {
        const idx = cur.text.indexOf(": ");
        key = cur.text.slice(0, idx).trim();
        inline = cur.text.slice(idx + 2).trim();
      }
      // strip optional quotes around keys
      if ((key.startsWith('"') && key.endsWith('"')) || (key.startsWith("'") && key.endsWith("'"))) {
        key = key.slice(1, -1);
      }
      if (inline !== undefined && inline !== "" && inline !== "|" && inline !== ">") {
        if (inline.startsWith("{") || inline.startsWith("[")) {
          obj[key] = JSON.parse(inline);
        } else {
          obj[key] = parseScalar(inline);
        }
      } else {
        const nxt = peek();
        if (nxt && nxt.indent > cur.indent) {
          obj[key] = parseBlock(nxt.indent);
        } else {
          obj[key] = null;
        }
      }
    }
    return obj;
  }

  const doc = parseBlock(0);
  if (doc == null || typeof doc !== "object") {
    throw new Error("YAML subset: failed to parse document");
  }
  return doc;
}
