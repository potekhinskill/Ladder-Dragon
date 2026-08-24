# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: bind independently confirmed candidates to immutable execution policies.
"""Append-only CHAMPION activation registry for confirmed SHADOW experiments."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import sqlite3
import time
from typing import Mapping, TYPE_CHECKING

from ladder_dragon.strategy.prediction.experiment_lifecycle import (
    canonical_json,
    confirmation_report,
    load_manifest,
    sha256_json,
)
from ladder_dragon.strategy.prediction.episode_semantics import (
    evidence_semantics_fingerprint,
)

if TYPE_CHECKING:
    from ladder_dragon.strategy.prediction.runtime import PredictionShadowStore


D = Decimal
CHAMPION_POLICY_SCHEMA_VERSION = 6
EXECUTION_REGIMES = ("RANGE", "TREND_UP", "TREND_DOWN")
PROTECTIVE_RUNTIME_ACTIONS = (
    "REDUCE_ORDER_NOTIONAL",
    "BLOCK_BUY",
    "CANCEL_OPEN_BUY",
    "TIGHTEN_PROTECTIVE_STOP",
    "EMERGENCY_FLATTEN",
)


def migrate_champion_registry(connection: sqlite3.Connection) -> None:
    """Create authoritative append-only CHAMPION activation records."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS prediction_champion_activations (
            activation_id TEXT PRIMARY KEY,
            schema_version INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            champion_version INTEGER NOT NULL,
            experiment_id TEXT NOT NULL UNIQUE,
            previous_activation_id TEXT,
            candidate_fingerprint TEXT NOT NULL,
            manifest_sha256 TEXT NOT NULL,
            confirmation_report_sha256 TEXT NOT NULL,
            execution_policy_json TEXT NOT NULL,
            execution_policy_fingerprint TEXT NOT NULL,
            champion_fingerprint TEXT NOT NULL UNIQUE,
            activated_at_ms INTEGER NOT NULL,
            product_version TEXT NOT NULL,
            source_commit TEXT NOT NULL,
            UNIQUE(symbol, champion_version),
            FOREIGN KEY(experiment_id)
                REFERENCES prediction_experiment_manifests(experiment_id),
            FOREIGN KEY(previous_activation_id)
                REFERENCES prediction_champion_activations(activation_id)
        );
        CREATE INDEX IF NOT EXISTS prediction_champion_symbol_order
            ON prediction_champion_activations(symbol, champion_version);
        CREATE UNIQUE INDEX IF NOT EXISTS prediction_champion_single_root
            ON prediction_champion_activations(symbol)
            WHERE previous_activation_id IS NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS prediction_champion_single_replacement
            ON prediction_champion_activations(previous_activation_id)
            WHERE previous_activation_id IS NOT NULL;
        CREATE TRIGGER IF NOT EXISTS prediction_champion_activation_no_update
        BEFORE UPDATE ON prediction_champion_activations
        BEGIN SELECT RAISE(ABORT, 'champion activation is immutable'); END;
        CREATE TRIGGER IF NOT EXISTS prediction_champion_activation_no_delete
        BEFORE DELETE ON prediction_champion_activations
        BEGIN SELECT RAISE(ABORT, 'champion activations are append-only'); END;
        """
    )


def _positive_decimal(value: object, *, field: str) -> Decimal:
    try:
        parsed = D(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} is invalid") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"{field} must be positive")
    return parsed


def _nonnegative_decimal(value: object, *, field: str) -> Decimal:
    try:
        parsed = D(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} is invalid") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{field} must be non-negative")
    return parsed


def _sha256(value: object, *, field: str) -> str:
    normalized = str(value).strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{field} is invalid")
    return normalized


def _evidence_fee_schedule(parameters: Mapping[str, object]) -> dict[str, str]:
    """Validate the authoritative fee schedule bound to experiment evidence."""
    schedule = parameters.get("fee_schedule")
    if not isinstance(schedule, Mapping):
        raise ValueError("CHAMPION evidence fee schedule is unavailable")
    if schedule.get("provenance") != "BINANCE_ACCOUNT_COMMISSION_MAX_V1":
        raise ValueError("CHAMPION evidence fees are not authoritative")
    result = {"provenance": "BINANCE_ACCOUNT_COMMISSION_MAX_V1"}
    for field in (
        "maker_buy_fee_pct",
        "maker_sell_fee_pct",
        "taker_buy_fee_pct",
        "taker_sell_fee_pct",
    ):
        result[field] = format(
            _nonnegative_decimal(schedule.get(field), field=field), "f"
        )
    return result


def execution_policy_from_manifest(
    manifest: Mapping[str, object],
    *,
    confirmation: Mapping[str, object],
    maximum_order_notional_usdt: object,
    maximum_inventory_usdt: object,
) -> dict[str, object]:
    """Build the exact executable policy from one immutable manifest."""
    parameters = manifest.get("candidate_parameters")
    if not isinstance(parameters, Mapping):
        raise ValueError("candidate parameters are unavailable")
    if parameters.get("candidate_rule_version") != 6:
        raise ValueError("CHAMPION candidate rule is not execution-bound")
    semantics_fingerprint = _sha256(
        parameters.get("evidence_semantics_fingerprint"),
        field="evidence semantics fingerprint",
    )
    if parameters.get("entry_order_policy") != "LIMIT_MAKER":
        raise ValueError("CHAMPION entry policy must be LIMIT_MAKER")
    if parameters.get("take_profit_order_policy") != "LIMIT_MAKER":
        raise ValueError("CHAMPION take-profit policy must be LIMIT_MAKER")
    if parameters.get("stop_order_policy") != "STOP_LOSS_LIMIT":
        raise ValueError("CHAMPION stop policy must be STOP_LOSS_LIMIT")
    if parameters.get("execution_model_promotion_ready") is not True:
        raise ValueError("CHAMPION execution model is not promotion-ready")
    execution_model_rule = str(
        parameters.get("execution_model_rule") or ""
    ).strip()
    if not execution_model_rule:
        raise ValueError("CHAMPION execution model identity is unavailable")
    evidence_fee_schedule = _evidence_fee_schedule(parameters)
    if parameters.get("entry_enabled") is not True:
        raise ValueError("CHAMPION entry must be enabled")
    entry_gap = _positive_decimal(
        parameters.get("entry_gap_bps"), field="entry gap"
    )
    target_return = _positive_decimal(
        parameters.get("target_return"), field="target return"
    )
    stop_limit_distance = _positive_decimal(
        parameters.get("stop_limit_distance"), field="stop-limit distance"
    )
    stop_trigger_offset = _positive_decimal(
        parameters.get("stop_trigger_offset_pct"),
        field="stop trigger offset",
    )
    if stop_trigger_offset >= stop_limit_distance:
        raise ValueError("stop trigger offset must remain below entry")
    maximum_holding = parameters.get("maximum_holding_min")
    primary_horizon = parameters.get("primary_horizon_min")
    if (
        isinstance(maximum_holding, bool)
        or not isinstance(maximum_holding, int)
        or maximum_holding <= 0
        or maximum_holding != primary_horizon
    ):
        raise ValueError("maximum holding time must equal the primary horizon")
    ttl = parameters.get("entry_ttl_sec")
    if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl <= 0:
        raise ValueError("entry TTL must be a positive integer")
    order_cap = _positive_decimal(
        maximum_order_notional_usdt, field="maximum order notional"
    )
    inventory_cap = _positive_decimal(
        maximum_inventory_usdt, field="maximum inventory"
    )
    if order_cap > inventory_cap:
        raise ValueError("maximum order notional exceeds maximum inventory")
    evidence_notional = _positive_decimal(
        parameters.get("evidence_notional_quote"),
        field="CHAMPION evidence notional",
    )
    if order_cap != evidence_notional or inventory_cap != evidence_notional:
        raise ValueError(
            "first CHAMPION caps must equal the evidence notional"
        )
    progress = confirmation.get("confirmation_progress")
    if not isinstance(progress, Mapping) or progress.get("status") != "PASS":
        raise ValueError("CHAMPION confirmation progress has not passed")
    raw_regimes = progress.get("confirmed_execution_regimes")
    if not isinstance(raw_regimes, list) or not raw_regimes:
        raise ValueError("CHAMPION confirmed execution regimes are unavailable")
    allowed_regimes = tuple(
        regime for regime in EXECUTION_REGIMES if regime in raw_regimes
    )
    if len(allowed_regimes) != len(raw_regimes):
        raise ValueError("CHAMPION confirmed execution regimes are invalid")
    criteria = manifest.get("criteria")
    if (
        not isinstance(criteria, Mapping)
        or criteria.get("regime_activation_policy")
        != "exact_preregistered_execution_regimes_v4"
    ):
        raise ValueError("CHAMPION regime activation policy is unavailable")
    frozen_regimes = criteria.get("eligible_regimes")
    if not isinstance(frozen_regimes, list) or raw_regimes != frozen_regimes:
        raise ValueError("CHAMPION regimes differ from the frozen policy")
    return {
        "schema_version": CHAMPION_POLICY_SCHEMA_VERSION,
        "symbol": str(manifest.get("symbol") or "").strip().upper(),
        "experiment_id": str(manifest.get("experiment_id") or ""),
        "generation": str(manifest.get("generation") or ""),
        "variant_id": str(manifest.get("selected_variant") or ""),
        "candidate_fingerprint": _sha256(
            manifest.get("candidate_fingerprint"),
            field="candidate fingerprint",
        ),
        "entry_gap_bps": format(entry_gap, "f"),
        "entry_ttl_sec": ttl,
        "target_return": format(target_return, "f"),
        "stop_limit_distance": format(stop_limit_distance, "f"),
        "stop_trigger_offset_pct": format(stop_trigger_offset, "f"),
        "maximum_holding_min": maximum_holding,
        "primary_horizon_min": primary_horizon,
        "entry_order_policy": "LIMIT_MAKER",
        "take_profit_order_policy": "LIMIT_MAKER",
        "stop_order_policy": "STOP_LOSS_LIMIT",
        "execution_model_rule": execution_model_rule,
        "evidence_semantics_fingerprint": semantics_fingerprint,
        "evidence_fee_schedule": evidence_fee_schedule,
        "maximum_order_notional_usdt": format(order_cap, "f"),
        "maximum_inventory_usdt": format(inventory_cap, "f"),
        "maximum_active_buy_orders": 1,
        "maximum_concurrent_positions": 1,
        "allowed_entry_regimes": list(allowed_regimes),
        "regime_activation_policy": "exact_preregistered_execution_regimes_v4",
        "runtime_mutation_policy": "protective_only",
        "allowed_runtime_actions": list(PROTECTIVE_RUNTIME_ACTIONS),
        "forbidden_runtime_actions": [
            "INCREASE_ORDER_NOTIONAL",
            "CHANGE_ENTRY_GAP",
            "CHANGE_ENTRY_TTL",
            "CHANGE_TAKE_PROFIT",
            "CHANGE_STOP_TRIGGER_OFFSET",
            "CHANGE_MAXIMUM_HOLDING_TIME",
        ],
        "probation": {
            "schema_version": 2,
            "duration_hours": 24,
            "maximum_entries": 3,
            "minimum_terminal_entries": 1,
            "minimum_closed_lifecycles": 1,
            "maximum_turnover_usdt": format(order_cap * Decimal("3"), "f"),
            "maximum_equity_loss_usdt": format(order_cap / Decimal("2"), "f"),
            "failure_action": "PERSISTENT_HALT",
            "entry_limit_action": "BLOCK_BUY_UNTIL_PROBATION_END",
        },
    }


def champion_allows_regime(
    policy: Mapping[str, object], regime: object
) -> bool:
    """Fail closed unless the immutable policy confirms this entry regime."""
    if policy.get("schema_version") != CHAMPION_POLICY_SCHEMA_VERSION:
        return False
    if (
        policy.get("evidence_semantics_fingerprint")
        != evidence_semantics_fingerprint()
    ):
        return False
    allowed = policy.get("allowed_entry_regimes")
    if not isinstance(allowed, list) or not allowed:
        return False
    if any(item not in EXECUTION_REGIMES for item in allowed):
        return False
    return str(regime) in allowed


def _row_payload(row: sqlite3.Row | tuple[object, ...]) -> dict[str, object]:
    import json

    values = tuple(row)
    policy = json.loads(str(values[9]))
    if not isinstance(policy, dict):
        raise ValueError("CHAMPION execution policy is invalid")
    if sha256_json(policy) != str(values[10]):
        raise ValueError("CHAMPION execution policy fingerprint differs")
    identity = {
        "schema_version": int(values[1]),
        "symbol": str(values[2]),
        "champion_version": int(values[3]),
        "experiment_id": str(values[4]),
        "previous_activation_id": (
            str(values[5]) if values[5] is not None else None
        ),
        "candidate_fingerprint": str(values[6]),
        "manifest_sha256": str(values[7]),
        "confirmation_report_sha256": str(values[8]),
        "execution_policy_fingerprint": str(values[10]),
        "activated_at_ms": int(values[12]),
        "product_version": str(values[13]),
        "source_commit": str(values[14]),
    }
    if sha256_json(identity) != str(values[11]):
        raise ValueError("CHAMPION activation fingerprint differs")
    return {
        "activation_id": str(values[0]),
        **identity,
        "execution_policy": policy,
        "champion_fingerprint": str(values[11]),
        "status": "ACTIVE",
        "apply_allowed": True,
    }


def active_champion(
    store: "PredictionShadowStore", *, symbol: str
) -> dict[str, object] | None:
    """Return the single current CHAMPION or fail on ambiguous history."""
    normalized = str(symbol).strip().upper()
    with store._connect() as connection:
        rows = connection.execute(
            """SELECT activation_id,schema_version,symbol,champion_version,
                      experiment_id,previous_activation_id,candidate_fingerprint,
                      manifest_sha256,confirmation_report_sha256,
                      execution_policy_json,
                      execution_policy_fingerprint,champion_fingerprint,
                      activated_at_ms,product_version,source_commit
               FROM prediction_champion_activations AS active
               WHERE symbol=? AND NOT EXISTS (
                   SELECT 1 FROM prediction_champion_activations AS replacement
                   WHERE replacement.previous_activation_id=active.activation_id
               )
               ORDER BY champion_version""",
            (normalized,),
        ).fetchall()
    if len(rows) > 1:
        raise ValueError("multiple active CHAMPION policies")
    return _row_payload(rows[0]) if rows else None


def list_champions(
    store: "PredictionShadowStore", *, symbol: str | None = None
) -> list[dict[str, object]]:
    """List immutable activations and mark only the latest chain leaf active."""
    query = (
        "SELECT activation_id,schema_version,symbol,champion_version,"
        "experiment_id,previous_activation_id,candidate_fingerprint,"
        "manifest_sha256,confirmation_report_sha256,execution_policy_json,"
        "execution_policy_fingerprint,"
        "champion_fingerprint,activated_at_ms,product_version,source_commit "
        "FROM prediction_champion_activations"
    )
    params: tuple[object, ...] = ()
    if symbol is not None:
        query += " WHERE symbol=?"
        params = (str(symbol).strip().upper(),)
    query += " ORDER BY symbol,champion_version"
    with store._connect() as connection:
        rows = connection.execute(query, params).fetchall()
        replaced = {
            str(row[0])
            for row in connection.execute(
                """SELECT previous_activation_id
                   FROM prediction_champion_activations
                   WHERE previous_activation_id IS NOT NULL"""
            )
        }
    payload = [_row_payload(row) for row in rows]
    for item in payload:
        if item["activation_id"] in replaced:
            item["status"] = "SUPERSEDED"
            item["apply_allowed"] = False
    return payload


def activate_champion(
    store: "PredictionShadowStore",
    *,
    experiment_id: str,
    expected_report_sha256: str,
    expected_manifest_sha256: str,
    expected_execution_policy_fingerprint: str,
    expected_previous_activation_id: str | None,
    maximum_order_notional_usdt: object,
    maximum_inventory_usdt: object,
    product_version: str,
    source_commit: str,
    execution_halt_confirmed: bool,
    activated_at_ms: int | None = None,
) -> dict[str, object]:
    """Activate the exact reviewed CONFIRMED policy in one append-only step."""
    if execution_halt_confirmed is not True:
        raise ValueError("CHAMPION activation requires a confirmed execution halt")
    report_sha = _sha256(
        expected_report_sha256, field="confirmation report fingerprint"
    )
    manifest_sha = _sha256(
        expected_manifest_sha256, field="manifest fingerprint"
    )
    expected_policy_sha = _sha256(
        expected_execution_policy_fingerprint,
        field="execution policy fingerprint",
    )
    report = confirmation_report(store, experiment_id=experiment_id)
    if report.get("report_sha256") != report_sha:
        raise ValueError("confirmation report changed before activation")
    if not report.get("promotion_eligible"):
        raise ValueError("experiment is not eligible for CHAMPION activation")
    manifest = load_manifest(store, experiment_id)
    if manifest.get("manifest_sha256") != manifest_sha:
        raise ValueError("experiment manifest changed before activation")
    if manifest.get("current_status") != "CONFIRMED":
        raise ValueError("only a CONFIRMED experiment can become CHAMPION")
    policy = execution_policy_from_manifest(
        manifest,
        confirmation=report,
        maximum_order_notional_usdt=maximum_order_notional_usdt,
        maximum_inventory_usdt=maximum_inventory_usdt,
    )
    policy_fingerprint = sha256_json(policy)
    if policy_fingerprint != expected_policy_sha:
        raise ValueError("execution policy changed after preview")
    symbol = str(policy["symbol"])
    now_ms = int(time.time() * 1000) if activated_at_ms is None else int(activated_at_ms)
    source = str(source_commit).strip().lower()
    if len(source) != 40 or any(ch not in "0123456789abcdef" for ch in source):
        raise ValueError("source commit is invalid")

    with store._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            """SELECT activation_id,champion_version
               FROM prediction_champion_activations AS active
               WHERE symbol=? AND NOT EXISTS (
                   SELECT 1 FROM prediction_champion_activations AS replacement
                   WHERE replacement.previous_activation_id=active.activation_id
               )""",
            (symbol,),
        ).fetchall()
        if len(rows) > 1:
            raise ValueError("multiple active CHAMPION policies")
        current_id = str(rows[0][0]) if rows else None
        expected_previous = expected_previous_activation_id or None
        if current_id != expected_previous:
            raise ValueError("active CHAMPION changed before activation")
        version = int(rows[0][1]) + 1 if rows else 1
        identity = {
            "schema_version": CHAMPION_POLICY_SCHEMA_VERSION,
            "symbol": symbol,
            "champion_version": version,
            "experiment_id": str(experiment_id),
            "previous_activation_id": current_id,
            "candidate_fingerprint": str(policy["candidate_fingerprint"]),
            "manifest_sha256": manifest_sha,
            "confirmation_report_sha256": report_sha,
            "execution_policy_fingerprint": policy_fingerprint,
            "activated_at_ms": now_ms,
            "product_version": str(product_version),
            "source_commit": source,
        }
        champion_fingerprint = sha256_json(identity)
        activation_id = (
            f"champion:{symbol.lower()}:v{version}:"
            f"{champion_fingerprint[:16]}"
        )
        connection.execute(
            """INSERT INTO prediction_champion_activations
               (activation_id,schema_version,symbol,champion_version,
                experiment_id,previous_activation_id,candidate_fingerprint,
                manifest_sha256,confirmation_report_sha256,
                execution_policy_json,execution_policy_fingerprint,
                champion_fingerprint,activated_at_ms,product_version,
                source_commit)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                activation_id,
                CHAMPION_POLICY_SCHEMA_VERSION,
                symbol,
                version,
                str(experiment_id),
                current_id,
                str(policy["candidate_fingerprint"]),
                manifest_sha,
                report_sha,
                canonical_json(policy),
                policy_fingerprint,
                champion_fingerprint,
                now_ms,
                str(product_version),
                source,
            ),
        )
        connection.commit()
    activated = active_champion(store, symbol=symbol)
    if activated is None or activated["activation_id"] != activation_id:
        raise RuntimeError("new CHAMPION activation is not authoritative")
    return activated


def verify_active_champion(
    store: "PredictionShadowStore",
    *,
    symbol: str,
    activation_id: str,
    champion_fingerprint: str,
    execution_policy_fingerprint: str,
) -> dict[str, object]:
    """Verify the worker received the exact current activation."""
    champion = active_champion(store, symbol=symbol)
    if champion is None:
        raise ValueError("active CHAMPION is unavailable")
    expected = {
        "activation_id": activation_id,
        "champion_fingerprint": champion_fingerprint,
        "execution_policy_fingerprint": execution_policy_fingerprint,
    }
    for field, value in expected.items():
        if str(champion.get(field) or "") != str(value).strip().lower():
            raise ValueError(f"active CHAMPION {field} differs")
    return champion


__all__ = [
    "CHAMPION_POLICY_SCHEMA_VERSION",
    "PROTECTIVE_RUNTIME_ACTIONS",
    "activate_champion",
    "active_champion",
    "champion_allows_regime",
    "execution_policy_from_manifest",
    "list_champions",
    "migrate_champion_registry",
    "verify_active_champion",
]
