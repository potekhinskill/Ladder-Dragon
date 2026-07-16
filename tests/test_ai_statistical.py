from ai_advisor import MarketContext
from ai_statistical import (
    MulticlassLogisticRegime,
    context_vector,
    return_label,
)


def context(**overrides):
    values = dict(
        symbol="SOLUSDT", price=100, atr_pct=.01,
        deterministic_mode="FLAT", candidate_mode="FLAT",
        ema_gap_pct=0, ema_slope=0, adx=25,
        ladder_low_pct=-.5, ladder_down_pct=-20, ladder_up_pct=20,
        target_buys=4, risk_safe_cap_usdt=40,
    )
    values.update(overrides)
    return MarketContext(**values)


def test_context_vector_is_fixed_and_clipped():
    vector = context_vector(context(return_1h=1, volume_ratio_1h=100))
    assert len(vector) == 10
    assert max(vector) <= 3
    assert min(vector) >= -3


def test_return_label_has_flat_deadband():
    assert return_label(.01) == "UP"
    assert return_label(-.01) == "DOWN"
    assert return_label(.0005) == "FLAT"


def test_logistic_benchmark_requires_samples_then_learns_direction():
    model = MulticlassLogisticRegime()
    assert model.predict([0] * 10).available is False
    examples = []
    for _ in range(40):
        examples.append(([2, 2, 2, 1, 1, 1, 1, 1, .5, .5], "UP"))
        examples.append(([-2, -2, -2, -1, -1, -1, 1, 1, -.5, .5], "DOWN"))
        examples.append(([0, 0, 0, 0, 0, 0, -1, .5, 0, 0], "FLAT"))
    model.fit(examples)
    prediction = model.predict([2, 2, 2, 1, 1, 1, 1, 1, .5, .5])
    assert prediction.available is True
    assert prediction.mode == "UP"
    assert prediction.confidence > .5
