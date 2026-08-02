from decimal import Decimal
from pathlib import Path
import json
import multiprocessing
import sqlite3
import time

import pytest

from ladder_dragon.execution import tools_stats
from ladder_dragon.execution.trade_accounting import TradeExecution
from ladder_dragon.risk.risk_manager import (
    RiskLimits,
    RiskManager,
    RiskSnapshot,
    create_manual_halt,
    load_daily_trade_metrics,
    sync_manual_halt_state,
)
from ladder_dragon.risk import risk_manager as risk_module
from ladder_dragon.risk.trade_streaks import (
    MAX_RETAINED_SELL_OUTCOMES,
    record_trade_outcome,
)


def _reset_in_child(configured: RiskLimits, result_queue) -> None:
    RiskManager(configured).reset(force=True, now=1_700_000_100)
    result_queue.put("reset")


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


def test_default_raspberry_control_paths_move_to_existing_state_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    control_dir = tmp_path / "control"
    control_dir.mkdir()
    monkeypatch.setenv("LADDER_DRAGON_CONTROL_DIR", str(control_dir))
    monkeypatch.setenv("BOT_RUN_DIR", "/run/mybot")
    for name in ("CB_HALT_FILE", "CB_STATE_FILE", "CB_ALERTS_FILE"):
        monkeypatch.delenv(name, raising=False)

    configured = RiskLimits.from_env()

    assert configured.halt_file == control_dir / "circuit_halt.json"
    assert configured.state_file == control_dir / "risk_state.json"
    assert configured.alerts_file == control_dir / "risk_alerts.ndjson"


def test_runtime_mapping_resolves_persistent_control_paths(tmp_path: Path):
    control_dir = tmp_path / "control"
    control_dir.mkdir()

    configured = RiskLimits.from_runtime_mapping({
        "LADDER_DRAGON_CONTROL_DIR": str(control_dir),
        "BOT_RUN_DIR": "/run/mybot",
    })

    assert configured.halt_file == control_dir / "circuit_halt.json"
    assert configured.state_file == control_dir / "risk_state.json"
    assert configured.alerts_file == control_dir / "risk_alerts.ndjson"


def test_explicit_control_paths_are_never_redirected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    control_dir = tmp_path / "control"
    control_dir.mkdir()
    isolated = tmp_path / "testnet"
    monkeypatch.setenv("LADDER_DRAGON_CONTROL_DIR", str(control_dir))
    monkeypatch.setenv("BOT_RUN_DIR", "/run/mybot")
    monkeypatch.setenv("CB_HALT_FILE", str(isolated / "halt.json"))
    monkeypatch.setenv("CB_STATE_FILE", str(isolated / "state.json"))
    monkeypatch.setenv("CB_ALERTS_FILE", str(isolated / "alerts.ndjson"))

    configured = RiskLimits.from_env()

    assert configured.halt_file == isolated / "halt.json"
    assert configured.state_file == isolated / "state.json"
    assert configured.alerts_file == isolated / "alerts.ndjson"


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


def test_incomplete_loss_streak_blocks_buy_without_losing_risk_snapshot(
    tmp_path: Path,
):
    manager = RiskManager(limits(tmp_path))

    decision = manager.evaluate(
        snapshot(
            "1000",
            loss_streak_complete=False,
            loss_streak_incomplete_symbols=("SOLUSDT",),
        ),
        now=1_700_000_000,
    )

    assert decision.buy_blocked is True
    assert decision.halted is False
    assert decision.reasons == (
        "loss streak evidence is incomplete: SOLUSDT",
    )
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


def test_migrated_risk_metrics_use_bounded_sell_outcomes(tmp_path: Path):
    db = tmp_path / "stats.db"
    con = tools_stats.init_db(str(db))
    assert tools_stats.apply_trade(
        con,
        "SOLUSDT",
        "BUY",
        "100",
        "1",
        ts=1_700_000_000_000,
        trade_id=1,
        commission_quote="0.1",
        commission_value_status="exact",
    )
    assert tools_stats.apply_trade(
        con,
        "SOLUSDT",
        "SELL",
        "90",
        "1",
        ts=1_700_000_001_000,
        trade_id=2,
        commission_quote="0.1",
        commission_value_status="exact",
    )
    assert con.execute(
        "SELECT net_pnl_quote_text FROM risk_sell_outcomes"
    ).fetchone() == ("-10.2",)
    con.close()

    metrics = load_daily_trade_metrics(
        str(db), ["SOLUSDT"], now=1_700_000_002, streak_limit=3
    )

    assert metrics["consecutive_losses"] == 1
    assert metrics["symbol_consecutive_losses"] == {"SOLUSDT": 1}


