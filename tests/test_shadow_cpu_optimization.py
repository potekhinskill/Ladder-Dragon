"""Exact-result regressions for bounded training reuse and fresh summaries."""

import sqlite3

import pytest

from ladder_dragon.ai import ai_statistical as statistical
from ladder_dragon.strategy.prediction.runtime import PredictionShadowStore


@pytest.fixture(autouse=True)
def empty_cache():
    statistical._cached_regime_weights.cache_clear()
    yield
    statistical._cached_regime_weights.cache_clear()


def examples():
    return [([float(i % 3 - 1)] * 10, statistical.CLASSES[i % 3])
            for i in range(30)]


@pytest.mark.parametrize("minimum,calibration", [(5, 3), (100, 3), (5, 100)])
def test_cached_predictions_equal_original_for_each_current_context(monkeypatch, minimum, calibration):
    data = examples()
    options = dict(min_samples=minimum, min_calibration_samples=calibration)
    cached = [statistical.calibrated_logistic_prediction(data, [v] * 10, **options)
              for v in (-2., 0., 2.)]
    assert statistical._cached_regime_weights.cache_info().hits == 2
    monkeypatch.setattr(statistical, "_fit_regime", lambda model, rows: model.fit(rows))
    original = [statistical.calibrated_logistic_prediction(data, [v] * 10, **options)
                for v in (-2., 0., 2.)]
    assert cached == original


def test_prefix_identity_order_labels_and_eviction():
    data = examples()
    predict = statistical.calibrated_logistic_prediction
    predict(data, [0.] * 10)
    predict(data, [1.] * 10, min_samples=1)
    assert statistical._cached_regime_weights.cache_info().hits == 1
    # A changed later holdout must not contaminate the training prefix.
    data[-1] = ([2.] * 10, "DOWN")
    predict(data, [0.] * 10)
    assert statistical._cached_regime_weights.cache_info().hits == 2
    data[0] = ([.1] * 10, "UP")
    predict(data, [0.] * 10)
    data[0] = ([.1] * 10, "DOWN")
    predict(data, [0.] * 10)
    data[0], data[1] = data[1], data[0]
    predict(data, [0.] * 10)
    info = statistical._cached_regime_weights.cache_info()
    assert info.misses == 4
    assert info.currsize == 2
    predict(examples(), [0.] * 10)
    assert statistical._cached_regime_weights.cache_info().misses == 5


def test_changed_holdout_is_recalibrated_and_restart_is_equivalent(monkeypatch):
    data = examples()
    options = dict(min_samples=5, min_calibration_samples=3)
    statistical.calibrated_logistic_prediction(data, [1.] * 10, **options)
    data[-5:] = [([1.] * 10, "DOWN")] * 5
    warm = statistical.calibrated_logistic_prediction(data, [1.] * 10, **options)
    statistical._cached_regime_weights.cache_clear()
    assert statistical.calibrated_logistic_prediction(data, [1.] * 10, **options) == warm
    monkeypatch.setattr(statistical, "_fit_regime", lambda model, rows: model.fit(rows))
    assert statistical.calibrated_logistic_prediction(data, [1.] * 10, **options) == warm


def test_cached_weights_cannot_be_mutated_by_consumer():
    first = statistical.MulticlassLogisticRegime()
    statistical._fit_regime(first, examples())
    expected = first.predict([1.] * 10, min_samples=1)
    first.weights[0][0] = 1000.
    second = statistical.MulticlassLogisticRegime()
    statistical._fit_regime(second, examples())
    assert second.predict([1.] * 10, min_samples=1) == expected


