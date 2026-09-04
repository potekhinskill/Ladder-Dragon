from dataclasses import asdict
from decimal import Decimal as D

import pytest

from ladder_dragon.strategy.market_replay import BookLevel, MarketEvent
from ladder_dragon.strategy.prediction.historical_entry_replay import (
    historical_entry_replay,
    historical_entry_replays,
)
from ladder_dragon.strategy.prediction.historical_execution import HistoricalExecution
from ladder_dragon.strategy.prediction.historical_policy import HistoricalPolicy, RollingVeto


def policy(**changes):
    result = asdict(HistoricalPolicy(
        symbol="SOLUSDT", entry_gap_bps="100", take_profit_bps="100",
        stop_trigger_bps="100", stop_limit_bps="120", notional_quote="100",
        entry_ttl_ms=8000, holding_ms=15000, cadence_ms=1000, latency_ms=100,
        cancel_latency_ms=500, stop_grace_ms=2000, market_impact_bps="10",
        maximum_event_gap_ms=2000, allowed_regimes=["RANGE"], classifier_fingerprint="a" * 64,
        panic_source_fingerprint="c" * 64,
        veto_price_bps="-5", veto_signed_flow="-0.1", veto_ofi="-0.1",
        signal_window_ms=2000, maximum_attempts=100,
    ))
    result.update(changes)
    return result


def context(**changes):
    row = dict(observed_at_ms=1, valid_until_ms=100000, symbol="SOLUSDT",
               classifier_fingerprint="a" * 64, regime="RANGE", panic=False,
               panic_source_fingerprint="c" * 64, panic_observed_at_ms=1,
               tick_size="0.01", step_size="0.001", minimum_quantity="0.001",
               minimum_notional_quote="1", maker_buy_fee_pct="0.001",
               maker_sell_fee_pct="0.001", taker_buy_fee_pct="0.001", taker_sell_fee_pct="0.001",
               source_sha256="b" * 64)
    row.update(changes)
    return row


def event(stamp, bid="100", ask="101", trades=(), qty="10"):
    return MarketEvent(stamp, (BookLevel(D(bid), D(qty)), BookLevel(D("40"), D("10"))),
                       (BookLevel(D(ask), D("10")), BookLevel(D("200"), D("10"))),
                       tuple((D(p), D(q), side) for p, q, side in trades))


def run(events, **changes):
    return historical_entry_replay(iter(events), policy_payload=policy(**changes),
                                   context_rows=[context()], start_ms=3000, entry_end_ms=12000,
                                   end_ms=28000, cutoff_ms=28000)


