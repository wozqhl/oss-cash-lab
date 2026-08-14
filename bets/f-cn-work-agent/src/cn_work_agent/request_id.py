"""Resolve X-Request-Id: accept incoming or generate UUID. Echo on every response."""
from __future__ import annotations

import re
import uuid
from typing import Mapping

REQUEST_ID_HEADER = "X-Request-Id"
REQUEST_ID_MAX_LEN = 128
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def generate_request_id() -> str:
    return str(uuid.uuid4())


def is_uuid(value: object) -> bool:
    return isinstance(value, str) and bool(_UUID_RE.fullmatch(value))


def sanitize_request_id(raw: object) -> str | None:
    """Strip CR/LF/NUL, trim, cap length. Empty → None (caller generates)."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else ""
    s = str(raw).replace("\r", "").replace("\n", "").replace("\0", "").strip()
    if not s:
        return None
    if len(s) > REQUEST_ID_MAX_LEN:
        s = s[:REQUEST_ID_MAX_LEN]
    return s


def resolve_request_id(headers: Mapping[str, str] | None = None) -> str:
    """Incoming X-Request-Id or a generated UUID."""
    incoming = None
    if headers is not None:
        getter = getattr(headers, "get", None)
        raw = None
        if callable(getter):
            raw = getter("X-Request-Id")
            if raw is None:
                raw = getter("x-request-id")
        incoming = sanitize_request_id(raw)
    return incoming or generate_request_id()


def request_id_header(request_id: str) -> dict[str, str]:
    return {REQUEST_ID_HEADER: request_id}
