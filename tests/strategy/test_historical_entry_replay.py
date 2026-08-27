from dataclasses import asdict
from decimal import Decimal as D

import pytest

from ladder_dragon.strategy.market_replay import BookLevel, MarketEvent
from ladder_dragon.strategy.prediction.historical_entry_replay import historical_entry_replay
from ladder_dragon.strategy.prediction.historical_execution import HistoricalExecution
from ladder_dragon.strategy.prediction.historical_policy import HistoricalPolicy, RollingVeto


def policy(**changes):
    result = asdict(HistoricalPolicy(
        symbol="SOLUSDT", entry_gap_bps="100", take_profit_bps="100",
        stop_trigger_bps="100", stop_limit_bps="120", notional_quote="100",
        entry_ttl_ms=8000, holding_ms=15000, cadence_ms=1000, latency_ms=100,
        cancel_latency_ms=500, stop_grace_ms=2000, market_impact_bps="10",
        maximum_event_gap_ms=2000, allowed_regimes=["RANGE"], classifier_fingerprint="a" * 64,
        veto_price_bps="-5", veto_signed_flow="-0.1", veto_ofi="-0.1",
        signal_window_ms=2000, maximum_attempts=100,
    ))
    result.update(changes)
    return result


def context(**changes):
    row = dict(observed_at_ms=1, valid_until_ms=100000, symbol="SOLUSDT",
               classifier_fingerprint="a" * 64, regime="RANGE", panic=False,
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
    assert veto[1]["started_at_ms"] > veto[0]["cancel_effective_ts_ms"]
    assert report["promotion_eligible"] is False
    assert report["selection_artifact_ready"] is False


def test_cancel_cannot_erase_fill_before_arrival():
    p = HistoricalPolicy.parse(policy())
    episode = HistoricalExecution(event(3000), p, context(), "test")
    episode.process(event(3200), veto=True, panic=False)
    episode.process(event(3400, trades=((str(episode.entry), str(episode.quantity), "SELL"),)), veto=False, panic=False)
    assert episode.entry_qty == episode.quantity
    assert episode.phase == "PROTECTED"
    episode.process(event(3800), veto=False, panic=False)
    assert episode.result is None


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


def test_cli_publishes_immutable_paired_replay(tmp_path, monkeypatch, capsys):
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
    request.write_text(json.dumps(payload))
    output = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["replay", "--request", str(request), "--output", str(output)])
    assert main() == 0
    report = json.loads(output.read_text())
    assert report["summaries"]["veto"]["opportunities"] > report["summaries"]["baseline"]["opportunities"]
    before = output.read_bytes()
    assert main() == 2
    assert output.read_bytes() == before
    payload["context"][0]["maker_buy_fee_pct"] = "secret-sentinel"
    request.write_text(json.dumps(payload))
    assert main() == 2
    assert "secret-sentinel" not in capsys.readouterr().out
