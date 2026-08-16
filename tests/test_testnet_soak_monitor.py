from decimal import Decimal
import json
import sqlite3

from bin import testnet_soak_monitor as soak
from bin.testnet_soak_monitor import (
    SoakSample,
    evaluate_sample,
    oco_protection_coverage,
)


def sample(**overrides) -> SoakSample:
    values = dict(
        ts=1.0,
        account_qty=Decimal("0.129"),
        ledger_qty=Decimal("0.129"),
        market_price=Decimal("77"),
        holdings_exposure=Decimal("9.933"),
        total_exposure=Decimal("9.933"),
        open_buy_count=0,
        open_sell_count=2,
        protected_sell_legs=2,
        protected_sell_qty=Decimal("0.129"),
        protection_complete=True,
        halted=False,
    )
    values.update(overrides)
    return SoakSample(**values)


def evaluate(value: SoakSample):
    return evaluate_sample(
        value,
        max_open_buys=1,
        max_exposure=Decimal("25"),
        min_notional=Decimal("5"),
        quantity_tolerance=Decimal("0.001"),
    )


def test_protected_consistent_position_passes():
    assert evaluate(sample()) == ([], False, False)


def test_exposure_buy_count_and_halt_are_immediate_violations():
    violations, unprotected, mismatch = evaluate(
        sample(total_exposure=Decimal("30"), open_buy_count=2, halted=True)
    )
    assert len(violations) == 3
    assert unprotected is False
    assert mismatch is False


def test_unprotected_and_inventory_mismatch_use_grace_path():
    violations, unprotected, mismatch = evaluate(
        sample(
            ledger_qty=Decimal("0.100"),
            open_sell_count=0,
            protected_sell_legs=0,
            protected_sell_qty=Decimal("0"),
            protection_complete=False,
        )
    )
    assert violations == []
    assert unprotected is True
    assert mismatch is True


def test_nontradable_dust_does_not_require_oco():
    violations, unprotected, mismatch = evaluate(
        sample(
            account_qty=Decimal("0.001"),
            ledger_qty=Decimal("0.001"),
            holdings_exposure=Decimal("0.077"),
            total_exposure=Decimal("0.077"),
            open_sell_count=0,
            protected_sell_legs=0,
        )
    )
    assert violations == []
    assert unprotected is False
    assert mismatch is False


def test_complete_ocos_cannot_hide_an_unprotected_position_remainder():
    violations, unprotected, mismatch = evaluate(
        sample(
            account_qty=Decimal("0.300"),
            ledger_qty=Decimal("0.300"),
            holdings_exposure=Decimal("23.100"),
            total_exposure=Decimal("23.100"),
            protected_sell_legs=4,
            protected_sell_qty=Decimal("0.200"),
        )
    )
    assert violations == []
    assert unprotected is True
    assert mismatch is False


def test_oco_coverage_counts_each_complete_list_once():
    rows = [
        {
            "orderListId": list_id,
            "origQty": qty,
            "executedQty": "0",
        }
        for list_id, qty in ((11, "0.100"), (11, "0.100"), (12, "0.200"), (12, "0.200"))
    ]
    assert oco_protection_coverage(
        rows, quantity_tolerance=Decimal("0.001")
    ) == (4, Decimal("0.300"), True)


def test_incomplete_oco_is_not_complete_protection():
    rows = [{"orderListId": 11, "origQty": "0.100", "executedQty": "0"}]
    assert oco_protection_coverage(
        rows, quantity_tolerance=Decimal("0.001")
    ) == (1, Decimal("0"), False)


def _exchange_info():
    return {
        "symbols": [
            {
                "symbol": "SOLUSDT",
                "baseAsset": "SOL",
                "quoteAsset": "USDT",
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                    {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                    {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
                ],
            }
        ]
    }


def test_transient_source_failure_preserves_progress_and_retries(
    tmp_path, monkeypatch, capsys
):
    database = tmp_path / "stats.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE inventory_exact(symbol TEXT, qty_text TEXT)")
        connection.execute("INSERT INTO inventory_exact VALUES('SOLUSDT','0.129')")
    report = tmp_path / "soak.json"

    class Client:
        account_reads = 0

        def __init__(self, *_args):
            pass

        def public_get(self, path, _params=None):
            if path == "/api/v3/exchangeInfo":
                return _exchange_info()
            soak.RUN = False
            return {"price": "77"}

        def signed(self, _method, path, _params=None):
            if path == "/api/v3/account":
                self.account_reads += 1
                if self.account_reads == 1:
                    raise RuntimeError("private provider response")
                return {"balances": [{"asset": "SOL", "free": "0.129", "locked": "0"}]}
            return [
                {"side": "SELL", "orderListId": 10, "origQty": "0.129", "executedQty": "0"},
                {"side": "SELL", "orderListId": 10, "origQty": "0.129", "executedQty": "0"},
            ]

    monkeypatch.setattr(soak, "SpotTestnetClient", Client)
    monkeypatch.setattr(soak, "apply_testnet_paths", lambda: None)
    monkeypatch.setenv("BOT_STATS_DB", str(database))
    monkeypatch.setenv("BOT_RUN_DIR", str(tmp_path))
    monkeypatch.setattr(
        soak.sys,
        "argv",
        [
            "testnet_soak_monitor",
            "--duration-sec",
            "10",
            "--interval-sec",
            "0.001",
            "--report",
            str(report),
        ],
    )
    soak.RUN = True
    assert soak.main() == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "interrupted"
    assert payload["samples"] == 1
    assert payload["read_failures"] == 1
    assert payload["max_consecutive_read_failures"] == 1
    assert payload["last_source_error"] == "RuntimeError"
    assert "private provider response" not in capsys.readouterr().err


def test_persistent_source_failure_blocks_soak_without_sensitive_text(
    tmp_path, monkeypatch, capsys
):
    database = tmp_path / "stats.sqlite3"
    database.touch()
    report = tmp_path / "soak.json"

    class Client:
        def __init__(self, *_args):
            pass

        def public_get(self, path, _params=None):
            assert path == "/api/v3/exchangeInfo"
            return _exchange_info()

        def signed(self, _method, _path, _params=None):
            raise RuntimeError("private provider response")

    monkeypatch.setattr(soak, "SpotTestnetClient", Client)
    monkeypatch.setattr(soak, "apply_testnet_paths", lambda: None)
    monkeypatch.setattr(soak.time, "sleep", lambda _seconds: None)
    monkeypatch.setenv("BOT_STATS_DB", str(database))
    monkeypatch.setenv("BOT_RUN_DIR", str(tmp_path))
    monkeypatch.setattr(
        soak.sys,
        "argv",
        [
            "testnet_soak_monitor",
            "--duration-sec",
            "10",
            "--max-consecutive-read-failures",
            "2",
            "--report",
            str(report),
        ],
    )
    soak.RUN = True
    assert soak.main() == 1
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "source_unavailable"
    assert payload["samples"] == 0
    assert payload["read_failures"] == 2
    assert payload["max_consecutive_read_failures"] == 2
    assert "private provider response" not in capsys.readouterr().err
