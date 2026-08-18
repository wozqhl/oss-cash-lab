"""Adapter: DeepEval-shaped JSON -> agent-ci CaseResult (then JUnit/TAP/Markdown).

Not a DeepEval replacement and not full compatibility. A consumer dumps
JSON that looks like DeepEval ``evaluate()`` / persisted TestRun output;
we map the tiny fields we actually use (test name, success/score, optional
metrics) onto the existing reporters in ``agent_ci.runner``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_ci.runner import CaseResult


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _looks_like_deepeval(data: Any) -> bool:
    if isinstance(data, list):
        return any(
            isinstance(r, dict)
            and (
                "metrics_data" in r
                or "metricsData" in r
                or ("name" in r and "success" in r)
            )
            for r in data
        )
    if not isinstance(data, dict):
        return False
    for key in (
        "test_results",
        "testResults",
        "test_cases",
        "testCases",
        "conversationalTestCases",
        "conversational_test_cases",
    ):
        if key in data:
            return True
    if data.get("testPassed") is not None or data.get("testFailed") is not None:
        return True
    if data.get("test_passed") is not None or data.get("test_failed") is not None:
        return True
    return False


def _as_metric_dicts(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [m for m in raw if isinstance(m, dict)]


def _row_metrics(row: dict[str, Any]) -> list[dict[str, Any]]:
    return _as_metric_dicts(row.get("metrics_data") or row.get("metricsData"))


def iter_eval_rows(data: Any) -> list[dict[str, Any]]:
    """Pull test-case dicts from a DeepEval-like dump.

    Supported (honest subset, not the full TestRun / conversational / trace
    schema):
    - EvaluationResult: ``{test_results: [TestResult...]}`` (also testResults)
    - Persisted TestRun: ``{testCases: [...], testPassed, testFailed}``
    - Bare list of ``{name, success, metrics_data|metricsData}`` rows
    """
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("test_results", "testResults", "test_cases", "testCases"):
        inner = data.get(key)
        if isinstance(inner, list):
            return [r for r in inner if isinstance(r, dict)]
    conv = data.get("conversationalTestCases") or data.get("conversational_test_cases")
    if isinstance(conv, list):
        return [r for r in conv if isinstance(r, dict)]
    return []


def _row_passed(row: dict[str, Any]) -> bool:
    if isinstance(row.get("success"), bool):
        return bool(row["success"])
    metrics = _row_metrics(row)
    if metrics:
        for m in metrics:
            if m.get("error") not in (None, ""):
                return False
            if isinstance(m.get("success"), bool) and not m["success"]:
                return False
        return True
    return False


def _row_name(row: dict[str, Any], index: int) -> str:
    desc = row.get("name") or row.get("id")
    if not desc:
        desc = f"case-{index}"
    name = str(desc).replace("\n", " ").strip() or f"case-{index}"
    if len(name) > 120:
        name = name[:117] + "..."
    return name


def _row_score(row: dict[str, Any], passed: bool) -> float:
    if _is_number(row.get("score")):
        return float(row["score"])
    scores = [float(m["score"]) for m in _row_metrics(row) if _is_number(m.get("score"))]
    if scores:
        return sum(scores) / len(scores)
    return 1.0 if passed else 0.0


def _row_actual(row: dict[str, Any], passed: bool) -> str:
    metrics = _row_metrics(row)
    reasons: list[str] = []
    for m in metrics:
        err = m.get("error")
        reason = m.get("reason")
        ok = m.get("success")
        if err not in (None, ""):
            reasons.append(str(err))
        elif ok is False and reason not in (None, ""):
            reasons.append(str(reason))
        elif not passed and reason not in (None, ""):
            reasons.append(str(reason))
    if reasons:
        return "; ".join(reasons)
    actual = row.get("actual_output")
    if actual is None:
        actual = row.get("actualOutput")
    if not passed:
        if actual not in (None, ""):
            return str(actual)
        return "failed"
    return str(actual) if actual not in (None, "") else ""


def _row_expected(row: dict[str, Any]) -> str:
    expected = row.get("expected_output")
    if expected is None:
        expected = row.get("expectedOutput")
    if expected not in (None, ""):
        return str(expected)
    metrics = _row_metrics(row)
    for m in metrics:
        if isinstance(m.get("success"), bool) and not m["success"]:
            name = m.get("name") or "metric"
            if _is_number(m.get("threshold")):
                return f"{name} threshold={m['threshold']}"
            return str(name)
    if metrics:
        name = metrics[0].get("name") or "metric"
        if _is_number(metrics[0].get("threshold")):
            return f"{name} threshold={metrics[0]['threshold']}"
        return str(name)
    return ""


def row_to_case(row: dict[str, Any], index: int = 1) -> CaseResult:
    passed = _row_passed(row)
    return CaseResult(
        name=_row_name(row, index),
        passed=passed,
        expected=_row_expected(row),
        actual=_row_actual(row, passed),
        score=_row_score(row, passed),
    )


def cases_from_deepeval(data: Any) -> list[CaseResult]:
    """Convert a parsed DeepEval-like object into CaseResult rows."""
    rows = iter_eval_rows(data)
    if not rows:
        if _looks_like_deepeval(data):
            return []
        raise ValueError("no deepeval test_results[] / testCases[] found")
    return [row_to_case(r, i) for i, r in enumerate(rows, start=1)]


def load_deepeval(path: str | Path) -> list[CaseResult]:
    raw = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON: {e}") from e
    return cases_from_deepeval(data)