def test_failed_fit_is_not_cached(monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("synthetic fit failure")
    monkeypatch.setattr(statistical.MulticlassLogisticRegime, "fit", fail)
    for _ in range(2):
        with pytest.raises(ValueError, match="synthetic"):
            statistical.calibrated_logistic_prediction(examples(), [0.] * 10)
    assert statistical._cached_regime_weights.cache_info().currsize == 0
    assert statistical._cached_regime_weights.cache_info().misses == 2


def test_warm_cache_does_not_bypass_failed_source_read():
    from ladder_dragon.ai.context.statistical import statistical_prediction

    statistical.calibrated_logistic_prediction(examples(), [0.] * 10)
    def unavailable():
        raise sqlite3.OperationalError("synthetic unavailable source")
    with pytest.raises(sqlite3.OperationalError, match="synthetic"):
        statistical_prediction(unavailable, None, min_samples=5, numeric=float)
    assert statistical._cached_regime_weights.cache_info().hits == 0


def test_large_or_nonfinite_training_is_not_retained(monkeypatch):
    calls = []
    monkeypatch.setattr(statistical.MulticlassLogisticRegime, "fit",
                        lambda self, rows: calls.append(rows))
    for rows in ([([0.] * 10, "UP")] * 2001, [([float("nan")] * 10, "UP")]):
        statistical._fit_regime(statistical.MulticlassLogisticRegime(), rows)
    assert len(calls) == 2
    assert statistical._cached_regime_weights.cache_info().currsize == 0


def test_summary_uses_two_fresh_queries_with_exact_old_counts(tmp_path, monkeypatch):
    path = tmp_path / "summary.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE prediction_decisions(decision_id TEXT, symbol TEXT, kind TEXT);
            CREATE TABLE prediction_outcomes(decision_id TEXT, outcome_json TEXT,
                resolved_at_ms INTEGER, terminal_reason TEXT);
            INSERT INTO prediction_decisions VALUES
                ('a','SOLUSDT','STRATEGY'),('b','SOLUSDT','REANCHOR'),
                ('c','ETHUSDT','REANCHOR'),('d','SOLUSDT','REANCHOR');
            INSERT INTO prediction_outcomes VALUES
                ('a','{}',1,NULL),('a',NULL,NULL,NULL),
                ('b',NULL,2,'INSUFFICIENT_HISTORY'),('c','{}',1,NULL);
        """)
    statements = []
    def connect():
        connection = sqlite3.connect(path)
        connection.set_trace_callback(statements.append)
        return connection
    store = object.__new__(PredictionShadowStore)
    monkeypatch.setattr(store, "_connect", connect)
    monkeypatch.setattr(store, "reanchor_performance", lambda symbol: {})
    monkeypatch.setattr(store, "regime_performance", lambda symbol: {})
    for symbol in ("SOLUSDT", "ETHUSDT", "UNKNOWN"):
        statements.clear()
        result = store.summary(symbol.lower())
        assert len([s for s in statements if s.lstrip().startswith("SELECT")]) == 2
        with sqlite3.connect(path) as connection:
            for key, query in (
                ("decisions", "SELECT COUNT(*) FROM prediction_decisions WHERE symbol=?"),
                ("reanchor_counterfactuals", "SELECT COUNT(*) FROM prediction_decisions WHERE symbol=? AND kind='REANCHOR'"),
                ("resolved_outcomes", "SELECT COUNT(*) FROM prediction_outcomes o JOIN prediction_decisions d USING(decision_id) WHERE symbol=? AND o.outcome_json IS NOT NULL"),
                ("pending_outcomes", "SELECT COUNT(*) FROM prediction_outcomes o JOIN prediction_decisions d USING(decision_id) WHERE symbol=? AND o.resolved_at_ms IS NULL"),
                ("expired_outcomes", "SELECT COUNT(*) FROM prediction_outcomes o JOIN prediction_decisions d USING(decision_id) WHERE symbol=? AND o.terminal_reason='INSUFFICIENT_HISTORY'"),
            ):
                assert result[key] == connection.execute(query, (symbol,)).fetchone()[0]
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE prediction_outcomes SET outcome_json='{}', resolved_at_ms=3 WHERE resolved_at_ms IS NULL")
    assert store.summary("SOLUSDT")["pending_outcomes"] == 0
    assert store.summary("SOLUSDT")["resolved_outcomes"] == 2
