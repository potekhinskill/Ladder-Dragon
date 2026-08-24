# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: freeze the evidence semantics shared by collection and execution.
"""Canonical promotion evidence semantics for SOL execution episodes."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Mapping


EVIDENCE_SEMANTICS_VERSION = "minute_l2_episode_execution_v3"
EXECUTION_MODEL_RULE = "minute_l2_fifo_oco_gap_v3"
V19_EVIDENCE_SEMANTICS_VERSION = "minute_l2_episode_execution_v2"
V19_EXECUTION_MODEL_RULE = "minute_l2_fifo_oco_gap_v2"
REGIME_CLASSIFIER_VERSION = "execution_30m_ema_adx_hysteresis_v1"
EXECUTABLE_ENTRY_REGIMES = ("RANGE", "TREND_UP", "TREND_DOWN")


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


def evidence_semantics_contract() -> dict[str, object]:
    """Return the immutable contract used by v20 evidence and execution."""
    return {
        "version": EVIDENCE_SEMANTICS_VERSION,
        "execution_model_rule": EXECUTION_MODEL_RULE,
        "entry_order_policy": "LIMIT_MAKER",
        "take_profit_order_policy": "LIMIT_MAKER",
        "stop_order_policy": "STOP_LOSS_LIMIT",
        "panic_flatten_policy": "INCLUDE_NET_PNL_AND_DRAWDOWN",
        "panic_veto_policy": "TERMINAL_UNFILLED_ATTEMPT",
        "trade_page_policy": "BOUNDED_CONTIGUOUS_AGGTRADES_V1",
        "executable_entry_regimes": list(EXECUTABLE_ENTRY_REGIMES),
        "execution_model": execution_model_contract(),
        "regime_classifier": {
            "version": REGIME_CLASSIFIER_VERSION,
            "source": "confirmed_execution_regime",
            "interval": "30m",
            "ema_fast_length": 20,
            "ema_slow_length": 50,
            "adx_length": 14,
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


def canonical_digest(payload: Mapping[str, object]) -> str:
    """Hash one JSON-compatible contract with stable key ordering."""
    encoded = json.dumps(
        dict(payload), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def evidence_semantics_fingerprint() -> str:
    """Return the reviewed fingerprint required on every v20 episode."""
    return canonical_digest(evidence_semantics_contract())


def v19_evidence_semantics_fingerprint() -> str:
    """Preserve the exact historical v19 fingerprint."""
    contract = evidence_semantics_contract()
    contract["version"] = V19_EVIDENCE_SEMANTICS_VERSION
    contract["execution_model_rule"] = V19_EXECUTION_MODEL_RULE
    contract.pop("executable_entry_regimes", None)
    contract.pop("execution_model", None)
    return canonical_digest(contract)


def execution_validation_domain(
    candidate_parameters: Mapping[str, object],
) -> dict[str, object]:
    """Bind replay validation to the exact candidate and simulator domain."""
    fields = (
        "entry_gap_bps",
        "entry_ttl_sec",
        "target_return",
        "stop_limit_distance",
        "stop_trigger_offset_pct",
        "maximum_holding_min",
        "primary_horizon_min",
        "evidence_notional_quote",
        "execution_model_rule",
        "evidence_semantics_fingerprint",
    )
    domain = {field: candidate_parameters.get(field) for field in fields}
    domain["execution_model"] = execution_model_contract()
    return domain


def require_execution_regime_contract(observed: Mapping[str, object]) -> None:
    """Reject collection when the live classifier differs from v20."""
    expected = dict(evidence_semantics_contract()["regime_classifier"])
    comparable = {}
    required = {}
    for key, value in observed.items():
        if key == "interval":
            comparable[key] = str(value)
            required[key] = str(expected[key])
            continue
        try:
            comparable[key] = Decimal(str(value))
            required[key] = Decimal(str(expected[key]))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError("execution regime classifier is invalid") from exc
    if comparable != required:
        raise ValueError("execution regime classifier differs from v20 evidence")


def require_runtime_regime_contract(
    symbol: str, arguments: object, environ: Mapping[str, str]
) -> None:
    """Validate the supervisor arguments used by the confirmed regime."""
    if symbol.upper() != "SOLUSDT":
        return
    require_execution_regime_contract({
        "interval": getattr(arguments, "dir_interval"),
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
    })


__all__ = [
    "EVIDENCE_SEMANTICS_VERSION",
    "EXECUTABLE_ENTRY_REGIMES",
    "EXECUTION_MODEL_RULE",
    "REGIME_CLASSIFIER_VERSION",
    "V19_EVIDENCE_SEMANTICS_VERSION",
    "V19_EXECUTION_MODEL_RULE",
    "canonical_digest",
    "evidence_semantics_contract",
    "evidence_semantics_fingerprint",
    "execution_model_contract",
    "execution_validation_domain",
    "v19_evidence_semantics_fingerprint",
    "require_execution_regime_contract",
    "require_runtime_regime_contract",
]
