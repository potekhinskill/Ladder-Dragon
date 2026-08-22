# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: separate SHADOW candidate selection from independent confirmation.
"""Immutable experiment manifests and restart-safe confirmation evidence."""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json
import sqlite3
import time
from typing import Iterable, Mapping, Sequence, TYPE_CHECKING

from ladder_dragon.strategy.prediction.confirmation_statistics import (
    DEFAULT_CONFIRMATION_CRITERIA,
    DecisionEvidence,
    block_confirmation_gate,
    drawdown,
    non_overlapping_decisions,
    summarize_window,
    validate_confirmation_criteria,
)
from ladder_dragon.strategy.prediction.models import ResolvedSample
from ladder_dragon.strategy.prediction.statistical_design import (
    DEFAULT_STATISTICAL_DESIGN,
    EXPECTANCY_REGIMES,
)

if TYPE_CHECKING:
    from ladder_dragon.strategy.prediction.experiments import ShadowVariant
    from ladder_dragon.strategy.prediction.runtime import PredictionShadowStore


D = Decimal
ZERO = D("0")
MANIFEST_SCHEMA_VERSION = 3
REPORT_SCHEMA_VERSION = 5
STATISTICAL_METHOD_VERSION = "powered-historical-cold-start-v1"
EVIDENCE_ROLES = frozenset({"SELECTION", "CONFIRMATION", "DIAGNOSTIC", "LEGACY"})
LIFECYCLE_STATES = frozenset({
    "SELECTION", "FROZEN", "CONFIRMING", "CONFIRMED", "REJECTED",
    "SUPERSEDED", "BLOCKED",
})
TERMINAL_STATES = frozenset({"CONFIRMED", "REJECTED", "SUPERSEDED", "BLOCKED"})
ALLOWED_TRANSITIONS = {
    "SELECTION": frozenset({"FROZEN", "BLOCKED"}),
    "FROZEN": frozenset({"CONFIRMING", "SUPERSEDED", "BLOCKED"}),
    "CONFIRMING": frozenset({"CONFIRMED", "REJECTED", "SUPERSEDED", "BLOCKED"}),
    "CONFIRMED": frozenset({"SUPERSEDED"}),
    "REJECTED": frozenset({"SUPERSEDED"}),
    "SUPERSEDED": frozenset(),
    "BLOCKED": frozenset({"SUPERSEDED"}),
}
DEFAULT_CRITERIA = DEFAULT_CONFIRMATION_CRITERIA


