import json
import sqlite3
import time

from ladder_dragon.ai.context.runtime import AdvisorDecisionStore
from ladder_dragon.ai.ai_knowledge import (
    KnowledgeStore,
    cosine_similarity,
    hybrid_similarity,
)


def test_knowledge_store_ingests_only_evaluated_decisions_and_retrieves(tmp_path):
    path = tmp_path / "ai_decisions.sqlite3"
    decisions = AdvisorDecisionStore(str(path))
    decision_id = decisions.record(
        symbol="SOLUSDT",
        price=100.0,
        deterministic_mode="FLAT",
        recommended_mode="UP",
        width_scale=1.1,
        cap_scale=0.8,
        confidence=0.9,
        applied=True,
        feature_json=json.dumps([0.1] * 10),
        now=int(time.time()) - 7200,
    )

    knowledge = KnowledgeStore(str(path))
    assert knowledge.stats() == {
        "documents": 0, "virtual_documents": 0, "retrievals": 0,
    }

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE ai_decisions SET return_1h=?, evaluation_json=? WHERE decision_id=?",
                (0.012, json.dumps({"realized_execution": {
                    "net_pnl_quote": 1.2, "sell_qty": 1.0,
                    "financial_evidence_complete": True,
                }}), decision_id),
        )

    results = knowledge.retrieve("SOLUSDT", [0.1] * 10, now=int(time.time()))
    assert len(results) == 1
    assert results[0]["doc_id"]
    assert results[0]["score"] > 0.99
    assert "return_1h=0.01200" in results[0]["context"]

    knowledge.link_retrieval("new-decision", results)
    assert knowledge.stats() == {
        "documents": 1, "virtual_documents": 0, "retrievals": 1,
    }


def test_knowledge_store_rejects_real_closure_with_unknown_slippage(tmp_path):
    path = tmp_path / "ai_decisions.sqlite3"
    decisions = AdvisorDecisionStore(str(path))
    decision_id = decisions.record(
        symbol="SOLUSDT", price=100, deterministic_mode="FLAT",
        recommended_mode="UP", width_scale=1, cap_scale=1,
        confidence=.8, applied=True, feature_json=json.dumps([0.1] * 10),
        now=int(time.time()) - 7200,
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE ai_decisions SET return_1h=?,evaluation_json=? "
            "WHERE decision_id=?",
            (
                .01,
                json.dumps({"realized_execution": {
                    "closed": True, "sell_qty": 1,
                    "financial_evidence_complete": False,
                    "net_pnl_quote_text": None,
                }}),
                decision_id,
            ),
        )

    knowledge = KnowledgeStore(str(path))

    assert knowledge.retrieve("SOLUSDT", [0.1] * 10) == []
    assert knowledge.stats()["documents"] == 0


def test_knowledge_store_can_opt_in_to_settled_virtual_shadow(tmp_path):
    path = tmp_path / "ai_decisions.sqlite3"
    decisions = AdvisorDecisionStore(str(path))
    decision_id = decisions.record(
        symbol="SOLUSDT",
        price=100.0,
        deterministic_mode="FLAT",
        recommended_mode="UP",
        width_scale=1.1,
        cap_scale=0.8,
        confidence=0.6,
        applied=False,
        feature_json=json.dumps([0.3] * 10),
        now=int(time.time()) - 7200,
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE ai_decisions SET return_1h=?, evaluation_json=? WHERE decision_id=?",
            (
                0.02,
                json.dumps({
                    "1h": {
                        "ai": {"net_return": 0.01},
                        "baseline": {"net_return": 0.005},
                    }
                }),
                decision_id,
            ),
        )

    knowledge = KnowledgeStore(str(path))
    assert knowledge.retrieve("SOLUSDT", [0.3] * 10) == []
    results = knowledge.retrieve(
        "SOLUSDT", [0.3] * 10, include_virtual=True
    )
    assert len(results) == 1
    assert results[0]["outcome"]["source"] == "virtual_shadow"
    assert knowledge.stats() == {
        "documents": 0, "virtual_documents": 1, "retrievals": 0,
    }


def test_knowledge_store_excludes_future_documents(tmp_path):
    path = tmp_path / "ai_decisions.sqlite3"
    decisions = AdvisorDecisionStore(str(path))
    decision_id = decisions.record(
        symbol="ETHUSDT",
        price=100.0,
        deterministic_mode="FLAT",
        recommended_mode="FLAT",
        width_scale=1.0,
        cap_scale=1.0,
        confidence=0.8,
        applied=False,
        feature_json=json.dumps([0.2] * 10),
        now=int(time.time()) + 3600,
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE ai_decisions SET return_1h=? WHERE decision_id=?",
            (0.01, decision_id),
        )

    knowledge = KnowledgeStore(str(path))
    assert knowledge.retrieve("ETHUSDT", [0.2] * 10, now=int(time.time())) == []


