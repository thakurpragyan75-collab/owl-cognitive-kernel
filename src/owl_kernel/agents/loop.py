"""Bounded model → tool → observation loop. Kernel remains the authority."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..context import Context
from ..parse import ParseError, extract_json
from ..tools.spec import ToolError, ToolSpec
from .roles import ROLES, role_allows


DANGEROUS = frozenset({"SECRETS", "NETWORK"})
FINISH = "finish"


class AgentLoop:
    def __init__(
        self,
        *,
        provider,
        tools: dict[str, ToolSpec],
        recorder,
        trace_id: str,
        role: str = "debugger",
        max_iters: int = 24,
        memory=None,
    ):
        self.provider = provider
        self.tools = tools
        self.recorder = recorder
        self.trace_id = trace_id
        self.role = role
        self.max_iters = max_iters
        self.memory = memory
        self.observations: list[dict[str, Any]] = []
        self.ctx = Context()
        self.rejected: list[str] = []
        self.cancel = None

    def run(self, goal: str) -> dict[str, Any]:
        role = ROLES.get(self.role) or ROLES["debugger"]
        for i in range(self.max_iters):
            if self.cancel is not None and self.cancel.cancelled():
                return {"ok": False, "cancelled": True, "error": "cancelled", "iterations": i, "observations": self.observations}
            prompt = self._prompt(goal, role.name)
            raw = self.provider.complete(prompt, max_tokens=512)
            self.recorder.record(self.trace_id, "model.complete", {"i": i, "provider": self.provider.info.id, "bytes": len(raw)})
            try:
                action = extract_json(raw)
            except ParseError as e:
                self.rejected.append(str(e))
                self.observations.append({"tool": None, "error": f"malformed: {e}", "raw": raw[:300]})
                continue
            typ = str(action.get("type") or "")
            args = action.get("arguments") if isinstance(action.get("arguments"), dict) else {}
            if typ == FINISH:
                self.recorder.record(self.trace_id, "agent.finish", {"i": i})
                return {"ok": True, "iterations": i + 1, "observations": self.observations, "finish": args}
            spec = self.tools.get(typ)
            if spec is None:
                self.rejected.append(f"unknown tool {typ}")
                self.observations.append({"tool": typ, "error": "unknown_tool"})
                continue
            missing = [k for k in spec.required_args if k not in args or args[k] in (None, "")]
            if missing:
                self.observations.append({"tool": typ, "error": f"missing {missing}"})
                continue
            perm = next(iter(spec.permissions), "")
            if perm in DANGEROUS:
                self.observations.append({"tool": typ, "error": "dangerous_permission_denied"})
                continue
            if not role_allows(role.name, typ, perm):
                self.observations.append({"tool": typ, "error": "role_denied", "role": role.name})
                continue
            if self.cancel is not None and self.cancel.cancelled():
                return {"ok": False, "cancelled": True, "error": "cancelled", "iterations": i, "observations": self.observations}
            try:
                result = spec.run(**args)
            except (ToolError, Exception) as e:
                result = {"error": str(e)}
            obs = {"tool": typ, "result": result}
            self.observations.append(obs)
            self.ctx.add(f"tool:{typ}", json.dumps(result)[:3500], typ)
            if self.memory:
                self.memory.add("task", "observation", f"{typ}:{str(result)[:400]}", "tool")
            arg_hash = hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[:16]
            res_hash = hashlib.sha256(json.dumps(result, sort_keys=True, default=str).encode()).hexdigest()[:16]
            self.recorder.record(
                self.trace_id,
                "tool",
                {"tool": typ, "arg_hash": arg_hash, "result_hash": res_hash, "error": result.get("error") if isinstance(result, dict) else None},
            )
        return {"ok": False, "error": "iteration_limit", "observations": self.observations}

    def _prompt(self, goal: str, role: str) -> str:
        names = sorted(self.tools)
        obs_xml = []
        for o in self.observations[-8:]:
            payload = o.get("result") if "result" in o else o
            obs_xml.append(f"<obs tool='{o.get('tool')}'>{json.dumps(payload)[:4000]}</obs>")
        mem = ""
        if self.memory:
            facts = self.memory.facts("task")
            if facts:
                mem = "FACTS:\n" + "\n".join(facts[:8])
        return (
            f"GOAL: {goal}\nROLE: {role}\n"
            "Reply with a single JSON object {\"type\": tool, \"arguments\": {}, \"rationale\": str}.\n"
            f"TOOLS: {names}\n"
            f"{mem}\n"
            f"CONTEXT:\n{self.ctx.render()}\n"
            + "\n".join(obs_xml)
        )
