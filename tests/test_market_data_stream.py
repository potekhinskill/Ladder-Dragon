from decimal import Decimal

from ladder_dragon.execution.market_data_stream import (
    DecisionFreshnessPolicy,
    MarketSnapshotStore,
    combined_market_stream_url,
    evaluate_snapshot_gate,
)


def test_combined_market_stream_contains_realtime_sources():
    url = combined_market_stream_url("SOLUSDT")

    assert "solusdt@bookTicker" in url
    assert "solusdt@aggTrade" in url
    assert "solusdt@depth20@100ms" in url
    assert "solusdt@kline_1m" in url
    assert "apiKey" not in url


def test_market_snapshot_is_immutable_and_incremental():
    ticks = iter((1_000_000_000, 1_100_000_000, 1_200_000_000, 1_300_000_000))
    store = MarketSnapshotStore(
        "SOLUSDT",
        monotonic_ns=lambda: next(ticks),
        wall_time_ms=lambda: 1_700_000_000_000,
    )
    store.update({"b": "100", "B": "2", "a": "100.1", "A": "3"})
    store.update({
        "lastUpdateId": 10,
        "bids": [["100", "2"]],
        "asks": [["100.1", "1"]],
    })
    store.update({
        "e": "aggTrade", "p": "100.05", "q": "1", "T": 1000, "m": False,
    })
    store.update({
        "e": "kline",
        "k": {
            "x": True, "c": "100", "h": "101", "l": "99",
            "v": "2", "q": "200",
        },
    })

    snapshot = store.snapshot()
    assert snapshot.ready is True
    assert snapshot.best_bid == Decimal("100")
    assert snapshot.best_ask == Decimal("100.1")
    assert snapshot.spread_bps > 0
    assert snapshot.depth_imbalance > 0
    assert snapshot.trade_flow_quote == Decimal("100.05")
    assert snapshot.ema20 == Decimal("100")
    assert snapshot.atr14 == Decimal("2")
    assert snapshot.vwap == Decimal("100")


def test_depth_sequence_regression_fails_closed():
    ticks = iter((1, 2, 3))
    store = MarketSnapshotStore(
        "SOLUSDT",
        monotonic_ns=lambda: next(ticks),
    )
    store.update({"b": "100", "B": "2", "a": "100.1", "A": "3"})
    store.update({
        "lastUpdateId": 10,
        "bids": [["100", "2"]],
        "asks": [["100.1", "1"]],
    })
    store.update({
        "lastUpdateId": 9,
        "bids": [["100", "2"]],
        "asks": [["100.1", "1"]],
    })

    assert store.snapshot().sequence_ok is False


def test_snapshot_gate_rejects_stale_move_spread_and_negative_net_edge():
    ticks = iter((1_000_000_000, 1_100_000_000))
    store = MarketSnapshotStore(
        "SOLUSDT",
        monotonic_ns=lambda: next(ticks),
    )
    store.update({"b": "100", "B": "2", "a": "100.5", "A": "3"})
    store.update({
        "lastUpdateId": 10,
        "bids": [["100", "2"]],
        "asks": [["100.5", "1"]],
    })

    result = evaluate_snapshot_gate(
        store.snapshot(),
        decision_reference_price="99",
        expected_edge_bps="5",
        fee_bps="3",
        slippage_bps="2",
        policy=DecisionFreshnessPolicy(
            max_age_ms=100,
            max_spread_bps=Decimal("20"),
            max_price_move_bps=Decimal("5"),
            minimum_net_edge_bps=Decimal("2"),
        ),
        now_monotonic_ns=1_500_000_000,
    )

    assert result.approved is False
    assert set(result.reasons) == {
        "market snapshot stale",
        "spread above limit",
        "planned price moved",
        "net edge below minimum",
    }


def test_snapshot_gate_approves_fresh_economic_decision():
    ticks = iter((1_000_000_000, 1_100_000_000))
    store = MarketSnapshotStore(
        "SOLUSDT",
        monotonic_ns=lambda: next(ticks),
    )
    store.update({"b": "100", "B": "2", "a": "100.01", "A": "3"})
    store.update({
        "lastUpdateId": 10,
        "bids": [["100", "2"]],
        "asks": [["100.01", "1"]],
    })

    result = evaluate_snapshot_gate(
        store.snapshot(),
        decision_reference_price="100",
        expected_edge_bps="12",
        fee_bps="3",
        slippage_bps="2",
        policy=DecisionFreshnessPolicy(),
        now_monotonic_ns=1_200_000_000,
    )

    assert result.approved is True
    assert result.reasons == ()


def test_trade_frames_cannot_hide_a_stale_order_book():
    ticks = iter((1_000_000_000, 1_100_000_000, 9_000_000_000))
    store = MarketSnapshotStore(
        "SOLUSDT",
        monotonic_ns=lambda: next(ticks),
    )
    store.update({"b": "100", "B": "2", "a": "100.01", "A": "3"})
    store.update({
        "lastUpdateId": 10,
        "bids": [["100", "2"]],
        "asks": [["100.01", "1"]],
    })
    store.update({
        "e": "aggTrade",
        "p": "100.01",
        "q": "1",
        "T": 9000,
        "m": False,
    })

    result = evaluate_snapshot_gate(
        store.snapshot(),
        decision_reference_price="100",
        expected_edge_bps="12",
        fee_bps="3",
        slippage_bps="2",
        policy=DecisionFreshnessPolicy(max_age_ms=500),
        now_monotonic_ns=9_100_000_000,
    )

    assert result.approved is False
    assert "market snapshot stale" in result.reasons
