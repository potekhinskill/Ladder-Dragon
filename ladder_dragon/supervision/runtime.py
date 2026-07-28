#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: supervise strategy workers and enforce execution gates.

"""Ladder Dragon ai supervisor support."""

import os
import fcntl
import sys
import time
import math
import signal
import random
import argparse
import subprocess
import json
import sqlite3
import re
import hashlib
from urllib.parse import urlparse
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ladder_dragon.ai.ai_advisor import (
    AIAdvisor,
    AdvisorConfig,
    MarketContext,
    limit_cap_by_recommendation_decimal,
)
from ladder_dragon.ai.context.runtime import (
    AdvisorDecisionStore,
    build_market_features,
    build_portfolio_features,
    context_hash,
    load_trade_features,
)
from ladder_dragon.ai.ai_knowledge import KnowledgeStore
from ladder_dragon.ai.ai_policy import (
    PolicyConfig,
    UsageBudget,
    apply_safety_policy,
    read_usage_today,
    usage_budget_allows,
)
from ladder_dragon.ai.ai_statistical import context_vector
from ladder_dragon.ai.ai_runtime_status import write_runtime_status
from ladder_dragon.ai.ai_control import read_ai_control, resolve_ai_control_path
from ladder_dragon.supervision.entry_policy import (
    adaptive_best_buy_price as _adaptive_best_buy_price,
    directional_entry_settings as _directional_entry_settings,
    finite_decimal as _finite_decimal,
)
from ladder_dragon.supervision.vwap_config import (
    getenv_float,
    parse_decimal_limit_map,
    parse_limit_map,
    parse_pct_map,
    parse_vwap_output,
    resolve_vwap_params,
    resolve_vwap_value,
)
from ladder_dragon.supervision.prediction_shadow import (
    prediction_panic_state as _prediction_panic_state,
)
from ladder_dragon.supervision.process_manager import (
    schedule_child_restart,
    stop_child,
)
from ladder_dragon.supervision.recovery_gate import (
    bounded_recovery_reason as _runtime_recovery_reason,
    exchange_order_absent as _exchange_order_absent,
    pre_running_recovery_gate,
)
from ladder_dragon.supervision.risk_cycle import (
    build_risk_snapshot,
    configured_price_shocks_decimal as _configured_price_shocks_decimal,
    remaining_order_budget_decimal as _remaining_order_budget_decimal,
)
from ladder_dragon.supervision.symbol_service import (
    cap_scaling_inactive_reason as _cap_scaling_inactive_reason,
    limit_target_buys,
)
from ladder_dragon.execution.order_identity import client_order_id
from ladder_dragon.execution.exchange_math import format_step, round_step
from ladder_dragon.execution.order_recovery import (
    OrderJournal,
    read_order_journal_telemetry,
    read_order_observation,
)
from ladder_dragon.execution.cancel_replace import (
    CancelReplaceDependencies,
    atomic_cancel_replace_buy,
)
from ladder_dragon.execution.executor_recovery import classify_oco_legs
from ladder_dragon.execution.latency_trace import LatencyTrace
from ladder_dragon.execution.auth_resilience import (
    AuthResilienceState,
    load_auth_state,
    observe_public_ip_fingerprint,
    public_ip_fingerprint,
    register_auth_failure,
    register_auth_success,
    save_auth_state,
)
from ladder_dragon.execution.telegram_alerts import notify
from ladder_dragon.execution.maintenance_state import (
    DEFAULT_PATH as DEFAULT_MAINTENANCE_PATH,
    load_maintenance_state,
)
from ladder_dragon.risk.risk_manager import (
    RiskDecision,
    RiskLimits,
    RiskManager,
    RiskSnapshot,
    create_manual_halt,
    load_daily_trade_metrics,
    money,
)
from ladder_dragon.risk.risk_statistics import (
    correlated_symbols_multi_window as derive_correlated_symbols_multi_window,
    covariance_var,
    expected_shortfall,
    conversion_price_decimal,
    allocate_cap_by_marginal_risk_decimal,
    marginal_risk_contribution_decimal,
    stress_loss_decimal,
    correlation_clusters_multi_window,
    liquidity_is_sufficient_decimal,
)
from ladder_dragon.execution.executor_stats import commission_quote_value, poll_mytrades_once
from ladder_dragon.execution import tools_stats
from ladder_dragon.execution.inventory_lots import ensure_schema, sync_exchange_fill
from ladder_dragon.execution.time_safety import assess_exchange_clock
from ladder_dragon.execution.venue_config import apply_testnet_paths
from product_version import __version__, product_label, user_agent
from ladder_dragon.strategy.strategy_math import adx_from_klines as _adx_from_klines
from ladder_dragon.strategy.strategy_math import clamp, ema_series as _ema_series
from ladder_dragon.strategy.strategy_math import geometric_ladder as build_ladder_pct
from ladder_dragon.strategy.strategy_math import split_ladder
from ladder_dragon.strategy.strategy_math import RegimeHysteresis
from ladder_dragon.strategy.strategy_math import NumericHysteresis
from ladder_dragon.strategy.expectancy_controls import (
    CommissionSchedule,
    RegimeExecutionStateMachine,
    authoritative_commission_schedule,
    inventory_skew_scale,
    required_round_trip_edge,
)
from ladder_dragon.strategy.reanchor import plan_buy_reanchors
from ladder_dragon.strategy.prediction import (
    PredictionShadowStore,
    TradePlan,
    build_prediction_features,
    predict_distribution,
    trade_flow_from_agg_trades,
    walk_forward_prediction_report,
)
from ladder_dragon.numeric_compat import compatibility_float
from ladder_dragon.supervision.config import (
    build_supervisor_parser,
    validate_supervisor_args,
)

try:
    import requests
except ImportError:
    print("Please install requests: pip install requests", flush=True)
    raise

# >>> tools_market integration
try:
    from ladder_dragon.execution import tools_market as TM
except ImportError as e:
    print(f"[FATAL] cannot import tools_market: {e}", flush=True)
    raise
# <<< tools_market integration

# =========================
# Constants and environment
# =========================

BINANCE_API_BASE = (os.getenv("BINANCE_API_BASE") or os.getenv("BINANCE_BASE_URL") or "https://api.binance.com").rstrip("/")
API_KEY = os.getenv("BINANCE_API_KEY", "")
API_SECRET = os.getenv("BINANCE_API_SECRET", "")
USER_AGENT = os.getenv("USER_AGENT", user_agent("supervisor"))

SUPERVISOR_OPERATION_ERRORS = (
    ArithmeticError,
    KeyError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    requests.RequestException,
    sqlite3.Error,
    subprocess.SubprocessError,
)


def _analytics_float(value: object) -> float:
    """Convert an exact value only at a non-authoritative analytics boundary."""
    return compatibility_float(value, field="analytics value")


# Rounding mode and warm start for order cleanup
PRICE_ROUND_MODE = os.getenv("PRICE_ROUND_MODE", "nearest").lower()  # floor|ceil|nearest
CLEANUP_WARMUP_SEC = int(os.getenv("CLEANUP_WARMUP_SEC", "900") or 900)

SESSION = requests.Session()
if API_KEY:
    SESSION.headers.update({"X-MBX-APIKEY": API_KEY})
SESSION.headers.update({"User-Agent": USER_AGENT})

LOCK_FILE = os.path.join(
    os.getenv("BOT_RUN_DIR", "/run/mybot"), "ai_supervisor.lock"
)
_SINGLETON_LOCK_HANDLE: Any | None = None

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
_CHILD_PROCS: Dict[str, subprocess.Popen] = {}
_CHILD_STARTED_AT: Dict[str, float] = {}
_CHILD_RESTART_AFTER: Dict[str, float] = {}
_CHILD_FAILURES: Dict[str, int] = {}
LIVE_MODE = False
_AI_ADVISOR: Optional[AIAdvisor] = None
_AI_DECISIONS: Optional[AdvisorDecisionStore] = None
_AI_DECISIONS_PATH: Optional[Path] = None
_AI_KNOWLEDGE: Optional[KnowledgeStore] = None
_AI_POLICY: Optional[PolicyConfig] = None
_AI_RUNTIME_STATUS_PATH: Optional[Path] = None
_AI_RUNTIME_STATUS: Dict[str, Any] = {}
_AI_CONTROL_PATH: Optional[Path] = None
_PREDICTION_SHADOW: Optional[PredictionShadowStore] = None
_PREDICTION_LAST_ATTEMPT: Dict[str, float] = {}
_PREDICTION_GATE_CACHE: Dict[
    str, tuple[float, dict[str, object]]
] = {}
_STRATEGY_CONTROL_GATE_CACHE: Dict[
    str, tuple[float, dict[str, object]]
] = {}
_BLOCKED_SHADOW_LAST_ATTEMPT: Dict[str, float] = {}
_INFO_LOG_LAST_EMITTED: Dict[str, float] = {}
# Keep one decision_id for the lifetime of a cached recommendation. This
# prevents virtual statistics and RAG from treating every supervisor cycle as a new model.
_AI_DECISION_IDS: Dict[str, str] = {}
# The last complete-context cache is separate from the LLM response cache.
# Otherwise a cache hit would return only the basic indicators with
# ``*_available=False`` and the dashboard would incorrectly show stale/incomplete.
_AI_CONTEXT_CACHE: Dict[str, tuple[float, MarketContext]] = {}


def _acquire_singleton_lock(path: str = LOCK_FILE) -> None:
    """Acquire a process-lifetime flock or fail before any worker can start."""
    global _SINGLETON_LOCK_HANDLE
    if _SINGLETON_LOCK_HANDLE is not None:
        raise RuntimeError("supervisor singleton lock is already held by this process")
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    handle = os.fdopen(descriptor, "r+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        handle.close()
        raise
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()))
    handle.flush()
    os.fsync(handle.fileno())
    _SINGLETON_LOCK_HANDLE = handle


def _release_singleton_lock() -> None:
    """Release the held flock without unlinking the shared lock inode."""
    global _SINGLETON_LOCK_HANDLE
    handle = _SINGLETON_LOCK_HANDLE
    _SINGLETON_LOCK_HANDLE = None
    if handle is None:
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def env_flag(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "t", "yes", "y", "on")


def _configured_unvalued_assets() -> set[str]:
    """Handle configured unvalued assets."""
    raw = os.getenv("RISK_UNVALUED_ASSETS", "")
    assets = {item.strip().upper() for item in raw.split(",") if item.strip()}
    invalid = sorted(asset for asset in assets if not re.fullmatch(r"[A-Z0-9]{2,20}", asset))
    if invalid:
        raise RuntimeError(
            "RISK_UNVALUED_ASSETS contains invalid asset name(s): " + ",".join(invalid)
        )
    if assets:
        acknowledged = {
            item.strip().upper()
            for item in os.getenv("RISK_UNVALUED_ASSETS_ACK", "").split(",")
            if item.strip()
        }
        if assets != acknowledged:
            raise RuntimeError(
                "RISK_UNVALUED_ASSETS requires an exact matching "
                "RISK_UNVALUED_ASSETS_ACK"
            )
    return assets


def _build_ai_advisor(args: argparse.Namespace) -> Optional[AIAdvisor]:
    """Build ai advisor."""
    if not args.ai_advisor or args.ai_mode == "DISABLED":
        return None

    defaults = {
        "openai": (
            "https://api.openai.com/v1",
            "gpt-5-mini",
            "OPENAI_API_KEY",
        ),
        "deepseek": (
            "https://api.deepseek.com",
            "deepseek-v4-flash",
            "DEEPSEEK_API_KEY",
        ),
        "compatible": (
            args.ai_base_url,
            args.ai_model,
            "AI_API_KEY",
        ),
    }
    default_url, default_model, key_name = defaults[args.ai_provider]
    config = AdvisorConfig(
        enabled=True,
        provider=args.ai_provider,
        model=(args.ai_model or default_model).strip(),
        base_url=(args.ai_base_url or default_url).strip().rstrip("/"),
        api_key=os.environ[key_name],
        timeout_sec=_analytics_float(args.ai_timeout_sec),
        cache_sec=int(args.ai_cache_sec),
        min_confidence=_analytics_float(args.ai_min_confidence),
        width_scale_min=_analytics_float(args.ai_width_scale_min),
        width_scale_max=_analytics_float(args.ai_width_scale_max),
        cap_scale_min=_analytics_float(args.ai_cap_scale_min),
        cap_scale_max=_analytics_float(args.ai_cap_scale_max),
        usage_log_path=args.ai_usage_log,
        usage_log_max_bytes=int(args.ai_usage_log_max_bytes),
        input_cache_hit_usd_per_mtok=getenv_float(
            "AI_INPUT_CACHE_HIT_USD_PER_MTOK"
        ),
        input_cache_miss_usd_per_mtok=getenv_float(
            "AI_INPUT_CACHE_MISS_USD_PER_MTOK"
        ),
        output_usd_per_mtok=getenv_float("AI_OUTPUT_USD_PER_MTOK"),
    )
    budget = UsageBudget(
        max_requests=int(args.ai_max_requests_per_day),
        max_tokens=int(args.ai_daily_token_limit),
        max_cost_usd=Decimal(str(args.ai_daily_cost_limit_usd)),
    )

    def budget_checker() -> tuple[bool, str]:
        return usage_budget_allows(
            read_usage_today(args.ai_usage_log),
            budget,
        )

    def record_low_confidence(
        context: MarketContext,
        recommendation,
        confidence_accepted: bool,
    ) -> str | None:
        if _AI_DECISIONS is None:
            return None
        decision_id = _AI_DECISIONS.record(
            symbol=context.symbol,
            price=context.price,
            deterministic_mode=context.deterministic_mode,
            recommended_mode=recommendation.mode,
            width_scale=recommendation.ladder_width_scale,
            cap_scale=recommendation.cap_scale,
            confidence=recommendation.confidence,
            applied=confidence_accepted,
            policy_status="MODEL_ACCEPTED" if confidence_accepted else "LOW_CONFIDENCE",
            policy_reasons="" if confidence_accepted else "confidence_below_threshold",
            rationale=recommendation.rationale,
            config_version=__version__,
            context_hash_value=context_hash(context),
            feature_json=json.dumps(context_vector(context)),
        )
        if _AI_KNOWLEDGE is not None:
            _AI_KNOWLEDGE.link_retrieval(decision_id, context.rag_context)
        return decision_id

    return AIAdvisor(
        config,
        session=requests.Session(),
        logger=log,
        decision_recorder=record_low_confidence,
        budget_checker=budget_checker,
    )


def log(msg: str) -> None:
    print(msg, flush=True)


def _publish_ai_runtime_status(**updates: Any) -> None:
    """Handle publish ai runtime status."""
    if _AI_RUNTIME_STATUS_PATH is None:
        return
    _AI_RUNTIME_STATUS.update(updates)
    _AI_RUNTIME_STATUS["pid"] = os.getpid()
    try:
        write_runtime_status(_AI_RUNTIME_STATUS_PATH, _AI_RUNTIME_STATUS)
    except OSError as exc:
        dbg(f"[AI-STATUS] write failed: {exc}")


def _runtime_order_journal_snapshot() -> dict[str, Any]:
    """Publish journal counters without exposing SQLite to the dashboard."""
    path = os.getenv("BOT_ORDER_JOURNAL", "")
    if not path:
        return {"available": False, "reason": "order journal path missing"}
    return read_order_journal_telemetry(path)


def _auth_resilience_path() -> Path:
    """Resolve persistent auth state beside other durable runtime databases."""
    configured = os.getenv("BINANCE_AUTH_STATE_FILE", "").strip()
    if configured:
        return Path(configured)
    stats_path = os.getenv("BOT_STATS_DB", "").strip()
    if stats_path:
        return Path(stats_path).with_name("auth_resilience.json")
    return Path(os.getenv("BOT_RUN_DIR", ".runtime")) / "auth_resilience.json"


def _maintenance_path() -> Path:
    return Path(
        os.getenv("BOT_MAINTENANCE_FILE", str(DEFAULT_MAINTENANCE_PATH))
    )


def _wait_for_maintenance_clear(
    args: argparse.Namespace,
    limits: RiskLimits,
) -> None:
    """Keep LIVE inert while an explicit operator maintenance marker exists."""
    if not args.live:
        return
    while True:
        try:
            state = load_maintenance_state(_maintenance_path())
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            _publish_ai_runtime_status(
                state="RECOVERY_BLOCKED",
                error="maintenance state is invalid",
                maintenance={
                    "active": True,
                    "valid": False,
                    "error_type": type(exc).__name__,
                },
                risk={
                    "halted": bool(limits.halt_file.exists()),
                    "buy_blocked": True,
                    "reasons": ["maintenance state is invalid"],
                },
            )
            time.sleep(60)
            continue
        if not state.active:
            _publish_ai_runtime_status(
                maintenance={
                    "active": False,
                    "valid": True,
                    "reason": None,
                }
            )
            return
        _publish_ai_runtime_status(
            state="INTENTIONALLY_STOPPED",
            error=None,
            maintenance={
                "active": True,
                "valid": True,
                "reason": state.reason,
                "updated_at_epoch": state.updated_at_epoch,
            },
            risk={
                "halted": bool(limits.halt_file.exists()),
                "buy_blocked": True,
                "reasons": ["operator maintenance is active"],
            },
        )
        time.sleep(30)


