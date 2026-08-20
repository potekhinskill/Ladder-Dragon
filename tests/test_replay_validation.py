from decimal import Decimal

from ladder_dragon.execution.execution_latency import ExecutionOutcome
from ladder_dragon.strategy.market_replay import (
    BookLevel,
    MarketEvent,
    ReplayCalibration,
)
from ladder_dragon.strategy.replay_validation import (
    read_replay_validation,
    validate_replay_outcomes,
    write_replay_validation,
)


def calibration() -> ReplayCalibration:
    return ReplayCalibration(
        schema_version=3,
        archive_sha256="a" * 64,
        first_ts_ms=1000,
        last_ts_ms=3000,
        event_count=3,
        book_event_count=3,
        trade_count=1,
        execution_sample_count=2,
        eligible=True,
        reasons=(),
        spread_pct=Decimal("0.01"),
        slippage_pct=Decimal("0"),
        participation_rate=Decimal("1"),
        partial_fill_ratio=Decimal("1"),
        latency_ms_p95=0,
        market_impact_bps=Decimal("0"),
    )


def outcome(
    order_ref: str,
    *,
    price: str,
    quantity: str,
    quote: str,
    status: str,
    first_fill: int | None,
    side: str = "BUY",
    order_type: str = "LIMIT_MAKER",
    stop_price: str = "0",
) -> ExecutionOutcome:
    return ExecutionOutcome(
        order_ref=order_ref,
        symbol="SOLUSDT",
        side=side,
        intent_created_at_ms=1000,
        order_price=Decimal(price),
        original_quantity=Decimal("1"),
        cumulative_quantity=Decimal(quantity),
        cumulative_quote=Decimal(quote),
        final_status=status,
        first_fill_received_at_ms=first_fill,
        final_received_at_ms=3000,
        commission_quote=(
            Decimal(quote) * (
                Decimal("0.00075")
                if order_type == "LIMIT_MAKER" else Decimal("0.001")
            )
            if Decimal(quantity) > 0 else Decimal("0")
        ),
        order_type=order_type,
        stop_price=Decimal(stop_price),
    )


def test_replay_validation_matches_real_fill_and_cancel(tmp_path):
    events = [
        MarketEvent(
            ts_ms=1000,
            bids=(BookLevel(Decimal("99"), Decimal("10")),),
            asks=(BookLevel(Decimal("100"), Decimal("10")),),
        ),
        MarketEvent(
            ts_ms=2000,
            bids=(BookLevel(Decimal("99"), Decimal("10")),),
            asks=(BookLevel(Decimal("100"), Decimal("10")),),
            trades=((Decimal("99"), Decimal("11"), "SELL"),),
        ),
        MarketEvent(
            ts_ms=3000,
            bids=(BookLevel(Decimal("99"), Decimal("10")),),
            asks=(BookLevel(Decimal("100"), Decimal("10")),),
        ),
    ]
    report = validate_replay_outcomes(
        events,
        [
            outcome(
                "filled", price="99", quantity="1", quote="99",
                status="FILLED", first_fill=2000,
            ),
            outcome(
                "stop", price="99", quantity="1", quote="99",
                status="FILLED", first_fill=2000, side="SELL",
                order_type="STOP_LOSS_LIMIT", stop_price="99",
            ),
        ],
        calibration(),
        minimum_orders=2,
    )

    assert report.ready is True
    assert report.fill_classification_accuracy == Decimal("1")
    assert report.fill_ratio_mae == Decimal("0")
    assert report.price_error_bps_mae == Decimal("0")
    assert report.latency_error_ms_mae == Decimal("0")
    assert report.fee_error_quote_mae == Decimal("0")
    assert report.slippage_error_bps_mae == Decimal("0")
    assert report.queue_model == "L2_PRICE_LEVEL_FIFO_PROXY"
    assert report.exact_l3 is False
    assert report.actual_limit_maker_filled_orders == 1
    assert report.actual_stop_limit_filled_orders == 1

    path = tmp_path / "validation.json"
    write_replay_validation(path, report)
    assert read_replay_validation(path) == report


def test_replay_validation_fails_closed_without_empirical_coverage():
    events = [
        MarketEvent(
            ts_ms=timestamp,
            bids=(BookLevel(Decimal("99"), Decimal("10")),),
            asks=(BookLevel(Decimal("100"), Decimal("10")),),
        )
        for timestamp in (1000, 3000)
    ]
    report = validate_replay_outcomes(
        events,
        [
            outcome(
                "cancelled", price="90", quantity="0", quote="0",
                status="CANCELED", first_fill=None,
            )
        ],
        calibration(),
        minimum_orders=10,
    )

    assert report.ready is False
    assert "covered orders 1 < 10" in report.reasons
    assert "matched fill prices unavailable" in report.reasons
    assert "matched fill latencies unavailable" in report.reasons
