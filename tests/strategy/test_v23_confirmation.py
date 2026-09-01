from pathlib import Path
import json
import sqlite3
import hashlib

import pytest

from ladder_dragon.strategy.prediction.episode_semantics import (
    V23_EXECUTION_MODEL_RULE,
    execution_model_contract,
    v23_evidence_semantics_contract,
    v23_evidence_semantics_fingerprint,
)
from ladder_dragon.strategy.prediction import v23_confirmation as subject
from ladder_dragon.strategy.prediction.historical_policy import fingerprint
from ladder_dragon.strategy.depth_segments import atomic_json


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
    model = execution_model_contract()
    return {
        "symbol": "SOLUSDT",
        "entry_gap_bps": "48",
        "take_profit_bps": "80",
        "stop_limit_bps": "103.5",
        "stop_trigger_bps": "88.5",
        "notional_quote": "6",
        "entry_ttl_ms": 5_400_000,
        "holding_ms": 21_600_000,
        "cadence_ms": 300_000,
        "latency_ms": int(model["latency_ms"]),
        "veto_price_bps": "-10",
        "veto_signed_flow": "-0.2",
        "veto_ofi": "-0.3",
        "cancel_latency_ms": 1000,
        "signal_window_ms": 300000,
        "stop_grace_ms": int(model["stop_unfilled_grace_ms"]),
        "market_impact_bps": str(model["emergency_market_impact_bps"]),
        "maximum_event_gap_ms": int(model["maximum_event_gap_ms"]),
        "classifier_fingerprint": fingerprint(
            v23_evidence_semantics_contract()["regime_classifier"]
        ),
        "panic_source_fingerprint": "c" * 64,
        "allowed_regimes": ["RANGE"],
        "maximum_attempts": 1,
    }


def row(started_at_ms=2000, episode_id="veto-1"):
    return {
        "episode_id": episode_id,
        "started_at_ms": started_at_ms,
        "terminal_at_ms": started_at_ms + 500,
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


def request(source_prefix="c"):
    paths = []
    for index, start in enumerate((2_000, 4_000, 6_000)):
        paths.append({
            "archives": [{
                "path": f"segment-{index}.jsonl",
                "sha256": chr(ord(source_prefix) + index) * 64,
            }],
            "start_ms": start,
            "entry_end_ms": start + 1_000,
            "end_ms": start + 1_500,
            "cutoff_ms": start + 1_500,
        })
    return {
        "request_schema_version": 2,
        "cohort_contract": subject.PATH_COHORT_CONTRACT,
        "stability_block_index": 0,
        "policy": policy(),
        "paths": paths,
    }


def report_for_request(payload):
    windows = [{
        "start_ts_ms": path["start_ms"],
        "entry_end_ts_ms": path["entry_end_ms"],
        "end_ts_ms": path["end_ms"],
        "cutoff_ts_ms": path["cutoff_ms"],
        "source_sha256s": [
            archive["sha256"] for archive in path["archives"]
        ],
    } for path in payload["paths"]]
    return {
        "request_sha256": fingerprint(payload),
        "cohort_contract": payload["cohort_contract"],
        "stability_block_index": payload["stability_block_index"],
        "start_ts_ms": windows[0]["start_ts_ms"],
        "end_ts_ms": windows[-1]["end_ts_ms"],
        "cutoff_ts_ms": windows[-1]["cutoff_ts_ms"],
        "path_windows": windows,
        "source_sha256s": [
            source for window in windows for source in window["source_sha256s"]
        ],
        "model_source_sha256s": {"model.py": "f" * 64},
        "policy": payload["policy"],
    }


def write_request(tmp_path, payload):
    path = tmp_path / "request.json"
    atomic_json(path, payload)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_import_uses_only_disjoint_post_cutoff_exact_reports(
    tmp_path, monkeypatch
):
    pinned = request()
    report = report_for_request(pinned)
    request_path, request_sha = write_request(tmp_path, pinned)
    recorded = []
    monkeypatch.setattr(subject, "_active_v23_manifest", lambda store: manifest())
    monkeypatch.setattr(
        subject, "_selection_artifact",
        lambda store, params: {
            "source_archive_sha256s": ["9" * 64],
            "model_source_sha256s": {"model.py": "f" * 64},
        },
    )
    monkeypatch.setattr(subject, "load_historical_report", lambda path, sha: report)
    monkeypatch.setattr(subject, "validate_historical_replay_report", lambda *a, **k: None)
    monkeypatch.setattr(
        subject, "historical_report_rows",
        lambda report, name: [
            row(2_100, "veto-1"), row(4_100, "veto-2"),
            row(6_100, "veto-3"),
        ],
    )
    monkeypatch.setattr(
        subject,
        "confirmation_report",
        lambda *_args, **_kwargs: {
            "confirmation_progress": {
                "method": "ANYTIME_VALID",
                "status": "COLLECTING",
            }
        },
    )
    monkeypatch.setattr(
        subject, "record_completed_episode",
        lambda store, spec, result: (
            recorded.append((spec, result)) is None
        ),
    )

    result = subject.import_v23_confirmation_reports(
        object(), [(
            Path("report.json"), "e" * 64, request_path, request_sha,
        )]
    )

    assert result["status"] == "IMPORTED"
    assert result["episode_count"] == 3
    assert result["processed_immutable_path_count"] == 3
    assert result["imported_block_count"] == 1
    assert result["statistically_evaluated_block_count"] == 1
    assert recorded[0][0].evidence_semantics_fingerprint == (
        v23_evidence_semantics_fingerprint()
    )
    assert recorded[0][0].episode_id.startswith("v23-confirmation:")
    assert recorded[0][1].terminal_reason == "ENTRY_VETO"


def test_import_rejects_selection_source_reuse(tmp_path, monkeypatch):
    source = "c" * 64
    pinned = request()
    report = report_for_request(pinned)
    request_path, request_sha = write_request(tmp_path, pinned)
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
            object(), [(
                Path("report.json"), "e" * 64, request_path, request_sha,
            )]
        )


