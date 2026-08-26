# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: evaluate future entry vetoes from immutable public L2 archives.
"""Cutoff-safe L2 feature extraction and sequential cancel-policy replay."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from ladder_dragon.strategy.market_replay import MarketEvent, load_jsonl_archive


D = Decimal
ZERO = D("0")
ONE = D("1")
L2_FEATURE_CONTRACT = "binance_diff_depth_entry_veto_v1"
FILL_TIMESTAMP_RESOLUTION_MS = 60_000
FIXED_CANCEL_LATENCY_MS = 1_000
PREFILL_WINDOW_MS = 300_000


def _canonical(payload: Mapping[str, object]) -> str:
    return json.dumps(dict(payload), sort_keys=True, separators=(",", ":"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _top(event: MarketEvent) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    if not event.bids or not event.asks:
        raise ValueError("L2 entry-veto replay requires both book sides")
    bid = max(event.bids, key=lambda level: level.price)
    ask = min(event.asks, key=lambda level: level.price)
    if bid.price <= ZERO or ask.price <= bid.price:
        raise ValueError("L2 entry-veto replay book is invalid")
    return bid.price, bid.quantity, ask.price, ask.quantity


def _ofi_increment(
    previous: tuple[Decimal, Decimal, Decimal, Decimal],
    current: tuple[Decimal, Decimal, Decimal, Decimal],
) -> Decimal:
    """Return Cont-style best-level order-flow imbalance for one update."""
    old_bid, old_bid_qty, old_ask, old_ask_qty = previous
    bid, bid_qty, ask, ask_qty = current
    bid_flow = (
        bid_qty if bid > old_bid
        else -old_bid_qty if bid < old_bid
        else bid_qty - old_bid_qty
    )
    ask_flow = (
        -ask_qty if ask < old_ask
        else old_ask_qty if ask > old_ask
        else old_ask_qty - ask_qty
    )
    return bid_flow + ask_flow


def candidate_grid() -> tuple[dict[str, object], ...]:
    """Return the preregistered L2 selection grid for a future generation."""
    return tuple(
        {
            "candidate_id": f"p{abs(price)}_f{abs(flow)}_o{abs(ofi)}",
            "prefill_price_change_max_bps": str(price),
            "prefill_signed_trade_flow_max": format(
                -(D(flow) / D("100")), ".2f"
            ),
            "prefill_order_flow_imbalance_max": format(
                -(D(ofi) / D("100")), ".2f"
            ),
            "cancel_latency_ms": FIXED_CANCEL_LATENCY_MS,
            "minimum_signal_lead_ms": (
                FIXED_CANCEL_LATENCY_MS + FILL_TIMESTAMP_RESOLUTION_MS
            ),
        }
        for price in (5, 10, 15, 20)
        for flow in (10, 20, 30)
        for ofi in (5, 10, 20)
    )


def validate_archive(path: str | Path) -> tuple[list[MarketEvent], dict[str, object]]:
    """Load one public archive only when its sidecar proves its identity."""
    archive = Path(path)
    metadata_path = archive.with_suffix(archive.suffix + ".metadata.json")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError("L2 archive metadata is missing or invalid") from exc
    if not isinstance(metadata, dict) or metadata.get("contains_secrets") is not False:
        raise ValueError("L2 archive metadata does not prove a public source")
    actual = _sha256(archive)
    if metadata.get("archive_sha256") != actual:
        raise ValueError("L2 archive fingerprint differs from its metadata")
    events = load_jsonl_archive(archive)
    if not events:
        raise ValueError("L2 archive contains no events")
    return events, metadata


def l2_features_before_fill(
    events: Sequence[MarketEvent],
    *,
    fill_ts_ms: int,
) -> dict[str, object]:
    """Extract causal L2 and trade-flow signals before a coarse fill boundary."""
    start_ms = int(fill_ts_ms) - PREFILL_WINDOW_MS
    window = [event for event in events if start_ms <= event.ts_ms < fill_ts_ms]
    book_events = [event for event in window if event.bids and event.asks]
    if len(book_events) < 2 or book_events[0].ts_ms > start_ms + 5_000:
        raise ValueError("L2 archive does not cover the complete pre-fill window")
    first_top = _top(book_events[0])
    first_bid = first_top[0]
    previous = first_top
    ofi = ZERO
    ofi_scale = ZERO
    buy_qty = ZERO
    sell_qty = ZERO
    signals: dict[str, int] = {}
    grid = candidate_grid()
    for event in window:
        for _price, quantity, aggressor in event.trades:
            if quantity <= ZERO:
                continue
            if aggressor == "BUY":
                buy_qty += quantity
            elif aggressor == "SELL":
                sell_qty += quantity
        if not event.bids or not event.asks:
            continue
        current = _top(event)
        increment = _ofi_increment(previous, current)
        ofi += increment
        ofi_scale += abs(increment)
        previous = current
        price_bps = (current[0] / first_bid - ONE) * D("10000")
        total_trade = buy_qty + sell_qty
        signed_flow = (
            (buy_qty - sell_qty) / total_trade if total_trade > ZERO else ZERO
        )
        normalized_ofi = ofi / ofi_scale if ofi_scale > ZERO else ZERO
        for candidate in grid:
            identifier = str(candidate["candidate_id"])
            if identifier in signals or total_trade <= ZERO or ofi_scale <= ZERO:
                continue
            if (
                price_bps <= D(str(candidate["prefill_price_change_max_bps"]))
                and signed_flow <= D(str(candidate["prefill_signed_trade_flow_max"]))
                and normalized_ofi <= D(
                    str(candidate["prefill_order_flow_imbalance_max"])
                )
            ):
                signals[identifier] = int(event.ts_ms)
    final = _top(book_events[-1])
    trade_total = buy_qty + sell_qty
    return {
        "contract_version": L2_FEATURE_CONTRACT,
        "window_started_at_ms": start_ms,
        "window_ended_at_ms": int(fill_ts_ms) - 1,
        "fill_ts_ms": int(fill_ts_ms),
        "fill_timestamp_resolution_ms": FILL_TIMESTAMP_RESOLUTION_MS,
        "book_event_count": len(book_events),
        "event_count": len(window),
        "prefill_price_change_bps": format(
            (final[0] / first_bid - ONE) * D("10000"), "f"
        ),
        "prefill_signed_trade_flow": format(
            (buy_qty - sell_qty) / trade_total if trade_total > ZERO else ZERO,
            "f",
        ),
        "prefill_order_flow_imbalance": format(
            ofi / ofi_scale if ofi_scale > ZERO else ZERO, "f"
        ),
        "candidate_signal_ts_ms": signals,
    }


@dataclass(frozen=True)
class EntryVetoOpportunity:
    """One chronological opportunity used by sequential policy replay."""

    episode_id: str
    started_at_ms: int
    fill_ts_ms: int
    terminal_at_ms: int
    net_pnl_quote: Decimal
    signal_ts_ms: int | None
    fill_timestamp_resolution_ms: int = FILL_TIMESTAMP_RESOLUTION_MS


def replay_cancel_policy(
    opportunities: Iterable[EntryVetoOpportunity],
    *,
    cancel_latency_ms: int,
) -> dict[str, object]:
    """Replay one-slot execution, including cancel latency and freed capacity."""
    if cancel_latency_ms < 0:
        raise ValueError("cancel latency must be non-negative")
    available_at = -1
    retained_pnl = ZERO
    accepted = vetoed = late = skipped = 0
    retained_ids: list[str] = []
    vetoed_ids: list[str] = []
    for item in sorted(opportunities, key=lambda row: (row.started_at_ms, row.episode_id)):
        if item.started_at_ms < available_at:
            skipped += 1
            continue
        accepted += 1
        cancel_effective = (
            item.signal_ts_ms + cancel_latency_ms
            if item.signal_ts_ms is not None else None
        )
        earliest_fill = item.fill_ts_ms - item.fill_timestamp_resolution_ms
        if cancel_effective is not None and cancel_effective < earliest_fill:
            vetoed += 1
            vetoed_ids.append(item.episode_id)
            available_at = cancel_effective
            continue
        if cancel_effective is not None:
            late += 1
        retained_pnl += item.net_pnl_quote
        retained_ids.append(item.episode_id)
        available_at = item.terminal_at_ms
    return {
        "accepted_opportunities": accepted,
        "vetoed_before_possible_fill": vetoed,
        "late_cancel_signals": late,
        "skipped_while_position_active": skipped,
        "retained_net_pnl_quote": format(retained_pnl, "f"),
        "retained_episode_ids": retained_ids,
        "vetoed_episode_ids": vetoed_ids,
    }


def feature_digest(payload: Mapping[str, object]) -> str:
    """Return the stable identity of one extracted feature payload."""
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


__all__ = [
    "EntryVetoOpportunity",
    "FILL_TIMESTAMP_RESOLUTION_MS",
    "FIXED_CANCEL_LATENCY_MS",
    "L2_FEATURE_CONTRACT",
    "candidate_grid",
    "feature_digest",
    "l2_features_before_fill",
    "replay_cancel_policy",
    "validate_archive",
]
