#!/usr/bin/env bash
# Parse-only check for B-F Dockerfiles (no docker build required).
# Asserts Dockerfile + .dockerignore, EXPOSE <port>, CMD/ENTRYPOINT serve/cli
# bound to 0.0.0.0, FROM alpine bases, and HEALTHCHECK GET /health via wget.
# Optional docker build is skipped when docker is unavailable (same idea as
# compose-smoke).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/scripts/check-dockerfiles.py" "$ROOT"
