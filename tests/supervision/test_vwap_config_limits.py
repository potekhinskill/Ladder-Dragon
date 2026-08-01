"""Strict contracts for financial position-limit maps."""

from decimal import Decimal

import pytest

from ladder_dragon.supervision.vwap_config import parse_decimal_limit_map


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
