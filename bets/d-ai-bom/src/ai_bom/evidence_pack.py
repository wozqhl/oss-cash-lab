"""Local CRA Article 14 evidence pack: inventory + match, not a declaration.

Writes CycloneDX 1.7 JSON + SPDX 3.0.1 JSON + MANIFEST.md from an existing
scan and the existing exporters / license + advisory gates. Does not invent
CVEs, scores, or conformity badges.
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_bom.advisories import attach_advisory_hits, load_advisories, match_advisories_result
from ai_bom.export import dumps_export
from ai_bom.scanner import load_policy, scan_path

CDX_FILENAME = "bom.cdx.json"
SPDX3_FILENAME = "bom.spdx3.json"
MANIFEST_FILENAME = "MANIFEST.md"

DISCLAIMER = (
    "This pack is inventory + match evidence for CRA Article 14 "
    "(2026-09-11) orientation. It is not a CRA declaration, conformity "
    "claim, CE mark, or notified-body assessment."
)


def bet_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_policy_path() -> Path:
    return bet_root() / "policies" / "default.json"


def default_advisories_path() -> Path:
    return bet_root() / "examples" / "advisories" / "sample.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_optional_path(raw: str | None, default: Path) -> Path | None:
    """None → default if the file exists, else None. Empty string → skip."""
    if raw is None:
        return default if default.is_file() else None
    s = str(raw).strip()
    if not s:
        return None
    return Path(s)


def license_gate_exit(bom: dict[str, Any]) -> int:
    forbidden = (bom.get("summary") or {}).get("forbiddenLicenses") or []
    return 1 if forbidden else 0


def vuln_gate_exit(bom: dict[str, Any]) -> int:
    hits = (bom.get("summary") or {}).get("advisoryHits") or []
    return 1 if hits else 0


def render_manifest(
    *,
    timestamp: str,
    scan_dir: str,
    files: list[str],
    license_gate: int | None,
    vuln_gate: int | None,
    policy_path: str | None,
    advisories_path: str | None,
    zip_path: str | None = None,
) -> str:
    def _gate_cell(code: int | None) -> str:
        if code is None:
            return "skipped"
        return str(code)

    lines = [
        "# AI-BOM evidence pack",
        "",
        f"Generated: {timestamp}",
        f"Scan root: `{scan_dir}`",
        "",
        DISCLAIMER,
        "",
        "Gate exit 1 means a local fixture hit (forbidden license id, or an "
        "advisory identity/range in the file you passed). It is not an NVD/CVE "
        "score and is not a conformity result.",
        "",
        "## Files",
        "",
    ]
    for name in files:
        lines.append(f"- `{name}`")
    if zip_path:
        lines.append(f"- zip: `{zip_path}`")
    lines.extend(
        [
            "",
            "## Gates",
            "",
            "| Gate | Exit code | Input |",
            "|------|-----------|-------|",
            f"| license (`--gate-licenses`) | {_gate_cell(license_gate)} | `{policy_path or '—'}` |",
            f"| advisory (`--gate-vulns`) | {_gate_cell(vuln_gate)} | `{advisories_path or '—'}` |",
            "",
        ]
    )
    return "\n".join(lines)


@dataclass
class EvidencePackResult:
    outdir: Path | None
    zip_path: Path | None
    files: list[str] = field(default_factory=list)
    license_gate: int | None = None
    vuln_gate: int | None = None
    timestamp: str = ""
    scan_dir: str = ""
    policy_path: str | None = None
    advisories_path: str | None = None


def write_evidence_pack(
    scan_dir: Path,
    *,
    outdir: Path | None = None,
    zip_path: Path | None = None,
    policy_path: Path | None = None,
    advisories_path: Path | None = None,
    timestamp: str | None = None,
) -> EvidencePackResult:
    """Scan DIR and write CycloneDX 1.7 + SPDX 3.0.1 + MANIFEST.md.

    Gate codes are recorded in the manifest. This function does not raise on
    a license/advisory hit — those are the recorded exit codes, not a pack
    failure. IO / parse errors propagate to the caller.
    """
    if not scan_dir.exists():
        raise FileNotFoundError(f"path not found: {scan_dir}")
    if outdir is None and zip_path is None:
        raise ValueError("evidence-pack requires --out DIR and/or --zip [PATH]")

    policy = None
    policy_label: str | None = None
    if policy_path is not None:
        policy = load_policy(policy_path)
        policy_label = str(policy_path)

    bom = scan_path(scan_dir, policy=policy)

    vuln: int | None = None
    adv_label: str | None = None
    if advisories_path is not None:
        advisories = load_advisories(advisories_path)
        matched = match_advisories_result(bom.get("components") or [], advisories)
        bom = attach_advisory_hits(
            bom, matched.hits, range_skipped=matched.range_skipped
        )
        vuln = vuln_gate_exit(bom)
        adv_label = str(advisories_path)

    license_code: int | None = license_gate_exit(bom) if policy is not None else None
    ts = timestamp or _utc_now()

    cdx_text = dumps_export(bom, "cyclonedx")
    spdx3_text = dumps_export(bom, "spdx3")
    files = [CDX_FILENAME, SPDX3_FILENAME, MANIFEST_FILENAME]
    manifest = render_manifest(
        timestamp=ts,
        scan_dir=str(scan_dir),
        files=files,
        license_gate=license_code,
        vuln_gate=vuln,
        policy_path=policy_label,
        advisories_path=adv_label,
        zip_path=str(zip_path) if zip_path else None,
    )

    write_root = outdir
    tmp_root: Path | None = None
    if write_root is None:
        import tempfile

        tmp_root_ctx = tempfile.TemporaryDirectory()
        tmp_root = Path(tmp_root_ctx.name)
        write_root = tmp_root
    else:
        tmp_root_ctx = None
        write_root.mkdir(parents=True, exist_ok=True)

    try:
        cdx_p = write_root / CDX_FILENAME
        spdx3_p = write_root / SPDX3_FILENAME
        man_p = write_root / MANIFEST_FILENAME
        cdx_p.write_text(cdx_text, encoding="utf-8")
        spdx3_p.write_text(spdx3_text, encoding="utf-8")
        man_p.write_text(manifest, encoding="utf-8")

        if zip_path is not None:
            zip_path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.write(cdx_p, CDX_FILENAME)
                zf.write(spdx3_p, SPDX3_FILENAME)
                zf.write(man_p, MANIFEST_FILENAME)
    finally:
        if tmp_root_ctx is not None:
            tmp_root_ctx.cleanup()

    return EvidencePackResult(
        outdir=outdir,
        zip_path=zip_path,
        files=files,
        license_gate=license_code,
        vuln_gate=vuln,
        timestamp=ts,
        scan_dir=str(scan_dir),
        policy_path=policy_label,
        advisories_path=adv_label,
    )

