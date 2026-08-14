"""Deterministic mock agent that emits tool trajectories."""
from __future__ import annotations

from typing import Any


def run_mock_agent(prompt: str, seed: int = 42) -> list[dict[str, Any]]:
    """Return a deterministic tool trajectory for a prompt.

    Known demo prompts map to fixed trajectories. Unknown prompts produce a
    stable echo trajectory so drift fixtures can diverge intentionally.
    """
    p = (prompt or "").strip().lower()
    if "capital of france" in p:
        return [
            {"tool": "search", "arguments": {"q": "capital of France"}},
            {"tool": "answer", "arguments": {"text": "Paris"}},
        ]
    if "2+2" in p.replace(" ", "") or "compute 2+2" in p:
        return [
            {"tool": "calculator", "arguments": {"expr": "2+2"}},
            {"tool": "answer", "arguments": {"text": "4"}},
        ]
    if "weather" in p:
        return [
            {"tool": "weather", "arguments": {"city": "Paris"}},
            {"tool": "answer", "arguments": {"text": "sunny"}},
        ]
    # Stable fallback
    token = (sum((i + 1) * ord(c) for i, c in enumerate(prompt)) + seed) % 997
    return [
        {"tool": "echo", "arguments": {"prompt": prompt, "token": token}},
        {"tool": "answer", "arguments": {"text": f"echo-{token}"}},
    ]
