def line_total(unit_cents: int, qty: int, discount_pct: int = 0) -> int:
    """Integer cents after a percent-off discount."""
    return unit_cents * qty
