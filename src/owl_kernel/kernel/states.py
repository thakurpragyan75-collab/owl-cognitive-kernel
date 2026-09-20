from __future__ import annotations

from enum import Enum


class TaskState(str, Enum):
    CREATED = "CREATED"
    PLANNED = "PLANNED"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


LEGAL: dict[TaskState, frozenset[TaskState]] = {
    TaskState.CREATED: frozenset({TaskState.PLANNED, TaskState.CANCELLED}),
    TaskState.PLANNED: frozenset({TaskState.READY, TaskState.BLOCKED, TaskState.CANCELLED}),
    TaskState.READY: frozenset({TaskState.RUNNING, TaskState.CANCELLED, TaskState.BLOCKED}),
    TaskState.RUNNING: frozenset(
        {
            TaskState.WAITING,
            TaskState.WAITING_FOR_APPROVAL,
            TaskState.BLOCKED,
            TaskState.FAILED,
            TaskState.VERIFYING,
            TaskState.COMPLETED,
            TaskState.CANCELLED,
        }
    ),
    TaskState.WAITING: frozenset({TaskState.READY, TaskState.CANCELLED, TaskState.FAILED}),
    TaskState.WAITING_FOR_APPROVAL: frozenset({TaskState.RUNNING, TaskState.READY, TaskState.CANCELLED, TaskState.FAILED}),
    TaskState.BLOCKED: frozenset({TaskState.READY, TaskState.CANCELLED, TaskState.FAILED}),
    TaskState.FAILED: frozenset({TaskState.RETRYING, TaskState.CANCELLED}),
    TaskState.RETRYING: frozenset({TaskState.READY, TaskState.RUNNING, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.VERIFYING: frozenset({TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}),
    TaskState.COMPLETED: frozenset(),
    TaskState.CANCELLED: frozenset(),
}


class TransitionError(ValueError):
    pass


def can_transition(src: TaskState, dst: TaskState) -> bool:
    return dst in LEGAL[src]


def require(src: TaskState, dst: TaskState) -> None:
    if not can_transition(src, dst):
        raise TransitionError(f"illegal transition {src.value} → {dst.value}")
