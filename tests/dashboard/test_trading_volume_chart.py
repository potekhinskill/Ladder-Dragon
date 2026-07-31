import json
import sqlite3
from pathlib import Path
import time

from fastapi.testclient import TestClient
from ladder_dragon.dashboard.services.host_telemetry import (
    rolling_trade_volume_24h_usdt,
)
from tests.support.module_loaders import load_dashboard


def _trade_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE trades_exact (
          ts INTEGER NOT NULL,
          side TEXT NOT NULL,
          price_text TEXT NOT NULL,
          gross_qty_text TEXT NOT NULL
        )
        """
    )


def test_rolling_trade_volume_counts_buy_and_sell_without_future_leakage():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    _trade_table(connection)
    now = 1_700_000_000
    connection.executemany(
        "INSERT INTO trades_exact(ts,side,price_text,gross_qty_text) VALUES(?,?,?,?)",
        (
            (now - 86_400, "BUY", "100", "1"),
            (now - 10, "BUY", "2", "3"),
            (now, "SELL", "4", "5"),
            (now + 1, "BUY", "7", "1"),
        ),
    )

    assert rolling_trade_volume_24h_usdt(connection, [now, now + 2]) == [
        "26",
        "33",
    ]


def test_dashboard_declares_and_updates_the_fourth_chart():
    index = Path("FRONT/index.html").read_text(encoding="utf-8")
    script = Path("FRONT/dashboard.js").read_text(encoding="utf-8")
    locales = Path("FRONT/locales.js").read_text(encoding="utf-8")

    assert 'data-i18n="chart_trading_volume_24h"' in index
    assert '<canvas id="chartTradingVolume"></canvas>' in index
    assert "hist.trading_volume_24h_usdt" in script
    assert locales.count("chart_trading_volume_24h:") == 15


def test_history_api_returns_exact_aligned_trade_volume(tmp_path, monkeypatch):
    now = int(time.time()) - 10
    database = tmp_path / "stats.db"
    connection = sqlite3.connect(database)
    _trade_table(connection)
    connection.execute(
        "INSERT INTO trades_exact(ts,side,price_text,gross_qty_text) VALUES(?,?,?,?)",
        (now, "BUY", "2.50", "4"),
    )
    connection.commit()
    connection.close()
    history_file = tmp_path / "metrics.ndjson"
    history_file.write_text(
        json.dumps({"ts": now, "temp_c": 50, "cpu_pct": 4, "mem_used_gib": 1})
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BOT_STATS_DB", str(database))
    module = load_dashboard(monkeypatch, "dashboard_volume_exact")
    monkeypatch.setattr(module, "HIST_FILE", history_file)

    with TestClient(module.app) as client:
        response = client.get(
            "/api/history?hours=24&points=288",
            headers={"Authorization": "Bearer test-secret-token"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trading_volume_24h_status"] == "exact"
    assert payload["trading_volume_24h_usdt"]
    assert set(payload["trading_volume_24h_usdt"]) == {"10.00"}
    assert len(payload["trading_volume_24h_usdt"]) == len(payload["labels"])


def test_history_api_keeps_host_charts_when_trade_database_is_unavailable(
    tmp_path,
    monkeypatch,
):
    now = int(time.time()) - 10
    history_file = tmp_path / "metrics.ndjson"
    history_file.write_text(
        json.dumps({"ts": now, "temp_c": 50, "cpu_pct": 4, "mem_used_gib": 1})
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BOT_STATS_DB", str(tmp_path / "missing.db"))
    module = load_dashboard(monkeypatch, "dashboard_volume_unavailable")
    monkeypatch.setattr(module, "HIST_FILE", history_file)

    with TestClient(module.app) as client:
        response = client.get(
            "/api/history?hours=24&points=288",
            headers={"Authorization": "Bearer test-secret-token"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert 50 in payload["temp_c"]
    assert payload["trading_volume_24h_status"] == "unavailable"
    assert payload["trading_volume_24h_usdt"]
    assert set(payload["trading_volume_24h_usdt"]) == {None}
    assert len(payload["trading_volume_24h_usdt"]) == len(payload["labels"])
