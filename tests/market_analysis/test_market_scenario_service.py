from decimal import Decimal
import json
from pathlib import Path

import pytest

from ladder_dragon.market_analysis.binance_public import (
    MAX_RESPONSE_BYTES,
    PublicMarketDataError,
    fetch_closed_klines,
)
from ladder_dragon.market_analysis.config import (
    prove_execution_scope_unchanged,
    resolve_analysis_symbols,
    resolve_analysis_timeframes,
)
from ladder_dragon.market_analysis.runtime import MarketScenarioService
from ladder_dragon.market_analysis.store import MarketScenarioStore
from ladder_dragon.strategy.scenario_analysis import ScenarioBar, analyze_scenarios


D = Decimal


class _Response:
    def __init__(self, payload: object, *, status: int = 200) -> None:
        self.payload = json.dumps(payload).encode()
        self.status_code = status

    def iter_content(self, chunk_size: int):
        for index in range(0, len(self.payload), chunk_size):
            yield self.payload[index:index + chunk_size]


class _Session:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.headers: dict[str, str] = {}
        self.calls: list[dict[str, object]] = []

    def get(self, _url: str, **kwargs):
        self.calls.append(kwargs)
        return _Response(self.payload)


def _bars(count: int) -> list[ScenarioBar]:
    return [ScenarioBar(
        open_time_ms=index * 3_600_000,
        close_time_ms=(index + 1) * 3_600_000 - 1,
        open=D(100 + index),
        high=D(102 + index),
        low=D(99 + index),
        close=D(101 + index),
        volume=D("10"),
    ) for index in range(count)]


def _payload(count: int = 61) -> list[list[object]]:
    return [[
        bar.open_time_ms, str(bar.open), str(bar.high), str(bar.low),
        str(bar.close), str(bar.volume), bar.close_time_ms,
    ] for bar in _bars(count)]


def test_analysis_symbols_are_separate_from_execution_scope():
    analysis = resolve_analysis_symbols("SOLUSDT,ETHUSDT,BTCUSDT")
    assert analysis == ("SOLUSDT", "ETHUSDT", "BTCUSDT")
    scope = prove_execution_scope_unchanged(("SOLUSDT",), analysis)
    assert scope["execution_symbols"] == ["SOLUSDT"]
    assert scope["shadow_only_symbols"] == ["ETHUSDT", "BTCUSDT"]
    assert scope["execution_scope_unchanged"] is True
    assert resolve_analysis_timeframes("1h,4h,1d,1w,1M")[-1] == "1M"


def test_configuration_rejects_duplicates_and_unsupported_intervals():
    with pytest.raises(ValueError, match="duplicates"):
        resolve_analysis_symbols("SOLUSDT,SOLUSDT")
    with pytest.raises(ValueError, match="unsupported"):
        resolve_analysis_timeframes("1h,15m")


def test_public_client_discards_current_open_candle():
    payload = _payload()
    payload.append([
        61 * 3_600_000, "1", "2", "1", "2", "1", 62 * 3_600_000 - 1,
    ])
    session = _Session(payload)
    bars = fetch_closed_klines(
        session,
        base_url="https://example.invalid",
        symbol="SOLUSDT",
        timeframe="1h",
        now_ms=62 * 3_600_000 - 1,
    )
    assert len(bars) == 61
    assert session.calls[0]["stream"] is True


def test_public_client_rejects_oversized_payload():
    response = _Response([])
    response.payload = b"[" + b"0" * MAX_RESPONSE_BYTES + b"]"
    session = _Session([])
    session.get = lambda *_args, **_kwargs: response
    with pytest.raises(PublicMarketDataError):
        fetch_closed_klines(
            session,
            base_url="https://example.invalid",
            symbol="SOLUSDT",
            timeframe="1h",
            now_ms=10**15,
        )


def test_store_resolves_only_the_exact_next_candle(tmp_path: Path):
    store = MarketScenarioStore(tmp_path / "scenario.sqlite3")
    bars = _bars(61)
    analysis = analyze_scenarios(
        "SOLUSDT", "1h", bars[:60], now_ms=61 * 3_600_000
    )
    store.record(analysis, created_at_ms=61 * 3_600_000)
    assert store.settle(
        symbol="SOLUSDT",
        timeframe="1h",
        bars=[*bars[:59], bars[60]],
        round_trip_cost_pct=D("0.0025"),
    ) == 0
    assert store.settle(
        symbol="SOLUSDT",
        timeframe="1h",
        bars=bars,
        round_trip_cost_pct=D("0.0025"),
    ) == 1
    stats = store.statistics(symbol="SOLUSDT", timeframe="1h")
    assert stats["resolved"] == 1
    assert stats["status"] == "COLLECTING"
    assert stats["apply_allowed"] is False


def test_service_publishes_separate_symbol_results_without_order_authority(
    tmp_path: Path,
):
    session = _Session(_payload(60))
    status = tmp_path / "status.json"
    service = MarketScenarioService(
        database=tmp_path / "scenario.sqlite3",
        status_file=status,
        base_url="https://example.invalid",
        symbols=("SOLUSDT", "ETHUSDT"),
        timeframes=("1h",),
        execution_symbols=("SOLUSDT",),
        round_trip_cost_pct=D("0.0025"),
        now_ms=lambda: 61 * 3_600_000,
        session=session,
    )
    report = service.run_once()
    assert report["status"] == "PASS"
    assert report["apply_allowed"] is False
    assert report["can_change_orders"] is False
    assert [item["symbol"] for item in report["results"]] == [
        "SOLUSDT", "ETHUSDT",
    ]
    stored = json.loads(status.read_text())
    assert stored["scope"]["shadow_only_symbols"] == ["ETHUSDT"]


def test_market_analysis_package_has_no_order_imports():
    root = Path("ladder_dragon/market_analysis")
    source = "\n".join(path.read_text() for path in root.glob("*.py"))
    assert "execution.orders" not in source
    assert "place_limit_order" not in source
    assert "place_market_order" not in source
