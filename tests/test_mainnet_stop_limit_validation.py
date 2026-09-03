import argparse
from decimal import Decimal
import json
from pathlib import Path
import time

import pytest

from ladder_dragon.execution.execution_latency import load_execution_outcomes
from ladder_dragon.execution.order_recovery import OrderJournal
from ladder_dragon.verification.live import mainnet_stop_limit_validation as drill
from ladder_dragon.verification.live.validation_archive import (
    ValidationArchiveEvidenceError,
)


class EvidenceClient:
    def __init__(self, trades):
        self.trades = trades

    def signed(self, method, path, params=None):
        assert (method, path) == ("GET", "/api/v3/myTrades")
        assert params["orderId"] == 22
        return list(self.trades)

    def public_get(self, path, params=None):
        raise AssertionError((path, params))


def test_stop_leg_evidence_preserves_exact_order_type(tmp_path):
    trade = {
        "id": 7,
        "orderId": 22,
        "price": "99.85",
        "qty": "0.06",
        "commission": "0.005991",
        "commissionAsset": "USDT",
        "time": 2000,
        "isBuyer": False,
    }
    path = tmp_path / "execution.ndjson"
    order_ref, fee = drill._append_leg_evidence(
        path,
        client=EvidenceClient([trade]),
        symbol="SOLUSDT",
        leg={
            "orderId": 22,
            "clientOrderId": "stop-leg",
            "type": "STOP_LOSS_LIMIT",
            "status": "FILLED",
            "price": "99.85",
            "stopPrice": "99.90",
            "origQty": "0.06",
            "executedQty": "0.06",
        },
        intent_created_at_ms=1000,
        received_at_ms=2100,
    )

    outcomes = load_execution_outcomes(path)
    assert len(order_ref) == 24
    assert fee == Decimal("0.005991")
    assert len(outcomes) == 1
    assert outcomes[0].order_type == "STOP_LOSS_LIMIT"
    assert outcomes[0].stop_price == Decimal("99.90")
    assert outcomes[0].final_status == "FILLED"


def test_cancelled_stop_leg_is_a_terminal_zero_fill(tmp_path):
    path = tmp_path / "execution.ndjson"
    drill._append_leg_evidence(
        path,
        client=EvidenceClient([]),
        symbol="SOLUSDT",
        leg={
            "orderId": 22,
            "clientOrderId": "stop-leg",
            "type": "STOP_LOSS_LIMIT",
            "status": "CANCELED",
            "price": "99.85",
            "stopPrice": "99.90",
            "origQty": "0.06",
            "executedQty": "0",
            "cummulativeQuoteQty": "0",
            "updateTime": 2000,
        },
        intent_created_at_ms=1000,
        received_at_ms=2100,
    )

    outcome = load_execution_outcomes(path)[0]
    assert outcome.final_status == "CANCELED"
    assert outcome.cumulative_quantity == Decimal("0")


def test_stop_drill_rejects_missing_confirmation_before_client_use():
    args = argparse.Namespace()
    with pytest.raises(RuntimeError, match="confirmation missing"):
        drill.run_validation_drill(args, environ={}, client=object())


