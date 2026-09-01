# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: test reusable financial and safety invariants over generated inputs.
"""Property and mutation tests for canonical semantic authorities."""

from __future__ import annotations

from decimal import Decimal
import math
from pathlib import Path

from hypothesis import assume, given, settings, strategies as st
import pytest

from bin.audit_exchange_boundaries import audit_exchange_boundaries
from bin.audit_guard_contracts import CRITICAL_GUARDS, audit_guard_contracts
from bin.audit_semantic_authorities import audit_semantic_authorities
from ladder_dragon.execution.trade_accounting import (
    KNOWN_QUOTE_ASSETS,
    VALUED_COMMISSION_STATUSES,
    commission_status_is_valued,
    symbol_assets,
)
from ladder_dragon.strategy.entry_veto_signal import (
    EntryVetoSignalAccumulator,
    order_flow_increment,
)
from ladder_dragon.strategy.indicators import (
    atr_ema_from_klines,
    atr_sma_from_klines,
    atr_wilder_from_klines,
)
from ladder_dragon.strategy.market_replay import BookLevel, MarketEvent


ROOT = Path(__file__).resolve().parents[1]
PROPERTY_SETTINGS = settings(max_examples=60, deadline=None)


@PROPERTY_SETTINGS
@given(
    base=st.sampled_from(("SOL", "XRP", "KERNEL", "ATOM", "ALPHA")),
    quote=st.sampled_from(KNOWN_QUOTE_ASSETS),
)
def test_canonical_symbol_assets_round_trip_known_vocabulary(
    base: str, quote: str
) -> None:
    assume(not base.endswith(quote))
    assert symbol_assets(base + quote) == (base, quote)


@PROPERTY_SETTINGS
@given(st.text(alphabet="abcdefghijklmnopqrstuvwxyz_-", min_size=1, max_size=24))
def test_commission_status_predicate_accepts_only_canonical_values(
    status: str,
) -> None:
    normalized = status.strip().lower()
    assert commission_status_is_valued(status) is (
        normalized in VALUED_COMMISSION_STATUSES
    )


def _klines(scale: int, *, include_open: bool = True) -> list[list[str]]:
    rows: list[list[str]] = []
    close = 100 * scale
    for index in range(24):
        close += ((index % 5) - 2) * scale
        high = close + (2 + index % 3) * scale
        low = close - (1 + index % 2) * scale
        rows.append([
            str(index), str(close), str(high), str(low), str(close), "1",
        ])
    if include_open:
        rows.append(["24", str(close), str(close + scale), str(close), str(close), "1"])
    return rows


@PROPERTY_SETTINGS
@given(st.integers(min_value=1, max_value=1000))
def test_named_atr_algorithms_scale_with_price(scale: int) -> None:
    baseline = _klines(1)
    scaled = _klines(scale)
    functions = (
        lambda rows: atr_wilder_from_klines(rows, 14, exclude_latest=True),
        lambda rows: atr_sma_from_klines(rows, 14, exclude_latest=False),
        lambda rows: atr_ema_from_klines(rows, 14, exclude_latest=False),
    )
    for function in functions:
        assert math.isclose(
            function(scaled), function(baseline) * scale, rel_tol=1e-12
        )


@PROPERTY_SETTINGS
@given(
    high=st.integers(min_value=1_000, max_value=1_000_000),
    low=st.integers(min_value=-1_000_000, max_value=-1_000),
)
def test_wilder_atr_never_uses_the_open_candle(high: int, low: int) -> None:
    rows = _klines(1)
    expected = atr_wilder_from_klines(rows, 14, exclude_latest=True)
    rows[-1][2] = str(high)
    rows[-1][3] = str(low)
    assert atr_wilder_from_klines(rows, 14, exclude_latest=True) == expected


@pytest.mark.parametrize(
    "function",
    (
        atr_wilder_from_klines,
        atr_sma_from_klines,
        atr_ema_from_klines,
    ),
)
def test_named_atr_requires_an_explicit_candle_population(function) -> None:
    with pytest.raises(TypeError, match="exclude_latest"):
        function(_klines(1), 14)


