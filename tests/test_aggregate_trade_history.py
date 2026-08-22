from ladder_dragon.supervision.aggregate_trade_history import (
    load_aggregate_trade_window,
)


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
