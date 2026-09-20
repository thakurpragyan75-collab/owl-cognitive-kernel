"""Deterministic coding model used when no giant provider is healthy.

It only sees the prompt + tagged observations the kernel already collected.
It never imports the fixture. First patch is intentionally insufficient so
the kernel's retry/test loop is exercised. Second patch uses the local
test-oracle synthesizer on file bodies present in observations.
"""

from __future__ import annotations

import json
import re

from .base import Capabilities, ModelInfo
from .synth import extract_oracles, repair_source


def _act(typ: str, **args) -> str:
    return json.dumps({"type": typ, "arguments": args, "rationale": typ, "confidence": 0.7})


class MockCoderProvider:
    def __init__(self):
        self.info = ModelInfo(
            id="mock-coder",
            name="Local test-oracle coding model",
            available=True,
            capabilities=Capabilities(
                reasoning=True, coding=True, fast_response=True, tool_calling=True, local=True
            ),
            notes="Not a neural net. Synthesizes single-return functions from tests. Default on 8GB.",
        )
        self._step = 0
        self._files: dict[str, str] = {}
        self._tests: dict[str, str] = {}
        self._listed: list[str] = []
        self._weak_patch = False
        self._tested = False
        self._fixed = False
        self._retested = False

    def health(self) -> dict:
        self.info.available = True
        return {"id": self.info.id, "available": True, "loaded": True}

    def complete(self, prompt: str, *, max_tokens: int = 256) -> str:
        self._ingest(prompt)
        self._step += 1
        if not self._listed:
            return _act("inspect_repository")
        if not self._tests and not self._files:
            tests = [p for p in self._listed if "test" in p and p.endswith(".py")]
            if tests and self._step <= 4:
                return _act("read_file", path=tests[0])
            impl = [p for p in self._listed if p.endswith(".py") and "test" not in p]
            if impl:
                unread = [p for p in impl if p not in self._files]
                if unread:
                    return _act("read_file", path=unread[0])
            return _act("inspect_tests")
        # read remaining implementation files
        impl = [p for p in self._listed if p.endswith(".py") and "test" not in p and p not in self._files]
        if impl:
            return _act("read_file", path=impl[0])
        unread_tests = [p for p in self._listed if "test" in p and p.endswith(".py") and p not in self._tests]
        if unread_tests:
            return _act("read_file", path=unread_tests[0])
        if not self._weak_patch and self._files:
            self._weak_patch = True
            path, body = next(iter(self._files.items()))
            return _act(
                "apply_patch",
                file=path,
                new_content=body.rstrip() + "\n# candidate-1\n",
                reason="first candidate (intentionally incomplete)",
            )
        if not self._tested:
            self._tested = True
            return _act("run_tests")
        if not self._fixed:
            self._fixed = True
            oracles: list[dict] = []
            for body in self._tests.values():
                oracles.extend(extract_oracles(body))
            # also oracles from any test-looking file we stored as impl by mistake
            for path, body in list(self._files.items()) + list(self._tests.items()):
                if "test" in path:
                    oracles.extend(extract_oracles(body))
            patched_any = False
            for path, body in list(self._files.items()):
                clean = body.replace("# candidate-1\n", "")
                repaired = repair_source(clean, oracles)
                if repaired and repaired != clean:
                    self._files[path] = repaired
                    patched_any = True
                    return _act("apply_patch", file=path, new_content=repaired, reason="oracle synthesis from tests")
            if not patched_any:
                return _act("run_tests")
        if not self._retested:
            self._retested = True
            return _act("run_tests")
        # more files may still be broken
        oracles = []
        for body in list(self._tests.values()):
            oracles.extend(extract_oracles(body))
        for path, body in list(self._files.items()):
            repaired = repair_source(body.replace("# candidate-1\n", ""), oracles)
            if repaired and repaired.strip() != body.replace("# candidate-1\n", "").strip():
                self._files[path] = repaired
                self._retested = False
                return _act("apply_patch", file=path, new_content=repaired, reason="second file")
        return _act("finish", summary="verified")

    def _ingest(self, prompt: str) -> None:
        for m in re.finditer(r"<obs tool='([^']+)'>([\s\S]*?)</obs>", prompt):
            tool, raw = m.group(1), m.group(2)
            self._eat(tool, raw)
        # also json blobs
        if '"files":' in prompt and not self._listed:
            files = re.findall(r'"([^"\s]+\.py)"', prompt)
            self._listed = list(dict.fromkeys(files))

    def _eat(self, tool: str, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = None
        if tool == "inspect_repository" and isinstance(data, dict):
            files = data.get("files") or []
            self._listed = [f for f in files if isinstance(f, str)]
        if tool == "read_file" and isinstance(data, dict):
            path = data.get("path") or ""
            body = data.get("body") or ""
            if path and body:
                if "test" in path:
                    self._tests[path] = body
                else:
                    self._files[path] = body
        if tool == "inspect_tests" and isinstance(data, dict):
            for t in data.get("tests") or []:
                if t not in self._listed:
                    self._listed.append(t)
        if tool == "run_tests" and isinstance(data, dict):
            self._tested = True
