from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Plugin:
    name: str
    version: str
    capabilities: list[str]
    permissions: list[str]
    tools: list[str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    api: str = "kernel.v1"


class PluginRegistry:
    def __init__(self):
        self._p: dict[str, Plugin] = {}

    def register(self, plugin: Plugin) -> None:
        if plugin.api != "kernel.v1":
            raise ValueError("unsupported plugin api")
        if "SECRETS" in plugin.permissions:
            raise ValueError("plugins cannot request SECRETS")
        self._p[plugin.name] = plugin

    def get(self, name: str) -> Plugin | None:
        return self._p.get(name)
