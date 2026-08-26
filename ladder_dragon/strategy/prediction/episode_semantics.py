# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: freeze the evidence semantics shared by collection and execution.
"""Canonical promotion evidence semantics for SOL execution episodes."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Mapping


EVIDENCE_SEMANTICS_VERSION = "minute_l2_episode_execution_v5"
EXECUTION_MODEL_RULE = "minute_l2_fifo_oco_gap_v3"
V23_EVIDENCE_SEMANTICS_VERSION = "diff_depth_entry_veto_execution_v6"
V23_EXECUTION_MODEL_RULE = "diff_depth_fifo_oco_cancel_v4"
V21_EVIDENCE_SEMANTICS_VERSION = "minute_l2_episode_execution_v4"
V21_EXECUTION_MODEL_RULE = "minute_l2_fifo_oco_gap_v3"
V20_EVIDENCE_SEMANTICS_VERSION = "minute_l2_episode_execution_v3"
V20_EXECUTION_MODEL_RULE = "minute_l2_fifo_oco_gap_v3"
V19_EVIDENCE_SEMANTICS_VERSION = "minute_l2_episode_execution_v2"
V19_EXECUTION_MODEL_RULE = "minute_l2_fifo_oco_gap_v2"
REGIME_CLASSIFIER_VERSION = "execution_30m_ema_adx_hysteresis_v1"
REGIME_EMA_FAST_LENGTH = 20
REGIME_EMA_SLOW_LENGTH = 50
REGIME_ADX_LENGTH = 14
EXECUTABLE_ENTRY_REGIMES = ("RANGE", "TREND_UP", "TREND_DOWN")
V21_EXECUTABLE_ENTRY_REGIMES = ("RANGE",)
EXCURSION_POLICY = "BEST_BID_MFE_MAE_AFTER_ENTRY_TO_TERMINAL_V1"


def execution_model_contract() -> dict[str, object]:
    """Return every execution-sensitive simulator parameter."""
    return {
        "latency_ms": 1_000,
        "emergency_market_impact_bps": "10",
        "maximum_event_gap_ms": 180_000,
        "stop_unfilled_grace_ms": 60_000,
        "queue_cancellation_ahead_ratio": "0",
        "maker_queue_policy": "PUBLIC_L2_PRICE_LEVEL_FIFO_PROXY",
        "entry_rounding": "PRICE_FLOOR_QUANTITY_FLOOR",
        "take_profit_rounding": "PRICE_CEILING",
        "stop_limit_rounding": "PRICE_FLOOR",
        "stop_trigger_rounding": "PRICE_CEILING",
        "fee_mapping": {
            "entry_maker": "maker_buy_fee_pct",
            "entry_taker": "taker_buy_fee_pct",
            "exit_maker": "maker_sell_fee_pct",
            "exit_taker": "taker_sell_fee_pct",
        },
        "stop_trigger_source": "AGGREGATE_TRADE_AT_OR_BELOW_TRIGGER",
        "stop_gap_policy": "MARKET_FLATTEN_AFTER_GRACE",
    }


def _evidence_semantics_contract(
    *, version: str, execution_model_rule: str, include_excursions: bool,
) -> dict[str, object]:
    """Build one immutable evidence contract without changing old digests."""
    contract = {
        "version": version,
        "execution_model_rule": execution_model_rule,
        "entry_order_policy": "LIMIT_MAKER",
        "take_profit_order_policy": "LIMIT_MAKER",
        "stop_order_policy": "STOP_LOSS_LIMIT",
        "panic_flatten_policy": "INCLUDE_NET_PNL_AND_DRAWDOWN",
        "panic_veto_policy": "TERMINAL_UNFILLED_ATTEMPT",
        "trade_page_policy": "BOUNDED_CONTIGUOUS_AGGTRADES_V1",
        "executable_entry_regimes": list(V21_EXECUTABLE_ENTRY_REGIMES),
        "execution_model": execution_model_contract(),
        "regime_classifier": {
            "version": REGIME_CLASSIFIER_VERSION,
            "source": "confirmed_execution_regime",
            "interval": "30m",
            "ema_fast_length": REGIME_EMA_FAST_LENGTH,
            "ema_slow_length": REGIME_EMA_SLOW_LENGTH,
            "adx_length": REGIME_ADX_LENGTH,
            "ema_epsilon": "0.0005",
            "minimum_slope": "0.0002",
            "minimum_adx": "16",
            "direction_confirmations": 3,
            "execution_confirmations": 3,
            "recovery_confirmations": 3,
            "minimum_hold_seconds": "300",
            "panic_source": "executor_panic_state",
            "hysteresis_source": "execution_state_machine",
        },
        "expectancy_policy": "ALL_TERMINAL_ATTEMPTS_NET_OF_FEES_V1",
    }
    if include_excursions:
        contract["excursion_policy"] = EXCURSION_POLICY
    return contract


def evidence_semantics_contract() -> dict[str, object]:
    """Return the immutable contract used by current evidence and execution."""
    return _evidence_semantics_contract(
        version=EVIDENCE_SEMANTICS_VERSION,
        execution_model_rule=EXECUTION_MODEL_RULE,
        include_excursions=True,
    )


def canonical_digest(payload: Mapping[str, object]) -> str:
    """Hash one JSON-compatible contract with stable key ordering."""
    encoded = json.dumps(
        dict(payload), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def evidence_semantics_fingerprint() -> str:
    """Return the reviewed fingerprint required on every current episode."""
    return canonical_digest(evidence_semantics_contract())


def v23_evidence_semantics_contract() -> dict[str, object]:
    """Return future veto semantics without changing current v22 evidence."""
    contract = _evidence_semantics_contract(
        version=V23_EVIDENCE_SEMANTICS_VERSION,
        execution_model_rule=V23_EXECUTION_MODEL_RULE,
        include_excursions=True,
    )
    contract["entry_veto_policy"] = {
        "contract_version": "l2_adverse_selection_cancel_v2",
        "market_source": "BINANCE_DIFF_DEPTH_100MS_SEQUENCE_VALIDATED",
        "trade_source": "BINANCE_AGGTRADE",
        "order_flow_imbalance": "CONT_BEST_LEVEL_NORMALIZED_V1",
        "fill_timestamp_resolution_ms": 60_000,
        "cancel_timing": "FILLABLE_UNTIL_CANCEL_EFFECTIVE",
        "late_cancel_policy": "KEEP_ORIGINAL_FILL_AND_PNL",
        "capacity_policy": "SEQUENTIAL_ONE_SLOT_REPLAY",
    }
    return contract


def v23_evidence_semantics_fingerprint() -> str:
    """Return the future v23 semantics fingerprint."""
    return canonical_digest(v23_evidence_semantics_contract())


def v21_evidence_semantics_fingerprint() -> str:
    """Preserve the exact historical v21 fingerprint."""
    return canonical_digest(_evidence_semantics_contract(
        version=V21_EVIDENCE_SEMANTICS_VERSION,
        execution_model_rule=V21_EXECUTION_MODEL_RULE,
        include_excursions=False,
    ))


def v20_evidence_semantics_fingerprint() -> str:
    """Preserve the exact historical v20 fingerprint."""
    contract = _evidence_semantics_contract(
        version=V21_EVIDENCE_SEMANTICS_VERSION,
        execution_model_rule=V21_EXECUTION_MODEL_RULE,
        include_excursions=False,
    )
    contract["version"] = V20_EVIDENCE_SEMANTICS_VERSION
    contract["execution_model_rule"] = V20_EXECUTION_MODEL_RULE
    contract["executable_entry_regimes"] = list(EXECUTABLE_ENTRY_REGIMES)
    return canonical_digest(contract)


def v19_evidence_semantics_fingerprint() -> str:
    """Preserve the exact historical v19 fingerprint."""
    contract = _evidence_semantics_contract(
        version=V21_EVIDENCE_SEMANTICS_VERSION,
        execution_model_rule=V21_EXECUTION_MODEL_RULE,
        include_excursions=False,
    )
    contract["version"] = V19_EVIDENCE_SEMANTICS_VERSION
    contract["execution_model_rule"] = V19_EXECUTION_MODEL_RULE
    contract.pop("executable_entry_regimes", None)
    contract.pop("execution_model", None)
    return canonical_digest(contract)


def execution_engine_validation_domain(
    *,
    execution_model_rule: str,
    fee_schedule: Mapping[str, object],
) -> dict[str, object]:
    """Describe reusable order-engine evidence without candidate geometry."""
    rates = {
        field: str(fee_schedule.get(field))
        for field in (
            "maker_buy_fee_pct",
            "maker_sell_fee_pct",
            "taker_buy_fee_pct",
            "taker_sell_fee_pct",
        )
    }
    return {
        "schema_version": 1,
        "scope": "REUSABLE_EXECUTION_ENGINE",
        "execution_model_rule": str(execution_model_rule),
        "entry_order_policy": "LIMIT_MAKER",
        "take_profit_order_policy": "LIMIT_MAKER",
        "stop_order_policy": "STOP_LOSS_LIMIT",
        "queue_model": "L2_PRICE_LEVEL_FIFO_PROXY",
        "fee_schedule": rates,
        "execution_model": execution_model_contract(),
        "candidate_parameters_excluded": True,
    }


def require_execution_regime_contract(observed: Mapping[str, object]) -> None:
    """Reject collection when the live classifier differs from evidence."""
    expected = dict(evidence_semantics_contract()["regime_classifier"])
    if set(observed) != set(expected):
        raise ValueError("execution regime classifier fields differ from evidence")
    comparable = {}
    required = {}
    for key, value in observed.items():
        expected_value = expected[key]
        if isinstance(expected_value, str) and key not in {
            "ema_epsilon", "minimum_slope", "minimum_adx",
            "minimum_hold_seconds",
        }:
            comparable[key] = str(value)
            required[key] = str(expected_value)
            continue
        try:
            comparable[key] = Decimal(str(value))
            required[key] = Decimal(str(expected[key]))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("execution regime classifier is invalid") from exc
    if comparable != required:
        raise ValueError("execution regime classifier differs from evidence")


def require_runtime_regime_contract(
    symbol: str, arguments: object, environ: Mapping[str, str]
) -> None:
    """Validate the supervisor arguments used by the confirmed regime."""
    if symbol.upper() != "SOLUSDT":
        return
    if str(getattr(arguments, "dir_mode", "")).strip().lower() != "auto":
        raise ValueError("execution regime classifier requires automatic mode")
    require_execution_regime_contract({
        "version": REGIME_CLASSIFIER_VERSION,
        "source": "confirmed_execution_regime",
        "interval": getattr(arguments, "dir_interval"),
        "ema_fast_length": REGIME_EMA_FAST_LENGTH,
        "ema_slow_length": REGIME_EMA_SLOW_LENGTH,
        "adx_length": REGIME_ADX_LENGTH,
        "ema_epsilon": getattr(arguments, "dir_eps"),
        "minimum_slope": getattr(arguments, "dir_slope_min"),
        "minimum_adx": getattr(arguments, "dir_adx_min"),
        "direction_confirmations": getattr(arguments, "dir_confirm_bars"),
        "execution_confirmations": environ.get(
            "BOT_REGIME_CONFIRMATIONS", "3"
        ) or "3",
        "recovery_confirmations": environ.get(
            "BOT_REGIME_RECOVERY_CONFIRMATIONS", "3"
        ) or "3",
        "minimum_hold_seconds": environ.get(
            "BOT_REGIME_MIN_HOLD_SEC", "300"
        ) or "300",
        "panic_source": "executor_panic_state",
        "hysteresis_source": "execution_state_machine",
    })


__all__ = [
    "EVIDENCE_SEMANTICS_VERSION",
    "EXCURSION_POLICY",
    "EXECUTABLE_ENTRY_REGIMES",
    "EXECUTION_MODEL_RULE",
    "REGIME_CLASSIFIER_VERSION",
    "REGIME_EMA_FAST_LENGTH",
    "REGIME_EMA_SLOW_LENGTH",
    "REGIME_ADX_LENGTH",
    "V19_EVIDENCE_SEMANTICS_VERSION",
    "V19_EXECUTION_MODEL_RULE",
    "V20_EVIDENCE_SEMANTICS_VERSION",
    "V20_EXECUTION_MODEL_RULE",
    "V21_EVIDENCE_SEMANTICS_VERSION",
    "V21_EXECUTION_MODEL_RULE",
    "V21_EXECUTABLE_ENTRY_REGIMES",
    "V23_EVIDENCE_SEMANTICS_VERSION",
    "V23_EXECUTION_MODEL_RULE",
    "canonical_digest",
    "evidence_semantics_contract",
    "evidence_semantics_fingerprint",
    "execution_model_contract",
    "execution_engine_validation_domain",
    "v20_evidence_semantics_fingerprint",
    "v19_evidence_semantics_fingerprint",
    "v21_evidence_semantics_fingerprint",
    "v23_evidence_semantics_contract",
    "v23_evidence_semantics_fingerprint",
    "require_execution_regime_contract",
    "require_runtime_regime_contract",
]
