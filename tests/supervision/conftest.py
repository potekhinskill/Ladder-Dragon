"""Keep fail-closed supervision tests away from operator control files."""

import pytest


@pytest.fixture(autouse=True)
def isolated_control(tmp_path, monkeypatch):
    for key, name in (("CB_HALT_FILE", "halt.json"), ("CB_STATE_FILE", "risk.json"),
                      ("CB_ALERTS_FILE", "alerts.jsonl")):
        monkeypatch.setenv(key, str(tmp_path / name))
