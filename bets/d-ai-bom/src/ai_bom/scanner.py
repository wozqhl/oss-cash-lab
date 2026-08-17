"""AI-BOM scanner: models, prompts, MCP deps, packages, policy packs."""
from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

MODEL_RE = re.compile(
    r"(?:gpt-4o(?:-mini)?|claude-[\w-]+|qwen[\w.-]+|deepseek-[\w-]+|bert-base-uncased|huggingface\.co/[\w./-]+)",
    re.I,
)
HF_RE = re.compile(r"huggingface\.co/([\w./-]+)", re.I)
GGUF_RE = re.compile(r"([\w./-]+\.gguf)", re.I)
MCP_RE = re.compile(r"mcp[_-]?server[\w.-]*", re.I)
REQ_PKG_RE = re.compile(r"^([A-Za-z0-9_.-]+)")
SPDX_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+-]*$")
SPDX_EXPR_RE = re.compile(r"\s+(AND|OR|WITH)\s+", re.I)

EXCEPTIONS_FILENAME = ".aibom-exceptions.json"
ENV_EXCEPTIONS = "AI_BOM_EXCEPTIONS"

# Built-in fallback when no --policy is supplied (keeps prior smoke/--strict behavior).
DEFAULT_FORBIDDEN = [
    {
        "id": "pickle.load",
        "pattern": r"\bpickle\.loads?\b",
        "severity": "high",
        "message": "Unsafe pickle deserialization",
    }
]


