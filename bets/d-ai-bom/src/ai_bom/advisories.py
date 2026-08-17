"""Offline advisory fixture match (known-vuln vs scanned components).

Conservative: local JSON only. No NVD / OSV / GitHub Advisory fetch.
IDs in shipped fixtures are ADV-FIXTURE-* placeholders, not real CVEs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


SCHEMA_ID = "ai-bom-advisories/v1"


def _warn(msg: str) -> None:
    try:
        sys.stderr.write(f"ai-bom: {msg}\n")
        sys.stderr.flush()
    except OSError:
        pass


def _norm(raw: Any) -> str:
    return str(raw or "").strip()


def parse_purl(purl: str) -> dict[str, str]:
    """Split a Package URL into type / name / version (best-effort, no network)."""
    s = _norm(purl)
    empty = {"raw": s, "type": "", "name": "", "version": ""}
    if not s.lower().startswith("pkg:"):
        return empty
    rest = s[4:]
    if "/" not in rest:
        return {"raw": s, "type": rest.lower(), "name": "", "version": ""}
    typ, namever = rest.split("/", 1)
    version = ""
    name = namever
    if namever.startswith("@"):
        last_at = namever.rfind("@")
        if last_at > 0:
            name = namever[:last_at]
            version = namever[last_at + 1 :]
    elif "@" in namever:
        name, version = namever.rsplit("@", 1)
    return {
        "raw": s,
        "type": typ.lower(),
        "name": name.lower(),
        "version": version,
    }


def purl_identity_matches(advisory_purl: str, component_purl: str) -> bool:
    """Match package identity. Versioned advisory does not match unversioned component."""
    a = parse_purl(advisory_purl)
    c = parse_purl(component_purl)
    if not a["type"] or not a["name"] or not c["type"] or not c["name"]:
        left = _norm(advisory_purl).lower()
        right = _norm(component_purl).lower()
        return bool(left) and left == right
    if a["type"] != c["type"] or a["name"] != c["name"]:
        return False
    if a["version"]:
        return bool(c["version"]) and a["version"] == c["version"]
    return True


def _normalize_advisory(item: Any, idx: int) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(item, dict):
        return None, f"skipping advisory #{idx}: not an object"
    aid = _norm(item.get("id"))
    if not aid:
        return None, f"skipping advisory #{idx}: missing id"
    raw_comp = item.get("component")
    if not isinstance(raw_comp, dict):
        return None, f"skipping advisory {aid}: component must be an object"
    name = _norm(raw_comp.get("name"))
    purl = _norm(raw_comp.get("purl"))
    version = _norm(raw_comp.get("version"))
    if not name and not purl:
        return None, f"skipping advisory {aid}: component needs name or purl"
    return {
        "id": aid,
        "name": name,
        "purl": purl,
        "version": version,
        "severity": _norm(item.get("severity")) or "medium",
        "summary": _norm(item.get("summary")),
    }, None


def load_advisories(path: Path) -> list[dict[str, Any]]:
    """Load a local advisory fixture. Missing/invalid file raises (CLI → exit 2)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        raw_list = data
    elif isinstance(data, dict):
        raw_list = data.get("advisories")
        if raw_list is None:
            raise ValueError("advisories file must contain an 'advisories' array")
        if not isinstance(raw_list, list):
            raise ValueError("advisories must be an array")
    else:
        raise ValueError("advisories file must be a JSON object or array")
    out: list[dict[str, Any]] = []
    for i, item in enumerate(raw_list):
        entry, warn = _normalize_advisory(item, i)
        if warn:
            _warn(warn)
        if entry:
            out.append(entry)
    return out


def _component_matches(comp: dict[str, Any], adv: dict[str, Any]) -> bool:
    """AND of every identity field the advisory specifies."""
    cname = _norm(comp.get("name"))
    cver = _norm(comp.get("version"))
    cpurl = _norm(comp.get("purl") or comp.get("bom-ref"))
    if adv["name"]:
        if cname.lower() != adv["name"].lower():
            return False
    if adv["purl"]:
        if not cpurl or not purl_identity_matches(adv["purl"], cpurl):
            return False
    if adv["version"]:
        if not cver or cver != adv["version"]:
            return False
    return True


def match_advisories(
    components: list[dict[str, Any]] | None,
    advisories: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Return fixture hits. Deduped by (advisory id, component name, purl, path)."""
    hits: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for adv in advisories or []:
        if not isinstance(adv, dict):
            continue
        for comp in components or []:
            if not isinstance(comp, dict):
                continue
            if not _component_matches(comp, adv):
                continue
            name = _norm(comp.get("name"))
            purl = _norm(comp.get("purl") or comp.get("bom-ref"))
            path = _norm(comp.get("path"))
            key = (str(adv.get("id") or ""), name, purl, path)
            if key in seen:
                continue
            seen.add(key)
            hits.append(
                {
                    "id": adv.get("id") or "",
                    "component": name,
                    "version": _norm(comp.get("version")) or adv.get("version") or "",
                    "purl": purl,
                    "path": path,
                    "severity": adv.get("severity") or "medium",
                    "summary": adv.get("summary") or "",
                }
            )
    return hits


def attach_advisory_hits(bom: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    """Record hits on BOM summary. Does not change policyHits."""
    summary = dict(bom.get("summary") or {})
    summary["advisoryHits"] = list(hits)
    summary["advisoryHitCount"] = len(hits)
    out = dict(bom)
    out["summary"] = summary
    return out
