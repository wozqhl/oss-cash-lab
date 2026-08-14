/** Pack generate --out into a single SDK drop. No extra deps. */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import zlib from "node:zlib";
import { spawnSync } from "node:child_process";

export const ARCHIVE_TGZ = "sdk.tgz";
export const ARCHIVE_ZIP = "sdk.zip";
export const ARCHIVE_NAMES = [ARCHIVE_TGZ, ARCHIVE_ZIP];

export function tarAvailable() {
  const r = spawnSync("tar", ["--version"], { encoding: "utf8", timeout: 4000 });
  return !r.error && r.status === 0;
}

export function plannedArchiveName() {
  return tarAvailable() ? ARCHIVE_TGZ : ARCHIVE_ZIP;
}

const TAR_TIMEOUT_MS = 30000;

/**
 * Write sdk.tgz via tar -czf (preferred) or uncompressed sdk.zip.
 * Call after checksums.sha256. Archive is not listed in checksums.
 * Returns the archive filename.
 */
export function writeSdkArchive(absOut) {
  const outDir = path.resolve(absOut);
  if (!fs.existsSync(outDir) || !fs.statSync(outDir).isDirectory()) {
    throw new Error("archive: missing out dir " + outDir);
  }
  let name;
  if (tarAvailable()) {
    try {
      name = writeTgz(outDir);
    } catch {
      name = writeStoredZip(outDir);
    }
  } else {
    name = writeStoredZip(outDir);
  }
  for (const other of ARCHIVE_NAMES) {
    if (other === name) continue;
    const leftover = path.join(outDir, other);
    try {
      if (fs.existsSync(leftover)) fs.unlinkSync(leftover);
    } catch {
      /* ignore leftover cleanup */
    }
  }
  return name;
}

function writeTgz(absOut) {
  const tmp = path.join(os.tmpdir(), "sdk-mcp-gen-" + process.pid + "-" + Date.now() + ".tgz");
  try {
    const args = [
      "-czf",
      tmp,
      "-C",
      absOut,
      "--exclude=" + ARCHIVE_TGZ,
      "--exclude=" + ARCHIVE_ZIP,
      ".",
    ];
    const r = spawnSync("tar", args, { encoding: "utf8", timeout: TAR_TIMEOUT_MS });
    if (r.error || r.status !== 0) {
      const detail = r.error ? String(r.error.message || r.error) : String(r.stderr || r.status);
      throw new Error("tar pack failed: " + detail.trim());
    }
    if (!fs.existsSync(tmp) || !fs.statSync(tmp).size) {
      throw new Error("tar pack produced an empty archive");
    }
    fs.copyFileSync(tmp, path.join(absOut, ARCHIVE_TGZ));
    return ARCHIVE_TGZ;
  } finally {
    try {
      if (fs.existsSync(tmp)) fs.unlinkSync(tmp);
    } catch {
      /* ignore */
    }
  }
}

function listFilesRecursive(absOut) {
  const skip = new Set(ARCHIVE_NAMES.concat([".sdk.tgz.tmp", ".sdk.zip.tmp"]));
  const files = [];
  function walk(dir, rel) {
    let ents;
    try {
      ents = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const ent of ents) {
      if (rel === "" && skip.has(ent.name)) continue;
      const relPath = rel ? rel + "/" + ent.name : ent.name;
      const full = path.join(dir, ent.name);
      if (ent.isDirectory()) walk(full, relPath);
      else if (ent.isFile()) files.push({ rel: relPath.replace(/\\/g, "/"), full });
    }
  }
  walk(absOut, "");
  return files;
}

function u16(n) {
  const b = Buffer.alloc(2);
  b.writeUInt16LE(n & 0xffff, 0);
  return b;
}

function u32(n) {
  const b = Buffer.alloc(4);
  b.writeUInt32LE(n >>> 0, 0);
  return b;
}

function fileCrc(buf) {
  return zlib.crc32(buf) >>> 0;
}

/** Uncompressed (store-only) zip so Node needs no extra dep. */
function writeStoredZip(absOut) {
  const files = listFilesRecursive(absOut);
  const locals = [];
  const centrals = [];
  let offset = 0;
  const localSig = Buffer.from([0x50, 0x4b, 0x03, 0x04]);
  const centralSig = Buffer.from([0x50, 0x4b, 0x01, 0x02]);
  const eocdSig = Buffer.from([0x50, 0x4b, 0x05, 0x06]);
  for (const f of files) {
    const data = fs.readFileSync(f.full);
    const nameBuf = Buffer.from(f.rel, "utf8");
    const crc = fileCrc(data);
    const size = data.length;
    const local = Buffer.concat([
      localSig,
      u16(20),
      u16(0),
      u16(0),
      u16(0),
      u16(0),
      u32(crc),
      u32(size),
      u32(size),
      u16(nameBuf.length),
      u16(0),
      nameBuf,
      data,
    ]);
    const central = Buffer.concat([
      centralSig,
      u16(20),
      u16(20),
      u16(0),
      u16(0),
      u16(0),
      u16(0),
      u32(crc),
      u32(size),
      u32(size),
      u16(nameBuf.length),
      u16(0),
      u16(0),
      u16(0),
      u16(0),
      u32(0),
      u32(offset),
      nameBuf,
    ]);
    locals.push(local);
    centrals.push(central);
    offset += local.length;
  }
  const localBuf = Buffer.concat(locals);
  const centralBuf = Buffer.concat(centrals);
  const eocd = Buffer.concat([
    eocdSig,
    u16(0),
    u16(0),
    u16(files.length),
    u16(files.length),
    u32(centralBuf.length),
    u32(localBuf.length),
    u16(0),
  ]);
  fs.writeFileSync(path.join(absOut, ARCHIVE_ZIP), Buffer.concat([localBuf, centralBuf, eocd]));
  return ARCHIVE_ZIP;
}
