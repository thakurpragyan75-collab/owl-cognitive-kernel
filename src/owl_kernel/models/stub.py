from __future__ import annotations

from .base import Capabilities, ModelInfo


class StubProvider:
    """Always available. Never pretends to be Qwen or Devstral."""

    def __init__(self):
        self.info = ModelInfo(
            id="stub",
            name="Deterministic stub",
            available=True,
            capabilities=Capabilities(reasoning=True, coding=True, fast_response=True, local=True),
            notes="Used when no large model is loaded. Honest fallback.",
        )

    def health(self) -> dict:
        return {"id": "stub", "loaded": True, "available": True}

    def complete(self, prompt: str, *, max_tokens: int = 256) -> str:
        p = prompt.lower()
        if "quick sort" in p or "write" in p and "function" in p:
            return "def sort_values(xs):\n    return sorted(xs)\n"
        if "explain" in p:
            return "stub-explain: " + prompt[:180]
        return "stub-ok"
