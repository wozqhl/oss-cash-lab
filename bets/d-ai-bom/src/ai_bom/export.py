"""BOM exporters: internal JSON (default), CycloneDX 1.7 JSON/XML, SPDX 2.3 JSON/XML, SARIF 2.1.0, Markdown summary, GHA annotations, HTML summary.

No extra deps. Valid enough that jq can read .bomFormat / .spdxVersion / .version.
The scan result (custom AI-BOM with summary) stays the internal model.
SARIF reuses scanner.to_sarif (same builder as CLI --sarif).
CycloneDX XML reuses to_cyclonedx (same components/licenses/properties).
SPDX XML reuses to_spdx (same packages/licenseConcluded).
Markdown (`md`) is a human/Slack summary of summary counts — not another SBOM spec.
GHA (`gha` / `annotations`) is GitHub Actions workflow commands (`::error` / `::notice`) — not an SBOM spec.
HTML (`html`) is a self-contained BOM summary (stdlib `html.escape`, inline CSS, no CDN) — not an SBOM spec.
"""
from __future__ import annotations

import html
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from ai_bom import __version__

FORMATS = ("json", "cyclonedx", "spdx", "sarif", "cyclonedx-xml", "spdx-xml", "md", "gha", "html")
DEFAULT_FORMAT = "json"
FORMAT_ALIASES = {"cdx-xml": "cyclonedx-xml", "spdxxml": "spdx-xml", "markdown": "md", "annotations": "gha"}
FORMATS_HELP = "json|cyclonedx|cyclonedx-xml|spdx|spdx-xml|sarif|md|gha|html"
FORMAT_CHOICES = (*FORMATS, *FORMAT_ALIASES)

JSON_CONTENT_TYPE = "application/json; charset=utf-8"
SARIF_CONTENT_TYPE = "application/sarif+json; charset=utf-8"
CDX_XML_CONTENT_TYPE = "application/vnd.cyclonedx+xml; charset=utf-8"
SPDX_XML_CONTENT_TYPE = "application/spdx+xml; charset=utf-8"
MD_CONTENT_TYPE = "text/markdown; charset=utf-8"
GHA_CONTENT_TYPE = "text/plain; charset=utf-8"
HTML_CONTENT_TYPE = "text/html; charset=utf-8"
CDX_XMLNS = "http://cyclonedx.org/schema/bom/1.7"

CDX_SPEC_VERSION = "1.7"
SPDX_VERSION = "SPDX-2.3"

_SPDX_REF_SAFE = re.compile(r"[^A-Za-z0-9.-]+")

# Internal component.type → CycloneDX 1.7 component type (ML-BOM since 1.5).
_CDX_TYPE = {
    "library": "library",
    "application": "application",
    "framework": "framework",
    "container": "container",
    "file": "file",
    "data": "data",
    "model": "machine-learning-model",
    "model-file": "machine-learning-model",
    "machine-learning-model": "machine-learning-model",
    "prompt": "data",
    "mcp-server": "application",
}


def normalize_format(raw: str | None) -> str | None:
    """Return json|cyclonedx|cyclonedx-xml|spdx|spdx-xml|sarif|md|gha|html. Empty/None → json. Unknown → None."""
    if raw is None:
        return DEFAULT_FORMAT
    s = str(raw).strip().lower()
    if not s:
        return DEFAULT_FORMAT
    if s in FORMAT_ALIASES:
        return FORMAT_ALIASES[s]
    if s in FORMATS:
        return s
    return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _root_name(bom: dict[str, Any]) -> str:
    meta = bom.get("metadata") or {}
    comp = meta.get("component") or {}
    name = str(comp.get("name") or "").strip()
    return name or "ai-bom-scan"


def _root_path(bom: dict[str, Any]) -> str:
    meta = bom.get("metadata") or {}
    comp = meta.get("component") or {}
    return str(comp.get("path") or "")


def _stable_uuid(bom: dict[str, Any], salt: str = "") -> uuid.UUID:
    key = f"https://github.com/wozqhl/oss-cash-lab/ai-bom/{_root_path(bom)}/{_root_name(bom)}/{salt}"
    return uuid.uuid5(uuid.NAMESPACE_URL, key)


def _cdx_type(raw: Any) -> str:
    t = str(raw or "").strip().lower()
    return _CDX_TYPE.get(t, "file")


def _license_concluded(licenses: list[Any] | None) -> str:
    """SPDX licenseConcluded from CycloneDX licenses[]. Honest: UNKNOWN → NOASSERTION."""
    if not licenses:
        return "NOASSERTION"
    for entry in licenses:
        if not isinstance(entry, dict):
            continue
        if entry.get("expression"):
            expr = str(entry.get("expression") or "").strip()
            if expr:
                return expr
        lic = entry.get("license") or {}
        if not isinstance(lic, dict):
            continue
        lid = str(lic.get("id") or "").strip()
        if lid:
            return lid
        name = str(lic.get("name") or "").strip()
        if name and name.upper() not in {"UNKNOWN", "NOASSERTION", "NONE"}:
            # Free-text is not an SPDX id; don't pretend.
            return "NOASSERTION"
        if name.upper() in {"NOASSERTION", "NONE"}:
            return name.upper() if name.upper() == "NONE" else "NOASSERTION"
    return "NOASSERTION"


