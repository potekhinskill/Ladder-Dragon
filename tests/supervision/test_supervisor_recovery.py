import fcntl
import inspect
import os
from pathlib import Path
import subprocess
import sys
import time
import sqlite3
from decimal import Decimal
from types import SimpleNamespace

import pytest
import requests
from ladder_dragon.supervision import runtime as ai_supervisor
def test_supervisor_reconciles_durable_order_before_running(
    tmp_path, monkeypatch
):
    from ladder_dragon.execution.order_recovery import OrderJournal

    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    journal.prepare(
        client_order_id="LDBLAD-recover",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.1",
        price="75",
    )
    monkeypatch.setenv("BOT_ORDER_JOURNAL", str(journal.path))
    monkeypatch.setattr(
        ai_supervisor.TM,
        "_signed_get",
        lambda *_args, **_kwargs: {
            "orderId": 123,
            "status": "NEW",
            "executedQty": "0",
            "cummulativeQuoteQty": "0",
        },
    )

    result = ai_supervisor._pre_running_recovery_gate(
        SimpleNamespace(live=True, testnet=False), ["SOLUSDT"]
    )

    assert result == {
        "checked": 1,
        "protection_checks": 0,
        "blocked": False,
    }
    assert journal.get("LDBLAD-recover").state == "SUBMITTED"


def test_supervisor_blocks_executed_buy_without_protection(
    tmp_path, monkeypatch
):
    from ladder_dragon.execution.order_recovery import OrderJournal

    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    journal.prepare(
        client_order_id="LDBLAD-filled",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.1",
        price="75",
    )
    monkeypatch.setenv("BOT_ORDER_JOURNAL", str(journal.path))
    monkeypatch.setattr(
        ai_supervisor.TM,
        "_signed_get",
        lambda *_args, **_kwargs: {
            "orderId": 124,
            "status": "FILLED",
            "executedQty": "0.1",
            "cummulativeQuoteQty": "7.5",
        },
    )
    halts = []
    monkeypatch.setattr(
        ai_supervisor,
        "_create_manual_halt_once",
        lambda reason, **kwargs: halts.append((reason, kwargs)),
    )

    with pytest.raises(RuntimeError, match="without verified protection"):
        ai_supervisor._pre_running_recovery_gate(
            SimpleNamespace(live=True, testnet=False), ["SOLUSDT"]
        )
    assert halts[0][1]["metadata"] == {
        "gate": "startup_unprotected_fill",
        "symbol": "SOLUSDT",
        "client_order_id": "LDBLAD-filled",
        "exchange_order_id": 124,
    }
    assert "LDBLAD-filled order=124 executed=0.1" in halts[0][0]


def test_public_ip_guard_alert_never_exposes_address(
    tmp_path, monkeypatch
):
    from ladder_dragon.execution.auth_resilience import (
        AuthResilienceState,
        public_ip_fingerprint,
    )

    raw_ip = "203.0.113.92"
    baseline = AuthResilienceState(
        public_ip_sha256=public_ip_fingerprint("203.0.113.91")
    )
    alerts = []

    class Response:
        text = raw_ip

        @staticmethod
        def raise_for_status():
            return None

    monkeypatch.setenv(
        "BINANCE_AUTH_STATE_FILE", str(tmp_path / "auth.json")
    )
    monkeypatch.setenv(
        "BINANCE_PUBLIC_IP_ENDPOINTS",
        "https://one.example.invalid,https://two.example.invalid",
    )
    monkeypatch.setattr(ai_supervisor.requests, "get", lambda *_a, **_k: Response())
    monkeypatch.setattr(
        ai_supervisor, "notify",
        lambda *args, **kwargs: alerts.append((args, kwargs)),
    )

    with pytest.raises(RuntimeError, match="whitelist review"):
        ai_supervisor._observe_public_ip(baseline)

    persisted = (tmp_path / "auth.json").read_text()
    assert raw_ip not in persisted
    assert raw_ip not in str(alerts)


def test_public_ip_guard_disagreement_cannot_create_false_block(
    monkeypatch
):
    from ladder_dragon.execution.auth_resilience import (
        AuthResilienceState,
        public_ip_fingerprint,
    )

    baseline = AuthResilienceState(
        public_ip_sha256=public_ip_fingerprint("203.0.113.90")
    )

    class Response:
        def __init__(self, text):
            self.text = text

        @staticmethod
        def raise_for_status():
            return None

    monkeypatch.setenv(
        "BINANCE_PUBLIC_IP_ENDPOINTS",
        "https://one.example.invalid,https://two.example.invalid",
    )
    monkeypatch.setattr(
        ai_supervisor.requests,
        "get",
        lambda url, **_kwargs: Response(
            "203.0.113.91" if "one." in url else "203.0.113.92"
        ),
    )
    monkeypatch.setattr(
        ai_supervisor, "_save_auth_resilience_state",
        lambda _state: pytest.fail("disagreement was persisted"),
    )
    monkeypatch.setattr(
        ai_supervisor, "notify",
        lambda *_args, **_kwargs: pytest.fail("false change alert sent"),
    )

    assert ai_supervisor._observe_public_ip(baseline) == baseline


