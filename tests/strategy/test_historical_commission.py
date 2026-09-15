from decimal import Decimal as D, localcontext
from dataclasses import replace
import runpy

import pytest

from ladder_dragon.execution.buy_settlement import settle_buy
from ladder_dragon.strategy.prediction.historical_commission import buy_inventory


def fixture(scenario="BASE_BUY_QUOTE_SELL", **context_changes):
    h = runpy.run_path("tests/strategy/test_historical_entry_replay.py")
    context_changes.setdefault("step_size", "0.000001")
    context = h["context"](**context_changes)
    policy = h["HistoricalPolicy"].parse(h["policy"](commission_asset_scenario=scenario))
    x = h["HistoricalExecution"](h["event"](3000), policy, context, "commission")
    x.process(h["event"](3200), veto=False, panic=False)
    x.process(h["event"](3300, trades=((str(x.entry), str(x.quantity), "SELL"),)), veto=False, panic=False)
    return x, h


@pytest.mark.parametrize("scenario, asset", [("QUOTE", "USDT"), ("BASE_BUY_QUOTE_SELL", "SOL")])
def test_modeled_inventory_matches_runtime_settlement(scenario, asset):
    x, _ = fixture(scenario, step_size="0.001" if scenario == "QUOTE" else "0.000001")
    qty, price = x.entry_qty, x.entry
    fee = qty * D("0.001") if asset == "SOL" else price * qty * D("0.001")
    order = dict(symbol="SOLUSDT", side="BUY", orderId=42, status="FILLED", origQty=str(qty),
                 executedQty=str(qty), cummulativeQuoteQty=str(qty * price))
    fills = [dict(symbol="SOLUSDT", orderId=42, id=1, isBuyer=True, qty=str(qty), price=str(price),
                  quoteQty=str(qty * price), commission=str(fee), commissionAsset=asset)]
    settlement = settle_buy(order, fills, symbol="SOLUSDT", order_id=42)
    assert x.entry_net_qty == settlement.net_quantity
    if x.result is None:
        assert x.order("target").quantity == settlement.net_quantity


def test_base_fee_is_not_deducted_twice_on_complete_exit():
    # Exactly one gross unit makes the base fee representable at the configured step.
    h = runpy.run_path("tests/strategy/test_historical_entry_replay.py")
    policy = h["HistoricalPolicy"].parse(h["policy"](commission_asset_scenario="BASE_BUY_QUOTE_SELL", notional_quote="99.49"))
    x = h["HistoricalExecution"](h["event"](3000), policy, h["context"](), "fee")
    x.process(h["event"](3200), veto=False, panic=False)
    x.process(h["event"](3300, trades=((str(x.entry), str(x.quantity), "SELL"),)), veto=False, panic=False)
    assert x.entry_qty == 1 and x.order("target").quantity == D("0.999")
    x.process(h["event"](3500), veto=False, panic=False)
    result = x.process(h["event"](3600, trades=((str(x.target), "0.999", "BUY"),)), veto=False, panic=False)
    proceeds = x.target * D("0.999")
    assert D(result["net_pnl_quote"]) == proceeds - x.entry_cost - proceeds * D("0.001")
    assert D(result["gross_pnl_quote"]) - D(result["fee_quote"]) == D(result["net_pnl_quote"])
    assert result["unresolved_quantity"] == "0.000" and not result["censored"]
    assert result["eligible_for_promotion"] is False


def test_base_fee_dust_is_censored_not_erased():
    x, _ = fixture(step_size="0.001")
    assert x.result["terminal_reason"] == "UNREPRESENTABLE_NET_INVENTORY"
    assert x.result["net_pnl_quote"] is None and x.result["censored"]
    assert x.order("target") is None
    assert D(x.result["unresolved_quantity"]) == x.entry_net_qty > 0


