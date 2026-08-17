#!/usr/bin/env python3
"""Parse-only check for deploy/grafana dashboard JSON (no Grafana process).

Loads each *.json dashboard, requires Grafana 9/10 shape (`panels`,
`schemaVersion` ~38, `title`), at least 5 panels, a Prometheus datasource
template, and every PromQL `expr` to name a metric that appears in B-F
bet metric source files (stdlib json + grep of those files; no Grafana).

`oss-cash-lab.json` is the combined B-F portfolio dashboard (5 row
panels, cross-bet required metrics, a B deny/error metric). Other JSON
files (e.g. `e-otel-ai-cost.json`) are dedicated bet dashboards: same
parse/schema/PromQL-in-source checks, without the portfolio row/deny
requirements.
"""
from __future__ import annotations

import json
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

# PromQL keywords / functions — not metric names.
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

# Must appear across dashboard exprs (only if they exist in bet source).
REQUIRED_IF_PRESENT = (
    "http_requests_total",
    "circuit_open_total",
    "agent_ci_queue_depth",
    "ai_bom_policy_hits",
    "otel_ai_cost_total_usd",
    "cn_work_agent_approvals_pending",
)

DENY_METRICS = (
    "rate_limited_total",
    "ip_denied_total",
    "body_too_large_total",
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
    # Keep Prometheus-looking names (underscore, not a PromQL word).
    return {
        n
        for n in names
        if "_" in n and n.lower() not in PROMQL_WORDS and not n.startswith("_")
    }


def expr_metrics(expr: str) -> set[str]:
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


def walk_panels(panels) -> list[dict]:
    found: list[dict] = []
    if not isinstance(panels, list):
        return found
    for p in panels:
        if not isinstance(p, dict):
            continue
        found.append(p)
        nested = p.get("panels")
        if isinstance(nested, list) and nested:
            found.extend(walk_panels(nested))
    return found


def collect_exprs(panel: dict) -> list[str]:
    exprs: list[str] = []
    targets = panel.get("targets")
    if not isinstance(targets, list):
        return exprs
    for t in targets:
        if not isinstance(t, dict):
            continue
        expr = t.get("expr")
        if isinstance(expr, str) and expr.strip():
            exprs.append(expr.strip())
    return exprs


def require_datasource_template(dash: dict, path: Path) -> None:
    templating = dash.get("templating")
    if not isinstance(templating, dict):
        fail(f"{path.name}: missing templating")
    items = templating.get("list")
    if not isinstance(items, list) or not items:
        fail(f"{path.name}: templating.list empty")
    ok = False
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "datasource" and item.get("query") == "prometheus":
            ok = True
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                fail(f"{path.name}: datasource variable missing name")
    if not ok:
        fail(f"{path.name}: need templating datasource query=prometheus")


PORTFOLIO_DASHBOARD = "oss-cash-lab.json"


def check_dashboard(path: Path, known: set[str], source_blob: str, *, portfolio: bool) -> None:
    try:
        dash = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        fail(f"{path.name}: JSON parse error: {e}")
    if not isinstance(dash, dict):
        fail(f"{path.name}: expected object")
    title = dash.get("title")
    if not isinstance(title, str) or not title.strip():
        fail(f"{path.name}: missing title")
    schema = dash.get("schemaVersion")
    if not isinstance(schema, int) or schema < 36 or schema > 42:
        fail(f"{path.name}: schemaVersion {schema!r} not Grafana 9/10 (~38)")
    panels = dash.get("panels")
    if not isinstance(panels, list) or len(panels) < 5:
        n = len(panels) if isinstance(panels, list) else 0
        fail(f"{path.name}: panels len {n} < 5")
    require_datasource_template(dash, path)

    flat = walk_panels(panels)
    exprs: list[str] = []
    used: set[str] = set()
    for p in flat:
        for expr in collect_exprs(p):
            exprs.append(expr)
            mets = expr_metrics(expr)
            if not mets:
                fail(f"{path.name}: expr has no metric name: {expr!r}")
            missing = sorted(m for m in mets if m not in known)
            if missing:
                fail(
                    f"{path.name}: PromQL names not in bet metric source: "
                    f"{missing} (expr={expr!r})"
                )
            for m in mets:
                if m not in source_blob:
                    fail(f"{path.name}: metric {m} not grepped in bet source")
            used.update(mets)

    if len(exprs) < 5:
        fail(f"{path.name}: need >=5 PromQL expr, got {len(exprs)}")

    if portfolio:
        present_required = [m for m in REQUIRED_IF_PRESENT if m in known]
        missing_req = [m for m in present_required if m not in used]
        if missing_req:
            fail(f"{path.name}: dashboard missing required metrics {missing_req}")
        deny_used = [m for m in DENY_METRICS if m in used]
        if not deny_used:
            fail(
                f"{path.name}: need at least one deny/error metric "
                f"({', '.join(DENY_METRICS)})"
            )

        rows = [p for p in flat if p.get("type") == "row"]
        if len(rows) < 5:
            fail(f"{path.name}: need 5 row panels (B/C/D/E/F), got {len(rows)}")

    print(
        f"  ok {path.name}  title={title!r}  schemaVersion={schema}  "
        f"panels={len(panels)}  expr={len(exprs)}  metrics={len(used)}"
        f"{'  portfolio' if portfolio else '  dedicated'}"
    )


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
    grafana = root / "deploy" / "grafana"
    if not grafana.is_dir():
        fail(f"missing {grafana}")
    json_files = sorted(p for p in grafana.glob("*.json") if p.is_file())
    if not json_files:
        fail(f"no dashboard JSON under {grafana}")
    known = load_source_metrics(root)
    if len(known) < 10:
        fail(f"too few metric names from bet source: {sorted(known)}")
    blob = "\n".join((root / rel).read_text(encoding="utf-8") for rel in METRIC_SOURCES)
    for path in json_files:
        check_dashboard(
            path, known, blob, portfolio=(path.name == PORTFOLIO_DASHBOARD)
        )
    print(f"grafana dashboards ok ({len(json_files)} json, {len(known)} source metrics)")


if __name__ == "__main__":
    main()
