# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: measure post-fill entry quality without changing promotion evidence.
"""Persistent SHADOW diagnostics for adverse selection after a maker fill."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from typing import Mapping, TYPE_CHECKING

from ladder_dragon.strategy.market_replay import MarketEvent


if TYPE_CHECKING:
    from ladder_dragon.strategy.prediction.runtime import PredictionShadowStore


D = Decimal
ZERO = D("0")
ONE = D("1")
DIAGNOSTIC_CONTRACT_VERSION = "entry_path_shadow_v2"
HORIZONS_MIN = (1, 5, 15, 30, 60, 180, 360)
THRESHOLDS_BPS = (20, 40, 60, 80)
MAXIMUM_EVENT_GAP_MS = 180_000
MAXIMUM_ACTIVE_DIAGNOSTICS = 1_024
MAXIMUM_DIAGNOSTIC_SUMMARIES = 250_000
MAXIMUM_L2_FEATURES = 250_000
MAXIMUM_SELECTION_ARTIFACTS = 1_024
MINIMUM_SELECTION_ROWS = 30
MINIMUM_INDEPENDENT_SELECTION_ROWS = 12
ENTRY_VETO_CONTRACT_VERSION = "prefill_momentum_flow_v1"
L2_ENTRY_VETO_CONTRACT_VERSION = "l2_adverse_selection_cancel_v2"
PREFILL_OBSERVATION_WINDOW_MS = 300_000


def _decimal(value: object, *, field: str) -> Decimal:
    try:
        result = D(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


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
        _json_value(dict(payload)), sort_keys=True, separators=(",", ":")
    )


def _digest(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _best_bid(event: MarketEvent) -> Decimal:
    if not event.bids:
        raise ValueError("entry diagnostic requires a bid book")
    return max(level.price for level in event.bids)


def _best_ask(event: MarketEvent) -> Decimal:
    if not event.asks:
        raise ValueError("entry diagnostic requires an ask book")
    return min(level.price for level in event.asks)


def _book_imbalance(event: MarketEvent) -> Decimal:
    bid_quote = sum(
        (level.price * level.quantity for level in event.bids), ZERO
    )
    ask_quote = sum(
        (level.price * level.quantity for level in event.asks), ZERO
    )
    total = bid_quote + ask_quote
    return (bid_quote - ask_quote) / total if total > ZERO else ZERO


def _spread_bps(event: MarketEvent) -> Decimal:
    bid = _best_bid(event)
    ask = _best_ask(event)
    midpoint = (bid + ask) / D("2")
    if midpoint <= ZERO or ask < bid:
        raise ValueError("entry diagnostic spread is invalid")
    return (ask - bid) / midpoint * D("10000")


def normalize_entry_veto_rule(rule: Mapping[str, object]) -> dict[str, object]:
    """Validate and normalize one immutable future entry-veto contract."""
    version = rule.get("contract_version")
    expected = {
        "contract_version",
        "prefill_price_change_max_bps",
        "prefill_signed_trade_flow_max",
    }
    if version == L2_ENTRY_VETO_CONTRACT_VERSION:
        expected |= {
            "prefill_order_flow_imbalance_max",
            "cancel_latency_ms",
            "minimum_signal_lead_ms",
            "selection_artifact_sha256",
        }
    if set(rule) != expected:
        raise ValueError("entry-veto rule fields are invalid")
    if version not in {
        ENTRY_VETO_CONTRACT_VERSION, L2_ENTRY_VETO_CONTRACT_VERSION,
    }:
        raise ValueError("entry-veto contract version is invalid")
    price_bps = _decimal(
        rule.get("prefill_price_change_max_bps"), field="entry-veto price"
    )
    signed_flow = _decimal(
        rule.get("prefill_signed_trade_flow_max"), field="entry-veto flow"
    )
    if not D("-100") <= price_bps < ZERO:
        raise ValueError("entry-veto price threshold is outside its safe range")
    if not D("-1") <= signed_flow < ZERO:
        raise ValueError("entry-veto flow threshold is outside its safe range")
    output = {
        "contract_version": str(version),
        "prefill_price_change_max_bps": format(price_bps, "f"),
        "prefill_signed_trade_flow_max": format(signed_flow, "f"),
    }
    if version == L2_ENTRY_VETO_CONTRACT_VERSION:
        ofi = _decimal(
            rule.get("prefill_order_flow_imbalance_max"),
            field="entry-veto order-flow imbalance",
        )
        latency = rule.get("cancel_latency_ms")
        lead = rule.get("minimum_signal_lead_ms")
        artifact = str(rule.get("selection_artifact_sha256") or "")
        if not D("-1") <= ofi < ZERO:
            raise ValueError("entry-veto imbalance is outside its safe range")
        if (
            isinstance(latency, bool) or not isinstance(latency, int)
            or latency < 0 or latency > 10_000
        ):
            raise ValueError("entry-veto cancel latency is invalid")
        if (
            isinstance(lead, bool) or not isinstance(lead, int)
            or lead < latency + 60_000
        ):
            raise ValueError("entry-veto signal lead is not conservative")
        if len(artifact) != 64 or any(char not in "0123456789abcdef" for char in artifact):
            raise ValueError("entry-veto selection artifact is invalid")
        output.update({
            "prefill_order_flow_imbalance_max": format(ofi, "f"),
            "cancel_latency_ms": latency,
            "minimum_signal_lead_ms": lead,
            "selection_artifact_sha256": artifact,
        })
    return output


@dataclass
class EntryApproachTracker:
    """Keep a bounded five-minute window that ends before the fill interval."""

    samples: list[
        tuple[int, Decimal, Decimal, Decimal, Decimal, Decimal]
    ] = field(default_factory=list)

    @classmethod
    def from_seed(cls, event: MarketEvent) -> "EntryApproachTracker":
        tracker = cls()
        tracker.observe(event)
        return tracker

    def observe(self, event: MarketEvent) -> None:
        """Consume one completed interval that did not produce the fill."""
        buy_quantity = ZERO
        sell_quantity = ZERO
        for _price, quantity, aggressor in event.trades:
            if quantity <= ZERO:
                continue
            if aggressor == "BUY":
                buy_quantity += quantity
            elif aggressor == "SELL":
                sell_quantity += quantity
        self.samples.append((
            int(event.ts_ms), _best_bid(event), buy_quantity, sell_quantity,
            _book_imbalance(event), _spread_bps(event),
        ))
        cutoff = int(event.ts_ms) - PREFILL_OBSERVATION_WINDOW_MS
        self.samples[:] = [row for row in self.samples if row[0] >= cutoff]

    def snapshot(self, *, fill_ts_ms: int) -> dict[str, object]:
        """Return pre-fill values without using a later market event."""
        if not self.samples:
            raise ValueError("entry diagnostic pre-fill window is empty")
        buy_quantity = sum((row[2] for row in self.samples), ZERO)
        sell_quantity = sum((row[3] for row in self.samples), ZERO)
        total = buy_quantity + sell_quantity
        flow = (
            (buy_quantity - sell_quantity) / total
            if total > ZERO else ZERO
        )
        first = self.samples[0]
        latest = self.samples[-1]
        return {
            "prefill_window_contract": "completed_intervals_before_fill_v1",
            "approach_started_at_ms": first[0],
            "fill_ts_ms": int(fill_ts_ms),
            "prefill_duration_ms": max(0, int(fill_ts_ms) - first[0]),
            "prefill_price_change_pct": latest[1] / first[1] - ONE,
            "prefill_signed_trade_flow": flow,
            "prefill_trade_flow_available": total > ZERO,
            "prefill_book_imbalance": latest[4],
            "prefill_spread_bps": latest[5],
        }


def migrate_entry_diagnostics(connection: sqlite3.Connection) -> None:
    """Create bounded derived progress and immutable summary tables."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS prediction_entry_diagnostic_progress (
            episode_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            generation TEXT NOT NULL,
            candidate_fingerprint TEXT NOT NULL,
            fill_ts_ms INTEGER NOT NULL,
            progress_json TEXT NOT NULL,
            progress_sha256 TEXT NOT NULL,
            updated_at_ms INTEGER NOT NULL,
            FOREIGN KEY(episode_id)
                REFERENCES prediction_execution_episode_starts(episode_id)
        );
        CREATE TABLE IF NOT EXISTS prediction_entry_diagnostic_summaries (
            episode_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            generation TEXT NOT NULL,
            candidate_fingerprint TEXT NOT NULL,
            fill_ts_ms INTEGER NOT NULL,
            completed_at_ms INTEGER NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('COMPLETE','DATA_GAP')),
            summary_json TEXT NOT NULL,
            summary_sha256 TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL,
            FOREIGN KEY(episode_id)
                REFERENCES prediction_execution_episode_starts(episode_id)
        );
        CREATE INDEX IF NOT EXISTS prediction_entry_diagnostic_cohort
            ON prediction_entry_diagnostic_summaries(
                symbol,generation,completed_at_ms
            );
        CREATE TABLE IF NOT EXISTS prediction_entry_l2_features (
            episode_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            generation TEXT NOT NULL,
            candidate_fingerprint TEXT NOT NULL,
            fill_ts_ms INTEGER NOT NULL,
            archive_sha256 TEXT NOT NULL,
            feature_json TEXT NOT NULL,
            feature_sha256 TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL,
            FOREIGN KEY(episode_id)
                REFERENCES prediction_execution_episode_starts(episode_id)
        );
        CREATE INDEX IF NOT EXISTS prediction_entry_l2_feature_cohort
            ON prediction_entry_l2_features(
                symbol,generation,fill_ts_ms
            );
        CREATE TABLE IF NOT EXISTS prediction_entry_veto_selection_artifacts (
            artifact_sha256 TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            generation TEXT NOT NULL,
            candidate_fingerprint TEXT NOT NULL,
            cutoff_ts_ms INTEGER NOT NULL,
            artifact_json TEXT NOT NULL,
            created_at_ms INTEGER NOT NULL,
            UNIQUE(symbol,generation,candidate_fingerprint)
        );
        CREATE TRIGGER IF NOT EXISTS prediction_entry_summary_no_update
        BEFORE UPDATE ON prediction_entry_diagnostic_summaries
        BEGIN SELECT RAISE(ABORT, 'entry diagnostic summaries are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS prediction_entry_summary_no_delete
        BEFORE DELETE ON prediction_entry_diagnostic_summaries
        BEGIN SELECT RAISE(ABORT, 'entry diagnostic summaries are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS prediction_entry_l2_feature_no_update
        BEFORE UPDATE ON prediction_entry_l2_features
        BEGIN SELECT RAISE(ABORT, 'entry L2 features are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS prediction_entry_l2_feature_no_delete
        BEFORE DELETE ON prediction_entry_l2_features
        BEGIN SELECT RAISE(ABORT, 'entry L2 features are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS prediction_entry_veto_artifact_no_update
        BEFORE UPDATE ON prediction_entry_veto_selection_artifacts
        BEGIN SELECT RAISE(ABORT, 'entry veto selection is immutable'); END;
        CREATE TRIGGER IF NOT EXISTS prediction_entry_veto_artifact_no_delete
        BEFORE DELETE ON prediction_entry_veto_selection_artifacts
        BEGIN SELECT RAISE(ABORT, 'entry veto selection is append-only'); END;
        """
    )


def import_entry_veto_l2_archive(
    store: "PredictionShadowStore", archive_path: str | Path
) -> dict[str, object]:
    """Attach causal public L2 features to covered terminal filled paths."""
    from ladder_dragon.strategy.prediction.entry_veto_replay import (
        feature_digest,
        l2_features_before_fill,
        validate_archive,
    )

    events, metadata = validate_archive(archive_path)
    symbol = str(metadata.get("symbol") or "").upper()
    archive_hash = str(metadata["archive_sha256"])
    first_ms = min(event.ts_ms for event in events)
    last_ms = max(event.ts_ms for event in events)
    with store._connect() as connection:
        raw_rows = connection.execute(
            """SELECT d.episode_id,d.generation,d.candidate_fingerprint,
                      d.fill_ts_ms,r.result_json,r.result_sha256
               FROM prediction_entry_diagnostic_summaries d
               JOIN prediction_execution_episode_results r
                 ON r.episode_id=d.episode_id
               LEFT JOIN prediction_entry_l2_features f
                 ON f.episode_id=d.episode_id
               WHERE d.symbol=? AND r.eligible_for_promotion=1
                 AND d.fill_ts_ms>=? AND d.fill_ts_ms<=?
                 AND f.episode_id IS NULL
               ORDER BY d.fill_ts_ms,d.episode_id""",
            (symbol, first_ms + PREFILL_OBSERVATION_WINDOW_MS, last_ms),
        ).fetchall()
        rows = []
        for row in raw_rows:
            try:
                result = json.loads(str(row[4]))
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValueError("entry result evidence is damaged") from exc
            if (
                not isinstance(result, dict)
                or _digest(result) != str(row[5])
            ):
                raise ValueError("entry result evidence is damaged")
            if (
                result.get("eligible_for_promotion") is True
                and _decimal(
                    result.get("entry_filled_quantity", "0"), field="fill"
                ) > ZERO
            ):
                rows.append(row[:4])
        imported = 0
        skipped = 0
        for episode_id, generation, fingerprint, fill_ts_ms in rows:
            try:
                features = l2_features_before_fill(
                    events, fill_ts_ms=int(fill_ts_ms)
                )
            except ValueError:
                skipped += 1
                continue
            features.update({
                "episode_id": str(episode_id),
                "symbol": symbol,
                "generation": str(generation),
                "candidate_fingerprint": str(fingerprint),
                "archive_sha256": archive_hash,
            })
            count = int(connection.execute(
                "SELECT COUNT(*) FROM prediction_entry_l2_features"
            ).fetchone()[0])
            if count >= MAXIMUM_L2_FEATURES:
                raise RuntimeError("entry L2 feature capacity reached")
            encoded = _canonical(features)
            connection.execute(
                """INSERT INTO prediction_entry_l2_features
                   (episode_id,symbol,generation,candidate_fingerprint,
                    fill_ts_ms,archive_sha256,feature_json,feature_sha256,
                    created_at_ms) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    str(episode_id), symbol, str(generation), str(fingerprint),
                    int(fill_ts_ms), archive_hash, encoded,
                    feature_digest(features), int(time.time() * 1000),
                ),
            )
            imported += 1
    return {
        "status": "PASS",
        "mode": "SHADOW",
        "archive_sha256": archive_hash,
        "covered_paths": len(rows),
        "imported_paths": imported,
        "skipped_paths": skipped,
    }


def import_entry_veto_l2_history(
    store: "PredictionShadowStore", archive_directory: str | Path
) -> dict[str, object]:
    """Attach retained archives after a terminal filled path is available."""
    root = Path(archive_directory)
    if not root.is_dir():
        raise ValueError("L2 archive directory is unavailable")

    def pending_rows() -> list[tuple[str, str, int]]:
        with store._connect() as connection:
            rows = connection.execute(
                """SELECT d.episode_id,d.symbol,d.fill_ts_ms,
                          r.result_json,r.result_sha256
                   FROM prediction_entry_diagnostic_summaries d
                   JOIN prediction_execution_episode_results r
                     ON r.episode_id=d.episode_id
                   LEFT JOIN prediction_entry_l2_features f
                     ON f.episode_id=d.episode_id
                   WHERE r.eligible_for_promotion=1
                     AND f.episode_id IS NULL
                   ORDER BY d.fill_ts_ms,d.episode_id"""
            ).fetchall()
            pending = []
            for episode_id, symbol, fill_ts_ms, raw_result, result_hash in rows:
                try:
                    result = json.loads(str(raw_result))
                except (json.JSONDecodeError, TypeError, ValueError) as exc:
                    raise ValueError("entry result evidence is damaged") from exc
                if (
                    not isinstance(result, dict)
                    or _digest(result) != str(result_hash)
                ):
                    raise ValueError("entry result evidence is damaged")
                if (
                    result.get("eligible_for_promotion") is True
                    and _decimal(
                        result.get("entry_filled_quantity", "0"), field="fill"
                    ) > ZERO
                ):
                    pending.append(
                        (str(episode_id), str(symbol), int(fill_ts_ms))
                    )
            return pending

    pending = pending_rows()
    discovered = matched = validated = imported = skipped = 0
    for metadata_path in sorted(root.glob("*.jsonl.metadata.json")):
        discovered += 1
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError("L2 history metadata is invalid") from exc
        if (
            not isinstance(metadata, dict)
            or metadata.get("contains_secrets") is not False
        ):
            raise ValueError("L2 history metadata does not prove a public source")
        symbol = str(metadata.get("symbol") or "").upper()
        try:
            started_at_ms = int(metadata["started_at_ms"])
            finished_at_ms = int(metadata["finished_at_ms"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("L2 history time bounds are invalid") from exc
        if (
            not symbol or started_at_ms < 0
            or finished_at_ms <= started_at_ms
        ):
            raise ValueError("L2 history identity is invalid")
        archive_path = Path(str(metadata_path)[:-len(".metadata.json")])
        if (
            archive_path.is_symlink() or not archive_path.is_file()
            or archive_path.resolve().parent != root.resolve()
        ):
            raise ValueError("L2 history archive path is invalid")
        covered = [
            row for row in pending
            if row[1] == symbol
            and row[2] >= started_at_ms + PREFILL_OBSERVATION_WINDOW_MS
            and row[2] <= finished_at_ms
        ]
        if not covered:
            continue
        matched += 1
        report = import_entry_veto_l2_archive(store, archive_path)
        validated += 1
        imported += int(report["imported_paths"])
        skipped += int(report["skipped_paths"])
        pending = pending_rows()
        if not pending:
            break
    return {
        "status": "PASS" if not pending else "COLLECTING",
        "mode": "SHADOW",
        "discovered_archives": discovered,
        "matched_archives": matched,
        "validated_archives": validated,
        "imported_paths": imported,
        "skipped_paths": skipped,
        "pending_terminal_filled_paths": len(pending),
    }


def start_entry_diagnostic(
    store: "PredictionShadowStore",
    *,
    episode_id: str,
    symbol: str,
    generation: str,
    candidate_fingerprint: str,
    average_entry_price: Decimal,
    event: MarketEvent,
    approach: Mapping[str, object],
) -> None:
    """Persist one restart-safe post-fill tracker without changing the episode."""
    if average_entry_price <= ZERO or not average_entry_price.is_finite():
        raise ValueError("entry diagnostic price must be positive")
    if len(candidate_fingerprint) != 64:
        raise ValueError("entry diagnostic fingerprint must be SHA-256")
    _best_bid(event)
    fill_ts_ms = int(approach.get("fill_ts_ms", event.ts_ms))
    payload = {
        "contract_version": DIAGNOSTIC_CONTRACT_VERSION,
        "episode_id": str(episode_id),
        "symbol": symbol.upper(),
        "generation": str(generation),
        "candidate_fingerprint": str(candidate_fingerprint),
        "fill_ts_ms": fill_ts_ms,
        "average_entry_price": average_entry_price,
        "last_event_ts_ms": int(event.ts_ms),
        "maximum_event_gap_ms": 0,
        # Start at the execution price. The fill interval can contain later
        # book updates, so its closing bid is not a valid zero-time sample.
        "minimum_bid": average_entry_price,
        "maximum_bid": average_entry_price,
        "horizon_samples": {},
        "threshold_hit_ms": {},
        **dict(approach),
    }
    encoded = _canonical(payload)
    now_ms = int(time.time() * 1000)
    with store._connect() as connection:
        existing = connection.execute(
            "SELECT progress_json,progress_sha256 FROM "
            "prediction_entry_diagnostic_progress WHERE episode_id=?",
            (str(episode_id),),
        ).fetchone()
        if existing is not None:
            if str(existing[0]) != encoded or str(existing[1]) != _digest(payload):
                raise ValueError("entry diagnostic start differs from stored state")
            return
        if connection.execute(
            "SELECT 1 FROM prediction_entry_diagnostic_summaries WHERE episode_id=?",
            (str(episode_id),),
        ).fetchone():
            raise ValueError("entry diagnostic is already terminal")
        active = int(connection.execute(
            "SELECT COUNT(*) FROM prediction_entry_diagnostic_progress"
        ).fetchone()[0])
        if active >= MAXIMUM_ACTIVE_DIAGNOSTICS:
            raise RuntimeError("entry diagnostic active capacity reached")
        connection.execute(
            """INSERT INTO prediction_entry_diagnostic_progress
               (episode_id,symbol,generation,candidate_fingerprint,fill_ts_ms,
                progress_json,progress_sha256,updated_at_ms)
               VALUES(?,?,?,?,?,?,?,?)""",
            (
                str(episode_id), symbol.upper(), str(generation),
                str(candidate_fingerprint), fill_ts_ms, encoded,
                _digest(payload), now_ms,
            ),
        )


def _terminal_payload(
    payload: dict[str, object], *, status: str, completed_at_ms: int
) -> dict[str, object]:
    horizons = payload.get("horizon_samples")
    if not isinstance(horizons, dict):
        raise ValueError("entry diagnostic horizons are invalid")
    missing = [str(value) for value in HORIZONS_MIN if str(value) not in horizons]
    return {
        **payload,
        "status": status,
        "completed_at_ms": int(completed_at_ms),
        "complete": status == "COMPLETE" and not missing,
        "missing_horizons_min": missing,
        "affects_promotion": False,
    }


def _finish_progress(
    connection: sqlite3.Connection,
    payload: dict[str, object],
    *,
    status: str,
    completed_at_ms: int,
) -> None:
    summary = _terminal_payload(
        payload, status=status, completed_at_ms=completed_at_ms
    )
    count = int(connection.execute(
        "SELECT COUNT(*) FROM prediction_entry_diagnostic_summaries"
    ).fetchone()[0])
    if count >= MAXIMUM_DIAGNOSTIC_SUMMARIES:
        raise RuntimeError("entry diagnostic summary capacity reached")
    connection.execute(
        """INSERT INTO prediction_entry_diagnostic_summaries
           (episode_id,symbol,generation,candidate_fingerprint,fill_ts_ms,
            completed_at_ms,status,summary_json,summary_sha256,created_at_ms)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (
            str(summary["episode_id"]), str(summary["symbol"]),
            str(summary["generation"]), str(summary["candidate_fingerprint"]),
            int(summary["fill_ts_ms"]), int(completed_at_ms), status,
            _canonical(summary), _digest(summary), int(time.time() * 1000),
        ),
    )
    connection.execute(
        "DELETE FROM prediction_entry_diagnostic_progress WHERE episode_id=?",
        (str(summary["episode_id"]),),
    )


def advance_entry_diagnostics(
    store: "PredictionShadowStore", *, symbol: str, event: MarketEvent
) -> int:
    """Advance all post-fill paths for one symbol and finalize complete paths."""
    bid = _best_bid(event)
    completed = 0
    with store._connect() as connection:
        rows = connection.execute(
            """SELECT episode_id,progress_json,progress_sha256
               FROM prediction_entry_diagnostic_progress WHERE symbol=?
               ORDER BY fill_ts_ms,episode_id""",
            (symbol.upper(),),
        ).fetchall()
        for episode_id, raw, expected_hash in rows:
            try:
                payload = json.loads(str(raw))
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValueError("entry diagnostic progress is damaged") from exc
            if not isinstance(payload, dict) or _digest(payload) != str(expected_hash):
                raise ValueError("entry diagnostic progress fingerprint differs")
            last_ts = int(payload["last_event_ts_ms"])
            if event.ts_ms <= last_ts:
                continue
            gap_ms = int(event.ts_ms) - last_ts
            payload["maximum_event_gap_ms"] = max(
                int(payload.get("maximum_event_gap_ms", 0)), gap_ms
            )
            if gap_ms > MAXIMUM_EVENT_GAP_MS:
                _finish_progress(
                    connection, payload, status="DATA_GAP",
                    completed_at_ms=int(event.ts_ms),
                )
                completed += 1
                continue
            entry = _decimal(payload["average_entry_price"], field="entry price")
            minimum = min(
                _decimal(payload["minimum_bid"], field="minimum bid"), bid
            )
            maximum = max(
                _decimal(payload["maximum_bid"], field="maximum bid"), bid
            )
            payload["minimum_bid"] = minimum
            payload["maximum_bid"] = maximum
            payload["last_event_ts_ms"] = int(event.ts_ms)
            elapsed_ms = int(event.ts_ms) - int(payload["fill_ts_ms"])
            current_return = bid / entry - ONE
            favorable = max(ZERO, maximum / entry - ONE)
            adverse = max(ZERO, ONE - minimum / entry)
            hits = payload.get("threshold_hit_ms")
            horizons = payload.get("horizon_samples")
            if not isinstance(hits, dict) or not isinstance(horizons, dict):
                raise ValueError("entry diagnostic progress shape is invalid")
            for threshold in THRESHOLDS_BPS:
                key = str(threshold)
                if key not in hits and favorable * D("10000") >= D(threshold):
                    hits[key] = elapsed_ms
            for horizon in HORIZONS_MIN:
                key = str(horizon)
                if key in horizons or elapsed_ms < horizon * 60_000:
                    continue
                horizons[key] = {
                    "observed_at_ms": int(event.ts_ms),
                    "observation_lag_ms": elapsed_ms - horizon * 60_000,
                    "current_return_pct": current_return,
                    "maximum_favorable_excursion_pct": favorable,
                    "maximum_adverse_excursion_pct": adverse,
                    "profit_giveback_pct": max(ZERO, favorable - current_return),
                }
            if elapsed_ms >= HORIZONS_MIN[-1] * 60_000:
                _finish_progress(
                    connection, payload, status="COMPLETE",
                    completed_at_ms=int(event.ts_ms),
                )
                completed += 1
                continue
            encoded = _canonical(payload)
            connection.execute(
                """UPDATE prediction_entry_diagnostic_progress
                   SET progress_json=?,progress_sha256=?,updated_at_ms=?
                   WHERE episode_id=?""",
                (
                    encoded, _digest(payload), int(time.time() * 1000),
                    str(episode_id),
                ),
            )
    return completed


def _candidate_grid() -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "candidate_id": f"drop{drop}_flow{abs(flow)}",
            "prefill_price_change_max_bps": -drop,
            "prefill_signed_trade_flow_max": format(D(-flow) / D("100"), "f"),
        }
        for drop in (5, 10, 15, 20)
        for flow in (10, 20, 30)
    )


def _vetoes(summary: Mapping[str, object], candidate: Mapping[str, object]) -> bool:
    price_bps = _decimal(
        summary["prefill_price_change_pct"], field="prefill price change"
    ) * D("10000")
    flow = _decimal(
        summary["prefill_signed_trade_flow"], field="prefill trade flow"
    )
    return bool(
        price_bps <= D(str(candidate["prefill_price_change_max_bps"]))
        and flow <= D(str(candidate["prefill_signed_trade_flow_max"]))
        and summary.get("prefill_trade_flow_available") is True
    )


def _independent_rows(
    rows: list[tuple[dict[str, object], Decimal]],
) -> list[tuple[dict[str, object], Decimal]]:
    output = []
    next_allowed = -1
    for row in sorted(rows, key=lambda item: int(item[0]["fill_ts_ms"])):
        started = int(row[0]["fill_ts_ms"])
        if started < next_allowed:
            continue
        output.append(row)
        next_allowed = started + HORIZONS_MIN[-1] * 60_000 + 1
    return output


def _three_time_blocks(
    rows: list[tuple[dict[str, object], Decimal]],
) -> tuple[list[tuple[dict[str, object], Decimal]], ...]:
    """Split chronological independent evidence into three stable blocks."""
    ordered = sorted(rows, key=lambda item: int(item[0]["fill_ts_ms"]))
    blocks: list[list[tuple[dict[str, object], Decimal]]] = [[], [], []]
    for index, row in enumerate(ordered):
        block = min(2, index * 3 // max(1, len(ordered)))
        blocks[block].append(row)
    return tuple(blocks)


def _l2_candidate_result(
    rows: list[tuple[dict[str, object], Decimal]],
    candidate: Mapping[str, object],
) -> dict[str, object]:
    """Replay one exact L2 candidate over chronological one-slot opportunities."""
    from ladder_dragon.strategy.prediction.entry_veto_replay import (
        EntryVetoOpportunity,
        replay_cancel_policy,
    )

    identifier = str(candidate["candidate_id"])
    opportunities = []
    for payload, pnl in rows:
        features = payload.get("l2_features")
        if not isinstance(features, Mapping):
            continue
        signals = features.get("candidate_signal_ts_ms")
        signal = signals.get(identifier) if isinstance(signals, Mapping) else None
        opportunities.append(EntryVetoOpportunity(
            episode_id=str(payload["episode_id"]),
            started_at_ms=int(payload["started_at_ms"]),
            fill_ts_ms=int(payload["fill_ts_ms"]),
            terminal_at_ms=int(payload["terminal_at_ms"]),
            net_pnl_quote=pnl,
            signal_ts_ms=int(signal) if signal is not None else None,
            fill_timestamp_resolution_ms=int(
                features["fill_timestamp_resolution_ms"]
            ),
        ))
    result = replay_cancel_policy(
        opportunities,
        cancel_latency_ms=int(candidate["cancel_latency_ms"]),
    )
    original = sum((row[1] for row in rows), ZERO)
    result["original_net_pnl_quote"] = format(original, "f")
    result["avoided_net_pnl_quote"] = format(
        _decimal(result["retained_net_pnl_quote"], field="retained PnL")
        - original,
        "f",
    )
    return result


def entry_diagnostic_report(
    store: "PredictionShadowStore",
    *,
    symbol: str,
    generation: str,
    candidate_fingerprint: str,
    cutoff_ts_ms: int,
    target_return: Decimal,
    candidate_parameters: Mapping[str, object],
) -> dict[str, object]:
    """Build a cutoff-safe selection report that cannot authorize execution."""
    if target_return <= ZERO or not target_return.is_finite():
        raise ValueError("entry diagnostic target return must be positive")
    with store._connect() as connection:
        rows = connection.execute(
            """SELECT d.episode_id,d.summary_json,d.summary_sha256,
                      r.result_json,r.result_sha256,s.started_at_ms,
                      r.terminal_at_ms,f.feature_json,f.feature_sha256,
                      f.archive_sha256
               FROM prediction_entry_diagnostic_summaries d
               JOIN prediction_execution_episode_results r
                 ON r.episode_id=d.episode_id
               JOIN prediction_execution_episode_starts s
                 ON s.episode_id=d.episode_id
               LEFT JOIN prediction_entry_l2_features f
                 ON f.episode_id=d.episode_id
               WHERE d.symbol=? AND d.generation=?
                 AND d.candidate_fingerprint=? AND d.completed_at_ms<=?
               ORDER BY d.fill_ts_ms,d.episode_id LIMIT 10000""",
            (
                symbol.upper(), str(generation), str(candidate_fingerprint),
                int(cutoff_ts_ms),
            ),
        ).fetchall()
        active = int(connection.execute(
            """SELECT COUNT(*) FROM prediction_entry_diagnostic_progress
               WHERE symbol=? AND generation=? AND candidate_fingerprint=?
                 AND fill_ts_ms<=?""",
            (
                symbol.upper(), str(generation), str(candidate_fingerprint),
                int(cutoff_ts_ms),
            ),
        ).fetchone()[0])
    complete: list[tuple[dict[str, object], Decimal]] = []
    terminal_filled: list[tuple[dict[str, object], Decimal]] = []
    selection_ready: list[tuple[dict[str, object], Decimal]] = []
    incomplete = 0
    cohort_identity_by_id: dict[str, dict[str, object]] = {}
    for (
        episode_id, raw_summary, summary_hash, raw_result, result_hash,
        started_at_ms, terminal_at_ms, raw_features, feature_hash, archive_hash,
    ) in rows:
        summary = json.loads(str(raw_summary))
        result = json.loads(str(raw_result))
        if (
            not isinstance(summary, dict) or _digest(summary) != str(summary_hash)
            or not isinstance(result, dict) or _digest(result) != str(result_hash)
        ):
            raise ValueError("entry diagnostic evidence is damaged")
        if (
            result.get("eligible_for_promotion") is not True
            or _decimal(result.get("entry_filled_quantity", "0"), field="fill")
            <= ZERO
        ):
            continue
        summary = dict(summary)
        summary.update({
            "episode_id": str(episode_id),
            "started_at_ms": int(started_at_ms),
            "terminal_at_ms": int(terminal_at_ms),
            "terminal_maximum_favorable_excursion_pct": result.get(
                "maximum_favorable_excursion_pct", "0"
            ),
        })
        if raw_features is not None:
            features = json.loads(str(raw_features))
            if (
                not isinstance(features, dict)
                or _digest(features) != str(feature_hash)
            ):
                raise ValueError("entry L2 feature evidence is damaged")
            summary["l2_features"] = features
        row = (summary, _decimal(result["net_pnl_quote"], field="PnL"))
        terminal_filled.append(row)
        if summary.get("complete") is True:
            complete.append(row)
        else:
            incomplete += 1
        if isinstance(summary.get("l2_features"), Mapping):
            # Veto selection uses only causal pre-fill L2 and the immutable
            # terminal strategy result. Later diagnostic gaps are unrelated.
            selection_ready.append(row)
        cohort_identity_by_id[str(episode_id)] = {
            "episode_id": str(episode_id),
            "summary_sha256": str(summary_hash),
            "result_sha256": str(result_hash),
            "l2_feature_sha256": str(feature_hash) if feature_hash else None,
            "archive_sha256": str(archive_hash) if archive_hash else None,
        }
    independent = _independent_rows(terminal_filled)
    l2_independent = _independent_rows(selection_ready)
    selection_cohort = [
        cohort_identity_by_id[str(row[0]["episode_id"])]
        for row in l2_independent
    ]
    candidates = []
    from ladder_dragon.strategy.prediction.entry_veto_replay import candidate_grid
    blocks = _three_time_blocks(l2_independent)
    for candidate in candidate_grid():
        replay = _l2_candidate_result(l2_independent, candidate)
        block_results = [
            _l2_candidate_result(block, candidate) for block in blocks if block
        ]
        vetoed = int(replay["vetoed_before_possible_fill"])
        accepted = int(replay["accepted_opportunities"])
        veto_rate = D(vetoed) / D(accepted) if accepted else ZERO
        stable_blocks = sum(
            int(item["vetoed_before_possible_fill"]) > 0
            and _decimal(item["avoided_net_pnl_quote"], field="avoided PnL") >= ZERO
            for item in block_results
        )
        selected_row = {
            **candidate,
            **replay,
            "veto_rate": format(veto_rate, "f"),
            "time_blocks": block_results,
            "stable_time_blocks": stable_blocks,
            "required_stable_time_blocks": 2,
            "selection_eligible": bool(
                len(l2_independent) >= MINIMUM_INDEPENDENT_SELECTION_ROWS
                and len(block_results) == 3
                and stable_blocks >= 2
                and D("0.05") <= veto_rate <= D("0.40")
                and _decimal(
                    replay["avoided_net_pnl_quote"], field="avoided PnL"
                ) > ZERO
                and _decimal(
                    replay["retained_net_pnl_quote"], field="retained PnL"
                ) > ZERO
            ),
        }
        candidates.append(selected_row)
    eligible = [row for row in candidates if row["selection_eligible"]]
    selected = max(
        eligible,
        key=lambda row: (
            D(str(row["retained_net_pnl_quote"])),
            D(str(row["avoided_net_pnl_quote"])),
            str(row["candidate_id"]),
        ),
        default=None,
    )
    def target_reached(payload: Mapping[str, object]) -> bool:
        if payload.get("complete") is True:
            return bool(
                _decimal(payload["maximum_bid"], field="maximum bid")
                / _decimal(payload["average_entry_price"], field="entry price")
                - ONE >= target_return
            )
        return bool(
            _decimal(
                payload["terminal_maximum_favorable_excursion_pct"],
                field="terminal favorable excursion",
            )
            >= target_return
        )

    target_hits = sum(target_reached(row[0]) for row in independent)
    economics = fee_aware_candidate_economics(
        candidate_parameters,
        target_reachability=(
            D(target_hits) / D(len(independent)) if independent else None
        ),
    )
    ready = bool(
        len(selection_ready) >= MINIMUM_SELECTION_ROWS
        and len(l2_independent) >= MINIMUM_INDEPENDENT_SELECTION_ROWS
        and selected is not None
    )
    return {
        "schema_version": 2,
        "contract_version": DIAGNOSTIC_CONTRACT_VERSION,
        "mode": "SHADOW",
        "can_change_orders": False,
        "affects_v22_promotion": False,
        "selection_cutoff_ts_ms": int(cutoff_ts_ms),
        "completed_filled_paths": len(complete),
        "independent_filled_paths": len(independent),
        "selection_filled_paths": len(selection_ready),
        "l2_independent_filled_paths": len(l2_independent),
        "incomplete_paths": incomplete,
        "active_paths": active,
        "required_selection_paths": MINIMUM_SELECTION_ROWS,
        "required_completed_paths": MINIMUM_SELECTION_ROWS,
        "required_independent_paths": MINIMUM_INDEPENDENT_SELECTION_ROWS,
        "target_reachability": economics["target_reachability"],
        "candidate_economics": economics,
        "entry_veto_candidates": candidates,
        "selection_cohort": selection_cohort,
        "selection_cohort_sha256": _digest({"rows": selection_cohort}),
        "selected_entry_veto": selected if ready else None,
        "status": "READY_TO_FREEZE_V23" if ready else "COLLECTING_SELECTION",
        "readiness_reason": (
            "one cutoff-safe L2 cancel policy is ready to freeze"
            if ready else "independent L2 selection evidence is incomplete"
        ),
    }


def freeze_entry_veto_selection(
    store: "PredictionShadowStore",
    *,
    symbol: str,
    generation: str,
    candidate_fingerprint: str,
    cutoff_ts_ms: int,
    target_return: Decimal,
    candidate_parameters: Mapping[str, object],
) -> dict[str, object]:
    """Append one immutable selection artifact after a complete L2 report."""
    report = entry_diagnostic_report(
        store,
        symbol=symbol,
        generation=generation,
        candidate_fingerprint=candidate_fingerprint,
        cutoff_ts_ms=cutoff_ts_ms,
        target_return=target_return,
        candidate_parameters=candidate_parameters,
    )
    selected = report.get("selected_entry_veto")
    if report.get("status") != "READY_TO_FREEZE_V23" or not isinstance(selected, Mapping):
        raise ValueError("entry-veto selection evidence is not ready")
    artifact = {
        "schema_version": 1,
        "mode": "SHADOW_SELECTION",
        "can_change_orders": False,
        "symbol": symbol.upper(),
        "source_generation": str(generation),
        "candidate_fingerprint": str(candidate_fingerprint),
        "cutoff_ts_ms": int(cutoff_ts_ms),
        "selection_cohort_sha256": report["selection_cohort_sha256"],
        "selection_cohort": report["selection_cohort"],
        "target_reachability": report["target_reachability"],
        "selected_rule": dict(selected),
    }
    artifact_hash = _digest(artifact)
    with store._connect() as connection:
        count = int(connection.execute(
            "SELECT COUNT(*) FROM prediction_entry_veto_selection_artifacts"
        ).fetchone()[0])
        if count >= MAXIMUM_SELECTION_ARTIFACTS:
            raise RuntimeError("entry-veto selection artifact capacity reached")
        connection.execute(
            """INSERT INTO prediction_entry_veto_selection_artifacts
               (artifact_sha256,symbol,generation,candidate_fingerprint,
                cutoff_ts_ms,artifact_json,created_at_ms)
               VALUES(?,?,?,?,?,?,?)""",
            (
                artifact_hash, symbol.upper(), str(generation),
                str(candidate_fingerprint), int(cutoff_ts_ms),
                _canonical(artifact), int(time.time() * 1000),
            ),
        )
    return {**artifact, "artifact_sha256": artifact_hash}


def latest_entry_veto_selection(
    store: "PredictionShadowStore", *, symbol: str
) -> tuple[dict[str, object], Decimal]:
    """Return the latest immutable selection rule or fail before v23 starts."""
    with store._connect() as connection:
        row = connection.execute(
            """SELECT artifact_sha256,artifact_json
               FROM prediction_entry_veto_selection_artifacts
               WHERE symbol=? ORDER BY cutoff_ts_ms DESC,created_at_ms DESC
               LIMIT 1""",
            (symbol.upper(),),
        ).fetchone()
    if row is None:
        raise ValueError("entry-veto selection artifact is unavailable")
    try:
        artifact = json.loads(str(row[1]))
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError("entry-veto selection artifact is damaged") from exc
    if not isinstance(artifact, dict) or _digest(artifact) != str(row[0]):
        raise ValueError("entry-veto selection artifact identity differs")
    selected = artifact.get("selected_rule")
    if not isinstance(selected, Mapping):
        raise ValueError("entry-veto selected rule is unavailable")
    rule = {
        "contract_version": selected.get("contract_version"),
        "prefill_price_change_max_bps": selected.get(
            "prefill_price_change_max_bps"
        ),
        "prefill_signed_trade_flow_max": selected.get(
            "prefill_signed_trade_flow_max"
        ),
        "prefill_order_flow_imbalance_max": selected.get(
            "prefill_order_flow_imbalance_max"
        ),
        "cancel_latency_ms": selected.get("cancel_latency_ms"),
        "minimum_signal_lead_ms": selected.get("minimum_signal_lead_ms"),
        "selection_artifact_sha256": str(row[0]),
    }
    normalized = normalize_entry_veto_rule(rule)
    reachability = artifact.get("target_reachability")
    if reachability is None and isinstance(
        artifact.get("selection_metrics"), Mapping
    ):
        reachability = artifact["selection_metrics"].get(
            "target_reachability"
        )
    value = _decimal(reachability, field="target reachability")
    if not ZERO <= value <= ONE:
        raise ValueError("entry-veto target reachability is invalid")
    return normalized, value


def fee_aware_candidate_economics(
    candidate_parameters: Mapping[str, object],
    *,
    target_reachability: Decimal | None,
) -> dict[str, object]:
    """Calculate conservative round-trip economics for a future manifest."""
    fees = candidate_parameters.get("fee_schedule")
    if not isinstance(fees, Mapping):
        raise ValueError("candidate fee schedule is unavailable")
    target = _decimal(candidate_parameters.get("target_return"), field="target")
    stop = _decimal(candidate_parameters.get("stop_distance"), field="stop")
    entry_fee = _decimal(fees.get("maker_buy_fee_pct"), field="entry fee")
    target_fee = _decimal(fees.get("maker_sell_fee_pct"), field="target fee")
    stop_fee = _decimal(fees.get("taker_sell_fee_pct"), field="stop fee")
    net_win = target - entry_fee - (ONE + target) * target_fee
    net_loss = stop + entry_fee + (ONE - stop) * stop_fee
    denominator = net_win + net_loss
    if net_win <= ZERO or net_loss <= ZERO or denominator <= ZERO:
        raise ValueError("candidate fee-aware economics are invalid")
    return {
        "contract_version": "fee_aware_spot_geometry_v1",
        "expected_net_win_pct": format(net_win, "f"),
        "expected_stop_loss_pct": format(-net_loss, "f"),
        "minimum_break_even_win_rate": format(net_loss / denominator, "f"),
        "target_reachability": (
            format(target_reachability, "f")
            if target_reachability is not None else None
        ),
        "target_reachability_source": (
            "cutoff_safe_completed_entry_paths"
            if target_reachability is not None else "NOT_AVAILABLE"
        ),
    }


__all__ = [
    "DIAGNOSTIC_CONTRACT_VERSION",
    "ENTRY_VETO_CONTRACT_VERSION",
    "EntryApproachTracker",
    "HORIZONS_MIN",
    "advance_entry_diagnostics",
    "entry_diagnostic_report",
    "fee_aware_candidate_economics",
    "freeze_entry_veto_selection",
    "import_entry_veto_l2_archive",
    "import_entry_veto_l2_history",
    "latest_entry_veto_selection",
    "migrate_entry_diagnostics",
    "normalize_entry_veto_rule",
    "start_entry_diagnostic",
]