def _basename(raw: Any) -> str:
    """Last path segment only — never an absolute host path in the CDX export."""
    s = str(raw or "").strip().replace("\\", "/")
    if not s:
        return ""
    return s.rstrip("/").split("/")[-1]


def _cdx_component(src: dict[str, Any], idx: int) -> dict[str, Any]:
    name = str(src.get("name") or f"component-{idx}")
    ctype = _cdx_type(src.get("type"))
    out: dict[str, Any] = {
        "type": ctype,
        "name": name,
    }
    version = src.get("version")
    if version not in (None, ""):
        out["version"] = str(version)
    purl = src.get("purl")
    if purl:
        out["purl"] = str(purl)
    bref = src.get("bom-ref") or purl or f"{out['type']}:{name}:{idx}"
    out["bom-ref"] = str(bref)
    licenses = src.get("licenses")
    if isinstance(licenses, list) and licenses:
        out["licenses"] = licenses
    else:
        out["licenses"] = [{"license": {"name": "UNKNOWN"}}]
    # ML-BOM fields the scanner already has. Do not invent architecture / datasets / metrics.
    if ctype == "machine-learning-model":
        card_props: list[dict[str, str]] = []
        fmt = src.get("format")
        if fmt not in (None, ""):
            card_props.append({"name": "aibom:format", "value": str(fmt)})
        src_name = _basename(src.get("path"))
        if src_name:
            card_props.append({"name": "aibom:sourcePath", "value": src_name})
        if card_props:
            out["modelCard"] = {"properties": card_props}
    if ctype == "data":
        data_entry: dict[str, Any] = {"type": "configuration", "name": name}
        src_name = _basename(src.get("path"))
        if src_name:
            data_entry["description"] = src_name
        out["data"] = [data_entry]
    return out


def to_cyclonedx(bom: dict[str, Any]) -> dict[str, Any]:
    """CycloneDX 1.7 JSON from the internal AI-BOM. No custom `summary`.

    Policy hits live in `properties` (`aibom:policyHits`), not `vulnerabilities`.
    Component licenses stay on each component.
    """
    summary = bom.get("summary") or {}
    meta = bom.get("metadata") or {}
    root = meta.get("component") or {}
    policy = meta.get("policy") or {}
    components_in = bom.get("components") or []
    serial = str(_stable_uuid(bom, "cdx"))
    props: list[dict[str, str]] = [
        {
            "name": "aibom:policyHits",
            "value": str(int(summary.get("policyHits") or 0)),
        }
    ]
    forbidden_licenses = summary.get("forbiddenLicenses") or []
    if forbidden_licenses:
        props.append(
            {
                "name": "aibom:forbiddenLicenses",
                "value": json.dumps(
                    forbidden_licenses, ensure_ascii=False, separators=(",", ":")
                ),
            }
        )
    waived = summary.get("waived") or []
    if waived:
        props.append(
            {
                "name": "aibom:waived",
                "value": json.dumps(waived, ensure_ascii=False, separators=(",", ":")),
            }
        )
    expired = summary.get("expiredExceptions") or []
    if expired:
        props.append(
            {
                "name": "aibom:expiredExceptions",
                "value": json.dumps(expired, ensure_ascii=False, separators=(",", ":")),
            }
        )
    forbidden = summary.get("forbidden") or []
    if forbidden:
        props.append(
            {
                "name": "aibom:forbiddenPatterns",
                "value": json.dumps(forbidden, ensure_ascii=False, separators=(",", ":")),
            }
        )
    if policy.get("name"):
        props.append({"name": "aibom:policyName", "value": str(policy.get("name"))})

    metadata: dict[str, Any] = {
        "timestamp": _utc_now(),
        "tools": {
            "components": [
                {
                    "type": "application",
                    "name": "ai-bom",
                    "version": __version__,
                }
            ]
        },
        "component": {
            "type": "application",
            "name": str(root.get("name") or _root_name(bom)),
            "bom-ref": "ai-bom-root",
        },
    }

    return {
        "$schema": f"http://cyclonedx.org/schema/bom-{CDX_SPEC_VERSION}.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": CDX_SPEC_VERSION,
        "serialNumber": f"urn:uuid:{serial}",
        "version": int(bom.get("version") or 1),
        "metadata": metadata,
        "components": [_cdx_component(c, i) for i, c in enumerate(components_in)],
        "properties": props,
    }


def _spdx_ref(kind: str, name: str, idx: int) -> str:
    raw = _SPDX_REF_SAFE.sub("-", str(name or "component")).strip("-") or "component"
    raw = raw[:64]
    return f"SPDXRef-{kind}-{idx}-{raw}"