@PROPERTY_SETTINGS
@given(
    old_bid_qty=st.integers(min_value=1, max_value=10_000),
    bid_qty=st.integers(min_value=1, max_value=10_000),
    old_ask_qty=st.integers(min_value=1, max_value=10_000),
    ask_qty=st.integers(min_value=1, max_value=10_000),
)
def test_order_flow_increment_matches_all_six_cont_branches(
    old_bid_qty: int,
    bid_qty: int,
    old_ask_qty: int,
    ask_qty: int,
) -> None:
    old_bid = Decimal("100")
    old_ask = Decimal("103")
    previous = (
        old_bid,
        Decimal(old_bid_qty),
        old_ask,
        Decimal(old_ask_qty),
    )
    unchanged_ask = (old_ask, Decimal(old_ask_qty))
    unchanged_bid = (old_bid, Decimal(old_bid_qty))
    assert order_flow_increment(
        previous, (old_bid + 1, Decimal(bid_qty), *unchanged_ask)
    ) == Decimal(bid_qty)
    assert order_flow_increment(
        previous, (old_bid - 1, Decimal(bid_qty), *unchanged_ask)
    ) == -Decimal(old_bid_qty)
    assert order_flow_increment(
        previous, (old_bid, Decimal(bid_qty), *unchanged_ask)
    ) == Decimal(bid_qty - old_bid_qty)
    assert order_flow_increment(
        previous, (*unchanged_bid, old_ask - 1, Decimal(ask_qty))
    ) == -Decimal(ask_qty)
    assert order_flow_increment(
        previous, (*unchanged_bid, old_ask + 1, Decimal(ask_qty))
    ) == Decimal(old_ask_qty)
    assert order_flow_increment(
        previous, (*unchanged_bid, old_ask, Decimal(ask_qty))
    ) == Decimal(old_ask_qty - ask_qty)


def _signal_event(
    ts_ms: int,
    bid: str,
    bid_quantity: str,
    ask: str,
    ask_quantity: str,
    trade_side: str,
    trade_quantity: str,
) -> MarketEvent:
    return MarketEvent(
        ts_ms=ts_ms,
        bids=(BookLevel(Decimal(bid), Decimal(bid_quantity)),),
        asks=(BookLevel(Decimal(ask), Decimal(ask_quantity)),),
        trades=((Decimal(bid), Decimal(trade_quantity), trade_side),),
    )


def test_entry_veto_anchor_contribution_is_removed_exactly_once() -> None:
    accumulator = EntryVetoSignalAccumulator(window_ms=1_000)
    events = (
        _signal_event(0, "100", "10", "101", "10", "BUY", "1"),
        _signal_event(400, "101", "12", "102", "9", "SELL", "2"),
        _signal_event(1_100, "102", "8", "103", "7", "BUY", "3"),
        _signal_event(1_500, "101", "6", "102", "5", "SELL", "4"),
    )
    for event in events[:-1]:
        accumulator.update(event)

    first = accumulator.snapshot()
    assert first.order_flow_imbalance == Decimal("1")
    assert first.buy_quantity == Decimal("3")
    assert first.sell_quantity == Decimal("2")

    final = accumulator.update(events[-1])
    assert final.ready is True
    assert final.price_change_bps == Decimal("0")
    assert final.order_flow_imbalance == Decimal("4") / Decimal("30")
    assert final.signed_trade_flow == -Decimal("1") / Decimal("7")
    assert final.buy_quantity == Decimal("3")
    assert final.sell_quantity == Decimal("4")


def test_repository_semantic_and_transport_audits_pass() -> None:
    assert audit_semantic_authorities(ROOT)["violations"] == []
    assert audit_exchange_boundaries(ROOT)["violations"] == []
    assert audit_guard_contracts(ROOT)["violations"] == []


