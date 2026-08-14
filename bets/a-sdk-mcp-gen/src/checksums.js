/** SHA-256 manifest for generated out-dir artifacts. */
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

/** Files considered for checksums.sha256 (existing only). sdk.tgz/sdk.zip are omitted (written after this manifest). */
export const CHECKSUM_CANDIDATES = [
  "client.ts",
  "package.json",
  "client.py",
  "client.go",
  "Client.java",
  "client.rs",
  "Client.cs",
  "Client.kt",
  "Client.swift",
  "client.rb",
  "Client.php",
  "mcp-tools.json",
  "mcp-server.mjs",
  "mcp_server.py",
  "mcp_server.go",
  "mcp.json",
  "README.md",
  "LICENSE",
  "NOTICE",
  ".gitignore",
];

export const CHECKSUMS_FILE = "checksums.sha256";

export function sha256File(filePath) {
  const buf = fs.readFileSync(filePath);
  return crypto.createHash("sha256").update(buf).digest("hex");
}

/**
 * Write checksums.sha256 for candidates that exist under absOut.
 * Format: `<hex>  <filename>` (GNU sha256sum two-space style), one per line.
 * Returns list of filenames included.
 */
export function writeChecksumManifest(absOut) {
  const lines = [];
  const included = [];
  for (const name of CHECKSUM_CANDIDATES) {
    const p = path.join(absOut, name);
    if (!fs.existsSync(p) || !fs.statSync(p).isFile()) continue;
    const hash = sha256File(p);
    lines.push(`${hash}  ${name}`);
    included.push(name);
  }
  const manifestPath = path.join(absOut, CHECKSUMS_FILE);
  fs.writeFileSync(manifestPath, lines.length ? lines.join("\n") + "\n" : "");
  return included;
}

/**
 * Parse checksums.sha256 body into [{hash, name}, ...].
 * Accepts "HASH  name" or "HASH *name" / "HASH name".
 */
export function parseChecksumManifest(text) {
  const entries = [];
  for (const raw of String(text).split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const m = line.match(/^([a-fA-F0-9]{64})\s+\*?(\S+)\s*$/);
    if (!m) {
      throw new Error(`invalid checksums.sha256 line: ${raw}`);
    }
    entries.push({ hash: m[1].toLowerCase(), name: m[2] });
  }
  return entries;
}

/**
 * Verify checksums.sha256 under outDir.
 * Returns { ok, code, errors[], checked }.
 * code 0 = match; 1 = mismatch/missing/invalid.
 */
export function verifyChecksums(outDir) {
  const absOut = path.resolve(outDir);
  const manifestPath = path.join(absOut, CHECKSUMS_FILE);
  const errors = [];
  let checked = 0;

  if (!fs.existsSync(manifestPath)) {
    errors.push(`missing ${CHECKSUMS_FILE}`);
    return { ok: false, code: 1, errors, checked };
  }

  let entries;
  try {
    entries = parseChecksumManifest(fs.readFileSync(manifestPath, "utf8"));
  } catch (err) {
    errors.push(err.message || String(err));
    return { ok: false, code: 1, errors, checked };
  }

  if (!entries.length) {
    errors.push(`${CHECKSUMS_FILE} is empty`);
    return { ok: false, code: 1, errors, checked };
  }

  for (const { hash, name } of entries) {
    // refuse path traversal
    if (name.includes("..") || path.isAbsolute(name) || name.includes("/") || name.includes("\\")) {
      errors.push(`unsafe path in manifest: ${name}`);
      continue;
    }
    const filePath = path.join(absOut, name);
    if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
      errors.push(`missing file: ${name}`);
      continue;
    }
    const actual = sha256File(filePath);
    checked += 1;
    if (actual !== hash) {
      errors.push(`mismatch: ${name} (expected ${hash}, got ${actual})`);
    }
  }

  return { ok: errors.length === 0, code: errors.length ? 1 : 0, errors, checked };
}

export function runVerifyChecksums(outDir) {
  const absOut = path.resolve(outDir);
  const result = verifyChecksums(absOut);
  console.log(`verify-checksums: out=${absOut}`);
  console.log(`verify-checksums: checked=${result.checked}`);
  if (result.ok) {
    console.log("RESULT: OK");
  } else {
    for (const e of result.errors) console.error(`  ${e}`);
    console.log("RESULT: FAIL (exit 1)");
  }
  return result.code;
}
