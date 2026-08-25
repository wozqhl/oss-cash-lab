"""Local CRA Article 14 evidence pack: inventory + match, not a declaration.

Writes CycloneDX 1.7 JSON + SPDX 3.0.1 JSON + MANIFEST.md + pack.json from an
existing scan and the existing exporters / license + advisory gates. pack.json
includes a calendar window clock (days-until / days-overdue vs 2026-09-11 and
2027-12-11). Does not invent CVEs, scores, or conformity badges. The clock is a
calendar/evidence helper, not a CRA compliance certificate.
"""
from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from ai_bom.advisories import attach_advisory_hits, load_advisories, match_advisories_result
from ai_bom.export import dumps_export
from ai_bom.scanner import load_policy, scan_path

CDX_FILENAME = "bom.cdx.json"
SPDX3_FILENAME = "bom.spdx3.json"
MANIFEST_FILENAME = "MANIFEST.md"
PACK_FILENAME = "pack.json"

# Published CRA calendar dates (orientation only — not a legal determination).
ARTICLE14_DATE = date(2026, 9, 11)
SBOM_DATE = date(2027, 12, 11)

DISCLAIMER = (
    "This pack is inventory + match evidence for CRA Article 14 "
    "(2026-09-11) orientation. It is not a CRA declaration, conformity "
    "claim, CE mark, or notified-body assessment."
)
DISCLAIMER_ZH = (
    "本包是面向 CRA 第 14 条（2026-09-11）的库存+对照证据。"
    "不是 CRA 声明、符合性主张、CE 标志或公告机构评定。"
)
CLOCK_DISCLAIMER_EN = (
    "This is a calendar/evidence helper, not a CRA compliance certificate, "
    "conformity claim, CE mark, or notified-body assessment."
)
CLOCK_DISCLAIMER_ZH = (
    "这是日历/证据辅助，不是 CRA 合格证书、符合性声明、CE 标志或公告机构评定。"
)
CLOCK_NOTE_EN = (
    "daysUntil/daysOverdue are calendar offsets from asOf to the published "
    "CRA orientation dates. Not a reporting-obligation determination, NVD "
    "score, or conformity result."
)
CLOCK_NOTE_ZH = (
    "daysUntil/daysOverdue 是相对 asOf 到已公布 CRA 导向日期的日历差。"
    "不是报告义务判定、NVD 评分或符合性结论。"
)


def bet_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_policy_path() -> Path:
    return bet_root() / "policies" / "default.json"


def default_advisories_path() -> Path:
    return bet_root() / "examples" / "advisories" / "sample.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_as_of(raw: str | date | datetime | None, timestamp: str | None = None) -> date:
    """UTC calendar date for the window clock. Date-only; no invented timezone."""
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    if raw is not None and str(raw).strip():
        s = str(raw).strip()
        try:
            return date.fromisoformat(s[:10])
        except ValueError as e:
            raise ValueError(f"as-of must be YYYY-MM-DD, got {raw!r}") from e
    if timestamp:
        try:
            return date.fromisoformat(str(timestamp).strip()[:10])
        except ValueError as e:
            raise ValueError(f"timestamp date prefix must be YYYY-MM-DD, got {timestamp!r}") from e
    return datetime.now(timezone.utc).date()


def compute_window(as_of: date, target: date) -> dict[str, Any]:
    """daysUntil / daysOverdue vs a calendar date. Same-day → due (both 0)."""
    delta = (target - as_of).days
    if delta > 0:
        status = "until"
        days_until, days_overdue = delta, 0
    elif delta == 0:
        status = "due"
        days_until, days_overdue = 0, 0
    else:
        status = "overdue"
        days_until, days_overdue = 0, -delta
    return {
        "date": target.isoformat(),
        "daysUntil": days_until,
        "daysOverdue": days_overdue,
        "status": status,
    }


def _window_slice(win: dict[str, Any]) -> dict[str, Any]:
    return {
        "date": win["date"],
        "daysUntil": win["daysUntil"],
        "daysOverdue": win["daysOverdue"],
        "status": win["status"],
    }


