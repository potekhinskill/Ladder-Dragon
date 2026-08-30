from pathlib import Path
import json
import sqlite3

import pytest

from ladder_dragon.strategy.prediction.episode_semantics import (
    V23_EXECUTION_MODEL_RULE,
    v23_evidence_semantics_fingerprint,
)
from ladder_dragon.strategy.prediction import v23_confirmation as subject
from ladder_dragon.strategy.prediction.historical_policy import fingerprint


def parameters():
    return {
        "candidate_rule_version": 8,
        "execution_model_rule": V23_EXECUTION_MODEL_RULE,
        "evidence_semantics_fingerprint": v23_evidence_semantics_fingerprint(),
        "entry_gap_bps": "48",
        "target_return": "0.008",
        "stop_limit_distance": "0.01035",
        "stop_trigger_offset_pct": "0.0015",
        "evidence_notional_quote": "6",
        "entry_ttl_sec": 5400,
        "maximum_holding_min": 360,
        "regime_policy": "range_only",
        "entry_veto_rule": {
            "prefill_price_change_max_bps": "-10",
            "prefill_signed_trade_flow_max": "-0.2",
            "prefill_order_flow_imbalance_max": "-0.3",
            "cancel_latency_ms": 1000,
            "signal_window_ms": 300000,
            "selection_artifact_sha256": "a" * 64,
        },
    }


def manifest():
    return {
        "experiment_id": "sol-v23",
        "candidate_parameters": parameters(),
        "candidate_fingerprint": "b" * 64,
        "selected_variant": "v23_maker_ttl90_gap48_tp80_veto",
        "confirmation_start_ts_ms": 1000,
    }


def policy():
    return {
        "entry_gap_bps": "48",
        "take_profit_bps": "80",
        "stop_limit_bps": "103.5",
        "stop_trigger_bps": "88.5",
        "notional_quote": "6",
        "entry_ttl_ms": 5_400_000,
        "holding_ms": 21_600_000,
        "veto_price_bps": "-10",
        "veto_signed_flow": "-0.2",
        "veto_ofi": "-0.3",
        "cancel_latency_ms": 1000,
        "signal_window_ms": 300000,
        "allowed_regimes": ["RANGE"],
    }


def row():
    return {
        "episode_id": "veto-1",
        "started_at_ms": 2000,
        "terminal_at_ms": 3000,
        "terminal_reason": "ENTRY_VETO",
        "start_regime": "RANGE",
        "entry_price": "100",
        "take_profit_price": "100.8",
        "stop_trigger_price": "99.115",
        "stop_limit_price": "98.965",
        "quantity": "0.06",
        "entry_filled_quantity": "0",
        "entry_notional_quote": "0",
        "exit_filled_quantity": "0",
        "gross_pnl_quote": "0",
        "net_pnl_quote": "0",
        "fee_quote": "0",
        "fee_schedule": {
            "maker_buy_fee_pct": "0.001",
            "maker_sell_fee_pct": "0.001",
            "taker_buy_fee_pct": "0.001",
            "taker_sell_fee_pct": "0.001",
        },
        "stop_triggered": False,
        "stop_limit_unfilled": False,
        "panic_veto": False,
        "maximum_favorable_excursion_pct": "0",
        "maximum_adverse_excursion_pct": "0",
        "excursion_evidence_available": False,
        "eligible_for_promotion": True,
        "censored": False,
    }


def test_import_uses_only_disjoint_post_cutoff_exact_reports(monkeypatch):
    report = {
        "start_ts_ms": 2000,
        "end_ts_ms": 4000,
        "cutoff_ts_ms": 4000,
        "source_sha256s": ["c" * 64],
        "model_source_sha256s": {"model.py": "f" * 64},
        "policy": policy(),
    }
    recorded = []
    monkeypatch.setattr(subject, "_active_v23_manifest", lambda store: manifest())
    monkeypatch.setattr(
        subject, "_selection_artifact",
        lambda store, params: {
            "source_archive_sha256s": ["d" * 64],
            "model_source_sha256s": {"model.py": "f" * 64},
        },
    )
    monkeypatch.setattr(subject, "load_historical_report", lambda path, sha: report)
    monkeypatch.setattr(subject, "validate_historical_replay_report", lambda *a, **k: None)
    monkeypatch.setattr(subject, "historical_report_rows", lambda report, name: [row()])
    monkeypatch.setattr(
        subject, "record_completed_episode",
        lambda store, spec, result: recorded.append((spec, result)),
    )

    result = subject.import_v23_confirmation_reports(
        object(), [(Path("report.json"), "e" * 64)]
    )

    assert result["status"] == "IMPORTED"
    assert result["episode_count"] == 1
    assert recorded[0][0].evidence_semantics_fingerprint == (
        v23_evidence_semantics_fingerprint()
    )
    assert recorded[0][1].terminal_reason == "ENTRY_VETO"


def test_import_rejects_selection_source_reuse(monkeypatch):
    source = "c" * 64
    report = {
        "start_ts_ms": 2000,
        "end_ts_ms": 4000,
        "cutoff_ts_ms": 4000,
        "source_sha256s": [source],
        "model_source_sha256s": {"model.py": "f" * 64},
        "policy": policy(),
    }
    monkeypatch.setattr(subject, "_active_v23_manifest", lambda store: manifest())
    monkeypatch.setattr(
        subject, "_selection_artifact",
        lambda store, params: {
            "source_archive_sha256s": [source],
            "model_source_sha256s": {"model.py": "f" * 64},
        },
    )
    monkeypatch.setattr(subject, "load_historical_report", lambda path, sha: report)
    monkeypatch.setattr(subject, "validate_historical_replay_report", lambda *a, **k: None)

    with pytest.raises(ValueError, match="reuses an evidence source"):
        subject.import_v23_confirmation_reports(
            object(), [(Path("report.json"), "e" * 64)]
        )


def test_selection_artifact_uses_the_row_owned_identity(tmp_path):
    database = tmp_path / "prediction.sqlite3"
    payload = {
        "selected_rule": {"contract_version": "v3"},
        "source_archive_sha256s": ["c" * 64],
    }
    identity = fingerprint(payload)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """CREATE TABLE prediction_entry_veto_selection_artifacts (
                   artifact_sha256 TEXT, symbol TEXT, artifact_json TEXT
               )"""
        )
        connection.execute(
            "INSERT INTO prediction_entry_veto_selection_artifacts VALUES(?,?,?)",
            (identity, "SOLUSDT", json.dumps(payload)),
        )

    class Store:
        def _connect(self):
            return sqlite3.connect(database)

    selected = subject.load_v23_selection_artifact(
        Store(), {"entry_veto_rule": {"selection_artifact_sha256": identity}}
    )

    assert selected == payload