def _protected_oco_journal(tmp_path):
    from ladder_dragon.execution.order_recovery import OrderJournal

    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    buy = journal.prepare(
        client_order_id="LDBLAD-protected",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.1",
        price="75",
    )
    journal.record_exchange_order(
        buy.client_order_id,
        {
            "orderId": 124,
            "status": "FILLED",
            "executedQty": "0.1",
            "cummulativeQuoteQty": "7.5",
        },
    )
    protection = journal.prepare(
        client_order_id="LDSOCO-protected",
        parent_client_order_id=buy.client_order_id,
        symbol="SOLUSDT",
        side="SELL",
        purpose="oco",
        order_type="OCO",
        quantity="0.1",
        price="76",
    )
    journal.mark_protected(
        parent_client_order_id=buy.client_order_id,
        protection_client_order_id=protection.client_order_id,
        order_list_id=700,
    )
    return journal, buy, protection


def test_supervisor_verifies_both_oco_legs_before_running(
    tmp_path, monkeypatch
):
    journal, _buy, protection = _protected_oco_journal(tmp_path)
    monkeypatch.setenv("BOT_ORDER_JOURNAL", str(journal.path))

    def signed_get(path, params):
        if path == "/api/v3/orderList":
            return {
                "orderListId": 700,
                "listClientOrderId": protection.client_order_id,
                "contingencyType": "OCO",
                "listStatusType": "EXEC_STARTED",
                "orders": [
                    {"orderId": 701, "symbol": "SOLUSDT"},
                    {"orderId": 702, "symbol": "SOLUSDT"},
                ],
            }
        order_id = int(params["orderId"])
        return {
            "orderId": order_id,
            "orderListId": 700,
            "symbol": "SOLUSDT",
            "side": "SELL",
            "type": "LIMIT_MAKER" if order_id == 701 else "STOP_LOSS_LIMIT",
            "status": "NEW",
        }

    monkeypatch.setattr(ai_supervisor.TM, "_signed_get", signed_get)

    result = ai_supervisor._pre_running_recovery_gate(
        SimpleNamespace(live=True, testnet=False), ["SOLUSDT"]
    )

    assert result["protection_checks"] == 3
    metadata = journal.get(protection.client_order_id).metadata
    assert {row["order_id"] for row in metadata["verified_legs"]} == {
        701, 702
    }


def test_supervisor_verifies_filled_otoco_and_both_active_sell_legs(
    tmp_path,
    monkeypatch,
):
    from ladder_dragon.execution.order_recovery import OrderJournal

    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    journal.prepare(
        client_order_id="BUY-OTOCO",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="OTOCO_WORKING",
        quantity="0.1",
        price="75",
    )
    journal.record_exchange_order(
        "BUY-OTOCO",
        {
            "orderId": 800,
            "status": "FILLED",
            "executedQty": "0.1",
            "cummulativeQuoteQty": "7.5",
        },
    )
    journal.prepare(
        client_order_id="LIST-OTOCO",
        parent_client_order_id="BUY-OTOCO",
        symbol="SOLUSDT",
        side="SELL",
        purpose="otoco",
        order_type="OTOCO",
        quantity="0.1",
        price="76",
    )
    journal.mark_protected(
        parent_client_order_id="BUY-OTOCO",
        protection_client_order_id="LIST-OTOCO",
        order_list_id=900,
    )
    monkeypatch.setenv("BOT_ORDER_JOURNAL", str(journal.path))

    def signed_get(path, params):
        if path == "/api/v3/orderList":
            return {
                "orderListId": 900,
                "listClientOrderId": "LIST-OTOCO",
                "contingencyType": "OTOCO",
                "listStatusType": "EXEC_STARTED",
                "orders": [
                    {"orderId": 800, "symbol": "SOLUSDT"},
                    {"orderId": 801, "symbol": "SOLUSDT"},
                    {"orderId": 802, "symbol": "SOLUSDT"},
                ],
            }
        order_id = int(params["orderId"])
        if order_id == 800:
            return {
                "orderId": 800,
                "orderListId": 900,
                "clientOrderId": "BUY-OTOCO",
                "symbol": "SOLUSDT",
                "side": "BUY",
                "type": "LIMIT",
                "status": "FILLED",
            }
        return {
            "orderId": order_id,
            "orderListId": 900,
            "clientOrderId": (
                "TP-OTOCO" if order_id == 801 else "SL-OTOCO"
            ),
            "symbol": "SOLUSDT",
            "side": "SELL",
            "type": (
                "LIMIT_MAKER"
                if order_id == 801
                else "STOP_LOSS_LIMIT"
            ),
            "status": "NEW",
        }

    monkeypatch.setattr(ai_supervisor.TM, "_signed_get", signed_get)

    result = ai_supervisor._pre_running_recovery_gate(
        SimpleNamespace(live=True, testnet=False),
        ["SOLUSDT"],
    )

    assert result["protection_checks"] == 3
    protection = journal.get("LIST-OTOCO")
    assert {
        row["order_id"]
        for row in protection.metadata["verified_legs"]
    } == {801, 802}


