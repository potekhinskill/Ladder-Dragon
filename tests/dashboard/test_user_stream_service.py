"""User Stream dashboard metric regressions."""

from ladder_dragon.dashboard.services.user_stream import (
    current_soak_epoch_metrics,
)


def test_current_soak_epoch_metrics_preserve_lifetime_counter_context():
    metrics = current_soak_epoch_metrics({
        "current_soak_epoch_id": "transport-stability-2026-08-v1",
        "reconnects": 1_070,
        "order_events": 3,
        "soak_epochs": [{
            "id": "transport-stability-2026-08-v1",
            "started_at": 1_000,
            "baseline": {"reconnects": 1_069, "order_events": 2},
        }],
    }, now=1_000 + 1_800)

    assert metrics == {
        "soak_epoch_id": "transport-stability-2026-08-v1",
        "soak_epoch_hours": 0.5,
        "soak_epoch_reconnects": 1,
        "soak_epoch_order_events": 1,
    }


def test_current_soak_epoch_metrics_hide_damaged_evidence():
    metrics = current_soak_epoch_metrics({
        "current_soak_epoch_id": "transport-stability-2026-08-v1",
        "soak_epochs": [],
    }, now=2_000)

    assert metrics["soak_epoch_id"] is None
