from decimal import Decimal
import json

import pytest

from ladder_dragon.strategy.market_replay import (
    BookLevel,
    MarketEvent,
    OrderBookReplay,
    ReplayCalibration,
    ReplayOrder,
    archive_sha256,
    calibrate_market_events,
    load_jsonl_archive,
    read_calibration,
    write_calibration,
)
from bin import backtest


def test_price_time_priority_and_latency():
    replay = OrderBookReplay(latency_ms=100)
    replay.submit(ReplayOrder("late", "BUY", Decimal("10"), Decimal("1"), 0), 0)
    replay.submit(ReplayOrder("early", "BUY", Decimal("10"), Decimal("1"), 0), 0)
    event = MarketEvent(50, asks=(BookLevel(Decimal("10"), Decimal("2")),))
    assert replay.process(event) == []
    event = MarketEvent(100, asks=(BookLevel(Decimal("10"), Decimal("2")),))
    assert [fill[0] for fill in replay.process(event)] == ["late", "early"]


def test_price_priority_serves_more_aggressive_buy_first():
    replay = OrderBookReplay()
    replay.submit(ReplayOrder("lower", "BUY", Decimal("10"), Decimal("1"), 0), 0)
    replay.submit(ReplayOrder("higher", "BUY", Decimal("11"), Decimal("1"), 0), 0)
    event = MarketEvent(0, asks=(BookLevel(Decimal("9"), Decimal("1")),))
    assert [fill[0] for fill in replay.process(event)] == ["higher"]


def test_cancel_and_rate_limit():
    replay = OrderBookReplay(max_requests_per_minute=2)
    order = ReplayOrder("x", "BUY", Decimal("10"), Decimal("1"), 0)
    replay.submit(order, 0)
    assert replay.cancel("x", 1)
    with pytest.raises(RuntimeError):
        replay.submit(ReplayOrder("y", "BUY", Decimal("10"), Decimal("1"), 0), 2)


def _archive_rows():
    rows = [{
        "lastUpdateId": 100,
        "E": 1_000,
        "bids": [["99", "10"]],
        "asks": [["101", "10"]],
    }]
    last = 100
    for index in range(1, 4):
        ts = 1_000 + index * 100
        rows.extend([
            {
                "e": "depthUpdate", "E": ts, "U": last + 1,
                "u": last + 1, "pu": last,
                "b": [["99", str(10 + index)]],
                "a": [["101", str(10 + index)]],
            },
            {
                "e": "aggTrade", "E": ts + 1, "p": "101",
                "q": "0.5", "m": False,
            },
            {
                "e": "executionReport", "E": ts + 2, "T": ts + 2,
                "O": ts - 48, "q": "1", "l": "0.5",
                "x": "TRADE", "X": "PARTIALLY_FILLED", "i": index,
            },
        ])
        last += 1
    return rows


def test_raw_binance_archive_calibrates_with_sequence_and_provenance(tmp_path):
    archive = tmp_path / "events.jsonl"
    archive.write_text(
        "\n".join(json.dumps(row) for row in _archive_rows()) + "\n",
        encoding="utf-8",
    )
    events = load_jsonl_archive(archive)
    report = calibrate_market_events(
        events,
        source_sha256=archive_sha256(archive),
        min_book_events=3,
        min_trades=3,
    )
    assert report.eligible is True
    assert report.trade_count == 3
    assert report.execution_sample_count == 3
    assert report.partial_fill_ratio == Decimal("0.5")
    assert report.latency_ms_p95 == 50
    output = tmp_path / "calibration.json"
    write_calibration(output, report)
    assert read_calibration(output) == report


def test_raw_binance_archive_rejects_depth_sequence_gap(tmp_path):
    rows = _archive_rows()
    rows[1]["U"] = 999
    rows[1]["u"] = 999
    archive = tmp_path / "broken.jsonl"
    archive.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="sequence gap"):
        load_jsonl_archive(archive)