def test_supervisor_blocks_terminal_oco_leg(
    tmp_path, monkeypatch
):
    journal, _buy, _protection = _protected_oco_journal(tmp_path)
    monkeypatch.setenv("BOT_ORDER_JOURNAL", str(journal.path))

    def signed_get(path, params):
        if path == "/api/v3/orderList":
            return {
                "orderListId": 700,
                "listClientOrderId": "LDSOCO-protected",
                "contingencyType": "OCO",
                "listStatusType": "EXEC_STARTED",
                "orders": [
                    {"orderId": 701, "symbol": "SOLUSDT"},
                    {"orderId": 702, "symbol": "SOLUSDT"},
                ],
            }
        order_id = int(params["orderId"])
        return {
            "orderId": order_id,
            "orderListId": 700,
            "symbol": "SOLUSDT",
            "side": "SELL",
            "type": "LIMIT_MAKER" if order_id == 701 else "STOP_LOSS_LIMIT",
            "status": "CANCELED" if order_id == 702 else "NEW",
        }

    monkeypatch.setattr(ai_supervisor.TM, "_signed_get", signed_get)
    halts = []
    monkeypatch.setattr(
        ai_supervisor,
        "_create_manual_halt_once",
        lambda reason, **kwargs: halts.append((reason, kwargs)),
    )

    with pytest.raises(RuntimeError, match="journal protected BUY differs"):
        ai_supervisor._pre_running_recovery_gate(
            SimpleNamespace(live=True, testnet=False), ["SOLUSDT"]
        )
    assert len(halts) == 1
    assert halts[0][1]["metadata"]["gate"] == (
        "startup_journal_exchange_protection"
    )


def test_supervisor_closes_offline_filled_oco_before_running(
    tmp_path,
    monkeypatch,
):
    journal, buy, protection = _protected_oco_journal(tmp_path)
    monkeypatch.setenv("BOT_ORDER_JOURNAL", str(journal.path))

    def signed_get(path, params):
        if path == "/api/v3/orderList":
            return {
                "orderListId": 700,
                "listClientOrderId": protection.client_order_id,
                "contingencyType": "OCO",
                "listStatusType": "ALL_DONE",
                "orders": [
                    {"orderId": 701, "symbol": "SOLUSDT"},
                    {"orderId": 702, "symbol": "SOLUSDT"},
                ],
            }
        order_id = int(params["orderId"])
        return {
            "orderId": order_id,
            "orderListId": 700,
            "symbol": "SOLUSDT",
            "side": "SELL",
            "type": "LIMIT_MAKER" if order_id == 701 else "STOP_LOSS_LIMIT",
            "status": "FILLED" if order_id == 701 else "CANCELED",
            "executedQty": "0.1" if order_id == 701 else "0",
        }

    monkeypatch.setattr(ai_supervisor.TM, "_signed_get", signed_get)

    result = ai_supervisor._pre_running_recovery_gate(
        SimpleNamespace(live=True, testnet=False),
        ["SOLUSDT"],
    )

    assert result["protection_checks"] == 0
    assert journal.get(buy.client_order_id).state == "CLOSED"
    assert journal.get(protection.client_order_id).state == "CLOSED"
    assert journal.get(protection.client_order_id).metadata[
        "exit_reason"
    ] == "TP"


def test_runtime_protection_mismatch_creates_manual_halt(
    tmp_path, monkeypatch
):
    from ladder_dragon.execution.order_recovery import OrderJournal

    journal = OrderJournal(tmp_path / "orders.sqlite3", venue="mainnet")
    monkeypatch.setenv("BOT_ORDER_JOURNAL", str(journal.path))
    monkeypatch.setattr(ai_supervisor.TM, "BASE_URL", "https://api.binance.com")
    monkeypatch.setattr(
        ai_supervisor,
        "_verify_all_live_protection",
        lambda *_args: (_ for _ in ()).throw(
            RuntimeError("OCO is not actively protecting inventory")
        ),
    )
    halts = []
    monkeypatch.setattr(
        ai_supervisor,
        "_create_manual_halt_once",
        lambda reason, **kwargs: halts.append((reason, kwargs)),
    )

    with pytest.raises(RuntimeError, match="journal protected BUY differs"):
        ai_supervisor._runtime_protection_gate(
            ["SOLUSDT"], SimpleNamespace()
        )

    assert len(halts) == 1
    assert halts[0][1]["metadata"]["gate"] == (
        "journal_exchange_protection"
    )


def test_legacy_unresolved_fill_schema_remains_execution_blocking(
    tmp_path, monkeypatch
):
    path = tmp_path / "ai.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE ai_unresolved_fills(fill_key TEXT PRIMARY KEY)"
        )
        connection.execute(
            "INSERT INTO ai_unresolved_fills(fill_key) VALUES('fill-1')"
        )
    monkeypatch.setattr(ai_supervisor, "_AI_DECISIONS_PATH", path)
    monkeypatch.setattr(ai_supervisor, "_AI_DECISIONS", None)

    assert ai_supervisor._unresolved_fill_counts() == {
        "total": 1,
        "attribution": 0,
        "inventory": 1,
    }


def test_unresolved_fill_scopes_separate_ai_attribution_from_inventory(
    tmp_path, monkeypatch
):
    path = tmp_path / "ai.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE ai_unresolved_fills("
            "fill_key TEXT PRIMARY KEY,resolution_scope TEXT)"
        )
        connection.executemany(
            "INSERT INTO ai_unresolved_fills VALUES(?,?)",
            (
                ("attr", "ATTRIBUTION"),
                ("inventory", "INVENTORY"),
                ("damaged", "UNKNOWN"),
            ),
        )
    monkeypatch.setattr(ai_supervisor, "_AI_DECISIONS_PATH", path)

    assert ai_supervisor._unresolved_fill_counts() == {
        "total": 3,
        "attribution": 1,
        "inventory": 2,
    }


