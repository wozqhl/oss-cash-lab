"""Minimal local hosted-runner HTTP stub (stdlib only).

Not a cloud product — sketches the paid seat API from docs/hosted-runner.md.
OSS CLI remains free/offline; Bearer demo key sketches paid seats.

Local in-memory run queue (queued → running → done|failed|error) is OSS.
Hosted autoscaling / multi-node pools = paid later.
GET /health is liveness (always 200). GET /ready is readiness (503 queue_full).
"""
from __future__ import annotations

import json
import os
import queue
import re
import signal
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from agent_ci import __version__
from agent_ci.baseline import diff_baseline, diff_runs, diff_runs_to_html, diff_runs_to_md, load_baseline
from agent_ci.cors import cors_response_headers, handle_preflight, normalize_cors, request_origin
from agent_ci.metrics import CONTENT_TYPE as METRICS_CONTENT_TYPE, render_metrics
from agent_ci.request_id import REQUEST_ID_HEADER, resolve_request_id
from agent_ci.access_log import emit_access_log, mark_access_start
from agent_ci.runner import (
    CaseResult,
    GATE_ERROR,
    is_completed_status,
    parse_fail_under,
    quality_gate,
    run_cassette_suite,
    run_duration_seconds,
    run_suite,
    run_to_gha,
    run_to_html,
    run_to_junit,
    run_to_md,
    run_to_tap,
    runs_to_gha,
    runs_to_html,
    runs_to_junit,
    runs_to_md,
    runs_to_tap,
    suite_score,
    to_junit,
)
from agent_ci.webhook import notify_run_complete, parse_webhook_secret, parse_webhook_url
from agent_ci.runtime_config import summarize_runtime_config
from agent_ci.rate_limit import (
    SlidingWindowRateLimiter,
    client_ip_from_handler,
    resolve_rate_limit,
    skip_rate_limit,
)

# Local stub of a paid seat API key (not a real cloud credential).
DEMO_API_KEY = "demo"
DEFAULT_RUNS_DIR = Path("data/runs")
DEFAULT_CONCURRENCY = 1
DEFAULT_MAX_QUEUE = 16
MAX_DELAY_MS = 5000
RETRY_AFTER_SECONDS = 1
DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 1000
CASES_LIST_CAP = 500
CASE_STATUSES = frozenset({"passed", "failed", "error", "skipped"})
CASE_ERROR_MAX = 200
CASE_SECRET_NEEDLES = (
    "SECRET_PROMPT",
    "sk-",
    "Bearer ",
    "Authorization",
    "api_key",
    "apiKey",
    "webhookUrl",
    "webhook_url",
    "whsec_",
)
DEFAULT_RUNS_MAX = 1000
ENV_RUNS_MAX = "RUNS_MAX"
DEFAULT_OPENAPI_PATH = Path(__file__).resolve().parents[2] / "openapi" / "runner.openapi.json"
# Poll interval for `serve --watch` (fixtures/ max mtime). list_suites live-reads disk.
WATCH_POLL_MS = 400
DEFAULT_SHUTDOWN_DRAIN_MS = 5000
MAX_SHUTDOWN_DRAIN_MS = 30000


def resolve_drain_ms(raw: Any = None, env: dict[str, str] | None = None) -> int:
    """CLI `--drain-ms`, else env SHUTDOWN_DRAIN_MS, else 5s. Cap 30s."""
    source = raw
    if source is None or source == "":
        environ = env if env is not None else os.environ
        source = environ.get("SHUTDOWN_DRAIN_MS")
    try:
        n = int(source)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = DEFAULT_SHUTDOWN_DRAIN_MS
    if n < 0:
        n = DEFAULT_SHUTDOWN_DRAIN_MS
    return min(MAX_SHUTDOWN_DRAIN_MS, n)


def resolve_runs_max(raw: Any = None, env: dict[str, str] | None = None) -> int:
    """CLI `--runs-max` wins; else env RUNS_MAX; else 1000. `0` = unlimited."""
    source = raw
    if source is None or source == "":
        environ = env if env is not None else os.environ
        source = environ.get(ENV_RUNS_MAX)
    if source is None or source == "":
        return DEFAULT_RUNS_MAX
    try:
        n = int(source)
    except (TypeError, ValueError):
        return DEFAULT_RUNS_MAX
    if n < 0:
        return DEFAULT_RUNS_MAX
    return n


def begin_shutdown(server: Any) -> None:
    """Flip shutting_down so /ready is 503; stop new queue jobs; stop watch."""
    server.shutting_down = True
    rq = getattr(server, "run_queue", None)
    if rq is not None and hasattr(rq, "mark_stop"):
        rq.mark_stop()
    stop = getattr(server, "watch_stop", None)
    if stop is not None:
        stop.set()


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_openapi_path(root: Path | None = None) -> Path:
    """Bet-local OpenAPI file (package root / openapi/runner.openapi.json)."""
    if root is not None:
        alt = Path(root) / "openapi" / "runner.openapi.json"
        if alt.is_file():
            return alt.resolve()
    return DEFAULT_OPENAPI_PATH


def load_openapi_bytes(root: Path | None = None) -> bytes:
    """Read and JSON-validate the file-backed OpenAPI document."""
    path = resolve_openapi_path(root)
    raw = path.read_bytes()
    json.loads(raw.decode("utf-8"))
    return raw


def resolve_suite_path(suite_arg: str, root: Path | None = None) -> Path:
    """Resolve suite path relative to CWD, then package root (bet dir)."""
    suite = Path(suite_arg)
    if suite.is_absolute() and suite.exists():
        return suite
    if suite.exists():
        return suite.resolve()
    base = root or Path(__file__).resolve().parents[2]
    alt = base / suite_arg
    if alt.exists():
        return alt
    return suite


def fixtures_root(root: Path | None = None) -> Path:
    """Bet-local fixtures/ directory (package root / fixtures)."""
    base = root or Path(__file__).resolve().parents[2]
    return (base / "fixtures").resolve()


def _suite_entry(suite_dir: Path, fixtures: Path) -> dict[str, Any]:
    name = suite_dir.name
    case_count = len(list(suite_dir.glob("*.json")))
    # Relative path as used by POST /v1/runs {"suite":"fixtures/<name>"}.
    try:
        rel = suite_dir.resolve().relative_to(fixtures.parent.resolve())
        rel_path = rel.as_posix()
    except ValueError:
        rel_path = f"fixtures/{name}"
    return {
        "name": name,
        "path": rel_path,
        "caseCount": case_count,
    }


def list_suites(root: Path | None = None) -> list[dict[str, Any]]:
    """List available fixture suite dirs under fixtures/ (name, path, caseCount)."""
    fixtures = fixtures_root(root)
    if not fixtures.is_dir():
        return []
    suites: list[dict[str, Any]] = []
    for child in sorted(fixtures.iterdir(), key=lambda p: p.name):
        if child.is_dir() and not child.name.startswith("."):
            suites.append(_suite_entry(child, fixtures))
    return suites


def count_suite_dirs(fixtures: Path) -> int:
    """Count non-dot suite dirs under fixtures/ (watch log / smoke)."""
    if not fixtures.is_dir():
        return 0
    n = 0
    try:
        for child in fixtures.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                n += 1
    except OSError:
        return n
    return n


def watch_log(line: str) -> None:
    """Line-buffered-ish stdout for --watch (redirected logs must appear promptly)."""
    s = str(line)
    if not s.endswith("\n"):
        s += "\n"
    try:
        sys.stdout.write(s)
        sys.stdout.flush()
    except OSError:
        pass


def walk_max_mtime(path: Path) -> float:
    """Directory mtime, or simple walk of max mtime under path (files + dirs)."""
    max_m = 0.0
    try:
        st = path.stat()
        max_m = float(st.st_mtime)
    except OSError:
        return max_m
    if not path.is_dir():
        return max_m
    try:
        for p in path.rglob("*"):
            try:
                m = float(p.stat().st_mtime)
            except OSError:
                continue
            if m > max_m:
                max_m = m
    except OSError:
        pass
    return max_m


