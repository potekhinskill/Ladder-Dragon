from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
import time

import pytest

from ladder_dragon.execution.order_recovery import OrderJournal
from ladder_dragon.verification.live.mainnet_user_stream_drill import (
    build_parser,
    run_drill,
)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _exchange_info() -> dict:
    return {
        "symbols": [{
            "symbol": "SOLUSDT",
            "status": "TRADING",
            "baseAsset": "SOL",
            "quoteAsset": "USDT",
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                {
                    "filterType": "LOT_SIZE",
                    "stepSize": "0.001",
                    "minQty": "0.001",
                },
                {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
            ],
        }],
    }


class FakeClient:
    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path
        self.calls: list[tuple[str, str]] = []
        self.order: dict | None = None

    def public_get(self, path, _params=None):
        if path == "/api/v3/time":
            return {"serverTime": int(time.time() * 1000)}
        if path == "/api/v3/exchangeInfo":
            return _exchange_info()
        if path == "/api/v3/ticker/price":
            return {"price": "100"}
        raise AssertionError(path)

    def signed(self, method, path, params=None):
        self.calls.append((method, path))
        if (method, path) == ("GET", "/api/v3/account"):
            return {
                "canTrade": True,
                "balances": [
                    {"asset": "USDT", "free": "500", "locked": "0"},
                    {"asset": "SOL", "free": "3", "locked": "0"},
                ],
            }
        if (method, path) == ("GET", "/api/v3/openOrders"):
            if self.order and self.order["status"] == "NEW":
                return [self.order]
            return []
        if (method, path) == ("POST", "/api/v3/order/test"):
            return {}
        if (method, path) == ("POST", "/api/v3/order"):
            assert params["type"] == "LIMIT_MAKER"
            self.order = {
                "symbol": params["symbol"],
                "clientOrderId": params["newClientOrderId"],
                "orderId": 123,
                "status": "NEW",
                "executedQty": "0",
                "cummulativeQuoteQty": "0",
            }
            return dict(self.order)
        if (method, path) == ("GET", "/api/v3/order"):
            assert self.order is not None
            return dict(self.order)
        if (method, path) == ("DELETE", "/api/v3/order"):
            assert self.order is not None
            self.order["status"] = "CANCELED"
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            state["order_events"] += 1
            state["event_woken_rest_reconciliations"] += 1
            _write(self.state_path, state)
            return dict(self.order)
        raise AssertionError((method, path))


class FilledClient(FakeClient):
    def __init__(self, state_path: Path) -> None:
        super().__init__(state_path)
        self.base_free = Decimal("3")

    def signed(self, method, path, params=None):
        if (method, path) == ("GET", "/api/v3/account"):
            self.calls.append((method, path))
            return {
                "canTrade": True,
                "balances": [
                    {"asset": "USDT", "free": "500", "locked": "0"},
                    {
                        "asset": "SOL",
                        "free": format(self.base_free, "f"),
                        "locked": "0",
                    },
                ],
            }
        if (method, path) == ("POST", "/api/v3/order"):
            self.calls.append((method, path))
            quantity = Decimal(params["quantity"])
            if params["type"] == "LIMIT_MAKER":
                self.base_free += quantity
                self.order = {
                    "symbol": params["symbol"],
                    "clientOrderId": params["newClientOrderId"],
                    "orderId": 123,
                    "status": "FILLED",
                    "executedQty": params["quantity"],
                    "cummulativeQuoteQty": "6",
                }
                return dict(self.order)
            assert params["type"] == "MARKET"
            self.base_free -= quantity
            return {
                "symbol": params["symbol"],
                "clientOrderId": params["newClientOrderId"],
                "orderId": 124,
                "status": "FILLED",
                "executedQty": params["quantity"],
                "cummulativeQuoteQty": "5.99",
            }
        return super().signed(method, path, params)


def _args(tmp_path: Path, runtime: Path, state: Path):
    return build_parser().parse_args([
        "--runtime", str(runtime),
        "--state", str(state),
        "--journal", str(tmp_path / "drill.sqlite3"),
        "--production-journal", str(tmp_path / "production.sqlite3"),
        "--report", str(tmp_path / "drill.ndjson"),
        "--lock-file", str(tmp_path / "drill.lock"),
    ])


def _environment(tmp_path: Path) -> dict[str, str]:
    environment = {
        "BOT_LIVE_CONFIRMED": "YES",
        "BOT_MAINNET_USER_STREAM_DRILL_CONFIRMED": "YES",
        "BOT_MAINNET_USER_STREAM_DRILL_CLEANUP_CONFIRMED": "YES",
        "RISK_RESERVE_USDT": "300",
        "BOT_RUN_DIR": str(tmp_path / "run"),
        "CB_HALT_FILE": str(tmp_path / "halt.json"),
        "CB_STATE_FILE": str(tmp_path / "risk.json"),
        "CB_ALERTS_FILE": str(tmp_path / "alerts.ndjson"),
    }
    Path(environment["CB_HALT_FILE"]).parent.mkdir(parents=True, exist_ok=True)
    Path(environment["CB_HALT_FILE"]).write_text("{}", encoding="utf-8")
    return environment


