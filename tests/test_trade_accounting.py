from decimal import Decimal
import importlib.util
from pathlib import Path
import sqlite3

import pytest

from bin import pnl_24h
from ladder_dragon.execution import tools_stats
from ladder_dragon.risk.risk_manager import load_daily_trade_metrics
from ladder_dragon.execution.trade_accounting import TradeExecution, UnpricedCommission, replay_average_cost


def load_worker():
    path = Path("bin/autosize_universal.py").resolve()
    spec = importlib.util.spec_from_file_location("commission_worker", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_base_commission_reduces_buy_inventory_without_double_counting_cost():
    trade = TradeExecution.create(
        symbol="SOLUSDT",
        side="BUY",
        price="100",
        gross_qty="1",
        commission_asset="SOL",
        commission_amount="0.001",
        commission_quote="0.1",
    )
    result = replay_average_cost([trade])

    assert trade.net_qty == Decimal("0.999")
    assert result.qty == Decimal("0.999")
    assert result.avg_cost == Decimal("100") / Decimal("0.999")


def test_quote_and_bnb_commissions_are_included_in_cost_and_realized_pnl():
    buy = TradeExecution.create(
        symbol="SOLUSDT",
        side="BUY",
        price="100",
        gross_qty="1",
        commission_asset="USDT",
        commission_amount="0.1",
        commission_quote="0.1",
    )
    sell = TradeExecution.create(
        symbol="SOLUSDT",
        side="SELL",
        price="110",
        gross_qty="1",
        commission_asset="BNB",
        commission_amount="0.0002",
        commission_quote="0.06",
        commission_value_status="converted",
    )
    result = replay_average_cost([buy, sell])

    assert result.qty == Decimal("0")
    assert result.realized_pnl == Decimal("9.84")


def test_partial_fills_keep_exact_net_quantity_and_fifo(tmp_path):
    db = tmp_path / "stats.db"
    con = tools_stats.init_db(str(db))
    tools_stats.apply_trade(
        con, "SOLUSDT", "BUY", "100", "0.4", ts=1, trade_id=1,
        commission_asset="SOL", commission_amount="0.0004",
        commission_quote="0.04", commission_value_status="exact",
    )
    tools_stats.apply_trade(
        con, "SOLUSDT", "BUY", "101", "0.6", ts=2, trade_id=2,
        commission_asset="SOL", commission_amount="0.0006",
        commission_quote="0.0606", commission_value_status="exact",
    )
    tools_stats.apply_trade(
        con, "SOLUSDT", "SELL", "110", "0.5", ts=3, trade_id=3,
        commission_asset="USDT", commission_amount="0.055",
        commission_quote="0.055", commission_value_status="exact",
    )

    qty, avg, realized = tools_stats.get_inventory_decimal(con, "SOLUSDT")
    rows = con.execute(
        "SELECT gross_qty, net_qty, commission_asset FROM trades ORDER BY trade_id"
    ).fetchall()
    con.close()

    expected_avg = Decimal("100.6") / Decimal("0.999")
    assert rows == [("0.4", "0.3996", "SOL"), ("0.6", "0.5994", "SOL"), ("0.5", "0.5", "USDT")]
    assert qty == Decimal("0.499")
    assert avg == expected_avg
    assert realized == Decimal("54.945") - expected_avg * Decimal("0.5")


def test_trade_import_is_idempotent_after_restart(tmp_path):
    db = tmp_path / "stats.db"
    con = tools_stats.init_db(str(db))
    kwargs = dict(
        commission_asset="SOL",
        commission_amount="0.0001",
        commission_quote="0.01",
        commission_value_status="exact",
    )

    assert tools_stats.apply_trade(
        con, "SOLUSDT", "BUY", "100", "0.1", ts=1, trade_id=77, **kwargs
    ) is True
    assert tools_stats.apply_trade(
        con, "SOLUSDT", "BUY", "100", "0.1", ts=1, trade_id=77, **kwargs
    ) is False

    assert con.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 1
    assert tools_stats.get_inventory_decimal(con, "SOLUSDT")[0] == Decimal("0.0999")
    con.close()


def test_unpriced_commission_can_be_recovered_idempotently(tmp_path):
    db = tmp_path / "stats.db"
    con = tools_stats.init_db(str(db))
    common = dict(
        con=con, symbol="SOLUSDT", side="BUY", price="100", qty="1",
        ts=1, trade_id=88, commission_asset="BNB", commission_amount="0.001",
    )

    assert tools_stats.apply_trade(
        **common, commission_quote=None, commission_value_status="unpriced"
    ) is True
    assert tools_stats.apply_trade(
        **common, commission_quote="0.30", commission_value_status="converted"
    ) is True

    row = con.execute(
        "SELECT COUNT(*), commission_quote, commission_value_status FROM trades "
        "WHERE symbol='SOLUSDT' AND trade_id=88"
    ).fetchone()
    con.close()
    assert row == (1, "0.30", "converted")


def test_unpriced_external_commission_fails_closed_in_risk_metrics(tmp_path):
    db = tmp_path / "stats.db"
    con = tools_stats.init_db(str(db))
    tools_stats.apply_trade(
        con, "SOLUSDT", "BUY", "100", "1", ts=1_700_000_000_000, trade_id=1,
        commission_asset="BNB", commission_amount="0.001",
        commission_quote=None, commission_value_status="unpriced",
    )
    con.close()

    with pytest.raises(UnpricedCommission):
        load_daily_trade_metrics(str(db), ["SOLUSDT"], now=1_700_000_001)


def test_legacy_schema_remains_readable_by_risk_metrics(tmp_path):
    db = tmp_path / "legacy.db"
    with sqlite3.connect(db) as con:
        con.execute(
            "CREATE TABLE trades(id INTEGER PRIMARY KEY, symbol TEXT, side TEXT, "
            "price REAL, qty REAL, fee_quote REAL, ts INTEGER)"
        )
        con.execute(
            "INSERT INTO trades(symbol,side,price,qty,fee_quote,ts) VALUES(?,?,?,?,?,?)",
            ("SOLUSDT", "BUY", 100, 1, 0.1, 1_700_000_000_000),
        )

    metrics = load_daily_trade_metrics(str(db), ["SOLUSDT"], now=1_700_000_001)
    assert metrics["daily_buy_usdt"] == Decimal("100.0")


def test_worker_prices_bnb_commission_from_recorded_minute(monkeypatch):
    worker = load_worker()
    worker._COMMISSION_QUOTE_CACHE.clear()
    monkeypatch.setattr(worker, "get_symbol_assets", lambda symbol: ("SOL", "USDT"))
    monkeypatch.setattr(
        worker,
        "_public_get",
        lambda path, params: [[0, "0", "0", "0", "300.00", "0"]],
    )

    value, status = worker._commission_quote_value(
        "SOLUSDT", "BNB", Decimal("0.001"), Decimal("100"), 1_700_000_000_000
    )

    assert value == Decimal("0.30000")
    assert status == "converted"


def test_worker_marks_unknown_commission_pair_unpriced(monkeypatch):
    worker = load_worker()
    worker._COMMISSION_QUOTE_CACHE.clear()
    monkeypatch.setattr(worker, "get_symbol_assets", lambda symbol: ("SOL", "USDT"))
    monkeypatch.setattr(worker, "_public_get", lambda path, params: [])

    value, status = worker._commission_quote_value(
        "SOLUSDT", "UNKNOWN", Decimal("1"), Decimal("100"), 1_700_000_000_000
    )

    assert value is None
    assert status == "unpriced"


def test_worker_retries_unpriced_trade_before_advancing_cursor(tmp_path, monkeypatch):
    # Never inherit an operator's production AI database while pytest uses a
    # temporary statistics database.
    monkeypatch.setenv("AI_DECISIONS_DB", str(tmp_path / "ai_decisions.sqlite3"))
    worker = load_worker()
    worker.STATS_ENABLE = True
    worker.STATS_DB = str(tmp_path / "stats.db")
    worker.STATS_CON = None
    worker.TOOLS_STATS = None
    trade = {
        "id": 5,
        "isBuyer": True,
        "price": "100",
        "qty": "1",
        "time": 1_700_000_000_000,
        "commission": "0.001",
        "commissionAsset": "BNB",
    }
    monkeypatch.setattr(worker, "get_symbol_assets", lambda symbol: ("SOL", "USDT"))
    monkeypatch.setattr(worker, "_signed_request", lambda *args, **kwargs: [trade])
    monkeypatch.setattr(
        worker, "_commission_quote_value", lambda *args: (None, "unpriced")
    )

    worker._stats_poll_mytrades_once("SOLUSDT")
    assert worker.TOOLS_STATS.get_last_trade_id(worker.STATS_CON, "SOLUSDT") is None

    monkeypatch.setattr(
        worker,
        "_commission_quote_value",
        lambda *args: (Decimal("0.30"), "converted"),
    )
    worker._stats_poll_mytrades_once("SOLUSDT")

    assert worker.TOOLS_STATS.get_last_trade_id(worker.STATS_CON, "SOLUSDT") == 5
    row = worker.STATS_CON.execute(
        "SELECT COUNT(*), commission_quote, commission_value_status FROM trades"
    ).fetchone()
    worker.STATS_CON.close()
    assert row == (1, "0.30", "converted")
    with sqlite3.connect(tmp_path / "ai_decisions.sqlite3") as ai_connection:
        unresolved = ai_connection.execute(
            "SELECT COUNT(*) FROM ai_unresolved_fills"
        ).fetchone()[0]
    assert unresolved == 1


def test_pnl_report_uses_net_quantity_and_exact_commissions(tmp_path):
    db = tmp_path / "stats.db"
    con = tools_stats.init_db(str(db))
    con.row_factory = sqlite3.Row
    tools_stats.apply_trade(
        con, "SOLUSDT", "BUY", "100", "1", ts=1, trade_id=1,
        commission_asset="SOL", commission_amount="0.001",
        commission_quote="0.1", commission_value_status="exact",
    )
    tools_stats.apply_trade(
        con, "SOLUSDT", "SELL", "110", "0.5", ts=2, trade_id=2,
        commission_asset="USDT", commission_amount="0.055",
        commission_quote="0.055", commission_value_status="exact",
    )

    by_symbol, cash_total = pnl_24h.pnl_cash(con, 0, 10, ["SOLUSDT"])
    _, _, realized = pnl_24h.replay_until(con, 10, ["SOLUSDT"])
    con.close()

    avg = Decimal("100") / Decimal("0.999")
    assert by_symbol["SOLUSDT"] == Decimal("-45.055")
    assert cash_total == Decimal("-45.055")
    assert realized["SOLUSDT"] == Decimal("54.945") - avg * Decimal("0.5")
