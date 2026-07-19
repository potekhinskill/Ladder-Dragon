import json
import stat

import pytest

from ladder_dragon.ai.ai_control import (
    PROJECT_ROOT,
    read_ai_control,
    resolve_ai_control_path,
    write_ai_control,
)


def test_ai_control_is_atomic_versioned_and_private(tmp_path):
    target = tmp_path / "ai_control.json"
    document = write_ai_control(target, enabled=True, mode="APPLY")

    assert document["schema_version"] == 1
    assert read_ai_control(target)["mode"] == "APPLY"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert not list(target.parent.glob("*.tmp"))


def test_disabling_ai_forces_disabled_mode(tmp_path):
    target = tmp_path / "ai_control.json"
    write_ai_control(target, enabled=False, mode="APPLY")
    payload = read_ai_control(target)
    assert payload["enabled"] is False
    assert payload["mode"] == "DISABLED"


def test_invalid_ai_control_fails_closed(tmp_path):
    target = tmp_path / "ai_control.json"
    target.write_text(json.dumps({"schema_version": 1, "enabled": "yes", "mode": "APPLY"}))
    with pytest.raises(ValueError):
        read_ai_control(target)

    target.write_text(json.dumps({"schema_version": 1, "enabled": True, "mode": "DISABLED"}))
    with pytest.raises(ValueError):
        read_ai_control(target)


def test_ai_control_path_is_canonical_and_independent_of_cwd(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    expected = PROJECT_ROOT / "FastAPI/pi-dashboard/data/ai_control.json"
    assert resolve_ai_control_path() == expected
    assert resolve_ai_control_path("FastAPI/pi-dashboard/data/ai_control.json") == expected

    absolute = tmp_path / "private-control.json"
    assert resolve_ai_control_path(absolute) == absolute
