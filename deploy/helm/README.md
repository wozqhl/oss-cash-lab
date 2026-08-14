# Helm chart (B–F)

Thin **Deployment + Service** chart for the five HTTP bets, using the same placeholder images and ports as [`deploy/k8s/`](../k8s/). Optional **NetworkPolicy** via values (default **off**). Optional **PodDisruptionBudget** via `pdb.enabled` (default **off**). Optional **HorizontalPodAutoscaler** via `hpa.enabled` (default **off**; needs **metrics-server**). Optional **Ingress** via `ingress.enabled` (default **off**; needs an **ingress controller**). Optional **LimitRange** via `limitRange.enabled` (default **on**; type `Container` — fills omitted requests/limits; does not change explicit Deployment resources). Optional **ResourceQuota** via `resourceQuota.enabled` (default **off** so a thin install into a shared ns does not fight existing quotas). Optional **securityContext** via `securityContext.enabled` (default **on**; restricted-ish PSS on B–F Deployments). **No ServiceMonitor / PrometheusRule** (Prometheus Operator CRDs stay out so `helm template` / `helm install` work without those CRDs). After `helm install`, [`templates/NOTES.txt`](./oss-cash-lab/templates/NOTES.txt) prints how to reach B–F (`kubectl port-forward` + `curl /health` `/ready`; Ingress hosts when enabled).

**Not the default apply path.** Copy-paste / kustomize remains `kubectl apply -k deploy/k8s`. Use this chart only if you already run Helm. This box has **no cluster** and often **no helm** binary — CI/`make smoke` **parses** the chart (`helm template` when `helm` is on PATH; otherwise Chart.yaml / values / templates, skip like docker).

## Images are not published

```
ghcr.io/wozqhl/b-mcp-gateway:dev
ghcr.io/wozqhl/c-agent-ci:dev
ghcr.io/wozqhl/d-ai-bom:dev
ghcr.io/wozqhl/e-otel-ai-cost:dev
ghcr.io/wozqhl/f-cn-work-agent:dev
```

`imageRegistry` + per-bet `image.repository` / `tag: dev` in [`oss-cash-lab/values.yaml`](./oss-cash-lab/values.yaml). `imagePullPolicy: IfNotPresent`. Build locally the same way as k8s (see [deploy/k8s/README.md](../k8s/README.md)).

## Ports (CLI / Compose / k8s defaults)

| Bet | values key | containerPort | Service |
|-----|------------|---------------|---------|
| B mcp-gateway | `bets.b-mcp-gateway` | **8787** | ClusterIP `http` 80 → http |
| C agent-ci | `bets.c-agent-ci` | **8791** | ClusterIP `http` 80 → http |
| D ai-bom | `bets.d-ai-bom` | **8793** | ClusterIP `http` 80 → http |
| E otel-ai-cost | `bets.e-otel-ai-cost` | **8792** | ClusterIP `http` 80 → http |
| F cn-work-agent | `bets.f-cn-work-agent` | **8790** | ClusterIP `http` 80 → http |

