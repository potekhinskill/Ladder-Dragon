from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
import time

import pytest

from ladder_dragon.execution.order_recovery import OrderJournal
from ladder_dragon.verification.live import mainnet_limit_maker_validation as drill


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


def _commission() -> dict:
    return {
        "standardCommission": {
            "maker": "0.00075",
            "taker": "0.001",
            "buyer": "0",
            "seller": "0",
        },
        "taxCommission": {
            "maker": "0",
            "taker": "0",
            "buyer": "0",
            "seller": "0",
        },
        "specialCommission": {
            "maker": "0",
            "taker": "0",
            "buyer": "0",
            "seller": "0",
        },
        "discount": {
            "enabledForAccount": False,
            "enabledForSymbol": False,
        },
    }


class FakeClient:
    def __init__(self, state_path: Path, *, fill: bool = True) -> None:
        self.state_path = state_path
        self.fill = fill
        self.base_free = Decimal("3")
        self.orders: dict[str, dict] = {}
        self.calls: list[tuple[str, str]] = []
        self.next_order_id = 100

    def public_get(self, path, _params=None):
        if path == "/api/v3/time":
            return {"serverTime": int(time.time() * 1000)}
        if path == "/api/v3/exchangeInfo":
            return _exchange_info()
        if path == "/api/v3/ticker/bookTicker":
            return {"bidPrice": "99.98", "askPrice": "100.00"}
        if path == "/api/v3/ticker/price":
            return {"price": "100"}
        raise AssertionError(path)

    def _account(self) -> dict:
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

    def signed(self, method, path, params=None):
        params = dict(params or {})
        self.calls.append((method, path))
        if (method, path) == ("GET", "/api/v3/account"):
            return self._account()
        if (method, path) == ("GET", "/api/v3/account/commission"):
            return _commission()
        if (method, path) == ("GET", "/api/v3/openOrders"):
            return [
                row for row in self.orders.values()
                if row["status"] in {"NEW", "PARTIALLY_FILLED"}
            ]
        if (method, path) == ("POST", "/api/v3/order/test"):
            return {}
        if (method, path) == ("POST", "/api/v3/order"):
            order_id = self.next_order_id
            self.next_order_id += 1
            order_type = params["type"]
            quantity = Decimal(params["quantity"])
            if order_type == "LIMIT_MAKER":
                status = "FILLED" if self.fill else "NEW"
                executed = quantity if self.fill else Decimal("0")
                quote = executed * Decimal(params["price"])
                if self.fill:
                    self.base_free += executed
            else:
                assert order_type == "MARKET"
                status = "FILLED"
                executed = quantity
                quote = executed * Decimal("99.90")
                self.base_free -= executed
            row = {
                "symbol": params["symbol"],
                "clientOrderId": params["newClientOrderId"],
                "orderId": order_id,
                "status": status,
                "executedQty": format(executed, "f"),
                "cummulativeQuoteQty": format(quote, "f"),
            }
            self.orders[row["clientOrderId"]] = row
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            state["order_events"] += 1
            state["event_woken_rest_reconciliations"] += 1
            _write(self.state_path, state)
            return dict(row)
        if (method, path) == ("GET", "/api/v3/order"):
            return dict(self.orders[params["origClientOrderId"]])
        if (method, path) == ("DELETE", "/api/v3/order"):
            row = self.orders[params["origClientOrderId"]]
            row["status"] = "CANCELED"
            return dict(row)
        if (method, path) == ("GET", "/api/v3/myTrades"):
            order_id = int(params["orderId"])
            row = next(item for item in self.orders.values() if item["orderId"] == order_id)
            if Decimal(row["executedQty"]) <= 0:
                return []
            price = "99.99" if order_id == 100 else "99.90"
            return [{
                "id": order_id + 1000,
                "orderId": order_id,
                "price": price,
                "qty": row["executedQty"],
                "commission": "0.0000045",
                "commissionAsset": "USDT",
                "time": int(time.time() * 1000),
                "isBuyer": order_id == 100,
            }]
        raise AssertionError((method, path))


