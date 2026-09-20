from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class Capabilities:
    reasoning: bool = False
    coding: bool = False
    vision: bool = False
    fast_response: bool = True
    long_context: bool = False
    tool_calling: bool = False
    local: bool = True
    cloud: bool = False


@dataclass
class ModelInfo:
    id: str
    name: str
    available: bool
    capabilities: Capabilities
    notes: str = ""
    weight_gb: float = 0
    min_ram_gb: float = 0


class Provider(Protocol):
    info: ModelInfo

    def health(self) -> dict: ...
    def complete(self, prompt: str, *, max_tokens: int = 256) -> str: ...
