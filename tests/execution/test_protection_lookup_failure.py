import requests

from ladder_dragon.execution.protection.breakeven import BreakevenStateStore
from ladder_dragon.execution.protection.runtime import (
    ProtectionConfig,
    ProtectionDependencies,
    protect_filled_buys,
)


def test_buy_status_network_failure_halts_and_preserves_queue(tmp_path):
    halts: list[tuple[str, dict[str, object]]] = []
    logs: list[str] = []

    def unavailable(_symbol, _order_id):
        raise requests.ConnectionError("private endpoint unavailable")

    dependencies = ProtectionDependencies(
        logger=logs.append,
        debugger=lambda message: None,
        journal=lambda: None,
        get_order=unavailable,
        recover_existing_protection=lambda client_id: False,
        poll_trades=lambda symbol: None,
        pick_oco_prices=lambda *args: (110, 95, 94),
        average_entry=lambda *args: None,
        profit_floor_pct=lambda: 0.01,
        pull_filters=lambda symbol: None,
        get_symbol_assets=lambda symbol: ("SOL", "USDT"),
        get_balances=lambda: {},
        round_price=lambda symbol, value: value,
        round_quantity=lambda symbol, value: value,
        min_quantity=lambda symbol, hint: 0.001,
        min_notional=lambda symbol, price: 5,
        format_price=lambda symbol, value: str(value),
        format_quantity=lambda symbol, value: str(value),
        halt=lambda reason, **metadata: halts.append((reason, metadata)),
        place_oco_sell=lambda *args, **kwargs: None,
        place_limit_order=lambda *args, **kwargs: None,
        list_open_orders=lambda symbol: [],
        tick_size=lambda symbol: 0.01,
        price_eps_mult=lambda: 1.0,
        round_step=lambda value, step, mode: value,
        cancel_oco=lambda symbol, order_list_id: None,
    )

    remaining = protect_filled_buys(
        "SOLUSDT",
        [41, 42],
        [90.0, 110.0],
        config=ProtectionConfig(0.0015, "prefer-tp1", False, 30, 1000, None),
        panic_active=False,
        breakeven_enabled=False,
        state_store=BreakevenStateStore(
            run_dir=lambda: str(tmp_path),
            debugger=lambda message: None,
        ),
        dependencies=dependencies,
    )

    assert remaining == [41, 42]
    assert halts == [(
        "unable to verify BUY order 41: ConnectionError",
        {"symbol": "SOLUSDT", "order_id": 41, "error_type": "ConnectionError"},
    )]
    assert logs == [
        "[PROTECTION-ERR] SOLUSDT unable to verify BUY order 41: ConnectionError"
    ]
