from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import time

from ladder_dragon.strategy.market_replay import BookLevel, MarketEvent
from ladder_dragon.strategy.prediction.episode_evidence import (
    episode_confirmation_criteria,
    load_episode_results,
    model_validation_status,
    record_episode_result,
    record_episode_start,
    record_model_validation,
    recover_interrupted_episodes,
    sequential_episode_report,
)
from ladder_dragon.strategy.prediction.experiment_lifecycle import (
    confirmation_report,
    freeze_preselected_episode_experiment,
)
from ladder_dragon.strategy.prediction.experiments import build_shadow_variants
from ladder_dragon.strategy.prediction.models import TradePlan
from ladder_dragon.strategy.prediction.execution_episode import (
    ExecutionEpisode,
    ExecutionEpisodeResult,
    ExecutionEpisodeSpec,
)
from ladder_dragon.strategy.prediction.runtime import PredictionShadowStore
from ladder_dragon.strategy.prediction.episode_semantics import (
    evidence_semantics_fingerprint,
)


D = Decimal


def _event(
    timestamp: int,
    *,
    bid: str = "99",
    ask: str = "100",
    trades: tuple[tuple[Decimal, Decimal, str], ...] = (),
) -> MarketEvent:
    return MarketEvent(
        timestamp,
        bids=(BookLevel(D(bid), D("1")),),
        asks=(BookLevel(D(ask), D("1")),),
        trades=trades,
    )


def _spec(episode_id: str = "episode-1") -> ExecutionEpisodeSpec:
    return ExecutionEpisodeSpec(
        episode_id=episode_id,
        symbol="SOLUSDT",
        generation="v18",
        variant_id="v18_maker_ttl90_gap48",
        candidate_fingerprint="a" * 64,
        execution_model_rule="minute_l2_fifo_oco_gap_v1",
        start_regime="RANGE",
        started_at_ms=0,
        entry_deadline_ms=60_000,
        diagnostic_at_ms=300_000,
        primary_deadline_ms=360_000,
        entry_price=D("99"),
        take_profit_price=D("101"),
        stop_trigger_price=D("95"),
        stop_limit_price=D("94"),
        quantity=D("1"),
        maker_buy_fee_pct=D("0.001"),
        maker_sell_fee_pct=D("0.001"),
        taker_sell_fee_pct=D("0.002"),
        stop_unfilled_grace_ms=60_000,
        maximum_event_gap_ms=120_000,
    )


def _promotion_variant():
    baseline = TradePlan(
        entry_price=D("99"),
        take_profit_price=D("100"),
        stop_price=D("97"),
        notional_quote=D("10"),
        fee_pct=D("0.001"),
        slippage_pct=D("0.0005"),
        maker_buy_fee_pct=D("0.0007"),
        maker_sell_fee_pct=D("0.0008"),
        taker_buy_fee_pct=D("0.001"),
        taker_sell_fee_pct=D("0.0011"),
        fee_provenance="BINANCE_ACCOUNT_COMMISSION_MAX_V1",
    )
    return build_shadow_variants(
        market_price=D("100"),
        baseline_plan=baseline,
        required_edge_pct=D("0.001"),
        regime="RANGE",
        generation="v18",
        symbol="SOLUSDT",
    )[0]


def _v19_promotion_variant():
    baseline = _promotion_variant().baseline_plan
    return build_shadow_variants(
        market_price=D("100"),
        baseline_plan=baseline,
        required_edge_pct=D("0.001"),
        regime="RANGE",
        generation="v19",
        symbol="SOLUSDT",
    )[0]


def test_episode_models_partial_maker_fill_and_exact_tp_fees():
    episode = ExecutionEpisode(_spec(), _event(0))

    assert episode.process(
        _event(60_000, trades=((D("99"), D("1.5"), "SELL"),))
    ) is None
    result = episode.process(
        _event(120_000, bid="100", ask="101", trades=((D("101"), D("0.5"), "BUY"),))
    )

    assert result is not None
    assert result.terminal_reason == "TAKE_PROFIT"
    assert result.entry_fill_fraction == D("0.5")
    assert result.gross_pnl_quote == D("1.0")
    assert result.total_fee_quote == D("0.1000")
    assert result.net_pnl_quote == D("0.9000")
    assert result.eligible_for_promotion is True


