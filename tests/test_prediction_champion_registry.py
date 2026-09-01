from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from ladder_dragon.strategy.prediction import PredictionShadowStore
from ladder_dragon.strategy.prediction import champion_registry
from ladder_dragon.execution.worker.champion_preflight import (
    champion_ladder,
    require_live_champion,
)
from ladder_dragon.strategy.prediction.experiment_lifecycle import (
    canonical_json,
    sha256_json,
    supersede_experiment,
)
from ladder_dragon.strategy.prediction.episode_semantics import (
    evidence_semantics_fingerprint,
    v23_evidence_semantics_fingerprint,
)


REPORT_SHA = "b" * 64
SOURCE_COMMIT = "c" * 40


def _confirmed_manifest(
    store: PredictionShadowStore,
    *,
    experiment_id: str,
    generation: str,
    candidate_fingerprint: str,
) -> dict[str, object]:
    manifest = {
        "schema_version": 3,
        "experiment_id": experiment_id,
        "generation": generation,
        "symbol": "BTCUSDT",
        "selected_variant": f"{generation}_maker_ttl60_gap8p4",
        "candidate_fingerprint": candidate_fingerprint,
        "criteria": {
            "regime_activation_policy": "exact_preregistered_execution_regimes_v4",
            "eligible_regimes": ["RANGE"],
        },
        "candidate_parameters": {
            "candidate_rule_version": 7,
            "evidence_notional_quote": "6",
            "evidence_semantics_fingerprint": evidence_semantics_fingerprint(),
            "entry_gap_bps": "8.4",
            "entry_ttl_sec": 3600,
            "entry_enabled": True,
            "entry_order_policy": "LIMIT_MAKER",
            "take_profit_order_policy": "LIMIT_MAKER",
            "stop_order_policy": "STOP_LOSS_LIMIT",
            "execution_model_rule": "verified_replay_oco_v1",
            "execution_model_promotion_ready": True,
            "fee_schedule": {
                "maker_buy_fee_pct": "0.0007",
                "maker_sell_fee_pct": "0.0008",
                "taker_buy_fee_pct": "0.001",
                "taker_sell_fee_pct": "0.0011",
                "provenance": "BINANCE_ACCOUNT_COMMISSION_MAX_V1",
            },
            "target_return": "0.0096",
            "stop_limit_distance": "0.01",
            "stop_trigger_offset_pct": "0.0015",
            "maximum_holding_min": 360,
            "primary_horizon_min": 360,
        },
    }
    manifest_sha = sha256_json(manifest)
    with store._connect() as connection:
        connection.execute(
            """INSERT INTO prediction_experiment_manifests
               (experiment_id,schema_version,generation,symbol,selected_variant,
                selection_experiment_id,selection_end_ts_ms,
                confirmation_start_ts_ms,manifest_json,manifest_sha256,
                created_at_ms)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                experiment_id,
                3,
                generation,
                "BTCUSDT",
                manifest["selected_variant"],
                f"selection:{generation}:BTCUSDT",
                1,
                2,
                canonical_json(manifest),
                manifest_sha,
                3,
            ),
        )
        connection.executemany(
            """INSERT INTO prediction_experiment_transitions
               (experiment_id,from_status,to_status,changed_at_ms,reason)
               VALUES(?,?,?,?,?)""",
            (
                (experiment_id, "SELECTION", "FROZEN", 3, "test freeze"),
                (experiment_id, "FROZEN", "CONFIRMING", 4, "test confirmation"),
                (experiment_id, "CONFIRMING", "CONFIRMED", 5, "test pass"),
            ),
        )
    return {**manifest, "manifest_sha256": manifest_sha}


def _activate(
    store: PredictionShadowStore,
    monkeypatch: pytest.MonkeyPatch,
    manifest: dict[str, object],
    *,
    previous: str | None,
    activated_at_ms: int,
) -> dict[str, object]:
    confirmation = {
        "report_sha256": REPORT_SHA,
        "promotion_eligible": True,
        "confirmation_progress": {
            "status": "PASS",
            "confirmed_execution_regimes": ["RANGE"],
        },
    }
    monkeypatch.setattr(
        champion_registry,
        "confirmation_report",
        lambda *_args, **_kwargs: confirmation,
    )
    policy = champion_registry.execution_policy_from_manifest(
        manifest,
        confirmation=confirmation,
        maximum_order_notional_usdt="6",
        maximum_inventory_usdt="6",
    )
    return champion_registry.activate_champion(
        store,
        experiment_id=str(manifest["experiment_id"]),
        expected_report_sha256=REPORT_SHA,
        expected_manifest_sha256=str(manifest["manifest_sha256"]),
        expected_execution_policy_fingerprint=sha256_json(policy),
        expected_previous_activation_id=previous,
        maximum_order_notional_usdt="6",
        maximum_inventory_usdt="6",
        product_version="2.20.226",
        source_commit=SOURCE_COMMIT,
        execution_halt_confirmed=True,
        activated_at_ms=activated_at_ms,
    )


def test_execution_policy_rejects_configured_fee_evidence(tmp_path: Path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    manifest = _confirmed_manifest(
        store,
        experiment_id="btc-v14-confirmed",
        generation="v14",
        candidate_fingerprint="a" * 64,
    )
    manifest["candidate_parameters"]["fee_schedule"]["provenance"] = (
        "CONFIGURED_SYMMETRIC_V1"
    )

    with pytest.raises(ValueError, match="fees are not authoritative"):
        champion_registry.execution_policy_from_manifest(
            manifest,
            confirmation={
                "confirmation_progress": {
                    "status": "PASS",
                    "confirmed_execution_regimes": ["RANGE"],
                }
            },
            maximum_order_notional_usdt="6",
            maximum_inventory_usdt="6",
        )


def test_first_activation_is_restart_safe_and_exact(tmp_path: Path, monkeypatch):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    manifest = _confirmed_manifest(
        store,
        experiment_id="btc-v13-confirmed",
        generation="v13",
        candidate_fingerprint="a" * 64,
    )

    activated = _activate(
        store, monkeypatch, manifest, previous=None, activated_at_ms=10
    )
    restarted = PredictionShadowStore(store.path)
    loaded = champion_registry.active_champion(restarted, symbol="BTCUSDT")

    assert loaded == activated
    assert loaded["champion_version"] == 1
    assert loaded["execution_policy"]["entry_gap_bps"] == "8.4"
    assert loaded["execution_policy"]["entry_ttl_sec"] == 3600
    assert loaded["execution_policy"]["target_return"] == "0.0096"
    assert loaded["execution_policy"]["maximum_order_notional_usdt"] == "6"
    assert loaded["execution_policy"]["runtime_mutation_policy"] == "protective_only"
    assert loaded["execution_policy"]["allowed_entry_regimes"] == [
        "RANGE",
    ]
    assert champion_registry.champion_allows_regime(
        loaded["execution_policy"], "RANGE"
    ) is True
    assert champion_registry.champion_allows_regime(
        loaded["execution_policy"], "TREND_DOWN"
    ) is False


def test_v23_policy_binds_confirmed_volatility_scope(tmp_path, monkeypatch):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    manifest = _confirmed_manifest(
        store,
        experiment_id="btc-v23-confirmed",
        generation="v23",
        candidate_fingerprint="a" * 64,
    )
    parameters = manifest["candidate_parameters"]
    parameters["candidate_rule_version"] = 8
    parameters["evidence_semantics_fingerprint"] = (
        v23_evidence_semantics_fingerprint()
    )
    parameters["entry_veto_rule"] = {
        "contract_version": "l2_adverse_selection_cancel_v4",
        "prefill_price_change_max_bps": "-10",
        "prefill_signed_trade_flow_max": "-0.2",
        "prefill_order_flow_imbalance_max": "-0.3",
        "cancel_latency_ms": 1_000,
        "signal_window_ms": 300_000,
        "selection_artifact_sha256": "d" * 64,
    }
    volatility_policy = {
        "policy_sha256": "e" * 64,
        "low_max_bps": "0.34",
        "high_min_bps": "0.67",
            "volatility_metric": champion_registry.VOLATILITY_METRIC,
            "volatility_event_population": (
                champion_registry.VOLATILITY_EVENT_POPULATION
            ),
        "measurement_window_ms": (
            champion_registry.VOLATILITY_MEASUREMENT_WINDOW_MS
        ),
        "publish_interval_ms": (
            champion_registry.VOLATILITY_PUBLISH_INTERVAL_MS
        ),
    }
    scope = {
        "scope_sha256": "f" * 64,
        "confirmed_buckets": ["low", "normal"],
        "blocked_buckets": ["high"],
    }
    monkeypatch.setattr(champion_registry, "verify_volatility_policy", lambda _value: True)
    monkeypatch.setattr(champion_registry, "verify_volatility_scope", lambda *_args, **_kwargs: True)

    policy = champion_registry.execution_policy_from_manifest(
        manifest,
        confirmation={
            "confirmation_progress": {
                "status": "PASS",
                "confirmed_execution_regimes": ["RANGE"],
            },
            "execution_model_gate": {
                "volatility_policy": volatility_policy,
                "confirmed_volatility_scope": scope,
            },
        },
        maximum_order_notional_usdt="6",
        maximum_inventory_usdt="6",
    )

    assert policy["allowed_volatility_buckets"] == ["low", "normal"]
    assert policy["volatility_measurement_window_ms"] == 55 * 60_000
    assert policy["volatility_publish_interval_ms"] == 5 * 60_000
    assert champion_registry.champion_allows_volatility(policy, "normal") is True
    assert champion_registry.champion_allows_volatility(policy, "high") is False


def test_activation_rejects_caps_that_differ_from_preview(tmp_path: Path, monkeypatch):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    manifest = _confirmed_manifest(
        store,
        experiment_id="btc-v13-confirmed",
        generation="v13",
        candidate_fingerprint="a" * 64,
    )
    confirmation = {
        "report_sha256": REPORT_SHA,
        "promotion_eligible": True,
        "confirmation_progress": {
            "status": "PASS",
            "confirmed_execution_regimes": ["RANGE"],
        },
    }
    monkeypatch.setattr(
        champion_registry,
        "confirmation_report",
        lambda *_args, **_kwargs: confirmation,
    )
    reviewed = champion_registry.execution_policy_from_manifest(
        manifest,
        confirmation=confirmation,
        maximum_order_notional_usdt="6",
        maximum_inventory_usdt="6",
    )

    with pytest.raises(ValueError, match="caps must equal the evidence notional"):
        champion_registry.activate_champion(
            store,
            experiment_id=str(manifest["experiment_id"]),
            expected_report_sha256=REPORT_SHA,
            expected_manifest_sha256=str(manifest["manifest_sha256"]),
            expected_execution_policy_fingerprint=sha256_json(reviewed),
            expected_previous_activation_id=None,
            maximum_order_notional_usdt="60",
            maximum_inventory_usdt="180",
            product_version="2.20.226",
            source_commit=SOURCE_COMMIT,
            execution_halt_confirmed=True,
        )


def test_activation_without_execution_halt_fails_closed(tmp_path: Path, monkeypatch):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    manifest = _confirmed_manifest(
        store,
        experiment_id="btc-v13-confirmed",
        generation="v13",
        candidate_fingerprint="a" * 64,
    )
    monkeypatch.setattr(
        champion_registry,
        "confirmation_report",
        lambda *_args, **_kwargs: {
            "report_sha256": REPORT_SHA,
            "promotion_eligible": True,
        },
    )

    with pytest.raises(ValueError, match="confirmed execution halt"):
        champion_registry.activate_champion(
            store,
            experiment_id=str(manifest["experiment_id"]),
            expected_report_sha256=REPORT_SHA,
            expected_manifest_sha256=str(manifest["manifest_sha256"]),
            expected_execution_policy_fingerprint="d" * 64,
            expected_previous_activation_id=None,
            maximum_order_notional_usdt="6",
            maximum_inventory_usdt="6",
            product_version="2.20.226",
            source_commit=SOURCE_COMMIT,
            execution_halt_confirmed=False,
        )


def test_replacement_requires_reviewed_previous_and_preserves_history(
    tmp_path: Path, monkeypatch
):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    first_manifest = _confirmed_manifest(
        store,
        experiment_id="btc-v13-confirmed",
        generation="v13",
        candidate_fingerprint="a" * 64,
    )
    first = _activate(
        store, monkeypatch, first_manifest, previous=None, activated_at_ms=10
    )
    second_manifest = _confirmed_manifest(
        store,
        experiment_id="btc-v14-confirmed",
        generation="v14",
        candidate_fingerprint="d" * 64,
    )

    with pytest.raises(ValueError, match="changed before activation"):
        _activate(
            store,
            monkeypatch,
            second_manifest,
            previous="wrong-activation",
            activated_at_ms=20,
        )

    second = _activate(
        store,
        monkeypatch,
        second_manifest,
        previous=str(first["activation_id"]),
        activated_at_ms=20,
    )
    history = champion_registry.list_champions(store, symbol="BTCUSDT")

    assert second["champion_version"] == 2
    assert second["previous_activation_id"] == first["activation_id"]
    assert [row["status"] for row in history] == ["SUPERSEDED", "ACTIVE"]
    assert len({row["champion_fingerprint"] for row in history}) == 2


def test_activation_rows_are_immutable(tmp_path: Path, monkeypatch):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    manifest = _confirmed_manifest(
        store,
        experiment_id="btc-v13-confirmed",
        generation="v13",
        candidate_fingerprint="a" * 64,
    )
    activated = _activate(
        store, monkeypatch, manifest, previous=None, activated_at_ms=10
    )
    with store._connect() as connection:
        indexes = {
            str(row[1]): bool(row[2])
            for row in connection.execute(
                "PRAGMA index_list(prediction_champion_activations)"
            )
        }
    assert indexes["prediction_champion_single_root"] is True
    assert indexes["prediction_champion_single_replacement"] is True

    with store._connect() as connection, pytest.raises(
        sqlite3.IntegrityError, match="immutable"
    ):
        connection.execute(
            """UPDATE prediction_champion_activations
               SET champion_version=2 WHERE activation_id=?""",
            (activated["activation_id"],),
        )


def test_worker_identity_verification_rejects_a_different_fingerprint(
    tmp_path: Path, monkeypatch
):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    manifest = _confirmed_manifest(
        store,
        experiment_id="btc-v13-confirmed",
        generation="v13",
        candidate_fingerprint="a" * 64,
    )
    activated = _activate(
        store, monkeypatch, manifest, previous=None, activated_at_ms=10
    )

    with pytest.raises(ValueError, match="champion_fingerprint differs"):
        champion_registry.verify_active_champion(
            store,
            symbol="BTCUSDT",
            activation_id=str(activated["activation_id"]),
            champion_fingerprint="f" * 64,
            execution_policy_fingerprint=str(
                activated["execution_policy_fingerprint"]
            ),
        )


def test_worker_verification_rejects_a_superseded_champion_experiment(
    tmp_path: Path, monkeypatch
):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    manifest = _confirmed_manifest(
        store,
        experiment_id="btc-v13-confirmed",
        generation="v13",
        candidate_fingerprint="a" * 64,
    )
    activated = _activate(
        store, monkeypatch, manifest, previous=None, activated_at_ms=10
    )

    supersede_experiment(
        store,
        experiment_id=str(manifest["experiment_id"]),
        reason="test runtime revocation",
    )

    assert champion_registry.active_champion(store, symbol="BTCUSDT") is not None
    with pytest.raises(ValueError, match="SUPERSEDED, not CONFIRMED"):
        champion_registry.verify_active_champion(
            store,
            symbol="BTCUSDT",
            activation_id=str(activated["activation_id"]),
            champion_fingerprint=str(activated["champion_fingerprint"]),
            execution_policy_fingerprint=str(
                activated["execution_policy_fingerprint"]
            ),
        )


def test_direct_worker_rebuilds_policy_and_clamps_caps(tmp_path: Path, monkeypatch):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    manifest = _confirmed_manifest(
        store,
        experiment_id="btc-v13-confirmed",
        generation="v13",
        candidate_fingerprint="a" * 64,
    )
    activated = _activate(
        store, monkeypatch, manifest, previous=None, activated_at_ms=10
    )
    monkeypatch.setenv("PREDICTION_SHADOW_DB", str(store.path))
    monkeypatch.setenv(
        "BOT_CHAMPION_ACTIVATION_ID", str(activated["activation_id"])
    )
    monkeypatch.setenv(
        "BOT_CHAMPION_FINGERPRINT", str(activated["champion_fingerprint"])
    )
    monkeypatch.setenv(
        "BOT_CHAMPION_POLICY_FINGERPRINT",
        str(activated["execution_policy_fingerprint"]),
    )
    monkeypatch.setenv("BOT_CHAMPION_PROBATION_ALLOWED", "YES")
    monkeypatch.setenv("BOT_CAP_PER_ORDER", "100")
    monkeypatch.setenv("RISK_MANAGED_INVENTORY_HARD_CAP_BTCUSDT", "200")
    state = SimpleNamespace(os=os, _compat_float=float)
    args = SimpleNamespace(
        symbol="BTCUSDT",
        tp1=0.5,
        tp2=0.6,
        sl=-0.5,
        stop_limit_offset_pct=0.2,
        target_buy_per_symbol=7,
        buy_limit_maker=False,
        sell_limit_maker=False,
        bear_buy_shift_pct=0.2,
        bear_cap_scale=2.0,
        buy_vwap_discount=0.1,
        buy_vwap_discount_scale=3.0,
    )

    loaded = require_live_champion(state, args)
    ladder = champion_ladder(state, loaded, "60000")

    assert os.environ["BOT_CAP_PER_ORDER"] == "6"
    assert os.environ["RISK_MANAGED_INVENTORY_HARD_CAP_BTCUSDT"] == "6"
    assert args.tp1 == pytest.approx(0.0096)
    assert args.tp2 == pytest.approx(0.0096)
    assert args.sl == pytest.approx(-0.01)
    assert args.stop_limit_offset_pct == pytest.approx(0.0015)
    assert os.environ["BOT_MAX_HOLDING_MINUTES"] == "360"
    assert args.target_buy_per_symbol == 1
    assert args.buy_limit_maker is True
    assert args.sell_limit_maker is True
    assert args.bear_buy_shift_pct == 0
    assert args.bear_cap_scale == 1
    assert args.buy_vwap_discount is None
    assert args.buy_vwap_discount_scale is None
    assert ladder == pytest.approx([59350.104, 59949.6, 60525.11616])