def _extracted_license_id(label: str, idx: int) -> str:
    raw = _SPDX_REF_SAFE.sub("-", str(label or "unknown")).strip("-") or "unknown"
    return f"LicenseRef-aibom-{idx}-{raw[:48]}"


def to_spdx(bom: dict[str, Any]) -> dict[str, Any]:
    """SPDX 2.3 JSON from the internal AI-BOM.

    Packages get licenseConcluded from component licenses.
    Policy hits are comments + hasExtractedLicensingInfos (not pretended CVEs).
    """
    summary = bom.get("summary") or {}
    name = _root_name(bom)
    ns_uuid = _stable_uuid(bom, "spdx")
    namespace = (
        "https://github.com/wozqhl/oss-cash-lab/spdxdocs/"
        f"ai-bom-{quote(name, safe='')}-{ns_uuid}"
    )
    root_id = "SPDXRef-DOCUMENT"
    root_pkg_id = "SPDXRef-Package-root"
    packages: list[dict[str, Any]] = [
        {
            "SPDXID": root_pkg_id,
            "name": name,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "NOASSERTION",
            "copyrightText": "NOASSERTION",
            "comment": f"ai-bom scan root path={_root_path(bom) or '.'}",
        }
    ]
    for i, src in enumerate(bom.get("components") or []):
        if not isinstance(src, dict):
            continue
        cname = str(src.get("name") or f"component-{i}")
        licenses = src.get("licenses") if isinstance(src.get("licenses"), list) else []
        concluded = _license_concluded(licenses)
        pkg: dict[str, Any] = {
            "SPDXID": _spdx_ref("Package", cname, i),
            "name": cname,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": concluded,
            "licenseDeclared": concluded,
            "copyrightText": "NOASSERTION",
        }
        version = src.get("version")
        if version not in (None, ""):
            pkg["versionInfo"] = str(version)
        purl = src.get("purl")
        if purl:
            pkg["externalRefs"] = [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": str(purl),
                }
            ]
        ctype = src.get("type")
        if ctype:
            pkg["comment"] = f"ai-bom component type={ctype}"
        packages.append(pkg)

    extracted: list[dict[str, Any]] = []
    for i, hit in enumerate(summary.get("forbiddenLicenses") or []):
        if not isinstance(hit, dict):
            continue
        lid = str(hit.get("licenseId") or "UNKNOWN")
        extracted.append(
            {
                "licenseId": _extracted_license_id(lid, i),
                "extractedText": (
                    "ai-bom policy hit: forbidden license "
                    f"{lid} on component {hit.get('component') or hit.get('path') or '?'}"
                ),
                "name": f"Forbidden license {lid}",
                "comment": str(hit.get("message") or f"Forbidden license SPDX id: {lid}"),
            }
        )

    policy_hits = int(summary.get("policyHits") or 0)
    waived_n = len(summary.get("waived") or [])
    comment = (
        f"Generated by ai-bom {__version__}. "
        f"Internal AI-BOM summary.policyHits={policy_hits}"
        + (f" waived={waived_n}" if waived_n else "")
        + ". "
        "licenseConcluded is taken from scanned manifests; policy hits are not CVEs."
    )

    doc: dict[str, Any] = {
        "spdxVersion": SPDX_VERSION,
        "dataLicense": "CC0-1.0",
        "SPDXID": root_id,
        "name": f"ai-bom-{name}",
        "documentNamespace": namespace,
        "creationInfo": {
            "created": _utc_now(),
            "creators": [f"Tool: ai-bom-{__version__}"],
        },
        "packages": packages,
        "documentDescribes": [root_pkg_id],
        "comment": comment,
    }
    if extracted:
        doc["hasExtractedLicensingInfos"] = extracted
    return doc


def content_type_for(fmt: str | None = DEFAULT_FORMAT) -> str:
    """HTTP Content-Type for an export format (unknown → json)."""
    kind = normalize_format(fmt) or DEFAULT_FORMAT
    if kind == "sarif":
        return SARIF_CONTENT_TYPE
    if kind == "cyclonedx-xml":
        return CDX_XML_CONTENT_TYPE
    if kind == "spdx-xml":
        return SPDX_XML_CONTENT_TYPE
    if kind == "md":
        return MD_CONTENT_TYPE
    if kind == "gha":
        return GHA_CONTENT_TYPE
    if kind == "html":
        return HTML_CONTENT_TYPE
    return JSON_CONTENT_TYPE


def _xml_escape(text: Any) -> str:
    """Escape XML text/attribute content (`& < > "`)."""
    return html.escape("" if text is None else str(text), quote=True)


def _xml_elem(name: str, text: Any, indent: int) -> str:
    pad = "  " * indent
    return f"{pad}<{name}>{_xml_escape(text)}</{name}>\n"


