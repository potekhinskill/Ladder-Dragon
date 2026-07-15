from decimal import Decimal

from exchange_math import normalized_order_values, round_step


def test_step_rounding_has_no_binary_float_drift():
    assert round_step("0.3", "0.1", "floor") == Decimal("0.3")
    assert round_step("100.001", "0.01", "floor") == Decimal("100.00")
    assert round_step("100.001", "0.01", "ceil") == Decimal("100.01")


def test_min_notional_rounds_quantity_up_exactly():
    qty, price = normalized_order_values(
        "0.01",
        "99.999",
        step="0.001",
        tick="0.01",
        min_qty="0.001",
        min_notional="5",
        side="BUY",
    )
    assert price == "99.99"
    assert Decimal(qty) * Decimal(price) >= Decimal("5")