def test_episode_models_stop_trigger_gap_and_market_flatten():
    episode = ExecutionEpisode(_spec(), _event(0, bid="98", ask="100"))
    assert episode.process(
        _event(30_000, bid="99", trades=((D("99"), D("1"), "SELL"),))
    ) is None
    assert episode.process(_event(
        90_000,
        bid="90",
        ask="91",
        trades=((D("90"), D("1"), "SELL"),),
    )) is None
    result = episode.process(_event(150_000, bid="89", ask="90"))

    assert result is not None
    assert result.terminal_reason == "STOP_LIMIT_GAP_FLATTEN"
    assert result.stop_triggered is True
    assert result.stop_limit_unfilled is True
    assert result.exit_filled_quantity == D("1")
    assert result.net_pnl_quote < D("-10")


def test_episode_records_a_missed_fill_without_inventing_a_trade():
    episode = ExecutionEpisode(_spec(), _event(0))
    result = episode.process(_event(60_000))

    assert result is not None
    assert result.terminal_reason == "MISSED_FILL"
    assert result.entry_filled_quantity == 0
    assert result.net_pnl_quote == 0
    assert result.eligible_for_promotion is True


def test_panic_flatten_is_financial_evidence_and_veto_is_a_no_fill_attempt():
    filled = ExecutionEpisode(_spec("panic-filled"), _event(0))
    assert filled.process(
        _event(30_000, trades=((D("99"), D("2"), "SELL"),))
    ) is None
    flattened = filled.process(_event(60_000, bid="90"), panic_active=True)
    assert flattened is not None
    assert flattened.terminal_reason == "PANIC_FLATTEN"
    assert flattened.net_pnl_quote < 0
    assert flattened.eligible_for_promotion is True

    empty = ExecutionEpisode(_spec("panic-empty"), _event(0))
    veto = empty.process(_event(30_000), panic_active=True)
    assert veto is not None
    assert veto.terminal_reason == "PANIC_VETO"
    assert veto.entry_filled_quantity == 0
    assert veto.net_pnl_quote == 0
    assert veto.eligible_for_promotion is True


def test_v19_net_expectancy_rejects_frequent_wins_with_larger_panic_losses():
    rows = []
    for index in range(12):
        loss = index >= 10
        rows.append(replace(
            _result(index, "-1" if loss else "0.1"),
            generation="v19",
            variant_id="v19_maker_ttl90_gap48",
            execution_model_rule="minute_l2_fifo_oco_gap_v2",
            terminal_reason="PANIC_FLATTEN" if loss else "TAKE_PROFIT",
            panic_veto=loss,
            evidence_semantics_fingerprint=evidence_semantics_fingerprint(),
        ))
    report = sequential_episode_report(
        rows,
        criteria=episode_confirmation_criteria(
            "episode_net_expectancy_alpha_spending_v3"
        ),
    )
    assert report["financial_outcomes"] == 12
    assert report["panic_flatten_outcomes"] == 2
    assert D(report["net_pnl_quote"]) < 0
    assert report["status"] != "PASS"
    assert report["approved"] is False


def _result(index: int, pnl: str) -> ExecutionEpisodeResult:
    return ExecutionEpisodeResult(
        episode_id=f"episode-{index}",
        symbol="SOLUSDT",
        generation="v18",
        variant_id="v18_maker_ttl90_gap48",
        candidate_fingerprint="a" * 64,
        execution_model_rule="minute_l2_fifo_oco_gap_v1",
        start_regime=("RANGE", "TREND_UP", "TREND_DOWN")[index % 3],
        started_at_ms=index * 400_000,
        terminal_at_ms=index * 400_000 + 300_000,
        terminal_reason="TAKE_PROFIT" if D(pnl) > 0 else "TIME_STOP_360M",
        entry_filled_quantity=D("1"),
        entry_fill_fraction=D("1"),
        entry_notional_quote=D("10"),
        exit_filled_quantity=D("1"),
        gross_pnl_quote=D(pnl),
        net_pnl_quote=D(pnl),
        total_fee_quote=D("0.01"),
        adverse_selection_pct=D("0.001"),
        diagnostic_300m_net_pnl_quote=D(pnl),
        stop_triggered=False,
        stop_limit_unfilled=False,
        panic_veto=False,
        eligible_for_promotion=True,
    )


