#!/usr/bin/env python3
"""Parse + cheap CLI prove for examples/github-actions (no GitHub runners).

Workflows must have `on` + `jobs`. Composite action.yml must have `name` + `runs`.
README must mention the exact C JUnit / C run-vs-run diff md / D SARIF / E GHA / A OpenAPI-drift commands this script runs.
Prefers yaml.safe_load; falls back to the check-k8s.py indent subset (no new deps).
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

C_CMD = "python3 -m agent_ci run --suite fixtures/demo --junit junit.xml"
C_DIFF_CMD = "python3 -m agent_ci diff --from run-a.json --to run-b.json --format md"
C_DIFF_SUMMARY = (
    "PYTHONPATH=src python3 -m agent_ci diff --from run-a.json --to run-b.json "
    '--format md >> "$GITHUB_STEP_SUMMARY"'
)
D_CMD = (
    "python3 -m ai_bom scan examples/sample-app "
    "--policy policies/default.json --sarif ai-bom.sarif"
)
D_GHA_CMD = (
    "python3 -m ai_bom scan examples/sample-app "
    "--policy policies/default.json --format gha"
)
E_CMD = "node src/cli.js report --in examples/spans.json --format gha"
E_TENANT_CMD = (
    "node src/cli.js report --in examples/spans.json "
    "--tenant-budget acme=0.0001 --format gha"
)
E_MD_CMD = "node src/cli.js report --in examples/spans.json --format md --out costs.md"
A_GEN = "node src/cli.js generate examples/petstore.openapi.json --out sdk"
A_CHECK_BASELINE = (
    "node src/cli.js generate examples/petstore.openapi.json "
    "--out sdk-new --check-baseline sdk"
)
A_CHECK = "node src/cli.js check --out sdk-new --baseline sdk"
A_CHECK_TEMP = "node src/cli.js generate examples/petstore.openapi.json --check-baseline sdk"
C_RUN = "PYTHONPATH=src " + C_CMD
D_RUN = "PYTHONPATH=src " + D_CMD

WORKFLOWS = (
    "agent-ci-junit.yml",
    "ai-bom-sarif.yml",
    "otel-ai-cost-gha.yml",
    "sdk-mcp-gen-check.yml",
)
COMPOSITES = (
    "agent-ci-junit/action.yml",
    "ai-bom-sarif/action.yml",
    "otel-ai-cost-gha/action.yml",
    "sdk-mcp-gen-check/action.yml",
)


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def live_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.lstrip() and not ln.lstrip().startswith("#")]


def load_k8s():
    path = Path(__file__).resolve().parent / "check-k8s.py"
    spec = importlib.util.spec_from_file_location("check_k8s", path)
    if spec is None or spec.loader is None:
        fail(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def trigger_value(doc: dict):
    if "on" in doc:
        return doc["on"]
    if True in doc:  # PyYAML 1.1: key `on` → True
        return doc[True]
    return None


def load_mapping(path: Path, k8s) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None
    if yaml is not None:
        data = yaml.safe_load(text)
        engine = "pyyaml"
    else:
        try:
            docs, engine = k8s.load_docs(text)
        except Exception as e:
            fail(f"{path}: parse error: {e}")
        if len(docs) != 1:
            fail(f"{path}: expected 1 YAML doc, got {len(docs)}")
        data = docs[0]
    if not isinstance(data, dict):
        fail(f"{path}: expected a mapping (got {type(data).__name__})")
    return data, engine


def require_on_jobs(path: Path, doc: dict) -> None:
    on = trigger_value(doc)
    if on is None or on is False:
        fail(f"{path.name}: missing key `on`")
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        fail(f"{path.name}: missing non-empty `jobs`")


def require_name_runs(path: Path, doc: dict) -> None:
    name = doc.get("name")
    if not isinstance(name, str) or not name.strip():
        fail(f"{path}: missing `name`")
    runs = doc.get("runs")
    if not isinstance(runs, dict) or not runs:
        fail(f"{path}: missing `runs`")
    using = runs.get("using")
    if using != "composite":
        fail(f"{path}: runs.using must be composite (got {using!r})")
    steps = runs.get("steps")
    if not isinstance(steps, list) or not steps:
        fail(f"{path}: runs.steps must be a non-empty list")


def run_cli(cwd: Path, args: list[str], outfile: Path, kind: str) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    proc = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        fail(
            f"{kind} CLI exit {proc.returncode}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    if not outfile.is_file():
        fail(f"{kind} did not write {outfile}")


def run_node(cwd: Path, args: list[str], kind: str, *, expect_code: int = 0) -> str:
    proc = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if proc.returncode != expect_code:
        fail(
            f"{kind} CLI exit {proc.returncode} (want {expect_code})\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc.stdout


def prove_c(c_root: Path) -> None:
    out = c_root / "junit.xml"
    if out.exists():
        out.unlink()
    try:
        run_cli(
            c_root,
            [
                "python3",
                "-m",
                "agent_ci",
                "run",
                "--suite",
                "fixtures/demo",
                "--junit",
                "junit.xml",
            ],
            out,
            "C junit",
        )
        xml = out.read_text(encoding="utf-8")
        if "<testsuite" not in xml:
            fail("C junit.xml missing <testsuite")
        if 'failures="0"' not in xml:
            fail("C demo suite expected failures=\"0\"")
        print("  ok C CLI  fixtures/demo -> junit.xml")
        prove_c_diff(c_root)
    finally:
        if out.exists():
            out.unlink()


def prove_c_diff(c_root: Path) -> None:
    """Two identical demo-shaped run dumps → Markdown 'no changes' (exit 0)."""
    dump = {
        "runId": "gha-demo",
        "status": "done",
        "suite": "demo",
        "summary": {
            "cases": [
                {"name": "france-capital", "passed": True, "score": 1.0},
                {"name": "math-2plus2", "passed": True, "score": 1.0},
            ]
        },
    }
    tmp = Path(tempfile.mkdtemp(prefix="agent-ci-gha-diff-"))
    try:
        a = tmp / "run-a.json"
        b = tmp / "run-b.json"
        payload = json.dumps(dump, indent=2)
        a.write_text(payload, encoding="utf-8")
        b.write_text(payload, encoding="utf-8")
        env = os.environ.copy()
        env["PYTHONPATH"] = "src"
        proc = subprocess.run(
            [
                "python3",
                "-m",
                "agent_ci",
                "diff",
                "--from",
                str(a),
                "--to",
                str(b),
                "--format",
                "md",
            ],
            cwd=c_root,
            env=env,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            fail(
                f"C diff --format md exit {proc.returncode}\n"
                f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )
        out = proc.stdout
        if "no changes" not in out:
            fail(f"C identical demo dumps expected 'no changes'\n{out!r}")
        if not out.startswith("# "):
            fail(f"C diff md missing heading\n{out!r}")
        print("  ok C CLI  diff --format md identical demo dumps (no changes)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def prove_d(d_root: Path) -> None:
    out = d_root / "ai-bom.sarif"
    if out.exists():
        out.unlink()
    try:
        run_cli(
            d_root,
            [
                "python3",
                "-m",
                "ai_bom",
                "scan",
                "examples/sample-app",
                "--policy",
                "policies/default.json",
                "--sarif",
                "ai-bom.sarif",
            ],
            out,
            "D sarif",
        )
        sarif = json.loads(out.read_text(encoding="utf-8"))
        if sarif.get("version") != "2.1.0":
            fail(f"D SARIF version {sarif.get('version')!r} != 2.1.0")
        schema = str(sarif.get("$schema") or "")
        if "sarif" not in schema.lower():
            fail(f"D SARIF $schema missing sarif: {schema!r}")
        runs = sarif.get("runs")
        if not isinstance(runs, list) or not runs:
            fail("D SARIF missing runs[]")
        print("  ok D CLI  examples/sample-app -> ai-bom.sarif")
    finally:
        if out.exists():
            out.unlink()


def prove_e(e_root: Path) -> None:
    spans = e_root / "examples" / "spans.json"
    if not spans.is_file():
        fail(f"missing E fixture {spans}")

    out = run_node(
        e_root,
        ["node", "src/cli.js", "report", "--in", "examples/spans.json", "--format", "gha"],
        "E gha (no budget)",
    )
    if "::error" in out:
        fail("E happy-path --format gha expected no ::error (no --budget)")
    print("  ok E CLI  examples/spans.json --format gha (empty, exit 0)")

    tenant = run_node(
        e_root,
        [
            "node",
            "src/cli.js",
            "report",
            "--in",
            "examples/spans.json",
            "--tenant-budget",
            "acme=0.0001",
            "--format",
            "gha",
        ],
        "E gha (tenant-budget)",
    )
    if "::error title=tenant/acme::" not in tenant:
        fail(f"E tenant-budget --format gha missing ::error title=tenant/acme::\n{tenant!r}")
    print("  ok E CLI  --tenant-budget acme=0.0001 --format gha (::error, exit 0)")

    md = e_root / "costs.md"
    if md.exists():
        md.unlink()
    try:
        run_node(
            e_root,
            [
                "node",
                "src/cli.js",
                "report",
                "--in",
                "examples/spans.json",
                "--format",
                "md",
                "--out",
                "costs.md",
            ],
            "E md",
        )
        if not md.is_file():
            fail("E --format md did not write costs.md")
        body = md.read_text(encoding="utf-8")
        if "# otel-ai-cost" not in body:
            fail("E costs.md missing # otel-ai-cost")
        if "totalUsd" not in body:
            fail("E costs.md missing totalUsd")
        print("  ok E CLI  examples/spans.json --format md --out costs.md")
    finally:
        if md.exists():
            md.unlink()



def prove_a(a_root: Path) -> None:
    spec = a_root / "examples" / "petstore.openapi.json"
    if not spec.is_file():
        fail(f"missing A fixture {spec}")
    tmp = Path(tempfile.mkdtemp(prefix="sdk-mcp-gen-gha-"))
    try:
        baseline = tmp / "sdk"
        new = tmp / "sdk-new"
        run_node(
            a_root,
            [
                "node",
                "src/cli.js",
                "generate",
                "examples/petstore.openapi.json",
                "--out",
                str(baseline),
            ],
            "A generate baseline",
        )
        tools = baseline / "mcp-tools.json"
        if not tools.is_file():
            fail("A generate did not write mcp-tools.json")
        out = run_node(
            a_root,
            [
                "node",
                "src/cli.js",
                "generate",
                "examples/petstore.openapi.json",
                "--out",
                str(new),
                "--check-baseline",
                str(baseline),
            ],
            "A generate --check-baseline",
        )
        if "RESULT: BREAKING" in out:
            fail("A happy-path --check-baseline should not be BREAKING")
        if "RESULT: OK" not in out:
            fail(f"A happy-path --check-baseline missing RESULT: OK\n{out}")
        check_out = run_node(
            a_root,
            [
                "node",
                "src/cli.js",
                "check",
                "--out",
                str(new),
                "--baseline",
                str(baseline),
            ],
            "A check --out --baseline",
        )
        if "RESULT: OK" not in check_out:
            fail(f"A check --out --baseline missing RESULT: OK\n{check_out}")
        print("  ok A CLI  petstore generate + --check-baseline (exit 0)")
        print("  ok A CLI  check --out NEW --baseline sdk (exit 0)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
    examples = root / "examples" / "github-actions"
    if not examples.is_dir():
        fail(f"missing {examples}")

    live = root / ".github" / "workflows"
    for banned in WORKFLOWS:
        p = live / banned
        if p.exists():
            fail(
                f"{p} must not be a live workflow (examples only; "
                "would fail this repo's CI without a dedicated runner / code scanning)"
            )

    k8s = load_k8s()
    engines: set[str] = set()
    readme = (examples / "README.md").read_text(encoding="utf-8")
    for needle in (C_CMD, C_DIFF_CMD, C_DIFF_SUMMARY, D_CMD, D_GHA_CMD, C_RUN, D_RUN, E_CMD, E_TENANT_CMD, E_MD_CMD, A_GEN, A_CHECK_BASELINE, A_CHECK, A_CHECK_TEMP):
        if needle not in readme:
            fail(f"examples/github-actions/README.md missing exact command:\n  {needle}")

    for fname in WORKFLOWS:
        path = examples / fname
        if not path.is_file():
            fail(f"missing {path}")
        doc, engine = load_mapping(path, k8s)
        engines.add(engine)
        require_on_jobs(path, doc)
        text = path.read_text(encoding="utf-8")
        if fname == "agent-ci-junit.yml":
            if C_RUN not in text:
                fail(f"{fname} missing run line:\n  {C_RUN}")
            if "actions/upload-artifact@v4" not in text:
                fail(f"{fname} must upload-artifact@v4")
            if C_DIFF_SUMMARY not in text:
                fail(f"{fname} must document run-vs-run diff summary (comment ok):\n  {C_DIFF_SUMMARY}")
            if "GITHUB_STEP_SUMMARY" not in text:
                fail(f"{fname} must mention $GITHUB_STEP_SUMMARY for the Markdown diff")
            if "download-artifact" not in text and "previous artifact" not in text:
                fail(f"{fname} must document using a previous artifact as --from (comment ok)")
            if "no changes" not in text:
                fail(f"{fname} must document identical-demo happy path (no changes)")
            live_body = "\n".join(live_lines(text))
            if "dorny/test-reporter" in live_body:
                fail(f"{fname}: dorny/test-reporter must not be a live step")
            if "--fail-under" in live_body:
                fail(f"{fname}: do not add a failing suite / fail-under as a live step")
        if fname == "ai-bom-sarif.yml":
            if D_RUN not in text:
                fail(f"{fname} missing run line:\n  {D_RUN}")
            if "github/codeql-action/upload-sarif@v3" not in text:
                fail(f"{fname} must use github/codeql-action/upload-sarif@v3")
            live_body = "\n".join(live_lines(text))
            if "--format sarif" in live_body:
                fail(f"{fname}: SARIF flag is --sarif PATH, not --format sarif")
        if fname == "otel-ai-cost-gha.yml":
            live_body = "\n".join(live_lines(text))
            if E_CMD not in live_body:
                fail(f"{fname} missing live run line:\n  {E_CMD}")
            if E_MD_CMD not in live_body:
                fail(f"{fname} missing live run line:\n  {E_MD_CMD}")
            if "GITHUB_STEP_SUMMARY" not in live_body:
                fail(f"{fname} must write Markdown to $GITHUB_STEP_SUMMARY")
            if "actions/upload-artifact@v4" not in text:
                fail(f"{fname} must upload-artifact@v4")
            if "actions/setup-node@" not in live_body:
                fail(f"{fname} must setup-node")
            if "--budget policies/budget.json" not in text:
                fail(f"{fname} must document --budget policies/budget.json (comment ok)")
            if E_TENANT_CMD not in text:
                fail(f"{fname} must document tenant-budget command (comment ok):\n  {E_TENANT_CMD}")
            if "github/codeql-action/upload-sarif" in live_body:
                fail(f"{fname}: E annotations are stdout ::error, not upload-sarif")
        if fname == "sdk-mcp-gen-check.yml":
            live_body = "\n".join(live_lines(text))
            if A_GEN not in live_body:
                fail(f"{fname} missing live run line:\n  {A_GEN}")
            if A_CHECK_BASELINE not in live_body:
                fail(f"{fname} missing live run line:\n  {A_CHECK_BASELINE}")
            if "actions/setup-node@" not in live_body:
                fail(f"{fname} must setup-node")
            if "--check-baseline" not in live_body:
                fail(f"{fname} must run generate --check-baseline")
            if A_CHECK not in text:
                fail(f"{fname} must document two-step check (comment ok):\n  {A_CHECK}")
            if A_CHECK_TEMP not in text:
                fail(f"{fname} must document omit --out --check-baseline (comment ok):\n  {A_CHECK_TEMP}")
            if "github/codeql-action/upload-sarif" in live_body:
                fail(f"{fname}: A drift is CLI exit 1, not upload-sarif")
        print(f"  ok {fname}  on+jobs  ({engine})")

    for rel in COMPOSITES:
        path = examples / rel
        if not path.is_file():
            fail(f"missing {path}")
        doc, engine = load_mapping(path, k8s)
        engines.add(engine)
        require_name_runs(path, doc)
        text = path.read_text(encoding="utf-8")
        if rel.startswith("agent-ci-junit"):
            if "python3 -m agent_ci run" not in text or "--junit" not in text:
                fail(f"{rel} must run agent_ci with --junit")
        if rel.startswith("ai-bom-sarif"):
            if "python3 -m ai_bom scan" not in text or "--sarif" not in text:
                fail(f"{rel} must run ai_bom with --sarif")
        if rel.startswith("otel-ai-cost-gha"):
            if "node src/cli.js report" not in text or "--format gha" not in text:
                fail(f"{rel} must run otel-ai-cost report --format gha")
        if rel.startswith("sdk-mcp-gen-check"):
            if "node src/cli.js generate" not in text or "--check-baseline" not in text:
                fail(f"{rel} must run sdk-mcp-gen generate --check-baseline")
        print(f"  ok {rel}  name+runs.composite  ({engine})")

    prove_c(root / "bets" / "c-agent-ci")
    prove_d(root / "bets" / "d-ai-bom")
    prove_e(root / "bets" / "e-otel-ai-cost")
    prove_a(root / "bets" / "a-sdk-mcp-gen")
    print(f"gha examples ok ({', '.join(sorted(engines))} parser)")


if __name__ == "__main__":
    main()
