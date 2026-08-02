from datetime import datetime, timezone
import json

import pytest

from ladder_dragon.verification.checks.raspberry import _runtime_check
from ladder_dragon.verification.models import (
    HarnessContext,
    HarnessOptions,
    Status,
)


def _check(tmp_path, delta_marker):
    payload = {
        "state": "RUNNING",
        "execution_mode": "LIVE",
        "venue": "mainnet",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "recovery": {"blocked": False},
        "risk": {"halted": False, "buy_blocked": False},
    }
    if delta_marker is not ...:
        payload["risk"]["reconciliation_delta"] = delta_marker
    status_path = tmp_path / "runtime.json"
    status_path.write_text(json.dumps(payload), encoding="utf-8")
    options = HarnessOptions(
        profile="pi",
        output=tmp_path / "report.json",
        runtime_status=status_path,
    )
    return _runtime_check(
        HarnessContext(root=tmp_path, python="python", options=options)
    )


@pytest.mark.parametrize("delta_marker", [..., None, {}])
def test_runtime_check_blocks_missing_or_invalid_reconciliation_evidence(
    tmp_path, delta_marker
):
    result = _check(tmp_path, delta_marker)

    assert result.status is Status.BLOCKED
    assert "reconciliation evidence is unavailable" in result.summary
    assert result.metrics["reconciliation_mismatch_count"] is None


def test_runtime_check_accepts_explicit_empty_reconciliation_evidence(tmp_path):
    result = _check(tmp_path, [])

    assert result.status is Status.PASS
    assert result.metrics["reconciliation_mismatch_count"] == 0


def test_runtime_check_blocks_structured_reconciliation_difference(tmp_path):
    result = _check(
        tmp_path,
        [{"symbol": "SOLUSDT", "delta": "0.2"}],
    )

    assert result.status is Status.BLOCKED
    assert "account and journal reconciliation differs" in result.summary
    assert result.metrics["reconciliation_mismatch_count"] == 1
    assert "0.2" not in repr(result.metrics)
