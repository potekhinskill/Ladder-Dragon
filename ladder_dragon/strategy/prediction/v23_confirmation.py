# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: import disjoint exact L2 replay as immutable v23 confirmation evidence.
"""Fail-closed bridge from reviewed diff-depth reports to v23 episodes."""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
from typing import Mapping, Sequence

from ladder_dragon.strategy.prediction.episode_evidence import (
    record_completed_episode,
)
from ladder_dragon.strategy.prediction.episode_semantics import (
    V23_EXECUTION_MODEL_RULE,
    execution_model_contract,
    v23_evidence_semantics_contract,
    v23_evidence_semantics_fingerprint,
)
from ladder_dragon.strategy.prediction.execution_episode import (
    ExecutionEpisodeResult,
    ExecutionEpisodeSpec,
)
from ladder_dragon.strategy.prediction.experiment_lifecycle import (
    confirmation_report,
    list_experiments,
)
from ladder_dragon.strategy.prediction.historical_policy import fingerprint
from ladder_dragon.strategy.depth_segments import bounded_json
from ladder_dragon.strategy.prediction.historical_selection import (
    PATH_COHORT_CONTRACT,
    historical_report_rows,
    load_historical_report,
    validate_historical_replay_report,
)
from ladder_dragon.strategy.prediction.v23_contract import (
    V23_CONFIRMATION_BLOCK_SCHEMA_VERSION,
    V23_CONFIRMATION_COHORT_SCHEMA_VERSION,
    V23_CONFIRMATION_REQUEST_FIELDS,
    V23_CONFIRMATION_REQUEST_SCHEMA_VERSION,
)


D = Decimal
ZERO = D("0")
ONE = D("1")
MAXIMUM_CONFIRMATION_REPORTS = 128
MAXIMUM_CONFIRMATION_REQUEST_BYTES = 2 * 1024 * 1024

_POLICY_FIELDS = frozenset({
    "symbol", "entry_gap_bps", "take_profit_bps", "stop_limit_bps",
    "stop_trigger_bps", "notional_quote", "entry_ttl_ms", "holding_ms",
    "cadence_ms", "latency_ms", "cancel_latency_ms", "stop_grace_ms",
    "market_impact_bps", "maximum_event_gap_ms", "allowed_regimes",
    "classifier_fingerprint", "panic_source_fingerprint",
    "veto_price_bps", "veto_signed_flow", "veto_ofi",
    "signal_window_ms", "maximum_attempts",
})


def _decimal(value: object, *, field: str) -> Decimal:
    number = D(str(value))
    if not number.is_finite():
        raise ValueError(f"v23 confirmation {field} is invalid")
    return number


def find_active_v23_manifest(store) -> Mapping[str, object] | None:
    """Return the one valid confirming manifest, or None before v23 starts."""
    rows = [
        row for row in list_experiments(store, symbol="SOLUSDT")
        if row.get("generation") == "v23"
        and row.get("current_status") == "CONFIRMING"
    ]
    if not rows:
        return None
    if len(rows) != 1:
        raise ValueError("one confirming v23 manifest is required")
    manifest = rows[0]
    parameters = manifest.get("candidate_parameters")
    if (
        not isinstance(parameters, Mapping)
        or parameters.get("candidate_rule_version") != 8
        or parameters.get("execution_model_rule")
        != V23_EXECUTION_MODEL_RULE
        or parameters.get("evidence_semantics_fingerprint")
        != v23_evidence_semantics_fingerprint()
    ):
        raise ValueError("v23 manifest semantics are invalid")
    return manifest


def _active_v23_manifest(store) -> Mapping[str, object]:
    manifest = find_active_v23_manifest(store)
    if manifest is None:
        raise ValueError("one confirming v23 manifest is required")
    return manifest


