#!/usr/bin/env python3
"""Parse-only check for Prometheus alerting rules (no Prometheus process).

Loads deploy/prometheus/rules.yaml (plain groups) and
deploy/k8s/prometheusrule.yaml (PrometheusRule CRD wrapping the same groups).
Requires >=6 alerts with alert/expr/for/labels.severity/annotations.summary,
and every PromQL expr to name a metric that appears in B-F bet metric source
(stdlib yaml subset or PyYAML + grep of those files; no Prometheus).
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

METRIC_SOURCES = (
    "bets/b-mcp-gateway/src/metrics.js",
    "bets/c-agent-ci/src/agent_ci/metrics.py",
    "bets/d-ai-bom/src/ai_bom/metrics.py",
    "bets/e-otel-ai-cost/src/metrics.js",
    "bets/f-cn-work-agent/src/cn_work_agent/metrics.py",
)

# PromQL keywords / functions — not metric names. Same list as check-grafana.py.
PROMQL_WORDS = {
    "abs", "absent", "absent_over_time", "and", "avg", "avg_over_time",
    "bool", "bottomk", "by", "ceil", "changes", "clamp", "clamp_max",
    "clamp_min", "count", "count_over_time", "day_of_month", "day_of_week",
    "days_in_month", "delta", "deriv", "exp", "floor", "group", "group_left",
    "group_right", "histogram_quantile", "holt_winters", "hour", "idelta",
    "ignoring", "increase", "inf", "irate", "label_join", "label_replace",
    "last_over_time", "ln", "log10", "log2", "max", "max_over_time", "min",
    "min_over_time", "minute", "month", "nan", "offset", "on", "or", "pi",
    "predict_linear", "present_over_time", "quantile", "quantile_over_time",
    "rate", "resets", "round", "scalar", "sort", "sort_desc", "sqrt",
    "stddev", "stddev_over_time", "stdvar", "stdvar_over_time", "sum",
    "sum_over_time", "time", "timestamp", "topk", "unless", "vector",
    "without", "year",
}

REQUIRED_ALERTS = (
    "McpGatewayCircuitOpen",
    "McpGatewayRateLimited",
    "AgentCiQueueBacklog",
    "AgentCiRunFailures",
    "AiBomForbiddenLicense",
    "AiBomPolicyHits",
    "OtelAiCostHigh",
    "CnWorkApprovalsStuck",
)

IDENT_RE = re.compile(r"[a-zA-Z_:][a-zA-Z0-9_:]*")
BRACE_RE = re.compile(r"\{[^{}]*\}")
RANGE_RE = re.compile(r"\[[0-9]+[smhdwy]+\]")
GROUP_RE = re.compile(r"\b(?:by|without|on|ignoring)\s*\([^)]*\)", re.I)
TYPE_RE = re.compile(r"# TYPE\s+([a-zA-Z_:][a-zA-Z0-9_:]*)")
HELP_RE = re.compile(r"# HELP\s+([a-zA-Z_:][a-zA-Z0-9_:]*)")
FORMAT_RE = re.compile(r'formatCounter\(\s*"([a-zA-Z_:][a-zA-Z0-9_:]*)"')
ASSIGN_RE = re.compile(r'METRIC_[A-Z0-9_]+\s*=\s*"([a-zA-Z_:][a-zA-Z0-9_:]*)"')
BACKTICK_RE = re.compile(r"`([a-zA-Z_:][a-zA-Z0-9_:]*)`")
LITERAL_RE = re.compile(r'"([a-z][a-z0-9]+(?:_[a-z0-9]+)+)"')
FOR_RE = re.compile(r"^[0-9]+[smhd]$")


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def load_source_metrics(root: Path) -> set[str]:
    names: set[str] = set()
    for rel in METRIC_SOURCES:
        path = root / rel
        if not path.is_file():
            fail(f"missing metric source {rel}")
        text = path.read_text(encoding="utf-8")
        for rx in (TYPE_RE, HELP_RE, FORMAT_RE, ASSIGN_RE, BACKTICK_RE, LITERAL_RE):
            names.update(rx.findall(text))
    return {
        n
        for n in names
        if "_" in n and n.lower() not in PROMQL_WORDS and not n.startswith("_")
    }


def expr_metrics(expr: str) -> set[str]:
    """Strip by()/without() / {labels} / [range] / increase() wrappers."""
    stripped = BRACE_RE.sub(" ", expr)
    stripped = GROUP_RE.sub(" ", stripped)
    stripped = RANGE_RE.sub(" ", stripped)
    out: set[str] = set()
    for tok in IDENT_RE.findall(stripped):
        low = tok.lower()
        if low in PROMQL_WORDS:
            continue
        if tok.startswith("__"):
            continue
        out.add(tok)
    return out


def load_docs(text: str):
    try:
        import yaml  # type: ignore
    except ImportError:
        k8s_path = Path(__file__).resolve().parent / "check-k8s.py"
        spec = importlib.util.spec_from_file_location("check_k8s", k8s_path)
        if spec is None or spec.loader is None:
            fail("cannot load check-k8s.py subset parser")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.load_docs(text)
    docs = [d for d in yaml.safe_load_all(text) if d is not None]
    return docs, "pyyaml"


def collect_alerts(groups, origin: str) -> list[dict]:
    if not isinstance(groups, list) or not groups:
        fail(f"{origin}: groups must be a non-empty list")
    alerts: list[dict] = []
    for i, g in enumerate(groups):
        if not isinstance(g, dict):
            fail(f"{origin}: groups[{i}] must be a mapping")
        name = g.get("name")
        if not isinstance(name, str) or not name.strip():
            fail(f"{origin}: groups[{i}] missing name")
        rules = g.get("rules")
        if not isinstance(rules, list) or not rules:
            fail(f"{origin}: group {name!r} missing rules")
        for j, rule in enumerate(rules):
            if not isinstance(rule, dict):
                fail(f"{origin}: group {name!r} rules[{j}] must be a mapping")
            if "record" in rule:
                continue
            alert = rule.get("alert")
            expr = rule.get("expr")
            for_ = rule.get("for")
            labels = rule.get("labels")
            annotations = rule.get("annotations")
            if not isinstance(alert, str) or not alert.strip():
                fail(f"{origin}: group {name!r} rules[{j}] missing alert")
            if not isinstance(expr, str) or not expr.strip():
                fail(f"{origin}: {alert}: missing expr")
            if not isinstance(for_, str) or not FOR_RE.match(for_):
                fail(f"{origin}: {alert}: for must look like 5m (got {for_!r})")
            if not isinstance(labels, dict) or not labels:
                fail(f"{origin}: {alert}: missing labels")
            sev = labels.get("severity")
            if not isinstance(sev, str) or not sev.strip():
                fail(f"{origin}: {alert}: missing labels.severity")
            if not isinstance(annotations, dict) or not annotations:
                fail(f"{origin}: {alert}: missing annotations")
            summary = annotations.get("summary")
            if not isinstance(summary, str) or not summary.strip():
                fail(f"{origin}: {alert}: missing annotations.summary")
            alerts.append(
                {
                    "group": name,
                    "alert": alert,
                    "expr": expr.strip(),
                    "for": for_,
                    "severity": sev,
                    "summary": summary,
                }
            )
    return alerts


def fingerprint(alerts: list[dict]) -> list[tuple[str, str, str]]:
    return sorted((a["alert"], a["expr"], a["for"]) for a in alerts)


def check_exprs(alerts: list[dict], known: set[str], source_blob: str, origin: str) -> set[str]:
    used: set[str] = set()
    for a in alerts:
        mets = expr_metrics(a["expr"])
        if not mets:
            fail(f"{origin}: {a['alert']}: expr has no metric name: {a['expr']!r}")
        missing = sorted(m for m in mets if m not in known)
        if missing:
            fail(
                f"{origin}: {a['alert']}: PromQL names not in bet metric source: "
                f"{missing} (expr={a['expr']!r})"
            )
        for m in mets:
            if m not in source_blob:
                fail(f"{origin}: {a['alert']}: metric {m} not grepped in bet source")
        used.update(mets)
    return used


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
    plain_path = root / "deploy" / "prometheus" / "rules.yaml"
    crd_path = root / "deploy" / "k8s" / "prometheusrule.yaml"
    if not plain_path.is_file():
        fail(f"missing {plain_path}")
    if not crd_path.is_file():
        fail(f"missing {crd_path}")

    known = load_source_metrics(root)
    if len(known) < 10:
        fail(f"too few metric names from bet source: {sorted(known)}")
    blob = "\n".join((root / rel).read_text(encoding="utf-8") for rel in METRIC_SOURCES)

    try:
        plain_docs, plain_engine = load_docs(plain_path.read_text(encoding="utf-8"))
    except Exception as e:
        fail(f"{plain_path.name}: parse error: {e}")
    if len(plain_docs) != 1 or not isinstance(plain_docs[0], dict):
        fail(f"{plain_path.name}: expected one mapping document")
    if "kind" in plain_docs[0]:
        fail(f"{plain_path.name}: must be plain groups, not a Kubernetes object")
    groups = plain_docs[0].get("groups")
    plain_alerts = collect_alerts(groups, plain_path.name)

    try:
        crd_docs, crd_engine = load_docs(crd_path.read_text(encoding="utf-8"))
    except Exception as e:
        fail(f"{crd_path.name}: parse error: {e}")
    crds = [d for d in crd_docs if isinstance(d, dict) and d.get("kind") == "PrometheusRule"]
    if len(crds) != 1:
        fail(f"{crd_path.name}: expected 1 PrometheusRule (got {len(crds)})")
    crd = crds[0]
    api = crd.get("apiVersion")
    if api != "monitoring.coreos.com/v1":
        fail(f"{crd_path.name}: apiVersion must be monitoring.coreos.com/v1 (got {api!r})")
    crd_groups = crd.get("spec", {}).get("groups") if isinstance(crd.get("spec"), dict) else None
    crd_alerts = collect_alerts(crd_groups, crd_path.name)

    if len(plain_alerts) < 6:
        fail(f"{plain_path.name}: need >=6 alerts, got {len(plain_alerts)}")
    if fingerprint(plain_alerts) != fingerprint(crd_alerts):
        fail(
            f"{crd_path.name} groups must match {plain_path.name} "
            f"(alert/expr/for). plain={fingerprint(plain_alerts)} "
            f"crd={fingerprint(crd_alerts)}"
        )

    used = check_exprs(plain_alerts, known, blob, plain_path.name)
    check_exprs(crd_alerts, known, blob, crd_path.name)

    names = {a["alert"] for a in plain_alerts}
    missing_req = [n for n in REQUIRED_ALERTS if n not in names]
    if missing_req:
        fail(f"missing required alerts: {missing_req}")

    print(
        f"  ok {plain_path.name}  groups={len(groups)}  alerts={len(plain_alerts)}  "
        f"metrics={len(used)}  parser={plain_engine}"
    )
    print(
        f"  ok {crd_path.name}  PrometheusRule  alerts={len(crd_alerts)}  "
        f"parser={crd_engine}"
    )
    print(
        f"prometheus rules ok ({len(plain_alerts)} alerts, {len(used)} metrics, "
        f"{len(known)} source metrics)"
    )


if __name__ == "__main__":
    main()
