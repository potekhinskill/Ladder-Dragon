import sqlite3

import pytest

from ai_context import (
    AdvisorDecisionStore,
    build_portfolio_features,
    directional_success,
    load_trade_features,
    market_features_from_klines,
    build_market_features,
    orderbook_features,
    virtual_plan_result,
)


def create_stats_db(path):
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE trades(
                id INTEGER PRIMARY KEY,
                symbol TEXT, side TEXT, price REAL, qty REAL,
                fee_quote REAL, ts INTEGER, price_text TEXT,
                gross_qty TEXT, net_qty TEXT, commission_asset TEXT,
                commission_amount TEXT, commission_quote TEXT,
                commission_value_status TEXT
            );
            CREATE TABLE inventory(
                symbol TEXT PRIMARY KEY, qty REAL, avg_cost REAL,
                qty_text TEXT, avg_cost_text TEXT
            );
            """
        )


def test_trade_features_include_net_pnl_fees_series_and_position(tmp_path):
    db = tmp_path / "stats.db"
    create_stats_db(db)
    now_ms = 2_000_000_000_000
    rows = [
        ("BUY", 100, 1, 1, 0.10, now_ms - 3000),
        ("SELL", 110, 1, 1, 0.10, now_ms - 2000),
        ("BUY", 100, 1, 1, 0.10, now_ms - 1000),
        ("SELL", 90, 1, 1, 0.10, now_ms),
    ]
    with sqlite3.connect(db) as connection:
        for side, price, gross, net, fee, timestamp in rows:
            connection.execute(
                """
                INSERT INTO trades(
                    symbol,side,price,qty,fee_quote,ts,price_text,
                    gross_qty,net_qty,commission_asset,commission_amount,
                    commission_quote,commission_value_status
                ) VALUES('SOLUSDT',?,?,?,?,?,?,?,?,?,?,?,'exact')
                """,
                (
                    side, price, gross, fee, timestamp, str(price),
                    str(gross), str(net), "USDT", str(fee), str(fee),
                ),
            )
        connection.execute(
            "INSERT INTO inventory VALUES('SOLUSDT',1,100,'1','100')"
        )

    result = load_trade_features(
        str(db), "SOLUSDT", 105.0, now_ms=now_ms
    )

    assert result.trade_count_30d == 4
    assert result.sell_count_30d == 2
    assert result.win_rate_30d == 0.5
    assert result.consecutive_losses == 1
    assert result.fees_usdt_30d == pytest.approx(0.4)
    assert result.net_realized_pnl_30d == pytest.approx(-0.4)
    assert result.position_pnl_pct == pytest.approx(0.05)


def test_30d_pnl_uses_cost_basis_from_older_buy(tmp_path):
    db = tmp_path / "stats.db"
    create_stats_db(db)
    now_ms = 2_000_000_000_000
    with sqlite3.connect(db) as connection:
        connection.execute(
            """
            INSERT INTO trades(
                symbol,side,price,qty,fee_quote,ts,price_text,gross_qty,
                net_qty,commission_asset,commission_amount,commission_quote,
                commission_value_status
            ) VALUES('SOLUSDT','BUY',100,1,0,?,'100','1','1','USDT','0','0','exact')
            """,
            (now_ms - 40 * 86_400_000,),
        )
        connection.execute(
            """
            INSERT INTO trades(
                symbol,side,price,qty,fee_quote,ts,price_text,gross_qty,
                net_qty,commission_asset,commission_amount,commission_quote,
                commission_value_status
            ) VALUES('SOLUSDT','SELL',110,1,0,?,'110','1','1','USDT','0','0','exact')
            """,
            (now_ms - 1000,),
        )

    result = load_trade_features(str(db), "SOLUSDT", 110, now_ms=now_ms)

    assert result.trade_count_30d == 1
    assert result.sell_count_30d == 1
    assert result.net_realized_pnl_30d == 10
    assert result.win_rate_30d == 1


def test_market_and_orderbook_are_reduced_to_aggregates():
    klines = []
    for index in range(289):
        close = 100 + index * 0.1
        volume = 10 if index < 277 else 20
        klines.append([index, close, close, close, close, volume])

    market = market_features_from_klines(klines)
    spread, top5, top20 = orderbook_features(
        {
            "bids": [["99.9", "2"]] * 20,
            "asks": [["100.1", "1"]] * 20,
        }
    )

    assert market.return_15m > 0
    assert market.return_24h > market.return_1h
    assert market.volume_ratio_1h == 2
    assert spread == pytest.approx(20)
    assert top5 == pytest.approx(1 / 3)
    assert top20 == pytest.approx(1 / 3)


def test_market_features_accept_a_valid_zero_imbalance_orderbook():
    klines = [[index, 100, 100, 100, 100, 10] for index in range(289)]
    result = build_market_features(
        "SOLUSDT",
        get_klines=lambda *_args, **_kwargs: klines,
        public_get=lambda *_args, **_kwargs: {
            "bids": [["100", "1"]] * 20,
            "asks": [["100", "1"]] * 20,
        },
    )
    assert result.market_data_available is True
    assert result.orderbook_available is True


def test_portfolio_features_do_not_expose_order_ids_or_full_balance():
    result = build_portfolio_features(
        "SOLUSDT",
        open_orders=[
            {
                "symbol": "SOLUSDT",
                "side": "BUY",
                "price": "100",
                "origQty": "0.2",
                "orderId": 123,
            },
            {
                "symbol": "SOLUSDT",
                "side": "SELL",
                "price": "110",
                "origQty": "0.1",
                "orderId": 456,
            },
        ],
        balances={"USDT": {"free": 300}, "BTC": {"free": 99}},
        portfolio_cap_usdt=100,
        reserve_usdt=100,
    )

    assert result.open_buy_count == 1
    assert result.open_sell_count == 1
    assert result.open_buy_exposure_usdt == 20
    assert result.portfolio_cap_used_pct == 0.2
    assert result.free_reserve_ratio == 3
    assert not hasattr(result, "order_id")
    assert not hasattr(result, "balances")


def test_decision_store_settles_horizons_and_calculates_accuracy(tmp_path):
    store = AdvisorDecisionStore(str(tmp_path / "decisions.db"))
    store.record(
        symbol="SOLUSDT",
        price=100,
        deterministic_mode="FLAT",
        recommended_mode="UP",
        width_scale=1,
        cap_scale=0.8,
        confidence=0.8,
        applied=True,
        now=1000,
    )

    assert store.settle("SOLUSDT", 102, now=1000 + 900) == 1
    performance = store.performance("SOLUSDT")
    assert performance.ai_samples_15m == 1
    assert performance.ai_accuracy_15m == 1
    assert performance.ai_samples_1h == 0

    assert store.settle("SOLUSDT", 98, now=1000 + 14_400) == 1
    performance = store.performance("SOLUSDT")
    assert performance.ai_samples_1h == 1
    assert performance.ai_accuracy_1h == 0
    assert performance.ai_samples_4h == 1
    assert performance.ai_accuracy_4h == 0


def test_decision_store_records_virtual_ai_and_baseline_plan(tmp_path):
    store = AdvisorDecisionStore(str(tmp_path / "decisions.db"))
    store.record(
        symbol="SOLUSDT",
        price=100,
        deterministic_mode="FLAT",
        recommended_mode="UP",
        width_scale=1,
        cap_scale=.5,
        confidence=.8,
        applied=False,
        policy_status="SHADOW",
        now=1000,
    )
    candles = [
        [0, 100, 102, 98, 101],
        [1, 101, 104, 100, 103],
    ]
    store.settle(
        "SOLUSDT",
        103,
        now=1000 + 3600,
        candles_lookup=lambda *_: candles,
    )
    row = store.dashboard_summary()["recent"][0]
    assert row["evaluation"]["1h"]["ai"]["filled"] is True
    assert row["evaluation"]["1h"]["baseline"]["filled"] is True
    assert "net_return" in row["evaluation"]["1h"]["ai"]
    assert "mfe" in row["evaluation"]["1h"]["ai"]
    assert "mae" in row["evaluation"]["1h"]["ai"]


def test_directional_success_has_flat_deadband():
    assert directional_success("UP", 0.004) == 1
    assert directional_success("DOWN", -0.004) == 1
    assert directional_success("FLAT", 0.0005) == 1
    assert directional_success("FLAT", 0.01) == 0


def test_virtual_shadow_plan_includes_fill_costs_mfe_and_mae(monkeypatch):
    monkeypatch.setenv("AI_SHADOW_FEE_PCT", "0.001")
    monkeypatch.setenv("AI_SHADOW_SLIPPAGE_PCT", "0.001")
    result = virtual_plan_result(
        100, "UP", 1, .5,
        [
            [0, 100, 102, 99, 101],
            [1, 101, 104, 100, 103],
        ],
    )
    assert result["filled"] is True
    assert result["entry"] == 99.5
    assert result["mfe"] > 0
    assert result["mae"] < 0
    assert result["net_return"] == pytest.approx(
        (103 / 99.5 - 1) - .0042
    )
    assert result["scaled_pnl_pct"] == pytest.approx(result["net_return"] * .5)
