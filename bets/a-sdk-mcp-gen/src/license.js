/** Apache-2.0 LICENSE + NOTICE for generated SDK out dirs. No extra deps. */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const LICENSE_FILE = "LICENSE";
export const NOTICE_FILE = "NOTICE";

const HERE = path.dirname(fileURLToPath(import.meta.url));

/** Short Apache-2.0 stub when the portfolio LICENSE cannot be found. */
export const APACHE_2_STUB = `Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
`;

/**
 * Walk up from this module looking for a repo-root LICENSE that mentions Apache.
 * Prefer the monorepo LICENSE when present; do not use process.cwd() (user tree).
 */
export function findRepoLicensePath() {
  let dir = HERE;
  for (let i = 0; i < 8; i++) {
    const candidate = path.join(dir, LICENSE_FILE);
    try {
      if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) {
        const text = fs.readFileSync(candidate, "utf8");
        if (/Apache/i.test(text)) return candidate;
      }
    } catch {
      /* continue walking */
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

/** Full Apache-2.0 text from the portfolio LICENSE, else a short Apache-2.0 stub. */
export function readLicenseText() {
  const found = findRepoLicensePath();
  if (found) {
    try {
      const text = fs.readFileSync(found, "utf8");
      if (text && /Apache/i.test(text)) return text.endsWith("\n") ? text : text + "\n";
    } catch {
      /* fall through to stub */
    }
  }
  return APACHE_2_STUB.endsWith("\n") ? APACHE_2_STUB : APACHE_2_STUB + "\n";
}

/**
 * Title/url from the OpenAPI document only — never fetch --header values.
 */
export function specNoticeMeta(spec) {
  const title = spec && spec.info && spec.info.title ? String(spec.info.title).trim() : "";
  const ext = spec && spec.externalDocs && spec.externalDocs.url ? String(spec.externalDocs.url).trim() : "";
  const contact = spec && spec.info && spec.info.contact && spec.info.contact.url
    ? String(spec.info.contact.url).trim()
    : "";
  return { specTitle: title, specUrl: ext || contact };
}

export function generateNotice({ packageName, specTitle, specUrl } = {}) {
  const name = String(packageName || "client").trim() || "client";
  const title = specTitle ? String(specTitle).trim() : "";
  const url = specUrl ? String(specUrl).trim() : "";
  let basedOn = "This generated SDK is based on an OpenAPI document.";
  if (title && url) basedOn = `This generated SDK is based on OpenAPI from "${title}" (${url}).`;
  else if (title) basedOn = `This generated SDK is based on OpenAPI from "${title}".`;
  else if (url) basedOn = `This generated SDK is based on OpenAPI from ${url}.`;
  return [
    name,
    "Copyright 2026",
    "",
    `Generated package: ${name}`,
    basedOn,
    "",
    "Licensed under the Apache License, Version 2.0 (the \"License\");",
    "you may not use this file except in compliance with the License.",
    "You may obtain a copy of the License at",
    "",
    "    http://www.apache.org/licenses/LICENSE-2.0",
    "",
    "See the LICENSE file in this directory.",
    "",
    "Unless required by applicable law or agreed to in writing, software",
    "distributed under the License is distributed on an \"AS IS\" BASIS,",
    "WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.",
    "See the License for the specific language governing permissions and",
    "limitations under the License.",
    "",
  ].join("\n");
}

/**
 * Always overwrite LICENSE + NOTICE (generated artifacts).
 * Returns ["LICENSE", "NOTICE"].
 */
export function writeLicenseArtifacts(absOut, spec, packageName) {
  const meta = specNoticeMeta(spec);
  fs.writeFileSync(path.join(absOut, LICENSE_FILE), readLicenseText());
  fs.writeFileSync(
    path.join(absOut, NOTICE_FILE),
    generateNotice({ packageName, specTitle: meta.specTitle, specUrl: meta.specUrl }),
  );
  return [LICENSE_FILE, NOTICE_FILE];
}

/** Drop leftover generated LICENSE/NOTICE when --no-license. */
export function removeLicenseArtifacts(absOut) {
  for (const name of [LICENSE_FILE, NOTICE_FILE]) {
    const p = path.join(absOut, name);
    try {
      if (fs.existsSync(p) && fs.statSync(p).isFile()) fs.unlinkSync(p);
    } catch {
      /* ignore */
    }
  }
}
