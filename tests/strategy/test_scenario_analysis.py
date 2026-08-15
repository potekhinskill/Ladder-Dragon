from decimal import Decimal

import pytest

from ladder_dragon.strategy.scenario_analysis import (
    ScenarioBar,
    analyze_scenarios,
    realized_shadow_returns,
)


D = Decimal


def _bars(count: int = 60, *, start: Decimal = D("100")) -> list[ScenarioBar]:
    output = []
    for index in range(count):
        close = start + D(index)
        output.append(ScenarioBar(
            open_time_ms=index * 3_600_000,
            close_time_ms=(index + 1) * 3_600_000 - 1,
            open=close - D("0.5"),
            high=close + D("1"),
            low=close - D("1"),
            close=close,
            volume=D("10"),
        ))
    return output


def test_analysis_uses_formal_rules_and_cannot_apply_orders():
    analysis = analyze_scenarios(
        "SOLUSDT", "1h", _bars(), now_ms=61 * 3_600_000
    )
    assert analysis.primary_scenario == "BULLISH"
    assert analysis.shadow_action == "LONG"
    assert analysis.mode == "SHADOW"
    assert analysis.apply_allowed is False
    assert analysis.can_change_orders is False
    assert analysis.bullish_weight > analysis.bearish_weight
    assert analysis.range_low < analysis.fibonacci_618 < analysis.fibonacci_500
    assert analysis.fibonacci_500 < analysis.fibonacci_382 < analysis.range_high


def test_analysis_rejects_an_open_candle_and_unsupported_interval():
    bars = _bars()
    with pytest.raises(ValueError, match="open candles are forbidden"):
        analyze_scenarios("SOLUSDT", "1h", bars, now_ms=bars[-1].close_time_ms)
    with pytest.raises(ValueError, match="unsupported"):
        analyze_scenarios("SOLUSDT", "15m", bars, now_ms=61 * 3_600_000)


def test_shadow_returns_include_costs_and_never_invent_short_profit():
    candidate, baseline, edge = realized_shadow_returns(
        action="LONG",
        entry_price=D("100"),
        exit_price=D("101"),
        round_trip_cost_pct=D("0.0025"),
    )
    assert candidate == D("0.0075")
    assert baseline == candidate
    assert edge == 0
    cash, baseline_down, cash_edge = realized_shadow_returns(
        action="CASH",
        entry_price=D("100"),
        exit_price=D("90"),
        round_trip_cost_pct=D("0.0025"),
    )
    assert cash == 0
    assert baseline_down == D("-0.1025")
    assert cash_edge == D("0.1025")
