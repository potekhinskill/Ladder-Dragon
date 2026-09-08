"""Exercise startup balance reuse through the real producer and risk consumer."""

import os
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest

from ladder_dragon.supervision import runtime


@pytest.fixture
def startup(monkeypatch, tmp_path):
    args = SimpleNamespace(
        live=True, testnet=False, auto_cap=True, alloc_pct="0.50",
        cap_floor_usdt="5", cap_ceil_usdt="50", target_buy_per_symbol=1,
    )
    limits = runtime.RiskLimits.from_mapping({"RISK_RESERVE_USDT": "10"})
    limits = replace(limits, halt_file=tmp_path / "halt.json")
    for name, value in {
        "BOT_STATS_DB": str(tmp_path / "stats.sqlite3"),
        "BOT_CAP_PER_ORDER": "50", "RISK_RESERVE_USDT": "10",
        "RISK_CONVERSION_DEPTH_REQUIRED": "0", "RISK_BATCH_TICKERS": "0",
        "RISK_RECONCILE_SYNC_FILLS": "0", "RISK_RECONCILE_STRICT": "0",
        "RISK_PUBLIC_READ_CONCURRENCY": "1",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(runtime.TM, "API_KEY", "configured")
    monkeypatch.setattr(runtime.TM, "API_SECRET", "configured")
    monkeypatch.setattr(runtime, "_FILTERS_CACHE", {})
    monkeypatch.setattr(runtime, "_configured_unvalued_assets", lambda: set())
    monkeypatch.setattr(runtime, "_record_preflight_startup_phase", lambda *_a: None)
    monkeypatch.setattr(runtime, "_record_risk_startup_phase", lambda *_a: None)
    monkeypatch.setattr(runtime, "_log_info_rate_limited", lambda *_a, **_kw: None)
    monkeypatch.setattr(runtime, "_control_mode", lambda _name: "OFF")
    monkeypatch.setattr(runtime, "load_daily_trade_metrics", lambda *_a, **_kw: {})
    monkeypatch.setattr(runtime, "get_initial_last_price_decimal", lambda _s: Decimal("100"))
    monkeypatch.setattr(runtime, "LIVE_MODE", True)
    monkeypatch.setattr(runtime, "_runtime_protection_gate", lambda *_a, **_kw: None)
    monkeypatch.setattr(runtime, "read_clock_and_filters", lambda *_a, **_kw: {
        "SOLUSDT": dict(tickSize=1, stepSize=1, minQty=1, minNotional=1),
    })
    return args, limits


def account(free, *, locked="0", can_trade=True):
    return {"canTrade": can_trade, "balances": [
        {"asset": "USDT", "free": free, "locked": locked},
    ]}


def test_preflight_to_cap_and_fresh_risk(startup, monkeypatch):
    args, limits = startup
    calls = []
    responses = iter([
        account("100.123456789123456789", locked="100"),
        account("12"), [], account("9"), [],
    ])

    def signed_get(path):
        calls.append(path)
        return next(responses)

    monkeypatch.setattr(runtime.TM, "_signed_get", signed_get)
    balances = runtime._preflight_live(args, ["SOLUSDT"], limits)
    assert balances == {"USDT": Decimal("100.123456789123456789")}
    cap = runtime.auto_cap_if_needed(args, 1, balances)
    assert cap == Decimal("45.0617283945617283945")
    assert os.environ["BOT_CAP_PER_ORDER"] == "45.06"
    assert calls == ["/api/v3/account"]

    # The initial allocation is not authority for a later account balance.
    first, _, _ = runtime._build_risk_snapshot(["SOLUSDT"], limits)
    assert first.free_usdt == Decimal("12")
    assert min(cap, runtime._remaining_order_budget_decimal(limits, first)) == Decimal("2")
    second, _, _ = runtime._build_risk_snapshot(["SOLUSDT"], limits)
    assert second.free_usdt == Decimal("9")
    assert runtime._remaining_order_budget_decimal(limits, second) < 0
    assert calls == ["/api/v3/account", "/api/v3/account", "/api/v3/openOrders",
                     "/api/v3/account", "/api/v3/openOrders"]


@pytest.mark.parametrize("free", ["0", "9", "19.999999999999999999"])
def test_preflight_low_balance_closes_cap(startup, monkeypatch, free):
    args, limits = startup
    calls = []
    monkeypatch.setattr(runtime.TM, "_signed_get", lambda path: calls.append(path) or account(free))
    balances = runtime._preflight_live(args, ["SOLUSDT"], limits)
    assert runtime.auto_cap_if_needed(args, 1, balances) == Decimal("0")
    assert os.environ["BOT_CAP_PER_ORDER"] == "0"
    assert calls == ["/api/v3/account"]


@pytest.mark.parametrize("balances", [{}, {"USDT": "private-marker"},
                         {"USDT": Decimal("NaN")}, {"USDT": Decimal("Infinity")}])
def test_invalid_projection_closes_cap(startup, monkeypatch, capsys, balances):
    args, _ = startup
    def forbidden(*_a, **_kw):
        raise AssertionError("unexpected account retry")
    monkeypatch.setattr(runtime.TM, "_signed_get", forbidden)
    assert runtime.auto_cap_if_needed(args, 1, balances) == Decimal("0")
    assert os.environ["BOT_CAP_PER_ORDER"] == "0"
    assert "private-marker" not in str(capsys.readouterr())


def test_dry_preflight_uses_uncached_cap_read(startup, monkeypatch):
    args, limits = startup
    args.live = False
    calls = []
    monkeypatch.setattr(runtime.TM, "_signed_get", lambda path: calls.append(path) or account("40"))
    balances = runtime._preflight_live(args, ["SOLUSDT"], limits)
    assert balances is None
    assert calls == []
    assert runtime.auto_cap_if_needed(args, 1, balances) == Decimal("15")
    assert calls == ["/api/v3/account"]


def test_disabled_auto_cap_does_not_read_or_change_cap(startup, monkeypatch):
    args, _ = startup
    args.auto_cap = False
    def forbidden(*_a, **_kw):
        raise AssertionError("unexpected account read")
    monkeypatch.setattr(runtime.TM, "_signed_get", forbidden)
    assert runtime.auto_cap_if_needed(args, 1) is None
    assert os.environ["BOT_CAP_PER_ORDER"] == "50"


def test_rejected_preflight_returns_no_projection(startup, monkeypatch):
    args, limits = startup
    monkeypatch.setattr(runtime.TM, "_signed_get", lambda _p: account("100", can_trade=False))
    with pytest.raises(RuntimeError, match="not allowed to trade"):
        runtime._preflight_live(args, ["SOLUSDT"], limits)


def test_bad_fresh_account_cannot_use_startup_projection(startup, monkeypatch, capsys):
    args, limits = startup
    calls = []
    responses = iter([account("100"), account("private-marker")])
    def signed_get(path):
        calls.append(path)
        return next(responses)
    monkeypatch.setattr(runtime.TM, "_signed_get", signed_get)
    balances = runtime._preflight_live(args, ["SOLUSDT"], limits)
    assert runtime.auto_cap_if_needed(args, 1, balances) == Decimal("45")
    with pytest.raises(ValueError, match="invalid exact exchange number") as error:
        runtime._build_risk_snapshot(["SOLUSDT"], limits)
    assert calls == ["/api/v3/account", "/api/v3/account"]
    assert "private-marker" not in str(error.value)
    assert "private-marker" not in str(capsys.readouterr())