def test_replay_market_impact_uses_basis_points():
    replay = OrderBookReplay(market_impact_bps=Decimal("10"))
    replay.submit(ReplayOrder("x", "BUY", Decimal("11"), Decimal("1"), 0), 0)
    fills = replay.process(MarketEvent(
        0, asks=(BookLevel(Decimal("10"), Decimal("1")),)
    ))
    assert fills[0][2] == Decimal("10.020")


def test_depth_cancellation_advances_only_configured_queue_fraction():
    replay = OrderBookReplay(queue_cancellation_ahead_ratio=Decimal("0.5"))
    replay.process(MarketEvent(
        0, bids=(BookLevel(Decimal("10"), Decimal("10")),)
    ))
    order = ReplayOrder("queued", "BUY", Decimal("10"), Decimal("1"), 0)
    replay.submit(order, 1, queue_ahead=Decimal("2"))

    replay.process(MarketEvent(
        2, bids=(BookLevel(Decimal("10"), Decimal("8")),)
    ))

    assert order.queue_ahead == Decimal("1")


def test_public_trade_quantity_is_shared_and_fills_exact_price_as_maker():
    replay = OrderBookReplay(maker_fee_pct=Decimal("0.001"))
    replay.process(MarketEvent(
        1,
        bids=(BookLevel(Decimal("100"), Decimal("2")),),
        asks=(BookLevel(Decimal("101"), Decimal("2")),),
    ))
    replay.submit(ReplayOrder("first", "BUY", Decimal("100"), Decimal("1"), 1), 1)
    replay.submit(ReplayOrder("second", "BUY", Decimal("100"), Decimal("1"), 1), 1)

    fills = replay.process(MarketEvent(
        2,
        bids=(BookLevel(Decimal("100"), Decimal("2")),),
        asks=(BookLevel(Decimal("101"), Decimal("2")),),
        trades=((Decimal("100"), Decimal("3.5"), "SELL"),),
    ))

    assert [(fill.order_id, fill.quantity) for fill in fills] == [
        ("first", Decimal("1")),
        ("second", Decimal("0.5")),
    ]
    assert all(fill.liquidity == "MAKER" for fill in fills)
    assert sum((fill.fee_quote for fill in fills), Decimal("0")) == Decimal("0.15")


def test_order_crosses_as_taker_only_when_it_reaches_venue():
    replay = OrderBookReplay(taker_fee_pct=Decimal("0.002"))
    replay.process(MarketEvent(
        1,
        bids=(BookLevel(Decimal("99"), Decimal("1")),),
        asks=(BookLevel(Decimal("101"), Decimal("1")),),
    ))
    order = ReplayOrder("resting", "BUY", Decimal("100"), Decimal("1"), 1)
    replay.submit(order, 1)
    assert replay.process(MarketEvent(
        2,
        bids=(BookLevel(Decimal("99"), Decimal("1")),),
        asks=(BookLevel(Decimal("101"), Decimal("1")),),
    )) == []

    assert replay.process(MarketEvent(
        3,
        bids=(BookLevel(Decimal("99"), Decimal("1")),),
        asks=(BookLevel(Decimal("99"), Decimal("1")),),
    )) == []
    assert order.remaining == Decimal("1")

    taker = ReplayOrder("taker", "BUY", Decimal("101"), Decimal("1"), 3)
    replay.submit(taker, 3)
    fill = replay.process(MarketEvent(
        4,
        bids=(BookLevel(Decimal("99"), Decimal("1")),),
        asks=(BookLevel(Decimal("100"), Decimal("1")),),
    ))[0]
    assert fill.order_id == "taker"
    assert fill.liquidity == "TAKER"
    assert fill.fee_quote == Decimal("0.2")


def test_public_trade_at_another_price_cannot_consume_local_fifo_queue():
    replay = OrderBookReplay()
    replay.process(MarketEvent(
        1,
        bids=(BookLevel(Decimal("100"), Decimal("2")),),
        asks=(BookLevel(Decimal("101"), Decimal("2")),),
    ))
    order = ReplayOrder("resting", "BUY", Decimal("100"), Decimal("1"), 1)
    replay.submit(order, 1)

    assert replay.process(MarketEvent(
        2,
        bids=(BookLevel(Decimal("100"), Decimal("2")),),
        asks=(BookLevel(Decimal("101"), Decimal("2")),),
        trades=((Decimal("99"), Decimal("10"), "SELL"),),
    )) == []
    assert order.queue_ahead == Decimal("2")
    assert order.remaining == Decimal("1")


