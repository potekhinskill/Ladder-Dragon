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
    assert fills[0][2] == Decimal("10.010")


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
