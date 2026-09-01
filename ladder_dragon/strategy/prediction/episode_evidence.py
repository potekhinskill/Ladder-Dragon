# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: persist and evaluate compact promotion execution episodes.
"""Append-only episode evidence and preregistered sequential statistics."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
import hashlib
import json
from math import comb
import sqlite3
import time
from typing import Iterable, Mapping, TYPE_CHECKING

from ladder_dragon.strategy.prediction.execution_episode import (
    ExecutionEpisodeResult,
    ExecutionEpisodeSpec,
    result_from_payload,
)
from ladder_dragon.strategy.prediction.episode_expectancy import (
    net_expectancy_criteria,
    sequential_net_expectancy_report,
)


if TYPE_CHECKING:
    from ladder_dragon.strategy.prediction.runtime import PredictionShadowStore


D = Decimal
ZERO = D("0")
ONE = D("1")
MAXIMUM_EPISODES = 250_000
MAXIMUM_MODEL_VALIDATIONS = 1_024
SEQUENTIAL_LOOKS = (
    (12, D("0.005")),
    (24, D("0.010")),
    (34, D("0.015")),
    (43, D("0.020")),
)
DESIGN_POSITIVE_OUTCOME_PROBABILITY = D("0.72")
DESIGN_TARGET_POWER = D("0.80")
MAXIMUM_TERMINAL_EPISODES = 300
MAXIMUM_CONFIRMATION_DURATION_MS = 14 * 24 * 60 * 60_000
MINIMUM_FILLED_EPISODES = 10
MINIMUM_FILL_RATE = D("0.05")
MAXIMUM_DRAWDOWN_FRACTION = D("0.25")
REGIME_NONINFERIORITY_FRACTION = D("0.02")
EPISODE_CRITERIA_SCHEMA_VERSION = 2
EPISODE_STATISTICAL_METHOD = "group_sequential_combined_gate_alpha_spending_v2"
ELIGIBLE_REGIMES = ("RANGE", "TREND_UP", "TREND_DOWN")


def episode_confirmation_criteria(
    statistical_design_version: str,
) -> dict[str, object]:
    """Return the immutable criteria evaluated by one promotion generation."""
    if statistical_design_version == "episode_net_expectancy_alpha_spending_v3":
        return net_expectancy_criteria()
    if statistical_design_version == "episode_anytime_expectancy_v4":
        return net_expectancy_criteria(anytime_valid=True)
    if statistical_design_version == "episode_anytime_expectancy_v5":
        return net_expectancy_criteria(anytime_valid=True, exact_policy=True)
    if statistical_design_version == "episode_anytime_expectancy_v6":
        return net_expectancy_criteria(
            anytime_valid=True,
            exact_policy=True,
            excursion_diagnostics=True,
        )
    if statistical_design_version == "episode_anytime_expectancy_v7":
        return net_expectancy_criteria(
            anytime_valid=True,
            exact_policy=True,
            excursion_diagnostics=True,
            economic_futility=True,
        )
    if statistical_design_version == "episode_anytime_expectancy_v8":
        return net_expectancy_criteria(
            anytime_valid=True,
            exact_policy=True,
            excursion_diagnostics=True,
            economic_futility=True,
            fixed_confirmation_cohort=True,
        )
    if statistical_design_version != "episode_combined_alpha_spending_v2":
        raise ValueError("unsupported episode statistical design")
    return {
        "criteria_schema_version": EPISODE_CRITERIA_SCHEMA_VERSION,
        "method": EPISODE_STATISTICAL_METHOD,
        "trial_definition": "eligible_nonzero_primary_net_pnl",
        "sequential_looks": [
            {"sample_count": count, "alpha_spend": format(alpha, "f")}
            for count, alpha in SEQUENTIAL_LOOKS
        ],
        "minimum_eligible_terminal_episodes": 12,
        "minimum_filled_episodes": MINIMUM_FILLED_EPISODES,
        "minimum_fill_rate": "0.10",
        "maximum_drawdown_fraction": format(MAXIMUM_DRAWDOWN_FRACTION, "f"),
        "eligible_regimes": list(ELIGIBLE_REGIMES),
        "minimum_regime_filled_episodes": 3,
        "minimum_confirmed_regimes": 2,
        "regime_noninferiority_fraction": format(
            REGIME_NONINFERIORITY_FRACTION, "f"
        ),
        "regime_activation_policy": "confirmed_only_v1",
        "maximum_terminal_episodes": MAXIMUM_TERMINAL_EPISODES,
        "maximum_confirmation_duration_ms": MAXIMUM_CONFIRMATION_DURATION_MS,
        "panic_policy": "separate_safety_veto",
    }


def _json_value(value: object) -> object:
    if isinstance(value, D):
        return format(value, "f")
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _canonical(payload: Mapping[str, object]) -> str:
    return json.dumps(
        _json_value(dict(payload)),
        sort_keys=True,
        separators=(",", ":"),
    )


def _digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def migrate_episode_evidence(connection: sqlite3.Connection) -> None:
    """Create bounded append-only derived SHADOW evidence tables."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS prediction_execution_episode_starts (
            episode_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            generation TEXT NOT NULL,
            variant_id TEXT NOT NULL,
            candidate_fingerprint TEXT NOT NULL,
            execution_model_rule TEXT NOT NULL,
            started_at_ms INTEGER NOT NULL,
            spec_json TEXT NOT NULL,
            spec_sha256 TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL,
            UNIQUE(symbol, generation, started_at_ms)
        );
        CREATE TABLE IF NOT EXISTS prediction_execution_episode_results (
            episode_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            generation TEXT NOT NULL,
            variant_id TEXT NOT NULL,
            candidate_fingerprint TEXT NOT NULL,
            execution_model_rule TEXT NOT NULL,
            terminal_at_ms INTEGER NOT NULL,
            eligible_for_promotion INTEGER NOT NULL CHECK(
                eligible_for_promotion IN (0,1)
            ),
            result_json TEXT NOT NULL,
            result_sha256 TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL,
            FOREIGN KEY(episode_id)
                REFERENCES prediction_execution_episode_starts(episode_id)
        );
        CREATE INDEX IF NOT EXISTS prediction_episode_result_cohort
            ON prediction_execution_episode_results(
                symbol,generation,variant_id,terminal_at_ms
            );
        CREATE TABLE IF NOT EXISTS prediction_execution_model_validations (
            validation_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            execution_model_rule TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('PASS','BLOCKED')),
            terminal_orders INTEGER NOT NULL CHECK(terminal_orders>=0),
            filled_orders INTEGER NOT NULL CHECK(filled_orders>=0),
            report_json TEXT NOT NULL,
            report_sha256 TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            validated_at_ms INTEGER NOT NULL,
            created_at_ms INTEGER NOT NULL,
            UNIQUE(symbol,execution_model_rule,report_sha256)
        );
        CREATE INDEX IF NOT EXISTS prediction_model_validation_latest
            ON prediction_execution_model_validations(
                symbol,execution_model_rule,validated_at_ms
            );
        CREATE TRIGGER IF NOT EXISTS prediction_episode_start_no_update
        BEFORE UPDATE ON prediction_execution_episode_starts
        BEGIN SELECT RAISE(ABORT, 'episode starts are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS prediction_episode_start_no_delete
        BEFORE DELETE ON prediction_execution_episode_starts
        BEGIN SELECT RAISE(ABORT, 'episode starts are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS prediction_episode_result_no_update
        BEFORE UPDATE ON prediction_execution_episode_results
        BEGIN SELECT RAISE(ABORT, 'episode results are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS prediction_episode_result_no_delete
        BEFORE DELETE ON prediction_execution_episode_results
        BEGIN SELECT RAISE(ABORT, 'episode results are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS prediction_model_validation_no_update
        BEFORE UPDATE ON prediction_execution_model_validations
        BEGIN SELECT RAISE(ABORT, 'model validations are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS prediction_model_validation_no_delete
        BEFORE DELETE ON prediction_execution_model_validations
        BEGIN SELECT RAISE(ABORT, 'model validations are append-only'); END;
        """
    )
    from ladder_dragon.strategy.prediction.entry_diagnostics import (
        migrate_entry_diagnostics,
    )

    migrate_entry_diagnostics(connection)


def record_episode_start(
    store: "PredictionShadowStore",
    spec: ExecutionEpisodeSpec,
) -> None:
    """Append one compact episode start or fail at the fixed growth ceiling."""
    payload = _json_value(asdict(spec))
    if not isinstance(payload, dict):
        raise ValueError("episode specification is invalid")
    with store._connect() as connection:
        count = int(connection.execute(
            "SELECT COUNT(*) FROM prediction_execution_episode_starts"
        ).fetchone()[0])
        if count >= MAXIMUM_EPISODES:
            raise RuntimeError("prediction execution episode capacity reached")
        connection.execute(
            """INSERT INTO prediction_execution_episode_starts
               (episode_id,symbol,generation,variant_id,candidate_fingerprint,
                execution_model_rule,started_at_ms,spec_json,spec_sha256,
                created_at_ms) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                spec.episode_id,
                spec.symbol,
                spec.generation,
                spec.variant_id,
                spec.candidate_fingerprint,
                spec.execution_model_rule,
                spec.started_at_ms,
                _canonical(payload),
                _digest(payload),
                int(time.time() * 1000),
            ),
        )


def record_episode_result(
    store: "PredictionShadowStore",
    result: ExecutionEpisodeResult,
) -> None:
    """Append one terminal result and verify its immutable start identity."""
    payload = result.payload()
    with store._connect() as connection:
        start = connection.execute(
            """SELECT symbol,generation,variant_id,candidate_fingerprint,
                      execution_model_rule
               FROM prediction_execution_episode_starts WHERE episode_id=?""",
            (result.episode_id,),
        ).fetchone()
        identity = (
            result.symbol,
            result.generation,
            result.variant_id,
            result.candidate_fingerprint,
            result.execution_model_rule,
        )
        if start is None or tuple(start) != identity:
            raise ValueError("episode result identity differs from its start")
        try:
            start_payload = json.loads(str(connection.execute(
                "SELECT spec_json FROM prediction_execution_episode_starts "
                "WHERE episode_id=?",
                (result.episode_id,),
            ).fetchone()[0]))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError("episode start payload is damaged") from exc
        start_semantics_fingerprint = (
            str(start_payload.get("evidence_semantics_fingerprint") or "")
            if isinstance(start_payload, dict) else None
        )
        if (
            start_semantics_fingerprint is None
            or start_semantics_fingerprint
            != result.evidence_semantics_fingerprint
        ):
            raise ValueError("episode evidence semantics differ from its start")
        connection.execute(
            """INSERT INTO prediction_execution_episode_results
               (episode_id,symbol,generation,variant_id,candidate_fingerprint,
                execution_model_rule,terminal_at_ms,eligible_for_promotion,
                result_json,result_sha256,created_at_ms)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                result.episode_id,
                result.symbol,
                result.generation,
                result.variant_id,
                result.candidate_fingerprint,
                result.execution_model_rule,
                result.terminal_at_ms,
                int(result.eligible_for_promotion),
                _canonical(payload),
                _digest(payload),
                int(time.time() * 1000),
            ),
        )


def record_completed_episode(
    store: "PredictionShadowStore",
    spec: ExecutionEpisodeSpec,
    result: ExecutionEpisodeResult,
) -> bool:
    """Append one externally replayed start and result in one transaction."""
    identity = (
        spec.episode_id,
        spec.symbol,
        spec.generation,
        spec.variant_id,
        spec.candidate_fingerprint,
        spec.execution_model_rule,
    )
    result_identity = (
        result.episode_id,
        result.symbol,
        result.generation,
        result.variant_id,
        result.candidate_fingerprint,
        result.execution_model_rule,
    )
    if identity != result_identity:
        raise ValueError("completed episode identity differs")
    if (
        spec.evidence_semantics_fingerprint
        != result.evidence_semantics_fingerprint
    ):
        raise ValueError("completed episode semantics differ")
    spec_payload = _json_value(asdict(spec))
    result_payload = result.payload()
    if not isinstance(spec_payload, dict):
        raise ValueError("completed episode specification is invalid")
    now_ms = int(time.time() * 1000)
    spec_sha256 = _digest(spec_payload)
    result_sha256 = _digest(result_payload)
    with store._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing_start = connection.execute(
            "SELECT spec_sha256 FROM prediction_execution_episode_starts "
            "WHERE episode_id=?",
            (spec.episode_id,),
        ).fetchone()
        existing_result = connection.execute(
            "SELECT result_sha256 FROM prediction_execution_episode_results "
            "WHERE episode_id=?",
            (spec.episode_id,),
        ).fetchone()
        if existing_start is not None or existing_result is not None:
            if (
                existing_start is None
                or existing_result is None
                or str(existing_start[0]) != spec_sha256
                or str(existing_result[0]) != result_sha256
            ):
                raise ValueError("completed episode replay identity differs")
            return False
        count = int(connection.execute(
            "SELECT COUNT(*) FROM prediction_execution_episode_starts"
        ).fetchone()[0])
        if count >= MAXIMUM_EPISODES:
            raise RuntimeError("prediction execution episode capacity reached")
        connection.execute(
            """INSERT INTO prediction_execution_episode_starts
               (episode_id,symbol,generation,variant_id,candidate_fingerprint,
                execution_model_rule,started_at_ms,spec_json,spec_sha256,
                created_at_ms) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                spec.episode_id, spec.symbol, spec.generation, spec.variant_id,
                spec.candidate_fingerprint, spec.execution_model_rule,
                spec.started_at_ms, _canonical(spec_payload),
                spec_sha256, now_ms,
            ),
        )
        connection.execute(
            """INSERT INTO prediction_execution_episode_results
               (episode_id,symbol,generation,variant_id,candidate_fingerprint,
                execution_model_rule,terminal_at_ms,eligible_for_promotion,
                result_json,result_sha256,created_at_ms)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                result.episode_id, result.symbol, result.generation,
                result.variant_id, result.candidate_fingerprint,
                result.execution_model_rule, result.terminal_at_ms,
                int(result.eligible_for_promotion),
                _canonical(result_payload), result_sha256, now_ms,
            ),
        )
    return True


def recover_interrupted_episodes(
    store: "PredictionShadowStore",
    *,
    symbol: str,
    now_ms: int,
) -> int:
    """Close pre-restart active episodes as ineligible without inventing fills."""
    with store._connect() as connection:
        rows = connection.execute(
            """SELECT s.episode_id,s.symbol,s.generation,s.variant_id,
                      s.candidate_fingerprint,s.execution_model_rule,
                      s.started_at_ms,s.spec_json,s.spec_sha256
               FROM prediction_execution_episode_starts s
               LEFT JOIN prediction_execution_episode_results r
                 ON r.episode_id=s.episode_id
               WHERE s.symbol=? AND r.episode_id IS NULL""",
            (symbol.upper(),),
        ).fetchall()
    recovered = 0
    for row in rows:
        spec_payload = json.loads(str(row[7]))
        if not isinstance(spec_payload, dict) or _digest(spec_payload) != str(row[8]):
            raise ValueError("interrupted episode specification is damaged")
        result = ExecutionEpisodeResult(
            episode_id=str(row[0]),
            symbol=str(row[1]),
            generation=str(row[2]),
            variant_id=str(row[3]),
            candidate_fingerprint=str(row[4]),
            execution_model_rule=str(row[5]),
            evidence_semantics_fingerprint=str(
                spec_payload.get("evidence_semantics_fingerprint") or ""
            ),
            start_regime=str(spec_payload.get("start_regime") or "UNKNOWN"),
            started_at_ms=int(row[6]),
            terminal_at_ms=int(now_ms),
            terminal_reason="PROCESS_RESTART_DATA_GAP",
            entry_filled_quantity=ZERO,
            entry_fill_fraction=ZERO,
            entry_notional_quote=ZERO,
            exit_filled_quantity=ZERO,
            gross_pnl_quote=ZERO,
            net_pnl_quote=ZERO,
            total_fee_quote=ZERO,
            adverse_selection_pct=ZERO,
            diagnostic_300m_net_pnl_quote=None,
            stop_triggered=False,
            stop_limit_unfilled=False,
            panic_veto=False,
            eligible_for_promotion=False,
        )
        record_episode_result(store, result)
        recovered += 1
    return recovered


def load_episode_results(
    store: "PredictionShadowStore",
    *,
    symbol: str,
    generation: str,
    variant_id: str,
    limit: int = 1_000,
    started_after_ms: int | None = None,
    candidate_fingerprint: str | None = None,
    execution_model_rule: str | None = None,
    episode_id_prefix: str | None = None,
) -> list[ExecutionEpisodeResult]:
    """Load a bounded chronological cohort and verify every payload hash."""
    if not 1 <= int(limit) <= 10_000:
        raise ValueError("episode result limit is invalid")
    if episode_id_prefix is not None and (
        not isinstance(episode_id_prefix, str)
        or not episode_id_prefix
        or len(episode_id_prefix) > 128
        or "%" in episode_id_prefix
        or "_" in episode_id_prefix
    ):
        raise ValueError("episode result prefix is invalid")
    with store._connect() as connection:
        query = """SELECT r.result_json,r.result_sha256
               FROM prediction_execution_episode_results r
               JOIN prediction_execution_episode_starts s
                 ON s.episode_id=r.episode_id
               WHERE r.symbol=? AND r.generation=? AND r.variant_id=?"""
        params: list[object] = [symbol.upper(), generation, variant_id]
        if started_after_ms is not None:
            query += " AND s.started_at_ms>=?"
            params.append(int(started_after_ms))
        if candidate_fingerprint is not None:
            query += " AND r.candidate_fingerprint=?"
            params.append(str(candidate_fingerprint))
        if execution_model_rule is not None:
            query += " AND r.execution_model_rule=?"
            params.append(str(execution_model_rule))
        if episode_id_prefix is not None:
            query += " AND s.episode_id LIKE ?"
            params.append(f"{episode_id_prefix}%")
        query += " ORDER BY r.terminal_at_ms LIMIT ?"
        params.append(int(limit))
        rows = connection.execute(query, params).fetchall()
    output = []
    for raw, expected_hash in rows:
        payload = json.loads(str(raw))
        if not isinstance(payload, dict) or _digest(payload) != str(expected_hash):
            raise ValueError("execution episode result is damaged")
        output.append(result_from_payload(payload))
    return output


def _sign_tail(wins: int, trials: int) -> Decimal:
    if not 0 <= wins <= trials:
        raise ValueError("sign-test counts are invalid")
    numerator = sum(comb(trials, index) for index in range(wins, trials + 1))
    return D(numerator) / (D(2) ** trials)


def _critical_wins(trials: int, alpha: Decimal) -> int:
    for wins in range(trials + 1):
        if _sign_tail(wins, trials) <= alpha:
            return wins
    raise ValueError("sequential sign boundary is unreachable")


def _design_power(trials: int, alpha: Decimal) -> Decimal:
    critical = _critical_wins(trials, alpha)
    probability = DESIGN_POSITIVE_OUTCOME_PROBABILITY
    return sum((
        D(comb(trials, wins))
        * probability ** wins
        * (ONE - probability) ** (trials - wins)
        for wins in range(critical, trials + 1)
    ), ZERO)


def _maximum_drawdown(values: Iterable[Decimal]) -> Decimal:
    equity = ZERO
    peak = ZERO
    drawdown = ZERO
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def _validated_episode_criteria(
    criteria: Mapping[str, object] | None,
) -> dict[str, object]:
    """Validate the frozen evaluator contract without applying local defaults."""
    if not isinstance(criteria, Mapping):
        raise ValueError("frozen episode criteria are unavailable")
    if criteria.get("criteria_schema_version") != EPISODE_CRITERIA_SCHEMA_VERSION:
        raise ValueError("frozen episode criteria schema is unsupported")
    if criteria.get("method") != EPISODE_STATISTICAL_METHOD:
        raise ValueError("frozen episode statistical method is unsupported")
    expected = episode_confirmation_criteria("episode_combined_alpha_spending_v2")
    if _canonical(criteria) != _canonical(expected):
        raise ValueError("frozen episode criteria differ from the evaluator contract")
    return expected


def _regime_report(
    rows: list[ExecutionEpisodeResult],
    *,
    regimes: tuple[str, ...],
    minimum_filled: int,
    noninferiority_fraction: Decimal,
) -> tuple[dict[str, dict[str, object]], tuple[str, ...]]:
    reports: dict[str, dict[str, object]] = {}
    confirmed = []
    for regime in regimes:
        cohort = [
            row for row in rows
            if row.entry_filled_quantity > ZERO and row.start_regime == regime
        ]
        pnl = sum((row.net_pnl_quote for row in cohort), ZERO)
        notional = sum((row.entry_notional_quote for row in cohort), ZERO)
        mean_pnl = pnl / D(len(cohort)) if cohort else ZERO
        mean_notional = notional / D(len(cohort)) if cohort else ZERO
        measured = len(cohort) >= minimum_filled
        noninferior = bool(
            measured
            and mean_pnl >= -mean_notional * noninferiority_fraction
        )
        if noninferior:
            confirmed.append(regime)
        reports[regime] = {
            "filled_episodes": len(cohort),
            "required_filled_episodes": minimum_filled,
            "measured": measured,
            "mean_net_pnl_quote": format(mean_pnl, "f"),
            "noninferior": noninferior,
        }
    return reports, tuple(confirmed)


def _projected_timestamp(
    rows: list[ExecutionEpisodeResult],
    *,
    observed_events: int,
    required_events: int,
    mean_duration_ms: Decimal | None,
) -> int | None:
    if required_events <= observed_events:
        return rows[-1].terminal_at_ms if rows else None
    if not rows or observed_events <= 0 or mean_duration_ms is None:
        return None
    rate = D(observed_events) / D(len(rows))
    return int(
        D(rows[-1].terminal_at_ms)
        + mean_duration_ms * D(required_events - observed_events) / rate
    )


def sequential_episode_report(
    results: Iterable[ExecutionEpisodeResult],
    *,
    criteria: Mapping[str, object] | None,
) -> dict[str, object]:
    """Evaluate each look with the exact criteria frozen in the manifest."""
    if (
        isinstance(criteria, Mapping)
        and criteria.get("criteria_schema_version") in {3, 4, 5, 6, 7, 8}
    ):
        criteria_schema = int(criteria["criteria_schema_version"])
        expected = net_expectancy_criteria(
            anytime_valid=criteria_schema in {4, 5, 6, 7, 8},
            exact_policy=criteria_schema in {5, 6, 7, 8},
            excursion_diagnostics=criteria_schema in {6, 7, 8},
            economic_futility=criteria_schema in {7, 8},
            fixed_confirmation_cohort=criteria_schema == 8,
        )
        if _canonical(criteria) != _canonical(expected):
            return {
                "schema_version": 3,
                "method": "UNSUPPORTED_FROZEN_CONTRACT",
                "status": "BLOCKED",
                "approved": False,
                "readiness_reason": (
                    "frozen episode criteria differ from the evaluator contract"
                ),
                "looks": [],
                "projected_ready_ts_ms": None,
            }
        from ladder_dragon.strategy.prediction.episode_semantics import (
            evidence_semantics_fingerprint,
            v19_evidence_semantics_fingerprint,
            v20_evidence_semantics_fingerprint,
            v21_evidence_semantics_fingerprint,
            v23_evidence_semantics_fingerprint,
        )
        return sequential_net_expectancy_report(
            results,
            criteria=expected,
            required_semantics_fingerprint=(
                v23_evidence_semantics_fingerprint()
                if criteria_schema in {7, 8}
                else evidence_semantics_fingerprint()
                if criteria_schema == 6
                else v21_evidence_semantics_fingerprint()
                if criteria_schema == 5
                else v20_evidence_semantics_fingerprint()
                if criteria_schema == 4
                else v19_evidence_semantics_fingerprint()
            ),
        )
    all_results = sorted(results, key=lambda row: row.terminal_at_ms)
    rows = [row for row in all_results if row.eligible_for_promotion]
    filled = [row for row in rows if row.entry_filled_quantity > ZERO]
    sign_rows = [row for row in rows if row.net_pnl_quote != ZERO]
    try:
        contract = _validated_episode_criteria(criteria)
    except ValueError as exc:
        return {
            "schema_version": 2,
            "method": "UNSUPPORTED_FROZEN_CONTRACT",
            "eligible_terminal_episodes": len(rows),
            "filled_episodes": len(filled),
            "nonzero_sign_trials": len(sign_rows),
            "looks": [],
            "passed_at_episode": None,
            "next_sequential_look": None,
            "statistics_projected_ready_ts_ms": None,
            "regime_projected_ready_ts_ms": None,
            "projected_ready_ts_ms": None,
            "readiness_reason": str(exc),
            "regime_safety": {},
            "confirmed_execution_regimes": [],
            "regime_noninferiority_passed": False,
            "status": "BLOCKED",
            "approved": False,
        }

    looks = tuple(
        (int(item["sample_count"]), D(str(item["alpha_spend"])))
        for item in contract["sequential_looks"]
    )
    regimes = tuple(str(item) for item in contract["eligible_regimes"])
    minimum_terminal = int(contract["minimum_eligible_terminal_episodes"])
    minimum_filled = int(contract["minimum_filled_episodes"])
    minimum_fill_rate = D(str(contract["minimum_fill_rate"]))
    drawdown_fraction = D(str(contract["maximum_drawdown_fraction"]))
    minimum_regime = int(contract["minimum_regime_filled_episodes"])
    minimum_confirmed_regimes = int(contract["minimum_confirmed_regimes"])
    regime_fraction = D(str(contract["regime_noninferiority_fraction"]))
    maximum_terminal = int(contract["maximum_terminal_episodes"])

    passed_at: int | None = None
    passed_boundary: int | None = None
    passed_regimes: tuple[str, ...] = ()
    look_reports = []
    for sample_count, alpha in looks:
        sign_cohort = sign_rows[:sample_count]
        reached = len(sign_cohort) == sample_count
        boundary = sign_cohort[-1].terminal_at_ms if reached else None
        cohort = [
            row for row in rows
            if boundary is not None and row.terminal_at_ms <= boundary
        ]
        wins = sum(row.net_pnl_quote > ZERO for row in sign_cohort)
        p_value = _sign_tail(wins, len(sign_cohort)) if sign_cohort else ONE
        cohort_filled = sum(row.entry_filled_quantity > ZERO for row in cohort)
        fill_rate = D(cohort_filled) / D(len(cohort)) if cohort else ZERO
        pnl = sum((row.net_pnl_quote for row in cohort), ZERO)
        maximum_notional = max(
            (row.entry_notional_quote for row in cohort), default=ZERO
        )
        drawdown = _maximum_drawdown(row.net_pnl_quote for row in cohort)
        regime_reports, confirmed_regimes = _regime_report(
            cohort,
            regimes=regimes,
            minimum_filled=minimum_regime,
            noninferiority_fraction=regime_fraction,
        )
        passed = bool(
            reached
            and len(cohort) >= minimum_terminal
            and p_value <= alpha
            and pnl > ZERO
            and cohort_filled >= minimum_filled
            and fill_rate >= minimum_fill_rate
            and maximum_notional > ZERO
            and drawdown <= maximum_notional * drawdown_fraction
            and len(confirmed_regimes) >= minimum_confirmed_regimes
        )
        look_reports.append({
            "sample_count": sample_count,
            "alpha_spend": format(alpha, "f"),
            "reached": reached,
            "wins": wins,
            "nonzero_trials": len(sign_cohort),
            "critical_wins": _critical_wins(sample_count, alpha),
            "design_power": format(_design_power(sample_count, alpha), "f"),
            "one_sided_p_value": format(p_value, "f"),
            "eligible_terminal_episodes": len(cohort),
            "filled_episodes": cohort_filled,
            "fill_rate": format(fill_rate, "f"),
            "net_pnl_quote": format(pnl, "f"),
            "maximum_drawdown_quote": format(drawdown, "f"),
            "confirmed_execution_regimes": list(confirmed_regimes),
            "regime_safety": regime_reports,
            "passed": passed,
        })
        # Freeze the boundary only after every preregistered gate passes.
        if passed and passed_at is None:
            passed_at = sample_count
            passed_boundary = boundary
            passed_regimes = confirmed_regimes

    display_rows = [
        row for row in rows
        if passed_boundary is None or row.terminal_at_ms <= passed_boundary
    ]
    regime_reports, confirmed_regimes = _regime_report(
        display_rows,
        regimes=regimes,
        minimum_filled=minimum_regime,
        noninferiority_fraction=regime_fraction,
    )
    if passed_at is not None:
        confirmed_regimes = passed_regimes

    next_look = (
        None if passed_at is not None else
        next((count for count, _alpha in looks if count > len(sign_rows)), None)
    )
    losses = len(sign_rows) - sum(row.net_pnl_quote > ZERO for row in sign_rows)
    future_sign_possible = any(
        count > len(sign_rows) and losses <= count - _critical_wins(count, alpha)
        for count, alpha in looks
    )
    remaining_terminal = max(0, maximum_terminal - len(rows))
    regime_counts = {
        regime: sum(
            row.entry_filled_quantity > ZERO and row.start_regime == regime
            for row in rows
        )
        for regime in regimes
    }
    possible_regimes = sum(
        count >= minimum_regime
        or minimum_regime - count <= remaining_terminal
        for count in regime_counts.values()
    )
    status = "PASS" if passed_at is not None else "SHADOW"
    if status != "PASS" and (
        len(rows) >= maximum_terminal
        or next_look is None
        or not future_sign_possible
        or possible_regimes < minimum_confirmed_regimes
    ):
        status = "READY_TO_REJECT"

    durations = [
        D(row.terminal_at_ms - row.started_at_ms)
        for row in rows if row.terminal_at_ms > row.started_at_ms
    ]
    mean_duration_ms = sum(durations, ZERO) / D(len(durations)) if durations else None
    statistics_eta = (
        rows[-1].terminal_at_ms
        if passed_at is not None and rows else
        _projected_timestamp(
            rows,
            observed_events=len(sign_rows),
            required_events=next_look,
            mean_duration_ms=mean_duration_ms,
        )
        if next_look is not None else None
    )
    regime_etas = []
    for regime in regimes:
        eta = (
            rows[-1].terminal_at_ms
            if regime_reports[regime]["noninferior"] and rows else
            None
            if regime_counts[regime] >= minimum_regime else
            _projected_timestamp(
                rows,
                observed_events=regime_counts[regime],
                required_events=minimum_regime,
                mean_duration_ms=mean_duration_ms,
            )
        )
        if eta is not None:
            regime_etas.append(eta)
    regime_etas.sort()
    regime_eta = (
        regime_etas[minimum_confirmed_regimes - 1]
        if len(regime_etas) >= minimum_confirmed_regimes else None
    )
    combined_eta = (
        max(statistics_eta, regime_eta)
        if statistics_eta is not None and regime_eta is not None else None
    )
    panic_rows = [row for row in all_results if row.panic_veto]
    panic_failures = [
        row for row in panic_rows
        if row.entry_filled_quantity > row.exit_filled_quantity
    ]
    return {
        "schema_version": 2,
        "method": contract["method"],
        "primary_horizon_min": 360,
        "diagnostic_horizons_min": [300],
        "eligible_terminal_episodes": len(rows),
        "filled_episodes": len(filled),
        "nonzero_sign_trials": len(sign_rows),
        "maximum_terminal_episodes": maximum_terminal,
        "maximum_confirmation_duration_ms": contract[
            "maximum_confirmation_duration_ms"
        ],
        "power_analysis": {
            "scope": "conditional_nonzero_sign_test_only",
            "positive_outcome_probability": format(
                DESIGN_POSITIVE_OUTCOME_PROBABILITY, "f"
            ),
            "target_power": format(DESIGN_TARGET_POWER, "f"),
            "maximum_look_power": format(_design_power(*looks[-1]), "f"),
        },
        "alpha_total": format(sum((alpha for _n, alpha in looks), ZERO), "f"),
        "looks": look_reports,
        "passed_at_episode": passed_at,
        "next_sequential_look": next_look,
        "mean_episode_duration_ms": (
            format(mean_duration_ms, "f") if mean_duration_ms is not None else None
        ),
        "statistics_projected_ready_ts_ms": statistics_eta,
        "regime_projected_ready_ts_ms": regime_eta,
        "projected_ready_ts_ms": combined_eta,
        "readiness_reason": (
            "all preregistered gates passed"
            if status == "PASS" else
            "remaining preregistered looks cannot pass"
            if status == "READY_TO_REJECT" else
            "waiting for the next combined statistical and regime look"
        ),
        "regime_safety": regime_reports,
        "confirmed_execution_regimes": list(confirmed_regimes),
        "required_confirmed_regimes": minimum_confirmed_regimes,
        "regime_noninferiority_passed": (
            len(confirmed_regimes) >= minimum_confirmed_regimes
        ),
        "panic_veto": {
            "status": (
                "PASS" if panic_rows and not panic_failures
                else "BLOCKED" if panic_failures else "NOT_OBSERVED"
            ),
            "observations": len(panic_rows),
            "failures": len(panic_failures),
            "blocks_expectancy": False,
        },
        "status": status,
        "approved": status == "PASS",
    }


def model_validation_status(
    store: "PredictionShadowStore",
    *,
    symbol: str,
    execution_model_rule: str,
    expected_fee_schedule: Mapping[str, object] | None = None,
    expected_candidate_parameters: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return the latest immutable actual-order validation for one model."""
    with store._connect() as connection:
        row = connection.execute(
            """SELECT validation_id,status,terminal_orders,filled_orders,
                      report_json,report_sha256,source_sha256,validated_at_ms
               FROM prediction_execution_model_validations
               WHERE symbol=? AND execution_model_rule=?
               ORDER BY validated_at_ms DESC LIMIT 1""",
            (symbol.upper(), execution_model_rule),
        ).fetchone()
    if row is None:
        return {
            "status": "BLOCKED",
            "reason": "actual execution replay validation is unavailable",
            "minimum_terminal_orders": 10,
            "minimum_filled_orders": 1,
            "requires_filled_limit_maker": True,
            "requires_filled_stop_loss_limit": True,
        }
    try:
        report = json.loads(str(row[4]))
    except (json.JSONDecodeError, TypeError, ValueError):
        report = None
    if (
        not isinstance(report, dict)
        or _digest(report) != str(row[5])
    ):
        return {
            "status": "BLOCKED",
            "reason": "actual execution replay validation is damaged",
        }
    if expected_fee_schedule is not None:
        for field in (
            "maker_buy_fee_pct",
            "maker_sell_fee_pct",
            "taker_buy_fee_pct",
            "taker_sell_fee_pct",
        ):
            try:
                observed = D(str(report.get(field)))
                expected = D(str(expected_fee_schedule.get(field)))
            except (ArithmeticError, TypeError, ValueError):
                observed = expected = D("-1")
            if (
                not observed.is_finite()
                or not expected.is_finite()
                or observed < ZERO
                or observed != expected
            ):
                return {
                    "status": "BLOCKED",
                    "reason": "replay validation fee schedule differs",
                }
    if expected_candidate_parameters is not None:
        from ladder_dragon.strategy.prediction.episode_semantics import (
            canonical_digest,
            execution_engine_validation_domain,
        )
        schedule = expected_candidate_parameters.get("fee_schedule")
        if not isinstance(schedule, Mapping):
            return {
                "status": "BLOCKED",
                "reason": "replay validation fee schedule is unavailable",
            }
        expected_domain = execution_engine_validation_domain(
            execution_model_rule=execution_model_rule,
            fee_schedule=schedule,
            entry_veto_rule=(
                expected_candidate_parameters.get("entry_veto_rule")
                if expected_candidate_parameters.get("candidate_rule_version") == 8
                else None
            ),
        )
        observed_domain = report.get("validation_domain")
        if (
            not isinstance(observed_domain, Mapping)
            or canonical_digest(observed_domain)
            != canonical_digest(expected_domain)
        ):
            return {
                "status": "BLOCKED",
                "reason": "replay validation engine domain differs",
            }
    return {
        "validation_id": str(row[0]),
        "status": str(row[1]),
        "terminal_orders": int(row[2]),
        "filled_orders": int(row[3]),
        "report_sha256": str(row[5]),
        "source_sha256": str(row[6]),
        "validated_at_ms": int(row[7]),
        "actual_limit_maker_filled_orders": int(
            report.get("actual_limit_maker_filled_orders", 0)
        ),
        "actual_stop_limit_filled_orders": int(
            report.get("actual_stop_limit_filled_orders", 0)
        ),
        "replay_readiness": report.get("replay_readiness"),
        "confirmed_volatility_scope": (
            report.get("calibration_context_cohort", {}).get(
                "volatility_scope"
            )
            if isinstance(
                report.get("calibration_context_cohort"), Mapping
            ) else None
        ),
        "volatility_policy": (
            report.get("calibration_context_cohort", {}).get(
                "volatility_policy"
            )
            if isinstance(
                report.get("calibration_context_cohort"), Mapping
            ) else None
        ),
    }


def record_model_validation(
    store: "PredictionShadowStore",
    *,
    symbol: str,
    execution_model_rule: str,
    experiment_id: str,
    report: Mapping[str, object],
    validated_at_ms: int | None = None,
) -> str:
    """Import one sanitized empirical validation after strict readiness checks."""
    from ladder_dragon.strategy.replay_policy import (
        PRODUCTION_REPLAY_ACCEPTANCE_POLICY,
        ReplayAcceptancePolicy,
    )
    from ladder_dragon.strategy.replay_validation import (
        ReplayValidation,
        replay_acceptance_reasons,
    )
    from ladder_dragon.strategy.replay_cohorts import verify_cohort_fingerprint
    from ladder_dragon.strategy.volatility_policy import (
        verify_volatility_policy,
        verify_volatility_scope,
    )
    from ladder_dragon.strategy.prediction.experiment_lifecycle import (
        load_manifest,
    )
    from ladder_dragon.strategy.prediction.episode_semantics import (
        canonical_digest,
        execution_engine_validation_domain,
    )
    if report.get("ready") is not True:
        raise ValueError("replay validation must contain a strict PASS")
    manifest = load_manifest(store, str(experiment_id))
    parameters = manifest.get("candidate_parameters")
    requires_scoped_volatility = bool(
        isinstance(parameters, Mapping)
        and parameters.get("candidate_rule_version") == 8
    )
    validation = ReplayValidation.from_dict(dict(report))
    observed_policy = validation.acceptance_policy
    if not isinstance(observed_policy, Mapping):
        raise ValueError("replay acceptance policy is unavailable")
    parsed_policy = ReplayAcceptancePolicy.from_dict(observed_policy)
    expected_policy = PRODUCTION_REPLAY_ACCEPTANCE_POLICY
    if (
        parsed_policy != expected_policy
        or validation.acceptance_policy_sha256 != expected_policy.fingerprint
        or replay_acceptance_reasons(validation, expected_policy)
        or validation.reasons
    ):
        raise ValueError("replay acceptance policy or recomputed result differs")
    readiness = validation.replay_readiness
    order_cohort = validation.order_validation_cohort
    context_cohort = validation.calibration_context_cohort
    order_hashes = set(
        order_cohort.get("archive_sha256s", ())
        if isinstance(order_cohort, Mapping) else ()
    )
    order_attempt_count = int(
        order_cohort.get("attempt_count", 0)
        if isinstance(order_cohort, Mapping) else 0
    )
    order_schema = int(
        order_cohort.get("schema_version", 1)
        if isinstance(order_cohort, Mapping) else 0
    )
    order_successful_count = int(
        order_cohort.get("successful_attempt_count", order_attempt_count)
        if isinstance(order_cohort, Mapping) else 0
    )
    context_hashes = set(
        context_cohort.get("archive_sha256s", ())
        if isinstance(context_cohort, Mapping) else ()
    )
    context_readiness = (
        context_cohort.get("readiness")
        if isinstance(context_cohort, Mapping) else None
    )
    context_volatility_policy = (
        context_cohort.get("volatility_policy")
        if isinstance(context_cohort, Mapping) else None
    )
    context_volatility_scope = (
        context_cohort.get("volatility_scope")
        if isinstance(context_cohort, Mapping) else None
    )
    if context_volatility_policy is not None and not (
        isinstance(context_volatility_policy, Mapping)
        and verify_volatility_policy(context_volatility_policy)
    ):
        raise ValueError("replay volatility policy is invalid")
    if requires_scoped_volatility and not (
        isinstance(context_volatility_policy, Mapping)
        and isinstance(context_volatility_scope, Mapping)
        and verify_volatility_scope(
            context_volatility_scope, policy=context_volatility_policy
        )
    ):
        raise ValueError("replay volatility activation scope is invalid")
    confirmed_volatility_buckets = (
        set(context_volatility_scope["confirmed_buckets"])
        if requires_scoped_volatility else {"low", "normal", "high"}
    )
    if (
        not validation.ready
        or validation.covered_orders < 10
        or validation.excluded_orders != 0
        or not isinstance(order_cohort, Mapping)
        or not verify_cohort_fingerprint(order_cohort)
        or order_attempt_count < 10
        or order_successful_count < 10
        or len(order_hashes) != order_successful_count
        or (
            order_schema >= 2
            and (
                int(order_cohort.get("definite_failure_count", 0))
                != order_attempt_count - order_successful_count
                or not isinstance(order_cohort.get("terminal_outcomes"), list)
                or len(order_cohort["terminal_outcomes"])
                != order_attempt_count
            )
        )
        or order_hashes != set(validation.archive_sha256s)
        or len(set(order_cohort.get("order_refs", ()))) < 10
        or not isinstance(context_cohort, Mapping)
        or not verify_cohort_fingerprint(context_cohort)
        or context_cohort.get("scope") != "READ_ONLY_CALIBRATION_CONTEXT"
        or not context_hashes
        or bool(order_hashes & context_hashes)
        or not isinstance(context_readiness, Mapping)
        or context_readiness.get("ready") is not True
        or set(context_readiness.get("archive_sha256s", ())) != context_hashes
        or int(context_readiness.get("archive_count", 0)) < 3
        or D(str(context_readiness.get("span_days", "0"))) < D("2")
        or set(
            context_readiness.get(
                "required_regimes", context_readiness.get("regimes", ())
            )
        ) != confirmed_volatility_buckets
        or not confirmed_volatility_buckets.issubset(
            set(context_readiness.get("regimes", ()))
        )
        or (
            isinstance(context_volatility_policy, Mapping)
            and (
                context_readiness.get("volatility_policy_sha256")
                != context_volatility_policy.get("policy_sha256")
                or context_readiness.get(
                    "volatility_confirmation_after_cutoff"
                ) is not True
            )
        )
        or validation.actual_filled_orders < 1
        or validation.actual_limit_maker_filled_orders < 1
        or validation.actual_stop_limit_filled_orders < 1
        or validation.queue_model != "L2_PRICE_LEVEL_FIFO_PROXY"
        or not isinstance(readiness, Mapping)
        or readiness.get("ready") is not True
        or set(readiness.get("archive_sha256s", ()))
        != order_hashes | context_hashes
        or int(readiness.get("archive_count", 0)) < 3
        or D(str(readiness.get("span_days", "0"))) < D("2")
        or set(
            readiness.get("required_regimes", readiness.get("regimes", ()))
        ) != confirmed_volatility_buckets
        or not confirmed_volatility_buckets.issubset(
            set(readiness.get("regimes", ()))
        )
        or int(readiness.get("measured_latency_archives", 0)) < 1
        or int(readiness.get("execution_sample_count", 0)) < 10
        or int(readiness.get("validated_order_count", 0)) < 10
    ):
        raise ValueError("strict replay readiness is not promotion-ready")
    if (
        manifest.get("symbol") != symbol.upper()
        or manifest.get("current_status") not in {"CONFIRMING", "CONFIRMED"}
        or not isinstance(parameters, Mapping)
        or parameters.get("execution_model_rule") != execution_model_rule
    ):
        raise ValueError("replay validation experiment identity differs")
    schedule = parameters.get("fee_schedule")
    if not isinstance(schedule, Mapping):
        raise ValueError("replay validation fee schedule is unavailable")
    rates = {
        "maker_buy_fee_pct": validation.maker_buy_fee_pct,
        "maker_sell_fee_pct": validation.maker_sell_fee_pct,
        "taker_buy_fee_pct": validation.taker_buy_fee_pct,
        "taker_sell_fee_pct": validation.taker_sell_fee_pct,
    }
    if any(
        value is None or value != D(str(schedule.get(field)))
        for field, value in rates.items()
    ):
        raise ValueError("replay validation fee schedule differs")
    expected_domain = execution_engine_validation_domain(
        execution_model_rule=execution_model_rule,
        fee_schedule=schedule,
        entry_veto_rule=(
            parameters.get("entry_veto_rule")
            if parameters.get("candidate_rule_version") == 8 else None
        ),
    )
    if (
        not isinstance(validation.validation_domain, Mapping)
        or canonical_digest(validation.validation_domain)
        != canonical_digest(expected_domain)
    ):
        raise ValueError("replay validation engine domain differs")
    # The importer verifies the source-owned domain. It never adds proof that
    # the replay report did not contain before this boundary.
    stored_report = dict(report)
    payload_hash = _digest(stored_report)
    source_hash = str(validation.archive_sha256).strip().lower()
    if len(source_hash) != 64 or any(
        character not in "0123456789abcdef" for character in source_hash
    ):
        raise ValueError("replay validation source hash is invalid")
    timestamp = (
        int(time.time() * 1000)
        if validated_at_ms is None else int(validated_at_ms)
    )
    identity = {
        "symbol": symbol.upper(),
        "execution_model_rule": execution_model_rule,
        "report_sha256": payload_hash,
        "source_sha256": source_hash,
        "validated_at_ms": timestamp,
    }
    validation_id = hashlib.sha256(
        _canonical(identity).encode("utf-8")
    ).hexdigest()
    with store._connect() as connection:
        count = int(connection.execute(
            "SELECT COUNT(*) FROM prediction_execution_model_validations"
        ).fetchone()[0])
        if count >= MAXIMUM_MODEL_VALIDATIONS:
            raise RuntimeError("execution model validation capacity reached")
        connection.execute(
            """INSERT INTO prediction_execution_model_validations
               (validation_id,symbol,execution_model_rule,status,
                terminal_orders,filled_orders,report_json,report_sha256,
                source_sha256,validated_at_ms,created_at_ms)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                validation_id,
                symbol.upper(),
                execution_model_rule,
                "PASS",
                validation.covered_orders,
                validation.actual_filled_orders,
                _canonical(stored_report),
                payload_hash,
                source_hash,
                timestamp,
                int(time.time() * 1000),
            ),
        )
    return validation_id


__all__ = [
    "MAXIMUM_EPISODES",
    "MAXIMUM_MODEL_VALIDATIONS",
    "SEQUENTIAL_LOOKS",
    "load_episode_results",
    "migrate_episode_evidence",
    "model_validation_status",
    "record_completed_episode",
    "record_episode_result",
    "record_episode_start",
    "record_model_validation",
    "recover_interrupted_episodes",
    "sequential_episode_report",
]
