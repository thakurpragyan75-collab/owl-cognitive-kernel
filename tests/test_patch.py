from pathlib import Path
import pytest
from owl_kernel.patch.engine import PatchError, apply_patch, make_replace, sha


def test_rejects_stale_base(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("a=1\n")
    p = make_replace(tmp_path, "a.py", "a=2\n", "bump")
    f.write_text("changed under us\n")
    with pytest.raises(PatchError):
        apply_patch(tmp_path, p)


def test_applies_when_hash_matches(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("a=1\n")
    p = make_replace(tmp_path, "a.py", "a=2\n", "bump")
    apply_patch(tmp_path, p)
    assert f.read_text() == "a=2\n"
