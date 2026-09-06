"""Prove reuse of the validated preflight account for startup auto-cap."""

import inspect
import os
from decimal import Decimal
from types import SimpleNamespace

from ladder_dragon.supervision import runtime
from ladder_dragon.supervision import risk_cycle


def test_auto_cap_reuses_preflight_balances_without_signed_read(monkeypatch):
    args = SimpleNamespace(
        auto_cap=True,
        alloc_pct="0.50",
        cap_floor_usdt="5",
        cap_ceil_usdt="10",
        target_buy_per_symbol=1,
    )
    monkeypatch.setenv("RISK_RESERVE_USDT", "300")
    monkeypatch.setattr(
        runtime.TM,
        "_signed_get",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("unexpected account read")
        ),
    )
    account = {
        "balances": [
            {"asset": "USDT", "free": "331.09148973", "locked": "0"}
        ]
    }

    cap = runtime.auto_cap_if_needed(
        args,
        n_syms=1,
        balances=account,
    )

    assert cap == Decimal("10")
    assert os.environ["BOT_CAP_PER_ORDER"] == "10.00"


def test_risk_snapshot_keeps_an_independent_fresh_account_read():
    source = inspect.getsource(risk_cycle.build_risk_snapshot)

    assert "balances = get_balances_full()" in source
