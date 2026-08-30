import json
from dataclasses import replace
from decimal import Decimal

import pytest

from ladder_dragon.execution.market_data_stream import (
    BinanceMarketDataObserver,
    DecisionFreshnessPolicy,
    MarketSnapshotStore,
    combined_market_stream_url,
    evaluate_entry_veto,
    evaluate_snapshot_gate,
)


def test_combined_market_stream_contains_realtime_sources():
    url = combined_market_stream_url("SOLUSDT")

    assert "solusdt@aggTrade" in url
    assert "solusdt@depth@100ms" in url
    assert "depth20" not in url
    assert "kline" not in url
    assert "apiKey" not in url


def test_market_snapshot_is_immutable_and_incremental():
    ticks = iter((1_000_000_000, 1_100_000_000, 1_200_000_000))
    store = MarketSnapshotStore(
        "SOLUSDT",
        monotonic_ns=lambda: next(ticks),
        wall_time_ms=lambda: 1_700_000_000_000,
    )
    store.initialize_depth({
        "lastUpdateId": 10,
        "bids": [["100", "2"]],
        "asks": [["100.1", "1"]],
    })
    store.update({"e": "depthUpdate", "U": 11, "u": 11, "b": [], "a": []})
    store.update({
        "e": "aggTrade", "a": 1, "p": "100.05", "q": "1", "T": 1000, "m": False,
    })
    snapshot = store.snapshot()
    assert snapshot.ready is True
    assert snapshot.best_bid == Decimal("100")
    assert snapshot.best_ask == Decimal("100.1")
    assert snapshot.spread_bps > 0
    assert snapshot.depth_imbalance > 0
    assert snapshot.trade_flow_quote == Decimal("100.05")


def test_depth_sequence_regression_fails_closed_until_fresh_snapshot():
    ticks = iter((1, 2, 3, 4))
    store = MarketSnapshotStore(
        "SOLUSDT",
        monotonic_ns=lambda: next(ticks),
    )
    store.initialize_depth({
        "lastUpdateId": 10,
        "bids": [["100", "2"]],
        "asks": [["100.1", "1"]],
    })
    with pytest.raises(ValueError, match="sequence gap"):
        store.update({
            "e": "depthUpdate", "U": 12, "u": 12,
            "b": [["100", "3"]], "a": [],
        })
    store.begin_stream_session()
    store.initialize_depth({
        "lastUpdateId": 11,
        "bids": [["100", "3"]], "asks": [["100.1", "1"]],
    })
    store.update({"e": "depthUpdate", "U": 12, "u": 12, "b": [], "a": []})

    snapshot = store.snapshot()
    assert snapshot.sequence_ok is True
    assert snapshot.depth_update_id == 12
    assert snapshot.depth_imbalance > 0


def test_duplicate_full_depth_snapshot_refreshes_without_latching_failure():
    ticks = iter((1, 2, 3))
    store = MarketSnapshotStore(
        "SOLUSDT",
        monotonic_ns=lambda: next(ticks),
    )
    store.update({
        "lastUpdateId": 10,
        "bids": [["100", "1"]],
        "asks": [["100.1", "3"]],
    })
    first_imbalance = store.snapshot().depth_imbalance

    store.update({
        "lastUpdateId": 10,
        "bids": [["100", "4"]],
        "asks": [["100.1", "1"]],
    })

    snapshot = store.snapshot()
    assert snapshot.sequence_ok is True
    assert snapshot.depth_update_id == 10
    assert snapshot.depth_imbalance > first_imbalance


def test_new_stream_session_requires_fresh_book_and_depth_frames():
    ticks = iter((1, 2, 3, 4))
    store = MarketSnapshotStore(
        "SOLUSDT",
        monotonic_ns=lambda: next(ticks),
    )
    store.initialize_depth({
        "lastUpdateId": 10,
        "bids": [["100", "2"]],
        "asks": [["100.1", "1"]],
    })
    store.update({"e": "depthUpdate", "U": 11, "u": 11, "b": [], "a": []})
    assert store.snapshot().ready is True

    store.begin_stream_session()
    reset = store.snapshot()
    assert reset.ready is False
    assert reset.depth_update_id is None
    assert reset.sequence_ok is True

    store.initialize_depth({"lastUpdateId": 1, "bids": [["100", "2"]], "asks": [["100.1", "1"]]})
    assert store.snapshot().ready is False
    store.update({"e": "depthUpdate", "U": 2, "u": 2, "b": [], "a": []})
    assert store.snapshot().ready is True


