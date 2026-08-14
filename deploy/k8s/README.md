# Kubernetes manifests (B–F)

Minimal **Deployment + Service** for the five HTTP bets, plus **NetworkPolicy** ([`networkpolicy.yaml`](./networkpolicy.yaml)), plus **PodDisruptionBudget** ([`pdb.yaml`](./pdb.yaml); `policy/v1`, `maxUnavailable: 1`), plus **HorizontalPodAutoscaler** ([`hpa.yaml`](./hpa.yaml); `autoscaling/v2`, CPU 70%, min 1 / max 4 — **needs metrics-server** to scale; idle without it), plus **Ingress** ([`ingress.yaml`](./ingress.yaml); `networking.k8s.io/v1`, five host rules Prefix `/`, class `nginx` — **needs an ingress controller**; idle without it; **no TLS secrets**), plus **LimitRange** ([`limitrange.yaml`](./limitrange.yaml); `v1`, type `Container` — defaultRequest 50m/64Mi, default 500m/256Mi when resources are omitted; does **not** change Deployments that already set resources), plus **ResourceQuota** ([`resourcequota.yaml`](./resourcequota.yaml); `v1` — namespace hard caps sized for B–F × HPA maxReplicas 4 plus headroom so the demo namespace cannot unbounded-scale; pairs with LimitRange), plus restricted-ish **securityContext** on each B–F Deployment (non-root, drop ALL, read-only root + emptyDir `/tmp`; B/C/F also `/app/data`), plus optional Prometheus Operator **ServiceMonitors** for `GET /metrics`, plus importable Grafana JSON in [`deploy/grafana/`](../grafana/), plus Prometheus alerting rules in [`deploy/prometheus/`](../prometheus/) and [`prometheusrule.yaml`](./prometheusrule.yaml). Optional Helm chart (same images/ports; **not** the default apply path): [`deploy/helm/`](../helm/). This tree is copy-pasteable; this box has **no cluster**, **no Grafana**, and **no Prometheus**, so CI/`make smoke` only **parses** YAML (and dashboard JSON / rule files).

## Images are not published

Container images are placeholders:

```
ghcr.io/wozqhl/b-mcp-gateway:dev
ghcr.io/wozqhl/c-agent-ci:dev
ghcr.io/wozqhl/d-ai-bom:dev
ghcr.io/wozqhl/e-otel-ai-cost:dev
ghcr.io/wozqhl/f-cn-work-agent:dev
```

They are **not** pushed to GHCR yet. `imagePullPolicy: IfNotPresent` so a locally loaded image can run. This box often has **no Docker** — `make smoke` only **parses** Dockerfiles (`scripts/check-dockerfiles.sh`). When you have Docker:

```bash
docker build -t ghcr.io/wozqhl/b-mcp-gateway:dev bets/b-mcp-gateway
docker build -t ghcr.io/wozqhl/c-agent-ci:dev bets/c-agent-ci
docker build -t ghcr.io/wozqhl/d-ai-bom:dev bets/d-ai-bom
docker build -t ghcr.io/wozqhl/e-otel-ai-cost:dev bets/e-otel-ai-cost
docker build -t ghcr.io/wozqhl/f-cn-work-agent:dev bets/f-cn-work-agent
```

Compose `build.context` / `dockerfile: Dockerfile` match those paths. Images bind `0.0.0.0` (not 127.0.0.1) so kubelet probes work. Bases: `node:20-alpine` (B/E), `python:3.12-alpine` (C/D/F). Image HEALTHCHECK → `GET /health` on the EXPOSE port (busybox `wget`; not `/ready`).

## Ports (CLI / Compose defaults)

| Bet | Manifest | containerPort | Service |
|-----|----------|---------------|---------|
| B mcp-gateway | `b-mcp-gateway.yaml` | **8787** | ClusterIP `http` 80 → 8787 |
| C agent-ci | `c-agent-ci.yaml` | **8791** | ClusterIP `http` 80 → 8791 |
| D ai-bom | `d-ai-bom.yaml` | **8793** | ClusterIP `http` 80 → 8793 |
| E otel-ai-cost | `e-otel-ai-cost.yaml` | **8792** | ClusterIP `http` 80 → 8792 |
| F cn-work-agent | `f-cn-work-agent.yaml` | **8790** | ClusterIP `http` 80 → 8790 |

