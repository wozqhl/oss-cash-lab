"""Deterministic fixture-driven eval runner (cassette trajectories)."""
from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_ci.cassette import compare_trajectories, load_cassette
from agent_ci.mock_agent import run_mock_agent


@dataclass
class CaseResult:
    name: str
    passed: bool
    expected: str
    actual: str
    score: float = 1.0
    trajectory: list[dict[str, Any]] | None = None


def mock_llm(prompt: str, seed: int = 42) -> str:
    """Backward-compatible helper used by smoke."""
    traj = run_mock_agent(prompt, seed=seed)
    for step in reversed(traj):
        if step.get("tool") == "answer":
            return str(step.get("arguments", {}).get("text", ""))
    return json.dumps(traj)


def run_suite(cases: list[dict[str, Any]], seed: int = 42) -> list[CaseResult]:
    """Legacy prompt/expect suite used by smoke."""
    results: list[CaseResult] = []
    for case in cases:
        traj = run_mock_agent(case["prompt"], seed=seed)
        actual = mock_llm(case["prompt"], seed=seed)
        expected = str(case["expect"])
        passed = actual.strip() == expected.strip()
        results.append(
            CaseResult(
                name=case.get("name", "unnamed"),
                passed=passed,
                expected=expected,
                actual=actual,
                score=1.0 if passed else 0.0,
                trajectory=traj,
            )
        )
    return results


def run_cassette_suite(suite_dir: Path, seed: int = 42) -> list[CaseResult]:
    files = sorted(suite_dir.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"no cassette json in {suite_dir}")
    results: list[CaseResult] = []
    for f in files:
        cass = load_cassette(f)
        actual = run_mock_agent(cass.get("prompt", ""), seed=seed)
        ok, msg = compare_trajectories(cass["trajectory"], actual)
        results.append(
            CaseResult(
                name=str(cass.get("name", f.stem)),
                passed=ok,
                expected=json.dumps(cass["trajectory"], sort_keys=True),
                actual=json.dumps(actual, sort_keys=True) if ok else msg,
                score=1.0 if ok else 0.0,
                trajectory=actual,
            )
        )
    return results


def _xml_escape(text: Any) -> str:
    """Escape XML attribute/text content (`& < > "`)."""
    return html.escape("" if text is None else str(text), quote=True)


def _format_time(t: Any) -> str:
    try:
        n = float(t)
    except (TypeError, ValueError):
        n = 0.0
    if n < 0:
        n = 0.0
    if n == int(n):
        return str(int(n))
    return f"{n:.3f}"


def _parse_iso_ts(ts: Any) -> float | None:
    if not ts:
        return None
    s = str(ts).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s).timestamp()
    except (TypeError, ValueError):
        return None


GATE_ERROR = "below_threshold"
COMPLETED_STATUSES = frozenset({"done", "error", "failed"})


def pass_rate_score(passed: int, total: int) -> float:
    """Suite score 0–100 = passed/total * 100. total=0 → 0."""
    t = int(total)
    if t <= 0:
        return 0.0
    return 100.0 * float(int(passed)) / float(t)


def suite_score(results: list[CaseResult] | None) -> float:
    """Pass-rate score from CaseResult list (0 if empty)."""
    rows = results or []
    total = len(rows)
    passed = sum(1 for r in rows if r.passed)
    return pass_rate_score(passed, total)


def parse_fail_under(raw: Any) -> float | None:
    """None/omit → no gate. Finite number otherwise. Rejects bool/str."""
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError("failUnder must be a number")
    n = float(raw)
    if n != n or n in (float("inf"), float("-inf")):
        raise ValueError("failUnder must be a finite number")
    return n


def quality_gate(score: float, fail_under: float | None) -> dict[str, Any] | None:
    """`{failUnder, passed}` when a threshold is set. passed = score >= failUnder."""
    if fail_under is None:
        return None
    return {"failUnder": fail_under, "passed": not (float(score) < float(fail_under))}


