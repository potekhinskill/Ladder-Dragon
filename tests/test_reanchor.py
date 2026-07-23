from decimal import Decimal
from types import SimpleNamespace

import pytest

from bin import ai_supervisor
from bin.supervisor_config import build_supervisor_parser, validate_supervisor_args
from ladder_dragon.strategy.reanchor import BuyReanchor, plan_buy_reanchors


def order(
    order_id: int,
    *,
    side: str = "BUY",
    price: str = "100",
    executed: str = "0",
    update_ms: int = 800_000,
    order_type: str = "LIMIT",
):
    return {
        "orderId": order_id,
        "side": side,
        "type": order_type,
        "price": price,
        "executedQty": executed,
        "updateTime": update_ms,
    }


def test_reanchor_is_bounded_and_buy_only_without_lookahead():
    planned = plan_buy_reanchors(
        [
            order(1),
            order(2, side="SELL", price="112"),
            order(3, order_type="STOP_LOSS_LIMIT", price="95"),
        ],
        ["109", "105", "95"],
        now_price="110",
        tick_size="0.01",
        now_ms=1_000_000,
        min_age_sec=120,
        trigger_pct="0.0025",
        max_step_pct="0.005",
        max_per_cycle=1,
    )

    assert planned == [
        BuyReanchor(
            order_id=1,
            old_price=Decimal("100"),
            target_price=Decimal("100.50"),
            age_sec=200,
        )
    ]


def test_reanchor_never_cancels_partial_fill_and_preserves_price_rank():
    planned = plan_buy_reanchors(
        [
            order(1, price="108", executed="0.01"),
            order(2, price="100"),
        ],
        ["109", "105"],
        now_price="110",
        tick_size="0.01",
        now_ms=1_000_000,
        min_age_sec=120,
        trigger_pct="0.0025",
        max_step_pct="0.005",
        max_per_cycle=2,
    )

    assert [item.order_id for item in planned] == [2]
    assert planned[0].target_price == Decimal("100.50")


def test_reanchor_waits_for_age_and_trigger_and_rejects_nonfinite_market():
    assert plan_buy_reanchors(
        [order(1, update_ms=950_000)],
        ["109"],
        now_price="110",
        tick_size="0.01",
        now_ms=1_000_000,
        min_age_sec=120,
        trigger_pct="0.0025",
        max_step_pct="0.005",
        max_per_cycle=1,
    ) == []
    assert plan_buy_reanchors(
        [order(1, price="108.80")],
        ["109"],
        now_price="110",
        tick_size="0.01",
        now_ms=1_000_000,
        min_age_sec=120,
        trigger_pct="0.0025",
        max_step_pct="0.005",
        max_per_cycle=1,
    ) == []
    with pytest.raises(ValueError, match="finite"):
        plan_buy_reanchors(
            [order(1)],
            ["109"],
            now_price="NaN",
            tick_size="0.01",
            now_ms=1_000_000,
            min_age_sec=120,
            trigger_pct="0.0025",
            max_step_pct="0.005",
            max_per_cycle=1,
        )


def test_reanchor_tracks_rising_ladder_in_bounded_steps_but_never_chases_down():
    current_order = order(1, price="100", update_ms=0)
    observed_targets = []
    for cycle, (market, desired) in enumerate(
        [("101", "100.70"), ("102", "101.70"), ("103", "102.70")],
        start=1,
    ):
        current_order["updateTime"] = cycle * 1_000
        planned = plan_buy_reanchors(
            [current_order],
            [desired],
            now_price=market,
            tick_size="0.01",
            now_ms=cycle * 1_000 + 120_000,
            min_age_sec=120,
            trigger_pct="0.0025",
            max_step_pct="0.005",
            max_per_cycle=1,
        )
        assert len(planned) == 1
        observed_targets.append(planned[0].target_price)
        current_order["price"] = str(planned[0].target_price)

    assert observed_targets == [
        Decimal("100.50"),
        Decimal("101.00"),
        Decimal("101.50"),
    ]
    assert plan_buy_reanchors(
        [order(2, price="101.50")],
        ["100.50"],
        now_price="102",
        tick_size="0.01",
        now_ms=1_000_000,
        min_age_sec=120,
        trigger_pct="0.0025",
        max_step_pct="0.005",
        max_per_cycle=1,
    ) == []