Labels: `app.oss-cash-lab.dev/<bet>: "true"` (selector + metadata). Replicas: 1. Resources: `50m/64Mi` requests, `500m/256Mi` limits. Service + containerPort name: **`http`** (so ServiceMonitor `port: http` works). PDBs use `maxUnavailable: 1` (see [PodDisruptionBudget](#poddisruptionbudget) — replica 1 vs drain). Optional HPAs use CPU 70% with `minReplicas: 1` / `maxReplicas: 4` (see [HorizontalPodAutoscaler](#horizontalpodautoscaler) — **metrics-server** required to scale). Optional Ingress uses per-host Prefix `/` (see [Ingress](#ingress) — **ingress controller** required; idle without it). Namespace **LimitRange** fills omitted container requests/limits to match those values (see [LimitRange](#limitrange) — does not change explicit Deployment resources). Namespace **ResourceQuota** caps pods/CPU/memory/services for B–F × HPA max 4 plus headroom (see [ResourceQuota](#resourcequota) — does not change Deployment resource blocks). Each Deployment sets restricted-ish **securityContext** (see [securityContext](#securitycontext) — `runAsUser` 1000 for B/E `node`, 65532 for C/D/F).

## Probes + drain

Each container:

- **livenessProbe:** HTTP GET `/health`, `initialDelaySeconds: 3`, `periodSeconds: 10` — stays **200** during drain (and B circuit-open / C queue-full).
- **readinessProbe:** HTTP GET `/ready`, `initialDelaySeconds: 2`, `periodSeconds: 5` — **503** on SIGTERM drain (`shutting_down`), B `circuit_open`, or C `queue_full`.
- **terminationGracePeriodSeconds: 10** — process drain is ~5s (`--drain-ms` / `SHUTDOWN_DRAIN_MS`, cap 30s) plus buffer so kubelet does not SIGKILL mid-drain.

Compose / `make stack-demo` healthchecks stay on `/health` (do not switch those to `/ready`).

## Env

No committed secrets. Optional names from Compose/CLI are **commented** in each Deployment (F IM tokens, webhook URLs/secrets, `SHUTDOWN_DRAIN_MS`, `LOG_FORMAT`, CORS). Fill via a Secret/ConfigMap in a real cluster; do not invent values here.

## Apply (when you have a cluster)

```bash
kubectl apply -k deploy/k8s
# or one service:
kubectl apply -f deploy/k8s/b-mcp-gateway.yaml
# NetworkPolicy (also in kustomize; built-in networking.k8s.io/v1):
kubectl apply -f deploy/k8s/networkpolicy.yaml
# PodDisruptionBudget (also in kustomize; built-in policy/v1):
kubectl apply -f deploy/k8s/pdb.yaml
# HorizontalPodAutoscaler (also in kustomize; built-in autoscaling/v2;
# needs metrics-server to actually scale — idle without it):
kubectl apply -f deploy/k8s/hpa.yaml
# Ingress (also in kustomize; built-in networking.k8s.io/v1;
# needs an ingress controller — idle without it; TLS omitted):
kubectl apply -f deploy/k8s/ingress.yaml
# LimitRange (also in kustomize; built-in v1; type Container;
# fills omitted requests/limits — does not change explicit resources):
kubectl apply -f deploy/k8s/limitrange.yaml
# ResourceQuota (also in kustomize; built-in v1; namespace hard caps
# for B–F × HPA maxReplicas 4 plus headroom):
kubectl apply -f deploy/k8s/resourcequota.yaml
# metrics scrape + alerts (needs Prometheus Operator CRDs):
kubectl apply -f deploy/k8s/servicemonitor.yaml
kubectl apply -f deploy/k8s/prometheusrule.yaml
```

Default namespace. `kustomization.yaml` lists the five Deployment+Service files **and** `networkpolicy.yaml` **and** `pdb.yaml` **and** `hpa.yaml` **and** `ingress.yaml` **and** `limitrange.yaml` **and** `resourcequota.yaml` (built-in APIs). HPA needs **metrics-server** to scale; without it the objects sit idle and `replicas: 1` is unchanged. Ingress needs an **ingress controller** (ingress-nginx or similar); without it the object sits idle. LimitRange fills omitted container CPU/memory requests/limits (HPA denominator + noisy-neighbor cap) and does **not** change Deployments that already set resources. ResourceQuota caps namespace pods/CPU/memory/services (B–F × HPA maxReplicas 4 plus headroom) so the demo cannot unbounded-scale; floor is ≥ replica=1 so apply does not block the demo. securityContext is baked into each B–F Deployment YAML (no extra overlay). ServiceMonitors and PrometheusRules stay out so apply-k still works without CRDs. This kustomize path stays the **default**; Helm is optional.

## Helm (optional)

A thin chart wrapping these Deployments+Services lives in [`deploy/helm/oss-cash-lab/`](../helm/oss-cash-lab/). Default apply path stays `kubectl apply -k deploy/k8s`. The chart does **not** include ServiceMonitor/PrometheusRule CRDs. Optional NetworkPolicy via `networkPolicy.enabled` (default `false`). Optional PDB via `pdb.enabled` (default `false`; `maxUnavailable: 1` when on). Optional HPA via `hpa.enabled` (default `false`; CPU 70%, min 1 / max 4 when on — needs metrics-server). Optional Ingress via `ingress.enabled` (default `false`; class `nginx`, five hosts when on — needs an ingress controller). Optional LimitRange via `limitRange.enabled` (default **`true`**; type `Container`, defaultRequest 50m/64Mi — does not change explicit Deployment resources). Optional ResourceQuota via `resourceQuota.enabled` (default **`false`** so a thin install into a shared ns does not fight existing quotas). Optional securityContext via `securityContext.enabled` (default **`true`**; restricted-ish PSS on B–F Deployments). See [deploy/helm/README.md](../helm/README.md). `make check-helm` / smoke parse the chart (`helm template` if `helm` is on PATH; otherwise Chart.yaml / values / `{{` templates — skip like docker).

## NetworkPolicy

[`networkpolicy.yaml`](./networkpolicy.yaml) — one `NetworkPolicy` per B–F bet (`---` separated). `apiVersion: networking.k8s.io/v1` (built-in; **listed in** `kustomization.yaml`). `policyTypes: [Ingress, Egress]`.

| Bet | `podSelector.matchLabels` | named port |
|-----|---------------------------|------------|
| B mcp-gateway | `app.oss-cash-lab.dev/b-mcp-gateway: "true"` | `http` |
| C agent-ci | `app.oss-cash-lab.dev/c-agent-ci: "true"` | `http` |
| D ai-bom | `app.oss-cash-lab.dev/d-ai-bom: "true"` | `http` |
| E otel-ai-cost | `app.oss-cash-lab.dev/e-otel-ai-cost: "true"` | `http` |
| F cn-work-agent | `app.oss-cash-lab.dev/f-cn-work-agent: "true"` | `http` |

**Ingress** (TCP `http`, the container/Service port name):

- same namespace: `podSelector: {}` (all pods in the NetworkPolicy namespace)
- Prometheus Operator scrape: any namespace, pods labeled `app.kubernetes.io/name: prometheus` (matches kube-prometheus-stack / Operator; ServiceMonitors scrape `port: http`)
- `kube-system` namespace (`kubernetes.io/metadata.name: kube-system`) for in-cluster probes / CoreDNS-adjacent traffic

**Kubelet probes / CNI:** liveness (`/health`) and readiness (`/ready`) usually come from the **node** IP, not a pod. Many CNIs (Calico/Cilium default) exempt host→pod; some (or a host-firewall mode) will drop them. If probes fail after apply, add an extra ingress peer `- {}` (allow all sources) on port `http`. **Do not** drop the named port. The default CNI on some clusters (Flannel, kindnet without a policy plugin) **ignores** NetworkPolicy — apply is then a no-op for enforcement. Confirm your CNI implements NetworkPolicy before relying on these objects.

**Egress** allow-list (do **not** ship an empty egress list — that default-denies DNS and outbound webhooks):

- DNS: UDP **and** TCP port **53** (CoreDNS / node-local-dns)
- HTTPS: TCP port **443** (B/C/D/E/F webhook POSTs and HTTP upstreams)

This box has **no cluster**; smoke only **parses** the YAML.

## PodDisruptionBudget

[`pdb.yaml`](./pdb.yaml) — one `PodDisruptionBudget` per B–F bet (`---` separated). `apiVersion: policy/v1` (built-in; **listed in** `kustomization.yaml`). Selector `matchLabels` is the same `app.oss-cash-lab.dev/<bet>: "true"` as the Deployment.

| Bet | `selector.matchLabels` | budget |
|-----|------------------------|--------|
| B mcp-gateway | `app.oss-cash-lab.dev/b-mcp-gateway: "true"` | `maxUnavailable: 1` |
| C agent-ci | `app.oss-cash-lab.dev/c-agent-ci: "true"` | `maxUnavailable: 1` |
| D ai-bom | `app.oss-cash-lab.dev/d-ai-bom: "true"` | `maxUnavailable: 1` |
| E otel-ai-cost | `app.oss-cash-lab.dev/e-otel-ai-cost: "true"` | `maxUnavailable: 1` |
| F cn-work-agent | `app.oss-cash-lab.dev/f-cn-work-agent: "true"` | `maxUnavailable: 1` |

**Replica 1 vs drain:** Deployments ship `replicas: 1`. `minAvailable: 1` with one replica **blocks** voluntary eviction (node drain / cluster upgrade) — Kubernetes will not evict the last pod. Static YAML therefore uses **`maxUnavailable: 1`**, which with replica=1 **allows** eviction (the pod is disrupted). That is the safer default for this tree.

**HA:** bump `replicas` to **≥ 2**, then switch the PDB to `minAvailable: 1` if you want voluntary disruptions to keep at least one ready pod. Do not treat this PDB as HA while replicaCount is 1.

This box has **no cluster**; smoke only **parses** the YAML.

## HorizontalPodAutoscaler

[`hpa.yaml`](./hpa.yaml) — one `HorizontalPodAutoscaler` per B–F bet (`---` separated). `apiVersion: autoscaling/v2` (built-in; **listed in** `kustomization.yaml`). `scaleTargetRef` is the Deployment of the same name. `minReplicas: 1`, `maxReplicas: 4`, metric **CPU** `averageUtilization: 70`.

| Bet | `scaleTargetRef.name` | min | max | metric |
|-----|----------------------|-----|-----|--------|
| B mcp-gateway | `b-mcp-gateway` | 1 | 4 | cpu 70% |
| C agent-ci | `c-agent-ci` | 1 | 4 | cpu 70% |
| D ai-bom | `d-ai-bom` | 1 | 4 | cpu 70% |
| E otel-ai-cost | `e-otel-ai-cost` | 1 | 4 | cpu 70% |
| F cn-work-agent | `f-cn-work-agent` | 1 | 4 | cpu 70% |

**metrics-server required.** CPU utilization comes from the `metrics.k8s.io` API (typically the [metrics-server](https://github.com/kubernetes-sigs/metrics-server) addon). Without it, HPA objects still apply but **do not scale** — Deployments stay at `replicas: 1`. That is expected on this tree (no cluster / no metrics-server here). Containers already set CPU **requests** (`50m`) so utilization has a denominator once metrics-server is present.

`minReplicas: 1` does **not** raise the default replica count. Helm `hpa.enabled` defaults **false** so `helm install` does not manage replicas unless you opt in.

This box has **no cluster**; smoke only **parses** the YAML.

## Ingress

[`ingress.yaml`](./ingress.yaml) — one `Ingress` for B–F (`networking.k8s.io/v1`; **listed in** `kustomization.yaml`). **Five host rules**, path **Prefix `/`**, backend Service port **`http`** (80). Per-host `/` so backends do **not** need path strip (services serve `/health` `/ready` `/metrics` at `/`, not under `/mcp` `/ci` …). Path-based on a single host (`oss-cash-lab.local` + `/mcp` `/gateway` `/ci` `/bom` `/cost` `/agent`) would need a rewrite.

| Host | backend Service |
|------|-----------------|
| `gateway.oss-cash-lab.local` | `b-mcp-gateway` |
| `ci.oss-cash-lab.local` | `c-agent-ci` |
| `bom.oss-cash-lab.local` | `d-ai-bom` |
| `cost.oss-cash-lab.local` | `e-otel-ai-cost` |
| `agent.oss-cash-lab.local` | `f-cn-work-agent` |

**ingressClassName: `nginx`** (ingress-nginx). Change `spec.ingressClassName` for Traefik / Contour / HAProxy / Istio. **Needs an ingress controller**; without one the object still applies but **sits idle** (no Address, no traffic).

**TLS omitted** for local — no Secrets. Do not add `spec.tls` here.

**/etc/hosts** (point at the controller / kind/minikube port-forward, often `127.0.0.1`):

```
127.0.0.1 gateway.oss-cash-lab.local ci.oss-cash-lab.local bom.oss-cash-lab.local cost.oss-cash-lab.local agent.oss-cash-lab.local
```

If [NetworkPolicy](#networkpolicy) is in effect, allow the controller namespace (typically `ingress-nginx`) to reach named port `http`. Helm `ingress.enabled` defaults **false** so `helm install` does not require a controller.

This box has **no cluster**; smoke only **parses** the YAML.

## LimitRange

[`limitrange.yaml`](./limitrange.yaml) — one namespace `LimitRange` (`v1`; **listed in** `kustomization.yaml`). `type: Container`. Fills **omitted** container CPU/memory requests and limits so HPA has a request denominator and noisy-neighbor pods cannot burst unbounded.

| field | cpu | memory | matches |
|-------|-----|--------|---------|
| `min` | 25m | 32Mi | below current requests |
| `defaultRequest` | 50m | 64Mi | current Deployment **requests** |
| `default` | 500m | 256Mi | current Deployment **limits** |
| `max` | 1 | 512Mi | above current limits |

Existing B–F Deployments already set `resources` (`50m/64Mi` requests, `500m/256Mi` limits), so this object **does not change** those pods. It only applies when a container omits requests and/or limits (sidecars, future overlays). `min` ≤ request ≤ limit ≤ `max` still holds for the shipped values.

Helm `limitRange.enabled` defaults **true** (same object; disable with `--set limitRange.enabled=false`).

This box has **no cluster**; smoke only **parses** the YAML.

## ResourceQuota

[`resourcequota.yaml`](./resourcequota.yaml) — one namespace `ResourceQuota` (`v1`; **listed in** `kustomization.yaml`). Hard caps sized for **5 B–F services × HPA `maxReplicas: 4`**, plus headroom, so the demo namespace cannot unbounded-scale. Pairs with [LimitRange](#limitrange) (per-container) and [HPA](#horizontalpodautoscaler) (`maxReplicas: 4`).

| hard | value | why |
|------|-------|-----|
| `pods` | 24 | 5 × 4 = 20, plus headroom for Jobs/hooks/rollouts |
| `requests.cpu` | 2 | 5 × 50m × 4 = 1, plus headroom |
| `requests.memory` | 2Gi | 5 × 64Mi × 4 = 1280Mi, plus headroom |
| `limits.cpu` | 12 | 5 × 500m × 4 = 10, plus headroom |
| `limits.memory` | 6Gi | 5 × 256Mi × 4 = 5Gi, plus headroom |
| `services` | 10 | 5 ClusterIP, plus headroom |

**Floor:** caps are **≥** current explicit Deployment requests × `replicas: 1` (5 × 50m/64Mi requests, 5 × 500m/256Mi limits, 5 pods, 5 services) so apply does **not** block the replica=1 demo. Does **not** change Deployment resource blocks or HPA `maxReplicas`.

Helm `resourceQuota.enabled` defaults **false** so a thin install into a shared namespace does not fight existing quotas (`--set resourceQuota.enabled=true` to render).

This box has **no cluster**; smoke only **parses** the YAML.


## securityContext

Baked into each B–F Deployment (no extra file / overlay). Restricted-ish Pod Security Standards so enterprise/CIS questionnaires see non-root, no privilege escalation, drop ALL, and a read-only root filesystem.

**Pod** `securityContext`: `runAsNonRoot: true`, numeric `runAsUser` / `runAsGroup` / `fsGroup` matching the image `USER`, `seccompProfile.type: RuntimeDefault`.

| Bet | Dockerfile USER | runAsUser |
|-----|-----------------|-----------|
| B mcp-gateway | `node` (`node:20-alpine`) | **1000** |
| C agent-ci | `65532` | **65532** |
| D ai-bom | `65532` | **65532** |
| E otel-ai-cost | `node` (`node:20-alpine`) | **1000** |
| F cn-work-agent | `65532` | **65532** |

**Container** `securityContext`: `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, `capabilities.drop: [ALL]`, `runAsNonRoot: true`. No `privileged: true`.

**Writable bits:** `emptyDir` `tmp` at `/tmp` on every bet (Node/Python need it). B/C/F also mount `emptyDir` `data` at `/app/data` (audit JSONL / runs). D/E are read-only besides `/tmp`. No hostPath.

Helm `securityContext.enabled` defaults **true** (same fields; `--set securityContext.enabled=false` omits them).

This box has **no cluster**; smoke only **parses** the YAML.

## ServiceMonitor (Prometheus Operator)

[`servicemonitor.yaml`](./servicemonitor.yaml) — one `ServiceMonitor` per bet (`---` separated) because labels differ (`app.oss-cash-lab.dev/<bet>: "true"`). Each endpoint scrapes `port: http`, `path: /metrics`, `interval: 30s`. `namespaceSelector.any: true` so scrape works in whatever namespace you apply.

**Requires** Prometheus Operator CRDs (`monitoring.coreos.com/v1`). This box has **no cluster** and smoke **does not apply** these objects. `kubectl apply -f deploy/k8s/servicemonitor.yaml` fails without the CRDs; that is expected.

## PrometheusRule (alerting)

[`prometheusrule.yaml`](./prometheusrule.yaml) — one `PrometheusRule` wrapping the same `groups` as [`deploy/prometheus/rules.yaml`](../prometheus/rules.yaml) (vanilla `prometheus --rule.file` / Mimir). Eight actionable alerts on real B–F names (`McpGatewayCircuitOpen`, `McpGatewayRateLimited`, `AgentCiQueueBacklog`, `AgentCiRunFailures`, `AiBomForbiddenLicense`, `AiBomPolicyHits`, `OtelAiCostHigh` example 50 USD, `CnWorkApprovalsStuck`).

**Requires** Prometheus Operator CRDs (`monitoring.coreos.com/v1`). Apply after CRDs: `kubectl apply -f deploy/k8s/prometheusrule.yaml`. Not listed in `kustomization.yaml`. See [deploy/prometheus/README.md](../prometheus/README.md).

## Grafana dashboard (import JSON)

Importable Grafana 9/10 JSON for these B–F `/metrics` lives in [`deploy/grafana/`](../grafana/) ([`oss-cash-lab.json`](../grafana/oss-cash-lab.json)). Grafana → Dashboards → Import; Prometheus datasource uid `prometheus` or `${DS_PROMETHEUS}`. Combined dashboard, five rows (B/C/D/E/F). **No live Grafana** here — `make smoke` only parses JSON (`scripts/check-grafana.sh`). See [deploy/grafana/README.md](../grafana/README.md).

## Prove (no cluster)

`make smoke` runs `scripts/check-k8s.sh` (parse every YAML file; PyYAML `safe_load_all` if installed, else a tiny indent-based subset parser — no new product dependency), `scripts/check-grafana.sh` (load `deploy/grafana/*.json`; no Grafana process), `scripts/check-prometheus-rules.sh` (load `deploy/prometheus/rules.yaml` + this `prometheusrule.yaml`; no Prometheus process), and `scripts/check-dockerfiles.sh` (Dockerfile exists, `EXPOSE` matches the port table, CMD/ENTRYPOINT mentions serve/cli and binds `0.0.0.0`, image HEALTHCHECK → `/health` via wget; skip `docker build` if Docker is missing). Asserts each B–F file has a Deployment and a Service, probe paths `/health` and `/ready` (probe ports stay the containerPort numbers), Service port name `http`, and `terminationGracePeriodSeconds >= 10`. Also parses `servicemonitor.yaml` (kind `ServiceMonitor`, path `/metrics`, 5 monitors) and `prometheusrule.yaml` (kind `PrometheusRule`, ≥6 alerts) — **does not fail if the CRD is unknown**; it is just YAML. Neither CRD file is in `kustomization.yaml`. Parses `networkpolicy.yaml` (5 `NetworkPolicy`, `policyTypes` Ingress+Egress, B–F `podSelector` labels, egress port 53 or 443) and requires it in `kustomization.yaml`. Parses `pdb.yaml` (5 `PodDisruptionBudget`, `policy/v1`, B–F `selector.matchLabels`, `maxUnavailable` or `minAvailable` set) and requires it in `kustomization.yaml`. Parses `hpa.yaml` (5 `HorizontalPodAutoscaler`, `autoscaling/v2`, `minReplicas` ≤ `maxReplicas`, CPU utilization target, B–F `scaleTargetRef` Deployment) and requires it in `kustomization.yaml`. Parses `ingress.yaml` (1 `Ingress`, `networking.k8s.io/v1`, 5 hosts or 5 rules, B–F Service backends, `ingressClassName: nginx`) and requires it in `kustomization.yaml`. Parses `limitrange.yaml` (1 `LimitRange`, `v1`, type `Container`, `defaultRequest.cpu` set) and requires it in `kustomization.yaml`. Parses `resourcequota.yaml` (1 `ResourceQuota`, `v1`, `spec.hard.pods` set) and requires it in `kustomization.yaml`. Asserts each B–F Deployment has pod `runAsNonRoot` + numeric `runAsUser`, container `allowPrivilegeEscalation: false` / `readOnlyRootFilesystem: true` / `capabilities.drop` includes ALL / `runAsNonRoot: true`, and a `/tmp` volumeMount when the root FS is read-only. `make local-mvp` / `make stack-demo` do **not** start Kubernetes, Grafana, Prometheus, Helm, or containers. Helm chart parse is `make check-helm` (also hooked from smoke).
