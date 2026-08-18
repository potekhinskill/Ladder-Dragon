# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify that execution scope controls inventory evidence applicability.
"""Strategy-control scope regressions."""

from ladder_dragon.supervision import runtime


def test_shadow_only_inventory_gate_is_immediately_not_applicable(monkeypatch):
    class Store:
        def resolved_samples(self, symbol, *, kind):
            assert symbol == "ETHUSDT"
            assert kind == "CONTROL_INVENTORY_V4"
            return []

    monkeypatch.setattr(runtime, "_PREDICTION_SHADOW", Store())
    monkeypatch.setattr(runtime, "_AI_RUNTIME_STATUS", {
        "symbols": ["SOLUSDT"]
    })
    runtime._STRATEGY_CONTROL_GATE_CACHE.clear()

    gate = runtime._strategy_control_gate("ETHUSDT", "inventory")

    assert gate["status"] == "NOT_APPLICABLE"
    assert gate["binding_reachability"]["projected_ready_ts_ms"] is None
    runtime._STRATEGY_CONTROL_GATE_CACHE.clear()