def test_reanchor_shadow_best_buy_stays_within_market_gap():
    planned = plan_buy_reanchors(
        [order(1, price="99.40")],
        ["99.50"],
        now_price="100",
        tick_size="0.01",
        now_ms=1_000_000,
        min_age_sec=120,
        trigger_pct="0.0025",
        max_step_pct="0.005",
        max_per_cycle=1,
        max_market_gap_pct="0.0015",
    )

    assert planned == [
        BuyReanchor(
            order_id=1,
            old_price=Decimal("99.40"),
            target_price=Decimal("99.85"),
            age_sec=200,
        )
    ]
    assert planned[0].target_price < Decimal("100")


def test_supervisor_reanchor_cancels_once_and_returns_bounded_replacement(monkeypatch):
    open_orders = [order(7)]
    canceled = []
    lifetimes = []
    stopped = []
    monkeypatch.setattr(ai_supervisor, "list_open_orders", lambda symbol: open_orders)
    monkeypatch.setattr(
        ai_supervisor,
        "cancel_order",
        lambda symbol, order_id: canceled.append((symbol, order_id)) or True,
    )
    monkeypatch.setattr(
        ai_supervisor,
        "_log_order_lifetime",
        lambda *args, **kwargs: lifetimes.append((args, kwargs)),
    )
    monkeypatch.setattr(ai_supervisor.time, "time", lambda: 1_000)
    monkeypatch.setattr(ai_supervisor, "log", lambda message: None)
    monkeypatch.setattr(
        ai_supervisor,
        "_stop_child",
        lambda symbol, reason: stopped.append((symbol, reason)) or True,
    )
    args = SimpleNamespace(
        reanchor_mode="APPLY",
        reanchor_min_age_sec=120,
        reanchor_trigger_pct=Decimal("0.0025"),
        reanchor_max_step_pct=Decimal("0.005"),
        reanchor_max_per_cycle=1,
    )

    result = ai_supervisor.smart_rolling(
        "SOLUSDT",
        110.0,
        [109.0, 105.0],
        args,
        tick_size="0.01",
        prediction_apply_approved=True,
    )

    assert canceled == [("SOLUSDT", 7)]
    assert result["cancel"]["reanchor"] == 1
    assert result["replacement_prices"] == [100.5]
    assert lifetimes[0][1]["cancel_reason"] == "adaptive-reanchor"
    assert stopped == [("SOLUSDT", "adaptive BUY re-anchor")]
    assert result["apply_gate_approved"] is True


def test_supervisor_reanchor_apply_falls_back_to_shadow_without_gate(
    monkeypatch,
):
    monkeypatch.setattr(ai_supervisor, "list_open_orders", lambda symbol: [order(7)])
    canceled = []
    monkeypatch.setattr(
        ai_supervisor,
        "cancel_order",
        lambda symbol, order_id: canceled.append(order_id) or True,
    )
    monkeypatch.setattr(ai_supervisor.time, "time", lambda: 1_000)
    messages = []
    monkeypatch.setattr(ai_supervisor, "log", messages.append)
    args = SimpleNamespace(
        reanchor_mode="APPLY",
        reanchor_min_age_sec=120,
        reanchor_trigger_pct=Decimal("0.0025"),
        reanchor_max_step_pct=Decimal("0.005"),
        reanchor_max_per_cycle=1,
    )

    result = ai_supervisor.smart_rolling(
        "SOLUSDT", 110.0, [109.0], args, tick_size="0.01"
    )

    assert canceled == []
    assert result["effective_mode"] == "SHADOW"
    assert result["cancel"]["shadow"] == 1
    assert any(message.startswith("[REANCHOR-GATE]") for message in messages)