def load_v23_selection_artifact(
    store, parameters: Mapping[str, object]
) -> dict:
    """Verify the row-owned hash of the immutable selection JSON body."""
    rule = parameters.get("entry_veto_rule")
    if not isinstance(rule, Mapping):
        raise ValueError("v23 confirmation veto rule is unavailable")
    identity = str(rule.get("selection_artifact_sha256") or "")
    with store._connect() as connection:
        row = connection.execute(
            """SELECT artifact_sha256,artifact_json FROM
                      prediction_entry_veto_selection_artifacts
               WHERE artifact_sha256=? AND symbol='SOLUSDT'""",
            (identity,),
        ).fetchone()
    if row is None:
        raise ValueError("v23 selection artifact is unavailable")
    payload = json.loads(str(row[1]))
    if not isinstance(payload, dict):
        raise ValueError("v23 selection artifact is invalid")
    if str(row[0]) != identity or fingerprint(payload) != identity:
        raise ValueError("v23 selection artifact identity differs")
    return payload


def _selection_artifact(store, parameters: Mapping[str, object]) -> dict:
    return load_v23_selection_artifact(store, parameters)


def _validate_policy(
    policy: Mapping[str, object], parameters: Mapping[str, object]
) -> None:
    rule = parameters["entry_veto_rule"]
    model = execution_model_contract()
    expected = {
        "symbol": "SOLUSDT",
        "entry_gap_bps": str(parameters["entry_gap_bps"]),
        "take_profit_bps": format(
            _decimal(parameters["target_return"], field="target") * D("10000"),
            "f",
        ),
        "stop_limit_bps": format(
            _decimal(parameters["stop_limit_distance"], field="stop")
            * D("10000"),
            "f",
        ),
        "stop_trigger_bps": format(
            (
                _decimal(parameters["stop_limit_distance"], field="stop")
                - _decimal(
                    parameters["stop_trigger_offset_pct"],
                    field="stop trigger",
                )
            ) * D("10000"),
            "f",
        ),
        "notional_quote": str(parameters["evidence_notional_quote"]),
        "entry_ttl_ms": int(parameters["entry_ttl_sec"]) * 1_000,
        "holding_ms": int(parameters["maximum_holding_min"]) * 60_000,
        "cadence_ms": 300_000,
        "latency_ms": int(model["latency_ms"]),
        "veto_price_bps": str(rule["prefill_price_change_max_bps"]),
        "veto_signed_flow": str(
            rule["prefill_signed_trade_flow_max"]
        ),
        "veto_ofi": str(rule["prefill_order_flow_imbalance_max"]),
        "cancel_latency_ms": int(rule["cancel_latency_ms"]),
        "signal_window_ms": int(rule["signal_window_ms"]),
        "stop_grace_ms": int(model["stop_unfilled_grace_ms"]),
        "market_impact_bps": str(model["emergency_market_impact_bps"]),
        "maximum_event_gap_ms": int(model["maximum_event_gap_ms"]),
        "maximum_attempts": 1,
    }
    decimal_fields = {
        "entry_gap_bps", "take_profit_bps", "stop_limit_bps",
        "stop_trigger_bps", "notional_quote", "veto_price_bps",
        "veto_signed_flow", "veto_ofi", "market_impact_bps",
    }
    if set(policy) != _POLICY_FIELDS:
        raise ValueError("v23 confirmation policy schema differs")
    for field, value in expected.items():
        differs = (
            _decimal(policy.get(field), field=field)
            != _decimal(value, field=field)
            if field in decimal_fields
            else policy.get(field) != value
        )
        if differs:
            raise ValueError("v23 confirmation policy differs from manifest")
    regimes = tuple(policy.get("allowed_regimes") or ())
    frozen_policy = str(parameters.get("regime_policy") or "")
    frozen = ("RANGE",) if frozen_policy == "range_only" else ()
    if not frozen or regimes != frozen:
        raise ValueError("v23 confirmation regimes differ from manifest")
    classifier = fingerprint(
        v23_evidence_semantics_contract()["regime_classifier"]
    )
    if policy.get("classifier_fingerprint") != classifier:
        raise ValueError("v23 confirmation classifier differs from manifest")
    if not re.fullmatch(
        r"[a-f0-9]{64}", str(policy.get("panic_source_fingerprint", ""))
    ):
        raise ValueError("v23 confirmation PANIC source is invalid")


