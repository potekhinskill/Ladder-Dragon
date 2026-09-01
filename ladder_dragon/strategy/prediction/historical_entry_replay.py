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
MAXIMUM_BATCH_POLICIES = 64


def historical_entry_replays(
    events: Iterable[MarketEvent],
    *,
    jobs: list[tuple[dict, list[dict]]],
    start_ms: int,
    entry_end_ms: int,
    end_ms: int,
    cutoff_ms: int,
) -> list[dict]:
    """Replay many policies in one verified pass over the unchanged stream."""
    if not 1 <= len(jobs) <= MAXIMUM_BATCH_POLICIES:
        raise ValueError("historical replay policy batch is invalid")
    states = []
    for policy_payload, context_rows in jobs:
        policy = HistoricalPolicy.parse(policy_payload)
        states.append({
            "payload": policy_payload,
            "policy": policy,
            "context_rows": context_rows,
            "context": HistoricalContext(context_rows, policy, cutoff_ms),
            "signal": RollingVeto(policy),
            "active": {"baseline": None, "veto": None},
            "next_at": {"baseline": start_ms, "veto": start_ms},
            "results": {"baseline": [], "veto": []},
            "attempts": {"baseline": 0, "veto": 0},
        })
    if any(type(value) is not int for value in (start_ms, entry_end_ms, end_ms, cutoff_ms)):
        raise ValueError("historical window timestamps must be integers")
    if not 0 < start_ms < entry_end_ms < end_ms <= cutoff_ms:
        raise ValueError("historical replay window is invalid")
    for state in states:
        policy = state["policy"]
        if end_ms - entry_end_ms < policy.holding_ms + policy.cancel_latency_ms:
            raise ValueError("historical replay lacks its full terminal observation tail")
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
        if previous is not None and any(
            event.ts_ms - previous > state["policy"].maximum_event_gap_ms
            for state in states
        ):
            raise ValueError("historical market data gap")
        previous = event.ts_ms
        first_seen = event.ts_ms if first_seen is None else first_seen
        last_seen = event.ts_ms
        for state in states:
            policy = state["policy"]
            if event.ts_ms < start_ms - policy.signal_window_ms:
                continue
            triggered = state["signal"].update(event)
            if event.ts_ms < start_ms:
                continue
            row = state["context"].at(event.ts_ms)
            for name in state["active"]:
                episode = state["active"][name]
                if episode is not None:
                    terminal = episode.process(
                        event,
                        veto=triggered is True and name == "veto",
                        panic=row["panic"],
                    )
                    if terminal is not None:
                        state["results"][name].append(terminal)
                        state["active"][name] = None
                        # A terminal event cannot create a new entry at the same event.
                        state["next_at"][name] = max(
                            state["next_at"][name],
                            (event.ts_ms // policy.cadence_ms + 1)
                            * policy.cadence_ms,
                        )
                if (
                    state["active"][name] is None
                    and event.ts_ms >= state["next_at"][name]
                    and event.ts_ms < entry_end_ms
                    and triggered is not None
                    and not row["panic"]
                    and row["regime"] in policy.allowed_regimes
                ):
                    if state["attempts"][name] >= policy.maximum_attempts:
                        # The preregistered cap is a trial boundary, not an
                        # error. Later market events cannot add another trial.
                        state["next_at"][name] = entry_end_ms
                        continue
                    state["attempts"][name] += 1
                    episode = HistoricalExecution(
                        event,
                        policy,
                        row,
                        f"{name}-{state['attempts'][name]}",
                    )
                    state["next_at"][name] = (
                        event.ts_ms // policy.cadence_ms + 1
                    ) * policy.cadence_ms
                    if episode.result is not None:
                        state["results"][name].append(episode.result)
                    else:
                        state["active"][name] = episode
    if last_seen is None:
        raise ValueError("historical terminal observation tail is incomplete")
    source_files = [Path(__file__), Path(__file__).with_name("historical_execution.py"),
                    Path(__file__).with_name("historical_policy.py"),
                    Path(__file__).parents[1] / "market_replay.py"]
    model_sources = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source_files
    }
    reports = []
    for state in states:
        policy = state["policy"]
        if first_seen is None or first_seen > start_ms - policy.signal_window_ms:
            raise ValueError("historical signal warmup is incomplete")
        if last_seen < end_ms - policy.maximum_event_gap_ms:
            raise ValueError("historical terminal observation tail is incomplete")
        for name, episode in state["active"].items():
            if episode is not None:
                state["results"][name].append(
                    episode.finish(last_seen, "CENSORED_HISTORY", censored=True)
                )
        results = state["results"]
        attempts = state["attempts"]
        censored = any(
            row["censored"] for rows in results.values() for row in rows
        )
        summaries = {
            name: {
                "opportunities": attempts[name],
                "filled": sum(
                    Decimal(row["entry_filled_quantity"]) > 0 for row in rows
                ),
                "net_pnl_quote": str(sum(
                    (
                        Decimal(row["net_pnl_quote"])
                        for row in rows if not row["censored"]
                    ),
                    Decimal("0"),
                )),
                "censored": sum(row["censored"] for row in rows),
            }
            for name, rows in results.items()
        }
        policy_payload = state["payload"]
        context_rows = state["context_rows"]
        reports.append({
            "schema_version": 1, "model_contract": MODEL_CONTRACT,
            "status": "INCOMPLETE_HISTORY" if censored else "COMPLETE_SELECTION_REPLAY",
            "mode": "SHADOW", "apply_allowed": False, "promotion_eligible": False,
            "selection_artifact_ready": False,
            "model_source_sha256s": model_sources,
            "remaining_gates": ["independent time-block selection", "live runtime parity", "independent confirmation"],
            "policy": policy_payload, "policy_sha256": fingerprint(policy_payload),
            "context_sha256": fingerprint({"rows": context_rows}),
            "start_ts_ms": start_ms, "entry_end_ts_ms": entry_end_ms,
            "end_ts_ms": end_ms, "cutoff_ts_ms": cutoff_ms,
            "summaries": summaries, "episodes": results,
        })
    return reports


def historical_entry_replay(events: Iterable[MarketEvent], *, policy_payload: dict,
                            context_rows: list[dict], start_ms: int,
                            entry_end_ms: int, end_ms: int, cutoff_ms: int) -> dict:
    """Replay one policy through the shared bounded batch engine."""
    return historical_entry_replays(
        events,
        jobs=[(policy_payload, context_rows)],
        start_ms=start_ms,
        entry_end_ms=entry_end_ms,
        end_ms=end_ms,
        cutoff_ms=cutoff_ms,
    )[0]
