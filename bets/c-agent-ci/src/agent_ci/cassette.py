"""Cassette load/compare helpers for tool trajectories."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_cassette(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "name" not in data:
        data["name"] = path.stem
    if "trajectory" not in data:
        raise ValueError(f"cassette missing trajectory: {path}")
    return data


def normalize_step(step: dict[str, Any]) -> dict[str, Any]:
    return {
        "tool": step.get("tool") or step.get("name"),
        "arguments": step.get("arguments") or step.get("args") or {},
    }


def compare_trajectories(expected: list[dict[str, Any]], actual: list[dict[str, Any]]) -> tuple[bool, str]:
    exp = [normalize_step(s) for s in expected]
    act = [normalize_step(s) for s in actual]
    if exp == act:
        return True, "ok"
    return False, f"expected={exp!r} actual={act!r}"


def write_cassette(path: Path, name: str, prompt: str, trajectory: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"name": name, "prompt": prompt, "trajectory": trajectory}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