def _xml_licenses(licenses: list[Any], indent: int) -> str:
    pad = "  " * indent
    inner = "  " * (indent + 1)
    parts = [f"{pad}<licenses>\n"]
    for entry in licenses:
        if not isinstance(entry, dict):
            continue
        expr = entry.get("expression")
        if expr not in (None, ""):
            parts.append(_xml_elem("expression", expr, indent + 1))
            continue
        lic = entry.get("license") or {}
        if not isinstance(lic, dict):
            continue
        parts.append(f"{inner}<license>\n")
        if lic.get("id") not in (None, ""):
            parts.append(_xml_elem("id", lic.get("id"), indent + 2))
        if lic.get("name") not in (None, ""):
            parts.append(_xml_elem("name", lic.get("name"), indent + 2))
        if lic.get("expression") not in (None, "") and not lic.get("id") and not lic.get("name"):
            parts.append(_xml_elem("expression", lic.get("expression"), indent + 2))
        parts.append(f"{inner}</license>\n")
    parts.append(f"{pad}</licenses>\n")
    return "".join(parts)


def _xml_component(comp: dict[str, Any], indent: int) -> str:
    pad = "  " * indent
    ctype = _xml_escape(comp.get("type") or "file")
    attrs = f'type="{ctype}"'
    bref = str(comp.get("bom-ref") or "").strip()
    if bref:
        attrs += f' bom-ref="{_xml_escape(bref)}"'
    parts = [f"{pad}<component {attrs}>\n"]
    parts.append(_xml_elem("name", comp.get("name") or "", indent + 1))
    if comp.get("version") not in (None, ""):
        parts.append(_xml_elem("version", comp.get("version"), indent + 1))
    if comp.get("purl"):
        parts.append(_xml_elem("purl", comp.get("purl"), indent + 1))
    licenses = comp.get("licenses")
    if isinstance(licenses, list) and licenses:
        parts.append(_xml_licenses(licenses, indent + 1))
    model_card = comp.get("modelCard")
    if isinstance(model_card, dict) and model_card:
        parts.append(f"{pad}  <modelCard>\n")
        mc_props = model_card.get("properties")
        if isinstance(mc_props, list) and mc_props:
            parts.append(_xml_properties(mc_props, indent + 2))
        parts.append(f"{pad}  </modelCard>\n")
    data_list = comp.get("data")
    if isinstance(data_list, list):
        for d in data_list:
            if not isinstance(d, dict):
                continue
            parts.append(f"{pad}  <data>\n")
            if d.get("type") not in (None, ""):
                parts.append(_xml_elem("type", d.get("type"), indent + 2))
            if d.get("name") not in (None, ""):
                parts.append(_xml_elem("name", d.get("name"), indent + 2))
            if d.get("description") not in (None, ""):
                parts.append(_xml_elem("description", d.get("description"), indent + 2))
            parts.append(f"{pad}  </data>\n")
    parts.append(f"{pad}</component>\n")
    return "".join(parts)


def _xml_properties(props: list[Any], indent: int) -> str:
    pad = "  " * indent
    parts = [f"{pad}<properties>\n"]
    for p in props:
        if not isinstance(p, dict):
            continue
        name = _xml_escape(p.get("name") or "")
        value = _xml_escape(p.get("value") if p.get("value") is not None else "")
        parts.append(f'{pad}  <property name="{name}">{value}</property>\n')
    parts.append(f"{pad}</properties>\n")
    return "".join(parts)


def to_cyclonedx_xml(bom: dict[str, Any]) -> str:
    """CycloneDX 1.7 XML from the same model as to_cyclonedx. No extra deps.

    Root is `<bom xmlns="http://cyclonedx.org/schema/bom/1.7" version="1" serialNumber=...>`.
    Empty scan still emits `<components>` (empty) and is valid XML.
    """
    cdx = to_cyclonedx(bom)
    version = int(cdx.get("version") or 1)
    serial = str(cdx.get("serialNumber") or "").strip()
    attrs = f'xmlns="{_xml_escape(CDX_XMLNS)}" version="{_xml_escape(version)}"'
    if serial:
        attrs += f' serialNumber="{_xml_escape(serial)}"'
    parts = [f"<bom {attrs}>\n"]

    meta = cdx.get("metadata") or {}
    parts.append("  <metadata>\n")
    ts = meta.get("timestamp")
    if ts:
        parts.append(_xml_elem("timestamp", ts, 2))
    tools = meta.get("tools") or {}
    tool_comps = tools.get("components") if isinstance(tools, dict) else None
    if isinstance(tool_comps, list) and tool_comps:
        parts.append("    <tools>\n")
        parts.append("      <components>\n")
        for tc in tool_comps:
            if isinstance(tc, dict):
                parts.append(_xml_component(tc, 4))
        parts.append("      </components>\n")
        parts.append("    </tools>\n")
    root = meta.get("component")
    if isinstance(root, dict) and root:
        parts.append(_xml_component(root, 2))
    parts.append("  </metadata>\n")

    parts.append("  <components>\n")
    for c in cdx.get("components") or []:
        if isinstance(c, dict):
            parts.append(_xml_component(c, 2))
    parts.append("  </components>\n")

    props = cdx.get("properties") or []
    if isinstance(props, list) and props:
        parts.append(_xml_properties(props, 1))

    parts.append("</bom>\n")
    return "".join(parts)



