"""Thin OWL adapter. HUD stays in OWL. Kernel speaks protocol v1 JSON.

OWL should call these functions (or HTTP later) — never import kernel internals.
"""

from __future__ import annotations

from pathlib import Path

from .protocol.v1 import PROTOCOL_VERSION
from .runtime import Runtime


def health() -> dict:
    return {"protocol": PROTOCOL_VERSION, "ok": True, "service": "owl-cognitive-kernel"}


def start_goal(source: str, repo: str | Path, work: str | Path) -> dict:
    rt = Runtime(work, repo)
    return rt.execute(source)
