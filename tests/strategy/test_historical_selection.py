import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest

from ladder_dragon.strategy.prediction.historical_entry_replay import MODEL_CONTRACT
from ladder_dragon.strategy.prediction.historical_policy import fingerprint
from ladder_dragon.strategy.prediction.historical_selection import (
    _one_sided_binomial_lower_bound,
    historical_selection_artifact,
    import_historical_selection,
)
from ladder_dragon.strategy.prediction.runtime import PredictionShadowStore


def policy():
    return {
        "symbol": "SOLUSDT",
        "holding_ms": 21_600_000,
        "cancel_latency_ms": 1_000,
        "signal_window_ms": 300_000,
        "veto_price_bps": "-10",
        "veto_signed_flow": "-0.2",
        "veto_ofi": "-0.2",
    }


def test_exact_rate_bound_is_conservative_and_monotonic():
    seven = _one_sided_binomial_lower_bound(7, 12)
    twelve = _one_sided_binomial_lower_bound(12, 12)

    assert 0 < seven < Decimal("7") / Decimal("12")
    assert seven < twelve < Decimal("1")
    assert _one_sided_binomial_lower_bound(0, 12) == 0


def report(block: int):
    start = 1_000_000 + block * 100_000_000
    veto = []
    baseline = []
    for index in range(3):
        stamp = start + index * 21_600_000
        veto.append({
            "started_at_ms": stamp,
            "net_pnl_quote": "1",
            "censored": False,
            "terminal_reason": "ENTRY_VETO" if index < 2 else "TAKE_PROFIT",
            "entry_order_submitted": index >= 2,
            "signal_ts_ms": stamp if index < 2 else None,
            "cancel_effective_ts_ms": None,
        })
        baseline.append({
            "started_at_ms": stamp,
            "net_pnl_quote": "-1",
            "censored": False,
            "terminal_reason": "STOP_LIMIT",
            "entry_order_submitted": True,
            "signal_ts_ms": None,
            "cancel_effective_ts_ms": None,
        })
    body = {
        "schema_version": 1,
        "model_contract": MODEL_CONTRACT,
        "status": "COMPLETE_SELECTION_REPLAY",
        "mode": "SHADOW",
        "apply_allowed": False,
        "promotion_eligible": False,
        "selection_artifact_ready": False,
        "policy": policy(),
        "policy_sha256": fingerprint(policy()),
        "model_source_sha256s": {"model.py": "a" * 64},
        "source_sha256s": [format(block + 1, "064x")],
        "start_ts_ms": start,
        "entry_end_ts_ms": start + 64_800_000,
        "end_ts_ms": start + 86_401_000,
        "cutoff_ts_ms": start + 86_401_000,
        "summaries": {
            "baseline": {"opportunities": 10},
            "veto": {"opportunities": 10},
        },
        "episodes": {"baseline": baseline, "veto": veto},
    }
    return {**body, "report_sha256": fingerprint(body)}


def rehash(payload):
    payload["report_sha256"] = fingerprint({
        key: value for key, value in payload.items() if key != "report_sha256"
    })


def test_non_overlapping_historical_blocks_create_selection_only_artifact():
    result = historical_selection_artifact(
        [report(index) for index in range(4)],
        source_generation="v22",
        candidate_fingerprint="b" * 64,
        cutoff_ts_ms=500_000_000,
    )
    assert result["evidence_role"] == "HISTORICAL_SELECTION_ONLY"
    assert result["historical_evidence_reused_for_confirmation"] is False
    assert result["selection_metrics"]["independent_paths"] == 12
    assert result["selected_rule"]["cancel_latency_ms"] == 1000
    assert result["can_change_orders"] is False


def test_overlap_reuse_and_weak_policy_fail_closed():
    rows = [report(index) for index in range(4)]
    rows[1]["start_ts_ms"] = rows[0]["end_ts_ms"]
    rehash(rows[1])
    with pytest.raises(ValueError, match="overlap"):
        historical_selection_artifact(
            rows, source_generation="v22", candidate_fingerprint="b" * 64,
            cutoff_ts_ms=500_000_000,
        )


def test_pre_submit_veto_with_cancel_timing_is_rejected():
    rows = [report(index) for index in range(4)]
    veto = rows[0]["episodes"]["veto"][0]
    veto["cancel_effective_ts_ms"] = veto["signal_ts_ms"] + 1_000
    rehash(rows[0])

    with pytest.raises(ValueError, match="entry-veto timing is invalid"):
        historical_selection_artifact(
            rows,
            source_generation="v22",
            candidate_fingerprint="b" * 64,
            cutoff_ts_ms=500_000_000,
        )
    rows = [report(index) for index in range(4)]
    rows[1]["source_sha256s"] = rows[0]["source_sha256s"]
    rehash(rows[1])
    with pytest.raises(ValueError, match="reused"):
        historical_selection_artifact(
            rows, source_generation="v22", candidate_fingerprint="b" * 64,
            cutoff_ts_ms=500_000_000,
        )
    rows = [report(index) for index in range(4)]
    for row in rows[2]["episodes"]["veto"]:
        row["net_pnl_quote"] = "-100"
    rehash(rows[2])
    with pytest.raises(ValueError, match="incomplete"):
        historical_selection_artifact(
            rows, source_generation="v22", candidate_fingerprint="b" * 64,
            cutoff_ts_ms=500_000_000,
        )


def test_import_pins_file_hashes_and_keeps_artifact_immutable(tmp_path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    files = []
    for index in range(4):
        path = tmp_path / f"report-{index}.json"
        raw = json.dumps(report(index), sort_keys=True, separators=(",", ":")).encode()
        path.write_bytes(raw)
        files.append((path, hashlib.sha256(raw).hexdigest()))
    artifact = import_historical_selection(
        store,
        report_files=files,
        source_generation="v22",
        candidate_fingerprint="b" * 64,
        cutoff_ts_ms=500_000_000,
    )
    with store._connect() as connection:
        stored = connection.execute(
            "SELECT artifact_json FROM prediction_entry_veto_selection_artifacts WHERE artifact_sha256=?",
            (artifact["artifact_sha256"],),
        ).fetchone()
    assert stored is not None
    assert json.loads(stored[0])["evidence_role"] == "HISTORICAL_SELECTION_ONLY"
    files[0][0].write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="fingerprint"):
        import_historical_selection(
            store, report_files=files, source_generation="v22",
            candidate_fingerprint="c" * 64, cutoff_ts_ms=400_000_000,
        )


def test_report_file_paths_are_not_persisted(tmp_path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    files = []
    for index in range(4):
        path = tmp_path / f"private-path-{index}.json"
        raw = json.dumps(report(index), sort_keys=True, separators=(",", ":")).encode()
        path.write_bytes(raw)
        files.append((path, hashlib.sha256(raw).hexdigest()))
    import_historical_selection(
        store, report_files=files, source_generation="v22",
        candidate_fingerprint="d" * 64, cutoff_ts_ms=500_000_000,
    )
    assert b"private-path" not in store.path.read_bytes()