def _xml_spdx_package(pkg: dict[str, Any], indent: int) -> str:
    pad = "  " * indent
    parts = [f"{pad}<package>\n"]
    for key in (
        "SPDXID",
        "name",
        "versionInfo",
        "downloadLocation",
        "filesAnalyzed",
        "licenseConcluded",
        "licenseDeclared",
        "copyrightText",
        "comment",
    ):
        if key not in pkg and key != "licenseConcluded":
            continue
        if key == "filesAnalyzed":
            val = pkg.get(key)
            if val is None:
                continue
            parts.append(_xml_elem(key, "true" if val else "false", indent + 1))
            continue
        if key == "licenseConcluded":
            parts.append(_xml_elem(key, pkg.get(key) if pkg.get(key) not in (None, "") else "NOASSERTION", indent + 1))
            continue
        if pkg.get(key) not in (None, ""):
            parts.append(_xml_elem(key, pkg.get(key), indent + 1))
    refs = pkg.get("externalRefs")
    if isinstance(refs, list) and refs:
        inner = "  " * (indent + 1)
        ref_pad = "  " * (indent + 2)
        parts.append(f"{inner}<externalRefs>\n")
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            parts.append(f"{ref_pad}<externalRef>\n")
            for k in ("referenceCategory", "referenceType", "referenceLocator"):
                if ref.get(k) not in (None, ""):
                    parts.append(_xml_elem(k, ref.get(k), indent + 3))
            parts.append(f"{ref_pad}</externalRef>\n")
        parts.append(f"{inner}</externalRefs>\n")
    parts.append(f"{pad}</package>\n")
    return "".join(parts)


def _xml_spdx_extracted(info: dict[str, Any], indent: int) -> str:
    pad = "  " * indent
    parts = [f"{pad}<extractedLicensingInfo>\n"]
    for key in ("licenseId", "extractedText", "name", "comment"):
        if info.get(key) not in (None, ""):
            parts.append(_xml_elem(key, info.get(key), indent + 1))
    parts.append(f"{pad}</extractedLicensingInfo>\n")
    return "".join(parts)


def to_spdx_xml(bom: dict[str, Any]) -> str:
    """SPDX 2.3 XML from the same model as to_spdx. No extra deps.

    Root is `<SpdxDocument>` with `spdxVersion` SPDX-2.3, packages, licenseConcluded.
    Empty scan still emits `<packages>` and is valid XML.
    """
    doc = to_spdx(bom)
    parts = ["<SpdxDocument>\n"]
    parts.append(_xml_elem("spdxVersion", doc.get("spdxVersion") or SPDX_VERSION, 1))
    if doc.get("dataLicense") not in (None, ""):
        parts.append(_xml_elem("dataLicense", doc.get("dataLicense"), 1))
    if doc.get("SPDXID") not in (None, ""):
        parts.append(_xml_elem("SPDXID", doc.get("SPDXID"), 1))
    parts.append(_xml_elem("name", doc.get("name") or "", 1))
    if doc.get("documentNamespace"):
        parts.append(_xml_elem("documentNamespace", doc.get("documentNamespace"), 1))

    ci = doc.get("creationInfo") or {}
    if isinstance(ci, dict) and ci:
        parts.append("  <creationInfo>\n")
        if ci.get("created"):
            parts.append(_xml_elem("created", ci.get("created"), 2))
        for creator in ci.get("creators") or []:
            parts.append(_xml_elem("creators", creator, 2))
        parts.append("  </creationInfo>\n")

    parts.append("  <packages>\n")
    for pkg in doc.get("packages") or []:
        if isinstance(pkg, dict):
            parts.append(_xml_spdx_package(pkg, 2))
    parts.append("  </packages>\n")

    for desc in doc.get("documentDescribes") or []:
        parts.append(_xml_elem("documentDescribes", desc, 1))
    if doc.get("comment"):
        parts.append(_xml_elem("comment", doc.get("comment"), 1))

    extracted = doc.get("hasExtractedLicensingInfos") or []
    if isinstance(extracted, list) and extracted:
        parts.append("  <hasExtractedLicensingInfos>\n")
        for info in extracted:
            if isinstance(info, dict):
                parts.append(_xml_spdx_extracted(info, 2))
        parts.append("  </hasExtractedLicensingInfos>\n")

    parts.append("</SpdxDocument>\n")
    return "".join(parts)




def _md_cell(text: Any) -> str:
    """Escape GFM table cells. Collapse newlines; escape pipes. Never dump file contents."""
    s = "" if text is None else str(text)
    s = s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return s.replace("|", "\\|")


def _md_component_label(hit: dict[str, Any]) -> str:
    """Component name, else basename of path (no file contents)."""
    name = str(hit.get("component") or "").strip()
    if name:
        return name
    path = str(hit.get("path") or "").strip().replace("\\", "/")
    if not path:
        return ""
    return path.rstrip("/").split("/")[-1]


