# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve AI-status presentation through explicit component ownership.

import sqlite3
import json


def read_ai_decisions(deps, db_path, limit):
    recent = []
    knowledge_stats = {
        "documents": 0, "virtual_documents": 0,
        "archived_virtual_documents": 0,
        "virtual_policy": "archived_not_retrievable",
        "retrievals": 0,
        "unresolved_fills": 0,
        "unresolved_attribution_fills": 0,
        "unresolved_inventory_fills": 0,
        "reviewed_unattributable_fills": 0,
        "closed_decisions": 0,
        "realized_net_pnl_quote": 0.0,
    }
    if db_path.exists():
        with sqlite3.connect(
            f"file:{db_path}?mode=ro", uri=True, timeout=1
        ) as connection:
            connection.row_factory = sqlite3.Row
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(ai_decisions)")
            }
            expressions = {
                "decision_id": "decision_id" if "decision_id" in columns else "''",
                "policy_status": (
                    "policy_status" if "policy_status" in columns else "''"
                ),
                "policy_reasons": (
                    "policy_reasons" if "policy_reasons" in columns else "''"
                ),
                "benchmark_mode": (
                    "benchmark_mode" if "benchmark_mode" in columns else "''"
                ),
                "evaluation_json": (
                    "evaluation_json" if "evaluation_json" in columns else "'{}'"
                ),
                "rationale": "rationale" if "rationale" in columns else "''",
                "context_version": "context_version" if "context_version" in columns else "''",
                "config_version": "config_version" if "config_version" in columns else "''",
            }
            recent = [
                dict(row)
                for row in connection.execute(
                    f"""
                        SELECT {expressions['decision_id']} AS decision_id,symbol,created_at,deterministic_mode AS baseline_mode,
                               recommended_mode,width_scale,cap_scale,confidence,
                               applied,{expressions['policy_status']} AS status,
                               {expressions['policy_reasons']} AS policy_reasons,
                               {expressions['benchmark_mode']} AS benchmark_mode,
                               return_15m,return_1h,return_4h,
                               {expressions['evaluation_json']} AS evaluation_json,
                               {expressions['rationale']} AS rationale,
                               {expressions['context_version']} AS context_version,
                               {expressions['config_version']} AS config_version
                        FROM ai_decisions ORDER BY created_at DESC LIMIT ?
                        """,
                    (limit,),
                ).fetchall()
            ]
            for row in recent:
                row["evaluation"] = json.loads(row.pop("evaluation_json") or "{}")
            tables = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            knowledge_stats.update(
                deps._ai_database_aggregates(
                    connection,
                    db_path=db_path,
                    evaluation_expression=expressions["evaluation_json"],
                    tables=tables,
                )
            )
            if "knowledge_retrievals" in tables:
                for row in recent:
                    decision_id = row.get("decision_id")
                    if not decision_id:
                        row["rag_documents"] = []
                        continue
                    row["rag_documents"] = [
                        {"document_id": item[0], "rank": int(item[1]), "score": float(item[2])}
                        for item in connection.execute(
                            """SELECT document_id,rank,score FROM knowledge_retrievals
                                   WHERE decision_id=? ORDER BY rank LIMIT 5""",
                            (decision_id,),
                        ).fetchall()
                    ]
    return recent, knowledge_stats
