from decimal import Decimal

from ladder_dragon.strategy.market_replay import ReplayCalibration
from ladder_dragon.strategy.replay_readiness import audit_replay_readiness


def calibration(index: int, volatility: str, *, measured: bool = False) -> ReplayCalibration:
    day = 86_400_000
    return ReplayCalibration(
        schema_version=3,
        archive_sha256=f"{index:064x}",
        first_ts_ms=index * day,
        last_ts_ms=index * day + 900_000,
        event_count=1000,
        book_event_count=700,
        trade_count=300,
        execution_sample_count=10,
        eligible=True,
        reasons=(),
        spread_pct=Decimal("0.0001"),
        slippage_pct=Decimal("0.0002"),
        participation_rate=Decimal("0.2"),
        partial_fill_ratio=Decimal("0.5"),
        latency_ms_p95=100,
        market_impact_bps=Decimal("1"),
        volatility_bps_p95=Decimal(volatility),
        latency_source=(
            "intent_to_execution_report_receive"
            if measured else "public_event_receive"
        ),
    )


def test_replay_readiness_requires_days_regimes_and_measured_latency():
    report = audit_replay_readiness([
        calibration(1, "0.2"),
        calibration(2, "1.0", measured=True),
        calibration(3, "3.0"),
    ])

    assert report.ready is True
    assert report.regimes == ("high", "low", "normal")
    assert report.span_days >= Decimal("2")


def test_replay_readiness_fails_closed_on_short_homogeneous_data():
    row = calibration(1, "0.2")
    report = audit_replay_readiness([row])

    assert report.ready is False
    assert "archives 1 < 3" in report.reasons
    assert any("missing volatility regimes" in reason for reason in report.reasons)
    assert any("measured latency archives" in reason for reason in report.reasons)
