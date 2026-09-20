from pathlib import Path
from owl_kernel.codegraph.index import incremental, index_repo


def test_index_and_incremental(tmp_path):
    (tmp_path / "m.py").write_text("import n\ndef foo():\n    return 1\n")
    (tmp_path / "n.py").write_text("def bar():\n    return 2\n")
    (tmp_path / "test_m.py").write_text("def test_foo():\n    assert True\n")
    g = index_repo(tmp_path)
    assert any(s.name == "foo" for s in g.symbols)
    assert g.files_depending_on("n")
    assert g.tests_for("m.py")
    (tmp_path / "m.py").write_text("import n\ndef foo():\n    return 3\ndef extra():\n    return 0\n")
    g2 = incremental(g)
    assert any(s.name == "extra" for s in g2.symbols)