def gate_failed(gate: dict[str, Any] | None) -> bool:
    return isinstance(gate, dict) and not gate.get("passed")


def is_completed_status(status: Any) -> bool:
    return str(status or "") in COMPLETED_STATUSES


def run_duration_seconds(record: dict[str, Any] | None) -> float:
    """Elapsed seconds from startedAt/createdAt → finishedAt (0 if missing)."""
    if not isinstance(record, dict):
        return 0.0
    start = _parse_iso_ts(record.get("startedAt") or record.get("createdAt"))
    end = _parse_iso_ts(record.get("finishedAt"))
    if start is None or end is None:
        return 0.0
    d = end - start
    return d if d >= 0 else 0.0


def _with_gate_cases(
    results: list[CaseResult],
    gate: dict[str, Any] | None,
) -> list[CaseResult]:
    """If the quality gate failed and every case passed, add a synthetic failure."""
    cases = list(results)
    if gate_failed(gate) and all(r.passed for r in cases):
        cases.append(
            CaseResult(
                name=GATE_ERROR,
                passed=False,
                expected="",
                actual=GATE_ERROR,
                score=0.0,
            )
        )
    return cases


def to_junit(
    results: list[CaseResult],
    suite_name: str = "agent-ci",
    *,
    errors: int = 0,
    time_s: float | int | str = 0,
    gate: dict[str, Any] | None = None,
) -> str:
    """JUnit-ish XML for GitHub Actions / Jenkins / GitLab.

    Single `<testsuite>` (empty list → tests="0"). Failure text is escaped.
    Quality-gate fail (`gate.passed=false`) → failures>=1; if all cases passed
    but score is still below the threshold, a synthetic `below_threshold` case
    is added (`<failure message="below_threshold">`).
    """
    cases = _with_gate_cases(results, gate)
    failures = sum(1 for r in cases if not r.passed)
    name = _xml_escape(suite_name)
    t = _format_time(time_s)
    err_n = max(int(errors), 0)
    lines = [
        f'<testsuite name="{name}" tests="{len(cases)}" failures="{failures}" errors="{err_n}" time="{t}">',
    ]
    classname = name
    for r in cases:
        cname = _xml_escape(r.name)
        rt = _format_time(getattr(r, "time", 0) or 0)
        if r.passed:
            lines.append(
                f'  <testcase classname="{classname}" name="{cname}" time="{rt}" />'
            )
            continue
        if str(r.actual) == GATE_ERROR and not r.expected:
            msg = GATE_ERROR
            body = GATE_ERROR
        else:
            msg = f"expected {r.expected} got {r.actual}"
            body = r.actual if r.actual not in (None, "") else msg
        lines.append(
            f'  <testcase classname="{classname}" name="{cname}" time="{rt}">'
        )
        lines.append(
            f'    <failure message="{_xml_escape(msg)}">{_xml_escape(body)}</failure>'
        )
        lines.append("  </testcase>")
    lines.append("</testsuite>")
    return "\n".join(lines) + "\n"


def run_to_junit(record: dict[str, Any] | None) -> str:
    """Build JUnit XML from a stored run record (GET /v1/runs/{id} payload).

    Reuses `summary.cases` `{name,passed,score}` and `status`/`error`/`detail`.
    Does not invent a second result schema. Empty/missing cases → tests="0"
    unless `status=error` (one `<error>` testcase).
    """
    rec = record if isinstance(record, dict) else {}
    suite = str(rec.get("suite") or "agent-ci")
    status = str(rec.get("status") or "")
    time_s = run_duration_seconds(rec)
    if status == "error":
        name = _xml_escape(suite)
        t = _format_time(time_s)
        err = rec.get("error") or "error"
        detail = rec.get("detail") if rec.get("detail") not in (None, "") else err
        case_name = _xml_escape(rec.get("runId") or "run")
        return (
            f'<testsuite name="{name}" tests="1" failures="0" errors="1" time="{t}">\n'
            f'  <testcase classname="{name}" name="{case_name}" time="{t}">\n'
            f'    <error message="{_xml_escape(err)}">{_xml_escape(detail)}</error>\n'
            f"  </testcase>\n"
            f"</testsuite>\n"
        )
    summary = rec.get("summary") if isinstance(rec.get("summary"), dict) else {}
    raw_cases = summary.get("cases") or []
    results: list[CaseResult] = []
    if isinstance(raw_cases, list):
        for c in raw_cases:
            if not isinstance(c, dict):
                continue
            passed = bool(c.get("passed"))
            results.append(
                CaseResult(
                    name=str(c.get("name") or "unnamed"),
                    passed=passed,
                    expected="",
                    actual="" if passed else "failed",
                    score=float(c.get("score") if c.get("score") is not None else (1.0 if passed else 0.0)),
                )
            )
    gate = rec.get("gate") if isinstance(rec.get("gate"), dict) else None
    return to_junit(results, suite_name=suite, time_s=time_s, gate=gate)


