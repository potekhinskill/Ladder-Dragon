import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from bin.audit_backtest_reports import classify_report, main
from bin.backtest import build_report
from ladder_dragon.strategy.simulation import SimulationConfig


def current_report(*, impact="10"):
    config = SimulationConfig(market_impact_bps=Decimal(impact))
    result = SimpleNamespace(
        final_equity=Decimal("1010"),
        realized_pnl=Decimal("10"),
        fees=Decimal("1"),
        trades=2,
        buy_hold_equity=Decimal("1005"),
    )
    return build_report(
        result,
        config,
        csv_sha256="a" * 64,
        archive_hash="b" * 64,
        calibration_hash="c" * 64,
        calibration=None,
        generated_at=100,
    )


def test_backtest_report_records_execution_model_and_provenance():
    report = current_report()
    assert report["report_schema_version"] == 2
    assert report["execution_model"]["market_impact_bps_divisor"] == "10000"
    assert report["execution_model"]["archive_book_model"] == (
        "L2_PRICE_LEVEL_FIFO_ESTIMATE"
    )
    assert report["execution_model"]["exact_l3"] is False
    assert report["config"]["market_impact_bps"] == "10"
    assert report["inputs"] == {
        "candles_sha256": "a" * 64,
        "archive_sha256": "b" * 64,
        "calibration_sha256": "c" * 64,
    }
    assert classify_report(report)["current"] is True


def test_legacy_nonzero_impact_requires_rerun_but_zero_is_informational():
    legacy = {
        "final_equity": "1000",
        "realized_pnl": "0",
        "trades": "2",
        "calibration": {"parameters": {"market_impact_bps": "5"}},
    }
    result = classify_report(legacy)
    assert result["rerun_required"] is True
    legacy["calibration"]["parameters"]["market_impact_bps"] = "0"
    result = classify_report(legacy)
    assert result["rerun_required"] is False
    assert result["current"] is False


def test_audit_cli_returns_two_for_invalidated_report(tmp_path, monkeypatch):
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({
        "final_equity": "1000",
        "realized_pnl": "0",
        "trades": "2",
        "config": {"market_impact_bps": "1"},
    }), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["audit_backtest_reports", str(path)])
    assert main() == 2


def test_report_classifier_rejects_non_report_and_bad_impact():
    with pytest.raises(ValueError, match="not a Ladder Dragon"):
        classify_report({"hello": "world"})
    report = current_report()
    report["config"]["market_impact_bps"] = "NaN"
    with pytest.raises(ValueError, match="invalid market_impact"):
        classify_report(report)
