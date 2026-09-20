from pathlib import Path
from owl_kernel.runtime import Runtime

FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "fixture_repo"


def test_demo_finds_bug_heals_and_passes(tmp_path):
    src = "Find the bug, determine the root cause, create a fix, run the relevant tests, and only apply the fix if the tests pass."
    rt = Runtime(tmp_path / "work", FIXTURE)
    result = rt.execute(src)
    assert result["ok"] is True
    assert "return a + b" in result["diff"]
    assert result["provider"] == "stub"
    assert result["replay"]
    # original fixture still broken — kernel used an isolated copy
    assert "return a - b" in (FIXTURE / "mathutil.py").read_text()
