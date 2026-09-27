# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve dashboard AI reporting with explicit service ownership.

import sqlite3
from pathlib import Path
from typing import Dict


def database_aggregates(
    deps,
    connection: sqlite3.Connection,
    *,
    db_path: Path,
    evaluation_expression: str,
    tables: set[str],
) -> Dict:
    """Compute growing AI counters in SQL and cache the bounded result."""
    cache_key = f"database:{db_path}"
    cached = deps._ai_cache_get(cache_key)
    if cached is not None:
        return cached

    stats = {
        "documents": 0,
        "virtual_documents": 0,
        "archived_virtual_documents": 0,
        "virtual_policy": "archived_not_retrievable",
        "retrievals": 0,
        "unresolved_fills": 0,
        "unresolved_attribution_fills": 0,
        "unresolved_inventory_fills": 0,
        "reviewed_unattributable_fills": 0,
        "closed_decisions": 0,
        "incomplete_closed_decisions": 0,
        "realized_net_pnl_quote": 0.0,
    }
    safe_evaluation = (
        f"CASE WHEN json_valid({evaluation_expression}) "
        f"THEN {evaluation_expression} ELSE '{{}}' END"
    )
    realized = connection.execute(
        f"""
        SELECT
          COALESCE(SUM(CASE
            WHEN json_extract({safe_evaluation}, '$.realized_execution.closed') = 1
             AND json_extract({safe_evaluation}, '$.realized_execution.financial_evidence_complete') = 1
            THEN 1 ELSE 0 END), 0) AS closed_count,
          COALESCE(SUM(CASE
            WHEN json_extract({safe_evaluation}, '$.realized_execution.closed') = 1
             AND COALESCE(json_extract({safe_evaluation}, '$.realized_execution.financial_evidence_complete'), 0) != 1
            THEN 1 ELSE 0 END), 0) AS incomplete_closed_count,
          COALESCE(SUM(CASE
            WHEN json_extract({safe_evaluation}, '$.realized_execution.closed') = 1
             AND json_extract({safe_evaluation}, '$.realized_execution.financial_evidence_complete') = 1
            THEN CAST(COALESCE(
              json_extract({safe_evaluation}, '$.realized_execution.net_pnl_quote_text'),
              json_extract({safe_evaluation}, '$.realized_execution.net_pnl_quote'),
              0
            ) AS REAL)
            ELSE 0 END), 0) AS net_pnl
        FROM ai_decisions
        """
    ).fetchone()
    stats["closed_decisions"] = int(realized["closed_count"] or 0)
    stats["incomplete_closed_decisions"] = int(
        realized["incomplete_closed_count"] or 0
    )
    stats["realized_net_pnl_quote"] = float(realized["net_pnl"] or 0)

    if "knowledge_documents" in tables:
        document_rows = connection.execute(
            """
            SELECT status, COUNT(*) AS count
            FROM knowledge_documents
            WHERE status IN ('validated', 'virtual_validated')
            GROUP BY status
            """
        ).fetchall()
        for row in document_rows:
            target = (
                "documents"
                if row["status"] == "validated"
                else "archived_virtual_documents"
            )
            stats[target] = int(row["count"])
    if "knowledge_retrievals" in tables:
        stats["retrievals"] = int(
            connection.execute("SELECT COUNT(*) FROM knowledge_retrievals").fetchone()[0]
        )
    if "ai_unresolved_fills" in tables:
        from ladder_dragon.ai.unresolved_fills import lifecycle_counts

        unresolved = lifecycle_counts(connection)
        stats["unresolved_fills"] = unresolved["pending"]
        stats["unresolved_attribution_fills"] = unresolved["attribution"]
        stats["unresolved_inventory_fills"] = unresolved["inventory"]
        stats["reviewed_unattributable_fills"] = unresolved[
            "reviewed_unattributable"
        ]
    return deps._ai_cache_put(cache_key, stats)