def runs_to_junit(
    records: list[dict[str, Any]] | None,
    suite_name: str = "agent-ci",
) -> str:
    """JUnit for completed runs (`done`|`failed`|`error`). Empty → valid suite tests="0"."""
    completed: list[dict[str, Any]] = []
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        if is_completed_status(rec.get("status")):
            completed.append(rec)
    if not completed:
        return to_junit([], suite_name=suite_name)
    if len(completed) == 1:
        return run_to_junit(completed[0])
    lines = ["<testsuites>"]
    for rec in completed:
        inner = run_to_junit(rec).rstrip("\n")
        for line in inner.splitlines():
            lines.append("  " + line)
    lines.append("</testsuites>")
    return "\n".join(lines) + "\n"


def _tap_escape(text: Any) -> str:
    """Keep TAP descriptions from becoming comments (`#`) or wrapping."""
    s = "" if text is None else str(text)
    s = s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return s.replace("#", "\\#")


def _tap_diagnostics(text: Any) -> list[str]:
    """TAP diagnostic comments (`# …`). Empty → no lines."""
    s = "" if text is None else str(text)
    if s == "":
        return []
    return ["# " + raw.replace("\r", "") for raw in s.splitlines()]


def _emit_tap(cases: list[CaseResult], suite_name: str) -> str:
    """TAP13 stream: version, plan `1..N` (empty → `1..0`), `ok` / `not ok`."""
    rows = list(cases)
    lines = ["TAP version 13", f"1..{len(rows)}"]
    for i, r in enumerate(rows, start=1):
        label = f"{suite_name} {r.name}".strip() if suite_name else str(r.name)
        desc = _tap_escape(label)
        if r.passed:
            lines.append(f"ok {i} - {desc}")
            continue
        lines.append(f"not ok {i} - {desc}")
        if str(r.actual) == GATE_ERROR and not r.expected:
            msg = GATE_ERROR
        else:
            msg = r.actual if r.actual not in (None, "") else f"expected {r.expected} got {r.actual}"
        lines.extend(_tap_diagnostics(msg))
    return "\n".join(lines) + "\n"


def to_tap(
    results: list[CaseResult],
    suite_name: str = "agent-ci",
    *,
    gate: dict[str, Any] | None = None,
) -> str:
    """TAP version 13 for GitLab / Jenkins / harnesses that ingest TAP.

    Reuses CaseResult. Failures are `not ok` plus `#` diagnostics.
    `#` in names is escaped so it cannot start a comment (plan stays `1..N`).
    Quality-gate fail (`gate.passed=false`) → at least one `not ok`; if every
    case passed but score is still below the threshold, a synthetic
    `below_threshold` case is added (same as JUnit).
    Empty list → `1..0`.
    """
    return _emit_tap(_with_gate_cases(results, gate), suite_name)