def _load_confirmation_request(path: Path, expected_sha256: str) -> dict:
    """Load one exact request file before it can authorize report import."""
    if not re.fullmatch(r"[a-f0-9]{64}", str(expected_sha256)):
        raise ValueError("v23 confirmation request hash is invalid")
    raw = path.read_bytes()
    if len(raw) > MAXIMUM_CONFIRMATION_REQUEST_BYTES:
        raise ValueError("v23 confirmation request is oversized")
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("v23 confirmation request file differs")
    try:
        request = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("v23 confirmation request is invalid") from exc
    if not isinstance(request, dict):
        raise ValueError("v23 confirmation request must be an object")
    return request


def _validate_report_request(
    report: Mapping[str, object], request: Mapping[str, object]
) -> None:
    """Require one report to reproduce its complete immutable request."""
    if (
        set(request) != V23_CONFIRMATION_REQUEST_FIELDS
        or request.get("request_schema_version")
        != V23_CONFIRMATION_REQUEST_SCHEMA_VERSION
        or request.get("cohort_contract") != PATH_COHORT_CONTRACT
        or report.get("request_sha256") != fingerprint(dict(request))
        or report.get("cohort_contract") != request.get("cohort_contract")
        or report.get("stability_block_index")
        != request.get("stability_block_index")
        or report.get("policy") != request.get("policy")
    ):
        raise ValueError("v23 confirmation report differs from request")
    paths = request.get("paths")
    if not isinstance(paths, list) or len(paths) != 3:
        raise ValueError("v23 confirmation request paths are invalid")
    expected_windows = []
    expected_sources = []
    for path in paths:
        if not isinstance(path, Mapping) or set(path) != {
            "archives", "start_ms", "entry_end_ms", "end_ms", "cutoff_ms",
        }:
            raise ValueError("v23 confirmation request path is invalid")
        archives = path.get("archives")
        if not isinstance(archives, list) or not archives:
            raise ValueError("v23 confirmation request sources are invalid")
        sources = []
        for archive in archives:
            if (
                not isinstance(archive, Mapping)
                or set(archive) != {"path", "sha256"}
                or not isinstance(archive.get("path"), str)
                or not re.fullmatch(
                    r"[a-f0-9]{64}", str(archive.get("sha256", ""))
                )
            ):
                raise ValueError("v23 confirmation request source is invalid")
            sources.append(str(archive["sha256"]))
        expected_sources.extend(sources)
        expected_windows.append({
            "start_ts_ms": path.get("start_ms"),
            "entry_end_ts_ms": path.get("entry_end_ms"),
            "end_ts_ms": path.get("end_ms"),
            "cutoff_ts_ms": path.get("cutoff_ms"),
            "source_sha256s": sources,
        })
    if (
        len(expected_sources) != len(set(expected_sources))
        or report.get("source_sha256s") != expected_sources
        or report.get("path_windows") != expected_windows
    ):
        raise ValueError("v23 confirmation report sources differ from request")


