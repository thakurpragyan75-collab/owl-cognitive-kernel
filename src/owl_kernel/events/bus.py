from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable


class EventBus:
    def __init__(self):
        self._h: dict[str, list[Callable[[dict], None]]] = defaultdict(list)
        self.history: list[tuple[str, dict]] = []

    def on(self, name: str, fn: Callable[[dict], None]) -> None:
        self._h[name].append(fn)

    def emit(self, name: str, payload: dict[str, Any] | None = None) -> None:
        payload = payload or {}
        self.history.append((name, payload))
        for fn in self._h.get(name, []):
            fn(payload)
        for fn in self._h.get("*", []):
            fn({"event": name, **payload})
