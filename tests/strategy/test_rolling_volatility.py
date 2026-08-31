from decimal import Decimal
from types import SimpleNamespace

from ladder_dragon.strategy.depth_segments import bounded_json
from ladder_dragon.strategy.prediction.historical_policy import fingerprint
from ladder_dragon.strategy.rolling_volatility import (
    ROLLING_PUBLISH_INTERVAL_MS,
    ROLLING_WINDOW_MS,
    RollingVolatilityPublisher,
)
from ladder_dragon.strategy.volatility_policy import VOLATILITY_METRIC


def test_rolling_publisher_writes_one_bounded_public_record(tmp_path):
    path = tmp_path / ".rolling-volatility-SOLUSDT.json"
    publisher = RollingVolatilityPublisher(
        path, symbol="SOLUSDT", session_id="session"
    )
    report = None
    for index in range(3_302):
        timestamp = 1_000_000 + index * 1_000
        price = Decimal("100") + Decimal(index % 5) / Decimal("100")
        book = SimpleNamespace(
            update_id=index + 1,
            bids={price: Decimal("1")},
            asks={price + Decimal("0.01"): Decimal("1")},
            received_ms=timestamp,
        )
        report = publisher.observe(book) or report

    stored = bounded_json(path)
    body = {
        key: value for key, value in stored.items()
        if key != "telemetry_sha256"
    }
    assert report is not None
    assert stored["contains_secrets"] is False
    assert stored["sequence_verified"] is True
    assert stored["schema_version"] == 2
    assert stored["volatility_metric"] == VOLATILITY_METRIC
    assert stored["measurement_window_ms"] == ROLLING_WINDOW_MS
    assert stored["publish_interval_ms"] == ROLLING_PUBLISH_INTERVAL_MS
    assert (
        stored["window_ended_at_ms"] - stored["window_started_at_ms"]
        == ROLLING_WINDOW_MS
    )
    assert stored["book_update_count"] >= 100
    assert stored["telemetry_sha256"] == fingerprint(body)
    assert "API_KEY" not in str(stored)
    assert "API_SECRET" not in str(stored)