class WatchState:
    """Generation counter for GET /health `watch: {generation}` when --watch is on."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._generation = 0

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"generation": int(self._generation)}

    def bump(self) -> int:
        with self._lock:
            self._generation += 1
            return int(self._generation)


def start_fixtures_watch(
    path: Path,
    *,
    watch_state: WatchState | None = None,
    poll_ms: int = WATCH_POLL_MS,
    log: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> tuple[threading.Thread, threading.Event]:
    """Poll fixtures/ max mtime; log regenerated and bump generation.

    list_suites still live-reads disk (no required cache). Errors keep the
    previous generation; mtime advances only after a successful tick.
    Returns (daemon thread, stop event).
    """
    log = log or watch_log
    stop = stop_event or threading.Event()
    last = walk_max_mtime(path)
    try:
        shown = str(path.resolve())
    except OSError:
        shown = str(path)
    log(f"watching {shown} (poll {poll_ms}ms)")

    def loop() -> None:
        nonlocal last
        interval = max(int(poll_ms), 1) / 1000.0
        while not stop.wait(interval):
            try:
                now = walk_max_mtime(path)
                if not (now > last):
                    continue
                count = count_suite_dirs(path)
                gen = watch_state.bump() if watch_state is not None else 0
                last = now
                log("regenerated " + json.dumps({"suiteCount": count, "generation": gen}))
            except Exception as e:
                try:
                    sys.stderr.write(f"watch regenerate error: {e}\n")
                    sys.stderr.flush()
                except OSError:
                    pass

    t = threading.Thread(target=loop, name="agent-ci-watch", daemon=True)
    t.start()
    return t, stop


def _suite_case_rows(suite_dir: Path) -> list[dict[str, str]]:
    """Cassette names only — never prompt / trajectory / expected / actual."""
    rows: list[dict[str, str]] = []
    try:
        files = sorted(suite_dir.glob("*.json"), key=lambda x: x.name)
    except OSError:
        return rows
    for child in files:
        if child.is_file() and not child.name.startswith("."):
            rows.append({"name": child.stem})
    return rows


def get_suite(name: str, root: Path | None = None) -> dict[str, Any] | None:
    """One suite by directory name. Allowlist ok/id/name/path/caseCount/cases[{name}].

    Never dumps cassette file contents (prompt/trajectory/secrets).
    """
    if not name or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", name):
        return None
    fixtures = fixtures_root(root)
    suite_dir = fixtures / name
    if not suite_dir.is_dir():
        return None
    # Stay inside fixtures/ (reject weird symlink escapes).
    try:
        suite_dir.resolve().relative_to(fixtures.resolve())
    except ValueError:
        return None
    entry = _suite_entry(suite_dir, fixtures)
    return {
        "ok": True,
        "id": entry["name"],
        "name": entry["name"],
        "path": entry["path"],
        "caseCount": entry["caseCount"],
        "cases": _suite_case_rows(suite_dir),
    }


def results_summary(results: list[CaseResult]) -> dict[str, Any]:
    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed
    return {
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "ok": failed == 0,
        "cases": [
            {
                "name": r.name,
                "passed": bool(r.passed),
                "score": float(r.score),
            }
            for r in results
        ],
    }


def _persist_run(record: dict[str, Any], runs_dir: Path) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    out = runs_dir / f"{record['runId']}.json"
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def execute_run(
    body: dict[str, Any],
    *,
    runs_dir: Path,
    root: Path | None = None,
    run_id: str | None = None,
    created_at: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Run suite from path or embedded cases; optionally diff baseline.

    Optional body.delayMs (capped) sleeps before work — local stub aid for
    concurrency / queue demos; not a product feature.
    """
    delay_ms = body.get("delayMs")
    if delay_ms is not None:
        try:
            ms = int(delay_ms)
        except (TypeError, ValueError) as e:
            raise ValueError("delayMs must be an integer") from e
        if ms < 0:
            raise ValueError("delayMs must be >= 0")
        time.sleep(min(ms, MAX_DELAY_MS) / 1000.0)

    seed = int(body.get("seed", 42))
    suite_name = "embedded"
    results: list[CaseResult]

    if "cases" in body and body["cases"] is not None:
        cases = body["cases"]
        if not isinstance(cases, list) or not cases:
            raise ValueError("cases must be a non-empty list")
        results = run_suite(cases, seed=seed)
        suite_name = str(body.get("suiteName") or body.get("suite") or "embedded")
    elif body.get("suite"):
        suite_path = resolve_suite_path(str(body["suite"]), root=root)
        if not suite_path.is_dir():
            raise FileNotFoundError(f"suite not found: {suite_path}")
        results = run_cassette_suite(suite_path, seed=seed)
        suite_name = suite_path.name
    else:
        raise ValueError("body must include 'suite' (path) or 'cases' (embedded)")

    summary = results_summary(results)
    baseline_ok: bool | None = None
    baseline_report: list[str] | None = None

    baseline_arg = body.get("baseline")
    if baseline_arg is not None:
        if isinstance(baseline_arg, dict):
            baseline = baseline_arg
        else:
            bpath = Path(str(baseline_arg))
            if not bpath.is_absolute() and not bpath.exists():
                alt = (root or Path(__file__).resolve().parents[2]) / str(baseline_arg)
                if alt.exists():
                    bpath = alt
            baseline = load_baseline(bpath)
        baseline_ok, baseline_report = diff_baseline(baseline, results)
        if not baseline_ok:
            summary["ok"] = False

    score = suite_score(results)
    fail_under = None
    if "failUnder" in body and body.get("failUnder") is not None:
        fail_under = parse_fail_under(body.get("failUnder"))
    gate = quality_gate(score, fail_under)
    status = "done"
    if gate is not None and not gate.get("passed"):
        status = "failed"
        summary["ok"] = False

    rid = run_id or uuid.uuid4().hex[:12]
    record: dict[str, Any] = {
        "runId": rid,
        "version": __version__,
        "createdAt": created_at or _utc_now(),
        "finishedAt": _utc_now(),
        "status": status,
        "suite": suite_name,
        "seed": seed,
        "passed": bool(summary["ok"]),
        "score": score,
        "summary": summary,
        "baselineOk": baseline_ok,
        "baselineReport": baseline_report,
    }
    if gate is not None:
        record["gate"] = gate
    if status == "failed":
        record["error"] = GATE_ERROR
        record["passed"] = False
    if request_id:
        record["requestId"] = request_id

    out = _persist_run(record, runs_dir)
    junit_path = runs_dir / f"{rid}.junit.xml"
    junit_path.write_text(
        to_junit(
            results,
            suite_name=suite_name,
            time_s=run_duration_seconds(record),
            gate=gate,
        ),
        encoding="utf-8",
    )
    record["stored"] = str(out)
    record["junit"] = str(junit_path)
    # Re-write with stored/junit paths.
    _persist_run(record, runs_dir)
    return record



def load_run(run_id: str, runs_dir: Path) -> dict[str, Any] | None:
    if not re.fullmatch(r"[0-9a-fA-F-]{8,64}", run_id):
        return None
    path = runs_dir / f"{run_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


RUN_ID_RE = re.compile(r"^[0-9a-fA-F-]{8,64}$")