def _evidence(tmp_path: Path, *, halted: bool = True):
    runtime = tmp_path / "runtime.json"
    state = tmp_path / "stream.json"
    _write(runtime, {
        "execution_mode": "LIVE",
        "venue": "mainnet",
        "risk": {"halted": halted, "buy_blocked": halted},
        "ai": {"mode": "SHADOW"},
    })
    _write(state, {
        "state": "connected",
        "order_events": 0,
        "event_woken_rest_reconciliations": 0,
    })
    OrderJournal(tmp_path / "production.sqlite3", venue="mainnet")
    return runtime, state


def test_mainnet_stream_drill_places_cancels_and_proves_rest(tmp_path):
    runtime, state = _evidence(tmp_path)
    client = FakeClient(state)

    report = run_drill(
        _args(tmp_path, runtime, state),
        environ=_environment(tmp_path),
        client=client,
    )

    assert report["status"] == "passed"
    assert report["order_status"] == "CANCELED"
    assert report["executed_qty"] == "0"
    assert report["order_events_delta"] == 1
    assert report["event_rest_delta"] == 1
    assert client.calls.count(("POST", "/api/v3/order")) == 1
    assert client.calls.count(("DELETE", "/api/v3/order")) == 1


def test_mainnet_stream_drill_requires_halt_before_mutation(tmp_path):
    runtime, state = _evidence(tmp_path, halted=False)
    client = FakeClient(state)

    with pytest.raises(RuntimeError, match="requires LIVE SHADOW"):
        run_drill(
            _args(tmp_path, runtime, state),
            environ=_environment(tmp_path),
            client=client,
        )

    assert ("POST", "/api/v3/order") not in client.calls


def test_mainnet_stream_drill_requires_every_confirmation(tmp_path):
    runtime, state = _evidence(tmp_path)
    environment = _environment(tmp_path)
    environment.pop("BOT_MAINNET_USER_STREAM_DRILL_CLEANUP_CONFIRMED")
    client = FakeClient(state)

    with pytest.raises(RuntimeError, match="confirmation missing"):
        run_drill(
            _args(tmp_path, runtime, state),
            environ=environment,
            client=client,
        )

    assert client.calls == []


def test_mainnet_stream_drill_requires_persistent_halt_file(tmp_path):
    runtime, state = _evidence(tmp_path)
    environment = _environment(tmp_path)
    Path(environment["CB_HALT_FILE"]).unlink()
    client = FakeClient(state)

    with pytest.raises(RuntimeError, match="persistent circuit HALT"):
        run_drill(
            _args(tmp_path, runtime, state),
            environ=environment,
            client=client,
        )

    assert client.calls == []


def test_mainnet_stream_drill_resolves_pi_control_directory(tmp_path):
    runtime, state = _evidence(tmp_path)
    environment = _environment(tmp_path)
    for name in ("CB_HALT_FILE", "CB_STATE_FILE", "CB_ALERTS_FILE"):
        environment.pop(name)
    control_dir = tmp_path / "persistent-control"
    control_dir.mkdir()
    (control_dir / "circuit_halt.json").write_text("{}", encoding="utf-8")
    environment["LADDER_DRAGON_CONTROL_DIR"] = str(control_dir)
    environment["BOT_RUN_DIR"] = "/run/mybot"

    report = run_drill(
        _args(tmp_path, runtime, state),
        environ=environment,
        client=FakeClient(state),
    )

    assert report["status"] == "passed"


def test_mainnet_stream_drill_never_reports_credentials(tmp_path):
    runtime, state = _evidence(tmp_path, halted=False)
    environment = _environment(tmp_path)
    environment["BINANCE_API_KEY"] = "private-key-value"
    environment["BINANCE_API_SECRET"] = "private-secret-value"

    with pytest.raises(RuntimeError) as captured:
        run_drill(
            _args(tmp_path, runtime, state),
            environ=environment,
            client=FakeClient(state),
        )

    message = str(captured.value)
    assert "private-key-value" not in message
    assert "private-secret-value" not in message


def test_mainnet_stream_drill_flattens_unexpected_fill_and_halts(tmp_path):
    runtime, state = _evidence(tmp_path)
    environment = _environment(tmp_path)
    client = FilledClient(state)

    with pytest.raises(RuntimeError, match="unexpectedly executed"):
        run_drill(
            _args(tmp_path, runtime, state),
            environ=environment,
            client=client,
        )

    assert client.base_free == Decimal("3.000")
    assert client.calls.count(("POST", "/api/v3/order")) == 2
    assert Path(environment["CB_HALT_FILE"]).is_file()
    assert not (tmp_path / "drill.ndjson").exists()
