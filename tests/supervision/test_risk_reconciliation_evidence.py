from ladder_dragon.risk.risk_manager import RiskDecision
from ladder_dragon.supervision.risk_cycle import (
    RiskReconciliationError,
    risk_operation_failure_status,
)


def test_reconciliation_error_keeps_exact_machine_readable_evidence():
    error = RiskReconciliationError(
        [
            {
                "symbol": "SOLUSDT",
                "account": "0.30000000",
                "ledger": "0.10000000",
                "delta": "0.20000000",
                "allowed": "0.00030000",
            }
        ]
    )
    decision = RiskDecision(
        halted=False,
        buy_blocked=True,
        reasons=("risk telemetry unavailable",),
    )

    status = risk_operation_failure_status(
        {"current_cap_per_order_usdt": "10"},
        error,
        decision,
        2,
    )

    assert status["current_cap_per_order_usdt"] == "10"
    assert status["reconciliation_delta"] == [
        {
            "symbol": "SOLUSDT",
            "account": "0.30000000",
            "ledger": "0.10000000",
            "delta": "0.20000000",
            "allowed": "0.00030000",
        }
    ]


def test_generic_failure_does_not_publish_error_text_or_false_evidence():
    error = RuntimeError(
        "https://api.binance.com/api/v3/account?signature=private"
    )
    decision = RiskDecision(
        halted=False,
        buy_blocked=True,
        reasons=("risk telemetry unavailable",),
    )

    status = risk_operation_failure_status({}, error, decision, 1)

    assert status["reconciliation_delta"] is None
    assert "signature" not in repr(status)