def test_semantic_audit_rejects_a_copied_quote_vocabulary(
    tmp_path: Path,
) -> None:
    package = tmp_path / "ladder_dragon" / "example"
    package.mkdir(parents=True)
    (tmp_path / "bin").mkdir()
    (package / "bad.py").write_text(
        'QUOTES = ("USDT", "USDC", "BTC", "ETH")\n',
        encoding="utf-8",
    )
    report = audit_semantic_authorities(tmp_path)
    assert any("copied quote vocabulary" in item for item in report["violations"])


def test_semantic_audit_rejects_an_inline_atr_consumer(tmp_path: Path) -> None:
    package = tmp_path / "ladder_dragon" / "strategy"
    package.mkdir(parents=True)
    (tmp_path / "bin").mkdir()
    (package / "bad.py").write_text(
        "def compute_atr(rows):\n    return sum(rows) / len(rows)\n",
        encoding="utf-8",
    )
    report = audit_semantic_authorities(tmp_path)
    assert any("ATR consumer bypasses authority" in item for item in report["violations"])


def test_semantic_audit_rejects_an_implicit_atr_candle_population(
    tmp_path: Path,
) -> None:
    package = tmp_path / "ladder_dragon" / "strategy"
    package.mkdir(parents=True)
    (tmp_path / "bin").mkdir()
    (package / "bad.py").write_text(
        "def compute_atr(rows):\n"
        "    return atr_wilder_from_klines(rows, 14)\n",
        encoding="utf-8",
    )
    report = audit_semantic_authorities(tmp_path)
    assert any(
        "ATR call omits candle population" in item
        for item in report["violations"]
    )


def test_semantic_audit_rejects_an_unknown_fee_rate_literal(tmp_path: Path) -> None:
    package = tmp_path / "ladder_dragon" / "strategy"
    package.mkdir(parents=True)
    (tmp_path / "bin").mkdir()
    (package / "bad.py").write_text(
        'from decimal import Decimal\ndefault_fee_pct = Decimal("0.0015")\n',
        encoding="utf-8",
    )
    report = audit_semantic_authorities(tmp_path)
    assert any(
        "hardcoded fee-rate literal outside authority" in item
        for item in report["violations"]
    )


@pytest.mark.parametrize(
    "source",
    (
        "def model(maker_fee_pct: Decimal = Decimal(\"0.0015\")):\n"
        "    return maker_fee_pct\n",
        "def model(*, maker_fee_pct: Decimal = Decimal(\"0.0015\")):\n"
        "    return maker_fee_pct\n",
        "result = model(maker_fee_pct=Decimal(\"0.0015\"))\n",
    ),
)
def test_semantic_audit_rejects_fee_rate_defaults_and_keywords(
    tmp_path: Path,
    source: str,
) -> None:
    package = tmp_path / "ladder_dragon" / "strategy"
    package.mkdir(parents=True)
    (tmp_path / "bin").mkdir()
    (package / "bad.py").write_text(
        "from decimal import Decimal\n" + source,
        encoding="utf-8",
    )
    report = audit_semantic_authorities(tmp_path)
    assert any(
        "hardcoded fee-rate literal outside authority" in item
        for item in report["violations"]
    )


def test_semantic_audit_allows_fee_amounts_and_error_thresholds(
    tmp_path: Path,
) -> None:
    package = tmp_path / "ladder_dragon" / "strategy"
    package.mkdir(parents=True)
    (tmp_path / "bin").mkdir()
    (package / "good.py").write_text(
        "from decimal import Decimal\n"
        "fees_quote = Decimal(\"0\")\n"
        "maximum_fee_error_quote_mae = Decimal(\"0.02\")\n",
        encoding="utf-8",
    )
    assert audit_semantic_authorities(tmp_path)["violations"] == []


