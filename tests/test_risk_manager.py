from decimal import Decimal
from pathlib import Path
import json
import sqlite3

import pytest

from ladder_dragon.risk.risk_manager import (
    RiskLimits,
    RiskManager,
    RiskSnapshot,
    create_manual_halt,
    load_daily_trade_metrics,
    sync_manual_halt_state,
)


def limits(tmp_path: Path, **overrides) -> RiskLimits:
    values = dict(
        max_daily_loss_usdt=Decimal("100"),
        max_start_drawdown_pct=Decimal("0.05"),
        max_peak_drawdown_pct=Decimal("0.03"),
        portfolio_cap_usdt=Decimal("1000"),
        daily_turnover_cap_usdt=Decimal("2000"),
        daily_trade_count_cap=20,
        daily_buy_cap_usdt=Decimal("1000"),
        open_order_count_cap=10,
        correlated_cap_usdt=Decimal("800"),
        reserve_usdt=Decimal("100"),
        max_consecutive_losses=3,
        cooldown_sec=60,
        halt_file=tmp_path / "halt.json",
        state_file=tmp_path / "state.json",
        alerts_file=tmp_path / "alerts.ndjson",
    )
    values.update(overrides)
    return RiskLimits(**values)


def snapshot(equity: str, **overrides) -> RiskSnapshot:
    values = dict(
        equity_usdt=Decimal(equity),
        exposure_usdt=Decimal("100"),
        free_usdt=Decimal("500"),
    )
    values.update(overrides)
    return RiskSnapshot(**values)


def test_daily_loss_trips_persistent_halt(tmp_path: Path):
    manager = RiskManager(limits(tmp_path))
    assert not manager.evaluate(snapshot("1000"), now=1_700_000_000).halted

    decision = manager.evaluate(snapshot("899"), now=1_700_000_100)
    assert decision.halted
    assert decision.buy_blocked
    assert "daily equity loss" in decision.reasons[0]
    assert (tmp_path / "halt.json").exists()

    restarted = RiskManager(limits(tmp_path))
    assert restarted.evaluate(snapshot("1100"), now=1_700_000_200).halted


def test_peak_drawdown_trips_after_new_high(tmp_path: Path):
    manager = RiskManager(limits(tmp_path, max_daily_loss_usdt=Decimal("1000")))
    manager.evaluate(snapshot("1000"), now=1_700_000_000)
    manager.evaluate(snapshot("1100"), now=1_700_000_010)
    decision = manager.evaluate(snapshot("1060"), now=1_700_000_020)
    assert decision.halted
    assert any("peak-equity" in reason for reason in decision.reasons)


def test_soft_limits_block_buys_without_permanent_halt(tmp_path: Path):
    manager = RiskManager(limits(tmp_path))
    decision = manager.evaluate(
        snapshot("1000", exposure_usdt=Decimal("1000")),
        now=1_700_000_000,
    )
    assert decision.buy_blocked
    assert not decision.halted
    assert not (tmp_path / "halt.json").exists()


def test_risk_snapshot_normalizes_legacy_numeric_inputs_to_decimal():
    observed = RiskSnapshot(
        equity_usdt=1000.25,
        exposure_usdt=400.5,
        free_usdt=599.75,
        daily_turnover_usdt=12.5,
        daily_buy_usdt=10.25,
        correlated_exposure_usdt=300.125,
        symbol_exposure_usdt={"solusdt": 300.125},
    )

    assert observed.equity_usdt == Decimal("1000.25")
    assert observed.daily_buy_usdt == Decimal("10.25")
    assert observed.correlated_exposure_usdt == Decimal("300.125")
    assert observed.symbol_exposure_usdt == {
        "SOLUSDT": Decimal("300.125")
    }


def test_risk_snapshot_rejects_non_finite_financial_values():
    with pytest.raises(ValueError, match="equity_usdt must be finite"):
        RiskSnapshot(
            equity_usdt="NaN",
            exposure_usdt="0",
            free_usdt="0",
        )


