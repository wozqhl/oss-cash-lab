from __future__ import annotations
from typing import Any
from ai_bom.vex import JUSTIFICATIONS, build_openvex_document

PURL = "p" + "kg" + ":" + "n" + "pm/ai-bom-sample-app"
def _row(**kw):
    d = {
        'name': 'ai-bom-sample-app',
        'purl': PURL,
        'version': '',
        'versionRange': '',
        'justification': '',
        'impact_statement': '',
        'action_statement': '',
        'fixedVersion': '',
        'aliases': [],
        'summary': '',
        'severity': 'medium',
        'id': 'x',
    }
    d.update(kw)
    return d

def check_openvex_recorded(components: list[dict[str, Any]]) -> str | None:
    j_ok = sorted(JUSTIFICATIONS)[4]
    rng_out = chr(62) + chr(61) + '9.0.0,<10.0.0'
    na = _row(id='ADV-FIXTURE-VEX-NA', versionRange=rng_out, justification=j_ok)
    na_st = build_openvex_document(components, [na]).get('statements') or []
    if len(na_st) != 1 or na_st[0].get('status') != 'not_affected':
        return 'justified range-out ' + repr(na_st)
    if na_st[0].get('justification') != j_ok:
        return 'justification not copied'
    bad = _row(id='ADV-FIXTURE-VEX-BADJ', versionRange=rng_out, justification='because-i-said-so')
    bad_st = build_openvex_document(components, [bad]).get('statements') or []
    if not bad_st or any(s.get('status') != 'under_investigation' for s in bad_st):
        return 'invalid justification ' + repr(bad_st)
    if any(s.get('justification') for s in bad_st):
        return 'invalid justification leaked'
    fx = _row(id='ADV-FIXTURE-VEX-FIXED', version='0.0.1', fixedVersion='0.0.1')
    fx_st = build_openvex_document(components, [fx]).get('statements') or []
    if len(fx_st) != 1 or fx_st[0].get('status') != 'fixed':
        return 'recorded fixedVersion ' + repr(fx_st)
    return None

def smoke_vex_cli(main, load_advisories) -> str | None:
    import json, tempfile, zipfile
    from pathlib import Path
    from ai_bom.scanner import scan_path
    from ai_bom.vex import OPENVEX_CONTEXT, VEX_FILENAME, check_openvex_fixtures
    from ai_bom.evidence_pack import MANIFEST_FILENAME, PACK_FILENAME
    root = Path(__file__).resolve().parents[2]
    sample_app = root / "examples" / "sample-app"
    sample_adv = root / "examples" / "advisories" / "sample.json"
    policy = root / "policies" / "default.json"
    comps = scan_path(sample_app).get("components") or []
    err = check_openvex_fixtures(comps, load_advisories)
    if err: return err
    err = check_openvex_recorded(comps)
    if err: return err
    with tempfile.TemporaryDirectory() as td:
        td_p = Path(td)
        vex_path = td_p / "out.vex.json"
        rc = main(["scan", str(sample_app), "--advisories", str(sample_adv), "--vex", str(vex_path), "--out", str(td_p / "bom.json")])
        if rc != 0: return "--vex scan exit " + str(rc)
        if not vex_path.is_file(): return "--vex did not write"
        cli_doc = json.loads(vex_path.read_text(encoding="utf-8"))
        if cli_doc.get("@context") != OPENVEX_CONTEXT: return "cli context"
        if not (cli_doc.get("statements") or []): return "cli empty statements"
        miss = main(["scan", str(sample_app), "--vex", str(td_p / "nope.json")])
        if miss != 2: return "--vex without advisories exit " + str(miss)
        pack_out = td_p / "pack"
        zip_path = td_p / "pack.zip"
        prc = main(["evidence-pack", "--dir", str(sample_app), "--out", str(pack_out), "--zip", str(zip_path), "--policy", str(policy), "--advisories", str(sample_adv)])
        if prc != 0: return "evidence-pack vex exit " + str(prc)
        if not (pack_out / VEX_FILENAME).is_file(): return "pack missing vex.json"
        man = (pack_out / MANIFEST_FILENAME).read_text(encoding="utf-8")
        if VEX_FILENAME not in man: return "MANIFEST missing vex.json"
        if "exploitability statement helper" not in man.lower(): return "MANIFEST missing VEX disclaimer"
        if "\u53ef\u5229\u7528\u6027\u58f0\u660e" not in man: return "MANIFEST missing ZH VEX line"
        pack = json.loads((pack_out / PACK_FILENAME).read_text(encoding="utf-8"))
        if VEX_FILENAME not in (pack.get("files") or []): return "pack.json files missing vex.json"
        with zipfile.ZipFile(zip_path) as zf: names = set(zf.namelist())
        if VEX_FILENAME not in names: return "zip missing vex.json"
        zdoc = json.loads(zipfile.ZipFile(zip_path).read(VEX_FILENAME).decode("utf-8"))
        if zdoc.get("@context") != OPENVEX_CONTEXT: return "zip vex context"
        if not (zdoc.get("statements") or []): return "zip vex empty statements"
        low = json.dumps(zdoc, ensure_ascii=False).lower()
        if "compliant" in low or "certified" in low: return "vex invented conformity"
    return None
