def in_stock(on_hand: int, requested: int) -> bool:
    """True when the shelf can fill the order, including an exact match."""
    return on_hand > requested