def to_markdown(bom: dict[str, Any]) -> str:
    """Human/Slack Markdown summary from the internal AI-BOM. Not an SBOM spec.

    Heading + component/policyHits/waived counts, license table, policy-hit table,
    waived (+ expired) tables. Empty scan still emits heading + zeros (HTTP 200).
    Never dumps file contents or secrets.
    """
    summary = bom.get("summary") or {}
    components = bom.get("components") or []
    n_comp = len(components)
    policy_hits = int(summary.get("policyHits") or 0)
    waived = [w for w in (summary.get("waived") or []) if isinstance(w, dict)]
    expired = [e for e in (summary.get("expiredExceptions") or []) if isinstance(e, dict)]
    licenses = summary.get("licenses") or {}
    if not isinstance(licenses, dict):
        licenses = {}
    forbidden = [h for h in (summary.get("forbidden") or []) if isinstance(h, dict)]
    gaps = [g for g in (summary.get("disclosureGaps") or []) if isinstance(g, dict)]
    forbidden_licenses = [
        h for h in (summary.get("forbiddenLicenses") or []) if isinstance(h, dict)
    ]

    lines: list[str] = [
        "# AI-BOM",
        "",
        f"**components:** {n_comp}  **policyHits:** {policy_hits}  **waived:** {len(waived)}",
        "",
        "## licenses",
        "",
        "| license | count |",
        "| --- | --- |",
    ]
    for k, n in licenses.items():
        lines.append(f"| {_md_cell(k)} | {_md_cell(n)} |")
    lines.extend(
        [
            "",
            "## policy hits",
            "",
            "| component | license | rule |",
            "| --- | --- | --- |",
        ]
    )
    for h in forbidden:
        rule = h.get("pattern") or h.get("id") or "forbidden"
        lines.append(
            f"| {_md_cell(_md_component_label(h))} |  | {_md_cell(rule)} |"
        )
    for g in gaps:
        rid = g.get("id") or g.get("check") or "gap"
        lines.append(
            f"| {_md_cell(rid)} |  | {_md_cell('disclosure/' + str(rid))} |"
        )
    for h in forbidden_licenses:
        lid = h.get("licenseId") or "UNKNOWN"
        rid = h.get("id") or f"license/{lid}"
        lines.append(
            f"| {_md_cell(_md_component_label(h))} | {_md_cell(lid)} | {_md_cell(rid)} |"
        )
    lines.extend(
        [
            "",
            "## waived",
            "",
            "| component | license | reason |",
            "| --- | --- | --- |",
        ]
    )
    for w in waived:
        lines.append(
            f"| {_md_cell(w.get('component') or '')} | {_md_cell(w.get('license') or '')} | {_md_cell(w.get('reason') or '')} |"
        )
    lines.extend(
        [
            "",
            "## expired",
            "",
            "| component | license | expires |",
            "| --- | --- | --- |",
        ]
    )
    for e in expired:
        lines.append(
            f"| {_md_cell(e.get('component') or '')} | {_md_cell(e.get('license') or '')} | {_md_cell(e.get('expires') or '')} |"
        )
    lines.append("")
    return "\n".join(lines)



def _gha_escape_data(text: Any) -> str:
    """Escape `%`, CR, LF in GitHub Actions workflow-command data."""
    s = "" if text is None else str(text)
    return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _gha_escape_property(text: Any) -> str:
    """Escape GHA property values (`:`, `,`, plus data escapes)."""
    return _gha_escape_data(text).replace(":", "%3A").replace(",", "%2C")


def _gha_line(kind: str, title: str, message: str) -> str:
    return (
        f"::{kind} title={_gha_escape_property(title)}::{_gha_escape_data(message)}"
    )


def to_gha(bom: dict[str, Any]) -> str:
    """GitHub Actions workflow commands for policy hits / forbidden licenses.

    Policy hit / forbidden license → `::error title=<component>::<license or rule>`.
    Waived hit → `::notice title=<component>::waived <reason>`.
    Clean scan → empty (no `::error`). Does not require GitHub.
    Same summary as SARIF / Markdown; `%` / CR / LF / `:` / `,` escaped like C `to_gha`.
    """
    summary = bom.get("summary") or {}
    forbidden = [h for h in (summary.get("forbidden") or []) if isinstance(h, dict)]
    gaps = [g for g in (summary.get("disclosureGaps") or []) if isinstance(g, dict)]
    forbidden_licenses = [
        h for h in (summary.get("forbiddenLicenses") or []) if isinstance(h, dict)
    ]
    waived = [w for w in (summary.get("waived") or []) if isinstance(w, dict)]

    lines: list[str] = []
    for h in forbidden:
        title = _md_component_label(h) or "component"
        rule = h.get("pattern") or h.get("id") or "forbidden"
        lines.append(_gha_line("error", title, str(rule)))
    for g in gaps:
        rid = str(g.get("id") or g.get("check") or "gap")
        lines.append(_gha_line("error", rid, f"disclosure/{rid}"))
    for h in forbidden_licenses:
        title = _md_component_label(h) or str(h.get("component") or "component")
        lid = h.get("licenseId") or "UNKNOWN"
        lines.append(_gha_line("error", title, str(lid)))
    for w in waived:
        title = str(w.get("component") or "").strip() or _md_component_label(w) or "component"
        reason = str(w.get("reason") or "").strip()
        msg = f"waived {reason}" if reason else "waived"
        lines.append(_gha_line("notice", title, msg))
    if not lines:
        return ""
    return "\n".join(lines) + "\n"



