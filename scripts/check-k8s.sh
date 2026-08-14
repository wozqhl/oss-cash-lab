#!/usr/bin/env bash
# Parse-only check for deploy/k8s manifests (no cluster, no Helm).
# Prefers PyYAML yaml.safe_load_all when installed; otherwise a tiny indent-based
# subset parser in scripts/check-k8s.py (no new product dependency).
# Asserts each B–F file has a Deployment + Service, probes /health and /ready,
# and terminationGracePeriodSeconds >= 10.
# servicemonitor.yaml is YAML-only (kind ServiceMonitor, path /metrics, 5
# monitors); prometheusrule.yaml is YAML-only (kind PrometheusRule); both
# Prometheus Operator CRDs are not required and not applied in smoke.
# networkpolicy.yaml is networking.k8s.io/v1 (built-in, listed in
# kustomization.yaml): 5 NetworkPolicies, Ingress+Egress, B–F podSelectors.
# pdb.yaml is policy/v1 (built-in, listed in kustomization.yaml): 5
# PodDisruptionBudgets, B–F selectors, maxUnavailable or minAvailable set.
# hpa.yaml is autoscaling/v2 (built-in, listed in kustomization.yaml): 5
# HorizontalPodAutoscalers, min<=max, CPU target, B–F Deployment scaleTargetRef.
# ingress.yaml is networking.k8s.io/v1 (built-in, listed in kustomization.yaml):
# 1 Ingress, 5 hosts or 5 rules, B–F Service backends, class nginx. Needs an
# ingress controller; idle without it. TLS omitted.
# limitrange.yaml is v1 (built-in, listed in kustomization.yaml): 1 LimitRange,
# type Container, defaultRequest.cpu set (HPA denominator if resources omitted).
# resourcequota.yaml is v1 (built-in, listed in kustomization.yaml): 1
# ResourceQuota, spec.hard.pods set (namespace cap; pairs with LimitRange + HPA).
# B–F Deployments: pod+container securityContext (runAsNonRoot, numeric
# runAsUser, drop ALL, no privilege escalation, read-only root + /tmp).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/scripts/check-k8s.py" "$ROOT/deploy/k8s"
