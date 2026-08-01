# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: parse and resolve supervisor VWAP configuration.
"""Parse and resolve supervisor VWAP configuration without runtime coupling."""

from __future__ import annotations

import argparse
import os
import re
from decimal import Decimal
from typing import Collection, Dict, Optional, Tuple

from ladder_dragon.numeric_compat import compatibility_float
from ladder_dragon.supervision.entry_policy import finite_decimal


def _analytics_float(value: object) -> float:
    return compatibility_float(value, field="analytics value")


def parse_pct_map(value: str) -> Dict[str, Tuple[float, float, float]]:
    result: Dict[str, Tuple[float, float, float]] = {}
    if not value:
        return result
    for raw in value.split(";"):
        if not raw.strip() or "=" not in raw:
            continue
        key, encoded = raw.split("=", 1)
        parts = [item.strip() for item in encoded.split(",")]
        if len(parts) != 3:
            continue
        try:
            result[key.strip()] = tuple(_analytics_float(item) for item in parts)
        except (TypeError, ValueError, OverflowError):
            continue
    return result


def parse_limit_map(value: str) -> Dict[str, float]:
    result: Dict[str, float] = {}
    if not value:
        return result
    for raw in value.split(","):
        if not raw.strip() or ":" not in raw:
            continue
        key, encoded = raw.split(":", 1)
        try:
            result[key.strip()] = _analytics_float(encoded.strip())
        except (TypeError, ValueError, OverflowError):
            continue
    return result


def parse_decimal_limit_map(
    value: str,
    *,
    option_name: str = "position limit map",
    allowed_symbols: Collection[str] | None = None,
) -> Dict[str, Decimal]:
    """Parse every financial limit or reject the complete malformed map."""
    result: Dict[str, Decimal] = {}
    if not value:
        return result
    allowed = set(allowed_symbols) if allowed_symbols is not None else None
    for index, raw in enumerate(value.split(","), start=1):
        if not raw.strip() or raw.count(":") != 1:
            raise ValueError(
                f"{option_name} item {index} must use SYMBOL:VALUE"
            )
        key, encoded = raw.split(":", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Z0-9]{5,20}", key):
            raise ValueError(
                f"{option_name} item {index} has an invalid symbol"
            )
        if key in result:
            raise ValueError(f"{option_name} contains duplicate symbols")
        if allowed is not None and key not in allowed:
            raise ValueError(
                f"{option_name} contains a symbol outside --symbols"
            )
        try:
            parsed = finite_decimal(
                encoded.strip(),
                name=f"limit for {key}",
            )
        except ValueError as exc:
            raise ValueError(
                f"{option_name} item {index} has an invalid value"
            ) from exc
        if parsed < 0:
            raise ValueError(f"{option_name} values must be non-negative")
        result[key] = parsed
    return result


def normalize_runtime_args(
    args: argparse.Namespace,
    symbols: Collection[str] | None = None,
) -> None:
    """Normalize planning arguments before any retry loop can use them."""
    if isinstance(args.ladder_pct, str):
        ladder_pct = [
            item.strip() for item in args.ladder_pct.split(",")
        ]
        if len(ladder_pct) != 3:
            raise SystemExit(
                "--ladder-pct expects three numbers: low,down,up"
            )
        args.ladder_pct = tuple(
            _analytics_float(item) for item in ladder_pct
        )
    if isinstance(args.ladder_pct_map, str):
        args.ladder_pct_map = parse_pct_map(args.ladder_pct_map)
    if isinstance(args.pos_max_base_map, str):
        args.pos_max_base_map = parse_decimal_limit_map(
            args.pos_max_base_map,
            option_name="--pos-max-base-map",
            allowed_symbols=symbols,
        )
    if isinstance(args.pos_max_usdt_map, str):
        args.pos_max_usdt_map = parse_decimal_limit_map(
            args.pos_max_usdt_map,
            option_name="--pos-max-usdt-map",
            allowed_symbols=symbols,
        )
    for name in (
        "child_buy_vwap_premium_map",
        "child_buy_vwap_discount_map",
        "child_buy_vwap_discount_scale_map",
    ):
        value = getattr(args, name, "")
        if isinstance(value, str):
            setattr(args, name, parse_limit_map(value))


def getenv_float(name: str, default: Optional[float] = None) -> Optional[float]:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return _analytics_float(value)
    except (TypeError, ValueError, OverflowError):
        return default


def resolve_vwap_value(
    symbol: str,
    base: Optional[float],
    mapping: Optional[Dict[str, float]],
    env_name: str,
    fallback: Optional[float] = None,
) -> Optional[float]:
    if mapping and symbol in mapping:
        return mapping[symbol]
    if base is not None:
        return base
    return getenv_float(env_name, fallback)


