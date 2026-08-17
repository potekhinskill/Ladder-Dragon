from decimal import Decimal

from ladder_dragon.risk.risk_manager import RiskLimits, RiskManager, RiskSnapshot
from ladder_dragon.risk.inventory_caps import (
    clamp_symbol_order_caps,
    open_buy_notional,
    remaining_inventory_budget,
)


D = Decimal


def _limits(tmp_path, cap=None):
    caps = {} if cap is None else {"SOLUSDT": D(cap)}
    return RiskLimits(
        max_daily_loss_usdt=D("100"),
        max_start_drawdown_pct=D("0.1"),
        max_peak_drawdown_pct=D("0.1"),
        portfolio_cap_usdt=D("1000"),
        daily_turnover_cap_usdt=D("1000"),
        daily_trade_count_cap=100,
        daily_buy_cap_usdt=D("1000"),
        open_order_count_cap=100,
        correlated_cap_usdt=D("1000"),
        reserve_usdt=D("0"),
        max_consecutive_losses=10,
        cooldown_sec=0,
        halt_file=tmp_path / "halt.json",
        state_file=tmp_path / "state.json",
        alerts_file=tmp_path / "alerts.ndjson",
        managed_inventory_caps_usdt=caps,
    )


def _snapshot(exposure):
    return RiskSnapshot(
        equity_usdt=D("1000"),
        exposure_usdt=D(exposure),
        free_usdt=D("500"),
        symbol_exposure_usdt={"SOLUSDT": D(exposure)},
    )


def test_missing_symbol_inventory_cap_blocks_buys_unconditionally(tmp_path):
    decision = RiskManager(_limits(tmp_path)).evaluate(
        _snapshot("10"), now=1_700_000_000
    )

    assert decision.buy_blocked is True
    assert decision.halted is False
    assert decision.reasons == (
        "managed inventory hard CAP is unavailable: SOLUSDT",
    )


def test_absolute_symbol_inventory_cap_blocks_without_control_mode(tmp_path):
    decision = RiskManager(_limits(tmp_path, "30")).evaluate(
        _snapshot("30"), now=1_700_000_000
    )

    assert decision.buy_blocked is True
    assert decision.reasons == (
        "managed inventory hard CAP reached: SOLUSDT",
    )


def test_symbol_inventory_below_cap_remains_eligible(tmp_path):
    decision = RiskManager(_limits(tmp_path, "30")).evaluate(
        _snapshot("29.99"), now=1_700_000_000
    )

    assert decision.buy_blocked is False


def test_inventory_budget_includes_holdings_and_unfilled_buy_commitments():
    open_notional = open_buy_notional([{
        "side": "BUY",
        "price": "10",
        "origQty": "1",
        "executedQty": "0.4",
    }])

    assert open_notional == D("6.0")
    assert remaining_inventory_budget(
        hard_cap_quote="30",
        held_base_quantity="2",
        market_price="10",
        open_buy_notional_quote=open_notional,
    ) == D("4.0")


def test_batch_cap_reserves_remaining_inventory_across_all_slots():
    caps = clamp_symbol_order_caps(
        ["SOLUSDT"],
        safe_order_cap=D("10"),
        allocations={"SOLUSDT": D("10")},
        exposures={"SOLUSDT": D("29.99")},
        hard_caps={"SOLUSDT": D("30")},
        possible_orders_per_symbol=2,
    )

    assert caps == {"SOLUSDT": D("0.005")}
