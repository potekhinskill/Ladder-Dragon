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
) -> list[ExecutionEpisodeResult]:
    """Load a bounded chronological cohort and verify every payload hash."""
    if not 1 <= int(limit) <= 10_000:
        raise ValueError("episode result limit is invalid")
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


def sequential_episode_report(
    results: Iterable[ExecutionEpisodeResult],
) -> dict[str, object]:
    """Apply the preregistered sign-test alpha spending to primary outcomes."""
    rows = [row for row in results if row.eligible_for_promotion]
    filled = [row for row in rows if row.entry_filled_quantity > 0]
    sign_rows = [row for row in rows if row.net_pnl_quote != ZERO]
    passed_at: int | None = None
    look_reports = []
    for sample_count, alpha in SEQUENTIAL_LOOKS:
        sign_cohort = sign_rows[:sample_count]
        boundary = (
            sign_cohort[-1].terminal_at_ms if len(sign_cohort) == sample_count
            else None
        )
        cohort = [
            row for row in rows
            if boundary is not None and row.terminal_at_ms <= boundary
        ]
        wins = sum(row.net_pnl_quote > ZERO for row in sign_cohort)
        p_value = (
            _sign_tail(wins, len(sign_cohort))
            if sign_cohort else ONE
        )
        cohort_filled = sum(row.entry_filled_quantity > 0 for row in cohort)
        fill_rate = D(cohort_filled) / D(len(cohort)) if cohort else ZERO
        pnl = sum((row.net_pnl_quote for row in cohort), ZERO)
        maximum_notional = max(
            (row.entry_notional_quote for row in cohort), default=ZERO
        )
        drawdown = _maximum_drawdown(row.net_pnl_quote for row in cohort)
        reached = len(sign_rows) >= sample_count
        passed = bool(
            reached
            and p_value <= alpha
            and pnl > ZERO
            and cohort_filled >= MINIMUM_FILLED_EPISODES
            and fill_rate >= MINIMUM_FILL_RATE
            and maximum_notional > ZERO
            and drawdown <= maximum_notional * MAXIMUM_DRAWDOWN_FRACTION
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
            "filled_episodes": cohort_filled,
            "fill_rate": format(fill_rate, "f"),
            "net_pnl_quote": format(pnl, "f"),
            "maximum_drawdown_quote": format(drawdown, "f"),
            "passed": passed,
        })
        if passed and passed_at is None:
            passed_at = sample_count

    regime_boundary = (
        sign_rows[passed_at - 1].terminal_at_ms
        if passed_at is not None else None
    )
    regime_filled = [
        row for row in filled
        if regime_boundary is None or row.terminal_at_ms <= regime_boundary
    ]
    regime_reports: dict[str, dict[str, object]] = {}
    regime_pass = True
    for regime in ("RANGE", "TREND_UP", "TREND_DOWN"):
        cohort = [row for row in regime_filled if row.start_regime == regime]
        pnl = sum((row.net_pnl_quote for row in cohort), ZERO)
        notional = sum((row.entry_notional_quote for row in cohort), ZERO)
        mean_pnl = pnl / D(len(cohort)) if cohort else ZERO
        mean_notional = notional / D(len(cohort)) if cohort else ZERO
        measured = len(cohort) >= 3
        noninferior = (
            mean_pnl >= -mean_notional * REGIME_NONINFERIORITY_FRACTION
            if measured else True
        )
        regime_pass = regime_pass and measured and noninferior
        regime_reports[regime] = {
            "filled_episodes": len(cohort),
            "measured": measured,
            "mean_net_pnl_quote": format(mean_pnl, "f"),
            "noninferior": noninferior,
        }

    panic_rows = [row for row in results if row.panic_veto]
    panic_failures = [
        row for row in panic_rows
        if row.entry_filled_quantity > row.exit_filled_quantity
    ]
    status = "PASS" if passed_at is not None and regime_pass else "SHADOW"
    if len(rows) >= MAXIMUM_TERMINAL_EPISODES and passed_at is None:
        status = "READY_TO_REJECT"
    next_look = next(
        (sample_count for sample_count, _alpha in SEQUENTIAL_LOOKS
         if sample_count > len(sign_rows)),
        None,
    )
    durations = [
        D(row.terminal_at_ms - row.started_at_ms)
        for row in rows if row.terminal_at_ms > row.started_at_ms
    ]
    mean_duration_ms = (
        sum(durations, ZERO) / D(len(durations)) if durations else None
    )
    projected_ready_ts_ms = (
        int(
            rows[-1].terminal_at_ms
            + mean_duration_ms
            * D(next_look - len(sign_rows))
            / (D(len(sign_rows)) / D(len(rows)))
        )
        if (
            rows and sign_rows and mean_duration_ms is not None
            and next_look is not None
        )
        else None
    )
    return {
        "schema_version": 1,
        "method": "group_sequential_sign_test_alpha_spending_v1",
        "primary_horizon_min": 360,
        "diagnostic_horizons_min": [300],
        "eligible_terminal_episodes": len(rows),
        "filled_episodes": len(filled),
        "nonzero_sign_trials": len(sign_rows),
        "maximum_terminal_episodes": MAXIMUM_TERMINAL_EPISODES,
        "maximum_confirmation_duration_ms": MAXIMUM_CONFIRMATION_DURATION_MS,
        "power_analysis": {
            "scope": "conditional_nonzero_sign_test_only",
            "positive_outcome_probability": format(
                DESIGN_POSITIVE_OUTCOME_PROBABILITY, "f"
            ),
            "target_power": format(DESIGN_TARGET_POWER, "f"),
            "maximum_look_power": format(
                _design_power(*SEQUENTIAL_LOOKS[-1]), "f"
            ),
        },
        "alpha_total": format(sum((alpha for _n, alpha in SEQUENTIAL_LOOKS), ZERO), "f"),
        "looks": look_reports,
        "passed_at_episode": passed_at,
        "next_sequential_look": next_look,
        "mean_episode_duration_ms": (
            format(mean_duration_ms, "f") if mean_duration_ms is not None else None
        ),
        "projected_ready_ts_ms": projected_ready_ts_ms,
        "readiness_reason": (
            "preregistered sequential boundary passed"
            if status == "PASS" else
            "all preregistered looks failed"
            if status == "READY_TO_REJECT" else
            "waiting for terminal sequential episodes"
        ),
        "regime_safety": regime_reports,
        "regime_noninferiority_passed": regime_pass,
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
    from ladder_dragon.strategy.replay_validation import ReplayValidation
    from ladder_dragon.strategy.prediction.experiment_lifecycle import (
        load_manifest,
    )
    if report.get("ready") is not True:
        raise ValueError("replay validation must contain a strict PASS")
    validation = ReplayValidation.from_dict(dict(report))
    if (
        not validation.ready
        or validation.covered_orders < 10
        or validation.actual_filled_orders < 1
        or validation.actual_limit_maker_filled_orders < 1
        or validation.actual_stop_limit_filled_orders < 1
        or validation.queue_model != "L2_PRICE_LEVEL_FIFO_PROXY"
    ):
        raise ValueError("replay validation is not promotion-ready")
    manifest = load_manifest(store, str(experiment_id))
    parameters = manifest.get("candidate_parameters")
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
    payload_hash = _digest(dict(report))
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
                _canonical(dict(report)),
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
    "record_episode_result",
    "record_episode_start",
    "record_model_validation",
    "recover_interrupted_episodes",
    "sequential_episode_report",
]
