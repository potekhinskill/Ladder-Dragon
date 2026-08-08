import sqlite3
from decimal import Decimal

import pytest

from ladder_dragon.ai.context.runtime import AdvisorDecisionStore, evaluate_realized_ai_pnl


def test_ai_decision_fills_are_linked_and_evaluated(tmp_path):
    store = AdvisorDecisionStore(str(tmp_path / "ai.db"))
    decision = store.record(symbol="SOLUSDT", price=100, deterministic_mode="FLAT",
                            recommended_mode="UP", width_scale=1, cap_scale=1,
                            confidence=.8, applied=True)
    store.record_fill(
        decision, symbol="SOLUSDT", side="BUY", price=100, qty=1,
        fee_quote=.1, slippage_quote=0, ts=10,
    )
    store.record_fill(decision, symbol="SOLUSDT", side="SELL", price=102, qty=1, fee_quote=.1,
                      exit_reason="OCO_TP", slippage_quote=0, ts=70)
    result = store.evaluate_execution(decision, baseline_exit_price=101)
    assert result["net_pnl_quote"] == 1.8
    assert result["holding_duration_sec"] == 60.0
    assert result["opportunity_cost_quote"] < 0


def test_ai_pnl_preserves_exact_decimal_companions():
    result = evaluate_realized_ai_pnl(
        [
            {"side": "BUY", "price": "0.123456789", "qty": "3.00000000",
             "fee_quote": "0.00000001", "slippage_quote": "0",
             "slippage_value_status": "exact"},
            {"side": "SELL", "price": "0.223456789", "qty": "3.00000000",
             "fee_quote": "0.00000002", "slippage_quote": "0",
             "slippage_value_status": "exact"},
        ]
    )

    assert Decimal(result["net_pnl_quote_text"]) == Decimal("0.29999997000000000")
    assert result["buy_qty_text"] == "3.00000000"
    assert result["sell_qty_text"] == "3.00000000"


def test_ai_store_persists_exact_fill_and_expected_price_text(tmp_path):
    path = tmp_path / "ai.db"
    store = AdvisorDecisionStore(str(path))
    decision = store.record(
        symbol="SOLUSDT", price=100, deterministic_mode="FLAT",
        recommended_mode="UP", width_scale=1, cap_scale=1,
        confidence=.8, applied=False,
    )
    store.link_client_order(
        "exact-client", decision, symbol="SOLUSDT",
        expected_price="0.123456789123456789",
    )
    store.record_fill(
        decision, symbol="SOLUSDT", side="BUY",
        price="0.123456789123456789", qty="3.000000000000000001",
        fee_quote="0.000000000000000003", slippage_quote="0.000000000000000004",
    )

    with sqlite3.connect(path) as connection:
        fill = connection.execute(
            "SELECT typeof(price),price,price_text,typeof(qty),qty,qty_text,"
            "typeof(fee_quote),fee_quote,fee_quote_text,"
            "typeof(slippage_quote),slippage_quote,slippage_quote_text,"
            "slippage_value_status FROM ai_fills"
        ).fetchone()
        expected = connection.execute(
            "SELECT expected_price_text FROM ai_order_links WHERE client_order_id='exact-client'"
        ).fetchone()
    assert fill == (
        "text", "0.123456789123456789", "0.123456789123456789",
        "text", "3.000000000000000001", "3.000000000000000001",
        "text", "0.000000000000000003", "0.000000000000000003",
        "text", "0.000000000000000004", "0.000000000000000004",
        "exact",
    )
    assert expected == ("0.123456789123456789",)


def test_ai_store_persists_exact_decision_price_and_settlement_returns(tmp_path):
    path = tmp_path / "ai.db"
    store = AdvisorDecisionStore(str(path))
    decision = store.record(
        symbol="SOLUSDT", price="0.123456789123456789",
        deterministic_mode="FLAT", recommended_mode="UP",
        width_scale=1, cap_scale=1, confidence=.8, applied=False,
        now=1_000,
    )
    assert store.settle(
        "SOLUSDT", "0.223456789123456789", now=20_000,
        price_lookup=lambda _symbol, _stamp: "0.223456789123456789",
    ) == 1

    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT price_text,return_15m_text,return_1h_text,return_4h_text "
            "FROM ai_decisions WHERE decision_id=?",
            (decision,),
        ).fetchone()
    expected_return = (
        Decimal("0.223456789123456789")
        / Decimal("0.123456789123456789")
        - Decimal("1")
    )
    assert row[0] == "0.123456789123456789"
    assert all(Decimal(value) == expected_return for value in row[1:])