def _cases_from_record(
    record: dict[str, Any] | None,
) -> tuple[str, list[CaseResult], dict[str, Any] | None]:
    """Suite name + CaseResult list + gate from a stored run record.

    `status=error` → one failing case (`error`/`detail`). Does not invent a
    second result schema (`summary.cases` `{name,passed,score}`).
    """
    rec = record if isinstance(record, dict) else {}
    suite = str(rec.get("suite") or "agent-ci")
    status = str(rec.get("status") or "")
    if status == "error":
        err = rec.get("error") or "error"
        detail = rec.get("detail") if rec.get("detail") not in (None, "") else err
        results = [
            CaseResult(
                name=str(rec.get("runId") or "run"),
                passed=False,
                expected="",
                actual=str(detail),
                score=0.0,
            )
        ]
        return suite, results, None
    summary = rec.get("summary") if isinstance(rec.get("summary"), dict) else {}
    raw_cases = summary.get("cases") or []
    results: list[CaseResult] = []
    if isinstance(raw_cases, list):
        for c in raw_cases:
            if not isinstance(c, dict):
                continue
            passed = bool(c.get("passed"))
            results.append(
                CaseResult(
                    name=str(c.get("name") or "unnamed"),
                    passed=passed,
                    expected="",
                    actual="" if passed else "failed",
                    score=float(
                        c.get("score")
                        if c.get("score") is not None
                        else (1.0 if passed else 0.0)
                    ),
                )
            )
    gate = rec.get("gate") if isinstance(rec.get("gate"), dict) else None
    return suite, results, gate


def run_to_tap(record: dict[str, Any] | None) -> str:
    """Build TAP13 from a stored run record (GET /v1/runs/{id} payload).

    Reuses `summary.cases` / `status`/`error`/`detail` / quality gate.
    Empty/missing cases → `1..0` unless `status=error` (one `not ok`).
    """
    suite, results, gate = _cases_from_record(record)
    return to_tap(results, suite_name=suite, gate=gate)


def runs_to_tap(
    records: list[dict[str, Any]] | None,
    suite_name: str = "agent-ci",
) -> str:
    """TAP13 for completed runs (`done`|`failed`|`error`). Empty → `1..0`."""
    completed: list[dict[str, Any]] = []
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        if is_completed_status(rec.get("status")):
            completed.append(rec)
    if not completed:
        return to_tap([], suite_name=suite_name)
    if len(completed) == 1:
        return run_to_tap(completed[0])
    merged: list[CaseResult] = []
    for rec in completed:
        suite, results, gate = _cases_from_record(rec)
        for r in _with_gate_cases(results, gate):
            merged.append(
                CaseResult(
                    name=f"{suite} {r.name}".strip(),
                    passed=r.passed,
                    expected=r.expected,
                    actual=r.actual,
                    score=r.score,
                    trajectory=r.trajectory,
                )
            )
    return _emit_tap(merged, "")


def _md_escape_cell(text: Any) -> str:
    """Escape `|` in Markdown table cells so names cannot split columns."""
    s = "" if text is None else str(text)
    s = s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return s.replace("|", "\\|")


def _format_score(score: Any) -> str:
    try:
        n = float(score)
    except (TypeError, ValueError):
        n = 0.0
    if n != n or n in (float("inf"), float("-inf")):
        n = 0.0
    if abs(n - round(n)) < 1e-9:
        return str(int(round(n)))
    return f"{n:.1f}"


def _md_gate_label(gate: dict[str, Any] | None) -> str:
    if not isinstance(gate, dict):
        return "none"
    return "pass" if gate.get("passed") else "fail"


def _md_status(
    results: list[CaseResult],
    gate: dict[str, Any] | None,
    status: Any = None,
) -> str:
    """`done` or `failed` (record `error` → `failed`)."""
    raw = str(status or "")
    if raw in ("failed", "error"):
        return "failed"
    if gate_failed(gate):
        return "failed"
    if any(not r.passed for r in results):
        return "failed"
    return "done"