def resolve_vwap_params(
    symbol: str,
    dir_mode: str,
    atr_pct: float,
    args: argparse.Namespace,
) -> tuple[
    Optional[float],
    Optional[float],
    Optional[float],
    Optional[str],
    Optional[int],
]:
    premium = resolve_vwap_value(
        symbol,
        getattr(args, "child_buy_vwap_premium", None),
        getattr(args, "child_buy_vwap_premium_map", {}),
        "BUY_VWAP_PREMIUM",
    )
    discount = resolve_vwap_value(
        symbol,
        getattr(args, "child_buy_vwap_discount", None),
        getattr(args, "child_buy_vwap_discount_map", {}),
        "BUY_VWAP_DISCOUNT",
    )
    scale = resolve_vwap_value(
        symbol,
        getattr(args, "child_buy_vwap_discount_scale", None),
        getattr(args, "child_buy_vwap_discount_scale_map", {}),
        "BUY_VWAP_DISCOUNT_SCALE",
        fallback=1.0,
    )
    scale = 1.0 if scale is None else scale

    if args.child_buy_vwap_auto:
        mode = (dir_mode or "").upper()
        if premium is not None:
            multiplier = 1.0
            if mode == "UP":
                multiplier *= max(
                    0.05,
                    _analytics_float(args.child_buy_vwap_premium_up_mult),
                )
            elif mode == "DOWN":
                multiplier *= max(
                    0.05,
                    _analytics_float(args.child_buy_vwap_premium_down_mult),
                )
            if atr_pct and args.child_buy_vwap_premium_atr_coef:
                multiplier *= max(
                    0.1,
                    1.0
                    - atr_pct
                    * _analytics_float(args.child_buy_vwap_premium_atr_coef),
                )
            premium *= multiplier
        if scale is not None and atr_pct and args.child_buy_vwap_discount_scale_atr_coef:
            scale *= 1.0 + max(0.0, atr_pct) * _analytics_float(
                args.child_buy_vwap_discount_scale_atr_coef
            )

    floor = max(0.0, _analytics_float(args.child_buy_vwap_premium_floor))
    ceiling = max(floor, _analytics_float(args.child_buy_vwap_premium_ceil))
    if premium is not None:
        premium = max(floor, min(ceiling, premium))

    scale_min = max(
        0.1,
        _analytics_float(args.child_buy_vwap_discount_scale_min),
    )
    scale_max = max(
        scale_min,
        _analytics_float(args.child_buy_vwap_discount_scale_max),
    )
    if scale is not None:
        scale = max(scale_min, min(scale_max, scale))
        if abs(scale - 1.0) < 1e-4:
            scale = None
    if discount is not None and discount <= 0:
        discount = None

    interval = getattr(args, "child_buy_vwap_interval", None) or os.getenv(
        "BUY_VWAP_INTERVAL"
    )
    if interval:
        interval = interval.strip() or None
    if getattr(args, "child_buy_vwap_window", None) is not None:
        window: Optional[int] = int(args.child_buy_vwap_window)
    else:
        encoded_window = os.getenv("BUY_VWAP_WINDOW")
        try:
            window = int(encoded_window) if encoded_window else None
        except (TypeError, ValueError, OverflowError):
            window = None
    return premium, discount, scale, interval, window


def _parse_vwap_line(value: str) -> Dict[str, float]:
    mapping: Dict[str, float] = {}
    for raw in value.split(",") if value else ():
        if not raw.strip() or ":" not in raw:
            continue
        symbol, encoded = raw.split(":", 1)
        try:
            mapping[symbol.strip().upper()] = _analytics_float(encoded)
        except (TypeError, ValueError, OverflowError):
            continue
    return mapping


def parse_vwap_output(
    text: str,
) -> tuple[Dict[str, float], Dict[str, float], Dict[str, float]]:
    premium: Dict[str, float] = {}
    discount: Dict[str, float] = {}
    scale: Dict[str, float] = {}
    for raw in text.splitlines() if text else ():
        if not raw.strip() or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        mapping = _parse_vwap_line(value.strip())
        normalized = key.strip().upper()
        if normalized.endswith("DISCOUNT_SCALE_MAP"):
            scale.update(mapping)
        elif normalized.endswith("PREMIUM_MAP"):
            premium.update(mapping)
        elif normalized.endswith("DISCOUNT_MAP"):
            discount.update(mapping)
    return premium, discount, scale