def test_missing_asset_never_invents_net_inventory():
    x, _ = fixture("UNSPECIFIED")
    assert x.result["terminal_reason"] == "COMMISSION_ASSET_UNSPECIFIED"
    assert x.result["entry_net_quantity"] is None
    assert x.result["unresolved_quantity"] is None
    assert D(x.result["unsettled_gross_quantity"]) == x.entry_qty > 0
    assert x.result["net_pnl_quote"] is None and x.order("target") is None


def test_legacy_policy_is_explicitly_unqualified_and_inputs_unchanged():
    h = runpy.run_path("tests/strategy/test_historical_entry_replay.py")
    payload = h["policy"]()
    payload.pop("commission_asset_scenario")
    original = payload.copy()
    assert h["HistoricalPolicy"].parse(payload).commission_asset_scenario == "UNSPECIFIED"
    assert payload == original


def test_third_asset_requires_its_own_valuation_contract():
    h = runpy.run_path("tests/strategy/test_historical_entry_replay.py")
    with pytest.raises(ValueError):
        h["HistoricalPolicy"].parse(h["policy"](commission_asset_scenario="BNB"))


def test_fee_precision_does_not_depend_on_ambient_context():
    with localcontext() as context:
        context.prec = 4
        net, fee = buy_inventory("SOLUSDT", D("100"), D("1"),
                                  D("0.000000000000000000000000000001"), "BASE_BUY_QUOTE_SELL")
    assert net == D("0.999999999999999999999999999999")
    assert fee == D("0.0000000000000000000000000001")


def test_unqualified_episode_does_not_free_slot_for_later_buys():
    h = runpy.run_path("tests/strategy/test_historical_entry_replay.py")
    events = [replace(event, trades=((D("90"), D("100"), "SELL"),)) for event in h["declining_history"]()]
    report = h["run"](events, commission_asset_scenario="UNSPECIFIED", veto_price_bps="-9000")
    assert report["status"] == "INCOMPLETE_HISTORY"
    for name in ("baseline", "veto"):
        assert len(report["episodes"][name]) == 1
        assert report["episodes"][name][0]["terminal_reason"] == "COMMISSION_ASSET_UNSPECIFIED"
    assert "historical_commission.py" in report["model_source_sha256s"]
    assert "trade_accounting.py" in report["model_source_sha256s"]


def test_partial_cancel_race_protects_cumulative_net_fills():
    h = runpy.run_path("tests/strategy/test_historical_entry_replay.py")
    policy = h["HistoricalPolicy"].parse(h["policy"](commission_asset_scenario="BASE_BUY_QUOTE_SELL"))
    x = h["HistoricalExecution"](h["event"](3000), policy, h["context"](step_size="0.0001"), "partial-fee")
    x.process(h["event"](3200), veto=False, panic=False)
    for stamp in (3300, 3800):
        x.process(h["event"](stamp, trades=((str(x.entry), "0.1", "SELL"),)), veto=False, panic=False)
    x.process(h["event"](3801), veto=False, panic=False)
    assert x.entry_qty == D("0.2") and x.order("target").quantity == D("0.1998")


def test_future_fee_context_cannot_rewrite_prior_episode():
    h = runpy.run_path("tests/strategy/test_historical_entry_replay.py")
    events = [replace(event, trades=((D("90"), D("100"), "SELL"),)) for event in h["declining_history"]()]
    policy = h["policy"](commission_asset_scenario="UNSPECIFIED", veto_price_bps="-9000")
    reports = []
    for rate in ("0.001", "0.09"):
        reports.append(h["historical_entry_replay"](
            iter(events), policy_payload=policy,
            context_rows=[h["context"](), h["context"](observed_at_ms=5000, panic_observed_at_ms=5000,
                                                         maker_buy_fee_pct=rate)],
            start_ms=3000, entry_end_ms=12000, end_ms=28000, cutoff_ms=28000,
        ))
    assert reports[0]["episodes"] == reports[1]["episodes"]
    assert reports[0]["context_sha256"] != reports[1]["context_sha256"]
