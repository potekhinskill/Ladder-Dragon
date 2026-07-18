from pathlib import Path

from ladder_dragon.execution.executor_protection import (
    BreakevenRuntime,
    BreakevenStateStore,
    ProtectionConfig,
    ProtectionDependencies,
    maintain_breakeven,
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

    def place_oco(*args, **kwargs):
        placed.append((args, kwargs))
        return {"orderListId": 77}

    deps = dependencies(
        get_order=lambda symbol, order_id: {
            "orderId": order_id,
            "status": "FILLED",
            "executedQty": "0.100",
            "cummulativeQuoteQty": "10.0",
        },
        poll_trades=lambda symbol: polls.append(symbol),
        place_oco_sell=place_oco,
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
    assert placed[0][0][:5] == ("SOLUSDT", 0.1, 110.0, 95.0, 94.0)
    assert polls == ["SOLUSDT"]
    assert store.load("SOLUSDT")["77"]["fill_price"] == 100.0


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
    assert fallbacks[0][0][:4] == ("SELL", "SOLUSDT", 0.1, 110.0)
    assert halts == []


def test_live_failed_oco_flattens_and_halts(tmp_path, monkeypatch):
    monkeypatch.setenv("BOT_LIVE_CONFIRMED", "YES")
    flattened, halts = [], []
    deps = dependencies(
        get_order=lambda symbol, order_id: {"orderId": order_id, "status": "FILLED",
                                             "executedQty": "0.100", "cummulativeQuoteQty": "10.0"},
        place_market_order=lambda *args, **kwargs: flattened.append((args, kwargs)),
        halt=lambda reason, **metadata: halts.append(reason),
    )
    remaining = protect_filled_buys("SOLUSDT", [42], [90.0, 110.0], config=config(),
                                    panic_active=False, breakeven_enabled=False,
                                    state_store=state_store(tmp_path), dependencies=deps)
    assert remaining == [42]
    assert flattened[0][0][:3] == ("SOLUSDT", "SELL", 0.1)
    assert "fallback prefer-tp1" in halts[0]


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

    deps = dependencies(
        logger=logs.append,
        list_open_orders=lambda symbol: open_orders,
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
    assert replacements[0][0][0:3] == ("SOLUSDT", 0.6, 110.0)
    assert "77" not in store.load("SOLUSDT")
    assert store.load("SOLUSDT")["78"]["fill_price"] == 100.0
    assert any("OCO re-arm" in line for line in logs)


def test_breakeven_runtime_respects_interval():
    runtime = BreakevenRuntime(enabled=True, offset_pct=0.001, check_interval=3)
    assert runtime.due() is False
    assert runtime.due() is False
    assert runtime.due() is True
    assert runtime.due() is False


def test_gap_below_stop_cancels_oco_and_confirms_market_flatten():
    canceled, sold = [], []
    deps = dependencies(
        list_open_orders=lambda symbol: [{"side": "SELL", "orderListId": 77, "stopPrice": "95"}],
        get_balances=lambda: {"SOL": {"free": 1.0, "locked": 0.0}},
        cancel_oco=lambda symbol, oid: canceled.append(oid),
        place_market_order=lambda *args: sold.append(args) or {"orderId": 99, "status": "FILLED"},
    )
    assert emergency_gap_flatten("SOLUSDT", 80.0, dependencies=deps)
    assert canceled == [77]
    assert sold[0][:3] == ("SOLUSDT", "SELL", 0.999)
