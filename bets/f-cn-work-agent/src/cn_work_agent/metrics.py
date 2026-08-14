"""Prometheus text exposition of approval/webhook gauges/counters (stdlib only)."""

from __future__ import annotations

import threading
from typing import Any, Mapping

METRIC_PENDING = "cn_work_agent_approvals_pending"
METRIC_DECIDED = "cn_work_agent_approvals_decided_total"
METRIC_WEBHOOKS = "cn_work_agent_webhooks_total"

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

# Gauge: current pending rows in the local JSONL (no expire_due on scrape).
# Counters: decided (approve/reject/TTL expire) + outbound webhook attempts
# (process lifetime; not persisted).


def _nonneg_int(n: Any) -> int:
    try:
        x = int(n)
    except (TypeError, ValueError):
        return 0
    return x if x >= 0 else 0


class Metrics:
    """Process-lifetime decided + webhook counters. Pending is supplied at render."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._decided = 0
        self._webhooks = 0

    def add_decided(self, n: int = 1) -> None:
        if n <= 0:
            return
        with self._lock:
            self._decided += n

    def add_webhooks(self, n: int = 1) -> None:
        if n <= 0:
            return
        with self._lock:
            self._webhooks += n

    def snapshot(self, pending: int = 0) -> dict[str, int]:
        with self._lock:
            return {
                "pending": _nonneg_int(pending),
                "decided": self._decided,
                "webhooks": self._webhooks,
            }


def render_metrics(snapshot: Mapping[str, Any] | None = None) -> str:
    """Prometheus 0.0.4 text for approval/webhook snapshot.

    Gauge: `cn_work_agent_approvals_pending`.
    Counters: `cn_work_agent_approvals_decided_total`, `cn_work_agent_webhooks_total`.
    """
    snap = snapshot or {}
    pending = _nonneg_int(snap.get("pending"))
    decided = _nonneg_int(snap.get("decided"))
    webhooks = _nonneg_int(snap.get("webhooks"))
    lines = [
        f"# HELP {METRIC_PENDING} Number of pending approvals in the local JSONL",
        f"# TYPE {METRIC_PENDING} gauge",
        f"{METRIC_PENDING} {pending}",
        f"# HELP {METRIC_DECIDED} Total approvals decided (approve/reject/TTL expire)",
        f"# TYPE {METRIC_DECIDED} counter",
        f"{METRIC_DECIDED} {decided}",
        f"# HELP {METRIC_WEBHOOKS} Total outbound approval-decision webhook attempts",
        f"# TYPE {METRIC_WEBHOOKS} counter",
        f"{METRIC_WEBHOOKS} {webhooks}",
        "",
    ]
    return "\n".join(lines)
