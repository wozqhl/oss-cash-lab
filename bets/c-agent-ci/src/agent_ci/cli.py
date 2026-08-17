"""CLI for agent-ci."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent_ci import __version__
from agent_ci.baseline import diff_baseline, diff_runs, diff_runs_to_html, diff_runs_to_md, load_baseline, save_baseline
from agent_ci.cassette import write_cassette
from agent_ci.mock_agent import run_mock_agent
from agent_ci.runner import CaseResult, GATE_ERROR, is_completed_status, quality_gate, run_cassette_suite, run_suite, run_to_gha, run_to_html, run_to_junit, run_to_md, run_to_tap, runs_to_gha, runs_to_html, runs_to_junit, runs_to_md, runs_to_tap, suite_score, to_gha, to_html, to_junit, to_md, to_tap
from agent_ci.suite_import import import_suite
from agent_ci.promptfoo import cases_from_promptfoo, load_promptfoo
from agent_ci.check_run import (
    build_check_run_payload,
    post_check_run_payload,
    write_check_run_payload,
)
from agent_ci.cors import (
    DEFAULT_CORS_EXPOSE_HEADERS,
    DEFAULT_CORS_HEADERS,
    acao_value,
    cors_response_headers,
    handle_preflight,
    normalize_cors,
    origin_allowed,
    parse_cors_origins,
    resolve_cors_origins,
)
from agent_ci.request_id import (
    is_uuid,
    resolve_request_id,
    sanitize_request_id,
)
from agent_ci.access_log import (
    format_access_log,
    resolve_log_json,
    should_skip_access_log,
)
from agent_ci.rate_limit import (
    DEFAULT_RATE_LIMIT_PER_MINUTE,
    ENV_RATE_LIMIT_PER_MINUTE,
    ENV_RATE_LIMIT_RPM,
    SlidingWindowRateLimiter,
    client_ip_from_headers,
    resolve_rate_limit,
    skip_rate_limit,
)
from agent_ci.metrics import (
    METRIC_COMPLETED,
    METRIC_FAILED,
    METRIC_QUEUE_DEPTH,
    METRIC_RUNNING,
    render_metrics,
)
from agent_ci.webhook import (
    DEFAULT_RETRY_DELAY_S,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    build_webhook_payload,
    notify_run_complete,
    post_run_webhook,
    resolve_webhook_secret,
    resolve_webhook_url,
    run_conclusion,
    should_retry_webhook,
    sign_webhook_body,
    verify_webhook_signature,
    webhook_unix_seconds,
)

DEMO_CASES = [
    {"name": "france-capital", "prompt": "What is the capital of France?", "expect": "Paris"},
    {"name": "math-2plus2", "prompt": "Compute 2+2", "expect": "4"},
]


def _fail_under_arg(raw: str) -> float:
    try:
        n = float(raw)
    except ValueError as e:
        raise argparse.ArgumentTypeError("must be a number") from e
    if n != n or n in (float("inf"), float("-inf")):
        raise argparse.ArgumentTypeError("must be a finite number")
    if n < 0 or n > 100:
        raise argparse.ArgumentTypeError("must be between 0 and 100")
    return n


def _write_junit(path: str | None, results, suite_name: str, gate=None) -> None:
    if not path:
        return
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_junit(results, suite_name=suite_name, gate=gate), encoding="utf-8")


def _write_tap(path: str | None, results, suite_name: str, gate=None) -> None:
    if not path:
        return
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_tap(results, suite_name=suite_name, gate=gate), encoding="utf-8")


def _resolve_suite(suite_arg: str) -> Path:
    suite = Path(suite_arg)
    if not suite.is_absolute() and not suite.exists():
        alt = Path(__file__).resolve().parents[2] / suite_arg
        if alt.exists():
            return alt
    return suite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-ci")
    parser.add_argument("--version", action="store_true")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("smoke")

    p_run = sub.add_parser("run")
    p_run.add_argument("--suite", default="fixtures/demo")
    p_run.add_argument("--junit", default=None, help="Write JUnit XML to this path")
    p_run.add_argument(
        "--format",
        choices=("text", "junit", "tap", "md", "html", "gha", "annotations"),
        default="text",
        help="Stdout format: text (default), junit XML (GitHub Actions / Jenkins / GitLab), tap (TAP version 13), md (Markdown for GitHub Actions $GITHUB_STEP_SUMMARY), html (self-contained HTML table, no CDN), or gha/annotations (GitHub Actions workflow commands ::error)",
    )
    p_run.add_argument("--seed", type=int, default=42)
    p_run.add_argument(
        "--fail-under",
        dest="fail_under",
        type=_fail_under_arg,
        default=None,
        metavar="N",
        help=(
            "Quality gate: exit 1 when pass-rate score (passed/total*100, or 0 if "
            "total=0) is below N (0–100). Default: no gate (today's exit: 0 if all "
            "cases pass, 1 if any fail)."
        ),
    )
    p_run.add_argument(
        "--save-baseline",
        default=None,
        help="Write baseline JSON on successful run (e.g. out/baseline.json)",
    )
    p_run.add_argument(
        "--diff-baseline",
        default=None,
        help="Compare run vs baseline; fail on trajectory/score regression",
    )

    p_rec = sub.add_parser("record")
    p_rec.add_argument("--prompt", default="What is the capital of France?")
    p_rec.add_argument("--name", default="recorded")
    p_rec.add_argument("--out", default="fixtures/demo/recorded.json")
    p_rec.add_argument("--seed", type=int, default=42)

    p_demo = sub.add_parser("demo")
    p_demo.add_argument("--junit", action="store_true")

    p_imp = sub.add_parser("import-suite")
    p_imp.add_argument("--from", dest="src", required=True, help="Source zip or directory")
    p_imp.add_argument("--to", dest="dst", default="fixtures/private-demo")

    p_pf = sub.add_parser(
        "from-promptfoo",
        help="Adapt Promptfoo eval --output JSON into JUnit/TAP via existing reporters (not a third eval DSL)",
    )
    p_pf.add_argument(
        "--in",
        dest="input_path",
        required=True,
        help="Promptfoo output JSON (results.results[].success / gradingResult, or outputs[])",
    )
    p_pf.add_argument("--junit", default=None, help="Write JUnit XML to this path")
    p_pf.add_argument("--tap", default=None, help="Write TAP version 13 to this path")
    p_pf.add_argument(
        "--format",
        choices=("text", "junit", "tap"),
        default="text",
        help="Stdout format: text (default), junit XML, or tap (TAP version 13)",
    )
    p_pf.add_argument(
        "--fail-under",
        dest="fail_under",
        type=_fail_under_arg,
        default=None,
        metavar="N",
        help="Quality gate: exit 1 when pass-rate score is below N (0-100)",
    )
    p_pf.add_argument(
        "--suite-name",
        default="promptfoo",
        help="testsuite / TAP label (default: promptfoo)",
    )

    p_diff = sub.add_parser(
        "diff",
        help="Compare two completed run JSON files (same shape as GET /v1/runs/{id}/diff; --format md for Markdown, --format html for HTML)",
    )
    p_diff.add_argument(
        "--from",
        dest="from_path",
        required=True,
        help="Baseline / last-green run JSON (from)",
    )
    p_diff.add_argument(
        "--to",
        dest="to_path",
        required=True,
        help="Newer run JSON (to)",
    )
    p_diff.add_argument(
        "--format",
        choices=("json", "md", "html"),
        default="json",
        help="Stdout format: json (default, same as GET /v1/runs/{id}/diff), md (Markdown for GitHub Actions $GITHUB_STEP_SUMMARY; same as GET /v1/runs/{id}/diff.md), or html (self-contained HTML table, no CDN; same as GET /v1/runs/{id}/diff.html)",
    )

    p_serve = sub.add_parser("serve", help="Local hosted-runner HTTP stub")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8791)
    p_serve.add_argument(
        "--runs-dir",
        default="data/runs",
        help="Where to store run JSON (default: ./data/runs)",
    )
    p_serve.add_argument(
        "--require-key",
        action="store_true",
        help="Require Authorization Bearer demo (paid-seat sketch)",
    )
    p_serve.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Max concurrent runs (default: 1; local in-memory queue)",
    )
    p_serve.add_argument(
        "--max-queue",
        type=int,
        default=16,
        help="Max waiting runs before POST returns 429 Retry-After (default: 16)",
    )
    p_serve.add_argument(
        "--runs-max",
        dest="runs_max",
        type=int,
        default=None,
        help=(
            "Max finished runs kept in memory (default 1000; env RUNS_MAX). "
            "0 = unlimited. Over cap drop oldest done|failed|error. "
            "Does not cap the in-flight queue."
        ),
    )
    p_serve.add_argument(
        "--cors-origins",
        default=None,
        help="CSV of allowed Origins (empty/omit = deny extra CORS; * allowed). Env AGENT_CI_CORS_ORIGINS when flag omitted.",
    )
    p_serve.add_argument(
        "--webhook-url",
        default=None,
        help="POST run-complete JSON when a run reaches done|failed|error (fire-and-forget, short timeout; never fails the run). Env AGENT_CI_WEBHOOK_URL when flag omitted. Empty/omit = disabled. Always sends X-Webhook-Timestamp unix-seconds. OSS 1 retry on 5xx/network/timeout after ~50ms (4xx/success no retry). Exponential backoff / queues / key rotation / timestamp replay window enforcement = paid later.",
    )
    p_serve.add_argument(
        "--webhook-secret",
        default=None,
        help="HMAC-SHA256 key for outbound run-complete POST (`X-Webhook-Signature: sha256=<hex>` of raw body). Env AGENT_CI_WEBHOOK_SECRET when flag omitted. Empty/omit = unsigned. Simple HMAC is OSS (body only). Always sends X-Webhook-Timestamp unix-seconds; replay window enforcement = paid later.",
    )
    p_serve.add_argument(
        "--watch",
        action="store_true",
        help=(
            "Poll fixtures/ max mtime (~400ms); log regenerated and bump GET /health "
            "watch.generation. GET /v1/suites still live-reads disk (picks up new dirs). "
            "Default off (stack-demo / main serve unchanged)."
        ),
    )
    p_serve.add_argument(
        "--drain-ms",
        type=int,
        default=None,
        help="SIGTERM/SIGINT drain window in ms (default 5000, cap 30000). Env SHUTDOWN_DRAIN_MS.",
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
        "--log-json",
        dest="log_json",
        action="store_true",
        default=None,
        help=(
            "JSON access logs on stdout (one line per app request). "
            "Env LOG_FORMAT=json when flag omitted. Default off."
        ),
    )

    p_chk = sub.add_parser(
        "report-check",
        help="Format suite results as a GitHub Check Run payload (local OSS)",
    )
    p_chk.add_argument("--suite", default="fixtures/demo")
    p_chk.add_argument(
        "--out",
        default="out/check-run.json",
        help="Write Check Run JSON payload locally (default: out/check-run.json)",
    )
    p_chk.add_argument("--seed", type=int, default=42)
    p_chk.add_argument("--name", default="agent-ci", help="Check Run name")
    p_chk.add_argument(
        "--head-sha",
        default="0000000000000000000000000000000000000000",
        help="Placeholder commit SHA for local payload (not posted to GitHub)",
    )
    p_chk.add_argument(
        "--post-url",
        default=None,
        help="Optional local mock receiver URL (e.g. http://127.0.0.1:8791/v1/check-runs)",
    )

    args = parser.parse_args(argv)

    if args.version:
        print(__version__)
        return 0

    if args.cmd == "smoke":
        results = run_suite(DEMO_CASES, seed=42)
        if not all(r.passed for r in results):
            print("smoke failed", file=sys.stderr)
            return 1
        from agent_ci.runner import CaseResult
        ok_case = CaseResult(name="ok", passed=True, expected="a", actual="a")
        bad_case = CaseResult(
            name="bad & x",
            passed=False,
            expected="want",
            actual="got & <fail>",
        )
        junit_xml = to_junit([ok_case, bad_case], suite_name="smoke")
        junit_ok = (
            "<testsuite" in junit_xml
            and "<failure" in junit_xml
            and "&amp;" in junit_xml
            and "&lt;" in junit_xml
            and 'tests="2"' in junit_xml
            and 'failures="1"' in junit_xml
            and 'errors="0"' in junit_xml
            and "classname=" in junit_xml
            and "got & <fail>" not in junit_xml
        )
        if not junit_ok:
            print("smoke failed junit xml", junit_xml, file=sys.stderr)
            return 1
        empty_xml = to_junit([], suite_name="empty")
        if "<testsuite" not in empty_xml or 'tests="0"' not in empty_xml:
            print("smoke failed empty junit", empty_xml, file=sys.stderr)
            return 1
        fake_run = {
            "runId": "abc123abc123",
            "status": "done",
            "suite": "demo",
            "passed": False,
            "summary": {
                "total": 2,
                "passed": 1,
                "failed": 1,
                "ok": False,
                "cases": [
                    {"name": "ok", "passed": True, "score": 1.0},
                    {"name": "a & b", "passed": False, "score": 0.0},
                ],
            },
        }
        from_run = run_to_junit(fake_run)
        if (
            "<testsuite" not in from_run
            or "<failure" not in from_run
            or "&amp;" not in from_run
        ):
            print("smoke failed run_to_junit", from_run, file=sys.stderr)
            return 1
        empty_agg = runs_to_junit([])
        if "<testsuite" not in empty_agg or 'tests="0"' not in empty_agg:
            print("smoke failed empty runs_to_junit", empty_agg, file=sys.stderr)
            return 1
        err_run = run_to_junit(
            {
                "runId": "err1err1err1",
                "status": "error",
                "suite": "demo",
                "error": "suite_not_found",
                "detail": "missing & gone",
            }
        )
        if "<error" not in err_run or "&amp;" not in err_run or 'errors="1"' not in err_run:
            print("smoke failed error run_to_junit", err_run, file=sys.stderr)
            return 1
        two_pass = [
            CaseResult(name="a", passed=True, expected="x", actual="x"),
            CaseResult(name="b", passed=True, expected="y", actual="y"),
        ]
        mixed = [
            CaseResult(name="a", passed=True, expected="x", actual="x"),
            CaseResult(name="b", passed=False, expected="y", actual="z"),
        ]
        if (
            suite_score(two_pass) != 100.0
            or suite_score(mixed) != 50.0
            or suite_score([]) != 0.0
            or quality_gate(100.0, 80) != {"failUnder": 80, "passed": True}
            or quality_gate(50.0, 80) != {"failUnder": 80, "passed": False}
            or quality_gate(100.0, None) is not None
        ):
            print("smoke failed suite_score/quality_gate", file=sys.stderr)
            return 1
        from agent_ci.baseline import diff_runs as _diff_runs, diff_runs_to_html as _diff_html, diff_runs_to_md as _diff_md
        from agent_ci.serve import (
            CASES_LIST_CAP,
            cases_json as _cases_json,
            diff_runs_response as _diff_http,
            execute_run as _execute_run,
            get_suite as _get_suite,
        )
        empty_from = {
            "runId": "aaaaaaaaaaaa",
            "status": "done",
            "suite": "demo",
            "summary": {"cases": []},
        }
        empty_to = {
            "runId": "bbbbbbbbbbbb",
            "status": "done",
            "suite": "demo",
            "summary": {"cases": []},
        }
        empty_diff = _diff_runs(empty_from, empty_to)
        if (
            empty_diff.get("ok") is not True
            or empty_diff.get("from") != "aaaaaaaaaaaa"
            or empty_diff.get("to") != "bbbbbbbbbbbb"
            or empty_diff.get("added") != []
            or empty_diff.get("removed") != []
            or empty_diff.get("regressed") != []
            or empty_diff.get("fixed") != []
            or empty_diff.get("unchanged") != 0
        ):
            print("smoke failed empty run diff", empty_diff, file=sys.stderr)
            return 1
        green = {
            "runId": "aa11aa11aa11",
            "status": "done",
            "suite": "demo",
            "summary": {
                "cases": [
                    {"name": "ok", "passed": True},
                    {"name": "flaky", "passed": True},
                ]
            },
        }
        extra_fail = {
            "runId": "bb22bb22bb22",
            "status": "done",
            "suite": "demo",
            "summary": {
                "cases": [
                    {"name": "ok", "passed": True},
                    {"name": "flaky", "passed": False},
                ]
            },
        }
        reg = _diff_runs(green, extra_fail)
        if (
            reg.get("regressed") != ["demo/flaky"]
            or reg.get("added") != []
            or reg.get("removed") != []
            or reg.get("fixed") != []
            or reg.get("unchanged") != 1
            or reg.get("from") != "aa11aa11aa11"
            or reg.get("to") != "bb22bb22bb22"
        ):
            print("smoke failed extra-fail run diff", reg, file=sys.stderr)
            return 1
        same = _diff_runs(green, {
            "runId": "cc33cc33cc33",
            "status": "done",
            "suite": "demo",
            "summary": {
                "cases": [
                    {"name": "ok", "passed": True},
                    {"name": "flaky", "passed": True},
                ]
            },
        })
        if (
            same.get("added") != []
            or same.get("removed") != []
            or same.get("regressed") != []
            or same.get("fixed") != []
            or same.get("unchanged") != 2
        ):
            print("smoke failed identical run diff", same, file=sys.stderr)
            return 1
        md_reg = _diff_md(reg)
        if (
            not md_reg.startswith("# ")
            or "regressed" not in md_reg
            or "demo/flaky" not in md_reg
            or "text/markdown" in md_reg
        ):
            print("smoke failed extra-fail run diff md", md_reg, file=sys.stderr)
            return 1
        md_same = _diff_md(same)
        if (
            not md_same.startswith("# ")
            or "no changes" not in md_same
            or "## regressed" in md_same
            or "| demo/flaky |" in md_same
        ):
            print("smoke failed identical run diff md", md_same, file=sys.stderr)
            return 1
        md_empty = _diff_md(empty_diff)
        if not md_empty.startswith("# ") or "no changes" not in md_empty:
            print("smoke failed empty run diff md", md_empty, file=sys.stderr)
            return 1
        html_reg = _diff_html(reg)
        if (
            "<table" not in html_reg
            or "flaky" not in html_reg
            or "demo/flaky" not in html_reg
            or 'class="fail"' not in html_reg
            or "text/html" in html_reg
        ):
            print("smoke failed extra-fail run diff html", html_reg, file=sys.stderr)
            return 1
        html_same = _diff_html(same)
        if (
            "no changes" not in html_same
            or "<table" in html_same
            or "<h1" not in html_same
        ):
            print("smoke failed identical run diff html", html_same, file=sys.stderr)
            return 1
        html_empty = _diff_html(empty_diff)
        if "<h1" not in html_empty or "no changes" not in html_empty or "<table" in html_empty:
            print("smoke failed empty run diff html", html_empty, file=sys.stderr)
            return 1
        pipe_diff = _diff_runs(
            {
                "runId": "ff11ff11ff11",
                "status": "done",
                "suite": "demo",
                "summary": {"cases": []},
            },
            {
                "runId": "ff22ff22ff22",
                "status": "done",
                "suite": "demo",
                "summary": {"cases": [{"name": "a | b", "passed": True}]},
            },
        )
        md_pipe = _diff_md(pipe_diff)
        if "a \\| b" not in md_pipe or "| a | b |" in md_pipe:
            print("smoke failed pipe-escape run diff md", md_pipe, file=sys.stderr)
            return 1
        amp_diff = _diff_runs(
            {
                "runId": "ee11ee11ee11",
                "status": "done",
                "suite": "demo",
                "summary": {"cases": []},
            },
            {
                "runId": "ee22ee22ee22",
                "status": "done",
                "suite": "demo",
                "summary": {"cases": [{"name": "a & <b>", "passed": True}]},
            },
        )
        html_amp = _diff_html(amp_diff)
        if (
            "&amp;" not in html_amp
            or "&lt;" not in html_amp
            or "a & <b>" in html_amp
            or "<table" not in html_amp
        ):
            print("smoke failed html-escape run diff html", html_amp, file=sys.stderr)
            return 1
        store = {"aa11aa11aa11": green, "bb22bb22bb22": extra_fail}
        queued = {"runId": "dd44dd44dd44", "status": "queued", "suite": "demo"}
        store["dd44dd44dd44"] = queued
        code404, body404 = _diff_http("ee55ee55ee55", "aa11aa11aa11", store.get)
        code409, body409 = _diff_http("dd44dd44dd44", "aa11aa11aa11", store.get)
        code200, body200 = _diff_http("bb22bb22bb22", "aa11aa11aa11", store.get)
        code400, body400 = _diff_http("bb22bb22bb22", None, store.get)
        if (
            code404 != 404
            or body404.get("error") != "run_not_found"
            or code409 != 409
            or body409.get("error") != "run_not_done"
            or code200 != 200
            or "demo/flaky" not in (body200.get("regressed") or [])
            or code400 != 400
        ):
            print(
                "smoke failed diff_runs_response",
                code404, body404, code409, body409, code200, body200, code400, body400,
                file=sys.stderr,
            )
            return 1

        empty_cases = _cases_json({"runId": "cccccccccccc", "status": "done", "suite": "demo", "summary": {"cases": []}})
        none_cases = _cases_json(None)
        queued_cases = _cases_json({"runId": "dddddddddddd", "status": "queued", "suite": "demo"})
        mixed_run = {
            "runId": "eeeeeeeeeeee",
            "status": "done",
            "suite": "demo",
            "summary": {
                "cases": [
                    {"name": "ok", "passed": True, "durationMs": 12},
                    {"name": "flaky", "passed": False, "error": "failed"},
                ]
            },
        }
        mixed_inv = _cases_json(mixed_run)
        fail_only = _cases_json(mixed_run, status="failed")
        unknown_st = _cases_json(mixed_run, status="nope")
        leaky_run = {
            "runId": "ffffffffffff",
            "status": "done",
            "suite": "demo",
            "summary": {
                "cases": [
                    {
                        "name": "leaky",
                        "passed": False,
                        "prompt": "SECRET_PROMPT do not leak",
                        "expected": "sk-planted-api-key-must-not-appear",
                        "actual": "SECRET_PROMPT",
                        "output": "Authorization: Bearer sk-test",
                        "error": "SECRET_PROMPT leaked",
                    }
                ]
            },
        }
        leaky_inv = _cases_json(leaky_run)
        leaky_blob = json.dumps(leaky_inv, ensure_ascii=False)
        big_run = {
            "runId": "bbbbbbbbbbbb",
            "status": "done",
            "suite": "demo",
            "summary": {
                "cases": [{"name": f"c{i}", "passed": True} for i in range(CASES_LIST_CAP + 1)]
            },
        }
        big_inv = _cases_json(big_run)
        helper_ok = (
            empty_cases == {"ok": True, "runId": "cccccccccccc", "status": "done", "count": 0, "cases": []}
            and none_cases.get("ok") is True
            and none_cases.get("count") == 0
            and none_cases.get("cases") == []
            and queued_cases.get("ok") is True
            and queued_cases.get("count") == 0
            and queued_cases.get("cases") == []
            and queued_cases.get("status") == "queued"
            and mixed_inv.get("ok") is True
            and mixed_inv.get("count") == 2
            and [c.get("name") for c in (mixed_inv.get("cases") or [])] == ["ok", "flaky"]
            and (mixed_inv.get("cases") or [{}])[0].get("status") == "passed"
            and (mixed_inv.get("cases") or [{}, {}])[1].get("status") == "failed"
            and (mixed_inv.get("cases") or [{}])[0].get("durationMs") == 12
            and (mixed_inv.get("cases") or [{}, {}])[1].get("error") == "failed"
            and fail_only.get("count") == 1
            and (fail_only.get("cases") or [{}])[0].get("name") == "flaky"
            and unknown_st.get("ok") is True
            and unknown_st.get("count") == 0
            and unknown_st.get("cases") == []
            and "SECRET_PROMPT" not in leaky_blob
            and "sk-planted" not in leaky_blob
            and "Authorization" not in leaky_blob
            and "Bearer " not in leaky_blob
            and (leaky_inv.get("cases") or [{}])[0].get("name") == "leaky"
            and (leaky_inv.get("cases") or [{}])[0].get("status") == "failed"
            and "prompt" not in (leaky_inv.get("cases") or [{}])[0]
            and "expected" not in (leaky_inv.get("cases") or [{}])[0]
            and "actual" not in (leaky_inv.get("cases") or [{}])[0]
            and "error" not in (leaky_inv.get("cases") or [{}])[0]
            and big_inv.get("truncated") is True
            and big_inv.get("count") == CASES_LIST_CAP + 1
            and len(big_inv.get("cases") or []) == CASES_LIST_CAP
            and (big_inv.get("cases") or [{}])[0].get("name") == "c0"
        )
        if not helper_ok:
            print(
                "smoke failed cases_json",
                empty_cases,
                mixed_inv,
                fail_only,
                leaky_inv,
                big_inv.get("count"),
                file=sys.stderr,
            )
            return 1
        import tempfile
        demo_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as cases_td:
            demo_rec = _execute_run(
                {"suite": "fixtures/demo"},
                runs_dir=Path(cases_td),
                root=demo_root,
            )
            demo_inv = _cases_json(demo_rec)
            demo_names = [c.get("name") for c in (demo_inv.get("cases") or [])]
            if (
                demo_inv.get("ok") is not True
                or int(demo_inv.get("count") or 0) < 1
                or "france-capital" not in demo_names
            ):
                print("smoke failed cases_json demo run", demo_inv, file=sys.stderr)
                return 1

        demo_suite = _get_suite("demo", demo_root)
        miss_suite = _get_suite("no-such-suite-xyz", demo_root)
        suite_blob = json.dumps(demo_suite or {}, ensure_ascii=False)
        suite_names = [c.get("name") for c in ((demo_suite or {}).get("cases") or [])]
        empty_root = Path(tempfile.mkdtemp(prefix="c-empty-suite-"))
        try:
            (empty_root / "fixtures" / "empty").mkdir(parents=True)
            empty_suite = _get_suite("empty", empty_root)
        finally:
            import shutil as _shutil
            _shutil.rmtree(empty_root, ignore_errors=True)
        leaky_fix = Path(tempfile.mkdtemp(prefix="c-leaky-suite-"))
        try:
            leaky_dir = leaky_fix / "fixtures" / "leaky"
            leaky_dir.mkdir(parents=True)
            (leaky_dir / "planted.json").write_text(
                json.dumps({
                    "name": "planted",
                    "prompt": "SECRET_PROMPT do not leak",
                    "trajectory": [{"tool": "x", "arguments": {"k": "sk-planted-api-key"}}],
                }),
                encoding="utf-8",
            )
            leaky_suite = _get_suite("leaky", leaky_fix)
            leaky_suite_blob = json.dumps(leaky_suite or {}, ensure_ascii=False)
        finally:
            import shutil as _shutil2
            _shutil2.rmtree(leaky_fix, ignore_errors=True)
        suite_helper_ok = (
            isinstance(demo_suite, dict)
            and demo_suite.get("ok") is True
            and demo_suite.get("id") == "demo"
            and demo_suite.get("name") == "demo"
            and "france-capital" in suite_names
            and "math-2plus2" in suite_names
            and all(set((c or {}).keys()) <= {"name"} for c in (demo_suite.get("cases") or []))
            and "prompt" not in suite_blob
            and "trajectory" not in suite_blob
            and "SECRET_PROMPT" not in suite_blob
            and miss_suite is None
            and (empty_suite or {}).get("ok") is True
            and (empty_suite or {}).get("id") == "empty"
            and (empty_suite or {}).get("cases") == []
            and (leaky_suite or {}).get("ok") is True
            and (leaky_suite or {}).get("cases") == [{"name": "planted"}]
            and "SECRET_PROMPT" not in leaky_suite_blob
            and "sk-planted" not in leaky_suite_blob
            and "trajectory" not in leaky_suite_blob
            and "prompt" not in leaky_suite_blob
        )
        if not suite_helper_ok:
            print(
                "smoke failed get_suite",
                demo_suite,
                miss_suite,
                empty_suite,
                leaky_suite,
                file=sys.stderr,
            )
            return 1

        synth = to_junit(
            two_pass, suite_name="gate", gate={"failUnder": 101, "passed": False}
        )
        if (
            GATE_ERROR not in synth
            or 'failures="1"' not in synth
            or f'message="{GATE_ERROR}"' not in synth
        ):
            print("smoke failed synthetic junit gate", synth, file=sys.stderr)
            return 1
        hash_fail = CaseResult(
            name="bad & # x",
            passed=False,
            expected="want",
            actual="got # fail",
        )
        tap_txt = to_tap([ok_case, hash_fail], suite_name="smoke")
        tap_result_lines = [
            ln
            for ln in tap_txt.splitlines()
            if ln.startswith("ok ") or ln.startswith("not ok ")
        ]
        tap_ok = (
            tap_txt.startswith("TAP version 13")
            and "1..2" in tap_txt
            and "ok " in tap_txt
            and "not ok " in tap_txt
            and len(tap_result_lines) == 2
            and "&" in tap_txt
            and "\\#" in tap_txt
            and not any(
                (rest := ln.split(" - ", 1)[-1] if " - " in ln else "")
                and "#" in rest.replace("\\#", "")
                for ln in tap_result_lines
            )
        )
        if not tap_ok:
            print("smoke failed tap13", tap_txt, file=sys.stderr)
            return 1
        empty_tap = to_tap([], suite_name="empty")
        if "TAP version 13" not in empty_tap or "1..0" not in empty_tap:
            print("smoke failed empty tap", empty_tap, file=sys.stderr)
            return 1
        from_run_tap = run_to_tap(fake_run)
        if (
            "TAP version 13" not in from_run_tap
            or "ok " not in from_run_tap
            or "not ok " not in from_run_tap
            or "&" not in from_run_tap
        ):
            print("smoke failed run_to_tap", from_run_tap, file=sys.stderr)
            return 1
        empty_agg_tap = runs_to_tap([])
        if "TAP version 13" not in empty_agg_tap or "1..0" not in empty_agg_tap:
            print("smoke failed empty runs_to_tap", empty_agg_tap, file=sys.stderr)
            return 1
        err_tap = run_to_tap(
            {
                "runId": "err1err1err1",
                "status": "error",
                "suite": "demo",
                "error": "suite_not_found",
                "detail": "missing & # gone",
            }
        )
        if "not ok " not in err_tap or "TAP version 13" not in err_tap:
            print("smoke failed error run_to_tap", err_tap, file=sys.stderr)
            return 1
        synth_tap = to_tap(
            two_pass, suite_name="gate", gate={"failUnder": 101, "passed": False}
        )
        if "not ok " not in synth_tap or GATE_ERROR not in synth_tap:
            print("smoke failed synthetic tap gate", synth_tap, file=sys.stderr)
            return 1
        pipe_fail = CaseResult(
            name="a | b",
            passed=False,
            expected="want",
            actual="got | fail",
        )
        md_txt = to_md([ok_case, pipe_fail], suite_name="smoke")
        md_ok = (
            md_txt.startswith("# ")
            and "| case | status | time |" in md_txt
            and "fail" in md_txt
            and "a \\| b" in md_txt
            and "| a | b |" not in md_txt
        )
        if not md_ok:
            print("smoke failed markdown report", md_txt, file=sys.stderr)
            return 1
        empty_md = to_md([], suite_name="empty")
        if (
            not empty_md.startswith("# ")
            or "| case | status | time |" not in empty_md
            or "| pass |" in empty_md
            or "| fail |" in empty_md
        ):
            print("smoke failed empty markdown", empty_md, file=sys.stderr)
            return 1
        from_run_md = run_to_md(fake_run)
        if (
            not from_run_md.startswith("# ")
            or "| case |" not in from_run_md
            or "fail" not in from_run_md
        ):
            print("smoke failed run_to_md", from_run_md, file=sys.stderr)
            return 1
        empty_agg_md = runs_to_md([])
        if not empty_agg_md.startswith("# ") or "| fail |" in empty_agg_md:
            print("smoke failed empty runs_to_md", empty_agg_md, file=sys.stderr)
            return 1
        err_md = run_to_md(
            {
                "runId": "err1err1err1",
                "status": "error",
                "suite": "demo",
                "error": "suite_not_found",
                "detail": "missing | gone",
            }
        )
        if not err_md.startswith("# ") or "fail" not in err_md:
            print("smoke failed error run_to_md", err_md, file=sys.stderr)
            return 1
        synth_md = to_md(
            two_pass, suite_name="gate", gate={"failUnder": 101, "passed": False}
        )
        if "fail" not in synth_md or GATE_ERROR not in synth_md:
            print("smoke failed synthetic markdown gate", synth_md, file=sys.stderr)
            return 1
        html_txt = to_html([ok_case, bad_case], suite_name="smoke")
        html_ok = (
            html_txt.startswith("<!doctype html>")
            and "<table" in html_txt
            and "fail" in html_txt
            and "&amp;" in html_txt
            and "&lt;" in html_txt
            and "bad & x" not in html_txt
            and "got & <fail>" not in html_txt
            and 'class="fail"' in html_txt
        )
        if not html_ok:
            print("smoke failed html report", html_txt, file=sys.stderr)
            return 1
        empty_html = to_html([], suite_name="empty")
        if (
            "<h1" not in empty_html
            or "no runs" not in empty_html
            or "<table" not in empty_html
            or 'class="fail"' in empty_html
        ):
            print("smoke failed empty html", empty_html, file=sys.stderr)
            return 1
        from_run_html = run_to_html(fake_run)
        if (
            "<table" not in from_run_html
            or "fail" not in from_run_html
            or "&amp;" not in from_run_html
        ):
            print("smoke failed run_to_html", from_run_html, file=sys.stderr)
            return 1
        empty_agg_html = runs_to_html([])
        if "<h1" not in empty_agg_html or "no runs" not in empty_agg_html:
            print("smoke failed empty runs_to_html", empty_agg_html, file=sys.stderr)
            return 1
        err_html = run_to_html(
            {
                "runId": "err1err1err1",
                "status": "error",
                "suite": "demo",
                "error": "suite_not_found",
                "detail": "missing & <gone>",
            }
        )
        if (
            "<h1" not in err_html
            or "fail" not in err_html
            or "&amp;" not in err_html
            or "&lt;" not in err_html
            or "missing & <gone>" in err_html
        ):
            print("smoke failed error run_to_html", err_html, file=sys.stderr)
            return 1
        synth_html = to_html(
            two_pass, suite_name="gate", gate={"failUnder": 101, "passed": False}
        )
        if (
            "fail" not in synth_html
            or GATE_ERROR not in synth_html
            or "failUnder" not in synth_html
        ):
            print("smoke failed synthetic html gate", synth_html, file=sys.stderr)
            return 1
        gha_txt = to_gha([ok_case, bad_case], suite_name="smoke")
        gha_pass = to_gha([ok_case], suite_name="smoke")
        gha_ok = (
            "::error" in gha_txt
            and "title=smoke/" in gha_txt
            and "::error" not in gha_pass
            and gha_pass == ""
        )
        if not gha_ok:
            print("smoke failed gha annotations", gha_txt, gha_pass, file=sys.stderr)
            return 1
        empty_gha = to_gha([], suite_name="empty")
        if empty_gha != "" or "::error" in empty_gha:
            print("smoke failed empty gha", empty_gha, file=sys.stderr)
            return 1
        from_run_gha = run_to_gha(fake_run)
        if "::error" not in from_run_gha or "title=demo/" not in from_run_gha:
            print("smoke failed run_to_gha", from_run_gha, file=sys.stderr)
            return 1
        empty_agg_gha = runs_to_gha([])
        if empty_agg_gha != "" or "::error" in empty_agg_gha:
            print("smoke failed empty runs_to_gha", empty_agg_gha, file=sys.stderr)
            return 1
        err_gha = run_to_gha(
            {
                "runId": "err1err1err1",
                "status": "error",
                "suite": "demo",
                "error": "suite_not_found",
                "detail": "missing % gone\nnext",
            }
        )
        if (
            "::error" not in err_gha
            or "title=demo/" not in err_gha
            or "%25" not in err_gha
            or "%0A" not in err_gha
        ):
            print("smoke failed error run_to_gha", err_gha, file=sys.stderr)
            return 1
        synth_gha = to_gha(
            two_pass,
            suite_name="gate",
            gate={"failUnder": 101, "passed": False},
            score=100.0,
        )
        if (
            "::error title=gate::" not in synth_gha
            or "score 100 < failUnder 101" not in synth_gha
            or GATE_ERROR in synth_gha
        ):
            print("smoke failed synthetic gha gate", synth_gha, file=sys.stderr)
            return 1
        import contextlib
        import io
        import shutil
        import tempfile as _gate_tmp

        def _run_cli(argv):
            buf = io.StringIO()
            err = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
                code = main(argv)
            return code, buf.getvalue(), err.getvalue()

        import tempfile as _diff_tmp
        with _diff_tmp.TemporaryDirectory() as _dtd:
            dp = Path(_dtd)
            (dp / "from.json").write_text(json.dumps(green), encoding="utf-8")
            (dp / "to.json").write_text(json.dumps(extra_fail), encoding="utf-8")
            (dp / "same.json").write_text(
                json.dumps(
                    {
                        "runId": "cc33cc33cc33",
                        "status": "done",
                        "suite": "demo",
                        "summary": {
                            "cases": [
                                {"name": "ok", "passed": True},
                                {"name": "flaky", "passed": True},
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            code, out, _err = _run_cli(
                ["diff", "--from", str(dp / "from.json"), "--to", str(dp / "to.json")]
            )
            try:
                cli_diff = json.loads(out)
            except json.JSONDecodeError:
                cli_diff = {}
            if code != 0 or "demo/flaky" not in (cli_diff.get("regressed") or []):
                print(
                    f"smoke failed cli diff extra-fail code={code} out={out!r} err={_err!r}",
                    file=sys.stderr,
                )
                return 1
            code, out, _err = _run_cli(
                ["diff", "--from", str(dp / "from.json"), "--to", str(dp / "same.json")]
            )
            try:
                cli_same = json.loads(out)
            except json.JSONDecodeError:
                cli_same = {}
            if (
                code != 0
                or cli_same.get("regressed") != []
                or cli_same.get("added") != []
                or cli_same.get("removed") != []
                or cli_same.get("fixed") != []
                or cli_same.get("unchanged") != 2
            ):
                print(
                    f"smoke failed cli diff identical code={code} out={out!r} err={_err!r}",
                    file=sys.stderr,
                )
                return 1
            code, out, _err = _run_cli(
                [
                    "diff",
                    "--from",
                    str(dp / "from.json"),
                    "--to",
                    str(dp / "to.json"),
                    "--format",
                    "md",
                ]
            )
            if (
                code != 0
                or "regressed" not in out
                or "demo/flaky" not in out
                or not out.startswith("# ")
            ):
                print(
                    f"smoke failed cli diff extra-fail md code={code} out={out!r} err={_err!r}",
                    file=sys.stderr,
                )
                return 1
            code, out, _err = _run_cli(
                [
                    "diff",
                    "--from",
                    str(dp / "from.json"),
                    "--to",
                    str(dp / "same.json"),
                    "--format",
                    "md",
                ]
            )
            if (
                code != 0
                or "no changes" not in out
                or not out.startswith("# ")
                or "## regressed" in out
            ):
                print(
                    f"smoke failed cli diff identical md code={code} out={out!r} err={_err!r}",
                    file=sys.stderr,
                )
                return 1
            code, out, _err = _run_cli(
                [
                    "diff",
                    "--from",
                    str(dp / "from.json"),
                    "--to",
                    str(dp / "to.json"),
                    "--format",
                    "html",
                ]
            )
            if (
                code != 0
                or "<table" not in out
                or "flaky" not in out
                or 'class="fail"' not in out
            ):
                print(
                    f"smoke failed cli diff extra-fail html code={code} out={out!r} err={_err!r}",
                    file=sys.stderr,
                )
                return 1
            code, out, _err = _run_cli(
                [
                    "diff",
                    "--from",
                    str(dp / "from.json"),
                    "--to",
                    str(dp / "same.json"),
                    "--format",
                    "html",
                ]
            )
            if (
                code != 0
                or "no changes" not in out
                or "<table" in out
            ):
                print(
                    f"smoke failed cli diff identical html code={code} out={out!r} err={_err!r}",
                    file=sys.stderr,
                )
                return 1

        code, out, _err = _run_cli(
            ["run", "--suite", "fixtures/demo", "--fail-under", "80"]
        )
        if code != 0:
            print(
                f"smoke failed fail-under 80 on 2-pass code={code} out={out!r} err={_err!r}",
                file=sys.stderr,
            )
            return 1
        code, out, _err = _run_cli(["run", "--suite", "fixtures/demo"])
        if code != 0:
            print(
                f"smoke failed no-flag 2-pass code={code} out={out!r} err={_err!r}",
                file=sys.stderr,
            )
            return 1
        code, out, _err = _run_cli(
            ["run", "--suite", "fixtures/demo", "--format", "gha"]
        )
        if code != 0 or "::error" in out:
            print(
                f"smoke failed format gha pass-only code={code} out={out!r} err={_err!r}",
                file=sys.stderr,
            )
            return 1
        code, out, _err = _run_cli(
            ["run", "--suite", "fixtures/demo", "--format", "annotations"]
        )
        if code != 0 or "::error" in out:
            print(
                f"smoke failed format annotations pass-only code={code} out={out!r} err={_err!r}",
                file=sys.stderr,
            )
            return 1
        _root = Path(__file__).resolve().parents[2]
        with _gate_tmp.TemporaryDirectory() as td:
            mixed_dir = Path(td) / "mixed"
            mixed_dir.mkdir()
            shutil.copy(
                _root / "fixtures" / "demo" / "france-capital.json",
                mixed_dir / "france-capital.json",
            )
            shutil.copy(
                _root / "fixtures" / "drift" / "france-drift.json",
                mixed_dir / "france-drift.json",
            )
            code, out, _err = _run_cli(
                ["run", "--suite", str(mixed_dir), "--fail-under", "80"]
            )
            if code != 1:
                print(
                    f"smoke failed fail-under 80 on 1-pass/1-fail code={code} out={out!r} err={_err!r}",
                    file=sys.stderr,
                )
                return 1
            code, out, _err = _run_cli(
                ["run", "--suite", str(mixed_dir), "--format", "gha"]
            )
            if code != 1 or "::error" not in out:
                print(
                    f"smoke failed format gha mixed-fail code={code} out={out!r} err={_err!r}",
                    file=sys.stderr,
                )
                return 1
            code, out, _err = _run_cli(
                [
                    "run",
                    "--suite",
                    str(mixed_dir),
                    "--format",
                    "gha",
                    "--fail-under",
                    "80",
                ]
            )
            if code != 1 or "::error" not in out or "title=gate" not in out:
                print(
                    f"smoke failed format gha mixed gate code={code} out={out!r} err={_err!r}",
                    file=sys.stderr,
                )
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
                None, env={"AGENT_CI_CORS_ORIGINS": "http://localhost:3000"}
            )
            == ["http://localhost:3000"]
            and resolve_cors_origins("", env={"AGENT_CI_CORS_ORIGINS": "*"}) == []
            and resolve_cors_origins("*", env={}) == ["*"]
            and "X-Request-Id" in DEFAULT_CORS_HEADERS
            and "X-Request-Id" in DEFAULT_CORS_EXPOSE_HEADERS
            and any(h.lower() == "retry-after" for h in DEFAULT_CORS_EXPOSE_HEADERS)
            and "X-Request-Id" in (cors.get("headers") or [])
            and "X-Request-Id" in (cors.get("expose") or [])
            and any(h.lower() == "retry-after" for h in (cors.get("expose") or []))
            and "X-Request-Id"
            in str((pf_ok.get("headers") or {}).get("Access-Control-Allow-Headers", ""))
            and "retry-after"
            in str((pf_ok.get("headers") or {}).get("Access-Control-Expose-Headers", "")).lower()
            and "x-request-id"
            in str((pf_ok.get("headers") or {}).get("Access-Control-Expose-Headers", "")).lower()
            and "retry-after"
            in str(
                cors_response_headers("http://localhost:3000", cors).get(
                    "Access-Control-Expose-Headers", ""
                )
            ).lower()
            and "x-request-id"
            in str(
                cors_response_headers("http://localhost:3000", cors).get(
                    "Access-Control-Expose-Headers", ""
                )
            ).lower()
            and "Access-Control-Expose-Headers" not in (pf_evil.get("headers") or {})
            and "Access-Control-Allow-Origin" not in (pf_evil.get("headers") or {})
        )
        if not cors_ok:
            print("smoke failed cors", file=sys.stderr)
            return 1

        rl = SlidingWindowRateLimiter(window_seconds=60.0)
        assert rl.check("127.0.0.1", 2)[0] is True
        assert rl.check("127.0.0.1", 2)[0] is True
        allowed, retry_after = rl.check("127.0.0.1", 2)
        if allowed or retry_after < 1:
            print("smoke failed rate_limit sliding window", allowed, retry_after, file=sys.stderr)
            return 1
        if not rl.check("10.0.0.1", 2)[0]:
            print("smoke failed rate_limit ip isolation", file=sys.stderr)
            return 1
        if (
            not skip_rate_limit("/health")
            or not skip_rate_limit("/ready")
            or not skip_rate_limit("/metrics")
            or skip_rate_limit("/v1/suites")
            or skip_rate_limit("/v1/runs")
            or skip_rate_limit("/openapi.json")
        ):
            print("smoke failed rate_limit skip paths", file=sys.stderr)
            return 1
        if client_ip_from_headers({"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}) != "1.2.3.4":
            print("smoke failed rate_limit xff first hop", file=sys.stderr)
            return 1
        if client_ip_from_headers({}, remote="127.0.0.1") != "127.0.0.1":
            print("smoke failed rate_limit socket fallback", file=sys.stderr)
            return 1
        if (
            resolve_rate_limit(None, env={}) != DEFAULT_RATE_LIMIT_PER_MINUTE
            or resolve_rate_limit(2, env={ENV_RATE_LIMIT_PER_MINUTE: "9"}) != 2
            or resolve_rate_limit(None, env={ENV_RATE_LIMIT_PER_MINUTE: "3"}) != 3
            or resolve_rate_limit(None, env={ENV_RATE_LIMIT_RPM: "4"}) != 4
            or resolve_rate_limit(0, env={}) is not None
        ):
            print("smoke failed rate_limit resolve", file=sys.stderr)
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
            print("smoke failed X-Request-Id resolve/sanitize", file=sys.stderr)
            return 1
        access_line = format_access_log(
            service="agent-ci",
            method="GET",
            path="/v1/suites",
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
            and access_obj.get("service") == "agent-ci"
            and access_obj.get("method") == "GET"
            and access_obj.get("path") == "/v1/suites"
            and access_obj.get("status") == 200
            and access_obj.get("requestId") == "test-log-1"
            and isinstance(access_obj.get("durationMs"), (int, float))
            and access_obj.get("durationMs") == 12
            and '"msg":"http"' in access_line
            and should_skip_access_log("GET", "/metrics")
            and should_skip_access_log("GET", "/health")
            and should_skip_access_log("GET", "/ready")
            and should_skip_access_log("OPTIONS", "/v1/suites")
            and not should_skip_access_log("GET", "/v1/suites")
            and resolve_log_json(None, env={}) is False
            and resolve_log_json(None, env={"LOG_FORMAT": "json"}) is True
            and resolve_log_json(True, env={}) is True
            and resolve_log_json(False, env={"LOG_FORMAT": "json"}) is False
        )
        if not access_ok:
            print("smoke failed JSON access log format/resolve", access_line, file=sys.stderr)
            return 1
        hook_ok = (
            resolve_webhook_url(None, env={}) is None
            and resolve_webhook_url(
                None, env={"AGENT_CI_WEBHOOK_URL": "http://127.0.0.1:9/hook"}
            )
            == "http://127.0.0.1:9/hook"
            and resolve_webhook_url("", env={"AGENT_CI_WEBHOOK_URL": "http://x"}) is None
            and resolve_webhook_url(
                "http://cli/hook", env={"AGENT_CI_WEBHOOK_URL": "http://env/hook"}
            )
            == "http://cli/hook"
            and resolve_webhook_secret(None, env={}) is None
            and resolve_webhook_secret(
                None, env={"AGENT_CI_WEBHOOK_SECRET": "whsec_env"}
            )
            == "whsec_env"
            and resolve_webhook_secret("", env={"AGENT_CI_WEBHOOK_SECRET": "whsec_env"})
            is None
            and resolve_webhook_secret(
                "whsec_cli", env={"AGENT_CI_WEBHOOK_SECRET": "whsec_env"}
            )
            == "whsec_cli"
            and run_conclusion({"status": "done", "passed": True}) == "success"
            and run_conclusion({"status": "done", "passed": False}) == "failure"
            and run_conclusion({"status": "error"}) == "error"
            and run_conclusion({"status": "failed", "passed": False, "error": "below_threshold"}) == "failure"
        )
        if not hook_ok:
            print("smoke failed webhook resolve/conclusion", file=sys.stderr)
            return 1
        hook_payload = build_webhook_payload(
            {
                "runId": "abc123abc123",
                "status": "done",
                "passed": True,
                "requestId": "mvp-req-id-a1b2c3d4",
                "summary": {"total": 2, "passed": 2, "failed": 0, "ok": True},
            }
        )
        hook_payload_ok = (
            hook_payload.get("runId") == "abc123abc123"
            and hook_payload.get("status") == "done"
            and hook_payload.get("requestId") == "mvp-req-id-a1b2c3d4"
            and hook_payload.get("conclusion") == "success"
            and isinstance(hook_payload.get("summary"), dict)
            and hook_payload["summary"].get("passed") == 2
            and set(hook_payload) >= {"runId", "status", "summary", "requestId", "conclusion"}
        )
        if not hook_payload_ok:
            print("smoke failed webhook payload", file=sys.stderr)
            return 1
        gate_hook = build_webhook_payload(
            {
                "runId": "abc123abc123",
                "status": "failed",
                "passed": False,
                "score": 50.0,
                "error": GATE_ERROR,
                "gate": {"failUnder": 80, "passed": False},
                "requestId": "mvp-req-id-a1b2c3d4",
                "summary": {"total": 2, "passed": 1, "failed": 1, "ok": False},
            }
        )
        if (
            gate_hook.get("status") != "failed"
            or gate_hook.get("conclusion") != "failure"
            or gate_hook.get("score") != 50.0
            or gate_hook.get("gate") != {"failUnder": 80, "passed": False}
        ):
            print("smoke failed webhook payload score/gate", gate_hook, file=sys.stderr)
            return 1
        hmac_body = b'{"runId":"abc","status":"done"}'
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
            print("smoke failed webhook HMAC sign/verify", file=sys.stderr)
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
            print("smoke failed webhook timestamp", file=sys.stderr)
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
            print("smoke failed webhook should_retry_webhook policy", file=sys.stderr)
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

        retry_payload = {
            "runId": "rid-retry",
            "status": "done",
            "summary": {"total": 1, "passed": 1, "failed": 0, "ok": True},
            "requestId": "rid-retry",
            "conclusion": "success",
        }

        def _run_post(urlopen_fn, extra=None):
            extra = extra or {}
            sleeps = []
            post_run_webhook(
                "http://127.0.0.1:9/hook",
                retry_payload,
                urlopen=urlopen_fn,
                sleep=lambda s: sleeps.append(s),
                retry_delay=extra.get("retry_delay", DEFAULT_RETRY_DELAY_S),
                secret=extra.get("secret"),
            )
            return sleeps

        import urllib.error as _ue

        def _req_header(req, name):
            items = dict(req.header_items()) if hasattr(req, "header_items") else dict(req.headers or {})
            want = str(name).lower()
            for k, v in items.items():
                if str(k).lower() == want:
                    return v
            return None

        calls200 = []

        def urlopen_200(req, timeout=None):
            calls200.append(req)
            return _FakeResp(200)

        sleeps = _run_post(urlopen_200)
        if len(calls200) != 1 or sleeps:
            print(
                f"smoke failed webhook no-retry on 200 calls={len(calls200)} sleeps={sleeps}",
                file=sys.stderr,
            )
            return 1

        calls400 = []

        def urlopen_400(req, timeout=None):
            calls400.append(req)
            return _FakeResp(400)

        sleeps = _run_post(urlopen_400)
        if len(calls400) != 1 or sleeps:
            print(
                f"smoke failed webhook no-retry on 4xx calls={len(calls400)} sleeps={sleeps}",
                file=sys.stderr,
            )
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
            print(
                f"smoke failed webhook retry on 5xx calls={len(calls500)} sleeps={sleeps}",
                file=sys.stderr,
            )
            return 1

        calls_net = []

        def urlopen_net(req, timeout=None):
            calls_net.append(req)
            if len(calls_net) == 1:
                raise _ue.URLError("ECONNRESET")
            return _FakeResp(200)

        sleeps = _run_post(urlopen_net)
        if len(calls_net) != 2 or sleeps != [DEFAULT_RETRY_DELAY_S]:
            print(
                f"smoke failed webhook retry on network error calls={len(calls_net)} sleeps={sleeps}",
                file=sys.stderr,
            )
            return 1

        calls_hmac = []

        def urlopen_hmac(req, timeout=None):
            calls_hmac.append(req)
            if len(calls_hmac) == 1:
                return _FakeResp(503)
            return _FakeResp(200)

        sleeps = _run_post(
            urlopen_hmac, {"secret": "whsec_retry", "retry_delay": 0}
        )
        if len(calls_hmac) != 2:
            print(
                f"smoke failed webhook HMAC retry call count {len(calls_hmac)}",
                file=sys.stderr,
            )
            return 1
        sig0 = _req_header(calls_hmac[0], SIGNATURE_HEADER)
        sig1 = _req_header(calls_hmac[1], SIGNATURE_HEADER)
        expected = sign_webhook_body("whsec_retry", calls_hmac[0].data)
        if sig0 != expected or sig1 != expected:
            print(
                f"smoke failed webhook HMAC retry signatures {sig0} {sig1}",
                file=sys.stderr,
            )
            return 1
        ts0 = _req_header(calls_hmac[0], TIMESTAMP_HEADER)
        ts1 = _req_header(calls_hmac[1], TIMESTAMP_HEADER)
        if not ts0 or not ts1:
            print(
                f"smoke failed webhook timestamp on retry ts0={ts0} ts1={ts1}",
                file=sys.stderr,
            )
            return 1

        try:
            notify_run_complete(None, {"status": "done"})
            notify_run_complete(
                "http://127.0.0.1:1/nope", {"runId": "x", "status": "queued"}
            )
            notify_run_complete(
                "http://127.0.0.1:1/nope",
                {"runId": "x", "status": "done"},
                secret="whsec_smoke",
            )
        except Exception as e:
            print(f"smoke failed webhook notify swallow: {e}", file=sys.stderr)
            return 1
        spec_path = Path(__file__).resolve().parents[2] / "openapi" / "runner.openapi.json"
        try:
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"smoke failed openapi load: {e}", file=sys.stderr)
            return 1
        need = [
            "/health",
            "/metrics",
            "/v1/runs",
            "/v1/runs/{id}",
            "/v1/runs/{id}/junit",
            "/v1/runs/{id}/junit.xml",
            "/v1/runs/junit.xml",
            "/v1/runs/{id}/tap",
            "/v1/runs/{id}/tap.txt",
            "/v1/runs/tap.txt",
            "/v1/runs/{id}/md",
            "/v1/runs/{id}/report.md",
            "/v1/runs/report.md",
            "/v1/runs/{id}/html",
            "/v1/runs/{id}/report.html",
            "/v1/runs/report.html",
            "/v1/runs/{id}/annotations",
            "/v1/runs/{id}/annotations.txt",
            "/v1/runs/annotations.txt",
            "/v1/runs/{id}/diff",
            "/v1/runs/{id}/diff.md",
            "/v1/runs/{id}/diff.html",
            "/v1/runs/{id}/cases",
            "/v1/check-runs",
            "/v1/suites",
            "/v1/suites/{name}",
            "/v1/config",
        ]
        paths = spec.get("paths") or {}
        missing = [p for p in need if p not in paths]
        post_runs = ((paths.get("/v1/runs") or {}).get("post") or {}).get("responses") or {}
        get_run = ((paths.get("/v1/runs/{id}") or {}).get("get") or {}).get("responses") or {}
        schemes = ((spec.get("components") or {}).get("securitySchemes") or {})
        desc = str((spec.get("info") or {}).get("description") or "")
        schemas = ((spec.get("components") or {}).get("schemas") or {})
        get_metrics = ((paths.get("/metrics") or {}).get("get") or {})
        openapi_ok = (
            not missing
            and "202" in post_runs
            and "429" in post_runs
            and "401" in post_runs
            and "404" in get_run
            and "BearerAuth" in schemes
            and get_metrics.get("operationId") == "getMetrics"
            and "AGENT_CI_WEBHOOK_URL" in desc
            and "AGENT_CI_WEBHOOK_SECRET" in desc
            and "X-Webhook-Signature" in desc
            and "X-Webhook-Timestamp" in desc
            and "GET /metrics" in desc
            and "--watch" in desc
            and "RunCompleteWebhook" in schemas
            and "WatchSnapshot" in schemas
            and "shutting_down" in str((schemas.get("Ready") or {}).get("properties") or {})
            and "503" in (((paths.get("/ready") or {}).get("get") or {}).get("responses") or {})
            and "CorsConfig" in schemas
            and "retry-after" in str((schemas.get("CorsConfig") or {}).get("description") or "").lower()
            and "expose" in str((schemas.get("CorsConfig") or {}).get("description") or "").lower()
            and "get" in (paths.get("/v1/runs/{id}/junit.xml") or {})
            and "get" in (paths.get("/v1/runs/junit.xml") or {})
            and "junit.xml" in desc
            and "get" in (paths.get("/v1/runs/{id}/tap.txt") or {})
            and "get" in (paths.get("/v1/runs/{id}/tap") or {})
            and "get" in (paths.get("/v1/runs/tap.txt") or {})
            and "tap.txt" in desc
            and "get" in (paths.get("/v1/runs/{id}/report.md") or {})
            and "get" in (paths.get("/v1/runs/{id}/md") or {})
            and "get" in (paths.get("/v1/runs/report.md") or {})
            and "report.md" in desc
            and "GITHUB_STEP_SUMMARY" in desc
            and "get" in (paths.get("/v1/runs/{id}/report.html") or {})
            and "get" in (paths.get("/v1/runs/{id}/html") or {})
            and "get" in (paths.get("/v1/runs/report.html") or {})
            and "report.html" in desc
            and (
                ((paths.get("/v1/runs/{id}/html") or {}).get("get") or {}).get("operationId")
                == "getRunHtml"
                or "getRunHtml"
                in str(
                    ((paths.get("/v1/runs/{id}/report.html") or {}).get("get") or {}).get(
                        "operationId"
                    )
                    or ""
                )
                or "getRunHtml"
                in str(
                    ((paths.get("/v1/runs/{id}/html") or {}).get("get") or {}).get(
                        "operationId"
                    )
                    or ""
                )
            )
            and "get" in (paths.get("/v1/runs/{id}/annotations.txt") or {})
            and "get" in (paths.get("/v1/runs/{id}/annotations") or {})
            and "get" in (paths.get("/v1/runs/annotations.txt") or {})
            and "annotations.txt" in desc
            and "RateLimited" in ((spec.get("components") or {}).get("responses") or {})
            and "429" in (((paths.get("/v1/suites") or {}).get("get") or {}).get("responses") or {})
            and "429" in (((paths.get("/v1/runs") or {}).get("get") or {}).get("responses") or {})
            and ("rate_limited" in desc or "RATE_LIMIT_PER_MINUTE" in desc)
            and "Retry-After" in desc
            and "failUnder" in str((schemas.get("CreateRunRequest") or {}).get("properties") or {})
            and "score" in str((schemas.get("RunRecord") or {}).get("properties") or {})
            and "gate" in str((schemas.get("RunRecord") or {}).get("properties") or {})
            and "failed" in str((schemas.get("RunRecord") or {}).get("properties") or {})
            and "QualityGate" in schemas
            and "failUnder" in desc
            and "below_threshold" in desc
            and "score" in str((schemas.get("RunCompleteWebhook") or {}).get("properties") or {})
            and "gate" in str((schemas.get("RunCompleteWebhook") or {}).get("properties") or {})
            and "failed" in str((schemas.get("RunCompleteWebhook") or {}).get("properties") or {})
            and ("RUNS_MAX" in desc or "--runs-max" in desc or "runs-max" in desc)
            and "get" in (paths.get("/v1/runs/{id}/diff") or {})
            and ((paths.get("/v1/runs/{id}/diff") or {}).get("get") or {}).get("operationId")
            == "getRunDiff"
            and "200" in (((paths.get("/v1/runs/{id}/diff") or {}).get("get") or {}).get("responses") or {})
            and "404" in (((paths.get("/v1/runs/{id}/diff") or {}).get("get") or {}).get("responses") or {})
            and "409" in (((paths.get("/v1/runs/{id}/diff") or {}).get("get") or {}).get("responses") or {})
            and "get" in (paths.get("/v1/runs/{id}/diff.md") or {})
            and ((paths.get("/v1/runs/{id}/diff.md") or {}).get("get") or {}).get("operationId")
            == "getRunDiffMd"
            and "200" in (((paths.get("/v1/runs/{id}/diff.md") or {}).get("get") or {}).get("responses") or {})
            and "404" in (((paths.get("/v1/runs/{id}/diff.md") or {}).get("get") or {}).get("responses") or {})
            and "409" in (((paths.get("/v1/runs/{id}/diff.md") or {}).get("get") or {}).get("responses") or {})
            and "get" in (paths.get("/v1/runs/{id}/diff.html") or {})
            and ((paths.get("/v1/runs/{id}/diff.html") or {}).get("get") or {}).get("operationId")
            == "getRunDiffHtml"
            and "200" in (((paths.get("/v1/runs/{id}/diff.html") or {}).get("get") or {}).get("responses") or {})
            and "404" in (((paths.get("/v1/runs/{id}/diff.html") or {}).get("get") or {}).get("responses") or {})
            and "409" in (((paths.get("/v1/runs/{id}/diff.html") or {}).get("get") or {}).get("responses") or {})
            and "RunDiff" in schemas
            and ("run_not_done" in desc or "/diff" in desc)
            and "diff.md" in desc
            and "diff.html" in desc
            and "get" in (paths.get("/v1/config") or {})
            and ((paths.get("/v1/config") or {}).get("get") or {}).get("operationId")
            == "getConfig"
            and "RuntimeConfig" in schemas
            and "GET /v1/config" in desc
            and "hasUrl" in str((schemas.get("RuntimeConfig") or {}))
            and "hasSecret" in str((schemas.get("RuntimeConfig") or {}))
            and "get" in (paths.get("/v1/runs/{id}/cases") or {})
            and ((paths.get("/v1/runs/{id}/cases") or {}).get("get") or {}).get("operationId")
            == "listRunCases"
            and "200" in (((paths.get("/v1/runs/{id}/cases") or {}).get("get") or {}).get("responses") or {})
            and "404" in (((paths.get("/v1/runs/{id}/cases") or {}).get("get") or {}).get("responses") or {})
            and "RunCases" in schemas
            and "RunCaseRow" in schemas
            and ("listRunCases" in desc or "/cases" in desc)
            and ((paths.get("/v1/suites/{name}") or {}).get("get") or {}).get("operationId")
            == "getSuite"
            and "200" in (((paths.get("/v1/suites/{name}") or {}).get("get") or {}).get("responses") or {})
            and "404" in (((paths.get("/v1/suites/{name}") or {}).get("get") or {}).get("responses") or {})
            and "SuiteDetail" in schemas
            and ("getSuite" in desc or "SuiteDetail" in desc)
        )
        if not openapi_ok:
            print(f"smoke failed openapi paths missing={missing}", file=sys.stderr)
            return 1
        zero = render_metrics()
        sample = render_metrics({"queued": 1, "running": 2, "completed": 3, "failed": 4})
        metrics_ok = (
            METRIC_QUEUE_DEPTH in zero
            and METRIC_RUNNING in zero
            and METRIC_COMPLETED in zero
            and METRIC_FAILED in zero
            and f"{METRIC_QUEUE_DEPTH} 0" in zero
            and f"{METRIC_QUEUE_DEPTH} 1" in sample
            and f"{METRIC_RUNNING} 2" in sample
            and f"{METRIC_COMPLETED} 3" in sample
            and f"{METRIC_FAILED} 4" in sample
            and "# TYPE" in sample
        )
        if not metrics_ok:
            print("smoke failed metrics render", file=sys.stderr)
            return 1
        from agent_ci.serve import (
            WATCH_POLL_MS,
            WatchState,
            start_fixtures_watch,
            walk_max_mtime,
        )
        if WATCH_POLL_MS != 400:
            print(
                f"smoke failed WATCH_POLL_MS expected 400 got {WATCH_POLL_MS}",
                file=sys.stderr,
            )
            return 1
        import os as _os
        import tempfile
        import threading as _threading
        import time as _watch_time
        with tempfile.TemporaryDirectory() as watch_td:
            wroot = Path(watch_td)
            demo = wroot / "demo"
            demo.mkdir()
            (demo / "case.json").write_text("{}", encoding="utf-8")
            m0 = walk_max_mtime(wroot)
            state = WatchState()
            if state.snapshot() != {"generation": 0}:
                print(
                    f"smoke failed watch generation initial {state.snapshot()}",
                    file=sys.stderr,
                )
                return 1
            logs: list[str] = []
            stop = _threading.Event()
            _t, stop = start_fixtures_watch(
                wroot,
                watch_state=state,
                poll_ms=50,
                log=logs.append,
                stop_event=stop,
            )
            added = wroot / "watch-added"
            added.mkdir()
            later = _watch_time.time() + 1
            _os.utime(added, (later, later))
            _os.utime(wroot, (later, later))
            m1 = walk_max_mtime(wroot)
            if not (m1 > m0):
                stop.set()
                print(
                    f"smoke failed walk_max_mtime m0={m0} m1={m1}",
                    file=sys.stderr,
                )
                return 1
            ok_gen = False
            for _ in range(40):
                if int(state.snapshot().get("generation") or 0) >= 1:
                    ok_gen = True
                    break
                _watch_time.sleep(0.05)
            stop.set()
            _t.join(timeout=1)
            if not ok_gen:
                print(
                    f"smoke failed watch generation bump {state.snapshot()} logs={logs}",
                    file=sys.stderr,
                )
                return 1
            joined = "\n".join(logs)
            if "watching" not in joined or "regenerated" not in joined:
                print(f"smoke failed watch log {logs}", file=sys.stderr)
                return 1

        from agent_ci.serve import (
            DEFAULT_RUNS_MAX,
            DEFAULT_SHUTDOWN_DRAIN_MS,
            ENV_RUNS_MAX,
            MAX_SHUTDOWN_DRAIN_MS,
            begin_shutdown,
            cap_finished_runs,
            resolve_drain_ms,
            resolve_runs_max,
            start_background,
        )
        import urllib.error
        import urllib.request

        if (
            resolve_drain_ms(200) != 200
            or resolve_drain_ms(-1) != DEFAULT_SHUTDOWN_DRAIN_MS
            or resolve_drain_ms(99999) != MAX_SHUTDOWN_DRAIN_MS
            or resolve_drain_ms(None, env={}) != DEFAULT_SHUTDOWN_DRAIN_MS
            or resolve_drain_ms(None, env={"SHUTDOWN_DRAIN_MS": "250"}) != 250
        ):
            print("smoke failed resolve_drain_ms", file=sys.stderr)
            return 1
        with tempfile.TemporaryDirectory() as sd_td:
            sd_runs = Path(sd_td) / "runs"
            sd_server, _sd_thread = start_background(
                host="127.0.0.1",
                port=0,
                runs_dir=sd_runs,
                root=Path(__file__).resolve().parents[2],
            )
            try:
                host, port = sd_server.server_address[:2]
                base = f"http://{host}:{port}"
                import time as _sd_time
                ready0 = None
                for _ in range(50):
                    try:
                        with urllib.request.urlopen(base + "/ready") as resp:
                            ready0 = json.loads(resp.read().decode("utf-8"))
                            if resp.status != 200 or ready0.get("ok") is not True:
                                print(f"smoke failed ready before shutdown {ready0}", file=sys.stderr)
                                return 1
                        break
                    except urllib.error.URLError:
                        _sd_time.sleep(0.02)
                else:
                    print("smoke failed shutdown serve did not listen", file=sys.stderr)
                    return 1
                begin_shutdown(sd_server)
                try:
                    urllib.request.urlopen(base + "/ready")
                    print("smoke failed ready expected 503 shutting_down", file=sys.stderr)
                    return 1
                except urllib.error.HTTPError as e:
                    body = json.loads(e.read().decode("utf-8"))
                    if e.code != 503 or body.get("reason") != "shutting_down" or body.get("ok") is not False:
                        print(f"smoke failed ready shutting_down {e.code} {body}", file=sys.stderr)
                        return 1
                with urllib.request.urlopen(base + "/health") as resp:
                    health1 = json.loads(resp.read().decode("utf-8"))
                    if resp.status != 200 or health1.get("ok") is not True or health1.get("shuttingDown") is not True:
                        print(f"smoke failed health shuttingDown {health1}", file=sys.stderr)
                        return 1
            finally:
                try:
                    sd_server.shutdown()
                except Exception:
                    pass
                sd_server.server_close()

        if (
            DEFAULT_RUNS_MAX != 1000
            or ENV_RUNS_MAX != "RUNS_MAX"
            or resolve_runs_max(None, env={}) != DEFAULT_RUNS_MAX
            or resolve_runs_max(2, env={ENV_RUNS_MAX: "9"}) != 2
            or resolve_runs_max(None, env={ENV_RUNS_MAX: "3"}) != 3
            or resolve_runs_max(0, env={}) != 0
            or resolve_runs_max(-1, env={}) != DEFAULT_RUNS_MAX
            or resolve_runs_max("nope", env={}) != DEFAULT_RUNS_MAX
        ):
            print("smoke failed resolve_runs_max", file=sys.stderr)
            return 1
        mem_cap = {
            "aaaaaaaaaaaa": {
                "runId": "aaaaaaaaaaaa",
                "status": "done",
                "createdAt": "2026-01-01T00:00:00Z",
                "summary": {"passed": 1, "failed": 0, "total": 1},
            },
            "bbbbbbbbbbbb": {
                "runId": "bbbbbbbbbbbb",
                "status": "done",
                "createdAt": "2026-01-01T00:00:01Z",
                "summary": {"passed": 1, "failed": 0, "total": 1},
            },
            "cccccccccccc": {
                "runId": "cccccccccccc",
                "status": "failed",
                "createdAt": "2026-01-01T00:00:02Z",
                "summary": {"passed": 0, "failed": 1, "total": 1},
            },
            "dd44dd44dd44": {
                "runId": "dd44dd44dd44",
                "status": "queued",
                "createdAt": "2026-01-01T00:00:00Z",
            },
            "runningrunni": {
                "runId": "runningrunni",
                "status": "running",
                "createdAt": "2026-01-01T00:00:00Z",
            },
        }
        dropped_ids = cap_finished_runs(mem_cap, 2)
        if (
            dropped_ids != ["aaaaaaaaaaaa"]
            or "aaaaaaaaaaaa" in mem_cap
            or set(mem_cap)
            != {"bbbbbbbbbbbb", "cccccccccccc", "dd44dd44dd44", "runningrunni"}
        ):
            print(
                f"smoke failed cap_finished_runs dropped={dropped_ids} keys={sorted(mem_cap)}",
                file=sys.stderr,
            )
            return 1
        unlimited = {
            "a": {"runId": "a", "status": "done", "createdAt": "2026-01-01T00:00:00Z"},
            "b": {"runId": "b", "status": "done", "createdAt": "2026-01-01T00:00:01Z"},
            "c": {"runId": "c", "status": "error", "createdAt": "2026-01-01T00:00:02Z"},
        }
        if cap_finished_runs(unlimited, 0) != [] or len(unlimited) != 3:
            print("smoke failed cap_finished_runs 0 unlimited", file=sys.stderr)
            return 1

        with tempfile.TemporaryDirectory() as cap_td:
            cap_runs = Path(cap_td) / "runs"
            cap_server, _cap_thread = start_background(
                host="127.0.0.1",
                port=0,
                runs_dir=cap_runs,
                root=Path(__file__).resolve().parents[2],
                runs_max=2,
                rate_limit=0,
            )
            try:
                host, port = cap_server.server_address[:2]
                base = f"http://{host}:{port}"
                import time as _cap_time
                for _ in range(50):
                    try:
                        with urllib.request.urlopen(base + "/health") as resp:
                            if resp.status == 200:
                                break
                    except urllib.error.URLError:
                        _cap_time.sleep(0.02)
                else:
                    print("smoke failed runs-max serve did not listen", file=sys.stderr)
                    return 1
                case_body = json.dumps(
                    {
                        "cases": [
                            {
                                "name": "france-capital",
                                "prompt": "What is the capital of France?",
                                "expect": "Paris",
                            }
                        ]
                    }
                ).encode("utf-8")
                posted: list[str] = []
                for _ in range(3):
                    req = urllib.request.Request(
                        base + "/v1/runs",
                        data=case_body,
                        method="POST",
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req) as resp:
                        payload = json.loads(resp.read().decode("utf-8"))
                        rid = str(payload.get("runId") or "")
                        if not rid:
                            print(f"smoke failed runs-max POST {payload}", file=sys.stderr)
                            return 1
                        posted.append(rid)
                last = posted[-1]
                rec = None
                for _ in range(80):
                    try:
                        with urllib.request.urlopen(base + "/v1/runs/" + last) as resp:
                            rec = json.loads(resp.read().decode("utf-8"))
                    except urllib.error.HTTPError:
                        rec = None
                    if rec and rec.get("status") in ("done", "failed", "error"):
                        break
                    _cap_time.sleep(0.05)
                else:
                    print(f"smoke failed runs-max last run not done {rec}", file=sys.stderr)
                    return 1
                with urllib.request.urlopen(base + "/v1/runs?limit=10") as resp:
                    listing = json.loads(resp.read().decode("utf-8"))
                runs = listing.get("runs") or []
                listed = [str(r.get("runId") or "") for r in runs]
                if len(runs) != 2 or listing.get("count") != 2:
                    print(
                        f"smoke failed runs-max list length {listing}",
                        file=sys.stderr,
                    )
                    return 1
                if posted[0] in listed or posted[1] not in listed or posted[2] not in listed:
                    print(
                        f"smoke failed runs-max retained posted={posted} listed={listed}",
                        file=sys.stderr,
                    )
                    return 1
                try:
                    urllib.request.urlopen(base + "/v1/runs/" + posted[0])
                    print("smoke failed runs-max oldest expected 404", file=sys.stderr)
                    return 1
                except urllib.error.HTTPError as e:
                    if e.code != 404:
                        print(
                            f"smoke failed runs-max oldest status {e.code}",
                            file=sys.stderr,
                        )
                        return 1
                with urllib.request.urlopen(base + "/v1/runs/" + posted[2]) as resp:
                    newest = json.loads(resp.read().decode("utf-8"))
                    if newest.get("runId") != posted[2]:
                        print(f"smoke failed runs-max newest {newest}", file=sys.stderr)
                        return 1
            finally:
                try:
                    cap_server.shutdown()
                except Exception:
                    pass
                cap_server.server_close()

        from agent_ci.runtime_config import (
            FORBIDDEN_RUNTIME_CONFIG_KEYS,
            assert_runtime_config_safe,
            summarize_runtime_config,
        )

        cfg_payload = summarize_runtime_config(
            queue={"concurrency": 1, "maxQueue": 16, "queued": 2, "running": 1},
            max_queue=16,
            cors_origins=["http://localhost:3000"],
            rate_limit=120,
            runs_max=1000,
            webhook_url="http://127.0.0.1:9/hook?token=planted_url_token",
            webhook_secret="whsec_must_not_leak",
            suites_count=3,
        )
        cfg_blob = json.dumps(cfg_payload, ensure_ascii=False)
        cfg_safe = assert_runtime_config_safe(cfg_payload)
        cfg_ok = (
            cfg_payload.get("ok") is True
            and (cfg_payload.get("queue") or {}).get("max") == 16
            and (cfg_payload.get("queue") or {}).get("queued") == 2
            and (cfg_payload.get("queue") or {}).get("running") == 1
            and (cfg_payload.get("rateLimit") or {}).get("perMinute") == 120
            and (cfg_payload.get("cors") or {}).get("origins") == ["http://localhost:3000"]
            and cfg_payload.get("runsMax") == 1000
            and cfg_payload.get("failUnder") is None
            and (cfg_payload.get("webhooks") or {}).get("hasUrl") is True
            and (cfg_payload.get("webhooks") or {}).get("hasSecret") is True
            and cfg_payload.get("suitesCount") == 3
            and cfg_safe.get("ok") is True
            and "planted_url_token" not in cfg_blob
            and "whsec_must_not_leak" not in cfg_blob
            and "Authorization" not in cfg_blob
            and "webhookUrl" not in cfg_blob
            and "webhookSecret" not in cfg_blob
            and "secret" in FORBIDDEN_RUNTIME_CONFIG_KEYS
            and "Authorization" in FORBIDDEN_RUNTIME_CONFIG_KEYS
        )
        empty_cfg = summarize_runtime_config(
            queue={"maxQueue": 16, "queued": 0, "running": 0},
            max_queue=16,
            cors_origins=[],
            rate_limit=0,
            runs_max=0,
            webhook_url=None,
            webhook_secret=None,
            suites_count=0,
        )
        empty_ok = (
            empty_cfg.get("ok") is True
            and (empty_cfg.get("webhooks") or {}).get("hasUrl") is False
            and (empty_cfg.get("webhooks") or {}).get("hasSecret") is False
            and empty_cfg.get("runsMax") == 0
            and (empty_cfg.get("rateLimit") or {}).get("perMinute") is None
            and (empty_cfg.get("cors") or {}).get("origins") == []
            and assert_runtime_config_safe(empty_cfg).get("ok") is True
        )
        if not cfg_ok or not cfg_safe.get("ok") or not empty_ok:
            print(
                "smoke failed summarize_runtime_config",
                cfg_payload,
                cfg_safe,
                empty_cfg,
                file=sys.stderr,
            )
            return 1

        cfg_http_ok = False
        with tempfile.TemporaryDirectory() as cfg_td:
            cfg_runs = Path(cfg_td) / "runs"
            cfg_server, _cfg_thread = start_background(
                host="127.0.0.1",
                port=0,
                runs_dir=cfg_runs,
                root=Path(__file__).resolve().parents[2],
                cors_origins=["http://localhost:3000"],
                webhook_url="http://127.0.0.1:9/hook?token=http_url_token_must_not_leak",
                webhook_secret="http_whsec_must_not_leak",
                rate_limit=0,
            )
            try:
                host, port = cfg_server.server_address[:2]
                base = f"http://{host}:{port}"
                import time as _cfg_time
                cfg_http_body = None
                cfg_http_hdrs: dict[str, str] = {}
                cfg_http_status = 0
                for _ in range(80):
                    try:
                        req = urllib.request.Request(
                            base + "/v1/config",
                            headers={"X-Request-Id": "smoke-config-rid"},
                        )
                        with urllib.request.urlopen(req) as resp:
                            cfg_http_status = resp.status
                            cfg_http_hdrs = {str(k).lower(): v for k, v in resp.headers.items()}
                            raw = resp.read()
                        if cfg_http_status == 200:
                            cfg_http_body = json.loads(raw.decode("utf-8"))
                            break
                    except (OSError, json.JSONDecodeError, urllib.error.URLError):
                        _cfg_time.sleep(0.05)
                cfg_http_blob = json.dumps(cfg_http_body or {}, ensure_ascii=False)
                cfg_http_safe = assert_runtime_config_safe(cfg_http_body or {})
                q = (cfg_http_body or {}).get("queue") or {}
                cors = (cfg_http_body or {}).get("cors") or {}
                cfg_http_ok = (
                    cfg_http_status == 200
                    and (cfg_http_body or {}).get("ok") is True
                    and (q.get("max") is not None or cors.get("origins") is not None)
                    and (cfg_http_body or {}).get("webhooks", {}).get("hasUrl") is True
                    and (cfg_http_body or {}).get("webhooks", {}).get("hasSecret") is True
                    and cors.get("origins") == ["http://localhost:3000"]
                    and cfg_http_hdrs.get("x-request-id") == "smoke-config-rid"
                    and cfg_http_safe.get("ok") is True
                    and all(
                        n not in cfg_http_blob
                        for n in (
                            "http_url_token_must_not_leak",
                            "http_whsec_must_not_leak",
                            "whsec_must_not_leak",
                            "planted_url_token",
                            "Authorization",
                            "webhookUrl",
                            "webhookSecret",
                        )
                    )
                )
            finally:
                try:
                    cfg_server.shutdown()
                except Exception:
                    pass
                cfg_server.server_close()
        if not cfg_http_ok:
            print(
                "smoke failed GET /v1/config HTTP",
                file=sys.stderr,
            )
            return 1


        cases_http_ok = False
        with tempfile.TemporaryDirectory() as cases_http_td:
            cases_runs = Path(cases_http_td) / "runs"
            from agent_ci.serve import start_background as _start_bg
            cases_server, _cases_thread = _start_bg(
                host="127.0.0.1",
                port=0,
                runs_dir=cases_runs,
                root=Path(__file__).resolve().parents[2],
                rate_limit=0,
            )
            try:
                host, port = cases_server.server_address[:2]
                base = f"http://{host}:{port}"
                import time as _cases_time
                import urllib.error
                import urllib.request
                for _ in range(50):
                    try:
                        with urllib.request.urlopen(base + "/health") as resp:
                            if resp.status == 200:
                                break
                    except urllib.error.URLError:
                        _cases_time.sleep(0.02)
                else:
                    print("smoke failed cases serve did not listen", file=sys.stderr)
                    return 1
                miss_status = 0
                miss_body = {}
                try:
                    urllib.request.urlopen(base + "/v1/runs/deadbeefdead/cases")
                except urllib.error.HTTPError as e:
                    miss_status = e.code
                    miss_body = json.loads(e.read().decode("utf-8"))
                demo_rec = _execute_run(
                    {"suite": "fixtures/demo"},
                    runs_dir=cases_runs,
                    root=Path(__file__).resolve().parents[2],
                )
                rid = str(demo_rec.get("runId") or "")
                req = urllib.request.Request(
                    base + "/v1/runs/" + rid + "/cases",
                    headers={"X-Request-Id": "smoke-cases-rid"},
                )
                with urllib.request.urlopen(req) as resp:
                    http_status = resp.status
                    http_hdrs = {str(k).lower(): v for k, v in resp.headers.items()}
                    http_body = json.loads(resp.read().decode("utf-8"))
                names = [c.get("name") for c in (http_body.get("cases") or [])]
                http_blob = json.dumps(http_body, ensure_ascii=False)
                suite_req = urllib.request.Request(
                    base + "/v1/suites/demo",
                    headers={"X-Request-Id": "smoke-suite-rid"},
                )
                with urllib.request.urlopen(suite_req) as resp:
                    suite_http_status = resp.status
                    suite_http_hdrs = {str(k).lower(): v for k, v in resp.headers.items()}
                    suite_http_body = json.loads(resp.read().decode("utf-8"))
                suite_http_names = [c.get("name") for c in (suite_http_body.get("cases") or [])]
                suite_http_blob = json.dumps(suite_http_body, ensure_ascii=False)
                suite_miss_status = 0
                suite_miss_body = {}
                try:
                    urllib.request.urlopen(base + "/v1/suites/no-such-suite-xyz")
                except urllib.error.HTTPError as e:
                    suite_miss_status = e.code
                    suite_miss_body = json.loads(e.read().decode("utf-8"))
                cases_http_ok = (
                    miss_status == 404
                    and miss_body.get("error") == "run_not_found"
                    and miss_body.get("ok") is False
                    and http_status == 200
                    and http_body.get("ok") is True
                    and http_body.get("runId") == rid
                    and int(http_body.get("count") or 0) >= 1
                    and "france-capital" in names
                    and http_hdrs.get("x-request-id") == "smoke-cases-rid"
                    and "SECRET_PROMPT" not in http_blob
                    and suite_http_status == 200
                    and suite_http_body.get("ok") is True
                    and suite_http_body.get("id") == "demo"
                    and "france-capital" in suite_http_names
                    and suite_http_hdrs.get("x-request-id") == "smoke-suite-rid"
                    and "prompt" not in suite_http_blob
                    and "trajectory" not in suite_http_blob
                    and "SECRET_PROMPT" not in suite_http_blob
                    and suite_miss_status == 404
                    and suite_miss_body.get("error") == "suite_not_found"
                    and suite_miss_body.get("ok") is False
                )
            finally:
                try:
                    cases_server.shutdown()
                except Exception:
                    pass
                cases_server.server_close()
        if not cases_http_ok:
            print("smoke failed GET /v1/runs/{id}/cases HTTP", file=sys.stderr)
            return 1


        from agent_ci.promptfoo import cases_from_promptfoo as _pf_cases
        _pf_root = Path(__file__).resolve().parents[2]
        _pf_good = _pf_root / "fixtures" / "promptfoo" / "good.json"
        _pf_bad = _pf_root / "fixtures" / "promptfoo" / "bad.json"
        if not _pf_good.is_file() or not _pf_bad.is_file():
            print("smoke failed promptfoo fixtures missing", file=sys.stderr)
            return 1
        good_cases = load_promptfoo(_pf_good)
        if len(good_cases) != 2 or not all(c.passed for c in good_cases):
            print("smoke failed promptfoo good fixture cases", good_cases, file=sys.stderr)
            return 1
        names = {c.name for c in good_cases}
        if "france-capital" not in names or "math-2plus2" not in names:
            print("smoke failed promptfoo good names", names, file=sys.stderr)
            return 1
        outputs_shape = {
            "version": 3,
            "results": {
                "outputs": [
                    {"pass": True, "score": 1.0, "description": "ok-out"},
                    {
                        "pass": False,
                        "score": 0.0,
                        "description": "bad-out",
                        "gradingResult": {"pass": False, "score": 0.0, "reason": "got & <fail>"},
                    },
                ]
            },
        }
        out_cases = _pf_cases(outputs_shape)
        if len(out_cases) != 2 or (not out_cases[0].passed) or out_cases[1].passed:
            print("smoke failed promptfoo outputs[] shape", out_cases, file=sys.stderr)
            return 1
        if out_cases[1].actual != "got & <fail>":
            print("smoke failed promptfoo reason", out_cases[1].actual, file=sys.stderr)
            return 1
        try:
            _pf_cases({"not": "promptfoo"})
            print("smoke failed promptfoo invalid shape accepted", file=sys.stderr)
            return 1
        except ValueError:
            pass
        empty_cases = _pf_cases({"version": 3, "results": [], "stats": {"successes": 0, "failures": 0, "errors": 0}})
        if empty_cases != []:
            print("smoke failed promptfoo empty summary", empty_cases, file=sys.stderr)
            return 1
        with _gate_tmp.TemporaryDirectory() as _ptd:
            jp = Path(_ptd) / "good.xml"
            tp = Path(_ptd) / "good.tap"
            code, out, _err = _run_cli(
                [
                    "from-promptfoo",
                    "--in",
                    str(_pf_good),
                    "--junit",
                    str(jp),
                    "--tap",
                    str(tp),
                    "--fail-under",
                    "80",
                ]
            )
            if code != 0 or not jp.is_file() or not tp.is_file():
                print(
                    f"smoke failed from-promptfoo good code={code} out={out!r} err={_err!r}",
                    file=sys.stderr,
                )
                return 1
            gxml = jp.read_text(encoding="utf-8")
            gtap = tp.read_text(encoding="utf-8")
            if "<testsuite" not in gxml or 'failures="0"' not in gxml or "france-capital" not in gxml:
                print("smoke failed from-promptfoo good junit", gxml, file=sys.stderr)
                return 1
            if "TAP version 13" not in gtap or "ok " not in gtap:
                print("smoke failed from-promptfoo good tap", gtap, file=sys.stderr)
                return 1
            bj = Path(_ptd) / "bad.xml"
            code, out, _err = _run_cli(
                [
                    "from-promptfoo",
                    "--in",
                    str(_pf_bad),
                    "--junit",
                    str(bj),
                    "--fail-under",
                    "80",
                    "--format",
                    "junit",
                ]
            )
            if code != 1 or not bj.is_file():
                print(
                    f"smoke failed from-promptfoo bad code={code} out={out!r} err={_err!r}",
                    file=sys.stderr,
                )
                return 1
            bxml = bj.read_text(encoding="utf-8")
            if "<failure" not in bxml or "&amp;" not in bxml or "&lt;" not in bxml:
                print("smoke failed from-promptfoo bad junit escape", bxml, file=sys.stderr)
                return 1
            if "got & <fail>" in bxml:
                print("smoke failed from-promptfoo unescaped", bxml, file=sys.stderr)
                return 1
            code, out, _err = _run_cli(
                ["from-promptfoo", "--in", str(Path(_ptd) / "missing.json")]
            )
            if code != 2:
                print(f"smoke failed from-promptfoo missing code={code}", file=sys.stderr)
                return 1

        print(
            f"agent-ci {__version__} smoke OK — {len(results)} cases passed + cors+requestId+openapi+metrics+webhook+hmac+retry+watch+shutdown+accessLog+junit+tap+md+html+gha+rateLimit+qualityGate+runsMax+runDiff+runDiffMd+runDiffHtml+config+runCases+suiteDetail+promptfoo"
        )
        return 0

    if args.cmd == "record":
        traj = run_mock_agent(args.prompt, seed=args.seed)
        out = Path(args.out)
        write_cassette(out, args.name, args.prompt, traj)
        print(json.dumps({"wrote": str(out), "trajectory": traj}, indent=2))
        return 0

    if args.cmd == "demo":
        results = run_suite(DEMO_CASES, seed=42)
        for r in results:
            status = "PASS" if r.passed else "FAIL"
            print(f"[{status}] {r.name}: expected={r.expected!r} actual={r.actual!r}")
        if args.junit:
            print(to_junit(results), end="")
        return 0 if all(r.passed for r in results) else 1

    if args.cmd == "import-suite":
        src = Path(args.src)
        dst = Path(args.dst)
        summary = import_suite(src, dst)
        print(json.dumps(summary, indent=2))
        return 0

    if args.cmd == "diff":
        from_path = Path(args.from_path)
        to_path = Path(args.to_path)
        if not from_path.is_file():
            print(f"run not found: {from_path}", file=sys.stderr)
            return 2
        if not to_path.is_file():
            print(f"run not found: {to_path}", file=sys.stderr)
            return 2
        try:
            from_run = json.loads(from_path.read_text(encoding="utf-8"))
            to_run = json.loads(to_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"invalid run JSON: {e}", file=sys.stderr)
            return 2
        if not isinstance(from_run, dict) or not isinstance(to_run, dict):
            print("run JSON must be an object", file=sys.stderr)
            return 2
        for rec, label in ((from_run, from_path), (to_run, to_path)):
            status = rec.get("status")
            if status is not None and not is_completed_status(status):
                print(
                    f"run_not_done: {rec.get('runId') or label} status={status}",
                    file=sys.stderr,
                )
                return 2
        payload = diff_runs(from_run, to_run)
        fmt = getattr(args, "format", "json")
        if fmt == "md":
            print(diff_runs_to_md(payload), end="")
        elif fmt == "html":
            print(diff_runs_to_html(payload), end="")
        else:
            print(json.dumps(payload, indent=2))
        return 0

    if args.cmd == "serve":
        from agent_ci.serve import resolve_runs_max, serve_forever

        root = Path(__file__).resolve().parents[2]
        if args.concurrency < 1:
            print("--concurrency must be >= 1", file=sys.stderr)
            return 2
        if args.max_queue < 0:
            print("--max-queue must be >= 0", file=sys.stderr)
            return 2
        cors_origins = resolve_cors_origins(args.cors_origins)
        webhook_url = resolve_webhook_url(args.webhook_url)
        webhook_secret = resolve_webhook_secret(args.webhook_secret)
        serve_forever(
            host=args.host,
            port=args.port,
            runs_dir=Path(args.runs_dir),
            root=root,
            require_key=args.require_key,
            concurrency=args.concurrency,
            max_queue=args.max_queue,
            cors_origins=cors_origins,
            webhook_url=webhook_url,
            webhook_secret=webhook_secret,
            watch=bool(getattr(args, "watch", False)),
            drain_ms=getattr(args, "drain_ms", None),
            log_json=resolve_log_json(getattr(args, "log_json", None)),
            rate_limit=resolve_rate_limit(getattr(args, "rate_limit", None)),
            runs_max=resolve_runs_max(getattr(args, "runs_max", None)),
        )
        return 0

    if args.cmd == "report-check":
        suite = _resolve_suite(args.suite)
        if suite.is_dir():
            results = run_cassette_suite(suite, seed=args.seed)
            suite_name = suite.name
        else:
            if args.suite in ("demo", "fixtures/demo") and not suite.exists():
                results = run_suite(DEMO_CASES, seed=args.seed)
                suite_name = "demo"
            else:
                print(f"suite not found: {suite}", file=sys.stderr)
                return 2
        payload = build_check_run_payload(
            results,
            name=args.name,
            suite_name=suite_name,
            head_sha=args.head_sha,
        )
        write_check_run_payload(args.out, payload)
        print(f"wrote check-run payload -> {args.out}")
        print(
            json.dumps(
                {
                    "name": payload["name"],
                    "conclusion": payload["conclusion"],
                    "summary": payload["output"]["summary"],
                    "out": args.out,
                },
                indent=2,
            )
        )
        if args.post_url:
            code, body = post_check_run_payload(args.post_url, payload)
            print(f"posted to {args.post_url} -> HTTP {code}")
            if body:
                print(body)
            if code >= 400:
                return 1
        # Exit non-zero when suite failed (CI-friendly), even if payload written.
        return 0 if all(r.passed for r in results) else 1

    if args.cmd == "run":
        suite = _resolve_suite(args.suite)
        if suite.is_dir():
            results = run_cassette_suite(suite, seed=args.seed)
            suite_name = suite.name
        else:
            if args.suite in ("demo", "fixtures/demo") and not suite.exists():
                results = run_suite(DEMO_CASES, seed=args.seed)
                suite_name = "demo"
            else:
                print(f"suite not found: {suite}", file=sys.stderr)
                return 2
        score = suite_score(results)
        gate = quality_gate(score, getattr(args, "fail_under", None))
        xml = to_junit(results, suite_name=suite_name, gate=gate)
        _write_junit(args.junit, results, suite_name, gate=gate)
        fmt = getattr(args, "format", "text")
        if fmt == "junit":
            print(xml, end="")
        elif fmt == "tap":
            print(to_tap(results, suite_name=suite_name, gate=gate), end="")
        elif fmt == "md":
            print(to_md(results, suite_name=suite_name, gate=gate), end="")
        elif fmt == "html":
            print(to_html(results, suite_name=suite_name, gate=gate), end="")
        elif fmt in ("gha", "annotations"):
            print(to_gha(results, suite_name=suite_name, gate=gate, score=score), end="")
        else:
            for r in results:
                status = "PASS" if r.passed else "FAIL"
                print(f"[{status}] {r.name} score={r.score}")
                if not r.passed:
                    print(f"  {r.actual}")
            print(f"score={score}")

        suite_ok = all(r.passed for r in results)
        exit_code = 0 if suite_ok else 1
        if gate is not None and not gate.get("passed"):
            print(
                f"quality gate failed: score={score} < fail-under={gate.get('failUnder')}",
                file=sys.stderr,
            )
            exit_code = 1

        if args.save_baseline:
            if suite_ok:
                save_baseline(Path(args.save_baseline), results, suite=suite_name)
                print(f"saved baseline -> {args.save_baseline}")
            else:
                print("skip --save-baseline (suite not fully passing)", file=sys.stderr)

        if args.diff_baseline:
            baseline = load_baseline(Path(args.diff_baseline))
            ok, report = diff_baseline(baseline, results)
            print("\n".join(report))
            if not ok:
                exit_code = 1

        return exit_code

    if args.cmd == "from-promptfoo":
        src = _resolve_suite(args.input_path)
        if not src.is_file():
            print(f"promptfoo results not found: {src}", file=sys.stderr)
            return 2
        try:
            results = load_promptfoo(src)
        except ValueError as e:
            print(f"invalid promptfoo results: {e}", file=sys.stderr)
            return 2
        suite_name = getattr(args, "suite_name", None) or "promptfoo"
        score = suite_score(results)
        gate = quality_gate(score, getattr(args, "fail_under", None))
        xml = to_junit(results, suite_name=suite_name, gate=gate)
        _write_junit(args.junit, results, suite_name, gate=gate)
        _write_tap(getattr(args, "tap", None), results, suite_name, gate=gate)
        fmt = getattr(args, "format", "text")
        if fmt == "junit":
            print(xml, end="")
        elif fmt == "tap":
            print(to_tap(results, suite_name=suite_name, gate=gate), end="")
        else:
            for r in results:
                status = "PASS" if r.passed else "FAIL"
                print(f"[{status}] {r.name} score={r.score}")
                if not r.passed:
                    print(f"  {r.actual}")
            print(f"score={score}")
        suite_ok = all(r.passed for r in results)
        exit_code = 0 if suite_ok else 1
        if gate is not None and not gate.get("passed"):
            print(
                f"quality gate failed: score={score} < fail-under={gate.get('failUnder')}",
                file=sys.stderr,
            )
            exit_code = 1
        return exit_code

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
