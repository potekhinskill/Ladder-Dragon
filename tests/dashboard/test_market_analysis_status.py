from datetime import datetime, timezone
import json
from pathlib import Path

from ladder_dragon.dashboard.services.market_analysis import market_analysis_snapshot


def test_dashboard_market_status_preserves_shadow_boundary(tmp_path: Path):
    status = tmp_path / "status.json"
    status.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "LIVE",
        "apply_allowed": True,
        "can_change_orders": True,
        "results": [{"symbol": "BTCUSDT"}],
        "failures": [],
    }))
    payload = market_analysis_snapshot(status)
    assert payload["ok"] is True
    assert payload["mode"] == "SHADOW"
    assert payload["apply_allowed"] is False
    assert payload["can_change_orders"] is False


def test_dashboard_market_status_fails_closed(tmp_path: Path):
    payload = market_analysis_snapshot(tmp_path / "missing.json")
    assert payload == {
        "ok": False,
        "status": "UNAVAILABLE",
        "mode": "SHADOW",
        "apply_allowed": False,
        "can_change_orders": False,
        "results": [],
        "failures": [],
    }


def test_dashboard_declares_market_scenario_route():
    source = Path("ladder_dragon/dashboard/runtime.py").read_text()
    assert '@app.get("/api/market/scenarios")' in source
    html = Path("FRONT/index.html").read_text()
    javascript = Path("FRONT/dashboard.js").read_text()
    assert 'id="market-scenario-body"' in html
    assert "updateMarketScenarios(scenarios)" in javascript
    assert "B/R/S" in javascript