def test_reset_requires_cooldown_or_force(tmp_path: Path):
    manager = RiskManager(limits(tmp_path))
    manager.evaluate(snapshot("1000"), now=1_700_000_000)
    manager.evaluate(snapshot("800"), now=1_700_000_010)
    with pytest.raises(RuntimeError):
        manager.reset(now=1_700_000_020)
    manager.reset(force=True, now=1_700_000_020)
    assert not (tmp_path / "halt.json").exists()


def test_daily_trade_metrics(tmp_path: Path):
    db = tmp_path / "stats.db"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE trades(
          id INTEGER PRIMARY KEY, symbol TEXT, side TEXT, price REAL,
          qty REAL, fee_quote REAL, ts INTEGER
        );
        """
    )
    now = 1_700_000_000
    con.executemany(
        "INSERT INTO trades(symbol,side,price,qty,fee_quote,ts) VALUES(?,?,?,?,?,?)",
        [
            ("SOLUSDT", "BUY", 100, 1, 0.1, now * 1000),
            ("SOLUSDT", "SELL", 90, 1, 0.1, (now + 1) * 1000),
        ],
    )
    con.commit()
    con.close()
    result = load_daily_trade_metrics(str(db), ["SOLUSDT"], now=now + 2)
    assert result["daily_trade_count"] == 2
    assert result["daily_turnover_usdt"] == Decimal("190.0")
    assert result["daily_buy_usdt"] == Decimal("100.0")
    assert result["consecutive_losses"] == 1


def test_execution_failure_creates_persistent_manual_halt(tmp_path: Path):
    configured = limits(tmp_path)
    marker_path = create_manual_halt(
        "BUY 123 filled without protection",
        limits=configured,
        now=1000,
        metadata={"symbol": "SOLUSDT", "order_id": 123},
    )
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["manual_reset_required"] is True
    assert marker["reasons"] == ["BUY 123 filled without protection"]
    assert marker["metadata"]["order_id"] == 123
    state = json.loads(configured.state_file.read_text(encoding="utf-8"))
    assert state["halted"] is True
    assert state["halt_reasons"] == ["BUY 123 filled without protection"]
    assert state["halted_at"] == marker["halted_at"]
    assert state["cooldown_until"] == marker["cooldown_until"]


def test_manual_halt_preserves_existing_equity_state(tmp_path: Path):
    configured = limits(tmp_path)
    configured.state_file.write_text(
        json.dumps(
            {
                "day": "2026-07-29",
                "start_equity_usdt": "1000.25",
                "peak_equity_usdt": "1010.50",
                "last_equity_usdt": "1005.75",
            }
        ),
        encoding="utf-8",
    )

    create_manual_halt(
        "protection unavailable",
        limits=configured,
        now=1_775_000_000,
    )

    state = json.loads(configured.state_file.read_text(encoding="utf-8"))
    assert state["halted"] is True
    assert state["start_equity_usdt"] == "1000.25"
    assert state["peak_equity_usdt"] == "1010.50"
    assert state["last_equity_usdt"] == "1005.75"


def test_existing_halt_repairs_missing_risk_state(tmp_path: Path):
    configured = limits(tmp_path)
    configured.halt_file.write_text(
        json.dumps(
            {
                "halted_at": "2026-07-29T12:00:00+00:00",
                "reasons": ["unprotected managed inventory"],
                "manual_reset_required": True,
                "cooldown_until": 1_775_000_060,
            }
        ),
        encoding="utf-8",
    )

    assert sync_manual_halt_state(configured) is True

    state = json.loads(configured.state_file.read_text(encoding="utf-8"))
    assert state["halted"] is True
    assert state["halt_reasons"] == ["unprotected managed inventory"]
    assert state["halted_at"] == "2026-07-29T12:00:00+00:00"