def _read_auth_resilience_state() -> AuthResilienceState:
    """Treat damaged persisted state as a maximum-delay fail-closed state."""
    path = _auth_resilience_path()
    try:
        return load_auth_state(path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        log(
            "[AUTH-BACKOFF] persisted state is invalid; "
            f"error_type={type(exc).__name__}"
        )
        now = int(time.time())
        return AuthResilienceState(
            attempt=1000,
            retry_at_epoch=now + 900,
            public_ip_changed=True,
            updated_at_epoch=now,
        )


def _save_auth_resilience_state(state: AuthResilienceState) -> None:
    save_auth_state(_auth_resilience_path(), state)


def _observe_public_ip(state: AuthResilienceState) -> AuthResilienceState:
    """Check egress identity without logging or persisting the public IP."""
    configured = os.getenv("BINANCE_PUBLIC_IP_ENDPOINTS", "").strip()
    if not configured:
        configured = os.getenv("BINANCE_PUBLIC_IP_ENDPOINT", "").strip()
    endpoints = [
        item.strip() for item in configured.split(",") if item.strip()
    ]
    hosts: set[str] = set()
    valid_endpoints: list[str] = []
    for endpoint in endpoints[:3]:
        parsed = urlparse(endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.hostname in hosts
        ):
            continue
        hosts.add(parsed.hostname)
        valid_endpoints.append(endpoint)
    if not valid_endpoints:
        return state
    fingerprints: list[str] = []
    for endpoint in valid_endpoints:
        try:
            response = requests.get(endpoint, timeout=5)
            response.raise_for_status()
            fingerprints.append(public_ip_fingerprint(response.text))
        except (requests.RequestException, UnicodeError, ValueError) as exc:
            log(
                "[IP-GUARD] one public IP source unavailable; "
                f"error_type={type(exc).__name__}"
            )
    consensus = (
        fingerprints[0]
        if len(fingerprints) >= 2 and len(set(fingerprints)) == 1
        else None
    )
    if consensus is None:
        _publish_ai_runtime_status(ip_guard={
            "configured_sources": len(valid_endpoints),
            "available_sources": len(fingerprints),
            "consensus": False,
            "address_exposed": False,
        })
        log(
            "[IP-GUARD] source consensus unavailable; "
            "Binance signed authentication remains authoritative"
        )
        return state
    observed = observe_public_ip_fingerprint(state, consensus)
    if observed != state:
        _save_auth_resilience_state(observed)
    _publish_ai_runtime_status(ip_guard={
        "configured_sources": len(valid_endpoints),
        "available_sources": len(fingerprints),
        "consensus": True,
        "changed": observed.public_ip_changed,
        "address_exposed": False,
    })
    if observed.public_ip_changed:
        notify(
            "public egress IP changed",
            ["Binance whitelist review is required; BUY remains blocked"],
            {"fingerprint": consensus[:12], "sources": len(fingerprints)},
        )
        raise RuntimeError(
            "public egress IP fingerprint changed; "
            "Binance whitelist review required"
        )
    return observed


def _verify_live_protection(
    journal: OrderJournal,
    parent_client_order_id: str,
) -> int:
    """Verify an exact protection order and every OCO leg at Binance."""
    protection = journal.protection_for_parent(parent_client_order_id)
    if protection is None:
        raise RuntimeError("protected BUY has no linked protection intent")
    if protection.order_type in {"OCO", "OTOCO"}:
        list_type = protection.order_type
        payload = TM._signed_get(
            "/api/v3/orderList",
            {"origClientOrderId": protection.client_order_id},
        )
        if not isinstance(payload, dict):
            raise RuntimeError("OCO reconciliation response is invalid")
        if (
            str(payload.get("listClientOrderId") or "")
            != protection.client_order_id
            or int(payload.get("orderListId", -1))
            != int(protection.exchange_order_list_id or -2)
            or str(payload.get("contingencyType") or "").upper() != list_type
        ):
            raise RuntimeError(
                f"{list_type} identity differs from durable journal"
            )
        list_status = str(
            payload.get("listStatusType") or ""
        ).upper()
        if list_status not in {"EXEC_STARTED", "ALL_DONE"}:
            raise RuntimeError(
                f"{list_type} has an unknown exchange status"
            )
        references = payload.get("orders")
        expected_orders = 3 if list_type == "OTOCO" else 2
        if (
            not isinstance(references, list)
            or len(references) != expected_orders
        ):
            raise RuntimeError(
                f"{list_type} does not contain exactly "
                f"{expected_orders} orders"
            )
        queried: list[dict[str, Any]] = []
        for reference in references:
            if not isinstance(reference, dict) or reference.get("orderId") is None:
                raise RuntimeError("OCO leg reference is invalid")
            if str(reference.get("symbol") or "").upper() != protection.symbol:
                raise RuntimeError("OCO leg symbol differs from durable journal")
            leg = TM._signed_get(
                "/api/v3/order",
                {
                    "symbol": protection.symbol,
                    "orderId": int(reference["orderId"]),
                },
            )
            if not isinstance(leg, dict):
                raise RuntimeError("OCO leg reconciliation response is invalid")
            queried.append(leg)
        if list_type == "OTOCO":
            working = [
                order
                for order in queried
                if str(order.get("clientOrderId") or "")
                == parent_client_order_id
            ]
            if (
                len(working) != 1
                or str(working[0].get("side") or "").upper() != "BUY"
                or str(working[0].get("status") or "").upper() != "FILLED"
            ):
                raise RuntimeError("OTOCO working BUY is not exactly FILLED")
            legs = [
                order
                for order in queried
                if str(order.get("clientOrderId") or "")
                != parent_client_order_id
            ]
        else:
            legs = queried
        if any(str(leg.get("side") or "").upper() != "SELL" for leg in legs):
            raise RuntimeError(f"{list_type} contains a non-SELL protection leg")
        if any(
            str(leg.get("symbol") or "").upper() != protection.symbol
            or int(leg.get("orderListId", -1))
            != int(protection.exchange_order_list_id or -2)
            for leg in legs
        ):
            raise RuntimeError(
                f"{list_type} leg identity differs from durable journal"
            )
        leg_types = {str(leg.get("type") or "").upper() for leg in legs}
        if not ({"LIMIT_MAKER", "LIMIT"} & leg_types) or not (
            {"STOP_LOSS_LIMIT", "STOP_LOSS"} & leg_types
        ):
            raise RuntimeError(
                f"{list_type} protection leg types are invalid"
            )
        outcome, filled_leg, exit_reason = classify_oco_legs(legs)
        if list_status == "ALL_DONE" and outcome == "CLOSED":
            if (
                filled_leg is None
                or exit_reason is None
                or filled_leg.get("orderId") is None
            ):
                raise RuntimeError(
                    f"{list_type} closed without an exact SELL fill"
                )
            journal.record_verified_protection_legs(
                protection.client_order_id,
                legs,
            )
            journal.mark_exact_lifecycle_closed(
                protection_client_order_id=protection.client_order_id,
                exit_order_id=int(filled_leg["orderId"]),
                exit_reason=exit_reason,
            )
            return 0
        if list_status != "EXEC_STARTED" or outcome != "ACTIVE":
            raise RuntimeError(
                f"{list_type} is not actively protecting inventory"
            )
        observed_ids = {int(leg["orderId"]) for leg in legs}
        stored_ids = {
            int(row["order_id"])
            for row in (protection.metadata or {}).get("verified_legs", [])
            if isinstance(row, dict) and row.get("order_id") is not None
        }
        if stored_ids and stored_ids != observed_ids:
            raise RuntimeError(
                f"{list_type} exchange legs differ from durable journal"
            )
        journal.update_metadata(
            protection.client_order_id,
            {
                "verified_legs": [
                    {
                        "order_id": int(leg["orderId"]),
                        "client_order_id": str(
                            leg.get("clientOrderId") or ""
                        ),
                        "leg_type": str(leg.get("type") or "").upper(),
                    }
                    for leg in legs
                ],
                "startup_exchange_verified_at": int(time.time()),
            },
        )
        return 3
    payload = TM._signed_get(
        "/api/v3/order",
        {
            "symbol": protection.symbol,
            "origClientOrderId": protection.client_order_id,
        },
    )
    if (
        not isinstance(payload, dict)
        or str(payload.get("symbol") or "").upper() != protection.symbol
        or int(payload.get("orderId", -1))
        != int(protection.exchange_order_id or -2)
        or str(payload.get("side") or "").upper() != "SELL"
        or str(payload.get("type") or "").upper()
        != protection.order_type.upper()
        or str(payload.get("status") or "").upper()
        not in {"NEW", "PARTIALLY_FILLED"}
    ):
        raise RuntimeError("single-order protection is not active")
    return 1


def _verify_all_live_protection(
    journal: OrderJournal,
    symbols: list[str],
) -> int:
    """Verify every journal-protected BUY against authoritative Binance state."""
    checked = 0
    configured = {str(symbol).upper() for symbol in symbols}
    for buy in journal.protected_buys():
        if buy.symbol not in configured:
            raise RuntimeError("protected journal symbol is outside configuration")
        checked += _verify_live_protection(journal, buy.client_order_id)
    return checked


def _create_manual_halt_once(
    reason: str,
    *,
    limits: RiskLimits | None = None,
    metadata: dict[str, object],
) -> None:
    """Persist and notify one safety reason without repeating every risk tick."""
    resolved_limits = limits or RiskLimits.from_env()
    halt_file = getattr(resolved_limits, "halt_file", None)
    if halt_file is not None:
        try:
            payload = json.loads(Path(halt_file).read_text(encoding="utf-8"))
            if reason in list(payload.get("reasons") or []):
                return
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
            pass
    create_manual_halt(
        reason,
        limits=resolved_limits,
        metadata=metadata,
    )


def _runtime_protection_gate(symbols: list[str], limits: RiskLimits) -> int:
    """Fail closed when a journal-protected lot has no active exchange protection."""
    path = os.getenv("BOT_ORDER_JOURNAL", "").strip()
    if not path:
        raise RuntimeError("LIVE order journal path is missing")
    journal = OrderJournal(
        path,
        venue="testnet" if "testnet" in TM.BASE_URL.lower() else "mainnet",
    )
    try:
        return _verify_all_live_protection(journal, symbols)
    except (RuntimeError, ValueError, KeyError, TypeError, requests.RequestException) as exc:
        reason = f"journal protected BUY differs from Binance: {exc}"
        _create_manual_halt_once(
            reason,
            limits=limits,
            metadata={"gate": "journal_exchange_protection"},
        )
        raise RuntimeError(reason) from exc


def _unresolved_fill_counts() -> Dict[str, int]:
    """Separate execution inventory risk from advisory attribution gaps."""
    if _AI_DECISIONS_PATH is None or not _AI_DECISIONS_PATH.exists():
        return {"total": 0, "attribution": 0, "inventory": 0}
    try:
        with sqlite3.connect(
            f"file:{_AI_DECISIONS_PATH}?mode=ro",
            uri=True,
            timeout=2,
        ) as connection:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='ai_unresolved_fills'"
            ).fetchone()
            if table is None:
                raise RuntimeError("unresolved-fill table is missing")
            total = int(
                connection.execute(
                    "SELECT COUNT(*) FROM ai_unresolved_fills"
                ).fetchone()[0]
            )
            columns = {
                str(row[1])
                for row in connection.execute(
                    "PRAGMA table_info(ai_unresolved_fills)"
                )
            }
            if "resolution_scope" not in columns:
                # A legacy or damaged schema has not proven that its rows are
                # attribution-only. Preserve the historical fail-closed rule.
                return {
                    "total": total,
                    "attribution": 0,
                    "inventory": total,
                }
            attribution = int(
                connection.execute(
                    "SELECT COUNT(*) FROM ai_unresolved_fills "
                    "WHERE resolution_scope='ATTRIBUTION'"
                ).fetchone()[0]
            )
            inventory = int(
                connection.execute(
                    "SELECT COUNT(*) FROM ai_unresolved_fills "
                    "WHERE resolution_scope='INVENTORY' "
                    "OR resolution_scope IS NULL "
                    "OR resolution_scope NOT IN ('ATTRIBUTION','INVENTORY')"
                ).fetchone()[0]
            )
            return {
                "total": total,
                "attribution": attribution,
                "inventory": inventory,
            }
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        raise RuntimeError("unresolved-fill reconciliation unavailable") from exc


def _pre_running_recovery_gate(
    args: argparse.Namespace,
    symbols: List[str],
) -> dict[str, Any]:
    """Reconcile every durable nonterminal intent before claiming RUNNING."""
    return pre_running_recovery_gate(args, symbols, runtime=globals())


def _refresh_ai_control(args: argparse.Namespace) -> None:
    """Handle refresh ai control."""
    global _AI_POLICY
    if _AI_CONTROL_PATH is None or _AI_POLICY is None:
        return
    configured_mode = args.ai_mode if args.ai_advisor else "DISABLED"
    control_error = None
    try:
        control = read_ai_control(_AI_CONTROL_PATH)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        control = {"enabled": False, "mode": "DISABLED"}
        control_error = str(exc)
    if control is None:
        effective_mode = configured_mode
        control_enabled = configured_mode != "DISABLED"
    else:
        control_enabled = bool(control.get("enabled"))
        effective_mode = configured_mode if control_enabled else "DISABLED"
    previous_mode = _AI_POLICY.mode
    if effective_mode != previous_mode:
        _AI_POLICY = replace(_AI_POLICY, mode=effective_mode)
        log(f"[AI-CONTROL] mode={effective_mode}")
        if effective_mode == "DISABLED" and previous_mode != "DISABLED":
            # Existing children may have received AI parameters; restart them so
            # the next plan is fully deterministic.
            _stop_children("AI disabled from dashboard")
    ai_status = _AI_RUNTIME_STATUS.setdefault("ai", {})
    ai_status.update({
        "mode": effective_mode,
        "configured_mode": configured_mode,
        "control_enabled": control_enabled,
        "control_error": control_error,
    })
    _publish_ai_runtime_status()


def dbg(msg: str) -> None:
    if LOG_LEVEL in ("DEBUG", "TRACE"):
        print(msg, flush=True)

# =========================
# Utilities
# =========================

# VWAP configuration parsing lives in ladder_dragon.supervision.vwap_config.

def symbol_assets(symbol: str) -> Tuple[str, str]:
    if symbol.endswith("USDT"):
        return symbol[:-4], "USDT"
    for q in ("BUSD", "USDC", "BTC", "ETH"):
        if symbol.endswith(q):
            return symbol[:-len(q)], q
    return symbol[:-3], symbol[-3:]

# =========================
# Resilient backoff with jitter
# =========================

# ================
# Request signing
# ================

# ---- tools_market-based HTTP helpers ----

def _public_get(path: str, params: Dict[str, Any] = None, timeout: int = 15) -> Any:
    return TM._public_get(path, params or {})

def _canonical_signed_request(method: str, path: str, params: Dict[str, Any] = None, timeout: int = 15) -> Any:
    if params is None:
        params = {}
    base_params = params.copy()
    base_params["timestamp"] = str(TM._timestamp_ms())
    base_params["recvWindow"] = str(getattr(TM, "RECV_WINDOW", 5000))

    items: List[Tuple[str, str]] = [(k, str(v)) for k, v in base_params.items()]
    sig = TM._sign_tuples(items, TM.API_SECRET)
    items.append(("signature", sig))

    headers = {"X-MBX-APIKEY": TM.API_KEY} if TM.API_KEY else {}
    url = f"{TM.BASE_URL}{path}"
    r = TM._do_request(method.upper(), url, params=items, headers=headers)
    TM._raise_for_binance(r)
    try:
        return r.json()
    except ValueError:
        return r.text

# ===========================
# Account and market access
# ===========================

def get_server_time_offset_ms() -> int:
    try:
        t0 = int(time.time() * 1000)
        j = _public_get("/api/v3/time")
        srv = int(j.get("serverTime", t0))
        t1 = int(time.time() * 1000)
        rtt = (t1 - t0) // 2
        offset = srv - (t0 + rtt)
        log(f"[INFO] Server time offset: {offset} ms")
        return offset
    except (
        requests.RequestException,
        RuntimeError,
        TypeError,
        ValueError,
        KeyError,
    ) as e:
        log(f"[WARN] server time failed: {e}")
        return 0

def get_last_price(symbol: str) -> float:
    return _analytics_float(get_last_price_decimal(symbol))


def get_last_price_decimal(symbol: str) -> Decimal:
    """Return an exact positive ticker price for financial valuation."""
    price = _finite_decimal(TM.get_ticker_price(symbol), name=f"{symbol} ticker price")
    if price <= 0:
        raise ValueError(f"{symbol} ticker price must be positive")
    return price

def get_24h_volume_quote(symbol: str) -> float:
    j = _public_get("/api/v3/ticker/24hr", params={"symbol": symbol})
    return _analytics_float(j.get("quoteVolume", 0.0))

def get_exchange_filters(symbol: str) -> Dict[str, object]:
    f = TM.get_symbol_filters(symbol)
    tick_exact = str(f.get("tickSizeExact", f.get("tickSize", "0")))
    step_exact = str(f.get("stepSizeExact", f.get("stepSize", "0")))
    min_qty_exact = str(f.get("minQtyExact", f.get("minQty", "0")))
    min_notional_exact = str(
        f.get("minNotionalExact", f.get("minNotional", "0"))
    )
    tick = _analytics_float(tick_exact)
    step = _analytics_float(step_exact)
    min_qty = _analytics_float(min_qty_exact)
    min_notional = _analytics_float(min_notional_exact)
    log(f"[FILTERS] {symbol} tickSize={tick:.8f} stepSize={step:.8f} "
        f"minQty={min_qty:.6f} minNotional={min_notional:.2f}")
    return {
        "tickSize": tick,
        "stepSize": step,
        "minQty": min_qty,
        "minNotional": min_notional,
        "tickSizeExact": tick_exact,
        "stepSizeExact": step_exact,
        "minQtyExact": min_qty_exact,
        "minNotionalExact": min_notional_exact,
    }

# --- filter cache ---
_FILTERS_CACHE: Dict[str, Dict[str, object]] = {}

def get_exchange_filters_cached(symbol: str) -> Dict[str, object]:
    f = _FILTERS_CACHE.get(symbol)
    if f is None:
        f = get_exchange_filters(symbol)
        _FILTERS_CACHE[symbol] = f
    return f

def invalidate_exchange_filters_cache(symbol: Optional[str] = None) -> None:
    if symbol is None:
        _FILTERS_CACHE.clear()
    else:
        _FILTERS_CACHE.pop(symbol, None)

def get_balances() -> Dict[str, Decimal]:
    j = TM._signed_get("/api/v3/account")
    out: Dict[str, Decimal] = {}
    for b in j.get("balances", []):
        free = _finite_decimal(b.get("free", "0"), name="balance.free")
        locked = _finite_decimal(b.get("locked", "0"), name="balance.locked")
        if free + locked > 0:
            out[b["asset"]] = free
    return out

def get_balances_full() -> Dict[str, Dict[str, Decimal]]:
    j = TM._signed_get("/api/v3/account")
    out: Dict[str, Dict[str, Decimal]] = {}
    for b in j.get("balances", []):
        free = _finite_decimal(b.get("free", "0"), name="balance.free")
        locked = _finite_decimal(b.get("locked", "0"), name="balance.locked")
        if free + locked > 0:
            out[b["asset"]] = {"free": free, "locked": locked}
    return out

_AVG_CACHE: Dict[str, Dict[str, object]] = {}

def avg_entry_price(symbol: str, *, cache_ttl: int = 45, lookback: int = 1000) -> Optional[Decimal]:
    """Reconstruct the exact average entry without inventing missing history."""
    now_ts = time.time()
    ent = _AVG_CACHE.get(symbol)
    if ent and (now_ts - _analytics_float(ent.get("ts", 0.0))) < cache_ttl and money(ent.get("pos", 0)) > 0:
        return _finite_decimal(ent.get("avg", "0"), name="cached average entry")

    base, quote = symbol_assets(symbol)
    bals = get_balances_full()
    bal = bals.get(base, {"free": Decimal("0"), "locked": Decimal("0")})
    pos = money(bal.get("free", 0)) + money(bal.get("locked", 0))
    if pos <= 0:
        _AVG_CACHE[symbol] = {"ts": now_ts, "avg": 0.0, "pos": 0.0}
        return None

    stats_db = os.getenv("BOT_STATS_DB", "").strip()
    if stats_db:
        try:
            with sqlite3.connect(f"file:{stats_db}?mode=ro", uri=True, timeout=3) as con:
                row = con.execute(
                    "SELECT qty_text,avg_cost_text FROM inventory_exact WHERE symbol=?",
                    (symbol.upper(),),
                ).fetchone()
            if row and Decimal(str(row[0])) > 0 and Decimal(str(row[1])) > 0:
                avg_px = _finite_decimal(row[1], name="inventory average entry")
                _AVG_CACHE[symbol] = {
                    "ts": now_ts,
                    "avg": avg_px,
                    "pos": _finite_decimal(row[0], name="inventory quantity"),
                }
                return avg_px
        except (OSError, sqlite3.Error, ArithmeticError, ValueError):
            pass

    try:
        trades = TM._signed_get("/api/v3/myTrades", {"symbol": symbol, "limit": lookback}) or []
    except (requests.RequestException, RuntimeError, TypeError, ValueError) as e:
        dbg(f"[AVG] {symbol} myTrades error: {e}")
        return (
            _finite_decimal(ent.get("avg", "0"), name="cached average entry")
            if ent and money(ent.get("pos", 0)) > 0 else None
        )

    if not isinstance(trades, list) or not trades:
        return None

    try:
        trades.sort(key=lambda t: int(t.get("time", 0)))
    except (TypeError, ValueError):
        return (
            _finite_decimal(ent.get("avg", "0"), name="cached average entry")
            if ent and money(ent.get("pos", 0)) > 0 else None
        )

    qty = Decimal("0")
    cost = Decimal("0")
    for t in trades:
        try:
            is_buy = bool(t.get("isBuyer"))
            q = _finite_decimal(t.get("qty") or "0", name="trade quantity")
            p = _finite_decimal(t.get("price") or "0", name="trade price")
            commission = _finite_decimal(
                t.get("commission") or "0", name="trade commission"
            )
            commission_asset = str(t.get("commissionAsset", "")).upper()
            if is_buy:
                net_q = q - commission if commission_asset == base.upper() else q
                cash_fee = commission if commission_asset == quote.upper() else Decimal("0")
                qty += max(Decimal("0"), net_q)
                cost += p * q + cash_fee
            else:
                inventory_out = q + commission if commission_asset == base.upper() else q
                sell = min(inventory_out, qty)
                if sell > 0 and qty > 0:
                    avg = cost / qty if qty > 0 else Decimal("0")
                    cost -= avg * sell
                    qty -= sell
        except (ArithmeticError, KeyError, TypeError, ValueError):
            continue

    if qty <= 0:
        _AVG_CACHE[symbol] = {"ts": now_ts, "avg": 0.0, "pos": 0.0}
        return None

    avg_px = cost / qty
    _AVG_CACHE[symbol] = {"ts": now_ts, "avg": avg_px, "pos": qty}
    return avg_px

def list_open_orders(symbol: str) -> List[Dict[str, Any]]:
    try:
        return TM._signed_get("/api/v3/openOrders", {"symbol": symbol}) or []
    except (AttributeError, TypeError, ValueError):
        return []

def cancel_order(symbol: str, order_id: int) -> bool:
    if not LIVE_MODE:
        log(f"[DRY] skip cancel {symbol} orderId={order_id}")
        return False
    try:
        _canonical_signed_request("DELETE", "/api/v3/order", {"symbol": symbol, "orderId": order_id})
        return True
    except (
        requests.RequestException,
        RuntimeError,
        ArithmeticError,
        TypeError,
        ValueError,
    ) as e:
        log(f"[CANCEL] {symbol} orderId={order_id} -> {e}")
        return False


# --- filter errors (price/quantity format) ---
def _is_filter_error(e: Exception) -> bool:
    try:
        resp = getattr(e, "response", None)
        if resp is None:
            return False
        j = resp.json()
        code = j.get("code")
        # -1013 BAD_ARGUMENTS / INVALID_PRICE_QTY, -1111 precision, -1102 and -1106 are format errors.
        return code in (-1013, -1111, -1102, -1106)
    except (TypeError, ValueError):
        return False

# ======= precise qty/price formatting for exchange steps =======

def _round_price(price: float, tick: float, mode: str) -> float:
    if tick <= 0:
        return _analytics_float(f"{price:.8f}")
    x = price / tick
    if mode == "ceil":
        q = math.ceil(x) * tick
    elif mode == "nearest":
        q = math.floor(x + 0.5) * tick
    else:
        q = math.floor(x) * tick
    return _analytics_float(f"{q:.8f}")

def _round_to_tick(price: float, tick: float) -> float:
    return _round_price(price, tick, PRICE_ROUND_MODE)


def _deduplicate_ladder_prices(
    prices: List[float], now_price: float, tick: object
) -> List[float]:
    """Round ladder prices and deduplicate exact exchange tick keys by side."""
    seen: set[tuple[str, str]] = set()
    deduplicated: List[float] = []
    for price in prices:
        rounded = round_step(price, tick, PRICE_ROUND_MODE)
        rounded_float = _analytics_float(rounded)
        side = "B" if rounded_float < now_price else "S"
        key = (format_step(rounded, tick), side)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(rounded_float)
    return deduplicated

def place_limit_order(symbol: str, side: str, quantity: object, price: object,
                      filters: Optional[Dict[str, object]] = None) -> Optional[Dict[str, Any]]:
    """Place limit order."""
    if not LIVE_MODE:
        log(f"[DRY] skip LIMIT {symbol} {side.upper()} {quantity} @ {price}")
        return None
    try:
        qty_s, price_s = TM.round_qty_price(
            symbol=symbol,
            qty=_finite_decimal(quantity, name="quantity"),
            price=_finite_decimal(price, name="price"),
            side=side.upper(),
        )

        params = {
            "symbol": symbol,
            "side": side.upper(),
            "type": "LIMIT",
            "timeInForce": "GTC",
            "quantity": qty_s,
            "price": price_s,
            "newOrderRespType": "ACK",
            "newClientOrderId": client_order_id(symbol, side, "limit", price_s, qty_s),
        }
        j = _canonical_signed_request("POST", "/api/v3/order", params)
        oid = j.get("orderId") if isinstance(j, dict) else None
        log(f"[PLACE] {symbol} {side.upper()} {qty_s} @ {price_s} (order {oid})")
        return j if isinstance(j, dict) else None

    except SUPERVISOR_OPERATION_ERRORS as e:
        log(f"[PLACE-ERR] {symbol} {side.upper()} {quantity} @ {price} -> {e}")
        # Attempt one filter invalidation and retry.
        if _is_filter_error(e):
            invalidate_exchange_filters_cache(symbol)
            try:
                # Normalize through TM again in case the exchange steps changed.
                qty_s, price_s = TM.round_qty_price(
                    symbol=symbol,
                    qty=_finite_decimal(quantity, name="quantity"),
                    price=_finite_decimal(price, name="price"),
                    side=side.upper(),
                )
                params = {
                    "symbol": symbol,
                    "side": side.upper(),
                    "type": "LIMIT",
                    "timeInForce": "GTC",
                    "quantity": qty_s,
                    "price": price_s,
                    "newOrderRespType": "ACK",
                    "newClientOrderId": client_order_id(symbol, side, "limit", price_s, qty_s),
                }
                j2 = _canonical_signed_request("POST", "/api/v3/order", params)
                oid2 = j2.get("orderId") if isinstance(j2, dict) else None
                log(f"[PLACE-RETRY] {symbol} {side.upper()} {qty_s} @ {price_s} (order {oid2})")
                return j2 if isinstance(j2, dict) else None
            except SUPERVISOR_OPERATION_ERRORS as e2:
                log(f"[PLACE-RETRY-ERR] {symbol} -> {e2}")
        return None

