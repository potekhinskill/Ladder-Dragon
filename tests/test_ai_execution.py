from ai_context import AdvisorDecisionStore


def test_ai_decision_fills_are_linked_and_evaluated(tmp_path):
    store = AdvisorDecisionStore(str(tmp_path / "ai.db"))
    decision = store.record(symbol="SOLUSDT", price=100, deterministic_mode="FLAT",
                            recommended_mode="UP", width_scale=1, cap_scale=1,
                            confidence=.8, applied=True)
    store.record_fill(decision, symbol="SOLUSDT", side="BUY", price=100, qty=1, fee_quote=.1, ts=10)
    store.record_fill(decision, symbol="SOLUSDT", side="SELL", price=102, qty=1, fee_quote=.1,
                      exit_reason="OCO_TP", ts=70)
    result = store.evaluate_execution(decision, baseline_exit_price=101)
    assert result["net_pnl_quote"] == 1.8
    assert result["holding_duration_sec"] == 60.0
    assert result["opportunity_cost_quote"] < 0
