from owl_kernel.models.synth import extract_oracles, repair_source


def test_oracle_repairs_binop_from_tests():
    src = "def mix(x, y):\n    return x - y\n"
    tests = "def test_mix():\n    assert mix(2, 3) == 5\n"
    oracles = extract_oracles(tests)
    out = repair_source(src, oracles)
    assert out is not None
    assert "x + y" in out or "x+y" in out.replace(" ", "")


def test_oracle_repairs_comparison_with_docstring():
    src = 'def fits(have, need):\n    """doc"""\n    return have > need\n'
    tests = "def test_eq():\n    assert fits(3, 3) is True\ndef test_no():\n    assert fits(2, 3) is False\n"
    out = repair_source(src, extract_oracles(tests))
    assert out is not None
    assert ">=" in out


def test_oracle_uses_unused_percent_param():
    src = 'def pay(price, qty, off=0):\n    """cents"""\n    return price * qty\n'
    tests = "def test_off():\n    assert pay(100, 2, 10) == 180\ndef test_none():\n    assert pay(50, 3, 0) == 150\n"
    out = repair_source(src, extract_oracles(tests))
    assert out is not None
    ns = {}
    exec(out, ns)
    assert ns["pay"](100, 2, 10) == 180
