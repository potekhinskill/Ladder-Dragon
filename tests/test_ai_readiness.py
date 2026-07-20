import json
import sqlite3
from decimal import Decimal

from ladder_dragon.ai.ai_readiness import audit_ai_readiness


def make_db(path, *, edges, stops=0, real_rag=0, unresolved=0):
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE ai_decisions(symbol TEXT,evaluation_json TEXT)"
        )
        connection.execute(
            "CREATE TABLE ai_unresolved_fills(symbol TEXT)"
        )
        connection.execute(
            "CREATE TABLE knowledge_documents(symbol TEXT,status TEXT)"
        )
        for index, edge in enumerate(edges):
            result = {
                "closed": True,
                "net_pnl_quote_text": "1.25",
                "opportunity_cost_quote_text": format(-Decimal(edge), "f"),
                "exit_reason": "STOP" if index < stops else "TP",
            }
            connection.execute(
                "INSERT INTO ai_decisions VALUES (?,?)",
                ("SOLUSDT", json.dumps({"realized_execution": result})),
            )
        connection.executemany(
            "INSERT INTO knowledge_documents VALUES (?,?)",
            [("SOLUSDT", "validated")] * real_rag,
        )
        connection.executemany(
            "INSERT INTO ai_unresolved_fills VALUES (?)",
            [("SOLUSDT",)] * unresolved,
        )


def test_ai_readiness_passes_only_with_positive_real_evidence(tmp_path):
    path = tmp_path / "ai.sqlite3"
    make_db(path, edges=["1", "1", "1", "1", "1"], real_rag=5)

    report = audit_ai_readiness(path, "SOLUSDT")

    assert report.ready is True
    assert report.net_pnl_quote == Decimal("6.25")
    assert report.edge_ci_low == Decimal("1")


def test_ai_readiness_fails_closed_on_missing_and_unresolved_evidence(tmp_path):
    path = tmp_path / "ai.sqlite3"
    make_db(path, edges=["-1"], real_rag=0, unresolved=1)

    report = audit_ai_readiness(path, "SOLUSDT")

    assert report.ready is False
    assert "closed decisions 1 < 5" in report.reasons
    assert "real RAG episodes 0 < 5" in report.reasons
    assert "unresolved fills 1 > 0" in report.reasons
    assert "realized edge confidence interval includes zero" in report.reasons
