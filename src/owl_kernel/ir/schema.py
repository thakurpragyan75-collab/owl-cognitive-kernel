from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


ALLOWED_PERMISSIONS = frozenset({"READ", "WRITE", "EXECUTE", "NETWORK", "SECRETS", "GIT"})
ALLOWED_ROLES = frozenset(
    {"architect", "researcher", "coder", "debugger", "tester", "security", "docs"}
)


@dataclass(frozen=True)
class Action:
    id: str
    kind: str
    description: str
    depends_on: tuple[str, ...] = ()
    agent: str = "researcher"
    permission: str = "READ"
    model_need: str = "fast_response"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Intent:
    """Intermediate representation of a natural-language goal.

    Natural language is the source language. This IR is the compiled program.
    """

    goal: str
    actors: list[str] = field(default_factory=list)
    resources: list[str] = field(default_factory=list)
    actions: list[Action] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    expected_result: str = ""
    verification_rules: list[str] = field(default_factory=list)
    rollback_policy: str = "isolated_workspace"
    language: str = "en"
    source: str = ""

    def validate(self) -> None:
        if not self.goal.strip():
            raise ValueError("intent goal is empty")
        ids = [a.id for a in self.actions]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate action ids")
        known = set(ids)
        for a in self.actions:
            if a.permission not in ALLOWED_PERMISSIONS:
                raise ValueError(f"illegal permission {a.permission}")
            if a.agent not in ALLOWED_ROLES:
                raise ValueError(f"unknown agent {a.agent}")
            for d in a.depends_on:
                if d not in known:
                    raise ValueError(f"unknown dependency {d}")
                if d == a.id:
                    raise ValueError("self-dependency")
        if _has_cycle(self.actions):
            raise ValueError("action graph has a cycle")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["actions"] = [a.to_dict() for a in self.actions]
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Intent":
        acts = [Action(**{**a, "depends_on": tuple(a.get("depends_on") or ())}) for a in data.get("actions") or []]
        skip = {"actions"}
        kw = {k: v for k, v in data.items() if k not in skip}
        return cls(actions=acts, **kw)


def _has_cycle(actions: list[Action]) -> bool:
    graph = {a.id: list(a.depends_on) for a in actions}
    seen: set[str] = set()
    stack: set[str] = set()

    def dfs(n: str) -> bool:
        if n in stack:
            return True
        if n in seen:
            return False
        stack.add(n)
        for d in graph.get(n, []):
            if dfs(d):
                return True
        stack.remove(n)
        seen.add(n)
        return False

    return any(dfs(n) for n in graph)
