#!/usr/bin/env bash
# Parse-only check for deploy/helm/oss-cash-lab (no cluster).
# Always asserts Chart.yaml name, values.yaml bets, templates contain {{ and
# Deployment. Runs `helm template` when helm is on PATH (5 Deployments,
# PDB, HPA, Ingress, and ResourceQuota off by default; LimitRange on
# by default;
# --set pdb.enabled=true renders 5 PDBs;
# --set hpa.enabled=true renders 5 HPAs;
# --set ingress.enabled=true renders 1 Ingress with 5 hosts;
# --set limitRange.enabled=false renders 0 LimitRange;
# --set resourceQuota.enabled=true renders 1 ResourceQuota;
# securityContext on by default; --set securityContext.enabled=false omits it);
# templates/NOTES.txt must exist (port-forward + /health); helm template
# NOTES (via Files/tpl) must contain those strings when helm is on PATH;
# otherwise skips like docker / compose-smoke. No Prometheus Operator CRDs.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/scripts/check-helm.py" "$ROOT"