Labels: `app.oss-cash-lab.dev/<bet>: "true"` (selector + metadata; matches k8s YAML). Replicas: `replicaCount: 1`. Named port: **`http`**. Disable a bet with `bets.<name>.enabled: false`. PDB is off by default so replicaCount 1 can still drain (see [PodDisruptionBudget](#poddisruptionbudget-optional)). HPA is off by default so replicaCount 1 is not managed without metrics-server (see [HorizontalPodAutoscaler](#horizontalpodautoscaler-optional)). Ingress is off by default so install does not require a controller (see [Ingress](#ingress-optional)). LimitRange is **on** by default so omitted container resources still get requests/limits (see [LimitRange](#limitrange-optional)). ResourceQuota is **off** by default so a shared-namespace install does not fight existing quotas (see [ResourceQuota](#resourcequota-optional)). securityContext is **on** by default so B–F pods run restricted-ish PSS (see [securityContext](#securitycontext-optional)).

## Probes + drain

Same as [`deploy/k8s/`](../k8s/): liveness `GET /health`, readiness `GET /ready`, `terminationGracePeriodSeconds: 10`.

## NetworkPolicy (optional)

`networkPolicy.enabled: false` by default. Set `true` to render one `NetworkPolicy` per enabled bet (same Ingress/Egress peers as [`deploy/k8s/networkpolicy.yaml`](../k8s/networkpolicy.yaml): same-namespace + Prometheus scrape + kube-system; egress DNS 53 + HTTPS 443). CNI must implement NetworkPolicy; kubelet probes are node-network — see the k8s README.

## PodDisruptionBudget (optional)

`pdb.enabled: false` by default so `replicaCount: 1` does **not** surprise-block node drain. Set `true` to render one `PodDisruptionBudget` per enabled bet (`policy/v1`, selector `app.oss-cash-lab.dev/<bet>: "true"`, **`maxUnavailable: 1`**).

**Replica 1 vs drain:** `minAvailable: 1` with one replica **blocks** voluntary eviction. This chart therefore uses `maxUnavailable: 1` when PDB is on, matching [`deploy/k8s/pdb.yaml`](../k8s/pdb.yaml). **HA** needs `replicaCount >= 2` plus a `minAvailable: 1` budget (edit the template or overlay); do not treat PDB-on + replicaCount 1 as high availability.

```bash
helm install oss-cash-lab deploy/helm/oss-cash-lab --set pdb.enabled=true
```

## HorizontalPodAutoscaler (optional)

`hpa.enabled: false` by default so `replicaCount: 1` is **not** taken over unless you opt in. Set `true` to render one `HorizontalPodAutoscaler` per enabled bet (`autoscaling/v2`, `scaleTargetRef` the Deployment, **CPU** `averageUtilization` 70, `minReplicas: 1` / `maxReplicas: 4`).

**metrics-server required** to actually scale (`metrics.k8s.io`). Without it, HPA objects sit idle and Deployments stay at `replicaCount: 1`. Containers already set CPU requests (`50m`). This does **not** change the `replicaCount: 1` default.

```bash
helm install oss-cash-lab deploy/helm/oss-cash-lab --set hpa.enabled=true
```

## Ingress (optional)

`ingress.enabled: false` by default so `helm install` does **not** require an ingress controller. Set `true` to render one `Ingress` (`networking.k8s.io/v1`) with five host rules, path **Prefix `/`**, backend Service port **`http`**. Hosts and class live in values (`ingress.className: nginx`, `ingress.hosts`).

| Host | backend Service |
|------|-----------------|
| `gateway.oss-cash-lab.local` | `b-mcp-gateway` |
| `ci.oss-cash-lab.local` | `c-agent-ci` |
| `bom.oss-cash-lab.local` | `d-ai-bom` |
| `cost.oss-cash-lab.local` | `e-otel-ai-cost` |
| `agent.oss-cash-lab.local` | `f-cn-work-agent` |

**Needs ingress-nginx** (or change `ingress.className` for Traefik / Contour / HAProxy / Istio). Without a controller the object sits idle. **TLS omitted** for local (no Secrets). Point `/etc/hosts` at the controller:

```
127.0.0.1 gateway.oss-cash-lab.local ci.oss-cash-lab.local bom.oss-cash-lab.local cost.oss-cash-lab.local agent.oss-cash-lab.local
```

Per-host `/` so backends do not need path strip (same as [`deploy/k8s/ingress.yaml`](../k8s/ingress.yaml)). If NetworkPolicy is on, allow the controller namespace to reach port `http`.

```bash
helm install oss-cash-lab deploy/helm/oss-cash-lab --set ingress.enabled=true
# other controller:
helm install oss-cash-lab deploy/helm/oss-cash-lab --set ingress.enabled=true --set ingress.className=traefik
```

## LimitRange (optional)

`limitRange.enabled: true` by default so omitted container CPU/memory still get a **request** (HPA denominator) and a **limit** (noisy-neighbor cap). Set `false` to skip the object. When on: one `LimitRange` (`v1`, `type: Container`).

| field | cpu | memory | matches |
|-------|-----|--------|---------|
| `min` | 25m | 32Mi | below current requests |
| `defaultRequest` | 50m | 64Mi | current Deployment **requests** |
| `default` | 500m | 256Mi | current Deployment **limits** |
| `max` | 1 | 512Mi | above current limits |

Does **not** change Deployments that already set `resources` (same as [`deploy/k8s/limitrange.yaml`](../k8s/limitrange.yaml)). Values live under `limitRange.*`.

```bash
helm install oss-cash-lab deploy/helm/oss-cash-lab --set limitRange.enabled=false
```

## ResourceQuota (optional)

`resourceQuota.enabled: false` by default so a thin `helm install` into a **shared namespace** does **not** fight existing quotas (unlike LimitRange, which defaults on). Set `true` to render one `ResourceQuota` (`v1`) with hard caps sized for 5 B–F × HPA `maxReplicas: 4` plus headroom (pairs with LimitRange + HPA).

| hard | value | why |
|------|-------|-----|
| `pods` | 24 | 5 × 4 = 20, plus headroom |
| `requests.cpu` | 2 | 5 × 50m × 4 = 1, plus headroom |
| `requests.memory` | 2Gi | 5 × 64Mi × 4 = 1280Mi, plus headroom |
| `limits.cpu` | 12 | 5 × 500m × 4 = 10, plus headroom |
| `limits.memory` | 6Gi | 5 × 256Mi × 4 = 5Gi, plus headroom |
| `services` | 10 | 5 ClusterIP, plus headroom |

Floor is **≥** replica=1 Deployment requests so apply does not block the demo. Does **not** change Deployment resource blocks. Values live under `resourceQuota.hard`.

```bash
helm install oss-cash-lab deploy/helm/oss-cash-lab --set resourceQuota.enabled=true
```


## securityContext (optional)

`securityContext.enabled: true` by default so B–F Deployments render restricted-ish PSS (non-root, no privilege escalation, drop ALL, read-only root + `emptyDir` `/tmp`). Set `false` to omit the fields. When on: same pod+container `securityContext` as [`deploy/k8s/`](../k8s/) (`runAsUser` 1000 for B/E `node`, 65532 for C/D/F; B/C/F also mount `/app/data`).

```bash
helm install oss-cash-lab deploy/helm/oss-cash-lab --set securityContext.enabled=false
```

## Prometheus Operator CRDs

**Not in this chart.** Apply [`deploy/k8s/servicemonitor.yaml`](../k8s/servicemonitor.yaml) and [`deploy/k8s/prometheusrule.yaml`](../k8s/prometheusrule.yaml) separately after the CRDs exist.

## Install (when you have a cluster + helm)

```bash
# render only (no cluster):
helm template oss-cash-lab deploy/helm/oss-cash-lab
# install:
helm install oss-cash-lab deploy/helm/oss-cash-lab
# NetworkPolicy on:
helm install oss-cash-lab deploy/helm/oss-cash-lab --set networkPolicy.enabled=true
# PodDisruptionBudget on (maxUnavailable: 1; replicaCount 1 can still drain):
helm install oss-cash-lab deploy/helm/oss-cash-lab --set pdb.enabled=true
# HorizontalPodAutoscaler on (CPU 70%, min 1 / max 4; needs metrics-server):
helm install oss-cash-lab deploy/helm/oss-cash-lab --set hpa.enabled=true
# Ingress on (class nginx, five *.oss-cash-lab.local hosts; needs ingress-nginx):
helm install oss-cash-lab deploy/helm/oss-cash-lab --set ingress.enabled=true
# LimitRange off (default is on; fills omitted container requests/limits):
helm install oss-cash-lab deploy/helm/oss-cash-lab --set limitRange.enabled=false
# ResourceQuota on (default is off; namespace hard caps for B–F × HPA max 4):
helm install oss-cash-lab deploy/helm/oss-cash-lab --set resourceQuota.enabled=true
# securityContext off (default is on; restricted-ish PSS on B–F Deployments):
helm install oss-cash-lab deploy/helm/oss-cash-lab --set securityContext.enabled=false
# skip a bet:
helm install oss-cash-lab deploy/helm/oss-cash-lab --set bets.e-otel-ai-cost.enabled=false
```

Default namespace. Chart `version` **0.1.0** (`Chart.yaml`).

`helm install` prints [`templates/NOTES.txt`](./oss-cash-lab/templates/NOTES.txt) (last-mile). `helm template` evaluates NOTES (syntax) but does **not** print them.

## NOTES (after install)

[`oss-cash-lab/templates/NOTES.txt`](./oss-cash-lab/templates/NOTES.txt) is the last-mile for this thin chart:

- **Port-forward** each ClusterIP Service (port **80**) using the CLI/container port as the local port, then `curl /health` and `/ready`:
  `kubectl port-forward svc/b-mcp-gateway 8787:80` (C **8791**, D **8793**, E **8792**, F **8790**).
- **Images are placeholders** `ghcr.io/wozqhl/<bet>:dev` — **not published**. Build/load locally or pods ImagePullBackOff.
- When `ingress.enabled`, also print the five hosts (`gateway` / `ci` / `bom` / `cost` / `agent`.oss-cash-lab.local) and an `/etc/hosts` line.
- One-line optional-object status (NetworkPolicy / PDB / HPA / LimitRange / ResourceQuota / SecurityContext). Do not spam.

## Prove (no cluster)

```bash
make check-helm   # also hooked from make smoke
# or: bash scripts/check-helm.sh
```

`scripts/check-helm.py` asserts `Chart.yaml` `name: oss-cash-lab`, `values.yaml` has the five bets, `pdb.enabled` / `hpa.enabled` / `ingress.enabled` / `resourceQuota.enabled` default **false**, `limitRange.enabled` / `securityContext.enabled` default **true**, `templates/*.yaml` contain `{{` plus `Deployment` plus `pdb.yaml` plus `hpa.yaml` plus `ingress.yaml` plus `limitrange.yaml` plus `resourcequota.yaml`, and `templates/NOTES.txt` exists with `port-forward` + `/health`. If `helm` is on PATH it runs `helm template oss-cash-lab deploy/helm/oss-cash-lab` and requires **5 Deployments**, **0** PDB / HPA / Ingress / ResourceQuota, **1** `LimitRange` (`defaultRequest`), and default securityContext fields (`allowPrivilegeEscalation: false`, `readOnlyRootFilesystem`, `/tmp`); rendered NOTES must contain `port-forward` and `/health`; then `--set pdb.enabled=true` must render **5** `PodDisruptionBudget`, `--set hpa.enabled=true` must render **5** `HorizontalPodAutoscaler`, `--set ingress.enabled=true` must render **1** `Ingress` (5 hosts, class nginx) and NOTES must list those hosts plus `/etc/hosts`, `--set limitRange.enabled=false` must render **0** `LimitRange`, `--set resourceQuota.enabled=true` must render **1** `ResourceQuota`, and `--set securityContext.enabled=false` must omit those securityContext fields. If helm is missing, `helm template` is **skipped** (same idea as `check-dockerfiles` / compose-smoke) but NOTES.txt is still parsed for `port-forward` + `/health`. Does **not** apply to a cluster. `make local-mvp` / `make stack-demo` do not run Helm.