def test_observer_reconnect_resets_connection_scoped_depth_identity():
    store = MarketSnapshotStore("SOLUSDT", monotonic_ns=lambda: 1)
    store.initialize_depth({"lastUpdateId": 10, "bids": [["100", "2"]], "asks": [["100.1", "1"]]})

    class StopState:
        stopped = False

        def is_set(self):
            return self.stopped

        def set(self):
            self.stopped = True

        def wait(self, _timeout):
            return self.stopped

    stop = StopState()

    class BrokenConnection:
        def recv(self):
            raise OSError("connection lost")

    class RecoveredConnection:
        def recv(self):
            stop.set()
            return json.dumps({
                "e": "depthUpdate", "U": 6, "u": 6,
                "b": [], "a": [],
            })

    connections = iter((BrokenConnection(), RecoveredConnection()))
    observer = BinanceMarketDataObserver(
        store,
        testnet=False,
        logger=lambda _message: None,
        connect=lambda _url, timeout: next(connections),
        snapshot_fetcher=lambda _symbol: {
            "lastUpdateId": 5,
            "bids": [["100", "2"]], "asks": [["100.1", "1"]],
        },
    )
    observer._stop = stop

    observer._run()

    snapshot = store.snapshot()
    assert snapshot.sequence_ok is True
    assert snapshot.depth_update_id == 6


def test_snapshot_gate_rejects_stale_move_spread_and_negative_net_edge():
    ticks = iter((1_000_000_000, 1_100_000_000))
    store = MarketSnapshotStore(
        "SOLUSDT",
        monotonic_ns=lambda: next(ticks),
    )
    store.initialize_depth({
        "lastUpdateId": 10,
        "bids": [["100", "2"]],
        "asks": [["100.5", "1"]],
    })
    store.update({"e": "depthUpdate", "U": 11, "u": 11, "b": [], "a": []})

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
    store.initialize_depth({
        "lastUpdateId": 10,
        "bids": [["100", "2"]],
        "asks": [["100.01", "1"]],
    })
    store.update({"e": "depthUpdate", "U": 11, "u": 11, "b": [], "a": []})

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
    store.initialize_depth({
        "lastUpdateId": 10,
        "bids": [["100", "2"]],
        "asks": [["100.01", "1"]],
    })
    store.update({"e": "depthUpdate", "U": 11, "u": 11, "b": [], "a": []})
    store.update({
        "e": "aggTrade",
        "a": 1,
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


def test_trade_flow_running_total_expires_old_frames_exactly():
    now = [1_000]
    store = MarketSnapshotStore(
        "SOLUSDT",
        monotonic_ns=lambda: 1,
        wall_time_ms=lambda: now[0],
        flow_window_ms=2_000,
    )
    store.initialize_depth({"lastUpdateId": 1, "bids": [["10", "2"]], "asks": [["11", "2"]]})
    store.update({
        "e": "aggTrade", "a": 1, "p": "10", "q": "2", "T": 1_000, "m": False,
    })
    now[0] = 2_000
    store.update({
        "e": "aggTrade", "a": 2, "p": "5", "q": "1", "T": 2_000, "m": True,
    })
    assert store.snapshot().trade_flow_quote == Decimal("15")

    now[0] = 3_001
    store.update({
        "e": "aggTrade", "a": 3, "p": "2", "q": "3", "T": 3_001, "m": False,
    })

    assert store.snapshot().trade_flow_quote == Decimal("1")


def test_entry_veto_cancels_adverse_or_unavailable_evidence():
    store = MarketSnapshotStore("SOLUSDT", monotonic_ns=lambda: 1)
    unavailable = evaluate_entry_veto(
        store.snapshot(),
        {
            "contract_version": "l2_adverse_selection_cancel_v2",
            "prefill_price_change_max_bps": "-10",
            "prefill_signed_trade_flow_max": "-0.2",
            "prefill_order_flow_imbalance_max": "-0.1",
            "cancel_latency_ms": 1000,
            "minimum_signal_lead_ms": 61000,
            "selection_artifact_sha256": "a" * 64,
        },
        now_monotonic_ns=1,
    )
    assert unavailable.cancel is True

    adverse = replace(
        store.snapshot(),
        ready=True,
        veto_ready=True,
        sequence_ok=True,
        received_monotonic_ns=1,
        prefill_price_change_bps=Decimal("-11"),
        prefill_signed_trade_flow=Decimal("-0.3"),
        prefill_order_flow_imbalance=Decimal("-0.2"),
    )
    decision = evaluate_entry_veto(
        adverse,
        {
            "contract_version": "l2_adverse_selection_cancel_v2",
            "prefill_price_change_max_bps": "-10",
            "prefill_signed_trade_flow_max": "-0.2",
            "prefill_order_flow_imbalance_max": "-0.1",
            "cancel_latency_ms": 1000,
            "minimum_signal_lead_ms": 61000,
            "selection_artifact_sha256": "a" * 64,
        },
        now_monotonic_ns=1,
    )
    assert decision.cancel is True
    assert decision.signal_observed is True
