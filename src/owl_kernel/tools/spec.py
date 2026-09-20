from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: str
    permissions: frozenset[str]
    side_effects: str
    reversible: bool
    timeout_s: int
    required_args: tuple[str, ...]
    run: Callable[..., Any]


class ToolError(ValueError):
    pass
