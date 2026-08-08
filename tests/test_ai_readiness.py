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
                "financial_evidence_complete": True,
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
    make_db(path, edges=["1"] * 60, real_rag=5)

    report = audit_ai_readiness(path, "SOLUSDT")

    assert report.ready is True
    assert report.net_pnl_quote == Decimal("75.00")
    assert report.edge_ci_low == Decimal("1")
    assert report.edge_ci_high == Decimal("1")


def test_ai_readiness_default_rejects_small_positive_sample(tmp_path):
    path = tmp_path / "ai.sqlite3"
    make_db(path, edges=["1"] * 5, real_rag=5)

    report = audit_ai_readiness(path, "SOLUSDT")

    assert report.ready is False
    assert "closed decisions 5 < 60" in report.reasons


def test_ai_readiness_fails_closed_on_missing_and_unresolved_evidence(tmp_path):
    path = tmp_path / "ai.sqlite3"
    make_db(path, edges=["-1"], real_rag=0, unresolved=1)

    report = audit_ai_readiness(path, "SOLUSDT")

    assert report.ready is False
    assert "closed decisions 1 < 60" in report.reasons
    assert "real RAG episodes 0 < 5" in report.reasons
    assert "unresolved fills 1 > 0" in report.reasons
    assert "realized edge confidence interval includes zero" in report.reasons


def test_ai_readiness_excludes_incomplete_closed_evidence(tmp_path):
    path = tmp_path / "ai.sqlite3"
    make_db(path, edges=["1"] * 60, real_rag=5)
    with sqlite3.connect(path) as connection:
        payload = {
            "realized_execution": {
                "closed": True,
                "financial_evidence_complete": False,
                "net_pnl_quote_text": None,
                "opportunity_cost_quote_text": None,
            }
        }
        connection.execute(
            "UPDATE ai_decisions SET evaluation_json=? WHERE rowid=1",
            (json.dumps(payload),),
        )

    report = audit_ai_readiness(path, "SOLUSDT")

    assert report.ready is False
    assert report.closed_decisions == 59
    assert report.incomplete_closed_decisions == 1
    assert "closed decisions 59 < 60" in report.reasons
