# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: combine regime challengers without ever expanding execution risk.

"""Conservative defensive ensemble for SHADOW and separately approved APPLY."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping


D = Decimal
ONE = D("1")


@dataclass(frozen=True)
class RegimeVote:
    source: str
    label: str
    confidence: Decimal
    available: bool = True

    def __post_init__(self) -> None:
        if self.label not in {"DOWN", "FLAT", "UP", "PANIC"}:
            raise ValueError("unsupported regime vote")
        if not ZERO <= self.confidence <= ONE:
            raise ValueError("confidence must be within [0, 1]")


ZERO = D("0")


@dataclass(frozen=True)
class DefensiveEnsembleDecision:
    buy_allowed: bool
    cap_scale: Decimal
    reason: str
    disagreement: bool
    votes: tuple[RegimeVote, ...]


def conservative_regime_ensemble(
    votes: Mapping[str, RegimeVote],
    *,
    baseline_buy_allowed: bool,
    baseline_cap_scale: Decimal = ONE,
    veto_confidence: Decimal = D("0.55"),
) -> DefensiveEnsembleDecision:
    """Allow only baseline-equivalent or more conservative decisions.

    LLM is a challenger/veto only. It cannot override a deterministic or
    statistical veto and cannot make a baseline-disallowed BUY permissible.
    """
    if not ZERO <= baseline_cap_scale <= ONE:
        raise ValueError("baseline_cap_scale must be within [0, 1]")
    available = tuple(
        vote for _name, vote in sorted(votes.items()) if vote.available
    )
    labels = {vote.label for vote in available}
    disagreement = len(labels) > 1
    vetoes = [
        vote for vote in available
        if vote.label in {"DOWN", "PANIC"}
        and vote.confidence >= veto_confidence
    ]
    if not baseline_buy_allowed:
        return DefensiveEnsembleDecision(
            False,
            ZERO,
            "baseline strategy already forbids BUY",
            disagreement,
            available,
        )
    if vetoes:
        sources = ",".join(sorted(vote.source for vote in vetoes))
        return DefensiveEnsembleDecision(
            False,
            ZERO,
            f"defensive veto: {sources}",
            disagreement,
            available,
        )
    if disagreement:
        return DefensiveEnsembleDecision(
            False,
            ZERO,
            "predictor disagreement fails closed",
            True,
            available,
        )
    return DefensiveEnsembleDecision(
        True,
        min(ONE, baseline_cap_scale),
        "conservative predictors agree without expanding baseline risk",
        False,
        available,
    )
