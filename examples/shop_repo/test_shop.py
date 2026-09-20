from price import line_total
from stock import in_stock


def test_exact_count_is_in_stock():
    assert in_stock(3, 3) is True


def test_surplus_is_in_stock():
    assert in_stock(4, 3) is True


def test_short_stock():
    assert in_stock(2, 3) is False


def test_discounted_line():
    assert line_total(100, 2, 10) == 180


def test_no_discount():
    assert line_total(50, 3, 0) == 150
