from __future__ import annotations

import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from ..events.bus import EventBus
from ..ir.schema import Intent
from ..replay.recorder import Recorder
from ..cancel import Cancelled
from .states import TaskState
from .task import Task

READ_KINDS = frozenset(
    {
        "inspect_repo",
        "search_code",
        "analyze_deps",
        "inspect_repository",
        "list_files",
        "read_file",
        "report",
        "verify",
    }
)
DESTRUCTIVE = frozenset({"apply_patch", "self_heal", "run_python"})


class Kernel:
    """Durable task engine. State lives in SQLite so crashes can recover."""

    def __init__(self, db_path: str | Path, *, max_retries: int = 3, max_workers: int = 4):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_retries = max_retries
        self.max_workers = max(1, max_workers)
        self.bus = EventBus()
        self.recorder = Recorder(self.db_path.with_suffix(".trace.jsonl"))
        self._con = sqlite3.connect(self.db_path, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._cancelled: set[str] = set()
        self._approvals: set[str] = set()
        self.cancel_token = None
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
        row["outputs_json"] = json.dumps(t.outputs, default=str)
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
        return [t for t in self.all_tasks() if t.state == TaskState.READY and t.id not in self._cancelled]

    def cancel(self, task_id: str) -> Task | None:
        t = self.get(task_id)
        if not t:
            return None
        self._cancelled.add(task_id)
        if t.state not in {TaskState.COMPLETED, TaskState.CANCELLED}:
            try:
                t.transit(TaskState.CANCELLED)
            except Exception:
                t.state = TaskState.CANCELLED
            self._save(t)
        for child in self.all_tasks():
            if task_id in child.dependencies and child.state not in {TaskState.COMPLETED, TaskState.CANCELLED}:
                self.cancel(child.id)
        self.bus.emit("task.cancelled", {"id": task_id})
        return t

    def approve(self, task_id: str) -> Task | None:
        t = self.get(task_id)
        if not t:
            return None
        self._approvals.add(task_id)
        if t.state == TaskState.WAITING_FOR_APPROVAL:
            t.transit(TaskState.READY)
            self._save(t)
        return t

    def recover(self) -> list[Task]:
        """Interrupted RUNNING tasks become FAILED (not blindly retried)."""
        recovered = []
        for t in self.all_tasks():
            if t.state == TaskState.RUNNING:
                t.transit(TaskState.FAILED)
                t.outputs["recovery"] = "interrupted_running"
                self._save(t)
                recovered.append(t)
            elif t.state == TaskState.RETRYING:
                t.transit(TaskState.READY)
                t.outputs["recovery"] = "retrying_requeued"
                self._save(t)
                recovered.append(t)
        return recovered

    def requeue(self, t: Task, reason: str) -> bool:
        if t.retry_count >= t.max_retries:
            return False
        if t.kind in DESTRUCTIVE:
            # destructive failures stay FAILED until an explicit new candidate
            return False
        t.retry_count += 1
        t.outputs["retry_reason"] = reason
        t.transit(TaskState.RETRYING)
        t.transit(TaskState.READY)
        self._save(t)
        return True

    def unblock(self) -> None:
        done = {t.id for t in self.all_tasks() if t.state == TaskState.COMPLETED}
        failed = {t.id for t in self.all_tasks() if t.state == TaskState.FAILED}
        cancelled = {t.id for t in self.all_tasks() if t.state == TaskState.CANCELLED}
        for t in self.all_tasks():
            if t.state != TaskState.BLOCKED:
                continue
            if any(d in cancelled for d in t.dependencies):
                t.transit(TaskState.CANCELLED)
                self._save(t)
            elif any(d in failed for d in t.dependencies):
                t.transit(TaskState.FAILED)
                t.outputs["blocked_by_failure"] = True
                self._save(t)
            elif all(d in done for d in t.dependencies):
                t.transit(TaskState.READY)
                self._save(t)

    def run_ready(self, handler: Callable[[Task], dict[str, Any]]) -> list[Task]:
        batch = self.ready()
        if not batch:
            return []
        reads = [t for t in batch if t.kind in READ_KINDS]
        rest = [t for t in batch if t not in reads]
        ran: list[Task] = []
        if len(reads) > 1:
            ran.extend(self._run_parallel(reads, handler))
        else:
            for t in reads:
                ran.append(self._run_one(t, handler))
        for t in rest:
            ran.append(self._run_one(t, handler))
        self.unblock()
        return [x for x in ran if x]

    def _run_parallel(self, tasks: list[Task], handler: Callable[[Task], dict[str, Any]]) -> list[Task]:
        if self.cancel_token is not None and self.cancel_token.cancelled():
            ran = []
            for t in tasks:
                try:
                    t.transit(TaskState.CANCELLED)
                except Exception:
                    t.state = TaskState.CANCELLED
                self._save(t)
                ran.append(t)
            return ran
        # handlers run concurrently; sqlite writes stay on this thread after join
        for t in tasks:
            t.transit(TaskState.RUNNING)
            self._save(t)
        results: dict[str, tuple[Task, dict | None, str | None]] = {}

        def call(t: Task) -> tuple[str, dict | None, str | None]:
            if self.cancel_token is not None and self.cancel_token.cancelled():
                return t.id, {"cancelled": True}, "cancelled"
            try:
                return t.id, handler(t) or {}, None
            except Cancelled as e:
                return t.id, {"cancelled": True}, str(e) or "cancelled"
            except Exception as e:
                return t.id, None, str(e)

        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(tasks))) as pool:
            futs = {pool.submit(call, t): t for t in tasks}
            for fut in as_completed(futs):
                tid, out, err = fut.result()
                results[tid] = (futs[fut], out, err)
        ran = []
        for t in tasks:
            _, out, err = results[t.id]
            ran.append(self._finish(t, out, err))
        return ran

    def _run_one(self, t: Task, handler: Callable[[Task], dict[str, Any]]) -> Task:
        if t.id in self._cancelled or (self.cancel_token is not None and self.cancel_token.cancelled()):
            try:
                t.transit(TaskState.CANCELLED)
            except Exception:
                t.state = TaskState.CANCELLED
            self._save(t)
            return t
        t.transit(TaskState.RUNNING)
        self._save(t)
        self.bus.emit("task.started", {"id": t.id})
        self.recorder.record(t.trace_id or t.id, "task.started", {"id": t.id, "kind": t.kind})
        try:
            out = handler(t) or {}
            err = None
        except Cancelled as e:
            self._cancelled.add(t.id)
            try:
                t.transit(TaskState.CANCELLED)
            except Exception:
                t.state = TaskState.CANCELLED
            t.outputs["error"] = str(e) or "cancelled"
            self._save(t)
            return t
        except Exception as e:
            out, err = None, str(e)
        return self._finish(t, out, err)

    def _finish(self, t: Task, out: dict | None, err: str | None) -> Task:
        if t.id in self._cancelled or (self.cancel_token is not None and self.cancel_token.cancelled()) or err == "cancelled" or (out and out.get("cancelled")):
            try:
                t.transit(TaskState.CANCELLED)
            except Exception:
                t.state = TaskState.CANCELLED
            self._save(t)
            return t
        if err:
            t.outputs["error"] = err
            t.transit(TaskState.FAILED)
            self.requeue(t, err)
            self._save(t)
            self.recorder.record(t.trace_id or t.id, "task.finished", {"id": t.id, "state": t.state.value})
            return t
        assert out is not None
        t.outputs.update(out)
        if out.get("failed"):
            t.transit(TaskState.FAILED)
            t.outputs["error"] = out.get("error") or "task failed"
            self.requeue(t, t.outputs["error"])
        elif out.get("awaiting_approval"):
            t.transit(TaskState.WAITING_FOR_APPROVAL)
        elif t.kind in {"verify", "run_tests"} or out.get("verify"):
            t.transit(TaskState.VERIFYING)
            if out.get("ok", True):
                t.transit(TaskState.COMPLETED)
                t.verification = "passed"
            else:
                t.transit(TaskState.FAILED)
                t.verification = "failed"
        else:
            t.transit(TaskState.COMPLETED)
        self._save(t)
        self.recorder.record(t.trace_id or t.id, "task.finished", {"id": t.id, "state": t.state.value})
        return t

    def run_to_idle(self, handler: Callable[[Task], dict[str, Any]], *, limit: int = 64) -> list[Task]:
        seen: list[Task] = []
        idle = 0
        for _ in range(limit):
            if self.cancel_token is not None and self.cancel_token.cancelled():
                for t in self.all_tasks():
                    if t.state not in {TaskState.COMPLETED, TaskState.CANCELLED, TaskState.FAILED}:
                        self._cancelled.add(t.id)
                        try:
                            t.transit(TaskState.CANCELLED)
                        except Exception:
                            t.state = TaskState.CANCELLED
                        self._save(t)
                break
            if self._cancelled and all(t.state in {TaskState.CANCELLED, TaskState.COMPLETED, TaskState.FAILED} for t in self.all_tasks()):
                break
            batch = self.run_ready(handler)
            if not batch:
                idle += 1
                if idle > 1:
                    break
                time.sleep(0.01)
                continue
            idle = 0
            seen.extend(batch)
        return seen

    def deadlock(self) -> bool:
        tasks = self.all_tasks()
        blocked = [t for t in tasks if t.state == TaskState.BLOCKED]
        if not blocked:
            return False
        living = {t.id for t in tasks if t.state not in {TaskState.FAILED, TaskState.CANCELLED, TaskState.COMPLETED}}
        for t in blocked:
            if any(d in living for d in t.dependencies):
                return False
        return True

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
        raw = r["outputs_json"] or "{}"
        try:
            t.outputs = json.loads(raw) if raw.startswith("{") or raw.startswith("[") else {}
        except json.JSONDecodeError:
            t.outputs = {}
        return t