def test_report_must_match_the_complete_request():
    pinned = request()
    report = report_for_request(pinned)

    subject._validate_report_request(report, pinned)

    changed_policy = dict(report)
    changed_policy["policy"] = {
        **report["policy"], "stop_grace_ms": 1,
    }
    with pytest.raises(ValueError, match="differs from request"):
        subject._validate_report_request(changed_policy, pinned)

    changed_window = dict(report)
    changed_window["path_windows"] = [
        *report["path_windows"][:-1],
        {**report["path_windows"][-1], "end_ts_ms": 9_000},
    ]
    with pytest.raises(ValueError, match="sources differ from request"):
        subject._validate_report_request(changed_window, pinned)


def test_policy_rejects_a_self_consistent_request_with_missing_latency():
    incomplete = policy()
    incomplete.pop("latency_ms")

    with pytest.raises(ValueError, match="policy schema differs"):
        subject._validate_policy(incomplete, parameters())


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


def test_directory_import_accepts_only_cohort_owned_reports(
    tmp_path, monkeypatch
):
    root = tmp_path / ".historical-replay"
    reports = root / "confirmation-reports"
    requests = root / "confirmation-requests"
    blocks = root / "confirmation-blocks"
    reports.mkdir(parents=True)
    requests.mkdir()
    blocks.mkdir()
    cohort_body = {
        "schema_version": subject.V23_CONFIRMATION_COHORT_SCHEMA_VERSION,
        "mode": "SHADOW_CONFIRMATION",
        "apply_allowed": False,
    }
    cohort = {**cohort_body, "cohort_sha256": fingerprint(cohort_body)}
    atomic_json(root / "confirmation-cohort.json", cohort)
    request = globals()["request"]()
    request_identity = fingerprint(request)
    request_path = requests / f"{request_identity}.json"
    atomic_json(request_path, request)
    atomic_json(blocks / f"00-{request_identity}.json", {
        "schema_version": subject.V23_CONFIRMATION_BLOCK_SCHEMA_VERSION,
        "cohort_sha256": cohort["cohort_sha256"],
        "block_index": 0,
        "request_sha256": request_identity,
        "source_archive_sha256s": sorted(
            archive["sha256"]
            for path in request["paths"]
            for archive in path["archives"]
        ),
        "previous_block_sha256": None,
    })
    report_path = reports / f"{hashlib.sha256(request_path.read_bytes()).hexdigest()}.json"
    atomic_json(report_path, {"start_ts_ms": 2_000})
    captured = []
    monkeypatch.setattr(subject, "find_active_v23_manifest", lambda _store: manifest())
    monkeypatch.setattr(
        subject, "import_v23_confirmation_reports",
        lambda _store, rows: captured.extend(rows) or {"status": "IMPORTED"},
    )

    result = subject.import_v23_confirmation_directory(object(), reports)

    assert result["status"] == "IMPORTED"
    assert captured[0][0] == report_path
    assert captured[0][2] == request_path

    rogue = reports / ("f" * 64 + ".json")
    atomic_json(rogue, {"start_ts_ms": 3_000})
    with pytest.raises(ValueError, match="not cohort-owned"):
        subject.import_v23_confirmation_directory(object(), reports)
