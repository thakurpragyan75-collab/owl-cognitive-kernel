"""Bounded context for the model. Never dump the whole repository."""

from __future__ import annotations

from dataclasses import dataclass, field


MAX_CHARS = 12_000


@dataclass
class ContextItem:
    why: str
    body: str
    source: str


@dataclass
class Context:
    items: list[ContextItem] = field(default_factory=list)

    def add(self, why: str, body: str, source: str) -> None:
        if any(i.body == body for i in self.items):
            return
        self.items.append(ContextItem(why, body[:4000], source))

    def render(self) -> str:
        parts = []
        n = 0
        for it in self.items:
            chunk = f"[{it.why} | {it.source}]\n{it.body}\n"
            if n + len(chunk) > MAX_CHARS:
                break
            parts.append(chunk)
            n += len(chunk)
        return "\n".join(parts)

    def size(self) -> int:
        return len(self.render())