def test_semantic_audit_allows_imported_fee_rate_authority(tmp_path: Path) -> None:
    package = tmp_path / "ladder_dragon" / "strategy"
    package.mkdir(parents=True)
    (tmp_path / "bin").mkdir()
    (package / "good.py").write_text(
        "from ladder_dragon.strategy.fee_defaults import "
        "DEFAULT_RESEARCH_MAKER_FEE_PCT\n"
        "def model(maker_fee_pct=DEFAULT_RESEARCH_MAKER_FEE_PCT):\n"
        "    return maker_fee_pct\n",
        encoding="utf-8",
    )
    assert audit_semantic_authorities(tmp_path)["violations"] == []


def test_exchange_audit_rejects_a_new_direct_mutation(tmp_path: Path) -> None:
    package = tmp_path / "ladder_dragon" / "execution"
    package.mkdir(parents=True)
    (package / "bad.py").write_text(
        'def submit(client):\n    return client.signed_request("POST", "/api/v3/order")\n',
        encoding="utf-8",
    )
    report = audit_exchange_boundaries(tmp_path)
    assert any("unapproved POST" in item for item in report["violations"])


def test_guard_audit_kills_a_removed_rejection_mutant(tmp_path: Path) -> None:
    for relative in CRITICAL_GUARDS:
        source = (ROOT / relative).read_text(encoding="utf-8")
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source, encoding="utf-8")
    target = tmp_path / "ladder_dragon/supervision/execution_promotion.py"
    source = target.read_text(encoding="utf-8")
    old = '''def require_safe_execution_scope(report: Mapping[str, object]) -> None:
    """Reject blocked execution when a caller requires a ready scope."""
    blocked = report.get("blocked_execution_symbols")
    if isinstance(blocked, list) and blocked:
        symbols = ",".join(str(item) for item in blocked)
        raise ValueError(
            "execution promotion is blocked for staged symbols: " + symbols
        )
'''
    new = '''def require_safe_execution_scope(report: Mapping[str, object]) -> None:
    """Mutant without a rejection path."""
    if report.get("blocked_execution_symbols"):
        return None
'''
    assert old in source
    target.write_text(source.replace(old, new), encoding="utf-8")
    report = audit_guard_contracts(tmp_path)
    assert any(
        item.endswith("require_safe_execution_scope:no rejection path")
        for item in report["violations"]
    )


def test_guard_audit_kills_a_class_method_rejection_mutant(tmp_path: Path) -> None:
    for relative in CRITICAL_GUARDS:
        source = (ROOT / relative).read_text(encoding="utf-8")
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source, encoding="utf-8")
    target = tmp_path / "ladder_dragon/execution/time_safety.py"
    source = target.read_text(encoding="utf-8")
    old = '''    def require_safe(self) -> None:
        if not self.safe:
            raise RuntimeError(self.reason)
'''
    new = '''    def require_safe(self) -> None:
        if not self.safe:
            return None
'''
    assert old in source
    target.write_text(source.replace(old, new), encoding="utf-8")
    report = audit_guard_contracts(tmp_path)
    assert any(
        item.endswith("ClockCheck.require_safe:no rejection path")
        for item in report["violations"]
    )


def test_guard_audit_rejects_a_missing_registered_class_method(
    tmp_path: Path,
) -> None:
    for relative in CRITICAL_GUARDS:
        source = (ROOT / relative).read_text(encoding="utf-8")
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source, encoding="utf-8")
    target = tmp_path / "ladder_dragon/execution/time_safety.py"
    source = target.read_text(encoding="utf-8")
    old = "    def require_safe(self) -> None:\n"
    assert old in source
    target.write_text(
        source.replace(old, "    def unregistered_safe(self) -> None:\n"),
        encoding="utf-8",
    )
    report = audit_guard_contracts(tmp_path)
    assert any(
        item.endswith("ClockCheck.require_safe:missing")
        for item in report["violations"]
    )


def test_unknown_symbol_suffix_fails_closed() -> None:
    with pytest.raises(ValueError, match="cannot determine assets"):
        symbol_assets("SOLXYZ")
