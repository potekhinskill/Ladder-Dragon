from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from product_version import __version__

from bin.prediction_experiment import (
    _freeze_horizons,
    _parser,
    _selection_variants,
    _source_commit,
)
from ladder_dragon.strategy.prediction import (
    PredictionFeatures,
    PredictionShadowStore,
    TradePlan,
    predict_distribution,
)
from ladder_dragon.strategy.prediction.experiment_lifecycle import (
    selection_experiment_id,
    variant_fingerprints,
)
from ladder_dragon.strategy.prediction.experiments import (
    EXPERIMENT_HORIZONS_MIN,
    SHADOW_GENERATION,
    build_shadow_variants,
    configured_entry_gap_bps,
)


D = Decimal


def test_champion_activation_does_not_accept_a_caller_halt_path():
    arguments = [
        "champion-activate", "experiment-id",
        "--report-sha256", "a" * 64,
        "--manifest-sha256", "b" * 64,
        "--expected-execution-policy-fingerprint", "c" * 64,
        "--expected-previous-activation-id", "NONE",
        "--maximum-order-usdt", "6",
        "--maximum-inventory-usdt", "18",
        "--confirm", "ACTIVATE",
    ]

    parsed = _parser().parse_args(arguments)
    assert not hasattr(parsed, "halt_file")
    with pytest.raises(SystemExit):
        _parser().parse_args([*arguments, "--halt-file", "/tmp/decoy"])


def test_entry_veto_freeze_requires_an_exact_cutoff_and_confirmation():
    parsed = _parser().parse_args([
        "entry-veto-freeze", "sol-v22-live-confirmation",
        "--cutoff-ts-ms", "123456", "--confirm", "FREEZE-VETO",
    ])

    assert parsed.cutoff_ts_ms == 123456
    assert parsed.confirm == "FREEZE-VETO"
    with pytest.raises(SystemExit):
        _parser().parse_args([
            "entry-veto-report", "sol-v22-live-confirmation",
        ])


def test_freeze_horizons_are_symbol_generation_scoped():
    assert _freeze_horizons("v14", "SOLUSDT") == (300, 360)
    assert _freeze_horizons("v12", "ETHUSDT") == (300, 360)


def test_champion_source_requires_clean_published_annotated_release(monkeypatch):
    head = "d" * 40
    tag = f"v{__version__}"

    def completed(command, **_kwargs):
        key = tuple(command[1:])
        outputs = {
            ("rev-parse", "HEAD"): head,
            ("status", "--porcelain"): "",
            ("cat-file", "-t", f"refs/tags/{tag}"): "tag",
            ("rev-list", "-n", "1", tag): head,
            ("rev-parse", "origin/main"): head,
        }
        return type("Result", (), {"stdout": outputs[key]})()

    monkeypatch.setattr("bin.prediction_experiment.subprocess.run", completed)
    assert _source_commit() == head

    def dirty(command, **kwargs):
        result = completed(command, **kwargs)
        if tuple(command[1:]) == ("status", "--porcelain"):
            result.stdout = " M product_version.py"
        return result

    monkeypatch.setattr("bin.prediction_experiment.subprocess.run", dirty)
    with pytest.raises(RuntimeError, match="clean checkout"):
        _source_commit()


def test_configured_gap_rejects_unknown_semantics():
    with pytest.raises(ValueError, match="unavailable for generation"):
        configured_entry_gap_bps("v10_maker_ttl60_gap38", generation="v10")
    with pytest.raises(ValueError, match="unavailable for variant"):
        configured_entry_gap_bps("v11_maker_ttl60_gap99")
    assert configured_entry_gap_bps(
        "v11_maker_ttl60_gap42", generation="v11"
    ) == D("42")
    with pytest.raises(ValueError, match="requires a symbol"):
        configured_entry_gap_bps(
            "v12_maker_ttl60_gap46", generation="v12"
        )
    assert configured_entry_gap_bps(
        "v12_maker_ttl60_gap46", generation="v12", symbol="SOLUSDT"
    ) == D("46")
    assert configured_entry_gap_bps(
        "v12_maker_ttl60_gap22", generation="v12", symbol="ETHUSDT"
    ) == D("22")
    assert configured_entry_gap_bps(
        "v12_maker_ttl60_gap8p4", generation="v12", symbol="BTCUSDT"
    ) == D("8.40000")
    assert configured_entry_gap_bps(
        "v14_maker_ttl90_gap48", generation="v14", symbol="SOLUSDT"
    ) == D("48")