def test_fill_mapping_uses_exchange_order_id_and_unresolved_is_excluded(tmp_path):
    store = AdvisorDecisionStore(str(tmp_path / "ai.db"))
    decision = store.record(symbol="SOLUSDT", price=100, deterministic_mode="FLAT",
                            recommended_mode="UP", width_scale=1, cap_scale=1,
                            confidence=.8, applied=True)
    store.link_client_order(
        "client-buy", decision, symbol="SOLUSDT", order_type="LIMIT",
        exchange_order_id=12345, expected_price=100,
    )
    mapping = store.decision_for_exchange_order(12345)
    assert mapping == (decision, "client-buy", "")
    assert store.order_link_for_exchange_order(12345)["expected_price"] == 100
    store.record_fill(
        decision, symbol="SOLUSDT", side="BUY", price=100, qty=.5,
        order_id=12345, client_order_id="client-buy", ts=10,
    )
    store.record_unresolved_fill(
        symbol="SOLUSDT", side="SELL", price=99, qty=.1,
        order_id=99999, trade_id=77, ts=20,
    )
    assert store.unresolved_fill_count() == 1
    result = store.evaluate_execution(decision)
    assert result["sell_qty"] == 0
    assert result["closed"] is False


def test_late_exchange_link_resolves_fill_atomically(tmp_path):
    path = tmp_path / "ai.db"
    store = AdvisorDecisionStore(str(path))
    decision = store.record(
        symbol="SOLUSDT", price=100, deterministic_mode="FLAT",
        recommended_mode="UP", width_scale=1, cap_scale=1,
        confidence=.8, applied=True,
    )
    store.link_client_order(
        "client-buy", decision, symbol="SOLUSDT", order_type="LIMIT"
    )
    store.record_unresolved_fill(
        symbol="SOLUSDT", side="BUY", price="77.33", qty="0.124",
        fee_quote="0.001", order_id=12345, trade_id=88, ts=20,
    )

    store.update_order_link("client-buy", exchange_order_id=12345)

    assert store.unresolved_fill_count() == 0
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT decision_id,client_order_id,order_id,trade_id,"
            "price_text,qty_text,fee_quote_text,link_status,"
            "slippage_value_status FROM ai_fills"
        ).fetchone()
    assert row == (
        decision, "client-buy", "12345", "88",
        "77.33", "0.124", "0.001", "resolved", "unavailable",
    )


def test_store_startup_backfills_previously_known_unresolved_fill(tmp_path):
    path = tmp_path / "ai.db"
    store = AdvisorDecisionStore(str(path))
    decision = store.record(
        symbol="SOLUSDT", price=100, deterministic_mode="FLAT",
        recommended_mode="UP", width_scale=1, cap_scale=1,
        confidence=.8, applied=True,
    )
    store.link_client_order(
        "client-buy", decision, symbol="SOLUSDT",
        order_type="LIMIT", exchange_order_id=12345,
    )
    store.record_unresolved_fill(
        symbol="SOLUSDT", side="BUY", price="77.33", qty="0.124",
        order_id=12345, trade_id=89, ts=21,
    )
    assert store.unresolved_fill_count() == 1

    restarted = AdvisorDecisionStore(str(path))

    assert restarted.unresolved_fill_count() == 0
    assert restarted.evaluate_execution(decision)["buy_qty_text"] == "0.124"


def test_unresolved_fill_scope_keeps_attribution_out_of_inventory_gate(
    tmp_path,
):
    store = AdvisorDecisionStore(str(tmp_path / "ai.db"))
    store.record_unresolved_fill(
        symbol="SOLUSDT",
        side="BUY",
        price="77.33",
        qty="0.124",
        order_id=12345,
    )
    store.record_unresolved_fill(
        symbol="SOLUSDT",
        side="BUY",
        price="76.00",
        qty="0.100",
        order_id=67890,
        ts=21,
        resolution_scope="INVENTORY",
    )

    assert store.unresolved_fill_count() == 2
    assert store.unresolved_fill_count_by_scope("ATTRIBUTION") == 1
    assert store.unresolved_fill_count_by_scope("INVENTORY") == 1


