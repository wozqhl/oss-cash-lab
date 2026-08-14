"""CORS allowlist: preflight OPTIONS + ACAO on GET/POST. Default: disabled (no extra CORS).

Mirrors bets/c-agent-ci/src/agent_ci/cors.py and bets/b-mcp-gateway/src/cors.js
(Python stdlib). Empty origins = deny extra CORS.
"""
from __future__ import annotations

import os
from typing import Any, Mapping

DEFAULT_CORS_METHODS = ["GET", "POST", "OPTIONS"]
DEFAULT_CORS_HEADERS = [
    "Content-Type",
    "Authorization",
    "X-Lark-Signature",
    "X-Lark-Request-Timestamp",
    "X-Lark-Request-Nonce",
    "X-DingTalk-Timestamp",
    "X-DingTalk-Sign",
    "X-Request-Id",
]
DEFAULT_CORS_EXPOSE_HEADERS = [
    "Retry-After",
    "X-Request-Id",
]

ENV_CORS_ORIGINS = "CORS_ORIGINS"


def parse_cors_origins(raw: str | None) -> list[str]:
    """Split CSV origins; empty/None → []. '*' is a valid token."""
    if raw is None:
        return []
    return [p.strip() for p in str(raw).split(",") if p.strip()]


def origins_from_config(config: Mapping[str, Any] | None) -> list[str]:
    """Read config `cors.origins` (list or CSV string). Missing/empty → []."""
    if not config:
        return []
    cors = config.get("cors")
    if not isinstance(cors, dict):
        return []
    origins = cors.get("origins")
    if origins is None:
        return []
    if isinstance(origins, str):
        return parse_cors_origins(origins)
    if isinstance(origins, (list, tuple)):
        return [str(o).strip() for o in origins if str(o).strip()]
    return []


def resolve_cors_origins(
    cli_value: str | None = None,
    env: Mapping[str, str] | None = None,
    config: Mapping[str, Any] | None = None,
) -> list[str]:
    """CLI `--cors-origins` wins when provided (including empty);
    else env `CORS_ORIGINS` if set; else config `cors.origins`.
    """
    if cli_value is not None:
        return parse_cors_origins(cli_value)
    environ = env if env is not None else os.environ
    if ENV_CORS_ORIGINS in environ:
        return parse_cors_origins(environ.get(ENV_CORS_ORIGINS, ""))
    return origins_from_config(config)


def normalize_cors(
    origins: list[str] | None,
    *,
    methods: list[str] | None = None,
    headers: list[str] | None = None,
    expose: list[str] | None = None,
) -> dict[str, Any] | None:
    """Missing / empty origins => disabled (None). origins including '*' allows any Origin."""
    cleaned = [str(o).strip() for o in (origins or []) if str(o).strip()]
    if not cleaned:
        return None
    meth = (
        [str(m).strip().upper() for m in methods if str(m).strip()]
        if methods
        else list(DEFAULT_CORS_METHODS)
    )
    hdrs = (
        [str(h).strip() for h in headers if str(h).strip()]
        if headers
        else list(DEFAULT_CORS_HEADERS)
    )
    exp = (
        [str(h).strip() for h in expose if str(h).strip()]
        if expose
        else list(DEFAULT_CORS_EXPOSE_HEADERS)
    )
    return {
        "origins": cleaned,
        "methods": meth or list(DEFAULT_CORS_METHODS),
        "headers": hdrs or list(DEFAULT_CORS_HEADERS),
        "expose": exp,
        "allow_any": "*" in cleaned,
    }


def request_origin(headers: Mapping[str, str] | None) -> str | None:
    if not headers:
        return None
    raw = None
    getter = getattr(headers, "get", None)
    if callable(getter):
        raw = getter("Origin")
        if raw is None:
            raw = getter("origin")
    if raw is None or raw == "":
        return None
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else ""
    t = str(raw).strip()
    return t or None


def origin_allowed(origin: str | None, cors: dict[str, Any] | None) -> bool:
    if not cors:
        return False
    if cors.get("allow_any"):
        return True
    if not origin:
        return False
    return origin in cors.get("origins", [])


def acao_value(origin: str | None, cors: dict[str, Any] | None) -> str | None:
    if not cors:
        return None
    if cors.get("allow_any"):
        return "*"
    if origin and origin in cors.get("origins", []):
        return origin
    return None


def cors_response_headers(
    origin: str | None,
    cors: dict[str, Any] | None,
) -> dict[str, str]:
    """Headers to merge onto a real (non-preflight) response when Origin matches."""
    if not cors:
        return {}
    acao = acao_value(origin, cors)
    if not acao:
        return {}
    headers = {
        "Access-Control-Allow-Origin": acao,
    }
    if acao != "*":
        headers["Vary"] = "Origin"
    expose = cors.get("expose") or []
    if expose:
        headers["Access-Control-Expose-Headers"] = ", ".join(expose)
    return headers


def handle_preflight(
    origin: str | None,
    cors: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """OPTIONS preflight.

    Returns None when CORS is disabled (caller 404s as usual).
    Allowed origin → {status: 204, headers, body: None}.
    Explicit list + origin not allowed → {status: 403, headers: {}, body}.
    """
    if not cors:
        return None
    if not origin_allowed(origin, cors):
        return {
            "status": 403,
            "headers": {},
            "body": {"error": "forbidden", "reason": "cors_denied"},
        }
    acao = "*" if cors.get("allow_any") else origin
    headers = {
        "Access-Control-Allow-Origin": str(acao),
        "Access-Control-Allow-Methods": ", ".join(cors.get("methods") or DEFAULT_CORS_METHODS),
        "Access-Control-Allow-Headers": ", ".join(cors.get("headers") or DEFAULT_CORS_HEADERS),
        "Access-Control-Max-Age": "600",
    }
    if acao != "*":
        headers["Vary"] = "Origin"
    expose = cors.get("expose") or []
    if expose:
        headers["Access-Control-Expose-Headers"] = ", ".join(expose)
    return {"status": 204, "headers": headers, "body": None}
