"""Simple local approval records (JSONL) for on-prem MVP."""
from __future__ import annotations

import csv
import html
import io
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_lock = threading.Lock()

DEFAULT_APPROVAL_TTL_SECONDS = 86400
EXPIRED_REASON = "expired"
DEFAULT_APPROVALS_MAX = 2000
ENV_APPROVALS_MAX = "APPROVALS_MAX"
DECIDED_STATUSES = frozenset({"approved", "rejected"})
APPROVAL_LIST_STATUSES = frozenset({"pending", "approved", "rejected", "expired"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(raw: Any) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def resolve_approval_ttl(config: dict[str, Any] | None = None) -> int | None:
    """
    Resolve approval TTL in seconds.

    Priority: APPROVAL_TTL_SECONDS env → config.approval_ttl_seconds → default 86400.
    None means expiry disabled (<=0).
    """
    cfg = config or {}
    raw: Any = os.environ.get("APPROVAL_TTL_SECONDS")
    if raw is None or raw == "":
        raw = cfg.get("approval_ttl_seconds")
    if raw is None or raw == "":
        return DEFAULT_APPROVAL_TTL_SECONDS
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_APPROVAL_TTL_SECONDS
    if n <= 0:
        return None
    return n


def resolve_approvals_max(
    raw: Any = None,
    env: dict[str, str] | None = None,
    config: dict[str, Any] | None = None,
) -> int:
    """CLI `--approvals-max` wins; else env APPROVALS_MAX; else config.approvals_max; else 2000. `0` = unlimited."""
    source = raw
    if source is None or source == "":
        environ = env if env is not None else os.environ
        source = environ.get(ENV_APPROVALS_MAX)
    if source is None or source == "":
        cfg = config or {}
        source = cfg.get("approvals_max")
    if source is None or source == "":
        return DEFAULT_APPROVALS_MAX
    try:
        n = int(source)
    except (TypeError, ValueError):
        return DEFAULT_APPROVALS_MAX
    if n < 0:
        return DEFAULT_APPROVALS_MAX
    return n


def _read_all(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("id"):
                out.append(row)
    return out


def _write_all(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


_UNSET: Any = object()


def _resolve_approvals_max_arg(approvals_max: Any, config: dict[str, Any] | None) -> int:
    if approvals_max is _UNSET:
        return resolve_approvals_max(config=config)
    return resolve_approvals_max(approvals_max, config=config)


def _is_decided(row: dict[str, Any]) -> bool:
    return row.get("status") in DECIDED_STATUSES


def _decided_sort_key(row: dict[str, Any]) -> tuple[float, str]:
    created = _parse_dt(row.get("created_at") or row.get("createdAt"))
    ts = created.timestamp() if created is not None else 0.0
    return (ts, str(row.get("id") or ""))


def _cap_decided_rows(
    rows: list[dict[str, Any]],
    max_decided: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Drop oldest decided rows over cap. Pending kept. ``0`` = unlimited."""
    try:
        cap = int(max_decided)
    except (TypeError, ValueError):
        cap = DEFAULT_APPROVALS_MAX
    if cap <= 0:
        return rows, []
    decided = [r for r in rows if _is_decided(r)]
    extra = len(decided) - cap
    if extra <= 0:
        return rows, []
    decided.sort(key=_decided_sort_key)
    dropped_ids = [str(r.get("id") or "") for r in decided[:extra] if r.get("id")]
    drop = set(dropped_ids)
    kept = [r for r in rows if str(r.get("id") or "") not in drop]
    return kept, dropped_ids


def cap_decided_approvals(
    path: str | Path,
    max_decided: Any = _UNSET,
    *,
    config: dict[str, Any] | None = None,
) -> list[str]:
    """Drop oldest decided (approved/rejected/expired) JSONL rows over cap.

    Pending rows are never dropped. ``max_decided`` 0 = unlimited.
    Returns dropped ids (oldest first).
    """
    cap = _resolve_approvals_max_arg(max_decided, config)
    p = Path(path)
    with _lock:
        rows = _read_all(p)
        kept, dropped = _cap_decided_rows(rows, cap)
        if dropped:
            _write_all(p, kept)
        return dropped


def expire_due(
    path: str | Path,
    ttl_seconds: Any = _UNSET,
    *,
    now: datetime | None = None,
    config: dict[str, Any] | None = None,
    approvals_max: Any = _UNSET,
) -> list[dict[str, Any]]:
    """
    Mark pending approvals older than TTL as rejected with reason=expired.

    Returns the list of records that were expired in this call.
    Omit ttl_seconds to resolve from env/config (default 86400).
    Pass ttl_seconds=None to disable; pass a positive int to force that TTL.
    After expiry, drop oldest decided rows over ``approvals_max`` (pending kept).
    """
    p = Path(path)
    if ttl_seconds is _UNSET:
        ttl = resolve_approval_ttl(config)
    else:
        ttl = ttl_seconds
    cap = _resolve_approvals_max_arg(approvals_max, config)

    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    else:
        moment = moment.astimezone(timezone.utc)

    expired: list[dict[str, Any]] = []
    with _lock:
        rows = _read_all(p)
        changed = False
        if ttl is not None and ttl > 0:
            for i, r in enumerate(rows):
                if r.get("status") != "pending":
                    continue
                created = _parse_dt(r.get("created_at"))
                if created is None:
                    continue
                age = (moment - created).total_seconds()
                if age < ttl:
                    continue
                r = dict(r)
                r["status"] = "rejected"
                r["decision"] = "reject"
                r["reason"] = EXPIRED_REASON
                if not r.get("note"):
                    r["note"] = EXPIRED_REASON
                r["updated_at"] = moment.isoformat()
                rows[i] = r
                expired.append(dict(r))
                changed = True
        kept, dropped = _cap_decided_rows(rows, cap)
        if dropped:
            rows = kept
            changed = True
        if changed:
            _write_all(p, rows)
    return expired


def create_approval(
    path: str | Path,
    text: str,
    platform: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Append a pending approval record; return the created dict.

    Optional request_id is stored as requestId when provided (X-Request-Id).
    """
    p = Path(path)
    rec: dict[str, Any] = {
        "id": f"appr_{uuid.uuid4().hex[:12]}",
        "status": "pending",
        "text": text,
        "platform": platform,
        "created_at": _now(),
        "updated_at": _now(),
        "decision": None,
        "note": None,
        "reason": None,
    }
    if request_id:
        rec["requestId"] = request_id
    with _lock:
        rows = _read_all(p)
        rows.append(rec)
        _write_all(p, rows)
    return dict(rec)


def approval_counts(path: str | Path) -> dict[str, int]:
    """Count pending vs decided JSONL rows. No expire_due (cheap; no write)."""
    pending = 0
    decided = 0
    p = Path(path)
    with _lock:
        rows = _read_all(p)
    for r in rows:
        st = r.get("status")
        if st == "pending":
            pending += 1
        elif st in ("approved", "rejected"):
            decided += 1
    return {"pending": pending, "decided": decided}


def _row_matches_status(row: dict[str, Any], status: str) -> bool:
    """Match a list-filter token. ``expired`` is reason=expired (store status stays rejected)."""
    if status == "expired":
        return (row.get("reason") or "") == EXPIRED_REASON or row.get("status") == "expired"
    return (row.get("status") or "") == status


def filter_approvals_by_status(
    rows: list[dict[str, Any]] | None,
    status: str | None = None,
    *,
    pending_only: bool = False,
) -> list[dict[str, Any]]:
    """Filter list rows in one place.

    Omit ``status`` → unchanged (unless ``pending_only``).
    Allowed: pending / approved / rejected / expired.
    Unknown or empty-invalid → empty list (not an error).
    ``status`` wins over ``pending_only``.
    """
    items = list(rows or [])
    if status is not None:
        want = str(status).strip().lower()
        if want not in APPROVAL_LIST_STATUSES:
            return []
        return [r for r in items if _row_matches_status(r, want)]
    if pending_only:
        return [r for r in items if r.get("status") == "pending"]
    return items


def list_approvals(
    path: str | Path,
    *,
    limit: int | None = 50,
    pending_only: bool = False,
    status: str | None = None,
    ttl_seconds: Any = _UNSET,
    config: dict[str, Any] | None = None,
    approvals_max: Any = _UNSET,
) -> list[dict[str, Any]]:
    """List approvals: pending first, then recent by updated_at desc. Expires due first.

    ``limit=None`` returns all rows (CSV audit export). Default 50 for JSON list.
    Dropped decided rows (over ``approvals_max``) are omitted.
    ``status`` filters after expiry (unknown/empty → empty list). Omit → unfiltered.
    """
    if ttl_seconds is _UNSET:
        expire_due(path, config=config, approvals_max=approvals_max)
    else:
        expire_due(path, ttl_seconds=ttl_seconds, config=config, approvals_max=approvals_max)
    p = Path(path)
    with _lock:
        rows = _read_all(p)
    rows = filter_approvals_by_status(rows, status, pending_only=pending_only)
    pending = [r for r in rows if r.get("status") == "pending"]
    others = [r for r in rows if r.get("status") != "pending"]
    pending.sort(key=lambda r: r.get("updated_at") or r.get("created_at") or "", reverse=True)
    others.sort(key=lambda r: r.get("updated_at") or r.get("created_at") or "", reverse=True)
    ordered = pending + others
    if limit is None:
        return ordered
    return ordered[: max(0, limit)]


CSV_COLUMNS = ("id", "platform", "status", "createdAt", "decidedAt", "reason")


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def approval_csv_row(rec: dict[str, Any] | None) -> dict[str, str]:
    """Map a JSONL approval record to spreadsheet columns. No text/note/tokens/HMAC."""
    r = rec or {}
    status = _csv_cell(r.get("status"))
    created = r.get("createdAt") if r.get("createdAt") not in (None, "") else r.get("created_at")
    decided = ""
    if status in ("approved", "rejected"):
        decided = (
            r.get("decidedAt")
            or r.get("decided_at")
            or r.get("updated_at")
            or ""
        )
    return {
        "id": _csv_cell(r.get("id")),
        "platform": _csv_cell(r.get("platform")),
        "status": status,
        "createdAt": _csv_cell(created),
        "decidedAt": _csv_cell(decided),
        "reason": _csv_cell(r.get("reason")),
    }


def format_approvals_csv(rows: list[dict[str, Any]] | None = None) -> str:
    """Audit CSV: header ``id,platform,status,createdAt,decidedAt,reason``. Empty → header only."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for rec in rows or []:
        mapped = approval_csv_row(rec)
        writer.writerow([mapped[c] for c in CSV_COLUMNS])
    return buf.getvalue()


def _md_escape_cell(value: Any) -> str:
    """Escape `|` and flatten newlines so cells cannot split a GFM table."""
    s = _csv_cell(value)
    s = s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return s.replace("|", "\\|")


def format_approvals_md(rows: list[dict[str, Any]] | None = None) -> str:
    """GFM table for Feishu/WeCom docs. Same columns as CSV. Empty → heading + header only."""
    header = "| " + " | ".join(CSV_COLUMNS) + " |"
    sep = "| " + " | ".join("---" for _ in CSV_COLUMNS) + " |"
    lines = ["# Approvals", header, sep]
    for rec in rows or []:
        mapped = approval_csv_row(rec)
        cells = [_md_escape_cell(mapped[c]) for c in CSV_COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _html_escape(text: Any) -> str:
    """Escape HTML text/attributes (`& < > "`)."""
    return html.escape("" if text is None else str(text), quote=True)


_HTML_STYLE = (
    "body{font-family:ui-sans-serif,system-ui,sans-serif;margin:2rem;color:#111;max-width:56rem}"
    "h1{font-size:1.25rem}"
    "table{border-collapse:collapse;margin:1rem 0;min-width:28rem}"
    "th,td{border:1px solid #ddd;padding:.4rem .6rem;text-align:left}"
    "th{background:#f5f5f5}"
    ".pending{background:#fff8e1}"
    ".pending td.status{color:#b8860b;font-weight:700}"
    ".approved{background:#f1faf3}"
    ".approved td.status{color:#0a7a28;font-weight:700}"
    ".rejected,.expired{background:#fdf2f2}"
    ".rejected td.status,.expired td.status{color:#b00020;font-weight:700}"
    ".meta{color:#555;font-size:.9rem}"
)


def _html_title(rec: dict[str, Any] | None) -> str:
    """Title/summary from approval text. Flatten newlines. Caller must escape."""
    r = rec or {}
    raw = r.get("text")
    if raw in (None, ""):
        raw = r.get("title") or r.get("summary") or ""
    s = "" if raw is None else str(raw)
    return s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")


def _html_row_class(mapped: dict[str, str]) -> str:
    status = (mapped.get("status") or "").strip().lower()
    reason = (mapped.get("reason") or "").strip().lower()
    if status == "pending":
        return "pending"
    if reason == "expired":
        return "expired"
    if status == "approved":
        return "approved"
    return "rejected"


def format_approvals_html(rows: list[dict[str, Any]] | None = None) -> str:
    """Self-contained HTML approval list. No CDN. Empty → heading + “no approvals”.

    Columns similar to CSV/MD plus title/summary from `text`. All text escaped.
    Pending vs decided/expired rows are visually distinct (inline CSS).
    """
    items = rows or []
    row_html: list[str] = []
    for rec in items:
        mapped = approval_csv_row(rec)
        cls = _html_row_class(mapped)
        title = _html_escape(_html_title(rec))
        row_html.append(
            f'<tr class="{cls}">'
            f"<td><code>{_html_escape(mapped['id'])}</code></td>"
            f"<td>{_html_escape(mapped['platform'])}</td>"
            f'<td class="status">{_html_escape(mapped["status"])}</td>'
            f"<td>{title}</td>"
            f"<td>{_html_escape(mapped['createdAt'])}</td>"
            f"<td>{_html_escape(mapped['decidedAt'])}</td>"
            f"<td>{_html_escape(mapped['reason'])}</td>"
            "</tr>"
        )
    tbody = ("\n".join(row_html) + "\n") if row_html else ""
    empty_note = "<p>no approvals</p>\n" if not items else ""
    n = len(items)
    pending_n = sum(1 for r in items if (r.get("status") or "") == "pending")
    try:
        from cn_work_agent import __version__ as _ver
    except Exception:
        _ver = ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Approvals · local list</title>
<style>
{_HTML_STYLE}
</style>
</head>
<body>
<h1>Approvals</h1>
<p class="meta">OSS local serve · hosted IM sync = paid · self-contained HTML · no CDN</p>
{empty_note}<p class="meta">{n} row(s) · pending={pending_n}</p>
<table>
<thead><tr><th>id</th><th>platform</th><th>status</th><th>title</th><th>created</th><th>decided</th><th>reason</th></tr></thead>
<tbody>
{tbody}</tbody>
</table>
<p class="meta">Generated by cn-work-agent {_html_escape(_ver)}</p>
</body>
</html>
"""



def get_approval(
    path: str | Path,
    approval_id: str,
    *,
    ttl_seconds: Any = _UNSET,
    config: dict[str, Any] | None = None,
    approvals_max: Any = _UNSET,
) -> dict[str, Any] | None:
    if ttl_seconds is _UNSET:
        expire_due(path, config=config, approvals_max=approvals_max)
    else:
        expire_due(
            path, ttl_seconds=ttl_seconds, config=config, approvals_max=approvals_max
        )
    p = Path(path)
    with _lock:
        rows = _read_all(p)
    for r in rows:
        if r.get("id") == approval_id:
            return dict(r)
    return None


def decide_approval(
    path: str | Path,
    approval_id: str,
    decision: str,
    note: str | None = None,
    *,
    ttl_seconds: Any = _UNSET,
    config: dict[str, Any] | None = None,
    approvals_max: Any = _UNSET,
) -> dict[str, Any]:
    """Update approval status to approved/rejected. Raises KeyError / ValueError."""
    if ttl_seconds is _UNSET:
        expire_due(path, config=config, approvals_max=approvals_max)
    else:
        expire_due(
            path, ttl_seconds=ttl_seconds, config=config, approvals_max=approvals_max
        )
    cap = _resolve_approvals_max_arg(approvals_max, config)
    decision = (decision or "").strip().lower()
    if decision not in {"approve", "reject"}:
        raise ValueError("decision must be approve or reject")
    status = "approved" if decision == "approve" else "rejected"
    p = Path(path)
    with _lock:
        rows = _read_all(p)
        found: dict[str, Any] | None = None
        for i, r in enumerate(rows):
            if r.get("id") == approval_id:
                if r.get("status") != "pending":
                    if r.get("reason") == EXPIRED_REASON or r.get("note") == EXPIRED_REASON:
                        raise ValueError("approval expired")
                    raise ValueError(f"approval not pending (status={r.get('status')})")
                r = dict(r)
                r["status"] = status
                r["decision"] = decision
                r["note"] = note or ""
                r["reason"] = None
                r["updated_at"] = _now()
                rows[i] = r
                found = r
                break
        if found is None:
            raise KeyError(approval_id)
        rows, _dropped = _cap_decided_rows(rows, cap)
        _write_all(p, rows)
        return dict(found)


def decide_hint(approval_id: str, base_url: str = "http://127.0.0.1:8790") -> str:
    """Human-readable curl hint for deciding an approval."""
    base = base_url.rstrip("/")
    return (
        f'curl -s -X POST {base}/approvals/{approval_id}/decide '
        f'-H \'content-type: application/json\' '
        f'-d \'{{"decision":"approve","note":"ok"}}\''
    )


def is_approval_intent(text: str) -> bool:
    t = (text or "").strip()
    low = t.lower()
    return ("审批" in t) or ("approve request" in low)
