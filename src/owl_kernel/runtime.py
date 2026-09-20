"""Compile → DAG → isolated candidate → model/tool loop → verify. No fixture knowledge."""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .agents.loop import AgentLoop
from .cancel import CancelToken, Cancelled
from .candidate import Candidate, CandidateState
from .codegraph.index import incremental, index_repo
from .failure import parse_pytest
from .ir.compiler import compile_intent
from .kernel.engine import Kernel
from .kernel.task import Task
from .memory.store import Memory
from .metrics import Metrics
from .models.mock_coder import MockCoderProvider
from .models.router import ModelRouter
from .repo_target import RepoTarget, resolve_repository
from .resources import snapshot as resource_snapshot
from .sandbox.exec import Sandbox
from .security.auditor import audit_text, document_is_untrusted
from .tools.builtin import build_tools

SUCCESS_STATES = {"VERIFIED", "WAITING_FOR_APPROVAL", "READY_FOR_PROMOTION"}
LOCKED_STATES = {"CANCELLED", "DISCARDED", "PROMOTION_REJECTED"}


class Runtime:
    def __init__(
        self,
        work: str | Path,
        repo: str | Path | RepoTarget,
        *,
        router: ModelRouter | None = None,
        wait_for_approval: bool = False,
        allowed_roots: list[Path] | None = None,
        max_retries: int = 3,
        max_iterations: int = 24,
        timeout_seconds: int = 300,
    ):
        self.work = Path(work)
        self.work.mkdir(parents=True, exist_ok=True)
        if isinstance(repo, RepoTarget):
            self.target = repo
        else:
            self.target = resolve_repository(repo, allowed_roots=allowed_roots)
        self.repo = self.target.path
        self.max_heal = max(1, int(max_retries))
        self.max_iterations = max(1, int(max_iterations))
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.kernel = Kernel(self.work / "kernel.db", max_retries=self.max_heal)
        self.router = router or ModelRouter()
        self.isolated = self.work / "isolated"
        self.memory = Memory(self.work / "memory.db")
        self.metrics = Metrics()
        self.candidate: Candidate | None = None
        self._agent_ran = False
        self.wait_for_approval = wait_for_approval
        self.cancel_token = CancelToken()
        self.kernel.cancel_token = self.cancel_token
        self.events: list[dict] = []
        self._cv = threading.Condition()
        self._state_lock = threading.Lock()
        self.state = "CREATED"
        self.task_id = ""
        self.findings: list[dict] = []
        self.ctx: dict = {}
        self.attempt = 0
        self.deadline = 0.0

    def emit(self, typ: str, data: dict | None = None) -> None:
        ev = {"type": typ, "timestamp": datetime.now(timezone.utc).isoformat(), "data": data or {}}
        with self._cv:
            self.events.append(ev)
            self._cv.notify_all()
        self.kernel.recorder.record(self.task_id or "runtime", typ, data or {})

    def _set_state(self, new: str) -> str:
        with self._state_lock:
            if self.state in LOCKED_STATES:
                return self.state
            if self.cancel_token.cancelled() and new in SUCCESS_STATES | {"RUNNING", "VERIFYING", "CREATED"}:
                self.state = "CANCELLED"
                return self.state
            self.state = new
            return self.state

    def execute(self, source: str) -> dict:
        self.task_id = self.task_id or str(uuid4())
        self.deadline = time.monotonic() + self.timeout_seconds
        if document_is_untrusted(source):
            self._set_state("FAILED")
            return self._result(ok=False, error="prompt injection in source")
        if self.cancel_token.cancelled():
            return self._cancelled_result()
        host = resource_snapshot()
        intent = compile_intent(source)
        self.emit("task.started", {"task_id": self.task_id, "repository": str(self.repo)})
        self.kernel.submit_intent(intent, trace_id=self.task_id)
        self.candidate = Candidate(self.repo, self.isolated).snapshot()
        self.target.baseline_hash = self.candidate.origin_hash
        self.emit("candidate.snapshotted", {"baseline_hash": self.candidate.origin_hash, "label": self.target.label})
        provider = self._coding_provider()
        self.metrics.provider = provider.info.id
        ctx: dict = {
            "heal_used": 0,
            "trace": self.task_id,
            "intent": intent.to_dict(),
            "provider": provider.info.id,
            "host": host,
        }
        self.ctx = ctx
        if self._set_state("RUNNING") != "RUNNING":
            return self._cancelled_result()
        if self.candidate:
            self.candidate.state = CandidateState.RUNNING

        def handler(t: Task) -> dict:
            self.cancel_token.raise_if_cancelled()
            if time.monotonic() > self.deadline:
                raise Cancelled("timeout")
            return self._handle(t, ctx, provider)

        try:
            self.kernel.run_to_idle(handler)
        except Cancelled:
            return self._cancelled_result()
        if self.cancel_token.cancelled():
            return self._cancelled_result()
        self.ctx = ctx
        self.attempt = int(ctx.get("heal_used") or 0)
        tasks = self.kernel.all_tasks()
        report = next((t for t in tasks if t.kind == "report"), None)
        ok = bool(report and report.state.value == "COMPLETED" and ctx.get("verify_ok"))
        if not ok:
            if self.candidate:
                self.candidate.state = CandidateState.FAILED
                self.candidate.discard()
            self._set_state("FAILED")
            self.emit("task.completed", {"state": self.state})
            return self._result(ok=False, extra={"intent": intent.to_dict()})
        if self.candidate:
            self.candidate.accept_isolated()
            self.candidate.state = CandidateState.VERIFIED
        if self.wait_for_approval:
            if self.candidate:
                self.candidate.state = CandidateState.WAITING_FOR_APPROVAL
            if self._set_state("WAITING_FOR_APPROVAL") != "WAITING_FOR_APPROVAL":
                return self._cancelled_result()
            self.emit("approval.required", {"task_id": self.task_id})
            self.emit("task.completed", {"state": "WAITING_FOR_APPROVAL"})
        else:
            if self._set_state("VERIFIED") != "VERIFIED":
                return self._cancelled_result()
            self.emit("task.completed", {"state": "VERIFIED"})
        return self._result(ok=True, extra={"intent": intent.to_dict()})

    def request_cancel(self, reason: str = "user") -> None:
        self.cancel_token.cancel(reason)
        self.emit("task.cancel_requested", {"reason": reason})
        with self._state_lock:
            if self.state in {"WAITING_FOR_APPROVAL", "VERIFIED", "READY_FOR_PROMOTION"}:
                if self.candidate and not self.candidate.discarded:
                    self.candidate.discard()
                self.state = "CANCELLED"
                self.emit("task.completed", {"state": "CANCELLED"})
            elif self.state not in LOCKED_STATES:
                self.state = "CANCEL_REQUESTED"

    def approve(self, actor: str = "human") -> dict:
        if actor != "human":
            return {"ok": False, "error": {"code": "APPROVAL_DENIED", "message": "only a human actor may approve"}}
        if self.state != "WAITING_FOR_APPROVAL":
            return {"ok": False, "error": {"code": "NOT_WAITING", "message": f"state is {self.state}"}}
        if self.cancel_token.cancelled():
            return {"ok": False, "error": {"code": "CANCELLED", "message": "task was cancelled"}}
        if self.candidate:
            self.candidate.approved_by = actor
        return self.prepare_promotion()

    def reject(self, reason: str = "") -> dict:
        if self.candidate:
            self.candidate.discard()
        self._set_state("DISCARDED")
        self.emit("candidate.rejected", {"reason": reason})
        self.emit("candidate.discarded", {"reason": reason})
        return {"ok": True, "task_id": self.task_id, "state": "DISCARDED"}

    def prepare_promotion(self) -> dict:
        if self.cancel_token.cancelled():
            return {"ok": False, "error": {"code": "CANCELLED", "message": "cancelled"}, "state": "CANCELLED"}
        if not self.candidate or not self.candidate.workspace.exists():
            return {"ok": False, "error": {"code": "NO_CANDIDATE", "message": "no candidate workspace"}}
        if self.candidate.state not in {
            CandidateState.VERIFIED,
            CandidateState.WAITING_FOR_APPROVAL,
            CandidateState.READY_FOR_PROMOTION,
        }:
            return {"ok": False, "error": {"code": "NOT_VERIFIED", "message": self.candidate.state.value}}
        if not self.candidate.origin_matches_baseline():
            self.candidate.state = CandidateState.PROMOTION_REJECTED
            self._set_state("PROMOTION_REJECTED")
            return {
                "ok": False,
                "error": {"code": "STALE_ORIGIN", "message": "origin changed after baseline; refusing to overwrite"},
                "state": "PROMOTION_REJECTED",
            }
        if self.candidate.approved_by != "human":
            return {"ok": False, "error": {"code": "NO_APPROVAL", "message": "human approval required"}}
        sb = Sandbox(self.isolated, allow={"READ", "WRITE", "EXECUTE"})
        try:
            ok, out = sb.run_pytest(cancel=self.cancel_token)
        except Cancelled:
            return {"ok": False, "error": {"code": "CANCELLED", "message": "cancelled"}, "state": "CANCELLED"}
        self.ctx["tests"] = out
        self.ctx["tests_ok"] = ok
        if not ok:
            return {"ok": False, "error": {"code": "TESTS_FAILED", "message": "candidate tests no longer pass"}, "state": self.state}
        findings = []
        for p in self.isolated.rglob("*.py"):
            findings.extend(audit_text(p.read_text(encoding="utf-8"), source=str(p)))
        self.findings = [f.__dict__ for f in findings]
        blocking = [f for f in findings if f.rule in {"secret_exposure", "unsafe_exec"}]
        if blocking:
            return {"ok": False, "error": {"code": "SECURITY_FAILED", "message": "security checks failed"}}
        self.ctx["diff"] = self.candidate.diff()
        self.candidate.state = CandidateState.READY_FOR_PROMOTION
        self._set_state("READY_FOR_PROMOTION")
        self.emit("approval.granted", {"actor": self.candidate.approved_by})
        return {"ok": True, "task_id": self.task_id, "state": "READY_FOR_PROMOTION"}

    def _cancelled_result(self) -> dict:
        if self.candidate and self.candidate.workspace.exists() and not self.candidate.discarded:
            self.candidate.state = CandidateState.CANCELLED
            self.candidate.discard()
        self._set_state("CANCELLED")
        self.emit("task.completed", {"state": "CANCELLED"})
        return self._result(ok=False, error="cancelled")

    def _tests_obj(self) -> dict:
        raw = str(self.ctx.get("tests") or "")
        passed = bool(self.ctx.get("tests_ok"))
        m = re.search(r"\d+ passed", raw)
        summary = m.group(0) if m else (raw.strip()[-240:] if raw.strip() else "")
        return {"passed": passed, "summary": summary}

    def http_result(self) -> dict:
        ok = self.state in SUCCESS_STATES
        body = self._result(ok=ok)
        task = {
            "id": self.task_id,
            "state": self.state,
            "repository": str(self.repo),
            "provider": self.metrics.provider or "mock-coder",
            "changed_files": body.get("changed") or [],
            "tests": self._tests_obj(),
            "security": body.get("security") or {"passed": False, "findings": []},
            "candidate": body.get("candidate"),
            "diff": body.get("diff") or "",
        }
        body["task"] = task
        body["changed_files"] = task["changed_files"]
        return body

    def _result(self, ok: bool, error: str | None = None, ctx: dict | None = None, extra: dict | None = None) -> dict:
        ctx = ctx or self.ctx or {}
        cand = self.candidate
        origin_modified = bool(cand and not cand.origin_matches_baseline()) if cand else False
        body = {
            "ok": ok,
            "state": self.state,
            "task_id": self.task_id,
            "trace_id": self.task_id,
            "repository": self.target.to_dict(),
            "provider": self.metrics.provider or ctx.get("provider"),
            "agent": "debugger",
            "diff": ctx.get("diff", "") if cand and not cand.discarded else (ctx.get("diff") or ""),
            "tests": ctx.get("tests", ""),
            "failures": ctx.get("failures"),
            "metrics": self.metrics.summary(),
            "replay": list(self.kernel.recorder.dry_run(self.task_id)),
            "events": list(self.events),
            "changed": cand.changed_files() if cand and not cand.discarded else [],
            "candidate": {
                "state": cand.state.value if cand else "NONE",
                "original_modified": origin_modified,
                "workspace": str(self.isolated) if cand and not cand.discarded else None,
                "baseline_hash": cand.origin_hash if cand else "",
            },
            "security": {
                "passed": bool(ok and not error and not any(f.get("rule") in {"secret_exposure", "unsafe_exec"} for f in self.findings)),
                "findings": self.findings,
            },
        }
        if cand and not cand.discarded and not body["diff"]:
            body["diff"] = cand.diff()
        if error:
            body["error"] = error
        if extra:
            body.update(extra)
        if "intent" not in body:
            body["intent"] = ctx.get("intent")
        tasks = []
        try:
            tasks = [{"id": t.id, "kind": t.kind, "state": t.state.value, "out": t.outputs} for t in self.kernel.all_tasks()]
        except Exception:
            pass
        body["tasks"] = tasks
        return body

    def _coding_provider(self):
        p = self.router.choose("coding")
        if p.info.id == "stub" or not getattr(p.info.capabilities, "tool_calling", False):
            return MockCoderProvider()
        return p

    def _handle(self, t: Task, ctx: dict, provider) -> dict:
        self.cancel_token.raise_if_cancelled()
        self.ctx = ctx
        kind = t.kind
        root = self.isolated
        if kind == "inspect_repo":
            g = index_repo(root)
            ctx["graph"] = g
            self.emit("tool.called", {"tool": "inspect_repository"})
            return {"files": list(g.files)[:40], "symbols": len(g.symbols)}
        if kind == "search_code":
            g = ctx.get("graph") or index_repo(root)
            self.emit("tool.called", {"tool": "search_code"})
            return {"files": list(g.files)[:40], "symbols": [s.__dict__ for s in g.symbols[:30]]}
        if kind == "analyze_deps":
            g = ctx.get("graph") or index_repo(root)
            self.emit("tool.called", {"tool": "analyze_deps"})
            return {"imports": g.imports, "tests": g.tests}
        if kind in {"propose_patch", "apply_patch", "self_heal"}:
            return self._agent(ctx, provider, t.goal)
        if kind in {"run_tests"}:
            sb = Sandbox(root, allow={"READ", "WRITE", "EXECUTE"})
            ok, out = sb.run_pytest(cancel=self.cancel_token)
            parsed = parse_pytest(out)
            ctx["tests"] = out
            ctx["tests_ok"] = ok
            ctx["failures"] = parsed
            if ok:
                self.metrics.tests_ok += 1
            else:
                self.metrics.tests_fail += 1
            if self.candidate:
                ctx["diff"] = self.candidate.diff()
            self.emit("tests.finished", {"passed": ok})
            if not ok:
                self.emit("retry.started", {"attempt": ctx.get("heal_used", 0) + 1})
            return {"ok": True, "tests_passed": ok, "output": out, "failures": parsed}
        if kind == "verify":
            if self.candidate:
                self.candidate.state = CandidateState.VERIFYING
            self._set_state("VERIFYING")
            findings = []
            for p in root.rglob("*.py"):
                findings.extend(audit_text(p.read_text(encoding="utf-8"), source=str(p)))
            self.findings = [f.__dict__ for f in findings]
            blocking = [f for f in findings if f.rule in {"secret_exposure", "unsafe_exec"}]
            ok = bool(ctx.get("tests_ok")) and not blocking
            ctx["verify_ok"] = ok
            if self.candidate:
                ctx["diff"] = self.candidate.diff()
            self.emit("verification.finished", {"passed": ok})
            return {"ok": ok, "verify": True, "findings": self.findings}
        if kind == "report":
            return {"diff": ctx.get("diff", ""), "ok": ctx.get("verify_ok", False)}
        return {"ok": True}

    def _agent(self, ctx: dict, provider, goal: str) -> dict:
        self.cancel_token.raise_if_cancelled()
        if self._agent_ran and ctx.get("tests_ok"):
            return {"skipped": True, "reason": "already_verified"}
        if ctx.get("heal_used", 0) >= self.max_heal and self._agent_ran:
            return {"failed": True, "error": "heal iteration limit"}
        ctx["heal_used"] = ctx.get("heal_used", 0) + 1
        self.attempt = ctx["heal_used"]
        self._agent_ran = True
        sb = Sandbox(self.isolated, allow={"READ", "WRITE", "EXECUTE"})
        tools = build_tools(self.isolated, sb)
        loop = AgentLoop(
            provider=provider,
            tools=tools,
            recorder=self.kernel.recorder,
            trace_id=ctx["trace"],
            role="debugger",
            memory=self.memory,
            max_iters=self.max_iterations,
        )
        loop.cancel = self.cancel_token
        self.emit("agent.iteration", {"iteration": ctx["heal_used"], "provider": provider.info.id})
        result = loop.run(goal or ctx["intent"]["goal"])
        if result.get("cancelled") or self.cancel_token.cancelled():
            raise Cancelled("agent cancelled")
        self.metrics.model_calls += result.get("iterations") or 0
        self.metrics.tool_calls += len(result.get("observations") or [])
        self.metrics.context_chars = loop.ctx.size()
        if "graph" in ctx:
            ctx["graph"] = incremental(ctx["graph"])
        ok, out = sb.run_pytest(cancel=self.cancel_token)
        ctx["tests_ok"] = ok
        ctx["tests"] = out
        ctx["failures"] = parse_pytest(out)
        if self.candidate:
            ctx["diff"] = self.candidate.diff()
        ctx["agent"] = {"iterations": result.get("iterations"), "ok": result.get("ok")}
        self.emit("tests.finished", {"passed": ok})
        return {"agent": True, "tests_passed": ok, "ok": True, "iterations": result.get("iterations")}
