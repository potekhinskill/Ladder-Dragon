import json
import os
from pathlib import Path
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from ladder_dragon.ai.ai_runtime_status import write_runtime_status
from ladder_dragon.ai.context.runtime import AdvisorDecisionStore
from ladder_dragon.execution.order_recovery import OrderJournal
from ladder_dragon.persistence.migrations import migrate
from tests.support.module_loaders import load_dashboard

from tests.test_dashboard_security import dashboard_source, load_dashboard

def test_dashboard_labels_stream_sessions_and_mixed_protection_explicitly():
    source = dashboard_source()
    locales = Path("FRONT/locales.js").read_text(encoding="utf-8")

    assert "observed total" not in source
    assert "cumulative_observation_hours" not in source
    assert "· soak " not in source
    assert "position_legacy_outside" in source
    assert locales.count("position_legacy_outside:") == 2


def test_dashboard_localizes_position_codes_with_safe_unknown_fallback():
    source = dashboard_source()
    locales = Path("FRONT/locales.js").read_text(encoding="utf-8")

    for code in (
        "partial_inventory_lots",
        "managed_lot_armed_only",
        "unmanaged_unprotected",
        "journal_exchange_mismatch",
    ):
        assert f"{code}: 'position_status_" in source
    assert "position_status_unknown" in source
    assert "protection.cost_basis_status" not in source
    assert "protection.gap_watchdog" not in source
    for key in (
        "position_managed",
        "position_legacy",
        "position_status_partial_inventory_lots",
        "position_status_managed_lot_armed_only",
        "position_status_unmanaged_unprotected",
        "position_status_unknown",
    ):
        assert locales.count(f"{key}:") == 2


def test_dashboard_renders_one_concise_operational_position_summary():
    index = Path("FRONT/index.html").read_text(encoding="utf-8")
    source = dashboard_source()
    styles = Path("FRONT/dashboard.css").read_text(encoding="utf-8")
    locales = Path("FRONT/locales.js").read_text(encoding="utf-8")

    assert 'id="positions-body" class="position-list"' in index
    assert "position-table" not in index
    assert 'class="position-summary"' in source
    assert 'position-summary position-account' in source
    assert "managedUnprotectedQty=Math.max(0,managedQty-managedProtectedQty)" in source
    assert "protectionRequired=managedQty>0&&managedUnprotectedQty>1e-12" in source
    assert "position_action_required" in source
    assert "position_unprotected" in source
    assert "position_new_buys_blocked" in source
    assert "position_total_balance" in source
    assert "position_legacy_outside" in source
    assert "position_basis_hidden" in source
    assert "<details class=\"position-details\">" not in source
    assert "(protection.tp||[])" not in source
    assert "(protection.stop||[])" not in source
    assert ".position-summary{display:grid" in styles
    assert "@media (max-width:520px)" in styles
    for key in (
        "position_action_required",
        "position_managed_position",
        "position_protected",
        "position_unprotected",
        "position_new_buys_blocked",
        "position_total_balance",
        "position_legacy_outside",
        "position_basis_hidden",
    ):
        assert locales.count(f"{key}:") == 2


def test_dashboard_labels_virtual_rag_as_archived_only():
    index = dashboard_source()
    source = Path("ladder_dragon/dashboard/runtime.py").read_text(encoding="utf-8")

    assert "RAG real / archived virtual / retrievals" in index
    assert "knowledge.archived_virtual_documents" in index
    assert '"virtual_policy": "archived_not_retrievable"' in source


def test_order_journal_pending_excludes_terminal_failures(tmp_path, monkeypatch):
    module = load_dashboard(monkeypatch)
    journal_path = tmp_path / "order_intents.sqlite3"
    journal = OrderJournal(journal_path, venue="mainnet")
    failed = journal.prepare(
        client_order_id="LDSLAD-failed",
        symbol="SOLUSDT",
        side="SELL",
        purpose="ladder",
        order_type="LIMIT",
        quantity="1",
        price="100",
    )
    journal.mark_failed(failed.client_order_id, "exchange confirmed order absent")
    journal.prepare(
        client_order_id="LDBLAD-pending",
        symbol="SOLUSDT",
        side="BUY",
        purpose="ladder",
        order_type="LIMIT",
        quantity="0.1",
        price="90",
    )

    snapshot = module._order_journal_snapshot({
        "paths": {"order_journal": str(journal_path)}
    })

    assert snapshot["counts"] == {"FAILED": 1, "PREPARED": 1}
    assert snapshot["cancelled"] == 0
    assert snapshot["pending"] == 1