def test_stop_drill_report_blocks_second_release_attempt(tmp_path):
    path = tmp_path / "report.ndjson"
    path.write_text(
        json.dumps(
            {
                "product_version": drill.__version__,
                "mutation_started": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="already attempted"):
        drill._require_no_prior_attempt(path)


def test_stop_drill_confirmation_error_never_reports_secrets():
    environment = {
        "BINANCE_API_KEY": "private-key-value",
        "BINANCE_API_SECRET": "private-secret-value",
    }
    with pytest.raises(RuntimeError) as captured:
        drill.run_validation_drill(
            argparse.Namespace(), environ=environment, client=object()
        )

    assert "private-key-value" not in str(captured.value)
    assert "private-secret-value" not in str(captured.value)


class FakeArchive:
    def __init__(self, path: Path) -> None:
        self.path = path

    def start(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{}\n", encoding="utf-8")
        return self.path

    def stop(self) -> dict[str, object]:
        return {"contains_secrets": False, "archive_sha256": "c" * 64}


class FailingArchive(FakeArchive):
    def start(self) -> Path:
        raise RuntimeError("private archive source detail")


class ShortEvidenceArchive(FakeArchive):
    def stop(self) -> dict[str, object]:
        raise ValidationArchiveEvidenceError()


class FullDrillClient:
    def __init__(self) -> None:
        self.base_free = Decimal("3")
        self.oco_canceled = False
        self.cleanup: dict | None = None

    def public_get(self, path, params=None):
        if path == "/api/v3/time":
            return {"serverTime": int(time.time() * 1000)}
        if path == "/api/v3/exchangeInfo":
            return {
                "symbols": [{
                    "symbol": "SOLUSDT",
                    "status": "TRADING",
                    "isSpotTradingAllowed": True,
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
                }]
            }
        if path == "/api/v3/ticker/price":
            return {"symbol": "SOLUSDT", "price": "100"}
        raise AssertionError((path, params))

    def _account(self):
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

    @staticmethod
    def _commission():
        zero = {"maker": "0", "taker": "0", "buyer": "0", "seller": "0"}
        return {
            "standardCommission": {
                "maker": "0.00075",
                "taker": "0.001",
                "buyer": "0",
                "seller": "0",
            },
            "taxCommission": zero,
            "specialCommission": zero,
            "discount": {
                "enabledForAccount": False,
                "enabledForSymbol": False,
            },
        }

    def _leg(self, order_id: int):
        stop = order_id == 204
        return {
            "symbol": "SOLUSDT",
            "orderId": order_id,
            "clientOrderId": "sl" if stop else "tp",
            "side": "SELL",
            "type": "STOP_LOSS_LIMIT" if stop else "LIMIT_MAKER",
            "status": "CANCELED" if self.oco_canceled else "NEW",
            "price": "99.85" if stop else "105.00",
            "stopPrice": "99.90" if stop else "0",
            "origQty": "0.060",
            "executedQty": "0",
            "cummulativeQuoteQty": "0",
            "updateTime": 2000,
        }

    def signed(self, method, path, params=None):
        params = dict(params or {})
        if (method, path) == ("GET", "/api/v3/account"):
            return self._account()
        if (method, path) == ("GET", "/api/v3/account/commission"):
            return self._commission()
        if (method, path) == ("GET", "/api/v3/openOrders"):
            return []
        if (method, path) == ("POST", "/api/v3/order"):
            if params["side"] == "BUY":
                self.base_free += Decimal("0.060")
                return {
                    "symbol": "SOLUSDT",
                    "orderId": 101,
                    "clientOrderId": params["newClientOrderId"],
                    "status": "FILLED",
                    "executedQty": "0.060",
                    "cummulativeQuoteQty": "6",
                }
            self.base_free -= Decimal(params["quantity"])
            self.cleanup = {
                "symbol": "SOLUSDT",
                "orderId": 303,
                "clientOrderId": params["newClientOrderId"],
                "status": "FILLED",
                "executedQty": params["quantity"],
                "cummulativeQuoteQty": "5.994",
            }
            return dict(self.cleanup)
        if (method, path) == ("POST", "/api/v3/orderList/oco"):
            return {
                "orderListId": 202,
                "listClientOrderId": params["listClientOrderId"],
                "listStatusType": "EXEC_STARTED",
            }
        if (method, path) == ("GET", "/api/v3/orderList"):
            return {
                "orderListId": 202,
                "listClientOrderId": "oco",
                "listStatusType": (
                    "ALL_DONE" if self.oco_canceled else "EXEC_STARTED"
                ),
                "orders": [
                    {"orderId": 203, "clientOrderId": "tp"},
                    {"orderId": 204, "clientOrderId": "sl"},
                ],
            }
        if (method, path) == ("DELETE", "/api/v3/orderList"):
            self.oco_canceled = True
            return {"orderListId": 202, "listStatusType": "ALL_DONE"}
        if (method, path) == ("GET", "/api/v3/order"):
            if "orderId" in params:
                return self._leg(int(params["orderId"]))
            assert self.cleanup is not None
            return dict(self.cleanup)
        if (method, path) == ("GET", "/api/v3/myTrades"):
            if int(params["orderId"]) in {203, 204}:
                return []
            return [{
                "id": 1303,
                "orderId": 303,
                "price": "99.90",
                "qty": "0.060",
                "commission": "0.005994",
                "commissionAsset": "USDT",
                "time": 3000,
                "isBuyer": False,
            }]
        raise AssertionError((method, path, params))


def _full_drill_setup(tmp_path):
    runtime = tmp_path / "runtime.json"
    state = tmp_path / "state.json"
    runtime.write_text(
        json.dumps({
            "execution_mode": "LIVE",
            "venue": "mainnet",
            "risk": {"halted": True, "buy_blocked": True},
            "ai": {"mode": "SHADOW"},
        }),
        encoding="utf-8",
    )
    state.write_text(
        json.dumps({
            "state": "connected",
            "order_events": 0,
            "event_woken_rest_reconciliations": 0,
        }),
        encoding="utf-8",
    )
    OrderJournal(tmp_path / "production.sqlite3", venue="mainnet")
    halt = tmp_path / "halt.json"
    halt.write_text("{}", encoding="utf-8")
    environment = {
        **drill.CONFIRMATIONS,
        "RISK_RESERVE_USDT": "300",
        "CB_HALT_FILE": str(halt),
        "CB_STATE_FILE": str(tmp_path / "risk.json"),
        "CB_ALERTS_FILE": str(tmp_path / "alerts.ndjson"),
    }
    args = drill.build_parser().parse_args([
        "--runtime", str(runtime),
        "--state", str(state),
        "--journal", str(tmp_path / "validation.sqlite3"),
        "--production-journal", str(tmp_path / "production.sqlite3"),
        "--report", str(tmp_path / "report.ndjson"),
        "--execution-log", str(tmp_path / "execution.ndjson"),
        "--archive-dir", str(tmp_path / "archives"),
        "--wait-sec", "30",
    ])
    return args, environment


def test_stop_drill_runs_one_bounded_no_fill_lifecycle(
    tmp_path, monkeypatch
):
    args, environment = _full_drill_setup(tmp_path)
    monkeypatch.setattr(
        drill,
        "_wait_for_order_list",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        drill.stream_drill,
        "_wait_for_stream_evidence",
        lambda *_args, **_kwargs: {
            "order_events": 4,
            "event_woken_rest_reconciliations": 4,
        },
    )

    report = drill.run_validation_drill(
        args,
        environ=environment,
        client=FullDrillClient(),
        archive_factory=lambda **_options: FakeArchive(
            tmp_path / "archives" / "stop.jsonl"
        ),
    )

    assert report["status"] == "no_stop_fill"
    assert report["stop_filled"] is False
    assert report["archive_sha256"] == "c" * 64
    outcomes = load_execution_outcomes(tmp_path / "execution.ndjson")
    assert {item.order_type for item in outcomes} == {
        "LIMIT_MAKER",
        "STOP_LOSS_LIMIT",
    }
    telemetry = OrderJournal(
        tmp_path / "validation.sqlite3",
        venue="mainnet-stop-validation",
    ).nonterminal_orders("SOLUSDT")
    assert telemetry == []


def test_stop_archive_failure_is_definite_before_mutation(
    tmp_path, monkeypatch
):
    args, environment = _full_drill_setup(tmp_path)
    args.batch_manifest = str(tmp_path / "batch.json")
    monkeypatch.setattr(
        drill,
        "validation_batch_archive_directory",
        lambda _path: Path(args.archive_dir).resolve(),
    )
    completed: list[str] = []
    monkeypatch.setattr(
        drill,
        "reserve_validation_attempt",
        lambda *_args, **_kwargs: {
            "attempt_id": "attempt-one",
            "manifest_sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(
        drill,
        "complete_validation_attempt",
        lambda *_args, **kwargs: completed.append(str(kwargs["status"])),
    )
    client = FullDrillClient()

    with pytest.raises(drill.PreMutationValidationFailure) as captured:
        drill.run_validation_drill(
            args,
            environ=environment,
            client=client,
            archive_factory=lambda **_options: FailingArchive(
                tmp_path / "archives" / "stop.jsonl"
            ),
        )

    assert "private archive source detail" not in str(captured.value)
    assert completed == ["FAILED_DEFINITE"]
    assert client.base_free == Decimal("3")
    reports = [
        json.loads(line)
        for line in (tmp_path / "report.ndjson").read_text().splitlines()
    ]
    assert reports[-1]["failure_phase"] == "pre_mutation"
    assert reports[-1]["mutation_started"] is False


def test_stop_short_archive_is_definite_after_cleanup(tmp_path, monkeypatch):
    args, environment = _full_drill_setup(tmp_path)
    args.batch_manifest = str(tmp_path / "batch.json")
    monkeypatch.setattr(
        drill,
        "validation_batch_archive_directory",
        lambda _path: Path(args.archive_dir).resolve(),
    )
    completed: list[str] = []
    monkeypatch.setattr(
        drill,
        "reserve_validation_attempt",
        lambda *_args, **_kwargs: {
            "attempt_id": "attempt-one",
            "manifest_sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(
        drill,
        "complete_validation_attempt",
        lambda *_args, **kwargs: completed.append(str(kwargs["status"])),
    )
    monkeypatch.setattr(
        drill,
        "_wait_for_order_list",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        drill.stream_drill,
        "_wait_for_stream_evidence",
        lambda *_args, **_kwargs: {
            "order_events": 4,
            "event_woken_rest_reconciliations": 4,
        },
    )
    client = FullDrillClient()

    with pytest.raises(ValidationArchiveEvidenceError):
        drill.run_validation_drill(
            args,
            environ=environment,
            client=client,
            archive_factory=lambda **_options: ShortEvidenceArchive(
                tmp_path / "archives" / "stop.jsonl"
            ),
        )

    assert completed == ["FAILED_DEFINITE"]
    assert client.base_free == Decimal("3")
    reports = [
        json.loads(line)
        for line in (tmp_path / "report.ndjson").read_text().splitlines()
    ]
    assert reports[-1]["failure_phase"] == "post_mutation"
    assert reports[-1]["error_code"] == "PUBLIC_ARCHIVE_EVIDENCE_INSUFFICIENT"
