"""Compile → DAG → isolated candidate → model/tool loop → verify. No fixture knowledge."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from .agents.loop import AgentLoop
from .candidate import Candidate
from .codegraph.index import incremental, index_repo
from .failure import parse_pytest
from .ir.compiler import compile_intent
from .kernel.engine import Kernel
from .kernel.task import Task
from .memory.store import Memory
from .metrics import Metrics
from .models.mock_coder import MockCoderProvider
from .models.router import ModelRouter
from .resources import snapshot as resource_snapshot
from .sandbox.exec import Sandbox
from .security.auditor import audit_text, document_is_untrusted
from .tools.builtin import build_tools


class Runtime:
    def __init__(self, work: str | Path, repo: str | Path, *, router: ModelRouter | None = None):
        self.work = Path(work)
        self.work.mkdir(parents=True, exist_ok=True)
        self.repo = Path(repo).resolve()
        self.kernel = Kernel(self.work / "kernel.db")
        self.router = router or ModelRouter()
        self.isolated = self.work / "isolated"
        self.memory = Memory(self.work / "memory.db")
        self.metrics = Metrics()
        self.max_heal = 3
        self.candidate: Candidate | None = None
        self._agent_ran = False

    def execute(self, source: str) -> dict:
        if document_is_untrusted(source):
            return {"ok": False, "error": "prompt injection in source"}
        host = resource_snapshot()
        intent = compile_intent(source)
        trace = str(uuid4())
        self.kernel.submit_intent(intent, trace_id=trace)
        self.candidate = Candidate(self.repo, self.isolated).snapshot()
        provider = self._coding_provider()
        self.metrics.provider = provider.info.id
        ctx: dict = {
            "heal_used": 0,
            "trace": trace,
            "intent": intent.to_dict(),
            "provider": provider.info.id,
            "host": host,
        }

        def handler(t: Task) -> dict:
            return self._handle(t, ctx, provider)

        self.kernel.run_to_idle(handler)
        tasks = self.kernel.all_tasks()
        report = next((t for t in tasks if t.kind == "report"), None)
        ok = bool(report and report.state.value == "COMPLETED" and ctx.get("verify_ok"))
        if not ok and self.candidate:
            self.candidate.discard()
        elif self.candidate:
            self.candidate.accept_isolated()
        return {
            "ok": ok,
            "trace_id": trace,
            "intent": intent.to_dict(),
            "tasks": [{"id": t.id, "kind": t.kind, "state": t.state.value, "out": t.outputs} for t in tasks],
            "diff": ctx.get("diff", ""),
            "tests": ctx.get("tests", ""),
            "failures": ctx.get("failures"),
            "provider": ctx["provider"],
            "metrics": self.metrics.summary(),
            "replay": list(self.kernel.recorder.dry_run(trace)),
            "changed": self.candidate.changed_files() if self.candidate and not self.candidate.discarded else [],
        }

    def _coding_provider(self):
        p = self.router.choose("coding")
        if p.info.id == "stub" or not getattr(p.info.capabilities, "tool_calling", False):
            return MockCoderProvider()
        return p

    def _handle(self, t: Task, ctx: dict, provider) -> dict:
        kind = t.kind
        root = self.isolated
        if kind == "inspect_repo":
            g = index_repo(root)
            ctx["graph"] = g
            return {"files": list(g.files)[:40], "symbols": len(g.symbols)}
        if kind == "search_code":
            g = ctx.get("graph") or index_repo(root)
            return {"files": list(g.files)[:40], "symbols": [s.__dict__ for s in g.symbols[:30]]}
        if kind == "analyze_deps":
            g = ctx.get("graph") or index_repo(root)
            return {"imports": g.imports, "tests": g.tests}
        if kind in {"propose_patch", "apply_patch", "self_heal"}:
            return self._agent(ctx, provider, t.goal)
        if kind in {"run_tests"}:
            sb = Sandbox(root, allow={"READ", "WRITE", "EXECUTE"})
            ok, out = sb.run_pytest()
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
            return {"ok": True, "tests_passed": ok, "output": out, "failures": parsed}
        if kind == "verify":
            findings = []
            for p in root.rglob("*.py"):
                findings.extend(audit_text(p.read_text(encoding="utf-8"), source=str(p)))
            # Untrusted content (comments/docs saying "bypass sandbox") is recorded,
            # never treated as authority, and does not fail a clean candidate.
            blocking = [f for f in findings if f.rule in {"secret_exposure", "unsafe_exec"}]
            ok = bool(ctx.get("tests_ok")) and not blocking
            ctx["verify_ok"] = ok
            if self.candidate:
                ctx["diff"] = self.candidate.diff()
            return {"ok": ok, "verify": True, "findings": [f.__dict__ for f in findings]}
        if kind == "report":
            return {"diff": ctx.get("diff", ""), "ok": ctx.get("verify_ok", False)}
        return {"ok": True}

    def _agent(self, ctx: dict, provider, goal: str) -> dict:
        if self._agent_ran and ctx.get("tests_ok"):
            return {"skipped": True, "reason": "already_verified"}
        if ctx.get("heal_used", 0) >= self.max_heal and self._agent_ran:
            return {"failed": True, "error": "heal iteration limit"}
        ctx["heal_used"] = ctx.get("heal_used", 0) + 1
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
        )
        result = loop.run(goal or ctx["intent"]["goal"])
        self.metrics.model_calls += result.get("iterations") or 0
        self.metrics.tool_calls += len(result.get("observations") or [])
        self.metrics.context_chars = loop.ctx.size()
        if "graph" in ctx:
            ctx["graph"] = incremental(ctx["graph"])
        ok, out = sb.run_pytest()
        ctx["tests_ok"] = ok
        ctx["tests"] = out
        ctx["failures"] = parse_pytest(out)
        if self.candidate:
            ctx["diff"] = self.candidate.diff()
        ctx["agent"] = {"iterations": result.get("iterations"), "ok": result.get("ok")}
        return {"agent": True, "tests_passed": ok, "ok": True, "iterations": result.get("iterations")}