def test_supervisor_reanchor_is_disabled_by_default_and_fails_closed(monkeypatch):
    monkeypatch.delenv("ADAPTIVE_REANCHOR_MODE", raising=False)
    parser = build_supervisor_parser()
    args = parser.parse_args([])
    assert args.reanchor_mode == "OFF"

    monkeypatch.setattr(ai_supervisor, "list_open_orders", lambda symbol: [order(9)])
    canceled = []
    monkeypatch.setattr(
        ai_supervisor,
        "cancel_order",
        lambda symbol, order_id: canceled.append(order_id) or True,
    )
    result = ai_supervisor.smart_rolling(
        "SOLUSDT",
        110.0,
        [109.0],
        SimpleNamespace(reanchor_mode="OFF"),
        tick_size="0.01",
    )
    assert canceled == []
    assert result["replacement_prices"] == []


def test_reanchor_runtime_telemetry_accumulates_without_order_capability(monkeypatch):
    monkeypatch.setattr(ai_supervisor, "_AI_RUNTIME_STATUS", {})
    monkeypatch.setattr(ai_supervisor, "_AI_RUNTIME_STATUS_PATH", None)
    args = SimpleNamespace(
        reanchor_mode="SHADOW",
        reanchor_min_age_sec=120,
        reanchor_trigger_pct=Decimal("0.0005"),
        reanchor_max_step_pct=Decimal("0.005"),
        reanchor_max_market_gap_pct=Decimal("0.0015"),
        reanchor_max_per_cycle=1,
    )
    result = {
        "kept": 1,
        "cancel": {"shadow": 1, "reanchor": 0},
        "proposals": [
            {
                "order_id": 11,
                "old_price": "77.48",
                "target_price": "77.52",
                "age_sec": 180,
            }
        ],
    }

    ai_supervisor._publish_reanchor_runtime("SOLUSDT", result, args)
    ai_supervisor._publish_reanchor_runtime("SOLUSDT", result, args)

    telemetry = ai_supervisor._AI_RUNTIME_STATUS["reanchor"]
    assert telemetry["mode"] == "SHADOW"
    assert telemetry["trigger_pct"] == "0.0005"
    assert telemetry["max_market_gap_pct"] == "0.0015"
    assert telemetry["totals"] == {
        "shadow_candidates": 2,
        "apply_cancels": 0,
    }
    assert telemetry["symbols"]["SOLUSDT"]["proposals"][0]["order_id"] == 11
    assert set(telemetry["symbols"]["SOLUSDT"]["proposals"][0]) == {
        "order_id", "old_price", "target_price", "age_sec",
    }
    assert "secret" not in str(telemetry).lower()
    assert "api_key" not in str(telemetry).lower()


def test_supervisor_reanchor_shadow_logs_without_cancel_or_restart(monkeypatch):
    monkeypatch.setattr(ai_supervisor, "list_open_orders", lambda symbol: [order(11)])
    canceled = []
    stopped = []
    messages = []
    monkeypatch.setattr(
        ai_supervisor,
        "cancel_order",
        lambda symbol, order_id: canceled.append(order_id) or True,
    )
    monkeypatch.setattr(
        ai_supervisor,
        "_stop_child",
        lambda symbol, reason: stopped.append(symbol) or True,
    )
    monkeypatch.setattr(ai_supervisor.time, "time", lambda: 1_000)
    monkeypatch.setattr(ai_supervisor, "log", messages.append)
    args = SimpleNamespace(
        reanchor_mode="SHADOW",
        reanchor_min_age_sec=120,
        reanchor_trigger_pct=Decimal("0.0025"),
        reanchor_max_step_pct=Decimal("0.005"),
        reanchor_max_per_cycle=1,
    )

    result = ai_supervisor.smart_rolling(
        "SOLUSDT", 110.0, [109.0], args, tick_size="0.01"
    )

    assert canceled == []
    assert stopped == []
    assert result["cancel"]["shadow"] == 1
    assert result["replacement_prices"] == []
    assert any(message.startswith("[REANCHOR-SHADOW]") for message in messages)


