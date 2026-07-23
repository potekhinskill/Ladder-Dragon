import json

import pytest

from ladder_dragon.execution.maintenance_state import (
    clear_maintenance,
    load_maintenance_state,
    set_maintenance,
)


def test_maintenance_state_is_explicit_and_reversible(tmp_path):
    path = tmp_path / "maintenance.json"

    active = set_maintenance(
        path, "Operator intentionally stopped trading", now_epoch=100
    )

    assert active.active is True
    assert load_maintenance_state(path) == active
    assert path.stat().st_mode & 0o777 == 0o644
    cleared = clear_maintenance(path, now_epoch=200)
    assert cleared.active is False
    assert load_maintenance_state(path) == cleared


def test_maintenance_reason_rejects_secret_like_or_multiline_text(tmp_path):
    with pytest.raises(ValueError, match="reason"):
        set_maintenance(tmp_path / "maintenance.json", "token=abc\nsecret")


def test_damaged_maintenance_state_does_not_look_intentional(tmp_path):
    path = tmp_path / "maintenance.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "active": "yes",
        "reason": "Operator stop",
        "updated_at_epoch": 100,
    }))
    with pytest.raises(ValueError, match="fields"):
        load_maintenance_state(path)
