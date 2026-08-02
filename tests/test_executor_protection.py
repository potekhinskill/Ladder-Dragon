from pathlib import Path
from decimal import Decimal

import requests

from ladder_dragon.execution.protection.breakeven import (
    BreakevenRuntime,
    BreakevenStateStore,
    maintain_breakeven,
)
from ladder_dragon.execution.protection.runtime import (
    ProtectionConfig,
    ProtectionDependencies,
    protect_filled_buys,
    emergency_gap_flatten,
)


def dependencies(**overrides):
    values = {
        "logger": lambda message: None,
        "debugger": lambda message: None,
        "journal": lambda: None,
        "get_order": lambda symbol, order_id: None,
        "recover_existing_protection": lambda client_id: False,
        "poll_trades": lambda symbol: None,
        "pick_oco_prices": lambda symbol, ladder, fill, offset: (
            110.0,
            95.0,
            94.0,
        ),
        "average_entry": lambda symbol, ttl, lookback: None,
        "profit_floor_pct": lambda: 0.01,
        "pull_filters": lambda symbol: None,
        "get_symbol_assets": lambda symbol: ("SOL", "USDT"),
        "get_balances": lambda: {
            "SOL": {"free": 1.0, "locked": 0.0}
        },
        "round_price": lambda symbol, value: round(value, 2),
        "round_quantity": lambda symbol, value: round(value, 3),
        "min_quantity": lambda symbol, hint: 0.001,
        "min_notional": lambda symbol, price: 5.0,
        "format_price": lambda symbol, value: f"{value:.2f}",
        "format_quantity": lambda symbol, value: f"{value:.3f}",
        "halt": lambda reason, **metadata: None,
        "place_oco_sell": lambda *args, **kwargs: None,
        "place_limit_order": lambda *args, **kwargs: None,
        "list_open_orders": lambda symbol: [],
        "tick_size": lambda symbol: 0.01,
        "price_eps_mult": lambda: 1.0,
        "round_step": lambda value, step, mode: round(value, 2),
        "cancel_oco": lambda symbol, order_list_id: None,
        "sleep": lambda seconds: None,
        "now": lambda: 1_700_000_000.0,
    }
    values.update(overrides)
    return ProtectionDependencies(**values)


def config() -> ProtectionConfig:
    return ProtectionConfig(
        stop_limit_offset_pct=0.0015,
        oco_fallback="prefer-tp1",
        sell_limit_maker=False,
        avg_cache_ttl=30,
        avg_lookback=1000,
        panic_sell_floor_pct=None,
    )


def state_store(tmp_path: Path) -> BreakevenStateStore:
    return BreakevenStateStore(
        run_dir=lambda: str(tmp_path),
        debugger=lambda message: None,
    )


def test_filled_buy_gets_verified_oco_and_leaves_watch_list(tmp_path):
    placed = []
    polls = []
    lot_lookups = []

    def place_oco(*args, **kwargs):
        placed.append((args, kwargs))
        return {"orderListId": 77}

    def lot_id_for_fill(symbol, fill_price, order_id):
        lot_lookups.append((symbol, fill_price, order_id))
        return 91

    deps = dependencies(
        get_order=lambda symbol, order_id: {
            "orderId": order_id,
            "status": "FILLED",
            "executedQty": "0.100",
            "cummulativeQuoteQty": "10.0",
        },
        poll_trades=lambda symbol: polls.append(symbol),
        place_oco_sell=place_oco,
        lot_id_for_fill=lot_id_for_fill,
    )
    store = state_store(tmp_path)

    remaining = protect_filled_buys(
        "SOLUSDT",
        [42],
        [90.0, 110.0],
        config=config(),
        panic_active=False,
        breakeven_enabled=True,
        state_store=store,
        dependencies=deps,
    )

    assert remaining == []
    assert placed[0][0][:5] == (
        "SOLUSDT",
        Decimal("0.1"),
        Decimal("110.0"),
        Decimal("95.0"),
        Decimal("94.0"),
    )
    assert polls == ["SOLUSDT"]
    assert lot_lookups == [("SOLUSDT", Decimal("100"), 42)]
    assert placed[0][1]["lot_id"] == 91
    assert store.load("SOLUSDT")["77"]["fill_price"] == "100"


