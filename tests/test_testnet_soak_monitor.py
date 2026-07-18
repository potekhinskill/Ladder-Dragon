from decimal import Decimal

from bin.testnet_soak_monitor import SoakSample, evaluate_sample


def sample(**overrides) -> SoakSample:
    values = dict(
        ts=1.0,
        account_qty=Decimal("0.129"),
        ledger_qty=Decimal("0.129"),
        market_price=Decimal("77"),
        holdings_exposure=Decimal("9.933"),
        total_exposure=Decimal("9.933"),
        open_buy_count=0,
        open_sell_count=2,
        protected_sell_legs=2,
        halted=False,
    )
    values.update(overrides)
    return SoakSample(**values)


def evaluate(value: SoakSample):
    return evaluate_sample(
        value,
        max_open_buys=1,
        max_exposure=Decimal("25"),
        min_notional=Decimal("5"),
        quantity_tolerance=Decimal("0.001"),
    )


def test_protected_consistent_position_passes():
    assert evaluate(sample()) == ([], False, False)


def test_exposure_buy_count_and_halt_are_immediate_violations():
    violations, unprotected, mismatch = evaluate(
        sample(total_exposure=Decimal("30"), open_buy_count=2, halted=True)
    )
    assert len(violations) == 3
    assert unprotected is False
    assert mismatch is False


def test_unprotected_and_inventory_mismatch_use_grace_path():
    violations, unprotected, mismatch = evaluate(
        sample(
            ledger_qty=Decimal("0.100"),
            open_sell_count=0,
            protected_sell_legs=0,
        )
    )
    assert violations == []
    assert unprotected is True
    assert mismatch is True


def test_nontradable_dust_does_not_require_oco():
    violations, unprotected, mismatch = evaluate(
        sample(
            account_qty=Decimal("0.001"),
            ledger_qty=Decimal("0.001"),
            holdings_exposure=Decimal("0.077"),
            total_exposure=Decimal("0.077"),
            open_sell_count=0,
            protected_sell_legs=0,
        )
    )
    assert violations == []
    assert unprotected is False
    assert mismatch is False
