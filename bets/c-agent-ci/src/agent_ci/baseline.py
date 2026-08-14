"""Baseline save/diff for paid-pilot packaging."""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from agent_ci.runner import CaseResult, _html_document


def score_of(result: CaseResult) -> float:
    if getattr(result, "score", None) is not None:
        return float(result.score)
    return 1.0 if result.passed else 0.0


def results_to_baseline(results: list[CaseResult], suite: str = "") -> dict[str, Any]:
    cases: dict[str, Any] = {}
    for r in results:
        traj = getattr(r, "trajectory", None)
        cases[r.name] = {
            "passed": bool(r.passed),
            "score": score_of(r),
            "trajectory": traj,
        }
    return {"version": 1, "suite": suite, "cases": cases}


def save_baseline(path: Path, results: list[CaseResult], suite: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = results_to_baseline(results, suite=suite)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_baseline(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def diff_baseline(baseline: dict[str, Any], results: list[CaseResult]) -> tuple[bool, list[str]]:
    """Return (ok, report_lines). Fails on trajectory/score regression vs baseline."""
    base_cases = baseline.get("cases") or {}
    by_name = {r.name: r for r in results}
    lines: list[str] = ["baseline diff report:"]
    ok = True

    for name, b in sorted(base_cases.items()):
        r = by_name.get(name)
        if r is None:
            ok = False
            lines.append(f"  MISSING  {name}")
            continue
        b_score = float(b.get("score", 1.0 if b.get("passed") else 0.0))
        r_score = score_of(r)
        if r_score < b_score:
            ok = False
            lines.append(f"  SCORE    {name}: {r_score} < baseline {b_score}")
        if b.get("passed") and not r.passed:
            ok = False
            lines.append(f"  FAIL     {name}: was pass, now fail")
        b_traj = b.get("trajectory")
        r_traj = getattr(r, "trajectory", None)
        if b_traj is not None and r_traj is not None and b_traj != r_traj:
            ok = False
            lines.append(f"  TRAJ     {name}: trajectory changed")
        if r.passed and b.get("passed") and r_score >= b_score and (
            b_traj is None or r_traj is None or b_traj == r_traj
        ):
            lines.append(f"  OK       {name}")

    for name in sorted(by_name):
        if name not in base_cases:
            lines.append(f"  NEW      {name}")

    if ok:
        lines.append("result: PASS (no regression)")
    else:
        lines.append("result: FAIL (regression vs baseline)")
    return ok, lines

def case_identity(suite: str, name: str) -> str:
    """Stable case key: `suite/name` (suite may be empty → just name)."""
    s = str(suite or "").strip()
    n = str(name or "").strip() or "unnamed"
    return f"{s}/{n}" if s else n


def cases_from_run(record: dict[str, Any] | None) -> dict[str, bool]:
    """Map `suite/name` → passed from a run record (`summary.cases`)."""
    rec = record if isinstance(record, dict) else {}
    suite = str(rec.get("suite") or "")
    summary = rec.get("summary") if isinstance(rec.get("summary"), dict) else {}
    rows = summary.get("cases") if isinstance(summary.get("cases"), list) else []
    out: dict[str, bool] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "")
        out[case_identity(suite, name)] = bool(row.get("passed"))
    return out


def diff_runs(from_run: dict[str, Any] | None, to_run: dict[str, Any] | None) -> dict[str, Any]:
    """Compare two completed run records by case identity (`suite/name`).

    Distinct from `diff_baseline` (trajectory/score vs a saved snapshot).
    `ok` is True when the comparison itself succeeded (not "no regressions").
    Empty both → added/removed/regressed/fixed empty, unchanged 0.
    """
    left = from_run if isinstance(from_run, dict) else {}
    right = to_run if isinstance(to_run, dict) else {}
    from_cases = cases_from_run(left)
    to_cases = cases_from_run(right)
    from_keys = set(from_cases)
    to_keys = set(to_cases)
    added = sorted(to_keys - from_keys)
    removed = sorted(from_keys - to_keys)
    common = from_keys & to_keys
    regressed = sorted(k for k in common if from_cases[k] and not to_cases[k])
    fixed = sorted(k for k in common if (not from_cases[k]) and to_cases[k])
    unchanged = sum(1 for k in common if from_cases[k] == to_cases[k])
    return {
        "ok": True,
        "from": str(left.get("runId") or ""),
        "to": str(right.get("runId") or ""),
        "added": added,
        "removed": removed,
        "regressed": regressed,
        "fixed": fixed,
        "unchanged": unchanged,
    }


def _md_escape_cell(text: Any) -> str:
    """Escape `|` in Markdown table cells so identities cannot split columns."""
    s = "" if text is None else str(text)
    s = s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return s.replace("|", "\\|")


def diff_runs_to_md(diff: dict[str, Any] | None) -> str:
    """Markdown for a `diff_runs` payload (GitHub Actions `$GITHUB_STEP_SUMMARY`).

    Shape::

        # agent-ci diff
        **from:** <id>  **to:** <id>
        **added:** N  **removed:** N  **regressed:** N  **fixed:** N  **unchanged:** N

        ## regressed
        | case |
        | --- |
        | suite/name |

    `|` in case identities is escaped. Empty added/removed/regressed/fixed →
    heading + counts + "no changes" (no tables). Non-empty buckets become GFM
    tables. Distinct from `to_md` (per-run case table).
    """
    d = diff if isinstance(diff, dict) else {}

    def _names(key: str) -> list[str]:
        raw = d.get(key) or []
        if not isinstance(raw, list):
            return []
        return [str(x) for x in raw if x is not None and str(x) != ""]

    added = _names("added")
    removed = _names("removed")
    regressed = _names("regressed")
    fixed = _names("fixed")
    try:
        unchanged = int(d.get("unchanged") or 0)
    except (TypeError, ValueError):
        unchanged = 0
    if unchanged < 0:
        unchanged = 0
    from_id = str(d.get("from") or "")
    to_id = str(d.get("to") or "")
    lines = [
        "# agent-ci diff",
        f"**from:** {from_id}  **to:** {to_id}",
        (
            f"**added:** {len(added)}  **removed:** {len(removed)}  "
            f"**regressed:** {len(regressed)}  **fixed:** {len(fixed)}  "
            f"**unchanged:** {unchanged}"
        ),
        "",
    ]
    buckets = (
        ("regressed", regressed),
        ("added", added),
        ("removed", removed),
        ("fixed", fixed),
    )
    if not any(items for _, items in buckets):
        lines.append("no changes")
        lines.append("")
        return "\n".join(lines)
    for title, items in buckets:
        if not items:
            continue
        lines.append(f"## {title}")
        lines.append("")
        lines.append("| case |")
        lines.append("| --- |")
        for name in items:
            lines.append(f"| {_md_escape_cell(name)} |")
        lines.append("")
    return "\n".join(lines)


def diff_runs_to_html(diff: dict[str, Any] | None) -> str:
    """Self-contained HTML for a `diff_runs` payload (local 5-min demo).

    Shape::

        <h1>agent-ci diff</h1>
        <p class="meta">from: <id>  to: <id></p>
        <p class="meta">added: N  removed: N  regressed: N  fixed: N  unchanged: N</p>
        <h2>regressed</h2>
        <table>…</table>

    Names escaped (`html.escape`, `& < > "`). Empty added/removed/regressed/fixed
    → heading + “no changes” (no tables). Non-empty buckets become tables.
    Regressed rows use class `fail` (red via inline CSS). No CDN. Distinct from
    `to_html` (per-run case table). JSON/`diff_runs_to_md` unchanged.
    """
    d = diff if isinstance(diff, dict) else {}

    def _names(key: str) -> list[str]:
        raw = d.get(key) or []
        if not isinstance(raw, list):
            return []
        return [str(x) for x in raw if x is not None and str(x) != ""]

    added = _names("added")
    removed = _names("removed")
    regressed = _names("regressed")
    fixed = _names("fixed")
    try:
        unchanged = int(d.get("unchanged") or 0)
    except (TypeError, ValueError):
        unchanged = 0
    if unchanged < 0:
        unchanged = 0
    from_id = html.escape(str(d.get("from") or ""), quote=True)
    to_id = html.escape(str(d.get("to") or ""), quote=True)
    parts = [
        "<h1>agent-ci diff</h1>\n",
        f'<p class="meta">from: {from_id}  to: {to_id}</p>\n',
        (
            f'<p class="meta">added: {len(added)}  removed: {len(removed)}  '
            f"regressed: {len(regressed)}  fixed: {len(fixed)}  "
            f"unchanged: {unchanged}</p>\n"
        ),
    ]
    buckets = (
        ("regressed", regressed, True),
        ("added", added, False),
        ("removed", removed, False),
        ("fixed", fixed, False),
    )
    if not any(items for _, items, _ in buckets):
        parts.append("<p>no changes</p>\n")
    else:
        for title, items, is_fail in buckets:
            if not items:
                continue
            parts.append(f"<h2>{html.escape(title, quote=True)}</h2>\n")
            parts.append("<table>\n")
            parts.append("<thead><tr><th>case</th></tr></thead>\n<tbody>\n")
            for name in items:
                cls = ' class="fail"' if is_fail else ""
                cell = html.escape(name, quote=True)
                parts.append(f"<tr{cls}><td>{cell}</td></tr>\n")
            parts.append("</tbody>\n</table>\n")
    return _html_document("agent-ci diff", "".join(parts))
