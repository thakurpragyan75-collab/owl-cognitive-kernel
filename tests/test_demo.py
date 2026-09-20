from pathlib import Path
from owl_kernel.runtime import Runtime

ROOT = Path(__file__).resolve().parents[1]
SHOP = ROOT / "examples" / "shop_repo"
MATH = ROOT / "examples" / "fixture_repo"
RUNTIME = (ROOT / "src" / "owl_kernel" / "runtime.py").read_text()


def test_runtime_has_no_fixture_cheat():
    assert "return a - b" not in RUNTIME
    assert "def add(" not in RUNTIME
    assert "in_stock" not in RUNTIME
    assert "line_total" not in RUNTIME


def test_shop_multi_file_repair(tmp_path):
    src = (
        "Inspect this repository, find the cause of the failing behavior, "
        "repair it, run the relevant tests, perform security verification, "
        "and produce a final report. Only apply if the tests pass."
    )
    rt = Runtime(tmp_path / "work", SHOP)
    result = rt.execute(src)
    assert result["ok"] is True, result.get("tests") or result
    assert result["provider"] == "mock-coder"
    assert result["replay"]
    assert "return on_hand > requested" in (SHOP / "stock.py").read_text()
    assert "return unit_cents * qty" in (SHOP / "price.py").read_text()
    isolated = tmp_path / "work" / "isolated"
    ns: dict = {}
    exec((isolated / "stock.py").read_text(), ns)
    exec((isolated / "price.py").read_text(), ns)
    assert ns["in_stock"](3, 3) is True
    assert ns["line_total"](100, 2, 10) == 180


def test_mathutil_still_heals_via_oracle_not_cheat(tmp_path):
    rt = Runtime(tmp_path / "work", MATH)
    result = rt.execute("Find the bug, fix it, run tests, only apply if tests pass.")
    assert result["ok"] is True, result.get("tests")
    assert "return a - b" in (MATH / "mathutil.py").read_text()
    isolated = tmp_path / "work" / "isolated"
    ns: dict = {}
    exec((isolated / "mathutil.py").read_text(), ns)
    assert ns["add"](2, 3) == 5
