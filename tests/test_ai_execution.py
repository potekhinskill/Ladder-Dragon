import sqlite3

from ladder_dragon.ai.ai_context import AdvisorDecisionStore


def test_ai_decision_fills_are_linked_and_evaluated(tmp_path):
    store = AdvisorDecisionStore(str(tmp_path / "ai.db"))
    decision = store.record(symbol="SOLUSDT", price=100, deterministic_mode="FLAT",
                            recommended_mode="UP", width_scale=1, cap_scale=1,
                            confidence=.8, applied=True)
    store.record_fill(decision, symbol="SOLUSDT", side="BUY", price=100, qty=1, fee_quote=.1, ts=10)
    store.record_fill(decision, symbol="SOLUSDT", side="SELL", price=102, qty=1, fee_quote=.1,
                      exit_reason="OCO_TP", ts=70)
    result = store.evaluate_execution(decision, baseline_exit_price=101)
    assert result["net_pnl_quote"] == 1.8
    assert result["holding_duration_sec"] == 60.0
    assert result["opportunity_cost_quote"] < 0


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


def test_realized_result_records_partial_fill_and_exit_metadata(tmp_path):
    store = AdvisorDecisionStore(str(tmp_path / "ai.db"))
    decision = store.record(symbol="SOLUSDT", price=100, deterministic_mode="FLAT",
                            recommended_mode="UP", width_scale=1, cap_scale=1,
                            confidence=.8, applied=True)
    store.record_fill(decision, symbol="SOLUSDT", side="BUY", price=100, qty=1, ts=10)
    store.record_fill(decision, symbol="SOLUSDT", side="SELL", price=101, qty=.5,
                      exit_reason="STOP", slippage_quote=.1, ts=20)
    result = store.evaluate_execution(decision)
    assert result["partial_fill"] is True
    assert result["exit_reason"] == "STOP"
    assert result["slippage_quote"] == .1


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
            """
        )
    AdvisorDecisionStore(str(path))
    with sqlite3.connect(path) as connection:
        fill_columns = {row[1] for row in connection.execute("PRAGMA table_info(ai_fills)")}
        link_columns = {row[1] for row in connection.execute("PRAGMA table_info(ai_order_links)")}
        assert {"order_id", "trade_id", "slippage_quote"} <= fill_columns
        assert {"exchange_order_id", "expected_price"} <= link_columns
