# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: freeze replay calibration and validation acceptance rules.
"""Immutable acceptance policy for empirical execution replay evidence."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
from typing import Mapping


def _canonical(payload: Mapping[str, object]) -> str:
    return json.dumps(dict(payload), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class ReplayAcceptancePolicy:
    """Define the only policy accepted by production replay import."""

    policy_id: str = "REPLAY_ACCEPTANCE_V1"
    minimum_orders: int = 10
    minimum_classification_accuracy: Decimal = Decimal("0.80")
    maximum_fill_ratio_mae: Decimal = Decimal("0.25")
    maximum_price_error_bps_mae: Decimal = Decimal("10")
    maximum_latency_error_ms_mae: Decimal = Decimal("1000")
    maximum_fee_error_quote_mae: Decimal = Decimal("0.02")
    maximum_slippage_error_bps_mae: Decimal = Decimal("10")
    minimum_book_events: int = 100
    minimum_trades: int = 50
    require_zero_excluded_orders: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "minimum_orders": self.minimum_orders,
            "minimum_classification_accuracy": format(
                self.minimum_classification_accuracy, "f"
            ),
            "maximum_fill_ratio_mae": format(self.maximum_fill_ratio_mae, "f"),
            "maximum_price_error_bps_mae": format(
                self.maximum_price_error_bps_mae, "f"
            ),
            "maximum_latency_error_ms_mae": format(
                self.maximum_latency_error_ms_mae, "f"
            ),
            "maximum_fee_error_quote_mae": format(
                self.maximum_fee_error_quote_mae, "f"
            ),
            "maximum_slippage_error_bps_mae": format(
                self.maximum_slippage_error_bps_mae, "f"
            ),
            "minimum_book_events": self.minimum_book_events,
            "minimum_trades": self.minimum_trades,
            "require_zero_excluded_orders": self.require_zero_excluded_orders,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(_canonical(self.as_dict()).encode()).hexdigest()

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "ReplayAcceptancePolicy":
        return cls(
            policy_id=str(payload.get("policy_id", "")),
            minimum_orders=int(payload.get("minimum_orders", 0)),
            minimum_classification_accuracy=Decimal(str(
                payload.get("minimum_classification_accuracy", "0")
            )),
            maximum_fill_ratio_mae=Decimal(str(
                payload.get("maximum_fill_ratio_mae", "0")
            )),
            maximum_price_error_bps_mae=Decimal(str(
                payload.get("maximum_price_error_bps_mae", "0")
            )),
            maximum_latency_error_ms_mae=Decimal(str(
                payload.get("maximum_latency_error_ms_mae", "0")
            )),
            maximum_fee_error_quote_mae=Decimal(str(
                payload.get("maximum_fee_error_quote_mae", "0")
            )),
            maximum_slippage_error_bps_mae=Decimal(str(
                payload.get("maximum_slippage_error_bps_mae", "0")
            )),
            minimum_book_events=int(payload.get("minimum_book_events", 0)),
            minimum_trades=int(payload.get("minimum_trades", 0)),
            require_zero_excluded_orders=(
                payload.get("require_zero_excluded_orders") is True
            ),
        )


PRODUCTION_REPLAY_ACCEPTANCE_POLICY = ReplayAcceptancePolicy()


__all__ = ["PRODUCTION_REPLAY_ACCEPTANCE_POLICY", "ReplayAcceptancePolicy"]
