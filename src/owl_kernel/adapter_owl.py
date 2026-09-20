"""Thin OWL adapter. HUD stays in OWL. Kernel speaks protocol v1 JSON."""

from __future__ import annotations

from pathlib import Path

from .protocol.v1 import PROTOCOL_VERSION, SERVICE_NAME, SERVICE_VERSION
from .runtime import Runtime


def health() -> dict:
    return {
        "ok": True,
        "protocol": PROTOCOL_VERSION,
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
    }


def start_goal(source: str, repo: str | Path, work: str | Path) -> dict:
    rt = Runtime(work, repo)
    return rt.execute(source)
