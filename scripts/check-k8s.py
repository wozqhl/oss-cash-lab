#!/usr/bin/env python3
"""Parse-only check for deploy/k8s manifests (no cluster).

Prefers PyYAML yaml.safe_load_all when installed; otherwise a tiny indent-based
subset parser (mappings / sequences / scalars; no anchors, tags, or flow).
Asserts each B–F file has a Deployment + Service, probes /health and /ready,
and terminationGracePeriodSeconds >= 10. kustomization.yaml is parsed but
skipped for Deployment/Service asserts (kind: Kustomization).
servicemonitor.yaml is parsed as YAML only (Prometheus Operator CRDs are not
required): kind ServiceMonitor, path /metrics, 5 monitors (or 5 endpoints).
prometheusrule.yaml is parsed as YAML only: kind PrometheusRule, spec.groups
present; not listed in kustomization.yaml (CRD, like ServiceMonitor).
networkpolicy.yaml is a built-in networking.k8s.io/v1 resource (listed in
kustomization.yaml): 5 NetworkPolicies, policyTypes Ingress+Egress, podSelector
matches a B–F app.oss-cash-lab.dev/<bet> label, egress includes port 53 or 443.
pdb.yaml is a built-in policy/v1 resource (listed in kustomization.yaml): 5
PodDisruptionBudgets, selector matchLabels match B–F, maxUnavailable or
minAvailable set (static YAML uses maxUnavailable: 1 so replica=1 can drain).
hpa.yaml is a built-in autoscaling/v2 resource (listed in kustomization.yaml):
5 HorizontalPodAutoscalers, minReplicas <= maxReplicas, CPU utilization
target, scaleTargetRef kind Deployment named B–F. Needs metrics-server to
scale; objects sit idle without it (replica=1 unchanged).
ingress.yaml is a built-in networking.k8s.io/v1 resource (listed in
kustomization.yaml): 1 Ingress, 5 hosts or 5 rules, backends match B–F
Service names, ingressClassName nginx. Needs an ingress controller
(ingress-nginx or similar); without it the object sits idle. TLS omitted.
limitrange.yaml is a built-in v1 resource (listed in kustomization.yaml):
1 LimitRange, type Container, defaultRequest.cpu set so omitted containers
still get a request (HPA denominator) and default limits (noisy-neighbor).
Does not change Deployments that already set resources.
resourcequota.yaml is a built-in v1 resource (listed in kustomization.yaml):
1 ResourceQuota, spec.hard.pods set. Namespace hard caps sized for B–F ×
HPA maxReplicas 4 plus headroom so the demo namespace cannot unbounded-scale.
Pairs with LimitRange. Floor >= replica=1 Deployment requests.
B–F Deployments also set restricted-ish pod+container securityContext
(runAsNonRoot, numeric runAsUser matching Dockerfile USER, drop ALL,
allowPrivilegeEscalation false, readOnlyRootFilesystem + emptyDir /tmp).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

EXPECTED = [
    ("b-mcp-gateway.yaml", "b-mcp-gateway", 8787),
    ("c-agent-ci.yaml", "c-agent-ci", 8791),
    ("d-ai-bom.yaml", "d-ai-bom", 8793),
    ("e-otel-ai-cost.yaml", "e-otel-ai-cost", 8792),
    ("f-cn-work-agent.yaml", "f-cn-work-agent", 8790),
]

SERVICEMONITOR = "servicemonitor.yaml"
PROMETHEUSRULE = "prometheusrule.yaml"
NETWORKPOLICY = "networkpolicy.yaml"
PDB = "pdb.yaml"
HPA = "hpa.yaml"
INGRESS = "ingress.yaml"
LIMITRANGE = "limitrange.yaml"
RESOURCEQUOTA = "resourcequota.yaml"
KNOWN_YAML = {f for f, _, _ in EXPECTED} | {
    "kustomization.yaml",
    SERVICEMONITOR,
    PROMETHEUSRULE,
    NETWORKPOLICY,
    PDB,
    HPA,
    INGRESS,
    LIMITRANGE,
    RESOURCEQUOTA,
}


class ParseError(Exception):
    pass


def strip_inline_comment(line: str) -> str:
    in_s = in_d = False
    esc = False
    out = []
    for c in line:
        if esc:
            out.append(c)
            esc = False
            continue
        if c == "\\" and in_d:
            out.append(c)
            esc = True
            continue
        if c == "'" and not in_d:
            in_s = not in_s
            out.append(c)
            continue
        if c == '"' and not in_s:
            in_d = not in_d
            out.append(c)
            continue
        if c == "#" and not in_s and not in_d:
            break
        out.append(c)
    return "".join(out).rstrip()


def parse_scalar(raw: str):
    raw = raw.strip()
    if raw == "" or raw in ("null", "~", "Null", "NULL"):
        return None
    if raw in ("true", "True", "TRUE"):
        return True
    if raw in ("false", "False", "FALSE"):
        return False
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"):
        inner = raw[1:-1]
        if raw[0] == '"':
            inner = (
                inner.replace("\\\\", "\0")
                .replace("\\n", "\n")
                .replace("\\t", "\t")
                .replace('\\"', '"')
                .replace("\0", "\\")
            )
        return inner
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    return raw


def split_key(content: str):
    if content[:1] in ('"', "'"):
        q = content[0]
        end = 1
        while end < len(content) and content[end] != q:
            end += 1
        key = content[1:end]
        rest = content[end + 1 :].lstrip()
        if not rest.startswith(":"):
            raise ParseError(f"bad quoted key: {content!r}")
        return key, rest[1:]
    idx = content.index(":")
    return content[:idx], content[idx + 1 :]


def looks_like_map_entry(item_raw: str) -> bool:
    if not item_raw or item_raw[:1] in ('"', "'"):
        return False
    if ": " in item_raw or item_raw.rstrip().endswith(":"):
        key = item_raw.split(":", 1)[0]
        return key.strip() != ""
    return False


def tokenize_lines(text: str):
    rows = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        stripped = strip_inline_comment(raw)
        if not stripped.strip():
            continue
        lead = stripped[: len(stripped) - len(stripped.lstrip(" "))]
        if "\t" in lead or stripped.lstrip().startswith("\t"):
            raise ParseError(f"line {lineno}: tabs not supported in subset parser")
        indent = len(stripped) - len(stripped.lstrip(" "))
        content = stripped[indent:]
        rows.append((lineno, indent, content))
    return rows


def nonempty_chunk(text: str) -> bool:
    for line in text.splitlines():
        if strip_inline_comment(line).strip():
            return True
    return False


def parse_value_block(rows, i, min_indent):
    if i >= len(rows):
        return None, i
    _, indent, content = rows[i]
    if indent < min_indent:
        return None, i
    if content.startswith("- ") or content == "-":
        return parse_seq(rows, i, indent)
    return parse_map(rows, i, indent)


def parse_map(rows, i, indent):
    result = {}
    while i < len(rows):
        lineno, ind, content = rows[i]
        if ind < indent:
            break
        if ind > indent:
            raise ParseError(f"line {lineno}: unexpected indent in mapping")
        if content.startswith("- ") or content == "-":
            break
        if ":" not in content:
            raise ParseError(f"line {lineno}: expected key: {content!r}")
        key, rest = split_key(content)
        rest = rest.strip()
        if rest:
            result[key] = parse_scalar(rest)
            i += 1
        elif i + 1 < len(rows) and rows[i + 1][1] > indent:
            val, i = parse_value_block(rows, i + 1, indent + 1)
            result[key] = val
        else:
            result[key] = None
            i += 1
    return result, i


def parse_seq(rows, i, indent):
    result = []
    item_key_indent = indent + 2
    while i < len(rows):
        lineno, ind, content = rows[i]
        if ind < indent:
            break
        if ind > indent:
            raise ParseError(f"line {lineno}: unexpected indent in sequence")
        if not (content.startswith("- ") or content == "-"):
            break
        item_raw = "" if content == "-" else content[2:]
        if item_raw == "":
            if i + 1 < len(rows) and rows[i + 1][1] > indent:
                val, i = parse_value_block(rows, i + 1, indent + 1)
                result.append(val)
            else:
                result.append(None)
                i += 1
            continue
        if looks_like_map_entry(item_raw):
            key, rest = split_key(item_raw)
            rest = rest.strip()
            m = {}
            if rest:
                m[key] = parse_scalar(rest)
                i += 1
            elif i + 1 < len(rows) and rows[i + 1][1] > indent:
                val, i = parse_value_block(rows, i + 1, item_key_indent)
                m[key] = val
            else:
                m[key] = None
                i += 1
            while i < len(rows):
                ln, ind2, c2 = rows[i]
                if ind2 < item_key_indent:
                    break
                if c2.startswith("- ") or c2 == "-":
                    break
                if ind2 != item_key_indent:
                    raise ParseError(f"line {ln}: bad list-item continuation indent")
                k2, r2 = split_key(c2)
                r2 = r2.strip()
                if r2:
                    m[k2] = parse_scalar(r2)
                    i += 1
                elif i + 1 < len(rows) and rows[i + 1][1] > item_key_indent:
                    val, i = parse_value_block(rows, i + 1, item_key_indent + 1)
                    m[k2] = val
                else:
                    m[k2] = None
                    i += 1
            result.append(m)
        else:
            result.append(parse_scalar(item_raw))
            i += 1
    return result, i


def parse_document(text: str):
    rows = tokenize_lines(text)
    if not rows:
        return None
    obj, nxt = parse_value_block(rows, 0, rows[0][1])
    if nxt != len(rows):
        raise ParseError(f"trailing content at line {rows[nxt][0]}")
    return obj


def subset_load_all(text: str):
    chunks = []
    cur = []
    for line in text.splitlines(keepends=True):
        if line.strip() == "---":
            if cur:
                chunks.append("".join(cur))
                cur = []
            continue
        cur.append(line)
    if cur:
        chunks.append("".join(cur))
    docs = []
    for ch in chunks:
        if not nonempty_chunk(ch):
            continue
        docs.append(parse_document(ch))
    return docs


def load_docs(text: str):
    try:
        import yaml  # type: ignore
    except ImportError:
        return subset_load_all(text), "subset"
    docs = [d for d in yaml.safe_load_all(text) if d is not None]
    return docs, "pyyaml"


def get_in(obj, *path, default=None):
    cur = obj
    for p in path:
        if isinstance(p, int):
            if not isinstance(cur, list) or p >= len(cur) or p < 0:
                return default
            cur = cur[p]
        else:
            if not isinstance(cur, dict) or p not in cur:
                return default
            cur = cur[p]
    return cur


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def check_service_file(path: Path, bet: str, port: int) -> str:
    text = path.read_text(encoding="utf-8")
    try:
        docs, engine = load_docs(text)
    except ParseError as e:
        fail(f"{path.name}: parse error: {e}")
    kinds = [d.get("kind") for d in docs if isinstance(d, dict)]
    if "Deployment" not in kinds:
        fail(f"{path.name}: missing kind: Deployment")
    if "Service" not in kinds:
        fail(f"{path.name}: missing kind: Service")
    dep = next(d for d in docs if isinstance(d, dict) and d.get("kind") == "Deployment")
    svc = next(d for d in docs if isinstance(d, dict) and d.get("kind") == "Service")
    grace = get_in(dep, "spec", "template", "spec", "terminationGracePeriodSeconds")
    if not isinstance(grace, int) or grace < 10:
        fail(f"{path.name}: terminationGracePeriodSeconds must be >= 10 (got {grace!r})")
    containers = get_in(dep, "spec", "template", "spec", "containers")
    if not isinstance(containers, list) or not containers:
        fail(f"{path.name}: Deployment has no containers")
    c0 = containers[0]
    live = get_in(c0, "livenessProbe", "httpGet", "path")
    ready = get_in(c0, "readinessProbe", "httpGet", "path")
    if live != "/health":
        fail(f"{path.name}: livenessProbe httpGet.path must be /health (got {live!r})")
    if ready != "/ready":
        fail(f"{path.name}: readinessProbe httpGet.path must be /ready (got {ready!r})")
    live_port = get_in(c0, "livenessProbe", "httpGet", "port")
    ready_port = get_in(c0, "readinessProbe", "httpGet", "port")
    if live_port != port:
        fail(f"{path.name}: livenessProbe httpGet.port must stay {port} (got {live_port!r})")
    if ready_port != port:
        fail(f"{path.name}: readinessProbe httpGet.port must stay {port} (got {ready_port!r})")
    cport = get_in(c0, "ports", 0, "containerPort")
    if cport != port:
        fail(f"{path.name}: containerPort {cport!r} != expected {port}")
    stype = get_in(svc, "spec", "type")
    if stype != "ClusterIP":
        fail(f"{path.name}: Service type must be ClusterIP (got {stype!r})")
    sport = get_in(svc, "spec", "ports", 0, "port")
    tport = get_in(svc, "spec", "ports", 0, "targetPort")
    if sport != 80 or tport != port:
        fail(f"{path.name}: Service port must be 80 -> {port} (got {sport!r} -> {tport!r})")
    pname = get_in(svc, "spec", "ports", 0, "name")
    if pname != "http":
        fail(f"{path.name}: Service port name must be http (got {pname!r})")
    pod_sc = get_in(dep, "spec", "template", "spec", "securityContext") or {}
    if not isinstance(pod_sc, dict):
        fail(f"{path.name}: pod securityContext must be a mapping")
    if pod_sc.get("runAsNonRoot") not in (True, "true"):
        fail(f"{path.name}: pod securityContext.runAsNonRoot must be true")
    run_as = pod_sc.get("runAsUser")
    if not isinstance(run_as, int):
        fail(f"{path.name}: pod securityContext.runAsUser must be numeric (got {run_as!r})")
    csc = c0.get("securityContext") if isinstance(c0, dict) else None
    if not isinstance(csc, dict):
        fail(f"{path.name}: container securityContext must be a mapping")
    if csc.get("allowPrivilegeEscalation") not in (False, "false"):
        fail(
            f"{path.name}: container allowPrivilegeEscalation must be false "
            f"(got {csc.get('allowPrivilegeEscalation')!r})"
        )
    if csc.get("readOnlyRootFilesystem") not in (True, "true"):
        fail(
            f"{path.name}: container readOnlyRootFilesystem must be true "
            f"(got {csc.get('readOnlyRootFilesystem')!r})"
        )
    if csc.get("runAsNonRoot") not in (True, "true"):
        fail(f"{path.name}: container runAsNonRoot must be true")
    if csc.get("privileged") in (True, "true"):
        fail(f"{path.name}: container must not set privileged: true")
    drop = get_in(csc, "capabilities", "drop") or []
    if isinstance(drop, str):
        inner = drop.strip()
        if inner.startswith("[") and inner.endswith("]"):
            drop_list = [x.strip().strip("\"") for x in inner[1:-1].split(",") if x.strip()]
        else:
            drop_list = [inner] if inner else []
    elif isinstance(drop, list):
        drop_list = [str(x) for x in drop]
    else:
        drop_list = []
    if "ALL" not in drop_list:
        fail(f"{path.name}: capabilities.drop must include ALL (got {drop_list!r})")
    if csc.get("readOnlyRootFilesystem") in (True, "true"):
        mounts = c0.get("volumeMounts") or []
        if not isinstance(mounts, list):
            fail(f"{path.name}: volumeMounts must be a list when readOnlyRootFilesystem is true")
        paths = [m.get("mountPath") for m in mounts if isinstance(m, dict)]
        if "/tmp" not in paths:
            fail(f"{path.name}: volumeMount for /tmp required when readOnlyRootFilesystem is true")
    label = f"app.oss-cash-lab.dev/{bet}"
    if get_in(dep, "metadata", "labels", label) not in (True, "true"):
        fail(f"{path.name}: Deployment missing label {label}")
    if get_in(svc, "metadata", "labels", label) not in (True, "true"):
        fail(f"{path.name}: Service missing label {label}")
    return engine


def check_servicemonitors(k8s: Path) -> str:
    """Parse servicemonitor.yaml only — unknown CRDs must not fail the check."""
    path = k8s / SERVICEMONITOR
    if not path.is_file():
        fail(f"missing {path}")
    try:
        docs, engine = load_docs(path.read_text(encoding="utf-8"))
    except ParseError as e:
        fail(f"{SERVICEMONITOR}: parse error: {e}")
    sms = [d for d in docs if isinstance(d, dict) and d.get("kind") == "ServiceMonitor"]
    endpoints = []
    for sm in sms:
        api = sm.get("apiVersion")
        if api != "monitoring.coreos.com/v1":
            fail(f"{SERVICEMONITOR}: apiVersion must be monitoring.coreos.com/v1 (got {api!r})")
        eps = get_in(sm, "spec", "endpoints")
        if not isinstance(eps, list) or not eps:
            fail(f"{SERVICEMONITOR}: {sm.get('metadata', {}).get('name')!r} missing endpoints")
        endpoints.extend(eps)
        ns = get_in(sm, "spec", "namespaceSelector")
        if not isinstance(ns, dict) or not ns:
            fail(f"{SERVICEMONITOR}: missing spec.namespaceSelector")
        if ns.get("any") not in (True, "true"):
            names = ns.get("matchNames") or []
            if not (isinstance(names, list) and "default" in names):
                fail(f"{SERVICEMONITOR}: namespaceSelector must be any: true or matchNames default")
    if len(sms) != 5 and len(endpoints) != 5:
        fail(
            f"{SERVICEMONITOR}: expected 5 ServiceMonitors or 5 endpoints "
            f"(got {len(sms)} monitors, {len(endpoints)} endpoints)"
        )
    for ep in endpoints:
        if not isinstance(ep, dict):
            fail(f"{SERVICEMONITOR}: endpoint must be a mapping (got {ep!r})")
        if ep.get("path") != "/metrics":
            fail(f"{SERVICEMONITOR}: endpoint path must be /metrics (got {ep.get('path')!r})")
        if ep.get("port") != "http":
            fail(f"{SERVICEMONITOR}: endpoint port must be http (got {ep.get('port')!r})")
        if ep.get("interval") != "30s":
            fail(f"{SERVICEMONITOR}: endpoint interval must be 30s (got {ep.get('interval')!r})")
    expected_labels = {f"app.oss-cash-lab.dev/{bet}" for _, bet, _ in EXPECTED}
    found = set()
    for sm in sms:
        ml = get_in(sm, "spec", "selector", "matchLabels") or {}
        if not isinstance(ml, dict):
            fail(f"{SERVICEMONITOR}: missing spec.selector.matchLabels")
        hit = [k for k in expected_labels if ml.get(k) in (True, "true")]
        if not hit:
            fail(f"{SERVICEMONITOR}: matchLabels must include a B–F app.oss-cash-lab.dev/<bet> label")
        found.update(hit)
    if len(sms) == 5 and found != expected_labels:
        missing = sorted(expected_labels - found)
        fail(f"{SERVICEMONITOR}: missing bet matchLabels: {missing}")
    print(
        f"  ok {SERVICEMONITOR}  {len(sms)} ServiceMonitor(s)  "
        f"{len(endpoints)} endpoint(s)  path /metrics  port http"
    )
    return engine



def check_prometheusrule(k8s: Path) -> str:
    """Parse prometheusrule.yaml only — unknown CRDs must not fail the check."""
    path = k8s / PROMETHEUSRULE
    if not path.is_file():
        fail(f"missing {path}")
    try:
        docs, engine = load_docs(path.read_text(encoding="utf-8"))
    except ParseError as e:
        fail(f"{PROMETHEUSRULE}: parse error: {e}")
    rules = [d for d in docs if isinstance(d, dict) and d.get("kind") == "PrometheusRule"]
    if len(rules) != 1:
        fail(f"{PROMETHEUSRULE}: expected 1 PrometheusRule (got {len(rules)})")
    pr = rules[0]
    api = pr.get("apiVersion")
    if api != "monitoring.coreos.com/v1":
        fail(f"{PROMETHEUSRULE}: apiVersion must be monitoring.coreos.com/v1 (got {api!r})")
    groups = get_in(pr, "spec", "groups")
    if not isinstance(groups, list) or not groups:
        fail(f"{PROMETHEUSRULE}: spec.groups must be a non-empty list")
    n_alerts = 0
    for g in groups:
        if not isinstance(g, dict):
            fail(f"{PROMETHEUSRULE}: group must be a mapping")
        rules_list = g.get("rules")
        if not isinstance(rules_list, list) or not rules_list:
            fail(f"{PROMETHEUSRULE}: group {g.get('name')!r} missing rules")
        for rule in rules_list:
            if isinstance(rule, dict) and rule.get("alert"):
                n_alerts += 1
    if n_alerts < 6:
        fail(f"{PROMETHEUSRULE}: need >=6 alerts, got {n_alerts}")
    print(
        f"  ok {PROMETHEUSRULE}  PrometheusRule  {len(groups)} group(s)  "
        f"{n_alerts} alert(s)"
    )
    return engine



def _policy_types(np) -> list:
    raw = get_in(np, "spec", "policyTypes") or []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    # subset parser may keep flow `[Ingress, Egress]` as a scalar string
    if isinstance(raw, str):
        inner = raw.strip()
        if inner.startswith("[") and inner.endswith("]"):
            return [p.strip() for p in inner[1:-1].split(",") if p.strip()]
        return [inner] if inner else []
    return []


def _egress_ports(np) -> set:
    ports = set()
    egress = get_in(np, "spec", "egress") or []
    if not isinstance(egress, list):
        return ports
    for rule in egress:
        if not isinstance(rule, dict):
            continue
        plist = rule.get("ports") or []
        if not isinstance(plist, list):
            continue
        for item in plist:
            if not isinstance(item, dict):
                continue
            port = item.get("port")
            if isinstance(port, int):
                ports.add(port)
            elif isinstance(port, str) and port.isdigit():
                ports.add(int(port))
    return ports


def check_networkpolicies(k8s: Path) -> str:
    """Parse networkpolicy.yaml — built-in API, listed in kustomization.yaml."""
    path = k8s / NETWORKPOLICY
    if not path.is_file():
        fail(f"missing {path}")
    try:
        docs, engine = load_docs(path.read_text(encoding="utf-8"))
    except ParseError as e:
        fail(f"{NETWORKPOLICY}: parse error: {e}")
    nps = [d for d in docs if isinstance(d, dict) and d.get("kind") == "NetworkPolicy"]
    if len(nps) != 5:
        fail(f"{NETWORKPOLICY}: expected 5 NetworkPolicies (got {len(nps)})")
    expected_labels = {f"app.oss-cash-lab.dev/{bet}" for _, bet, _ in EXPECTED}
    found = set()
    for np in nps:
        api = np.get("apiVersion")
        if api != "networking.k8s.io/v1":
            fail(f"{NETWORKPOLICY}: apiVersion must be networking.k8s.io/v1 (got {api!r})")
        types = _policy_types(np)
        if "Ingress" not in types or "Egress" not in types:
            name = get_in(np, "metadata", "name")
            fail(f"{NETWORKPOLICY}: {name!r} policyTypes must include Ingress and Egress (got {types!r})")
        ingress = get_in(np, "spec", "ingress")
        if not isinstance(ingress, list) or not ingress:
            name = get_in(np, "metadata", "name")
            fail(f"{NETWORKPOLICY}: {name!r} missing spec.ingress")
        eports = _egress_ports(np)
        if 53 not in eports and 443 not in eports:
            name = get_in(np, "metadata", "name")
            fail(
                f"{NETWORKPOLICY}: {name!r} egress must include port 53 or 443 "
                f"(got {sorted(eports)!r})"
            )
        ml = get_in(np, "spec", "podSelector", "matchLabels") or {}
        if not isinstance(ml, dict):
            fail(f"{NETWORKPOLICY}: missing spec.podSelector.matchLabels")
        hit = [k for k in expected_labels if ml.get(k) in (True, "true")]
        if not hit:
            fail(
                f"{NETWORKPOLICY}: podSelector.matchLabels must include a "
                f"B–F app.oss-cash-lab.dev/<bet> label"
            )
        found.update(hit)
    if found != expected_labels:
        missing = sorted(expected_labels - found)
        fail(f"{NETWORKPOLICY}: missing bet podSelectors: {missing}")
    print(
        f"  ok {NETWORKPOLICY}  {len(nps)} NetworkPolicy  "
        f"Ingress+Egress  DNS/443 egress  B–F podSelectors"
    )
    return engine


def _pdb_budget_set(pdb) -> bool:
    """True if maxUnavailable or minAvailable is present (int, str, or 0)."""
    spec = pdb.get("spec") if isinstance(pdb, dict) else None
    if not isinstance(spec, dict):
        return False
    for key in ("maxUnavailable", "minAvailable"):
        if key in spec and spec[key] is not None:
            return True
    return False


def check_pdbs(k8s: Path) -> str:
    """Parse pdb.yaml — built-in policy/v1, listed in kustomization.yaml."""
    path = k8s / PDB
    if not path.is_file():
        fail(f"missing {path}")
    try:
        docs, engine = load_docs(path.read_text(encoding="utf-8"))
    except ParseError as e:
        fail(f"{PDB}: parse error: {e}")
    pdbs = [d for d in docs if isinstance(d, dict) and d.get("kind") == "PodDisruptionBudget"]
    if len(pdbs) != 5:
        fail(f"{PDB}: expected 5 PodDisruptionBudget (got {len(pdbs)})")
    expected_labels = {f"app.oss-cash-lab.dev/{bet}" for _, bet, _ in EXPECTED}
    found = set()
    for pdb in pdbs:
        api = pdb.get("apiVersion")
        if api != "policy/v1":
            fail(f"{PDB}: apiVersion must be policy/v1 (got {api!r})")
        if not _pdb_budget_set(pdb):
            name = get_in(pdb, "metadata", "name")
            fail(
                f"{PDB}: {name!r} must set spec.maxUnavailable or spec.minAvailable"
            )
        ml = get_in(pdb, "spec", "selector", "matchLabels") or {}
        if not isinstance(ml, dict):
            fail(f"{PDB}: missing spec.selector.matchLabels")
        hit = [k for k in expected_labels if ml.get(k) in (True, "true")]
        if not hit:
            fail(
                f"{PDB}: selector.matchLabels must include a "
                f"B–F app.oss-cash-lab.dev/<bet> label"
            )
        found.update(hit)
    if found != expected_labels:
        missing = sorted(expected_labels - found)
        fail(f"{PDB}: missing bet selectors: {missing}")
    print(
        f"  ok {PDB}  {len(pdbs)} PodDisruptionBudget  "
        f"maxUnavailable|minAvailable  B–F selectors"
    )
    return engine



def check_hpas(k8s: Path) -> str:
    """Parse hpa.yaml — built-in autoscaling/v2, listed in kustomization.yaml."""
    path = k8s / HPA
    if not path.is_file():
        fail(f"missing {path}")
    try:
        docs, engine = load_docs(path.read_text(encoding="utf-8"))
    except ParseError as e:
        fail(f"{HPA}: parse error: {e}")
    hpas = [
        d for d in docs if isinstance(d, dict) and d.get("kind") == "HorizontalPodAutoscaler"
    ]
    if len(hpas) != 5:
        fail(f"{HPA}: expected 5 HorizontalPodAutoscaler (got {len(hpas)})")
    expected_names = {bet for _, bet, _ in EXPECTED}
    found = set()
    for hpa in hpas:
        api = hpa.get("apiVersion")
        if api != "autoscaling/v2":
            fail(f"{HPA}: apiVersion must be autoscaling/v2 (got {api!r})")
        min_r = get_in(hpa, "spec", "minReplicas")
        max_r = get_in(hpa, "spec", "maxReplicas")
        if not isinstance(min_r, int) or not isinstance(max_r, int):
            name = get_in(hpa, "metadata", "name")
            fail(f"{HPA}: {name!r} minReplicas/maxReplicas must be ints (got {min_r!r}/{max_r!r})")
        if min_r > max_r:
            name = get_in(hpa, "metadata", "name")
            fail(f"{HPA}: {name!r} minReplicas {min_r} > maxReplicas {max_r}")
        kind = get_in(hpa, "spec", "scaleTargetRef", "kind")
        if kind != "Deployment":
            name = get_in(hpa, "metadata", "name")
            fail(f"{HPA}: {name!r} scaleTargetRef.kind must be Deployment (got {kind!r})")
        target = get_in(hpa, "spec", "scaleTargetRef", "name")
        if target not in expected_names:
            fail(
                f"{HPA}: scaleTargetRef.name must be a B–F Deployment "
                f"(got {target!r})"
            )
        found.add(target)
        metrics = get_in(hpa, "spec", "metrics") or []
        if not isinstance(metrics, list) or not metrics:
            name = get_in(hpa, "metadata", "name")
            fail(f"{HPA}: {name!r} missing spec.metrics")
        has_cpu = False
        for m in metrics:
            if not isinstance(m, dict):
                continue
            resource = m.get("resource") if m.get("type") == "Resource" else None
            if not isinstance(resource, dict):
                resource = m.get("resource") if isinstance(m.get("resource"), dict) else None
            if not isinstance(resource, dict):
                continue
            if resource.get("name") != "cpu":
                continue
            target_m = resource.get("target") or {}
            if not isinstance(target_m, dict):
                continue
            util = target_m.get("averageUtilization")
            if isinstance(util, int) and util > 0:
                has_cpu = True
                break
            if isinstance(util, str) and util.isdigit() and int(util) > 0:
                has_cpu = True
                break
        if not has_cpu:
            name = get_in(hpa, "metadata", "name")
            fail(f"{HPA}: {name!r} must set a CPU utilization target (averageUtilization)")
    if found != expected_names:
        missing = sorted(expected_names - found)
        fail(f"{HPA}: missing B–F scaleTargetRef: {missing}")
    print(
        f"  ok {HPA}  {len(hpas)} HorizontalPodAutoscaler  "
        f"min<=max  cpu target  B–F scaleTargetRef"
    )
    return engine



EXPECTED_INGRESS_HOSTS = {
    "gateway.oss-cash-lab.local": "b-mcp-gateway",
    "ci.oss-cash-lab.local": "c-agent-ci",
    "bom.oss-cash-lab.local": "d-ai-bom",
    "cost.oss-cash-lab.local": "e-otel-ai-cost",
    "agent.oss-cash-lab.local": "f-cn-work-agent",
}


def _backend_service(path_item):
    """Return (service_name, port_ok) from an Ingress path backend."""
    if not isinstance(path_item, dict):
        return None, False
    svc = get_in(path_item, "backend", "service") or {}
    if not isinstance(svc, dict):
        return None, False
    name = svc.get("name")
    port = svc.get("port") or {}
    if not isinstance(port, dict):
        return name, False
    pname = port.get("name")
    pnum = port.get("number")
    port_ok = pname == "http" or pnum == 80
    return name, port_ok


def check_ingress(k8s: Path) -> str:
    """Parse ingress.yaml — built-in networking.k8s.io/v1, listed in kustomization.yaml."""
    path = k8s / INGRESS
    if not path.is_file():
        fail(f"missing {path}")
    try:
        docs, engine = load_docs(path.read_text(encoding="utf-8"))
    except ParseError as e:
        fail(f"{INGRESS}: parse error: {e}")
    ings = [d for d in docs if isinstance(d, dict) and d.get("kind") == "Ingress"]
    if len(ings) != 1:
        fail(f"{INGRESS}: expected 1 Ingress (got {len(ings)})")
    ing = ings[0]
    api = ing.get("apiVersion")
    if api != "networking.k8s.io/v1":
        fail(f"{INGRESS}: apiVersion must be networking.k8s.io/v1 (got {api!r})")
    class_name = get_in(ing, "spec", "ingressClassName")
    if class_name != "nginx":
        fail(f"{INGRESS}: ingressClassName must be nginx (got {class_name!r})")
    tls = get_in(ing, "spec", "tls")
    if tls:
        fail(f"{INGRESS}: TLS must be omitted for local (got {tls!r})")
    rules = get_in(ing, "spec", "rules") or []
    if not isinstance(rules, list):
        fail(f"{INGRESS}: spec.rules must be a list")
    expected_services = {bet for _, bet, _ in EXPECTED}
    hosts = []
    backends = set()
    for rule in rules:
        if not isinstance(rule, dict):
            fail(f"{INGRESS}: rule must be a mapping")
        host = rule.get("host")
        if host:
            hosts.append(host)
        paths = get_in(rule, "http", "paths") or []
        if not isinstance(paths, list) or not paths:
            fail(f"{INGRESS}: host {host!r} missing http.paths")
        for item in paths:
            if not isinstance(item, dict):
                fail(f"{INGRESS}: path item must be a mapping")
            if item.get("path") != "/":
                fail(
                    f"{INGRESS}: path must be / Prefix so backends need no strip "
                    f"(got {item.get('path')!r})"
                )
            if item.get("pathType") != "Prefix":
                fail(f"{INGRESS}: pathType must be Prefix (got {item.get('pathType')!r})")
            svc_name, port_ok = _backend_service(item)
            if svc_name not in expected_services:
                fail(
                    f"{INGRESS}: backend service must be a B–F Service name "
                    f"(got {svc_name!r})"
                )
            if not port_ok:
                fail(
                    f"{INGRESS}: backend port must be name http or number 80 "
                    f"(host {host!r})"
                )
            backends.add(svc_name)
            expected_svc = EXPECTED_INGRESS_HOSTS.get(host)
            if expected_svc and expected_svc != svc_name:
                fail(
                    f"{INGRESS}: host {host!r} must route to {expected_svc} "
                    f"(got {svc_name!r})"
                )
    if len(ings) != 1:
        fail(f"{INGRESS}: expected 1 Ingress (got {len(ings)})")
    if len(hosts) != 5 and len(rules) != 5:
        fail(
            f"{INGRESS}: expected 5 hosts or 5 rules "
            f"(got {len(hosts)} hosts, {len(rules)} rules)"
        )
    if backends != expected_services:
        missing = sorted(expected_services - backends)
        fail(f"{INGRESS}: backends must match B–F Service names (missing {missing})")
    host_set = set(hosts)
    if host_set and host_set != set(EXPECTED_INGRESS_HOSTS):
        missing = sorted(set(EXPECTED_INGRESS_HOSTS) - host_set)
        extra = sorted(host_set - set(EXPECTED_INGRESS_HOSTS))
        fail(f"{INGRESS}: unexpected hosts missing={missing} extra={extra}")
    print(
        f"  ok {INGRESS}  1 Ingress  {len(hosts)} host(s)  {len(rules)} rule(s)  "
        f"class nginx  B–F backends"
    )
    return engine



def check_limitrange(k8s: Path) -> str:
    """Parse limitrange.yaml — built-in v1, listed in kustomization.yaml."""
    path = k8s / LIMITRANGE
    if not path.is_file():
        fail(f"missing {path}")
    try:
        docs, engine = load_docs(path.read_text(encoding="utf-8"))
    except ParseError as e:
        fail(f"{LIMITRANGE}: parse error: {e}")
    lrs = [d for d in docs if isinstance(d, dict) and d.get("kind") == "LimitRange"]
    if len(lrs) != 1:
        fail(f"{LIMITRANGE}: expected 1 LimitRange (got {len(lrs)})")
    lr = lrs[0]
    api = lr.get("apiVersion")
    if api != "v1":
        fail(f"{LIMITRANGE}: apiVersion must be v1 (got {api!r})")
    limits = get_in(lr, "spec", "limits") or []
    if not isinstance(limits, list) or not limits:
        fail(f"{LIMITRANGE}: spec.limits must be a non-empty list")
    has_container = False
    has_default_request_cpu = False
    for item in limits:
        if not isinstance(item, dict):
            fail(f"{LIMITRANGE}: spec.limits item must be a mapping")
        if item.get("type") == "Container":
            has_container = True
        dr = item.get("defaultRequest") or {}
        if isinstance(dr, dict) and dr.get("cpu"):
            has_default_request_cpu = True
    if not has_container:
        fail(f"{LIMITRANGE}: spec.limits must include type Container")
    if not has_default_request_cpu:
        fail(
            f"{LIMITRANGE}: defaultRequest.cpu must be set "
            f"(HPA needs a request denominator when resources are omitted)"
        )
    print(
        f"  ok {LIMITRANGE}  1 LimitRange  type Container  defaultRequest.cpu"
    )
    return engine



def check_resourcequota(k8s: Path) -> str:
    """Parse resourcequota.yaml — built-in v1, listed in kustomization.yaml."""
    path = k8s / RESOURCEQUOTA
    if not path.is_file():
        fail(f"missing {path}")
    try:
        docs, engine = load_docs(path.read_text(encoding="utf-8"))
    except ParseError as e:
        fail(f"{RESOURCEQUOTA}: parse error: {e}")
    rqs = [d for d in docs if isinstance(d, dict) and d.get("kind") == "ResourceQuota"]
    if len(rqs) != 1:
        fail(f"{RESOURCEQUOTA}: expected 1 ResourceQuota (got {len(rqs)})")
    rq = rqs[0]
    api = rq.get("apiVersion")
    if api != "v1":
        fail(f"{RESOURCEQUOTA}: apiVersion must be v1 (got {api!r})")
    hard = get_in(rq, "spec", "hard") or {}
    if not isinstance(hard, dict) or not hard:
        fail(f"{RESOURCEQUOTA}: spec.hard must be a non-empty mapping")
    pods = hard.get("pods")
    if pods is None or pods == "":
        fail(f"{RESOURCEQUOTA}: spec.hard.pods must be set")
    print(
        f"  ok {RESOURCEQUOTA}  1 ResourceQuota  hard.pods={pods!s}"
    )
    return engine


def main() -> None:

    if len(sys.argv) > 1:
        k8s = Path(sys.argv[1])
    else:
        k8s = Path(__file__).resolve().parent.parent / "deploy" / "k8s"
    if not k8s.is_dir():
        fail(f"missing directory {k8s}")
    engines = set()
    for fname, bet, port in EXPECTED:
        path = k8s / fname
        if not path.is_file():
            fail(f"missing {path}")
        engines.add(check_service_file(path, bet, port))
        print(
            f"  ok {fname}  Deployment+Service  /health /ready  grace>=10  "
            f"port {port}  securityContext"
        )
    kust = k8s / "kustomization.yaml"
    if kust.is_file():
        try:
            docs, engine = load_docs(kust.read_text(encoding="utf-8"))
        except ParseError as e:
            fail(f"kustomization.yaml: parse error: {e}")
        engines.add(engine)
        kinds = [d.get("kind") for d in docs if isinstance(d, dict)]
        if "Kustomization" not in kinds:
            fail("kustomization.yaml: expected kind: Kustomization")
        resources = get_in(docs[0], "resources") or []
        missing = [f for f, _, _ in EXPECTED if f not in resources]
        if missing:
            fail(f"kustomization.yaml missing resources: {missing}")
        if NETWORKPOLICY not in resources:
            fail("kustomization.yaml missing resources: ['networkpolicy.yaml']")
        if PDB not in resources:
            fail("kustomization.yaml missing resources: ['pdb.yaml']")
        if HPA not in resources:
            fail("kustomization.yaml missing resources: ['hpa.yaml']")
        if INGRESS not in resources:
            fail("kustomization.yaml missing resources: ['ingress.yaml']")
        if LIMITRANGE not in resources:
            fail("kustomization.yaml missing resources: ['limitrange.yaml']")
        if RESOURCEQUOTA not in resources:
            fail("kustomization.yaml missing resources: ['resourcequota.yaml']")
        if SERVICEMONITOR in resources:
            fail("kustomization.yaml must not list servicemonitor.yaml (CRDs optional)")
        if PROMETHEUSRULE in resources:
            fail("kustomization.yaml must not list prometheusrule.yaml (CRDs optional)")
        print("  ok kustomization.yaml  (parse only; no Deployment/Service assert)")
    engines.add(check_servicemonitors(k8s))
    engines.add(check_prometheusrule(k8s))
    engines.add(check_networkpolicies(k8s))
    engines.add(check_pdbs(k8s))
    engines.add(check_hpas(k8s))
    engines.add(check_ingress(k8s))
    engines.add(check_limitrange(k8s))
    engines.add(check_resourcequota(k8s))
    extra = sorted(p.name for p in k8s.glob("*.yaml") if p.name not in KNOWN_YAML)
    if extra:
        fail(f"unexpected yaml files (check-k8s does not cover): {extra}")
    print(f"k8s manifests ok ({', '.join(sorted(engines))} parser)")


if __name__ == "__main__":
    main()