def test_loss_streak_uses_fifo_sign_instead_of_average_cost(tmp_path: Path):
    db = tmp_path / "stats.db"
    con = tools_stats.init_db(str(db))
    for side, price, timestamp, trade_id in (
        ("BUY", "200", 1_700_000_000_000, 1),
        ("BUY", "100", 1_700_000_001_000, 2),
        ("SELL", "160", 1_700_000_002_000, 3),
    ):
        assert tools_stats.apply_trade(
            con,
            "SOLUSDT",
            side,
            price,
            "1",
            ts=timestamp,
            trade_id=trade_id,
            commission_quote="0",
            commission_value_status="exact",
        )

    assert con.execute(
        "SELECT net_pnl_quote_text FROM risk_sell_outcomes"
    ).fetchone() == ("-40",)
    assert tools_stats.get_inventory_decimal(con, "SOLUSDT")[2] == Decimal("10")
    con.close()

    metrics = load_daily_trade_metrics(
        str(db), ["SOLUSDT"], now=1_700_000_003, streak_limit=3
    )
    assert metrics["consecutive_losses"] == 1
    assert metrics["symbol_consecutive_losses"] == {"SOLUSDT": 1}


def test_loss_streak_marks_missing_fifo_without_rejecting_accounting(
    tmp_path: Path,
):
    db = tmp_path / "stats.db"
    con = tools_stats.init_db(str(db))

    assert tools_stats.apply_trade(
        con,
        "SOLUSDT",
        "SELL",
        "160",
        "1",
        ts=1_700_000_000_000,
        trade_id=1,
        commission_quote="0",
        commission_value_status="exact",
    )

    assert con.execute("SELECT COUNT(*) FROM trades").fetchone() == (1,)
    assert con.execute("SELECT COUNT(*) FROM risk_sell_outcomes").fetchone() == (0,)
    assert con.execute(
        "SELECT last_trade_at,last_trade_row_id,open_fifo_lot_count "
        "FROM risk_sell_outcome_state"
    ).fetchone() == (1_700_000_000_000, 1, 0)
    con.close()

    metrics = load_daily_trade_metrics(
        str(db), ["SOLUSDT"], now=1_700_000_001, streak_limit=3
    )
    assert metrics["loss_streak_complete"] is False
    assert metrics["loss_streak_incomplete_symbols"] == ("SOLUSDT",)


def test_incomplete_fifo_symbol_does_not_block_an_exact_symbol(tmp_path: Path):
    db = tmp_path / "stats.db"
    con = tools_stats.init_db(str(db))
    for symbol, side, price, timestamp, trade_id in (
        ("ETHUSDT", "SELL", "2000", 1_700_000_000_000, 1),
        ("SOLUSDT", "BUY", "100", 1_700_000_001_000, 2),
        ("SOLUSDT", "SELL", "110", 1_700_000_002_000, 3),
    ):
        assert tools_stats.apply_trade(
            con,
            symbol,
            side,
            price,
            "1",
            ts=timestamp,
            trade_id=trade_id,
            commission_quote="0",
            commission_value_status="exact",
        )
    con.close()

    metrics = load_daily_trade_metrics(
        str(db), ["SOLUSDT"], now=1_700_000_003, streak_limit=3
    )
    assert metrics["consecutive_losses"] == 0
    assert metrics["symbol_consecutive_losses"] == {"SOLUSDT": 0}
    assert metrics["loss_streak_complete"] is True
    eth_metrics = load_daily_trade_metrics(
        str(db), ["ETHUSDT"], now=1_700_000_003, streak_limit=3
    )
    assert eth_metrics["loss_streak_complete"] is False
    assert eth_metrics["loss_streak_incomplete_symbols"] == ("ETHUSDT",)