def test_reanchor_restart_stops_only_the_selected_symbol(monkeypatch):
    class Process:
        def __init__(self, pid):
            self.pid = pid
            self.terminated = False

        def poll(self):
            return 0 if self.terminated else None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout):
            return 0

    sol = Process(101)
    eth = Process(202)
    ai_supervisor._CHILD_PROCS.clear()
    ai_supervisor._CHILD_PROCS.update({"SOLUSDT": sol, "ETHUSDT": eth})
    ai_supervisor._CHILD_STARTED_AT.update({"SOLUSDT": 1, "ETHUSDT": 1})
    monkeypatch.setattr(ai_supervisor, "log", lambda message: None)
    try:
        assert ai_supervisor._stop_child(
            "SOLUSDT", "adaptive BUY re-anchor"
        ) is True
        assert sol.terminated is True
        assert eth.terminated is False
        assert "SOLUSDT" not in ai_supervisor._CHILD_PROCS
        assert ai_supervisor._CHILD_PROCS["ETHUSDT"] is eth
    finally:
        ai_supervisor._CHILD_PROCS.clear()
        ai_supervisor._CHILD_STARTED_AT.clear()
        ai_supervisor._CHILD_RESTART_AFTER.clear()
        ai_supervisor._CHILD_FAILURES.clear()


def test_reanchor_restart_failure_retains_worker_and_defers_replacement(monkeypatch):
    class Process:
        pid = 303

        def poll(self):
            return None

        def terminate(self):
            raise OSError("permission denied")

    process = Process()
    ai_supervisor._CHILD_PROCS.clear()
    ai_supervisor._CHILD_PROCS["SOLUSDT"] = process
    monkeypatch.setattr(ai_supervisor, "log", lambda message: None)
    try:
        assert ai_supervisor._stop_child("SOLUSDT", "refresh") is False
        assert ai_supervisor._CHILD_PROCS["SOLUSDT"] is process
    finally:
        ai_supervisor._CHILD_PROCS.clear()


def test_reanchor_configuration_rejects_unsafe_refresh_rate():
    parser = build_supervisor_parser()
    args = parser.parse_args(
        [
            "--base-script",
            "bin/autosize_universal.py",
            "--no-ai-advisor",
            "--reanchor-min-age-sec",
            "59",
        ]
    )
    with pytest.raises(SystemExit):
        validate_supervisor_args(parser, args)

    args = parser.parse_args(
        [
            "--base-script",
            "bin/autosize_universal.py",
            "--no-ai-advisor",
            "--reanchor-max-market-gap-pct",
            "0",
        ]
    )
    with pytest.raises(SystemExit):
        validate_supervisor_args(parser, args)


def test_supervisor_configuration_rejects_unsafe_auth_backoff():
    parser = build_supervisor_parser()
    args = parser.parse_args(
        [
            "--base-script",
            "bin/autosize_universal.py",
            "--no-ai-advisor",
            "--binance-auth-backoff-initial-sec",
            "29",
        ]
    )
    with pytest.raises(SystemExit):
        validate_supervisor_args(parser, args)

    args = parser.parse_args(
        [
            "--base-script",
            "bin/autosize_universal.py",
            "--no-ai-advisor",
            "--binance-auth-backoff-initial-sec",
            "60",
            "--binance-auth-backoff-max-sec",
            "59",
        ]
    )
    with pytest.raises(SystemExit):
        validate_supervisor_args(parser, args)
