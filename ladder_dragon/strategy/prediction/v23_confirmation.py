# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: import disjoint exact L2 replay as immutable v23 confirmation evidence.
"""Fail-closed bridge from reviewed diff-depth reports to v23 episodes."""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Mapping, Sequence

from ladder_dragon.strategy.prediction.episode_evidence import (
    record_completed_episode,
)
from ladder_dragon.strategy.prediction.episode_semantics import (
    V23_EXECUTION_MODEL_RULE,
    execution_model_contract,
    v23_evidence_semantics_fingerprint,
)
from ladder_dragon.strategy.prediction.execution_episode import (
    ExecutionEpisodeResult,
    ExecutionEpisodeSpec,
)
from ladder_dragon.strategy.prediction.experiment_lifecycle import (
    list_experiments,
)
from ladder_dragon.strategy.prediction.historical_policy import fingerprint
from ladder_dragon.strategy.prediction.historical_selection import (
    historical_report_rows,
    load_historical_report,
    validate_historical_replay_report,
)


D = Decimal
ZERO = D("0")
ONE = D("1")
MAXIMUM_CONFIRMATION_REPORTS = 128


def _decimal(value: object, *, field: str) -> Decimal:
    number = D(str(value))
    if not number.is_finite():
        raise ValueError(f"v23 confirmation {field} is invalid")
    return number


def _active_v23_manifest(store) -> Mapping[str, object]:
    rows = [
        row for row in list_experiments(store, symbol="SOLUSDT")
        if row.get("generation") == "v23"
        and row.get("current_status") == "CONFIRMING"
    ]
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


def _selection_artifact(store, parameters: Mapping[str, object]) -> dict:
    rule = parameters.get("entry_veto_rule")
    if not isinstance(rule, Mapping):
        raise ValueError("v23 confirmation veto rule is unavailable")
    identity = str(rule.get("selection_artifact_sha256") or "")
    with store._connect() as connection:
        row = connection.execute(
            """SELECT artifact_json FROM
                      prediction_entry_veto_selection_artifacts
               WHERE artifact_sha256=? AND symbol='SOLUSDT'""",
            (identity,),
        ).fetchone()
    if row is None:
        raise ValueError("v23 selection artifact is unavailable")
    payload = json.loads(str(row[0]))
    if not isinstance(payload, dict):
        raise ValueError("v23 selection artifact is invalid")
    body = {
        key: value for key, value in payload.items()
        if key != "artifact_sha256"
    }
    if payload.get("artifact_sha256") != fingerprint(body):
        raise ValueError("v23 selection artifact identity differs")
    return payload


def _validate_policy(
    policy: Mapping[str, object], parameters: Mapping[str, object]
) -> None:
    rule = parameters["entry_veto_rule"]
    expected = {
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
        "veto_price_bps": str(rule["prefill_price_change_max_bps"]),
        "veto_signed_flow": str(
            rule["prefill_signed_trade_flow_max"]
        ),
        "veto_ofi": str(rule["prefill_order_flow_imbalance_max"]),
        "cancel_latency_ms": int(rule["cancel_latency_ms"]),
        "signal_window_ms": int(rule["signal_window_ms"]),
    }
    decimal_fields = {
        "entry_gap_bps", "take_profit_bps", "stop_limit_bps",
        "stop_trigger_bps", "notional_quote", "veto_price_bps",
        "veto_signed_flow", "veto_ofi",
    }
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
    episode_id = hashlib.sha256(
        (
            f"v23-confirmation:{report_sha}:"
            f"{row.get('episode_id')}:{manifest['candidate_fingerprint']}"
        ).encode("utf-8")
    ).hexdigest()
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
    reports: Sequence[tuple[Path, str]],
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
    for path, expected_sha in reports:
        report = load_historical_report(path, expected_sha)
        validate_historical_replay_report(
            report, cutoff_ts_ms=int(report["cutoff_ts_ms"])
        )
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
        loaded.append((report, expected_sha))
    created = 0
    for report, report_sha in loaded:
        for row in historical_report_rows(report, "veto"):
            if row.get("censored") is True:
                continue
            spec, result = _episode_pair(
                row, manifest=manifest, report_sha=report_sha
            )
            record_completed_episode(store, spec, result)
            created += 1
    return {
        "schema_version": 1,
        "mode": "SHADOW_CONFIRMATION",
        "apply_allowed": False,
        "generation": "v23",
        "experiment_id": manifest["experiment_id"],
        "report_count": len(loaded),
        "episode_count": created,
        "source_archive_count": len(observed_sources),
        "selection_sources_reused": False,
        "status": "IMPORTED",
    }


__all__ = ["import_v23_confirmation_reports"]
