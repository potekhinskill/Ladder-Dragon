# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: prove one uncertain BUY submission stops every later batch mutation.
"""Fail-closed BUY batch tests for lost exchange acknowledgements."""

from decimal import Decimal

import pytest
import requests

from ladder_dragon.execution.order_recovery import OrderJournal
from ladder_dragon.execution.orders.reconciliation import UncertainOrderSubmission
from ladder_dragon.execution.orders.runtime import OrderDependencies, place_limit_order
from ladder_dragon.execution.worker.buy_service import place_buys
from tests.support.module_loaders import load_worker


def test_lost_limit_ack_raises_typed_uncertainty_after_halt(tmp_path):
    journal = OrderJournal(tmp_path / "orders.sqlite3")
    halts = []
    dependencies = OrderDependencies(
        live=lambda: True,
        logger=lambda _message: None,
        pull_filters=lambda _symbol: None,
        round_price=lambda _symbol, value: value,
        round_qty=lambda _symbol, value: value,
        min_qty=lambda _symbol, _hint: Decimal("0.001"),
        min_notional=lambda _symbol, _price: Decimal("5"),
        format_price=lambda _symbol, value: f"{value:.2f}",
        format_qty=lambda _symbol, value: f"{value:.3f}",
        journal=lambda: journal,
        signed_request=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            requests.Timeout("response lost")
        ),
        get_order_by_client_id=lambda _symbol, _client_id: None,
        get_order_list_by_client_id=lambda _client_id: None,
        verify_oco_legs=lambda _symbol, _payload: [],
        cancel_oco=lambda _symbol, _order_list_id: None,
        halt=lambda reason, **metadata: halts.append((reason, metadata)),
        validate_limit_sell_prices=lambda _symbol, _prices: None,
    )

    with pytest.raises(UncertainOrderSubmission):
        place_limit_order(
            "BUY", "SOLUSDT", Decimal("0.1"), Decimal("100"),
            dependencies=dependencies,
        )

    assert len(halts) == 1
    assert journal.nonterminal_orders()[0].state == "UNKNOWN"


def test_uncertain_first_buy_prevents_second_batch_post(monkeypatch):
    worker = load_worker()
    worker.RUN = True
    posts = []
    monkeypatch.setenv("RISK_MANAGED_INVENTORY_HARD_CAP_SOLUSDT", "30")
    monkeypatch.setenv("RISK_RESERVE_USDT", "0")
    monkeypatch.setattr(worker, "get_symbol_assets", lambda _symbol: ("SOL", "USDT"))
    monkeypatch.setattr(
        worker, "get_balances",
        lambda: {"SOL": {"free": "0", "locked": "0"}, "USDT": {"free": "30", "locked": "0"}},
    )
    monkeypatch.setattr(worker, "get_price_exact", lambda _symbol: Decimal("100"))
    monkeypatch.setattr(worker, "list_open_orders", lambda _symbol: [])
    monkeypatch.setattr(
        worker, "buy_candidates_decimal",
        lambda *_args, **_kwargs: [Decimal("90"), Decimal("80")],
    )
    worker.symbol_filters["SOLUSDT"] = {
        "tickSize": 0.01, "stepSize": 0.001,
        "minQty": 0.001, "minNotional": 5.0,
    }

    def uncertain(*_args, **_kwargs):
        posts.append("POST")
        raise UncertainOrderSubmission("lost acknowledgement")

    monkeypatch.setattr(worker, "place_limit_order", uncertain)

    result = place_buys(
        "SOLUSDT", [90.0, 80.0], Decimal("10"),
        target_buy_per_symbol=2, live_mode=True, runtime=vars(worker),
    )

    assert result == []
    assert posts == ["POST"]
