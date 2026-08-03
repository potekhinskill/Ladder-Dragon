"""Executor configuration boundary tests."""

import pytest

from ladder_dragon.execution.executor_config import build_executor_parser


@pytest.mark.parametrize(
    "variable",
    (
        "BOT_FAST_MARKET_MAX_AGE_MS",
        "BOT_FAST_MARKET_MAX_SPREAD_BPS",
        "BOT_FAST_MARKET_MAX_MOVE_BPS",
        "BOT_FAST_MARKET_MIN_NET_EDGE_BPS",
    ),
)
def test_environment_numbers_fail_with_safe_parser_error(
    monkeypatch,
    capsys,
    variable,
):
    secret_marker = "invalid-value-MUST-NOT-LEAK"
    monkeypatch.setenv(variable, secret_marker)

    with pytest.raises(SystemExit) as exc:
        build_executor_parser()

    assert exc.value.code == 2
    diagnostic = capsys.readouterr().err
    assert variable in diagnostic
    assert secret_marker not in diagnostic
