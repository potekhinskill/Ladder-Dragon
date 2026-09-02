"""Runtime identity checks for LIVE execution-authority bindings."""

from __future__ import annotations

import pytest

from ladder_dragon.execution.worker.authority_attestation import (
    WorkerAuthorityBindingError,
    require_worker_authority_binding,
)
from ladder_dragon.execution.worker.champion_preflight import require_live_champion
from ladder_dragon.strategy.prediction.champion_registry import (
    verify_active_champion_lifecycle,
)
from ladder_dragon.supervision.authority_attestation import (
    SupervisorAuthorityBindingError,
    require_supervisor_authority_binding,
)


def test_runtime_authority_attestation_accepts_canonical_callables() -> None:
    require_supervisor_authority_binding(verify_active_champion_lifecycle)
    require_worker_authority_binding(require_live_champion)


@pytest.mark.parametrize(
    ("attest", "error_type", "message"),
    (
        (
            require_supervisor_authority_binding,
            SupervisorAuthorityBindingError,
            "supervisor execution authority runtime binding changed",
        ),
        (
            require_worker_authority_binding,
            WorkerAuthorityBindingError,
            "worker execution authority runtime binding changed",
        ),
    ),
)
def test_runtime_authority_attestation_rejects_same_name_noop(
    attest, error_type, message: str
) -> None:
    def same_name_noop(*_args, **_kwargs):
        return None

    same_name_noop.__name__ = message.split()[0]
    with pytest.raises(error_type, match=message) as captured:
        attest(same_name_noop)

    diagnostic = str(captured.value)
    assert "same_name_noop" not in diagnostic
    assert "sensitive-value-not-for-report" not in diagnostic