def declining_history():
    return [event(t, bid=str(D("100") - D(t // 1000) / 10), ask=str(D("101") - D(t // 1000) / 10),
                  trades=(("100", "0.1", "SELL"),)) for t in range(1000, 28001, 1000)]


def test_successful_cancel_creates_previously_unknown_opportunities():
    report = run(declining_history())
    baseline = report["episodes"]["baseline"]
    veto = report["episodes"]["veto"]
    assert report["status"] == "COMPLETE_SELECTION_REPLAY"
    assert len(veto) > len(baseline)
    assert any(row["started_at_ms"] not in {item["started_at_ms"] for item in baseline} for row in veto)
    assert veto[0]["terminal_reason"] == "ENTRY_VETO"
    assert veto[0]["entry_order_submitted"] is False
    assert veto[0]["entry_filled_quantity"] == "0"
    assert veto[0]["cancel_effective_ts_ms"] is None
    assert veto[1]["started_at_ms"] > veto[0]["terminal_at_ms"]
    assert report["promotion_eligible"] is False
    assert report["selection_artifact_ready"] is False


def test_preregistered_attempt_cap_stops_without_a_replay_error():
    report = run(declining_history(), maximum_attempts=1)

    assert report["summaries"]["baseline"]["opportunities"] == 1
    assert report["summaries"]["veto"]["opportunities"] == 1
    assert len(report["episodes"]["baseline"]) == 1
    assert len(report["episodes"]["veto"]) == 1


def test_policy_batch_matches_independent_replays_in_one_event_pass():
    history = declining_history()
    first = policy(veto_price_bps="-5")
    second = policy(veto_price_bps="-10")
    batched = historical_entry_replays(
        iter(history),
        jobs=[(first, [context()]), (second, [context()])],
        start_ms=3000,
        entry_end_ms=12000,
        end_ms=28000,
        cutoff_ms=28000,
    )
    independent = [
        historical_entry_replay(
            iter(history),
            policy_payload=item,
            context_rows=[context()],
            start_ms=3000,
            entry_end_ms=12000,
            end_ms=28000,
            cutoff_ms=28000,
        )
        for item in (first, second)
    ]
    assert batched == independent


def test_cancel_cannot_erase_fill_before_arrival():
    p = HistoricalPolicy.parse(policy())
    episode = HistoricalExecution(event(3000), p, context(), "test")
    episode.process(event(3200), veto=True, panic=False)
    episode.process(event(3400, trades=((str(episode.entry), str(episode.quantity), "SELL"),)), veto=False, panic=False)
    assert episode.entry_qty == episode.quantity
    assert episode.phase == "PROTECTED"
    episode.process(event(3800), veto=False, panic=False)
    assert episode.result is None


def test_pre_submit_veto_never_creates_an_order():
    episode = HistoricalExecution(
        event(3000), HistoricalPolicy.parse(policy()), context(), "veto",
        pre_submit_veto=True,
    )

    assert episode.result["terminal_reason"] == "ENTRY_VETO"
    assert episode.result["entry_order_submitted"] is False
    assert episode.result["entry_filled_quantity"] == "0"
    assert episode.orders.orders == []


def test_partial_fill_survives_cancel_and_gets_protection():
    episode = HistoricalExecution(event(3000), HistoricalPolicy.parse(policy()), context(), "partial")
    episode.process(event(3200), veto=True, panic=False)
    episode.process(event(3300, trades=((str(episode.entry), "0.1", "SELL"),)), veto=False, panic=False)
    episode.process(event(3800), veto=False, panic=False)
    assert episode.entry_qty == D("0.1")
    assert episode.phase == "PROTECTED"
    assert episode.order("target").quantity == D("0.1")
    assert episode.result is None


def test_fill_wins_ambiguous_cancel_timestamp_tie():
    episode = HistoricalExecution(event(3000), HistoricalPolicy.parse(policy()), context(), "tie")
    episode.process(event(3200), veto=True, panic=False)
    episode.process(event(3700, trades=((str(episode.entry), str(episode.quantity), "SELL"),)), veto=False, panic=False)
    assert episode.entry_qty == episode.quantity
    assert episode.phase == "PROTECTED"


def test_submission_timestamp_tie_cannot_award_fill():
    episode = HistoricalExecution(event(3000), HistoricalPolicy.parse(policy()), context(), "arrival-tie")
    episode.process(event(3100, trades=((str(episode.entry), str(episode.quantity), "SELL"),)), veto=False, panic=False)
    assert episode.entry_qty == 0


def test_post_only_uses_real_arrival_book_not_seed():
    episode = HistoricalExecution(event(3000), HistoricalPolicy.parse(policy()), context(), "cross")
    result = episode.process(event(3200, "98", "99"), veto=False, panic=False)
    assert result["terminal_reason"] == "ENTRY_REJECTED_POST_ONLY"
    assert result["entry_filled_quantity"] == "0"


def test_panic_exit_loss_is_included():
    episode = HistoricalExecution(event(3000), HistoricalPolicy.parse(policy()), context(), "panic")
    episode.process(event(3200), veto=False, panic=False)
    episode.process(event(3400, trades=((str(episode.entry), str(episode.quantity), "SELL"),)), veto=False, panic=False)
    result = episode.process(event(3800, "98", "99"), veto=False, panic=True)
    assert result["terminal_reason"] == "PANIC_FLATTEN"
    assert D(result["net_pnl_quote"]) < 0


def test_missing_or_future_context_blocks_entire_replay():
    for row in [context(observed_at_ms=5000), context(valid_until_ms=4000)]:
        with pytest.raises(ValueError, match="context unavailable"):
            historical_entry_replay(declining_history(), policy_payload=policy(), context_rows=[row],
                                    start_ms=3000, entry_end_ms=12000, end_ms=28000, cutoff_ms=28000)


def test_gap_and_short_tail_never_return_success():
    history = declining_history()
    with pytest.raises(ValueError, match="data gap"):
        run(history[:4] + history[8:])
    with pytest.raises(ValueError, match="tail is incomplete"):
        run(history[:-5])


def test_veto_has_no_fill_time_or_future_outcome_input():
    early = declining_history()[:4]
    first, second = RollingVeto(HistoricalPolicy.parse(policy())), RollingVeto(HistoricalPolicy.parse(policy()))
    assert [first.update(row) for row in early] == [second.update(row) for row in early]
    result = run(declining_history())
    changed = run(declining_history() + [event(29000, "50", "51")])
    assert result == changed  # immutable cutoff; no result leakage from future events


def test_shared_signal_matches_live_window_boundary_and_reconnect_reset():
    from ladder_dragon.execution.market_data_stream import MarketSnapshotStore

    now = [1]
    store = MarketSnapshotStore(
        "SOLUSDT",
        monotonic_ns=lambda: now[0] * 1_000_000 + 1,
        wall_time_ms=lambda: now[0],
        flow_window_ms=2_000,
    )
    rolling = RollingVeto(HistoricalPolicy.parse(policy(signal_window_ms=2_000)))
    initial = event(1, bid="100", ask="101", qty="2")
    rolling.update(initial)
    store.initialize_depth({
        "lastUpdateId": 1,
        "bids": [["100", "2"], ["40", "10"]],
        "asks": [["101", "10"], ["200", "10"]],
    })

    now[0] = 1_001
    rolling.update(event(1_001, bid="100", ask="101", qty="3"))
    store.update({
        "e": "depthUpdate", "U": 2, "u": 2,
        "b": [["100", "3"]], "a": [],
    })
    now[0] = 1_501
    rolling.update(event(
        1_501, bid="100", ask="101", qty="3",
        trades=(("100.5", "1", "BUY"),),
    ))
    store.update({
        "e": "aggTrade", "a": 1, "p": "100.5", "q": "1",
        "T": 1_501, "m": False,
    })
    now[0] = 3_002
    rolling.update(event(3_002, bid="99", ask="101", qty="3"))
    store.update({
        "e": "depthUpdate", "U": 3, "u": 3,
        "b": [["100", "0"], ["99", "3"]], "a": [],
    })
    rolling.update(event(
        3_002, bid="99", ask="101", qty="3",
        trades=(("99", "2", "SELL"),),
    ))
    store.update({
        "e": "aggTrade", "a": 2, "p": "99", "q": "2",
        "T": 3_002, "m": True,
    })

    historical = rolling.accumulator.snapshot()
    live = store.snapshot()
    assert live.prefill_price_change_bps == historical.price_change_bps
    assert live.prefill_signed_trade_flow == historical.signed_trade_flow
    assert live.prefill_order_flow_imbalance == historical.order_flow_imbalance
    assert live.trade_flow_quote == historical.trade_flow_quote

    store.begin_stream_session()
    reset = store.snapshot()
    assert reset.veto_ready is False
    assert reset.trade_flow_quote == 0
    assert reset.prefill_price_change_bps == 0


@pytest.mark.parametrize("change", [{"latency_ms": True}, {"entry_gap_bps": 100.0}, {"veto_ofi": "NaN"},
                                    {"allowed_regimes": ["RECOVERY"]}])
def test_policy_is_strict_and_fail_closed(change):
    with pytest.raises(ValueError):
        HistoricalPolicy.parse(policy(**change))


def test_uncovered_queue_blocks_instead_of_assuming_zero():
    episode = HistoricalExecution(event(3000), HistoricalPolicy.parse(policy()), context(), "queue")
    shallow = MarketEvent(3200, (BookLevel(D("100"), D("1")),), (BookLevel(D("101"), D("1")),))
    with pytest.raises(ValueError, match="queue price"):
        episode.process(shallow, veto=False, panic=False)


@pytest.mark.parametrize("recorded_context", [False, True])
def test_cli_publishes_immutable_paired_replay(tmp_path, monkeypatch, capsys, recorded_context):
    import json
    import sys
    from bin.replay_historical_entries import main
    from ladder_dragon.strategy.market_replay import archive_sha256

    archive = tmp_path / "history.jsonl"
    rows = [{"s": "SOLUSDT", "E": 1000, "_received_at_ms": 1000, "lastUpdateId": 1,
             "bids": [["100", "10"], ["40", "10"]], "asks": [["101", "10"], ["200", "10"]]}]
    old_bid, old_ask = "100", "101"
    for n in range(2, 29):
        bid, ask = str(D("100") - D(n) / 10), str(D("101") - D(n) / 10)
        rows += [{"e": "depthUpdate", "s": "SOLUSDT", "E": n * 1000, "_received_at_ms": n * 1000,
                  "U": n, "u": n, "b": [[old_bid, "0"], [bid, "10"]], "a": [[old_ask, "0"], [ask, "10"]]},
                 {"e": "aggTrade", "s": "SOLUSDT", "E": n * 1000, "_received_at_ms": n * 1000,
                  "a": n, "p": "100", "q": "0.1", "m": True}]
        old_bid, old_ask = bid, ask
    archive.write_text("".join(json.dumps(row) + "\n" for row in rows))
    digest = archive_sha256(archive)
    archive.with_suffix(".jsonl.metadata.json").write_text(json.dumps({
        "schema_version": 1, "symbol": "SOLUSDT", "contains_secrets": False,
        "archive_sha256": digest, "event_count": len(rows),
        "first_snapshot_update_id": 1, "last_update_id": 28,
    }))
    request = tmp_path / "request.json"
    payload = {"policy": policy(), "context": [context()], "archives": [{"path": str(archive), "sha256": digest}],
               "start_ms": 3000, "entry_end_ms": 12000, "end_ms": 28000, "cutoff_ms": 28000}
    extra = []
    if recorded_context:
        from ladder_dragon.supervision.historical_context import HistoricalContextCollector
        from ladder_dragon.strategy.prediction.episode_semantics import v23_evidence_semantics_contract
        from ladder_dragon.strategy.prediction.historical_policy import fingerprint
        from ladder_dragon.supervision.panic_observer import panic_observer_fingerprint, refresh_panic_observation
        classifier = v23_evidence_semantics_contract()["regime_classifier"]
        filters = {"symbols": [{"symbol": "SOLUSDT", "status": "TRADING", "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
            {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
            {"filterType": "NOTIONAL", "minNotional": "5"},
        ]}]}
        fees = {"symbol": "SOLUSDT", **{name: {"maker": "0.001", "taker": "0.001", "buyer": "0", "seller": "0"}
                                        for name in ("standardCommission", "taxCommission", "specialCommission")}}
        bars = [[(n - 119) * 60_000, "100", "101", "99", "100", "1", (n - 119) * 60_000 + 59_999]
                for n in range(120)]
        collector = HistoricalContextCollector(
            tmp_path / "context.sqlite3",
            public_get=lambda endpoint, _params: bars if endpoint == "/api/v3/klines" else filters,
            signed_get=lambda *_: fees, clock=lambda: 1000, panic_run_dir=tmp_path,
        )
        assert collector.collect("SOLUSDT", {
            "classifier": classifier,
            "captured_at_ms": 1000,
            "regime": "RANGE",
            "panic": False,
            "panic_hits": 0,
            "panic_observation": refresh_panic_observation(
                "SOLUSDT", public_get=collector.public_get, now_ms=1000, run_dir=tmp_path),
        })["status"] == "AVAILABLE"
        payload.pop("context")
        payload["policy"]["classifier_fingerprint"] = fingerprint(classifier)
        payload["policy"]["panic_source_fingerprint"] = panic_observer_fingerprint()
        extra = ["--context-db", str(collector.path)]
    request.write_text(json.dumps(payload))
    output = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["replay", "--request", str(request), "--output", str(output), *extra])
    assert main() == 0
    report = json.loads(output.read_text())
    assert report["summaries"]["veto"]["opportunities"] > report["summaries"]["baseline"]["opportunities"]
    if recorded_context:
        assert report["context_evidence"]["records"][0]["payload"]["sources"]["fees"]["kind"] == "BINANCE_ACCOUNT_COMMISSION_MAX_V1"
    before = output.read_bytes()
    assert main() == 2
    assert output.read_bytes() == before
    payload["context"] = [context(maker_buy_fee_pct="secret-sentinel")]
    request.write_text(json.dumps(payload))
    assert main() == 2
    assert "secret-sentinel" not in capsys.readouterr().out
