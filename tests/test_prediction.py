from dataclasses import replace
from decimal import Decimal
import hashlib
import json

from ladder_dragon.strategy.prediction import (
    PredictionBar,
    PredictionFeatures,
    PredictionOutcome,
    PredictionShadowStore,
    ResolvedSample,
    TradePlan,
    build_prediction_features,
    evaluate_plan,
    predict_distribution,
    prediction_apply_gate,
    trade_flow_from_agg_trades,
    walk_forward_prediction_report,
)
from ladder_dragon.strategy.prediction_archive import (
    load_verified_prediction_archive,
)


D = Decimal


def _klines(count: int = 80) -> list[list[object]]:
    rows = []
    for index in range(count):
        price = D("100") + D(str(index)) * D("0.05")
        open_time = index * 60_000
        rows.append([
            open_time,
            str(price - D("0.02")),
            str(price + D("0.08")),
            str(price - D("0.08")),
            str(price),
            str(D("10") + D(str(index % 5))),
            open_time + 59_999,
        ])
    return rows


def _features(snapshot_ts_ms: int = 59_999) -> PredictionFeatures:
    return PredictionFeatures(
        snapshot_ts_ms=snapshot_ts_ms,
        last_closed_bar_ts_ms=snapshot_ts_ms,
        price=D("100"),
        ema_slope=D("0.001"),
        ema_distance_pct=D("0.001"),
        adx=D("30"),
        plus_di=D("35"),
        minus_di=D("15"),
        atr_pct=D("0.002"),
        atr_change_pct=D("0.1"),
        vwap_deviation_pct=D("0.001"),
        rsi=D("55"),
        macd_histogram_pct=D("0.0002"),
        volume_ratio=D("1.1"),
        orderbook_imbalance=D("0.2"),
        orderbook_available=True,
        trade_flow_imbalance=D("0"),
        trade_flow_available=False,
        spread_bps=D("1"),
        depth_quote=D("10000"),
        acceleration=D("0.0001"),
        executor_panic_active=False,
        executor_panic_hits=0,
        regime="TREND_UP",
    )


def _plan(entry: str = "99") -> TradePlan:
    value = D(entry)
    return TradePlan(
        entry_price=value,
        take_profit_price=value * D("1.01"),
        stop_price=value * D("0.99"),
        notional_quote=D("50"),
        fee_pct=D("0.001"),
        slippage_pct=D("0.0005"),
    )


def test_features_use_only_closed_bars_and_mark_missing_trade_flow():
    rows = _klines()
    last_closed = int(rows[-2][6])
    as_of = last_closed + 20_000
    future_close = D(str(rows[-1][4]))
    features, bars = build_prediction_features(
        rows,
        as_of_ms=as_of,
        depth={
            "bids": [["103.8", "5"], ["103.7", "3"]],
            "asks": [["103.9", "4"], ["104.0", "3"]],
        },
    )

    assert features.snapshot_ts_ms == as_of
    assert features.last_closed_bar_ts_ms == last_closed
    assert features.price != future_close
    assert bars[-1].close_time_ms == last_closed
    assert features.orderbook_available is True
    assert features.trade_flow_available is False
    assert features.regime in {"TREND_UP", "TREND_DOWN", "RANGE", "PANIC"}


def test_distribution_excludes_future_resolved_samples():
    features = _features(snapshot_ts_ms=600_000)
    plan = _plan()
    past = ResolvedSample(
        snapshot_ts_ms=500_000,
        regime="TREND_UP",
        horizon_min=1,
        outcome=PredictionOutcome(
            1, True, True, D("2"), D("0.001"), 20, "TP", 560_000
        ),
        baseline_net_pnl_quote=D("0"),
    )
    future = replace(
        past,
        snapshot_ts_ms=700_000,
        outcome=replace(past.outcome, net_pnl_quote=D("-100")),
    )

    prediction = predict_distribution(
        features, plan, [past, future], min_samples=1
    )[0]

    assert prediction.samples == 1
    assert prediction.available is True
    assert prediction.expected_net_pnl_quote > D("-10")


def test_trade_flow_uses_only_closed_interval_and_signed_taker_volume():
    flow, available = trade_flow_from_agg_trades(
        [
            {"T": 100, "q": "3", "m": False},
            {"T": 110, "q": "1", "m": True},
            {"T": 121, "q": "100", "m": True},
        ],
        start_ms=100,
        end_ms=120,
    )

    assert available is True
    assert flow == D("0.5")


def test_executor_panic_state_is_recorded_as_panic_regime():
    rows = _klines()
    features, _ = build_prediction_features(
        rows,
        as_of_ms=int(rows[-1][6]) + 1,
        executor_panic_active=True,
        executor_panic_hits=2,
    )

    assert features.regime == "PANIC"
    assert features.executor_panic_active is True
    assert features.executor_panic_hits == 2