def test_order_journal_prefers_sanitized_runtime_snapshot(monkeypatch):
    module = load_dashboard(monkeypatch)
    runtime = {
        "order_journal": {
            "available": True,
            "counts": {"CANCELED": 39, "FAILED": 2, "SUBMITTED": 1},
            "cancelled": 39,
            "pending": 1,
            "latest": {
                "symbol": "SOLUSDT",
                "side": "BUY",
                "status": "SUBMITTED",
                "order_id": 123,
                "executed_qty": "0",
                "quantity": "0.127",
                "partial_fill": False,
                "latency_ms": None,
                "commission_usdt": None,
                "updated_at_epoch": 1_784_466_426,
            },
        },
        "paths": {"order_journal": "/path/dashboard/must/not/open.sqlite3"},
    }

    snapshot = module._order_journal_snapshot(runtime)

    assert snapshot["source"] == "runtime"
    assert snapshot["cancelled"] == 39
    assert snapshot["pending"] == 1
    assert snapshot["latest"]["order_id"] == 123
    assert snapshot["latest"]["updated_at"]


def test_open_orders_exposes_read_only_order_fields_without_secrets(monkeypatch):
    monkeypatch.setenv("DASHBOARD_BINANCE_API_KEY", "read-only-key")
    monkeypatch.setenv("DASHBOARD_BINANCE_API_SECRET", "read-only-secret")
    module = load_dashboard(monkeypatch)
    monkeypatch.setattr(module, "_signed", lambda method, path, params=None: [
        {
            "orderId": 123,
            "clientOrderId": "LDBLAD-example",
            "symbol": "SOLUSDT",
            "side": "BUY",
            "type": "LIMIT",
            "timeInForce": "GTC",
            "price": "74.60",
            "stopPrice": "0.00",
            "origQty": "0.133",
            "executedQty": "0.033",
            "status": "NEW",
            "time": 1784319000000,
            "updateTime": 1784319001000,
        },
    ])
    with TestClient(module.app) as client:
        response = client.get(
            "/api/account/open-orders",
            headers={"Authorization": "Bearer test-secret-token"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    order = payload["orders"][0]
    assert order["symbol"] == "SOLUSDT"
    assert order["remaining_qty"] == pytest.approx(0.1)
    assert order["status"] == "NEW"
    assert "read-only-secret" not in response.text


def test_open_orders_uses_short_cache_and_never_posts(monkeypatch):
    monkeypatch.setenv("DASHBOARD_BINANCE_API_KEY", "read-only-key")
    monkeypatch.setenv("DASHBOARD_BINANCE_API_SECRET", "read-only-secret")
    module = load_dashboard(monkeypatch)
    readonly_signed = module._signed
    calls = {"signed": 0}

    def signed(method, path, params=None):
        calls["signed"] += 1
        assert method == "GET"
        assert path == "/api/v3/openOrders"
        return []

    monkeypatch.setattr(module, "_signed", signed)
    first = module.account_open_orders_snapshot()
    second = module.account_open_orders_snapshot()

    assert first == second
    assert calls == {"signed": 1}
    with pytest.raises(RuntimeError, match="read-only"):
        readonly_signed("POST", "/api/v3/order", {})


def test_open_orders_returns_marked_stale_snapshot_on_transient_error(monkeypatch):
    monkeypatch.setenv("DASHBOARD_BINANCE_API_KEY", "read-only-key")
    monkeypatch.setenv("DASHBOARD_BINANCE_API_SECRET", "read-only-secret")
    module = load_dashboard(monkeypatch)
    module._OPEN_ORDERS_CACHE.update({
        "ts": module.time.monotonic() - module._OPEN_ORDERS_CACHE_TTL_SEC - 1,
        "payload": {
            "ok": True, "stale": False, "updated_at": "2026-07-20 01:00:00",
            "venue": "https://api.binance.com", "count": 1,
            "orders": [{"order_id": 123, "status": "NEW"}],
        },
    })
    monkeypatch.setattr(
        module, "_signed",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Binance unavailable")),
    )

    with TestClient(module.app) as client:
        response = client.get(
            "/api/account/open-orders",
            headers={"Authorization": "Bearer test-secret-token"},
        )

    assert response.status_code == 200
    assert response.headers["warning"].startswith("110 ")
    payload = response.json()
    assert payload["stale"] is True
    assert payload["warning"] == "OPEN_ORDERS_STALE"
    assert payload["count"] == 1
    assert "Binance unavailable" not in response.text


def test_ai_status_exposes_decision_rationale_and_realized_summary(tmp_path, monkeypatch):
    db = tmp_path / "ai.db"
    store = AdvisorDecisionStore(str(db))
    decision = store.record(
        symbol="SOLUSDT", price=100, deterministic_mode="FLAT",
        recommended_mode="UP", width_scale=1, cap_scale=1, confidence=.8,
        applied=True, rationale="Test rationale", policy_status="APPLIED",
    )
    store.record_fill(decision, symbol="SOLUSDT", side="BUY", price=100, qty=1, ts=10)
    store.record_fill(decision, symbol="SOLUSDT", side="SELL", price=101, qty=1,
                      exit_reason="TP", ts=20)
    store.record_unresolved_fill(
        symbol="SOLUSDT", side="BUY", price=99, qty=.1, order_id=101
    )
    store.record_unresolved_fill(
        symbol="SOLUSDT", side="BUY", price=98, qty=.1, order_id=102,
        ts=21, resolution_scope="INVENTORY",
    )
    store.evaluate_execution(decision)
    monkeypatch.setenv("AI_DECISIONS_DB", str(db))
    module = load_dashboard(monkeypatch)
    with TestClient(module.app) as client:
        response = client.get(
            "/api/ai/status",
            headers={"Authorization": "Bearer test-secret-token"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["recent"][0]["decision_id"] == decision
    assert payload["recent"][0]["rationale"] == "Test rationale"
    assert payload["knowledge_base"]["closed_decisions"] == 1
    assert payload["knowledge_base"]["realized_net_pnl_quote"] > 0
    assert payload["knowledge_base"]["unresolved_fills"] == 2
    assert payload["knowledge_base"]["unresolved_attribution_fills"] == 1
    assert payload["knowledge_base"]["unresolved_inventory_fills"] == 1


def test_ai_control_button_changes_only_advisory_mode(tmp_path, monkeypatch):
    status_file = tmp_path / "ai_status.json"
    control_file = tmp_path / "ai_control.json"
    write_runtime_status(status_file, {
        "state": "RUNNING",
        "ai": {
            "enabled": True,
            "mode": "APPLY",
            "configured_mode": "APPLY",
        },
    })
    monkeypatch.setenv("AI_RUNTIME_STATUS_FILE", str(status_file))
    monkeypatch.setenv("AI_CONTROL_FILE", str(control_file))
    module = load_dashboard(monkeypatch)
    headers = {"Authorization": "Bearer test-secret-token"}
    with TestClient(module.app) as client:
        initial = client.get("/api/ai/control", headers=headers)
        csrf = client.get("/api/security/csrf", headers=headers).json()["csrf_token"]
        write_headers = {
            **headers,
            "Origin": "http://testserver",
            "X-CSRF-Token": csrf,
        }
        disabled = client.post(
            "/api/ai/control", headers=write_headers, json={"enabled": False}
        )
        enabled = client.post(
            "/api/ai/control", headers=write_headers, json={"enabled": True}
        )

    assert initial.status_code == 200
    assert initial.json()["enabled"] is True
    assert disabled.status_code == 200
    assert disabled.json()["mode"] == "DISABLED"
    assert enabled.status_code == 200
    assert enabled.json()["mode"] == "APPLY"


def test_ai_control_rejects_missing_csrf_and_cross_origin(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_CONTROL_FILE", str(tmp_path / "ai_control.json"))
    module = load_dashboard(monkeypatch)
    auth = {"Authorization": "Bearer test-secret-token"}
    with TestClient(module.app) as client:
        token = client.get("/api/security/csrf", headers=auth).json()["csrf_token"]
        missing = client.post("/api/ai/control", headers=auth, json={"enabled": False})
        cross_origin = client.post(
            "/api/ai/control",
            headers={**auth, "Origin": "https://evil.invalid", "X-CSRF-Token": token},
            json={"enabled": False},
        )
    assert missing.status_code == 403
    assert cross_origin.status_code == 403


def test_log_api_is_disabled_by_default(monkeypatch):
    module = load_dashboard(monkeypatch)
    with TestClient(module.app) as client:
        response = client.get(
            "/api/bot/logs",
            headers={"Authorization": "Bearer test-secret-token"},
        )
    assert response.status_code == 404


def test_proxy_auth_requires_shared_secret(monkeypatch):
    monkeypatch.setenv("DASHBOARD_AUTH_TOKEN", "")
    monkeypatch.setenv("DASHBOARD_TRUST_PROXY_AUTH", "1")
    monkeypatch.setenv("DASHBOARD_PROXY_AUTH_SECRET", "a" * 64)
    module = load_dashboard(
        monkeypatch,
        "proxy_dashboard",
        auth_token=None,
    )

    with TestClient(module.app) as client:
        forged = client.get(
            "/api/does-not-exist",
            headers={"X-Authenticated-User": "dashboard"},
        )
        trusted = client.get(
            "/api/does-not-exist",
            headers={
                "X-Authenticated-User": "dashboard",
                "X-Dashboard-Proxy-Secret": "a" * 64,
            },
        )

    assert forged.status_code == 401
    assert trusted.status_code == 404


def test_raw_log_routes_are_not_registered(monkeypatch):
    module = load_dashboard(monkeypatch)
    paths = {route.path for route in module.app.routes}
    assert "/api/bot/logs" not in paths
    assert "/api/bot/logs/stream" not in paths


def test_dashboard_cannot_scrape_bot_process_secrets(monkeypatch):
    module = load_dashboard(monkeypatch)
    assert not hasattr(module, "_read_environ_of_pid")
    assert not hasattr(module, "_load_api_keys_from_systemd")


def test_dashboard_rate_limit_is_enforced(monkeypatch):
    monkeypatch.setenv("DASHBOARD_RATE_LIMIT_PER_MIN", "2")
    module = load_dashboard(monkeypatch)
    headers = {"Authorization": "Bearer test-secret-token"}
    with TestClient(module.app) as client:
        assert client.get("/api/bot/logs", headers=headers).status_code == 404
        assert client.get("/api/bot/logs", headers=headers).status_code == 404
        assert client.get("/api/bot/logs", headers=headers).status_code == 429


def test_dashboard_rate_limit_prunes_expired_client_keys(monkeypatch):
    module = load_dashboard(monkeypatch)
    module._RATE_BUCKETS.clear()
    module._RATE_PRUNE_STATE["last"] = 0.0
    module._RATE_BUCKETS["expired"].append(1.0)
    module._RATE_BUCKETS["active"].append(100.0)

    with module._RATE_LOCK:
        module._prune_rate_buckets(120.0)

    assert "expired" not in module._RATE_BUCKETS
    assert list(module._RATE_BUCKETS["active"]) == [100.0]


def test_ai_usage_summary_is_cached_for_bounded_polling(tmp_path, monkeypatch):
    usage = tmp_path / "usage.ndjson"
    now = datetime(2026, 7, 20, 12, tzinfo=timezone.utc)
    event = {
        "timestamp": now.isoformat(),
        "total_tokens": 10,
        "estimated_cost_usd": "0.001",
        "outcome": "applied",
    }
    usage.write_text(json.dumps(event) + "\n", encoding="utf-8")
    module = load_dashboard(monkeypatch)

    first = module._ai_usage_today(usage, now=now)
    usage.write_text((json.dumps(event) + "\n") * 2, encoding="utf-8")
    cached = module._ai_usage_today(usage, now=now)
    key = f"usage:{usage}:{now.date().isoformat()}"
    module._AI_SUMMARY_CACHE[key]["cached_at"] -= 31
    refreshed = module._ai_usage_today(usage, now=now)

    assert first["requests"] == 1
    assert cached["requests"] == 1
    assert refreshed["requests"] == 2


def test_ai_status_is_authenticated_and_contains_no_secrets(tmp_path, monkeypatch):
    db = tmp_path / "ai.db"
    usage = tmp_path / "usage.ndjson"
    now = datetime.now(timezone.utc)
    with sqlite3.connect(db) as connection:
        connection.execute(
            """
            CREATE TABLE ai_decisions(
                symbol TEXT,created_at INTEGER,deterministic_mode TEXT,
                recommended_mode TEXT,width_scale REAL,cap_scale REAL,
                confidence REAL,applied INTEGER,policy_status TEXT,
                policy_reasons TEXT,benchmark_mode TEXT,return_15m REAL,
                return_1h REAL,return_4h REAL
            )
            """
        )
        connection.execute(
            "INSERT INTO ai_decisions VALUES"
            "('SOLUSDT',?,'FLAT','UP',1,0.5,.8,0,'SHADOW','shadow_mode','UP',.01,.02,.03)",
            (int(now.timestamp()),),
        )
    usage.write_text(json.dumps({
        "timestamp": now.isoformat(),
        "total_tokens": 100,
        "estimated_cost_usd": "0.001",
        "outcome": "applied",
    }) + "\n")
    monkeypatch.setenv("AI_DECISIONS_DB", str(db))
    monkeypatch.setenv("AI_USAGE_LOG", str(usage))
    monkeypatch.setenv("AI_MODE", "SHADOW")
    monkeypatch.setenv(
        "AI_RUNTIME_STATUS_FILE", str(tmp_path / "ai_status.json")
    )
    module = load_dashboard(monkeypatch)
    headers = {"Authorization": "Bearer test-secret-token"}

    with TestClient(module.app) as client:
        response = client.get("/api/ai/status", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "SHADOW"
    assert payload["recent"][0]["recommended_mode"] == "UP"
    assert "api_key" not in response.text.lower()
    assert payload["recent"][0]["rationale"] == ""
    assert "deepseek_api_key" not in response.text.lower()


def test_dashboard_follows_active_bot_venue_and_ai_paths(tmp_path, monkeypatch):
    stats_db = tmp_path / "testnet_stats.db"
    decisions_db = tmp_path / "testnet_ai.db"
    usage_log = tmp_path / "ai_usage.ndjson"
    status_file = tmp_path / "ai_status.json"
    with sqlite3.connect(decisions_db) as connection:
        connection.execute(
            """
            CREATE TABLE ai_decisions(
                symbol TEXT,created_at INTEGER,deterministic_mode TEXT,
                recommended_mode TEXT,width_scale REAL,cap_scale REAL,
                confidence REAL,applied INTEGER,policy_status TEXT,
                policy_reasons TEXT,benchmark_mode TEXT,return_15m REAL,
                return_1h REAL,return_4h REAL
            )
            """
        )
        connection.execute(
            "INSERT INTO ai_decisions VALUES"
            "('ETHUSDT',2,'FLAT','DOWN',1.1,0.6,.9,1,'APPLIED','','DOWN',-.01,-.02,-.03)"
        )
    write_runtime_status(status_file, {
        "state": "RUNNING",
        "venue": "testnet",
        "execution_mode": "LIVE",
        "product": {"name": "Ladder Dragon", "version": "2.7.0"},
        "ai": {
            "mode": "APPLY",
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "budgets": {
                "max_requests_per_day": 10,
                "max_tokens_per_day": 1000,
                "max_cost_usd_per_day": "0.05",
            },
        },
        "paths": {
            "stats_db": str(stats_db),
            "ai_decisions_db": str(decisions_db),
            "ai_usage_log": str(usage_log),
        },
    })
    monkeypatch.setenv("AI_RUNTIME_STATUS_FILE", str(status_file))
    monkeypatch.setenv("DASHBOARD_FOLLOW_BOT_PATHS", "1")
    module = load_dashboard(monkeypatch)
    headers = {"Authorization": "Bearer test-secret-token"}

    with TestClient(module.app) as client:
        response = client.get("/api/ai/status", headers=headers)

    payload = response.json()
    assert response.status_code == 200
    assert payload["mode"] == "APPLY"
    assert payload["state"] == "ACTIVE"
    assert payload["runtime"]["connected"] is True
    assert payload["runtime"]["venue"] == "testnet"
    assert payload["runtime"]["execution_mode"] == "LIVE"
    assert payload["runtime"]["provider"] == "deepseek"
    assert payload["runtime"]["budgets"] == {
        "max_requests_per_day": 10,
        "max_tokens_per_day": 1000,
        "max_cost_usd_per_day": "0.05",
    }
    assert payload["recent"][0]["symbol"] == "ETHUSDT"
    assert payload["data_sources"]["decisions_db"] == str(decisions_db)
    assert module.get_db_path() == str(stats_db)


def test_old_daily_ai_errors_do_not_keep_dashboard_degraded(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    usage_log = tmp_path / "ai_usage.ndjson"
    old_timestamp = (now - timedelta(hours=1)).isoformat()
    usage_log.write_text(
        "".join(
            json.dumps(
                {
                    "timestamp": old_timestamp,
                    "total_tokens": 10,
                    "estimated_cost_usd": "0.001",
                    "outcome": "error",
                }
            )
            + "\n"
            for _ in range(3)
        ),
        encoding="utf-8",
    )
    status_file = tmp_path / "ai_status.json"
    write_runtime_status(
        status_file,
        {"state": "RUNNING", "ai": {"mode": "SHADOW", "enabled": True}},
    )
    monkeypatch.setenv("AI_USAGE_LOG", str(usage_log))
    monkeypatch.setenv("AI_RUNTIME_STATUS_FILE", str(status_file))
    monkeypatch.setenv("AI_ERROR_DEGRADED_WINDOW_SEC", "900")
    module = load_dashboard(monkeypatch)

    with TestClient(module.app) as client:
        response = client.get(
            "/api/ai/status",
            headers={"Authorization": "Bearer test-secret-token"},
        )

    payload = response.json()
    assert response.status_code == 200
    assert payload["state"] == "SHADOW"
    assert payload["usage_today"]["errors"] == 3
    assert payload["usage_today"]["recent_errors"] == 0
    assert payload["degraded_reasons"] == []


def test_github_update_check_is_cached_and_compares_commits(monkeypatch):
    monkeypatch.setenv("DASHBOARD_GITHUB_REPOSITORY", "owner/repo")
    module = load_dashboard(monkeypatch)
    local_commit = "a" * 40
    remote_commit = "b" * 40
    monkeypatch.setattr(module, "_git_head_commit", lambda: local_commit)

    class Response:
        status_code = 200

        def json(self):
            return {
                "sha": remote_commit,
                "html_url": "https://github.com/owner/repo/commit/" + remote_commit,
            }

    class Session:
        def __init__(self):
            self.calls = 0

        def get(self, *args, **kwargs):
            self.calls += 1
            return Response()

    session = Session()
    monkeypatch.setattr(module, "SESSION", session)
    with TestClient(module.app) as client:
        headers = {"Authorization": "Bearer test-secret-token"}
        first = client.get("/api/update/check", headers=headers)
        second = client.get("/api/update/check", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["update_available"] is True
    assert first.json()["current_commit"] == local_commit
    assert first.json()["remote_commit"] == remote_commit
    assert first.json()["remote_url"] == "https://github.com/owner/repo/commit/" + remote_commit
    assert first.json()["stale"] is False
    assert second.json()["cache_age_sec"] >= 0
    assert session.calls == 1


def test_github_update_check_marks_expired_fallback_stale(monkeypatch):
    monkeypatch.setenv("DASHBOARD_GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("DASHBOARD_GITHUB_UPDATE_CHECK_SEC", "60")
    module = load_dashboard(monkeypatch)
    monkeypatch.setattr(module, "_git_head_commit", lambda: "a" * 40)

    class Response:
        def __init__(self, status_code):
            self.status_code = status_code

        def json(self):
            return {
                "sha": "b" * 40,
                "html_url": "https://github.com/owner/repo/commit/" + "b" * 40,
            }

    class Session:
        fail = False

        def __init__(self):
            self.calls = 0

        def get(self, *args, **kwargs):
            self.calls += 1
            return Response(503 if self.fail else 200)

    session = Session()
    monkeypatch.setattr(module, "SESSION", session)
    headers = {"Authorization": "Bearer test-secret-token"}
    with TestClient(module.app) as client:
        fresh = client.get("/api/update/check", headers=headers)
        module._GITHUB_UPDATE_CACHE["ts"] -= (
            module.GITHUB_UPDATE_CHECK_TTL_SEC + 1
        )
        module._GITHUB_UPDATE_CACHE["attempt_ts"] -= (
            module.GITHUB_UPDATE_CHECK_TTL_SEC + 1
        )
        session.fail = True
        stale = client.get("/api/update/check", headers=headers)
        stale_cached = client.get("/api/update/check", headers=headers)

    assert fresh.json()["stale"] is False
    assert stale.json()["ok"] is True
    assert stale.json()["stale"] is True
    assert stale.json()["cache_age_sec"] >= 61
    assert stale_cached.json()["stale"] is True
    assert session.calls == 2
    assert stale.json()["error"] == "GitHub HTTP 503"