def place_market_order(symbol: str, side: str, quantity: object,
                       ref_price: Optional[object] = None,
                       filters: Optional[Dict[str, object]] = None) -> Optional[Dict[str, Any]]:
    """Place market order."""
    if not LIVE_MODE:
        log(f"[DRY] skip MARKET {symbol} {side.upper()} {quantity}")
        return None
    try:
        if ref_price is None:
            ref_price = get_last_price(symbol)

        qty_s, _ = TM.round_qty_price(
            symbol=symbol,
            qty=_finite_decimal(quantity, name="quantity"),
            price=_finite_decimal(ref_price, name="reference price"),
            side=side.upper(),
        )

        params = {
            "symbol": symbol,
            "side": side.upper(),
            "type": "MARKET",
            "quantity": qty_s,
            "newOrderRespType": "ACK",
            "newClientOrderId": client_order_id(symbol, side, "market", ref_price, qty_s, bucket_seconds=30),
        }
        j = _canonical_signed_request("POST", "/api/v3/order", params)
        oid = j.get("orderId") if isinstance(j, dict) else None
        log(f"[PLACE] {symbol} {side.upper()} {qty_s} @ MARKET (order {oid})")
        return j if isinstance(j, dict) else None

    except SUPERVISOR_OPERATION_ERRORS as e:
        log(f"[PLACE-ERR] {symbol} {side.upper()} MARKET {quantity} -> {e}")
        if _is_filter_error(e):
            invalidate_exchange_filters_cache(symbol)
            try:
                if ref_price is None:
                    ref_price = get_last_price(symbol)
                qty_s, _ = TM.round_qty_price(
                    symbol=symbol,
                    qty=_finite_decimal(quantity, name="quantity"),
                    price=_finite_decimal(ref_price, name="reference price"),
                    side=side.upper(),
                )
                params = {
                    "symbol": symbol,
                    "side": side.upper(),
                    "type": "MARKET",
                    "quantity": qty_s,
                    "newOrderRespType": "ACK",
                    "newClientOrderId": client_order_id(symbol, side, "market", ref_price, qty_s, bucket_seconds=30),
                }
                j2 = _canonical_signed_request("POST", "/api/v3/order", params)
                oid2 = j2.get("orderId") if isinstance(j2, dict) else None
                log(f"[PLACE-RETRY] {symbol} {side.upper()} {qty_s} @ MARKET (order {oid2})")
                return j2 if isinstance(j2, dict) else None
            except SUPERVISOR_OPERATION_ERRORS as e2:
                log(f"[PLACE-RETRY-ERR] {symbol} -> {e2}")
        return None

# ============================
# Smart order cleanup
# ============================

