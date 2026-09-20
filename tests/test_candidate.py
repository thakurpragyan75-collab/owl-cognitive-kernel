from owl_kernel.candidate import Candidate


def test_origin_never_mutated_and_discard(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    (origin / "a.py").write_text("x=1\n")
    work = tmp_path / "iso"
    c = Candidate(origin, work).snapshot()
    (work / "a.py").write_text("x=2\n")
    assert c.changed_files() == ["a.py"]
    assert "x=2" in c.diff()
    c.discard()
    assert (origin / "a.py").read_text() == "x=1\n"
    assert not work.exists()