def test_blocked_shadow_is_rate_limited_and_never_enables_execution(
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(ai_supervisor, "_AI_ADVISOR", object())
    monkeypatch.setattr(
        ai_supervisor, "_AI_POLICY", SimpleNamespace(mode="SHADOW")
    )
    monkeypatch.setattr(
        ai_supervisor,
        "run_for_symbol",
        lambda symbol, args, *, execution_allowed: calls.append(
            (symbol, execution_allowed)
        ),
    )
    monkeypatch.setattr(
        ai_supervisor, "_BLOCKED_SHADOW_LAST_ATTEMPT", {}
    )
    monkeypatch.setenv("AI_BLOCKED_SHADOW_INTERVAL_SEC", "60")

    ai_supervisor._collect_blocked_shadow(
        ["SOLUSDT"], SimpleNamespace(), now_monotonic=100
    )
    ai_supervisor._collect_blocked_shadow(
        ["SOLUSDT"], SimpleNamespace(), now_monotonic=120
    )
    ai_supervisor._collect_blocked_shadow(
        ["SOLUSDT"], SimpleNamespace(), now_monotonic=161
    )

    assert calls == [("SOLUSDT", False), ("SOLUSDT", False)]


def test_blocked_shadow_plan_skips_every_order_mutation(monkeypatch):
    parser = ai_supervisor.build_supervisor_parser()
    args = parser.parse_args(
        [
            "--base-script",
            str(Path("bin/autosize_universal.py").resolve()),
            "--symbols",
            "SOLUSDT",
        ]
    )
    ai_supervisor.validate_supervisor_args(parser, args)
    ladder_pct = [item.strip() for item in args.ladder_pct.split(",")]
    args.ladder_pct = tuple(float(item) for item in ladder_pct)
    args.ladder_pct_map = ai_supervisor.parse_ladder_pct_map(
        args.ladder_pct_map
    )
    monkeypatch.setattr(ai_supervisor, "_AI_ADVISOR", None)
    monkeypatch.setattr(ai_supervisor, "_AI_POLICY", None)
    messages = []
    monkeypatch.setattr(ai_supervisor, "log", messages.append)
    monkeypatch.setattr(ai_supervisor, "_INFO_LOG_LAST_EMITTED", {})
    monkeypatch.setattr(ai_supervisor, "get_last_price", lambda _symbol: 100.0)
    monkeypatch.setattr(
        ai_supervisor, "_atr_pct", lambda *_args, **_kwargs: (0.2, 0.002)
    )
    monkeypatch.setattr(
        ai_supervisor,
        "_infer_market_mode",
        lambda *_args, **_kwargs: (
            "UP",
            {
                "ema_fast": 101,
                "ema_slow": 100,
                "slope": 0.001,
                "adx": 30,
                "candidate": "UP",
            },
        ),
    )
    monkeypatch.setattr(
        ai_supervisor,
        "get_exchange_filters_cached",
        lambda _symbol: {
            "tickSize": 0.01,
            "tickSizeExact": "0.01",
        },
    )
    monkeypatch.setattr(
        ai_supervisor,
        "resolve_vwap_params",
        lambda *_args, **_kwargs: (None, None, None, None, None),
    )
    mutations = (
        "startup_cleanup_orders",
        "smart_cleanup_orders",
        "smart_rolling",
        "position_guard_and_maybe_flatten",
        "run_child",
    )
    for name in mutations:
        monkeypatch.setattr(
            ai_supervisor,
            name,
            lambda *_args, _name=name, **_kwargs: pytest.fail(
                f"blocked SHADOW entered {_name}"
            ),
        )
    recorded = []
    monkeypatch.setattr(
        ai_supervisor,
        "_record_prediction_shadow",
        lambda symbol, **kwargs: recorded.append(
            (symbol, kwargs["deterministic_mode"])
        ),
    )

    ai_supervisor.run_for_symbol(
        "SOLUSDT", args, execution_allowed=False
    )
    ai_supervisor.run_for_symbol(
        "SOLUSDT", args, execution_allowed=False
    )

    assert recorded == [("SOLUSDT", "UP"), ("SOLUSDT", "UP")]
    assert not any("ladder ->" in message for message in messages)
    blocked_summaries = [
        message for message in messages
        if message.startswith("[BLOCKED-SHADOW]")
    ]
    assert len(blocked_summaries) == 1
    assert "levels=" in blocked_summaries[0]
    assert "order mutation disabled" in blocked_summaries[0]
    routine_prefixes = (
        "[PLAN]", "[ATR]", "[REGIME-", "[EXPECTANCY-SHADOW]",
        "[EXPECTANCY-CONFIG]", "[ENTRY-ADAPT]",
        "[INVENTORY-SKEW-", "[POS-MODE]",
    )
    for prefix in routine_prefixes:
        assert sum(message.startswith(prefix) for message in messages) <= 1
    for prefix in (
        "[PLAN]", "[ATR]", "[REGIME-", "[ENTRY-ADAPT]",
        "[INVENTORY-SKEW-", "[POS-MODE]",
    ):
        assert sum(message.startswith(prefix) for message in messages) == 1


def test_known_empty_order_snapshot_does_not_repeat_rest_query(monkeypatch):
    messages = []
    monkeypatch.setattr(
        ai_supervisor.TM,
        "_signed_get",
        lambda *_args, **_kwargs: pytest.fail("unexpected REST query"),
    )
    monkeypatch.setattr(ai_supervisor, "log", messages.append)

    assert ai_supervisor._cancel_open_buy_orders([]) == 0
    assert messages == []


def test_stable_risk_info_is_rate_limited(monkeypatch):
    messages = []
    timestamps = iter((100.0, 120.0, 3701.0))
    monkeypatch.setattr(ai_supervisor, "log", messages.append)
    monkeypatch.setattr(
        ai_supervisor.time, "monotonic", lambda: next(timestamps)
    )
    monkeypatch.setattr(ai_supervisor, "_INFO_LOG_LAST_EMITTED", {})

    assert ai_supervisor._log_info_rate_limited("MONKY", "allowlisted")
    assert not ai_supervisor._log_info_rate_limited("MONKY", "allowlisted")
    assert ai_supervisor._log_info_rate_limited("MONKY", "allowlisted")
    assert messages == ["allowlisted", "allowlisted"]


def test_halted_runtime_still_collects_non_executing_shadow_evidence():
    runtime_source = inspect.getsource(ai_supervisor.main)
    collect_at = runtime_source.index("_collect_blocked_shadow(")
    blocked_start = runtime_source.rindex(
        "if risk_buy_blocked:", 0, collect_at
    )
    blocked_end = runtime_source.index(
        "if now_loop >= next_vwap_refresh:", blocked_start
    )
    blocked_branch = runtime_source[blocked_start:blocked_end]

    assert "_collect_blocked_shadow(" in blocked_branch
    assert "execution remains stopped" in blocked_branch.lower()
    assert "last_risk_signature" not in blocked_branch


def test_supervisor_live_waits_while_maintenance_is_active(
    tmp_path, monkeypatch
):
    from ladder_dragon.execution.maintenance_state import MaintenanceState

    states = iter((
        MaintenanceState(
            active=True,
            reason="Operator intentionally stopped trading",
            updated_at_epoch=100,
        ),
        MaintenanceState(),
    ))
    published = []
    sleeps = []
    monkeypatch.setattr(
        ai_supervisor, "load_maintenance_state", lambda _path: next(states)
    )
    monkeypatch.setattr(
        ai_supervisor,
        "_publish_ai_runtime_status",
        lambda **updates: published.append(updates),
    )
    monkeypatch.setattr(
        ai_supervisor.time, "sleep", lambda seconds: sleeps.append(seconds)
    )

    ai_supervisor._wait_for_maintenance_clear(
        SimpleNamespace(live=True),
        SimpleNamespace(halt_file=tmp_path / "halt.json"),
    )

    assert sleeps == [30]
    assert published[0]["state"] == "INTENTIONALLY_STOPPED"
    assert published[0]["risk"]["buy_blocked"] is True
    assert published[-1]["maintenance"]["active"] is False
    runtime_source = inspect.getsource(ai_supervisor.main)
    defer = runtime_source.index(
        "BUY cancellation deferred until "
    )
    cancel = runtime_source.index(
        "_cancel_open_buy_orders(", defer
    )
    assert defer < cancel
    assert "orders or None" not in runtime_source


def test_cleanup_layers_keep_fresh_off_ladder_order(monkeypatch):
    now_ms = int(time.time() * 1000)
    orders = [
        {
            "symbol": "SOLUSDT",
            "orderId": 42,
            "side": "BUY",
            "type": "LIMIT",
            "price": "99.00",
            "updateTime": now_ms - 60_000,
        }
    ]
    canceled = []
    monkeypatch.setenv("START_CLEANUP_OFFLADDER_GRACE_SEC", "900")
    monkeypatch.setenv("CLEANUP_OFFLADDER_GRACE_SEC", "900")
    monkeypatch.setattr(ai_supervisor, "list_open_orders", lambda symbol: orders)
    monkeypatch.setattr(
        ai_supervisor,
        "cancel_order",
        lambda symbol, order_id: canceled.append(order_id) or True,
    )

    result = ai_supervisor.startup_cleanup_orders(
        "SOLUSDT",
        now_price=100.0,
        ladder_prices=[98.0],
        tick_size=0.01,
        grace_sec=900,
    )

    assert result == {"reviewed": 1, "canceled": 0}
    assert canceled == []

    periodic = ai_supervisor.smart_cleanup_orders(
        "SOLUSDT",
        now_price=100.0,
        ladder_prices=[98.0],
        tick_size=0.01,
        near_ttl_sec=900,
        far_ttl_sec=7200,
    )
    assert periodic == {"reviewed": 1, "canceled": 0}
    assert canceled == []


def test_cleanup_layers_never_cancel_protective_sell(monkeypatch):
    now_ms = int(time.time() * 1000)
    protective_orders = [
        {
            "symbol": "SOLUSDT",
            "orderId": 501,
            "orderListId": 900,
            "side": "SELL",
            "type": "STOP_LOSS_LIMIT",
            "price": "70.00",
            "stopPrice": "70.10",
            "updateTime": now_ms - 86_400_000,
        },
        {
            "symbol": "SOLUSDT",
            "orderId": 502,
            "orderListId": 900,
            "side": "SELL",
            "type": "LIMIT_MAKER",
            "price": "80.00",
            "updateTime": now_ms - 86_400_000,
        },
    ]
    canceled = []
    monkeypatch.setattr(
        ai_supervisor, "list_open_orders", lambda _symbol: protective_orders
    )
    monkeypatch.setattr(
        ai_supervisor,
        "cancel_order",
        lambda _symbol, order_id: canceled.append(order_id) or True,
    )

    startup = ai_supervisor.startup_cleanup_orders(
        "SOLUSDT",
        now_price=76.0,
        ladder_prices=[75.0],
        tick_size=0.01,
        grace_sec=1,
    )
    periodic = ai_supervisor.smart_cleanup_orders(
        "SOLUSDT",
        now_price=76.0,
        ladder_prices=[75.0],
        tick_size=0.01,
        near_ttl_sec=1,
        far_ttl_sec=1,
    )

    assert startup == {"reviewed": 2, "canceled": 0}
    assert periodic == {"reviewed": 2, "canceled": 0}
    assert canceled == []


def test_supervisor_deduplicates_ladder_with_exact_tick_formatting(monkeypatch):
    monkeypatch.setattr(ai_supervisor, "PRICE_ROUND_MODE", "nearest")

    prices = ai_supervisor._deduplicate_ladder_prices(
        ["75.124", "75.125", "75.126", "76.001"],
        76.0,
        "0.01",
    )

    assert prices == [75.12, 75.13, 76.0]

def test_startup_cleanup_reports_ttl_distance_and_observed_market(monkeypatch):
    now_ms = int(time.time() * 1000)
    order = {
        "symbol": "SOLUSDT",
        "orderId": 77,
        "side": "BUY",
        "type": "LIMIT",
        "price": "75.00",
        "executedQty": "0",
        "updateTime": now_ms - 901_000,
    }
    messages = []
    monkeypatch.setattr(ai_supervisor, "list_open_orders", lambda symbol: [order])
    monkeypatch.setattr(ai_supervisor, "cancel_order", lambda *args: True)
    monkeypatch.setattr(ai_supervisor, "log", messages.append)
    monkeypatch.setattr(
        ai_supervisor,
        "read_order_observation",
        lambda path, order_id: {
            "market_min_price": "75.40",
            "market_observation_count": 12,
        },
    )

    result = ai_supervisor.startup_cleanup_orders(
        "SOLUSDT",
        now_price=76.0,
        ladder_prices=[75.0],
        tick_size=0.01,
        grace_sec=900,
    )

    assert result == {"reviewed": 1, "canceled": 1}
    lifetime = next(message for message in messages if message.startswith("[ORDER-LIFETIME]"))
    assert '"cancel_reason":"age>900s"' in lifetime
    assert '"ttl_sec":900' in lifetime
    assert '"limit_below_market_pct":"1.3158"' in lifetime
    assert '"minimum_observed_market_price":"75.40"' in lifetime


def test_reconciliation_retries_recent_fill_and_allows_exchange_dust(tmp_path, monkeypatch):
    db_path = tmp_path / "stats.db"
    with sqlite3.connect(db_path) as con:
        con.execute("CREATE TABLE inventory(symbol TEXT PRIMARY KEY, qty REAL NOT NULL)")
        con.execute("INSERT INTO inventory(symbol, qty) VALUES('SOLUSDT', 0.000871)")

    monkeypatch.setenv("BOT_STATS_DB", str(db_path))
    monkeypatch.setenv("RISK_RECONCILE_STRICT", "1")
    monkeypatch.setenv("RISK_RECONCILE_SYNC_FILLS", "0")
    monkeypatch.setenv("RISK_RECONCILE_GRACE_SEC", "0.2")
    monkeypatch.setenv("RISK_RECONCILE_RETRY_SEC", "0.01")
    monkeypatch.setenv("RISK_RECONCILE_DUST_STEPS", "1")
    ai_supervisor._FILTERS_CACHE["SOLUSDT"] = {
        "tickSize": 0.01,
        "stepSize": 0.001,
        "minQty": 0.001,
        "minNotional": 5.0,
    }

    balances = [
        {"SOL": {"free": 0.129742, "locked": 0.0}, "USDT": {"free": 1000.0, "locked": 0.0}},
        {"SOL": {"free": 0.000742, "locked": 0.0}, "USDT": {"free": 1000.0, "locked": 0.0}},
    ]
    monkeypatch.setattr(ai_supervisor, "get_balances_full", lambda: balances.pop(0))
    monkeypatch.setattr(ai_supervisor, "get_last_price", lambda symbol: 77.0)
    monkeypatch.setattr(ai_supervisor.TM, "_signed_get", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        ai_supervisor,
        "load_daily_trade_metrics",
        lambda *args, **kwargs: {
            "daily_turnover_usdt": 0,
            "daily_buy_usdt": 0,
            "daily_trade_count": 0,
            "consecutive_losses": 0,
        },
    )

    limits = ai_supervisor.RiskLimits.from_env()
    snapshot, orders, _ = ai_supervisor._build_risk_snapshot(["SOLUSDT"], limits)

    assert snapshot.exposure_usdt == ai_supervisor.money("0.057134")
    assert orders == []


def test_reconciliation_imports_new_binance_fill_before_risk_gate(tmp_path, monkeypatch):
    db_path = tmp_path / "stats.db"
    con = ai_supervisor.tools_stats.init_db(str(db_path))
    ai_supervisor.tools_stats.apply_trade(
        con, "SOLUSDT", "BUY", 70.0, 5.863,
        ts=1_700_000_000_000, trade_id=100,
        commission_asset="USDT", commission_amount=0,
        commission_quote=0, commission_value_status="exact",
    )
    con.close()

    monkeypatch.setenv("BOT_STATS_DB", str(db_path))
    monkeypatch.setenv("RISK_RECONCILE_STRICT", "1")
    monkeypatch.setenv("RISK_RECONCILE_SYNC_FILLS", "1")
    monkeypatch.setenv("RISK_RECONCILE_GRACE_SEC", "0")
    ai_supervisor._FILTERS_CACHE["SOLUSDT"] = {
        "tickSize": 0.01,
        "stepSize": 0.001,
        "minQty": 0.001,
        "minNotional": 5.0,
    }
    monkeypatch.setattr(
        ai_supervisor,
        "get_balances_full",
        lambda: {
            "SOL": {"free": 3.778, "locked": 0.0},
            "USDT": {"free": 1000.0, "locked": 0.0},
        },
    )
    monkeypatch.setattr(ai_supervisor, "get_last_price", lambda symbol: 75.0)

    def signed(path, params=None):
        if path == "/api/v3/myTrades":
            return [{
                "id": 101,
                "orderId": 17517152455,
                "isBuyer": False,
                "price": "75.0",
                "qty": "2.085",
                "commission": "0",
                "commissionAsset": "USDT",
                "time": 1_700_000_010_000,
            }]
        return []

    monkeypatch.setattr(ai_supervisor.TM, "_signed_get", signed)
    monkeypatch.setattr(
        ai_supervisor,
        "load_daily_trade_metrics",
        lambda *args, **kwargs: {
            "daily_turnover_usdt": 0,
            "daily_buy_usdt": 0,
            "daily_trade_count": 0,
            "consecutive_losses": 0,
        },
    )

    limits = ai_supervisor.RiskLimits.from_env()
    snapshot, orders, _ = ai_supervisor._build_risk_snapshot(["SOLUSDT"], limits)

    assert snapshot.exposure_usdt == ai_supervisor.money("283.35")
    assert orders == []
    with sqlite3.connect(db_path) as check:
        qty = check.execute(
            "SELECT qty_text FROM inventory WHERE symbol='SOLUSDT'"
        ).fetchone()[0]
    assert Decimal(qty) == Decimal("3.778")


def test_reconciliation_fill_import_failure_is_fail_closed(tmp_path, monkeypatch):
    db_path = tmp_path / "stats.db"
    con = ai_supervisor.tools_stats.init_db(str(db_path))
    con.close()
    monkeypatch.setenv("BOT_STATS_DB", str(db_path))

    def unavailable(*args, **kwargs):
        raise RuntimeError("Binance myTrades unavailable")

    monkeypatch.setattr(ai_supervisor.TM, "_signed_get", unavailable)

    with pytest.raises(RuntimeError, match="fresh fill import failed"):
        ai_supervisor._sync_recent_account_fills(["SOLUSDT"])


def test_unvalued_asset_requires_exact_ack_and_is_excluded_from_equity(tmp_path, monkeypatch):
    db_path = tmp_path / "stats.db"
    with sqlite3.connect(db_path) as con:
        con.execute("CREATE TABLE inventory(symbol TEXT PRIMARY KEY, qty REAL NOT NULL)")
        con.execute("INSERT INTO inventory(symbol, qty) VALUES('SOLUSDT', 0.129742)")

    monkeypatch.setenv("BOT_STATS_DB", str(db_path))
    monkeypatch.setenv("RISK_RECONCILE_STRICT", "1")
    monkeypatch.setenv("RISK_RECONCILE_SYNC_FILLS", "0")
    monkeypatch.setenv("RISK_RECONCILE_GRACE_SEC", "0")
    monkeypatch.setenv("RISK_UNVALUED_ASSETS", "MONKY")
    monkeypatch.setenv("RISK_UNVALUED_ASSETS_ACK", "MONKY")
    ai_supervisor._FILTERS_CACHE["SOLUSDT"] = {
        "tickSize": 0.01,
        "stepSize": 0.001,
        "minQty": 0.001,
        "minNotional": 5.0,
    }

    monkeypatch.setattr(
        ai_supervisor,
        "get_balances_full",
        lambda: {
            "SOL": {"free": 0.129742, "locked": 0.0},
            "USDT": {"free": 1000.0, "locked": 0.0},
            "MONKY": {"free": 74339.03, "locked": 0.0},
        },
    )

    def price(symbol):
        if symbol == "SOLUSDT":
            return 77.0
        raise RuntimeError("missing non-tradable pair")

    monkeypatch.setattr(ai_supervisor, "get_last_price", price)
    monkeypatch.setattr(
        ai_supervisor,
        "get_last_price_decimal",
        lambda symbol: Decimal(str(price(symbol))),
    )
    monkeypatch.setattr(ai_supervisor.TM, "_signed_get", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        ai_supervisor,
        "load_daily_trade_metrics",
        lambda *args, **kwargs: {
            "daily_turnover_usdt": 0,
            "daily_buy_usdt": 0,
            "daily_trade_count": 0,
            "consecutive_losses": 0,
        },
    )

    limits = ai_supervisor.RiskLimits.from_env()
    snapshot, orders, _ = ai_supervisor._build_risk_snapshot(["SOLUSDT"], limits)

    assert snapshot.equity_usdt == ai_supervisor.money("1009.990134")
    assert snapshot.exposure_usdt == ai_supervisor.money("9.990134")
    assert orders == []


def test_unvalued_asset_ack_must_match_exactly(monkeypatch):
    monkeypatch.setenv("RISK_UNVALUED_ASSETS", "MONKY")
    monkeypatch.setenv("RISK_UNVALUED_ASSETS_ACK", "OTHER")
    try:
        ai_supervisor._configured_unvalued_assets()
    except RuntimeError as exc:
        assert "exact matching" in str(exc)
    else:
        raise AssertionError("unvalued asset allowlist accepted without exact ACK")


def test_remaining_order_budget_normalizes_legacy_float_telemetry(tmp_path):
    configured = ai_supervisor.RiskLimits.from_mapping({})
    observed = ai_supervisor.RiskSnapshot(
        equity_usdt=794.25,
        exposure_usdt=463.15,
        free_usdt=331.09,
        daily_buy_usdt=0.0,
        correlated_exposure_usdt=463.15,
    )

    remaining = ai_supervisor._remaining_order_budget_decimal(
        configured,
        observed,
    )

    assert remaining == Decimal("31.09")
    assert isinstance(remaining, Decimal)


def test_risk_shock_detector_handles_mixed_valuation_price_types():
    first_reasons, first = ai_supervisor._configured_price_shocks_decimal(
        ["SOLUSDT"],
        {
            "SOLUSDT": 75.0,
            "ETHUSDT": Decimal("1900.00"),
        },
        {},
        "0.05",
    )
    second_reasons, second = ai_supervisor._configured_price_shocks_decimal(
        ["SOLUSDT"],
        {
            "SOLUSDT": Decimal("75.75"),
            "ETHUSDT": Decimal("1710.00"),
        },
        {
            **first,
            "ETHUSDT": Decimal("1900.00"),
        },
        Decimal("0.05"),
    )

    assert first_reasons == []
    assert second_reasons == []
    assert second == {"SOLUSDT": Decimal("75.75")}


def test_risk_shock_detector_reports_configured_symbol_only():
    reasons, normalized = ai_supervisor._configured_price_shocks_decimal(
        ["SOLUSDT"],
        {
            "SOLUSDT": Decimal("70"),
            "ETHUSDT": Decimal("1000"),
        },
        {
            "SOLUSDT": 75.0,
            "ETHUSDT": Decimal("1900"),
        },
        "0.05",
    )

    assert reasons == ["SOLUSDT moved 6.67%"]
    assert normalized == {"SOLUSDT": Decimal("70")}


def test_testnet_uses_separate_stats_and_order_journals(tmp_path, monkeypatch):
    main_stats = tmp_path / "mainnet.db"
    test_stats = tmp_path / "testnet.db"
    main_journal = tmp_path / "mainnet_orders.db"
    test_journal = tmp_path / "testnet_orders.db"
    test_run_dir = tmp_path / "testnet_run"
    main_run_dir = tmp_path / "mainnet_run"
    monkeypatch.setenv("BOT_STATS_DB", str(main_stats))
    monkeypatch.setenv("BOT_TESTNET_STATS_DB", str(test_stats))
    monkeypatch.setenv("BOT_ORDER_JOURNAL", str(main_journal))
    monkeypatch.setenv("BOT_TESTNET_ORDER_JOURNAL", str(test_journal))
    monkeypatch.setenv("BOT_RUN_DIR", str(main_run_dir))
    monkeypatch.setenv("CB_HALT_FILE", str(main_run_dir / "circuit_halt.json"))
    monkeypatch.setenv("CB_STATE_FILE", str(main_run_dir / "risk_state.json"))
    monkeypatch.setenv("CB_ALERTS_FILE", str(main_run_dir / "risk_alerts.ndjson"))
    monkeypatch.setenv("BOT_TESTNET_RUN_DIR", str(test_run_dir))

    ai_supervisor._configure_venue(SimpleNamespace(testnet=True, live=False))

    assert __import__("os").environ["BOT_STATS_DB"] == str(test_stats)
    assert __import__("os").environ["BOT_ORDER_JOURNAL"] == str(test_journal)
    assert __import__("os").environ["BOT_RUN_DIR"] == str(test_run_dir)
    assert __import__("os").environ["CB_HALT_FILE"] == str(test_run_dir / "circuit_halt.json")


def test_unknown_supervisor_flag_is_fatal():
    result = subprocess.run(
        [sys.executable, "-m", "bin.ai_supervisor", "--definitely-unknown"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr


def test_dry_supervisor_refuses_missing_worker_file():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "bin.ai_supervisor",
            "--base-script",
            "definitely-missing-worker.py",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "--base-script does not exist" in result.stderr


def test_live_requires_explicit_confirmation(monkeypatch, tmp_path):
    env = dict(**__import__("os").environ)
    # An explicit empty value prevents python-dotenv from reloading the
    # production confirmation from .env inside the subprocess. Keep every
    # runtime path in the pytest sandbox as an additional fail-closed guard.
    env["BOT_LIVE_CONFIRMED"] = ""
    env["BOT_RUN_DIR"] = str(tmp_path)
    env["BOT_TESTNET_RUN_DIR"] = str(tmp_path / "testnet")
    env["AI_RUNTIME_STATUS_FILE"] = str(tmp_path / "ai_status.json")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "bin.ai_supervisor",
            "--live",
            "--base-script",
            "bin/autosize_universal.py",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert result.returncode == 2
    assert "BOT_LIVE_CONFIRMED=YES" in result.stderr
    assert "Permission denied" not in result.stderr