def _html_escape(text: Any) -> str:
    """Escape HTML text/attributes (`& < > "`)."""
    return html.escape("" if text is None else str(text), quote=True)


_HTML_STYLE = (
    "body{font-family:ui-sans-serif,system-ui,sans-serif;margin:2rem;color:#111;max-width:52rem}"
    "h1{font-size:1.25rem}"
    "h2{font-size:1.05rem;margin-top:1.5rem}"
    "table{border-collapse:collapse;margin:1rem 0;min-width:28rem}"
    "th,td{border:1px solid #ddd;padding:.4rem .6rem;text-align:left}"
    "th{background:#f5f5f5}"
    ".fail{color:#b00020;font-weight:700}"
    ".ok{color:#0a7a28}"
    ".meta{color:#555;font-size:.9rem}"
    ".stat{font-size:1.4rem;font-weight:600}"
    "code{background:#f4f4f4;padding:0.1rem 0.3rem}"
    "nav a{margin-right:1rem}"
)


def _html_comp_license(src: dict[str, Any]) -> str:
    licenses = src.get("licenses") if isinstance(src.get("licenses"), list) else []
    concluded = _license_concluded(licenses)
    if concluded and concluded != "NOASSERTION":
        return concluded
    for entry in licenses or []:
        if not isinstance(entry, dict):
            continue
        lic = entry.get("license") or {}
        if isinstance(lic, dict):
            name = str(lic.get("name") or "").strip()
            if name:
                return name
    return "UNKNOWN"


def to_html(bom: dict[str, Any], *, watch: bool = False, include_nav: bool = False) -> str:
    """Self-contained HTML BOM summary from the internal AI-BOM. Not an SBOM spec.

    Heading + component count, license table, policy hits / forbidden licenses
    (red if any). Empty scan still emits heading + zeros (HTTP 200).
    Names escaped (`& < > "`). No CDN / external CSS/JS.
    `include_nav` adds serve-index links (GET /); CLI / `/v1/bom.html` omit them.
    """
    summary = bom.get("summary") or {}
    meta = bom.get("metadata") or {}
    comp = meta.get("component") or {}
    policy = meta.get("policy") or {}
    components = [c for c in (bom.get("components") or []) if isinstance(c, dict)]
    n_comp = len(components)
    licenses = summary.get("licenses") or {}
    if not isinstance(licenses, dict):
        licenses = {}
    forbidden = [h for h in (summary.get("forbidden") or []) if isinstance(h, dict)]
    gaps = [g for g in (summary.get("disclosureGaps") or []) if isinstance(g, dict)]
    forbidden_licenses = [
        h for h in (summary.get("forbiddenLicenses") or []) if isinstance(h, dict)
    ]
    waived = [w for w in (summary.get("waived") or []) if isinstance(w, dict)]
    expired = [e for e in (summary.get("expiredExceptions") or []) if isinstance(e, dict)]
    policy_hits = int(
        summary.get("policyHits", len(forbidden) + len(gaps) + len(forbidden_licenses)) or 0
    )
    name = _html_escape(str(comp.get("name") or ""))
    path = _html_escape(str(comp.get("path") or ""))
    policy_name = _html_escape(str(policy.get("name") or "(built-in)"))
    policy_ver = _html_escape(str(policy.get("version") or ""))
    policy_label = policy_name if not policy_ver else f"{policy_name} v{policy_ver}"
    hit_cls = "fail" if policy_hits else "ok"

    lic_rows = []
    for k, n in licenses.items():
        lic_rows.append(
            f"<tr><td><code>{_html_escape(k)}</code></td>"
            f"<td>{_html_escape(n)}</td></tr>"
        )
    lic_tbody = "\n".join(lic_rows) + ("\n" if lic_rows else "")

    comp_rows = []
    for c in components:
        comp_rows.append(
            "<tr>"
            f"<td><code>{_html_escape(c.get('name') or '')}</code></td>"
            f"<td>{_html_escape(c.get('type') or '')}</td>"
            f"<td>{_html_escape(c.get('version') or '')}</td>"
            f"<td><code>{_html_escape(_html_comp_license(c))}</code></td>"
            "</tr>"
        )
    comp_tbody = "\n".join(comp_rows) + ("\n" if comp_rows else "")

    hit_rows = []
    for h in forbidden:
        hit_rows.append(
            '<tr class="fail"><td>forbidden</td>'
            f"<td><code>{_html_escape(h.get('pattern') or h.get('id') or '')}</code></td>"
            f"<td><code>{_html_escape(_md_component_label(h) or h.get('path') or '')}</code></td></tr>"
        )
    for g in gaps:
        rid = g.get("id") or g.get("check") or "gap"
        hit_rows.append(
            '<tr class="fail"><td>disclosure</td>'
            f"<td><code>{_html_escape(rid)}</code></td>"
            f"<td>{_html_escape(g.get('description_en') or g.get('detail') or '')}</td></tr>"
        )
    for h in forbidden_licenses:
        hit_rows.append(
            '<tr class="fail"><td>license</td>'
            f"<td><code>{_html_escape(h.get('licenseId') or 'UNKNOWN')}</code></td>"
            f"<td><code>{_html_escape(_md_component_label(h) or h.get('path') or '')}</code></td></tr>"
        )
    for w in waived:
        hit_rows.append(
            "<tr><td>waived</td>"
            f"<td><code>{_html_escape(w.get('license') or '')}</code></td>"
            f"<td><code>{_html_escape(w.get('component') or '')}</code> {_html_escape(w.get('reason') or '')}</td></tr>"
        )
    hits_tbody = "\n".join(hit_rows) + ("\n" if hit_rows else "")
    hits_empty = "<p><em>No policy hits.</em></p>\n" if not hit_rows else ""

    nav = ""
    if include_nav:
        nav = """<nav>
  <a href="/bom.json">bom.json</a>
  <a href="/v1/bom">v1/bom</a>
  <a href="/v1/bom?format=cyclonedx">cyclonedx</a>
  <a href="/v1/bom?format=cyclonedx-xml">cyclonedx-xml</a>
  <a href="/v1/bom?format=spdx">spdx</a>
  <a href="/v1/bom?format=spdx-xml">spdx-xml</a>
  <a href="/v1/bom?format=sarif">sarif</a>
  <a href="/v1/bom.md">md</a>
  <a href="/v1/bom.gha.txt">gha</a>
  <a href="/v1/bom.html">html</a>
  <a href="/v1/policy">v1/policy</a>
  <a href="/v1/config">v1/config</a>
  <a href="/evidence.md">evidence.md</a>
  <a href="/health">health</a>
  <a href="/ready">ready</a>
  <a href="/openapi.json">openapi.json</a>
  <a href="/metrics">metrics</a>
</nav>
"""

    snap = "snapshot (watch)" if watch else "snapshot at process start"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AI-BOM · local summary</title>
