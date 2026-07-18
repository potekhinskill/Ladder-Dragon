import json
import stat

from ladder_dragon.ai.ai_runtime_status import read_runtime_status, write_runtime_status


def test_runtime_status_is_atomic_private_and_versioned(tmp_path):
    target = tmp_path / "run" / "ai_status.json"

    write_runtime_status(target, {
        "state": "RUNNING",
        "venue": "testnet",
        "ai": {"mode": "SHADOW"},
    })

    payload = read_runtime_status(target)
    assert payload["schema_version"] == 1
    assert payload["state"] == "RUNNING"
    assert payload["venue"] == "testnet"
    assert payload["updated_at"]
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert not list(target.parent.glob("*.tmp"))
    assert json.loads(target.read_text())["ai"]["mode"] == "SHADOW"
