"""OpenVEX 0.2.0 from observed local advisory matches.

Generated only from scanned components vs a local fixture. Status is derived:
affected (real identity/range hit), not_affected (range excludes observed
version, and only when the fixture recorded a justification or impact_statement),
under_investigation (range excludes / unparseable and no recorded justification),
fixed only when the fixture literally records a fixedVersion equal to the
observed version.

Not a CRA conformity claim, NVD feed, or exploitability oracle.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from ai_bom.advisories import (
    _identity_matches,
    _norm,
    version_in_range,
)

OPENVEX_CONTEXT = "https://openvex.dev/ns/v0.2.0"
OPENVEX_SPEC = "0.2.0"
OPENVEX_AUTHOR = "ai-bom"
VEX_FILENAME = "vex.json"

# OpenVEX 0.2.0 status justifications (verified labels only).
JUSTIFICATIONS = frozenset(
    {
        "component_not_present",
        "vulnerable_code_not_present",
        "vulnerable_code_not_in_execute_path",
        "vulnerable_code_cannot_be_controlled_by_adversary",
        "inline_mitigations_already_exist",
    }
)

STATUSES = frozenset({"not_affected", "affected", "fixed", "under_investigation"})

AFFECTED_ACTION = (
    "Local advisory fixture match on the observed component. "
    "The fixture recorded no remediation. Not an NVD/CVE fix."
)

VEX_DISCLAIMER_EN = (
    "OpenVEX is an exploitability statement helper for Article 14-style "
    "reporting from local fixture matches. It is not a CRA conformity claim, "
    "CE mark, or notified-body assessment."
)
VEX_DISCLAIMER_ZH = (
    "OpenVEX 是面向第 14 条风格报告的可利用性声明辅助，来自本地 fixture 对照。"
    "不是 CRA 符合性主张、CE 标志或公告机构评定。"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def recorded_justification(adv: dict[str, Any]) -> str:
    raw = _norm(adv.get("justification"))
    return raw if raw in JUSTIFICATIONS else ""


def recorded_impact_statement(adv: dict[str, Any]) -> str:
    return _norm(adv.get("impact_statement"))


def recorded_action_statement(adv: dict[str, Any]) -> str:
    return _norm(adv.get("action_statement"))


def recorded_fixed_version(adv: dict[str, Any]) -> str:
    return _norm(adv.get("fixedVersion"))


def recorded_aliases(adv: dict[str, Any]) -> list[str]:
    raw = adv.get("aliases")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        s = _norm(item)
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _product_from_component(comp: dict[str, Any]) -> dict[str, Any] | None:
    """OpenVEX product from a scanned component. Omit rather than invent CPE."""
    purl = _norm(comp.get("purl") or comp.get("bom-ref"))
    product: dict[str, Any] = {}
    if purl.lower().startswith("pkg:"):
        product["@id"] = purl
        product["identifiers"] = {"purl": purl}
    else:
        return None
    sha = _norm(comp.get("sha256"))
    if sha:
        product["hashes"] = {"sha-256": sha}
    return product


def derive_status(
    comp: dict[str, Any],
    adv: dict[str, Any],
) -> tuple[str, dict[str, str]] | None:
    """Return (status, extra fields) or None when this is not an observed match.

    Extra keys are only those the OpenVEX statement should carry
    (justification / impact_statement / action_statement / status_notes).
    """
    extra: dict[str, str] = {}
    cver = _norm(comp.get("version"))
    fixed = recorded_fixed_version(adv)
    if fixed and cver and cver == fixed:
        return "fixed", extra

    rng = _norm(adv.get("versionRange"))
    exact = _norm(adv.get("version"))
    justification = recorded_justification(adv)
    impact = recorded_impact_statement(adv)

    if rng:
        hit = version_in_range(cver, rng)
        if hit is True:
            action = recorded_action_statement(adv) or AFFECTED_ACTION
            extra["action_statement"] = action
            return "affected", extra
        notes = ""
        if hit is False:
            notes = (
                "Recorded versionRange excludes observed version "
                + (cver or "(none)")
                + "."
            )
        else:
            notes = "Recorded versionRange is unparseable; status not determined."
        extra["status_notes"] = notes
        if hit is False and (justification or impact):
            if justification:
                extra["justification"] = justification
            if impact:
                extra["impact_statement"] = impact
            return "not_affected", extra
        return "under_investigation", extra

    if exact:
        if not cver or cver != exact:
            return None
    action = recorded_action_statement(adv) or AFFECTED_ACTION
    extra["action_statement"] = action
    return "affected", extra


def _statement_sort_key(stmt: dict[str, Any]) -> tuple[str, str, str]:
    vuln = stmt.get("vulnerability") or {}
    name = str(vuln.get("name") or "")
    status = str(stmt.get("status") or "")
    products = stmt.get("products") or []
    pid = ""
    if products and isinstance(products[0], dict):
        pid = str(products[0].get("@id") or "")
    return (name, status, pid)


def observe_vex_statements(
    components: list[dict[str, Any]] | None,
    advisories: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """One OpenVEX statement per (advisory, status) with products the scanner saw."""
    grouped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    product_seen: dict[tuple[str, str, str, str, str], set[str]] = {}

    for adv in advisories or []:
        if not isinstance(adv, dict):
            continue
        aid = _norm(adv.get("id"))
        if not aid:
            continue
        for comp in components or []:
            if not isinstance(comp, dict):
                continue
            if not _identity_matches(comp, adv):
                continue
            derived = derive_status(comp, adv)
            if derived is None:
                continue
            status, extra = derived
            product = _product_from_component(comp)
            if product is None:
                continue
            key = (
                aid,
                status,
                extra.get("justification") or "",
                extra.get("impact_statement") or "",
                extra.get("status_notes") or "",
            )
            bucket = grouped.get(key)
            if bucket is None:
                vuln: dict[str, Any] = {"name": aid}
                summary = _norm(adv.get("summary"))
                if summary:
                    vuln["description"] = summary
                aliases = recorded_aliases(adv)
                if aliases:
                    vuln["aliases"] = aliases
                stmt: dict[str, Any] = {
                    "vulnerability": vuln,
                    "products": [],
                    "status": status,
                }
                for field in (
                    "justification",
                    "impact_statement",
                    "action_statement",
                    "status_notes",
                ):
                    if extra.get(field):
                        stmt[field] = extra[field]
                grouped[key] = stmt
                product_seen[key] = set()
                bucket = stmt
            pid = str(product.get("@id") or "")
            if pid in product_seen[key]:
                continue
            product_seen[key].add(pid)
            bucket["products"].append(product)

    statements = list(grouped.values())
    for stmt in statements:
        stmt["products"].sort(key=lambda p: str((p or {}).get("@id") or ""))
    statements.sort(key=_statement_sort_key)
    return statements


def _document_id(statements: list[dict[str, Any]], author: str) -> str:
    payload = json.dumps(
        {"author": author, "statements": statements},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return "https://openvex.dev/docs/public/ai-bom-vex-" + digest


def build_openvex_document(
    components: list[dict[str, Any]] | None,
    advisories: list[dict[str, Any]] | None,
    *,
    timestamp: str | None = None,
    author: str = OPENVEX_AUTHOR,
) -> dict[str, Any]:
    """OpenVEX 0.2.0 document. Empty statements when nothing was observed."""
    statements = observe_vex_statements(components, advisories)
    ts = timestamp or _utc_now()
    author_s = _norm(author) or OPENVEX_AUTHOR
    return {
        "@context": OPENVEX_CONTEXT,
        "@id": _document_id(statements, author_s),
        "author": author_s,
        "timestamp": ts,
        "version": 1,
        "tooling": "ai-bom",
        "statements": statements,
    }


def dumps_openvex(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"

def check_openvex_fixtures(components: list[dict[str, Any]], load_adv) -> str | None:
    """Semantic checks against shipped fixtures. load_adv(path) -> rows. None = ok."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    adv_dir = root / "examples" / "advisories"
    sample_rows = load_adv(adv_dir / "sample.json")
    sample_doc = build_openvex_document(
        components, sample_rows, timestamp="2026-08-26T00:00:00Z"
    )
    if sample_doc.get("@context") != OPENVEX_CONTEXT:
        return f"context {sample_doc.get('@context')}"
    if sample_doc.get("author") != OPENVEX_AUTHOR:
        return f"author {sample_doc.get('author')}"
    if sample_doc.get("timestamp") != "2026-08-26T00:00:00Z":
        return f"timestamp {sample_doc.get('timestamp')}"
    if sample_doc.get("version") != 1:
        return f"version {sample_doc.get('version')}"
    sid = str(sample_doc.get("@id") or "")
    if not sid.startswith("https://openvex.dev/docs/public/ai-bom-vex-"):
        return f"document id {sid}"
    again = build_openvex_document(
        components, sample_rows, timestamp="2026-08-27T00:00:00Z"
    )
    if again.get("@id") != sample_doc.get("@id"):
        return "document id not stable"
    stmts = sample_doc.get("statements") or []
    if not isinstance(stmts, list) or len(stmts) < 3:
        return f"sample statements {len(stmts) if isinstance(stmts, list) else stmts}"
    names = sorted(
        str((s.get("vulnerability") or {}).get("name") or "")
        for s in stmts
        if isinstance(s, dict)
    )
    for want in ("ADV-FIXTURE-1", "ADV-FIXTURE-2", "ADV-FIXTURE-3"):
        if want not in names:
            return f"missing {want} in {names}"
    statuses = {s.get("status") for s in stmts if isinstance(s, dict)}
    if statuses != {"affected"}:
        return f"sample statuses {statuses}"
    for s in stmts:
        if not isinstance(s, dict):
            continue
        if not (s.get("vulnerability") or {}).get("name"):
            return f"statement missing vuln name {s}"
        products = s.get("products") or []
        if not products:
            return f"statement missing products {s}"
        for prod in products:
            if not isinstance(prod, dict):
                return f"bad product {prod}"
            pid = str(prod.get("@id") or "")
            if not pid.startswith("pkg:"):
                return f"product @id not a purl {pid}"
            ident = prod.get("identifiers") or {}
            if ident.get("purl") != pid:
                return f"product identifiers.purl {ident}"
        if not s.get("action_statement"):
            return f"affected missing action_statement {s}"
        if "CVE-20" in json.dumps(s):
            return "invented CVE in sample VEX"

    in_st = (build_openvex_document(components, load_adv(adv_dir / "range-in.json")).get("statements") or [])
    if not in_st or any(s.get("status") != "affected" for s in in_st):
        return f"range-in statuses {[s.get('status') for s in in_st]}"
    out_st = (build_openvex_document(components, load_adv(adv_dir / "range-out.json")).get("statements") or [])
    if not out_st:
        return "range-out produced no statement for identity match"
    if any(s.get("status") in {"affected", "fixed"} for s in out_st):
        return f"range-out must not be affected/fixed {[s.get('status') for s in out_st]}"
    if any(s.get("status") != "under_investigation" for s in out_st):
        return f"range-out without justification should be under_investigation {[s.get('status') for s in out_st]}"
    if any(s.get("justification") for s in out_st):
        return "range-out invented justification"
    skip_st = (build_openvex_document(components, load_adv(adv_dir / "range-skip.json")).get("statements") or [])
    if skip_st and any(s.get("status") != "under_investigation" for s in skip_st):
        return f"range-skip {[s.get('status') for s in skip_st]}"
    clean_st = (build_openvex_document(components, load_adv(adv_dir / "clean.json")).get("statements") or [])
    if clean_st:
        return f"clean fixture should not emit statements {clean_st}"
    return None