def canonical_json(value: object) -> str:
    """Return the deterministic serialization used for all fingerprints."""
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def sha256_json(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def selection_experiment_id(generation: str, symbol: str) -> str:
    return f"selection:{generation.lower()}:{symbol.upper()}"


def migrate_experiment_lifecycle(connection: sqlite3.Connection) -> None:
    """Create append-only lifecycle tables without changing old evidence roles."""
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(prediction_decisions)")
    }
    if "experiment_id" not in columns:
        connection.execute(
            "ALTER TABLE prediction_decisions ADD COLUMN experiment_id TEXT"
        )
    if "evidence_role" not in columns:
        # Existing evidence predates the protocol and remains LEGACY.
        connection.execute(
            "ALTER TABLE prediction_decisions "
            "ADD COLUMN evidence_role TEXT NOT NULL DEFAULT 'LEGACY'"
        )
    if "candidate_fingerprint" not in columns:
        connection.execute(
            "ALTER TABLE prediction_decisions "
            "ADD COLUMN candidate_fingerprint TEXT"
        )
    if "baseline_fingerprint" not in columns:
        connection.execute(
            "ALTER TABLE prediction_decisions "
            "ADD COLUMN baseline_fingerprint TEXT"
        )
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS prediction_experiment_manifests (
            experiment_id TEXT PRIMARY KEY,
            schema_version INTEGER NOT NULL,
            generation TEXT NOT NULL,
            symbol TEXT NOT NULL,
            selected_variant TEXT NOT NULL,
            selection_experiment_id TEXT NOT NULL,
            selection_end_ts_ms INTEGER NOT NULL,
            confirmation_start_ts_ms INTEGER NOT NULL,
            manifest_json TEXT NOT NULL,
            manifest_sha256 TEXT NOT NULL UNIQUE,
            created_at_ms INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS prediction_experiment_transitions (
            transition_id INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id TEXT NOT NULL,
            from_status TEXT NOT NULL,
            to_status TEXT NOT NULL,
            changed_at_ms INTEGER NOT NULL,
            reason TEXT NOT NULL,
            FOREIGN KEY(experiment_id)
                REFERENCES prediction_experiment_manifests(experiment_id)
        );
        CREATE INDEX IF NOT EXISTS prediction_experiment_scope
            ON prediction_experiment_manifests(generation, symbol, created_at_ms);
        CREATE INDEX IF NOT EXISTS prediction_experiment_transition_order
            ON prediction_experiment_transitions(experiment_id, transition_id);
        CREATE TRIGGER IF NOT EXISTS prediction_experiment_manifest_no_update
        BEFORE UPDATE ON prediction_experiment_manifests
        BEGIN SELECT RAISE(ABORT, 'frozen experiment manifest is immutable'); END;
        CREATE TRIGGER IF NOT EXISTS prediction_experiment_manifest_no_delete
        BEFORE DELETE ON prediction_experiment_manifests
        BEGIN SELECT RAISE(ABORT, 'frozen experiment manifest is immutable'); END;
        CREATE TRIGGER IF NOT EXISTS prediction_experiment_transition_no_update
        BEFORE UPDATE ON prediction_experiment_transitions
        BEGIN SELECT RAISE(ABORT, 'experiment transitions are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS prediction_experiment_transition_no_delete
        BEFORE DELETE ON prediction_experiment_transitions
        BEGIN SELECT RAISE(ABORT, 'experiment transitions are append-only'); END;
    """)
    from ladder_dragon.strategy.prediction.champion_registry import (
        migrate_champion_registry,
    )
    migrate_champion_registry(connection)
    from ladder_dragon.strategy.prediction.episode_evidence import (
        migrate_episode_evidence,
    )
    migrate_episode_evidence(connection)


def _ratio(numerator: Decimal, denominator: Decimal, *, field: str) -> str:
    if denominator <= 0:
        raise ValueError(f"{field} denominator must be positive")
    return format(numerator / denominator, "f")


def _fee_schedule_rule(plan: "TradePlan") -> dict[str, object]:
    """Describe exact fee provenance without using account identifiers."""
    return {
        "provenance": plan.fee_provenance,
        "conservative_fee_pct": format(plan.fee_pct, "f"),
        "maker_buy_fee_pct": (
            format(plan.maker_buy_fee_pct, "f")
            if plan.maker_buy_fee_pct is not None else None
        ),
        "maker_sell_fee_pct": (
            format(plan.maker_sell_fee_pct, "f")
            if plan.maker_sell_fee_pct is not None else None
        ),
        "taker_buy_fee_pct": (
            format(plan.taker_buy_fee_pct, "f")
            if plan.taker_buy_fee_pct is not None else None
        ),
        "taker_sell_fee_pct": (
            format(plan.taker_sell_fee_pct, "f")
            if plan.taker_sell_fee_pct is not None else None
        ),
    }


def candidate_rule(
    variant: "ShadowVariant",
    *,
    generation: str,
    horizons_min: Sequence[int],
) -> dict[str, object]:
    """Describe stable decision semantics without a snapshot's absolute price."""
    plan = variant.plan
    common = {
        "generation": generation,
        "variant_id": variant.variant_id,
        "dimension": variant.dimension,
        "entry_gap_bps": (
            format(variant.entry_gap_bps, "f")
            if variant.entry_gap_bps is not None else None
        ),
        "entry_ttl_sec": plan.entry_ttl_sec,
        "entry_enabled": plan.entry_enabled,
        "target_return": _ratio(
            plan.take_profit_price - plan.entry_price,
            plan.entry_price,
            field="target return",
        ),
        "stop_distance": _ratio(
            plan.entry_price - plan.stop_price,
            plan.entry_price,
            field="stop distance",
        ),
        "fee_pct": format(plan.fee_pct, "f"),
        "slippage_pct": format(plan.slippage_pct, "f"),
        "notional_policy": (
            "fixed_shadow_evidence_notional"
            if variant.candidate_rule_version == 3
            else "current_strategy_cap"
        ),
        "evidence_notional_quote": (
            format(plan.notional_quote, "f")
            if variant.candidate_rule_version == 3 else None
        ),
        "regime_policy": variant.regime_policy,
        "horizons_min": [int(value) for value in horizons_min],
        "model_rule": variant.model_rule,
        "online_update_rule": "immutable_code_and_past_resolved_evidence_only",
    }
    if variant.candidate_rule_version == 1:
        return {
            **common,
            "entry_order_policy": (
                "LIMIT_MAKER" if variant.maker_only else "BASELINE"
            ),
            "exit_order_policy": (
                "LIMIT_MAKER" if variant.maker_only else "BASELINE"
            ),
        }
    if variant.candidate_rule_version not in {2, 3}:
        raise ValueError("candidate rule version is unsupported")
    rule = {
        **common,
        "candidate_rule_version": variant.candidate_rule_version,
        "entry_order_policy": (
            "LIMIT_MAKER" if variant.maker_only else "BASELINE"
        ),
        "take_profit_order_policy": (
            "LIMIT_MAKER" if variant.maker_only else "BASELINE"
        ),
        "stop_order_policy": (
            "STOP_LOSS_LIMIT" if variant.maker_only else "BASELINE"
        ),
        "execution_model_rule": variant.execution_model_rule,
        "execution_model_promotion_ready": (
            variant.execution_model_promotion_ready
        ),
        "fee_schedule": _fee_schedule_rule(plan),
    }
    if variant.candidate_rule_version == 3:
        if plan.maximum_holding_min is None:
            raise ValueError("promotion candidate requires maximum holding time")
        rule.update({
            "stop_limit_distance": common["stop_distance"],
            "stop_trigger_offset_pct": format(
                plan.stop_limit_offset_pct, "f"
            ),
            "maximum_holding_min": plan.maximum_holding_min,
            "primary_horizon_min": max(int(value) for value in horizons_min),
            "diagnostic_horizons_min": [
                int(value) for value in horizons_min
                if int(value) != max(int(item) for item in horizons_min)
            ],
            "episode_concurrency": 1,
            "panic_policy": "SEPARATE_SAFETY_VETO",
        })
    return rule


def baseline_rule(variant: "ShadowVariant") -> dict[str, object]:
    plan = variant.baseline_plan
    rule = {
        "rule": "current_strategy_plan",
        "target_return": _ratio(
            plan.take_profit_price - plan.entry_price,
            plan.entry_price,
            field="baseline target return",
        ),
        "stop_distance": _ratio(
            plan.entry_price - plan.stop_price,
            plan.entry_price,
            field="baseline stop distance",
        ),
        "fee_pct": format(plan.fee_pct, "f"),
        "slippage_pct": format(plan.slippage_pct, "f"),
        "entry_ttl_sec": plan.entry_ttl_sec,
        "entry_enabled": plan.entry_enabled,
    }
    if variant.candidate_rule_version in {2, 3}:
        rule["fee_schedule"] = _fee_schedule_rule(plan)
    return rule


def variant_fingerprints(
    variant: "ShadowVariant",
    *,
    generation: str,
    horizons_min: Sequence[int],
    criteria: Mapping[str, object] | None = None,
) -> tuple[str, str]:
    policy = dict(DEFAULT_CRITERIA if criteria is None else criteria)
    if policy.get("criteria_schema_version") != 2:
        if int(policy["embargo_ms"]) < 0:
            raise ValueError("confirmation embargo must be non-negative")
        if int(policy["window_size_decisions"]) <= 0:
            raise ValueError("confirmation window size must be positive")
        if int(policy["required_complete_windows"]) <= 0:
            raise ValueError("required confirmation windows must be positive")
        if not 0 < int(policy["minimum_positive_windows"]) <= int(
            policy["required_complete_windows"]
        ):
            raise ValueError("positive confirmation windows are invalid")
        if (
            int(policy["window_size_decisions"])
            * int(policy["required_complete_windows"])
            < int(policy["min_independent_samples"])
        ):
            raise ValueError("confirmation windows cannot weaken the sample minimum")
    candidate = {
        "candidate": candidate_rule(
            variant, generation=generation, horizons_min=horizons_min
        ),
        "criteria": policy,
    }
    return sha256_json(candidate), sha256_json(baseline_rule(variant))


def _current_status(connection: sqlite3.Connection, experiment_id: str) -> str:
    rows = connection.execute(
        """SELECT from_status,to_status FROM prediction_experiment_transitions
           WHERE experiment_id=? ORDER BY transition_id""",
        (experiment_id,),
    ).fetchall()
    if not rows:
        raise ValueError("experiment has no lifecycle transition")
    expected = str(rows[0][0])
    for from_status, to_status in rows:
        if str(from_status) != expected:
            raise ValueError("experiment transition history is ambiguous")
        expected = str(to_status)
    if expected not in LIFECYCLE_STATES:
        raise ValueError("experiment lifecycle status is invalid")
    return expected


def transition_experiment(
    connection: sqlite3.Connection,
    *,
    experiment_id: str,
    to_status: str,
    reason: str,
    changed_at_ms: int | None = None,
) -> str:
    """Append one validated state transition inside the caller transaction."""
    target = str(to_status).upper()
    current = _current_status(connection, experiment_id)
    if target == current:
        return current
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise ValueError(f"invalid experiment transition: {current} to {target}")
    connection.execute(
        """INSERT INTO prediction_experiment_transitions
           (experiment_id,from_status,to_status,changed_at_ms,reason)
           VALUES(?,?,?,?,?)""",
        (
            experiment_id,
            current,
            target,
            int(time.time() * 1000) if changed_at_ms is None else int(changed_at_ms),
            str(reason)[:240],
        ),
    )
    return target


def _manifest_row(connection: sqlite3.Connection, experiment_id: str) -> tuple:
    row = connection.execute(
        """SELECT manifest_json,manifest_sha256,generation,symbol,selected_variant,
                  selection_end_ts_ms,confirmation_start_ts_ms
           FROM prediction_experiment_manifests WHERE experiment_id=?""",
        (experiment_id,),
    ).fetchone()
    if row is None:
        raise ValueError("experiment manifest is missing")
    payload = json.loads(str(row[0]))
    if sha256_json(payload) != str(row[1]):
        raise ValueError("experiment manifest fingerprint differs")
    return row


def load_manifest(
    store: "PredictionShadowStore", experiment_id: str
) -> dict[str, object]:
    with store._connect() as connection:
        row = _manifest_row(connection, experiment_id)
        payload = json.loads(str(row[0]))
        payload["manifest_sha256"] = str(row[1])
        payload["current_status"] = _current_status(connection, experiment_id)
        return payload


def list_experiments(
    store: "PredictionShadowStore", *, symbol: str | None = None
) -> list[dict[str, object]]:
    query = "SELECT experiment_id FROM prediction_experiment_manifests"
    params: tuple[object, ...] = ()
    if symbol is not None:
        query += " WHERE symbol=?"
        params = (symbol.upper(),)
    query += " ORDER BY created_at_ms,experiment_id"
    with store._connect() as connection:
        identifiers = [str(row[0]) for row in connection.execute(query, params)]
    return [load_manifest(store, item) for item in identifiers]


def _active_manifest(
    store: "PredictionShadowStore", *, generation: str, symbol: str
) -> dict[str, object] | None:
    candidates = [
        row for row in list_experiments(store, symbol=symbol)
        if row.get("generation") == generation
        and row.get("current_status") not in TERMINAL_STATES
    ]
    if len(candidates) > 1:
        raise ValueError("multiple active experiment manifests")
    return candidates[0] if candidates else None


def evidence_assignment(
    store: "PredictionShadowStore",
    *,
    generation: str,
    symbol: str,
    variant: "ShadowVariant",
    horizons_min: Sequence[int],
    snapshot_ts_ms: int,
) -> tuple[str, str]:
    """Assign one new snapshot without ever relabeling historical evidence."""
    active = _active_manifest(store, generation=generation, symbol=symbol)
    if active is None:
        prior = [
            row for row in list_experiments(store, symbol=symbol)
            if row.get("generation") == generation
        ]
        if prior:
            # A completed generation cannot silently start a second hypothesis.
            return f"diagnostic:{generation.lower()}:{symbol.upper()}", "DIAGNOSTIC"
        return selection_experiment_id(generation, symbol), "SELECTION"
    if int(snapshot_ts_ms) < int(active["confirmation_start_ts_ms"]):
        return str(active["experiment_id"]), "DIAGNOSTIC"
    if variant.variant_id != active["selected_variant"]:
        return str(active["experiment_id"]), "DIAGNOSTIC"
    candidate_fp, baseline_fp = variant_fingerprints(
        variant,
        generation=generation,
        horizons_min=horizons_min,
        criteria=active["criteria"],
    )
    if (
        candidate_fp != active["candidate_fingerprint"]
        or baseline_fp != active["baseline_fingerprint"]
    ):
        with store._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            transition_experiment(
                connection,
                experiment_id=str(active["experiment_id"]),
                to_status="BLOCKED",
                reason="candidate or baseline fingerprint changed",
            )
            connection.commit()
        return str(active["experiment_id"]), "DIAGNOSTIC"
    return str(active["experiment_id"]), "CONFIRMATION"


def freeze_experiment(
    store: "PredictionShadowStore",
    *,
    experiment_id: str,
    generation: str,
    symbol: str,
    selected_variant: "ShadowVariant",
    all_variants: Iterable["ShadowVariant"],
    horizons_min: Sequence[int],
    selection_end_ts_ms: int,
    product_version: str,
    source_commit: str,
    frozen_at_ms: int | None = None,
    criteria: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Freeze an explicitly selected candidate after complete selection outcomes."""
    identifier = str(experiment_id).strip()
    if not identifier or len(identifier) > 120:
        raise ValueError("experiment_id must contain 1 to 120 characters")
    policy = dict(DEFAULT_CRITERIA if criteria is None else criteria)
    required = tuple(int(value) for value in horizons_min)
    if not required or sorted(set(required)) != list(required):
        raise ValueError("manifest horizons must be unique and increasing")
    feasibility = validate_confirmation_criteria(
        policy, required_horizons_min=required
    )
    variants = tuple(all_variants)
    if selected_variant.variant_id not in {row.variant_id for row in variants}:
        raise ValueError("selected variant is not in the selection cohort")
    cohort = selection_experiment_id(generation, symbol)
    cutoff = int(selection_end_ts_ms)
    frozen_at = int(time.time() * 1000) if frozen_at_ms is None else int(frozen_at_ms)
    with store._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute(
            "SELECT 1 FROM prediction_experiment_manifests WHERE experiment_id=?",
            (identifier,),
        ).fetchone():
            raise ValueError("experiment_id is already frozen")
        kinds = tuple(row.kind for row in variants)
        placeholders = ",".join("?" for _ in kinds)
        decisions = connection.execute(
            f"""SELECT d.decision_id,d.kind,d.snapshot_ts_ms,
                       COUNT(o.horizon_min),
                       SUM(CASE WHEN o.outcome_json IS NOT NULL THEN 1 ELSE 0 END),
                       MAX(o.eligible_at_ms),d.candidate_fingerprint,
                       d.baseline_fingerprint
                FROM prediction_decisions d
                JOIN prediction_outcomes o ON o.decision_id=d.decision_id
                WHERE d.experiment_id=? AND d.evidence_role='SELECTION'
                  AND d.symbol=? AND d.snapshot_ts_ms<=?
                  AND d.kind IN ({placeholders})
                GROUP BY d.decision_id,d.kind,d.snapshot_ts_ms""",
            (cohort, symbol.upper(), cutoff, *kinds),
        ).fetchall()
        if not decisions:
            raise ValueError("closed selection cohort is missing")
        observed_kinds = {str(row[1]) for row in decisions}
        if observed_kinds != set(kinds):
            raise ValueError("selection cohort does not contain every candidate")
        snapshots_by_kind = {
            kind: [int(row[2]) for row in decisions if str(row[1]) == kind]
            for kind in kinds
        }
        if any(
            len(snapshots) != len(set(snapshots))
            for snapshots in snapshots_by_kind.values()
        ):
            raise ValueError("selection cohort contains duplicate candidate snapshots")
        snapshot_sets = [set(snapshots) for snapshots in snapshots_by_kind.values()]
        if not snapshot_sets or any(
            snapshots != snapshot_sets[0] for snapshots in snapshot_sets[1:]
        ):
            raise ValueError("selection candidates do not share identical snapshots")
        if cutoff != max(snapshot_sets[0]):
            raise ValueError("selection cutoff is not the final shared snapshot")
        if any(int(row[3]) != len(required) or int(row[4] or 0) != len(required) for row in decisions):
            raise ValueError("selection outcomes are not fully closed")
        if any(int(row[2]) > cutoff for row in decisions):
            raise ValueError("selection cutoff is inconsistent")
        last_eligible = max(int(row[5]) for row in decisions)
        if frozen_at <= last_eligible:
            raise ValueError("freeze time precedes closed selection evidence")
        embargo = int(policy["embargo_ms"])
        confirmation_start = max(frozen_at, last_eligible + 1 + embargo)
        minimum_boundary = cutoff + max(required) * 60_000 + embargo
        if confirmation_start < minimum_boundary:
            raise ValueError("confirmation boundary is not purged")
        candidate_fp, baseline_fp = variant_fingerprints(
            selected_variant,
            generation=generation,
            horizons_min=required,
            criteria=policy,
        )
        selected_rows = [row for row in decisions if str(row[1]) == selected_variant.kind]
        if any(
            str(row[6] or "") != candidate_fp
            or str(row[7] or "") != baseline_fp
            for row in selected_rows
        ):
            raise ValueError("selection fingerprint differs from selected candidate")
        # Freeze is an irreversible boundary. A complete cohort is necessary,
        # but it is not sufficient unless the preregistered selection gate passed.
        from ladder_dragon.strategy.prediction.experiments import (
            shadow_variant_report,
        )
        selection_report = shadow_variant_report(
            store,
            symbol=symbol,
            variants=variants,
            before_ts_ms=cutoff,
            resolved_before_ts_ms=frozen_at,
            generation=generation,
            horizons_min=required,
        )
        selected_report = selection_report["variants"].get(
            selected_variant.variant_id, {}
        )
        if not bool(selected_report.get("selection_gate_passed")):
            raise ValueError("selected candidate did not pass the selection gate")
        manifest = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "experiment_id": identifier,
            "generation": generation,
            "symbol": symbol.upper(),
            "scope": {"symbol": symbol.upper()},
            "selected_variant": selected_variant.variant_id,
            "candidate_parameters": candidate_rule(
                selected_variant,
                generation=generation,
                horizons_min=required,
            ),
            "candidate_fingerprint": candidate_fp,
            "baseline": baseline_rule(selected_variant),
            "baseline_fingerprint": baseline_fp,
            "criteria": policy,
            "statistical_method": STATISTICAL_METHOD_VERSION,
            "independence_spacing_ms": feasibility[
                "independence_spacing_ms"
            ],
            "selection_rule": "explicit_operator_choice_after_configuration_holm_review",
            "selection_gate_passed": True,
            "selection_gate_policy": "walk_forward_configuration_holm_v1",
            "selection_experiment_id": cohort,
            "selection_end_ts_ms": cutoff,
            "frozen_at_ms": frozen_at,
            "confirmation_start_ts_ms": confirmation_start,
            "product_version": str(product_version),
            "source_commit": str(source_commit),
            "lifecycle_status": "FROZEN",
            "can_change_orders": False,
            "apply_allowed": False,
        }
        encoded = canonical_json(manifest)
        digest = sha256_json(manifest)
        connection.execute(
            """INSERT INTO prediction_experiment_manifests
               (experiment_id,schema_version,generation,symbol,selected_variant,
                selection_experiment_id,selection_end_ts_ms,
                confirmation_start_ts_ms,manifest_json,manifest_sha256,created_at_ms)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                identifier, MANIFEST_SCHEMA_VERSION, generation, symbol.upper(),
                selected_variant.variant_id, cohort, cutoff, confirmation_start,
                encoded, digest, frozen_at,
            ),
        )
        connection.execute(
            """INSERT INTO prediction_experiment_transitions
               (experiment_id,from_status,to_status,changed_at_ms,reason)
               VALUES(?,?,?,?,?)""",
            (identifier, "SELECTION", "FROZEN", frozen_at, "operator freeze"),
        )
        connection.commit()
    result = dict(manifest)
    result["manifest_sha256"] = digest
    result["current_status"] = "FROZEN"
    return result


def freeze_preselected_episode_experiment(
    store: "PredictionShadowStore",
    *,
    experiment_id: str,
    generation: str,
    symbol: str,
    selected_variant: "ShadowVariant",
    horizons_min: Sequence[int],
    product_version: str,
    source_commit: str,
    frozen_at_ms: int | None = None,
) -> dict[str, object]:
    """Freeze one preregistered candidate before live episode confirmation."""
    from ladder_dragon.strategy.prediction.experiment_config import (
        experiment_spec_for_generation,
    )
    from ladder_dragon.strategy.prediction.episode_evidence import (
        episode_confirmation_criteria,
    )
    spec = experiment_spec_for_generation(generation, symbol=symbol)
    if spec.lifecycle_mode != "PROMOTION" or len(spec.maker_ttls) != 1 or len(spec.maker_entry_gaps) != 1:
        raise ValueError("episode bootstrap requires one promotion candidate")
    required = tuple(int(value) for value in horizons_min)
    if required != spec.horizons_min:
        raise ValueError("episode horizons differ from the preregistered design")
    frozen_at = int(time.time() * 1000) if frozen_at_ms is None else int(frozen_at_ms)
    criteria = episode_confirmation_criteria(spec.statistical_design_version)
    maximum_duration_ms = int(criteria["maximum_confirmation_duration_ms"])
    candidate_fp, baseline_fp = variant_fingerprints(
        selected_variant,
        generation=generation,
        horizons_min=required,
        criteria=criteria,
    )
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "experiment_id": str(experiment_id),
        "generation": generation,
        "symbol": symbol.upper(),
        "scope": {"symbol": symbol.upper()},
        "selected_variant": selected_variant.variant_id,
        "candidate_parameters": candidate_rule(
            selected_variant,
            generation=generation,
            horizons_min=required,
        ),
        "candidate_fingerprint": candidate_fp,
        "baseline": baseline_rule(selected_variant),
        "baseline_fingerprint": baseline_fp,
        "criteria": criteria,
        "statistical_method": criteria["method"],
        "independence_spacing_ms": None,
        "selection_rule": "preregistered_single_candidate_before_live_confirmation",
        "selection_gate_passed": True,
        "selection_gate_policy": "historical_selection_variance_only_v1",
        "historical_evidence_role": "SELECTION_AND_VARIANCE_ONLY",
        "historical_evidence_reused_for_confirmation": False,
        "selection_experiment_id": selection_experiment_id(generation, symbol),
        "selection_end_ts_ms": frozen_at,
        "frozen_at_ms": frozen_at,
        "confirmation_start_ts_ms": frozen_at + 1,
        "confirmation_deadline_ts_ms": (
            frozen_at + 1 + maximum_duration_ms
        ),
        "product_version": str(product_version),
        "source_commit": str(source_commit),
        "lifecycle_status": "CONFIRMING",
        "can_change_orders": False,
        "apply_allowed": False,
    }
    digest = sha256_json(manifest)
    if _active_manifest(store, generation=generation, symbol=symbol) is not None:
        raise ValueError("generation already has an active experiment")
    with store._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute(
            "SELECT 1 FROM prediction_experiment_manifests WHERE experiment_id=?",
            (str(experiment_id),),
        ).fetchone():
            raise ValueError("experiment_id is already frozen")
        connection.execute(
            """INSERT INTO prediction_experiment_manifests
               (experiment_id,schema_version,generation,symbol,selected_variant,
                selection_experiment_id,selection_end_ts_ms,
                confirmation_start_ts_ms,manifest_json,manifest_sha256,created_at_ms)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                str(experiment_id), MANIFEST_SCHEMA_VERSION, generation,
                symbol.upper(), selected_variant.variant_id,
                selection_experiment_id(generation, symbol), frozen_at,
                frozen_at + 1, canonical_json(manifest), digest, frozen_at,
            ),
        )
        connection.execute(
            """INSERT INTO prediction_experiment_transitions
               (experiment_id,from_status,to_status,changed_at_ms,reason)
               VALUES(?,?,?,?,?)""",
            (str(experiment_id), "SELECTION", "FROZEN", frozen_at,
             "preregistered single-candidate freeze"),
        )
        transition_experiment(
            connection,
            experiment_id=str(experiment_id),
            to_status="CONFIRMING",
            reason="live episode confirmation started",
            changed_at_ms=frozen_at + 1,
        )
        connection.commit()
    return load_manifest(store, str(experiment_id))


def _episode_confirmation_report(
    store: "PredictionShadowStore",
    manifest: Mapping[str, object],
) -> dict[str, object]:
    """Evaluate only terminal episodes created after the frozen boundary."""
    from ladder_dragon.strategy.prediction.episode_evidence import (
        load_episode_results,
        model_validation_status,
        sequential_episode_report,
    )
    parameters = manifest["candidate_parameters"]
    results = load_episode_results(
        store,
        symbol=str(manifest["symbol"]),
        generation=str(manifest["generation"]),
        variant_id=str(manifest["selected_variant"]),
        started_after_ms=int(manifest["confirmation_start_ts_ms"]),
        candidate_fingerprint=str(manifest["candidate_fingerprint"]),
        execution_model_rule=str(parameters["execution_model_rule"]),
    )
    sequential = sequential_episode_report(
        results,
        criteria=manifest.get("criteria"),
    )
    deadline = int(manifest["confirmation_deadline_ts_ms"])
    deadline_expired = int(time.time() * 1000) > deadline
    if deadline_expired and sequential["status"] != "PASS":
        sequential = dict(sequential)
        sequential["status"] = "READY_TO_REJECT"
        sequential["approved"] = False
        sequential["readiness_reason"] = (
            "preregistered confirmation deadline expired"
        )
    sequential["confirmation_deadline_ts_ms"] = deadline
    sequential["confirmation_deadline_expired"] = deadline_expired
    validation = model_validation_status(
        store,
        symbol=str(manifest["symbol"]),
        execution_model_rule=str(parameters["execution_model_rule"]),
        expected_fee_schedule=parameters["fee_schedule"],
    )
    evaluation_passed = bool(sequential["approved"])
    validation_passed = validation.get("status") == "PASS"
    sequential["execution_model_projected_ready_ts_ms"] = (
        int(time.time() * 1000) if validation_passed else None
    )
    sequential["champion_projected_ready_ts_ms"] = (
        max(
            int(sequential["projected_ready_ts_ms"] or 0),
            int(sequential["execution_model_projected_ready_ts_ms"] or 0),
        )
        if evaluation_passed and validation_passed else None
    )
    finalization_ready = sequential["status"] in {"PASS", "READY_TO_REJECT"}
    lifecycle_status = str(manifest["current_status"])
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "experiment_lifecycle_status": lifecycle_status,
        "experiment_id": manifest["experiment_id"],
        "generation": manifest["generation"],
        "selected_variant": manifest["selected_variant"],
        "candidate_fingerprint": manifest["candidate_fingerprint"],
        "baseline_fingerprint": manifest["baseline_fingerprint"],
        "selection_cutoff_ts_ms": manifest["selection_end_ts_ms"],
        "confirmation_start_ts_ms": manifest["confirmation_start_ts_ms"],
        "confirmation_status": (
            "PASSED" if lifecycle_status == "CONFIRMED" and evaluation_passed
            else "READY_TO_FINALIZE" if finalization_ready else "IN_PROGRESS"
        ),
        "confirmation_progress": sequential,
        "statistical_method": sequential["method"],
        "blocking_reasons": (
            [] if evaluation_passed else [
                "preregistered live episode test has not passed"
            ]
        ),
        "evaluation_passed": evaluation_passed,
        "finalization_ready": finalization_ready,
        "proposed_final_status": (
            "CONFIRMED" if evaluation_passed else "REJECTED"
        ) if finalization_ready else None,
        "first_gate_passed": lifecycle_status == "CONFIRMED" and evaluation_passed,
        "eligible_for_second_gate_review": (
            lifecycle_status == "CONFIRMED" and evaluation_passed
        ),
        "execution_model_gate": validation,
        "promotion_eligible": bool(
            lifecycle_status == "CONFIRMED"
            and evaluation_passed
            and validation_passed
        ),
        "apply_allowed": False,
        "can_change_orders": False,
        "lookahead": False,
    }
    report["report_sha256"] = sha256_json(report)
    return report


def _confirmation_decisions(
    store: "PredictionShadowStore", manifest: Mapping[str, object]
) -> tuple[list[DecisionEvidence], list[str]]:
    required = tuple(int(value) for value in manifest["candidate_parameters"]["horizons_min"])
    with store._connect() as connection:
        rows = connection.execute(
            """SELECT d.decision_id,d.snapshot_ts_ms,d.feature_json,
                      o.horizon_min,o.outcome_json,o.baseline_outcome_json,
                      d.candidate_fingerprint,d.baseline_fingerprint,
                      d.plan_json,d.baseline_plan_json
               FROM prediction_decisions d
               JOIN prediction_outcomes o ON o.decision_id=d.decision_id
               WHERE d.experiment_id=? AND d.evidence_role='CONFIRMATION'
                 AND d.symbol=? AND d.kind=? AND d.snapshot_ts_ms>=?
               ORDER BY d.snapshot_ts_ms,d.decision_id,o.horizon_min""",
            (
                manifest["experiment_id"], manifest["symbol"],
                f"EXPERIMENT_{str(manifest['selected_variant']).upper()}",
                int(manifest["confirmation_start_ts_ms"]),
            ),
        ).fetchall()
    grouped: dict[str, list[tuple]] = {}
    for row in rows:
        grouped.setdefault(str(row[0]), []).append(row)
    output: list[DecisionEvidence] = []
    reasons: list[str] = []
    for decision_id, values in grouped.items():
        from ladder_dragon.strategy.prediction.experiments import ShadowVariant
        plan = store._plan(str(values[0][8]))
        baseline_plan = store._plan(str(values[0][9]))
        if plan is None or baseline_plan is None:
            reasons.append("confirmation plan evidence is incomplete")
        else:
            # The entry gap is frozen strategy semantics, not a value that can
            # be reconstructed from a later snapshot price and stored plan.
            frozen_gap = manifest["candidate_parameters"]["entry_gap_bps"]
            candidate_parameters = manifest["candidate_parameters"]
            legacy_rule = (
                "exit_order_policy" in candidate_parameters
                and "stop_order_policy" not in candidate_parameters
            )
            reconstructed = ShadowVariant(
                variant_id=str(manifest["selected_variant"]),
                dimension=str(manifest["candidate_parameters"]["dimension"]),
                kind=f"EXPERIMENT_{str(manifest['selected_variant']).upper()}",
                plan=plan,
                baseline_plan=baseline_plan,
                maker_only=(
                    manifest["candidate_parameters"]["entry_order_policy"]
                    == "LIMIT_MAKER"
                ),
                entry_gap_bps=(
                    D(str(frozen_gap)) if frozen_gap is not None else None
                ),
                regime_policy=str(manifest["candidate_parameters"]["regime_policy"]),
                model_rule=str(manifest["candidate_parameters"]["model_rule"]),
                candidate_rule_version=(
                    1 if legacy_rule else int(
                        candidate_parameters.get("candidate_rule_version", 0)
                    )
                ),
                execution_model_rule=str(
                    candidate_parameters.get("execution_model_rule") or ""
                ),
                execution_model_promotion_ready=(
                    candidate_parameters.get(
                        "execution_model_promotion_ready"
                    ) is True
                ),
            )
            actual_candidate, actual_baseline = variant_fingerprints(
                reconstructed,
                generation=str(manifest["generation"]),
                horizons_min=required,
                criteria=manifest["criteria"],
            )
            if (
                actual_candidate != manifest["candidate_fingerprint"]
                or actual_baseline != manifest["baseline_fingerprint"]
            ):
                reasons.append("confirmation rule differs from frozen manifest")
        if any(
            str(row[6] or "") != str(manifest["candidate_fingerprint"])
            or str(row[7] or "") != str(manifest["baseline_fingerprint"])
            for row in values
        ):
            reasons.append("confirmation fingerprint differs from frozen manifest")
        horizons = tuple(int(row[3]) for row in values)
        complete = horizons == required and all(row[4] is not None and row[5] is not None for row in values)
        features = json.loads(str(values[0][2]))
        samples: list[ResolvedSample] = []
        if complete:
            for row in values:
                outcome = store._outcome(str(row[4]))
                baseline = store._outcome(str(row[5]))
                samples.append(ResolvedSample(
                    snapshot_ts_ms=int(row[1]),
                    regime=str(features.get("regime", "UNKNOWN")),
                    horizon_min=int(row[3]),
                    outcome=outcome,
                    baseline_net_pnl_quote=baseline.net_pnl_quote,
                ))
        output.append(DecisionEvidence(
            decision_id=decision_id,
            snapshot_ts_ms=int(values[0][1]),
            regime=str(features.get("regime", "UNKNOWN")),
            samples=tuple(samples),
            complete=complete,
        ))
    snapshots = [row.snapshot_ts_ms for row in output]
    if len(snapshots) != len(set(snapshots)):
        reasons.append("confirmation contains duplicate decision snapshots")
    return output, reasons


def confirmation_report(
    store: "PredictionShadowStore", *, experiment_id: str
) -> dict[str, object]:
    """Read post-freeze evidence without changing experiment state."""
    try:
        manifest = load_manifest(store, experiment_id)
    except (ValueError, sqlite3.Error, json.JSONDecodeError) as exc:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "experiment_id": experiment_id,
            "confirmation_status": "BLOCKED",
            "blocking_reasons": [str(exc)],
            "first_gate_passed": False,
            "eligible_for_second_gate_review": False,
            "promotion_eligible": False,
            "apply_allowed": False,
            "can_change_orders": False,
            "lookahead": False,
        }
    if manifest.get("statistical_method") in {
        "group_sequential_sign_test_alpha_spending_v1",
        "group_sequential_combined_gate_alpha_spending_v2",
    }:
        return _episode_confirmation_report(store, manifest)
    decisions, reasons = _confirmation_decisions(store, manifest)
    criteria = manifest["criteria"]
    required_horizons = tuple(
        int(value)
        for value in manifest["candidate_parameters"]["horizons_min"]
    )
    try:
        feasibility = validate_confirmation_criteria(
            criteria, required_horizons_min=required_horizons
        )
    except (KeyError, TypeError, ValueError) as exc:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "experiment_id": experiment_id,
            "experiment_lifecycle_status": manifest["current_status"],
            "confirmation_status": "BLOCKED",
            "blocking_reasons": [str(exc)],
            "first_gate_passed": False,
            "eligible_for_second_gate_review": False,
            "promotion_eligible": False,
            "apply_allowed": False,
            "can_change_orders": False,
            "lookahead": False,
        }
    all_independent_decisions = non_overlapping_decisions(
        decisions, required_horizons_min=required_horizons
    )
    panic_decisions = [
        row for row in all_independent_decisions if row.regime == "PANIC"
    ]
    independent_decisions = [
        row for row in all_independent_decisions
        if row.regime in EXPECTANCY_REGIMES
    ]
    size = int(criteria["window_size_decisions"])
    required_windows = int(criteria["required_complete_windows"])
    required_decisions = size * required_windows
    first_pending = next(
        (
            index
            for index, row in enumerate(independent_decisions)
            if not row.complete
        ),
        len(independent_decisions),
    )
    # A later closed outcome cannot jump over an earlier unresolved decision.
    complete_prefix = independent_decisions[:first_pending]
    pending_tail = independent_decisions[first_pending:]
    windows = [
        summarize_window(
            complete_prefix[offset:offset + size], offset // size + 1
        )
        for offset in range(
            0, len(complete_prefix) - len(complete_prefix) % size, size
        )
    ]
    remainder = complete_prefix[len(windows) * size:] + pending_tail
    if remainder:
        windows.append({
            "index": len(windows) + 1,
            "status": "PENDING",
            "start_ts_ms": min(row.snapshot_ts_ms for row in remainder),
            "end_ts_ms": max(row.snapshot_ts_ms for row in remainder),
            "independent_decisions": len(remainder),
            "evidence_complete": False,
            "blocking_reasons": ["window is incomplete"],
        })
    full = [row for row in windows if row["status"] == "COMPLETE"]
    evaluated_windows = full[:required_windows]
    evaluated_blocks = [
        complete_prefix[offset:offset + size]
        for offset in range(0, required_decisions, size)
        if len(complete_prefix[offset:offset + size]) == size
    ]
    positive = sum(bool(row["positive"]) for row in evaluated_windows)
    negative = len(evaluated_windows) - positive
    longest_negative = 0
    current_negative = 0
    for row in evaluated_windows:
        current_negative = 0 if row["positive"] else current_negative + 1
        longest_negative = max(longest_negative, current_negative)
    gate = block_confirmation_gate(
        evaluated_blocks,
        criteria=criteria,
        required_horizons_min=required_horizons,
    )
    required_regime_blocks = int(gate["minimum_sign_blocks"])
    regime_block_counts = {
        regime: int(gate["hypotheses"][f"regime_{regime}"]["blocks"])
        for regime in EXPECTANCY_REGIMES
    }
    observed_blocks = len(evaluated_blocks)
    remaining_blocks = max(0, required_windows - observed_blocks)
    irrecoverable_regimes = sorted(
        regime for regime, count in regime_block_counts.items()
        if count + remaining_blocks < required_regime_blocks
    )
    confirmation_futile = bool(irrecoverable_regimes)
    projected_regime_blocks: dict[str, int | None] = {}
    for regime, count in regime_block_counts.items():
        projected_regime_blocks[regime] = (
            (required_regime_blocks * observed_blocks + count - 1) // count
            if count > 0 else None
        )
    confirmation_eta_blocks = None if confirmation_futile else required_windows
    last_confirmation_ts = (
        complete_prefix[-1].snapshot_ts_ms if complete_prefix else None
    )
    confirmation_eta_ms = (
        last_confirmation_ts
        + max(0, confirmation_eta_blocks - observed_blocks)
        * size * feasibility["independence_spacing_ms"]
        if last_confirmation_ts is not None and confirmation_eta_blocks is not None
        else None
    )
    enough = (
        len(evaluated_windows) == required_windows
        and len(complete_prefix) >= required_decisions
        and required_decisions >= int(criteria["min_independent_samples"])
    )
    if not enough:
        reasons.append("predeclared confirmation volume is incomplete")
        if pending_tail and len(complete_prefix) < required_decisions:
            reasons.append("confirmation sequence contains an unresolved decision")
    if positive < int(criteria["minimum_positive_windows"]):
        reasons.append("positive-window requirement is not met")
    if longest_negative > int(criteria["maximum_consecutive_negative_windows"]):
        reasons.append("negative-window sequence exceeds the limit")
    if confirmation_futile:
        reasons.append(
            "predeclared confirmation regime coverage is irrecoverable: "
            + ",".join(irrecoverable_regimes)
        )
    reasons.extend(str(item) for item in gate.get("reasons", []))
    reasons = list(dict.fromkeys(reasons))
    pnl_values = [
        D(str(row["candidate_net_pnl_quote"])) for row in evaluated_windows
    ]
    edge_values = [D(str(row["edge_quote"])) for row in evaluated_windows]
    evaluated_count = len(evaluated_windows)
    regime_edges: dict[str, Decimal] = {}
    for row in evaluated_windows:
        for regime, values in row["regimes"].items():
            regime_edges[regime] = (
                regime_edges.get(regime, ZERO) + D(str(values["edge_quote"]))
            )
    confirmation_deadline_ms = int(manifest["confirmation_start_ts_ms"]) + int(
        criteria.get(
            "maximum_confirmation_duration_ms",
            DEFAULT_STATISTICAL_DESIGN.maximum_confirmation_duration_ms,
        )
    )
    deadline_expired = int(time.time() * 1000) > confirmation_deadline_ms
    if deadline_expired and not enough:
        reasons.append("predeclared confirmation deadline expired")
        reasons = list(dict.fromkeys(reasons))
    evaluation_passed = enough and not reasons
    finalization_ready = enough or deadline_expired or confirmation_futile
    lifecycle_status = str(manifest["current_status"])
    if lifecycle_status == "CONFIRMED" and evaluation_passed:
        status = "PASSED"
    elif lifecycle_status == "CONFIRMED":
        status = "BLOCKED_BY_CURRENT_METHOD"
    elif lifecycle_status == "REJECTED":
        status = "FAILED"
    elif lifecycle_status == "BLOCKED":
        status = "BLOCKED"
    elif finalization_ready:
        status = "READY_TO_FINALIZE"
    else:
        status = "IN_PROGRESS"
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "experiment_lifecycle_status": lifecycle_status,
        "experiment_id": manifest["experiment_id"],
        "generation": manifest["generation"],
        "selected_variant": manifest["selected_variant"],
        "candidate_fingerprint": manifest["candidate_fingerprint"],
        "baseline_fingerprint": manifest["baseline_fingerprint"],
        "selection_cutoff_ts_ms": manifest["selection_end_ts_ms"],
        "confirmation_start_ts_ms": manifest["confirmation_start_ts_ms"],
        "confirmation_status": status,
        "confirmation_progress": {
            "raw_decisions": len(decisions),
            "excluded_overlapping_decisions": (
                len(decisions) - len(all_independent_decisions)
            ),
            "panic_safety_decisions": len(panic_decisions),
            "panic_blocks_expectancy": False,
            "complete_decisions": len(complete_prefix),
            "pending_decisions": len(pending_tail),
            "required_decisions": required_decisions,
            "complete_windows": len(full),
            "required_complete_windows": required_windows,
            "evaluated_windows": len(evaluated_windows),
            "regime_distinct_blocks": regime_block_counts,
            "required_regime_distinct_blocks": required_regime_blocks,
            "projected_regime_total_blocks": projected_regime_blocks,
            "irrecoverable_regimes": irrecoverable_regimes,
            "confirmation_futile": confirmation_futile,
            "confirmation_estimated_ready_ts_ms": confirmation_eta_ms,
            "confirmation_deadline_ts_ms": confirmation_deadline_ms,
            "confirmation_deadline_expired": deadline_expired,
            "readiness_reason": (
                "predeclared confirmation regime coverage is irrecoverable"
                if confirmation_futile else
                "predeclared confirmation deadline expired"
                if deadline_expired and not enough else
                "live independent confirmation is incomplete"
                if not enough else
                "confirmation criteria are not met"
                if not evaluation_passed else
                "confirmation gate passed"
            ),
        },
        "statistical_method": STATISTICAL_METHOD_VERSION,
        "independence_spacing_ms": feasibility["independence_spacing_ms"],
        "complete_windows": len(full),
        "pending_windows": sum(row["status"] == "PENDING" for row in windows),
        "positive_windows": positive,
        "negative_windows": negative,
        "positive_window_fraction": (
            format(D(str(positive)) / D(str(evaluated_count)), "f")
            if evaluated_count else "0"
        ),
        "cumulative_pnl_quote": format(sum(pnl_values, ZERO), "f"),
        "mean_pnl_per_window_quote": (
            format(sum(pnl_values, ZERO) / D(str(evaluated_count)), "f")
            if evaluated_count else "0"
        ),
        "mean_edge_per_window_quote": (
            format(sum(edge_values, ZERO) / D(str(evaluated_count)), "f")
            if evaluated_count else "0"
        ),
        "worst_window_pnl_quote": format(min(pnl_values), "f") if full else None,
        "maximum_consecutive_negative_windows": longest_negative,
        "overall_drawdown_quote": format(drawdown(pnl_values), "f"),
        "regimes_without_positive_edge": sorted(
            regime for regime, edge in regime_edges.items() if edge <= 0
        ),
        "window_block_net_expectancy_ci": gate["net_expectancy_ci"],
        "window_block_baseline_edge_ci": gate["baseline_edge_ci"],
        "windows": windows,
        "statistical_gate": gate,
        "blocking_reasons": reasons,
        "evaluation_passed": evaluation_passed,
        "finalization_ready": finalization_ready,
        "proposed_final_status": (
            "CONFIRMED" if evaluation_passed else "REJECTED"
        ) if finalization_ready else None,
        "first_gate_passed": (
            lifecycle_status == "CONFIRMED" and evaluation_passed
        ),
        "eligible_for_second_gate_review": (
            lifecycle_status == "CONFIRMED" and evaluation_passed
        ),
        "execution_model_gate": {
            "status": (
                "PASS"
                if manifest["candidate_parameters"].get(
                    "execution_model_promotion_ready"
                ) is True else "NOT_IMPLEMENTED"
            ),
            "model_rule": manifest["candidate_parameters"].get(
                "execution_model_rule"
            ),
            "reason": (
                None
                if manifest["candidate_parameters"].get(
                    "execution_model_promotion_ready"
                ) is True
                else "maker fills and STOP_LOSS_LIMIT gaps are not represented"
            ),
        },
        "promotion_eligible": (
            lifecycle_status == "CONFIRMED"
            and evaluation_passed
            and manifest["candidate_parameters"].get(
                "execution_model_promotion_ready"
            ) is True
        ),
        "apply_allowed": False,
        "can_change_orders": False,
        "lookahead": False,
    }
    report["report_sha256"] = sha256_json(report)
    return report


def finalize_experiment(
    store: "PredictionShadowStore",
    *,
    experiment_id: str,
    expected_report_sha256: str,
) -> dict[str, object]:
    """Finalize the exact reviewed report with an append-only transition."""
    report = confirmation_report(store, experiment_id=experiment_id)
    expected = str(expected_report_sha256).strip().lower()
    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        raise ValueError("reviewed confirmation report fingerprint is invalid")
    if report.get("report_sha256") != expected:
        raise ValueError("confirmation report changed before finalization")
    if not report.get("finalization_ready"):
        raise ValueError("confirmation is not ready for finalization")
    with store._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        # Hold the writer reservation while the exact reviewed report is checked.
        locked_report = confirmation_report(store, experiment_id=experiment_id)
        if locked_report.get("report_sha256") != expected:
            raise ValueError("confirmation report changed before finalization")
        target = str(locked_report["proposed_final_status"])
        current = _current_status(connection, experiment_id)
        if current not in {"FROZEN", "CONFIRMING"}:
            raise ValueError("experiment is already finalized")
        if current == "FROZEN":
            transition_experiment(
                connection,
                experiment_id=experiment_id,
                to_status="CONFIRMING",
                reason="operator requested confirmation finalization",
            )
        transition_experiment(
            connection,
            experiment_id=experiment_id,
            to_status=target,
            reason=(
                "reviewed first confirmation gate passed"
                if target == "CONFIRMED"
                else "reviewed first confirmation gate failed"
            ),
        )
        connection.commit()
    return confirmation_report(store, experiment_id=experiment_id)


def supersede_experiment(
    store: "PredictionShadowStore", *, experiment_id: str, reason: str
) -> str:
    with store._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        status = transition_experiment(
            connection,
            experiment_id=experiment_id,
            to_status="SUPERSEDED",
            reason=reason,
        )
        connection.commit()
    return status


__all__ = [
    "DEFAULT_CRITERIA",
    "EVIDENCE_ROLES",
    "MANIFEST_SCHEMA_VERSION",
    "REPORT_SCHEMA_VERSION",
    "baseline_rule",
    "candidate_rule",
    "canonical_json",
    "confirmation_report",
    "evidence_assignment",
    "finalize_experiment",
    "freeze_experiment",
    "freeze_preselected_episode_experiment",
    "list_experiments",
    "load_manifest",
    "migrate_experiment_lifecycle",
    "selection_experiment_id",
    "sha256_json",
    "supersede_experiment",
    "transition_experiment",
    "variant_fingerprints",
]
