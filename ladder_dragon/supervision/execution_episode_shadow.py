# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: collect sequential promotion episodes from sanitized public data.
"""Online SHADOW adapter for compact execution episodes."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import sqlite3
from typing import Mapping, Sequence

from ladder_dragon.execution.exchange_math import (
    exact_symbol_filters,
    round_step,
)
from ladder_dragon.strategy.market_replay import BookLevel, MarketEvent
from ladder_dragon.strategy.prediction.episode_evidence import (
    load_episode_results,
    model_validation_status,
    record_episode_result,
    record_episode_start,
    recover_interrupted_episodes,
    sequential_episode_report,
)
from ladder_dragon.strategy.prediction.entry_diagnostics import (
    EntryApproachTracker,
    advance_entry_diagnostics,
    entry_diagnostic_report,
    start_entry_diagnostic,
)
from ladder_dragon.strategy.prediction.execution_episode import (
    ExecutionEpisode,
    ExecutionEpisodeSpec,
)
from ladder_dragon.strategy.prediction.experiment_config import (
    ShadowExperimentSpec,
)
from ladder_dragon.strategy.prediction.episode_semantics import (
    V21_EXECUTABLE_ENTRY_REGIMES,
    evidence_semantics_fingerprint,
    execution_model_contract,
)
from ladder_dragon.strategy.prediction.experiment_lifecycle import (
    list_experiments,
    variant_fingerprints,
)
from ladder_dragon.strategy.prediction.experiments import ShadowVariant
from ladder_dragon.strategy.prediction.models import PredictionFeatures
from ladder_dragon.strategy.prediction.runtime import PredictionShadowStore


D = Decimal
ZERO = D("0")


@dataclass
class _ActiveEpisode:
    episode: ExecutionEpisode
    approach: EntryApproachTracker


_ACTIVE: dict[str, _ActiveEpisode] = {}
_RECOVERED: set[str] = set()


def _generation_manifest(
    store: PredictionShadowStore, *, symbol: str, generation: str
) -> Mapping[str, object] | None:
    rows = [
        row for row in list_experiments(store, symbol=symbol)
        if row.get("generation") == generation
    ]
    if len(rows) > 1:
        raise ValueError("promotion generation has multiple manifests")
    return rows[0] if rows else None


def _decimal(value: object, *, field: str) -> Decimal:
    try:
        parsed = D(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be finite")
    return parsed


def _levels(raw: object, *, reverse: bool) -> tuple[BookLevel, ...]:
    if not isinstance(raw, list):
        raise ValueError("execution episode book side is unavailable")
    levels = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            raise ValueError("execution episode book level is invalid")
        price = _decimal(item[0], field="book price")
        quantity = _decimal(item[1], field="book quantity")
        if price <= 0 or quantity < 0:
            raise ValueError("execution episode book level is invalid")
        if quantity > 0:
            levels.append(BookLevel(price, quantity))
    return tuple(sorted(levels, key=lambda item: item.price, reverse=reverse))


def _event(
    *,
    timestamp_ms: int,
    depth: Mapping[str, object],
    trades: Sequence[Mapping[str, object]],
    interval_start_ms: int,
) -> MarketEvent:
    normalized_trades = []
    previous_id: int | None = None
    for row in trades:
        trade_id = int(row.get("a", -1))
        trade_ts = int(row.get("T", 0))
        if not interval_start_ms < trade_ts <= timestamp_ms:
            continue
        if previous_id is not None and trade_id != previous_id + 1:
            raise ValueError("aggregate trade sequence is incomplete")
        previous_id = trade_id
        normalized_trades.append((
            _decimal(row.get("p"), field="trade price"),
            _decimal(row.get("q"), field="trade quantity"),
            "SELL" if bool(row.get("m")) else "BUY",
        ))
    return MarketEvent(
        ts_ms=int(timestamp_ms),
        bids=_levels(depth.get("bids"), reverse=True),
        asks=_levels(depth.get("asks"), reverse=False),
        trades=tuple(normalized_trades),
        event_type="minutePublicEvidence",
    )


def _episode_spec(
    *,
    symbol: str,
    generation: ShadowExperimentSpec,
    variant: ShadowVariant,
    features: PredictionFeatures,
    execution_regime: str | None = None,
    filters: Mapping[str, object],
    criteria: Mapping[str, object] | None = None,
) -> ExecutionEpisodeSpec:
    exact = exact_symbol_filters(filters)
    if exact is None:
        raise ValueError("exact exchange filters are unavailable")
    plan = variant.plan
    model = execution_model_contract()
    if plan.entry_ttl_sec is None or plan.maximum_holding_min is None:
        raise ValueError("promotion candidate timing is unavailable")
    entry = round_step(plan.entry_price, exact.tick, "floor")
    target = round_step(plan.take_profit_price, exact.tick, "ceil")
    stop_limit = round_step(plan.stop_price, exact.tick, "floor")
    stop_trigger = round_step(
        stop_limit * (D("1") + plan.stop_limit_offset_pct),
        exact.tick,
        "ceil",
    )
    quantity = round_step(plan.notional_quote / entry, exact.step, "floor")
    if (
        quantity < exact.minimum_quantity
        or quantity * entry < exact.minimum_notional
    ):
        raise ValueError("promotion episode is below exchange minimum")
    fingerprints = variant_fingerprints(
        variant,
        generation=generation.generation,
        horizons_min=generation.horizons_min,
        criteria=criteria,
    )
    candidate_fingerprint = fingerprints[0]
    identity = (
        f"{symbol.upper()}:{generation.generation}:{variant.variant_id}:"
        f"{features.snapshot_ts_ms}:{candidate_fingerprint}"
    )
    episode_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    start = int(features.snapshot_ts_ms)
    return ExecutionEpisodeSpec(
        episode_id=episode_id,
        symbol=symbol.upper(),
        generation=generation.generation,
        variant_id=variant.variant_id,
        candidate_fingerprint=candidate_fingerprint,
        execution_model_rule=generation.execution_model_rule,
        evidence_semantics_fingerprint=evidence_semantics_fingerprint(),
        start_regime=execution_regime or features.regime,
        started_at_ms=start,
        entry_deadline_ms=start + plan.entry_ttl_sec * 1_000,
        diagnostic_at_ms=start + 300 * 60_000,
        primary_deadline_ms=start + plan.maximum_holding_min * 60_000,
        entry_price=entry,
        take_profit_price=target,
        stop_trigger_price=stop_trigger,
        stop_limit_price=stop_limit,
        quantity=quantity,
        maker_buy_fee_pct=(
            plan.maker_buy_fee_pct
            if plan.maker_buy_fee_pct is not None else plan.fee_pct
        ),
        maker_sell_fee_pct=(
            plan.maker_sell_fee_pct
            if plan.maker_sell_fee_pct is not None else plan.fee_pct
        ),
        taker_buy_fee_pct=(
            plan.taker_buy_fee_pct
            if plan.taker_buy_fee_pct is not None else plan.fee_pct
        ),
        taker_sell_fee_pct=(
            plan.taker_sell_fee_pct
            if plan.taker_sell_fee_pct is not None else plan.fee_pct
        ),
        latency_ms=int(model["latency_ms"]),
        market_impact_bps=D(str(model["emergency_market_impact_bps"])),
        stop_unfilled_grace_ms=int(model["stop_unfilled_grace_ms"]),
        maximum_event_gap_ms=int(model["maximum_event_gap_ms"]),
    )


def collect_execution_episode(
    store: PredictionShadowStore,
    *,
    symbol: str,
    generation: ShadowExperimentSpec,
    variants: Sequence[ShadowVariant],
    features: PredictionFeatures,
    execution_regime: str | None = None,
    depth: Mapping[str, object],
    trades: Sequence[Mapping[str, object]],
    trades_complete: bool,
    filters: Mapping[str, object],
) -> dict[str, object]:
    """Advance one episode, then start the next only after a later interval."""
    normalized = symbol.upper()
    evidence_regime = execution_regime or features.regime
    if generation.lifecycle_mode != "PROMOTION":
        return {
            "status": "DIAGNOSTIC_ONLY",
            "execution_model_status": "NOT_PROMOTION_ELIGIBLE",
        }
    if normalized != "SOLUSDT" or len(variants) != 1:
        raise ValueError("promotion episode scope requires one SOL candidate")
    if normalized not in _RECOVERED:
        recover_interrupted_episodes(
            store,
            symbol=normalized,
            now_ms=features.snapshot_ts_ms,
        )
        _RECOVERED.add(normalized)

    manifest = _generation_manifest(
        store, symbol=normalized, generation=generation.generation
    )
    current_fingerprint = variant_fingerprints(
        variants[0],
        generation=generation.generation,
        horizons_min=generation.horizons_min,
        criteria=(manifest.get("criteria") if manifest is not None else None),
    )[0]
    if (
        manifest is not None
        and current_fingerprint != manifest.get("candidate_fingerprint")
    ):
        raise ValueError("promotion candidate differs from frozen manifest")
    if manifest is not None:
        parameters = manifest.get("candidate_parameters")
        if (
            not isinstance(parameters, Mapping)
            or parameters.get("evidence_semantics_fingerprint")
            != evidence_semantics_fingerprint()
        ):
            raise ValueError("promotion evidence semantics differ from manifest")
    frozen_regimes = (
        tuple(manifest.get("criteria", {}).get("eligible_regimes", ()))
        if manifest is not None
        and isinstance(manifest.get("criteria"), Mapping)
        else V21_EXECUTABLE_ENTRY_REGIMES
    )
    if not frozen_regimes:
        raise ValueError("promotion entry regime scope is unavailable")

    event = _event(
        timestamp_ms=features.snapshot_ts_ms,
        depth=depth,
        trades=trades,
        interval_start_ms=features.snapshot_ts_ms - 60_000,
    )
    diagnostic_error: str | None = None
    try:
        advance_entry_diagnostics(store, symbol=normalized, event=event)
    except (ArithmeticError, RuntimeError, ValueError, sqlite3.Error) as exc:
        # Entry diagnostics are derived SHADOW evidence. They cannot stop the
        # frozen v22 episode or alter any promotion decision.
        diagnostic_error = type(exc).__name__
    active = _ACTIVE.get(normalized)
    terminal_this_interval = False
    if active is not None:
        entry_before = active.episode.entry_quantity
        result = (
            active.episode.process(
                event, panic_active=evidence_regime == "PANIC"
            )
            if trades_complete
            else active.episode.abort(
                features.snapshot_ts_ms, "INCOMPLETE_TRADE_PAGE"
            )
        )
        if (
            entry_before <= ZERO
            and active.episode.entry_quantity > ZERO
        ):
            try:
                start_entry_diagnostic(
                    store,
                    episode_id=active.episode.spec.episode_id,
                    symbol=normalized,
                    generation=generation.generation,
                    candidate_fingerprint=(
                        active.episode.spec.candidate_fingerprint
                    ),
                    average_entry_price=(
                        active.episode.entry_cost
                        / active.episode.entry_quantity
                    ),
                    event=event,
                    # The tracker excludes this fill interval. This prevents
                    # trade flow observed after the fill from leaking backward.
                    approach=active.approach.snapshot(
                        fill_ts_ms=features.snapshot_ts_ms
                    ),
                )
            except (
                ArithmeticError, RuntimeError, ValueError, sqlite3.Error
            ) as exc:
                diagnostic_error = type(exc).__name__
        elif result is None and active.episode.entry_quantity <= ZERO:
            active.approach.observe(event)
        if result is not None:
            record_episode_result(store, result)
            _ACTIVE.pop(normalized, None)
            terminal_this_interval = True

    if (
        not terminal_this_interval
        and normalized not in _ACTIVE
        # Collect only regimes that the immutable CHAMPION can execute.
        and evidence_regime in frozen_regimes
        and trades_complete
        and (
            manifest is None
            or (
                manifest.get("current_status") == "CONFIRMING"
                and features.snapshot_ts_ms
                <= int(manifest["confirmation_deadline_ts_ms"])
            )
        )
    ):
        spec = _episode_spec(
            symbol=normalized,
            generation=generation,
            variant=variants[0],
            features=features,
            execution_regime=evidence_regime,
            filters=filters,
            criteria=(
                manifest.get("criteria") if manifest is not None else None
            ),
        )
        episode = ExecutionEpisode(spec, event)
        record_episode_start(store, spec)
        if episode.result is not None:
            record_episode_result(store, episode.result)
        else:
            _ACTIVE[normalized] = _ActiveEpisode(
                episode=episode,
                approach=EntryApproachTracker.from_seed(event),
            )

    results = load_episode_results(
        store,
        symbol=normalized,
        generation=generation.generation,
        variant_id=variants[0].variant_id,
        started_after_ms=(
            int(manifest["confirmation_start_ts_ms"])
            if manifest is not None else None
        ),
        candidate_fingerprint=(
            str(manifest["candidate_fingerprint"])
            if manifest is not None else None
        ),
        execution_model_rule=generation.execution_model_rule,
    )
    report = sequential_episode_report(
        results,
        criteria=(manifest.get("criteria") if manifest is not None else None),
    )
    if manifest is not None and isinstance(
        manifest.get("candidate_parameters"), Mapping
    ):
        try:
            report["entry_quality_diagnostics"] = entry_diagnostic_report(
                store,
                symbol=normalized,
                generation=generation.generation,
                candidate_fingerprint=str(manifest["candidate_fingerprint"]),
                cutoff_ts_ms=features.snapshot_ts_ms,
                target_return=D(str(
                    manifest["candidate_parameters"]["target_return"]
                )),
                candidate_parameters=manifest["candidate_parameters"],
            )
        except (ArithmeticError, RuntimeError, ValueError, sqlite3.Error) as exc:
            diagnostic_error = diagnostic_error or type(exc).__name__
    if diagnostic_error is not None:
        report["entry_quality_diagnostics"] = {
            "status": "DEGRADED",
            "reason_code": diagnostic_error,
            "mode": "SHADOW",
            "can_change_orders": False,
            "affects_v22_promotion": False,
        }
    if manifest is None:
        report["status"] = "AWAITING_BOOTSTRAP"
        report["approved"] = False
        report["readiness_reason"] = (
            "operator must freeze the preregistered candidate"
        )
    elif (
        features.snapshot_ts_ms > int(manifest["confirmation_deadline_ts_ms"])
        and report.get("status") != "PASS"
    ):
        report["status"] = "READY_TO_REJECT"
        report["approved"] = False
        report["readiness_reason"] = (
            "preregistered confirmation deadline expired"
        )
    validation = model_validation_status(
        store,
        symbol=normalized,
        execution_model_rule=generation.execution_model_rule,
        expected_fee_schedule={
            "maker_buy_fee_pct": variants[0].plan.maker_buy_fee_pct,
            "maker_sell_fee_pct": variants[0].plan.maker_sell_fee_pct,
            "taker_buy_fee_pct": variants[0].plan.taker_buy_fee_pct,
            "taker_sell_fee_pct": variants[0].plan.taker_sell_fee_pct,
        },
        expected_candidate_parameters=(
            manifest.get("candidate_parameters")
            if isinstance(manifest, Mapping) else None
        ),
    )
    report.update({
        "mode": "SHADOW",
        "can_change_orders": False,
        "generation": generation.generation,
        "variant_id": variants[0].variant_id,
        "execution_model_rule": generation.execution_model_rule,
        "active_episode": normalized in _ACTIVE,
        "compact_terminal_records": len(results),
        "raw_l2_retained": False,
        "experiment_id": (
            manifest.get("experiment_id") if manifest is not None else None
        ),
        "experiment_lifecycle_status": (
            manifest.get("current_status") if manifest is not None
            else "PRESELECTED"
        ),
        "model_validation": validation,
        "execution_model_projected_ready_ts_ms": (
            features.snapshot_ts_ms if validation.get("status") == "PASS" else None
        ),
        "champion_projected_ready_ts_ms": (
            features.snapshot_ts_ms
            if report.get("approved") and validation.get("status") == "PASS"
            else None
        ),
    })
    report["promotion_eligible"] = bool(
        report.get("approved")
        and report["model_validation"].get("status") == "PASS"
        and manifest is not None
        and manifest.get("current_status") == "CONFIRMED"
    )
    return report


__all__ = ["collect_execution_episode"]