def test_protection_reuses_one_authoritative_balance_snapshot(tmp_path):
    balance_reads = []
    observed_positions = []
    deps = dependencies(
        get_order=lambda symbol, order_id: {
            "orderId": order_id,
            "status": "FILLED",
            "executedQty": "0.100",
            "cummulativeQuoteQty": "10.0",
        },
        get_balances=lambda: (
            balance_reads.append(True)
            or {"SOL": {"free": "0.100", "locked": "0.025"}}
        ),
        average_entry_for_position=(
            lambda symbol, position, ttl, lookback: (
                observed_positions.append(position) or Decimal("99")
            )
        ),
        place_oco_sell=lambda *args, **kwargs: {"orderListId": 77},
    )

    remaining = protect_filled_buys(
        "SOLUSDT",
        [42],
        [90.0, 110.0],
        config=config(),
        panic_active=False,
        breakeven_enabled=False,
        state_store=state_store(tmp_path),
        dependencies=deps,
    )

    assert remaining == []
    assert len(balance_reads) == 1
    assert observed_positions == [Decimal("0.125")]


def test_terminal_partial_exit_reprotects_only_confirmed_residual(tmp_path):
    placed = []

    class Journal:
        def get_by_exchange_order_id(self, _order_id):
            return type("Intent", (), {"client_order_id": "BUY-parent"})()

        def record_exchange_order(self, *_args):
            return None

        def partial_protection_exit_quantity(self, parent_client_order_id):
            assert parent_client_order_id == "BUY-parent"
            return Decimal("0.040")

    deps = dependencies(
        journal=lambda: Journal(),
        get_order=lambda symbol, order_id: {
            "orderId": order_id,
            "status": "FILLED",
            "executedQty": "0.100",
            "cummulativeQuoteQty": "10.0",
        },
        recover_existing_protection=lambda client_id: False,
        get_balances=lambda: {"SOL": {"free": "0.060", "locked": "0"}},
        place_oco_sell=lambda *args, **kwargs: (
            placed.append((args, kwargs)) or {"orderListId": 77}
        ),
    )

    remaining = protect_filled_buys(
        "SOLUSDT",
        [42],
        [90.0, 110.0],
        config=config(),
        panic_active=False,
        breakeven_enabled=False,
        state_store=state_store(tmp_path),
        dependencies=deps,
    )

    assert remaining == []
    assert placed[0][0][1] == Decimal("0.06")


def test_terminal_zero_fill_buy_leaves_protection_watch_list(tmp_path):
    logs = []
    terminal_unfilled = set()
    deps = dependencies(
        logger=logs.append,
        get_order=lambda symbol, order_id: {
            "orderId": order_id,
            "status": "CANCELED",
            "executedQty": "0.00000000",
            "cummulativeQuoteQty": "0.00000000",
        },
        place_oco_sell=lambda *args, **kwargs: pytest.fail(
            "zero-fill cancellation must not create OCO"
        ),
    )

    remaining = protect_filled_buys(
        "SOLUSDT",
        [42],
        [90.0, 110.0],
        config=config(),
        panic_active=False,
        breakeven_enabled=False,
        state_store=state_store(tmp_path),
        dependencies=deps,
        terminal_unfilled_order_ids=terminal_unfilled,
    )

    assert remaining == []
    assert terminal_unfilled == {42}
    assert any("OCO not needed" in message for message in logs)