def test_unresolved_fill_scope_rejects_unknown_classification(tmp_path):
    store = AdvisorDecisionStore(str(tmp_path / "ai.db"))

    with pytest.raises(ValueError, match="resolution scope"):
        store.record_unresolved_fill(
            symbol="SOLUSDT",
            side="BUY",
            price="77.33",
            qty="0.124",
            resolution_scope="UNKNOWN",
        )


def test_unresolved_fill_amount_columns_keep_exact_text(tmp_path):
    path = tmp_path / "ai.db"
    store = AdvisorDecisionStore(str(path))
    store.record_unresolved_fill(
        symbol="SOLUSDT",
        side="BUY",
        price="0.123456789123456789",
        qty="3.000000000000000001",
        fee_quote="0.000000000000000003",
        order_id=12345,
    )

    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT typeof(price),price,price_text,typeof(qty),qty,qty_text,"
            "typeof(fee_quote),fee_quote,fee_quote_text "
            "FROM ai_unresolved_fills"
        ).fetchone()

    assert row == (
        "text", "0.123456789123456789", "0.123456789123456789",
        "text", "3.000000000000000001", "3.000000000000000001",
        "text", "0.000000000000000003", "0.000000000000000003",
    )


def test_legacy_unresolved_mapping_migrates_to_attribution_scope(tmp_path):
    path = tmp_path / "ai.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE ai_unresolved_fills(
                fill_key TEXT PRIMARY KEY, symbol TEXT NOT NULL,
                side TEXT NOT NULL, order_id TEXT, trade_id TEXT,
                price REAL NOT NULL, qty REAL NOT NULL,
                fee_quote REAL NOT NULL DEFAULT 0, ts INTEGER NOT NULL,
                reason TEXT NOT NULL, created_at INTEGER NOT NULL
            )"""
        )
        connection.execute(
            "INSERT INTO ai_unresolved_fills VALUES("
            "'legacy','SOLUSDT','BUY','123',NULL,77.33,0.124,0,"
            "20,'exchange_order_id_not_mapped_to_decision',20)"
        )

    store = AdvisorDecisionStore(str(path))

    assert store.unresolved_fill_count_by_scope("ATTRIBUTION") == 1
    assert store.unresolved_fill_count_by_scope("INVENTORY") == 0
    with sqlite3.connect(path) as connection:
        affinities = {
            row[1]: row[2]
            for row in connection.execute(
                "PRAGMA table_info(ai_unresolved_fills)"
            )
        }
        values = connection.execute(
            "SELECT typeof(price),price,price_text,typeof(qty),qty,qty_text "
            "FROM ai_unresolved_fills"
        ).fetchone()
    assert affinities["price"] == "TEXT"
    assert affinities["qty"] == "TEXT"
    assert affinities["fee_quote"] == "TEXT"
    assert values[0] == "text"
    assert values[1] == values[2]
    assert float(values[1]) == 77.33
    assert values[3] == "text"
    assert values[4] == values[5]
    assert float(values[4]) == 0.124


def test_unresolved_fill_migration_rejects_invalid_exact_evidence(tmp_path):
    path = tmp_path / "damaged-ai.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """CREATE TABLE ai_unresolved_fills(
                fill_key TEXT PRIMARY KEY, symbol TEXT NOT NULL,
                side TEXT NOT NULL, order_id TEXT, trade_id TEXT,
                price REAL NOT NULL, qty REAL NOT NULL,
                fee_quote REAL NOT NULL DEFAULT 0,
                price_text TEXT, qty_text TEXT, fee_quote_text TEXT,
                ts INTEGER NOT NULL, reason TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )"""
        )
        connection.execute(
            "INSERT INTO ai_unresolved_fills VALUES("
            "'damaged','SOLUSDT','BUY','123',NULL,77.33,0.124,0,"
            "'not-a-decimal','0.124','0',20,'damaged evidence',20)"
        )

    with pytest.raises(ValueError, match="monetary evidence") as caught:
        AdvisorDecisionStore(str(path))

    assert "not-a-decimal" not in str(caught.value)
    with sqlite3.connect(path) as connection:
        price_affinity = {
            row[1]: row[2]
            for row in connection.execute(
                "PRAGMA table_info(ai_unresolved_fills)"
            )
        }["price"]
    assert price_affinity == "REAL"


def test_realized_result_records_partial_fill_and_exit_metadata(tmp_path):
    store = AdvisorDecisionStore(str(tmp_path / "ai.db"))
    decision = store.record(symbol="SOLUSDT", price=100, deterministic_mode="FLAT",
                            recommended_mode="UP", width_scale=1, cap_scale=1,
                            confidence=.8, applied=True)
    store.record_fill(
        decision, symbol="SOLUSDT", side="BUY", price=100, qty=1,
        slippage_quote=0, ts=10,
    )
    store.record_fill(decision, symbol="SOLUSDT", side="SELL", price=101, qty=.5,
                      exit_reason="STOP", slippage_quote=.1, ts=20)
    result = store.evaluate_execution(decision)
    assert result["partial_fill"] is True
    assert result["exit_reason"] == "STOP"
    assert result["slippage_quote"] == .1


def test_unknown_slippage_blocks_financial_evidence(tmp_path):
    store = AdvisorDecisionStore(str(tmp_path / "ai.db"))
    decision = store.record(
        symbol="SOLUSDT", price=100, deterministic_mode="FLAT",
        recommended_mode="UP", width_scale=1, cap_scale=1,
        confidence=.8, applied=True,
    )
    store.record_fill(
        decision, symbol="SOLUSDT", side="BUY", price=100, qty=1,
        slippage_quote=0, ts=10,
    )
    store.record_fill(
        decision, symbol="SOLUSDT", side="SELL", price=101, qty=1, ts=20,
    )

    result = store.evaluate_execution(decision)

    assert result["closed"] is True
    assert result["financial_evidence_complete"] is False
    assert result["slippage_value_status"] == "unavailable"
    assert result["slippage_quote_text"] is None
    assert result["net_pnl_quote_text"] is None
    assert result["opportunity_cost_quote_text"] is None


def test_exchange_trade_id_is_idempotent_and_preserved(tmp_path):
    store = AdvisorDecisionStore(str(tmp_path / "ai.db"))
    decision = store.record(
        symbol="SOLUSDT", price=100, deterministic_mode="FLAT",
        recommended_mode="UP", width_scale=1, cap_scale=1, confidence=.8,
        applied=True,
    )
    first = store.record_fill(
        decision, symbol="SOLUSDT", side="BUY", price=100, qty=.5,
        order_id=123, trade_id=456, client_order_id="buy-client", ts=10,
    )
    second = store.record_fill(
        decision, symbol="SOLUSDT", side="BUY", price=100, qty=.5,
        order_id=123, trade_id=456, client_order_id="buy-client", ts=10,
    )
    assert first == second
    result = store.evaluate_execution(decision)
    assert result["buy_qty"] == .5


def test_restart_relink_does_not_replace_original_decision(tmp_path):
    store = AdvisorDecisionStore(str(tmp_path / "ai.db"))
    first = store.record(
        symbol="SOLUSDT", price=100, deterministic_mode="FLAT",
        recommended_mode="UP", width_scale=1, cap_scale=1, confidence=.8,
        applied=True,
    )
    second = store.record(
        symbol="SOLUSDT", price=101, deterministic_mode="UP",
        recommended_mode="FLAT", width_scale=1, cap_scale=1, confidence=.8,
        applied=False,
    )
    store.link_client_order("oco-client", first, symbol="SOLUSDT", order_type="OCO")
    store.link_client_order("oco-client", second, symbol="SOLUSDT", order_type="OCO")
    assert store.decision_for_client_order("oco-client")[0] == first


def test_legacy_ai_schema_migrates_before_new_indexes(tmp_path):
    path = tmp_path / "legacy-ai.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE ai_decisions(
                decision_id TEXT PRIMARY KEY, symbol TEXT NOT NULL,
                created_at INTEGER NOT NULL, price REAL NOT NULL,
                deterministic_mode TEXT NOT NULL, recommended_mode TEXT NOT NULL,
                width_scale REAL NOT NULL, cap_scale REAL NOT NULL,
                confidence REAL NOT NULL, applied INTEGER NOT NULL,
                policy_status TEXT NOT NULL DEFAULT '',
                policy_reasons TEXT NOT NULL DEFAULT '',
                benchmark_mode TEXT NOT NULL DEFAULT '',
                evaluation_json TEXT NOT NULL DEFAULT '{}',
                feature_json TEXT NOT NULL DEFAULT '[]',
                return_15m REAL, return_1h REAL, return_4h REAL
            );
            CREATE TABLE ai_fills(
                fill_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL,
                symbol TEXT NOT NULL, side TEXT NOT NULL, price REAL NOT NULL,
                qty REAL NOT NULL, fee_quote REAL NOT NULL DEFAULT 0,
                exit_reason TEXT NOT NULL DEFAULT '', ts INTEGER NOT NULL
            );
            CREATE TABLE ai_order_links(
                client_order_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL,
                symbol TEXT NOT NULL, lot_id INTEGER,
                order_type TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL
            );
            INSERT INTO ai_decisions(
                decision_id,symbol,created_at,price,deterministic_mode,
                recommended_mode,width_scale,cap_scale,confidence,applied,
                return_1h
            ) VALUES(
                'legacy','SOLUSDT',strftime('%s','now'),12.5,
                'FLAT','UP',1,1,0.8,0,0.125
            );
            """
        )
    AdvisorDecisionStore(str(path))
    with sqlite3.connect(path) as connection:
        fill_columns = {row[1] for row in connection.execute("PRAGMA table_info(ai_fills)")}
        link_columns = {row[1] for row in connection.execute("PRAGMA table_info(ai_order_links)")}
        decision_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(ai_decisions)")
        }
        assert {"order_id", "trade_id", "slippage_quote"} <= fill_columns
        assert {"exchange_order_id", "expected_price"} <= link_columns
        assert {
            "price_text", "return_15m_text", "return_1h_text", "return_4h_text"
        } <= decision_columns
        assert connection.execute(
            "SELECT price_text,return_1h_text FROM ai_decisions WHERE decision_id='legacy'"
        ).fetchone() == ("12.5", "0.125")


