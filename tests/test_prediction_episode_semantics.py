"""Fail-closed contracts for the executable episode regime classifier."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from ladder_dragon.strategy.prediction.episode_semantics import (
    require_runtime_regime_contract,
)
from ladder_dragon.supervision.config import build_supervisor_parser


def _arguments(**changes):
    values = {
        "dir_mode": "auto",
        "dir_interval": "30m",
        "dir_eps": 0.0005,
        "dir_slope_min": 0.0002,
        "dir_adx_min": 16.0,
        "dir_confirm_bars": 3,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def test_runtime_classifier_requires_the_complete_frozen_contract():
    require_runtime_regime_contract("SOLUSDT", _arguments(), {})

    with pytest.raises(ValueError, match="automatic mode"):
        require_runtime_regime_contract(
            "SOLUSDT", _arguments(dir_mode="flat"), {}
        )
    with pytest.raises(ValueError, match="differs from v21"):
        require_runtime_regime_contract(
            "SOLUSDT", _arguments(), {"BOT_REGIME_CONFIRMATIONS": "2"}
        )


def test_classifier_contract_runs_before_the_worker_mutation_boundary():
    source = Path("ladder_dragon/supervision/runtime.py").read_text(
        encoding="utf-8"
    )
    validation = source.index(
        "require_runtime_regime_contract(symbol, args, os.environ)"
    )
    plan = source.index("now_p = get_last_price(symbol)", validation)
    worker = source.index("\n            run_child(", validation)

    assert validation < plan
    assert validation < worker


def test_removed_direction_hysteresis_option_cannot_silently_drift():
    _args, unknown = build_supervisor_parser().parse_known_args([
        "--dir-hyst-bars", "9",
    ])

    assert unknown == ["--dir-hyst-bars", "9"]
