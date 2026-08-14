"""GitHub Check Run payload adapter (local / OSS).

Formats agent-ci CaseResult lists (or JUnit-ish case summaries) into a
payload shaped like GitHub's Checks API create-check-run body.

OSS scope: write JSON locally + optional POST to a local mock receiver.
Real GitHub token posting (Checks API against github.com) is a paid/hosted
wedge — not implemented here.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Sequence

from agent_ci.runner import CaseResult


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _case_lines(results: Sequence[CaseResult]) -> list[str]:
    lines: list[str] = []
    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        lines.append(f"- [{mark}] {r.name} (score={r.score})")
        if not r.passed and r.actual:
            # Keep failure detail short for Check Run text.
            detail = str(r.actual).replace("\n", " ")
            if len(detail) > 200:
                detail = detail[:197] + "..."
            lines.append(f"  {detail}")
    return lines


def build_check_run_payload(
    results: Sequence[CaseResult],
    *,
    name: str = "agent-ci",
    suite_name: str = "demo",
    head_sha: str = "0000000000000000000000000000000000000000",
    details_url: str | None = None,
    external_id: str | None = None,
) -> dict[str, Any]:
    """Build a GitHub Checks API-compatible create-check-run payload.

    Required-ish fields for completed runs: name, head_sha, status,
    conclusion, completed_at, output.{title,summary,text}.
    """
    total = len(results)
    failed = sum(1 for r in results if not r.passed)
    passed = total - failed
    conclusion = "success" if failed == 0 else "failure"
    now = _utc_now()

    summary = (
        f"agent-ci suite `{suite_name}`: {passed}/{total} passed, {failed} failed."
    )
    text_parts = [
        f"### agent-ci / {suite_name}",
        "",
        summary,
        "",
        "#### Cases",
        *_case_lines(results),
        "",
        "_Local Check Run adapter (OSS). Real GitHub token posting is paid/hosted._",
    ]
    payload: dict[str, Any] = {
        "name": name,
        "head_sha": head_sha,
        "status": "completed",
        "conclusion": conclusion,
        "started_at": now,
        "completed_at": now,
        "output": {
            "title": f"agent-ci · {suite_name}",
            "summary": summary,
            "text": "\n".join(text_parts) + "\n",
        },
    }
    if details_url:
        payload["details_url"] = details_url
    if external_id:
        payload["external_id"] = external_id
    return payload


def write_check_run_payload(path: str | Any, payload: dict[str, Any]) -> None:
    from pathlib import Path

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def post_check_run_payload(
    url: str,
    payload: dict[str, Any],
    *,
    timeout: float = 5.0,
) -> tuple[int, str]:
    """POST JSON payload to a URL (intended for local mock receiver only).

    Does not attach a GitHub token. Returns (status_code, response_body).
    """
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "agent-ci-check-run-adapter/local",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return int(resp.status), body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return int(e.code), body