def test_invalid_terminal_executed_quantity_fails_closed(tmp_path):
    halts = []
    terminal_unfilled = set()
    deps = dependencies(
        get_order=lambda symbol, order_id: {
            "orderId": order_id,
            "status": "CANCELED",
            "executedQty": "not-a-number",
        },
        halt=lambda reason, **metadata: halts.append((reason, metadata)),
    )

    remaining = protect_filled_buys(
        "SOLUSDT",
        [42],
        [90.0, 110.0],
        config=config(),
        panic_active=False,
        breakeven_enabled=False,
        state_store=state_store(tmp_path),
        dependencies=deps,
        terminal_unfilled_order_ids=terminal_unfilled,
    )

    assert remaining == [42]
    assert terminal_unfilled == set()
    assert "invalid executed quantity" in halts[0][0]


def test_failed_oco_uses_single_tp_fallback(tmp_path, monkeypatch):
    # Keep this non-LIVE branch independent from the host service environment.
    monkeypatch.delenv("BOT_LIVE_CONFIRMED", raising=False)
    fallbacks = []
    halts = []

    def place_limit(*args, **kwargs):
        fallbacks.append((args, kwargs))
        return {"orderId": 88, "clientOrderId": "fallback"}

    deps = dependencies(
        get_order=lambda symbol, order_id: {
            "orderId": order_id,
            "status": "FILLED",
            "executedQty": "0.100",
            "cummulativeQuoteQty": "10.0",
        },
        place_limit_order=place_limit,
        halt=lambda reason, **metadata: halts.append(reason),
    )

    remaining = protect_filled_buys(
        "SOLUSDT",
        [42],
        [90.0, 110.0],
        config=config(),
        panic_active=False,
        breakeven_enabled=False,
        state_store=state_store(tmp_path),
        dependencies=deps,
    )

    assert remaining == []
    assert fallbacks[0][0][:4] == (
        "SELL", "SOLUSDT", Decimal("0.1"), Decimal("110.0")
    )
    assert halts == []


def test_live_failed_oco_flattens_and_halts(tmp_path, monkeypatch):
    monkeypatch.setenv("BOT_LIVE_CONFIRMED", "YES")
    flattened, halts = [], []
    live_config = ProtectionConfig(
        stop_limit_offset_pct=0.0015,
        oco_fallback="halt",
        sell_limit_maker=False,
        avg_cache_ttl=30,
        avg_lookback=1000,
        panic_sell_floor_pct=None,
    )
    deps = dependencies(
        get_order=lambda symbol, order_id: {"orderId": order_id, "status": "FILLED",
                                             "executedQty": "0.100", "cummulativeQuoteQty": "10.0"},
        place_market_order=lambda *args, **kwargs: (
            flattened.append((args, kwargs))
            or {"orderId": 90, "status": "FILLED", "executedQty": "0.100"}
        ),
        halt=lambda reason, **metadata: halts.append(reason),
    )
    remaining = protect_filled_buys("SOLUSDT", [42], [90.0, 110.0], config=live_config,
                                    panic_active=False, breakeven_enabled=False,
                                    state_store=state_store(tmp_path), dependencies=deps)
    assert remaining == []
    assert flattened[0][0][:3] == ("SOLUSDT", "SELL", Decimal("0.1"))
    assert "emergency MARKET flatten confirmed" in halts[0]