def _episode_pair(
    row: Mapping[str, object], *, manifest: Mapping[str, object], report_sha: str
) -> tuple[ExecutionEpisodeSpec, ExecutionEpisodeResult]:
    parameters = manifest["candidate_parameters"]
    model = execution_model_contract()
    started = int(row["started_at_ms"])
    terminal = int(row["terminal_at_ms"])
    if terminal < started:
        raise ValueError("v23 confirmation terminal time is invalid")
    for field in (
        "stop_triggered", "stop_limit_unfilled", "panic_veto",
        "excursion_evidence_available", "eligible_for_promotion",
    ):
        if type(row.get(field)) is not bool:
            raise ValueError("v23 confirmation boolean field is invalid")
    quantity = _decimal(row["quantity"], field="quantity")
    entry_quantity = _decimal(
        row["entry_filled_quantity"], field="entry quantity"
    )
    fees = row.get("fee_schedule")
    if not isinstance(fees, Mapping):
        raise ValueError("v23 confirmation fee schedule is unavailable")
    episode_digest = hashlib.sha256(
        (
            f"v23-confirmation:{report_sha}:"
            f"{row.get('episode_id')}:{manifest['candidate_fingerprint']}"
        ).encode("utf-8")
    ).hexdigest()
    episode_id = f"v23-confirmation:{episode_digest}"
    semantics = v23_evidence_semantics_fingerprint()
    spec = ExecutionEpisodeSpec(
        episode_id=episode_id,
        symbol="SOLUSDT",
        generation="v23",
        variant_id=str(manifest["selected_variant"]),
        candidate_fingerprint=str(manifest["candidate_fingerprint"]),
        execution_model_rule=V23_EXECUTION_MODEL_RULE,
        evidence_semantics_fingerprint=semantics,
        start_regime=str(row["start_regime"]),
        started_at_ms=started,
        entry_deadline_ms=started + int(parameters["entry_ttl_sec"]) * 1_000,
        diagnostic_at_ms=started + 300 * 60_000,
        primary_deadline_ms=started + int(
            parameters["maximum_holding_min"]
        ) * 60_000,
        entry_price=_decimal(row["entry_price"], field="entry price"),
        take_profit_price=_decimal(
            row["take_profit_price"], field="target price"
        ),
        stop_trigger_price=_decimal(
            row["stop_trigger_price"], field="stop trigger"
        ),
        stop_limit_price=_decimal(
            row["stop_limit_price"], field="stop limit"
        ),
        quantity=quantity,
        maker_buy_fee_pct=_decimal(
            fees["maker_buy_fee_pct"], field="maker BUY fee"
        ),
        maker_sell_fee_pct=_decimal(
            fees["maker_sell_fee_pct"], field="maker SELL fee"
        ),
        taker_buy_fee_pct=_decimal(
            fees["taker_buy_fee_pct"], field="taker BUY fee"
        ),
        taker_sell_fee_pct=_decimal(
            fees["taker_sell_fee_pct"], field="taker SELL fee"
        ),
        latency_ms=int(model["latency_ms"]),
        market_impact_bps=D(str(model["emergency_market_impact_bps"])),
        stop_unfilled_grace_ms=int(model["stop_unfilled_grace_ms"]),
        maximum_event_gap_ms=int(model["maximum_event_gap_ms"]),
    )
    net = _decimal(row["net_pnl_quote"], field="net PnL")
    total_fee = _decimal(row["fee_quote"], field="fee")
    adverse = _decimal(
        row["maximum_adverse_excursion_pct"], field="adverse excursion"
    )
    result = ExecutionEpisodeResult(
        episode_id=episode_id,
        symbol="SOLUSDT",
        generation="v23",
        variant_id=str(manifest["selected_variant"]),
        candidate_fingerprint=str(manifest["candidate_fingerprint"]),
        execution_model_rule=V23_EXECUTION_MODEL_RULE,
        evidence_semantics_fingerprint=semantics,
        start_regime=str(row["start_regime"]),
        started_at_ms=started,
        terminal_at_ms=terminal,
        terminal_reason=str(row["terminal_reason"]),
        entry_filled_quantity=entry_quantity,
        entry_fill_fraction=(
            min(ONE, entry_quantity / quantity) if quantity > ZERO else ZERO
        ),
        entry_notional_quote=_decimal(
            row["entry_notional_quote"], field="entry notional"
        ),
        exit_filled_quantity=_decimal(
            row["exit_filled_quantity"], field="exit quantity"
        ),
        gross_pnl_quote=_decimal(row["gross_pnl_quote"], field="gross PnL"),
        net_pnl_quote=net,
        total_fee_quote=total_fee,
        adverse_selection_pct=adverse,
        diagnostic_300m_net_pnl_quote=None,
        stop_triggered=bool(row["stop_triggered"]),
        stop_limit_unfilled=bool(row["stop_limit_unfilled"]),
        panic_veto=bool(row["panic_veto"]),
        eligible_for_promotion=bool(row["eligible_for_promotion"]),
        maximum_favorable_excursion_pct=_decimal(
            row["maximum_favorable_excursion_pct"],
            field="favorable excursion",
        ),
        maximum_adverse_excursion_pct=adverse,
        excursion_evidence_available=bool(
            row["excursion_evidence_available"]
        ),
    )
    return spec, result