def load_policy(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("policy must be a JSON object")
    return data


def _compiled_forbidden(policy: dict[str, Any] | None) -> list[dict[str, Any]]:
    raw = (policy or {}).get("forbiddenPatterns") if policy else None
    if not raw:
        raw = DEFAULT_FORBIDDEN
    out = []
    for item in raw:
        try:
            rx = re.compile(item["pattern"])
        except re.error as e:
            raise ValueError(f"bad forbidden pattern {item.get('id')}: {e}") from e
        out.append({**item, "_re": rx})
    return out


def _line_of_match(text: str, start: int) -> int:
    """1-based line number for a match start offset."""
    return text.count("\n", 0, start) + 1


def scan_text(text: str, source: str, forbidden_rules: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    models = sorted(set(MODEL_RE.findall(text)))
    for m in HF_RE.findall(text):
        models.append("huggingface.co/" + m)
    models = sorted(set(models))
    ggufs = sorted(set(GGUF_RE.findall(text)))
    mcps = sorted(set(MCP_RE.findall(text)))
    norm = source.replace("\\", "/")
    prompts = [source] if source.endswith((".prompt", ".prompts.md")) or "/prompts/" in norm else []
    rules = forbidden_rules if forbidden_rules is not None else _compiled_forbidden(None)
    forbidden: list[dict[str, Any]] = []
    for rule in rules:
        for m in rule["_re"].finditer(text):
            forbidden.append(
                {
                    "pattern": rule.get("id") or rule.get("pattern"),
                    "path": source,
                    "line": _line_of_match(text, m.start()),
                    "severity": rule.get("severity", "medium"),
                    "message": rule.get("message", ""),
                }
            )
            break  # one hit per rule per file (stable for CI)
    return {"models": models, "gguf": ggufs, "mcp": mcps, "prompts": prompts, "forbidden": forbidden}


def license_entry_from_spdx(raw: str | None, *, missing: str = "UNKNOWN") -> list[dict[str, Any]]:
    """CycloneDX licenses[] for a raw SPDX id / expression / free-text name.

    missing:
      - "UNKNOWN" -> {"license": {"name": "UNKNOWN"}}
      - "NOASSERTION" -> {"license": {"id": "NOASSERTION"}}  (requirements.txt)
    """
    if raw is None or not str(raw).strip():
        if missing == "NOASSERTION":
            return [{"license": {"id": "NOASSERTION"}}]
        return [{"license": {"name": "UNKNOWN"}}]
    s = str(raw).strip()
    if SPDX_EXPR_RE.search(s):
        return [{"expression": s}]
    if SPDX_ID_RE.fullmatch(s):
        return [{"license": {"id": s}}]
    return [{"license": {"name": s}}]


def _licenses_from_package_json_field(lic: Any) -> list[dict[str, Any]]:
    if isinstance(lic, str):
        return license_entry_from_spdx(lic)
    if isinstance(lic, dict):
        return license_entry_from_spdx(lic.get("type") or lic.get("name"))
    return license_entry_from_spdx(None)


def _license_label(entry: dict[str, Any]) -> str:
    if "expression" in entry:
        return str(entry["expression"])
    lic = entry.get("license") or {}
    if isinstance(lic, dict):
        return str(lic.get("id") or lic.get("name") or "UNKNOWN")
    return "UNKNOWN"


def summarize_licenses(components: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in components:
        licenses = c.get("licenses") or license_entry_from_spdx(None)
        for entry in licenses:
            label = _license_label(entry)
            counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))



def _forbidden_license_id_set(policy: dict[str, Any] | None) -> set[str]:
    if not policy:
        return set()
    raw = policy.get("forbiddenLicenseIds") or []
    out: set[str] = set()
    for item in raw:
        s = str(item).strip()
        if s:
            out.add(s)
    return out


def _spdx_ids_from_license_entry(entry: dict[str, Any]) -> list[str]:
    """Extract SPDX-like ids from a CycloneDX licenses[] entry (id or expression tokens)."""
    if not isinstance(entry, dict):
        return []
    if "expression" in entry:
        expr = str(entry.get("expression") or "")
        parts = SPDX_EXPR_RE.split(expr)
        ids: list[str] = []
        for p in parts:
            tok = p.strip()
            if not tok or tok.upper() in {"AND", "OR", "WITH"}:
                continue
            tok = tok.strip("()")
            if SPDX_ID_RE.fullmatch(tok):
                ids.append(tok)
        return ids
    lic = entry.get("license") or {}
    if isinstance(lic, dict):
        lid = lic.get("id")
        if lid and SPDX_ID_RE.fullmatch(str(lid)):
            return [str(lid)]
    return []


def _check_forbidden_licenses(
    components: list[dict[str, Any]], policy: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Policy hits when a component carries a forbidden SPDX license id."""
    forbidden_ids = _forbidden_license_id_set(policy)
    if not forbidden_ids:
        return []
    hits: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for c in components:
        name = str(c.get("name") or "?")
        cpath = str(c.get("path") or "")
        for entry in c.get("licenses") or []:
            for lid in _spdx_ids_from_license_entry(entry):
                if lid not in forbidden_ids:
                    continue
                key = (lid, name, cpath)
                if key in seen:
                    continue
                seen.add(key)
                hits.append(
                    {
                        "id": f"license/{lid}",
                        "licenseId": lid,
                        "component": name,
                        "path": cpath,
                        "purl": c.get("purl") or c.get("bom-ref") or "",
                        "severity": "high",
                        "message": f"Forbidden license SPDX id: {lid}",
                    }
                )
    return hits


def _attach_default_licenses(components: list[dict[str, Any]]) -> None:
    """Ensure every component has a CycloneDX licenses[] field."""
    unknown = license_entry_from_spdx(None)
    for c in components:
        if "licenses" not in c:
            c["licenses"] = list(unknown)


def _scan_requirements(path: Path) -> list[dict[str, Any]]:
    comps = []
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = REQ_PKG_RE.match(line)
            if m:
                comps.append(
                    {
                        "type": "library",
                        "name": m.group(1),
                        "bom-ref": "pkg:pypi/" + m.group(1),
                        "path": str(path),
                        "purl": "pkg:pypi/" + m.group(1),
                        "licenses": list(license_entry_from_spdx(None, missing="NOASSERTION")),
                    }
                )
    except OSError:
        pass
    return comps


def _scan_package_json(path: Path) -> list[dict[str, Any]]:
    """Scan package.json for name/version/SPDX field."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    name = data.get("name") or path.parent.name
    version = data.get("version")
    if "license" in data:
        licenses = _licenses_from_package_json_field(data.get("license"))
    elif isinstance(data.get("licenses"), list) and data["licenses"]:
        licenses = _licenses_from_package_json_field(data["licenses"][0])
    else:
        licenses = license_entry_from_spdx(None)
    eco = "p" + "kg" + ":" + "n" + "pm/"
    purl = eco + str(name) + (("@" + str(version)) if version else "")
    comp: dict[str, Any] = {
        "type": "library",
        "name": name,
        "path": str(path),
        "bom-ref": purl,
        "purl": purl,
        "licenses": licenses,
    }
    if version:
        comp["version"] = version
    return [comp]


def _scan_pyproject(path: Path) -> list[dict[str, Any]]:
    """Scan pyproject.toml project table for SPDX license."""
    try:
        import tomllib
    except ImportError:  # pragma: no cover
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    project = data.get("project") or {}
    if not isinstance(project, dict):
        project = {}
    name = project.get("name") or path.parent.name
    version = project.get("version")
    raw = None
    if project.get("license-expression"):
        raw = project.get("license-expression")
    else:
        lic = project.get("license")
        if isinstance(lic, str):
            raw = lic
        elif isinstance(lic, dict):
            raw = lic.get("text") or lic.get("id")
    licenses = license_entry_from_spdx(raw if raw else None)
    eco = "p" + "kg" + ":" + "pypi/"
    purl = eco + str(name) + (("@" + str(version)) if version else "")
    comp: dict[str, Any] = {
        "type": "library",
        "name": name,
        "path": str(path),
        "bom-ref": purl,
        "purl": purl,
        "licenses": licenses,
    }
    if version:
        comp["version"] = version
    return [comp]


def _scan_mcp_json(path: Path) -> list[dict[str, Any]]:
    comps = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return comps
    servers = data.get("mcpServers") or data.get("servers") or {}
    for name, cfg in servers.items():
        comps.append(
            {
                "type": "mcp-server",
                "name": name,
                "path": str(path),
                "command": (cfg or {}).get("command"),
            }
        )
    return comps


def _check_disclosures(root: Path, components: list[dict[str, Any]], policy: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not policy:
        return []
    reqs = policy.get("requiredDisclosures") or []
    if not reqs:
        return []
    types = {c.get("type") for c in components}
    names = {c.get("name") for c in components}
    has_model = bool(types & {"model", "model-file"})
    has_prompt = "prompt" in types
    mcp_names = {c.get("name") for c in components if c.get("type") == "mcp-server"}
    prompts_dir = root / "prompts" if root.is_dir() else None
    mcp_cfg = None
    if root.is_dir():
        for cand in ("mcp.json", "mcp_config.json", ".mcp.json"):
            p = root / cand
            if p.is_file():
                mcp_cfg = p
                break

    misses: list[dict[str, Any]] = []
    for d in reqs:
        check = d.get("check")
        ok = True
        detail = ""
        if check == "has_models":
            ok = has_model
            detail = "no model/model-file components" if not ok else ""
        elif check == "prompts_if_dir":
            if prompts_dir and prompts_dir.is_dir() and any(prompts_dir.iterdir()):
                ok = has_prompt
                detail = "prompts/ present but no prompt components" if not ok else ""
        elif check == "mcp_if_config":
            if mcp_cfg:
                declared = _scan_mcp_json(mcp_cfg)
                missing = [c["name"] for c in declared if c["name"] not in mcp_names and c["name"] not in names]
                ok = not missing
                detail = f"missing MCP: {missing}" if missing else ""
        else:
            continue
        if not ok:
            misses.append(
                {
                    "id": d.get("id", check),
                    "check": check,
                    "description_en": d.get("description_en") or d.get("description", ""),
                    "description_zh": d.get("description_zh", ""),
                    "detail": detail,
                }
            )
    return misses



def parse_ignore_arg(value: str | None) -> list[str]:
    """Split CLI --ignore CSV into patterns (comma-separated)."""
    if not value:
        return []
    return [p.strip() for p in value.split(",") if p.strip()]


def load_aibomignore(root: Path) -> list[str]:
    """Load gitignore-like patterns from <root>/.aibomignore (if present)."""
    if not root.is_dir():
        return []
    ign = root / ".aibomignore"
    if not ign.is_file():
        return []
    patterns: list[str] = []
    try:
        lines = ign.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        patterns.append(s)
    return patterns


def is_ignored(rel: str, patterns: list[str]) -> bool:
    """Match relative paths against simple .aibomignore / --ignore patterns.

    Supported forms (gitignore-like, intentionally small):
      - exact prefix: ``vendor/`` or ``vendor`` matches ``vendor/...``
      - ``*`` suffix/glob: ``*.pyc`` matches basename or full relative path
      - directory names: ``node_modules`` matches any path segment of that name
    """
    if not patterns:
        return False
    norm = rel.replace("\\", "/").lstrip("./")
    if not norm:
        return False
    parts = [p for p in norm.split("/") if p]
    basename = parts[-1] if parts else norm
    for raw in patterns:
        pat = raw.replace("\\", "/").strip()
        if not pat:
            continue
        if pat.endswith("/"):
            prefix = pat.rstrip("/")
            if not prefix:
                continue
            if norm == prefix or norm.startswith(prefix + "/"):
                return True
            if prefix in parts:
                return True
            continue
        if "*" in pat:
            if fnmatch.fnmatch(norm, pat) or fnmatch.fnmatch(basename, pat):
                return True
            # also allow segment-level globs (e.g. temp*)
            if any(fnmatch.fnmatch(p, pat) for p in parts):
                return True
            continue
        # exact prefix from root
        if norm == pat or norm.startswith(pat + "/"):
            return True
        # directory / path segment name
        if pat in parts:
            return True
    return False


def _warn_exceptions(msg: str) -> None:
    """stderr warning; never dump file contents (may contain extra fields)."""
    try:
        sys.stderr.write(f"ai-bom: {msg}\n")
        sys.stderr.flush()
    except OSError:
        pass


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def parse_expires_date(raw: Any) -> date | None:
    """Parse YYYY-MM-DD. Invalid → None."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def resolve_exceptions_path(
    cli_value: str | None,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """CLI `--exceptions` wins when provided (including empty); else env.

    Empty/omit → no extra file (scan-root `.aibom-exceptions.json` still auto-detected).
    """
    if cli_value is not None:
        s = str(cli_value).strip()
        return s or None
    environ = env if env is not None else os.environ
    s = str(environ.get(ENV_EXCEPTIONS) or "").strip()
    return s or None


def _normalize_exception(item: Any, idx: int) -> tuple[dict[str, Any] | None, str | None]:
    """Require component + license + reason. Optional expires YYYY-MM-DD."""
    if not isinstance(item, dict):
        return None, f"skipping exception #{idx}: not an object"
    component = str(item.get("component") or "").strip()
    license_id = str(item.get("license") or "").strip()
    reason = str(item.get("reason") or "").strip()
    if not component or not license_id or not reason:
        return None, f"skipping exception #{idx}: missing component, license, or reason"
    expires_raw = item.get("expires")
    expires_s = None
    if expires_raw is not None and str(expires_raw).strip():
        expires_s = str(expires_raw).strip()
        if parse_expires_date(expires_s) is None:
            return None, f"skipping exception #{idx}: invalid expires (use YYYY-MM-DD)"
    return {
        "component": component,
        "license": license_id,
        "reason": reason,
        "expires": expires_s,
    }, None


def load_exceptions_file(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Load sidecar JSON. Missing file → empty. Bad JSON → empty + warning (no crash)."""
    if not path.is_file():
        return [], []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return [], [f"could not read {path.name}; ignoring exceptions"]
    except json.JSONDecodeError:
        return [], [f"invalid JSON in {path.name}; ignoring exceptions"]
    except UnicodeDecodeError:
        return [], [f"invalid encoding in {path.name}; ignoring exceptions"]
    if not isinstance(data, dict):
        return [], [f"{path.name} must be a JSON object; ignoring exceptions"]
    raw_list = data.get("exceptions")
    if raw_list is None:
        return [], []
    if not isinstance(raw_list, list):
        return [], [f"{path.name} exceptions must be an array; ignoring"]
    out: list[dict[str, Any]] = []
    warnings: list[str] = []
    for i, item in enumerate(raw_list):
        entry, warn = _normalize_exception(item, i)
        if warn:
            warnings.append(warn)
        if entry:
            out.append(entry)
    return out, warnings


def collect_exceptions(
    root: Path,
    extra_path: str | None = None,
    *,
    warn: bool = True,
) -> list[dict[str, Any]]:
    """Auto-detect scan-root `.aibom-exceptions.json` and optional extra `--exceptions` file.

    Extra file is first (CLI/env wins on first-match). Same resolved path is loaded once.
    """
    files: list[Path] = []
    seen: set[str] = set()

    def add(p: Path) -> None:
        try:
            key = str(p.resolve())
        except OSError:
            key = str(p)
        if key in seen:
            return
        seen.add(key)
        files.append(p)

    if extra_path:
        ep = Path(extra_path)
        if ep.is_file():
            add(ep)
        elif warn:
            _warn_exceptions(f"exceptions file not found: {ep.name}; ignoring")
    if root.is_dir():
        auto = root / EXCEPTIONS_FILENAME
        if auto.is_file():
            add(auto)

    out: list[dict[str, Any]] = []
    for f in files:
        entries, warnings = load_exceptions_file(f)
        if warn:
            for w in warnings:
                _warn_exceptions(w)
        out.extend(entries)
    return out


def build_policy_gate(
    policy: dict[str, Any] | None,
    *,
    scan_root: Path | None = None,
    exceptions_path: str | None = None,
    exceptions_count: int | None = None,
) -> dict[str, Any]:
    """Active license/policy gate JSON for GET /v1/policy.

    Returns ids/counts only — never dumps policy file contents, regexes,
    exception reasons, ignore-file lines, or secrets. Missing policy → 200-shaped
    empty lists (`ok: true`).
    """
    ids: list[str] = []
    pattern_ids: list[str] = []
    if isinstance(policy, dict):
        for item in policy.get("forbiddenLicenseIds") or []:
            s = str(item).strip()
            if s:
                ids.append(s)
        for item in policy.get("forbiddenPatterns") or []:
            if isinstance(item, dict):
                pid = str(item.get("id") or "").strip()
                if pid:
                    pattern_ids.append(pid)
            elif item is not None and str(item).strip():
                pattern_ids.append(str(item).strip())
    ignore_file = False
    root = Path(scan_root) if scan_root is not None else None
    if root is not None:
        try:
            ignore_file = bool(root.is_dir() and (root / ".aibomignore").is_file())
        except OSError:
            ignore_file = False
    if exceptions_count is None:
        if root is not None:
            exceptions_count = len(
                collect_exceptions(root, extra_path=exceptions_path, warn=False)
            )
        else:
            exceptions_count = 0
    return {
        "ok": True,
        "forbiddenLicenseIds": ids,
        "forbiddenPatterns": pattern_ids,
        "exceptionsCount": int(exceptions_count or 0),
        "ignoreFile": bool(ignore_file),
    }


COMPONENTS_LIST_CAP = 500


def _safe_component_path(raw: Any, scan_root: Path | None = None) -> str:
    """Relative to scan root, else basename. Never an absolute host path."""
    s = str(raw or "").strip()
    if not s:
        return ""
    p = Path(s)
    root = Path(scan_root) if scan_root is not None and str(scan_root) else None
    if root is not None:
        norm = s.replace("\\", "/")
        root_s = str(root).replace("\\", "/")
        if norm == root_s:
            name = Path(norm).name
            return name if name not in ("", ".", "..") else ""
        prefix = root_s.rstrip("/") + "/"
        if norm.startswith(prefix):
            rel = norm[len(prefix) :]
            if rel and ".." not in Path(rel).parts and not Path(rel).is_absolute():
                return rel
        try:
            rel_p = p.resolve().relative_to(root.resolve())
            if rel_p.as_posix() and ".." not in rel_p.parts:
                return rel_p.as_posix()
        except (ValueError, OSError):
            pass
        try:
            rel_p = p.relative_to(root)
            rel = rel_p.as_posix()
            if rel and ".." not in rel_p.parts and not Path(rel).is_absolute():
                return rel
        except ValueError:
            pass
    name = p.name
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        return ""
    return name


def _component_license_label(comp: dict[str, Any]) -> str:
    licenses = comp.get("licenses") or []
    if licenses and isinstance(licenses[0], dict):
        return _license_label(licenses[0])
    return "UNKNOWN"


def list_components(
    bom: dict[str, Any] | None,
    *,
    license: str | None = None,
    scan_root: Path | str | None = None,
    cap: int = COMPONENTS_LIST_CAP,
) -> dict[str, Any]:
    """Lightweight inventory for GET /v1/components.

    Buyers get a table (name, version, license, path) without downloading
    CycloneDX/SPDX. Paths are relative to scan_root or basename — never
    absolute host paths. Optional ``license`` is a case-insensitive exact
    match on the license label. Cap default 500; ``truncated: true`` when
    more match. Empty scan → ``{ok:true, count:0, components:[]}``.
    """
    if scan_root is None:
        meta = ((bom or {}).get("metadata") or {}).get("component") or {}
        raw_root = meta.get("path")
        scan_root = raw_root if raw_root else None
    root = Path(scan_root) if scan_root else None
    want = str(license).strip() if license else ""
    rows: list[dict[str, Any]] = []
    for c in (bom or {}).get("components") or []:
        if not isinstance(c, dict):
            continue
        lic = _component_license_label(c)
        if want and lic.lower() != want.lower():
            continue
        rows.append(
            {
                "name": str(c.get("name") or ""),
                "version": str(c.get("version") or ""),
                "license": lic,
                "path": _safe_component_path(c.get("path"), root),
            }
        )
    limit = cap if isinstance(cap, int) and cap > 0 else COMPONENTS_LIST_CAP
    truncated = len(rows) > limit
    out: dict[str, Any] = {
        "ok": True,
        "count": min(len(rows), limit),
        "components": rows[:limit],
    }
    if truncated:
        out["truncated"] = True
    return out


EXCEPTIONS_LIST_CAP = 500
# Short human note only. Longer legal text stays off the public GET.
_REASON_MAX_LEN = 80
_SECRET_REASON_RE = re.compile(
    r"(sk-|Bearer\s|api[_-]?key|Authorization|whsec_|token=)",
    re.I,
)


def _exception_is_expired(expires_s: str | None, today: date | None = None) -> bool:
    """Same rule as apply_license_exceptions: expires < today UTC."""
    if not expires_s:
        return False
    exp_d = parse_expires_date(expires_s)
    if exp_d is None:
        return False
    day = today if today is not None else utc_today()
    return exp_d < day


def _safe_exception_reason(raw: Any) -> str | None:
    """Include only a short human note. Omit secrets / URLs / long text."""
    s = str(raw or "").strip()
    if not s or len(s) > _REASON_MAX_LEN:
        return None
    if _SECRET_REASON_RE.search(s):
        return None
    low = s.lower()
    if "http://" in low or "https://" in low:
        return None
    return s


def _normalize_expired_filter(expired: Any) -> tuple[bool | None, bool]:
    """Return (filter, unknown). unknown → empty list 200, not 400."""
    if expired is None:
        return None, False
    if expired is True or expired is False:
        return bool(expired), False
    if isinstance(expired, str):
        s = expired.strip().lower()
        if s == "true":
            return True, False
        if s == "false":
            return False, False
        return None, True
    return None, True


def exceptions_json(
    loaded: list[dict[str, Any]] | None,
    expired: Any = None,
    cap: int = EXCEPTIONS_LIST_CAP,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Redacted waiver inventory for GET /v1/exceptions.

    ``count`` is the full matching waiver count (before cap). Array is
    original file order, capped at 500; ``truncated: true`` only when more.
    Empty / None → ``{ok:true, count:0, exceptions:[]}``.

    Never includes sidecar path, full policy JSON, webhook URL/secret,
    API keys, Authorization, or a raw file dump. Optional ``reason`` only
    when it is a short human note already on the sidecar and does not
    look like a secret.
    """
    want, unknown = _normalize_expired_filter(expired)
    if unknown:
        return {"ok": True, "count": 0, "exceptions": []}
    rows: list[dict[str, Any]] = []
    for item in loaded or []:
        if not isinstance(item, dict):
            continue
        exp_raw = item.get("expires")
        exp_s = str(exp_raw).strip() if exp_raw is not None and str(exp_raw).strip() else None
        is_expired = _exception_is_expired(exp_s, today)
        if want is not None and is_expired != want:
            continue
        row: dict[str, Any] = {
            "component": str(item.get("component") or ""),
            "license": str(item.get("license") or ""),
            "expiresAt": exp_s,
            "expired": is_expired,
        }
        reason = _safe_exception_reason(item.get("reason"))
        if reason is not None:
            row["reason"] = reason
        rows.append(row)
    limit = cap if isinstance(cap, int) and cap > 0 else EXCEPTIONS_LIST_CAP
    truncated = len(rows) > limit
    out: dict[str, Any] = {
        "ok": True,
        "count": len(rows),
        "exceptions": rows[:limit],
    }
    if truncated:
        out["truncated"] = True
    return out


def component_name_matches(name: str, pattern: str) -> bool:
    """Exact match, or fnmatch glob when the pattern contains glob chars."""
    if name == pattern:
        return True
    if any(ch in pattern for ch in "*?["):
        return fnmatch.fnmatch(name, pattern)
    return False


def apply_license_exceptions(
    hits: list[dict[str, Any]],
    exceptions: list[dict[str, Any]],
    *,
    today: date | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Split forbidden-license hits into remaining / waived / expiredExceptions.

    Match component name (exact or glob) AND license id. Expired (`expires` < today UTC)
    are not applied — the hit still counts.
    """
    if not hits:
        return [], [], []
    if not exceptions:
        return list(hits), [], []
    day = today if today is not None else utc_today()
    remaining: list[dict[str, Any]] = []
    waived: list[dict[str, Any]] = []
    expired: list[dict[str, Any]] = []
    for hit in hits:
        name = str(hit.get("component") or "")
        lid = str(hit.get("licenseId") or "")
        matched: dict[str, Any] | None = None
        for ex in exceptions:
            if str(ex.get("license") or "") != lid:
                continue
            if not component_name_matches(name, str(ex.get("component") or "")):
                continue
            matched = ex
            break
        if matched is None:
            remaining.append(hit)
            continue
        exp_s = matched.get("expires")
        exp_d = parse_expires_date(exp_s) if exp_s else None
        if exp_d is not None and exp_d < day:
            remaining.append(hit)
            expired.append(
                {
                    "component": name,
                    "license": lid,
                    "reason": matched.get("reason") or "",
                    "expires": str(exp_s),
                }
            )
            continue
        waived.append(
            {
                "component": name,
                "license": lid,
                "reason": matched.get("reason") or "",
                "path": hit.get("path") or "",
                "purl": hit.get("purl") or "",
            }
        )
    return remaining, waived, expired


def bom_without_exceptions(bom: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct a BOM as if license exceptions were not applied (HTTP `?exceptions=` skip)."""
    summary = dict(bom.get("summary") or {})
    waived = list(summary.get("waived") or [])
    fl = list(summary.get("forbiddenLicenses") or [])
    for w in waived:
        if not isinstance(w, dict):
            continue
        lid = str(w.get("license") or "UNKNOWN")
        fl.append(
            {
                "id": f"license/{lid}",
                "licenseId": lid,
                "component": w.get("component"),
                "path": w.get("path") or "",
                "purl": w.get("purl") or "",
                "severity": "high",
                "message": f"Forbidden license SPDX id: {lid}",
            }
        )
    summary["forbiddenLicenses"] = fl
    summary["waived"] = []
    summary["expiredExceptions"] = []
    summary["policyHits"] = (
        len(summary.get("forbidden") or [])
        + len(summary.get("disclosureGaps") or [])
        + len(fl)
    )
    out = dict(bom)
    out["summary"] = summary
    return out


def exceptions_query_skips(raw: str | None, present: bool = False) -> bool:
    """True when HTTP `?exceptions=` means skip applying waivers."""
    if not present:
        return False
    s = str(raw or "").strip().lower()
    return s in ("", "0", "false", "no", "off", "skip", "none")


def scan_path(
    root: Path,
    policy: dict[str, Any] | None = None,
    ignore: list[str] | None = None,
    exceptions_path: str | None = None,
) -> dict[str, Any]:
    components: list[dict[str, Any]] = []
    seen_models: set[str] = set()
    seen_mcp: set[str] = set()
    seen_gguf: set[str] = set()
    prompts: list[str] = []
    forbidden: list[dict[str, Any]] = []
    rules = _compiled_forbidden(policy)
    patterns = list(load_aibomignore(root))
    if ignore:
        patterns.extend(ignore)

    if root.is_file():
        files = [root]
    else:
        exts = {".py", ".ts", ".js", ".json", ".yml", ".yaml", ".md", ".toml", ".prompt", ".txt", ".gguf"}
        files = [p for p in root.rglob("*") if p.is_file() and (p.suffix in exts or p.name == "requirements.txt")]

    for f in files[:500]:
        if root.is_dir():
            try:
                rel_key = f.relative_to(root).as_posix()
            except ValueError:
                rel_key = f.as_posix()
        else:
            rel_key = f.name
        if is_ignored(rel_key, patterns):
            continue
        if f.name == EXCEPTIONS_FILENAME:
            continue
        rel = str(f)
        if f.name == "requirements.txt":
            components.extend(_scan_requirements(f))
        if f.name == "package.json":
            components.extend(_scan_package_json(f))
        if f.name == "pyproject.toml":
            components.extend(_scan_pyproject(f))
        if f.name in {"mcp.json", "mcp_config.json", ".mcp.json"}:
            for c in _scan_mcp_json(f):
                seen_mcp.add(c["name"])
                components.append(c)
        if f.suffix == ".gguf":
            seen_gguf.add(f.name)
            components.append({"type": "model-file", "name": f.name, "path": rel, "format": "gguf"})
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        hit = scan_text(text, rel, rules)
        for m in hit["models"]:
            if m not in seen_models:
                seen_models.add(m)
                components.append({"type": "model", "name": m, "path": rel})
        for g in hit["gguf"]:
            if g not in seen_gguf:
                seen_gguf.add(g)
                components.append({"type": "model-file", "name": g, "path": rel, "format": "gguf"})
        for m in hit["mcp"]:
            if m not in seen_mcp:
                seen_mcp.add(m)
                components.append({"type": "mcp-server", "name": m, "path": rel})
        prompts.extend(hit["prompts"])
        forbidden.extend(hit["forbidden"])

    for p in sorted(set(prompts)):
        components.append({"type": "prompt", "name": Path(p).name, "path": p})

    disclosure_gaps = _check_disclosures(root, components, policy)
    _attach_default_licenses(components)
    license_counts = summarize_licenses(components)
    forbidden_licenses = _check_forbidden_licenses(components, policy)
    exceptions = collect_exceptions(root, extra_path=exceptions_path)
    forbidden_licenses, waived, expired_exceptions = apply_license_exceptions(
        forbidden_licenses, exceptions
    )
    policy_meta = None
    if policy:
        policy_meta = {
            "name": policy.get("name"),
            "version": policy.get("version"),
            "forbiddenRuleCount": len(policy.get("forbiddenPatterns") or []),
            "requiredDisclosureCount": len(policy.get("requiredDisclosures") or []),
            "forbiddenLicenseCount": len(policy.get("forbiddenLicenseIds") or []),
        }

    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.7",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": root.name if root.is_dir() else root.stem,
                "path": str(root),
            },
            "policy": policy_meta,
            "ignorePatterns": patterns,
            "exceptionsCount": len(exceptions),
        },
        "components": components,
        "summary": {
            "models": sorted(seen_models),
            "modelFiles": sorted(seen_gguf),
            "mcpServers": sorted(seen_mcp),
            "prompts": sorted(set(prompts)),
            "forbidden": forbidden,
            "disclosureGaps": disclosure_gaps,
            "forbiddenLicenses": forbidden_licenses,
            "waived": waived,
            "expiredExceptions": expired_exceptions,
            "policyHits": len(forbidden) + len(disclosure_gaps) + len(forbidden_licenses),
            "licenses": license_counts,
        },
    }


def dumps_bom(bom: dict[str, Any]) -> str:
    return json.dumps(bom, indent=2, ensure_ascii=False) + "\n"


def render_evidence(bom: dict[str, Any]) -> str:
    """Short bilingual DRAFT evidence pack for auditors."""
    meta = bom.get("metadata") or {}
    comp = meta.get("component") or {}
    summary = bom.get("summary") or {}
    policy = meta.get("policy") or {}
    components = bom.get("components") or []
    forbidden = summary.get("forbidden") or []
    gaps = summary.get("disclosureGaps") or []
    forbidden_licenses = summary.get("forbiddenLicenses") or []
    waived = summary.get("waived") or []
    expired_exceptions = summary.get("expiredExceptions") or []
    advisory_hits = summary.get("advisoryHits") or []
    by_type: dict[str, list[str]] = {}
    for c in components:
        by_type.setdefault(c.get("type") or "unknown", []).append(c.get("name") or "?")

    lines: list[str] = []
    lines.append("# AI-BOM Compliance Evidence Pack / AI-BOM 合规证据包")
    lines.append("")
    lines.append("> **DRAFT for auditors / 审计草稿** — not a legal attestation. / 非正式鉴证。")
    lines.append("")
    lines.append("## Target / 扫描目标")
    lines.append("")
    lines.append(f"- Name / 名称: `{comp.get('name', '')}`")
    lines.append(f"- Path / 路径: `{comp.get('path', '')}`")
    if policy:
        lines.append(f"- Policy pack / 策略包: `{policy.get('name')}` v{policy.get('version')}")
    else:
        lines.append("- Policy pack / 策略包: _(built-in pickle fallback)_")
    lines.append("")
    lines.append("## Components summary / 组件摘要")
    lines.append("")
    lines.append(f"- Total components / 组件总数: **{len(components)}**")
    lines.append(f"- Models / 模型: {', '.join(f'`{m}`' for m in summary.get('models') or []) or '_none_'}")
    lines.append(f"- Model files / 模型文件: {', '.join(f'`{m}`' for m in summary.get('modelFiles') or []) or '_none_'}")
    lines.append(f"- MCP servers / MCP: {', '.join(f'`{m}`' for m in summary.get('mcpServers') or []) or '_none_'}")
    lines.append(f"- Prompts / 提示词: {len(summary.get('prompts') or [])}")
    lines.append("")
    lic_counts = summary.get("licenses") or summarize_licenses(components)
    lines.append("## License summary / 许可证摘要")
    lines.append("")
    if lic_counts:
        total_lic = sum(lic_counts.values())
        lines.append(f"- Components with licenses field / 含许可证字段组件: **{total_lic}**")
        lines.append(f"- Distinct license keys / 许可证种类: **{len(lic_counts)}**")
        for k, n in lic_counts.items():
            lines.append(f"- `{k}`: **{n}**")
    else:
        lines.append("_No license data. / 无许可证数据。_")
    lines.append("")
    lines.append("### By type / 按类型")
    lines.append("")
    for t, names in sorted(by_type.items()):
        uniq = sorted(set(names))
        lines.append(f"- `{t}` ({len(uniq)}): {', '.join(f'`{n}`' for n in uniq[:20])}")
    lines.append("")
    lines.append("## Policy hits / 策略命中")
    lines.append("")
    lines.append(f"- Forbidden pattern hits / 禁止模式命中: **{len(forbidden)}**")
    lines.append(f"- Disclosure gaps / 披露缺口: **{len(gaps)}**")
    lines.append(f"- Forbidden license hits / 禁止许可证命中: **{len(forbidden_licenses)}**")
    lines.append(f"- Waived licenses / 已豁免许可证: **{len(waived)}**")
    lines.append(f"- Expired exceptions / 过期例外: **{len(expired_exceptions)}**")
    total_hits = summary.get(
        "policyHits", len(forbidden) + len(gaps) + len(forbidden_licenses)
    )
    lines.append(f"- Total policyHits / 合计: **{total_hits}**")
    lines.append("")
    if forbidden:
        lines.append("### Forbidden patterns / 禁止模式")
        lines.append("")
        for h in forbidden:
            lines.append(
                f"- `{h.get('pattern')}` @ `{h.get('path')}`"
                f" [{h.get('severity', '')}] — {h.get('message', '')}"
            )
        lines.append("")
    else:
        lines.append("_No forbidden pattern hits. / 无禁止模式命中。_")
        lines.append("")
    if gaps:
        lines.append("### Required disclosure gaps / 必披披露缺口")
        lines.append("")
        for g in gaps:
            zh = g.get("description_zh") or ""
            en = g.get("description_en") or ""
            lines.append(f"- `{g.get('id')}`: {en}")
            if zh:
                lines.append(f"  - 中文: {zh}")
            if g.get("detail"):
                lines.append(f"  - detail: {g['detail']}")
        lines.append("")
    else:
        lines.append("_No disclosure gaps. / 无披露缺口。_")
        lines.append("")
    if forbidden_licenses:
        lines.append("### Forbidden licenses / 禁止许可证")
        lines.append("")

        for h in forbidden_licenses:
            lines.append(
                f"- `{h.get('licenseId')}` on `{h.get('component')}`"
                f" @ `{h.get('path')}` [{h.get('severity', '')}] — {h.get('message', '')}"
            )
        lines.append("")
    else:
        lines.append("_No forbidden license hits. / 无禁止许可证命中。_")
        lines.append("")
    if waived:
        lines.append("### Waived licenses / 已豁免许可证")
        lines.append("")
        for w in waived:
            lines.append(
                f"- `{w.get('license')}` on `{w.get('component')}`"
                f" — {w.get('reason', '')}"
            )
        lines.append("")
    else:
        lines.append("_No waived licenses. / 无已豁免许可证。_")
        lines.append("")
    if expired_exceptions:
        lines.append("### Expired exceptions / 过期例外")
        lines.append("")
        for e in expired_exceptions:
            lines.append(
                f"- `{e.get('license')}` on `{e.get('component')}`"
                f" expired `{e.get('expires')}` — {e.get('reason', '')}"
            )
        lines.append("")
    else:
        lines.append("_No expired exceptions. / 无过期例外。_")
        lines.append("")
    if advisory_hits:
        lines.append("## Advisory hits / 本地咨询命中")
        lines.append("")
        lines.append(
            f"- Local advisory fixture hits / 本地清单命中: **{len(advisory_hits)}**"
        )
        lines.append("")
        for h in advisory_hits:
            lines.append(
                f"- `{h.get('id')}` on `{h.get('component')}`"
                f" @ `{h.get('path')}` [{h.get('severity', '')}] — {h.get('summary', '')}"
            )
        lines.append("")
        lines.append("_Fixture IDs only. Not NVD completeness. / 仅为本地清单，非 NVD 全量。_")
        lines.append("")

    lines.append("## Exit guidance / 退出码说明")
    lines.append("")
    lines.append("| Code | Meaning |")
    lines.append("|------|---------|")
    lines.append("| 0 | Scan OK (no `--strict` violations) |")
    lines.append("| 1 | `--strict`: forbidden hits, disclosure gaps, and/or forbidden licenses; `--gate-licenses`: forbidden licenses; `--gate-vulns`: local advisory fixture hits |")
    lines.append("| 2 | Usage / IO / policy parse error |")
    lines.append("")
    lines.append("---")
    lines.append("*Generated by ai-bom · DRAFT*")
    lines.append("")
    return "\n".join(lines)


SARIF_SCHEMA = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/"
    "Schemata/sarif-schema-2.1.0.json"
)


def _sarif_level(severity: str | None, default: str = "warning") -> str:
    s = (severity or "").lower()
    if s in ("critical", "high", "error"):
        return "error"
    if s in ("medium", "warning"):
        return "warning"
    if s in ("low", "note", "info"):
        return "note"
    return default


def _rel_uri(path: str, root: Path | None) -> str:
    p = Path(path)
    try:
        if root is not None:
            return p.resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        pass
    return p.as_posix().lstrip("./")


def to_sarif(bom: dict[str, Any], tool_version: str = "0.1.0") -> dict[str, Any]:
    """Build a SARIF 2.1.0 log from a scan BOM (forbidden / licenses / disclosure gaps)."""
    from ai_bom import __version__ as pkg_version

    version = tool_version or pkg_version
    summary = bom.get("summary") or {}
    meta = bom.get("metadata") or {}
    comp = meta.get("component") or {}
    root_path = Path(comp.get("path") or ".")
    policy = meta.get("policy") or {}
    forbidden = summary.get("forbidden") or []
    gaps = summary.get("disclosureGaps") or []
    forbidden_licenses = summary.get("forbiddenLicenses") or []
    waived = summary.get("waived") or []

    rules: list[dict[str, Any]] = []
    rule_index: dict[str, int] = {}

    def ensure_rule(rule_id: str, name: str, desc: str, level: str) -> None:
        if rule_id in rule_index:
            return
        rule_index[rule_id] = len(rules)
        rules.append(
            {
                "id": rule_id,
                "name": name,
                "shortDescription": {"text": name},
                "fullDescription": {"text": desc or name},
                "defaultConfiguration": {"level": level},
                "helpUri": "https://github.com/wozqhl/oss-cash-lab/tree/main/bets/d-ai-bom",
            }
        )

    results: list[dict[str, Any]] = []

    for hit in forbidden:
        rid = str(hit.get("pattern") or "forbidden")
        msg = hit.get("message") or f"Forbidden pattern: {rid}"
        level = _sarif_level(hit.get("severity"), "error")
        ensure_rule(rid, rid, msg, level)
        loc: dict[str, Any] = {
            "physicalLocation": {
                "artifactLocation": {"uri": _rel_uri(str(hit.get("path") or ""), root_path)},
            }
        }
        line = hit.get("line")
        if isinstance(line, int) and line > 0:
            loc["physicalLocation"]["region"] = {"startLine": line}
        results.append(
            {
                "ruleId": rid,
                "ruleIndex": rule_index[rid],
                "level": level,
                "message": {"text": msg},
                "locations": [loc],
            }
        )

    for gap in gaps:
        rid = f"disclosure/{gap.get('id') or gap.get('check') or 'gap'}"
        en = gap.get("description_en") or gap.get("description") or "Required disclosure gap"
        detail = gap.get("detail") or ""
        msg = f"{en}" + (f" ({detail})" if detail else "")
        level = "warning"
        ensure_rule(rid, rid, en, level)
        results.append(
            {
                "ruleId": rid,
                "ruleIndex": rule_index[rid],
                "level": level,
                "kind": "review",
                "message": {"text": msg},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {
                                "uri": (comp.get("name") or root_path.name or "."),
                            }
                        }
                    }
                ],
            }
        )

    for hit in forbidden_licenses:
        lid = str(hit.get("licenseId") or "UNKNOWN")
        rid = str(hit.get("id") or f"license/{lid}")
        msg = hit.get("message") or f"Forbidden license SPDX id: {lid}"
        level = _sarif_level(hit.get("severity"), "error")
        ensure_rule(rid, rid, msg, level)
        if hit.get("path"):
            uri = _rel_uri(str(hit.get("path") or ""), root_path)
        else:
            uri = hit.get("component") or comp.get("name") or root_path.name or "."
        results.append(
            {
                "ruleId": rid,
                "ruleIndex": rule_index[rid],
                "level": level,
                "message": {"text": msg},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": uri},
                        }
                    }
                ],
                "properties": {
                    "licenseId": lid,
                    "component": hit.get("component"),
                    "purl": hit.get("purl") or "",
                },
            }
        )

    for w in waived:
        if not isinstance(w, dict):
            continue
        lid = str(w.get("license") or "UNKNOWN")
        rid = f"license/{lid}"
        reason = str(w.get("reason") or "")
        msg = f"Waived forbidden license {lid} on {w.get('component') or '?'}"
        if reason:
            msg = f"{msg}: {reason}"
        ensure_rule(rid, rid, f"Forbidden license SPDX id: {lid}", "note")
        if w.get("path"):
            uri = _rel_uri(str(w.get("path") or ""), root_path)
        else:
            uri = w.get("component") or comp.get("name") or root_path.name or "."
        results.append(
            {
                "ruleId": rid,
                "ruleIndex": rule_index[rid],
                "level": "note",
                "kind": "review",
                "message": {"text": msg},
                "suppressions": [
                    {
                        "kind": "external",
                        "justification": reason or "license exception",
                    }
                ],
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": uri},
                        }
                    }
                ],
                "properties": {
                    "licenseId": lid,
                    "component": w.get("component"),
                    "purl": w.get("purl") or "",
                    "waived": True,
                },
            }
        )

    driver: dict[str, Any] = {
        "name": "ai-bom",
        "version": version,
        "informationUri": "https://github.com/wozqhl/oss-cash-lab/tree/main/bets/d-ai-bom",
        "rules": rules,
    }
    if policy.get("name"):
        driver["properties"] = {
            "policyName": policy.get("name"),
            "policyVersion": policy.get("version"),
        }

    return {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {"driver": driver},
                "results": results,
                "invocations": [
                    {
                        "executionSuccessful": True,
                        "workingDirectory": {
                            "uri": root_path.as_posix() if root_path.is_absolute() else root_path.resolve().as_posix()
                        },
                    }
                ],
            }
        ],
    }


def dumps_sarif(sarif: dict[str, Any]) -> str:
    return json.dumps(sarif, indent=2, ensure_ascii=False) + "\n"
