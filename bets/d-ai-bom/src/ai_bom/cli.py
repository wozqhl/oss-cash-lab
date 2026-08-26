"""CLI for ai-bom.

Exit codes:
  0  success (no --strict / --gate-licenses / --gate-vulns violations)
     evidence-pack: pack written (gate codes recorded in MANIFEST.md)
  1  --strict: forbidden pattern hits, disclosure gaps, and/or forbidden licenses
     --gate-licenses: forbidden licenses only (CI license-policy gate)
     --gate-vulns: local advisory fixture hits (offline; not NVD)
  2  usage / IO / policy parse error
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from ai_bom import __version__
from ai_bom.advisories import (
    attach_advisory_hits,
    load_advisories,
    match_advisories,
    match_advisories_result,
    parse_purl,
    purl_identity_matches,
)
from ai_bom.osv_convert import convert_files, convert_record, dumps_converted
from ai_bom.evidence_pack import (
    ARTICLE14_DATE,
    CDX_FILENAME,
    MANIFEST_FILENAME,
    PACK_FILENAME,
    SBOM_DATE,
    SPDX3_FILENAME,
    build_cra_clock,
    default_advisories_path,
    default_policy_path,
    resolve_optional_path,
    write_evidence_pack,
)
from ai_bom.vex import (
    OPENVEX_CONTEXT,
    VEX_FILENAME,
    build_openvex_document,
    dumps_openvex,
)
from ai_bom.scanner import (
    COMPONENTS_LIST_CAP,
    ENV_EXCEPTIONS,
    EXCEPTIONS_FILENAME,
    EXCEPTIONS_LIST_CAP,
    bom_without_exceptions,
    build_policy_gate,
    component_name_matches,
    dumps_bom,
    dumps_sarif,
    exceptions_json,
    exceptions_query_skips,
    list_components,
    load_exceptions_file,
    load_policy,
    parse_ignore_arg,
    render_evidence,
    resolve_exceptions_path,
    scan_path,
    sha256_file,
    to_sarif,
)
from ai_bom.export import (
    DEFAULT_FORMAT,
    FORMAT_CHOICES,
    FORMATS,
    FORMATS_HELP,
    dumps_export,
    normalize_format,
    to_cyclonedx,
    to_cyclonedx_xml,
    to_gha,
    to_html,
    to_markdown,
    to_spdx,
    to_spdx3,
    to_spdx_xml,
)
from ai_bom.cors import (
    DEFAULT_CORS_EXPOSE_HEADERS,
    DEFAULT_CORS_HEADERS,
    DEFAULT_CORS_METHODS,
    ENV_CORS_ORIGINS,
    acao_value,
    cors_response_headers,
    handle_preflight,
    normalize_cors,
    origin_allowed,
    parse_cors_origins,
    resolve_cors_origins,
)
from ai_bom.rate_limit import (
    DEFAULT_RATE_LIMIT_PER_MINUTE,
    ENV_RATE_LIMIT_PER_MINUTE,
    ENV_RATE_LIMIT_RPM,
    SlidingWindowRateLimiter,
    client_ip_from_headers,
    resolve_rate_limit,
    skip_rate_limit,
)
from ai_bom.metrics import (
    CONTENT_TYPE as METRICS_CONTENT_TYPE,
    METRIC_COMPONENT_COUNT,
    METRIC_FORBIDDEN_LICENSES,
    METRIC_POLICY_HITS,
    render_metrics,
)
from ai_bom.request_id import (
    is_uuid,
    resolve_request_id,
    sanitize_request_id,
)
from ai_bom.access_log import (
    format_access_log,
    resolve_log_json,
    should_skip_access_log,
)
from ai_bom.serve import (
    DEFAULT_SERVE_HOST,
    DEFAULT_SERVE_PORT,
    WATCH_POLL_MS,
    DEFAULT_SHUTDOWN_DRAIN_MS,
    MAX_SHUTDOWN_DRAIN_MS,
    begin_shutdown,
    build_snapshot,
    create_bom_server,
    load_serve_policy,
    parse_serve_ignore,
    resolve_drain_ms,
    serve_forever,
    walk_max_mtime,
)
from ai_bom.webhook import (
    DEFAULT_RETRY_DELAY_S,
    DEFAULT_TIMEOUT_S,
    ENV_WEBHOOK_SECRET,
    ENV_WEBHOOK_URL,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    build_webhook_payload,
    notify_policy_hit,
    parse_webhook_url,
    post_policy_webhook,
    resolve_webhook_secret,
    resolve_webhook_url,
    should_notify_policy_hit,
    should_retry_webhook,
    sign_webhook_body,
    verify_webhook_signature,
    webhook_unix_seconds,
)


def _load_policy_arg(policy_path: str | None):
    if not policy_path:
        return None, None
    try:
        return load_policy(Path(policy_path)), None
    except OSError as e:
        return None, f"policy IO error: {e}"
    except (ValueError, json.JSONDecodeError) as e:
        return None, f"policy parse error: {e}"



def _run_convert_advisories(args) -> int:
    paths = [Path(x) for x in (getattr(args, "paths", None) or [])]
    if not paths:
        print("convert-advisories requires one or more OSV/GHSA JSON files")
        return 2
    out = getattr(args, "out", None)
    if not out:
        print("convert-advisories requires --out <file>")
        return 2
    try:
        result = convert_files(paths)
    except OSError as e:
        print(f"convert-advisories IO error: {e}")
        return 2
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"convert-advisories parse error: {e}")
        return 2
    outp = Path(out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(dumps_converted(result.document), encoding="utf-8")
    print(f"wrote {outp} converted={result.converted} skipped={result.skipped}")
    return 0


def _run_evidence_pack(args) -> int:
    scan_dir = Path(getattr(args, "dir", None) or "")
    if not scan_dir or not str(scan_dir):
        print("evidence-pack requires --dir DIR")
        return 2
    if not scan_dir.exists():
        print(f"path not found: {scan_dir}")
        return 2
    out_raw = getattr(args, "out", None)
    zip_raw = getattr(args, "zip_path", None)
    if out_raw is None and zip_raw is None:
        print("evidence-pack requires --out DIR and/or --zip [PATH]")
        return 2
    outdir = Path(out_raw) if out_raw else None
    zip_path = None
    if zip_raw is not None:
        if zip_raw == "":
            zip_path = (outdir.parent / f"{outdir.name}.zip") if outdir else Path("evidence-pack.zip")
        else:
            zip_path = Path(zip_raw)
    try:
        policy_path = resolve_optional_path(getattr(args, "policy", None), default_policy_path())
        advisories_path = resolve_optional_path(
            getattr(args, "advisories", None), default_advisories_path()
        )
        if getattr(args, "policy", None) and policy_path is not None and not policy_path.is_file():
            print(f"policy not found: {policy_path}")
            return 2
        if getattr(args, "advisories", None) and advisories_path is not None and not advisories_path.is_file():
            print(f"advisories not found: {advisories_path}")
            return 2
        result = write_evidence_pack(
            scan_dir,
            outdir=outdir,
            zip_path=zip_path,
            policy_path=policy_path,
            advisories_path=advisories_path,
            as_of=getattr(args, "as_of", None),
        )
    except OSError as e:
        print(f"evidence-pack IO error: {e}")
        return 2
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"evidence-pack parse error: {e}")
        return 2
    if result.outdir:
        for name in result.files:
            print(f"wrote {result.outdir / name}")
    if result.zip_path:
        print(f"wrote {result.zip_path}")
    lic = result.license_gate if result.license_gate is not None else "skipped"
    vul = result.vuln_gate if result.vuln_gate is not None else "skipped"
    print(f"license-gate={lic} vuln-gate={vul}")
    clock = result.clock or {}
    windows = clock.get("windows") or {}
    a14 = windows.get("article14Reporting") or {}
    sbom = windows.get("sbom") or {}
    print(
        f"cra-clock asOf={clock.get('asOf')} "
        f"article14 daysUntil={a14.get('daysUntil')} daysOverdue={a14.get('daysOverdue')} "
        f"sbom daysUntil={sbom.get('daysUntil')} daysOverdue={sbom.get('daysOverdue')} "
        f"observedVulns={clock.get('observedVulnCount', 0)}"
    )
    return 0


def _smoke_vex() -> str | None:
    from ai_bom.vex_recorded import smoke_vex_cli
    return smoke_vex_cli(main, load_advisories)

def _smoke_evidence_pack() -> str | None:
    """Write pack for sample-app + CRA fixtures; assert three artifacts. None = ok."""
    root = Path(__file__).resolve().parents[2]
    sample_app = root / "examples" / "sample-app"
    fixtures = root / "examples" / "cra-fixtures"
    policy = root / "policies" / "default.json"
    clean = root / "examples" / "advisories" / "clean.json"
    sample_adv = root / "examples" / "advisories" / "sample.json"
    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)
        sample_out = td_p / "sample-pack"
        rc = main([
            "evidence-pack",
            "--dir", str(sample_app),
            "--out", str(sample_out),
            "--policy", str(policy),
            "--advisories", str(sample_adv),
        ])
        if rc != 0:
            return f"sample-app pack exit {rc}"
        cdx_p = sample_out / CDX_FILENAME
        spdx3_p = sample_out / SPDX3_FILENAME
        man_p = sample_out / MANIFEST_FILENAME
        pack_p = sample_out / PACK_FILENAME
        if not (cdx_p.is_file() and spdx3_p.is_file() and man_p.is_file() and pack_p.is_file()):
            return f"sample-app missing artifacts {[p.name for p in (cdx_p, spdx3_p, man_p, pack_p) if not p.is_file()]}"
        try:
            cdx = json.loads(cdx_p.read_text(encoding="utf-8"))
            spdx3 = json.loads(spdx3_p.read_text(encoding="utf-8"))
        except Exception as e:
            return f"sample-app pack parse {e}"
        if cdx.get("bomFormat") != "CycloneDX" or cdx.get("specVersion") != "1.7":
            return f"sample-app cyclonedx {cdx.get('bomFormat')} {cdx.get('specVersion')}"
        if (spdx3.get("creationInfo") or {}).get("specVersion") != "3.0.1":
            return f"sample-app spdx3 {(spdx3.get('creationInfo') or {}).get('specVersion')}"
        man = man_p.read_text(encoding="utf-8")
        if "inventory + match evidence" not in man or "not a CRA declaration" not in man:
            return "sample-app MANIFEST missing disclaimer"
        low = man.lower()
        if "compliant" in low or "certified" in low:
            return "sample-app MANIFEST invented conformity badge"
        if "Generated:" not in man or "license (`--gate-licenses`)" not in man:
            return "sample-app MANIFEST missing timestamp/gates"
        pass_out = td_p / "pass-pack"
        pass_rc = main([
            "evidence-pack",
            "--dir", str(fixtures / "license-pass"),
            "--out", str(pass_out),
            "--policy", str(policy),
            "--advisories", str(clean),
        ])
        if pass_rc != 0:
            return f"license-pass pack exit {pass_rc}"
        if not all((pass_out / n).is_file() for n in (CDX_FILENAME, SPDX3_FILENAME, MANIFEST_FILENAME, PACK_FILENAME)):
            return "license-pass missing artifacts"
        fail_out = td_p / "fail-pack"
        fail_rc = main([
            "evidence-pack",
            "--dir", str(fixtures / "license-fail"),
            "--out", str(fail_out),
            "--policy", str(policy),
            "--advisories", str(clean),
        ])
        if fail_rc != 0:
            return f"license-fail pack exit {fail_rc}"
        if not all((fail_out / n).is_file() for n in (CDX_FILENAME, SPDX3_FILENAME, MANIFEST_FILENAME, PACK_FILENAME)):
            return "license-fail missing artifacts"
        fail_man = (fail_out / MANIFEST_FILENAME).read_text(encoding="utf-8")
        if "| license (`--gate-licenses`) | 1 |" not in fail_man:
            return f"license-fail gate not recorded as 1: {fail_man}"
        pass_man = (pass_out / MANIFEST_FILENAME).read_text(encoding="utf-8")
        if "| license (`--gate-licenses`) | 0 |" not in pass_man:
            return f"license-pass gate not recorded as 0: {pass_man}"
        zip_path = td_p / "pack.zip"
        zip_rc = main([
            "evidence-pack",
            "--dir", str(sample_app),
            "--zip", str(zip_path),
            "--policy", str(policy),
            "--advisories", str(clean),
        ])
        if zip_rc != 0 or not zip_path.is_file():
            return f"zip pack exit {zip_rc} exists={zip_path.is_file()}"
        import zipfile
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
        want = {CDX_FILENAME, SPDX3_FILENAME, MANIFEST_FILENAME, PACK_FILENAME}
        if not want <= names:
            return f"zip missing {want - names}"
        miss_rc = main(["evidence-pack", "--dir", str(sample_app)])
        if miss_rc != 2:
            return f"missing --out/--zip exit {miss_rc}"
    return None


_OBS_CARD = """# Observed Tiny Model

A fixture description only.