def import_v23_confirmation_reports(
    store,
    reports: Sequence[tuple[Path, str, Path, str]],
) -> dict[str, object]:
    """Import reviewed post-cutoff L2 reports; never import selection history."""
    if not 1 <= len(reports) <= MAXIMUM_CONFIRMATION_REPORTS:
        raise ValueError("v23 confirmation report count is invalid")
    manifest = _active_v23_manifest(store)
    parameters = manifest["candidate_parameters"]
    selection = _selection_artifact(store, parameters)
    selection_sources = set(selection.get("source_archive_sha256s") or ())
    loaded = []
    previous_end = int(manifest["confirmation_start_ts_ms"])
    observed_sources: set[str] = set()
    for path, expected_sha, request_path, request_sha in reports:
        request = _load_confirmation_request(request_path, request_sha)
        report = load_historical_report(path, expected_sha)
        validate_historical_replay_report(
            report, cutoff_ts_ms=int(report["cutoff_ts_ms"])
        )
        _validate_report_request(report, request)
        if int(report["start_ts_ms"]) <= previous_end:
            raise ValueError("v23 confirmation reports overlap or precede cutoff")
        previous_end = int(report["end_ts_ms"])
        sources = set(report["source_sha256s"])
        if selection_sources & sources or observed_sources & sources:
            raise ValueError("v23 confirmation reuses an evidence source")
        if (
            report.get("model_source_sha256s")
            != selection.get("model_source_sha256s")
        ):
            raise ValueError(
                "v23 confirmation implementation differs from selection"
            )
        observed_sources |= sources
        _validate_policy(report["policy"], parameters)
        windows = report.get("path_windows")
        rows = historical_report_rows(report, "veto")
        terminal_rows = [
            row for row in rows if row.get("censored") is not True
        ]
        if (
            not isinstance(windows, list)
            or len(windows) != len(terminal_rows)
            or any(
                not isinstance(window, Mapping)
                or not (
                    int(window["start_ts_ms"])
                    <= int(row["started_at_ms"])
                    < int(window["entry_end_ts_ms"])
                )
                for window, row in zip(windows, terminal_rows)
            )
        ):
            raise ValueError("v23 confirmation path trial cardinality differs")
        loaded.append((report, expected_sha, terminal_rows, len(windows)))
    created = imported_episodes = imported_paths = 0
    for report, report_sha, terminal_rows, path_count in loaded:
        imported_paths += path_count
        for row in terminal_rows:
            spec, result = _episode_pair(
                row, manifest=manifest, report_sha=report_sha
            )
            imported_episodes += 1
            created += int(record_completed_episode(store, spec, result))
    evaluation = confirmation_report(
        store, experiment_id=str(manifest["experiment_id"])
    )
    progress = evaluation.get("confirmation_progress")
    statistically_evaluated = bool(
        isinstance(progress, Mapping)
        and progress.get("method") != "UNSUPPORTED_FROZEN_CONTRACT"
        and progress.get("status") != "BLOCKED"
    )
    return {
        "schema_version": 1,
        "mode": "SHADOW_CONFIRMATION",
        "apply_allowed": False,
        "generation": "v23",
        "experiment_id": manifest["experiment_id"],
        "report_count": len(loaded),
        "processed_immutable_path_count": imported_paths,
        "episode_count": created,
        "created_episode_count": created,
        "imported_episode_count": imported_episodes,
        "imported_block_count": len(loaded),
        "statistically_evaluated_block_count": (
            len(loaded) if statistically_evaluated else 0
        ),
        "statistical_status": (
            progress.get("status") if isinstance(progress, Mapping) else "BLOCKED"
        ),
        "source_archive_count": len(observed_sources),
        "selection_sources_reused": False,
        "status": "IMPORTED",
    }