def _log_order_lifetime(
    symbol: str,
    order: Dict[str, Any],
    *,
    now_price: float,
    age_sec: int,
    ttl_sec: Optional[int],
    cancel_reason: str,
) -> None:
    """Emit durable, secret-free evidence explaining an unfilled cancel."""
    order_id = int(order.get("orderId") or 0)
    observation = read_order_observation(
        os.getenv("BOT_ORDER_JOURNAL", ""),
        order_id,
    )
    limit_price = money(order.get("price") or "0")
    market_price = money(now_price)
    distance_pct = None
    if market_price > 0 and limit_price > 0:
        distance_pct = (
            (market_price - limit_price) / market_price * Decimal("100")
        ).quantize(Decimal("0.0001"))
    log(
        "[ORDER-LIFETIME] "
        + json.dumps(
            {
                "symbol": symbol,
                "order_id": order_id,
                "cancel_reason": cancel_reason,
                "age_sec": max(0, int(age_sec)),
                "ttl_sec": int(ttl_sec) if ttl_sec is not None else None,
                "limit_price": str(limit_price),
                "market_price_at_cancel": str(market_price),
                "limit_below_market_pct": (
                    str(distance_pct) if distance_pct is not None else None
                ),
                "minimum_observed_market_price": observation.get(
                    "market_min_price"
                ),
                "market_observation_count": observation.get(
                    "market_observation_count", 0
                ),
                "executed_qty": str(order.get("executedQty") or "0"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )

def startup_cleanup_orders(symbol: str,
                           now_price: float,
                           ladder_prices: List[float],
                           tick_size: float,
                           grace_sec: Optional[int]) -> Dict[str, int]:
    """Cancel only proven stale startup BUYs while preserving every SELL."""
    try:
        orders = list_open_orders(symbol)
    except SUPERVISOR_OPERATION_ERRORS as e:
        log(f"[START-CLEANUP] {symbol} list_open_orders failed: {e}")
        return {"reviewed": 0, "canceled": 0}
    if not orders:
        return {"reviewed": 0, "canceled": 0}

    allowed = {_round_to_tick(p, tick_size) for p in ladder_prices}
    now_ms = int(time.time() * 1000)

    reviewed = canceled = 0
    for o in orders:
        try:
            reviewed += 1
            # Generic ladder cleanup owns BUY intents only. Protective SELL,
            # OCO and OTOCO legs are lifecycle-managed by the executor and may
            # never be removed by age or ladder-distance policy.
            if str(o.get("side") or "").upper() != "BUY":
                continue
            typ = (o.get("type") or "").upper()
            if typ not in ("LIMIT", "LIMIT_MAKER"):
                continue

            price = _analytics_float(o.get("price") or 0.0)
            pr = _round_to_tick(price, tick_size)
            upd = int(o.get("updateTime") or o.get("time") or now_ms)
            age = max(0, (now_ms - upd)//1000)

            off = pr not in allowed
            old = (grace_sec is not None and age > int(grace_sec))
            offladder_grace = int(
                os.getenv(
                    "START_CLEANUP_OFFLADDER_GRACE_SEC",
                    str(grace_sec if grace_sec is not None else 900),
                )
                or 0
            )

            do_cancel = False
            reason = None
            if old:
                do_cancel = True
                reason = f"age>{grace_sec}s"
            elif off:
                if offladder_grace == 0 or age > offladder_grace:
                    do_cancel = True
                    reason = "off-ladder"

            if do_cancel:
                if cancel_order(symbol, int(o.get("orderId"))):
                    canceled += 1
                    log(
                        f"[START-CLEANUP] {symbol} canceled id={o.get('orderId')} "
                        f"price={pr} age={age}s ttl={grace_sec}s reason={reason}"
                    )
                    _log_order_lifetime(
                        symbol,
                        o,
                        now_price=now_price,
                        age_sec=age,
                        ttl_sec=grace_sec,
                        cancel_reason=str(reason),
                    )
        except SUPERVISOR_OPERATION_ERRORS as e:
            log(f"[START-CLEANUP] {symbol} skip: {e}")

    log(f"[START-CLEANUP-SUM] {symbol} reviewed={reviewed} canceled={canceled}")
    return {"reviewed": reviewed, "canceled": canceled}

def smart_cleanup_orders(symbol: str,
                         now_price: float,
                         ladder_prices: List[float],
                         tick_size: float,
                         near_ttl_sec: Optional[int],
                         far_ttl_sec: Optional[int],
                         cancel_offladder: bool = True) -> Dict[str, int]:
    """Apply bounded TTL cleanup without touching protective orders."""
    try:
        orders = list_open_orders(symbol)
    except SUPERVISOR_OPERATION_ERRORS as e:
        log(f"[CLEANUP] {symbol} list_open_orders failed: {e}")
        return {"reviewed": 0, "canceled": 0}
    if not orders:
        return {"reviewed": 0, "canceled": 0}

    now_ms = int(time.time() * 1000)
    near_lo = now_price * 0.90
    near_hi = now_price * 1.10
    allowed = {_round_to_tick(p, tick_size) for p in ladder_prices} if cancel_offladder else set()
    offladder_grace = int(
        os.getenv("CLEANUP_OFFLADDER_GRACE_SEC", str(CLEANUP_WARMUP_SEC)) or 0
    )

    reviewed = canceled = 0
    for o in orders:
        try:
            reviewed += 1
            # SELL orders can be the only active protection for filled
            # inventory. Only the executor's exact lifecycle may cancel them.
            if str(o.get("side") or "").upper() != "BUY":
                continue
            price = _analytics_float(o.get("price") or 0.0)
            pr = _round_to_tick(price, tick_size)
            upd = int(o.get("updateTime") or o.get("time") or now_ms)
            age = max(0, (now_ms - upd)//1000)

            in_near = (near_lo <= price <= near_hi)
            ttl = (near_ttl_sec if in_near else far_ttl_sec)
            reason = None

            if ttl and age > ttl:
                reason = f"age>{ttl}s"
            elif cancel_offladder and pr not in allowed and age > offladder_grace:
                reason = "off-ladder"

            if reason:
                if cancel_order(symbol, int(o.get("orderId"))):
                    canceled += 1
                    log(f"[CLEANUP] {symbol} canceled {o.get('side')} {o.get('type')} id={o.get('orderId')} price={pr} age={age}s reason={reason}")
                    _log_order_lifetime(
                        symbol,
                        o,
                        now_price=now_price,
                        age_sec=age,
                        ttl_sec=ttl,
                        cancel_reason=str(reason),
                    )
        except SUPERVISOR_OPERATION_ERRORS as e:
            log(f"[CLEANUP] {symbol} skip: {e}")

    log(f"[CLEANUP-SUM] {symbol} reviewed={reviewed} canceled={canceled}")
    return {"reviewed": reviewed, "canceled": canceled}

# ===========================
# Ladder scheduler
# ===========================

# ===========================
# Smart Rolling (brief)
# ===========================

def _atomic_reanchor_cap(symbol: str) -> Decimal:
    values: list[Decimal] = []
    for variable in (
        "BOT_OPERATOR_CAP_PER_ORDER_USDT",
        "BOT_CAP_PER_ORDER",
        f"RISK_SYMBOL_CAP_{symbol.upper()}",
    ):
        raw = os.getenv(variable, "").strip()
        if not raw:
            continue
        value = Decimal(raw)
        if not value.is_finite() or value <= 0:
            raise ValueError(f"{variable} must be finite and positive")
        values.append(value)
    if not values:
        raise RuntimeError("atomic re-anchor has no hard per-order CAP")
    return min(values)


def _atomic_reanchor_buy(
    symbol: str,
    order: Mapping[str, object],
    target_price: Decimal,
    *,
    testnet: bool,
) -> Dict[str, Any] | None:
    """Replace one untouched BUY through the durable cancel-replace boundary."""
    path = os.getenv("BOT_ORDER_JOURNAL", "").strip()
    if not path:
        raise RuntimeError("atomic re-anchor requires BOT_ORDER_JOURNAL")
    journal = OrderJournal(
        path,
        venue="testnet" if testnet else "mainnet",
    )

    def get_by_id(query_symbol: str, order_id: int):
        return TM._signed_get(
            "/api/v3/order",
            {"symbol": query_symbol, "orderId": int(order_id)},
        )

    def get_by_client(query_symbol: str, client_id: str):
        try:
            return TM._signed_get(
                "/api/v3/order",
                {
                    "symbol": query_symbol,
                    "origClientOrderId": client_id,
                },
            )
        except SUPERVISOR_OPERATION_ERRORS as exc:
            if _exchange_order_absent(exc):
                return None
            raise

    trace = LatencyTrace(symbol, "cancel-replace")
    trace.mark("risk_decision")
    result = atomic_cancel_replace_buy(
        symbol,
        order,
        target_price,
        maximum_notional=_atomic_reanchor_cap(symbol),
        dependencies=CancelReplaceDependencies(
            journal=lambda: journal,
            signed_request=_canonical_signed_request,
            get_order_by_id=get_by_id,
            get_order_by_client_id=get_by_client,
            halt=lambda reason, **metadata: create_manual_halt(
                reason,
                metadata=metadata,
            ),
            logger=log,
        ),
        latency_trace=trace,
    )
    try:
        trace.append(
            os.getenv(
                "BOT_LATENCY_TRACE_LOG",
                str(Path("logs") / "latency_trace.ndjson"),
            )
        )
    except OSError as exc:
        dbg(f"[LATENCY] trace unavailable={type(exc).__name__}")
    return result


def smart_rolling(symbol: str,
                  now_price: float,
                  ladder: List[float],
                  args: argparse.Namespace,
                  *,
                  tick_size: object,
                  prediction_apply_approved: bool = False) -> Dict[str, Any]:
    """Plan bounded re-anchors while keeping SHADOW strictly non-mutating."""
    # Open-order visibility is an execution prerequisite. Propagate failures
    # instead of assuming an empty book and potentially duplicating orders.
    open_orders = list_open_orders(symbol)
    configured_mode = str(getattr(args, "reanchor_mode", "OFF")).upper()
    reanchor_mode = configured_mode
    if configured_mode == "APPLY" and not prediction_apply_approved:
        reanchor_mode = "SHADOW"
        log(
            f"[REANCHOR-GATE] {symbol} APPLY blocked; "
            "prediction evidence remains SHADOW"
        )
    if reanchor_mode == "OFF":
        return {
            "kept": len(open_orders),
            "cancel": {"ttl": 0, "atr": 0, "reanchor": 0, "shadow": 0},
            "replacement_prices": [],
            "proposals": [],
            "effective_mode": "OFF",
            "apply_gate_approved": False,
        }
    try:
        planned = plan_buy_reanchors(
            open_orders,
            ladder,
            now_price=now_price,
            tick_size=tick_size,
            now_ms=int(time.time() * 1000),
            min_age_sec=int(args.reanchor_min_age_sec),
            trigger_pct=args.reanchor_trigger_pct,
            max_step_pct=args.reanchor_max_step_pct,
            max_per_cycle=int(args.reanchor_max_per_cycle),
            max_market_gap_pct=getattr(
                args, "reanchor_max_market_gap_pct", Decimal("0.0015")
            ),
        )
    except (ArithmeticError, TypeError, ValueError) as exc:
        log(f"[REANCHOR-BLOCK] {symbol} invalid planning input: {exc}")
        return {
            "kept": len(open_orders),
            "cancel": {"ttl": 0, "atr": 0, "reanchor": 0, "shadow": 0},
            "replacement_prices": [],
            "proposals": [],
            "effective_mode": reanchor_mode,
            "apply_gate_approved": bool(prediction_apply_approved),
        }

    proposals = [
        {
            "order_id": candidate.order_id,
            "old_price": str(candidate.old_price),
            "target_price": str(candidate.target_price),
            "age_sec": candidate.age_sec,
        }
        for candidate in planned
    ]

    if reanchor_mode == "SHADOW":
        for candidate in planned:
            log(
                f"[REANCHOR-SHADOW] {symbol} BUY id={candidate.order_id} "
                f"old={candidate.old_price} target={candidate.target_price} "
                f"age={candidate.age_sec}s"
            )
        return {
            "kept": len(open_orders),
            "cancel": {
                "ttl": 0,
                "atr": 0,
                "reanchor": 0,
                "shadow": len(planned),
            },
            "replacement_prices": [],
            "proposals": proposals,
            "effective_mode": "SHADOW",
            "apply_gate_approved": bool(prediction_apply_approved),
        }

    canceled = 0
    replacements: List[float] = []
    atomic_mode = os.getenv(
        "BOT_REANCHOR_CANCEL_REPLACE",
        "1",
    ).lower() in ("1", "true", "yes")
    by_id: Dict[int, Mapping[str, object]] = {}
    for order in open_orders:
        try:
            order_id = int(order.get("orderId") or 0)
        except (TypeError, ValueError):
            continue
        if order_id > 0:
            by_id[order_id] = order
    if planned and atomic_mode and not _stop_child(
        symbol,
        "atomic adaptive BUY re-anchor",
    ):
        log(
            f"[REANCHOR-BLOCK] {symbol} worker did not stop; "
            "cancelReplace suppressed"
        )
        return {
            "kept": len(open_orders),
            "cancel": {
                "ttl": 0,
                "atr": 0,
                "reanchor": 0,
                "shadow": 0,
            },
            "replacement_prices": [],
            "proposals": proposals,
            "effective_mode": "APPLY",
            "apply_gate_approved": True,
        }
    for candidate in planned:
        order = by_id.get(candidate.order_id)
        if atomic_mode:
            if order is None:
                continue
            try:
                replacement = _atomic_reanchor_buy(
                    symbol,
                    order,
                    candidate.target_price,
                    testnet=bool(getattr(args, "testnet", False)),
                )
            except SUPERVISOR_OPERATION_ERRORS as exc:
                log(
                    f"[REANCHOR-BLOCK] {symbol} cancelReplace "
                    f"error={type(exc).__name__}"
                )
                continue
            if not replacement:
                continue
        elif not cancel_order(symbol, candidate.order_id):
            continue
        canceled += 1
        replacements.append(_analytics_float(candidate.target_price))
        log(
            f"[REANCHOR] {symbol} "
            f"{'atomically replaced' if atomic_mode else 'canceled'} "
            f"BUY id={candidate.order_id} "
            f"old={candidate.old_price} target={candidate.target_price} "
            f"age={candidate.age_sec}s"
        )
        if order is not None:
            _log_order_lifetime(
                symbol,
                order,
                now_price=now_price,
                age_sec=candidate.age_sec,
                ttl_sec=int(args.reanchor_min_age_sec),
                cancel_reason="adaptive-reanchor",
            )
    if (
        canceled
        and not atomic_mode
        and not _stop_child(symbol, "adaptive BUY re-anchor")
    ):
        replacements.clear()
        log(
            f"[REANCHOR-BLOCK] {symbol} worker did not stop; "
            "replacement deferred"
        )
    return {
        "kept": max(0, len(open_orders) - canceled),
        "cancel": {"ttl": 0, "atr": 0, "reanchor": canceled, "shadow": 0},
        "replacement_prices": replacements,
        "proposals": proposals,
        "effective_mode": "APPLY",
        "apply_gate_approved": True,
    }


def _publish_reanchor_runtime(
    symbol: str,
    result: Mapping[str, object],
    args: argparse.Namespace,
) -> None:
    """Expose non-secret adaptive-order telemetry to the dashboard."""
    cancel = result.get("cancel")
    cancel_counts = cancel if isinstance(cancel, Mapping) else {}
    shadow_count = max(0, int(cancel_counts.get("shadow", 0) or 0))
    apply_count = max(0, int(cancel_counts.get("reanchor", 0) or 0))
    runtime = _AI_RUNTIME_STATUS.setdefault("reanchor", {})
    if not isinstance(runtime, dict):
        runtime = {}
        _AI_RUNTIME_STATUS["reanchor"] = runtime
    totals = runtime.setdefault(
        "totals", {"shadow_candidates": 0, "apply_cancels": 0}
    )
    if not isinstance(totals, dict):
        totals = {"shadow_candidates": 0, "apply_cancels": 0}
        runtime["totals"] = totals
    totals["shadow_candidates"] = max(
        0, int(totals.get("shadow_candidates", 0) or 0)
    ) + shadow_count
    totals["apply_cancels"] = max(
        0, int(totals.get("apply_cancels", 0) or 0)
    ) + apply_count
    proposals = result.get("proposals")
    safe_proposals = proposals if isinstance(proposals, list) else []
    symbols = runtime.setdefault("symbols", {})
    if not isinstance(symbols, dict):
        symbols = {}
        runtime["symbols"] = symbols
    symbols[symbol] = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "kept": max(0, int(result.get("kept", 0) or 0)),
        "shadow_candidates": shadow_count,
        "apply_cancels": apply_count,
        "proposals": safe_proposals,
    }
    runtime.update({
        "configured_mode": str(
            getattr(args, "reanchor_mode", "OFF")
        ).upper(),
        "mode": str(
            result.get("effective_mode")
            or getattr(args, "reanchor_mode", "OFF")
        ).upper(),
        "apply_gate_approved": bool(
            result.get("apply_gate_approved", False)
        ),
        "min_age_sec": int(getattr(args, "reanchor_min_age_sec", 120)),
        "trigger_pct": str(getattr(args, "reanchor_trigger_pct", "0.0025")),
        "max_step_pct": str(getattr(args, "reanchor_max_step_pct", "0.005")),
        "max_market_gap_pct": str(
            getattr(args, "reanchor_max_market_gap_pct", "0.0015")
        ),
        "max_per_cycle": int(getattr(args, "reanchor_max_per_cycle", 1)),
    })
    _publish_ai_runtime_status()


def _prediction_reanchor_gate(symbol: str) -> dict[str, object]:
    """Return the current immutable counterfactual approval evidence."""
    now_monotonic = time.monotonic()
    cached = _PREDICTION_GATE_CACHE.get(symbol)
    if cached is not None and now_monotonic - cached[0] < 60:
        return cached[1]
    if _PREDICTION_SHADOW is None:
        result = {
            "approved": False,
            "mode": "SHADOW",
            "reasons": ["prediction journal is unavailable"],
        }
    else:
        try:
            samples = _PREDICTION_SHADOW.resolved_samples(
                symbol, kind="REANCHOR"
            )
            result = walk_forward_prediction_report(samples)["gate"]
        except (OSError, sqlite3.Error, TypeError, ValueError):
            result = {
                "approved": False,
                "mode": "SHADOW",
                "reasons": ["prediction gate evidence is unreadable"],
            }
    _PREDICTION_GATE_CACHE[symbol] = (now_monotonic, result)
    return result


def _strategy_control_gate(symbol: str) -> dict[str, object]:
    """Return look-ahead-safe approval evidence for strategy controls."""
    now_monotonic = time.monotonic()
    cached = _STRATEGY_CONTROL_GATE_CACHE.get(symbol)
    if cached is not None and now_monotonic - cached[0] < 60:
        return cached[1]
    if _PREDICTION_SHADOW is None:
        result = {
            "approved": False,
            "mode": "SHADOW",
            "reasons": ["prediction journal is unavailable"],
        }
    else:
        try:
            samples = _PREDICTION_SHADOW.resolved_samples(
                symbol, kind="STRATEGY"
            )
            result = walk_forward_prediction_report(samples)["gate"]
        except (OSError, sqlite3.Error, TypeError, ValueError):
            result = {
                "approved": False,
                "mode": "SHADOW",
                "reasons": ["strategy gate evidence is unreadable"],
            }
    _STRATEGY_CONTROL_GATE_CACHE[symbol] = (now_monotonic, result)
    return result


def _strategy_controls_apply_allowed(
    symbol: str,
) -> tuple[bool, dict[str, object]]:
    """Require operator approval and statistical evidence for APPLY."""
    gate = _strategy_control_gate(symbol)
    operator_approved = (
        os.getenv("BOT_STRATEGY_CONTROLS_APPROVED", "").strip().upper()
        == "YES"
    )
    return operator_approved and bool(gate.get("approved")), gate


def _prediction_plan(
    entry_price: object,
    *,
    take_profit_pct: object,
    stop_pct: object,
    notional_quote: Decimal,
    fee_pct: Decimal,
    slippage_pct: Decimal,
) -> TradePlan:
    """Create one exact long-only counterfactual plan."""
    entry = _finite_decimal(entry_price, name="prediction entry")
    take_profit = _finite_decimal(
        take_profit_pct, name="prediction take profit"
    )
    stop = _finite_decimal(stop_pct, name="prediction stop")
    return TradePlan(
        entry_price=entry,
        take_profit_price=entry * (Decimal("1") + take_profit),
        stop_price=entry * (Decimal("1") + stop),
        notional_quote=notional_quote,
        fee_pct=fee_pct,
        slippage_pct=slippage_pct,
    )


def _record_prediction_shadow(
    symbol: str,
    *,
    now_price: object,
    ladder: List[float],
    take_profit_pct: object,
    stop_pct: object,
    deterministic_mode: str,
    rolling: Mapping[str, object],
) -> None:
    """Persist look-ahead-safe forecasts without changing an order decision."""
    if _PREDICTION_SHADOW is None:
        return
    interval = max(
        10,
        int(os.getenv("PREDICTION_SHADOW_INTERVAL_SEC", "60") or "60"),
    )
    now_monotonic = time.monotonic()
    last_attempt = _PREDICTION_LAST_ATTEMPT.get(symbol)
    if (
        last_attempt is not None
        and now_monotonic - last_attempt < interval
    ):
        return
    # Rate-limit failed public reads as well as successful snapshots.
    _PREDICTION_LAST_ATTEMPT[symbol] = now_monotonic
    cap = _finite_decimal(
        os.getenv("BOT_CAP_PER_ORDER", "0") or "0",
        name="BOT_CAP_PER_ORDER",
    )
    if cap <= 0:
        return
    fee = _finite_decimal(
        os.getenv("PREDICTION_FEE_PCT", "0.00075") or "0.00075",
        name="PREDICTION_FEE_PCT",
    )
    slippage = _finite_decimal(
        os.getenv("PREDICTION_SLIPPAGE_PCT", "0.0005") or "0.0005",
        name="PREDICTION_SLIPPAGE_PCT",
    )
    as_of_ms = int(TM._timestamp_ms())
    klines = TM.get_klines(symbol, "1m", limit=1000)
    preliminary, _ = build_prediction_features(klines, as_of_ms=as_of_ms)
    snapshot_ms = preliminary.snapshot_ts_ms
    depth_raw = TM._public_get(
        "/api/v3/depth", {"symbol": symbol.upper(), "limit": 20}
    )
    depth = depth_raw if isinstance(depth_raw, Mapping) else None
    trades_raw = TM._public_get(
        "/api/v3/aggTrades",
        {
            "symbol": symbol.upper(),
            "startTime": snapshot_ms - 60_000,
            "endTime": snapshot_ms,
            "limit": 1000,
        },
    )
    trades = trades_raw if isinstance(trades_raw, list) else []
    flow, flow_available = trade_flow_from_agg_trades(
        [row for row in trades if isinstance(row, Mapping)],
        start_ms=snapshot_ms - 60_000,
        end_ms=snapshot_ms,
    )
    # A full Binance page may have truncated a high-activity minute. Keep the
    # value for diagnostics but never claim that such trade flow is complete.
    flow_available = flow_available and len(trades) < 1000
    panic_active, panic_hits = _prediction_panic_state(symbol)
    features, bars = build_prediction_features(
        klines,
        as_of_ms=as_of_ms,
        depth=depth,
        trade_flow_imbalance=flow,
        trade_flow_available=flow_available,
        executor_panic_active=panic_active,
        executor_panic_hits=panic_hits,
    )
    settled = _PREDICTION_SHADOW.settle(
        symbol, bars, as_of_ms=features.snapshot_ts_ms
    )
    history = _PREDICTION_SHADOW.resolved_samples(
        symbol, before_ts_ms=features.snapshot_ts_ms, kind="STRATEGY"
    )
    market = _finite_decimal(now_price, name="prediction market price")
    buy_levels = sorted(
        {
            _finite_decimal(level, name="prediction ladder level")
            for level in ladder
            if _finite_decimal(level, name="prediction ladder level") < market
        },
        reverse=True,
    )
    if buy_levels:
        strategy_plan = _prediction_plan(
            buy_levels[0],
            take_profit_pct=take_profit_pct,
            stop_pct=stop_pct,
            notional_quote=cap,
            fee_pct=fee,
            slippage_pct=slippage,
        )
        predictions = predict_distribution(features, strategy_plan, history)
        _PREDICTION_SHADOW.record(
            kind="STRATEGY",
            symbol=symbol,
            features=features,
            plan=strategy_plan,
            predictions=predictions,
            algorithm_decision=(
                f"mode={deterministic_mode};buy={strategy_plan.entry_price};"
                f"panic={panic_active};reason=current-ladder"
            ),
        )

    proposals_raw = rolling.get("proposals")
    proposals = proposals_raw if isinstance(proposals_raw, list) else []
    reanchor_history = _PREDICTION_SHADOW.resolved_samples(
        symbol, before_ts_ms=features.snapshot_ts_ms, kind="REANCHOR"
    )
    for proposal in proposals:
        if not isinstance(proposal, Mapping):
            continue
        old_plan = _prediction_plan(
            proposal.get("old_price"),
            take_profit_pct=take_profit_pct,
            stop_pct=stop_pct,
            notional_quote=cap,
            fee_pct=fee,
            slippage_pct=slippage,
        )
        proposed_plan = _prediction_plan(
            proposal.get("target_price"),
            take_profit_pct=take_profit_pct,
            stop_pct=stop_pct,
            notional_quote=cap,
            fee_pct=fee,
            slippage_pct=slippage,
        )
        predictions = predict_distribution(
            features, proposed_plan, reanchor_history
        )
        order_fingerprint = hashlib.sha256(
            str(proposal.get("order_id") or "").encode("utf-8")
        ).hexdigest()[:12]
        _PREDICTION_SHADOW.record(
            kind="REANCHOR",
            symbol=symbol,
            features=features,
            plan=proposed_plan,
            baseline_plan=old_plan,
            predictions=predictions,
            algorithm_decision=(
                f"order={order_fingerprint};old={old_plan.entry_price};"
                f"target={proposed_plan.entry_price};"
                f"panic={panic_active};reason=adaptive-reanchor"
            ),
        )

    reanchor_samples = _PREDICTION_SHADOW.resolved_samples(
        symbol, before_ts_ms=features.snapshot_ts_ms, kind="REANCHOR"
    )
    walk_forward = walk_forward_prediction_report(reanchor_samples)
    gate = walk_forward["gate"]
    _PREDICTION_GATE_CACHE[symbol] = (time.monotonic(), gate)
    strategy_samples = _PREDICTION_SHADOW.resolved_samples(
        symbol, before_ts_ms=features.snapshot_ts_ms, kind="STRATEGY"
    )
    strategy_walk_forward = walk_forward_prediction_report(strategy_samples)
    strategy_gate = strategy_walk_forward["gate"]
    _STRATEGY_CONTROL_GATE_CACHE[symbol] = (
        time.monotonic(),
        strategy_gate,
    )
    summary = _PREDICTION_SHADOW.summary(symbol)
    runtime = _AI_RUNTIME_STATUS.setdefault("prediction", {})
    if not isinstance(runtime, dict):
        runtime = {}
        _AI_RUNTIME_STATUS["prediction"] = runtime
    symbols = runtime.setdefault("symbols", {})
    if not isinstance(symbols, dict):
        symbols = {}
        runtime["symbols"] = symbols
    symbols[symbol] = {
        **summary,
        "snapshot_ts_ms": features.snapshot_ts_ms,
        "regime": features.regime,
        "executor_panic_active": features.executor_panic_active,
        "executor_panic_hits": features.executor_panic_hits,
        "settled_this_cycle": settled,
        "gate": gate,
        "strategy_control_gate": strategy_gate,
        "walk_forward": {
            "method": walk_forward["method"],
            "lookahead": walk_forward["lookahead"],
            "evaluated_samples": len(walk_forward["evaluated"]),
        },
    }
    runtime.update({
        "mode": "SHADOW",
        "horizons_min": [1, 5, 15],
        "can_change_orders": False,
        "trade_flow_available": features.trade_flow_available,
        "orderbook_available": features.orderbook_available,
        "last_error": None,
    })
    _publish_ai_runtime_status()

# ===========================
# ATR and automatic threshold adapter
# ===========================

def _klines(symbol: str, interval: str, limit: int = 30):
    return TM.get_klines(symbol, interval, limit=limit)

def _atr_pct(symbol: str, interval: str = '5m', length: int = 20) -> Tuple[float, float]:
    try:
        kl = _klines(symbol, interval, limit=length+2)
        if not kl or len(kl) < length+1:
            return 0.0, 0.0
        prev_close = _analytics_float(kl[0][4])
        trs = []
        for row in kl[1:]:
            high = _analytics_float(row[2]); low = _analytics_float(row[3]); close = _analytics_float(row[4])
            tr = max(high-low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
            prev_close = close
        atr = sum(trs[-length:]) / _analytics_float(length)
        last_close = _analytics_float(kl[-1][4])
        return atr, (atr / last_close if last_close > 0 else 0.0)
    except SUPERVISOR_OPERATION_ERRORS as e:
        log(f"[ATR] failed: {e}")
        return 0.0, 0.0

# ===========================
# Market direction detector (UP/DOWN/FLAT)
# ===========================

_DIR_STATE: Dict[str, Dict[str, Any]] = {}
_REGIME_HYSTERESIS: Dict[str, RegimeHysteresis] = {}
_PARAM_HYSTERESIS: Dict[str, Dict[str, NumericHysteresis]] = {}
_EXECUTION_REGIMES: Dict[str, RegimeExecutionStateMachine] = {}
_COMMISSION_CACHE: Dict[str, tuple[float, CommissionSchedule]] = {}


def _control_mode(name: str, default: str = "SHADOW") -> str:
    """Return OFF/SHADOW/APPLY and fail closed on a damaged setting."""
    value = str(os.getenv(name, default) or default).strip().upper()
    if value not in {"OFF", "SHADOW", "APPLY"}:
        raise ValueError(f"{name} must be OFF, SHADOW or APPLY")
    return value


def _commission_schedule(symbol: str) -> CommissionSchedule:
    """Read and briefly cache authoritative per-symbol account commissions."""
    ttl = max(
        1,
        int(os.getenv("BOT_COMMISSION_CACHE_SEC", "300") or "300"),
    )
    now = time.monotonic()
    cached = _COMMISSION_CACHE.get(symbol)
    if cached is not None and now - cached[0] <= ttl:
        return cached[1]
    payload = TM._signed_get(
        "/api/v3/account/commission",
        {"symbol": symbol.upper()},
    )
    if not isinstance(payload, Mapping):
        raise RuntimeError("Binance commission schedule is unavailable")
    schedule = authoritative_commission_schedule(payload)
    _COMMISSION_CACHE[symbol] = (now, schedule)
    return schedule


def _managed_inventory_exposure(
    symbol: str,
    price: object,
) -> Decimal:
    """Value only journal-attributed bot inventory, excluding legacy SOL."""
    snapshot = _runtime_order_journal_snapshot()
    if snapshot.get("available") is not True:
        raise RuntimeError("managed inventory journal is unavailable")
    quantity = Decimal("0")
    for item in snapshot.get("managed_buys", []):
        if (
            isinstance(item, Mapping)
            and str(item.get("symbol") or "").upper() == symbol.upper()
        ):
            quantity += _finite_decimal(
                item.get("quantity", "0"),
                name="managed inventory quantity",
            )
    return quantity * _finite_decimal(price, name="managed inventory price")


def _managed_inventory_hard_cap(symbol: str) -> Decimal:
    """Require a dedicated managed-inventory limit, never portfolio fallback."""
    safe_symbol = symbol.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,20}", safe_symbol):
        raise ValueError("managed inventory symbol is invalid")
    symbol_name = f"RISK_MANAGED_INVENTORY_HARD_CAP_{safe_symbol}"
    raw = os.getenv(symbol_name)
    source = symbol_name
    if raw is None or not raw.strip():
        source = "RISK_MANAGED_INVENTORY_HARD_CAP_USDT"
        raw = os.getenv(source)
    if raw is None or not raw.strip():
        raise ValueError(
            f"{symbol_name} or {source} must be explicitly configured"
        )
    cap = _finite_decimal(raw, name=source)
    if cap <= 0:
        raise ValueError(f"{source} must be positive")
    return cap


def _strategy_child_env(
    *,
    commission_schedule: CommissionSchedule | None,
    required_edge: Decimal | None,
    expectancy_mode: str,
    maker_mode: str,
) -> Dict[str, str]:
    """Build child controls without allowing SHADOW evidence to mutate plans."""
    child_env: Dict[str, str] = {}
    if commission_schedule is not None:
        child_env.update({
            # Authoritative rates improve exact accounting in every mode. Only
            # BOT_REQUIRED_EDGE_PCT is an execution-changing control.
            "BOT_BUY_FEE_PCT": format(
                commission_schedule.maker_buy, "f"
            ),
            "BOT_SELL_FEE_PCT": format(
                commission_schedule.maker_sell, "f"
            ),
            "BOT_FEE_PCT": format(
                max(
                    commission_schedule.maker_buy,
                    commission_schedule.maker_sell,
                ),
                "f",
            ),
        })
    if required_edge is not None and str(expectancy_mode).upper() == "APPLY":
        child_env["BOT_REQUIRED_EDGE_PCT"] = format(required_edge, "f")
    if str(maker_mode).upper() == "APPLY":
        child_env.update({
            "BUY_LIMIT_MAKER": "1",
            "SELL_LIMIT_MAKER": "1",
        })
    return child_env


def _child_process_env(
    extra_env: Mapping[str, object] | None,
) -> Dict[str, str]:
    """Build a child environment without inheriting a stale execution edge."""
    child_env = os.environ.copy()
    child_env.pop("BOT_REQUIRED_EDGE_PCT", None)
    if extra_env:
        child_env.update({key: str(value) for key, value in extra_env.items()})
    return child_env


def _infer_market_mode(symbol: str, *, interval: str = "30m", ema_fast_len: int = 20,
                       ema_slow_len: int = 50, eps: float = 0.0005, slope_min: float = 0.0002,
                       adx_min: float = 16.0, hyst_bars: int = 5, confirm_bars: int = 3,
                       do_log: bool = True) -> Tuple[str, Dict[str, float]]:
    need = max(ema_slow_len + 5, 100)
    kl = _klines(symbol, interval, limit=need)
    if not kl or len(kl) < ema_slow_len + 2:
        return "FLAT", {"ema_fast": 0, "ema_slow": 0, "slope": 0, "adx": 0, "candidate": "FLAT"}

    closes = [_analytics_float(r[4]) for r in kl]
    ema_fast = _ema_series(closes, ema_fast_len)
    ema_slow = _ema_series(closes, ema_slow_len)
    ef = _analytics_float(ema_fast[-1]); es = _analytics_float(ema_slow[-1])
    last_px = _analytics_float(closes[-1])

    step_back = min(confirm_bars, len(ema_fast) - 1)
    slope = (ema_fast[-1] - ema_fast[-1 - step_back]) / max(step_back, 1) / max(last_px, 1e-12)
    adx = _adx_from_klines(kl, length=14)

    up_cond   = (ef > es * (1.0 + eps)) and (slope >=  slope_min) and (adx >= adx_min)
    down_cond = (ef < es * (1.0 - eps)) and (slope <= -slope_min) and (adx >= adx_min)
    cand = "UP" if up_cond else ("DOWN" if down_cond else "FLAT")

    # One state per symbol prevents noisy VWAP/ADX signals from flipping the
    # mode back and forth between adjacent supervisor iterations.
    hysteresis = _REGIME_HYSTERESIS.setdefault(
        symbol,
        RegimeHysteresis("FLAT", min_hold_sec=_analytics_float(os.getenv("BOT_REGIME_MIN_HOLD_SEC", "300")),
                         confirmations=max(1, confirm_bars)),
    )
    mode = hysteresis.update(cand)
    _DIR_STATE[symbol] = {"mode": mode, "streak": 0, "last_cand": cand}

    if do_log:
        log(f"[DIR] {symbol} mode={mode} cand={cand} ema{ema_fast_len}={ef:.4f} ema{ema_slow_len}={es:.4f} slope={slope:.5f} adx={adx:.2f}")
    return mode, {"ema_fast": ef, "ema_slow": es, "slope": slope, "adx": adx, "candidate": cand}

# ===========================
# Position guardian
# ===========================

def _in_flatten_window(now_local: datetime, hhmm: str, t_minus_sec: int) -> bool:
    try:
        hh, mm = [int(x) for x in hhmm.split(":")]
    except (TypeError, ValueError):
        return False
    target = now_local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if now_local > target:
        target = target + timedelta(days=1)
    return (target - now_local).total_seconds() <= max(0, int(t_minus_sec))

def _net_position_base(symbol: str) -> Decimal:
    base, _ = symbol_assets(symbol)
    bals = get_balances_full()
    b = bals.get(base, {"free": Decimal("0"), "locked": Decimal("0")})
    return _finite_decimal(b.get("free", "0"), name="free balance") + _finite_decimal(
        b.get("locked", "0"), name="locked balance"
    )

def _pos_limits(symbol: str, args: argparse.Namespace) -> Tuple[Optional[Decimal], Optional[Decimal]]:
    mb = args.pos_max_base_map.get(symbol) if args.pos_max_base_map else None
    mu = args.pos_max_usdt_map.get(symbol) if args.pos_max_usdt_map else None
    return (
        _finite_decimal(mb, name="position base limit") if mb is not None else None,
        _finite_decimal(mu, name="position USDT limit") if mu is not None else None,
    )

def _prune_to_sells_only(now_price: float, ladder: List[float]) -> List[float]:
    _, sells = split_ladder(now_price, ladder)
    return sells

def _ensure_min_notional_qty(
    symbol: str,
    qty: object,
    price: object,
    step: object,
    min_qty: object,
    min_notional: object,
) -> Optional[Decimal]:
    del symbol
    qty_d = round_step(_finite_decimal(qty, name="quantity"), step, "floor")
    price_d = _finite_decimal(price, name="price")
    step_d = _finite_decimal(step, name="quantity step")
    min_qty_d = _finite_decimal(min_qty, name="minimum quantity")
    min_notional_d = _finite_decimal(min_notional, name="minimum notional")
    if qty_d <= 0 or price_d <= 0 or step_d <= 0:
        return None
    if qty_d < min_qty_d:
        qty_d = round_step(min_qty_d, step_d, "ceil")
    if qty_d * price_d < min_notional_d:
        qty_d = round_step(min_notional_d / price_d, step_d, "ceil")
        if qty_d * price_d < min_notional_d:
            return None
    return qty_d if qty_d > 0 else None

def position_guard_and_maybe_flatten(symbol: str, now_price: float, atr_abs: float,
                                     args: argparse.Namespace, filters: Dict[str, object]) -> str:
    """Enforce position limits and use flattening only under explicit policy."""
    if not args.pos_guard_enable and not args.flatten_enable:
        return "normal"

    max_base, max_usdt = _pos_limits(symbol, args)
    net_base = _net_position_base(symbol)
    now_price_d = _finite_decimal(now_price, name="market price")
    atr_abs_d = _finite_decimal(atr_abs, name="ATR")
    net_usdt = net_base * now_price_d

    hard = False; warn = False
    warn_thr_base = warn_thr_usdt = None

    if max_base is not None:
        hard = hard or (abs(net_base) > max_base)
        warn_thr_base = _finite_decimal(args.pos_warn_pct, name="warning ratio") * max_base
        warn = warn or (abs(net_base) > warn_thr_base)
    if max_usdt is not None:
        hard = hard or (abs(net_usdt) > max_usdt)
        warn_thr_usdt = _finite_decimal(args.pos_warn_pct, name="warning ratio") * max_usdt
        warn = warn or (abs(net_usdt) > warn_thr_usdt)

    now_local = datetime.now()
    in_flat = args.flatten_enable and _in_flatten_window(now_local, args.flatten_at, args.flatten_t_minus_sec)

    if (in_flat and not hard
            and bool(getattr(args, "flatten_avoid_loss", 0))
            and not bool(getattr(args, "flatten_force", 0))):
        cache_ttl = int(getattr(args, "flatten_avg_cache_ttl", 45))
        lookback = int(getattr(args, "flatten_avg_lookback", 1000))
        edge_pct = max(
            Decimal("0"),
            _finite_decimal(getattr(args, "flatten_min_edge_pct", 0), name="flatten edge"),
        )
        avg_px = avg_entry_price(symbol, cache_ttl=cache_ttl, lookback=lookback)
        if avg_px is not None:
            avg_px_d = _finite_decimal(avg_px, name="average entry price")
            guard_price = avg_px_d * (Decimal("1") + edge_pct)
            if now_price_d < guard_price:
                log(
                    f"[FLAT-GUARD] {symbol} skip flatten: avg≈{avg_px_d:.6f} guard≈{guard_price:.6f} now≈{now_price_d:.6f}"
                )
                in_flat = False

    if hard or in_flat:
        try:
            base, _ = symbol_assets(symbol)
            step = filters.get("stepSizeExact", filters["stepSize"])
            min_qty = filters.get("minQtyExact", filters["minQty"])
            min_notional = filters.get("minNotionalExact", filters["minNotional"])
            tick = filters.get("tickSizeExact", filters["tickSize"])

            target_base = Decimal("0") if (in_flat or args.pos_action_on_hard in ("flatten", "reduce_then_flatten"))\
                          else (warn_thr_base or Decimal("0")) * (1 if net_base >= 0 else -1)
            need_total = max(Decimal("0"), abs(net_base - target_base))

            bals_full = get_balances_full()
            free_base = _finite_decimal(
                bals_full.get(base, {}).get("free", "0"), name="free base balance"
            )
            sellable = max(Decimal("0"), free_base)

            if net_base <= 0:
                log(f"[POS] {symbol} net<=0 ({net_base:.6f}) -> nothing to flatten via SELL on spot")
                return "reduce_only" if warn else "normal"

            if sellable <= 0:
                log(f"[POS] {symbol} nothing free to sell (free={free_base:.6f}, locked may exist) -> reduce_only")
                return "reduce_only"

            left = min(need_total, sellable)
            if left <= 0:
                return "reduce_only" if warn else "normal"

            slice_cnt = max(1, int(args.flatten_slices))
            slice_pct = min(
                Decimal("1"),
                max(Decimal("0.05"), _finite_decimal(args.flatten_slice_pct, name="slice ratio")),
            )
            per_slice = max(left * slice_pct, left / slice_cnt)

            offset = min(
                Decimal("3"),
                max(Decimal("0"), _finite_decimal(args.flatten_limit_offset_atr, name="ATR offset")),
            )
            price = round_step(now_price_d + offset * atr_abs_d, tick, "ceil")

            tries = 0
            while left > 0 and tries < slice_cnt:
                qty = min(left, per_slice)
                qty = _ensure_min_notional_qty(symbol, qty, price, step, min_qty, min_notional)
                if qty is None or qty <= 0:
                    break
                ok = place_limit_order(symbol, "SELL", qty, price, filters=filters)
                if not ok and args.flatten_market_failover:
                    qty_m = _ensure_min_notional_qty(symbol, qty, now_price, step, min_qty, min_notional)
                    if qty_m:
                        place_market_order(symbol, "SELL", qty_m, ref_price=now_price, filters=filters)
                left -= qty
                tries += 1

            return "flattening"
        except SUPERVISOR_OPERATION_ERRORS as e:
            log(f"[FLAT-ERR] {symbol} error_type={e.__class__.__name__} detail={e}")
            return "reduce_only"

    if warn:
        log(f"[POS] {symbol} net≈{net_base:.6f} base / {net_usdt:.2f} USDT -> reduce-only (warn {args.pos_warn_pct*100:.1f}%)")
        return "reduce_only"

    return "normal"

# ===========================
# Child runner lifecycle
# ===========================

def _schedule_child_restart(
    symbol: str,
    return_code: int,
    runtime_sec: float,
    *,
    now: Optional[float] = None,
) -> float:
    """Handle schedule child restart."""
    return schedule_child_restart(
        symbol,
        return_code,
        runtime_sec,
        failures=_CHILD_FAILURES,
        restart_after=_CHILD_RESTART_AFTER,
        now=now,
    )

def run_child(symbol: str, ladder: List[float], args: argparse.Namespace,
              extra_env: Optional[Dict[str, str]] = None,
              tp1: Optional[float] = None, tp2: Optional[float] = None) -> None:
    """Handle run child."""
    # Reuse a known live process instead of duplicating it; restart a crashed
    # process with exponential backoff.
    now = time.time()
    _child = _CHILD_PROCS.get(symbol)
    if _child is not None:
        if _child.poll() is None:
            return
        return_code = _child.wait(timeout=0)
        runtime = max(0.0, now - _CHILD_STARTED_AT.pop(symbol, now))
        _CHILD_PROCS.pop(symbol, None)
        delay = _schedule_child_restart(symbol, return_code, runtime, now=now)
        if delay > 0:
            log(
                f"[CHILD-BACKOFF] {symbol} exit={return_code} runtime={runtime:.1f}s "
                f"failures={_CHILD_FAILURES[symbol]} retry_in={delay:.1f}s"
            )
            return

    restart_after = _CHILD_RESTART_AFTER.get(symbol, 0.0)
    if now < restart_after:
        return

    # The supervisor passes a computed trading plan to the worker. The worker
    # rechecks CLI, the LIVE gate, filters and the symbol lock.
    cli = [
        args.base_script,
        "--symbol", symbol,
        "--ladder-prices", ",".join(f"{p:.8f}" for p in ladder),
        "--max-oco-per-symbol", str(args.max_oco_per_symbol),
        "--tp1", f"{(tp1 if tp1 is not None else args.tp1):.6f}",
        "--tp2", f"{(tp2 if tp2 is not None else args.tp2):.6f}",
        "--sl",  f"{args.sl:.6f}",
        "--status-interval", str(args.status_interval),
        "--loop-minutes", str(args.child_loop_minutes),
        "--oco-fallback", args.oco_fallback,
        "--target-buy-per-symbol", str(args.target_buy_per_symbol),
    ]
    if getattr(args, "child_cap_floor_usdt", None) is not None:
        cli += ["--cap-floor-usdt", str(args.child_cap_floor_usdt)]
    if getattr(args, "child_min_order_usdt", None) is not None:
        cli += ["--min-order-usdt", str(args.child_min_order_usdt)]
    if args.oco_on_holdings:
        cli.append("--oco-on-holdings")
    if args.auto_oco_holdings:
        cli.append("--auto-oco-holdings")
    if args.live:
        cli.append("--live")
    if args.live or getattr(args, "enforce_target_buys", False):
        cli.append("--enforce-target-buys")
    if getattr(args, "enforce_sell_limit", False):
        cli.append("--enforce-sell-limit")
    if getattr(args, "attach_oco_on_fill", False):
        cli.append("--attach-oco-on-fill")
    if getattr(args, "check_fills_interval", None) is not None:
        cli += ["--check-fills-interval", str(args.check_fills_interval)]
    if getattr(args, "stop_limit_offset_pct", None) is not None:
        cli += ["--stop-limit-offset-pct", f"{args.stop_limit_offset_pct:.6f}"]

    if getattr(args, "child_skip_buy_while_panic", False):
        cli.append("--skip-buy-while-panic")
    if getattr(args, "child_buy_trend_ema_gap", None) is not None:
        cli += ["--buy-trend-ema-gap", f"{_analytics_float(args.child_buy_trend_ema_gap):.6f}"]
    if getattr(args, "child_buy_trend_interval", None):
        cli += ["--buy-trend-interval", str(args.child_buy_trend_interval)]
    if getattr(args, "child_bear_skip_buys", False):
        cli.append("--bear-skip-buys")
    if getattr(args, "child_bear_cap_scale", None) is not None and _analytics_float(args.child_bear_cap_scale) != 1.0:
        cli += ["--bear-cap-scale", f"{_analytics_float(args.child_bear_cap_scale):.6f}"]
    if getattr(args, "child_bear_buy_shift_pct", 0.0):
        cli += ["--bear-buy-shift-pct", f"{_analytics_float(args.child_bear_buy_shift_pct):.6f}"]
    if getattr(args, "child_panic_sell_floor_pct", None) is not None:
        cli += ["--panic-sell-floor-pct", f"{_analytics_float(args.child_panic_sell_floor_pct):.6f}"]
    if getattr(args, "child_buy_vwap_premium", None) is not None:
        cli += ["--buy-vwap-premium", f"{_analytics_float(args.child_buy_vwap_premium):.6f}"]
    if getattr(args, "child_buy_vwap_discount", None) is not None:
        cli += ["--buy-vwap-discount", f"{_analytics_float(args.child_buy_vwap_discount):.6f}"]
    if getattr(args, "child_buy_vwap_discount_scale", None) is not None and _analytics_float(args.child_buy_vwap_discount_scale) != 1.0:
        cli += ["--buy-vwap-discount-scale", f"{_analytics_float(args.child_buy_vwap_discount_scale):.6f}"]
    if getattr(args, "child_buy_vwap_interval", None):
        cli += ["--buy-vwap-interval", str(args.child_buy_vwap_interval)]
    if getattr(args, "child_buy_vwap_window", None) is not None:
        cli += ["--buy-vwap-window", str(int(args.child_buy_vwap_window))]

    if getattr(args, "breakeven_on_tp1_symbols", None):
        if str(args.breakeven_on_tp1_symbols).strip():
            cli += ["--breakeven-on-tp1-symbols", str(args.breakeven_on_tp1_symbols).strip()]
    if getattr(args, "breakeven_offset_pct", None) is not None:
        cli += ["--breakeven-offset-pct", f"{_analytics_float(args.breakeven_offset_pct):.6f}"]
    if getattr(args, "breakeven_check_interval", None) is not None:
        cli += ["--breakeven-check-interval", str(int(args.breakeven_check_interval))]

    py = sys.executable or "/usr/bin/python3"
    cmd = [py, "-u"] + cli
    log("[LAUNCH] " + " ".join(map(str, cmd)))
    try:
        env = _child_process_env(extra_env)
        p = subprocess.Popen(cmd, stdout=sys.stdout, stderr=sys.stderr, env=env)
        _CHILD_PROCS[symbol] = p
        _CHILD_STARTED_AT[symbol] = now
    except (OSError, subprocess.SubprocessError, TypeError, ValueError) as e:
        delay = _schedule_child_restart(symbol, 1, 0.0, now=now)
        log(f"[LAUNCH-ERR] {symbol} -> {e}")
        log(f"[CHILD-BACKOFF] {symbol} retry_in={delay:.1f}s")

# ===========================
# Balance-based automatic CAP
# ===========================

def auto_cap_if_needed(args: argparse.Namespace, n_syms: int) -> Decimal | None:
    """Allocate USDT remaining after the protected reserve across BUY slots."""
    if not args.auto_cap:
        return None
    try:
        bals = get_balances()
        if "USDT" not in bals:
            raise RuntimeError("USDT balance is unavailable")
        reserve = max(Decimal("0"), money(os.getenv("RISK_RESERVE_USDT", "0")))
        total_free = max(Decimal("0"), money(bals["USDT"]))
        spendable = max(Decimal("0"), total_free - reserve)
        min_pool = money(args.cap_floor_usdt or 0)
        if spendable < max(Decimal("10"), min_pool):
            os.environ["BOT_CAP_PER_ORDER"] = "0"
            log(
                f"[AUTO-CAP] spendable_after_reserve≈{spendable:.2f} < threshold; "
                "failed closed with BOT_CAP_PER_ORDER=0"
            )
            return Decimal("0")
        log(
            f"[BAL] USDT total_free≈{total_free:.2f} reserve≈{reserve:.2f} "
            f"spendable_after_reserve≈{spendable:.2f}"
        )
        if spendable <= 0:
            os.environ["BOT_CAP_PER_ORDER"] = "0"
            return Decimal("0")
        pool = spendable * money(args.alloc_pct)
        denom = Decimal(max(1, n_syms * max(1, args.target_buy_per_symbol)))
        cap = pool / denom
        if args.cap_floor_usdt is not None:
            cap = max(cap, money(args.cap_floor_usdt))
        if args.cap_ceil_usdt is not None:
            cap = min(cap, money(args.cap_ceil_usdt))
        cap = max(Decimal("5"), cap)
        os.environ["BOT_CAP_PER_ORDER"] = format(cap, ".2f")
        log(
            f"[AUTO-CAP] spendable_after_reserve≈{spendable:.2f} "
            f"→ BOT_CAP_PER_ORDER≈{cap:.2f} (n_syms={n_syms})"
        )
        return cap
    except (ArithmeticError, KeyError, RuntimeError, TypeError, ValueError) as exc:
        # Never retain a previous positive CAP when the current balance cannot
        # be valued. Zero propagates through every worker and risk allocation.
        os.environ["BOT_CAP_PER_ORDER"] = "0"
        log(
            f"[AUTO-CAP] failed closed: error_type={exc.__class__.__name__}; "
            "BOT_CAP_PER_ORDER=0"
        )
        return Decimal("0")

# ===========================
# Per-symbol logic
# ===========================

_STARTUP_CLEAN_DONE: Dict[str, bool] = {}


def _build_ai_market_context(
    symbol: str,
    *,
    price: float,
    atr_pct: float,
    deterministic_mode: str,
    diag: Mapping[str, Any],
    ladder: tuple[float, float, float],
    target_buys: int,
) -> MarketContext:
    """Build ai market context."""
    low, down, up = ladder
    price_exact = _finite_decimal(price, name="AI context price")
    risk_cap_exact = _finite_decimal(
        os.getenv("BOT_CAP_PER_ORDER", "0") or "0",
        name="AI context risk CAP",
    )
    base: Dict[str, Any] = {
        "symbol": symbol,
        "price": _analytics_float(price_exact),
        "price_text": format(price_exact, "f"),
        "atr_pct": _analytics_float(atr_pct),
        "deterministic_mode": deterministic_mode,
        "candidate_mode": str(diag.get("candidate", deterministic_mode)),
        "ema_gap_pct": (
            (_analytics_float(diag.get("ema_fast", 0)) - _analytics_float(diag.get("ema_slow", 0)))
            / max(_analytics_float(price), 1e-12)
        ),
        "ema_slope": _analytics_float(diag.get("slope", 0)),
        "adx": _analytics_float(diag.get("adx", 0)),
        "ladder_low_pct": _analytics_float(low),
        "ladder_down_pct": _analytics_float(down),
        "ladder_up_pct": _analytics_float(up),
        "target_buys": int(target_buys),
        "risk_safe_cap_usdt": _analytics_float(risk_cap_exact),
        "risk_safe_cap_usdt_text": format(risk_cap_exact, "f"),
    }
    if _AI_DECISIONS is not None:
        try:
            def horizon_price(sym: str, target_ms: int) -> Decimal:
                candles = TM.get_klines(
                    sym, "1m", limit=1, startTime=target_ms
                )
                if not candles:
                    raise ValueError("missing horizon candle")
                return _finite_decimal(
                    candles[0][1], name="AI horizon candle price"
                )

            def horizon_candles(
                sym: str, start_ms: int, end_ms: int
            ) -> List[List[Any]]:
                return TM.get_klines(
                    sym,
                    "1m",
                    limit=min(1000, max(1, (end_ms - start_ms) // 60_000 + 1)),
                    startTime=start_ms,
                    endTime=end_ms,
                )

            _AI_DECISIONS.settle(
                symbol,
                price,
                price_lookup=horizon_price,
                candles_lookup=horizon_candles,
            )
        except sqlite3.Error as exc:
            dbg(f"[AI-DECISION] settle failed: {exc}")
    if _AI_ADVISOR is None:
        return MarketContext(**base)

    now = time.time()
    cached_context = _AI_CONTEXT_CACHE.get(symbol)
    context_ttl = min(
        max(1.0, _analytics_float(os.getenv("AI_MAX_MARKET_AGE_SEC", "30") or 30)),
        max(1.0, _analytics_float(os.getenv("AI_MAX_PORTFOLIO_AGE_SEC", "30") or 30)),
    )
    # Context refreshes more often than the LLM response. This keeps the
    # order book and balance fresh without increasing paid DeepSeek requests.
    if cached_context is not None and now - cached_context[0] <= context_ttl:
        cached_at, previous = cached_context
        elapsed = max(0.0, now - cached_at)
        return replace(
            previous,
            market_data_age_sec=previous.market_data_age_sec + elapsed,
            portfolio_data_age_sec=previous.portfolio_data_age_sec + elapsed,
        )

    extra: Dict[str, Any] = {}
    trade_features = load_trade_features(
        os.getenv("BOT_STATS_DB", ""),
        symbol,
        price,
    )
    extra.update(asdict(trade_features))
    market_features = build_market_features(
        symbol,
        get_klines=TM.get_klines,
        public_get=TM._public_get,
    )
    extra.update(asdict(market_features))
    try:
        portfolio_features = build_portfolio_features(
            symbol,
            open_orders=list_open_orders(symbol),
            balances=get_balances_full(),
            portfolio_cap_usdt=(
                os.getenv("RISK_PORTFOLIO_CAP_USDT", "0") or "0"
            ),
            reserve_usdt=os.getenv("RISK_RESERVE_USDT", "0") or "0",
        )
        extra.update(asdict(portfolio_features))
    except (ArithmeticError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
        dbg(f"[AI-CONTEXT] portfolio aggregate unavailable: {exc}")
    if _AI_DECISIONS is not None:
        try:
            extra.update(asdict(_AI_DECISIONS.performance(symbol)))
        except sqlite3.Error as exc:
            dbg(f"[AI-DECISION] performance failed: {exc}")
    context = MarketContext(**base, **extra)
    if _AI_KNOWLEDGE is not None:
        knowledge_stats = _AI_KNOWLEDGE.stats()
        context = replace(
            context,
            real_rag_episode_count=int(knowledge_stats.get("documents", 0)),
        )
        context_ready = (
            context.market_data_available
            and context.orderbook_available
            and context.portfolio_data_available
            and context.market_data_age_sec <= _analytics_float(os.getenv("AI_RAG_MAX_MARKET_AGE_SEC", "30"))
            and context.portfolio_data_age_sec <= _analytics_float(os.getenv("AI_RAG_MAX_PORTFOLIO_AGE_SEC", "30"))
        )
        rag_documents = ()
        if context_ready:
            rag_documents = tuple(
                _AI_KNOWLEDGE.retrieve(
                    symbol,
                    context_vector(context),
                    limit=int(os.getenv("AI_RAG_TOP_K", "3") or 3),
                    include_virtual=False,
                    min_score=_analytics_float(os.getenv("AI_RAG_MIN_SCORE", "0.65") or 0.65),
                    min_matches=max(1, int(os.getenv("AI_RAG_MIN_MATCHES", "1") or 1)),
                    decay_days=max(0, int(os.getenv("AI_RAG_DECAY_DAYS", "180") or 180)),
                )
            )
        else:
            dbg(f"[AI-RAG] {symbol} skipped: incomplete_or_stale_context")
        context = replace(context, rag_context=rag_documents)
    _AI_CONTEXT_CACHE[symbol] = (now, context)
    return context


def run_for_symbol(
    symbol: str,
    args: argparse.Namespace,
    *,
    execution_allowed: bool = True,
) -> None:
    """Build one plan; optionally retain only read-only SHADOW telemetry."""
    # 1) Current price + ATR
    now_p = get_last_price(symbol)
    log(f"[PLAN] {symbol} now≈{now_p:.4f}")

    atr_abs, atr_pct = _atr_pct(symbol, interval=(args.atr_interval if hasattr(args, 'atr_interval') else '5m'), length=20)

    # 2) Baseline ATR-based TP/SL when not explicitly configured
    tp1_calc = clamp(atr_pct * _analytics_float(args.atr_mult_tp1), _analytics_float(args.tp1_min), _analytics_float(args.tp1_max))
    tp2_calc = clamp(atr_pct * _analytics_float(args.atr_mult_tp2), _analytics_float(args.tp1_min), _analytics_float(args.tp1_max * 1.8))
    tp1_use = _analytics_float(args.tp1) if args.tp1 is not None else tp1_calc
    tp2_use = _analytics_float(args.tp2) if args.tp2 is not None else tp2_calc
    log(f"[ATR] {symbol} ATR={atr_abs:.4f} -> tp1={tp1_use:.4f}..{args.tp1_max:.4f} with mults tp1={args.atr_mult_tp1} tp2={args.atr_mult_tp2} sl={args.atr_mult_sl}")

    # 3) Direction mode (auto/forced)
    if args.dir_mode != "auto":
        dir_mode = args.dir_mode.upper()
        _diag = {
            "ema_fast": 0.0,
            "ema_slow": 0.0,
            "slope": 0.0,
            "adx": 0.0,
            "candidate": dir_mode,
        }
        log(f"[DIR] {symbol} mode={dir_mode} (forced)")
    else:
        dir_mode, _diag = _infer_market_mode(
            symbol,
            interval=args.dir_interval,
            ema_fast_len=20,
            ema_slow_len=50,
            eps=_analytics_float(args.dir_eps),
            slope_min=_analytics_float(args.dir_slope_min),
            adx_min=_analytics_float(args.dir_adx_min),
            hyst_bars=int(args.dir_hyst_bars),
            confirm_bars=int(args.dir_confirm_bars),
            do_log=bool(args.dir_log)
        )

    raw_regime = {
        "UP": "TREND_UP",
        "DOWN": "TREND_DOWN",
        "FLAT": "RANGE",
    }.get(dir_mode, "RANGE")
    executor_panic, _panic_hits = _prediction_panic_state(symbol)
    regime_machine = _EXECUTION_REGIMES.setdefault(
        symbol,
        RegimeExecutionStateMachine(
            confirmations=max(
                1,
                int(os.getenv("BOT_REGIME_CONFIRMATIONS", "3") or "3"),
            ),
            recovery_confirmations=max(
                1,
                int(
                    os.getenv(
                        "BOT_REGIME_RECOVERY_CONFIRMATIONS", "3"
                    )
                    or "3"
                ),
            ),
            min_hold_sec=max(
                0.0,
                _analytics_float(
                    os.getenv("BOT_REGIME_MIN_HOLD_SEC", "300") or "300"
                ),
            ),
        ),
    )
    confirmed_regime = regime_machine.update(
        raw_regime,
        now=time.monotonic(),
        panic=executor_panic is True,
    )
    regime_policy = regime_machine.policy(
        trend_up_cap_scale=os.getenv(
            "BOT_REGIME_TREND_UP_CAP_SCALE", "0.75"
        )
        or "0.75",
    )
    regime_mode = _control_mode("BOT_REGIME_GATE_MODE")
    expectancy_mode = _control_mode("BOT_EXPECTANCY_MODE")
    inventory_mode = _control_mode("BOT_INVENTORY_SKEW_MODE")
    maker_mode = _control_mode("BOT_MAKER_POLICY_MODE")
    requested_apply = any(
        mode == "APPLY"
        for mode in (
            regime_mode,
            expectancy_mode,
            inventory_mode,
            maker_mode,
        )
    )
    controls_apply_allowed, controls_gate = (
        _strategy_controls_apply_allowed(symbol)
        if requested_apply
        else (False, _strategy_control_gate(symbol))
    )
    controls_gate_blocked = requested_apply and not controls_apply_allowed
    commission_schedule: CommissionSchedule | None = None
    required_edge: Decimal | None = None
    commission_error: str | None = None
    try:
        commission_schedule = _commission_schedule(symbol)
        required_edge = required_round_trip_edge(
            buy_fee=commission_schedule.maker_buy,
            sell_fee=commission_schedule.maker_sell,
            buy_slippage=os.getenv("BOT_BUY_SLIPPAGE_PCT", "0.0005")
            or "0.0005",
            sell_slippage=os.getenv("BOT_SELL_SLIPPAGE_PCT", "0.0005")
            or "0.0005",
            safety_margin=os.getenv(
                "BOT_EDGE_SAFETY_MARGIN_PCT", "0.0002"
            )
            or "0.0002",
            multiplier=os.getenv("BOT_EDGE_COST_MULTIPLIER", "3") or "3",
        )
    except (
        ArithmeticError,
        KeyError,
        RuntimeError,
        TypeError,
        ValueError,
        requests.RequestException,
    ) as exc:
        commission_error = type(exc).__name__
        if expectancy_mode == "APPLY":
            log(
                f"[EXPECTANCY-BLOCK] {symbol} authoritative commission "
                f"unavailable={commission_error}"
            )
    log(
        f"[REGIME-{regime_mode}] {symbol} raw={raw_regime} "
        f"confirmed={confirmed_regime} buys={regime_policy.buys_allowed} "
        f"cap_scale={regime_policy.cap_scale}"
    )
    if required_edge is not None:
        log(
            f"[EXPECTANCY-{expectancy_mode}] {symbol} required_edge="
            f"{required_edge:.8f} discount_not_relied_upon="
            f"{commission_schedule.discount_observed}"
        )
    expectancy_pause_buys = (
        expectancy_mode == "APPLY" and required_edge is None
    )
    if controls_gate_blocked:
        log(
            f"[STRATEGY-CONTROLS-BLOCK] {symbol} APPLY lacks approved "
            "walk-forward evidence or explicit operator approval"
        )

    operator_target_buys_limit = max(1, int(args.target_buy_per_symbol))
    target_buys_use = operator_target_buys_limit
    param_hyst = _PARAM_HYSTERESIS.setdefault(symbol, {
        "width": NumericHysteresis(1.0, max_step=_analytics_float(os.getenv("BOT_PARAM_MAX_STEP", "0.15"))),
        "cap": NumericHysteresis(1.0, max_step=_analytics_float(os.getenv("BOT_PARAM_MAX_STEP", "0.15"))),
        "buys": NumericHysteresis(_analytics_float(target_buys_use), max_step=0.5),
    })

    # Build a fully deterministic baseline first. The LLM receives only
    # aggregated indicators and never sees API keys, balances or order methods.
    low, down, up = args.ladder_pct
    if args.ladder_pct_map and symbol in args.ladder_pct_map:
        low, down, up = args.ladder_pct_map[symbol]
    ai_width_scale = 1.0
    ai_cap_scale = 1.0
    ai_pause_buys = False
    statistical = {"available": False, "samples": 0}
    statistical_regime_mode = _control_mode(
        "BOT_STATISTICAL_REGIME_MODE"
    )
    extra_env = _strategy_child_env(
        commission_schedule=commission_schedule,
        required_edge=required_edge,
        expectancy_mode=expectancy_mode,
        maker_mode=maker_mode,
    )
    advisor_active = (
        _AI_ADVISOR is not None
        and (_AI_POLICY is None or _AI_POLICY.mode != "DISABLED")
    )
    if advisor_active or (
        statistical_regime_mode != "OFF" and _AI_DECISIONS is not None
    ):
        ai_context = _build_ai_market_context(
            symbol,
            price=now_p,
            atr_pct=_analytics_float(atr_pct or 0),
            deterministic_mode=dir_mode,
            diag=_diag,
            ladder=(_analytics_float(low), _analytics_float(down), _analytics_float(up)),
            target_buys=target_buys_use,
        )
        statistical = (
            _AI_DECISIONS.statistical_prediction(
                ai_context,
                min_samples=int(args.ai_min_accuracy_samples) * 2,
            )
            if (
                statistical_regime_mode != "OFF"
                and _AI_DECISIONS is not None
            )
            else {"available": False, "samples": 0}
        )
        if statistical_regime_mode != "OFF":
            log(
                f"[STATISTICAL-{statistical_regime_mode}] {symbol} "
                f"available={statistical.get('available', False)} "
                f"mode={statistical.get('mode', 'FLAT')} "
                f"samples={statistical.get('samples', 0)}"
            )
        recommendation = (
            _AI_ADVISOR.recommend(ai_context)
            if advisor_active and _AI_ADVISOR is not None
            else None
        )
        if recommendation is not None:
            statistical_mode = (
                str(statistical["mode"])
                if statistical.get("available") else None
            )
            policy = apply_safety_policy(
                ai_context,
                recommendation,
                _AI_POLICY or PolicyConfig(mode="SHADOW"),
                benchmark_mode=statistical_mode,
            )
            if _AI_DECISIONS is not None:
                try:
                    decision_id = (
                        _AI_DECISION_IDS.get(symbol)
                        if _AI_ADVISOR.last_was_cache_hit
                        else _AI_ADVISOR.last_decision_id
                    )
                    if not decision_id:
                        decision_id = _AI_DECISIONS.record(
                            symbol=symbol,
                            price=now_p,
                            deterministic_mode=dir_mode,
                            recommended_mode=policy.recommendation.mode,
                            width_scale=policy.recommendation.ladder_width_scale,
                            cap_scale=policy.recommendation.cap_scale,
                            confidence=policy.recommendation.confidence,
                            applied=policy.apply,
                            policy_status=policy.status,
                            policy_reasons=",".join(policy.reasons),
                            benchmark_mode=policy.benchmark_mode,
                            feature_json=json.dumps(context_vector(ai_context)),
                            rationale=policy.recommendation.rationale,
                            config_version=__version__,
                            context_hash_value=context_hash(ai_context),
                        )
                        if _AI_KNOWLEDGE is not None:
                            _AI_KNOWLEDGE.link_retrieval(
                                decision_id, ai_context.rag_context
                            )
                    if not _AI_ADVISOR.last_was_cache_hit:
                        _AI_DECISIONS.update_policy(
                            decision_id,
                            policy_status=policy.status,
                            policy_reasons=",".join(policy.reasons),
                            benchmark_mode=policy.benchmark_mode,
                            applied=policy.apply,
                        )
                    _AI_DECISION_IDS[symbol] = decision_id
                    # Pass the exact ID to the child executor so fills are not
                    # attached to the symbol's last recommendation.
                    extra_env["BOT_AI_DECISION_ID"] = decision_id
                except sqlite3.Error as exc:
                    dbg(f"[AI-DECISION] record failed: {exc}")
            if policy.apply:
                if args.dir_mode == "auto":
                    dir_mode = policy.recommendation.mode
                ai_width_scale = policy.recommendation.ladder_width_scale
                ai_cap_scale = policy.recommendation.cap_scale
                ai_pause_buys = policy.pause_buys
                ai_width_scale = param_hyst["width"].update(ai_width_scale)
                ai_cap_scale = param_hyst["cap"].update(ai_cap_scale)
            log(
                f"[AI-ADVISOR] {symbol} provider={recommendation.provider} "
                f"model={recommendation.model} status={policy.status} "
                f"confidence={recommendation.confidence:.2f} "
                f"mode={policy.recommendation.mode} benchmark={policy.benchmark_mode} "
                f"stat_samples={statistical.get('samples', 0)} "
                f"width×{policy.recommendation.ladder_width_scale:.2f} "
                f"cap×{policy.recommendation.cap_scale:.2f} "
                f"guards={','.join(policy.reasons) or 'none'} "
                f"reason={recommendation.rationale}"
            )
            _publish_ai_runtime_status(
                state="RUNNING",
                last_decision={
                    "symbol": symbol,
                    "created_at": int(time.time()),
                    "baseline_mode": ai_context.deterministic_mode,
                    "recommended_mode": policy.recommendation.mode,
                    "confidence": policy.recommendation.confidence,
                    "policy_status": policy.status,
                    "policy_reasons": list(policy.reasons),
                    "applied": policy.apply,
                    "pause_buys": policy.pause_buys,
                    "statistical_challenger": statistical,
                },
            )

    auto_adapt = os.environ.get(
        "AUTO_ADAPT_ENABLE", "0"
    ) in ("1", "true", "True", "YES", "yes")
    configured_minimum_profit = _finite_decimal(
        os.environ.get("MIN_PROFIT_OVER_AVG", "0.002") or "0.002",
        name="configured minimum profit",
    )
    entry_gap, minimum_profit, tp1_exact = _directional_entry_settings(
        base_gap=os.environ.get("DEV_BUY_PCT", "0.004") or "0.004",
        atr_pct=atr_pct or 0,
        base_min_profit=configured_minimum_profit,
        auto_adapt=auto_adapt,
        gap_atr_coefficient=(
            os.environ.get("ADAPT_DEV_BUY_COEF", "0.6") or "0.6"
        ),
        profit_atr_coefficient=(
            os.environ.get("ADAPT_MIN_PROFIT_COEF", "0.6") or "0.6"
        ),
        gap_floor=(
            os.environ.get("ADAPT_MIN_FLOOR", "0.0025") or "0.0025"
        ),
        gap_ceiling=(
            os.environ.get("ADAPT_MAX_ENTRY_GAP_PCT", "0.02") or "0.02"
        ),
        mode=dir_mode,
        up_gap_multiplier=args.dir_up_dev_mult,
        down_gap_multiplier=args.dir_down_dev_mult,
        take_profit_pct=tp1_use,
        up_tp_multiplier=args.dir_up_tp1_mult,
        down_tp_multiplier=args.dir_down_tp1_mult,
        tp_floor=args.tp1_min,
        tp_ceiling=args.tp1_max,
    )
    expectancy_configuration_passes = bool(
        required_edge is not None
        and minimum_profit >= required_edge
        and tp1_exact >= required_edge
    )
    if required_edge is not None:
        log(
            f"[EXPECTANCY-CONFIG] {symbol} required={required_edge:.8f} "
            f"minimum_net={minimum_profit:.8f} tp={tp1_exact:.8f} "
            f"passes={expectancy_configuration_passes}"
        )
    if expectancy_mode == "APPLY" and not expectancy_configuration_passes:
        expectancy_pause_buys = True
    before_tp1 = tp1_use
    tp1_use = _analytics_float(tp1_exact)
    extra_env.update({
        "DEV_BUY_PCT": format(entry_gap, "f"),
        "MIN_PROFIT_OVER_AVG": format(minimum_profit, "f"),
    })
    if dir_mode == "UP":
        target_buys_use = max(1, int(args.dir_up_target_buys))
    elif dir_mode == "DOWN":
        target_buys_use = max(1, int(args.dir_down_target_buys))
    adaptive_target_buys = round(
        param_hyst["buys"].update(_analytics_float(target_buys_use))
    )
    target_buys_use = limit_target_buys(
        adaptive_target_buys,
        operator_target_buys_limit,
    )
    log(
        f"[ENTRY-ADAPT] {symbol} mode={dir_mode} "
        f"BUY gap={entry_gap:.4f} TP1 {before_tp1:.4f}→{tp1_use:.4f} "
        f"min_net={minimum_profit:.4f} "
        f"target_buys={args.target_buy_per_symbol}→{target_buys_use}"
    )

    vwap_premium_final, vwap_discount_final, vwap_scale_final, vwap_interval_final, vwap_window_final = resolve_vwap_params(
        symbol,
        dir_mode,
        atr_pct or 0.0,
        args,
    )

    if args.child_buy_vwap_auto:
        dbg(
            f"[VWAP-AUTO] {symbol} dir={dir_mode} atr_pct={atr_pct:.4f} premium={vwap_premium_final if vwap_premium_final is not None else '∅'} "
            f"discount={vwap_discount_final if vwap_discount_final is not None else '∅'} scale={vwap_scale_final if vwap_scale_final is not None else '∅'}"
        )

    # 4) Exchange filters: read once for tick normalization and guards
    filters = get_exchange_filters_cached(symbol)
    tick = filters["tickSize"]
    tick_exact = filters.get("tickSizeExact", tick)

    # 5) Build the ladder and deduplicate by tick step and side
    low *= ai_width_scale
    down *= ai_width_scale
    up *= ai_width_scale
    ladder_all = build_ladder_pct(now_p, low, down, up, args.grid_density)
    # DEV_BUY_PCT used to be a dead child environment value. Add the exact
    # adaptive best BUY to the actual ladder so an UP market starts closer
    # without crossing the market or enabling re-anchor APPLY.
    adaptive_best_buy = _adaptive_best_buy_price(now_p, entry_gap)
    ladder_all.append(adaptive_best_buy)

    ladder_all = _deduplicate_ladder_prices(ladder_all, now_p, tick_exact)

    log(f"[PLAN] {symbol} ladder -> " + ", ".join(f"{p:.2f}" for p in ladder_all))

    if execution_allowed:
        # 6) Cleanup at startup and on the regular interval.
        if not _STARTUP_CLEAN_DONE.get(symbol, False):
            startup_cleanup_orders(
                symbol,
                now_p,
                ladder_all,
                tick_size=tick,
                grace_sec=CLEANUP_WARMUP_SEC,
            )
            _STARTUP_CLEAN_DONE[symbol] = True

        smart_cleanup_orders(
            symbol,
            now_price=now_p,
            ladder_prices=ladder_all,
            tick_size=tick,
            near_ttl_sec=args.near_ttl_sec,
            far_ttl_sec=args.far_ttl_sec,
            cancel_offladder=True,
        )

        reanchor_gate = (
            _prediction_reanchor_gate(symbol)
            if str(args.reanchor_mode).upper() == "APPLY"
            else {"approved": False, "mode": "SHADOW"}
        )
        sr = smart_rolling(
            symbol,
            now_p,
            ladder_all,
            args,
            tick_size=tick_exact,
            prediction_apply_approved=bool(
                reanchor_gate.get("approved", False)
            ),
        )
        _publish_reanchor_runtime(symbol, sr, args)
        log(
            f"[SR-SUM] {symbol} kept={sr['kept']} "
            f"cancel(ttl)={sr['cancel'].get('ttl',0)} "
            f"cancel(atr)={sr['cancel'].get('atr',0)} "
            f"cancel(reanchor)={sr['cancel'].get('reanchor',0)} "
            f"shadow(reanchor)={sr['cancel'].get('shadow',0)}"
        )
    else:
        # A Risk block must stop execution but not blind SHADOW analytics.
        # This synthetic rolling result cannot cancel, replace or submit.
        sr = {
            "kept": 0,
            "cancel": {
                "ttl": 0,
                "atr": 0,
                "reanchor": 0,
                "shadow": 0,
            },
            "proposals": [],
            "replacement_prices": [],
        }
        log(
            f"[BLOCKED-SHADOW] {symbol} advisory snapshot only; "
            "order mutation disabled"
        )

    # 7) The exact entry adapter was applied to the ladder before cleanup.
    # AI may only reduce an already safe CAP. Even if the model returns a
    # coefficient above 1, the Risk Manager calculation remains the upper bound.
    risk_safe_cap = _finite_decimal(
        os.getenv("BOT_CAP_PER_ORDER", "0") or "0",
        name="BOT_CAP_PER_ORDER",
    )
    inventory_scale = Decimal("1")
    managed_exposure = Decimal("0")
    hard_inventory_cap: Decimal | None = None
    inventory_error: str | None = None
    if risk_safe_cap > 0:
        # An explicit per-symbol budget takes priority over the global CAP and
        # prevents a correlated asset from consuming the remaining portfolio limit.
        symbol_cap = _finite_decimal(
            os.getenv(f"RISK_SYMBOL_CAP_{symbol.upper()}", "0") or "0",
            name=f"RISK_SYMBOL_CAP_{symbol.upper()}",
        )
        if os.getenv(f"RISK_SYMBOL_CAP_{symbol.upper()}") is not None:
            risk_safe_cap = min(
                risk_safe_cap,
                max(Decimal("0"), symbol_cap),
            )
        try:
            hard_inventory_cap = _managed_inventory_hard_cap(symbol)
            managed_exposure = _managed_inventory_exposure(symbol, now_p)
            inventory_scale = inventory_skew_scale(
                managed_exposure,
                hard_inventory_cap,
                gamma=os.getenv("BOT_INVENTORY_SKEW_GAMMA", "2") or "2",
            )
        except (ArithmeticError, RuntimeError, TypeError, ValueError) as exc:
            inventory_error = type(exc).__name__
            if inventory_mode == "APPLY":
                inventory_scale = Decimal("0")
        if inventory_mode == "APPLY":
            risk_safe_cap *= inventory_scale
        if regime_mode == "APPLY":
            risk_safe_cap *= regime_policy.cap_scale
        advised_cap = limit_cap_by_recommendation_decimal(
            risk_safe_cap,
            ai_cap_scale,
        )
        extra_env["BOT_CAP_PER_ORDER"] = f"{advised_cap:.8f}"
        hard_cap_label = (
            f"{hard_inventory_cap:.8f}"
            if hard_inventory_cap is not None
            else "unavailable"
        )
        log(
            f"[INVENTORY-SKEW-{inventory_mode}] {symbol} managed="
            f"{managed_exposure:.8f} scale={inventory_scale:.8f} "
            f"hard_cap={hard_cap_label} error={inventory_error or 'none'}"
        )
    else:
        cap_scaling_reason = _cap_scaling_inactive_reason(
            risk_safe_cap,
            inventory_mode=inventory_mode,
            regime_mode=regime_mode,
        )
        if cap_scaling_reason is not None:
            log(
                f"[CAP-SCALING-INACTIVE] {symbol} {cap_scaling_reason}"
            )

    # 8) Directional entry and TP values are already immutable for this child.

    # 9) Position guardian is an execution path and is never entered by the
    # blocked SHADOW collector.
    mode = (
        position_guard_and_maybe_flatten(
            symbol, now_p, atr_abs, args, filters
        )
        if execution_allowed
        else "blocked_shadow"
    )
    log(f"[POS-MODE] {symbol} mode={mode}")

    child_ladder = _deduplicate_ladder_prices(
        [*sr.get("replacement_prices", []), *ladder_all],
        now_p,
        tick_exact,
    )
    controls_pause_buys = (
        controls_gate_blocked
        or expectancy_pause_buys
        or (
            regime_mode == "APPLY"
            and not regime_policy.buys_allowed
        )
        or (
            inventory_mode == "APPLY"
            and inventory_scale <= 0
        )
    )
    ladder_for_child = (
        child_ladder
        if mode not in ("reduce_only", "flattening")
        and not ai_pause_buys
        and not controls_pause_buys
        else _prune_to_sells_only(now_p, ladder_all)
    )
    if ai_pause_buys:
        log(f"[AI-POLICY] {symbol} PAUSE_BUYS: child receives SELL levels only")
    if controls_pause_buys:
        log(
            f"[NO-TRADE] {symbol} BUY disabled expectancy="
            f"{expectancy_pause_buys} regime={confirmed_regime} "
            f"inventory_scale={inventory_scale:.8f}; protection remains active"
        )
    controls_runtime = _AI_RUNTIME_STATUS.setdefault(
        "strategy_controls", {}
    )
    if isinstance(controls_runtime, dict):
        controls_runtime[symbol] = {
            "regime": {
                "mode": regime_mode,
                "raw": raw_regime,
                "confirmed": confirmed_regime,
                "buys_allowed": regime_policy.buys_allowed,
                "cap_scale": str(regime_policy.cap_scale),
            },
            "expectancy": {
                "mode": expectancy_mode,
                "required_edge_pct": (
                    str(required_edge)
                    if required_edge is not None
                    else None
                ),
                "commission_error": commission_error,
                "maker_policy_mode": maker_mode,
                "configuration_passes": expectancy_configuration_passes,
                "configured_minimum_net_pct": str(minimum_profit),
                "configured_take_profit_pct": str(tp1_exact),
            },
            "inventory_skew": {
                "mode": inventory_mode,
                "managed_exposure_usdt": str(managed_exposure),
                "hard_cap_usdt": (
                    str(hard_inventory_cap)
                    if hard_inventory_cap is not None
                    else None
                ),
                "scale": str(inventory_scale),
                "error": inventory_error,
            },
            "apply_gate": {
                "approved": controls_apply_allowed,
                "operator_approved": (
                    os.getenv(
                        "BOT_STRATEGY_CONTROLS_APPROVED", ""
                    ).strip().upper() == "YES"
                ),
                "evidence": controls_gate,
                "blocked": controls_gate_blocked,
            },
            "statistical_challenger": (
                statistical
                if "statistical" in locals()
                else {"available": False, "samples": 0}
            ),
            "buy_disabled": controls_pause_buys,
        }
        _publish_ai_runtime_status()

    # 10) Start the child with a temporary target_buys override
    orig_tb = int(args.target_buy_per_symbol)
    orig_vwap_premium = getattr(args, "child_buy_vwap_premium", None)
    orig_vwap_discount = getattr(args, "child_buy_vwap_discount", None)
    orig_vwap_scale = getattr(args, "child_buy_vwap_discount_scale", None)
    orig_vwap_interval = getattr(args, "child_buy_vwap_interval", None)
    orig_vwap_window = getattr(args, "child_buy_vwap_window", None)
    if execution_allowed:
        try:
            args.target_buy_per_symbol = int(target_buys_use)
            args.child_buy_vwap_premium = vwap_premium_final
            args.child_buy_vwap_discount = vwap_discount_final
            args.child_buy_vwap_discount_scale = vwap_scale_final
            args.child_buy_vwap_interval = vwap_interval_final
            args.child_buy_vwap_window = vwap_window_final
            run_child(
                symbol,
                ladder_for_child,
                args,
                extra_env=extra_env,
                tp1=tp1_use,
                tp2=tp2_use,
            )
        finally:
            args.target_buy_per_symbol = orig_tb
            args.child_buy_vwap_premium = orig_vwap_premium
            args.child_buy_vwap_discount = orig_vwap_discount
            args.child_buy_vwap_discount_scale = orig_vwap_scale
            args.child_buy_vwap_interval = orig_vwap_interval
            args.child_buy_vwap_window = orig_vwap_window

    # In execution mode SHADOW analytics runs only after the deterministic
    # worker launch. In blocked mode no worker or mutation path exists, so the
    # same evidence can be collected without delaying BUY protection.
    try:
        _record_prediction_shadow(
            symbol,
            now_price=now_p,
            ladder=ladder_all,
            take_profit_pct=tp1_use,
            stop_pct=args.sl,
            deterministic_mode=dir_mode,
            rolling=sr,
        )
    except SUPERVISOR_OPERATION_ERRORS as exc:
        log(f"[PREDICTION-SHADOW] {symbol} unavailable={type(exc).__name__}")
        runtime = _AI_RUNTIME_STATUS.setdefault("prediction", {})
        if isinstance(runtime, dict):
            runtime.update({
                "mode": "SHADOW",
                "can_change_orders": False,
                "last_error": type(exc).__name__,
            })
        _publish_ai_runtime_status()


def refresh_vwap_runtime_maps(args: argparse.Namespace,
                              symbols: List[str],
                              reason: str = "periodic") -> bool:
    """Refresh VWAP maps as advisory configuration, never as an order action."""
    if not symbols:
        return False

    script_dir = Path(__file__).resolve().parents[2] / "bin"
    sym_csv = ",".join(symbols)

    def _env(name: str, default: str) -> str:
        return os.getenv(name, default)

    base_cmd = [
        sys.executable or "/usr/bin/python3",
        str(script_dir / "gen_vwap_env.py"),
        "--symbols", sym_csv,
        "--interval", _env("BUY_VWAP_INTERVAL", "1m"),
        "--window", _env("BUY_VWAP_WINDOW", "240"),
        "--base-premium", _env("BUY_VWAP_PREMIUM", "0.0030"),
        "--base-discount", _env("BUY_VWAP_DISCOUNT", "0.0060"),
        "--base-scale", _env("BUY_VWAP_DISCOUNT_SCALE", "1.30"),
        "--premium-up-mult", _env("BUY_VWAP_PREMIUM_UP_MULT", "0.75"),
        "--premium-down-mult", _env("BUY_VWAP_PREMIUM_DOWN_MULT", "1.20"),
        "--premium-atr-coef", _env("BUY_VWAP_PREMIUM_ATR_COEF", "0.0"),
        "--premium-floor", _env("BUY_VWAP_PREMIUM_FLOOR", "0.0008"),
        "--premium-ceil", _env("BUY_VWAP_PREMIUM_CEIL", "0.0060"),
        "--scale-atr-coef", _env("BUY_VWAP_DISCOUNT_SCALE_ATR_COEF", "2.0"),
        "--scale-min", _env("BUY_VWAP_DISCOUNT_SCALE_MIN", "1.0"),
        "--scale-max", _env("BUY_VWAP_DISCOUNT_SCALE_MAX", "2.5"),
    ]

    env_vars = os.environ.copy()

    try:
        base_out = subprocess.check_output(base_cmd, text=True, env=env_vars)
    except subprocess.CalledProcessError as e:
        log(f"[VWAP-REFRESH] base generator failed ({reason}): {e}")
        return False
    except (OSError, RuntimeError, TypeError, ValueError) as e:
        log(f"[VWAP-REFRESH] base error ({reason}): {e}")
        return False

    premium_map, discount_map, scale_map = parse_vwap_output(base_out)

    if getattr(args, "vwap_autotune_enable", False):
        auto_cmd = [
            sys.executable or "/usr/bin/python3",
            str(script_dir / "gen_vwap_autotune.py"),
            "--symbols", sym_csv,
            "--hours", str(getattr(args, "vwap_autotune_hours", 24)),
            "--pnl-threshold", str(getattr(args, "vwap_autotune_threshold", 25.0)),
            "--alpha", str(getattr(args, "vwap_autotune_alpha", 0.6)),
            "--state-file", getattr(args, "vwap_autotune_state", "/run/mybot/vwap_state.json"),
        ]
        try:
            auto_out = subprocess.check_output(auto_cmd, text=True, env=env_vars)
        except subprocess.CalledProcessError as e:
            log(f"[VWAP-REFRESH] autotune failed ({reason}): {e}")
        except (OSError, RuntimeError, TypeError, ValueError) as e:
            log(f"[VWAP-REFRESH] autotune error ({reason}): {e}")
        else:
            p2, d2, s2 = parse_vwap_output(auto_out)
            if p2:
                premium_map.update(p2)
            if d2:
                discount_map.update(d2)
            if s2:
                scale_map.update(s2)

    if premium_map:
        args.child_buy_vwap_premium_map = premium_map
    if discount_map:
        args.child_buy_vwap_discount_map = discount_map
    if scale_map:
        args.child_buy_vwap_discount_scale_map = scale_map

    if premium_map or discount_map or scale_map:
        log(
            "[VWAP-REFRESH] maps updated (%s): premium=%s discount=%s scale=%s" % (
                reason,
                ",".join(f"{k}:{v:.6f}" for k, v in sorted(premium_map.items())) or "∅",
                ",".join(f"{k}:{v:.6f}" for k, v in sorted(discount_map.items())) or "∅",
                ",".join(f"{k}:{v:.6f}" for k, v in sorted(scale_map.items())) or "∅",
            )
        )
        return True

    log(f"[VWAP-REFRESH] no data received ({reason})")
    return False

# ===========================
# CLI arguments
# ===========================

def parse_ladder_pct_map(s: str) -> Dict[str, Tuple[float, float, float]]:
    return parse_pct_map(s)


def _configure_venue(args: argparse.Namespace) -> None:
    """Handle configure venue."""
    global BINANCE_API_BASE, API_KEY, API_SECRET
    if args.testnet:
        base = os.getenv("BINANCE_TESTNET_API_BASE", "https://testnet.binance.vision").rstrip("/")
        key = os.getenv("BINANCE_TESTNET_API_KEY", "")
        secret = os.getenv("BINANCE_TESTNET_API_SECRET", "")
        apply_testnet_paths()
        venue = "testnet"
    else:
        base = (os.getenv("BINANCE_API_BASE") or "https://api.binance.com").rstrip("/")
        key = os.getenv("BINANCE_API_KEY", "")
        secret = os.getenv("BINANCE_API_SECRET", "")
        venue = "mainnet"
    BINANCE_API_BASE, API_KEY, API_SECRET = base, key, secret
    TM.BASE_URL, TM.API_KEY, TM.API_SECRET = base, key, secret
    os.environ["BINANCE_API_BASE"] = base
    if key:
        os.environ["BINANCE_API_KEY"] = key
    if secret:
        os.environ["BINANCE_API_SECRET"] = secret
    SESSION.headers.pop("X-MBX-APIKEY", None)
    if key:
        SESSION.headers.update({"X-MBX-APIKEY": key})
    log(f"[VENUE] {venue} base={base} mode={'LIVE' if args.live else 'DRY'}")


def _preflight_live(args: argparse.Namespace, symbols: List[str], limits: RiskLimits) -> None:
    """Handle preflight live."""
    limits.validate()
    stats_db = os.getenv("BOT_STATS_DB", "").strip()
    cap_exact = _finite_decimal(
        args.cap_ceil_usdt or os.getenv("BOT_CAP_PER_ORDER", "50"),
        name="preflight CAP",
    )
    theoretical = (
        cap_exact
        * Decimal(args.target_buy_per_symbol)
        * Decimal(len(symbols))
    )
    max_exposure = min(
        theoretical,
        limits.portfolio_cap_usdt,
        limits.daily_buy_cap_usdt,
        limits.correlated_cap_usdt,
    )
    config = {
        "mode": "LIVE" if args.live else "DRY",
        "venue": "testnet" if args.testnet else "mainnet",
        "symbols": symbols,
        "target_buys_per_symbol": args.target_buy_per_symbol,
        "cap_per_order_usdt": _analytics_float(cap_exact),
        "max_new_buy_exposure_usdt": _analytics_float(
            max_exposure.quantize(Decimal("0.01"))
        ),
        "portfolio_cap_usdt": str(limits.portfolio_cap_usdt),
        "daily_buy_cap_usdt": str(limits.daily_buy_cap_usdt),
        "correlated_cap_usdt": str(limits.correlated_cap_usdt),
        "reserve_usdt": str(limits.reserve_usdt),
        "stats_db": stats_db or None,
    }
    log("[CONFIG] " + json.dumps(config, sort_keys=True))
    # DRY also prints the final configuration but does not require trading keys.
    if not args.live:
        return
    # Unvalued dust is allowed only by explicit name and acknowledgement.
    # Equity is conservative: an unknown asset can never increase CAP.
    unvalued_assets = _configured_unvalued_assets()
    if unvalued_assets:
        log(
            "[PREFLIGHT] explicitly acknowledged unvalued assets excluded "
            "from equity: " + ",".join(sorted(unvalued_assets))
        )
    if limits.halt_file.exists():
        log(
            f"[PREFLIGHT] persistent halt detected at {limits.halt_file}; "
            "supervisor will only reconcile and cancel BUY until manual reset"
        )
    if not TM.API_KEY or not TM.API_SECRET:
        prefix = "BINANCE_TESTNET" if args.testnet else "BINANCE"
        raise RuntimeError(f"{prefix}_API_KEY/SECRET are required for LIVE mode")

    if not stats_db:
        raise RuntimeError("BOT_STATS_DB is required for fail-closed LIVE mode")
    # LIVE cross-quote valuation must verify order-book depth.
    os.environ["RISK_CONVERSION_DEPTH_REQUIRED"] = "1"
    from ladder_dragon.execution import tools_stats
    con = tools_stats.init_db(stats_db)
    try:
        con.execute("SELECT 1 FROM trades LIMIT 1").fetchall()
    finally:
        con.close()

    # Check both clock offset and RTT: on a slow network, server-time estimation
    # is not reliable enough for signed orders.
    t0 = int(time.time() * 1000)
    server = _public_get("/api/v3/time")
    t1 = int(time.time() * 1000)
    clock = assess_exchange_clock(
        server_time_ms=int(server["serverTime"]),
        request_started_ms=t0,
        response_finished_ms=t1,
        max_offset_ms=int(os.getenv("RISK_MAX_TIME_OFFSET_MS", "1000")),
        max_round_trip_ms=int(os.getenv("RISK_MAX_TIME_RTT_MS", "5000")),
    )
    clock.require_safe()

    for symbol in symbols:
        filters = get_exchange_filters(symbol)
        required = ("tickSize", "stepSize", "minQty", "minNotional")
        invalid = [name for name in required if _analytics_float(filters.get(name, 0)) <= 0]
        if invalid:
            raise RuntimeError(f"invalid exchange filters for {symbol}: {','.join(invalid)}")

    account = TM._signed_get("/api/v3/account")
    if account.get("canTrade") is not True:
        raise RuntimeError("Binance account/API key is not allowed to trade")

    log("[PREFLIGHT] PASS " + json.dumps(config, sort_keys=True))


def _is_binance_auth_rejection(exc: BaseException) -> bool:
    """Recognize definitive Binance credential/IP rejections through wrappers."""
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status = getattr(current, "status", None)
        code = getattr(current, "code", None)
        if status in (401, 403) or code in (-2014, -2015, -1022):
            return True
        text = str(current).lower()
        if any(marker in text for marker in (
            "http 401",
            "http 403",
            "code=-2014",
            "code=-2015",
            "code=-1022",
            "'code': -2014",
            "'code': -2015",
            "'code': -1022",
            "invalid api-key",
            "api_key/secret are required",
        )):
            return True
        current = current.__cause__ or current.__context__
    return False


def _auth_retry_delay(
    attempt: int,
    *,
    initial_sec: int,
    max_sec: int,
) -> int:
    """Return bounded exponential delay for a one-based auth failure count."""
    exponent = min(max(0, int(attempt) - 1), 16)
    return min(int(max_sec), int(initial_sec) * (2 ** exponent))


def _auth_retry_schedule(
    attempt: int,
    *,
    initial_sec: int,
    max_sec: int,
    now: float,
) -> tuple[int, float]:
    """Return the delay and absolute runtime deadline for one auth retry."""
    delay = _auth_retry_delay(
        attempt,
        initial_sec=initial_sec,
        max_sec=max_sec,
    )
    return delay, now + delay


def _auth_backoff_active(retry_at: float, *, now: float) -> bool:
    """Tell runtime gates whether signed requests must remain deferred."""
    return retry_at > now


def _wait_for_auth_retry(
    delay_sec: int,
    *,
    attempt: int,
    persistent_halt: bool,
) -> None:
    """Keep fail-closed telemetry fresh while waiting for credential recovery."""
    deadline = time.monotonic() + max(1, int(delay_sec))
    while True:
        remaining = max(0, math.ceil(deadline - time.monotonic()))
        if remaining <= 0:
            return
        _publish_ai_runtime_status(
            state="AUTH_BACKOFF",
            error="Binance authentication unavailable",
            auth_backoff={
                "active": True,
                "attempt": int(attempt),
                "retry_in_sec": remaining,
                "retry_at": (
                    datetime.now(timezone.utc)
                    + timedelta(seconds=remaining)
                ).isoformat(),
            },
            risk={
                "halted": bool(persistent_halt),
                "buy_blocked": True,
                "reasons": (
                    ["persistent circuit halt", "Binance authentication unavailable"]
                    if persistent_halt
                    else ["Binance authentication unavailable"]
                ),
            },
        )
        time.sleep(min(30, remaining))


def _preflight_with_auth_backoff(
    args: argparse.Namespace,
    symbols: List[str],
    limits: RiskLimits,
) -> None:
    """Retry only definitive auth failures without a systemd restart storm."""
    state = _read_auth_resilience_state()
    attempt = int(state.attempt)
    if args.live:
        while True:
            try:
                state = _observe_public_ip(state)
            except RuntimeError:
                _publish_ai_runtime_status(
                    state="IP_BLOCKED",
                    error="public egress IP changed",
                    risk={
                        "halted": bool(limits.halt_file.exists()),
                        "buy_blocked": True,
                        "reasons": ["Binance whitelist review required"],
                    },
                    ip_guard={
                        "changed": True,
                        "address_exposed": False,
                    },
                )
                time.sleep(300)
                state = _read_auth_resilience_state()
                continue
            break
    while True:
        now_epoch = int(time.time())
        if state.retry_at_epoch > now_epoch:
            _wait_for_auth_retry(
                state.retry_at_epoch - now_epoch,
                attempt=max(1, state.attempt),
                persistent_halt=limits.halt_file.exists(),
            )
            state = AuthResilienceState(
                attempt=state.attempt,
                public_ip_sha256=state.public_ip_sha256,
                public_ip_changed=state.public_ip_changed,
                updated_at_epoch=int(time.time()),
            )
            _save_auth_resilience_state(state)
        try:
            _preflight_live(args, symbols, limits)
        except SUPERVISOR_OPERATION_ERRORS as exc:
            if not args.live or not _is_binance_auth_rejection(exc):
                _publish_ai_runtime_status(
                    state="PREFLIGHT_FAILED", error=str(exc)
                )
                raise
            state = register_auth_failure(
                state,
                initial_sec=args.binance_auth_backoff_initial_sec,
                max_sec=args.binance_auth_backoff_max_sec,
                now_epoch=int(time.time()),
            )
            _save_auth_resilience_state(state)
            attempt = state.attempt
            delay = max(1, state.retry_at_epoch - int(time.time()))
            log(
                "[AUTH-BACKOFF] Binance authentication rejected; "
                f"BUY blocked; retry={delay}s attempt={attempt}"
            )
            _wait_for_auth_retry(
                delay,
                attempt=attempt,
                persistent_halt=limits.halt_file.exists(),
            )
            state = AuthResilienceState(
                attempt=state.attempt,
                public_ip_sha256=state.public_ip_sha256,
                public_ip_changed=state.public_ip_changed,
                updated_at_epoch=int(time.time()),
            )
            _save_auth_resilience_state(state)
            continue
        else:
            state = register_auth_success(state, now_epoch=int(time.time()))
            _save_auth_resilience_state(state)
            if attempt:
                _publish_ai_runtime_status(
                    state="STARTING",
                    error=None,
                    auth_backoff={
                        "active": False,
                        "attempt": attempt,
                        "retry_in_sec": 0,
                        "retry_at": None,
                    },
                )
        try:
            recovery = _pre_running_recovery_gate(args, symbols)
        except SUPERVISOR_OPERATION_ERRORS as exc:
            recovery_reason = _runtime_recovery_reason(exc)
            log(
                "[RECOVERY] pre-RUNNING gate blocked; "
                f"reason={recovery_reason}"
            )
            _publish_ai_runtime_status(
                state="RECOVERY_BLOCKED",
                error=recovery_reason,
                recovery={
                    "checked": 0,
                    "blocked": True,
                    "error_type": type(exc).__name__,
                    "reason": recovery_reason,
                },
                risk={
                    "halted": bool(limits.halt_file.exists()),
                    "buy_blocked": True,
                    "reasons": [recovery_reason],
                },
            )
            time.sleep(60)
            continue
        _publish_ai_runtime_status(recovery=recovery)
        return


def _stop_child(symbol: str, reason: str) -> bool:
    """Gracefully stop one worker before replacing its immutable plan."""
    return stop_child(
        symbol,
        reason,
        processes=_CHILD_PROCS,
        started_at=_CHILD_STARTED_AT,
        restart_after=_CHILD_RESTART_AFTER,
        failures=_CHILD_FAILURES,
        logger=log,
    )


def _stop_children(reason: str) -> None:
    """Stop every managed child while retaining per-symbol cleanup semantics."""
    for symbol in list(_CHILD_PROCS):
        _stop_child(symbol, reason)


def _collect_blocked_shadow(
    symbols: List[str],
    args: argparse.Namespace,
    *,
    now_monotonic: float,
) -> None:
    """Keep advisory evidence fresh without entering any execution path."""
    if (
        _AI_ADVISOR is None
        or _AI_POLICY is None
        or str(_AI_POLICY.mode).upper() != "SHADOW"
    ):
        return
    interval = max(
        30,
        int(os.getenv("AI_BLOCKED_SHADOW_INTERVAL_SEC", "60") or "60"),
    )
    for symbol in symbols:
        last_attempt = _BLOCKED_SHADOW_LAST_ATTEMPT.get(symbol)
        if (
            last_attempt is not None
            and now_monotonic - last_attempt < interval
        ):
            continue
        # Rate-limit failures as well as successful observations.
        _BLOCKED_SHADOW_LAST_ATTEMPT[symbol] = now_monotonic
        try:
            run_for_symbol(symbol, args, execution_allowed=False)
        except SUPERVISOR_OPERATION_ERRORS as exc:
            log(
                f"[BLOCKED-SHADOW] {symbol} unavailable="
                f"{type(exc).__name__}"
            )


def _cancel_open_buy_orders(orders: Optional[List[Dict[str, Any]]] = None) -> int:
    """Handle cancel open buy orders."""
    orders = orders if orders is not None else (TM._signed_get("/api/v3/openOrders") or [])
    canceled = 0
    for order in orders:
        if str(order.get("side", "")).upper() != "BUY":
            continue
        if cancel_order(str(order["symbol"]), int(order["orderId"])):
            canceled += 1
    # A zero count is a stable no-op while BUY is blocked and used to flood
    # journald every risk cycle. Real cancellation remains operator-visible.
    if canceled:
        log(f"[RISK] canceled open BUY orders={canceled}")
    return canceled


def _log_info_rate_limited(
    key: str,
    message: str,
    *,
    interval_sec: float = 3600.0,
) -> bool:
    """Emit stable informational state at most once per bounded interval."""
    now = time.monotonic()
    interval = max(60.0, _analytics_float(interval_sec))
    previous = _INFO_LOG_LAST_EMITTED.get(key)
    if previous is not None and now - previous < interval:
        return False
    _INFO_LOG_LAST_EMITTED[key] = now
    log(message)
    return True


def _notify_risk(decision: RiskDecision) -> None:
    """Send risk."""
    reason = "; ".join(decision.reasons) or "risk limit"
    log(f"[RISK-ALERT] halted={decision.halted} buy_blocked={decision.buy_blocked}: {reason}")
    webhook = os.getenv("BOT_ALERT_WEBHOOK_URL", "").strip()
    if webhook:
        try:
            requests.post(webhook, json={
                "event": "circuit_breaker" if decision.halted else "buy_blocked",
                "reason": reason,
            }, timeout=5).raise_for_status()
        except requests.RequestException as exc:
            log(f"[RISK-ALERT] webhook failed: {exc}")


def _sync_recent_account_fills(symbols: List[str]) -> None:
    """Synchronize recent account fills."""
    stats_db = os.getenv("BOT_STATS_DB", "").strip()
    if not stats_db:
        raise RuntimeError("BOT_STATS_DB is required for fill reconciliation")

    con = tools_stats.init_db(stats_db)
    ensure_schema(con)
    cache: Dict[Tuple[str, str, int], Decimal] = {}

    def assets(symbol: str) -> Tuple[str, str]:
        return symbol_assets(symbol)

    def fee_value(symbol: str, asset: str, amount: Decimal, price: Decimal, ts: int):
        return commission_quote_value(
            symbol,
            asset,
            amount,
            price,
            ts,
            symbol_assets=assets,
            public_get=_public_get,
            cache=cache,
        )

    def signed_request(method: str, path: str, params: Dict[str, Any] | None = None):
        if method.upper() != "GET":
            raise RuntimeError("fill reconciliation only permits GET")
        return TM._signed_get(path, params or {})

    def on_fill(fill: Dict[str, Any]) -> None:
        # The ledger is protected by a unique trade_id; this callback only
        # synchronizes age-aware FIFO lots for time-stop/OCO.
        try:
            sync_exchange_fill(con, fill)
        except (
            sqlite3.Error,
            ValueError,
            ArithmeticError,
            RuntimeError,
        ) as exc:
            try:
                con.rollback()
            except sqlite3.Error as rollback_exc:
                raise RuntimeError(
                    "FIFO rollback failed during fill reconciliation"
                ) from rollback_exc
            # An historically incomplete FIFO must not discard a recorded
            # trade; account/inventory reconciliation remains mandatory and
            # blocks BUY on a real mismatch.
            log(f"[LOTS] {fill['symbol']} fill sync warning: {exc}")

    try:
        for symbol in symbols:
            poll_mytrades_once(
                symbol,
                connection=con,
                stats=tools_stats,
                signed_request=signed_request,
                commission_value=fee_value,
                logger=lambda message, symbol=symbol: log(f"[RECONCILE] {symbol} {message}"),
                on_fill=on_fill,
                strict=True,
            )
        con.commit()
    except (sqlite3.Error, OSError, ValueError, ArithmeticError, RuntimeError, requests.RequestException) as exc:
        raise RuntimeError(f"fresh fill import failed: {exc}") from exc
    finally:
        con.close()


def _build_risk_snapshot(
    symbols: List[str], limits: RiskLimits
) -> tuple[RiskSnapshot, List[Dict[str, Any]], Dict[str, object]]:
    """Delegate risk-cycle construction to the package service."""
    return build_risk_snapshot(symbols, limits, runtime=globals())

def main():
    """Handle main."""
    ap = build_supervisor_parser()
    args = ap.parse_args()
    log(f"[VERSION] {product_label('supervisor')}")
    symbols = validate_supervisor_args(ap, args)
    _configure_venue(args)
    global _AI_ADVISOR, _AI_DECISIONS, _AI_DECISIONS_PATH
    global _AI_KNOWLEDGE, _AI_POLICY
    global _AI_RUNTIME_STATUS_PATH, _AI_RUNTIME_STATUS, _AI_CONTROL_PATH
    global _PREDICTION_SHADOW
    _AI_DECISION_IDS.clear()
    _AI_CONTEXT_CACHE.clear()
    _PREDICTION_LAST_ATTEMPT.clear()
    _PREDICTION_GATE_CACHE.clear()
    _STRATEGY_CONTROL_GATE_CACHE.clear()
    _BLOCKED_SHADOW_LAST_ATTEMPT.clear()
    _INFO_LOG_LAST_EMITTED.clear()
    decisions_db = (
        os.getenv("AI_TESTNET_DECISIONS_DB", "").strip()
        if args.testnet else args.ai_decisions_db
    ) or args.ai_decisions_db
    _AI_DECISIONS_PATH = Path(decisions_db)
    statistical_regime_enabled = (
        _control_mode("BOT_STATISTICAL_REGIME_MODE") != "OFF"
    )
    _AI_DECISIONS = (
        AdvisorDecisionStore(decisions_db)
        if args.ai_advisor or statistical_regime_enabled
        else None
    )
    _AI_KNOWLEDGE = KnowledgeStore(decisions_db) if args.ai_advisor else None
    _AI_CONTROL_PATH = resolve_ai_control_path(os.getenv("AI_CONTROL_FILE"))
    configured_ai_mode = args.ai_mode if args.ai_advisor else "DISABLED"
    effective_ai_mode = configured_ai_mode
    try:
        initial_control = read_ai_control(_AI_CONTROL_PATH)
        if initial_control is not None and not initial_control.get("enabled", False):
            effective_ai_mode = "DISABLED"
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        # A corrupted control file must not enable AI.
        effective_ai_mode = "DISABLED"
    _AI_POLICY = PolicyConfig(
        mode=effective_ai_mode,
        max_market_age_sec=_analytics_float(args.ai_max_market_age_sec),
        max_portfolio_age_sec=_analytics_float(args.ai_max_portfolio_age_sec),
        max_spread_bps=_analytics_float(args.ai_max_spread_bps),
        high_volatility_pct=_analytics_float(args.ai_high_volatility_pct),
        max_consecutive_losses=int(
            os.getenv("RISK_MAX_CONSECUTIVE_LOSSES", "3") or 3
        ),
        min_trade_sells=int(args.ai_min_trade_sells),
        min_accuracy_samples=int(args.ai_min_accuracy_samples),
        min_ai_accuracy=_analytics_float(args.ai_min_accuracy),
        min_closed_decisions=int(args.ai_min_closed_decisions),
        min_real_rag_episodes=max(
            0, int(os.getenv("AI_MIN_REAL_RAG_EPISODES", "5") or 5)
        ),
        max_realized_stop_rate=_analytics_float(args.ai_max_realized_stop_rate),
    )
    _AI_ADVISOR = _build_ai_advisor(args)
    run_dir = Path(os.getenv("BOT_RUN_DIR", ".runtime"))
    prediction_enabled = os.getenv(
        "PREDICTION_SHADOW_ENABLED", "1"
    ).strip().lower() in {"1", "true", "yes", "on"}
    stats_path_text = os.getenv("BOT_STATS_DB", "").strip()
    default_prediction_path = (
        Path(stats_path_text).with_name("prediction_shadow.sqlite3")
        if stats_path_text else run_dir / "prediction_shadow.sqlite3"
    )
    prediction_path = Path(
        os.getenv("PREDICTION_SHADOW_DB", str(default_prediction_path))
    )
    _PREDICTION_SHADOW = None
    prediction_init_error = None
    if prediction_enabled:
        try:
            _PREDICTION_SHADOW = PredictionShadowStore(prediction_path)
        except (OSError, sqlite3.Error) as exc:
            prediction_init_error = type(exc).__name__
            log(
                "[PREDICTION-SHADOW] journal unavailable="
                f"{prediction_init_error}"
            )
    _AI_RUNTIME_STATUS_PATH = Path(
        os.getenv("AI_RUNTIME_STATUS_FILE", str(run_dir / "ai_status.json"))
    )
    _AI_RUNTIME_STATUS = {
        "product": {"name": "Ladder Dragon", "version": __version__},
        "started_at": datetime.now(timezone.utc).isoformat(),
        "state": "STARTING",
        "venue": "testnet" if args.testnet else "mainnet",
        "execution_mode": "LIVE" if args.live else "DRY",
        "symbols": symbols,
        "ai": {
            "enabled": _AI_ADVISOR is not None,
            "mode": effective_ai_mode,
            "configured_mode": configured_ai_mode,
            "control_enabled": effective_ai_mode != "DISABLED",
            "control_file": str(_AI_CONTROL_PATH),
            "provider": (
                _AI_ADVISOR.config.provider if _AI_ADVISOR is not None else None
            ),
            "model": (
                _AI_ADVISOR.config.model if _AI_ADVISOR is not None else None
            ),
            "budgets": {
                "max_requests_per_day": int(args.ai_max_requests_per_day),
                "max_tokens_per_day": int(args.ai_daily_token_limit),
                "max_cost_usd_per_day": str(args.ai_daily_cost_limit_usd),
            },
        },
        "paths": {
            "stats_db": os.getenv("BOT_STATS_DB", ""),
            "ai_decisions_db": decisions_db,
            "ai_usage_log": args.ai_usage_log,
            "order_journal": os.getenv("BOT_ORDER_JOURNAL", ""),
            "prediction_shadow_db": str(prediction_path),
        },
        "order_journal": _runtime_order_journal_snapshot(),
        "auth_backoff": {
            "active": False,
            "attempt": 0,
            "retry_in_sec": 0,
            "retry_at": None,
        },
        "reanchor": {
            "mode": str(args.reanchor_mode).upper(),
            "min_age_sec": int(args.reanchor_min_age_sec),
            "trigger_pct": str(args.reanchor_trigger_pct),
            "max_step_pct": str(args.reanchor_max_step_pct),
            "max_market_gap_pct": str(
                args.reanchor_max_market_gap_pct
            ),
            "max_per_cycle": int(args.reanchor_max_per_cycle),
            "totals": {"shadow_candidates": 0, "apply_cancels": 0},
            "symbols": {},
        },
        "prediction": {
            "enabled": _PREDICTION_SHADOW is not None,
            "mode": "SHADOW",
            "horizons_min": [1, 5, 15],
            "can_change_orders": False,
            "last_error": prediction_init_error,
            "symbols": {},
        },
    }
    _publish_ai_runtime_status()
    _refresh_ai_control(args)
    limits = RiskLimits.from_env()
    _publish_ai_runtime_status(
        risk_limits={
            "reserve_usdt": str(limits.reserve_usdt),
            "portfolio_cap_usdt": str(limits.portfolio_cap_usdt),
            "daily_buy_cap_usdt": str(limits.daily_buy_cap_usdt),
            "open_order_count_cap": limits.open_order_count_cap,
        }
    )
    _wait_for_maintenance_clear(args, limits)
    _preflight_with_auth_backoff(args, symbols, limits)
    global LIVE_MODE
    LIVE_MODE = bool(args.live)
    # In DRY the circuit breaker does not change persistent state. LIVE uses a
    # fail-closed manager and does not start workers without a fresh risk snapshot.
    risk_manager = RiskManager(limits) if args.live else None

    ai_label = (
        f"{args.ai_mode}:{_AI_ADVISOR.config.provider}/{_AI_ADVISOR.config.model}"
        if _AI_ADVISOR is not None else "disabled"
    )
    log(
        f"[SUP] symbols={symbols} ladder_mode={args.ladder_mode} "
        f"ai_advisor={ai_label}"
    )
    _publish_ai_runtime_status(state="RUNNING")

    lp = [x.strip() for x in args.ladder_pct.split(",")]
    if len(lp) != 3:
        raise SystemExit("--ladder-pct expects three numbers: low,down,up")
    args.ladder_pct = (_analytics_float(lp[0]), _analytics_float(lp[1]), _analytics_float(lp[2]))
    args.ladder_pct_map = parse_ladder_pct_map(args.ladder_pct_map)

    args.pos_max_base_map = parse_decimal_limit_map(args.pos_max_base_map)
    args.pos_max_usdt_map = parse_decimal_limit_map(args.pos_max_usdt_map)
    args.child_buy_vwap_premium_map = parse_limit_map(getattr(args, "child_buy_vwap_premium_map", ""))
    args.child_buy_vwap_discount_map = parse_limit_map(getattr(args, "child_buy_vwap_discount_map", ""))
    args.child_buy_vwap_discount_scale_map = parse_limit_map(getattr(args, "child_buy_vwap_discount_scale_map", ""))

    if args.singleton:
        try:
            _acquire_singleton_lock(LOCK_FILE)
            log(f"[SINGLETON] acquired flock {LOCK_FILE} pid={os.getpid()}")
        except (OSError, RuntimeError, BlockingIOError) as exc:
            log(
                f"[FATAL] singleton lock unavailable path={LOCK_FILE} "
                f"error_type={exc.__class__.__name__}"
            )
            raise SystemExit(3) from exc

    get_server_time_offset_ms()
    auto_cap = auto_cap_if_needed(args, n_syms=len(symbols))
    configured_order_cap = (
        auto_cap
        if auto_cap is not None
        else money(args.cap_ceil_usdt or os.getenv("BOT_CAP_PER_ORDER", "50"))
    )
    operator_order_cap = money(args.cap_ceil_usdt or configured_order_cap)
    if operator_order_cap <= 0:
        raise SystemExit("operator per-order CAP must be greater than zero")
    # This immutable child boundary is separate from BOT_CAP_PER_ORDER, which
    # Risk Manager narrows dynamically. Strategy, VWAP and AI may never raise a
    # worker order above the operator ceiling.
    os.environ["BOT_OPERATOR_CAP_PER_ORDER_USDT"] = str(operator_order_cap)

    def _next_vwap_refresh() -> float:
        base = max(0, int(getattr(args, "vwap_refresh_sec", 0)))
        if base <= 0:
            return math.inf
        delay = _analytics_float(base)
        jitter = max(0, int(getattr(args, "vwap_refresh_jitter_sec", 0)))
        if jitter > 0:
            delay += random.uniform(-jitter, jitter)
        return time.time() + max(5.0, delay)

    next_vwap_refresh = math.inf
    if getattr(args, "vwap_refresh_sec", 0) > 0:
        if getattr(args, "vwap_refresh_on_start", 1):
            try:
                if refresh_vwap_runtime_maps(args, symbols, reason="startup"):
                    next_vwap_refresh = _next_vwap_refresh()
                else:
                    next_vwap_refresh = _next_vwap_refresh()
            except SUPERVISOR_OPERATION_ERRORS as e:
                log(f"[VWAP-REFRESH] startup error: {e}")
                next_vwap_refresh = _next_vwap_refresh()
        else:
            next_vwap_refresh = _next_vwap_refresh()

    next_risk_check = 0.0
    risk_buy_blocked = False
    last_risk_signature: tuple[bool, tuple[str, ...]] | None = None
    previous_prices: Dict[str, Decimal] = {}
    consecutive_api_failures = 0
    runtime_auth_state = _read_auth_resilience_state()
    auth_failure_attempts = int(runtime_auth_state.attempt)
    auth_retry_at = _analytics_float(runtime_auth_state.retry_at_epoch)
    next_runtime_heartbeat = 0.0
    next_ai_control_check = 0.0
    risk_snapshot_available = False

    try:
        while True:
            now_loop = time.time()
            if now_loop >= next_ai_control_check:
                _refresh_ai_control(args)
                next_ai_control_check = now_loop + 2.0
            if now_loop >= next_runtime_heartbeat:
                auth_remaining = max(
                    0, math.ceil(auth_retry_at - now_loop)
                )
                # Remain visibly fail-closed until an authenticated risk
                # snapshot succeeds, including the instant a retry is due.
                auth_backoff_active = auth_failure_attempts > 0
                heartbeat_risk = dict(_AI_RUNTIME_STATUS.get("risk") or {})
                heartbeat_risk.update({
                    "buy_blocked": risk_buy_blocked,
                    "halted": bool(last_risk_signature and last_risk_signature[0]),
                    "reasons": list(last_risk_signature[1]) if last_risk_signature else [],
                    "consecutive_api_failures": consecutive_api_failures,
                    "current_cap_per_order_usdt": os.getenv("BOT_CAP_PER_ORDER"),
                    "operator_cap_per_order_usdt": os.getenv(
                        "BOT_OPERATOR_CAP_PER_ORDER_USDT"
                    ),
                })
                _publish_ai_runtime_status(
                    state=(
                        "AUTH_BACKOFF"
                        if auth_backoff_active
                        else "RUNNING"
                    ),
                    auth_backoff={
                        "active": auth_backoff_active,
                        "attempt": auth_failure_attempts,
                        "retry_in_sec": auth_remaining,
                        "retry_at": (
                            datetime.fromtimestamp(
                                auth_retry_at, timezone.utc
                            ).isoformat()
                            if auth_backoff_active
                            else None
                        ),
                    },
                    risk=heartbeat_risk,
                    order_journal=_runtime_order_journal_snapshot(),
                )
                # Do not write to the SD card on every trading tick; 30 seconds
                # is sufficient to show a live process in the dashboard.
                next_runtime_heartbeat = now_loop + 30.0
            if risk_manager is not None and now_loop >= next_risk_check:
                # Run risk checks before symbol planning. On any block, stop
                # workers and cancel only new BUY orders.
                orders: List[Dict[str, Any]] = []
                try:
                    snapshot, orders, prices = _build_risk_snapshot(symbols, limits)
                    risk_snapshot_available = True
                    consecutive_api_failures = 0
                    if auth_failure_attempts:
                        log(
                            "[AUTH-BACKOFF] Binance authentication recovered"
                        )
                        runtime_auth_state = register_auth_success(
                            runtime_auth_state,
                            now_epoch=int(now_loop),
                        )
                        _save_auth_resilience_state(runtime_auth_state)
                        auth_failure_attempts = 0
                        auth_retry_at = 0.0
                        _publish_ai_runtime_status(
                            error=None,
                            auth_backoff={
                                "active": False,
                                "attempt": 0,
                                "retry_in_sec": 0,
                                "retry_at": None,
                            }
                        )
                    shocks, previous_prices = _configured_price_shocks_decimal(
                        symbols,
                        prices,
                        previous_prices,
                        os.getenv("RISK_SHOCK_PCT", "0.05") or "0.05",
                    )
                    if shocks:
                        risk_manager.start_cooldown("; ".join(shocks))
                    decision = risk_manager.evaluate(snapshot)
                    unresolved_fills = _unresolved_fill_counts()
                    inventory_unresolved = unresolved_fills["inventory"]
                    if inventory_unresolved:
                        decision = RiskDecision(
                            halted=decision.halted,
                            buy_blocked=True,
                            reasons=tuple(
                                dict.fromkeys(
                                    [
                                        *decision.reasons,
                                        (
                                            f"{inventory_unresolved} unresolved "
                                            "inventory fill(s) require "
                                            "reconciliation"
                                        ),
                                    ]
                                )
                            ),
                        )
                    if not decision.buy_blocked:
                        # Narrow CAP further by the smallest remaining budget:
                        # portfolio, daily BUY, correlation and reserve.
                        remaining = _remaining_order_budget_decimal(limits, snapshot)
                        slots = max(1, args.target_buy_per_symbol * len(symbols))
                        safe_cap = min(configured_order_cap, max(Decimal("0"), remaining) / slots)
                        # Marginal-risk concentration: one asset must not receive
                        # all remaining CAP under stress.
                        if snapshot.exposure_usdt > 0 and snapshot.stress_loss_usdt > 0:
                            stress_ratio = min(Decimal("1"), snapshot.stress_loss_usdt / snapshot.exposure_usdt)
                            safe_cap *= max(Decimal("0"), Decimal("1") - stress_ratio)
                        allocations = allocate_cap_by_marginal_risk_decimal(
                            safe_cap,
                            {
                                symbol: value * snapshot.stress_loss_usdt
                                / max(snapshot.exposure_usdt, Decimal("1e-18"))
                                for symbol, value in snapshot.symbol_exposure_usdt.items()
                            },
                        )
                        cluster_mode = _control_mode(
                            "RISK_CLUSTER_GATE_MODE"
                        )
                        symbol_caps = {
                            symbol: min(
                                safe_cap,
                                allocations.get(symbol, safe_cap),
                            )
                            for symbol in symbols
                        }
                        if cluster_mode == "APPLY":
                            cluster_apply_allowed = all(
                                _strategy_controls_apply_allowed(symbol)[0]
                                for symbol in symbols
                            )
                            if not cluster_apply_allowed:
                                for symbol in symbols:
                                    symbol_caps[symbol] = Decimal("0")
                            else:
                                for cluster in snapshot.correlation_clusters:
                                    cluster_key = ",".join(cluster)
                                    cluster_remaining = max(
                                        Decimal("0"),
                                        limits.correlated_cap_usdt
                                        - snapshot.cluster_exposure_usdt.get(
                                            cluster_key, Decimal("0")
                                        ),
                                    )
                                    per_symbol = cluster_remaining / Decimal(
                                        max(1, len(cluster))
                                    )
                                    for symbol in cluster:
                                        symbol_caps[symbol] = min(
                                            symbol_caps.get(
                                                symbol, safe_cap
                                            ),
                                            per_symbol,
                                        )
                            for symbol in (
                                snapshot.liquidity_blocked_symbols
                            ):
                                symbol_caps[symbol] = Decimal("0")
                        for symbol in symbols:
                            os.environ[
                                f"RISK_SYMBOL_CAP_{symbol.upper()}"
                            ] = f"{symbol_caps.get(symbol, Decimal('0')):.8f}"
                        min_order = money(args.child_min_order_usdt or 0)
                        if safe_cap <= 0 or (min_order > 0 and safe_cap < min_order):
                            decision = RiskDecision(
                                halted=False,
                                buy_blocked=True,
                                reasons=(f"remaining risk budget {remaining:.2f} USDT cannot fund a safe order",),
                            )
                        else:
                            os.environ["BOT_CAP_PER_ORDER"] = str(safe_cap)
                            dbg(f"[RISK] dynamic safe order cap={safe_cap:.2f} USDT")
                    _publish_ai_runtime_status(
                        risk={
                            "buy_blocked": decision.buy_blocked,
                            "halted": decision.halted,
                            "reasons": list(decision.reasons),
                            "consecutive_api_failures": consecutive_api_failures,
                            "current_cap_per_order_usdt": os.getenv("BOT_CAP_PER_ORDER"),
                            "operator_cap_per_order_usdt": os.getenv(
                                "BOT_OPERATOR_CAP_PER_ORDER_USDT"
                            ),
                            "symbol_caps_usdt": {
                                symbol: os.getenv(f"RISK_SYMBOL_CAP_{symbol.upper()}")
                                for symbol in symbols
                                if os.getenv(f"RISK_SYMBOL_CAP_{symbol.upper()}") is not None
                            },
                            "unresolved_fills": unresolved_fills,
                            "snapshot": {
                                "equity_usdt": str(snapshot.equity_usdt),
                                "exposure_usdt": str(snapshot.exposure_usdt),
                                "free_usdt": str(snapshot.free_usdt),
                                "open_order_count": snapshot.open_order_count,
                                "daily_trade_count": snapshot.daily_trade_count,
                                "stale_order_count": snapshot.stale_order_count,
                                "correlation_clusters": [
                                    list(cluster)
                                    for cluster in snapshot.correlation_clusters
                                ],
                                "cluster_exposure_usdt": {
                                    key: str(value)
                                    for key, value in (
                                        snapshot.cluster_exposure_usdt.items()
                                    )
                                },
                                "liquidity_blocked_symbols": list(
                                    snapshot.liquidity_blocked_symbols
                                ),
                                "cluster_gate_mode": _control_mode(
                                    "RISK_CLUSTER_GATE_MODE"
                                ),
                            },
                        }
                    )
                except SUPERVISOR_OPERATION_ERRORS as exc:
                    # Unavailable telemetry is not a safe state: new BUY orders
                    # are blocked and a cooldown starts after repeated errors.
                    risk_snapshot_available = False
                    consecutive_api_failures += 1
                    threshold = max(1, int(os.getenv("RISK_API_FAILURE_THRESHOLD", "3")))
                    auth_rejected = _is_binance_auth_rejection(exc)
                    if auth_rejected:
                        runtime_auth_state = register_auth_failure(
                            runtime_auth_state,
                            initial_sec=args.binance_auth_backoff_initial_sec,
                            max_sec=args.binance_auth_backoff_max_sec,
                            now_epoch=int(now_loop),
                        )
                        _save_auth_resilience_state(runtime_auth_state)
                        auth_failure_attempts = runtime_auth_state.attempt
                        auth_retry_at = _analytics_float(
                            runtime_auth_state.retry_at_epoch
                        )
                        delay = max(
                            1, int(auth_retry_at - now_loop)
                        )
                        reason = (
                            "Binance authentication unavailable; "
                            f"retry in {delay}s"
                        )
                        log(
                            "[AUTH-BACKOFF] runtime authentication rejected; "
                            f"BUY blocked; retry={delay}s "
                            f"attempt={auth_failure_attempts}"
                        )
                        _publish_ai_runtime_status(
                            state="AUTH_BACKOFF",
                            error="Binance authentication unavailable",
                            auth_backoff={
                                "active": True,
                                "attempt": auth_failure_attempts,
                                "retry_in_sec": delay,
                                "retry_at": datetime.fromtimestamp(
                                    auth_retry_at, timezone.utc
                                ).isoformat(),
                            },
                        )
                    else:
                        reason = (
                            "risk telemetry unavailable "
                            f"({consecutive_api_failures}/{threshold}): {exc}"
                        )
                    if consecutive_api_failures >= threshold:
                        risk_manager.start_cooldown(reason)
                    decision = RiskDecision(halted=False, buy_blocked=True, reasons=(reason,))

                was_buy_blocked = risk_buy_blocked
                risk_buy_blocked = decision.buy_blocked
                if risk_buy_blocked:
                    reason = "; ".join(decision.reasons) or "risk limit"
                    if risk_manager is not None and not decision.halted and not was_buy_blocked:
                        risk_manager.start_cooldown(reason)
                    _stop_children(reason)
                    if _auth_backoff_active(
                        auth_retry_at, now=now_loop
                    ):
                        log(
                            "[AUTH-BACKOFF] BUY cancellation deferred until "
                            "authenticated reconciliation is available"
                        )
                    else:
                        try:
                            _cancel_open_buy_orders(
                                orders
                                if risk_snapshot_available
                                else None
                            )
                        except SUPERVISOR_OPERATION_ERRORS as exc:
                            log(f"[RISK] cancel BUY failed: {exc}")
                signature = (decision.halted, decision.reasons)
                if signature != last_risk_signature and decision.buy_blocked:
                    _notify_risk(decision)
                last_risk_signature = signature
                next_risk_check = max(
                    now_loop + max(1, int(args.risk_check_sec)),
                    auth_retry_at,
                )

            if risk_buy_blocked:
                # Execution remains stopped, but an authenticated healthy
                # snapshot may still feed advisory-only SHADOW evidence.
                if (
                    risk_snapshot_available
                    and not _auth_backoff_active(
                        auth_retry_at, now=now_loop
                    )
                ):
                    _collect_blocked_shadow(
                        symbols,
                        args,
                        now_monotonic=time.monotonic(),
                    )
                time.sleep(min(2.0, max(0.5, _analytics_float(args.risk_check_sec) / 2.0)))
                continue

            if now_loop >= next_vwap_refresh:
                try:
                    refresh_vwap_runtime_maps(args, symbols, reason="periodic")
                except SUPERVISOR_OPERATION_ERRORS as e:
                    log(f"[VWAP-REFRESH] periodic error: {e}")
                finally:
                    next_vwap_refresh = _next_vwap_refresh()

            for sym in symbols:
                try:
                    run_for_symbol(sym, args)
                except SUPERVISOR_OPERATION_ERRORS as e:
                    log(f"[ERR] {sym}: {e}")
                time.sleep(0.2)
            time.sleep(0.5)
    except KeyboardInterrupt:
        log("[SUP] shutdown requested")
    finally:
        _publish_ai_runtime_status(state="STOPPING")
        _stop_children("supervisor shutdown")
        _release_singleton_lock()
        log(f"[stop-all] singleton flock released ({LOCK_FILE})")

if __name__ == "__main__":
    main()
