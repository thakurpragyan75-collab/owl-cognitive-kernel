from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable

from ..events.bus import EventBus
from ..ir.schema import Intent
from ..replay.recorder import Recorder
from .states import TaskState
from .task import Task


class Kernel:
    """Durable task engine. State lives in SQLite so crashes can recover."""

    def __init__(self, db_path: str | Path, *, max_retries: int = 3):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_retries = max_retries
        self.bus = EventBus()
        self.recorder = Recorder(self.db_path.with_suffix(".trace.jsonl"))
        self._con = sqlite3.connect(self.db_path)
        self._con.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        self._con.execute(
            """CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                parent_id TEXT,
                goal TEXT,
                state TEXT,
                priority INTEGER,
                dependencies TEXT,
                agent TEXT,
                model TEXT,
                permissions TEXT,
                retry_count INTEGER,
                max_retries INTEGER,
                timeout_s INTEGER,
                created_at TEXT,
                updated_at TEXT,
                verification TEXT,
                kind TEXT,
                trace_id TEXT,
                outputs_json TEXT
            )"""
        )
        self._con.commit()

    def close(self) -> None:
        self._con.close()

    def submit_intent(self, intent: Intent, trace_id: str = "") -> list[Task]:
        tasks: list[Task] = []
        by_action: dict[str, Task] = {}
        for a in intent.actions:
            t = Task(
                goal=a.description,
                parent_id=None,
                agent=a.agent,
                model=a.model_need,
                permissions=[a.permission],
                kind=a.kind,
                trace_id=trace_id,
                max_retries=self.max_retries,
            )
            by_action[a.id] = t
            tasks.append(t)
        for a in intent.actions:
            t = by_action[a.id]
            t.dependencies = [by_action[d].id for d in a.depends_on]
        for t in tasks:
            t.transit(TaskState.PLANNED)
            ready = not t.dependencies
            t.transit(TaskState.READY if ready else TaskState.BLOCKED)
            self._save(t)
            self.bus.emit("task.created", {"id": t.id, "kind": t.kind})
        return tasks

    def _save(self, t: Task) -> None:
        row = t.to_row()
        cols = ",".join(row)
        qs = ",".join("?" for _ in row)
        self._con.execute(f"INSERT OR REPLACE INTO tasks ({cols}) VALUES ({qs})", list(row.values()))
        self._con.commit()

    def get(self, task_id: str) -> Task | None:
        cur = self._con.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        r = cur.fetchone()
        if not r:
            return None
        return self._from_row(r)

    def all_tasks(self) -> list[Task]:
        cur = self._con.execute("SELECT * FROM tasks")
        return [self._from_row(r) for r in cur.fetchall()]

    def ready(self) -> list[Task]:
        return [t for t in self.all_tasks() if t.state == TaskState.READY]

    def recover(self) -> list[Task]:
        """Interrupted RUNNING tasks become FAILED (not blindly retried)."""
        recovered = []
        for t in self.all_tasks():
            if t.state == TaskState.RUNNING:
                t.transit(TaskState.FAILED)
                t.outputs["recovery"] = "interrupted_running"
                self._save(t)
                recovered.append(t)
        return recovered

    def unblock(self) -> None:
        done = {t.id for t in self.all_tasks() if t.state == TaskState.COMPLETED}
        failed = {t.id for t in self.all_tasks() if t.state == TaskState.FAILED}
        for t in self.all_tasks():
            if t.state != TaskState.BLOCKED:
                continue
            if any(d in failed for d in t.dependencies):
                t.transit(TaskState.FAILED)
                t.outputs["blocked_by_failure"] = True
                self._save(t)
            elif all(d in done for d in t.dependencies):
                t.transit(TaskState.READY)
                self._save(t)

    def run_ready(self, handler: Callable[[Task], dict[str, Any]]) -> list[Task]:
        ran = []
        for t in self.ready():
            t.transit(TaskState.RUNNING)
            self._save(t)
            self.bus.emit("task.started", {"id": t.id})
            self.recorder.record(t.trace_id or t.id, "task.started", {"id": t.id, "kind": t.kind})
            try:
                out = handler(t) or {}
                t.outputs.update(out)
                if out.get("failed"):
                    raise RuntimeError(out.get("error") or "task failed")
                if t.kind in {"verify", "run_tests"} or out.get("verify"):
                    t.transit(TaskState.VERIFYING)
                    if out.get("ok", True):
                        t.transit(TaskState.COMPLETED)
                        t.verification = "passed"
                    else:
                        t.transit(TaskState.FAILED)
                        t.verification = "failed"
                else:
                    t.transit(TaskState.COMPLETED)
            except Exception as e:
                t.outputs["error"] = str(e)
                t.transit(TaskState.FAILED)
                if t.retry_count < t.max_retries:
                    t.retry_count += 1
                    t.transit(TaskState.RETRYING)
                    t.transit(TaskState.RUNNING)
                    t.transit(TaskState.FAILED)
            self._save(t)
            self.recorder.record(t.trace_id or t.id, "task.finished", {"id": t.id, "state": t.state.value})
            ran.append(t)
        self.unblock()
        return ran

    def run_to_idle(self, handler: Callable[[Task], dict[str, Any]], *, limit: int = 64) -> list[Task]:
        seen: list[Task] = []
        for _ in range(limit):
            batch = self.run_ready(handler)
            if not batch:
                break
            seen.extend(batch)
        return seen

    @staticmethod
    def _from_row(r: sqlite3.Row) -> Task:
        t = Task(
            goal=r["goal"],
            id=r["id"],
            parent_id=r["parent_id"],
            priority=r["priority"],
            dependencies=[x for x in (r["dependencies"] or "").split(",") if x],
            agent=r["agent"],
            model=r["model"],
            permissions=[x for x in (r["permissions"] or "").split(",") if x],
            retry_count=r["retry_count"],
            max_retries=r["max_retries"],
            timeout_s=r["timeout_s"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
            verification=r["verification"],
            kind=r["kind"],
            trace_id=r["trace_id"] or "",
        )
        t.state = TaskState(r["state"])
        return t