def to_md(
    results: list[CaseResult],
    suite_name: str = "agent-ci",
    *,
    gate: dict[str, Any] | None = None,
    status: str | None = None,
    score: float | int | None = None,
    time_s: float | int | str = 0,
) -> str:
    """Markdown run report for GitHub Actions `$GITHUB_STEP_SUMMARY` / humans.

    Shape::

        # agent-ci: <suite>
        **Status:** done|failed  **Score:** 100  **Gate:** pass/fail/none
        | case | status | time |
        | --- | --- | --- |
        | name | pass/fail | 0 |

    `|` in case names is escaped. Empty list → heading + table header, no data
    rows. Quality-gate fail (`gate.passed=false`) → at least one `fail` row
    (synthetic `below_threshold` if every case passed).
    """
    cases = _with_gate_cases(results, gate)
    st = _md_status(results, gate, status)
    if score is None:
        score = suite_score(results)
    heading = str(suite_name or "agent-ci").replace("\r", " ").replace("\n", " ")
    lines = [
        f"# agent-ci: {heading}",
        f"**Status:** {st}  **Score:** {_format_score(score)}  **Gate:** {_md_gate_label(gate)}",
        "| case | status | time |",
        "| --- | --- | --- |",
    ]
    suite_t = _format_time(time_s)
    for r in cases:
        cell = _md_escape_cell(r.name)
        row_st = "pass" if r.passed else "fail"
        raw_t = getattr(r, "time", None)
        if raw_t not in (None, ""):
            rt = _format_time(raw_t)
        elif len(cases) == 1:
            rt = suite_t
        else:
            rt = "0"
        lines.append(f"| {cell} | {row_st} | {rt} |")
    return "\n".join(lines) + "\n"


def run_to_md(record: dict[str, Any] | None) -> str:
    """Build Markdown from a stored run record (GET /v1/runs/{id} payload).

    Reuses `summary.cases` / `status`/`error`/`detail` / quality gate / `score`.
    Empty/missing cases → heading + no data rows unless `status=error`.
    """
    rec = record if isinstance(record, dict) else {}
    suite, results, gate = _cases_from_record(rec)
    score = rec.get("score")
    if score is None:
        score = suite_score(results)
    time_s = run_duration_seconds(rec)
    return to_md(
        results,
        suite_name=suite,
        gate=gate,
        status=str(rec.get("status") or ""),
        score=score,
        time_s=time_s,
    )


def runs_to_md(
    records: list[dict[str, Any]] | None,
    suite_name: str = "agent-ci",
) -> str:
    """Markdown for completed runs (`done`|`failed`|`error`). Empty → heading + no rows."""
    completed: list[dict[str, Any]] = []
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        if is_completed_status(rec.get("status")):
            completed.append(rec)
    if not completed:
        return to_md([], suite_name=suite_name)
    if len(completed) == 1:
        return run_to_md(completed[0])
    parts = [run_to_md(rec).rstrip("\n") for rec in completed]
    return "\n\n".join(parts) + "\n"


def _gha_escape_data(text: Any) -> str:
    """Escape `%`, CR, LF in GitHub Actions workflow-command data."""
    s = "" if text is None else str(text)
    return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _gha_escape_property(text: Any) -> str:
    """Escape GHA property values (`:`, `,`, plus data escapes)."""
    return _gha_escape_data(text).replace(":", "%3A").replace(",", "%2C")


def _gha_error_line(title: str, message: str) -> str:
    return (
        f"::error title={_gha_escape_property(title)}::{_gha_escape_data(message)}"
    )


def _case_fail_message(r: CaseResult) -> str:
    if str(r.actual) == GATE_ERROR and not r.expected:
        return GATE_ERROR
    if r.actual not in (None, ""):
        return str(r.actual)
    if r.expected not in (None, ""):
        return f"expected {r.expected} got {r.actual}"
    return "failed"