class CleanupFailureClient(FakeClient):
    def signed(self, method, path, params=None):
        if (
            (method, path) == ("POST", "/api/v3/order")
            and params["type"] == "MARKET"
        ):
            self.calls.append((method, path))
            raise RuntimeError("cleanup unavailable")
        return super().signed(method, path, params)


class FakeArchive:
    def __init__(self, path: Path) -> None:
        self.path = path

    def start(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{}\n", encoding="utf-8")
        return self.path

    def stop(self) -> dict[str, object]:
        return {"contains_secrets": False, "archive_sha256": "a" * 64}


class FailingArchive(FakeArchive):
    def start(self) -> Path:
        raise RuntimeError("archive handshake unavailable")

    def stop(self) -> dict[str, object]:
        raise AssertionError("an archive that never started must not be stopped")


def _archive_factory(tmp_path: Path):
    return lambda **_options: FakeArchive(tmp_path / "archive.jsonl")


def _environment(tmp_path: Path) -> dict[str, str]:
    control = tmp_path / "control"
    control.mkdir()
    halt = control / "circuit_halt.json"
    halt.write_text("{}", encoding="utf-8")
    return {
        "BOT_LIVE_CONFIRMED": "YES",
        "BOT_MAINNET_LIMIT_MAKER_VALIDATION_CONFIRMED": "YES",
        "BOT_MAINNET_LIMIT_MAKER_VALIDATION_CLEANUP_CONFIRMED": "YES",
        "RISK_RESERVE_USDT": "300",
        "CB_HALT_FILE": str(halt),
        "CB_STATE_FILE": str(control / "risk.json"),
        "CB_ALERTS_FILE": str(control / "alerts.ndjson"),
    }


def _args(tmp_path: Path, runtime: Path, state: Path):
    return drill.build_parser().parse_args([
        "--runtime", str(runtime),
        "--state", str(state),
        "--journal", str(tmp_path / "validation.sqlite3"),
        "--production-journal", str(tmp_path / "production.sqlite3"),
        "--report", str(tmp_path / "validation.ndjson"),
        "--execution-log", str(tmp_path / "execution.ndjson"),
        "--archive-dir", str(tmp_path / "archives"),
        "--lock-file", str(tmp_path / "validation.lock"),
        "--wait-sec", "5",
    ])


def _evidence(tmp_path: Path) -> tuple[Path, Path]:
    runtime = tmp_path / "runtime.json"
    state = tmp_path / "state.json"
    _write(runtime, {
        "execution_mode": "LIVE",
        "venue": "mainnet",
        "risk": {"halted": True, "buy_blocked": True},
        "ai": {"mode": "SHADOW"},
    })
    _write(state, {
        "state": "connected",
        "order_events": 0,
        "event_woken_rest_reconciliations": 0,
    })
    OrderJournal(tmp_path / "production.sqlite3", venue="mainnet")
    return runtime, state


def test_validation_drill_collects_maker_fill_and_restores_base(tmp_path):
    runtime, state = _evidence(tmp_path)
    client = FakeClient(state)

    report = drill.run_validation_drill(
        _args(tmp_path, runtime, state),
        environ=_environment(tmp_path),
        client=client,
        archive_factory=_archive_factory(tmp_path),
    )

    assert report["status"] == "passed"
    assert Decimal(report["executed_qty"]) > 0
    assert report["cleanup_order_filled"] is True
    assert report["base_residual_qty"] == "0"
    assert report["archive_sha256"] == "a" * 64
    assert Path(report["archive_path"]).is_file()
    assert client.base_free == Decimal("3.000")
    evidence = json.loads((tmp_path / "execution.ndjson").read_text())
    assert evidence["order_type"] == "LIMIT_MAKER"
    assert evidence["observation_source"] == "REST_TERMINAL_QUERY"
    assert "clientOrderId" not in evidence
    assert "orderId" not in evidence
    assert (tmp_path / "control" / "circuit_halt.json").is_file()


def test_validation_drill_records_exact_terminal_no_fill_evidence(
    tmp_path, monkeypatch
):
    runtime, state = _evidence(tmp_path)
    client = FakeClient(state, fill=False)

    def immediate(client_arg, *, symbol, order_client_id, timeout_sec):
        del symbol, timeout_sec
        return dict(client_arg.orders[order_client_id]), int(time.time() * 1000)

    monkeypatch.setattr(drill, "_wait_for_fill", immediate)
    report = drill.run_validation_drill(
        _args(tmp_path, runtime, state),
        environ=_environment(tmp_path),
        client=client,
        archive_factory=_archive_factory(tmp_path),
    )

    assert report["status"] == "no_fill"
    assert report["executed_qty"] == "0"
    evidence = json.loads((tmp_path / "execution.ndjson").read_text())
    assert evidence["order_type"] == "LIMIT_MAKER"
    assert evidence["order_status"] == "CANCELED"
    assert evidence["cumulative_quantity"] == "0"
    assert client.calls.count(("POST", "/api/v3/order")) == 1


def test_validation_drill_requires_specific_confirmation(tmp_path):
    runtime, state = _evidence(tmp_path)
    environment = _environment(tmp_path)
    environment.pop("BOT_MAINNET_LIMIT_MAKER_VALIDATION_CONFIRMED")
    client = FakeClient(state)

    with pytest.raises(RuntimeError, match="confirmation missing"):
        drill.run_validation_drill(
            _args(tmp_path, runtime, state),
            environ=environment,
            client=client,
            archive_factory=_archive_factory(tmp_path),
        )

    assert client.calls == []


def test_validation_drill_never_posts_before_archive_readiness(tmp_path):
    runtime, state = _evidence(tmp_path)
    client = FakeClient(state)

    with pytest.raises(RuntimeError, match="archive handshake unavailable"):
        drill.run_validation_drill(
            _args(tmp_path, runtime, state),
            environ=_environment(tmp_path),
            client=client,
            archive_factory=lambda **_options: FailingArchive(
                tmp_path / "archive.jsonl"
            ),
        )

    assert client.calls.count(("POST", "/api/v3/order")) == 0


def test_validation_drill_is_one_exchange_attempt_per_release(tmp_path):
    runtime, state = _evidence(tmp_path)
    args = _args(tmp_path, runtime, state)
    _write(Path(args.report), {
        "product_version": drill.__version__,
        "mutation_started": True,
        "status": "no_fill",
    })
    client = FakeClient(state)

    with pytest.raises(RuntimeError, match="already attempted"):
        drill.run_validation_drill(
            args,
            environ=_environment(tmp_path),
            client=client,
            archive_factory=_archive_factory(tmp_path),
        )

    assert client.calls == []


def test_validation_drill_preserves_halt_when_cleanup_fails(tmp_path):
    runtime, state = _evidence(tmp_path)
    environment = _environment(tmp_path)
    client = CleanupFailureClient(state)

    with pytest.raises(RuntimeError, match="cleanup unavailable"):
        drill.run_validation_drill(
            _args(tmp_path, runtime, state),
            environ=environment,
            client=client,
            archive_factory=_archive_factory(tmp_path),
        )

    assert Path(environment["CB_HALT_FILE"]).is_file()
    assert client.calls.count(("POST", "/api/v3/order")) == 3
    reports = [
        json.loads(line)
        for line in (tmp_path / "validation.ndjson").read_text().splitlines()
    ]
    assert reports[-1]["status"] == "failed"


def test_validation_drill_never_reports_credentials(tmp_path):
    runtime, state = _evidence(tmp_path)
    environment = _environment(tmp_path)
    environment["BINANCE_API_KEY"] = "private-key-value"
    environment["BINANCE_API_SECRET"] = "private-secret-value"
    environment.pop("BOT_MAINNET_LIMIT_MAKER_VALIDATION_CLEANUP_CONFIRMED")

    with pytest.raises(RuntimeError) as captured:
        drill.run_validation_drill(
            _args(tmp_path, runtime, state),
            environ=environment,
            client=FakeClient(state),
            archive_factory=_archive_factory(tmp_path),
        )

    assert "private-key-value" not in str(captured.value)
    assert "private-secret-value" not in str(captured.value)
