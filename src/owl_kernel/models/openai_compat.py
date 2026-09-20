"""Optional OpenAI-compatible HTTP provider (vLLM / llama.cpp server).

Never downloads weights. Availability is a live health check against a URL.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from .base import Capabilities, ModelInfo


class OpenAICompatProvider:
    def __init__(self, *, provider_id: str, name: str, base_url: str, model: str, cap: Capabilities, weight_gb: float, min_ram_gb: float, notes: str):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.info = ModelInfo(
            id=provider_id,
            name=name,
            available=False,
            capabilities=cap,
            notes=notes,
            weight_gb=weight_gb,
            min_ram_gb=min_ram_gb,
        )

    def health(self) -> dict:
        url = f"{self.base_url}/models"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=2) as res:
                self.info.available = res.status == 200
                return {"id": self.info.id, "available": self.info.available, "status": res.status}
        except Exception as e:
            self.info.available = False
            return {"id": self.info.id, "available": False, "error": str(e)}

    def complete(self, prompt: str, *, max_tokens: int = 256) -> str:
        if not self.info.available:
            self.health()
        if not self.info.available:
            raise RuntimeError(f"provider {self.info.id} unavailable")
        body = json.dumps(
            {"model": self.model, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens}
        ).encode()
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as res:
            data = json.loads(res.read().decode())
        return data["choices"][0]["message"]["content"]