def diff_runs_response(
    to_id: str,
    against: str | None,
    get_run: Callable[[str], dict[str, Any] | None],
) -> tuple[int, dict[str, Any]]:
    """HTTP mapping for GET /v1/runs/{id}/diff?against= (JSON, Markdown, or HTML).

    Missing run → 404 `{error:run_not_found}`. Incomplete (`queued`/`running`)
    → 409 `{error:run_not_done}`. Missing/invalid `against` → 400.
    Markdown/HTML are applied by the handler (`/diff.md` / `/diff.html` or
    `?format=md` / `?format=html`); this helper always returns the JSON payload.
    """
    if against is None or str(against).strip() == "":
        return 400, {"error": "bad_request", "detail": "against is required"}
    against_id = str(against).strip()
    if not RUN_ID_RE.fullmatch(against_id):
        return 400, {"error": "bad_request", "detail": "against must be a run id"}
    to_rec = get_run(to_id)
    if to_rec is None:
        return 404, {"error": "run_not_found", "runId": to_id}
    from_rec = get_run(against_id)
    if from_rec is None:
        return 404, {"error": "run_not_found", "runId": against_id}
    if not is_completed_status(to_rec.get("status")):
        return 409, {"error": "run_not_done", "runId": to_id}
    if not is_completed_status(from_rec.get("status")):
        return 409, {"error": "run_not_done", "runId": against_id}
    return 200, diff_runs(from_rec, to_rec)



