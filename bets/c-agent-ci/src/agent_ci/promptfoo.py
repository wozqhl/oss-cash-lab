"""Adapter: Promptfoo eval JSON -> agent-ci CaseResult (then JUnit/TAP).

Not a third eval DSL. Reads Promptfoo `eval --output` JSON (and close
shapes) and reuses the existing reporters in `agent_ci.runner`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_ci.runner import CaseResult


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _looks_like_promptfoo(data: Any) -> bool:
    if isinstance(data, list):
        return True
    if not isinstance(data, dict):
        return False
    if "evalId" in data or "outputs" in data or "shareableUrl" in data:
        return True
    if "results" in data:
        return True
    if data.get("version") is not None and ("stats" in data or "prompts" in data):
        return True
    return False


def _attach_desc(row: dict[str, Any], desc: Any) -> dict[str, Any]:
    if desc and not row.get("description"):
        return {**row, "description": desc}
    return row


def iter_eval_rows(data: Any) -> list[dict[str, Any]]:
    """Pull EvaluateResult-like dicts from Promptfoo output shapes.

    Supported (real `promptfoo eval --output` + docs variants):
    - OutputFile: `{results: {results: [EvaluateResult...]}}`  (v3)
    - EvaluateSummary: `{results: [EvaluateResult...]}`
    - Docs/latest table: `{results: {outputs: [...]}}` or `{outputs: [...]}`
    - EvaluateSummaryV2 table: `{results: {table: {body: [{outputs, description}]}}}`
    - Bare list of rows (JSONL collected / unit tests)
    """
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if not isinstance(data, dict):
        return []

    inner = data.get("results")
    if isinstance(inner, list):
        return [r for r in inner if isinstance(r, dict)]

    if isinstance(inner, dict):
        nested = inner.get("results")
        if isinstance(nested, list):
            return [r for r in nested if isinstance(r, dict)]
        outputs = inner.get("outputs")
        if isinstance(outputs, list):
            return [r for r in outputs if isinstance(r, dict)]
        table = inner.get("table")
        if isinstance(table, dict):
            rows: list[dict[str, Any]] = []
            for body in table.get("body") or []:
                if not isinstance(body, dict):
                    continue
                desc = body.get("description")
                for out in body.get("outputs") or []:
                    if isinstance(out, dict):
                        rows.append(_attach_desc(out, desc))
            if rows:
                return rows

    outputs = data.get("outputs")
    if isinstance(outputs, list):
        return [r for r in outputs if isinstance(r, dict)]
    return []


def _row_passed(row: dict[str, Any]) -> bool:
    if isinstance(row.get("success"), bool):
        return bool(row["success"])
    gr = row.get("gradingResult")
    if isinstance(gr, dict) and isinstance(gr.get("pass"), bool):
        return bool(gr["pass"])
    if isinstance(row.get("pass"), bool):
        return bool(row["pass"])
    return False


def _row_name(row: dict[str, Any], index: int) -> str:
    desc = row.get("description")
    tc = row.get("testCase")
    if not desc and isinstance(tc, dict):
        desc = tc.get("description")
    prompt = row.get("prompt")
    if not desc and isinstance(prompt, dict):
        desc = prompt.get("label")
    if not desc and row.get("testIdx") is not None:
        desc = f"test-{row['testIdx']}"
    if not desc:
        desc = f"case-{index}"
    name = str(desc).replace("\n", " ").strip() or f"case-{index}"
    if len(name) > 120:
        name = name[:117] + "..."
    return name


def _row_score(row: dict[str, Any], passed: bool) -> float:
    if _is_number(row.get("score")):
        return float(row["score"])
    gr = row.get("gradingResult")
    if isinstance(gr, dict) and _is_number(gr.get("score")):
        return float(gr["score"])
    return 1.0 if passed else 0.0


def _row_actual(row: dict[str, Any], passed: bool) -> str:
    gr = row.get("gradingResult") if isinstance(row.get("gradingResult"), dict) else {}
    reason = gr.get("reason") if gr else None
    err = row.get("error")
    if not passed:
        if reason not in (None, ""):
            return str(reason)
        if err not in (None, ""):
            return str(err)
        return "failed"
    return str(reason) if reason not in (None, "") else ""


def _row_expected(row: dict[str, Any]) -> str:
    gr = row.get("gradingResult") if isinstance(row.get("gradingResult"), dict) else {}
    assertion = gr.get("assertion") if gr else None
    if isinstance(assertion, dict) and assertion.get("value") not in (None, ""):
        return str(assertion["value"])
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


def cases_from_promptfoo(data: Any) -> list[CaseResult]:
    """Convert a parsed Promptfoo output object into CaseResult rows."""
    rows = iter_eval_rows(data)
    if not rows:
        if _looks_like_promptfoo(data):
            return []
        raise ValueError("no promptfoo results[] / outputs[] found")
    return [row_to_case(r, i) for i, r in enumerate(rows, start=1)]


def load_promptfoo(path: str | Path) -> list[CaseResult]:
    raw = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid JSON: {e}") from e
    return cases_from_promptfoo(data)
