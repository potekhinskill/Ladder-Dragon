# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: generate new historical entry opportunities after successful cancellation.
"""Paired chronological policy selection, independent of recorded live entries."""

from __future__ import annotations

from decimal import Decimal
import hashlib
from pathlib import Path
from typing import Iterable

from ladder_dragon.strategy.market_replay import MarketEvent
from ladder_dragon.strategy.prediction.historical_execution import HistoricalExecution
from ladder_dragon.strategy.prediction.historical_policy import (
    HistoricalContext, HistoricalPolicy, RollingVeto, fingerprint,
)

MODEL_CONTRACT = "historical_midpoint_fifo_cancel_selection_v1"


def historical_entry_replay(events: Iterable[MarketEvent], *, policy_payload: dict,
                            context_rows: list[dict], start_ms: int,
                            entry_end_ms: int, end_ms: int, cutoff_ms: int) -> dict:
    """Replay two independent one-slot policies over one unchanged market stream."""
    policy = HistoricalPolicy.parse(policy_payload)
    if any(type(value) is not int for value in (start_ms, entry_end_ms, end_ms, cutoff_ms)):
        raise ValueError("historical window timestamps must be integers")
    if not 0 < start_ms < entry_end_ms < end_ms <= cutoff_ms:
        raise ValueError("historical replay window is invalid")
    if end_ms - entry_end_ms < policy.holding_ms + policy.cancel_latency_ms:
        raise ValueError("historical replay lacks its full terminal observation tail")
    context = HistoricalContext(context_rows, policy, cutoff_ms)
    signal = RollingVeto(policy)
    active: dict[str, HistoricalExecution | None] = {"baseline": None, "veto": None}
    next_at = {name: start_ms for name in active}
    results: dict[str, list[dict]] = {name: [] for name in active}
    attempts = {name: 0 for name in active}
    previous = previous_input = None
    first_seen = last_seen = None
    count = 0
    for event in events:
        count += 1
        if count > 10_000_000:
            raise ValueError("historical replay event capacity reached")
        if previous_input is not None and event.ts_ms < previous_input:
            raise ValueError("historical events are not in receive order")
        previous_input = event.ts_ms
        if event.ts_ms > end_ms:
            # Continue validating the immutable source, but never use future data.
            continue
        if previous is not None and event.ts_ms - previous > policy.maximum_event_gap_ms:
            raise ValueError("historical market data gap")
        previous = event.ts_ms
        first_seen = event.ts_ms if first_seen is None else first_seen
        last_seen = event.ts_ms
        triggered = signal.update(event)
        if event.ts_ms < start_ms:
            continue
        row = context.at(event.ts_ms)
        for name in active:
            episode = active[name]
            if episode is not None:
                terminal = episode.process(event, veto=triggered is True and name == "veto", panic=row["panic"])
                if terminal is not None:
                    results[name].append(terminal)
                    active[name] = None
                    # A terminal event cannot also fill an entry created after it.
                    next_at[name] = max(next_at[name], (event.ts_ms // policy.cadence_ms + 1) * policy.cadence_ms)
            if (active[name] is None and event.ts_ms >= next_at[name]
                    and event.ts_ms < entry_end_ms and triggered is not None
                    and not row["panic"] and row["regime"] in policy.allowed_regimes):
                if attempts[name] >= policy.maximum_attempts:
                    raise ValueError("historical opportunity capacity reached")
                attempts[name] += 1
                episode = HistoricalExecution(event, policy, row, f"{name}-{attempts[name]}")
                next_at[name] = (event.ts_ms // policy.cadence_ms + 1) * policy.cadence_ms
                if episode.result is not None:
                    results[name].append(episode.result)
                else:
                    active[name] = episode
    if first_seen is None or first_seen > start_ms - policy.signal_window_ms:
        raise ValueError("historical signal warmup is incomplete")
    if last_seen is None or last_seen < end_ms - policy.maximum_event_gap_ms:
        raise ValueError("historical terminal observation tail is incomplete")
    for name, episode in active.items():
        if episode is not None:
            results[name].append(episode.finish(last_seen, "CENSORED_HISTORY", censored=True))
    censored = any(row["censored"] for rows in results.values() for row in rows)
    summaries = {
        name: {
            "opportunities": attempts[name],
            "filled": sum(Decimal(row["entry_filled_quantity"]) > 0 for row in rows),
            "net_pnl_quote": str(sum((Decimal(row["net_pnl_quote"]) for row in rows if not row["censored"]), Decimal("0"))),
            "censored": sum(row["censored"] for row in rows),
        }
        for name, rows in results.items()
    }
    source_files = [Path(__file__), Path(__file__).with_name("historical_execution.py"),
                    Path(__file__).with_name("historical_policy.py"),
                    Path(__file__).parents[1] / "market_replay.py"]
    return {
        "schema_version": 1, "model_contract": MODEL_CONTRACT,
        "status": "INCOMPLETE_HISTORY" if censored else "COMPLETE_SELECTION_REPLAY",
        "mode": "SHADOW", "apply_allowed": False, "promotion_eligible": False,
        "selection_artifact_ready": False,
        "model_source_sha256s": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files},
        "remaining_gates": ["independent time-block selection", "live runtime parity", "independent confirmation"],
        "policy": policy_payload, "policy_sha256": fingerprint(policy_payload),
        "context_sha256": fingerprint({"rows": context_rows}),
        "start_ts_ms": start_ms, "entry_end_ts_ms": entry_end_ms,
        "end_ts_ms": end_ms, "cutoff_ts_ms": cutoff_ms,
        "summaries": summaries, "episodes": results,
    }
