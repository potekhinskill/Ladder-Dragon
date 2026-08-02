from ladder_dragon.supervision.risk_cycle import (
    initial_runtime_risk_gate,
    initial_runtime_risk_status,
)


def test_live_starts_blocked_until_authoritative_risk_snapshot():
    gate = initial_runtime_risk_gate(live=True, persistent_halt=False)

    assert gate["state"] == "RISK_PENDING"
    assert gate["buy_blocked"] is True
    assert gate["halted"] is False
    assert gate["reasons"] == ("authoritative risk snapshot pending",)


def test_live_preserves_visible_persistent_halt_during_startup():
    gate = initial_runtime_risk_gate(live=True, persistent_halt=True)

    assert gate["state"] == "RISK_PENDING"
    assert gate["buy_blocked"] is True
    assert gate["halted"] is True
    assert gate["reasons"] == (
        "persistent circuit halt requires authoritative evaluation",
    )


def test_dry_runtime_does_not_publish_a_false_risk_block():
    gate = initial_runtime_risk_gate(live=False, persistent_halt=True)

    assert gate == {
        "state": "RUNNING",
        "buy_blocked": False,
        "halted": False,
        "reasons": (),
    }


def test_live_startup_status_nests_fail_closed_risk_evidence():
    status = initial_runtime_risk_status(
        live=True,
        persistent_halt=True,
    )

    assert status == {
        "state": "RISK_PENDING",
        "risk": {
            "buy_blocked": True,
            "halted": True,
            "reasons": [
                "persistent circuit halt requires authoritative evaluation"
            ],
            "reconciliation_delta": None,
        },
    }
