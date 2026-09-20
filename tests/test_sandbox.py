from pathlib import Path
import pytest
from owl_kernel.sandbox.exec import Sandbox, SandboxError


def test_blocks_traversal(tmp_path):
    sb = Sandbox(tmp_path)
    with pytest.raises(SandboxError):
        sb.resolve("../etc/passwd")


def test_blocks_network_and_secrets(tmp_path):
    sb = Sandbox(tmp_path, allow={"READ"})
    with pytest.raises(SandboxError):
        sb.resolve("x", perm="NETWORK")
    with pytest.raises(SandboxError):
        sb.resolve("x", perm="SECRETS")


def test_python_blocks_subprocess(tmp_path):
    sb = Sandbox(tmp_path, allow={"READ", "WRITE", "EXECUTE"})
    with pytest.raises(SandboxError):
        sb.run_python("import subprocess\nsubprocess.call(['true'])")


def test_python_ok(tmp_path):
    sb = Sandbox(tmp_path, allow={"READ", "WRITE", "EXECUTE"})
    out = sb.run_python("print(2+2)")
    assert "4" in out