def build_cra_clock(
    as_of: date,
    hits: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Machine-readable CRA window clock from observed advisory hits.

    Calendar math only. Does not invent CVSS, exploitability, or a duty to
    report. Observed vulns inherit the same published dates (not per-CVE SLAs).
    """
    article14 = {
        "id": "article-14",
        "labelEn": "Article 14-style vulnerability reporting clock",
        "labelZh": "第14条风格漏洞报告窗口",
        **compute_window(as_of, ARTICLE14_DATE),
    }
    sbom = {
        "id": "sbom",
        "labelEn": "CRA-oriented SBOM calendar date",
        "labelZh": "面向 CRA 的 SBOM 日历日期",
        **compute_window(as_of, SBOM_DATE),
    }
    observed: list[dict[str, Any]] = []
    for hit in hits or []:
        if not isinstance(hit, dict):
            continue
        aid = str(hit.get("id") or "").strip()
        if not aid:
            continue
        observed.append(
            {
                "id": aid,
                "component": str(hit.get("component") or ""),
                "version": str(hit.get("version") or ""),
                "windows": {
                    "article14Reporting": _window_slice(article14),
                    "sbom": _window_slice(sbom),
                },
            }
        )
    return {
        "schema": "ai-bom-cra-clock/v1",
        "kind": "calendar-helper",
        "disclaimerEn": CLOCK_DISCLAIMER_EN,
        "disclaimerZh": CLOCK_DISCLAIMER_ZH,
        "noteEn": CLOCK_NOTE_EN,
        "noteZh": CLOCK_NOTE_ZH,
        "asOf": as_of.isoformat(),
        "windows": {
            "article14Reporting": article14,
            "sbom": sbom,
        },
        "observedVulnCount": len(observed),
        "observedVulns": observed,
    }


def build_pack_document(
    *,
    timestamp: str,
    scan_dir: str,
    files: list[str],
    license_gate: int | None,
    vuln_gate: int | None,
    policy_path: str | None,
    advisories_path: str | None,
    clock: dict[str, Any],
    zip_path: str | None = None,
) -> dict[str, Any]:
    return {
        "schema": "ai-bom-evidence-pack/v1",
        "kind": "inventory-match-evidence",
        "disclaimerEn": DISCLAIMER + " " + CLOCK_DISCLAIMER_EN,
        "disclaimerZh": DISCLAIMER_ZH + CLOCK_DISCLAIMER_ZH,
        "generated": timestamp,
        "scanRoot": scan_dir,
        "files": list(files),
        "zip": zip_path,
        "gates": {
            "license": license_gate,
            "advisory": vuln_gate,
            "policyPath": policy_path,
            "advisoriesPath": advisories_path,
        },
        "clock": clock,
    }


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
    clock: dict[str, Any] | None = None,
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
        DISCLAIMER_ZH,
        "",
        CLOCK_DISCLAIMER_EN,
        CLOCK_DISCLAIMER_ZH,
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
    if clock:
        windows = clock.get("windows") or {}
        a14 = windows.get("article14Reporting") or {}
        sbom = windows.get("sbom") or {}
        lines.extend(
            [
                "## CRA window clock (calendar helper / 日历辅助)",
                "",
                CLOCK_DISCLAIMER_EN,
                CLOCK_DISCLAIMER_ZH,
                "",
                f"asOf: `{clock.get('asOf') or ''}`",
                f"observedVulnCount: {clock.get('observedVulnCount', 0)}",
                "",
                "| Window | Date | daysUntil | daysOverdue | status |",
                "|--------|------|-----------|-------------|--------|",
                (
                    f"| article-14 reporting | `{a14.get('date') or ARTICLE14_DATE.isoformat()}` | "
                    f"{a14.get('daysUntil', '')} | {a14.get('daysOverdue', '')} | "
                    f"{a14.get('status') or ''} |"
                ),
                (
                    f"| SBOM | `{sbom.get('date') or SBOM_DATE.isoformat()}` | "
                    f"{sbom.get('daysUntil', '')} | {sbom.get('daysOverdue', '')} | "
                    f"{sbom.get('status') or ''} |"
                ),
                "",
                CLOCK_NOTE_EN,
                CLOCK_NOTE_ZH,
                "",
            ]
        )
        vulns = clock.get("observedVulns") or []
        if vulns:
            lines.extend(["Observed fixture vulns (same calendar windows; not CVE scores):", ""])
            for hit in vulns:
                if not isinstance(hit, dict):
                    continue
                w = (hit.get("windows") or {}).get("article14Reporting") or {}
                lines.append(
                    f"- `{hit.get('id')}` {hit.get('component') or ''} "
                    f"article14 daysUntil={w.get('daysUntil')} "
                    f"daysOverdue={w.get('daysOverdue')}"
                )
            lines.append("")
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
    clock: dict[str, Any] = field(default_factory=dict)
    pack: dict[str, Any] = field(default_factory=dict)


def write_evidence_pack(
    scan_dir: Path,
    *,
    outdir: Path | None = None,
    zip_path: Path | None = None,
    policy_path: Path | None = None,
    advisories_path: Path | None = None,
    timestamp: str | None = None,
    as_of: str | date | datetime | None = None,
) -> EvidencePackResult:
    """Scan DIR and write CycloneDX 1.7 + SPDX 3.0.1 + MANIFEST.md + pack.json.

    Gate codes are recorded in the manifest / pack.json. The clock section is a
    calendar helper (days-until / days-overdue vs 2026-09-11 and 2027-12-11),
    not a CRA certificate. This function does not raise on a license/advisory
    hit — those are the recorded exit codes, not a pack failure. IO / parse
    errors propagate to the caller.
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
    hits: list[dict[str, Any]] = []
    if advisories_path is not None:
        advisories = load_advisories(advisories_path)
        matched = match_advisories_result(bom.get("components") or [], advisories)
        bom = attach_advisory_hits(
            bom, matched.hits, range_skipped=matched.range_skipped
        )
        hits = list(matched.hits)
        vuln = vuln_gate_exit(bom)
        adv_label = str(advisories_path)

    license_code: int | None = license_gate_exit(bom) if policy is not None else None
    ts = timestamp or _utc_now()
    as_of_date = parse_as_of(as_of, ts)
    clock = build_cra_clock(as_of_date, hits)

    cdx_text = dumps_export(bom, "cyclonedx")
    spdx3_text = dumps_export(bom, "spdx3")
    files = [CDX_FILENAME, SPDX3_FILENAME, MANIFEST_FILENAME, PACK_FILENAME]
    pack = build_pack_document(
        timestamp=ts,
        scan_dir=str(scan_dir),
        files=files,
        license_gate=license_code,
        vuln_gate=vuln,
        policy_path=policy_label,
        advisories_path=adv_label,
        clock=clock,
        zip_path=str(zip_path) if zip_path else None,
    )
    manifest = render_manifest(
        timestamp=ts,
        scan_dir=str(scan_dir),
        files=files,
        license_gate=license_code,
        vuln_gate=vuln,
        policy_path=policy_label,
        advisories_path=adv_label,
        zip_path=str(zip_path) if zip_path else None,
        clock=clock,
    )
    pack_text = json.dumps(pack, indent=2, ensure_ascii=False) + "\n"

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
        pack_p = write_root / PACK_FILENAME
        cdx_p.write_text(cdx_text, encoding="utf-8")
        spdx3_p.write_text(spdx3_text, encoding="utf-8")
        man_p.write_text(manifest, encoding="utf-8")
        pack_p.write_text(pack_text, encoding="utf-8")

        if zip_path is not None:
            zip_path.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.write(cdx_p, CDX_FILENAME)
                zf.write(spdx3_p, SPDX3_FILENAME)
                zf.write(man_p, MANIFEST_FILENAME)
                zf.write(pack_p, PACK_FILENAME)
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
        clock=clock,
        pack=pack,
    )
