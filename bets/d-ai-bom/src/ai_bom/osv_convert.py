"""Offline OSV / GitHub Advisory JSON to local ai-bom-advisories/v1 fixture.

No network. Does not invent CVSS scores or affected versions.
IDs stay as published (OSV- / GHSA- / ...). ADV-FIXTURE-* only if the
source record already used that namespace.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_bom.advisories import SCHEMA_ID, parse_purl


NOTE = (
    "Converted offline from OSV/GHSA JSON. Not an NVD/OSV/GHSA fetch. "
    "IDs kept from the source. Version ranges are recorded when present; "
    "exact versions are copied only when the source listed them."
)

_SIMPLE_SEVERITY = frozenset(
    {"critical", "high", "medium", "low", "info", "unknown", "moderate"}
)

_ECOSYSTEM_PURL_TYPE = {}
_ECOSYSTEM_PURL_TYPE["pypi"] = "pypi"
_ECOSYSTEM_PURL_TYPE["pip"] = "pypi"

@dataclass(frozen=True)
class ConvertResult:
    document: dict[str, Any]
    converted: int
    skipped: int

def _norm(raw: Any) -> str:
    return str(raw or "").strip()

def _classify(item: dict[str, Any]) -> str:
    if isinstance(item.get("affected"), list):
        return "osv"
    if isinstance(item.get("component"), dict):
        return "fixture"
    if item.get("ghsa_id") or item.get("ghsaId"):
        return "ghsa"
    vulns = item.get("vulnerabilities")
    if isinstance(vulns, list):
        return "ghsa"
    if isinstance(vulns, dict) and isinstance(vulns.get("nodes"), list):
        return "ghsa"
    if item.get("id") or item.get("schema_version"):
        return "osv"
    return "unknown"

def _simple_severity(item: dict[str, Any]) -> str:
    raw = item.get("severity")
    if isinstance(raw, str):
        s = raw.strip().lower()
        if s == "moderate":
            return "medium"
        if s in _SIMPLE_SEVERITY:
            return s
    ds = item.get("database_specific")
    if isinstance(ds, dict) and isinstance(ds.get("severity"), str):
        s = str(ds.get("severity") or "").strip().lower()
        if s == "moderate":
            return "medium"
        if s in _SIMPLE_SEVERITY:
            return s
    return ""

def _unversioned_purl(purl: str) -> str:
    raw = _norm(purl)
    parsed = parse_purl(raw)
    if not parsed.get("type") or not parsed.get("name"):
        return ""
    rest = raw[4:]
    if "/" not in rest:
        return ""
    typ, namever = rest.split("/", 1)
    name = namever
    if namever.startswith("@") and namever.rfind("@") > 0:
        name = namever[: namever.rfind("@")]
    elif "@" in namever:
        name = namever.rsplit("@", 1)[0]
    name = name.split("?", 1)[0].split("#", 1)[0]
    if not name:
        return ""
    return "pkg:" + typ.lower() + "/" + name

def _package_identity(pkg: dict[str, Any] | None) -> tuple[str, str]:
    if not isinstance(pkg, dict):
        return "", ""
    name = _norm(pkg.get("name"))
    eco = _norm(pkg.get("ecosystem"))
    raw_purl = _norm(pkg.get("purl"))
    if raw_purl:
        stripped = _unversioned_purl(raw_purl)
        if stripped:
            if not name:
                name = stripped.split("/", 1)[-1]
            return name, stripped
    if not name:
        return "", ""
    ptype = _ECOSYSTEM_PURL_TYPE.get(eco.lower())
    if ptype:
        return name, "pkg:" + ptype + "/" + name
    return name, ""

def _osv_event_op(key: str, ver: str) -> str:
    """Map one OSV event to a recorded operator. Empty if we cannot be honest."""
    v = _norm(ver)
    if not v:
        return ""
    if key == "introduced":
        return ">=" + v
    if key in ("fixed", "limit"):
        return "<" + v
    if key == "last_affected":
        return "<=" + v
    return ""


def _osv_range_text(aff: dict[str, Any]) -> str:
    """Record affected range as operators the gate can evaluate (>=, <, comma-AND).

    Multiple OSV ranges are a union; we do not invent OR matching, so they are
    joined with ' || ' and the gate skips that string (no invented hit).
    """
    ranges = aff.get("ranges")
    if not isinstance(ranges, list):
        return ""
    parts: list[str] = []
    for rng in ranges:
        if not isinstance(rng, dict):
            continue
        events = rng.get("events")
        if not isinstance(events, list):
            continue
        bits: list[str] = []
        for ev in events:
            if not isinstance(ev, dict):
                continue
            for key in ("introduced", "fixed", "last_affected", "limit"):
                if key in ev and ev[key] is not None and str(ev[key]).strip():
                    op = _osv_event_op(key, ev[key])
                    if op:
                        bits.append(op)
        if bits:
            parts.append(",".join(bits))
    if len(parts) == 1:
        return parts[0]
    if len(parts) > 1:
        return " || ".join(parts)
    return ""

def _exact_versions(aff: dict[str, Any]) -> list[str]:
    raw = aff.get("versions")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        ver = _norm(item)
        if ver and ver not in seen:
            seen.add(ver)
            out.append(ver)
    return out

def _with_version(purl: str, version: str) -> str:
    if not purl or not version:
        return purl
    if parse_purl(purl).get("version"):
        return purl
    return purl + "@" + version

def _summary_with_range(summary: str, version_range: str) -> str:
    text = summary
    rng = _norm(version_range)
    if rng and rng not in text:
        if text:
            return text + " [range: " + rng + "]"
        return "[range: " + rng + "]"
    return text

def _entry(aid: str, name: str, purl: str, version: str, severity: str, summary: str, version_range: str = "") -> dict[str, Any] | None:
    if not aid or (not name and not purl):
        return None
    comp: dict[str, Any] = {}
    if name:
        comp["name"] = name
    if purl:
        comp["purl"] = _with_version(purl, version) if version else purl
    if version:
        comp["version"] = version
    if version_range:
        comp["versionRange"] = version_range
    out: dict[str, Any] = {"id": aid, "component": comp, "summary": summary}
    if severity:
        out["severity"] = severity
    return out

def _from_osv(item: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    aid = _norm(item.get("id"))
    if not aid:
        return [], 1
    affected = item.get("affected")
    if not isinstance(affected, list) or not affected:
        return [], 1
    summary = _norm(item.get("summary")) or _norm(item.get("details"))
    severity = _simple_severity(item)
    entries: list[dict[str, Any]] = []
    skipped = 0
    for aff in affected:
        if not isinstance(aff, dict):
            skipped += 1
            continue
        pkg = aff.get("package") if isinstance(aff.get("package"), dict) else None
        name, purl = _package_identity(pkg)
        if not name and not purl:
            skipped += 1
            continue
        rng = _osv_range_text(aff)
        versions = _exact_versions(aff)
        note = _summary_with_range(summary, rng)
        rows = versions or [""]
        for ver in rows:
            row = _entry(aid, name, purl, ver, severity, note, rng)
            if row:
                entries.append(row)
            else:
                skipped += 1
    if not entries:
        return [], max(skipped, 1)
    return entries, skipped

def _ghsa_vuln_list(item: dict[str, Any]) -> list[Any]:
    raw = item.get("vulnerabilities")
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("nodes"), list):
        return raw["nodes"]
    return []

def _from_ghsa(item: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    aid = _norm(item.get("ghsa_id") or item.get("ghsaId") or item.get("id"))
    if not aid:
        return [], 1
    vulns = _ghsa_vuln_list(item)
    if not vulns:
        return [], 1
    summary = _norm(item.get("summary") or item.get("description"))
    severity = _simple_severity(item)
    entries: list[dict[str, Any]] = []
    skipped = 0
    for vuln in vulns:
        if not isinstance(vuln, dict):
            skipped += 1
            continue
        pkg = vuln.get("package")
        name, purl = _package_identity(pkg if isinstance(pkg, dict) else None)
        if not name and not purl:
            skipped += 1
            continue
        rng = _norm(vuln.get("vulnerable_version_range") or vuln.get("vulnerableVersionRange"))
        note = _summary_with_range(summary, rng)
        row = _entry(aid, name, purl, "", severity, note, rng)
        if row:
            entries.append(row)
        else:
            skipped += 1
    if not entries:
        return [], max(skipped, 1)
    return entries, skipped

def _from_fixture(item: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    aid = _norm(item.get("id"))
    raw_comp = item.get("component")
    if not aid or not isinstance(raw_comp, dict):
        return [], 1
    name = _norm(raw_comp.get("name"))
    purl = _norm(raw_comp.get("purl"))
    version = _norm(raw_comp.get("version"))
    if not name and not purl:
        return [], 1
    row = _entry(aid, name, purl, version, _simple_severity(item), _norm(item.get("summary")), _norm(raw_comp.get("versionRange")))
    if not row:
        return [], 1
    return [row], 0

def convert_record(item: Any) -> tuple[list[dict[str, Any]], int, str]:
    if not isinstance(item, dict):
        return [], 1, ""
    kind = _classify(item)
    if kind == "osv":
        entries, skipped = _from_osv(item)
        return entries, skipped, "osv" if entries else ""
    if kind == "ghsa":
        entries, skipped = _from_ghsa(item)
        return entries, skipped, "ghsa" if entries else ""
    if kind == "fixture":
        entries, skipped = _from_fixture(item)
        return entries, skipped, "fixture" if entries else ""
    return [], 1, ""

def expand_source(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if _norm(data.get("schema")) == SCHEMA_ID and isinstance(data.get("advisories"), list):
            return data["advisories"]
        if isinstance(data.get("vulns"), list):
            return data["vulns"]
        return [data]
    raise ValueError("OSV/GHSA file must be a JSON object or array")

def _document(entries: list[dict[str, Any]], sources: set[str]) -> dict[str, Any]:
    source = "+".join(sorted(sources)) if sources else "osv"
    doc: dict[str, Any] = {}
    doc["schema"] = SCHEMA_ID
    doc["source"] = source
    doc["note"] = NOTE
    doc["advisories"] = entries
    return doc

def convert_data(data: Any) -> ConvertResult:
    records = expand_source(data)
    entries: list[dict[str, Any]] = []
    converted = 0
    skipped = 0
    sources: set[str] = set()
    for rec in records:
        got, skip, src = convert_record(rec)
        skipped += skip
        if got:
            entries.extend(got)
            converted += len(got)
            if src:
                sources.add(src)
    return ConvertResult(_document(entries, sources), converted, skipped)

def convert_files(paths: list[Path]) -> ConvertResult:
    entries: list[dict[str, Any]] = []
    converted = 0
    skipped = 0
    sources: set[str] = set()
    for path in paths:
        part = convert_data(json.loads(path.read_text(encoding="utf-8")))
        entries.extend(part.document.get("advisories") or [])
        converted += part.converted
        skipped += part.skipped
        if part.converted:
            for bit in _norm(part.document.get("source")).split("+"):
                if bit:
                    sources.add(bit)
    return ConvertResult(_document(entries, sources), converted, skipped)

def dumps_converted(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"
