# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: audit whether real AI evidence can pass the production gate.
"""Read-only, exact AI and RAG production-readiness audit."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sqlite3


ZERO = Decimal("0")


def _decimal(item: dict, text_key: str, numeric_key: str) -> Decimal:
    value = item.get(text_key)
    if value in (None, ""):
        value = item.get(numeric_key, "0") or "0"
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"invalid AI financial field {numeric_key}") from exc
    if not result.is_finite():
        raise ValueError(f"non-finite AI financial field {numeric_key}")
    return result


@dataclass(frozen=True)
class AiReadiness:
    ready: bool
    reasons: tuple[str, ...]
    symbol: str
    closed_decisions: int
    real_rag_episodes: int
    virtual_rag_episodes: int
    unresolved_fills: int
    net_pnl_quote: Decimal
    edge_ci_low: Decimal
    edge_ci_high: Decimal
    stop_rate: Decimal

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "ready": self.ready,
            "reasons": list(self.reasons),
            "symbol": self.symbol,
            "closed_decisions": self.closed_decisions,
            "real_rag_episodes": self.real_rag_episodes,
            "virtual_rag_episodes": self.virtual_rag_episodes,
            "unresolved_fills": self.unresolved_fills,
            "net_pnl_quote": format(self.net_pnl_quote, "f"),
            "edge_ci_low": format(self.edge_ci_low, "f"),
            "edge_ci_high": format(self.edge_ci_high, "f"),
            "stop_rate": format(self.stop_rate, "f"),
        }


def audit_ai_readiness(
    db_path: str | Path,
    symbol: str,
    *,
    minimum_closed_decisions: int = 5,
    minimum_real_rag_episodes: int = 5,
    maximum_stop_rate: Decimal = Decimal("0.60"),
) -> AiReadiness:
    """Read evidence without creating tables or altering production data."""
    if minimum_closed_decisions < 1 or minimum_real_rag_episodes < 1:
        raise ValueError("AI readiness minimums must be positive")
    target = Path(db_path)
    if not target.is_file():
        raise FileNotFoundError(target)
    normalized_symbol = symbol.upper()
    with sqlite3.connect(
        f"file:{target}?mode=ro", uri=True, timeout=5
    ) as connection:
        table_names = {
            str(row[0]) for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        required = {
            "ai_decisions", "ai_unresolved_fills", "knowledge_documents"
        }
        missing = sorted(required - table_names)
        if missing:
            raise ValueError("missing AI tables: " + ",".join(missing))
        evaluations = connection.execute(
            "SELECT evaluation_json FROM ai_decisions WHERE symbol=?",
            (normalized_symbol,),
        ).fetchall()
        unresolved = int(connection.execute(
            "SELECT COUNT(*) FROM ai_unresolved_fills WHERE symbol=?",
            (normalized_symbol,),
        ).fetchone()[0])
        real_rag = int(connection.execute(
            "SELECT COUNT(*) FROM knowledge_documents "
            "WHERE symbol=? AND status='validated'",
            (normalized_symbol,),
        ).fetchone()[0])
        virtual_rag = int(connection.execute(
            "SELECT COUNT(*) FROM knowledge_documents "
            "WHERE symbol=? AND status='virtual_validated'",
            (normalized_symbol,),
        ).fetchone()[0])

    closed: list[dict] = []
    stop_count = 0
    for (raw_evaluation,) in evaluations:
        try:
            evaluation = json.loads(raw_evaluation or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        item = evaluation.get("realized_execution", {})
        if not isinstance(item, dict) or not item.get("closed"):
            continue
        closed.append(item)
        reason = str(item.get("exit_reason", "")).upper()
        stop_count += int("STOP" in reason or reason in {"SL", "STOP_LOSS"})

    edges = [
        -_decimal(item, "opportunity_cost_quote_text", "opportunity_cost_quote")
        for item in closed
    ]
    edge_mean = sum(edges, ZERO) / len(edges) if edges else ZERO
    if len(edges) > 1:
        variance = sum(
            ((value - edge_mean) ** 2 for value in edges), ZERO
        ) / Decimal(len(edges) - 1)
        margin = Decimal("1.96") * (
            variance / Decimal(len(edges))
        ).sqrt()
    else:
        margin = ZERO
    net_pnl = sum(
        (
            _decimal(item, "net_pnl_quote_text", "net_pnl_quote")
            for item in closed
        ),
        ZERO,
    )
    stop_rate = (
        Decimal(stop_count) / Decimal(len(closed)) if closed else ZERO
    )
    ci_low = edge_mean - margin
    ci_high = edge_mean + margin
    reasons: list[str] = []
    if len(closed) < minimum_closed_decisions:
        reasons.append(
            f"closed decisions {len(closed)} < {minimum_closed_decisions}"
        )
    if real_rag < minimum_real_rag_episodes:
        reasons.append(
            f"real RAG episodes {real_rag} < {minimum_real_rag_episodes}"
        )
    if unresolved:
        reasons.append(f"unresolved fills {unresolved} > 0")
    if not edges or ci_low <= 0:
        reasons.append("realized edge confidence interval includes zero")
    if stop_rate > maximum_stop_rate:
        reasons.append("realized stop rate exceeds threshold")
    return AiReadiness(
        ready=not reasons,
        reasons=tuple(reasons),
        symbol=normalized_symbol,
        closed_decisions=len(closed),
        real_rag_episodes=real_rag,
        virtual_rag_episodes=virtual_rag,
        unresolved_fills=unresolved,
        net_pnl_quote=net_pnl,
        edge_ci_low=ci_low,
        edge_ci_high=ci_high,
        stop_rate=stop_rate,
    )