def test_outcome_uses_stop_first_and_exact_round_trip_costs():
    plan = _plan("100")
    bars = [
        PredictionBar(
            open_time_ms=60_000,
            close_time_ms=119_999,
            open=D("100"),
            high=D("102"),
            low=D("98"),
            close=D("101"),
            volume=D("10"),
        )
    ]

    outcome = evaluate_plan(
        bars, snapshot_ts_ms=59_999, horizon_min=1, plan=plan
    )

    assert outcome is not None
    assert outcome.exit_reason == "STOP"
    assert outcome.tp_before_stop is False
    assert outcome.time_to_fill_sec == 60
    # Gross loss is 0.50 quote and exact round-trip costs are 0.15 quote.
    assert outcome.net_pnl_quote == D("-0.650")


def test_one_minute_store_waits_for_next_complete_bar(tmp_path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    features = _features(snapshot_ts_ms=90_000)
    plan = _plan("99")
    store.record(
        kind="STRATEGY",
        symbol="SOLUSDT",
        features=features,
        plan=plan,
        predictions=predict_distribution(features, plan, []),
        algorithm_decision="current-ladder",
    )
    bars = [
        PredictionBar(
            120_000,
            179_999,
            D("100"),
            D("101"),
            D("100"),
            D("100.5"),
            D("10"),
        )
    ]

    # snapshot + 60 seconds is still inside the first future OHLC bar.
    assert store.settle("SOLUSDT", bars, as_of_ms=150_000) == 0
    assert store.settle("SOLUSDT", bars, as_of_ms=179_999) == 1
    sample = store.resolved_samples("SOLUSDT")[0]
    assert sample.horizon_min == 1
    assert sample.outcome.exit_reason == "NO_FILL"
    assert sample.outcome.resolved_at_ms == 179_999


def test_store_expires_window_missing_from_available_history(tmp_path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    features = _features(snapshot_ts_ms=30_000)
    plan = _plan("99")
    store.record(
        kind="STRATEGY",
        symbol="SOLUSDT",
        features=features,
        plan=plan,
        predictions=predict_distribution(features, plan, []),
        algorithm_decision="old-window",
    )
    bars = [
        PredictionBar(
            600_000,
            659_999,
            D("100"),
            D("101"),
            D("99"),
            D("100"),
            D("10"),
        )
    ]

    assert store.settle("SOLUSDT", bars, as_of_ms=1_000_000) == 3
    summary = store.summary("SOLUSDT")
    assert summary["expired_outcomes"] == 3
    assert summary["pending_outcomes"] == 0
    assert summary["resolved_outcomes"] == 0


def test_verified_archive_backfills_only_complete_expired_windows(tmp_path):
    database = tmp_path / "prediction.sqlite3"
    store = PredictionShadowStore(database)
    features = _features(snapshot_ts_ms=30_000)
    plan = _plan("99")
    store.record(
        kind="STRATEGY",
        symbol="SOLUSDT",
        features=features,
        plan=plan,
        predictions=predict_distribution(features, plan, []),
        algorithm_decision="archive-window",
    )
    late = [PredictionBar(
        900_000, 959_999, D("100"), D("101"), D("99"), D("100"), D("1")
    )]
    assert store.settle("SOLUSDT", late, as_of_ms=1_000_000) == 3

    archive = tmp_path / "SOLUSDT.jsonl"
    lines = []
    for minute, price in ((60_000, "98"), (120_000, "100")):
        lines.append(json.dumps({
            "e": "aggTrade", "s": "SOLUSDT", "T": minute + 1_000,
            "p": price, "q": "1",
        }, separators=(",", ":")))
    archive.write_text("\n".join(lines) + "\n", encoding="utf-8")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".jsonl.metadata.json").write_text(
        json.dumps({
            "schema_version": 1,
            "symbol": "SOLUSDT",
            "archive_sha256": digest,
            "contains_secrets": False,
        }),
        encoding="utf-8",
    )
    verified = load_verified_prediction_archive(archive)

    # One- and five-minute outcomes cannot both be fabricated from two minutes.
    assert store.backfill_expired(
        verified.symbol,
        verified.bars,
        source_sha256=verified.source_sha256,
        as_of_ms=1_000_000,
    ) == 1
    summary = store.summary("SOLUSDT")
    assert summary["resolved_outcomes"] == 1
    assert summary["expired_outcomes"] == 2
    with store._connect() as connection:
        terminal, source = connection.execute(
            "SELECT terminal_reason,source_sha256 FROM prediction_outcomes "
            "WHERE outcome_json IS NOT NULL"
        ).fetchone()
    assert terminal == "BACKFILLED"
    assert source == digest


def test_prediction_archive_rejects_metadata_hash_mismatch(tmp_path):
    archive = tmp_path / "SOLUSDT.jsonl"
    archive.write_text(
        '{"e":"aggTrade","s":"SOLUSDT","T":61000,"p":"100","q":"1"}\n'
    )
    archive.with_suffix(".jsonl.metadata.json").write_text(
        json.dumps({
            "schema_version": 1,
            "symbol": "SOLUSDT",
            "archive_sha256": "0" * 64,
            "contains_secrets": False,
        })
    )
    import pytest
    with pytest.raises(ValueError, match="SHA-256"):
        load_verified_prediction_archive(archive)


def test_reanchor_store_resolves_proposed_and_original_buy(tmp_path):
    store = PredictionShadowStore(tmp_path / "prediction.sqlite3")
    features = _features()
    proposed = _plan("99")
    original = _plan("95")
    predictions = predict_distribution(features, proposed, [])
    store.record(
        kind="REANCHOR",
        symbol="SOLUSDT",
        features=features,
        plan=proposed,
        baseline_plan=original,
        predictions=predictions,
        algorithm_decision="order=hash;reason=adaptive-reanchor",
    )
    bars = [
        PredictionBar(
            60_000, 119_999, D("100"), D("101"), D("98"), D("100"), D("10")
        )
    ]

    assert store.settle("SOLUSDT", bars, as_of_ms=119_999) == 1
    samples = store.resolved_samples("SOLUSDT", kind="REANCHOR")

    assert len(samples) == 1
    assert samples[0].outcome.buy_filled is True
    assert samples[0].baseline_net_pnl_quote == D("0")
    assert store.summary("SOLUSDT")["reanchor_counterfactuals"] == 1
    regime = store.regime_performance(
        "SOLUSDT", minimum_samples_per_regime=1
    )
    assert regime["apply_allowed"] is False
    assert regime["groups"][0]["regime"] == "TREND_UP"
    assert regime["groups"][0]["kind"] == "REANCHOR"
    assert regime["groups"][0]["mean_buy_distance_pct"] == "0.01"
    assert "TREND_DOWN" in regime["missing_or_insufficient_regimes"]


def test_supervisor_shadow_records_strategy_and_hashed_reanchor(
    tmp_path, monkeypatch
):
    from bin import ai_supervisor

    database = tmp_path / "prediction.sqlite3"
    store = PredictionShadowStore(database)
    rows = _klines()
    as_of = int(rows[-1][6]) + 1
    monkeypatch.setattr(ai_supervisor, "_PREDICTION_SHADOW", store)
    monkeypatch.setattr(ai_supervisor, "_PREDICTION_LAST_ATTEMPT", {})
    # A fresh Linux runner may have less uptime than the throttle interval.
    # Missing history must still permit the first SHADOW snapshot.
    monkeypatch.setattr(ai_supervisor.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(ai_supervisor, "_AI_RUNTIME_STATUS", {})
    monkeypatch.setattr(ai_supervisor, "_AI_RUNTIME_STATUS_PATH", None)
    monkeypatch.setenv("BOT_CAP_PER_ORDER", "50")
    monkeypatch.setattr(ai_supervisor.TM, "_timestamp_ms", lambda: as_of)
    monkeypatch.setattr(
        ai_supervisor.TM, "get_klines", lambda *args, **kwargs: rows
    )

    def public_get(path, params):
        if path.endswith("depth"):
            return {"bids": [["103.9", "5"]], "asks": [["104.0", "4"]]}
        return [{"T": int(rows[-1][6]), "q": "2", "m": False}]

    monkeypatch.setattr(ai_supervisor.TM, "_public_get", public_get)
    ai_supervisor._record_prediction_shadow(
        "SOLUSDT",
        now_price="104",
        ladder=[103.5, 104.5],
        take_profit_pct="0.01",
        stop_pct="-0.01",
        deterministic_mode="UP",
        rolling={"proposals": [{
            "order_id": "raw-order-identifier",
            "old_price": "102",
            "target_price": "103",
            "age_sec": 300,
        }]},
    )

    summary = store.summary("SOLUSDT")
    assert summary["decisions"] == 2
    assert summary["reanchor_counterfactuals"] == 1
    assert ai_supervisor._AI_RUNTIME_STATUS["prediction"][
        "can_change_orders"
    ] is False
    assert b"raw-order-identifier" not in database.read_bytes()


def test_walk_forward_and_apply_gate_are_chronological_and_strict():
    regimes = ("TREND_UP", "TREND_DOWN", "RANGE", "PANIC")
    samples = []
    for index in range(120):
        horizon = (1, 5, 15)[index % 3]
        outcome = PredictionOutcome(
            horizon,
            True,
            True,
            D("1"),
            D("0.001"),
            30,
            "TP",
            index * 60_000 + horizon * 60_000,
        )
        samples.append(ResolvedSample(
            snapshot_ts_ms=index * 60_000,
            regime=regimes[index % len(regimes)],
            horizon_min=horizon,
            outcome=outcome,
            baseline_net_pnl_quote=D("0"),
        ))

    gate = prediction_apply_gate(samples)
    report = walk_forward_prediction_report(samples, min_train_samples=12)

    assert gate["approved"] is True
    assert gate["mode"] == "APPLY"
    assert report["lookahead"] is False
    assert report["evaluated"]
    assert all(
        row["train_max_ts_ms"] < row["snapshot_ts_ms"]
        for row in report["evaluated"]
    )
    assert prediction_apply_gate(samples[:10])["mode"] == "SHADOW"
