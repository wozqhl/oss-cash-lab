#!/usr/bin/env python3
"""Parse-only check for deploy/helm/oss-cash-lab (no cluster).

Asserts Chart.yaml name oss-cash-lab, values.yaml lists B–F bets, and
templates/*.yaml contain {{ plus Deployment. Optional `helm template` when
helm is on PATH (requires 5 Deployments); skipped when missing (like docker).
Does not include Prometheus Operator CRDs (ServiceMonitor/PrometheusRule).
Optional pdb.enabled (default false) so replicaCount 1 does not block drains.
Optional hpa.enabled (default false) so replicaCount 1 is not managed without
metrics-server; template exists and renders 5 HPAs when true.
Optional ingress.enabled (default false) so helm install does not require an
ingress controller; template exists and renders 1 Ingress (5 hosts) when true.
Optional limitRange.enabled (default true) so omitted container resources
still get requests/limits; template exists and renders 1 LimitRange by default
(--set limitRange.enabled=false renders none). Does not change explicit
Deployment resources.
Optional resourceQuota.enabled (default false) so a thin install into a
shared ns does not fight existing quotas; template exists and renders 0
ResourceQuota by default (--set resourceQuota.enabled=true renders 1).
Optional securityContext.enabled (default true) so B–F Deployments render
restricted-ish PSS (non-root, drop ALL, read-only root + /tmp);
--set securityContext.enabled=false omits those fields.
templates/NOTES.txt is required (port-forward + /health). helm template
evaluates NOTES (syntax) but does not print them; when helm is on PATH the
checker renders NOTES via a tiny Files/tpl chart and asserts port-forward
and /health (and five hosts when --set ingress.enabled=true). Parse-only
if helm is missing: the NOTES.txt file still must contain those strings.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

EXPECTED_BETS = [
    "b-mcp-gateway",
    "c-agent-ci",
    "d-ai-bom",
    "e-otel-ai-cost",
    "f-cn-work-agent",
]

CRD_KINDS = ("ServiceMonitor", "PrometheusRule")


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def check_chart_yaml(path: Path) -> None:
    if not path.is_file():
        fail(f"missing {path}")
    text = path.read_text(encoding="utf-8")
    if not re.search(r"^apiVersion:\s*v2\s*$", text, re.M):
        fail(f"{path}: apiVersion must be v2")
    if not re.search(r"^name:\s*oss-cash-lab\s*$", text, re.M):
        fail(f"{path}: name must be oss-cash-lab")
    if not re.search(r"^version:\s*0\.1\.0\s*$", text, re.M):
        fail(f"{path}: version must be 0.1.0")
    print("  ok Chart.yaml  name=oss-cash-lab  apiVersion=v2  version=0.1.0")


def check_values(path: Path) -> None:
    if not path.is_file():
        fail(f"missing {path}")
    text = path.read_text(encoding="utf-8")
    if "imageRegistry" not in text:
        fail(f"{path}: missing imageRegistry")
    if not re.search(r"^bets:\s*$", text, re.M):
        fail(f"{path}: missing bets: mapping")
    for bet in EXPECTED_BETS:
        if not re.search(rf"^\s+{re.escape(bet)}:\s*$", text, re.M):
            fail(f"{path}: missing bet {bet}")
    if "enabled: true" not in text:
        fail(f"{path}: expected per-bet enabled: true")
    if "replicaCount: 1" not in text:
        fail(f"{path}: expected replicaCount: 1")
    if "tag: dev" not in text:
        fail(f"{path}: expected image tag: dev")
    if "port: 80" not in text:
        fail(f"{path}: expected service.port: 80")
    if not re.search(r"networkPolicy:\s*\n\s+enabled:\s*false\b", text):
        fail(f"{path}: networkPolicy.enabled must default to false")
    if not re.search(r"pdb:\s*\n\s+enabled:\s*false\b", text):
        fail(f"{path}: pdb.enabled must default to false")
    if not re.search(r"hpa:\s*\n\s+enabled:\s*false\b", text):
        fail(f"{path}: hpa.enabled must default to false")
    if not re.search(r"ingress:\s*\n\s+enabled:\s*false\b", text):
        fail(f"{path}: ingress.enabled must default to false")
    if not re.search(r"limitRange:\s*\n\s+enabled:\s*true\b", text):
        fail(f"{path}: limitRange.enabled must default to true")
    if "defaultRequest:" not in text:
        fail(f"{path}: limitRange must set defaultRequest")
    if not re.search(r"resourceQuota:\s*\n\s+enabled:\s*false\b", text):
        fail(f"{path}: resourceQuota.enabled must default to false")
    if not re.search(r"securityContext:\s*\n\s+enabled:\s*true\b", text):
        fail(f"{path}: securityContext.enabled must default to true")
    if not re.search(r"className:\s*nginx\b", text):
        fail(f"{path}: ingress.className must be nginx")
    for host in (
        "gateway.oss-cash-lab.local",
        "ci.oss-cash-lab.local",
        "bom.oss-cash-lab.local",
        "cost.oss-cash-lab.local",
        "agent.oss-cash-lab.local",
    ):
        if host not in text:
            fail(f"{path}: missing ingress host {host}")
    print(
        f"  ok values.yaml  imageRegistry  bets={','.join(EXPECTED_BETS)}  "
        f"networkPolicy.enabled=false  pdb.enabled=false  hpa.enabled=false  "
        f"ingress.enabled=false  limitRange.enabled=true  "
        f"resourceQuota.enabled=false  securityContext.enabled=true"
    )


def check_templates(templates: Path) -> None:
    if not templates.is_dir():
        fail(f"missing {templates}")
    yamls = sorted(
        p for p in templates.iterdir() if p.suffix in (".yaml", ".yml") and p.is_file()
    )
    if not yamls:
        fail(f"{templates}: no *.yaml templates")
    saw_tpl = False
    saw_deploy = False
    saw_values = False
    for path in yamls:
        text = path.read_text(encoding="utf-8")
        if "{{" in text:
            saw_tpl = True
        if "Deployment" in text:
            saw_deploy = True
        if ".Values" in text:
            saw_values = True
        for kind in CRD_KINDS:
            if re.search(rf"kind:\s*{kind}\b", text):
                fail(f"{path}: must not include Prometheus Operator CRD {kind}")
    if not saw_tpl:
        fail(f"{templates}: templates/*.yaml must contain {{{{")
    if not saw_deploy:
        fail(f"{templates}: templates/*.yaml must contain Deployment")
    if not saw_values:
        fail(f"{templates}: templates/*.yaml must render {{{{ .Values }}}}")
    names = ", ".join(p.name for p in yamls)
    if "pdb.yaml" not in names:
        fail(f"{templates}: missing pdb.yaml template")
    if "hpa.yaml" not in names:
        fail(f"{templates}: missing hpa.yaml template")
    if "ingress.yaml" not in names:
        fail(f"{templates}: missing ingress.yaml template")
    if "limitrange.yaml" not in names:
        fail(f"{templates}: missing limitrange.yaml template")
    if "resourcequota.yaml" not in names:
        fail(f"{templates}: missing resourcequota.yaml template")
    print(f"  ok templates/  {{{{ + Deployment + .Values  ({names})")


def check_notes(templates: Path) -> None:
    path = templates / "NOTES.txt"
    if not path.is_file():
        fail(f"missing {path}")
    text = path.read_text(encoding="utf-8")
    if "port-forward" not in text:
        fail(f"{path}: must mention port-forward")
    if "/health" not in text:
        fail(f"{path}: must mention /health")
    print("  ok templates/NOTES.txt  port-forward + /health")


def helm_render_notes(chart: Path, extra_args: list[str] | None = None) -> str:
    """Render templates/NOTES.txt with helm (NOTES are not in helm template stdout)."""
    notes = (chart / "templates" / "NOTES.txt").read_text(encoding="utf-8")
    wrapper = (
        "apiVersion: v1\n"
        "kind: ConfigMap\n"
        "metadata:\n"
        "  name: oss-cash-lab-notes\n"
        "data:\n"
        "  notes: |\n"
        '{{ tpl (.Files.Get "notes.tpl") . | indent 4 }}\n'
    )
    with tempfile.TemporaryDirectory() as td:
        dest = Path(td) / "oss-cash-lab"
        (dest / "templates").mkdir(parents=True)
        shutil.copy(chart / "Chart.yaml", dest / "Chart.yaml")
        shutil.copy(chart / "values.yaml", dest / "values.yaml")
        (dest / "notes.tpl").write_text(notes, encoding="utf-8")
        (dest / "templates" / "notes-render.yaml").write_text(wrapper, encoding="utf-8")
        cmd = ["helm", "template", "oss-cash-lab", str(dest)]
        if extra_args:
            cmd.extend(extra_args)
        print(f"==> helm template NOTES {' '.join(extra_args or [])}".rstrip())
        try:
            proc = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            err = (exc.stderr or exc.stdout or str(exc)).strip()
            fail(f"helm template NOTES failed: {err}")
        return proc.stdout


def count_kind(rendered: str, kind: str) -> int:
    return len(re.findall(rf"^kind:\s*{re.escape(kind)}\s*$", rendered, re.M))


def maybe_helm_template(chart: Path) -> None:
    if shutil.which("helm") is None:
        print("skip: helm not on PATH (parse-only, like docker / compose-smoke)")
        return
    cmd = ["helm", "template", "oss-cash-lab", str(chart)]
    print(f"==> {' '.join(cmd)}")
    try:
        proc = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or str(exc)).strip()
        fail(f"helm template failed: {err}")
    rendered = proc.stdout
    n_deploy = count_kind(rendered, "Deployment")
    n_svc = count_kind(rendered, "Service")
    if n_deploy != 5:
        fail(f"helm template must render 5 Deployments (got {n_deploy})")
    if n_svc != 5:
        fail(f"helm template must render 5 Services (got {n_svc})")
    n_np = count_kind(rendered, "NetworkPolicy")
    if n_np != 0:
        fail(f"default helm template must not render NetworkPolicy (got {n_np})")
    n_pdb = count_kind(rendered, "PodDisruptionBudget")
    if n_pdb != 0:
        fail(f"default helm template must not render PodDisruptionBudget (got {n_pdb})")
    n_hpa = count_kind(rendered, "HorizontalPodAutoscaler")
    if n_hpa != 0:
        fail(f"default helm template must not render HorizontalPodAutoscaler (got {n_hpa})")
    n_ing = count_kind(rendered, "Ingress")
    if n_ing != 0:
        fail(f"default helm template must not render Ingress (got {n_ing})")
    n_lr = count_kind(rendered, "LimitRange")
    if n_lr != 1:
        fail(f"default helm template must render 1 LimitRange (got {n_lr})")
    n_rq = count_kind(rendered, "ResourceQuota")
    if n_rq != 0:
        fail(f"default helm template must not render ResourceQuota (got {n_rq})")
    if "defaultRequest" not in rendered:
        fail("default helm template LimitRange must set defaultRequest")
    if not re.search(r"type:\s*Container\b", rendered):
        fail("default helm template LimitRange must set type Container")
    if "allowPrivilegeEscalation" not in rendered:
        fail("default helm template must set allowPrivilegeEscalation")
    if not re.search(r"allowPrivilegeEscalation:\s*false\b", rendered):
        fail("default helm template allowPrivilegeEscalation must be false")
    if not re.search(r"readOnlyRootFilesystem:\s*true\b", rendered):
        fail("default helm template readOnlyRootFilesystem must be true")
    if not re.search(r"runAsNonRoot:\s*true\b", rendered):
        fail("default helm template runAsNonRoot must be true")
    if not re.search(r"runAsUser:\s*\d+", rendered):
        fail("default helm template must set numeric runAsUser")
    if "ALL" not in rendered:
        fail("default helm template capabilities.drop must include ALL")
    if not re.search(r"mountPath:\s*/tmp\b", rendered):
        fail("default helm template must mount /tmp when readOnlyRootFilesystem")
    for kind in CRD_KINDS:
        if count_kind(rendered, kind) != 0 or re.search(rf"kind:\s*{kind}\b", rendered):
            fail(f"helm template must not render {kind}")
    for needle in ("/health", "/ready", "terminationGracePeriodSeconds"):
        if needle not in rendered:
            fail(f"helm template output missing {needle}")
    print(
        f"  ok helm template  {n_deploy} Deployments  {n_svc} Services  "
        f"(NetworkPolicy off, PDB off, HPA off, Ingress off, LimitRange on, "
        f"ResourceQuota off, securityContext on)"
    )
    notes = helm_render_notes(chart)
    if "port-forward" not in notes:
        fail("helm template NOTES must contain port-forward")
    if "/health" not in notes:
        fail("helm template NOTES must contain /health")
    print("  ok helm template NOTES  port-forward + /health")
    cmd_on = ["helm", "template", "oss-cash-lab", str(chart), "--set", "pdb.enabled=true"]
    print(f"==> {' '.join(cmd_on)}")
    try:
        proc_on = subprocess.run(
            cmd_on,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or str(exc)).strip()
        fail(f"helm template --set pdb.enabled=true failed: {err}")
    rendered_on = proc_on.stdout
    n_pdb_on = count_kind(rendered_on, "PodDisruptionBudget")
    if n_pdb_on != 5:
        fail(f"helm template pdb.enabled=true must render 5 PodDisruptionBudget (got {n_pdb_on})")
    if "maxUnavailable" not in rendered_on and "minAvailable" not in rendered_on:
        fail("helm template pdb.enabled=true must set maxUnavailable or minAvailable")
    print(f"  ok helm template --set pdb.enabled=true  {n_pdb_on} PodDisruptionBudget")
    cmd_hpa = ["helm", "template", "oss-cash-lab", str(chart), "--set", "hpa.enabled=true"]
    print(f"==> {' '.join(cmd_hpa)}")
    try:
        proc_hpa = subprocess.run(
            cmd_hpa,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or str(exc)).strip()
        fail(f"helm template --set hpa.enabled=true failed: {err}")
    rendered_hpa = proc_hpa.stdout
    n_hpa_on = count_kind(rendered_hpa, "HorizontalPodAutoscaler")
    if n_hpa_on != 5:
        fail(
            f"helm template hpa.enabled=true must render 5 HorizontalPodAutoscaler "
            f"(got {n_hpa_on})"
        )
    if "averageUtilization" not in rendered_hpa and "cpu" not in rendered_hpa:
        fail("helm template hpa.enabled=true must set a CPU utilization target")
    if "scaleTargetRef" not in rendered_hpa:
        fail("helm template hpa.enabled=true must set scaleTargetRef")
    print(f"  ok helm template --set hpa.enabled=true  {n_hpa_on} HorizontalPodAutoscaler")
    cmd_ing = ["helm", "template", "oss-cash-lab", str(chart), "--set", "ingress.enabled=true"]
    print(f"==> {' '.join(cmd_ing)}")
    try:
        proc_ing = subprocess.run(
            cmd_ing,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or str(exc)).strip()
        fail(f"helm template --set ingress.enabled=true failed: {err}")
    rendered_ing = proc_ing.stdout
    n_ing_on = count_kind(rendered_ing, "Ingress")
    if n_ing_on != 1:
        fail(f"helm template ingress.enabled=true must render 1 Ingress (got {n_ing_on})")
    if not re.search(r"ingressClassName:\s*nginx\b", rendered_ing):
        fail("helm template ingress.enabled=true must set ingressClassName nginx")
    if re.search(r"^\s*tls:\s*$", rendered_ing, re.M) or "secretName" in rendered_ing:
        fail("helm template ingress.enabled=true must omit TLS secrets")
    for host in (
        "gateway.oss-cash-lab.local",
        "ci.oss-cash-lab.local",
        "bom.oss-cash-lab.local",
        "cost.oss-cash-lab.local",
        "agent.oss-cash-lab.local",
    ):
        if host not in rendered_ing:
            fail(f"helm template ingress.enabled=true missing host {host}")
    for bet in EXPECTED_BETS:
        if not re.search(rf"name:\s*{re.escape(bet)}\s*$", rendered_ing, re.M):
            fail(f"helm template ingress.enabled=true missing backend Service {bet}")
    n_hosts = len([ln for ln in rendered_ing.splitlines() if "host:" in ln and "oss-cash-lab.local" in ln])
    n_rules = n_hosts
    if n_hosts != 5 and n_rules != 5:
        fail(
            f"helm template ingress.enabled=true must have 5 hosts or 5 rules "
            f"(got {n_hosts} hosts)"
        )
    print(
        f"  ok helm template --set ingress.enabled=true  {n_ing_on} Ingress  "
        f"{n_hosts} host(s)  class nginx"
    )
    notes_ing = helm_render_notes(chart, ["--set", "ingress.enabled=true"])
    if "port-forward" not in notes_ing:
        fail("helm template NOTES ingress.enabled=true must contain port-forward")
    if "/health" not in notes_ing:
        fail("helm template NOTES ingress.enabled=true must contain /health")
    if "/etc/hosts" not in notes_ing:
        fail("helm template NOTES ingress.enabled=true must mention /etc/hosts")
    for host in (
        "gateway.oss-cash-lab.local",
        "ci.oss-cash-lab.local",
        "bom.oss-cash-lab.local",
        "cost.oss-cash-lab.local",
        "agent.oss-cash-lab.local",
    ):
        if host not in notes_ing:
            fail(f"helm template NOTES ingress.enabled=true missing host {host}")
    print("  ok helm template NOTES --set ingress.enabled=true  five hosts + /etc/hosts")
    cmd_lr_off = [
        "helm",
        "template",
        "oss-cash-lab",
        str(chart),
        "--set",
        "limitRange.enabled=false",
    ]
    print(f"==> {' '.join(cmd_lr_off)}")
    try:
        proc_lr_off = subprocess.run(
            cmd_lr_off,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or str(exc)).strip()
        fail(f"helm template --set limitRange.enabled=false failed: {err}")
    n_lr_off = count_kind(proc_lr_off.stdout, "LimitRange")
    if n_lr_off != 0:
        fail(
            f"helm template limitRange.enabled=false must render 0 LimitRange "
            f"(got {n_lr_off})"
        )
    print(
        f"  ok helm template --set limitRange.enabled=false  {n_lr_off} LimitRange"
    )
    cmd_rq = [
        "helm",
        "template",
        "oss-cash-lab",
        str(chart),
        "--set",
        "resourceQuota.enabled=true",
    ]
    print(f"==> {' '.join(cmd_rq)}")
    try:
        proc_rq = subprocess.run(
            cmd_rq,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or str(exc)).strip()
        fail(f"helm template --set resourceQuota.enabled=true failed: {err}")
    n_rq_on = count_kind(proc_rq.stdout, "ResourceQuota")
    if n_rq_on != 1:
        fail(
            f"helm template resourceQuota.enabled=true must render 1 ResourceQuota "
            f"(got {n_rq_on})"
        )
    if "pods:" not in proc_rq.stdout and "pods :" not in proc_rq.stdout:
        fail("helm template resourceQuota.enabled=true must set hard.pods")
    print(
        f"  ok helm template --set resourceQuota.enabled=true  {n_rq_on} ResourceQuota"
    )
    cmd_sc_off = [
        "helm",
        "template",
        "oss-cash-lab",
        str(chart),
        "--set",
        "securityContext.enabled=false",
    ]
    print(f"==> {' '.join(cmd_sc_off)}")
    try:
        proc_sc_off = subprocess.run(
            cmd_sc_off,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or exc.stdout or str(exc)).strip()
        fail(f"helm template --set securityContext.enabled=false failed: {err}")
    rendered_sc_off = proc_sc_off.stdout
    if "allowPrivilegeEscalation" in rendered_sc_off:
        fail("helm template securityContext.enabled=false must omit allowPrivilegeEscalation")
    if "readOnlyRootFilesystem" in rendered_sc_off:
        fail("helm template securityContext.enabled=false must omit readOnlyRootFilesystem")
    if re.search(r"runAsNonRoot:\s*true\b", rendered_sc_off):
        fail("helm template securityContext.enabled=false must omit runAsNonRoot")
    if re.search(r"mountPath:\s*/tmp\b", rendered_sc_off):
        fail("helm template securityContext.enabled=false must omit /tmp volumeMount")
    print("  ok helm template --set securityContext.enabled=false  securityContext omitted")


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    if len(sys.argv) > 1:
        root = Path(sys.argv[1]).resolve()
    chart = root / "deploy" / "helm" / "oss-cash-lab"
    check_chart_yaml(chart / "Chart.yaml")
    check_values(chart / "values.yaml")
    check_templates(chart / "templates")
    check_notes(chart / "templates")
    maybe_helm_template(chart)
    print("helm ok (parse-only)")


if __name__ == "__main__":
    main()