def test_cancelled_first_order_transfers_shared_public_queue():
    replay = OrderBookReplay()
    replay.process(MarketEvent(
        1,
        bids=(BookLevel(Decimal("100"), Decimal("2")),),
        asks=(BookLevel(Decimal("101"), Decimal("2")),),
    ))
    first = ReplayOrder("first", "BUY", Decimal("100"), Decimal("1"), 1)
    second = ReplayOrder("second", "BUY", Decimal("100"), Decimal("1"), 1)
    replay.submit(first, 1)
    replay.submit(second, 1)
    replay.process(MarketEvent(
        2,
        bids=(BookLevel(Decimal("100"), Decimal("2")),),
        asks=(BookLevel(Decimal("101"), Decimal("2")),),
    ))

    assert replay.cancel("first", 3) is True
    assert second.queue_ahead == Decimal("2")
    fills = replay.process(MarketEvent(
        4,
        bids=(BookLevel(Decimal("100"), Decimal("2")),),
        asks=(BookLevel(Decimal("101"), Decimal("2")),),
        trades=((Decimal("100"), Decimal("3"), "SELL"),),
    ))
    assert [(fill.order_id, fill.quantity) for fill in fills] == [
        ("second", Decimal("1"))
    ]


def test_replay_fees_are_validated_and_l3_request_fails_closed(monkeypatch, capsys):
    with pytest.raises(ValueError, match="non-negative"):
        OrderBookReplay(maker_fee_pct=Decimal("-0.1"))
    monkeypatch.setattr(
        "sys.argv", ["backtest", "candles.csv", "--require-l3"]
    )
    with pytest.raises(SystemExit) as exc_info:
        backtest.main()
    assert exc_info.value.code == 2
    assert "not L3 order IDs" in capsys.readouterr().err


def test_measured_execution_report_latency_overrides_public_proxy(tmp_path):
    archive = tmp_path / "measured.jsonl"
    archive.write_text(
        "\n".join(json.dumps(row) for row in _archive_rows()) + "\n",
        encoding="utf-8",
    )
    report = calibrate_market_events(
        load_jsonl_archive(archive),
        source_sha256="a" * 64,
        min_book_events=1,
        min_trades=1,
        measured_order_latencies_ms=[12, 20, 18],
    )

    assert report.latency_source == "intent_to_execution_report_receive"
    assert report.latency_ms_p95 == 18


def test_backtest_rejects_calibration_from_another_archive(tmp_path, monkeypatch):
    archive = tmp_path / "events.jsonl"
    archive.write_text(
        json.dumps({
            "lastUpdateId": 1,
            "E": 1_000,
            "bids": [["99", "1"]],
            "asks": [["101", "1"]],
        }) + "\n",
        encoding="utf-8",
    )
    calibration = ReplayCalibration(
        schema_version=1,
        archive_sha256="0" * 64,
        first_ts_ms=1_000,
        last_ts_ms=2_000,
        event_count=10,
        book_event_count=10,
        trade_count=10,
        execution_sample_count=10,
        eligible=True,
        reasons=(),
        spread_pct=Decimal("0.001"),
        slippage_pct=Decimal("0.0001"),
        participation_rate=Decimal("0.1"),
        partial_fill_ratio=Decimal("0.5"),
        latency_ms_p95=100,
        market_impact_bps=Decimal("1"),
    )
    report = tmp_path / "calibration.json"
    write_calibration(report, calibration)
    candles = tmp_path / "candles.csv"
    candles.write_text(
        "ts,open,high,low,close\n1700000000,100,101,99,100\n"
        "1700086400,100,101,99,100\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "backtest",
            str(candles),
            "--archive",
            str(archive),
            "--calibration",
            str(report),
        ],
    )
    with pytest.raises(SystemExit) as exc_info:
        backtest.main()
    assert exc_info.value.code == 2
