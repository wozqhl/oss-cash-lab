"""Offline advisory fixture match (known-vuln vs scanned components).

Conservative: local JSON only. No NVD / OSV / GitHub Advisory fetch.
IDs in shipped fixtures are ADV-FIXTURE-* placeholders, not real CVEs.

versionRange (when present) is evaluated with recorded operators only
(>= > < <= = and comma/AND). Unparseable ranges never invent a hit.
Exact component.version / versions[] matching is unchanged.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_ID = "ai-bom-advisories/v1"

_RANGE_OP_RE = re.compile(r"^(>=|<=|==|=|>|<)\s*(\S+)$")
_OSV_EVENT_RE = re.compile(
    r"\b(introduced|fixed|last_affected|limit)\s*:\s*(\S+)",
    re.I,
)
_AND_SPLIT_RE = re.compile(r"\s*,\s*|\s+AND\s+", re.I)


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


def parse_dotted_version(raw: str) -> tuple[int, ...] | None:
    """Dotted numeric version only. Refuse pre-releases / junk (no invented compare)."""
    s = _norm(raw)
    if s[:1] in ("v", "V") and len(s) > 1 and s[1].isdigit():
        s = s[1:]
    if not s:
        return None
    parts = s.split(".")
    out: list[int] = []
    for part in parts:
        if not part.isdigit():
            return None
        out.append(int(part))
    return tuple(out)


def compare_versions(left: str, right: str) -> int | None:
    a = parse_dotted_version(left)
    b = parse_dotted_version(right)
    if a is None or b is None:
        return None
    n = max(len(a), len(b))
    a = a + (0,) * (n - len(a))
    b = b + (0,) * (n - len(b))
    if a > b:
        return 1
    if a < b:
        return -1
    return 0


def _op_holds(cmp_val: int, op: str) -> bool:
    if op in (">=",):
        return cmp_val >= 0
    if op == ">":
        return cmp_val > 0
    if op in ("<=",):
        return cmp_val <= 0
    if op == "<":
        return cmp_val < 0
    if op in ("=", "=="):
        return cmp_val == 0
    return False


def _clauses_from_osv_events(expr: str) -> list[tuple[str, str]] | None:
    """Recorded converter event text: introduced:X fixed:Y (AND). ';' is multiple ranges → skip."""
    if "||" in expr:
        return None
    groups = [g.strip() for g in expr.split(";") if g.strip()]
    if len(groups) != 1:
        return None
    found = list(_OSV_EVENT_RE.finditer(groups[0]))
    if not found:
        return None
    # leftover junk besides events / spaces → unparseable
    stripped = _OSV_EVENT_RE.sub(" ", groups[0])
    if re.search(r"[^\s]", stripped):
        return None
    clauses: list[tuple[str, str]] = []
    for m in found:
        key = m.group(1).lower()
        ver = m.group(2)
        if parse_dotted_version(ver) is None:
            return None
        if key == "introduced":
            clauses.append((">=", ver))
        elif key in ("fixed", "limit"):
            clauses.append(("<", ver))
        elif key == "last_affected":
            clauses.append(("<=", ver))
        else:
            return None
    return clauses or None


def parse_version_range(expr: str) -> list[tuple[str, str]] | None:
    """AND clauses as (op, version). None = unparseable (do not match)."""
    raw = _norm(expr)
    if not raw:
        return None
    if "||" in raw:
        return None
    if _OSV_EVENT_RE.search(raw):
        return _clauses_from_osv_events(raw)
    chunks = [c.strip() for c in _AND_SPLIT_RE.split(raw) if c.strip()]
    if not chunks:
        return None
    clauses: list[tuple[str, str]] = []
    for chunk in chunks:
        m = _RANGE_OP_RE.match(chunk)
        if not m:
            return None
        op, ver = m.group(1), m.group(2)
        if parse_dotted_version(ver) is None:
            return None
        clauses.append((op, ver))
    return clauses


def version_in_range(version: str, expr: str) -> bool | None:
    """True/False when the range is evaluable; None if the range cannot be parsed."""
    clauses = parse_version_range(expr)
    if clauses is None:
        return None
    ver = _norm(version)
    if not ver or parse_dotted_version(ver) is None:
        return False
    for op, bound in clauses:
        cmp_val = compare_versions(ver, bound)
        if cmp_val is None:
            return False
        if not _op_holds(cmp_val, op):
            return False
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
    version_range = _norm(raw_comp.get("versionRange"))
    if not name and not purl:
        return None, f"skipping advisory {aid}: component needs name or purl"
    return {
        "id": aid,
        "name": name,
        "purl": purl,
        "version": version,
        "versionRange": version_range,
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


def _identity_matches(comp: dict[str, Any], adv: dict[str, Any]) -> bool:
    """AND of name / purl the advisory specifies (version handled separately)."""
    cname = _norm(comp.get("name"))
    cpurl = _norm(comp.get("purl") or comp.get("bom-ref"))
    if adv["name"]:
        if cname.lower() != adv["name"].lower():
            return False
    if adv["purl"]:
        if not cpurl or not purl_identity_matches(adv["purl"], cpurl):
            return False
    return True


def _component_matches(comp: dict[str, Any], adv: dict[str, Any]) -> bool:
    """AND of every identity field the advisory specifies, plus evaluable ranges."""
    if not _identity_matches(comp, adv):
        return False
    cver = _norm(comp.get("version"))
    if adv["version"]:
        if not cver or cver != adv["version"]:
            return False
    rng = _norm(adv.get("versionRange"))
    if rng:
        hit = version_in_range(cver, rng)
        if hit is not True:
            return False
    return True


@dataclass(frozen=True)
class AdvisoryMatchResult:
    hits: list[dict[str, Any]]
    range_skipped: int


def match_advisories_result(
    components: list[dict[str, Any]] | None,
    advisories: list[dict[str, Any]] | None,
) -> AdvisoryMatchResult:
    """Return fixture hits + count of unparseable versionRange rows (no invented hits)."""
    hits: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    skipped = 0
    for adv in advisories or []:
        if not isinstance(adv, dict):
            continue
        rng = _norm(adv.get("versionRange"))
        range_evaluable = True
        if rng:
            if parse_version_range(rng) is None:
                skipped += 1
                _warn(f"skipping advisory {adv.get('id') or '?'}: unparseable versionRange")
                range_evaluable = False
                if not _norm(adv.get("version")):
                    continue
        match_adv = adv
        if rng and not range_evaluable:
            # exact versions[] still applies; ignore the unparseable range
            match_adv = dict(adv)
            match_adv["versionRange"] = ""
        for comp in components or []:
            if not isinstance(comp, dict):
                continue
            if not _component_matches(comp, match_adv):
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
    return AdvisoryMatchResult(hits, skipped)


def match_advisories(
    components: list[dict[str, Any]] | None,
    advisories: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Return fixture hits. Deduped by (advisory id, component name, purl, path)."""
    return match_advisories_result(components, advisories).hits


def attach_advisory_hits(
    bom: dict[str, Any],
    hits: list[dict[str, Any]],
    range_skipped: int = 0,
) -> dict[str, Any]:
    """Record hits on BOM summary. Does not change policyHits."""
    summary = dict(bom.get("summary") or {})
    summary["advisoryHits"] = list(hits)
    summary["advisoryHitCount"] = len(hits)
    summary["advisoryRangeSkipped"] = int(range_skipped)
    out = dict(bom)
    out["summary"] = summary
    return out