def test_migrated_risk_metrics_do_not_replay_old_trade_rows(tmp_path: Path):
    db = tmp_path / "stats.db"
    con = tools_stats.init_db(str(db))
    con.execute(
        "INSERT INTO trades("
        "symbol,side,price_text,gross_qty,net_qty,commission_asset,"
        "commission_amount,commission_quote,commission_value_status,ts,trade_id"
        ") VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            "SOLUSDT", "BUY", "invalid-old-price", "1", "1", "USDT",
            "0", "0", "exact", 1_600_000_000_000, 10,
        ),
    )
    con.commit()
    con.close()

    metrics = load_daily_trade_metrics(
        str(db), ["SOLUSDT"], now=1_700_000_000, streak_limit=3
    )

    assert metrics["daily_trade_count"] == 0
    assert metrics["consecutive_losses"] == 0


def test_sell_outcome_index_has_a_fixed_growth_bound(tmp_path: Path):
    db = tmp_path / "stats.db"
    con = tools_stats.init_db(str(db))
    con.executemany(
        "INSERT INTO risk_sell_outcomes("
        "trade_row_id,symbol,exchange_trade_id,executed_at,net_pnl_quote_text"
        ") VALUES(?,?,?,?,?)",
        (
            (row_id, "SOLUSDT", row_id, row_id, "-1")
            for row_id in range(1, MAX_RETAINED_SELL_OUTCOMES + 2)
        ),
    )
    con.execute(
        "INSERT INTO risk_fifo_lots("
        "source_trade_row_id,symbol,exchange_trade_id,opened_at,"
        "remaining_qty_text,unit_cost_quote_text) VALUES(?,?,?,?,?,?)",
        (9_000, "SOLUSDT", 9_000, 9_000, "1", "100"),
    )
    con.execute(
        "UPDATE risk_sell_outcome_state SET open_fifo_lot_count=1"
    )
    record_trade_outcome(
        con,
        trade_row_id=9_001,
        exchange_trade_id=9_001,
        executed_at=9_001,
        trade=TradeExecution.create(
            symbol="SOLUSDT",
            side="SELL",
            price="101",
            gross_qty="1",
            commission_quote="0",
        ),
    )
    con.commit()

    assert con.execute("SELECT COUNT(*) FROM risk_sell_outcomes").fetchone() == (
        MAX_RETAINED_SELL_OUTCOMES,
    )
    con.close()


def test_out_of_order_symbol_sync_rebuilds_global_streak_by_trade_time(
    tmp_path: Path,
):
    db = tmp_path / "stats.db"
    con = tools_stats.init_db(str(db))
    for symbol, side, price, timestamp, trade_id in (
        ("SOLUSDT", "BUY", "100", 1_700_000_000_000, 1),
        ("SOLUSDT", "SELL", "90", 1_700_000_003_000, 2),
        ("ETHUSDT", "BUY", "100", 1_700_000_001_000, 3),
        ("ETHUSDT", "SELL", "110", 1_700_000_002_000, 4),
    ):
        assert tools_stats.apply_trade(
            con,
            symbol,
            side,
            price,
            "1",
            ts=timestamp,
            trade_id=trade_id,
            commission_quote="0",
            commission_value_status="exact",
        )
    con.close()

    metrics = load_daily_trade_metrics(
        str(db),
        ["SOLUSDT", "ETHUSDT"],
        now=1_700_000_004,
        streak_limit=3,
    )

    assert metrics["consecutive_losses"] == 1
    assert metrics["symbol_consecutive_losses"] == {
        "SOLUSDT": 1,
        "ETHUSDT": 0,
    }


def test_control_lock_serializes_reset_with_other_processes(tmp_path: Path):
    configured = limits(tmp_path)
    create_manual_halt("manual review", limits=configured, now=1_700_000_000)
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    process = context.Process(
        target=_reset_in_child,
        args=(configured, result_queue),
    )

    with risk_module._control_state_lock(configured):
        process.start()
        time.sleep(0.2)
        assert process.is_alive()
        assert configured.halt_file.exists()

    process.join(timeout=5)
    assert process.exitcode == 0
    assert result_queue.get(timeout=1) == "reset"
    assert not configured.halt_file.exists()
    state = json.loads(configured.state_file.read_text(encoding="utf-8"))
    assert state["halted"] is False


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
