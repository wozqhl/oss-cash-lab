"""Private suite import (dir copy or zip extract)."""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path


def import_suite(source: Path, dest: Path) -> dict:
    """Copy a suite dir or extract a zip into dest.

    Existing dest is replaced. Returns a small summary dict.
    """
    source = source.resolve()
    dest = dest.resolve()
    if not source.exists():
        raise FileNotFoundError(f"import source not found: {source}")

    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    copied = 0
    if source.is_file() and zipfile.is_zipfile(source):
        with zipfile.ZipFile(source, "r") as zf:
            zf.extractall(dest)
            copied = len([n for n in zf.namelist() if not n.endswith("/")])
    elif source.is_dir():
        for item in source.iterdir():
            target = dest / item.name
            if item.is_dir():
                shutil.copytree(item, target)
            else:
                shutil.copy2(item, target)
                copied += 1
    else:
        raise ValueError(f"unsupported import source (need dir or zip): {source}")

    json_count = len(list(dest.rglob("*.json")))
    return {"from": str(source), "to": str(dest), "entries": copied, "json_files": json_count}
