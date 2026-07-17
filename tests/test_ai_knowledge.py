import json
import sqlite3
import time

from ai_context import AdvisorDecisionStore
from ai_knowledge import KnowledgeStore, cosine_similarity


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
            (0.012, json.dumps({"realized_execution": {"net_pnl_quote": 1.2, "sell_qty": 1.0}}), decision_id),
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
