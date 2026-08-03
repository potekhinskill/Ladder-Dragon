import os
from pathlib import Path

import pytest

from ladder_dragon.execution.venue_config import apply_testnet_paths


def test_missing_testnet_paths_use_isolated_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("BOT_STATS_DB", str(tmp_path / "db" / "bot_stats.db"))
    monkeypatch.setenv(
        "BOT_ORDER_JOURNAL", str(tmp_path / "db" / "order_intents.sqlite3")
    )
    monkeypatch.setenv("BOT_RUN_DIR", "/run/mybot")
    monkeypatch.delenv("BOT_TESTNET_STATS_DB", raising=False)
    monkeypatch.delenv("BOT_TESTNET_ORDER_JOURNAL", raising=False)
    monkeypatch.delenv("BOT_TESTNET_RUN_DIR", raising=False)

    apply_testnet_paths()

    assert Path(os.environ["BOT_STATS_DB"]) == (
        tmp_path / "db" / "testnet_bot_stats.db"
    )
    assert Path(os.environ["BOT_ORDER_JOURNAL"]) == (
        tmp_path / "db" / "testnet_order_intents.sqlite3"
    )
    assert os.environ["BOT_RUN_DIR"] == "/run/mybot/testnet"
    assert os.environ["CB_HALT_FILE"] == (
        "/run/mybot/testnet/circuit_halt.json"
    )


def test_explicit_testnet_paths_replace_mainnet_as_one_set(tmp_path, monkeypatch):
    main = tmp_path / "main"
    test = tmp_path / "test"
    monkeypatch.setenv("BOT_STATS_DB", str(main / "stats.db"))
    monkeypatch.setenv("BOT_ORDER_JOURNAL", str(main / "orders.db"))
    monkeypatch.setenv("BOT_RUN_DIR", str(main / "run"))
    monkeypatch.setenv("BOT_TESTNET_STATS_DB", str(test / "stats.db"))
    monkeypatch.setenv("BOT_TESTNET_ORDER_JOURNAL", str(test / "orders.db"))
    monkeypatch.setenv("BOT_TESTNET_RUN_DIR", str(test / "run"))

    apply_testnet_paths()

    environ = os.environ
    assert environ["BOT_STATS_DB"] == str(test / "stats.db")
    assert environ["BOT_ORDER_JOURNAL"] == str(test / "orders.db")
    assert environ["BOT_RUN_DIR"] == str(test / "run")
    assert environ["CB_STATE_FILE"] == str(test / "run" / "risk_state.json")


@pytest.mark.parametrize(
    ("test_variable", "main_variable", "value", "reason"),
    (
        ("BOT_TESTNET_STATS_DB", "BOT_STATS_DB", "shared.db", "statistics"),
        (
            "BOT_TESTNET_ORDER_JOURNAL",
            "BOT_ORDER_JOURNAL",
            "shared.db",
            "order journal",
        ),
        ("BOT_TESTNET_RUN_DIR", "BOT_RUN_DIR", "shared-run", "runtime"),
    ),
)
def test_mainnet_path_reuse_fails_before_environment_changes(
    tmp_path,
    monkeypatch,
    test_variable,
    main_variable,
    value,
    reason,
):
    shared = str(tmp_path / value)
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv(test_variable, shared)
    monkeypatch.setenv(main_variable, shared)
    before = dict(os.environ)

    with pytest.raises(RuntimeError, match=reason):
        apply_testnet_paths()

    environ = os.environ
    for name in (
        "BOT_STATS_DB",
        "BOT_ORDER_JOURNAL",
        "BOT_RUN_DIR",
        "CB_HALT_FILE",
        "CB_STATE_FILE",
        "CB_ALERTS_FILE",
    ):
        assert environ.get(name) == before.get(name)


def test_testnet_databases_must_use_different_files(tmp_path, monkeypatch):
    shared = str(tmp_path / "shared.sqlite3")
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("BOT_TESTNET_STATS_DB", shared)
    monkeypatch.setenv("BOT_TESTNET_ORDER_JOURNAL", shared)

    with pytest.raises(RuntimeError, match="must differ"):
        apply_testnet_paths()


def test_collision_diagnostic_does_not_expose_path_values(tmp_path, monkeypatch):
    private_path = str(tmp_path / "private-location-marker")
    monkeypatch.setenv("BOT_STATS_DB", private_path)
    monkeypatch.setenv("BOT_TESTNET_STATS_DB", private_path)

    with pytest.raises(RuntimeError) as captured:
        apply_testnet_paths()

    assert "private-location-marker" not in str(captured.value)
