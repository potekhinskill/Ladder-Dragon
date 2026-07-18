# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Purpose: implement the ai knowledge component of the ai layer.
"""Локальная RAG-база проверенных AI-решений.

Модуль не вызывает внешние embedding API и не обучает DeepSeek. Для Raspberry
используется компактное embedding структурированных рыночных признаков
(feature vector из decision store), а в prompt попадают только короткие
обезличенные итоги уже оценённых исторических решений.
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence


EMBEDDING_DIMENSIONS = 10
DEFAULT_LIMIT = 3
MAX_CONTEXT_CHARS = 220


def _vector(value: str) -> tuple[float, ...] | None:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, list) or len(parsed) != EMBEDDING_DIMENSIONS:
        return None
    try:
        return tuple(float(item) for item in parsed)
    except (TypeError, ValueError):
        return None


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Косинусная близость двух фиксированных структурированных embeddings."""
    if len(left) != len(right) or not left:
        return 0.0
    dot = sum(float(a) * float(b) for a, b in zip(left, right))
    left_norm = math.sqrt(sum(float(a) * float(a) for a in left))
    right_norm = math.sqrt(sum(float(b) * float(b) for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


class KnowledgeStore:
    """Хранилище документов, embeddings и аудита retrieval в decision DB."""

    def __init__(self, db_path: str) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._last_sync = 0.0
        self._last_sync_virtual = False
        self._init()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _init(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_documents(
                    document_id TEXT PRIMARY KEY,
                    source_decision_id TEXT NOT NULL UNIQUE,
                    symbol TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    outcome_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'validated',
                    updated_at INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_retrievals(
                    decision_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    rank INTEGER NOT NULL,
                    score REAL NOT NULL,
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY(decision_id, document_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS knowledge_documents_symbol_time "
                "ON knowledge_documents(symbol, created_at)"
            )

    def sync_from_decisions(
        self, *, now: int | None = None, include_virtual: bool = False
    ) -> int:
        """Импортировать решения с уже рассчитанным исходом.

        Реальные документы требуют фактического закрытия позиции. В DRY можно
        отдельно включить ``include_virtual``: тогда в базу попадут только
        решения с завершённым горизонтом ``return_1h`` и статусом
        ``virtual_validated``. Виртуальные и реальные знания не смешиваются.
        """
        current = int(now or time.time())
        if (
            include_virtual == self._last_sync_virtual
            and current - self._last_sync < 30
        ):
            return 0
        inserted = 0
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT decision_id,symbol,created_at,deterministic_mode,
                       recommended_mode,width_scale,cap_scale,confidence,
                       feature_json,return_1h,evaluation_json
                FROM ai_decisions
                WHERE feature_json!='[]' AND return_1h IS NOT NULL
                """
            ).fetchall()
            for row in rows:
                (
                    decision_id, symbol, created_at, baseline_mode,
                    recommended_mode, width_scale, cap_scale, confidence,
                    feature_json, return_1h, evaluation_json,
                ) = row
                embedding = _vector(feature_json)
                if embedding is None:
                    continue
                try:
                    evaluation = json.loads(evaluation_json or "{}")
                except (TypeError, ValueError, json.JSONDecodeError):
                    evaluation = {}
                realized = evaluation.get("realized_execution", {})
                if not isinstance(realized, dict):
                    realized = {}
                is_real = float(realized.get("sell_qty", 0) or 0) > 0
                if is_real:
                    status = "validated"
                    outcome = {
                        "source": "realized_execution",
                        "return_1h": return_1h,
                        "net_pnl_quote": realized.get("net_pnl_quote"),
                        "holding_duration_sec": realized.get("holding_duration_sec"),
                        "opportunity_cost_quote": realized.get("opportunity_cost_quote"),
                    }
                elif include_virtual:
                    virtual = evaluation.get("1h", {})
                    if not isinstance(virtual, dict):
                        virtual = {}
                    ai_result = virtual.get("ai", {})
                    baseline_result = virtual.get("baseline", {})
                    # Price direction alone is insufficient: virtual RAG requires
                    # completed evaluations for both the AI plan and the baseline.
                    if not isinstance(ai_result, dict) or not isinstance(baseline_result, dict):
                        continue
                    status = "virtual_validated"
                    outcome = {
                        "source": "virtual_shadow",
                        "return_1h": return_1h,
                        "ai_net_return": ai_result.get("net_return"),
                        "baseline_net_return": baseline_result.get("net_return"),
                    }
                else:
                    # Without an explicit DRY flag, a virtual candle evaluation
                    # is not accepted as verified RAG experience.
                    continue
                content = (
                    f"{symbol} {'virtual shadow' if status == 'virtual_validated' else 'historical'} regime: "
                    f"baseline={baseline_mode}, "
                    f"recommendation={recommended_mode}, confidence={float(confidence):.2f}, "
                    f"width={float(width_scale):.2f}, cap={float(cap_scale):.2f}, "
                    f"return_1h={float(return_1h):.5f}"
                )[:MAX_CONTEXT_CHARS]
                document_id = uuid.uuid5(
                    uuid.NAMESPACE_URL, f"ladder-dragon:decision:{decision_id}"
                ).hex
                connection.execute(
                    """
                    INSERT INTO knowledge_documents(
                        document_id,source_decision_id,symbol,created_at,content,
                        embedding_json,outcome_json,status,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(source_decision_id) DO UPDATE SET
                        content=excluded.content,
                        embedding_json=excluded.embedding_json,
                        outcome_json=excluded.outcome_json,
                        status=excluded.status,
                        updated_at=excluded.updated_at
                    """,
                    (
                        document_id, decision_id, str(symbol).upper(), int(created_at),
                        content, json.dumps(embedding), json.dumps(outcome),
                        status, current,
                    ),
                )
                inserted += 1
        self._last_sync = float(current)
        self._last_sync_virtual = bool(include_virtual)
        return inserted

    def retrieve(
        self,
        symbol: str,
        embedding: Sequence[float],
        *,
        now: int | None = None,
        limit: int = DEFAULT_LIMIT,
        include_virtual: bool = False,
        min_score: float = 0.0,
        min_matches: int = 1,
        decay_days: int = 0,
    ) -> list[dict[str, Any]]:
        """Вернуть похожие проверенные случаи без будущих документов."""
        current = int(now or time.time())
        self.sync_from_decisions(now=current, include_virtual=include_virtual)
        statuses = ("validated", "virtual_validated") if include_virtual else ("validated",)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT document_id,content,embedding_json,created_at,outcome_json
                FROM knowledge_documents
                WHERE symbol=? AND status IN ({','.join('?' for _ in statuses)})
                  AND created_at < ?
                """,
                (symbol.upper(), *statuses, current),
            ).fetchall()
        ranked: list[dict[str, Any]] = []
        for document_id, content, embedding_json, created_at, outcome_json in rows:
            candidate = _vector(embedding_json)
            if candidate is None:
                continue
            score = cosine_similarity(embedding, candidate)
            if score < float(min_score):
                continue
            age_days = max(0.0, (current - int(created_at)) / 86_400)
            decay = (
                math.exp(-age_days / max(1.0, float(decay_days)))
                if decay_days and decay_days > 0 else 1.0
            )
            effective_score = score * decay
            ranked.append({
                "doc_id": str(document_id),
                "context": str(content)[:MAX_CONTEXT_CHARS],
                "score": round(effective_score, 6),
                "raw_score": round(score, 6),
                "age_days": round(age_days, 3),
                "created_at": int(created_at),
                "outcome": json.loads(outcome_json or "{}"),
            })
        ranked.sort(key=lambda item: (item["score"], item["created_at"]), reverse=True)
        if len(ranked) < max(1, int(min_matches)):
            return []
        return ranked[: max(0, min(int(limit), 5))]

    def link_retrieval(
        self,
        decision_id: str,
        documents: Sequence[Mapping[str, Any]],
        *,
        now: int | None = None,
    ) -> None:
        """Сохранить, какие historical documents повлияли на prompt."""
        current = int(now or time.time())
        with self._connect() as connection:
            for rank, document in enumerate(documents, start=1):
                document_id = str(document.get("doc_id", ""))
                if not document_id:
                    continue
                connection.execute(
                    """
                    INSERT OR REPLACE INTO knowledge_retrievals(
                        decision_id,document_id,rank,score,created_at
                    ) VALUES(?,?,?,?,?)
                    """,
                    (
                        decision_id, document_id, rank,
                        float(document.get("score", 0.0)), current,
                    ),
                )

    def stats(self) -> dict[str, int]:
        with self._connect() as connection:
            documents = connection.execute(
                "SELECT COUNT(*) FROM knowledge_documents WHERE status='validated'"
            ).fetchone()[0]
            virtual_documents = connection.execute(
                "SELECT COUNT(*) FROM knowledge_documents WHERE status='virtual_validated'"
            ).fetchone()[0]
            retrievals = connection.execute(
                "SELECT COUNT(*) FROM knowledge_retrievals"
            ).fetchone()[0]
        return {
            "documents": int(documents),
            "virtual_documents": int(virtual_documents),
            "retrievals": int(retrievals),
        }