def test_live_failed_oco_reports_incomplete_market_flatten(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("BOT_LIVE_CONFIRMED", "YES")
    halts = []
    deps = dependencies(
        get_order=lambda symbol, order_id: {
            "orderId": order_id,
            "status": "FILLED",
            "executedQty": "0.100",
            "cummulativeQuoteQty": "10.0",
        },
        place_market_order=lambda *args, **kwargs: {
            "orderId": 90,
            "status": "PARTIALLY_FILLED",
            "executedQty": "0.040",
        },
        halt=lambda reason, **metadata: halts.append(reason),
    )

    protect_filled_buys(
        "SOLUSDT",
        [42],
        [90.0, 110.0],
        config=config(),
        panic_active=False,
        breakeven_enabled=False,
        state_store=state_store(tmp_path),
        dependencies=deps,
    )

    assert "emergency MARKET flatten not fully confirmed" in halts[0]
    assert "expected=0.100 executed=0.040" in halts[0]


def test_live_failed_oco_catches_market_transport_error(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("BOT_LIVE_CONFIRMED", "YES")
    halts = []
    deps = dependencies(
        get_order=lambda symbol, order_id: {
            "orderId": order_id,
            "status": "FILLED",
            "executedQty": "0.100",
            "cummulativeQuoteQty": "10.0",
        },
        place_market_order=lambda *args, **kwargs: (
            _ for _ in ()
        ).throw(requests.ConnectionError("network unavailable")),
        halt=lambda reason, **metadata: halts.append(reason),
    )

    protect_filled_buys(
        "SOLUSDT",
        [42],
        [90.0, 110.0],
        config=config(),
        panic_active=False,
        breakeven_enabled=False,
        state_store=state_store(tmp_path),
        dependencies=deps,
    )

    assert "emergency MARKET flatten not fully confirmed" in halts[0]
    assert "error=ConnectionError" in halts[0]


def test_crossed_oco_relationship_flattens_before_post_and_closes_parent(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("BOT_LIVE_CONFIRMED", "YES")
    halts, polls, closed, metadata = [], [], [], []

    class Journal:
        def get_by_exchange_order_id(self, _order_id):
            return type("Intent", (), {"client_order_id": "BUY-parent"})()

        def update_metadata(self, client_id, values):
            metadata.append((client_id, values))

        def mark_closed(self, client_id):
            closed.append(client_id)

        def record_exchange_order(self, *_args):
            return None

    deps = dependencies(
        journal=lambda: Journal(),
        get_order=lambda symbol, order_id: {
            "orderId": order_id,
            "status": "FILLED",
            "executedQty": "0.100",
            "cummulativeQuoteQty": "10.0",
        },
        market_price=lambda _symbol: Decimal("94.99"),
        place_oco_sell=lambda *_args, **_kwargs: (
            (_ for _ in ()).throw(AssertionError("crossed OCO must not POST"))
        ),
        place_market_order=lambda *_args, **_kwargs: {
            "orderId": 91,
            "status": "FILLED",
            "executedQty": "0.100",
        },
        poll_trades=lambda symbol: polls.append(symbol),
        halt=lambda reason, **_metadata: halts.append(reason),
    )

    remaining = protect_filled_buys(
        "SOLUSDT",
        [42],
        [90.0, 110.0],
        config=config(),
        panic_active=False,
        breakeven_enabled=False,
        state_store=state_store(tmp_path),
        dependencies=deps,
    )

    assert remaining == []
    assert closed == ["BUY-parent"]
    assert metadata[0][1]["emergency_exit"] is True
    assert metadata[0][1]["exit_order_id"] == 91
    assert polls == ["SOLUSDT"]
    assert "fresh market crossed planned OCO relationship" in halts[0]
    assert "emergency MARKET flatten confirmed" in halts[0]


def test_crossed_oco_relationship_keeps_parent_open_when_flatten_partial(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("BOT_LIVE_CONFIRMED", "YES")
    halts, closed = [], []

    class Journal:
        def get_by_exchange_order_id(self, _order_id):
            return type("Intent", (), {"client_order_id": "BUY-parent"})()

        def update_metadata(self, *_args):
            raise AssertionError("partial flatten must not close metadata")

        def mark_closed(self, client_id):
            closed.append(client_id)

        def record_exchange_order(self, *_args):
            return None

    deps = dependencies(
        journal=lambda: Journal(),
        get_order=lambda symbol, order_id: {
            "orderId": order_id,
            "status": "FILLED",
            "executedQty": "0.100",
            "cummulativeQuoteQty": "10.0",
        },
        market_price=lambda _symbol: Decimal("95.00"),
        place_market_order=lambda *_args, **_kwargs: {
            "orderId": 91,
            "status": "PARTIALLY_FILLED",
            "executedQty": "0.040",
        },
        halt=lambda reason, **_metadata: halts.append(reason),
    )

    remaining = protect_filled_buys(
        "SOLUSDT",
        [42],
        [90.0, 110.0],
        config=config(),
        panic_active=False,
        breakeven_enabled=False,
        state_store=state_store(tmp_path),
        dependencies=deps,
    )

    assert remaining == [42]
    assert closed == []
    assert "not fully confirmed" in halts[0]


def test_protection_uses_full_step_aligned_fill_and_tp_ceil(tmp_path):
    placed = []
    deps = dependencies(
        get_order=lambda symbol, order_id: {
            "orderId": order_id,
            "status": "FILLED",
            "executedQty": "0.100",
            "cummulativeQuoteQty": "10.0",
        },
        pick_oco_prices=lambda *args: ("110.09", "95.04", "94.94"),
        pull_filters=lambda symbol: {
            "tickSizeExact": "0.1",
            "stepSizeExact": "0.001",
            "minQtyExact": "0.001",
            "minNotionalExact": "5",
        },
        get_balances=lambda: {
            "SOL": {"free": "0.100", "locked": "0"}
        },
        place_oco_sell=lambda *args, **kwargs: (
            placed.append((args, kwargs)) or {"orderListId": 77}
        ),
    )

    remaining = protect_filled_buys(
        "SOLUSDT",
        [42],
        [90.0, 110.09],
        config=config(),
        panic_active=False,
        breakeven_enabled=False,
        state_store=state_store(tmp_path),
        dependencies=deps,
    )

    assert remaining == []
    assert placed[0][0][:5] == (
        "SOLUSDT",
            Decimal("0.100"),
            Decimal("110.1"),
            Decimal("95.1"),
            Decimal("94.9"),
        )


def test_breakeven_rearms_partially_filled_oco(tmp_path):
    canceled = []
    replacements = []
    logs = []
    store = state_store(tmp_path)
    store.save(
        "SOLUSDT",
        {"77": {"fill_price": 100.0, "tp_price": 110.0, "ts": 1.0}},
    )
    open_orders = [
        {
            "side": "SELL",
            "orderListId": 77,
            "type": "LIMIT_MAKER",
            "origQty": "1.0",
            "executedQty": "0.4",
            "price": "110.0",
        },
        {
            "side": "SELL",
            "orderListId": 77,
            "type": "STOP_LOSS_LIMIT",
            "stopPrice": "95.0",
        },
    ]

    def replacement(*args, **kwargs):
        replacements.append((args, kwargs))
        return {"orderListId": 78}

    responses = iter((open_orders, []))
    deps = dependencies(
        logger=logs.append,
        list_open_orders=lambda symbol: next(responses),
        cancel_oco=lambda symbol, order_list_id: canceled.append(
            (symbol, order_list_id)
        ),
        place_oco_sell=replacement,
    )

    maintain_breakeven(
        "SOLUSDT",
        offset_pct=0.001,
        stop_limit_offset_pct=0.0015,
        state_store=store,
        dependencies=deps,
    )

    assert canceled == [("SOLUSDT", 77)]
    assert replacements[0][0][0:3] == (
        "SOLUSDT", Decimal("0.6"), Decimal("110.0")
    )
    assert "77" not in store.load("SOLUSDT")
    assert store.load("SOLUSDT")["78"]["fill_price"] == "100.0"
    assert any("OCO re-arm" in line for line in logs)


def test_breakeven_cancel_unknown_halts_without_replacement(tmp_path):
    replacements, halts = [], []
    store = state_store(tmp_path)
    store.save(
        "SOLUSDT",
        {"77": {"fill_price": 100.0, "tp_price": 110.0, "ts": 1.0}},
    )
    open_orders = [
        {
            "side": "SELL",
            "orderListId": 77,
            "type": "LIMIT_MAKER",
            "origQty": "1.0",
            "executedQty": "0.4",
            "price": "110.0",
        },
        {
            "side": "SELL",
            "orderListId": 77,
            "type": "STOP_LOSS_LIMIT",
            "stopPrice": "95.0",
        },
    ]
    deps = dependencies(
        list_open_orders=lambda symbol: open_orders,
        cancel_oco=lambda *args: (_ for _ in ()).throw(
            requests.ConnectionError("cancel ACK lost")
        ),
        place_oco_sell=lambda *args, **kwargs: replacements.append(args),
        halt=lambda reason, **metadata: halts.append((reason, metadata)),
    )

    maintain_breakeven(
        "SOLUSDT",
        offset_pct=0.001,
        stop_limit_offset_pct=0.0015,
        state_store=store,
        dependencies=deps,
    )

    assert replacements == []
    assert "old list remains open" in halts[0][0]
    assert "77" in store.load("SOLUSDT")


def test_breakeven_cancel_error_reconciles_absent_old_oco(tmp_path):
    replacements = []
    store = state_store(tmp_path)
    store.save(
        "SOLUSDT",
        {"77": {"fill_price": 100.0, "tp_price": 110.0, "ts": 1.0}},
    )
    initial = [
        {
            "side": "SELL",
            "orderListId": 77,
            "type": "LIMIT_MAKER",
            "origQty": "1.0",
            "executedQty": "0.4",
            "price": "110.0",
        },
        {
            "side": "SELL",
            "orderListId": 77,
            "type": "STOP_LOSS_LIMIT",
            "stopPrice": "95.0",
        },
    ]
    responses = iter((initial, []))
    deps = dependencies(
        list_open_orders=lambda symbol: next(responses),
        cancel_oco=lambda *args: (_ for _ in ()).throw(
            requests.ConnectionError("cancel ACK lost")
        ),
        place_oco_sell=lambda *args, **kwargs: (
            replacements.append(args) or {"orderListId": 78}
        ),
    )

    maintain_breakeven(
        "SOLUSDT",
        offset_pct=0.001,
        stop_limit_offset_pct=0.0015,
        state_store=store,
        dependencies=deps,
    )

    assert replacements[0][0:3] == (
        "SOLUSDT", Decimal("0.6"), Decimal("110.0")
    )
    assert "78" in store.load("SOLUSDT")


def test_breakeven_successful_cancel_requires_absent_old_oco(tmp_path):
    halts, replacements = [], []
    store = state_store(tmp_path)
    store.save("SOLUSDT", {"77": {"fill_price": 100.0}})
    open_orders = [
        {
            "side": "SELL", "orderListId": 77, "type": "LIMIT_MAKER",
            "origQty": "1", "executedQty": "0.4", "price": "110",
        },
        {
            "side": "SELL", "orderListId": 77,
            "type": "STOP_LOSS_LIMIT", "stopPrice": "95",
        },
    ]
    deps = dependencies(
        list_open_orders=lambda symbol: open_orders,
        place_oco_sell=lambda *args: replacements.append(args),
        halt=lambda reason, **metadata: halts.append((reason, metadata)),
    )

    maintain_breakeven(
        "SOLUSDT", offset_pct=0.001, stop_limit_offset_pct=0.0015,
        state_store=store, dependencies=deps,
    )

    assert replacements == []
    assert "old list remains open" in halts[0][0]
    assert halts[0][1]["order_list_id"] == 77


def test_breakeven_empty_replacement_halts_unprotected_position(tmp_path):
    halts = []
    store = state_store(tmp_path)
    store.save("SOLUSDT", {"77": {"fill_price": 100.0}})
    initial = [
        {
            "side": "SELL", "orderListId": 77, "type": "LIMIT_MAKER",
            "origQty": "1", "executedQty": "0.4", "price": "110",
        },
        {
            "side": "SELL", "orderListId": 77,
            "type": "STOP_LOSS_LIMIT", "stopPrice": "95",
        },
    ]
    responses = iter((initial, []))
    deps = dependencies(
        list_open_orders=lambda symbol: next(responses),
        place_oco_sell=lambda *args: None,
        halt=lambda reason, **metadata: halts.append((reason, metadata)),
    )

    maintain_breakeven(
        "SOLUSDT", offset_pct=0.001, stop_limit_offset_pct=0.0015,
        state_store=store, dependencies=deps,
    )

    assert "without confirmed protection" in halts[0][0]
    assert halts[0][1]["error_type"] == "UnconfirmedReplacement"
    assert "77" in store.load("SOLUSDT")


def test_breakeven_replacement_error_halts_without_secret_text(tmp_path):
    halts, logs = [], []
    store = state_store(tmp_path)
    store.save("SOLUSDT", {"77": {"fill_price": 100.0}})
    initial = [
        {
            "side": "SELL", "orderListId": 77, "type": "LIMIT_MAKER",
            "origQty": "1", "executedQty": "0.4", "price": "110",
        },
        {
            "side": "SELL", "orderListId": 77,
            "type": "STOP_LOSS_LIMIT", "stopPrice": "95",
        },
    ]
    responses = iter((initial, []))
    deps = dependencies(
        logger=logs.append,
        list_open_orders=lambda symbol: next(responses),
        place_oco_sell=lambda *args: (_ for _ in ()).throw(
            requests.ConnectionError("https://api.test/?signature=secret")
        ),
        halt=lambda reason, **metadata: halts.append((reason, metadata)),
    )

    maintain_breakeven(
        "SOLUSDT", offset_pct=0.001, stop_limit_offset_pct=0.0015,
        state_store=store, dependencies=deps,
    )

    evidence = repr((halts, logs))
    assert halts[0][1]["error_type"] == "ConnectionError"
    assert "signature=" not in evidence
    assert "secret" not in evidence


def test_breakeven_runtime_respects_interval():
    runtime = BreakevenRuntime(enabled=True, offset_pct=0.001, check_interval=3)
    assert runtime.due() is False
    assert runtime.due() is False
    assert runtime.due() is True
    assert runtime.due() is False


def test_gap_below_stop_cancels_oco_and_confirms_market_flatten():
    canceled, sold = [], []
    state = {"open": True}

    def open_orders(symbol):
        if not state["open"]:
            return []
        return [{
            "side": "SELL",
            "orderListId": 77,
            "stopPrice": "95",
            "origQty": "0.124",
            "executedQty": "0",
        }]

    def cancel(symbol, order_list_id):
        canceled.append(order_list_id)
        state["open"] = False

    deps = dependencies(
        list_open_orders=open_orders,
        get_balances=lambda: {
            "SOL": {
                "free": "3.756" if state["open"] else "3.880",
                "locked": "0.124" if state["open"] else "0",
            }
        },
        cancel_oco=cancel,
        place_market_order=lambda *args: (
            sold.append(args)
            or {"orderId": 99, "status": "FILLED", "executedQty": "0.124"}
        ),
    )
    assert emergency_gap_flatten("SOLUSDT", 80.0, dependencies=deps)
    assert canceled == [77]
    assert sold[0][:3] == ("SOLUSDT", "SELL", Decimal("0.124"))


def test_gap_flatten_waits_for_oco_release_before_market_sell():
    calls = {"orders": 0, "balances": 0}
    sleeps = []
    sold = []

    def open_orders(symbol):
        calls["orders"] += 1
        if calls["orders"] <= 3:
            return [{
                "side": "SELL",
                "orderListId": 77,
                "stopPrice": "95",
                "origQty": "1.000",
                "executedQty": "0",
            }]
        return []

    def balances():
        calls["balances"] += 1
        released = calls["balances"] >= 4
        return {
            "SOL": {
                "free": "1.000" if released else "0",
                "locked": "0" if released else "1.000",
            }
        }

    deps = dependencies(
        list_open_orders=open_orders,
        get_balances=balances,
        place_market_order=lambda *args: (
            sold.append(args)
            or {"orderId": 99, "status": "FILLED", "executedQty": "1.000"}
        ),
        sleep=sleeps.append,
    )

    assert emergency_gap_flatten(
        "SOLUSDT",
        80.0,
        dependencies=deps,
        cancel_release_timeout_sec=0.1,
        cancel_release_poll_sec=0.01,
    )
    assert len(sleeps) == 2
    assert sold[0][:3] == ("SOLUSDT", "SELL", Decimal("1.0"))


def test_gap_flatten_uses_smaller_residual_from_partially_filled_oco_leg():
    state = {"open": True}
    sold = []
    orders = [
        {
            "side": "SELL",
            "orderListId": 77,
            "type": "STOP_LOSS_LIMIT",
            "stopPrice": "95",
            "origQty": "1.000",
            "executedQty": "0",
        },
        {
            "side": "SELL",
            "orderListId": 77,
            "type": "LIMIT_MAKER",
            "stopPrice": "0",
            "origQty": "1.000",
            "executedQty": "0.600",
        },
    ]

    deps = dependencies(
        list_open_orders=lambda symbol: orders if state["open"] else [],
        cancel_oco=lambda symbol, order_list_id: state.update(open=False),
        get_balances=lambda: {
            "SOL": {
                "free": "3.756" if state["open"] else "4.156",
                "locked": "0.400" if state["open"] else "0",
            }
        },
        place_market_order=lambda *args: (
            sold.append(args)
            or {"orderId": 99, "status": "FILLED", "executedQty": "0.400"}
        ),
    )

    assert emergency_gap_flatten(
        "SOLUSDT",
        80.0,
        dependencies=deps,
    )
    assert sold[0][:3] == ("SOLUSDT", "SELL", Decimal("0.4"))


def test_gap_flatten_halts_when_oco_release_never_confirms():
    halts = []
    market_orders = []
    order = {
        "side": "SELL",
        "orderListId": 77,
        "stopPrice": "95",
        "origQty": "1.000",
        "executedQty": "0",
    }
    deps = dependencies(
        list_open_orders=lambda symbol: [order],
        get_balances=lambda: {
            "SOL": {"free": "0", "locked": "1.000"}
        },
        place_market_order=lambda *args: market_orders.append(args),
        halt=lambda reason, **metadata: halts.append(reason),
    )

    assert not emergency_gap_flatten(
        "SOLUSDT",
        80.0,
        dependencies=deps,
        cancel_release_timeout_sec=0.02,
        cancel_release_poll_sec=0.01,
    )
    assert market_orders == []
    assert "release not confirmed" in halts[0]


def test_gap_flatten_halts_on_partial_market_execution():
    state = {"open": True}
    halts = []

    def open_orders(symbol):
        return [{
            "side": "SELL",
            "orderListId": 77,
            "stopPrice": "95",
            "origQty": "1.000",
            "executedQty": "0",
        }] if state["open"] else []

    def cancel(symbol, order_list_id):
        state["open"] = False

    deps = dependencies(
        list_open_orders=open_orders,
        cancel_oco=cancel,
        get_balances=lambda: {
            "SOL": {
                "free": "0" if state["open"] else "1.000",
                "locked": "1.000" if state["open"] else "0",
            }
        },
        place_market_order=lambda *args: {
            "orderId": 99,
            "status": "PARTIALLY_FILLED",
            "executedQty": "0.400",
        },
        halt=lambda reason, **metadata: halts.append(reason),
    )

    assert not emergency_gap_flatten(
        "SOLUSDT",
        80.0,
        dependencies=deps,
    )
    assert "MARKET flatten incomplete" in halts[0]
    assert "expected=1.000 executed=0.400" in halts[0]