def test_preregistered_alpha_spending_can_pass_at_the_first_strong_look():
    report = sequential_episode_report(
        (_result(index, "0.2") for index in range(12)),
        criteria=episode_confirmation_criteria(
            "episode_combined_alpha_spending_v2"
        ),
    )

    assert report["alpha_total"] == "0.050"
    assert report["passed_at_episode"] == 12
    assert report["status"] == "PASS"
    assert report["approved"] is True
    assert D(report["power_analysis"]["maximum_look_power"]) >= D("0.80")


def test_early_sign_boundary_does_not_freeze_incomplete_regime_evidence():
    rows = [
        replace(_result(index, "0.2"), start_regime="RANGE")
        for index in range(12)
    ]
    rows.extend(
        replace(_result(index, "0.2"), start_regime="TREND_UP")
        for index in range(12, 24)
    )

    report = sequential_episode_report(
        rows,
        criteria=episode_confirmation_criteria(
            "episode_combined_alpha_spending_v2"
        ),
    )

    assert report["looks"][0]["passed"] is False
    assert report["passed_at_episode"] == 24
    assert report["confirmed_execution_regimes"] == ["RANGE", "TREND_UP"]


def test_exhausted_preregistered_looks_are_ready_to_reject_immediately():
    report = sequential_episode_report(
        (_result(index, "-0.2") for index in range(43)),
        criteria=episode_confirmation_criteria(
            "episode_combined_alpha_spending_v2"
        ),
    )

    assert report["next_sequential_look"] is None
    assert report["status"] == "READY_TO_REJECT"
    assert report["approved"] is False


def test_legacy_episode_manifest_is_blocked_instead_of_using_local_defaults():
    report = sequential_episode_report(
        (_result(index, "0.2") for index in range(12)),
        criteria={"min_independent_samples": 52},
    )

    assert report["status"] == "BLOCKED"
    assert report["approved"] is False


