from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .states import TaskState, require


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Task:
    goal: str
    id: str = field(default_factory=lambda: str(uuid4()))
    parent_id: str | None = None
    state: TaskState = TaskState.CREATED
    priority: int = 0
    dependencies: list[str] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    agent: str = "researcher"
    model: str = "stub"
    permissions: list[str] = field(default_factory=lambda: ["READ"])
    retry_count: int = 0
    max_retries: int = 3
    timeout_s: int = 120
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    verification: str = "pending"
    kind: str = "generic"
    trace_id: str = ""

    def transit(self, dst: TaskState) -> None:
        require(self.state, dst)
        self.state = dst
        self.updated_at = _now()

    def to_row(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "goal": self.goal,
            "state": self.state.value,
            "priority": self.priority,
            "dependencies": ",".join(self.dependencies),
            "agent": self.agent,
            "model": self.model,
            "permissions": ",".join(self.permissions),
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "timeout_s": self.timeout_s,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "verification": self.verification,
            "kind": self.kind,
            "trace_id": self.trace_id,
            "outputs_json": str(self.outputs),
        }
