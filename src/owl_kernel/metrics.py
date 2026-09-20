from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter


@dataclass
class Metrics:
    task_latency_s: list[float] = field(default_factory=list)
    model_calls: int = 0
    tool_calls: int = 0
    retries: int = 0
    failures: int = 0
    tests_ok: int = 0
    tests_fail: int = 0
    provider: str = ""
    context_chars: int = 0

    def mark_task(self, started: float) -> None:
        self.task_latency_s.append(perf_counter() - started)

    def summary(self) -> dict:
        return {
            "tasks": len(self.task_latency_s),
            "task_latency_s": round(sum(self.task_latency_s), 3),
            "model_calls": self.model_calls,
            "tool_calls": self.tool_calls,
            "retries": self.retries,
            "failures": self.failures,
            "tests_ok": self.tests_ok,
            "tests_fail": self.tests_fail,
            "provider": self.provider,
            "context_chars": self.context_chars,
        }
