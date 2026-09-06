"""Strict contracts for financial position-limit maps."""

from decimal import Decimal
import math
from types import SimpleNamespace

import pytest

from ladder_dragon.supervision.vwap_config import (
    next_vwap_refresh_epoch,
    parse_decimal_limit_map,
)


def test_next_vwap_refresh_retains_disabled_and_jittered_schedule():
    assert math.isinf(next_vwap_refresh_epoch(SimpleNamespace(
        vwap_refresh_sec=0, vwap_refresh_jitter_sec=10)))
    args = SimpleNamespace(vwap_refresh_sec=30, vwap_refresh_jitter_sec=5)

    assert next_vwap_refresh_epoch(
        args,
        now=lambda: 100.0,
        uniform=lambda low, high: (low + high) / 2,
    ) == 130.0


def test_decimal_limit_map_accepts_exact_configured_symbols():
    parsed = parse_decimal_limit_map(
        "SOLUSDT:0.126,ETHUSDT:10.00",
        option_name="--pos-max-base-map",
        allowed_symbols={"SOLUSDT", "ETHUSDT"},
    )

    assert parsed == {
        "SOLUSDT": Decimal("0.126"),
        "ETHUSDT": Decimal("10.00"),
    }


@pytest.mark.parametrize(
    "value",
    [
        "SOLUSDT=0.126",
        "SOLUSDT:bad",
        "SOLUSDT:NaN",
        "SOLUSDT:-0.126",
        "SOLUSDT:0.126,",
        "SOLUSDT:0.126,SOLUSDT:0.127",
        "solusdt:0.126",
    ],
)
def test_decimal_limit_map_rejects_the_complete_malformed_value(value):
    with pytest.raises(ValueError):
        parse_decimal_limit_map(
            value,
            option_name="--pos-max-base-map",
            allowed_symbols={"SOLUSDT"},
        )


def test_decimal_limit_map_rejects_valid_but_unconfigured_symbol():
    with pytest.raises(ValueError, match="outside --symbols"):
        parse_decimal_limit_map(
            "SOLUSTD:0.126",
            option_name="--pos-max-base-map",
            allowed_symbols={"SOLUSDT"},
        )
