import json
import threading
import time
from pathlib import Path

from owl_kernel.agents.loop import AgentLoop
from owl_kernel.parse import ParseError, extract_json
from owl_kernel.replay.recorder import Recorder
from owl_kernel.sandbox.exec import Sandbox, SandboxError
from owl_kernel.tools.builtin import build_tools


class Scripted:
    def __init__(self, replies):
        self.replies = list(replies)
        self.info = type("I", (), {"id": "scripted"})()

    def complete(self, prompt, *, max_tokens=256):
        return self.replies.pop(0) if self.replies else json.dumps({"type": "finish", "arguments": {}})


def test_extract_json_fence_and_junk():
    assert extract_json("```json\n{\"type\":\"finish\",\"arguments\":{}}\n```")["type"] == "finish"
    try:
        extract_json("not json at all")
        assert False
    except ParseError:
        pass


def test_unknown_tool_rejected(tmp_path):
    rec = Recorder(tmp_path / "t.jsonl")
    sb = Sandbox(tmp_path, allow={"READ", "WRITE", "EXECUTE"})
    tools = build_tools(tmp_path, sb)
    p = Scripted([json.dumps({"type": "rm_rf", "arguments": {"path": "/"}}), json.dumps({"type": "finish", "arguments": {}})])
    loop = AgentLoop(provider=p, tools=tools, recorder=rec, trace_id="x", role="debugger")
    out = loop.run("do harm")
    assert any(o.get("error") == "unknown_tool" for o in out["observations"])


def test_researcher_cannot_write(tmp_path):
    rec = Recorder(tmp_path / "t.jsonl")
    (tmp_path / "a.py").write_text("x=1\n")
    sb = Sandbox(tmp_path, allow={"READ", "WRITE", "EXECUTE"})
    tools = build_tools(tmp_path, sb)
    p = Scripted(
        [
            json.dumps({"type": "apply_patch", "arguments": {"file": "a.py", "new_content": "x=2\n"}}),
            json.dumps({"type": "finish", "arguments": {}}),
        ]
    )
    loop = AgentLoop(provider=p, tools=tools, recorder=rec, trace_id="x", role="researcher")
    out = loop.run("edit")
    assert any(o.get("error") == "role_denied" for o in out["observations"])
    assert (tmp_path / "a.py").read_text() == "x=1\n"


def test_path_traversal_blocked(tmp_path):
    sb = Sandbox(tmp_path, allow={"READ", "WRITE", "EXECUTE"})
    try:
        sb.read("../etc/passwd")
        assert False
    except SandboxError:
        pass


def test_secrets_and_network_never_in_tools(tmp_path):
    sb = Sandbox(tmp_path, allow={"READ"})
    tools = build_tools(tmp_path, sb)
    for spec in tools.values():
        assert "SECRETS" not in spec.permissions
        assert "NETWORK" not in spec.permissions
