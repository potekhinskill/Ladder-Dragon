# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: persist bounded append-only SHADOW scenario evidence.
"""SQLite evidence store for multi-symbol scenario analysis."""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Sequence

from ladder_dragon.strategy.scenario_analysis import (
    ScenarioAnalysis,
    ScenarioBar,
    realized_shadow_returns,
)


D = Decimal
ZERO = D("0")
STATISTICS_WINDOW = 1_000
MINIMUM_PASS_SAMPLES = 60


class MarketScenarioStore:
    """Store derived SHADOW evidence without deleting unresolved rows."""

    def __init__(self, path: Path, *, maximum_snapshots: int = 250_000) -> None:
        if maximum_snapshots < 1_000:
            raise ValueError("maximum_snapshots must be at least 1000")
        self.path = Path(path)
        self.maximum_snapshots = maximum_snapshots
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS market_scenario_snapshots(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id TEXT NOT NULL UNIQUE,
                    symbol TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    as_of_open_ms INTEGER NOT NULL,
                    as_of_close_ms INTEGER NOT NULL,
                    created_at_ms INTEGER NOT NULL,
                    entry_price_text TEXT NOT NULL,
                    shadow_action TEXT NOT NULL,
                    analysis_json TEXT NOT NULL,
                    mode TEXT NOT NULL CHECK(mode='SHADOW'),
                    apply_allowed INTEGER NOT NULL CHECK(apply_allowed=0),
                    UNIQUE(symbol,timeframe,as_of_open_ms)
                );
                CREATE INDEX IF NOT EXISTS market_scenario_scope_sequence
                ON market_scenario_snapshots(symbol,timeframe,sequence DESC);
                CREATE TABLE IF NOT EXISTS market_scenario_outcomes(
                    snapshot_id TEXT PRIMARY KEY,
                    resolved_at_ms INTEGER NOT NULL,
                    outcome_open_ms INTEGER NOT NULL,
                    outcome_close_ms INTEGER NOT NULL,
                    exit_price_text TEXT NOT NULL,
                    candidate_net_return_text TEXT NOT NULL,
                    baseline_net_return_text TEXT NOT NULL,
                    edge_text TEXT NOT NULL,
                    FOREIGN KEY(snapshot_id) REFERENCES market_scenario_snapshots(snapshot_id)
                );
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @staticmethod
    def snapshot_id(analysis: ScenarioAnalysis) -> str:
        identity = (
            f"{analysis.engine_version}|{analysis.symbol}|{analysis.timeframe}|"
            f"{analysis.as_of_open_ms}|{analysis.as_of_close_ms}"
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def record(self, analysis: ScenarioAnalysis, *, created_at_ms: int) -> str:
        """Insert one immutable snapshot or return its existing identity."""
        snapshot_id = self.snapshot_id(analysis)
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT snapshot_id FROM market_scenario_snapshots WHERE snapshot_id=?",
                (snapshot_id,),
            ).fetchone()
            if existing:
                return str(existing[0])
            count = int(connection.execute(
                "SELECT COUNT(*) FROM market_scenario_snapshots"
            ).fetchone()[0])
            if count >= self.maximum_snapshots:
                raise RuntimeError("market scenario evidence capacity reached")
            connection.execute(
                """INSERT INTO market_scenario_snapshots(
                       snapshot_id,symbol,timeframe,as_of_open_ms,as_of_close_ms,
                       created_at_ms,entry_price_text,shadow_action,analysis_json,
                       mode,apply_allowed
                   ) VALUES(?,?,?,?,?,?,?,?,?,'SHADOW',0)""",
                (
                    snapshot_id,
                    analysis.symbol,
                    analysis.timeframe,
                    analysis.as_of_open_ms,
                    analysis.as_of_close_ms,
                    int(created_at_ms),
                    format(analysis.current_price, "f"),
                    analysis.shadow_action,
                    json.dumps(analysis.as_dict(), sort_keys=True, separators=(",", ":")),
                ),
            )
        return snapshot_id

    def settle(
        self,
        *,
        symbol: str,
        timeframe: str,
        bars: Sequence[ScenarioBar],
        round_trip_cost_pct: Decimal,
    ) -> int:
        """Resolve only the exact next closed candle after each snapshot."""
        positions = {bar.open_time_ms: index for index, bar in enumerate(bars)}
        settled = 0
        with self._connect() as connection:
            pending = connection.execute(
                """SELECT s.snapshot_id,s.as_of_open_ms,s.entry_price_text,
                          s.shadow_action
                   FROM market_scenario_snapshots AS s
                   LEFT JOIN market_scenario_outcomes AS o
                     ON o.snapshot_id=s.snapshot_id
                   WHERE s.symbol=? AND s.timeframe=? AND o.snapshot_id IS NULL
                   ORDER BY s.sequence LIMIT 1000""",
                (symbol, timeframe),
            ).fetchall()
            for snapshot_id, open_ms, entry_text, action in pending:
                index = positions.get(int(open_ms))
                if index is None or index + 1 >= len(bars):
                    continue
                outcome = bars[index + 1]
                candidate, baseline, edge = realized_shadow_returns(
                    action=str(action),
                    entry_price=D(str(entry_text)),
                    exit_price=outcome.close,
                    round_trip_cost_pct=round_trip_cost_pct,
                )
                connection.execute(
                    """INSERT OR IGNORE INTO market_scenario_outcomes(
                           snapshot_id,resolved_at_ms,outcome_open_ms,outcome_close_ms,
                           exit_price_text,candidate_net_return_text,
                           baseline_net_return_text,edge_text
                       ) VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        snapshot_id,
                        outcome.close_time_ms,
                        outcome.open_time_ms,
                        outcome.close_time_ms,
                        format(outcome.close, "f"),
                        format(candidate, "f"),
                        format(baseline, "f"),
                        format(edge, "f"),
                    ),
                )
                settled += 1
        return settled

    @staticmethod
    def _metric(values: Sequence[Decimal]) -> dict[str, object]:
        if not values:
            return {"mean": None, "ci95_lower": None}
        count = D(len(values))
        mean = sum(values, ZERO) / count
        if len(values) < 2:
            lower = None
        else:
            variance = sum((value - mean) ** 2 for value in values) / D(len(values) - 1)
            lower = mean - D("1.96") * (variance / count).sqrt()
        return {
            "mean": format(mean, "f"),
            "ci95_lower": format(lower, "f") if lower is not None else None,
        }

    def statistics(self, *, symbol: str, timeframe: str) -> dict[str, object]:
        """Calculate bounded chronological statistics for one symbol and timeframe."""
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT o.candidate_net_return_text,o.edge_text
                   FROM market_scenario_snapshots AS s
                   JOIN market_scenario_outcomes AS o ON o.snapshot_id=s.snapshot_id
                   WHERE s.symbol=? AND s.timeframe=?
                   ORDER BY s.sequence DESC LIMIT ?""",
                (symbol, timeframe, STATISTICS_WINDOW),
            ).fetchall()
            pending = int(connection.execute(
                """SELECT COUNT(*) FROM market_scenario_snapshots AS s
                   LEFT JOIN market_scenario_outcomes AS o ON o.snapshot_id=s.snapshot_id
                   WHERE s.symbol=? AND s.timeframe=? AND o.snapshot_id IS NULL""",
                (symbol, timeframe),
            ).fetchone()[0])
        candidate = [D(str(row[0])) for row in rows]
        edges = [D(str(row[1])) for row in rows]
        expectancy = self._metric(candidate)
        edge = self._metric(edges)
        passed = bool(
            len(rows) >= MINIMUM_PASS_SAMPLES
            and expectancy["ci95_lower"] is not None
            and edge["ci95_lower"] is not None
            and D(str(expectancy["ci95_lower"])) > ZERO
            and D(str(edge["ci95_lower"])) > ZERO
        )
        return {
            "resolved": len(rows),
            "pending": pending,
            "window_limit": STATISTICS_WINDOW,
            "minimum_pass_samples": MINIMUM_PASS_SAMPLES,
            "expectancy_after_costs": expectancy,
            "edge_vs_always_long": edge,
            "status": "PASS" if passed else "COLLECTING",
            "apply_allowed": False,
        }
