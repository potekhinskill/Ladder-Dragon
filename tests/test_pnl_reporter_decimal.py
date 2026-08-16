from decimal import Decimal
from types import SimpleNamespace

import pytest

from bin import pnl_reporter
from bin.pnl_reporter import (
    MAX_PAGE_ATTEMPTS,
    MAX_RESPONSE_BYTES,
    PnLReportSourceError,
    fetch_trades,
    fifo_pnl,
    signed_get,
)


def test_fifo_reporter_uses_exact_decimal_accounting():
    gross, fees, stats = fifo_pnl(
        [
            {
                "symbol": "SOLUSDT",
                "isBuyer": True,
                "qty": "0.30000000",
                "price": "10.10000000",
                "quoteQty": "3.03000000",
                "commission": "0.00030000",
                "commissionAsset": "SOL",
            },
            {
                "symbol": "SOLUSDT",
                "isBuyer": False,
                "qty": "0.10000000",
                "price": "11.10000000",
                "quoteQty": "1.11000000",
                "commission": "0.00111000",
                "commissionAsset": "USDT",
            },
        ]
    )

    assert gross == Decimal("0.1000000000000000")
    assert fees == Decimal("0.0041400000000000")
    assert stats["open_lots_qty"] == Decimal("0.19970000")


def test_fifo_reporter_uses_canonical_non_usdt_quote_assets():
    gross, fees, stats = fifo_pnl(
        [
            {
                "symbol": "ETHGBP",
                "isBuyer": True,
                "qty": "1",
                "price": "2000",
                "quoteQty": "2000",
                "commission": "2",
                "commissionAsset": "GBP",
            }
        ]
    )

    assert gross == Decimal("0")
    assert fees == Decimal("2")
    assert stats["third_asset_fees_units"] == Decimal("0")


def test_fifo_reporter_rejects_an_unknown_quote_without_guessing():
    with pytest.raises(ValueError, match="cannot determine assets"):
        fifo_pnl(
            [
                {
                    "symbol": "ABCXYZ",
                    "isBuyer": True,
                    "qty": "1",
                    "price": "1",
                    "quoteQty": "1",
                    "commission": "0",
                    "commissionAsset": "XYZ",
                }
            ]
        )


def test_trade_pagination_retries_one_temporary_source_failure():
    calls = 0
    delays = []

    def request(_path, _params):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("private provider response")
        return []

    assert fetch_trades(
        "SOLUSDT",
        0,
        1,
        request=request,
        sleep=delays.append,
    ) == []
    assert calls == 2
    assert delays == [0.5]


def test_trade_pagination_blocks_persistent_failure_without_response_text():
    calls = 0

    def request(_path, _params):
        nonlocal calls
        calls += 1
        raise RuntimeError("private provider response")

    with pytest.raises(PnLReportSourceError) as captured:
        fetch_trades(
            "SOLUSDT",
            0,
            1,
            request=request,
            sleep=lambda _delay: None,
        )
    assert calls == MAX_PAGE_ATTEMPTS
    assert "private provider response" not in str(captured.value)


def test_signed_trade_response_has_a_streamed_byte_limit(monkeypatch):
    class Response:
        status_code = 200
        closed = False

        def iter_content(self, chunk_size):
            assert chunk_size == 8192
            yield b"["
            yield b"0" * MAX_RESPONSE_BYTES
            yield b"]"

        def close(self):
            self.closed = True

    response = Response()
    monkeypatch.setattr(pnl_reporter.requests, "get", lambda *_args, **_kwargs: response)
    with pytest.raises(PnLReportSourceError):
        signed_get("/api/v3/myTrades", {"symbol": "SOLUSDT"})
    assert response.closed is True


def test_main_returns_controlled_error_without_partial_report(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        pnl_reporter,
        "parse_args",
        lambda: SimpleNamespace(symbols="SOLUSDT", days=7),
    )
    monkeypatch.setattr(pnl_reporter, "REPORTS_DIR", str(tmp_path))
    monkeypatch.setattr(
        pnl_reporter,
        "fetch_trades",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PnLReportSourceError(endpoint="/api/v3/myTrades", status=None)
        ),
    )

    assert pnl_reporter.main() == 2
    assert not (tmp_path / "summary_7d.txt").exists()
    error = capsys.readouterr().err
    assert "PnLReportSourceError" in error
    assert "/api/v3/myTrades" not in error