def to_gha(
    results: list[CaseResult],
    suite_name: str = "agent-ci",
    *,
    gate: dict[str, Any] | None = None,
    score: float | int | None = None,
) -> str:
    """GitHub Actions workflow commands for log annotations.

    Fail/error → `::error title=<suite>/<case>::<message>`.
    Quality-gate fail → `::error title=gate::score N < failUnder M`.
    Pass-only / empty → no output (no `::error`). Does not require GitHub.
    Same CaseResult / gate as JUnit/TAP/Markdown; does not use the synthetic
    `below_threshold` case (dedicated `title=gate` line instead).
    """
    lines: list[str] = []
    suite = str(suite_name or "agent-ci")
    for r in results or []:
        if r.passed:
            continue
        title = f"{suite}/{r.name}"
        lines.append(_gha_error_line(title, _case_fail_message(r)))
    if gate_failed(gate):
        if score is None:
            score = suite_score(results)
        fail_under = (gate or {}).get("failUnder")
        msg = f"score {_format_score(score)} < failUnder {_format_score(fail_under)}"
        lines.append(_gha_error_line("gate", msg))
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def run_to_gha(record: dict[str, Any] | None) -> str:
    """Build GHA workflow commands from a stored run record.

    Reuses `summary.cases` / `status`/`error`/`detail` / quality gate / `score`.
    Empty/missing cases → empty string unless `status=error` or gate fail.
    """
    rec = record if isinstance(record, dict) else {}
    suite, results, gate = _cases_from_record(rec)
    score = rec.get("score")
    if score is None:
        score = suite_score(results)
    return to_gha(results, suite_name=suite, gate=gate, score=score)


def runs_to_gha(
    records: list[dict[str, Any]] | None,
    suite_name: str = "agent-ci",
) -> str:
    """GHA annotations for completed runs (`done`|`failed`|`error`). Empty → empty."""
    completed: list[dict[str, Any]] = []
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        if is_completed_status(rec.get("status")):
            completed.append(rec)
    if not completed:
        return to_gha([], suite_name=suite_name)
    if len(completed) == 1:
        return run_to_gha(completed[0])
    parts: list[str] = []
    for rec in completed:
        chunk = run_to_gha(rec).rstrip("\n")
        if chunk:
            parts.append(chunk)
    if not parts:
        return ""
    return "\n".join(parts) + "\n"


def _html_escape(text: Any) -> str:
    """Escape HTML text/attributes (`& < > "`)."""
    return html.escape("" if text is None else str(text), quote=True)


_HTML_STYLE = (
    "body{font-family:ui-sans-serif,system-ui,sans-serif;margin:2rem;color:#111}"
    "h1{font-size:1.25rem}"
    "table{border-collapse:collapse;margin:1rem 0;min-width:28rem}"
    "th,td{border:1px solid #ddd;padding:.4rem .6rem;text-align:left}"
    "th{background:#f5f5f5}"
    ".fail{color:#b00020;font-weight:700}"
    ".pass{color:#0a7a28}"
    ".meta{color:#555;font-size:.9rem}"
)


def _html_document(title: str, body: str) -> str:
    t = _html_escape(title)
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8"/>\n'
        f"<title>{t}</title>\n"
        f"<style>\n{_HTML_STYLE}\n</style>\n"
        "</head>\n"
        "<body>\n"
        f"{body}"
        "</body>\n"
        "</html>\n"
    )


def _html_gate_meta(gate: dict[str, Any] | None) -> str:
    label = _md_gate_label(gate)
    if not isinstance(gate, dict):
        return f"Gate: {label}"
    fu = gate.get("failUnder")
    if fu is None:
        return f"Gate: {label}"
    return f"Gate: {label}  failUnder: {_format_score(fu)}"


