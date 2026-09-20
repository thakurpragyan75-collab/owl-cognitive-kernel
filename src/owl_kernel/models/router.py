"""Pick one provider. Never load two giant models. Never fake availability."""

from __future__ import annotations

from .base import Capabilities, ModelInfo, Provider
from .openai_compat import OpenAICompatProvider
from .stub import StubProvider


# Official IDs verified 2026-09:
# Qwen/Qwen3-Coder-30B-A3B-Instruct  Apache-2.0  ~61GB bf16 / ~20GB 4-bit
# mistralai/Devstral-Small-2507      Apache-2.0  ~94GB bf16  (Mac 32GB class, not 8GB)

QWEN = "Qwen/Qwen3-Coder-30B-A3B-Instruct"
DEVSTRAL = "mistralai/Devstral-Small-2507"


class ModelRouter:
    def __init__(self, *, qwen_url: str = "", devstral_url: str = "", cloud_url: str = "", max_loaded: int = 1):
        self.max_loaded = max(1, max_loaded)
        self.stub = StubProvider()
        self.providers: list[Provider] = [self.stub]
        if qwen_url:
            self.providers.append(
                OpenAICompatProvider(
                    provider_id="qwen3-coder",
                    name=QWEN,
                    base_url=qwen_url,
                    model=QWEN,
                    cap=Capabilities(reasoning=True, coding=True, long_context=True, tool_calling=True, local=True),
                    weight_gb=61,
                    min_ram_gb=24,
                    notes="Optional. Do not enable on 8GB machines.",
                )
            )
        if devstral_url:
            self.providers.append(
                OpenAICompatProvider(
                    provider_id="devstral-small-2507",
                    name=DEVSTRAL,
                    base_url=devstral_url,
                    model=DEVSTRAL,
                    cap=Capabilities(reasoning=True, coding=True, tool_calling=True, local=True, long_context=True),
                    weight_gb=94,
                    min_ram_gb=32,
                    notes="Official Mistral: RTX 4090 or Mac 32GB. Not 8GB.",
                )
            )
        if cloud_url:
            self.providers.append(
                OpenAICompatProvider(
                    provider_id="cloud",
                    name="openai-compat-cloud",
                    base_url=cloud_url,
                    model="default",
                    cap=Capabilities(reasoning=True, coding=True, cloud=True, local=False, tool_calling=True),
                    weight_gb=0,
                    min_ram_gb=0,
                    notes="Optional cloud. Disabled unless URL set.",
                )
            )
        self._loaded: str | None = None

    def health_all(self) -> list[dict]:
        out = []
        for p in self.providers:
            h = p.health()
            out.append(h)
        return out

    def available(self) -> list[ModelInfo]:
        infos = []
        for p in self.providers:
            p.health()
            infos.append(p.info)
        return infos

    def choose(self, need: str) -> Provider:
        """need: fast_response | coding | reasoning | long_context"""
        ranking = {
            "coding": ["qwen3-coder", "devstral-small-2507", "cloud", "stub"],
            "reasoning": ["cloud", "qwen3-coder", "devstral-small-2507", "stub"],
            "long_context": ["qwen3-coder", "devstral-small-2507", "cloud", "stub"],
            "fast_response": ["stub", "cloud"],
            "tool_calling": ["qwen3-coder", "devstral-small-2507", "cloud", "stub"],
        }
        order = ranking.get(need, ["stub"])
        by_id = {p.info.id: p for p in self.providers}
        for pid in order:
            p = by_id.get(pid)
            if not p:
                continue
            h = p.health()
            if h.get("available"):
                if p.info.id != "stub" and self._loaded and self._loaded != p.info.id:
                    # refuse to load a second giant model
                    continue
                if p.info.id != "stub":
                    self._loaded = p.info.id
                return p
        return self.stub