def import_v23_confirmation_directory(store, directory: Path) -> dict[str, object]:
    """Import every complete queued report in chronological order."""
    if find_active_v23_manifest(store) is None:
        return {
            "schema_version": 1,
            "mode": "SHADOW_CONFIRMATION",
            "apply_allowed": False,
            "status": "INACTIVE",
            "report_count": 0,
            "episode_count": 0,
        }
    candidates = [
        path for path in directory.glob("*.json")
        if path.name != "status.json"
    ]
    if not candidates:
        return {
            "schema_version": 1,
            "mode": "SHADOW_CONFIRMATION",
            "apply_allowed": False,
            "status": "WAITING_REPORTS",
            "report_count": 0,
            "episode_count": 0,
        }
    if len(candidates) > MAXIMUM_CONFIRMATION_REPORTS:
        raise ValueError("v23 confirmation report capacity reached")
    root = directory.parent
    cohort = bounded_json(root / "confirmation-cohort.json")
    cohort_body = {
        key: value for key, value in cohort.items()
        if key != "cohort_sha256"
    }
    if (
        cohort.get("schema_version")
        != V23_CONFIRMATION_COHORT_SCHEMA_VERSION
        or cohort.get("mode") != "SHADOW_CONFIRMATION"
        or cohort.get("apply_allowed") is not False
        or cohort.get("cohort_sha256") != fingerprint(cohort_body)
    ):
        raise ValueError("v23 confirmation cohort contract is unavailable")
    accepted_requests: dict[str, tuple[Path, str]] = {}
    block_paths = sorted((root / "confirmation-blocks").glob("*.json"))
    if len(block_paths) > 14:
        raise ValueError("v23 confirmation block capacity reached")
    previous_block_sha256: str | None = None
    for ordinal, block_path in enumerate(block_paths):
        block = bounded_json(block_path)
        request_identity = str(block.get("request_sha256", ""))
        request_path = root / "confirmation-requests" / f"{request_identity}.json"
        request_raw = request_path.read_bytes()
        request = bounded_json(request_path)
        sources = sorted(
            str(archive["sha256"])
            for path in request.get("paths", [])
            for archive in path.get("archives", [])
        )
        if (
            block.get("schema_version")
            != V23_CONFIRMATION_BLOCK_SCHEMA_VERSION
            or block.get("cohort_sha256") != cohort.get("cohort_sha256")
            or block.get("block_index") != ordinal
            or block.get("previous_block_sha256") != previous_block_sha256
            or block.get("source_archive_sha256s") != sources
            or not sources
            or any(len(source) != 64 for source in sources)
            or fingerprint(request) != request_identity
            or block_path.name != f"{ordinal:02d}-{request_identity}.json"
        ):
            raise ValueError("v23 confirmation block identity differs")
        request_file_sha = hashlib.sha256(request_raw).hexdigest()
        accepted_requests[request_file_sha] = (
            request_path, request_file_sha,
        )
        previous_block_sha256 = fingerprint(block)
    if any(path.stem not in accepted_requests for path in candidates):
        raise ValueError("v23 confirmation report is not cohort-owned")
    loaded: list[tuple[int, Path, str, Path, str]] = []
    for path in candidates:
        raw = path.read_bytes()
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError("v23 confirmation report is oversized")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("v23 confirmation report must be an object")
        request_path, request_sha = accepted_requests[path.stem]
        loaded.append((
            int(payload["start_ts_ms"]), path,
            hashlib.sha256(raw).hexdigest(), request_path, request_sha,
        ))
    imported = import_v23_confirmation_reports(
        store,
        [
            (path, digest, request_path, request_sha)
            for _start, path, digest, request_path, request_sha
            in sorted(loaded)
        ],
    )
    return {
        **imported,
        "queued_block_count": len(block_paths),
        "replay_completed_block_count": len(candidates),
        "hash_verified_block_count": len(loaded),
    }


__all__ = [
    "find_active_v23_manifest",
    "import_v23_confirmation_reports",
    "import_v23_confirmation_directory",
    "load_v23_selection_artifact",
]