def test_legacy_ai_fill_amounts_migrate_to_exact_text(tmp_path):
    path = tmp_path / "legacy-fill.db"
    store = AdvisorDecisionStore(str(path))
    decision = store.record(
        symbol="SOLUSDT", price=100, deterministic_mode="FLAT",
        recommended_mode="UP", width_scale=1, cap_scale=1,
        confidence=.8, applied=True,
    )
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE ai_fills")
        connection.execute(
            """CREATE TABLE ai_fills(
                fill_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL,
                symbol TEXT NOT NULL, side TEXT NOT NULL,
                price REAL NOT NULL, qty REAL NOT NULL,
                fee_quote REAL NOT NULL DEFAULT 0,
                price_text TEXT, qty_text TEXT, fee_quote_text TEXT,
                exit_reason TEXT NOT NULL DEFAULT '', ts INTEGER NOT NULL,
                order_id TEXT, trade_id TEXT, client_order_id TEXT,
                order_list_id TEXT, leg_type TEXT NOT NULL DEFAULT '',
                link_status TEXT NOT NULL DEFAULT 'resolved',
                slippage_quote REAL NOT NULL DEFAULT 0,
                slippage_quote_text TEXT
            )"""
        )
        connection.execute(
            "INSERT INTO ai_fills VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "legacy-fill", decision, "SOLUSDT", "BUY", 0.1, 0.2, 0.0,
                "0.100000000000000001", "0.200000000000000001", "0",
                "", 10, None, None, None, None, "", "resolved", 0.0, "0",
            ),
        )

    AdvisorDecisionStore(str(path))

    with sqlite3.connect(path) as connection:
        affinities = {
            row[1]: row[2] for row in connection.execute(
                "PRAGMA table_info(ai_fills)"
            )
        }
        row = connection.execute(
            "SELECT price,price_text,qty,qty_text,slippage_value_status "
            "FROM ai_fills"
        ).fetchone()
    assert all(
        affinities[column] == "TEXT"
        for column in ("price", "qty", "fee_quote", "slippage_quote")
    )
    assert row == (
        "0.100000000000000001", "0.100000000000000001",
        "0.200000000000000001", "0.200000000000000001",
        "legacy_unverified",
    )


def test_ai_fill_schema_rejects_mismatched_exact_companion(tmp_path):
    path = tmp_path / "ai.db"
    store = AdvisorDecisionStore(str(path))
    decision = store.record(
        symbol="SOLUSDT", price=100, deterministic_mode="FLAT",
        recommended_mode="UP", width_scale=1, cap_scale=1,
        confidence=.8, applied=True,
    )
    with sqlite3.connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT INTO ai_fills(
                    fill_id,decision_id,symbol,side,price,qty,fee_quote,
                    price_text,qty_text,fee_quote_text,exit_reason,ts,
                    slippage_quote,slippage_quote_text,slippage_value_status
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "damaged", decision, "SOLUSDT", "BUY", "1.1", "1", "0",
                    "1.2", "1", "0", "", 1, "0", "0", "exact",
                ),
            )
