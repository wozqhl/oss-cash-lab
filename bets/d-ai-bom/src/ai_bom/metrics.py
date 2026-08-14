"""Prometheus text exposition of the BOM scan snapshot (stdlib only)."""

from __future__ import annotations

from typing import Any, Mapping

METRIC_COMPONENT_COUNT = "ai_bom_component_count"
METRIC_POLICY_HITS = "ai_bom_policy_hits"
METRIC_FORBIDDEN_LICENSES = "ai_bom_forbidden_licenses"

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

# Gauges: snapshot counts from the last scan (process start, or last --watch rescan).


def _nonneg_int(n: Any) -> int:
    try:
        x = int(n)
    except (TypeError, ValueError):
        return 0
    return x if x >= 0 else 0


def _counts(snapshot: Mapping[str, Any] | None) -> tuple[int, int, int]:
    """componentCount, policyHits, forbiddenLicenses from a BOM or health-like dict."""
    snap: Mapping[str, Any] = snapshot or {}
    nested = snap.get("bom")
    if isinstance(nested, dict):
        snap = nested
    if "components" in snap or "summary" in snap:
        components = snap.get("components") or []
        summary = snap.get("summary") or {}
        component_count = len(components) if isinstance(components, list) else _nonneg_int(components)
        policy_hits = _nonneg_int(summary.get("policyHits", 0))
        forbidden = summary.get("forbiddenLicenses") or []
        forbidden_licenses = (
            len(forbidden) if isinstance(forbidden, list) else _nonneg_int(forbidden)
        )
        return component_count, policy_hits, forbidden_licenses
    component_count = _nonneg_int(snap.get("componentCount", 0))
    policy_hits = _nonneg_int(snap.get("policyHits", 0))
    forbidden = snap.get("forbiddenLicenses", 0)
    if isinstance(forbidden, list):
        forbidden_licenses = len(forbidden)
    else:
        forbidden_licenses = _nonneg_int(forbidden)
    return component_count, policy_hits, forbidden_licenses


def render_metrics(snapshot: Mapping[str, Any] | None = None) -> str:
    """Prometheus 0.0.4 text for a BOM scan snapshot.

    Gauges: `ai_bom_component_count`, `ai_bom_policy_hits`, `ai_bom_forbidden_licenses`.
    """
    component_count, policy_hits, forbidden_licenses = _counts(snapshot)
    lines = [
        f"# HELP {METRIC_COMPONENT_COUNT} Number of components in the BOM snapshot",
        f"# TYPE {METRIC_COMPONENT_COUNT} gauge",
        f"{METRIC_COMPONENT_COUNT} {component_count}",
        f"# HELP {METRIC_POLICY_HITS} Policy hits (forbidden patterns + disclosure gaps + forbidden licenses)",
        f"# TYPE {METRIC_POLICY_HITS} gauge",
        f"{METRIC_POLICY_HITS} {policy_hits}",
        f"# HELP {METRIC_FORBIDDEN_LICENSES} Forbidden-license hits in the BOM snapshot",
        f"# TYPE {METRIC_FORBIDDEN_LICENSES} gauge",
        f"{METRIC_FORBIDDEN_LICENSES} {forbidden_licenses}",
        "",
    ]
    return "\n".join(lines)