<style>
{_HTML_STYLE}
</style>
</head>
<body>
<h1>AI-BOM local summary</h1>
<p class="meta">OSS local serve · hosted inventory = paid · self-contained HTML · no CDN</p>
{nav}<p>Target: <code>{name}</code> @ <code>{path}</code><br>
Policy: <code>{policy_label}</code></p>
<h2>Component count</h2>
<p class="stat">{n_comp}</p>
<table>
<thead><tr><th>name</th><th>type</th><th>version</th><th>license</th></tr></thead>
<tbody>
{comp_tbody}</tbody>
</table>
<h2>License summary</h2>
<table>
<thead><tr><th>License</th><th>Count</th></tr></thead>
<tbody>
{lic_tbody}</tbody>
</table>
<h2 class="{hit_cls}">Policy hits</h2>
<p class="stat {hit_cls}">{policy_hits}</p>
<p class="meta">forbidden={len(forbidden)} · disclosure gaps={len(gaps)} · forbidden licenses={len(forbidden_licenses)} · waived={len(waived)} · expired exceptions={len(expired)}</p>
{hits_empty}<table>
<thead><tr><th>Kind</th><th>Id</th><th>Where</th></tr></thead>
<tbody>
{hits_tbody}</tbody>
</table>
<p class="meta">Generated by ai-bom {_html_escape(__version__)} · {snap}</p>
</body>
</html>
"""


def dumps_export(bom: dict[str, Any], fmt: str | None = DEFAULT_FORMAT) -> str:
    """Serialize BOM as json (internal), cyclonedx, cyclonedx-xml, spdx, spdx-xml, sarif, md, gha, or html. Raises ValueError on bad fmt."""
    kind = normalize_format(fmt)
    if kind is None:
        raise ValueError(f"unsupported format (use {FORMATS_HELP})")
    if kind == "cyclonedx":
        return json.dumps(to_cyclonedx(bom), indent=2, ensure_ascii=False) + "\n"
    if kind == "cyclonedx-xml":
        return to_cyclonedx_xml(bom)
    if kind == "spdx":
        return json.dumps(to_spdx(bom), indent=2, ensure_ascii=False) + "\n"
    if kind == "spdx-xml":
        return to_spdx_xml(bom)
    if kind == "sarif":
        from ai_bom.scanner import dumps_sarif, to_sarif

        return dumps_sarif(to_sarif(bom, tool_version=__version__))
    if kind == "md":
        return to_markdown(bom)
    if kind == "gha":
        return to_gha(bom)
    if kind == "html":
        return to_html(bom)
    from ai_bom.scanner import dumps_bom

    return dumps_bom(bom)
