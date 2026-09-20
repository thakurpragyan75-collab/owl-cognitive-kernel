"""Parse pytest output into structured failures. No fixture knowledge."""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict


@dataclass
class TestFailure:
    nodeid: str
    message: str
    file: str = ""
    line: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def parse_pytest(output: str) -> dict:
    fails: list[TestFailure] = []
    for m in re.finditer(r"^(FAILED\s+)?([\w./-]+\.py(?:::\w+)*)\s+(?:FAILED)?", output, re.M):
        node = m.group(2)
        fails.append(TestFailure(nodeid=node, message="failed", file=node.split("::")[0]))
    for m in re.finditer(r"([\w./-]+\.py):(\d+): AssertionError(?::\s*(.*))?", output):
        fails.append(
            TestFailure(
                nodeid=m.group(1),
                message=m.group(3) or "AssertionError",
                file=m.group(1),
                line=int(m.group(2)),
            )
        )
    passed = "failed" not in output.lower() and "error" not in output.lower()
    if "passed" in output.lower() and "failed" not in output.lower() and "error" not in output.lower():
        passed = True
    if re.search(r"\d+ failed", output):
        passed = False
    return {
        "passed": passed,
        "failures": [f.to_dict() for f in fails],
        "raw_tail": output[-1500:],
    }