def _features(snapshot: int, price: str) -> PredictionFeatures:
    return PredictionFeatures(
        snapshot_ts_ms=snapshot,
        last_closed_bar_ts_ms=snapshot,
        price=D(price),
        ema_slope=D("0"),
        ema_distance_pct=D("0"),
        adx=D("12"),
        plus_di=D("20"),
        minus_di=D("20"),
        atr_pct=D("0.003"),
        atr_change_pct=D("0"),
        vwap_deviation_pct=D("0"),
        rsi=D("50"),
        macd_histogram_pct=D("0"),
        volume_ratio=D("1"),
        orderbook_imbalance=D("0"),
        orderbook_available=True,
        trade_flow_imbalance=D("0"),
        trade_flow_available=True,
        spread_bps=D("1"),
        depth_quote=D("10000"),
        acceleration=D("0"),
        executor_panic_active=False,
        executor_panic_hits=0,
        regime="RANGE",
    )


def test_selection_preview_uses_stable_configured_gap(tmp_path: Path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    baseline = TradePlan(
        entry_price=D("99.7"),
        take_profit_price=D("100.697"),
        stop_price=D("98.703"),
        notional_quote=D("10"),
        fee_pct=D("0.00075"),
        slippage_pct=D("0.0005"),
    )
    cohort = selection_experiment_id(SHADOW_GENERATION, "SOLUSDT")
    reconstructed = []
    for snapshot, market, rounded_entry in (
        (59_999, "100", D("99.5801")),
        (119_999, "101", D("100.5757")),
    ):
        features = _features(snapshot, market)
        configured = build_shadow_variants(
            market_price=D(market),
            baseline_plan=baseline,
            required_edge_pct=D("0.0096"),
            regime="RANGE",
        )[1]
        target_ratio = configured.plan.take_profit_price / configured.plan.entry_price
        stop_ratio = configured.plan.stop_price / configured.plan.entry_price
        rounded = replace(
            configured,
            plan=replace(
                configured.plan,
                entry_price=rounded_entry,
                take_profit_price=rounded_entry * target_ratio,
                stop_price=rounded_entry * stop_ratio,
            ),
        )
        candidate_fp, baseline_fp = variant_fingerprints(
            rounded,
            generation=SHADOW_GENERATION,
            horizons_min=EXPERIMENT_HORIZONS_MIN,
        )
        store.record(
            kind=rounded.kind,
            symbol="SOLUSDT",
            features=features,
            plan=rounded.plan,
            baseline_plan=baseline,
            predictions=predict_distribution(
                features,
                rounded.plan,
                [],
                horizons_min=EXPERIMENT_HORIZONS_MIN,
            ),
            algorithm_decision="stable selection preview regression",
            horizons_min=EXPERIMENT_HORIZONS_MIN,
            experiment_id=cohort,
            evidence_role="SELECTION",
            candidate_fingerprint=candidate_fp,
            baseline_fingerprint=baseline_fp,
        )
        reconstructed.append(_selection_variants(
            store,
            generation=SHADOW_GENERATION,
            symbol="SOLUSDT",
            cutoff=snapshot,
        )[0])

    assert [row.entry_gap_bps for row in reconstructed] == [D("48"), D("48")]
    assert [row.dimension for row in reconstructed] == [
        "maker_entry_ttl", "maker_entry_ttl",
    ]
    assert variant_fingerprints(
        reconstructed[0],
        generation=SHADOW_GENERATION,
        horizons_min=EXPERIMENT_HORIZONS_MIN,
    ) == variant_fingerprints(
        reconstructed[1],
        generation=SHADOW_GENERATION,
        horizons_min=EXPERIMENT_HORIZONS_MIN,
    )
