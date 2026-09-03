from decimal import Decimal
import sys

import pytest

from ladder_dragon.execution.execution_latency import ExecutionOutcome
from ladder_dragon.strategy.market_replay import (
    BookLevel,
    MarketEvent,
    ReplayCalibration,
)
from ladder_dragon.strategy.replay_validation import (
    ReplayValidationSession,
    read_replay_validation,
    validate_replay_outcomes,
    validate_replay_sessions,
    write_replay_validation,
    replay_acceptance_reasons,
)
from ladder_dragon.strategy.replay_policy import (
    PRODUCTION_REPLAY_ACCEPTANCE_POLICY,
)
from ladder_dragon.verification import replay_sessions


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
    created_at_ms: int = 1000,
    final_at_ms: int = 3000,
) -> ExecutionOutcome:
    return ExecutionOutcome(
        order_ref=order_ref,
        symbol="SOLUSDT",
        side=side,
        intent_created_at_ms=created_at_ms,
        order_price=Decimal(price),
        original_quantity=Decimal("1"),
        cumulative_quantity=Decimal(quantity),
        cumulative_quote=Decimal(quote),
        final_status=status,
        first_fill_received_at_ms=first_fill,
        final_received_at_ms=final_at_ms,
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


def test_stop_limit_trigger_does_not_add_second_client_latency():
    delayed = ReplayCalibration(
        **{**calibration().__dict__, "latency_ms_p95": 100}
    )
    events = [
        MarketEvent(
            ts_ms=1000,
            bids=(BookLevel(Decimal("100"), Decimal("10")),),
            asks=(BookLevel(Decimal("101"), Decimal("10")),),
        ),
        MarketEvent(
            ts_ms=1100,
            bids=(BookLevel(Decimal("99"), Decimal("10")),),
            asks=(BookLevel(Decimal("100"), Decimal("10")),),
            trades=((Decimal("99"), Decimal("1"), "SELL"),),
        ),
    ]

    report = validate_replay_outcomes(
        events,
        [
            outcome(
                "stop",
                price="99",
                quantity="1",
                quote="99",
                status="FILLED",
                first_fill=1100,
                side="SELL",
                order_type="STOP_LOSS_LIMIT",
                stop_price="99",
                final_at_ms=1100,
            )
        ],
        delayed,
        minimum_orders=1,
    )

    assert report.replay_filled_orders == 1
    assert report.fill_classification_accuracy == Decimal("1")
    assert report.fill_ratio_mae == Decimal("0")


def test_stop_limit_does_not_use_actual_fill_to_accept_early_trigger():
    delayed = ReplayCalibration(
        **{**calibration().__dict__, "latency_ms_p95": 100}
    )
    events = [
        MarketEvent(
            ts_ms=1000,
            bids=(BookLevel(Decimal("100"), Decimal("10")),),
            asks=(BookLevel(Decimal("101"), Decimal("10")),),
        ),
        MarketEvent(
            ts_ms=1050,
            bids=(BookLevel(Decimal("99"), Decimal("10")),),
            asks=(BookLevel(Decimal("100"), Decimal("10")),),
            trades=((Decimal("99"), Decimal("1"), "SELL"),),
        ),
        MarketEvent(
            ts_ms=1200,
            bids=(BookLevel(Decimal("100"), Decimal("10")),),
            asks=(BookLevel(Decimal("101"), Decimal("10")),),
        ),
    ]

    report = validate_replay_outcomes(
        events,
        [
            outcome(
                "stop",
                price="99",
                quantity="1",
                quote="99",
                status="FILLED",
                first_fill=1050,
                side="SELL",
                order_type="STOP_LOSS_LIMIT",
                stop_price="99",
                final_at_ms=1200,
            )
        ],
        delayed,
        minimum_orders=1,
    )

    assert report.replay_filled_orders == 0
    assert report.fill_classification_accuracy == Decimal("0")
    assert report.fill_ratio_mae == Decimal("1")
    assert "matched fill prices unavailable" in report.reasons


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


def test_replay_sessions_never_bridge_an_archive_gap():
    first = calibration()
    second = ReplayCalibration(
        **{
            **first.__dict__,
            "archive_sha256": "b" * 64,
            "first_ts_ms": 5000,
            "last_ts_ms": 7000,
        }
    )
    first_events = tuple(
        MarketEvent(
            ts_ms=timestamp,
            bids=(BookLevel(Decimal("99"), Decimal("10")),),
            asks=(BookLevel(Decimal("100"), Decimal("10")),),
        )
        for timestamp in (1000, 3000)
    )
    second_events = tuple(
        MarketEvent(
            ts_ms=timestamp,
            bids=(BookLevel(Decimal("99"), Decimal("10")),),
            asks=(BookLevel(Decimal("100"), Decimal("10")),),
        )
        for timestamp in (5000, 7000)
    )
    report = validate_replay_sessions(
        [
            ReplayValidationSession(first_events, first),
            ReplayValidationSession(second_events, second),
        ],
        [
            outcome(
                "crosses-gap",
                price="99",
                quantity="0",
                quote="0",
                status="CANCELED",
                first_fill=None,
                created_at_ms=2500,
                final_at_ms=5500,
            )
        ],
        minimum_orders=1,
    )

    assert report.covered_orders == 0
    assert report.excluded_orders == 1
    assert report.archive_sha256s == ("a" * 64, "b" * 64)


def test_replay_sessions_reject_duplicate_archive_identity():
    events = (
        MarketEvent(
            ts_ms=1000,
            bids=(BookLevel(Decimal("99"), Decimal("10")),),
            asks=(BookLevel(Decimal("100"), Decimal("10")),),
        ),
        MarketEvent(
            ts_ms=3000,
            bids=(BookLevel(Decimal("99"), Decimal("10")),),
            asks=(BookLevel(Decimal("100"), Decimal("10")),),
        ),
    )

    with pytest.raises(ValueError, match="archive identity"):
        validate_replay_sessions(
            [
                ReplayValidationSession(events, calibration()),
                ReplayValidationSession(events, calibration()),
            ],
            [],
        )


def test_production_policy_rejects_omitted_orders_and_weakened_thresholds():
    report = validate_replay_outcomes(
        [
            MarketEvent(
                ts_ms=timestamp,
                bids=(BookLevel(Decimal("99"), Decimal("10")),),
                asks=(BookLevel(Decimal("100"), Decimal("10")),),
            )
            for timestamp in (1000, 3000)
        ],
        [
            outcome(
                "outside", price="99", quantity="0", quote="0",
                status="CANCELED", first_fill=None,
                created_at_ms=500, final_at_ms=3500,
            )
        ],
        calibration(),
        minimum_orders=1,
    )
    assert report.excluded_orders == 1
    assert "excluded orders 1 != 0" in report.reasons
    reasons = replay_acceptance_reasons(
        report, PRODUCTION_REPLAY_ACCEPTANCE_POLICY
    )
    assert "covered orders 0 < 10" in reasons
    assert report.acceptance_policy_sha256 != (
        PRODUCTION_REPLAY_ACCEPTANCE_POLICY.fingerprint
    )


def test_replay_import_requires_a_complete_confirmed_identity(monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "validate_replay_sessions",
        "--session", "archive.jsonl", "calibration.json",
        "--execution-log", "execution.ndjson",
        "--maker-buy-fee-pct", "0.001",
        "--maker-sell-fee-pct", "0.001",
        "--taker-buy-fee-pct", "0.001",
        "--taker-sell-fee-pct", "0.001",
        "--prediction-db", "prediction.sqlite3",
    ])

    with pytest.raises(SystemExit, match="all identity arguments"):
        replay_sessions.main()


def test_replay_cli_separates_order_sessions_from_calibration_context():
    args = replay_sessions.build_parser().parse_args([
        "--session", "order.jsonl", "order.calibration.json",
        "--calibration-context", "low.calibration.json",
        "--calibration-context", "high.calibration.json",
        "--execution-log", "execution.ndjson",
        "--maker-buy-fee-pct", "0.001",
        "--maker-sell-fee-pct", "0.001",
        "--taker-buy-fee-pct", "0.001",
        "--taker-sell-fee-pct", "0.001",
    ])

    assert args.session == [["order.jsonl", "order.calibration.json"]]
    assert [path.name for path in args.calibration_context] == [
        "low.calibration.json", "high.calibration.json",
    ]
