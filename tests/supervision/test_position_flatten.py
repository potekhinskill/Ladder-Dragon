"""Position-flatten order acceptance regressions."""

from decimal import Decimal

from ladder_dragon.supervision.position_flatten import (
    BUY_BLOCKING_MODES,
    submit_flatten_slices,
)


def _normalizer(_symbol, quantity, *_args):
    return Decimal(str(quantity))


def test_stalled_flatten_remains_a_buy_blocking_mode():
    assert "flatten_stalled" in BUY_BLOCKING_MODES


def test_flatten_does_not_count_rejected_limit_and_market_orders():
    limit_calls = []
    market_calls = []
    accepted = submit_flatten_slices(
        symbol="SOLUSDT",
        remaining=Decimal("1"),
        per_slice=Decimal("0.5"),
        slice_count=2,
        limit_price=Decimal("100"),
        market_price=Decimal("99"),
        step="0.001",
        minimum_quantity="0.001",
        minimum_notional="5",
        market_failover=True,
        normalize_quantity=_normalizer,
        place_limit=lambda *args, **kwargs: limit_calls.append(args),
        place_market=lambda *args, **kwargs: market_calls.append(args),
    )

    assert accepted == 0
    assert len(limit_calls) == 1
    assert len(market_calls) == 1


def test_flatten_rejects_truthy_response_without_exchange_order_id():
    accepted = submit_flatten_slices(
        symbol="SOLUSDT",
        remaining=Decimal("1"),
        per_slice=Decimal("0.5"),
        slice_count=2,
        limit_price=Decimal("100"),
        market_price=Decimal("99"),
        step="0.001",
        minimum_quantity="0.001",
        minimum_notional="5",
        market_failover=False,
        normalize_quantity=_normalizer,
        place_limit=lambda *_args, **_kwargs: {"status": "NEW"},
        place_market=lambda *_args, **_kwargs: None,
    )

    assert accepted == 0


def test_flatten_counts_only_accepted_slice_submissions():
    accepted = submit_flatten_slices(
        symbol="SOLUSDT",
        remaining=Decimal("1"),
        per_slice=Decimal("0.5"),
        slice_count=2,
        limit_price=Decimal("100"),
        market_price=Decimal("99"),
        step="0.001",
        minimum_quantity="0.001",
        minimum_notional="5",
        market_failover=False,
        normalize_quantity=_normalizer,
        place_limit=lambda *_args, **_kwargs: {"orderId": 1},
        place_market=lambda *_args, **_kwargs: None,
    )

    assert accepted == 2


def test_flatten_counts_accepted_market_failover():
    accepted = submit_flatten_slices(
        symbol="SOLUSDT",
        remaining=Decimal("0.5"),
        per_slice=Decimal("0.5"),
        slice_count=1,
        limit_price=Decimal("100"),
        market_price=Decimal("99"),
        step="0.001",
        minimum_quantity="0.001",
        minimum_notional="5",
        market_failover=True,
        normalize_quantity=_normalizer,
        place_limit=lambda *_args, **_kwargs: None,
        place_market=lambda *_args, **_kwargs: {"orderId": 2},
    )

    assert accepted == 1


def test_flatten_rejects_minimum_repair_above_available_remainder():
    placements = []

    def repaired(_symbol, _quantity, *_args):
        return Decimal("1.1")

    accepted = submit_flatten_slices(
        symbol="SOLUSDT",
        remaining=Decimal("1"),
        per_slice=Decimal("0.5"),
        slice_count=2,
        limit_price=Decimal("100"),
        market_price=Decimal("99"),
        step="0.001",
        minimum_quantity="0.001",
        minimum_notional="5",
        market_failover=True,
        normalize_quantity=repaired,
        place_limit=lambda *args, **kwargs: placements.append(args),
        place_market=lambda *args, **kwargs: placements.append(args),
    )

    assert accepted == 0
    assert placements == []