def test_cosine_similarity_is_bounded_and_zero_safe():
    assert cosine_similarity([1, 0], [1, 0]) == 1.0
    assert cosine_similarity([1, 0], [0, 1]) == 0.0
    assert cosine_similarity([0, 0], [1, 0]) == 0.0


def test_hybrid_similarity_distinguishes_direction_from_magnitude():
    quiet = [0.3] * 10
    panic = [3.0] * 10

    assert cosine_similarity(quiet, panic) == 1.0
    assert hybrid_similarity(quiet, quiet) == 1.0
    assert 0.70 < hybrid_similarity(quiet, panic) < 0.75
    assert hybrid_similarity([0.0] * 10, quiet) == 0.0


def test_rag_applies_similarity_decay_and_minimum_match_gate(tmp_path):
    path = tmp_path / "ai_decisions.sqlite3"
    decisions = AdvisorDecisionStore(str(path))
    decision_id = decisions.record(
        symbol="SOLUSDT", price=100, deterministic_mode="FLAT",
        recommended_mode="UP", width_scale=1, cap_scale=1, confidence=.8,
        applied=True, feature_json=json.dumps([1.0] + [0.0] * 9),
        now=int(time.time()) - 86_400,
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE ai_decisions SET return_1h=?, evaluation_json=? WHERE decision_id=?",
                (.01, json.dumps({"realized_execution": {
                    "sell_qty": 1, "financial_evidence_complete": True,
                }}), decision_id),
        )
    knowledge = KnowledgeStore(str(path))
    assert knowledge.retrieve(
        "SOLUSDT", [1.0] + [0.0] * 9, min_score=.99,
        min_matches=2, now=int(time.time()), decay_days=30,
    ) == []
    results = knowledge.retrieve(
        "SOLUSDT", [1.0] + [0.0] * 9, min_score=.99,
        min_matches=1, now=int(time.time()), decay_days=30,
    )
    assert results and results[0]["raw_score"] > .99
    assert results[0]["score"] < results[0]["raw_score"]


def test_rag_prunes_expired_evidence_and_bounds_python_candidates(tmp_path):
    path = tmp_path / "ai_decisions.sqlite3"
    decisions = AdvisorDecisionStore(str(path))
    now = int(time.time())
    for index, age_sec in enumerate((100, 200, 300), start=1):
        decision_id = decisions.record(
            symbol="SOLUSDT",
            price=100,
            deterministic_mode="FLAT",
            recommended_mode="UP",
            width_scale=1,
            cap_scale=1,
            confidence=.8,
            applied=True,
            feature_json=json.dumps([index / 10] * 10),
            now=now - age_sec,
        )
        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE ai_decisions SET return_1h=?, evaluation_json=? "
                "WHERE decision_id=?",
                (
                    .01,
                    json.dumps(
                            {"realized_execution": {
                                "sell_qty": 1,
                                "financial_evidence_complete": True,
                            }}
                    ),
                    decision_id,
                ),
            )

    knowledge = KnowledgeStore(
        str(path),
        retention_days=30,
        candidate_limit=2,
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            INSERT INTO knowledge_documents(
                document_id,source_decision_id,symbol,created_at,content,
                embedding_json,outcome_json,status,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                "expired",
                "expired-source",
                "SOLUSDT",
                now - 31 * 86_400,
                "expired",
                json.dumps([0.1] * 10),
                "{}",
                "validated",
                now - 31 * 86_400,
            ),
        )
        connection.execute(
            "INSERT INTO knowledge_retrievals("
            "decision_id,document_id,rank,score,created_at"
            ") VALUES(?,?,?,?,?)",
            (
                "expired-link",
                "expired",
                1,
                1.0,
                now - 31 * 86_400,
            ),
        )

    results = knowledge.retrieve(
        "SOLUSDT",
        [0.1] * 10,
        now=now,
        limit=5,
    )

    assert len(results) == 2
    assert {result["created_at"] for result in results} == {
        now - 100,
        now - 200,
    }
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM knowledge_documents "
            "WHERE document_id='expired'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM knowledge_retrievals "
            "WHERE document_id='expired'"
        ).fetchone()[0] == 0
