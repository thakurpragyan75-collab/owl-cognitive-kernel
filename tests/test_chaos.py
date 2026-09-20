from pathlib import Path
import pytest
from owl_kernel.models.openai_compat import OpenAICompatProvider
from owl_kernel.models.base import Capabilities
from owl_kernel.patch.engine import Patch, apply_patch, PatchError
from owl_kernel.sandbox.exec import Sandbox, SandboxError


def test_unavailable_model():
    p = OpenAICompatProvider(
        provider_id="qwen3-coder",
        name="x",
        base_url="http://127.0.0.1:1",
        model="x",
        cap=Capabilities(),
        weight_gb=61,
        min_ram_gb=24,
        notes="",
    )
    h = p.health()
    assert h["available"] is False


def test_invalid_patch_outside(tmp_path):
    with pytest.raises(PatchError):
        apply_patch(tmp_path, Patch(target="/tmp/evil.py", expected_hash="", content="x", reason="no"))


def test_tool_timeout_python(tmp_path):
    sb = Sandbox(tmp_path, allow={"READ", "WRITE", "EXECUTE"})
    with pytest.raises(Exception):
        sb.run_python("while True:\n    pass\n", timeout=1)