def test_episode_store_is_append_only_and_restart_evidence_is_excluded(tmp_path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    spec = _spec("interrupted")
    record_episode_start(store, spec)

    assert recover_interrupted_episodes(
        store, symbol="SOLUSDT", now_ms=10_000
    ) == 1
    rows = load_episode_results(
        store,
        symbol="SOLUSDT",
        generation="v18",
        variant_id="v18_maker_ttl90_gap48",
    )
    assert rows[0].terminal_reason == "PROCESS_RESTART_DATA_GAP"
    assert rows[0].eligible_for_promotion is False

    with store._connect() as connection:
        try:
            connection.execute(
                "UPDATE prediction_execution_episode_results "
                "SET terminal_at_ms=11 WHERE episode_id='interrupted'"
            )
        except Exception as exc:  # SQLite exposes the trigger as an IntegrityError.
            assert "immutable" in str(exc)
        else:
            raise AssertionError("episode result update unexpectedly succeeded")


def test_episode_start_and_terminal_round_trip(tmp_path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    spec = _spec("complete")
    result = _result(1, "0.2")
    result = ExecutionEpisodeResult(**{
        **result.__dict__,
        "episode_id": "complete",
        "started_at_ms": spec.started_at_ms,
    })
    record_episode_start(store, spec)
    record_episode_result(store, result)

    loaded = load_episode_results(
        store,
        symbol="SOLUSDT",
        generation="v18",
        variant_id="v18_maker_ttl90_gap48",
    )
    assert loaded == [result]


def test_model_validation_requires_filled_maker_and_stop_limit_orders(tmp_path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    freeze_preselected_episode_experiment(
        store,
        experiment_id="validation-experiment",
        generation="v19",
        symbol="SOLUSDT",
        selected_variant=_v19_promotion_variant(),
        horizons_min=(300, 360),
        product_version="2.20.229",
        source_commit="b" * 40,
    )
    report = {
        "schema_version": 6,
        "ready": True,
        "reasons": [],
        "archive_sha256": "c" * 64,
        "covered_orders": 10,
        "excluded_orders": 0,
        "actual_filled_orders": 2,
        "replay_filled_orders": 2,
        "fill_classification_accuracy": "1",
        "fill_ratio_mae": "0",
        "price_error_bps_mae": "0",
        "latency_error_ms_mae": "0",
        "fee_error_quote_mae": "0",
        "slippage_error_bps_mae": "0",
        "queue_model": "L2_PRICE_LEVEL_FIFO_PROXY",
        "exact_l3": False,
        "actual_limit_maker_filled_orders": 1,
        "actual_stop_limit_filled_orders": 0,
        "maker_buy_fee_pct": "0.0007",
        "maker_sell_fee_pct": "0.0008",
        "taker_buy_fee_pct": "0.001",
        "taker_sell_fee_pct": "0.0011",
        "replay_readiness": {
            "ready": True,
            "reasons": [],
            "archive_count": 3,
            "span_days": "2",
            "regimes": ["low", "normal", "high"],
            "measured_latency_archives": 1,
            "execution_sample_count": 10,
            "book_event_count": 1000,
            "trade_count": 1000,
            "validation_report_count": 1,
            "validated_order_count": 10,
        },
    }
    try:
        record_model_validation(
            store,
            symbol="SOLUSDT",
            execution_model_rule="minute_l2_fifo_oco_gap_v2",
            experiment_id="validation-experiment",
            report=report,
        )
    except ValueError as exc:
        assert "promotion-ready" in str(exc)
    else:
        raise AssertionError("validation without a stop fill unexpectedly passed")

    report["actual_stop_limit_filled_orders"] = 1
    record_model_validation(
        store,
        symbol="SOLUSDT",
        execution_model_rule="minute_l2_fifo_oco_gap_v2",
        experiment_id="validation-experiment",
        report=report,
    )
    assert model_validation_status(
        store,
        symbol="SOLUSDT",
        execution_model_rule="minute_l2_fifo_oco_gap_v2",
    )["status"] == "PASS"
    with store._connect() as connection:
        try:
            connection.execute(
                "DELETE FROM prediction_execution_model_validations"
            )
        except Exception as exc:  # SQLite exposes the trigger as an IntegrityError.
            assert "append-only" in str(exc)
        else:
            raise AssertionError("model validation delete unexpectedly succeeded")


def test_preselected_manifest_excludes_pre_freeze_episode_results(tmp_path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    variant = _promotion_variant()
    frozen_at = int(time.time() * 1000)
    manifest = freeze_preselected_episode_experiment(
        store,
        experiment_id="sol-v18-live-confirmation",
        generation="v18",
        symbol="SOLUSDT",
        selected_variant=variant,
        horizons_min=(300, 360),
        product_version="2.20.229",
        source_commit="b" * 40,
        frozen_at_ms=frozen_at,
    )
    pre_freeze_spec = replace(
        _spec("pre-freeze"),
        candidate_fingerprint=str(manifest["candidate_fingerprint"]),
        started_at_ms=frozen_at - 1_000,
        entry_deadline_ms=frozen_at + 60_000,
        diagnostic_at_ms=frozen_at + 300_000,
        primary_deadline_ms=frozen_at + 360_000,
    )
    pre_freeze_result = replace(
        _result(99, "0.2"),
        episode_id="pre-freeze",
        candidate_fingerprint=str(manifest["candidate_fingerprint"]),
        started_at_ms=frozen_at - 1_000,
        terminal_at_ms=frozen_at + 1_000,
    )
    record_episode_start(store, pre_freeze_spec)
    record_episode_result(store, pre_freeze_result)

    assert manifest["current_status"] == "CONFIRMING"
    assert manifest["historical_evidence_reused_for_confirmation"] is False
    report = confirmation_report(
        store, experiment_id="sol-v18-live-confirmation"
    )
    assert report["confirmation_status"] == "IN_PROGRESS"
    assert report["confirmation_progress"]["eligible_terminal_episodes"] == 0
    assert report["execution_model_gate"]["status"] == "BLOCKED"
    assert report["promotion_eligible"] is False