def _html_section(
    results: list[CaseResult],
    suite_name: str = "agent-ci",
    *,
    gate: dict[str, Any] | None = None,
    status: str | None = None,
    score: float | int | None = None,
    time_s: float | int | str = 0,
) -> str:
    """Inner HTML (heading + meta + table). Empty → heading + “no runs” + header."""
    cases = _with_gate_cases(results, gate)
    st = _md_status(results, gate, status)
    if score is None:
        score = suite_score(results)
    heading = str(suite_name or "agent-ci").replace("\r", " ").replace("\n", " ")
    heading_esc = _html_escape(heading)
    suite_t = _format_time(time_s)
    rows: list[str] = []
    for r in cases:
        row_st = "pass" if r.passed else "fail"
        cls = "pass" if r.passed else "fail"
        raw_t = getattr(r, "time", None)
        if raw_t not in (None, ""):
            rt = _format_time(raw_t)
        elif len(cases) == 1:
            rt = suite_t
        else:
            rt = "0"
        msg = "" if r.passed else _case_fail_message(r)
        rows.append(
            f'<tr class="{cls}">'
            f"<td>{heading_esc}</td>"
            f"<td>{_html_escape(r.name)}</td>"
            f'<td class="{cls}">{row_st}</td>'
            f"<td>{_html_escape(rt)}</td>"
            f"<td>{_html_escape(msg)}</td>"
            "</tr>"
        )
    empty_note = "<p>no runs</p>\n" if not cases else ""
    tbody = ("\n".join(rows) + "\n") if rows else ""
    return (
        f"<h1>agent-ci: {heading_esc}</h1>\n"
        f'<p class="meta">Status: {_html_escape(st)}  '
        f"Score: {_html_escape(_format_score(score))}  "
        f"{_html_escape(_html_gate_meta(gate))}</p>\n"
        f"{empty_note}"
        "<table>\n"
        "<thead><tr><th>suite</th><th>case</th><th>status</th><th>time</th><th>message</th></tr></thead>\n"
        f"<tbody>\n{tbody}</tbody>\n"
        "</table>\n"
    )


def to_html(
    results: list[CaseResult],
    suite_name: str = "agent-ci",
    *,
    gate: dict[str, Any] | None = None,
    status: str | None = None,
    score: float | int | None = None,
    time_s: float | int | str = 0,
) -> str:
    """Self-contained HTML run report for the local 5-min demo.

    No CDN / external CSS/JS. Names escaped (`& < > "`). Fail rows use red
    status text (inline CSS). Empty list → heading + “no runs” + table header.
    Quality-gate fail → a `fail` row (synthetic `below_threshold` if every
    case passed). Score and fail-under gate shown when present.
    """
    heading = str(suite_name or "agent-ci").replace("\r", " ").replace("\n", " ")
    body = _html_section(
        results,
        suite_name=suite_name,
        gate=gate,
        status=status,
        score=score,
        time_s=time_s,
    )
    return _html_document(f"agent-ci: {heading}", body)


def run_to_html(record: dict[str, Any] | None) -> str:
    """Build HTML from a stored run record (GET /v1/runs/{id} payload).

    Reuses `summary.cases` / `status`/`error`/`detail` / quality gate / `score`.
    Empty/missing cases → heading + “no runs” unless `status=error`.
    """
    rec = record if isinstance(record, dict) else {}
    suite, results, gate = _cases_from_record(rec)
    score = rec.get("score")
    if score is None:
        score = suite_score(results)
    time_s = run_duration_seconds(rec)
    return to_html(
        results,
        suite_name=suite,
        gate=gate,
        status=str(rec.get("status") or ""),
        score=score,
        time_s=time_s,
    )


def _html_section_from_record(record: dict[str, Any] | None) -> str:
    rec = record if isinstance(record, dict) else {}
    suite, results, gate = _cases_from_record(rec)
    score = rec.get("score")
    if score is None:
        score = suite_score(results)
    time_s = run_duration_seconds(rec)
    return _html_section(
        results,
        suite_name=suite,
        gate=gate,
        status=str(rec.get("status") or ""),
        score=score,
        time_s=time_s,
    )


def runs_to_html(
    records: list[dict[str, Any]] | None,
    suite_name: str = "agent-ci",
) -> str:
    """HTML for completed runs (`done`|`failed`|`error`). Empty → heading + no runs."""
    completed: list[dict[str, Any]] = []
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        if is_completed_status(rec.get("status")):
            completed.append(rec)
    if not completed:
        return to_html([], suite_name=suite_name)
    if len(completed) == 1:
        return run_to_html(completed[0])
    body = "\n".join(_html_section_from_record(rec) for rec in completed)
    return _html_document("agent-ci", body)