def _iter_case_rows(run: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Pull case dicts from summary.cases, cases, or results — original order."""
    if not isinstance(run, dict):
        return []
    summary = run.get("summary") if isinstance(run.get("summary"), dict) else {}
    raw: Any = None
    if isinstance(summary.get("cases"), list):
        raw = summary["cases"]
    elif isinstance(run.get("cases"), list):
        raw = run["cases"]
    elif isinstance(run.get("results"), list):
        raw = run["results"]
    else:
        return []
    return [c for c in raw if isinstance(c, dict)]


def _case_status(row: dict[str, Any]) -> str:
    raw = row.get("status")
    if raw is not None and str(raw).strip() != "":
        s = str(raw).strip().lower()
        if s in CASE_STATUSES:
            return s
        if s in ("pass", "ok", "success"):
            return "passed"
        if s in ("fail", "failure"):
            return "failed"
        if s in ("skip",):
            return "skipped"
        if s in ("err",):
            return "error"
    if "passed" in row:
        return "passed" if row.get("passed") else "failed"
    return "failed"


def _safe_case_error(row: dict[str, Any]) -> str | None:
    """Short error already shown in JUnit/Markdown — never secrets or blobs."""
    raw = row.get("error")
    if raw is None:
        raw = row.get("message")
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or len(text) > CASE_ERROR_MAX:
        return None
    for needle in CASE_SECRET_NEEDLES:
        if needle in text or needle.lower() in text.lower():
            return None
    if "\n" in text:
        return None
    return text


def _case_duration_ms(row: dict[str, Any]) -> int | None:
    """Include durationMs only when already on the case record."""
    for key in ("durationMs", "duration_ms"):
        if row.get(key) is None:
            continue
        try:
            n = float(row[key])
        except (TypeError, ValueError):
            continue
        if n >= 0:
            return int(n)
    return None


def cases_json(
    run: dict[str, Any] | None,
    status: str | None = None,
    cap: int = CASES_LIST_CAP,
) -> dict[str, Any]:
    """Lightweight case inventory for GET /v1/runs/{id}/cases.

    Allowlist only: suite, name, status, optional durationMs, optional short
    error. Never copies prompt / expected / actual / output / secrets.
    Original suite order. ``count`` is the full (optionally filtered) size;
    array cap default 500; ``truncated: true`` when more than cap.
    Unknown ``status`` filter → empty list (not 400).
    """
    rec = run if isinstance(run, dict) else {}
    suite_default = str(rec.get("suite") or "")
    want = str(status).strip().lower() if status else ""
    rows: list[dict[str, Any]] = []
    for c in _iter_case_rows(rec):
        st = _case_status(c)
        if want and st != want:
            continue
        item: dict[str, Any] = {
            "suite": str(c.get("suite") or suite_default),
            "name": str(c.get("name") or "unnamed"),
            "status": st,
        }
        dur = _case_duration_ms(c)
        if dur is not None:
            item["durationMs"] = dur
        err = _safe_case_error(c)
        if err is not None:
            item["error"] = err
        rows.append(item)
    limit = cap if isinstance(cap, int) and cap > 0 else CASES_LIST_CAP
    truncated = len(rows) > limit
    out: dict[str, Any] = {
        "ok": True,
        "runId": rec.get("runId"),
        "status": rec.get("status"),
        "count": len(rows),
        "cases": rows[:limit],
    }
    if truncated:
        out["truncated"] = True
    return out


def _run_list_item(record: dict[str, Any]) -> dict[str, Any]:
    """Compact list row: id, status, summary pass/fail counts, createdAt."""
    summary = record.get("summary") if isinstance(record.get("summary"), dict) else {}
    passed = int(summary.get("passed") or 0)
    failed = int(summary.get("failed") or 0)
    total = summary.get("total")
    if total is None:
        total = passed + failed
    item: dict[str, Any] = {
        "runId": record.get("runId"),
        "status": record.get("status"),
        "createdAt": record.get("createdAt"),
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": int(total),
        },
    }
    if record.get("requestId"):
        item["requestId"] = record["requestId"]
    return item


def _run_sort_key(record: dict[str, Any]) -> tuple[Any, ...]:
    """Oldest-first key; reverse=True for newest-first lists."""
    return (
        record.get("createdAt") is not None,
        str(record.get("createdAt") or ""),
        str(record.get("runId") or ""),
    )


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    """Shallow copy without internal `_` keys (e.g. `_finishSeq`)."""
    return {k: v for k, v in record.items() if not str(k).startswith("_")}


def _finished_sort_key(record: dict[str, Any]) -> tuple[Any, ...]:
    """Oldest-finished first: finish seq, then finishedAt, then createdAt."""
    seq = record.get("_finishSeq")
    try:
        seq_n = int(seq) if seq is not None else -1
    except (TypeError, ValueError):
        seq_n = -1
    return (
        seq_n >= 0,
        seq_n if seq_n >= 0 else 0,
        record.get("finishedAt") is not None,
        str(record.get("finishedAt") or ""),
        record.get("createdAt") is not None,
        str(record.get("createdAt") or ""),
        str(record.get("runId") or ""),
    )


def list_memory_runs(
    memory: dict[str, dict[str, Any]] | None,
    *,
    limit: int = DEFAULT_LIST_LIMIT,
) -> list[dict[str, Any]]:
    """Compact list rows from an in-memory run map, newest createdAt first."""
    if limit < 0:
        raise ValueError("limit must be >= 0")
    cap = min(limit, MAX_LIST_LIMIT)
    items: list[dict[str, Any]] = []
    if memory:
        for rec in memory.values():
            if not isinstance(rec, dict) or not rec.get("runId"):
                continue
            items.append(_run_list_item(rec))
    items.sort(key=_run_sort_key, reverse=True)
    return items[:cap]


def cap_finished_runs(
    memory: dict[str, dict[str, Any]],
    max_finished: int,
) -> list[str]:
    """Drop oldest finished (done|failed|error) runs in-place.

    In-flight queued/running are never dropped. ``max_finished`` 0 = unlimited.
    Returns dropped run ids (oldest first).
    """
    if not isinstance(memory, dict):
        return []
    try:
        cap = int(max_finished)
    except (TypeError, ValueError):
        cap = DEFAULT_RUNS_MAX
    if cap <= 0:
        return []
    finished: list[dict[str, Any]] = [
        rec
        for rec in memory.values()
        if isinstance(rec, dict)
        and rec.get("runId")
        and is_completed_status(rec.get("status"))
    ]
    finished.sort(key=_finished_sort_key)
    extra = len(finished) - cap
    if extra <= 0:
        return []
    dropped = [str(rec["runId"]) for rec in finished[:extra]]
    for rid in dropped:
        memory.pop(rid, None)
    return dropped


def forget_run_files(runs_dir: Path, run_id: str) -> None:
    """Best-effort delete persisted `{id}.json` + `{id}.junit.xml`."""
    if not run_id:
        return
    directory = Path(runs_dir)
    for suffix in (".json", ".junit.xml"):
        path = directory / f"{run_id}{suffix}"
        try:
            path.unlink()
        except OSError:
            pass


def list_runs(runs_dir: Path, *, limit: int = DEFAULT_LIST_LIMIT) -> list[dict[str, Any]]:
    """Recent runs from data/runs/*.json, newest createdAt first.

    Only *.json run records (not *.junit.xml). Skips unreadable files.
    """
    if limit < 0:
        raise ValueError("limit must be >= 0")
    cap = min(limit, MAX_LIST_LIMIT)
    directory = Path(runs_dir)
    if not directory.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for path in directory.glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(record, dict) or not record.get("runId"):
            continue
        items.append(_run_list_item(record))
    items.sort(key=_run_sort_key, reverse=True)
    return items[:cap]


def load_junit(run_id: str, runs_dir: Path) -> str | None:
    if not re.fullmatch(r"[0-9a-fA-F-]{8,64}", run_id):
        return None
    path = runs_dir / f"{run_id}.junit.xml"
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def list_completed_run_records(
    runs_dir: Path,
    *,
    memory: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Full run JSON for status done|failed|error (memory wins, then data/runs/*.json)."""
    by_id: dict[str, dict[str, Any]] = {}
    directory = Path(runs_dir)
    if directory.is_dir():
        for path in directory.glob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                continue
            if not isinstance(record, dict) or not record.get("runId"):
                continue
            if not is_completed_status(record.get("status")):
                continue
            by_id[str(record["runId"])] = record
    if memory:
        for rec in memory.values():
            if not isinstance(rec, dict) or not rec.get("runId"):
                continue
            if not is_completed_status(rec.get("status")):
                continue
            by_id[str(rec["runId"])] = dict(rec)
    items = list(by_id.values())
    items.sort(key=_run_sort_key, reverse=True)
    return items


def junit_xml_for_run(
    run_id: str,
    runs_dir: Path,
    *,
    record: dict[str, Any] | None = None,
) -> str | None:
    """Stored `{id}.junit.xml`, else generate from a completed run record."""
    xml = load_junit(run_id, runs_dir)
    if xml is not None:
        return xml
    rec = record if isinstance(record, dict) else load_run(run_id, runs_dir)
    if rec is None:
        return None
    if not is_completed_status(rec.get("status")):
        return None
    return run_to_junit(rec)



def tap_txt_for_run(
    run_id: str,
    runs_dir: Path,
    *,
    record: dict[str, Any] | None = None,
) -> str | None:
    """TAP13 from a completed run record (no stored artifact file)."""
    rec = record if isinstance(record, dict) else load_run(run_id, runs_dir)
    if rec is None:
        return None
    if not is_completed_status(rec.get("status")):
        return None
    return run_to_tap(rec)


def md_report_for_run(
    run_id: str,
    runs_dir: Path,
    *,
    record: dict[str, Any] | None = None,
) -> str | None:
    """Markdown report from a completed run record (no stored artifact file)."""
    rec = record if isinstance(record, dict) else load_run(run_id, runs_dir)
    if rec is None:
        return None
    if not is_completed_status(rec.get("status")):
        return None
    return run_to_md(rec)


def gha_annotations_for_run(
    run_id: str,
    runs_dir: Path,
    *,
    record: dict[str, Any] | None = None,
) -> str | None:
    """GHA workflow commands from a completed run record (no stored artifact)."""
    rec = record if isinstance(record, dict) else load_run(run_id, runs_dir)
    if rec is None:
        return None
    if not is_completed_status(rec.get("status")):
        return None
    return run_to_gha(rec)


def html_report_for_run(
    run_id: str,
    runs_dir: Path,
    *,
    record: dict[str, Any] | None = None,
) -> str | None:
    """HTML report from a completed run record (no stored artifact file)."""
    rec = record if isinstance(record, dict) else load_run(run_id, runs_dir)
    if rec is None:
        return None
    if not is_completed_status(rec.get("status")):
        return None
    return run_to_html(rec)


def store_check_run_post(body: bytes, runs_dir: Path) -> Path:
    """Store a posted Check Run payload for local mock reporting proof."""
    # Prefer sibling data/ next to runs/; fall back to runs_dir parent.
    data_dir = runs_dir.parent if runs_dir.name == "runs" else runs_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    out = data_dir / "check-run-posted.json"
    out.write_bytes(body if body else b"{}")
    return out


def check_auth(authorization: str | None, require_key: bool = False) -> tuple[bool, str | None]:
    """Optional Bearer auth sketch.

    - No header: allowed unless require_key (OSS local).
    - Bearer <DEMO_API_KEY>: allowed (paid seat sketch).
    - Anything else: 401.
    """
    if not authorization:
        if require_key:
            return False, "missing_api_key"
        return True, None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False, "invalid_authorization"
    token = parts[1].strip()
    if token != DEMO_API_KEY:
        return False, "invalid_api_key"
    return True, None


def _suite_label(body: dict[str, Any]) -> str:
    if body.get("suite"):
        return str(body["suite"])
    if body.get("suiteName"):
        return str(body["suiteName"])
    if body.get("cases") is not None:
        return "embedded"
    return "unknown"


class RunQueue:
    """In-memory FIFO queue with worker pool (stdlib threading).

    Capacity: up to `concurrency` running + `max_queue` waiting.
    Extra POSTs beyond that → 429 + Retry-After.
    """

    def __init__(
        self,
        *,
        concurrency: int = DEFAULT_CONCURRENCY,
        max_queue: int = DEFAULT_MAX_QUEUE,
        runs_dir: Path,
        root: Path | None = None,
        webhook_url: str | None = None,
        webhook_secret: str | None = None,
        runs_max: int = DEFAULT_RUNS_MAX,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        if max_queue < 0:
            raise ValueError("max_queue must be >= 0")
        try:
            cap = int(runs_max)
        except (TypeError, ValueError):
            cap = DEFAULT_RUNS_MAX
        if cap < 0:
            cap = DEFAULT_RUNS_MAX
        self.concurrency = concurrency
        self.max_queue = max_queue
        self.runs_max = cap
        self.runs_dir = Path(runs_dir)
        self.root = root
        self.webhook_url = parse_webhook_url(webhook_url)
        self.webhook_secret = parse_webhook_secret(webhook_secret)
        self._q: queue.Queue[tuple[str, dict[str, Any], bool] | None] = queue.Queue()
        self._lock = threading.Lock()
        self._queued = 0
        self._running = 0
        self._completed = 0
        self._failed = 0
        self._finish_seq = 0
        self._memory: dict[str, dict[str, Any]] = {}
        self._stop = False
        self._workers: list[threading.Thread] = []
        for i in range(concurrency):
            t = threading.Thread(
                target=self._worker_loop,
                name=f"agent-ci-run-worker-{i}",
                daemon=True,
            )
            t.start()
            self._workers.append(t)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "concurrency": self.concurrency,
                "maxQueue": self.max_queue,
                "queued": self._queued,
                "running": self._running,
            }

    def mark_stop(self) -> None:
        """Stop accepting / starting new jobs (in-flight keep running)."""
        self._stop = True

    def ready_payload(self) -> tuple[int, dict[str, Any], dict[str, str]]:
        """Readiness: 200 if POST /v1/runs would enqueue; 503 if it would 429.

        Snapshot only — does not consume a queue slot. Liveness remains GET /health.
        """
        snap = self.snapshot()
        full = (
            int(snap["running"]) >= int(snap["concurrency"])
            and int(snap["queued"]) >= int(snap["maxQueue"])
        )
        if full:
            return (
                503,
                {"ok": False, "reason": "queue_full", "queue": snap},
                {"Retry-After": str(RETRY_AFTER_SECONDS)},
            )
        return (200, {"ok": True, "queue": snap}, {})

    def metrics_snapshot(self) -> dict[str, int]:
        """Queue gauges + process-lifetime done/error counters (Prometheus)."""
        with self._lock:
            return {
                "queued": self._queued,
                "running": self._running,
                "completed": self._completed,
                "failed": self._failed,
            }

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            mem = self._memory.get(run_id)
            if mem is not None:
                return _public_record(mem)
        return load_run(run_id, self.runs_dir)

    def completed_records(self) -> list[dict[str, Any]]:
        """In-memory runs that reached done|failed|error (copies)."""
        with self._lock:
            items = [
                _public_record(rec)
                for rec in self._memory.values()
                if isinstance(rec, dict)
                and is_completed_status(rec.get("status"))
            ]
        items.sort(key=_run_sort_key, reverse=True)
        return items

    def list_run_items(self, *, limit: int = DEFAULT_LIST_LIMIT) -> list[dict[str, Any]]:
        """Compact list rows for GET /v1/runs (retained memory, incl. in-flight)."""
        with self._lock:
            return list_memory_runs(self._memory, limit=limit)

    def _trim_finished(self) -> None:
        """Drop oldest finished runs over cap. Caller holds self._lock."""
        dropped = cap_finished_runs(self._memory, self.runs_max)
        for rid in dropped:
            forget_run_files(self.runs_dir, rid)

    def submit(
        self,
        body: dict[str, Any],
        *,
        request_id: str | None = None,
    ) -> tuple[int, dict[str, Any], dict[str, str]]:
        """Enqueue a run. Returns (http_status, payload, extra_headers)."""
        if self._stop:
            snap = self.snapshot()
            return (
                503,
                {"ok": False, "reason": "shutting_down", "error": "shutting_down", "queue": snap},
                {},
            )
        # Validate shape early so bad requests never occupy the queue.
        if not (
            ("cases" in body and body["cases"] is not None) or body.get("suite")
        ):
            return (
                400,
                {"error": "bad_request", "detail": "body must include 'suite' (path) or 'cases' (embedded)"},
                {},
            )
        if "cases" in body and body["cases"] is not None:
            cases = body["cases"]
            if not isinstance(cases, list) or not cases:
                return (
                    400,
                    {"error": "bad_request", "detail": "cases must be a non-empty list"},
                    {},
                )
        if body.get("delayMs") is not None:
            try:
                ms = int(body["delayMs"])
            except (TypeError, ValueError):
                return 400, {"error": "bad_request", "detail": "delayMs must be an integer"}, {}
            if ms < 0:
                return 400, {"error": "bad_request", "detail": "delayMs must be >= 0"}, {}
        if "failUnder" in body and body.get("failUnder") is not None:
            try:
                parse_fail_under(body.get("failUnder"))
            except ValueError as e:
                return 400, {"error": "bad_request", "detail": str(e)}, {}

        with self._lock:
            # Reserve a running slot when free so concurrent POSTs don't both
            # consume max_queue before a worker starts (queued→running race).
            reserved_running = False
            if self._running < self.concurrency:
                self._running += 1
                reserved_running = True
                status = "running"
            elif self._queued < self.max_queue:
                self._queued += 1
                status = "queued"
            else:
                return (
                    429,
                    {
                        "error": "queue_full",
                        "detail": f"max queue depth {self.max_queue}",
                        "retryAfter": RETRY_AFTER_SECONDS,
                        "queue": {
                            "concurrency": self.concurrency,
                            "maxQueue": self.max_queue,
                            "queued": self._queued,
                            "running": self._running,
                        },
                    },
                    {"Retry-After": str(RETRY_AFTER_SECONDS)},
                )

            run_id = uuid.uuid4().hex[:12]
            created = _utc_now()
            record: dict[str, Any] = {
                "runId": run_id,
                "version": __version__,
                "createdAt": created,
                "status": status,
                "suite": _suite_label(body),
                "seed": int(body.get("seed", 42)),
            }
            if request_id:
                record["requestId"] = request_id
            if status == "running":
                record["startedAt"] = created
            self._memory[run_id] = record
            stored = _persist_run(record, self.runs_dir)
            record["stored"] = str(stored)

        self._q.put((run_id, body, reserved_running))
        payload: dict[str, Any] = {
            "runId": run_id,
            "status": status,
            "suite": record["suite"],
            "stored": record.get("stored"),
        }
        if request_id:
            payload["requestId"] = request_id
        return (202, payload, {})

    def _worker_loop(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                self._q.task_done()
                return
            run_id, body, reserved_running = item
            created_at: str | None = None
            request_id: str | None = None
            if self._stop and not reserved_running:
                rec_for_hook = self._fail(run_id, "shutting_down", "server shutting down")
                with self._lock:
                    self._queued = max(0, self._queued - 1)
                if rec_for_hook is not None:
                    notify_run_complete(self.webhook_url, rec_for_hook, secret=self.webhook_secret)
                self._q.task_done()
                continue
            with self._lock:
                if reserved_running:
                    # Slot already reserved in submit; ensure status is running.
                    rec = self._memory.get(run_id)
                    if rec is not None:
                        rec["status"] = "running"
                        rec.setdefault("startedAt", _utc_now())
                        created_at = str(rec.get("createdAt"))
                        if rec.get("requestId"):
                            request_id = str(rec["requestId"])
                        _persist_run(rec, self.runs_dir)
                else:
                    self._queued = max(0, self._queued - 1)
                    self._running += 1
                    rec = self._memory.get(run_id)
                    if rec is not None:
                        rec["status"] = "running"
                        rec["startedAt"] = _utc_now()
                        created_at = str(rec.get("createdAt"))
                        if rec.get("requestId"):
                            request_id = str(rec["requestId"])
                        _persist_run(rec, self.runs_dir)

            rec_for_hook = None
            try:
                result = execute_run(
                    body,
                    runs_dir=self.runs_dir,
                    root=self.root,
                    run_id=run_id,
                    created_at=created_at,
                    request_id=request_id,
                )
                with self._lock:
                    self._finish_seq += 1
                    result["_finishSeq"] = self._finish_seq
                    self._memory[run_id] = result
                    self._completed += 1
                    self._trim_finished()
                rec_for_hook = _public_record(result)
            except FileNotFoundError as e:
                rec_for_hook = self._fail(run_id, "suite_not_found", str(e))
            except ValueError as e:
                rec_for_hook = self._fail(run_id, "bad_request", str(e))
            except Exception as e:  # pragma: no cover - local stub guard
                rec_for_hook = self._fail(run_id, "internal", str(e))
            finally:
                with self._lock:
                    self._running = max(0, self._running - 1)
                if rec_for_hook is not None:
                    notify_run_complete(self.webhook_url, rec_for_hook, secret=self.webhook_secret)
                self._q.task_done()

    def _fail(self, run_id: str, error: str, detail: str) -> dict[str, Any]:
        with self._lock:
            rec = self._memory.get(run_id) or {
                "runId": run_id,
                "version": __version__,
                "createdAt": _utc_now(),
            }
            rec.update(
                {
                    "status": "error",
                    "finishedAt": _utc_now(),
                    "passed": False,
                    "error": error,
                    "detail": detail,
                }
            )
            self._failed += 1
            self._finish_seq += 1
            rec["_finishSeq"] = self._finish_seq
            self._memory[run_id] = rec
            stored = _persist_run(_public_record(rec), self.runs_dir)
            rec["stored"] = str(stored)
            self._trim_finished()
            return _public_record(rec)

    def shutdown(self) -> None:
        self._stop = True
        for _ in self._workers:
            self._q.put(None)


class HostedRunnerHandler(BaseHTTPRequestHandler):
    runs_dir: Path = DEFAULT_RUNS_DIR
    root: Path | None = None
    require_key: bool = False
    run_queue: RunQueue | None = None
    concurrency: int = DEFAULT_CONCURRENCY
    max_queue: int = DEFAULT_MAX_QUEUE
    cors: dict[str, Any] | None = None
    webhook_url: str | None = None
    webhook_secret: str | None = None
    watch_state: WatchState | None = None

    def log_message(self, fmt: str, *args: Any) -> None:
        # Quiet default; still useful when debugging local-mvp.
        sys_stderr = __import__("sys").stderr
        sys_stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def handle_one_request(self) -> None:
        mark_access_start(self)
        super().handle_one_request()

    def _cors_headers(self) -> dict[str, str]:
        origin = request_origin(self.headers)
        return cors_response_headers(origin, self.cors)

    def _resolve_request_id(self) -> str:
        cached = getattr(self, "_cached_request_id", None)
        if cached:
            return cached
        rid = resolve_request_id(self.headers)
        self._cached_request_id = rid
        return rid

    def _merge_response_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        # CORS first; extra (e.g. Retry-After) wins on collision; X-Request-Id last.
        merged = {**self._cors_headers()}
        if extra:
            merged.update(extra)
        merged[REQUEST_ID_HEADER] = self._resolve_request_id()
        return merged

    def _rate_limit_or_reject(self, path: str) -> bool:
        """Apply per-IP sliding window. True if 429 already sent."""
        if skip_rate_limit(path):
            return False
        limiter: SlidingWindowRateLimiter | None = getattr(
            self.server, "rate_limiter", None
        )
        if limiter is None:
            limiter = getattr(self, "rate_limiter", None)
        if limiter is None:
            return False
        limit = getattr(self.server, "rate_limit", None)
        if limit is None and not hasattr(self.server, "rate_limit"):
            limit = getattr(self, "rate_limit", None)
        ip = client_ip_from_handler(self)
        allowed, retry_after = limiter.check(ip, limit)
        if allowed:
            return False
        self._send(
            429,
            {"ok": False, "reason": "rate_limited"},
            extra_headers={"Retry-After": str(retry_after)},
        )
        return True

    def _send(
        self,
        code: int,
        payload: dict[str, Any],
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for k, v in self._merge_response_headers(extra_headers).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)
        emit_access_log(self, service="agent-ci", status=code, bytes_out=len(body))

    def _send_raw(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in self._merge_response_headers().items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)
        emit_access_log(self, service="agent-ci", status=code, bytes_out=len(body))

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        if not raw:
            return {}
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def do_OPTIONS(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        origin = request_origin(self.headers)
        pf = handle_preflight(origin, self.cors)
        if pf is None:
            # CORS disabled: no extra CORS; same 404 as unknown methods/paths.
            self._send(404, {"error": "not_found", "path": path})
            return
        if pf["status"] == 204:
            self.send_response(204)
            for k, v in (pf.get("headers") or {}).items():
                self.send_header(k, v)
            self.send_header(REQUEST_ID_HEADER, self._resolve_request_id())
            self.end_headers()
            return
        self._send(int(pf["status"]), pf.get("body") or {"error": "forbidden"}, pf.get("headers") or {})

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if self._rate_limit_or_reject(path):
            return
        if path == "/health":
            q = self.run_queue.snapshot() if self.run_queue else {
                "concurrency": self.concurrency,
                "maxQueue": self.max_queue,
                "queued": 0,
                "running": 0,
            }
            payload: dict[str, Any] = {
                "ok": True,
                "service": "agent-ci-hosted-stub",
                "version": __version__,
                "mode": "local",
                "queue": q,
            }
            if self.watch_state is not None:
                payload["watch"] = self.watch_state.snapshot()
            if getattr(self.server, "shutting_down", False):
                payload["shuttingDown"] = True
            self._send(200, payload)
            return
        if path == "/ready":
            # Readiness only. Does not consume a queue slot. /health stays 200.
            # Shutdown 503 wins over healthy 200 (and over queue_full).
            if getattr(self.server, "shutting_down", False):
                q = self.run_queue.snapshot() if self.run_queue else {
                    "concurrency": self.concurrency,
                    "maxQueue": self.max_queue,
                    "queued": 0,
                    "running": 0,
                }
                self._send(503, {"ok": False, "reason": "shutting_down", "queue": q})
                return
            if self.run_queue is not None:
                code, payload, headers = self.run_queue.ready_payload()
                self._send(code, payload, headers)
            else:
                q = {
                    "concurrency": self.concurrency,
                    "maxQueue": self.max_queue,
                    "queued": 0,
                    "running": 0,
                }
                self._send(200, {"ok": True, "queue": q})
            return
        if path == "/metrics":
            snap = (
                self.run_queue.metrics_snapshot()
                if self.run_queue
                else {"queued": 0, "running": 0, "completed": 0, "failed": 0}
            )
            body = render_metrics(snap).encode("utf-8")
            self._send_raw(200, body, METRICS_CONTENT_TYPE)
            return
        if path == "/openapi.json":
            try:
                raw = load_openapi_bytes(self.root)
            except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
                self._send(500, {"error": "openapi_unavailable", "detail": str(e)})
                return
            self._send_raw(200, raw, "application/json; charset=utf-8")
            return
        if path == "/v1/config":
            # Public redacted runtime config (no Bearer). Allowlist only.
            # Never webhook URL (query tokens), secret, Bearer tokens, fixtures.
            cors = self.cors
            if cors and cors.get("allow_any"):
                origins = ["*"]
            else:
                origins = list((cors or {}).get("origins") or [])
            rq = self.run_queue
            if rq is not None:
                snap = rq.snapshot()
                runs_max = rq.runs_max
            else:
                snap = {
                    "concurrency": self.concurrency,
                    "maxQueue": self.max_queue,
                    "queued": 0,
                    "running": 0,
                }
                runs_max = getattr(self.server, "runs_max", DEFAULT_RUNS_MAX)
            rate = getattr(self.server, "rate_limit", None)
            if rate is None and not hasattr(self.server, "rate_limit"):
                rate = getattr(self, "rate_limit", None)
            payload = summarize_runtime_config(
                queue=snap,
                max_queue=self.max_queue,
                cors_origins=origins,
                rate_limit=rate,
                runs_max=runs_max,
                webhook_url=self.webhook_url,
                webhook_secret=self.webhook_secret,
                suites_count=len(list_suites(self.root)),
            )
            self._send(200, payload)
            return
        if path == "/v1/runs":
            qs = parse_qs(urlparse(self.path).query)
            limit = DEFAULT_LIST_LIMIT
            if "limit" in qs and qs["limit"]:
                try:
                    limit = int(qs["limit"][0])
                except (TypeError, ValueError):
                    self._send(400, {"error": "bad_request", "detail": "limit must be an integer"})
                    return
                if limit < 0:
                    self._send(400, {"error": "bad_request", "detail": "limit must be >= 0"})
                    return
            if self.run_queue is not None:
                runs = self.run_queue.list_run_items(limit=limit)
            else:
                runs = list_runs(self.runs_dir, limit=limit)
            self._send(200, {"runs": runs, "count": len(runs)})
            return
        if path in ("/v1/runs/junit.xml", "/v1/junit.xml"):
            if self.run_queue is not None:
                records = self.run_queue.completed_records()
            else:
                records = list_completed_run_records(self.runs_dir)
            xml = runs_to_junit(records)
            self._send_raw(200, xml.encode("utf-8"), "application/xml; charset=utf-8")
            return
        if path in ("/v1/runs/tap.txt", "/v1/tap.txt"):
            if self.run_queue is not None:
                records = self.run_queue.completed_records()
            else:
                records = list_completed_run_records(self.runs_dir)
            tap = runs_to_tap(records)
            self._send_raw(200, tap.encode("utf-8"), "text/plain; charset=utf-8")
            return
        if path in ("/v1/runs/report.md", "/v1/report.md"):
            if self.run_queue is not None:
                records = self.run_queue.completed_records()
            else:
                records = list_completed_run_records(self.runs_dir)
            md = runs_to_md(records)
            self._send_raw(200, md.encode("utf-8"), "text/markdown; charset=utf-8")
            return
        if path in ("/v1/runs/report.html", "/v1/report.html"):
            if self.run_queue is not None:
                records = self.run_queue.completed_records()
            else:
                records = list_completed_run_records(self.runs_dir)
            html_body = runs_to_html(records)
            self._send_raw(200, html_body.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path in ("/v1/runs/annotations.txt", "/v1/annotations.txt"):
            if self.run_queue is not None:
                records = self.run_queue.completed_records()
            else:
                records = list_completed_run_records(self.runs_dir)
            gha = runs_to_gha(records)
            self._send_raw(200, gha.encode("utf-8"), "text/plain; charset=utf-8")
            return
        m_junit = re.fullmatch(r"/v1/runs/([0-9a-fA-F-]{8,64})/junit(?:\.xml)?", path)
        if m_junit:
            run_id = m_junit.group(1)
            rec = self.run_queue.get(run_id) if self.run_queue else load_run(run_id, self.runs_dir)
            xml = junit_xml_for_run(run_id, self.runs_dir, record=rec)
            if xml is None:
                self._send(404, {"error": "junit_not_found", "runId": run_id})
                return
            self._send_raw(200, xml.encode("utf-8"), "application/xml; charset=utf-8")
            return
        m_tap = re.fullmatch(r"/v1/runs/([0-9a-fA-F-]{8,64})/tap(?:\.txt)?", path)
        if m_tap:
            run_id = m_tap.group(1)
            rec = self.run_queue.get(run_id) if self.run_queue else load_run(run_id, self.runs_dir)
            tap = tap_txt_for_run(run_id, self.runs_dir, record=rec)
            if tap is None:
                self._send(404, {"error": "tap_not_found", "runId": run_id})
                return
            self._send_raw(200, tap.encode("utf-8"), "text/plain; charset=utf-8")
            return
        m_md = re.fullmatch(r"/v1/runs/([0-9a-fA-F-]{8,64})/(?:report\.md|md)", path)
        if m_md:
            run_id = m_md.group(1)
            rec = self.run_queue.get(run_id) if self.run_queue else load_run(run_id, self.runs_dir)
            md = md_report_for_run(run_id, self.runs_dir, record=rec)
            if md is None:
                self._send(404, {"error": "md_not_found", "runId": run_id})
                return
            self._send_raw(200, md.encode("utf-8"), "text/markdown; charset=utf-8")
            return
        m_html = re.fullmatch(r"/v1/runs/([0-9a-fA-F-]{8,64})/(?:report\.html|html)", path)
        if m_html:
            run_id = m_html.group(1)
            rec = self.run_queue.get(run_id) if self.run_queue else load_run(run_id, self.runs_dir)
            html_body = html_report_for_run(run_id, self.runs_dir, record=rec)
            if html_body is None:
                self._send(404, {"error": "html_not_found", "runId": run_id})
                return
            self._send_raw(200, html_body.encode("utf-8"), "text/html; charset=utf-8")
            return
        m_gha = re.fullmatch(r"/v1/runs/([0-9a-fA-F-]{8,64})/annotations(?:\.txt)?", path)
        if m_gha:
            run_id = m_gha.group(1)
            rec = self.run_queue.get(run_id) if self.run_queue else load_run(run_id, self.runs_dir)
            gha = gha_annotations_for_run(run_id, self.runs_dir, record=rec)
            if gha is None:
                self._send(404, {"error": "annotations_not_found", "runId": run_id})
                return
            self._send_raw(200, gha.encode("utf-8"), "text/plain; charset=utf-8")
            return
        m_diff = re.fullmatch(r"/v1/runs/([0-9a-fA-F-]{8,64})/diff(?:\.md|\.html)?", path)
        if m_diff:
            run_id = m_diff.group(1)
            qs = parse_qs(urlparse(self.path).query)
            against = (qs.get("against") or [None])[0]
            fmt = str((qs.get("format") or [""])[0] or "").strip().lower()
            suffix_html = path.endswith(".html")
            suffix_md = path.endswith(".md")
            want_html = suffix_html or (not suffix_md and fmt in ("html",))
            want_md = suffix_md or (not suffix_html and fmt in ("md", "markdown"))
            def _get(rid: str) -> dict[str, Any] | None:
                return self.run_queue.get(rid) if self.run_queue else load_run(rid, self.runs_dir)
            code, payload = diff_runs_response(run_id, against, _get)
            if code != 200:
                self._send(code, payload)
                return
            if want_html:
                html_body = diff_runs_to_html(payload)
                self._send_raw(200, html_body.encode("utf-8"), "text/html; charset=utf-8")
                return
            if want_md:
                md = diff_runs_to_md(payload)
                self._send_raw(200, md.encode("utf-8"), "text/markdown; charset=utf-8")
                return
            self._send(code, payload)
            return
        m_cases = re.fullmatch(r"/v1/runs/([0-9a-fA-F-]{8,64})/cases", path)
        if m_cases:
            run_id = m_cases.group(1)
            rec = self.run_queue.get(run_id) if self.run_queue else load_run(run_id, self.runs_dir)
            if rec is None:
                self._send(404, {"ok": False, "error": "run_not_found", "runId": run_id})
                return
            qs = parse_qs(urlparse(self.path).query)
            status_f = (qs.get("status") or [None])[0]
            self._send(200, cases_json(rec, status=status_f))
            return
        m = re.fullmatch(r"/v1/runs/([0-9a-fA-F-]{8,64})", path)
        if m:
            run_id = m.group(1)
            run = self.run_queue.get(run_id) if self.run_queue else load_run(run_id, self.runs_dir)
            if run is None:
                self._send(404, {"error": "run_not_found", "runId": run_id})
                return
            self._send(200, run)
            return
        if path == "/v1/suites":
            suites = list_suites(self.root)
            self._send(200, {"suites": suites, "count": len(suites)})
            return
        m_suite = re.fullmatch(r"/v1/suites/([A-Za-z0-9][A-Za-z0-9_-]{0,127})", path)
        if m_suite:
            suite = get_suite(m_suite.group(1), self.root)
            if suite is None:
                sid = m_suite.group(1)
                self._send(404, {"ok": False, "error": "suite_not_found", "id": sid, "name": sid})
                return
            self._send(200, suite)
            return
        self._send(404, {"error": "not_found", "path": path})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if self._rate_limit_or_reject(path):
            return
        # Local mock Check Run receiver (OSS adapter proof; not GitHub).
        if path == "/v1/check-runs":
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                parsed = json.loads(raw.decode("utf-8") or "{}")
                if not isinstance(parsed, dict):
                    self._send(400, {"error": "invalid_json", "detail": "body must be object"})
                    return
            except json.JSONDecodeError:
                self._send(400, {"error": "invalid_json"})
                return
            stored = store_check_run_post(raw, self.runs_dir)
            self._send(
                202,
                {
                    "ok": True,
                    "received": True,
                    "stored": str(stored),
                    "name": parsed.get("name"),
                    "conclusion": parsed.get("conclusion"),
                },
            )
            return

        if path != "/v1/runs":
            self._send(404, {"error": "not_found", "path": path})
            return

        if getattr(self.server, "shutting_down", False):
            q = self.run_queue.snapshot() if self.run_queue else {
                "concurrency": self.concurrency,
                "maxQueue": self.max_queue,
                "queued": 0,
                "running": 0,
            }
            self._send(503, {"ok": False, "reason": "shutting_down", "error": "shutting_down", "queue": q})
            return

        ok, err = check_auth(self.headers.get("Authorization"), require_key=self.require_key)
        if not ok:
            self._send(401, {"error": err or "unauthorized"})
            return

        try:
            body = self._read_json()
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid_json"})
            return
        except ValueError as e:
            self._send(400, {"error": "bad_request", "detail": str(e)})
            return

        if self.run_queue is None:
            self._send(500, {"error": "internal", "detail": "run queue not configured"})
            return

        code, payload, headers = self.run_queue.submit(
            body, request_id=self._resolve_request_id()
        )
        self._send(code, payload, headers)


def make_server(
    host: str = "127.0.0.1",
    port: int = 8791,
    *,
    runs_dir: Path | None = None,
    root: Path | None = None,
    require_key: bool = False,
    concurrency: int = DEFAULT_CONCURRENCY,
    max_queue: int = DEFAULT_MAX_QUEUE,
    cors_origins: list[str] | None = None,
    webhook_url: str | None = None,
    webhook_secret: str | None = None,
    watch: bool = False,
    log_json: bool = False,
    rate_limit: int | None | object = ...,
    runs_max: int | None | object = ...,
) -> ThreadingHTTPServer:
    runs = Path(runs_dir or DEFAULT_RUNS_DIR)
    hook = parse_webhook_url(webhook_url)
    secret = parse_webhook_secret(webhook_secret)
    if runs_max is ...:
        resolved_runs_max = resolve_runs_max()
    else:
        resolved_runs_max = resolve_runs_max(runs_max)
    rq = RunQueue(
        concurrency=concurrency,
        max_queue=max_queue,
        runs_dir=runs,
        root=root,
        webhook_url=hook,
        webhook_secret=secret,
        runs_max=resolved_runs_max,
    )
    cors = normalize_cors(cors_origins)
    watch_state = WatchState() if watch else None

    class BoundHandler(HostedRunnerHandler):
        pass

    BoundHandler.runs_dir = runs
    BoundHandler.root = root
    BoundHandler.require_key = require_key
    BoundHandler.run_queue = rq
    BoundHandler.concurrency = concurrency
    BoundHandler.max_queue = max_queue
    BoundHandler.cors = cors
    BoundHandler.webhook_url = hook
    BoundHandler.webhook_secret = secret
    BoundHandler.watch_state = watch_state
    BoundHandler.log_json = bool(log_json)
    if rate_limit is ...:
        resolved_limit = resolve_rate_limit()
    else:
        resolved_limit = rate_limit  # type: ignore[assignment]
    BoundHandler.rate_limit = resolved_limit
    BoundHandler.rate_limiter = SlidingWindowRateLimiter()

    server = ThreadingHTTPServer((host, port), BoundHandler)
    server.daemon_threads = True
    server.allow_reuse_address = True
    server.run_queue = rq  # type: ignore[attr-defined]
    server.watch_state = watch_state  # type: ignore[attr-defined]
    server.watch_enabled = watch  # type: ignore[attr-defined]
    server.shutting_down = False  # type: ignore[attr-defined]
    server.log_json = bool(log_json)  # type: ignore[attr-defined]
    server.rate_limit = resolved_limit  # type: ignore[attr-defined]
    server.rate_limiter = BoundHandler.rate_limiter  # type: ignore[attr-defined]
    server.cors = cors  # type: ignore[attr-defined]
    server.webhook_url = hook  # type: ignore[attr-defined]
    server.webhook_secret = secret  # type: ignore[attr-defined]
    server.runs_max = resolved_runs_max  # type: ignore[attr-defined]
    return server


def serve_forever(
    host: str = "127.0.0.1",
    port: int = 8791,
    *,
    runs_dir: Path | None = None,
    root: Path | None = None,
    require_key: bool = False,
    concurrency: int = DEFAULT_CONCURRENCY,
    max_queue: int = DEFAULT_MAX_QUEUE,
    cors_origins: list[str] | None = None,
    webhook_url: str | None = None,
    webhook_secret: str | None = None,
    watch: bool = False,
    drain_ms: int | None = None,
    log_json: bool = False,
    rate_limit: int | None | object = ...,
    runs_max: int | None | object = ...,
) -> None:
    server = make_server(
        host,
        port,
        runs_dir=runs_dir,
        root=root,
        require_key=require_key,
        concurrency=concurrency,
        max_queue=max_queue,
        cors_origins=cors_origins,
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
        watch=watch,
        log_json=log_json,
        rate_limit=rate_limit,
        runs_max=runs_max,
    )
    cors_note = ",".join(cors_origins) if cors_origins else "deny"
    hook_note = parse_webhook_url(webhook_url) or "off"
    hmac_note = "on" if parse_webhook_secret(webhook_secret) else "off"
    watch_note = ("poll %dms" % WATCH_POLL_MS) if watch else "off"
    limit_note = (
        server.rate_limit if getattr(server, "rate_limit", None) is not None else "unlimited"
    )
    rq = getattr(server, "run_queue", None)
    runs_max_val = getattr(rq, "runs_max", None) if rq is not None else None
    runs_max_note = (
        "unlimited" if not runs_max_val else runs_max_val
    )
    print(
        f"agent-ci hosted stub listening on http://{host}:{port} "
        f"(runs_dir={runs_dir or DEFAULT_RUNS_DIR} "
        f"concurrency={concurrency} max_queue={max_queue} cors={cors_note} "
        f"webhook={hook_note} hmac={hmac_note} watch={watch_note} "
        f"rate_limit_per_minute={limit_note} runs_max={runs_max_note})",
        flush=True,
    )
    stop = threading.Event()
    server.watch_stop = stop  # type: ignore[attr-defined]
    if watch:
        start_fixtures_watch(
            fixtures_root(root),
            watch_state=getattr(server, "watch_state", None),
            stop_event=stop,
        )
    drain = resolve_drain_ms(drain_ms)
    started = threading.Event()

    def _begin() -> None:
        if started.is_set():
            return
        started.set()
        begin_shutdown(server)
        print("shutting down", flush=True)
        stop.set()

        def _later() -> None:
            time.sleep(drain / 1000.0)
            try:
                server.shutdown()
            except Exception:
                pass

        threading.Thread(target=_later, name="shutdown-drain", daemon=True).start()

    def _on_signal(signum: int, frame: Any) -> None:
        _begin()

    try:
        signal.signal(signal.SIGTERM, _on_signal)
        signal.signal(signal.SIGINT, _on_signal)
    except (ValueError, OSError):
        pass
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        _begin()
    finally:
        stop.set()
        rq = getattr(server, "run_queue", None)
        if rq is not None:
            rq.shutdown()
        print("exit", flush=True)
        server.server_close()


def start_background(
    host: str = "127.0.0.1",
    port: int = 8791,
    *,
    runs_dir: Path | None = None,
    root: Path | None = None,
    concurrency: int = DEFAULT_CONCURRENCY,
    max_queue: int = DEFAULT_MAX_QUEUE,
    cors_origins: list[str] | None = None,
    webhook_url: str | None = None,
    webhook_secret: str | None = None,
    watch: bool = False,
    rate_limit: int | None | object = ...,
    runs_max: int | None | object = ...,
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Helper for tests; returns (server, thread)."""
    server = make_server(
        host,
        port,
        runs_dir=runs_dir,
        root=root,
        concurrency=concurrency,
        max_queue=max_queue,
        cors_origins=cors_origins,
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
        watch=watch,
        rate_limit=rate_limit,
        runs_max=runs_max,
    )
    stop = threading.Event()
    server.watch_stop = stop  # type: ignore[attr-defined]
    if watch:
        start_fixtures_watch(
            fixtures_root(root),
            watch_state=getattr(server, "watch_state", None),
            stop_event=stop,
        )
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, t
