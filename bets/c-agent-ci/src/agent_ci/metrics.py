"""Prometheus text exposition of local run-queue gauges/counters (stdlib only)."""

from __future__ import annotations

from typing import Any, Mapping

METRIC_QUEUE_DEPTH = "agent_ci_queue_depth"
METRIC_RUNNING = "agent_ci_running"
METRIC_COMPLETED = "agent_ci_runs_completed_total"
METRIC_FAILED = "agent_ci_runs_failed_total"

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

# Gauges: current queue depth + in-flight workers.
# Counters: runs that reached done | error (process lifetime; not persisted).


def _nonneg_int(n: Any) -> int:
    try:
        x = int(n)
    except (TypeError, ValueError):
        return 0
    return x if x >= 0 else 0


def render_metrics(snapshot: Mapping[str, Any] | None = None) -> str:
    """Prometheus 0.0.4 text for a queue snapshot.

    Gauges: `agent_ci_queue_depth`, `agent_ci_running`.
    Counters: `agent_ci_runs_completed_total`, `agent_ci_runs_failed_total`.
    """
    snap = snapshot or {}
    queued = _nonneg_int(snap.get("queued"))
    running = _nonneg_int(snap.get("running"))
    completed = _nonneg_int(snap.get("completed"))
    failed = _nonneg_int(snap.get("failed"))
    lines = [
        f"# HELP {METRIC_QUEUE_DEPTH} Number of runs waiting in the local in-memory queue",
        f"# TYPE {METRIC_QUEUE_DEPTH} gauge",
        f"{METRIC_QUEUE_DEPTH} {queued}",
        f"# HELP {METRIC_RUNNING} Number of runs currently executing",
        f"# TYPE {METRIC_RUNNING} gauge",
        f"{METRIC_RUNNING} {running}",
        f"# HELP {METRIC_COMPLETED} Total runs that reached status=done",
        f"# TYPE {METRIC_COMPLETED} counter",
        f"{METRIC_COMPLETED} {completed}",
        f"# HELP {METRIC_FAILED} Total runs that reached status=error",
        f"# TYPE {METRIC_FAILED} counter",
        f"{METRIC_FAILED} {failed}",
        "",
    ]
    return "\n".join(lines)
