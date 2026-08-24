from ladder_dragon.supervision.aggregate_trade_history import (
    load_aggregate_trade_window,
    safe_aggregate_trade_error,
)
from ladder_dragon.execution.tools_market import BinanceHttpError


def _row(identifier: int, timestamp: int) -> dict[str, object]:
    return {"a": identifier, "T": timestamp, "p": "100", "q": "1", "m": False}


def test_aggregate_trade_window_paginates_without_losing_rows():
    pages = [
        [_row(index, 1_001 + index) for index in range(1_000)],
        [_row(1_000 + index, 2_001 + index) for index in range(5)],
    ]
    calls = []

    def public_get(_path, params):
        calls.append(dict(params))
        return pages[len(calls) - 1]

    rows, complete, page_count = load_aggregate_trade_window(
        public_get, symbol="SOLUSDT", start_ms=1_000, end_ms=10_000
    )
    assert complete is True
    assert page_count == 2
    assert len(rows) == 1_005
    assert calls[1]["fromId"] == 1_000
    assert "startTime" not in calls[1]
    assert "endTime" not in calls[1]


def test_aggregate_trade_window_stops_after_crossing_interval_end():
    pages = [
        [_row(index, 1_001 + index) for index in range(1_000)],
        [_row(1_000, 2_001), _row(1_001, 10_001), _row(1_002, 10_002)],
    ]
    calls = []

    def public_get(_path, params):
        calls.append(dict(params))
        return pages[len(calls) - 1]

    rows, complete, page_count = load_aggregate_trade_window(
        public_get, symbol="ETHUSDT", start_ms=1_000, end_ms=10_000
    )

    assert complete is True
    assert page_count == 2
    assert rows[-1]["a"] == 1_000
    assert len(rows) == 1_001
    assert calls[1] == {"symbol": "ETHUSDT", "limit": 1000, "fromId": 1_000}


def test_aggregate_trade_window_fails_closed_on_a_sequence_gap():
    def public_get(_path, _params):
        return [_row(1, 1_001), _row(3, 1_002)]

    try:
        load_aggregate_trade_window(
            public_get, symbol="SOLUSDT", start_ms=1_000, end_ms=2_000
        )
    except ValueError as exc:
        assert "incomplete" in str(exc)
    else:
        raise AssertionError("aggregate trade gap unexpectedly passed")


def test_aggregate_trade_window_marks_bounded_exhaustion_incomplete():
    def public_get(_path, params):
        first = int(params.get("fromId", 0))
        return [_row(first + index, 1_001 + index) for index in range(1_000)]

    _rows, complete, page_count = load_aggregate_trade_window(
        public_get,
        symbol="SOLUSDT",
        start_ms=1_000,
        end_ms=10_000,
        maximum_pages=2,
    )
    assert complete is False
    assert page_count == 2


def test_aggregate_trade_error_keeps_only_bounded_machine_fields():
    error = BinanceHttpError(
        "signature=secret&apiKey=private",
        status=400,
        code=-1128,
        endpoint="https://api.binance.com/api/v3/aggTrades?signature=secret",
    )

    summary = safe_aggregate_trade_error(error)

    assert summary == (
        "BinanceHttpError status=400 code=-1128 endpoint=/api/v3/aggTrades"
    )
    assert "secret" not in summary
    assert safe_aggregate_trade_error(ValueError("private response")) == "ValueError"