License: https://example.com/observed-license
"""



def _smoke_cra_clock() -> str | None:
    """Clock fields + fixture vuln window (frozen as-of). None = ok."""
    from datetime import date

    hits = [{"id": "ADV-FIXTURE-1", "component": "ai-bom-sample-app", "version": "0.0.1"}]
    early = build_cra_clock(date(2026, 8, 26), hits)
    a14 = (early.get("windows") or {}).get("article14Reporting") or {}
    sbom = (early.get("windows") or {}).get("sbom") or {}
    if a14.get("date") != ARTICLE14_DATE.isoformat() or sbom.get("date") != SBOM_DATE.isoformat():
        return f"frozen dates {a14.get('date')} {sbom.get('date')}"
    if a14.get("daysUntil") != 16 or a14.get("daysOverdue") != 0 or a14.get("status") != "until":
        return f"2026-08-26 article14 {a14}"
    if sbom.get("daysUntil") != (SBOM_DATE - date(2026, 8, 26)).days or sbom.get("daysOverdue") != 0:
        return f"2026-08-26 sbom {sbom}"
    if early.get("observedVulnCount") != 1:
        return f"observed count {early.get('observedVulnCount')}"
    ov = (early.get("observedVulns") or [None])[0] or {}
    ow = (ov.get("windows") or {}).get("article14Reporting") or {}
    if ov.get("id") != "ADV-FIXTURE-1" or ow.get("daysUntil") != 16:
        return f"fixture vuln window {ov}"
    late = build_cra_clock(date(2026, 9, 20), hits)
    late_a = (late.get("windows") or {}).get("article14Reporting") or {}
    if late_a.get("daysUntil") != 0 or late_a.get("daysOverdue") != 9 or late_a.get("status") != "overdue":
        return f"overdue article14 {late_a}"
    due = build_cra_clock(date(2026, 9, 11), hits)
    due_a = (due.get("windows") or {}).get("article14Reporting") or {}
    if due_a.get("status") != "due" or due_a.get("daysUntil") != 0 or due_a.get("daysOverdue") != 0:
        return f"due article14 {due_a}"
    blob = json.dumps(early, ensure_ascii=False).lower()
    if "compliant" in blob or "certified" in blob or "conformity certificate" in blob:
        return "clock invented conformity language"
    if "calendar/evidence helper" not in (early.get("disclaimerEn") or "").lower():
        return "missing EN helper disclaimer"
    if "日历" not in (early.get("disclaimerZh") or "") or "合格证书" not in (early.get("disclaimerZh") or ""):
        return "missing ZH helper disclaimer"

    root = Path(__file__).resolve().parents[2]
    sample_app = root / "examples" / "sample-app"
    policy = root / "policies" / "default.json"
    sample_adv = root / "examples" / "advisories" / "sample.json"
    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)
        out = td_p / "clock-pack"
        zip_path = td_p / "clock-pack.zip"
        rc = main([
            "evidence-pack",
            "--dir", str(sample_app),
            "--out", str(out),
            "--zip", str(zip_path),
            "--policy", str(policy),
            "--advisories", str(sample_adv),
            "--as-of", "2026-08-26",
        ])
        if rc != 0:
            return f"clock pack exit {rc}"
        pack_p = out / PACK_FILENAME
        if not pack_p.is_file():
            return "pack.json missing"
        try:
            pack = json.loads(pack_p.read_text(encoding="utf-8"))
        except Exception as e:
            return f"pack.json parse {e}"
        clock = pack.get("clock") or {}
        if clock.get("schema") != "ai-bom-cra-clock/v1":
            return f"clock schema {clock.get('schema')}"
        if clock.get("kind") != "calendar-helper":
            return f"clock kind {clock.get('kind')}"
        if clock.get("asOf") != "2026-08-26":
            return f"clock asOf {clock.get('asOf')}"
        ca = (clock.get("windows") or {}).get("article14Reporting") or {}
        if ca.get("daysUntil") != 16 or ca.get("date") != "2026-09-11":
            return f"pack article14 {ca}"
        vulns = clock.get("observedVulns") or []
        fixture = next((v for v in vulns if isinstance(v, dict) and str(v.get("id") or "").startswith("ADV-FIXTURE-")), None)
        if not fixture:
            return f"no fixture vuln in clock {vulns}"
        fw = (fixture.get("windows") or {}).get("article14Reporting") or {}
        if not isinstance(fw.get("daysUntil"), int) or not isinstance(fw.get("daysOverdue"), int):
            return f"fixture window not computed {fixture}"
        if fw.get("daysUntil") != 16:
            return f"fixture window daysUntil {fw}"
        man = (out / MANIFEST_FILENAME).read_text(encoding="utf-8")
        if "calendar/evidence helper" not in man.lower() or "日历/证据辅助" not in man:
            return "MANIFEST missing bilingual clock disclaimer"
        if "compliant" in man.lower() or "certified" in man.lower():
            return "MANIFEST invented conformity badge"
        import zipfile
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())
        if PACK_FILENAME not in names:
            return f"zip missing {PACK_FILENAME}: {names}"
        raw = zipfile.ZipFile(zip_path).read(PACK_FILENAME)
        zpack = json.loads(raw.decode("utf-8"))
        if not (zpack.get("clock") or {}).get("observedVulns"):
            return "zip pack.json clock missing observedVulns"
    return None


def _smoke_mlbom_observed() -> str | None:
    """Isolated observed-hash + model-card vs text-only negative. None = ok."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        obs = root / "obs"
        neg = root / "neg"
        models = obs / "models"
        models.mkdir(parents=True)
        gguf = models / "tiny.gguf"
        gguf.write_bytes(b"tiny-weights\n")
        (models / "model-card.md").write_text(_OBS_CARD, encoding="utf-8")
        neg.mkdir()
        (neg / "app.py").write_text('MODEL = "gpt-4o-mini"\n', encoding="utf-8")

        want = sha256_file(gguf)
        if not want:
            return "missing sha256 of tiny.gguf"

        obs_bom = scan_path(obs)
        neg_bom = scan_path(neg)
        cdx = to_cyclonedx(obs_bom)
        if cdx.get("specVersion") != "1.7":
            return f"cyclonedx specVersion {cdx.get('specVersion')}"
        ml = [
            c
            for c in (cdx.get("components") or [])
            if isinstance(c, dict) and c.get("type") == "machine-learning-model"
        ]
        if not ml:
            return "expected ML component"
        hashed = [
            c
            for c in ml
            if any(
                isinstance(h, dict) and h.get("alg") == "SHA-256" and h.get("content") == want
                for h in (c.get("hashes") or [])
            )
        ]
        if not hashed:
            return f"missing observed hash {want[:12]}"
        card_ok = any(
            any(
                isinstance(p, dict)
                and p.get("name") == "aibom:cardName"
                and p.get("value") == "Observed Tiny Model"
                for p in ((c.get("modelCard") or {}).get("properties") or [])
            )
            or c.get("description") == "A fixture description only."
            for c in ml
        )
        if not card_ok:
            return "missing observed model-card name/description"
        lic_ok = any(
            isinstance(e, dict)
            and (e.get("license") or {}).get("url") == "https://example.com/observed-license"
            for c in ml
            for e in (c.get("licenses") or [])
        ) or any(
            any(
                isinstance(p, dict)
                and p.get("name") == "aibom:licenseUrl"
                and "example.com/observed-license" in str(p.get("value") or "")
                for p in ((c.get("modelCard") or {}).get("properties") or [])
            )
            for c in ml
        )
        if not lic_ok:
            return "missing observed license URL"
        blob = json.dumps(cdx)
        if "accuracy" in blob.lower() and "Observed Tiny Model" not in blob:
            return "invented accuracy"
        if "datasets" in blob:
            return "invented datasets"
        if "quantitativeAnalysis" in blob:
            return "invented quantitativeAnalysis"

        spdx = to_spdx(obs_bom)
        if not any(
            any(
                isinstance(ck, dict)
                and ck.get("algorithm") == "SHA256"
                and ck.get("checksumValue") == want
                for ck in (pkg.get("checksums") or [])
            )
            for pkg in (spdx.get("packages") or [])
            if isinstance(pkg, dict)
        ):
            return "spdx missing observed hash"

        spdx3 = to_spdx3(obs_bom)
        if (spdx3.get("creationInfo") or {}).get("specVersion") != "3.0.1":
            return f"spdx3 specVersion {(spdx3.get('creationInfo') or {}).get('specVersion')}"
        elems = [e for e in (spdx3.get("element") or []) if isinstance(e, dict)]
        if not any(
            any(
                isinstance(h, dict)
                and h.get("algorithm") == "sha256"
                and h.get("hashValue") == want
                for h in (e.get("verifiedUsing") or [])
            )
            for e in elems
        ):
            return "spdx3 missing observed hash"
        files = [e for e in elems if e.get("type") == "software_File"]
        hashed_files = [
            e
            for e in files
            if e.get("name") == "tiny.gguf"
            and any(
                isinstance(h, dict)
                and h.get("algorithm") == "sha256"
                and h.get("hashValue") == want
                for h in (e.get("verifiedUsing") or [])
            )
        ]
        if not hashed_files:
            return "spdx3 missing observed file+hash"
        file_ids = {e.get("spdxId") for e in hashed_files}
        pkg_ids = {
            e.get("spdxId")
            for e in elems
            if str(e.get("type") or "").endswith("Package") and e.get("name") == "tiny.gguf"
        }
        if not any(
            e.get("type") == "Relationship"
            and e.get("relationshipType") == "contains"
            and e.get("from") in pkg_ids
            and any(t in file_ids for t in (e.get("to") or []))
            for e in elems
        ):
            return "spdx3 missing package contains file"

        neg_cdx = to_cyclonedx(neg_bom)
        neg_ml = [
            c
            for c in (neg_cdx.get("components") or [])
            if isinstance(c, dict) and c.get("type") == "machine-learning-model"
        ]
        if not neg_ml:
            return "negative fixture missing mentioned model"
        if any(c.get("hashes") for c in neg_ml):
            return "negative invented hashes"
        if any(
            any(
                isinstance(p, dict)
                and p.get("name") in {"aibom:cardName", "aibom:cardDescription", "aibom:licenseUrl"}
                for p in ((c.get("modelCard") or {}).get("properties") or [])
            )
            for c in neg_ml
        ):
            return "negative invented model-card fields"
        neg_spdx3 = to_spdx3(neg_bom)
        neg_elems = [e for e in (neg_spdx3.get("element") or []) if isinstance(e, dict)]
        if any(e.get("verifiedUsing") for e in neg_elems):
            return "negative must not invent hashes"
        if any(e.get("type") == "software_File" for e in neg_elems):
            return "negative must not invent files"
        if any(
            e.get("type") == "Relationship" and e.get("relationshipType") == "contains"
            for e in neg_elems
        ):
            return "negative must not invent contains"

        # SPDX 3 AI profile only when path+sha256 / model-card fields were observed.
        ai_pkgs = [e for e in elems if e.get("type") == "ai_AIPackage"]
        if not ai_pkgs:
            return "spdx3 missing ai_AIPackage for observed model file/card"
        if "ai" not in (spdx3.get("profileConformance") or []):
            return "spdx3 missing profileConformance ai when AIPackage present"
        if not any(
            e.get("software_primaryPurpose") == "model" for e in ai_pkgs
        ):
            return "spdx3 ai_AIPackage missing software_primaryPurpose=model"
        # License relationships required for AI profile conformance.
        ai_ids = {e.get("spdxId") for e in ai_pkgs}
        for aid in ai_ids:
            for rel in ("hasConcludedLicense", "hasDeclaredLicense"):
                if not any(
                    e.get("type") == "Relationship"
                    and e.get("relationshipType") == rel
                    and e.get("from") == aid
                    for e in elems
                ):
                    return f"spdx3 ai_AIPackage missing {rel}"
        if any(e.get("type") == "ai_AIPackage" for e in neg_elems):
            return "negative must not invent ai_AIPackage"
        if "ai" in (neg_spdx3.get("profileConformance") or []):
            return "negative must not claim AI profile"
        # No invented AI metrics / training graph as elements or relationships.
        if any(
            e.get("type") == "Relationship"
            and e.get("relationshipType") in {"trainedOn", "testedOn"}
            for e in elems
        ):
            return "spdx3 invented trainedOn/testedOn relationship"
        for e in elems:
            for key in e:
                if key in {"ai_metric", "ai_hyperparameter", "ai_energyConsumption"} or str(key).startswith("ai_metric"):
                    return f"spdx3 invented property {key}"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ai-bom",
        epilog="Exit codes: 0=ok  1=strict/gate-licenses/gate-vulns  2=usage/IO error",
    )
    parser.add_argument("--version", action="store_true")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("smoke")
    p_scan = sub.add_parser("scan", help="Scan a path and emit CycloneDX-like BOM")
    p_scan.add_argument("path", nargs="?", default=".")
    p_scan.add_argument("--out", default=None, help="Write BOM JSON to path")
    p_scan.add_argument(
        "--format",
        default=DEFAULT_FORMAT,
        choices=list(FORMAT_CHOICES),
        help="BOM export: json (default internal model), cyclonedx (CycloneDX 1.7 JSON), cyclonedx-xml (CycloneDX 1.7 XML; alias cdx-xml), spdx (SPDX 2.3 JSON), spdx-xml (SPDX 2.3 XML; alias spdxxml), spdx3 (SPDX 3.0.1 JSON; alias spdx-3), sarif (SARIF 2.1.0; same builder as --sarif PATH), md (human/Slack Markdown summary; alias markdown), gha (GitHub Actions ::error/::notice workflow commands; alias annotations), html (self-contained HTML BOM summary; no CDN)",
    )
    p_scan.add_argument(
        "--evidence",
        default=None,
        help="Write bilingual DRAFT evidence markdown for auditors",
    )
    p_scan.add_argument(
        "--policy",
        default=None,
        help="Policy pack JSON (forbidden patterns + required disclosures)",
    )
    p_scan.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if forbidden patterns, disclosure gaps, or forbidden licenses",
    )
    p_scan.add_argument(
        "--gate-licenses",
        action="store_true",
        help=(
            "CI license-policy gate: exit 1 if forbiddenLicenseIds match "
            "(existing policy). Does not fail on pickle/disclosure (use --strict)."
        ),
    )
    p_scan.add_argument(
        "--advisories",
        default=None,
        help=(
            "Local advisory JSON (offline fixture). Match scanned components "
            "by name/purl/version and recorded versionRange operators. "
            "Not an NVD/OSV/GitHub Advisory fetch."
        ),
    )
    p_scan.add_argument(
        "--gate-vulns",
        action="store_true",
        help=(
            "CI advisory-match gate: exit 1 if --advisories hits scanned "
            "components. Offline only; requires --advisories."
        ),
    )
    p_scan.add_argument(
        "--sarif",
        default=None,
        help="Write SARIF 2.1.0 JSON (policy hits) for GitHub code scanning",
    )
    p_scan.add_argument(
        "--vex",
        default=None,
        help=(
            "Write OpenVEX 0.2.0 JSON from observed --advisories matches "
            "(requires --advisories). Status is derived: affected / "
            "not_affected (only with a recorded justification) / "
            "under_investigation / fixed only when the fixture records "
            "fixedVersion. Not a CRA conformity claim."
        ),
    )
    p_scan.add_argument(
        "--ignore",
        default=None,
        help="Comma-separated ignore patterns (gitignore-like; merges with root .aibomignore)",
    )
    p_scan.add_argument(
        "--exceptions",
        default=None,
        help=(
            "License exception JSON (component+license waivers). "
            "Merges with scan-root .aibom-exceptions.json. "
            f"Env {ENV_EXCEPTIONS} when flag omitted. Empty = no extra file."
        ),
    )
    p_scan.add_argument(
        "--webhook-url",
        default=None,
        help=(
            "POST JSON on forbidden pattern hits or forbidden licenses "
            "(env AI_BOM_WEBHOOK_URL). Empty/omit = disabled. "
            "Always sends X-Webhook-Timestamp unix-seconds. OSS 1 retry on 5xx/network/timeout after ~50ms (4xx/success no retry). Exponential backoff / queues / key rotation / timestamp replay window enforcement = paid later."
        ),
    )
    p_scan.add_argument(
        "--webhook-secret",
        default=None,
        help=(
            "HMAC-SHA256 key for outbound policy-hit POST "
            "(`X-Webhook-Signature: sha256=<hex>` of raw body). "
            "Env AI_BOM_WEBHOOK_SECRET when flag omitted. Empty/omit = unsigned. "
            "Simple HMAC is OSS (body only). Always sends X-Webhook-Timestamp unix-seconds; replay window enforcement = paid later."
        ),
    )
    sub.add_parser("demo")
    p_policy = sub.add_parser(
        "policy",
        help="Print the active license/policy gate JSON (ids/counts only; no file dump)",
    )
    p_policy.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Scan root for ignoreFile + exceptionsCount (default: .)",
    )
    p_policy.add_argument(
        "--policy",
        default=None,
        help="Policy pack JSON (forbiddenLicenseIds + forbiddenPatterns ids)",
    )
    p_policy.add_argument(
        "--exceptions",
        default=None,
        help=(
            "License exception JSON (count only in output). "
            "Merges with scan-root .aibom-exceptions.json. "
            f"Env {ENV_EXCEPTIONS} when flag omitted. Empty = no extra file."
        ),
    )
    p_serve = sub.add_parser(
        "serve",
        help="Local BOM HTTP server (stdlib http.server; hosted inventory = paid)",
    )
    p_serve.add_argument(
        "--path",
        default=".",
        help="Scan root (default: .)",
    )
    p_serve.add_argument(
        "--host",
        default=DEFAULT_SERVE_HOST,
        help=f"Bind host (default: {DEFAULT_SERVE_HOST}; Compose uses 0.0.0.0)",
    )
    p_serve.add_argument(
        "--port",
        type=int,
        default=DEFAULT_SERVE_PORT,
        help=f"Bind port (default: {DEFAULT_SERVE_PORT})",
    )
    p_serve.add_argument(
        "--policy",
        default=None,
        help="Policy pack JSON (forbidden patterns + required disclosures)",
    )
    p_serve.add_argument(
        "--ignore",
        default=None,
        help="Comma-separated ignore patterns (gitignore-like; merges with root .aibomignore)",
    )
    p_serve.add_argument(
        "--exceptions",
        default=None,
        help=(
            "License exception JSON (component+license waivers). "
            "Merges with scan-root .aibom-exceptions.json. "
            f"Env {ENV_EXCEPTIONS} when flag omitted. Empty = no extra file."
        ),
    )
    p_serve.add_argument(
        "--cors-origins",
        default=None,
        help=(
            "CSV of allowed Origins (empty/omit = deny extra CORS; * allowed). "
            "Env AI_BOM_CORS_ORIGINS when flag omitted."
        ),
    )
    p_serve.add_argument(
        "--rate-limit",
        dest="rate_limit",
        type=int,
        default=None,
        help=(
            "Max requests per minute per client IP (default 120; "
            "env RATE_LIMIT_PER_MINUTE or RATE_LIMIT_RPM). 0 = unlimited. "
            "/health /ready /metrics are not limited."
        ),
    )
    p_serve.add_argument(
        "--watch",
        action="store_true",
        help=(
            "Poll scan-root max mtime (~500ms) and rescan snapshot "
            "(/bom.json /health /metrics / /). Default off (one-shot at start)."
        ),
    )
    p_serve.add_argument(
        "--drain-ms",
        type=int,
        default=None,
        help="SIGTERM/SIGINT drain window in ms (default 5000, cap 30000). Env SHUTDOWN_DRAIN_MS.",
    )
    p_serve.add_argument(
        "--log-json",
        dest="log_json",
        action="store_true",
        default=None,
        help=(
            "JSON access logs on stdout (one line per app request). "
            "Env LOG_FORMAT=json when flag omitted. Default off."
        ),
    )
    p_serve.add_argument(
        "--webhook-url",
        default=None,
        help=(
            "Presence only on GET /v1/config (webhooks.hasUrl). "
            "Serve does not POST; use scan --webhook-url to fire. "
            "Env AI_BOM_WEBHOOK_URL when flag omitted."
        ),
    )
    p_serve.add_argument(
        "--webhook-secret",
        default=None,
        help=(
            "Presence only on GET /v1/config (webhooks.hasSecret). "
            "The secret is never returned. Serve does not POST. "
            "Env AI_BOM_WEBHOOK_SECRET when flag omitted."
        ),
    )
    p_conv = sub.add_parser(
        "convert-advisories",
        help="Convert offline OSV/GHSA JSON into the local --advisories fixture schema (no network)",
    )
    p_conv.add_argument(
        "paths",
        nargs="+",
        help="OSV (or GHSA) JSON file(s)",
    )
    p_conv.add_argument(
        "--from-osv",
        action="store_true",
        help="Read OSV-style JSON (also accepts GHSA when the shape is close). Offline; no fetch.",
    )
    p_conv.add_argument(
        "--from-ghsa",
        action="store_true",
        help="Read GitHub Advisory JSON (REST-ish). Same converter; IDs stay GHSA-*.",
    )
    p_conv.add_argument(
        "--out",
        required=True,
        help="Write ai-bom-advisories/v1 JSON",
    )
    p_pack = sub.add_parser(
        "evidence-pack",
        help="Write CycloneDX 1.7 + SPDX 3.0.1 + OpenVEX 0.2.0 + MANIFEST.md + pack.json clock (Article 14 inventory+match; calendar helper, not a CRA certificate; VEX is not a conformity claim)",
    )
    p_pack.add_argument(
        "--dir",
        required=True,
        help="Scan root",
    )
    p_pack.add_argument(
        "--out",
        default=None,
        help="Write pack directory (bom.cdx.json, bom.spdx3.json, vex.json, MANIFEST.md, pack.json)",
    )
    p_pack.add_argument(
        "--zip",
        nargs="?",
        const="",
        default=None,
        dest="zip_path",
        help="Write a zip of the pack (optional path; default OUTDIR.zip or evidence-pack.zip)",
    )
    p_pack.add_argument(
        "--policy",
        default=None,
        help="Policy pack JSON (default: shipped policies/default.json)",
    )
    p_pack.add_argument(
        "--advisories",
        default=None,
        help="Local advisory fixture (default: examples/advisories/sample.json). Offline; not NVD.",
    )
    p_pack.add_argument(
        "--as-of",
        default=None,
        dest="as_of",
        help="UTC calendar date YYYY-MM-DD for the window clock (default: today UTC). Calendar helper only; not a certificate.",
    )
    args = parser.parse_args(argv)

    if args.version:
        print(__version__)
        return 0
    if args.cmd == "smoke":
        with tempfile.TemporaryDirectory() as td:
            sample = Path(td) / "app.py"
            sample.write_text(
                '# uses gpt-4o-mini and mcp_server_fs\nMODEL = "gpt-4o-mini"\n',
                encoding="utf-8",
            )
            bom = scan_path(Path(td))
            if "gpt-4o-mini" not in bom["summary"]["models"]:
                print("smoke failed: model not found")
                return 1
            if not any("mcp" in x.lower() for x in bom["summary"]["mcpServers"]):
                print("smoke failed: mcp not found")
                return 1
            tiny_inv = list_components(bom, scan_root=Path(td))
            if tiny_inv.get("ok") is not True or tiny_inv.get("count") != len(bom.get("components") or []):
                print("smoke failed list_components tiny", tiny_inv)
                return 1
        models = bom["summary"]["models"]

        sample_app = Path(__file__).resolve().parents[2] / "examples" / "sample-app"
        sample_bom = scan_path(sample_app)
        inv = list_components(sample_bom, scan_root=sample_app)
        inv_names = [c.get("name") for c in (inv.get("components") or [])]
        inv_blob = json.dumps(inv, ensure_ascii=False)
        empty_inv = list_components({"components": []})
        none_inv = list_components(None)
        leaky_inv = list_components(
            {
                "components": [
                    {
                        "name": "leaky",
                        "version": "1.0",
                        "path": "/home/user/ugly/sample-app/package.json",
                        "licenses": [{"license": {"id": "MIT"}}],
                    }
                ]
            },
            scan_root="/home/user/ugly/sample-app",
        )
        big_inv = list_components(
            {
                "components": [
                    {
                        "name": f"c{i}",
                        "licenses": [{"license": {"id": "MIT"}}],
                    }
                    for i in range(COMPONENTS_LIST_CAP + 1)
                ]
            }
        )
        mit_inv = list_components(sample_bom, license="MIT", scan_root=sample_app)
        inv_ok = (
            inv.get("ok") is True
            and inv.get("count") == len(sample_bom.get("components") or [])
            and inv.get("count") == len(inv.get("components") or [])
            and ("ai-bom-sample-app" in inv_names or "gpt-4o-mini" in inv_names)
            and all(
                not str(c.get("path") or "").startswith("/")
                and ":" not in str(c.get("path") or "")[:2]
                for c in (inv.get("components") or [])
            )
            and "/home/user" not in inv_blob
            and empty_inv == {"ok": True, "count": 0, "components": []}
            and none_inv == {"ok": True, "count": 0, "components": []}
            and (leaky_inv.get("components") or [{}])[0].get("path") == "package.json"
            and "/home/user" not in json.dumps(leaky_inv)
            and big_inv.get("truncated") is True
            and big_inv.get("count") == COMPONENTS_LIST_CAP
            and len(big_inv.get("components") or []) == COMPONENTS_LIST_CAP
            and mit_inv.get("ok") is True
            and mit_inv.get("count") >= 1
            and all(str(c.get("license") or "").lower() == "mit" for c in (mit_inv.get("components") or []))
        )
        if not inv_ok:
            print("smoke failed list_components sample-app", inv.get("count"), inv_names[:8], empty_inv, leaky_inv, big_inv.get("count"))
            return 1

        empty_ex = exceptions_json([])
        none_ex = exceptions_json(None)
        one_ex = exceptions_json(
            [
                {
                    "component": "leftpad",
                    "license": "GPL-3.0",
                    "reason": "vendor approved 2026-Q3",
                    "expires": "2099-12-31",
                }
            ]
        )
        exp_ex = exceptions_json(
            [
                {
                    "component": "oldpkg",
                    "license": "GPL-3.0",
                    "reason": "old waiver",
                    "expires": "2020-01-01",
                }
            ]
        )
        leaky_ex = exceptions_json(
            [
                {
                    "component": "leaky",
                    "license": "MIT",
                    "reason": "sk-SECRET and Bearer tok https://hooks.example/hook?token=abc",
                    "expires": None,
                    "webhook": "https://evil.example/hook",
                    "path": "/secret/waivers.json",
                }
            ]
        )
        leaky_blob = json.dumps(leaky_ex, ensure_ascii=False)
        big_ex = exceptions_json(
            [
                {
                    "component": f"c{i}",
                    "license": "MIT",
                    "reason": "n",
                    "expires": None,
                }
                for i in range(EXCEPTIONS_LIST_CAP + 1)
            ]
        )
        mix_ex = exceptions_json(
            [
                {
                    "component": "active",
                    "license": "MIT",
                    "reason": "n",
                    "expires": "2099-01-01",
                },
                {
                    "component": "stale",
                    "license": "MIT",
                    "reason": "n",
                    "expires": "2020-01-01",
                },
            ],
            expired=True,
        )
        unknown_ex = exceptions_json(
            [
                {
                    "component": "active",
                    "license": "MIT",
                    "reason": "n",
                    "expires": "2099-01-01",
                }
            ],
            expired="maybe",
        )
        one_row = (one_ex.get("exceptions") or [{}])[0]
        exp_row = (exp_ex.get("exceptions") or [{}])[0]
        leaky_row = (leaky_ex.get("exceptions") or [{}])[0]
        ex_ok = (
            empty_ex == {"ok": True, "count": 0, "exceptions": []}
            and none_ex == {"ok": True, "count": 0, "exceptions": []}
            and one_ex.get("ok") is True
            and one_ex.get("count") >= 1
            and one_row.get("component") == "leftpad"
            and one_row.get("license") == "GPL-3.0"
            and one_row.get("expiresAt") == "2099-12-31"
            and one_row.get("expired") is False
            and one_row.get("reason") == "vendor approved 2026-Q3"
            and exp_row.get("expired") is True
            and exp_row.get("expiresAt") == "2020-01-01"
            and "sk-SECRET" not in leaky_blob
            and "Bearer tok" not in leaky_blob
            and "hooks.example" not in leaky_blob
            and "evil.example" not in leaky_blob
            and "/secret/waivers.json" not in leaky_blob
            and "reason" not in leaky_row
            and "webhook" not in leaky_row
            and "path" not in leaky_row
            and big_ex.get("truncated") is True
            and big_ex.get("count") == EXCEPTIONS_LIST_CAP + 1
            and len(big_ex.get("exceptions") or []) == EXCEPTIONS_LIST_CAP
            and mix_ex.get("count") == 1
            and (mix_ex.get("exceptions") or [{}])[0].get("component") == "stale"
            and unknown_ex == {"ok": True, "count": 0, "exceptions": []}
        )
        if not ex_ok:
            print("smoke failed exceptions_json helper", empty_ex, one_ex, leaky_ex, big_ex.get("count"), mix_ex, unknown_ex)
            return 1

        cdx = to_cyclonedx(bom)
        spdx_doc = to_spdx(bom)
        json_default = dumps_export(bom, "json")
        try:
            json_obj = __import__("json").loads(json_default)
        except Exception:
            json_obj = {}
        format_ok = (
            cdx.get("bomFormat") == "CycloneDX"
            and cdx.get("specVersion") == "1.7"
            and isinstance(cdx.get("components"), list)
            and any(
                isinstance((c.get("licenses") or [{}])[0], dict)
                for c in (cdx.get("components") or [{}])
            )
            and any(
                (p.get("name") == "aibom:policyHits")
                for p in (cdx.get("properties") or [])
            )
            and spdx_doc.get("spdxVersion") == "SPDX-2.3"
            and isinstance(spdx_doc.get("packages"), list)
            and isinstance(spdx_doc.get("documentNamespace"), str)
            and spdx_doc.get("documentNamespace")
            and json_obj.get("bomFormat") == "CycloneDX"
            and json_obj.get("summary") is not None
            and json_obj.get("components") is not None
            and dumps_bom(bom) == json_default
            and normalize_format(None) == "json"
            and normalize_format("") == "json"
            and normalize_format("JSON") == "json"
            and normalize_format("cyclonedx") == "cyclonedx"
            and normalize_format("SPDX") == "spdx"
            and normalize_format("xml") is None
            and normalize_format("cyclonedx-xml") == "cyclonedx-xml"
            and normalize_format("CDX-XML") == "cyclonedx-xml"
            and normalize_format("spdx-xml") == "spdx-xml"
            and normalize_format("SPDX-XML") == "spdx-xml"
            and normalize_format("spdxxml") == "spdx-xml"
            and normalize_format("spdx3") == "spdx3"
            and normalize_format("SPDX3") == "spdx3"
            and normalize_format("spdx-3") == "spdx3"
            and "json" in FORMATS
            and "cyclonedx" in FORMATS
            and "spdx" in FORMATS
            and "sarif" in FORMATS
            and "cyclonedx-xml" in FORMATS
            and "spdx-xml" in FORMATS
            and "spdx3" in FORMATS
            and "md" in FORMATS
            and "gha" in FORMATS
            and "html" in FORMATS
            and normalize_format("sarif") == "sarif"
            and normalize_format("SARIF") == "sarif"
            and normalize_format("md") == "md"
            and normalize_format("MD") == "md"
            and normalize_format("markdown") == "md"
            and normalize_format("gha") == "gha"
            and normalize_format("GHA") == "gha"
            and normalize_format("annotations") == "gha"
            and normalize_format("html") == "html"
            and normalize_format("HTML") == "html"
        )
        if not format_ok:
            print("smoke failed cyclonedx/spdx export")
            return 1

        sample_cdx = to_cyclonedx(sample_bom)
        ml_comps = [
            c
            for c in (sample_cdx.get("components") or [])
            if isinstance(c, dict) and c.get("type") == "machine-learning-model"
        ]
        data_comps = [
            c
            for c in (sample_cdx.get("components") or [])
            if isinstance(c, dict) and c.get("type") == "data"
        ]
        has_gguf_card = any(
            any(
                p.get("name") == "aibom:format" and p.get("value") == "gguf"
                for p in ((c.get("modelCard") or {}).get("properties") or [])
            )
            for c in ml_comps
        )
        mlb_ok = (
            sample_cdx.get("specVersion") == "1.7"
            and sample_cdx.get("bomFormat") == "CycloneDX"
            and bool(ml_comps)
            and has_gguf_card
            and bool(data_comps)
            and all(isinstance(c.get("data"), list) and c["data"] for c in data_comps)
            and all(isinstance(c.get("licenses"), list) and c["licenses"] for c in ml_comps)
        )
        if not mlb_ok:
            print("smoke failed cyclonedx 1.7 ML-BOM fields", len(ml_comps), has_gguf_card, len(data_comps))
            return 1

        fixtures = Path(__file__).resolve().parents[2] / "examples" / "cra-fixtures"
        policy_path = Path(__file__).resolve().parents[2] / "policies" / "default.json"
        try:
            cra_policy = load_policy(policy_path)
        except Exception as e:
            print("smoke failed load cra policy", e)
            return 1
        pass_bom = scan_path(fixtures / "license-pass", policy=cra_policy)
        fail_bom = scan_path(fixtures / "license-fail", policy=cra_policy)
        pass_fl = pass_bom.get("summary", {}).get("forbiddenLicenses") or []
        fail_fl = fail_bom.get("summary", {}).get("forbiddenLicenses") or []
        if pass_fl:
            print("smoke failed license-pass fixture has forbidden licenses", pass_fl)
            return 1
        if not any(h.get("licenseId") == "GPL-3.0" for h in fail_fl):
            print("smoke failed license-fail fixture missing GPL-3.0", fail_fl)
            return 1

        adv_dir = Path(__file__).resolve().parents[2] / "examples" / "advisories"
        try:
            sample_adv = load_advisories(adv_dir / "sample.json")
            clean_adv = load_advisories(adv_dir / "clean.json")
        except Exception as e:
            print("smoke failed load advisories", e)
            return 1
        sample_hits = match_advisories(sample_bom.get("components") or [], sample_adv)
        clean_hits = match_advisories(sample_bom.get("components") or [], clean_adv)
        sample_ids = [h.get("id") for h in sample_hits]
        if "ADV-FIXTURE-1" not in sample_ids or "ADV-FIXTURE-2" not in sample_ids:
            print("smoke failed planted advisory match", sample_ids)
            return 1
        if clean_hits:
            print("smoke failed clean advisory had hits", clean_hits)
            return 1
        parsed = parse_purl("pkg:pypi/openai")
        if parsed.get("type") != "pypi" or parsed.get("name") != "openai":
            print("smoke failed parse_purl", parsed)
            return 1
        if not purl_identity_matches("pkg:pypi/openai", "pkg:pypi/openai"):
            print("smoke failed purl identity")
            return 1
        versioned_miss = match_advisories(
            [{"name": "openai", "purl": "pkg:pypi/openai"}],
            [{
                "id": "ADV-FIXTURE-X",
                "name": "openai",
                "purl": "pkg:pypi/openai@9.9.9",
                "version": "9.9.9",
                "severity": "high",
                "summary": "",
            }],
        )
        if versioned_miss:
            print("smoke failed versioned advisory matched unversioned component", versioned_miss)
            return 1

        osv_sample = adv_dir / "osv-sample.json"
        ghsa_sample = adv_dir / "ghsa-sample.json"
        try:
            conv = convert_files([osv_sample])
        except Exception as e:
            print("smoke failed convert osv-sample", e)
            return 1
        conv_ids = [a.get("id") for a in (conv.document.get("advisories") or [])]
        conv_names = [
            (a.get("component") or {}).get("name")
            for a in (conv.document.get("advisories") or [])
        ]
        if (
            conv.document.get("schema") != "ai-bom-advisories/v1"
            or conv.converted < 1
            or conv.skipped < 1
            or "openai" not in conv_names
            or not any(str(i).startswith("OSV-") for i in conv_ids)
            or any(str(i).startswith("ADV-FIXTURE-") for i in conv_ids)
        ):
            print("smoke failed osv convert", conv.converted, conv.skipped, conv_ids)
            return 1
        for row in conv.document.get("advisories") or []:
            if (row.get("component") or {}).get("version"):
                print("smoke failed osv convert invented version", row)
                return 1
        cvss_entries, _cvss_skip, _cvss_src = convert_record({
            "id": "OSV-2026-SAMPLE-CVSS",
            "summary": "cvss only",
            "severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H"}],
            "affected": [{"package": {"ecosystem": "PyPI", "name": "openai"}}],
        })
        if not cvss_entries or "severity" in cvss_entries[0]:
            print("smoke failed osv convert invented cvss severity", cvss_entries)
            return 1
        def _rows_from_converted(doc, include_range=True):
            rows = []
            for a in (doc.get("advisories") or []):
                comp = a.get("component") or {}
                rows.append({
                    "id": a.get("id") or "",
                    "name": comp.get("name") or "",
                    "purl": comp.get("purl") or "",
                    "version": comp.get("version") or "",
                    "versionRange": (comp.get("versionRange") or "") if include_range else "",
                    "severity": a.get("severity") or "medium",
                    "summary": a.get("summary") or "",
                })
            return rows

        conv_ranges = [
            (a.get("component") or {}).get("versionRange") or ""
            for a in (conv.document.get("advisories") or [])
        ]
        if not any((">=" in r or ">" in r or "<" in r or "=" in r) for r in conv_ranges):
            print("smoke failed osv convert missing versionRange operators", conv_ranges)
            return 1
        osv_rows = _rows_from_converted(conv.document)
        in_comp = [{"name": "openai", "version": "1.2.3", "purl": "pkg:pypi/openai@1.2.3"}]
        out_comp = [{"name": "openai", "version": "9.9.9", "purl": "pkg:pypi/openai@9.9.9"}]
        osv_in = match_advisories(in_comp, osv_rows)
        osv_out = match_advisories(out_comp, osv_rows)
        if not any(str(h.get("id") or "").startswith("OSV-") for h in osv_in):
            print("smoke failed converted range in-match", osv_in, conv_ranges)
            return 1
        if osv_out:
            print("smoke failed converted range out-match", osv_out, conv_ranges)
            return 1
        # unversioned sample-app openai must not invent a hit against a recorded range
        unversioned_osv = match_advisories(sample_bom.get("components") or [], osv_rows)
        if unversioned_osv:
            print("smoke failed unversioned component matched range", unversioned_osv)
            return 1
        clean_tree = scan_path(fixtures / "license-pass")
        clean_osv_hits = match_advisories(clean_tree.get("components") or [], osv_rows)
        if clean_osv_hits:
            print("smoke failed osv convert clean tree", clean_osv_hits)
            return 1
        try:
            range_in_adv = load_advisories(adv_dir / "range-in.json")
            range_out_adv = load_advisories(adv_dir / "range-out.json")
            range_skip_adv = load_advisories(adv_dir / "range-skip.json")
        except Exception as e:
            print("smoke failed load range fixtures", e)
            return 1
        range_in_hits = match_advisories(sample_bom.get("components") or [], range_in_adv)
        range_out_hits = match_advisories(sample_bom.get("components") or [], range_out_adv)
        range_skip_res = match_advisories_result(sample_bom.get("components") or [], range_skip_adv)
        if not any(h.get("id") == "ADV-FIXTURE-RANGE-IN" for h in range_in_hits):
            print("smoke failed fixture range in", range_in_hits)
            return 1
        if range_out_hits:
            print("smoke failed fixture range out", range_out_hits)
            return 1
        if range_skip_res.hits or range_skip_res.range_skipped < 1:
            print("smoke failed unparseable range skip", range_skip_res)
            return 1
        with tempfile.TemporaryDirectory() as ctd:
            cout = Path(ctd) / "from-osv.json"
            rc = main(["convert-advisories", "--from-osv", str(osv_sample), "--out", str(cout)])
            if rc != 0 or not cout.is_file():
                print("smoke failed convert-advisories cli", rc)
                return 1
            written = json.loads(cout.read_text(encoding="utf-8"))
            wids = [a.get("id") for a in (written.get("advisories") or [])]
            if any(str(i).startswith("ADV-FIXTURE-") for i in wids):
                print("smoke failed convert relabeled ADV-FIXTURE", wids)
                return 1
            in_dir = Path(ctd) / "in-range"
            out_dir = Path(ctd) / "out-range"
            in_dir.mkdir()
            out_dir.mkdir()
            (in_dir / "pyproject.toml").write_text(
                '[project]\nname = "openai"\nversion = "1.2.3"\n',
                encoding="utf-8",
            )
            (out_dir / "pyproject.toml").write_text(
                '[project]\nname = "openai"\nversion = "9.9.9"\n',
                encoding="utf-8",
            )
            hit_rc = main([
                "scan", str(in_dir),
                "--advisories", str(cout),
                "--gate-vulns",
                "--out", str(Path(ctd) / "hit.json"),
            ])
            if hit_rc != 1:
                print("smoke failed gate-vulns in-range after osv convert", hit_rc)
                return 1
            miss_rc = main([
                "scan", str(out_dir),
                "--advisories", str(cout),
                "--gate-vulns",
                "--out", str(Path(ctd) / "miss.json"),
            ])
            if miss_rc != 0:
                print("smoke failed gate-vulns out-range after osv convert", miss_rc)
                return 1
            pass_rc = main([
                "scan", str(fixtures / "license-pass"),
                "--advisories", str(cout),
                "--gate-vulns",
                "--out", str(Path(ctd) / "pass.json"),
            ])
            if pass_rc != 0:
                print("smoke failed clean tree after osv convert", pass_rc)
                return 1
            fix_in = main([
                "scan", str(sample_app),
                "--advisories", str(adv_dir / "range-in.json"),
                "--gate-vulns",
                "--out", str(Path(ctd) / "range-in.json"),
            ])
            fix_out = main([
                "scan", str(sample_app),
                "--advisories", str(adv_dir / "range-out.json"),
                "--gate-vulns",
                "--out", str(Path(ctd) / "range-out.json"),
            ])
            if fix_in != 1 or fix_out != 0:
                print("smoke failed fixture range gate", fix_in, fix_out)
                return 1
            ghsa_out = Path(ctd) / "from-ghsa.json"
            grc = main(["convert-advisories", "--from-ghsa", str(ghsa_sample), "--out", str(ghsa_out)])
            if grc != 0 or not ghsa_out.is_file():
                print("smoke failed convert-advisories ghsa cli", grc)
                return 1
            ghsa_doc = json.loads(ghsa_out.read_text(encoding="utf-8"))
            gids = [a.get("id") for a in (ghsa_doc.get("advisories") or [])]
            if (
                not gids
                or not all(str(i).startswith("GHSA-") for i in gids)
                or any(str(i).startswith("ADV-FIXTURE-") for i in gids)
            ):
                print("smoke failed ghsa convert ids", gids)
                return 1
            ghsa_rows = _rows_from_converted(ghsa_doc)
            ghsa_in = match_advisories(in_comp, ghsa_rows)
            ghsa_out_hits = match_advisories(out_comp, ghsa_rows)
            if not ghsa_in or ghsa_out_hits:
                print("smoke failed ghsa range match", ghsa_in, ghsa_out_hits)
                return 1
        print("osv-convert-ok")
        print("range-ok")

        mlbom_obs_err = _smoke_mlbom_observed()
        if mlbom_obs_err:
            print("smoke failed mlbom observed/negative", mlbom_obs_err)
            return 1
        print("mlbom-obs-ok")
        print("spdx3-files-ok")
        print("spdx3-ai-ok")

        pack_err = _smoke_evidence_pack()
        if pack_err:
            print("smoke failed evidence-pack", pack_err)
            return 1
        print("evidence-pack-ok")
        print("evidence-zip-ok")
        clock_err = _smoke_cra_clock()
        if clock_err:
            print("smoke failed cra-clock", clock_err)
            return 1
        print("cra-clock-ok")
        vex_err = _smoke_vex()
        if vex_err:
            print("smoke failed vex", vex_err)
            return 1
        print("vex-ok")

        sarif_doc = to_sarif(bom, tool_version=__version__)
        empty_sarif = to_sarif(
            {"summary": {}, "components": [], "metadata": {"component": {"name": "empty"}}}
        )
        sarif_text = dumps_export(bom, "sarif")
        try:
            sarif_obj = json.loads(sarif_text)
        except Exception:
            sarif_obj = {}
        sarif_ok = (
            sarif_doc.get("version") == "2.1.0"
            and isinstance(sarif_doc.get("runs"), list)
            and len(sarif_doc.get("runs") or []) >= 1
            and isinstance((sarif_doc.get("runs") or [{}])[0].get("results"), list)
            and empty_sarif.get("version") == "2.1.0"
            and isinstance(empty_sarif.get("runs"), list)
            and ((empty_sarif.get("runs") or [{}])[0].get("results") or []) == []
            and sarif_obj.get("version") == "2.1.0"
            and isinstance(sarif_obj.get("runs"), list)
            and sarif_text == dumps_sarif(sarif_doc)
        )
        if not sarif_ok:
            print("smoke failed sarif export")
            return 1

        cdx_xml = to_cyclonedx_xml(bom)
        cdx_xml_dump = dumps_export(bom, "cyclonedx-xml")
        empty_xml = dumps_export(
            {"summary": {}, "components": [], "metadata": {"component": {"name": "empty"}}}
        , "cyclonedx-xml")
        amp_xml = dumps_export(
            {
                "summary": {"policyHits": 0},
                "components": [
                    {"name": "foo & bar", "type": "library", "version": "1.0"}
                ],
                "metadata": {"component": {"name": "amp"}},
            },
            "cyclonedx-xml",
        )
        fixture_name = None
        for c in bom.get("components") or []:
            n = str((c or {}).get("name") or "")
            if n:
                fixture_name = n
                break
        if fixture_name is None:
            for m in (bom.get("summary") or {}).get("models") or []:
                if m:
                    fixture_name = str(m)
                    break
        xml_ok = (
            cdx_xml.lstrip().startswith("<bom")
            and 'xmlns="http://cyclonedx.org/schema/bom/1.7"' in cdx_xml
            and "version=\"1\"" in cdx_xml
            and "serialNumber=" in cdx_xml
            and "<components" in cdx_xml
            and "aibom:policyHits" in cdx_xml
            and cdx_xml_dump == cdx_xml
            and dumps_export(bom, "cdx-xml") == cdx_xml
            and empty_xml.lstrip().startswith("<bom")
            and 'xmlns="http://cyclonedx.org/schema/bom/1.7"' in empty_xml
            and "<components" in empty_xml
            and empty_xml.rstrip().endswith("</bom>")
            and "foo &amp; bar" in amp_xml
            and "foo & bar" not in amp_xml
            and fixture_name is not None
            and fixture_name in cdx_xml
        )
        if not xml_ok:
            print("smoke failed cyclonedx-xml export")
            return 1

        spdx_xml = to_spdx_xml(bom)
        spdx_xml_dump = dumps_export(bom, "spdx-xml")
        empty_spdx_xml = dumps_export(
            {"summary": {}, "components": [], "metadata": {"component": {"name": "empty"}}}
        , "spdx-xml")
        amp_spdx_xml = dumps_export(
            {
                "summary": {"policyHits": 0},
                "components": [
                    {"name": "foo & bar", "type": "library", "version": "1.0"}
                ],
                "metadata": {"component": {"name": "amp"}},
            },
            "spdx-xml",
        )
        spdx_xml_ok = (
            spdx_xml.lstrip().startswith("<SpdxDocument")
            and "SPDX-2.3" in spdx_xml
            and "<packages" in spdx_xml
            and "<licenseConcluded" in spdx_xml
            and spdx_xml_dump == spdx_xml
            and dumps_export(bom, "spdxxml") == spdx_xml
            and empty_spdx_xml.lstrip().startswith("<SpdxDocument")
            and "SPDX-2.3" in empty_spdx_xml
            and "<packages" in empty_spdx_xml
            and empty_spdx_xml.rstrip().endswith("</SpdxDocument>")
            and "foo &amp; bar" in amp_spdx_xml
            and "foo & bar" not in amp_spdx_xml
            and fixture_name is not None
            and fixture_name in spdx_xml
        )
        if not spdx_xml_ok:
            print("smoke failed spdx-xml export")
            return 1

        spdx3_doc = to_spdx3(bom)
        spdx3_dump = dumps_export(bom, "spdx3")
        empty_spdx3 = dumps_export(
            {"summary": {}, "components": [], "metadata": {"component": {"name": "empty"}}}
        , "spdx3")
        try:
            spdx3_obj = json.loads(spdx3_dump)
            empty_spdx3_obj = json.loads(empty_spdx3)
        except Exception:
            spdx3_obj = {}
            empty_spdx3_obj = {}
        spdx3_elems = [e for e in (spdx3_doc.get("element") or []) if isinstance(e, dict)]
        spdx3_pkgs = [e for e in spdx3_elems if str(e.get("type") or "").endswith("Package")]
        spdx3_lics = [
            e for e in spdx3_elems if "LicenseExpression" in str(e.get("type") or "")
        ]
        ci = spdx3_doc.get("creationInfo") if isinstance(spdx3_doc.get("creationInfo"), dict) else {}
        empty_ci = empty_spdx3_obj.get("creationInfo") if isinstance(empty_spdx3_obj.get("creationInfo"), dict) else {}
        spdx3_ok = (
            spdx3_doc.get("type") == "SpdxDocument"
            and isinstance(spdx3_doc.get("spdxId"), str)
            and spdx3_doc.get("spdxId")
            and isinstance(spdx3_doc.get("name"), str)
            and spdx3_doc.get("name")
            and ci.get("specVersion") == "3.0.1"
            and bool(spdx3_pkgs)
            and bool(spdx3_lics)
            and any(e.get("simplelicensing_licenseExpression") for e in spdx3_lics)
            and spdx3_obj.get("creationInfo", {}).get("specVersion") == "3.0.1"
            and dumps_export(bom, "spdx-3") == spdx3_dump
            and empty_ci.get("specVersion") == "3.0.1"
            and empty_spdx3_obj.get("type") == "SpdxDocument"
            and isinstance(empty_spdx3_obj.get("element"), list)
            and fixture_name is not None
            and fixture_name in spdx3_dump
        )
        if not spdx3_ok:
            print("smoke failed spdx3 export", ci.get("specVersion"), len(spdx3_pkgs), len(spdx3_lics))
            return 1

        md_text = to_markdown(bom)
        md_dump = dumps_export(bom, "md")
        empty_md = dumps_export(
            {"summary": {}, "components": [], "metadata": {"component": {"name": "empty"}}}
        , "md")
        amp_md = dumps_export(
            {
                "summary": {
                    "policyHits": 1,
                    "licenses": {"MIT": 1},
                    "forbiddenLicenses": [
                        {
                            "component": "foo | bar",
                            "licenseId": "GPL-3.0",
                            "id": "license/GPL-3.0",
                        }
                    ],
                    "waived": [],
                },
                "components": [
                    {"name": "foo | bar", "type": "library", "version": "1.0"}
                ],
                "metadata": {"component": {"name": "amp"}},
            },
            "md",
        )
        lic_or_name = False
        if fixture_name and fixture_name in md_text:
            lic_or_name = True
        if "UNKNOWN" in md_text or "MIT" in md_text:
            lic_or_name = True
        md_ok = (
            md_text.lstrip().startswith("# ")
            and "# AI-BOM" in md_text
            and "**policyHits:**" in md_text
            and "policyHits" in md_text
            and any(ch.isdigit() for ch in md_text)
            and lic_or_name
            and md_dump == md_text
            and dumps_export(bom, "markdown") == md_text
            and empty_md.lstrip().startswith("# ")
            and "**components:** 0" in empty_md
            and "**policyHits:** 0" in empty_md
            and "**waived:** 0" in empty_md
            and "foo \\| bar" in amp_md
            and "foo | bar" not in amp_md.replace("foo \\| bar", "")
        )
        if not md_ok:
            print("smoke failed md export")
            return 1

        html_text = to_html(bom)
        html_dump = dumps_export(bom, "html")
        empty_html = dumps_export(
            {"summary": {}, "components": [], "metadata": {"component": {"name": "empty"}}}
        , "html")
        amp_html = dumps_export(
            {
                "summary": {
                    "policyHits": 1,
                    "licenses": {"MIT": 1},
                    "forbiddenLicenses": [
                        {
                            "component": "foo & bar",
                            "licenseId": "GPL-3.0",
                            "id": "license/GPL-3.0",
                        }
                    ],
                    "waived": [],
                },
                "components": [
                    {"name": "foo & bar", "type": "library", "version": "1.0"}
                ],
                "metadata": {"component": {"name": "amp"}},
            },
            "html",
        )
        html_name_ok = "<table" in html_text
        if fixture_name and fixture_name in html_text:
            html_name_ok = True
        html_ok = (
            ("<!DOCTYPE html>" in html_text or html_text.lstrip().lower().startswith("<!doctype html"))
            and "<h1" in html_text
            and "AI-BOM" in html_text
            and "<table" in html_text
            and "Policy hits" in html_text
            and "License summary" in html_text
            and "Component count" in html_text
            and html_name_ok
            and html_dump == html_text
            and dumps_export(bom, "HTML") == html_text
            and "<h1" in empty_html
            and "AI-BOM" in empty_html
            and "<table" in empty_html
            and "foo &amp; bar" in amp_html
            and "foo & bar" not in amp_html
            and "GPL-3.0" in amp_html
            and 'class="fail"' in amp_html
        )
        if not html_ok:
            print("smoke failed html export")
            return 1

        gha_hit = dumps_export(
            {
                "summary": {
                    "policyHits": 2,
                    "forbidden": [
                        {"pattern": "pickle.load", "path": "app.py"},
                    ],
                    "forbiddenLicenses": [
                        {
                            "component": "leftpad",
                            "licenseId": "GPL-3.0",
                            "id": "license/GPL-3.0",
                        }
                    ],
                    "waived": [],
                },
                "components": [],
                "metadata": {"component": {"name": "hit"}},
            },
            "gha",
        )
        gha_pct = dumps_export(
            {
                "summary": {
                    "policyHits": 1,
                    "forbiddenLicenses": [
                        {
                            "component": "foo:bar,baz",
                            "licenseId": "GPL-3.0%\nX",
                        }
                    ],
                    "waived": [],
                },
                "components": [],
                "metadata": {"component": {"name": "esc"}},
            },
            "gha",
        )
        empty_gha = dumps_export(
            {"summary": {}, "components": [], "metadata": {"component": {"name": "empty"}}},
            "gha",
        )
        waived_gha = dumps_export(
            {
                "summary": {
                    "policyHits": 0,
                    "forbiddenLicenses": [],
                    "waived": [
                        {
                            "component": "leftpad",
                            "license": "GPL-3.0",
                            "reason": "vendor approved 2026-Q3",
                        }
                    ],
                },
                "components": [],
                "metadata": {"component": {"name": "waive"}},
            },
            "gha",
        )
        gha_dump = dumps_export(
            {
                "summary": {
                    "policyHits": 1,
                    "forbidden": [{"pattern": "pickle.load", "path": "app.py"}],
                },
                "components": [],
            },
            "gha",
        )
        gha_ok = (
            "::error" in gha_hit
            and "title=app.py::" in gha_hit
            and "pickle.load" in gha_hit
            and "title=leftpad::" in gha_hit
            and "GPL-3.0" in gha_hit
            and gha_hit.startswith("::error")
            and empty_gha == ""
            and "::error" not in empty_gha
            and "::error" not in waived_gha
            and "::notice" in waived_gha
            and "title=leftpad::" in waived_gha
            and "waived vendor approved 2026-Q3" in waived_gha
            and dumps_export(
                {
                    "summary": {
                        "policyHits": 1,
                        "forbidden": [{"pattern": "pickle.load", "path": "app.py"}],
                    },
                    "components": [],
                },
                "annotations",
            )
            == gha_dump
            and to_gha(
                {
                    "summary": {
                        "policyHits": 1,
                        "forbidden": [{"pattern": "pickle.load", "path": "app.py"}],
                    },
                    "components": [],
                }
            )
            == gha_dump
            and "%25" in gha_pct
            and "%0A" in gha_pct
            and "%3A" in gha_pct
            and "%2C" in gha_pct
            and "::error title=foo%3Abar%2Cbaz::" in gha_pct
        )
        if not gha_ok:
            print("smoke failed gha annotations", gha_hit, empty_gha, waived_gha, gha_pct)
            return 1

        policy_path = Path(__file__).resolve().parents[2] / "policies" / "default.json"
        try:
            lic_policy = load_policy(policy_path)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            print(f"smoke failed load default policy: {e}")
            return 1
        empty_gate = build_policy_gate(None)
        default_gate = build_policy_gate(lic_policy)
        gate_text = json.dumps(default_gate)
        gate_ok = (
            empty_gate.get("ok") is True
            and empty_gate.get("forbiddenLicenseIds") == []
            and empty_gate.get("forbiddenPatterns") == []
            and empty_gate.get("exceptionsCount") == 0
            and empty_gate.get("ignoreFile") is False
            and default_gate.get("ok") is True
            and "GPL-3.0" in (default_gate.get("forbiddenLicenseIds") or [])
            and "pickle.load" in (default_gate.get("forbiddenPatterns") or [])
            and r"\\bpickle" not in gate_text
            and "reason" not in default_gate
            and isinstance(default_gate.get("exceptionsCount"), int)
            and isinstance(default_gate.get("ignoreFile"), bool)
        )
        if not gate_ok:
            print("smoke failed policy gate helper", empty_gate, default_gate)
            return 1
        with tempfile.TemporaryDirectory() as ig_td:
            igroot = Path(ig_td)
            (igroot / ".aibomignore").write_text("vendor/\n", encoding="utf-8")
            ig_gate = build_policy_gate(None, scan_root=igroot)
            if ig_gate.get("ignoreFile") is not True or ig_gate.get("ok") is not True:
                print("smoke failed policy gate ignoreFile", ig_gate)
                return 1
            if "vendor/" in json.dumps(ig_gate):
                print("smoke failed policy gate dumped ignore contents", ig_gate)
                return 1
        with tempfile.TemporaryDirectory() as exc_td:
            eroot = Path(exc_td)
            (eroot / "package.json").write_text(
                json.dumps(
                    {"name": "leftpad", "version": "1.0.0", "license": "GPL-3.0"}
                ),
                encoding="utf-8",
            )
            (eroot / "app.py").write_text('MODEL = "gpt-4o-mini"\n', encoding="utf-8")
            bom_missing = scan_path(eroot, policy=lic_policy)
            fl_missing = bom_missing["summary"].get("forbiddenLicenses") or []
            if not any(
                h.get("licenseId") == "GPL-3.0" and h.get("component") == "leftpad"
                for h in fl_missing
            ):
                print("smoke failed exceptions: missing file should still hit GPL-3.0", fl_missing)
                return 1
            if bom_missing["summary"].get("waived"):
                print("smoke failed exceptions: missing file must not waive", bom_missing["summary"])
                return 1
            (eroot / EXCEPTIONS_FILENAME).write_text(
                json.dumps(
                    {
                        "exceptions": [
                            {
                                "component": "leftpad",
                                "license": "GPL-3.0",
                                "reason": "vendor approved 2026-Q3",
                                "expires": "2099-12-31",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            bom_ok = scan_path(eroot, policy=lic_policy)
            if bom_ok["summary"].get("forbiddenLicenses"):
                print("smoke failed exceptions: waived hit still in forbiddenLicenses", bom_ok["summary"])
                return 1
            gate_exc = build_policy_gate(lic_policy, scan_root=eroot)
            if gate_exc.get("exceptionsCount") != 1:
                print("smoke failed policy gate exceptionsCount", gate_exc)
                return 1
            if "vendor approved" in json.dumps(gate_exc) or "reason" in gate_exc:
                print("smoke failed policy gate dumped exception reason", gate_exc)
                return 1
            waived = bom_ok["summary"].get("waived") or []
            if not any(
                w.get("component") == "leftpad" and w.get("license") == "GPL-3.0"
                for w in waived
            ):
                print("smoke failed exceptions: waived missing leftpad", waived)
                return 1
            if (bom_ok["summary"].get("forbidden") or []) or (
                bom_ok["summary"].get("policyHits") or 0
            ):
                print("smoke failed exceptions: expected policyHits 0 after waiver", bom_ok["summary"])
                return 1
            cdx_w = to_cyclonedx(bom_ok)
            if not any(p.get("name") == "aibom:waived" for p in (cdx_w.get("properties") or [])):
                print("smoke failed exceptions: cyclonedx missing aibom:waived")
                return 1
            cdx_w_xml = to_cyclonedx_xml(bom_ok)
            if "aibom:waived" not in cdx_w_xml:
                print("smoke failed exceptions: cyclonedx-xml missing aibom:waived")
                return 1
            spdx_w_xml = to_spdx_xml(bom_ok)
            if "SPDX-2.3" not in spdx_w_xml or "leftpad" not in spdx_w_xml:
                print("smoke failed exceptions: spdx-xml missing SPDX-2.3/leftpad")
                return 1
            md_w = to_markdown(bom_ok)
            if "leftpad" not in md_w or "waived" not in md_w.lower():
                print("smoke failed exceptions: md missing waived leftpad")
                return 1
            html_missing = to_html(bom_missing)
            if "GPL-3.0" not in html_missing or "leftpad" not in html_missing:
                print("smoke failed exceptions: html missing GPL-3.0/leftpad")
                return 1
            if 'class="fail"' not in html_missing:
                print("smoke failed exceptions: html missing fail class for forbidden license")
                return 1
            html_w = to_html(bom_ok)
            if "leftpad" not in html_w or "waived" not in html_w.lower():
                print("smoke failed exceptions: html missing waived leftpad")
                return 1
            gha_missing = to_gha(bom_missing)
            if "::error" not in gha_missing or "title=leftpad::" not in gha_missing:
                print("smoke failed exceptions: gha missing GPL ::error", gha_missing)
                return 1
            if "GPL-3.0" not in gha_missing:
                print("smoke failed exceptions: gha missing GPL-3.0", gha_missing)
                return 1
            gha_w = to_gha(bom_ok)
            if "::error" in gha_w:
                print("smoke failed exceptions: waived gha still has ::error", gha_w)
                return 1
            if "::notice" not in gha_w or "title=leftpad::" not in gha_w or "waived" not in gha_w:
                print("smoke failed exceptions: waived gha missing ::notice", gha_w)
                return 1
            sarif_w = to_sarif(bom_ok, tool_version=__version__)
            sarif_results = (sarif_w.get("runs") or [{}])[0].get("results") or []
            waived_sarif = [
                r
                for r in sarif_results
                if (r.get("properties") or {}).get("waived")
                or r.get("suppressions")
            ]
            if not waived_sarif:
                print("smoke failed exceptions: sarif missing suppressed waived note")
                return 1
            if any(
                r.get("level") == "error" and str(r.get("ruleId") or "").startswith("license/")
                and not r.get("suppressions")
                for r in sarif_results
            ):
                print("smoke failed exceptions: sarif still errors on waived license")
                return 1
            skipped = bom_without_exceptions(bom_ok)
            if not (skipped["summary"].get("forbiddenLicenses") or []):
                print("smoke failed exceptions: skip reconstruct empty")
                return 1
            if skipped["summary"].get("waived"):
                print("smoke failed exceptions: skip should clear waived")
                return 1
            (eroot / EXCEPTIONS_FILENAME).write_text(
                json.dumps(
                    {
                        "exceptions": [
                            {
                                "component": "leftpad",
                                "license": "GPL-3.0",
                                "reason": "old waiver",
                                "expires": "2020-01-01",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            bom_exp = scan_path(eroot, policy=lic_policy)
            if not any(
                h.get("licenseId") == "GPL-3.0"
                for h in (bom_exp["summary"].get("forbiddenLicenses") or [])
            ):
                print("smoke failed exceptions: expired must still be a hit", bom_exp["summary"])
                return 1
            if not any(
                e.get("component") == "leftpad"
                for e in (bom_exp["summary"].get("expiredExceptions") or [])
            ):
                print("smoke failed exceptions: expiredExceptions missing", bom_exp["summary"])
                return 1
            if bom_exp["summary"].get("waived"):
                print("smoke failed exceptions: expired must not waive", bom_exp["summary"])
                return 1
            extra = eroot / "waivers.json"
            extra.write_text(
                json.dumps(
                    {
                        "exceptions": [
                            {
                                "component": "left*",
                                "license": "GPL-3.0",
                                "reason": "glob waiver",
                                "expires": "2099-01-01",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (eroot / EXCEPTIONS_FILENAME).unlink()
            bom_cli = scan_path(eroot, policy=lic_policy, exceptions_path=str(extra))
            if not any(
                w.get("component") == "leftpad" for w in (bom_cli["summary"].get("waived") or [])
            ):
                print("smoke failed exceptions: --exceptions glob path", bom_cli["summary"])
                return 1
            (eroot / EXCEPTIONS_FILENAME).write_text("{not-json", encoding="utf-8")
            bom_bad = scan_path(eroot, policy=lic_policy)
            if not any(
                h.get("licenseId") == "GPL-3.0"
                for h in (bom_bad["summary"].get("forbiddenLicenses") or [])
            ):
                print("smoke failed exceptions: bad JSON must not crash/waive", bom_bad["summary"])
                return 1
            (eroot / EXCEPTIONS_FILENAME).write_text(
                json.dumps({"exceptions": [{"license": "GPL-3.0"}]}),
                encoding="utf-8",
            )
            bom_skip_entry = scan_path(eroot, policy=lic_policy)
            if not any(
                h.get("licenseId") == "GPL-3.0"
                for h in (bom_skip_entry["summary"].get("forbiddenLicenses") or [])
            ):
                print("smoke failed exceptions: incomplete entry must skip", bom_skip_entry["summary"])
                return 1
            entries, warns = load_exceptions_file(eroot / EXCEPTIONS_FILENAME)
            if entries or not warns:
                print("smoke failed exceptions: incomplete entry warnings", entries, warns)
                return 1
        resolve_ok = (
            resolve_exceptions_path(None, env={}) is None
            and resolve_exceptions_path(None, env={ENV_EXCEPTIONS: "/tmp/x.json"})
            == "/tmp/x.json"
            and resolve_exceptions_path("", env={ENV_EXCEPTIONS: "/tmp/x.json"}) is None
            and resolve_exceptions_path("/cli.json", env={ENV_EXCEPTIONS: "/env.json"})
            == "/cli.json"
            and exceptions_query_skips("", present=True)
            and exceptions_query_skips("skip", present=True)
            and not exceptions_query_skips("skip", present=False)
            and component_name_matches("leftpad", "leftpad")
            and component_name_matches("leftpad", "left*")
            and not component_name_matches("other", "leftpad")
        )
        if not resolve_ok:
            print("smoke failed exceptions resolve/match helpers")
            return 1

        cors = normalize_cors(["http://localhost:3000"])
        star = normalize_cors(["*"])
        pf_ok = handle_preflight("http://localhost:3000", cors) or {}
        pf_evil = handle_preflight("http://evil.example", cors) or {}
        cors_ok = (
            cors is not None
            and origin_allowed("http://localhost:3000", cors)
            and not origin_allowed("http://evil.example", cors)
            and acao_value("http://localhost:3000", cors) == "http://localhost:3000"
            and acao_value("http://evil.example", cors) is None
            and pf_ok.get("status") == 204
            and pf_evil.get("status") == 403
            and handle_preflight("http://localhost:3000", None) is None
            and normalize_cors([]) is None
            and normalize_cors(None) is None
            and star is not None
            and origin_allowed("http://evil.example", star)
            and acao_value("http://evil.example", star) == "*"
            and cors_response_headers("http://localhost:3000", cors).get(
                "Access-Control-Allow-Origin"
            )
            == "http://localhost:3000"
            and "Access-Control-Allow-Origin"
            not in cors_response_headers("http://evil.example", cors)
            and parse_cors_origins("") == []
            and parse_cors_origins("http://localhost:3000, *")
            == ["http://localhost:3000", "*"]
            and resolve_cors_origins(None, env={}) == []
            and resolve_cors_origins(
                None, env={ENV_CORS_ORIGINS: "http://localhost:3000"}
            )
            == ["http://localhost:3000"]
            and resolve_cors_origins("", env={ENV_CORS_ORIGINS: "*"}) == []
            and resolve_cors_origins("*", env={}) == ["*"]
            and "GET" in DEFAULT_CORS_METHODS
            and "OPTIONS" in DEFAULT_CORS_METHODS
            and "HEAD" in DEFAULT_CORS_METHODS
            and "Content-Type" in DEFAULT_CORS_HEADERS
            and "X-Request-Id" in DEFAULT_CORS_HEADERS
            and "X-Request-Id" in DEFAULT_CORS_EXPOSE_HEADERS
            and any(h.lower() == "retry-after" for h in DEFAULT_CORS_EXPOSE_HEADERS)
            and "X-Request-Id" in (cors.get("headers") or [])
            and "X-Request-Id" in (cors.get("expose") or [])
            and any(h.lower() == "retry-after" for h in (cors.get("expose") or []))
            and "Content-Type"
            in str((pf_ok.get("headers") or {}).get("Access-Control-Allow-Headers", ""))
            and "X-Request-Id"
            in str((pf_ok.get("headers") or {}).get("Access-Control-Allow-Headers", ""))
            and "X-Request-Id"
            in str(
                cors_response_headers("http://localhost:3000", cors).get(
                    "Access-Control-Expose-Headers", ""
                )
            )
            and "retry-after"
            in str(
                cors_response_headers("http://localhost:3000", cors).get(
                    "Access-Control-Expose-Headers", ""
                )
            ).lower()
            and "retry-after"
            in str((pf_ok.get("headers") or {}).get("Access-Control-Expose-Headers", "")).lower()
        )
        if not cors_ok:
            print("smoke failed cors")
            return 1

        rl = SlidingWindowRateLimiter(window_seconds=60.0)
        assert rl.check("127.0.0.1", 2)[0] is True
        assert rl.check("127.0.0.1", 2)[0] is True
        allowed, retry_after = rl.check("127.0.0.1", 2)
        if allowed or retry_after < 1:
            print("smoke failed rate_limit sliding window", allowed, retry_after)
            return 1
        if not rl.check("10.0.0.1", 2)[0]:
            print("smoke failed rate_limit ip isolation")
            return 1
        if (
            not skip_rate_limit("/health")
            or not skip_rate_limit("/ready")
            or not skip_rate_limit("/metrics")
            or skip_rate_limit("/bom.json")
            or skip_rate_limit("/v1/bom")
            or skip_rate_limit("/v1/bom.xml")
            or skip_rate_limit("/v1/bom.spdx.xml")
            or skip_rate_limit("/v1/bom.md")
            or skip_rate_limit("/v1/bom.html")
            or skip_rate_limit("/v1/policy")
            or skip_rate_limit("/v1/config")
            or skip_rate_limit("/v1/components")
            or skip_rate_limit("/")
        ):
            print("smoke failed rate_limit skip paths")
            return 1
        if client_ip_from_headers({"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}) != "1.2.3.4":
            print("smoke failed rate_limit xff first hop")
            return 1
        if client_ip_from_headers({}, remote="127.0.0.1") != "127.0.0.1":
            print("smoke failed rate_limit socket fallback")
            return 1
        if (
            resolve_rate_limit(None, env={}) != DEFAULT_RATE_LIMIT_PER_MINUTE
            or resolve_rate_limit(2, env={ENV_RATE_LIMIT_PER_MINUTE: "9"}) != 2
            or resolve_rate_limit(None, env={ENV_RATE_LIMIT_PER_MINUTE: "3"}) != 3
            or resolve_rate_limit(None, env={ENV_RATE_LIMIT_RPM: "4"}) != 4
            or resolve_rate_limit(0, env={}) is not None
        ):
            print("smoke failed rate_limit resolve")
            return 1

        custom_rid = "mvp-req-id-a1b2c3d4"
        rid_ok = (
            resolve_request_id({"X-Request-Id": custom_rid}) == custom_rid
            and is_uuid(resolve_request_id({}))
            and is_uuid(resolve_request_id({"X-Request-Id": "  "}))
            and sanitize_request_id("foo\r\nX-Injected: 1") == "fooX-Injected: 1"
            and len(sanitize_request_id("x" * 200) or "") == 128
            and sanitize_request_id("") is None
        )
        if not rid_ok:
            print("smoke failed X-Request-Id resolve/sanitize")
            return 1

        access_line = format_access_log(
            service="ai-bom",
            method="GET",
            path="/bom.json",
            status=200,
            duration_ms=12,
            request_id="test-log-1",
        )
        try:
            access_obj = json.loads(access_line)
        except json.JSONDecodeError:
            access_obj = {}
        access_ok = (
            access_obj.get("level") == "info"
            and access_obj.get("msg") == "http"
            and access_obj.get("service") == "ai-bom"
            and access_obj.get("method") == "GET"
            and access_obj.get("path") == "/bom.json"
            and access_obj.get("status") == 200
            and access_obj.get("requestId") == "test-log-1"
            and isinstance(access_obj.get("durationMs"), (int, float))
            and access_obj.get("durationMs") == 12
            and '"msg":"http"' in access_line
            and should_skip_access_log("GET", "/metrics")
            and should_skip_access_log("GET", "/health")
            and should_skip_access_log("GET", "/ready")
            and should_skip_access_log("OPTIONS", "/bom.json")
            and not should_skip_access_log("GET", "/bom.json")
            and not should_skip_access_log("GET", "/v1/config")
            and resolve_log_json(None, env={}) is False
            and resolve_log_json(None, env={"LOG_FORMAT": "json"}) is True
            and resolve_log_json(True, env={}) is True
            and resolve_log_json(False, env={"LOG_FORMAT": "json"}) is False
        )
        if not access_ok:
            print("smoke failed JSON access log format/resolve", access_line)
            return 1

        hook_ok = (
            resolve_webhook_url(None, env={}) is None
            and resolve_webhook_url(
                None, env={ENV_WEBHOOK_URL: "http://127.0.0.1:9/hook"}
            )
            == "http://127.0.0.1:9/hook"
            and resolve_webhook_url("", env={ENV_WEBHOOK_URL: "http://x"}) is None
            and resolve_webhook_url(
                "http://cli/hook", env={ENV_WEBHOOK_URL: "http://env/hook"}
            )
            == "http://cli/hook"
            and parse_webhook_url("  ") is None
            and parse_webhook_url(None) is None
            and resolve_webhook_secret(None, env={}) is None
            and resolve_webhook_secret(
                None, env={ENV_WEBHOOK_SECRET: "whsec_env"}
            )
            == "whsec_env"
            and resolve_webhook_secret("", env={ENV_WEBHOOK_SECRET: "whsec_env"})
            is None
            and resolve_webhook_secret(
                "whsec_cli", env={ENV_WEBHOOK_SECRET: "whsec_env"}
            )
            == "whsec_cli"
            and DEFAULT_TIMEOUT_S > 0
            and DEFAULT_TIMEOUT_S <= 2
        )
        if not hook_ok:
            print("smoke failed webhook resolve")
            return 1
        hit_bom = {
            "summary": {
                "policyHits": 2,
                "forbidden": [{"pattern": "pickle.load", "path": "app.py"}],
                "forbiddenLicenses": [],
                "disclosureGaps": [],
                "models": ["gpt-4o-mini"],
            }
        }
        clean_bom = {
            "summary": {
                "policyHits": 0,
                "forbidden": [],
                "forbiddenLicenses": [],
                "disclosureGaps": [],
            }
        }
        lic_bom = {
            "summary": {
                "policyHits": 1,
                "forbidden": [],
                "forbiddenLicenses": [{"licenseId": "GPL-3.0", "component": "x"}],
            }
        }
        hook_payload = build_webhook_payload(hit_bom)
        hook_payload_ok = (
            hook_payload.get("ok") is False
            and hook_payload.get("policyHits") == 2
            and isinstance(hook_payload.get("forbiddenLicenses"), list)
            and isinstance(hook_payload.get("summary"), dict)
            and set(hook_payload) == {"ok", "policyHits", "forbiddenLicenses", "summary"}
            and should_notify_policy_hit(hit_bom)
            and should_notify_policy_hit(lic_bom)
            and not should_notify_policy_hit(clean_bom)
            and not should_notify_policy_hit(None)
            and not should_notify_policy_hit({})
        )
        if not hook_payload_ok:
            print("smoke failed webhook payload")
            return 1
        hmac_body = b'{"ok":false,"policyHits":1}'
        hmac_sig = sign_webhook_body("whsec_smoke", hmac_body)
        hmac_ok = (
            hmac_sig.startswith("sha256=")
            and len(hmac_sig) == len("sha256=") + 64
            and verify_webhook_signature("whsec_smoke", hmac_body, hmac_sig)
            and verify_webhook_signature(
                "whsec_smoke", hmac_body, hmac_sig.upper()
            )
            and not verify_webhook_signature("whsec_other", hmac_body, hmac_sig)
            and not verify_webhook_signature("whsec_smoke", hmac_body, None)
            and not verify_webhook_signature(None, hmac_body, hmac_sig)
            and not verify_webhook_signature("whsec_smoke", b"tampered", hmac_sig)
        )
        if not hmac_ok:
            print("smoke failed webhook HMAC sign/verify")
            return 1
        import time as _time
        ts_now = webhook_unix_seconds()
        wall = int(_time.time())
        ts_ok = (
            TIMESTAMP_HEADER == "X-Webhook-Timestamp"
            and abs(wall - ts_now) <= 2
            and webhook_unix_seconds(1_700_000_000.9) == 1_700_000_000
        )
        if not ts_ok:
            print("smoke failed webhook timestamp")
            return 1

        retry_policy_ok = (
            DEFAULT_RETRY_DELAY_S == 0.05
            and should_retry_webhook(status=500)
            and should_retry_webhook(status=503)
            and should_retry_webhook(status=599)
            and should_retry_webhook(error=OSError("network"))
            and not should_retry_webhook(status=200)
            and not should_retry_webhook(status=204)
            and not should_retry_webhook(status=400)
            and not should_retry_webhook(status=404)
            and not should_retry_webhook(status=429)
            and not should_retry_webhook()
        )
        if not retry_policy_ok:
            print("smoke failed webhook should_retry_webhook policy")
            return 1

        class _FakeResp:
            def __init__(self, status=200):
                self.status = status
                self.code = status

            def read(self):
                return b""

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        import urllib.error as _ue

        def _req_header(req, name):
            items = dict(req.header_items()) if hasattr(req, "header_items") else dict(req.headers or {})
            want = str(name).lower()
            for k, v in items.items():
                if str(k).lower() == want:
                    return v
            return None

        def _run_post(urlopen_fn, extra=None):
            extra = extra or {}
            sleeps = []
            post_policy_webhook(
                "http://127.0.0.1:9/hook",
                hook_payload,
                urlopen=urlopen_fn,
                sleep=lambda s: sleeps.append(s),
                retry_delay=extra.get("retry_delay", DEFAULT_RETRY_DELAY_S),
                secret=extra.get("secret"),
            )
            return sleeps

        calls200 = []

        def urlopen_200(req, timeout=None):
            calls200.append(req)
            return _FakeResp(200)

        sleeps = _run_post(urlopen_200)
        if len(calls200) != 1 or sleeps:
            print(f"smoke failed webhook no-retry on 200 calls={len(calls200)} sleeps={sleeps}")
            return 1

        calls400 = []

        def urlopen_400(req, timeout=None):
            calls400.append(req)
            return _FakeResp(400)

        sleeps = _run_post(urlopen_400)
        if len(calls400) != 1 or sleeps:
            print(f"smoke failed webhook no-retry on 4xx calls={len(calls400)} sleeps={sleeps}")
            return 1

        calls500 = []

        def urlopen_500(req, timeout=None):
            calls500.append(req)
            if len(calls500) == 1:
                return _FakeResp(500)
            return _FakeResp(200)

        sleeps = _run_post(urlopen_500)
        if (
            len(calls500) != 2
            or sleeps != [DEFAULT_RETRY_DELAY_S]
            or calls500[0].data != calls500[1].data
        ):
            print(f"smoke failed webhook retry on 5xx calls={len(calls500)} sleeps={sleeps}")
            return 1

        calls_net = []

        def urlopen_net(req, timeout=None):
            calls_net.append(req)
            if len(calls_net) == 1:
                raise _ue.URLError("ECONNRESET")
            return _FakeResp(200)

        sleeps = _run_post(urlopen_net)
        if len(calls_net) != 2 or sleeps != [DEFAULT_RETRY_DELAY_S]:
            print(f"smoke failed webhook retry on network error calls={len(calls_net)} sleeps={sleeps}")
            return 1

        calls_hmac = []

        def urlopen_hmac(req, timeout=None):
            calls_hmac.append(req)
            if len(calls_hmac) == 1:
                return _FakeResp(503)
            return _FakeResp(200)

        sleeps = _run_post(urlopen_hmac, {"secret": "whsec_retry", "retry_delay": 0})
        if len(calls_hmac) != 2:
            print(f"smoke failed webhook HMAC retry call count {len(calls_hmac)}")
            return 1
        sig0 = _req_header(calls_hmac[0], SIGNATURE_HEADER)
        sig1 = _req_header(calls_hmac[1], SIGNATURE_HEADER)
        expected = sign_webhook_body("whsec_retry", calls_hmac[0].data)
        if sig0 != expected or sig1 != expected:
            print(f"smoke failed webhook HMAC retry signatures {sig0} {sig1}")
            return 1
        ts0 = _req_header(calls_hmac[0], TIMESTAMP_HEADER)
        ts1 = _req_header(calls_hmac[1], TIMESTAMP_HEADER)
        if not ts0 or not ts1:
            print(f"smoke failed webhook timestamp on retry ts0={ts0} ts1={ts1}")
            return 1


        try:
            notify_policy_hit(None, hit_bom)
            notify_policy_hit("http://127.0.0.1:1/nope", clean_bom)
            notify_policy_hit(
                "http://127.0.0.1:1/nope", hit_bom, timeout=0.05, retry_delay=0
            )
            notify_policy_hit(
                "http://127.0.0.1:1/nope",
                hit_bom,
                timeout=0.05,
                secret="whsec_smoke",
                retry_delay=0,
            )
        except Exception as e:
            print(f"smoke failed webhook notify swallow: {e}")
            return 1

        spec_path = Path(__file__).resolve().parents[2] / "openapi" / "bom.openapi.json"
        try:
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"smoke failed openapi load: {e}")
            return 1
        need = ["/health", "/ready", "/bom.json", "/v1/bom", "/v1/bom.sarif", "/v1/bom.xml", "/v1/bom.spdx.xml", "/v1/bom.md", "/v1/bom.gha.txt", "/v1/bom.html", "/v1/policy", "/v1/config", "/v1/components", "/v1/exceptions", "/evidence.md", "/", "/metrics", "/openapi.json"]
        paths = spec.get("paths") or {}
        missing = [p for p in need if p not in paths]
        get_health = ((paths.get("/health") or {}).get("get") or {}).get("responses") or {}
        get_bom = ((paths.get("/bom.json") or {}).get("get") or {}).get("responses") or {}
        get_v1 = ((paths.get("/v1/bom") or {}).get("get") or {}).get("responses") or {}
        get_ev = ((paths.get("/evidence.md") or {}).get("get") or {}).get("responses") or {}
        get_idx = ((paths.get("/") or {}).get("get") or {}).get("responses") or {}
        get_metrics = ((paths.get("/metrics") or {}).get("get") or {}).get("responses") or {}
        responses = ((spec.get("components") or {}).get("responses") or {})
        params = ((spec.get("components") or {}).get("parameters") or {})
        headers = ((spec.get("components") or {}).get("headers") or {})
        desc = str((spec.get("info") or {}).get("description") or "")
        openapi_ok = (
            not missing
            and str(spec.get("openapi") or "").startswith("3.")
            and "get" in (paths.get("/health") or {})
            and "get" in (paths.get("/ready") or {})
            and ((paths.get("/ready") or {}).get("get") or {}).get("operationId") == "getReady"
            and "get" in (paths.get("/bom.json") or {})
            and "get" in (paths.get("/evidence.md") or {})
            and "get" in (paths.get("/") or {})
            and "get" in (paths.get("/openapi.json") or {})
            and "get" in (paths.get("/metrics") or {})
            and ((paths.get("/metrics") or {}).get("get") or {}).get("operationId") == "getMetrics"
            and "GET /metrics" in desc
            and "ai_bom_component_count" in desc
            and "403" in get_health
            and "403" in get_bom
            and "403" in get_v1
            and "400" in get_v1
            and "403" in get_ev
            and "403" in get_idx
            and "403" in get_metrics
            and "CorsDenied" in responses
            and ("403" in desc or "cors_denied" in desc)
            and ("X-Request-Id" in desc or "requestId" in desc)
            and "XRequestId" in params
            and "XRequestId" in headers
            and ((paths.get("/health") or {}).get("get") or {}).get("operationId") == "getHealth"
            and ((paths.get("/ready") or {}).get("get") or {}).get("operationId") == "getReady"
            and "503" in (((paths.get("/ready") or {}).get("get") or {}).get("responses") or {})
            and "shutting_down" in str(((spec.get("components") or {}).get("schemas") or {}).get("Ready") or "")
            and ((paths.get("/bom.json") or {}).get("get") or {}).get("operationId") == "getBom"
            and "get" in (paths.get("/v1/bom") or {})
            and ((paths.get("/v1/bom") or {}).get("get") or {}).get("operationId") == "getBomV1"
            and "BomFormat" in params
            and "sarif" in (((params.get("BomFormat") or {}).get("schema") or {}).get("enum") or [])
            and "json" in (((params.get("BomFormat") or {}).get("schema") or {}).get("enum") or [])
            and "cyclonedx-xml" in (((params.get("BomFormat") or {}).get("schema") or {}).get("enum") or [])
            and "spdx-xml" in (((params.get("BomFormat") or {}).get("schema") or {}).get("enum") or [])
            and "spdx3" in (((params.get("BomFormat") or {}).get("schema") or {}).get("enum") or [])
            and "md" in (((params.get("BomFormat") or {}).get("schema") or {}).get("enum") or [])
            and "gha" in (((params.get("BomFormat") or {}).get("schema") or {}).get("enum") or [])
            and "html" in (((params.get("BomFormat") or {}).get("schema") or {}).get("enum") or [])
            and ((paths.get("/v1/bom.sarif") or {}).get("get") or {}).get("operationId") == "getBomSarif"
            and "get" in (paths.get("/v1/bom.xml") or {})
            and ((paths.get("/v1/bom.xml") or {}).get("get") or {}).get("operationId") == "getBomXml"
            and "get" in (paths.get("/v1/bom.spdx.xml") or {})
            and ((paths.get("/v1/bom.spdx.xml") or {}).get("get") or {}).get("operationId") == "getBomSpdxXml"
            and "get" in (paths.get("/v1/bom.md") or {})
            and ((paths.get("/v1/bom.md") or {}).get("get") or {}).get("operationId") == "getBomMd"
            and "get" in (paths.get("/v1/bom.gha.txt") or {})
            and ((paths.get("/v1/bom.gha.txt") or {}).get("get") or {}).get("operationId") == "getBomGha"
            and "get" in (paths.get("/v1/bom.html") or {})
            and ((paths.get("/v1/bom.html") or {}).get("get") or {}).get("operationId") == "getBomHtml"
            and "get" in (paths.get("/v1/policy") or {})
            and ((paths.get("/v1/policy") or {}).get("get") or {}).get("operationId") == "getPolicy"
            and "PolicyGate" in ((spec.get("components") or {}).get("schemas") or {})
            and "403" in (((paths.get("/v1/policy") or {}).get("get") or {}).get("responses") or {})
            and "429" in (((paths.get("/v1/policy") or {}).get("get") or {}).get("responses") or {})
            and "GET /v1/policy" in desc
            and "get" in (paths.get("/v1/config") or {})
            and ((paths.get("/v1/config") or {}).get("get") or {}).get("operationId") == "getConfig"
            and "RuntimeConfig" in ((spec.get("components") or {}).get("schemas") or {})
            and "403" in (((paths.get("/v1/config") or {}).get("get") or {}).get("responses") or {})
            and "429" in (((paths.get("/v1/config") or {}).get("get") or {}).get("responses") or {})
            and "GET /v1/config" in desc
            and "get" in (paths.get("/v1/components") or {})
            and ((paths.get("/v1/components") or {}).get("get") or {}).get("operationId") == "listComponents"
            and "ComponentInventory" in ((spec.get("components") or {}).get("schemas") or {})
            and "403" in (((paths.get("/v1/components") or {}).get("get") or {}).get("responses") or {})
            and "429" in (((paths.get("/v1/components") or {}).get("get") or {}).get("responses") or {})
            and "GET /v1/components" in desc
            and "get" in (paths.get("/v1/exceptions") or {})
            and ((paths.get("/v1/exceptions") or {}).get("get") or {}).get("operationId") == "listExceptions"
            and "ExceptionInventory" in ((spec.get("components") or {}).get("schemas") or {})
            and "403" in (((paths.get("/v1/exceptions") or {}).get("get") or {}).get("responses") or {})
            and "429" in (((paths.get("/v1/exceptions") or {}).get("get") or {}).get("responses") or {})
            and "GET /v1/exceptions" in desc
            and "hasUrl" in str(((spec.get("components") or {}).get("schemas") or {}).get("RuntimeConfig") or {})
            and "hasSecret" in str(((spec.get("components") or {}).get("schemas") or {}).get("RuntimeConfig") or {})
            and "RateLimited" in responses
            and "429" in get_bom
            and "429" in get_v1
            and ("rate_limited" in desc or "429" in desc)
            and "Retry-After" in desc
            and "retry-after"
            in str(((spec.get("components") or {}).get("schemas") or {}).get("CorsConfig") or {}).lower()
        )
        if not openapi_ok:
            print(f"smoke failed openapi paths missing={missing}")
            return 1

        zero = render_metrics()
        sample = render_metrics(
            {
                "components": [{}, {}, {}],
                "summary": {
                    "policyHits": 2,
                    "forbiddenLicenses": [{"licenseId": "GPL-3.0"}],
                },
            }
        )
        healthish = render_metrics(
            {"componentCount": 4, "policyHits": 1, "forbiddenLicenses": []}
        )
        metrics_ok = (
            METRIC_COMPONENT_COUNT in zero
            and METRIC_POLICY_HITS in zero
            and METRIC_FORBIDDEN_LICENSES in zero
            and f"{METRIC_COMPONENT_COUNT} 0" in zero
            and f"{METRIC_POLICY_HITS} 0" in zero
            and f"{METRIC_FORBIDDEN_LICENSES} 0" in zero
            and f"{METRIC_COMPONENT_COUNT} 3" in sample
            and f"{METRIC_POLICY_HITS} 2" in sample
            and f"{METRIC_FORBIDDEN_LICENSES} 1" in sample
            and f"{METRIC_COMPONENT_COUNT} 4" in healthish
            and f"{METRIC_POLICY_HITS} 1" in healthish
            and f"{METRIC_FORBIDDEN_LICENSES} 0" in healthish
            and f"# TYPE {METRIC_COMPONENT_COUNT} gauge" in sample
            and f"# TYPE {METRIC_POLICY_HITS} gauge" in sample
            and f"# TYPE {METRIC_FORBIDDEN_LICENSES} gauge" in sample
            and "text/plain" in METRICS_CONTENT_TYPE
            and "0.0.4" in METRICS_CONTENT_TYPE
        )
        if not metrics_ok:
            print("smoke failed metrics render")
            return 1

        if WATCH_POLL_MS != 500:
            print(f"smoke failed WATCH_POLL_MS expected 500 got {WATCH_POLL_MS}")
            return 1
        import os as _os
        import time as _watch_time
        with tempfile.TemporaryDirectory() as watch_td:
            wroot = Path(watch_td)
            (wroot / "app.py").write_text(
                'MODEL = "gpt-4o-mini"\n', encoding="utf-8"
            )
            m0 = walk_max_mtime(wroot)
            snap0 = build_snapshot(wroot)
            c0 = int((snap0.get("health") or {}).get("componentCount") or 0)
            extra = wroot / "extra.py"
            extra.write_text('MODEL = "claude-3-opus"\n', encoding="utf-8")
            later = _watch_time.time() + 1
            _os.utime(extra, (later, later))
            m1 = walk_max_mtime(wroot)
            snap1 = build_snapshot(wroot)
            c1 = int((snap1.get("health") or {}).get("componentCount") or 0)
            if not (m1 > m0) or not (c1 > c0):
                print(f"smoke failed walk/rescan m0={m0} m1={m1} c0={c0} c1={c1}")
                return 1
            httpd = None
            try:
                httpd, snap_s = create_bom_server(wroot, host="127.0.0.1", port=0)
                before = int((snap_s.get("health") or {}).get("componentCount") or 0)
                (wroot / "third.py").write_text(
                    'MODEL = "qwen-plus"\n', encoding="utf-8"
                )
                after = int(
                    (httpd.reload_snapshot().get("health") or {}).get("componentCount") or 0
                )
                if not (after > before):
                    print(f"smoke failed serve reload {before} -> {after}")
                    return 1
                if (
                    resolve_drain_ms(200) != 200
                    or resolve_drain_ms(-1) != DEFAULT_SHUTDOWN_DRAIN_MS
                    or resolve_drain_ms(99999) != MAX_SHUTDOWN_DRAIN_MS
                ):
                    print("smoke failed resolve_drain_ms")
                    return 1
                import threading
                import urllib.error
                import urllib.request

                threading.Thread(
                    target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True
                ).start()
                host, port = httpd.server_address[:2]
                base = f"http://{host}:{port}"
                import time as _sd_time
                for _ in range(50):
                    try:
                        urllib.request.urlopen(base + "/health")
                        break
                    except Exception:
                        _sd_time.sleep(0.02)
                else:
                    print("smoke failed shutdown serve did not listen")
                    return 1
                with urllib.request.urlopen(base + "/v1/bom?format=sarif") as resp:
                    ctype = (resp.headers.get("Content-Type") or "").lower()
                    sarif_http = json.loads(resp.read().decode("utf-8"))
                    if resp.status != 200:
                        print(f"smoke failed HTTP sarif status {resp.status}")
                        return 1
                    if sarif_http.get("version") != "2.1.0" or not isinstance(
                        sarif_http.get("runs"), list
                    ):
                        print(f"smoke failed HTTP sarif body {sarif_http}")
                        return 1
                    if "json" not in ctype:
                        print(f"smoke failed HTTP sarif content-type {ctype}")
                        return 1
                with urllib.request.urlopen(base + "/v1/bom.sarif") as resp:
                    alias = json.loads(resp.read().decode("utf-8"))
                    if alias.get("version") != "2.1.0" or not isinstance(
                        alias.get("runs"), list
                    ):
                        print(f"smoke failed HTTP /v1/bom.sarif {alias}")
                        return 1
                with urllib.request.urlopen(base + "/v1/bom?format=cyclonedx-xml") as resp:
                    ctype = (resp.headers.get("Content-Type") or "").lower()
                    xml_http = resp.read().decode("utf-8")
                    if resp.status != 200:
                        print(f"smoke failed HTTP cyclonedx-xml status {resp.status}")
                        return 1
                    if not xml_http.lstrip().startswith("<bom"):
                        print(f"smoke failed HTTP cyclonedx-xml start {xml_http[:80]!r}")
                        return 1
                    if "http://cyclonedx.org/schema/bom/1.7" not in xml_http:
                        print("smoke failed HTTP cyclonedx-xml xmlns 1.7")
                        return 1
                    if "xml" not in ctype:
                        print(f"smoke failed HTTP cyclonedx-xml content-type {ctype}")
                        return 1
                with urllib.request.urlopen(base + "/v1/bom.xml") as resp:
                    alias_xml = resp.read().decode("utf-8")
                    if not alias_xml.lstrip().startswith("<bom") or "bom/1.7" not in alias_xml:
                        print(f"smoke failed HTTP /v1/bom.xml {alias_xml[:80]!r}")
                        return 1
                with urllib.request.urlopen(base + "/v1/bom?format=spdx-xml") as resp:
                    ctype = (resp.headers.get("Content-Type") or "").lower()
                    spdx_xml_http = resp.read().decode("utf-8")
                    if resp.status != 200:
                        print(f"smoke failed HTTP spdx-xml status {resp.status}")
                        return 1
                    if not spdx_xml_http.lstrip().startswith("<SpdxDocument"):
                        print(f"smoke failed HTTP spdx-xml start {spdx_xml_http[:80]!r}")
                        return 1
                    if "SPDX-2.3" not in spdx_xml_http:
                        print("smoke failed HTTP spdx-xml SPDX-2.3")
                        return 1
                    if "xml" not in ctype:
                        print(f"smoke failed HTTP spdx-xml content-type {ctype}")
                        return 1
                with urllib.request.urlopen(base + "/v1/bom.spdx.xml") as resp:
                    alias_spdx_xml = resp.read().decode("utf-8")
                    if not alias_spdx_xml.lstrip().startswith("<SpdxDocument") or "SPDX-2.3" not in alias_spdx_xml:
                        print(f"smoke failed HTTP /v1/bom.spdx.xml {alias_spdx_xml[:80]!r}")
                        return 1
                with urllib.request.urlopen(base + "/v1/bom?format=spdx3") as resp:
                    ctype = (resp.headers.get("Content-Type") or "").lower()
                    spdx3_http = json.loads(resp.read().decode("utf-8"))
                    if resp.status != 200:
                        print(f"smoke failed HTTP spdx3 status {resp.status}")
                        return 1
                    http_ci = spdx3_http.get("creationInfo") if isinstance(spdx3_http.get("creationInfo"), dict) else {}
                    if http_ci.get("specVersion") != "3.0.1":
                        print(f"smoke failed HTTP spdx3 specVersion {http_ci}")
                        return 1
                    if not spdx3_http.get("spdxId") or not isinstance(spdx3_http.get("element"), list):
                        print(f"smoke failed HTTP spdx3 body keys {list(spdx3_http)}")
                        return 1
                    if "json" not in ctype:
                        print(f"smoke failed HTTP spdx3 content-type {ctype}")
                        return 1
                with urllib.request.urlopen(base + "/v1/bom?format=md") as resp:
                    ctype = (resp.headers.get("Content-Type") or "").lower()
                    md_http = resp.read().decode("utf-8")
                    if resp.status != 200:
                        print(f"smoke failed HTTP md status {resp.status}")
                        return 1
                    if not md_http.lstrip().startswith("# "):
                        print(f"smoke failed HTTP md start {md_http[:80]!r}")
                        return 1
                    if "policyHits" not in md_http:
                        print("smoke failed HTTP md policyHits")
                        return 1
                    if "markdown" not in ctype:
                        print(f"smoke failed HTTP md content-type {ctype}")
                        return 1
                with urllib.request.urlopen(base + "/v1/bom.md") as resp:
                    alias_md = resp.read().decode("utf-8")
                    if not alias_md.lstrip().startswith("# ") or "AI-BOM" not in alias_md:
                        print(f"smoke failed HTTP /v1/bom.md {alias_md[:80]!r}")
                        return 1
                with urllib.request.urlopen(base + "/v1/bom?format=gha") as resp:
                    ctype = (resp.headers.get("Content-Type") or "").lower()
                    gha_http = resp.read().decode("utf-8")
                    if resp.status != 200:
                        print(f"smoke failed HTTP gha status {resp.status}")
                        return 1
                    if "::error" in gha_http:
                        print(f"smoke failed HTTP gha clean scan {gha_http!r}")
                        return 1
                    if "text/plain" not in ctype:
                        print(f"smoke failed HTTP gha content-type {ctype}")
                        return 1
                with urllib.request.urlopen(base + "/v1/bom.gha.txt") as resp:
                    alias_gha = resp.read().decode("utf-8")
                    if resp.status != 200:
                        print(f"smoke failed HTTP /v1/bom.gha.txt status {resp.status}")
                        return 1
                    if "::error" in alias_gha:
                        print(f"smoke failed HTTP /v1/bom.gha.txt clean {alias_gha!r}")
                        return 1
                with urllib.request.urlopen(base + "/v1/bom?format=html") as resp:
                    ctype = (resp.headers.get("Content-Type") or "").lower()
                    html_http = resp.read().decode("utf-8")
                    if resp.status != 200:
                        print(f"smoke failed HTTP html status {resp.status}")
                        return 1
                    if "<table" not in html_http and "AI-BOM" not in html_http:
                        print(f"smoke failed HTTP html body {html_http[:120]!r}")
                        return 1
                    if "html" not in ctype:
                        print(f"smoke failed HTTP html content-type {ctype}")
                        return 1
                with urllib.request.urlopen(base + "/v1/bom.html") as resp:
                    alias_html = resp.read().decode("utf-8")
                    if resp.status != 200:
                        print(f"smoke failed HTTP /v1/bom.html status {resp.status}")
                        return 1
                    if "<h1" not in alias_html or "AI-BOM" not in alias_html:
                        print(f"smoke failed HTTP /v1/bom.html {alias_html[:80]!r}")
                        return 1
                    if "<table" not in alias_html:
                        print("smoke failed HTTP /v1/bom.html missing table")
                        return 1
                req_pol = urllib.request.Request(
                    base + "/v1/policy", headers={"X-Request-Id": "smoke-policy-empty"}
                )
                with urllib.request.urlopen(req_pol) as resp:
                    ctype = (resp.headers.get("Content-Type") or "").lower()
                    pol_empty = json.loads(resp.read().decode("utf-8"))
                    if resp.status != 200:
                        print(f"smoke failed HTTP /v1/policy empty status {resp.status}")
                        return 1
                    if pol_empty.get("ok") is not True:
                        print(f"smoke failed HTTP /v1/policy empty body {pol_empty}")
                        return 1
                    if pol_empty.get("forbiddenLicenseIds") not in ([], None) and pol_empty.get("forbiddenLicenseIds"):
                        print(f"smoke failed HTTP /v1/policy expected empty without policy {pol_empty}")
                        return 1
                    if not isinstance(pol_empty.get("exceptionsCount"), int):
                        print(f"smoke failed HTTP /v1/policy exceptionsCount {pol_empty}")
                        return 1
                    if not isinstance(pol_empty.get("ignoreFile"), bool):
                        print(f"smoke failed HTTP /v1/policy ignoreFile {pol_empty}")
                        return 1
                    if "json" not in ctype:
                        print(f"smoke failed HTTP /v1/policy content-type {ctype}")
                        return 1
                    if (resp.headers.get("X-Request-Id") or "") != "smoke-policy-empty":
                        print(f"smoke failed HTTP /v1/policy X-Request-Id {resp.headers.get('X-Request-Id')}")
                        return 1
                pol_httpd = None
                try:
                    pol_httpd, _snap_p = create_bom_server(
                        wroot, host="127.0.0.1", port=0, policy=lic_policy
                    )
                    threading.Thread(
                        target=pol_httpd.serve_forever,
                        kwargs={"poll_interval": 0.2},
                        daemon=True,
                    ).start()
                    phost, pport = pol_httpd.server_address[:2]
                    pbase = f"http://{phost}:{pport}"
                    for _ in range(50):
                        try:
                            urllib.request.urlopen(pbase + "/health")
                            break
                        except Exception:
                            _sd_time.sleep(0.02)
                    else:
                        print("smoke failed policy serve did not listen")
                        return 1
                    with urllib.request.urlopen(pbase + "/v1/policy") as resp:
                        pol_http = json.loads(resp.read().decode("utf-8"))
                        if resp.status != 200:
                            print(f"smoke failed HTTP /v1/policy status {resp.status}")
                            return 1
                        if pol_http.get("ok") is not True:
                            print(f"smoke failed HTTP /v1/policy body {pol_http}")
                            return 1
                        if "GPL-3.0" not in (pol_http.get("forbiddenLicenseIds") or []):
                            print(f"smoke failed HTTP /v1/policy missing GPL-3.0 {pol_http}")
                            return 1
                        if r"\\bpickle" in json.dumps(pol_http) or "reason" in pol_http:
                            print(f"smoke failed HTTP /v1/policy dumped secrets {pol_http}")
                            return 1
                        if not resp.headers.get("X-Request-Id"):
                            print("smoke failed HTTP /v1/policy missing X-Request-Id")
                            return 1
                finally:
                    if pol_httpd is not None:
                        try:
                            pol_httpd.shutdown()
                        except Exception:
                            pass
                        pol_httpd.server_close()

                from ai_bom.runtime_config import (
                    FORBIDDEN_RUNTIME_CONFIG_KEYS,
                    assert_runtime_config_safe,
                    summarize_runtime_config,
                )

                cfg_payload = summarize_runtime_config(
                    cors_origins=["http://localhost:3000"],
                    rate_limit=120,
                    watch=True,
                    scan_path="/home/user/ugly/sample-app",
                    has_policy_file=True,
                    webhook_url="http://127.0.0.1:9/hook?token=planted_url_token",
                    webhook_secret="whsec_must_not_leak",
                )
                cfg_blob = json.dumps(cfg_payload, ensure_ascii=False)
                cfg_safe = assert_runtime_config_safe(cfg_payload)
                cfg_ok = (
                    cfg_payload.get("ok") is True
                    and (cfg_payload.get("rateLimit") or {}).get("perMinute") == 120
                    and (cfg_payload.get("cors") or {}).get("origins")
                    == ["http://localhost:3000"]
                    and cfg_payload.get("watch") is True
                    and cfg_payload.get("scanPathBase") == "sample-app"
                    and "/home/user" not in cfg_blob
                    and cfg_payload.get("hasPolicyFile") is True
                    and (cfg_payload.get("webhooks") or {}).get("hasUrl") is True
                    and (cfg_payload.get("webhooks") or {}).get("hasSecret") is True
                    and cfg_safe.get("ok") is True
                    and "planted_url_token" not in cfg_blob
                    and "whsec_must_not_leak" not in cfg_blob
                    and "Authorization" not in cfg_blob
                    and "webhookUrl" not in cfg_blob
                    and "webhookSecret" not in cfg_blob
                    and "forbiddenLicenseIds" not in cfg_blob
                    and "secret" in FORBIDDEN_RUNTIME_CONFIG_KEYS
                    and "Authorization" in FORBIDDEN_RUNTIME_CONFIG_KEYS
                )
                empty_cfg = summarize_runtime_config(
                    cors_origins=[],
                    rate_limit=0,
                    watch=False,
                    scan_path=".",
                    has_policy_file=False,
                    webhook_url=None,
                    webhook_secret=None,
                )
                empty_ok = (
                    empty_cfg.get("ok") is True
                    and (empty_cfg.get("webhooks") or {}).get("hasUrl") is False
                    and (empty_cfg.get("webhooks") or {}).get("hasSecret") is False
                    and empty_cfg.get("watch") is False
                    and empty_cfg.get("hasPolicyFile") is False
                    and (empty_cfg.get("rateLimit") or {}).get("perMinute") is None
                    and (empty_cfg.get("cors") or {}).get("origins") == []
                    and "scanPathBase" not in empty_cfg
                    and assert_runtime_config_safe(empty_cfg).get("ok") is True
                )
                if not cfg_ok or not cfg_safe.get("ok") or not empty_ok:
                    print(
                        "smoke failed summarize_runtime_config",
                        cfg_payload,
                        cfg_safe,
                        empty_cfg,
                    )
                    return 1

                req_cfg = urllib.request.Request(
                    base + "/v1/config",
                    headers={"X-Request-Id": "smoke-config-rid"},
                )
                with urllib.request.urlopen(req_cfg) as resp:
                    ctype = (resp.headers.get("Content-Type") or "").lower()
                    cfg_http = json.loads(resp.read().decode("utf-8"))
                    cfg_http_blob = json.dumps(cfg_http, ensure_ascii=False)
                    cors_or_rl = (cfg_http.get("cors") or {}).get("origins") is not None or (
                        cfg_http.get("rateLimit") or {}
                    ).get("perMinute") is not None or (cfg_http.get("rateLimit") or {}) == {
                        "perMinute": None
                    }
                    if resp.status != 200:
                        print(f"smoke failed HTTP /v1/config status {resp.status}")
                        return 1
                    if cfg_http.get("ok") is not True:
                        print(f"smoke failed HTTP /v1/config body {cfg_http}")
                        return 1
                    if not cors_or_rl:
                        print(f"smoke failed HTTP /v1/config missing cors or rateLimit {cfg_http}")
                        return 1
                    if "json" not in ctype:
                        print(f"smoke failed HTTP /v1/config content-type {ctype}")
                        return 1
                    if (resp.headers.get("X-Request-Id") or "") != "smoke-config-rid":
                        print(
                            f"smoke failed HTTP /v1/config X-Request-Id {resp.headers.get('X-Request-Id')}"
                        )
                        return 1
                    if any(
                        n in cfg_http_blob
                        for n in (
                            "whsec_must_not_leak",
                            "planted_url_token",
                            "webhookUrl",
                            "webhookSecret",
                        )
                    ):
                        print(f"smoke failed HTTP /v1/config leaked secret {cfg_http}")
                        return 1

                req_comp = urllib.request.Request(
                    base + "/v1/components",
                    headers={"X-Request-Id": "smoke-components-rid"},
                )
                with urllib.request.urlopen(req_comp) as resp:
                    ctype = (resp.headers.get("Content-Type") or "").lower()
                    comp_http = json.loads(resp.read().decode("utf-8"))
                    comp_blob = json.dumps(comp_http, ensure_ascii=False)
                    names = [c.get("name") for c in (comp_http.get("components") or [])]
                    if resp.status != 200:
                        print(f"smoke failed HTTP /v1/components status {resp.status}")
                        return 1
                    if comp_http.get("ok") is not True:
                        print(f"smoke failed HTTP /v1/components body {comp_http}")
                        return 1
                    if not isinstance(comp_http.get("count"), int) or comp_http.get("count") != len(comp_http.get("components") or []):
                        print(f"smoke failed HTTP /v1/components count {comp_http}")
                        return 1
                    if "gpt-4o-mini" not in names:
                        print(f"smoke failed HTTP /v1/components missing gpt-4o-mini {names}")
                        return 1
                    if any(str((c or {}).get("path") or "").startswith("/") for c in (comp_http.get("components") or [])):
                        print(f"smoke failed HTTP /v1/components absolute path {comp_http}")
                        return 1
                    if str(wroot) in comp_blob or "/home/" in comp_blob:
                        print(f"smoke failed HTTP /v1/components leaked host path {comp_http}")
                        return 1
                    if "json" not in ctype:
                        print(f"smoke failed HTTP /v1/components content-type {ctype}")
                        return 1
                    if (resp.headers.get("X-Request-Id") or "") != "smoke-components-rid":
                        print(f"smoke failed HTTP /v1/components X-Request-Id {resp.headers.get('X-Request-Id')}")
                        return 1

                req_exc = urllib.request.Request(
                    base + "/v1/exceptions",
                    headers={"X-Request-Id": "smoke-exceptions-rid"},
                )
                with urllib.request.urlopen(req_exc) as resp:
                    ctype = (resp.headers.get("Content-Type") or "").lower()
                    exc_http = json.loads(resp.read().decode("utf-8"))
                    if resp.status != 200:
                        print(f"smoke failed HTTP /v1/exceptions empty status {resp.status}")
                        return 1
                    if exc_http != {"ok": True, "count": 0, "exceptions": []}:
                        print(f"smoke failed HTTP /v1/exceptions empty body {exc_http}")
                        return 1
                    if "json" not in ctype:
                        print(f"smoke failed HTTP /v1/exceptions content-type {ctype}")
                        return 1
                    if (resp.headers.get("X-Request-Id") or "") != "smoke-exceptions-rid":
                        print(f"smoke failed HTTP /v1/exceptions X-Request-Id {resp.headers.get('X-Request-Id')}")
                        return 1

                empty_httpd = None
                try:
                    empty_root = wroot / "empty-inv"
                    empty_root.mkdir(exist_ok=True)
                    empty_httpd, _snap_e = create_bom_server(
                        empty_root, host="127.0.0.1", port=0
                    )
                    threading.Thread(
                        target=empty_httpd.serve_forever,
                        kwargs={"poll_interval": 0.2},
                        daemon=True,
                    ).start()
                    ehost, eport = empty_httpd.server_address[:2]
                    ebase = f"http://{ehost}:{eport}"
                    for _ in range(50):
                        try:
                            urllib.request.urlopen(ebase + "/health")
                            break
                        except Exception:
                            _sd_time.sleep(0.02)
                    else:
                        print("smoke failed empty components serve did not listen")
                        return 1
                    with urllib.request.urlopen(ebase + "/v1/components") as resp:
                        empty_http = json.loads(resp.read().decode("utf-8"))
                        if resp.status != 200:
                            print(f"smoke failed HTTP /v1/components empty status {resp.status}")
                            return 1
                        if empty_http != {"ok": True, "count": 0, "components": []}:
                            print(f"smoke failed HTTP /v1/components empty body {empty_http}")
                            return 1
                        if not resp.headers.get("X-Request-Id"):
                            print("smoke failed HTTP /v1/components empty missing X-Request-Id")
                            return 1
                    with urllib.request.urlopen(ebase + "/v1/exceptions") as resp:
                        empty_exc = json.loads(resp.read().decode("utf-8"))
                        if resp.status != 200:
                            print(f"smoke failed HTTP /v1/exceptions empty-inv status {resp.status}")
                            return 1
                        if empty_exc != {"ok": True, "count": 0, "exceptions": []}:
                            print(f"smoke failed HTTP /v1/exceptions empty-inv body {empty_exc}")
                            return 1
                finally:
                    if empty_httpd is not None:
                        try:
                            empty_httpd.shutdown()
                        except Exception:
                            pass
                        empty_httpd.server_close()

                exc_httpd = None
                try:
                    exc_root = wroot / "exc-inv"
                    exc_root.mkdir(exist_ok=True)
                    (exc_root / "package.json").write_text(
                        '{"name":"leftpad","version":"0.0.1","license":"GPL-3.0"}\n',
                        encoding="utf-8",
                    )
                    (exc_root / EXCEPTIONS_FILENAME).write_text(
                        json.dumps(
                            {
                                "exceptions": [
                                    {
                                        "component": "leftpad",
                                        "license": "GPL-3.0",
                                        "reason": "vendor approved 2026-Q3",
                                        "expires": "2099-12-31",
                                    },
                                    {
                                        "component": "oldpkg",
                                        "license": "GPL-3.0",
                                        "reason": "sk-SECRET Bearer tok https://hooks.example/hook",
                                        "expires": "2020-01-01",
                                    },
                                ]
                            }
                        ),
                        encoding="utf-8",
                    )
                    exc_httpd, _snap_x = create_bom_server(
                        exc_root, host="127.0.0.1", port=0, policy=lic_policy
                    )
                    threading.Thread(
                        target=exc_httpd.serve_forever,
                        kwargs={"poll_interval": 0.2},
                        daemon=True,
                    ).start()
                    xhost, xport = exc_httpd.server_address[:2]
                    xbase = f"http://{xhost}:{xport}"
                    for _ in range(50):
                        try:
                            urllib.request.urlopen(xbase + "/health")
                            break
                        except Exception:
                            _sd_time.sleep(0.02)
                    else:
                        print("smoke failed exceptions serve did not listen")
                        return 1
                    req_x = urllib.request.Request(
                        xbase + "/v1/exceptions",
                        headers={"X-Request-Id": "smoke-exceptions-iso"},
                    )
                    with urllib.request.urlopen(req_x) as resp:
                        exc_iso = json.loads(resp.read().decode("utf-8"))
                        exc_blob = json.dumps(exc_iso, ensure_ascii=False)
                        names = [e.get("component") for e in (exc_iso.get("exceptions") or [])]
                        if resp.status != 200:
                            print(f"smoke failed HTTP /v1/exceptions fixture status {resp.status}")
                            return 1
                        if exc_iso.get("ok") is not True:
                            print(f"smoke failed HTTP /v1/exceptions fixture body {exc_iso}")
                            return 1
                        if not isinstance(exc_iso.get("count"), int) or exc_iso.get("count") < 1:
                            print(f"smoke failed HTTP /v1/exceptions fixture count {exc_iso}")
                            return 1
                        if "leftpad" not in names:
                            print(f"smoke failed HTTP /v1/exceptions missing leftpad {names}")
                            return 1
                        left = next(
                            e for e in (exc_iso.get("exceptions") or []) if e.get("component") == "leftpad"
                        )
                        if left.get("expired") is not False or left.get("expiresAt") != "2099-12-31":
                            print(f"smoke failed HTTP /v1/exceptions leftpad expiry {left}")
                            return 1
                        stale = next(
                            (e for e in (exc_iso.get("exceptions") or []) if e.get("component") == "oldpkg"),
                            None,
                        )
                        if stale is None or stale.get("expired") is not True:
                            print(f"smoke failed HTTP /v1/exceptions expired flag {exc_iso}")
                            return 1
                        if any(
                            n in exc_blob
                            for n in (
                                "sk-SECRET",
                                "Bearer tok",
                                "hooks.example",
                                str(exc_root / EXCEPTIONS_FILENAME),
                            )
                        ):
                            print(f"smoke failed HTTP /v1/exceptions leaked secret {exc_iso}")
                            return 1
                        if (resp.headers.get("X-Request-Id") or "") != "smoke-exceptions-iso":
                            print("smoke failed HTTP /v1/exceptions fixture X-Request-Id")
                            return 1
                    with urllib.request.urlopen(xbase + "/v1/exceptions?expired=true") as resp:
                        only_exp = json.loads(resp.read().decode("utf-8"))
                        if only_exp.get("count") != 1 or (only_exp.get("exceptions") or [{}])[0].get("component") != "oldpkg":
                            print(f"smoke failed HTTP /v1/exceptions ?expired=true {only_exp}")
                            return 1
                    with urllib.request.urlopen(xbase + "/v1/exceptions?expired=maybe") as resp:
                        unk = json.loads(resp.read().decode("utf-8"))
                        if unk != {"ok": True, "count": 0, "exceptions": []}:
                            print(f"smoke failed HTTP /v1/exceptions unknown filter {unk}")
                            return 1
                finally:
                    if exc_httpd is not None:
                        try:
                            exc_httpd.shutdown()
                        except Exception:
                            pass
                        exc_httpd.server_close()

                cfg_httpd = None
                try:
                    cfg_httpd, _snap_c = create_bom_server(
                        wroot,
                        host="127.0.0.1",
                        port=0,
                        policy=lic_policy,
                        cors_origins=["http://localhost:3000"],
                        watch=True,
                        rate_limit=0,
                        webhook_url="http://127.0.0.1:9/hook?token=http_url_token_must_not_leak",
                        webhook_secret="http_whsec_must_not_leak",
                    )
                    threading.Thread(
                        target=cfg_httpd.serve_forever,
                        kwargs={"poll_interval": 0.2},
                        daemon=True,
                    ).start()
                    chost, cport = cfg_httpd.server_address[:2]
                    cbase = f"http://{chost}:{cport}"
                    for _ in range(50):
                        try:
                            urllib.request.urlopen(cbase + "/health")
                            break
                        except Exception:
                            _sd_time.sleep(0.02)
                    else:
                        print("smoke failed config serve did not listen")
                        return 1
                    req_iso = urllib.request.Request(
                        cbase + "/v1/config",
                        headers={"X-Request-Id": "smoke-config-iso"},
                    )
                    with urllib.request.urlopen(req_iso) as resp:
                        cfg_iso = json.loads(resp.read().decode("utf-8"))
                        cfg_iso_blob = json.dumps(cfg_iso, ensure_ascii=False)
                        cfg_iso_safe = assert_runtime_config_safe(cfg_iso)
                        cors = (cfg_iso.get("cors") or {})
                        if resp.status != 200:
                            print(f"smoke failed HTTP /v1/config planted status {resp.status}")
                            return 1
                        if cfg_iso.get("ok") is not True:
                            print(f"smoke failed HTTP /v1/config planted body {cfg_iso}")
                            return 1
                        if cors.get("origins") != ["http://localhost:3000"]:
                            print(f"smoke failed HTTP /v1/config planted cors {cfg_iso}")
                            return 1
                        if (cfg_iso.get("webhooks") or {}).get("hasUrl") is not True:
                            print(f"smoke failed HTTP /v1/config planted hasUrl {cfg_iso}")
                            return 1
                        if (cfg_iso.get("webhooks") or {}).get("hasSecret") is not True:
                            print(f"smoke failed HTTP /v1/config planted hasSecret {cfg_iso}")
                            return 1
                        if cfg_iso.get("hasPolicyFile") is not True:
                            print(f"smoke failed HTTP /v1/config planted hasPolicyFile {cfg_iso}")
                            return 1
                        if cfg_iso.get("watch") is not True:
                            print(f"smoke failed HTTP /v1/config planted watch {cfg_iso}")
                            return 1
                        if (resp.headers.get("X-Request-Id") or "") != "smoke-config-iso":
                            print("smoke failed HTTP /v1/config planted X-Request-Id")
                            return 1
                        if cfg_iso_safe.get("ok") is not True:
                            print(f"smoke failed HTTP /v1/config planted unsafe {cfg_iso_safe}")
                            return 1
                        if any(
                            n in cfg_iso_blob
                            for n in (
                                "http_url_token_must_not_leak",
                                "http_whsec_must_not_leak",
                                "whsec_must_not_leak",
                                "planted_url_token",
                                "Authorization",
                                "webhookUrl",
                                "webhookSecret",
                            )
                        ):
                            print(f"smoke failed HTTP /v1/config planted leak {cfg_iso}")
                            return 1
                finally:
                    if cfg_httpd is not None:
                        try:
                            cfg_httpd.shutdown()
                        except Exception:
                            pass
                        cfg_httpd.server_close()
                begin_shutdown(httpd)
                try:
                    urllib.request.urlopen(base + "/ready")
                    print("smoke failed ready expected 503 shutting_down")
                    return 1
                except urllib.error.HTTPError as e:
                    body = json.loads(e.read().decode("utf-8"))
                    if e.code != 503 or body.get("reason") != "shutting_down":
                        print(f"smoke failed ready shutting_down {e.code} {body}")
                        return 1
                with urllib.request.urlopen(base + "/health") as resp:
                    health1 = json.loads(resp.read().decode("utf-8"))
                    if health1.get("ok") is not True or health1.get("shuttingDown") is not True:
                        print(f"smoke failed health shuttingDown {health1}")
                        return 1
                try:
                    httpd.shutdown()
                except Exception:
                    pass
            finally:
                if httpd is not None:
                    httpd.server_close()

        print(f"ai-bom {__version__} smoke OK — models={models} + cors+requestId+openapi+metrics+webhook+hmac+retry+watch+shutdown+accessLog+cyclonedx+spdx+spdx3+sarif+cyclonedx-xml+spdx-xml+md+gha+html+rateLimit+exceptions+policyGate+config+exceptionsList+advisories+osvConvert+mlbomObs+spdx3Files+spdx3Ai+evidencePack+craClock+vex")
        return 0
    if args.cmd == "convert-advisories":
        return _run_convert_advisories(args)
    if args.cmd == "evidence-pack":
        return _run_evidence_pack(args)
    if args.cmd == "policy":
        target = Path(args.path)
        if not target.exists():
            print(f"path not found: {target}")
            return 2
        policy, err = _load_policy_arg(getattr(args, "policy", None))
        if err:
            print(err)
            return 2
        exceptions_path = resolve_exceptions_path(getattr(args, "exceptions", None))
        gate = build_policy_gate(
            policy,
            scan_root=target,
            exceptions_path=exceptions_path,
        )
        print(json.dumps(gate, indent=2, ensure_ascii=False) + "\n", end="")
        return 0
    if args.cmd == "serve":
        target = Path(args.path)
        if not target.exists():
            print(f"path not found: {target}")
            return 2
        policy, err = load_serve_policy(args.policy)
        if err:
            print(err)
            return 2
        ignore = parse_serve_ignore(args.ignore)
        exceptions_path = resolve_exceptions_path(getattr(args, "exceptions", None))
        cors_origins = resolve_cors_origins(args.cors_origins)
        webhook_url = resolve_webhook_url(getattr(args, "webhook_url", None))
        webhook_secret = resolve_webhook_secret(getattr(args, "webhook_secret", None))
        serve_forever(
            path=target.resolve(),
            host=args.host,
            port=args.port,
            policy=policy,
            ignore=ignore,
            exceptions_path=exceptions_path,
            cors_origins=cors_origins,
            watch=bool(getattr(args, "watch", False)),
            drain_ms=getattr(args, "drain_ms", None),
            log_json=resolve_log_json(getattr(args, "log_json", None)),
            rate_limit=resolve_rate_limit(getattr(args, "rate_limit", None)),
            webhook_url=webhook_url,
            webhook_secret=webhook_secret,
        )
        return 0
    if args.cmd in ("scan", "demo"):
        if args.cmd == "scan":
            target = Path(args.path)
        else:
            target = Path(__file__).resolve().parents[2]

        policy, err = _load_policy_arg(getattr(args, "policy", None))
        if err:
            print(err)
            return 2

        if not target.exists():
            print(f"path not found: {target}")
            return 2

        ignore = parse_ignore_arg(getattr(args, "ignore", None))
        exceptions_path = resolve_exceptions_path(getattr(args, "exceptions", None))
        bom = scan_path(
            target,
            policy=policy,
            ignore=ignore or None,
            exceptions_path=exceptions_path,
        )
        advisories_path = getattr(args, "advisories", None)
        gate_vulns = bool(getattr(args, "gate_vulns", False))
        if gate_vulns and not advisories_path:
            print("gate-vulns requires --advisories <file> (offline fixture; no NVD fetch)")
            return 2
        vex_out_early = getattr(args, "vex", None)
        if vex_out_early and not advisories_path:
            print("vex requires --advisories <file> (offline fixture; no NVD fetch)")
            return 2
        advisories: list = []
        if advisories_path:
            try:
                advisories = load_advisories(Path(advisories_path))
            except OSError as e:
                print(f"advisories IO error: {e}")
                return 2
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as e:
                print(f"advisories parse error: {e}")
                return 2
            matched = match_advisories_result(bom.get("components") or [], advisories)
            bom = attach_advisory_hits(
                bom, matched.hits, range_skipped=matched.range_skipped
            )
        fmt = getattr(args, "format", None) or DEFAULT_FORMAT
        if normalize_format(fmt) is None:
            print(f"unsupported --format (use {FORMATS_HELP})")
            return 2
        text = dumps_export(bom, fmt)
        out = getattr(args, "out", None)
        if out:
            outp = Path(out)
            outp.parent.mkdir(parents=True, exist_ok=True)
            outp.write_text(text, encoding="utf-8")
            print(f"wrote {outp} components={len(bom['components'])}")
        else:
            print(text, end="")

        evidence = getattr(args, "evidence", None)
        if evidence:
            evp = Path(evidence)
            evp.parent.mkdir(parents=True, exist_ok=True)
            evp.write_text(render_evidence(bom), encoding="utf-8")
            print(f"wrote {evp} policyHits={bom['summary'].get('policyHits', 0)}")

        sarif_out = getattr(args, "sarif", None)
        if sarif_out:
            sp = Path(sarif_out)
            sp.parent.mkdir(parents=True, exist_ok=True)
            sarif = to_sarif(bom, tool_version=__version__)
            sp.write_text(dumps_sarif(sarif), encoding="utf-8")
            n = len((sarif.get("runs") or [{}])[0].get("results") or [])
            print(f"wrote {sp} sarifResults={n}")

        vex_out = getattr(args, "vex", None)
        if vex_out:
            if not advisories_path:
                print("vex requires --advisories <file> (offline fixture; no NVD fetch)")
                return 2
            vp = Path(vex_out)
            vp.parent.mkdir(parents=True, exist_ok=True)
            vex_doc = build_openvex_document(bom.get("components") or [], advisories)
            vp.write_text(dumps_openvex(vex_doc), encoding="utf-8")
            print(f"wrote {vp} vexStatements={len(vex_doc.get('statements') or [])}")

        webhook_url = resolve_webhook_url(getattr(args, "webhook_url", None))
        webhook_secret = resolve_webhook_secret(getattr(args, "webhook_secret", None))
        notify_policy_hit(webhook_url, bom, secret=webhook_secret)

        forbidden = bom["summary"].get("forbidden") or []
        gaps = bom["summary"].get("disclosureGaps") or []
        forbidden_licenses = bom["summary"].get("forbiddenLicenses") or []
        if getattr(args, "strict", False) and (forbidden or gaps or forbidden_licenses):
            if forbidden:
                print(f"strict: forbidden patterns: {forbidden}")
            if gaps:
                print(f"strict: disclosure gaps: {gaps}")
            if forbidden_licenses:
                print(f"strict: forbidden licenses: {forbidden_licenses}")
            return 1
        if getattr(args, "gate_licenses", False) and forbidden_licenses:
            print(f"gate-licenses: forbidden licenses: {forbidden_licenses}")
            return 1
        if gate_vulns:
            advisory_hits = (bom.get("summary") or {}).get("advisoryHits") or []
            range_skipped = (bom.get("summary") or {}).get("advisoryRangeSkipped") or 0
            if range_skipped:
                print(f"gate-vulns: range skipped: {range_skipped}")
            if advisory_hits:
                print(f"gate-vulns: advisory hits: {advisory_hits}")
                return 1
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
