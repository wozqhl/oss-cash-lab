#!/usr/bin/env python3
"""Parse-only check for B-F Dockerfiles (no docker build required).

Asserts each HTTP bet has a Dockerfile + .dockerignore, EXPOSE <port>,
CMD/ENTRYPOINT mentions serve/cli and binds 0.0.0.0, FROM matches
the slim alpine bases used by k8s placeholders, and HEALTHCHECK probes
GET /health on that port via busybox wget (interval/timeout present).
Optional docker build is skipped when docker is unavailable (same idea
as compose-smoke).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

EXPECTED = [
    ("b-mcp-gateway", 8787, "node:20-alpine"),
    ("c-agent-ci", 8791, "python:3.12-alpine"),
    ("d-ai-bom", 8793, "python:3.12-alpine"),
    ("e-otel-ai-cost", 8792, "node:20-alpine"),
    ("f-cn-work-agent", 8790, "python:3.12-alpine"),
]

COMPOSE_HINTS = [
    ("b-mcp-gateway", "mcp-gateway"),
    ("c-agent-ci", "agent-ci"),
    ("d-ai-bom", "ai-bom"),
    ("e-otel-ai-cost", "otel-ai-cost"),
    ("f-cn-work-agent", "cn-work-agent"),
]


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def strip_comment(line: str) -> str:
    if line.lstrip().startswith("#"):
        return ""
    return line


def instructions(text: str) -> list[str]:
    out = []
    buf = []
    cont = False
    for raw in text.splitlines():
        line = strip_comment(raw).rstrip()
        if not line.strip() and not cont:
            continue
        if line.endswith("\\"):
            buf.append(line[:-1].rstrip())
            cont = True
            continue
        buf.append(line)
        out.append(" ".join(buf).strip())
        buf = []
        cont = False
    if buf:
        out.append(" ".join(buf).strip())
    return [x for x in out if x]


def last_instr(lines: list[str], names: tuple[str, ...]) -> str | None:
    found = None
    for line in lines:
        for n in names:
            if line.startswith(n + " ") or line == n:
                found = line
    return found


def check_dockerignore(path: Path) -> None:
    if not path.is_file():
        fail(f"missing {path}")
    text = path.read_text(encoding="utf-8")
    for token in ("node_modules", "__pycache__", ".git"):
        if token not in text:
            fail(f"{path}: .dockerignore must mention {token}")


def check_dockerfile(path: Path, bet: str, port: int, base: str) -> None:
    if not path.is_file():
        fail(f"missing {path}")
    lines = instructions(path.read_text(encoding="utf-8"))
    from_line = last_instr(lines, ("FROM",))
    if not from_line or base not in from_line:
        fail(f"{bet}: FROM must include {base} (got {from_line!r})")
    expose = last_instr(lines, ("EXPOSE",))
    if not expose or not re.search(rf"\b{port}\b", expose):
        fail(f"{bet}: EXPOSE {port} missing (got {expose!r})")
    cmd = last_instr(lines, ("CMD", "ENTRYPOINT"))
    if not cmd:
        fail(f"{bet}: missing CMD/ENTRYPOINT")
    low = cmd.lower()
    if "serve" not in low and "cli" not in low:
        fail(f"{bet}: CMD/ENTRYPOINT must mention serve/cli (got {cmd!r})")
    if "0.0.0.0" not in cmd:
        fail(f"{bet}: CMD/ENTRYPOINT must bind 0.0.0.0 (got {cmd!r})")
    hc = last_instr(lines, ("HEALTHCHECK",))
    if not hc:
        fail(f"{bet}: missing HEALTHCHECK")
    if "/health" not in hc:
        fail(f"{bet}: HEALTHCHECK must probe /health (got {hc!r})")
    if "/ready" in hc:
        fail(f"{bet}: HEALTHCHECK must not probe /ready (got {hc!r})")
    if not re.search(rf"\b{port}\b", hc):
        fail(f"{bet}: HEALTHCHECK must mention port {port} (got {hc!r})")
    if "wget" not in hc:
        fail(f"{bet}: HEALTHCHECK must use wget (got {hc!r})")
    if "curl" in hc.lower():
        fail(f"{bet}: HEALTHCHECK must not use curl (got {hc!r})")
    if "--interval" not in hc:
        fail(f"{bet}: HEALTHCHECK missing --interval (got {hc!r})")
    if "--timeout" not in hc:
        fail(f"{bet}: HEALTHCHECK missing --timeout (got {hc!r})")
    print(f"  ok {bet}  {from_line}  {expose}  serve@0.0.0.0  HEALTHCHECK /health:{port}")


def check_compose(root: Path) -> None:
    compose = root / "docker-compose.yml"
    if not compose.is_file():
        fail("missing docker-compose.yml")
    text = compose.read_text(encoding="utf-8")
    for bet, svc in COMPOSE_HINTS:
        ctx = f"context: ./bets/{bet}"
        if ctx not in text:
            fail(f"docker-compose.yml missing {ctx} for {svc}")
        if f"dockerfile: Dockerfile" not in text:
            fail("docker-compose.yml missing dockerfile: Dockerfile")
    print("  ok docker-compose.yml  build contexts match bets/<bet>/Dockerfile")


def maybe_docker_build(root: Path) -> None:
    if shutil.which("docker") is None:
        print("skip: docker not on PATH (parse-only, like compose-smoke)")
        return
    try:
        subprocess.run(
            ["docker", "info"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        print("skip: docker daemon not available (parse-only, like compose-smoke)")
        return
    if os.environ.get("DOCKERFILE_BUILD", "") not in ("1", "true", "yes"):
        print("skip: docker present; set DOCKERFILE_BUILD=1 to build one image")
        return
    bet = "e-otel-ai-cost"
    tag = f"ghcr.io/wozqhl/{bet}:dev"
    ctx = root / "bets" / bet
    print(f"==> docker build -t {tag} bets/{bet}")
    subprocess.run(["docker", "build", "-t", tag, str(ctx)], check=True)
    print(f"  ok docker build {tag}")


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    if len(sys.argv) > 1:
        root = Path(sys.argv[1]).resolve()
    for bet, port, base in EXPECTED:
        df = root / "bets" / bet / "Dockerfile"
        di = root / "bets" / bet / ".dockerignore"
        check_dockerignore(di)
        check_dockerfile(df, bet, port, base)
    check_compose(root)
    maybe_docker_build(root)
    print("dockerfiles ok (parse-only)")


if __name__ == "__main__":
    main()
