import hashlib
import hmac
import json
from pathlib import Path

import pytest
from websocket import WebSocketTimeoutException

from ladder_dragon.execution.user_stream import (
    BinanceUserDataObserver,
    OrderEventMailbox,
    parse_order_signal,
    reconciliation_due,
    signed_subscription_request,
    websocket_api_url,
)
from ladder_dragon.execution.execution_latency import (
    append_execution_latency_sample,
    load_execution_latencies,
)


def execution_report(**overrides):
    event = {
        "e": "executionReport",
        "E": 1_700_000_000_010,
        "T": 1_700_000_000_009,
        "s": "SOLUSDT",
        "i": 123,
        "c": "LDBLAD-test",
        "x": "TRADE",
        "X": "PARTIALLY_FILLED",
        "t": 456,
        "l": "0.01000000",
        "z": "0.01000000",
    }
    event.update(overrides)
    return {"subscriptionId": 7, "event": event}


def test_execution_report_parser_preserves_partial_fill_identity():
    signal = parse_order_signal(
        execution_report(),
        received_time_ms=1_700_000_000_020,
    )

    assert signal is not None
    assert signal.order_id == 123
    assert signal.client_order_id == "LDBLAD-test"
    assert signal.execution_type == "TRADE"
    assert signal.order_status == "PARTIALLY_FILLED"
    assert signal.last_quantity == "0.01000000"
    assert signal.cumulative_quantity == "0.01000000"
    assert signal.received_time_ms == 1_700_000_000_020
    assert parse_order_signal({"event": {"e": "outboundAccountPosition"}}) is None


def test_execution_latency_log_is_sanitized_and_calibratable(tmp_path):
    signal = parse_order_signal(
        execution_report(x="NEW", X="NEW", t=-1, l="0", z="0"),
        received_time_ms=1_700_000_000_020,
    )
    assert signal is not None
    path = tmp_path / "execution-latency.ndjson"

    payload = append_execution_latency_sample(
        path,
        signal,
        intent_created_at_ms=1_700_000_000_000,
    )

    text = path.read_text()
    assert "LDBLAD-test" not in text
    assert payload["intent_to_event_ms"] == 10
    assert load_execution_latencies(path) == [20]


def test_mailbox_deduplicates_events_and_consumes_only_requested_order():
    mailbox = OrderEventMailbox(max_events=4)
    first = parse_order_signal(execution_report())
    second = parse_order_signal(execution_report(i=124, c="other"))
    assert first is not None and second is not None

    assert mailbox.put(first) is True
    assert mailbox.put(first) is False
    assert mailbox.put(second) is True
    assert mailbox.consume_for([123]) == [first]
    assert mailbox.consume_for([123]) == []
    assert mailbox.consume_for([124]) == [second]


def test_stream_event_accelerates_but_never_replaces_rest_polling():
    event = parse_order_signal(execution_report())
    assert event is not None

    assert reconciliation_due(1, 5, [event]) is True
    assert reconciliation_due(4, 5, []) is False
    assert reconciliation_due(5, 5, []) is True


def test_hmac_subscription_request_matches_sorted_binance_payload():
    request = signed_subscription_request(
        "api-key",
        "secret",
        timestamp_ms=1_700_000_000_000,
        recv_window_ms=5000,
    )
    params = request["params"]
    canonical = (
        "apiKey=api-key&recvWindow=5000&timestamp=1700000000000"
    )
    expected = hmac.new(
        b"secret", canonical.encode(), hashlib.sha256
    ).hexdigest()

    assert request["method"] == "userDataStream.subscribe.signature"
    assert params["signature"] == expected
    assert websocket_api_url("https://api.binance.com") == (
        "wss://ws-api.binance.com:443/ws-api/v3"
    )
    assert websocket_api_url("https://testnet.binance.vision") == (
        "wss://ws-api.testnet.binance.vision/ws-api/v3"
    )


class FakeConnection:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.sent = []
        self.closed = False
        self.pings = 0

    def send(self, payload):
        self.sent.append(json.loads(payload))

    def recv(self):
        return json.dumps(next(self.frames))

    def close(self):
        self.closed = True

    def ping(self):
        self.pings += 1


def test_observer_writes_sanitized_state_and_queues_order_event(tmp_path):
    connection = FakeConnection([
        {"status": 200, "result": {"subscriptionId": 0}},
        execution_report(),
        {"event": {"e": "eventStreamTerminated", "E": 1}},
    ])
    mailbox = OrderEventMailbox()
    observer = BinanceUserDataObserver(
        api_key="public-api-key",
        api_secret="private-secret",
        rest_base_url="https://api.binance.com",
        mailbox=mailbox,
        logger=lambda message: None,
        state_path=tmp_path / "stream.json",
        connect=lambda *args, **kwargs: connection,
    )

    with pytest.raises(RuntimeError, match="ended"):
        observer._observe_connection()

    signal = mailbox.consume_for([123])
    assert len(signal) == 1
    assert connection.sent[0]["method"] == (
        "userDataStream.subscribe.signature"
    )
    state_text = (tmp_path / "stream.json").read_text()
    assert "public-api-key" not in state_text
    assert "private-secret" not in state_text
    assert json.loads(state_text)["order_events"] == 1


def test_invalid_or_terminated_stream_cannot_authorize_an_order(tmp_path):
    mailbox = OrderEventMailbox()
    observer = BinanceUserDataObserver(
        api_key="key",
        api_secret="secret",
        rest_base_url="https://api.binance.com",
        mailbox=mailbox,
        logger=lambda message: None,
        state_path=Path(tmp_path) / "stream.json",
        connect=lambda *args, **kwargs: FakeConnection([
            {"status": 401, "error": {"code": -2015}},
        ]),
    )

    with pytest.raises(RuntimeError, match="rejected"):
        observer._observe_connection()
    assert mailbox.consume_for([123]) == []
    assert reconciliation_due(5, 5, []) is True


def test_idle_socket_ping_does_not_disable_stream_or_rest_fallback(tmp_path):
    class IdleThenEventConnection(FakeConnection):
        def __init__(self):
            super().__init__([
                {"status": 200, "result": {"subscriptionId": 0}},
                execution_report(),
                {"event": {"e": "eventStreamTerminated", "E": 1}},
            ])
            self.recv_count = 0

        def recv(self):
            self.recv_count += 1
            if self.recv_count == 2:
                raise WebSocketTimeoutException("idle")
            return super().recv()

    connection = IdleThenEventConnection()
    mailbox = OrderEventMailbox()
    observer = BinanceUserDataObserver(
        api_key="key",
        api_secret="secret",
        rest_base_url="https://api.binance.com",
        mailbox=mailbox,
        logger=lambda message: None,
        state_path=tmp_path / "stream.json",
        connect=lambda *args, **kwargs: connection,
    )

    with pytest.raises(RuntimeError, match="ended"):
        observer._observe_connection()
    assert connection.pings == 1
    assert len(mailbox.consume_for([123])) == 1


def test_unwritable_health_snapshot_does_not_disable_notifications(tmp_path):
    messages = []
    mailbox = OrderEventMailbox()
    observer = BinanceUserDataObserver(
        api_key="key",
        api_secret="secret",
        rest_base_url="https://api.binance.com",
        mailbox=mailbox,
        logger=messages.append,
        state_path=tmp_path / "occupied" / "stream.json",
    )
    (tmp_path / "occupied").write_text("not a directory")

    observer._set_state(state="connected")

    assert observer.state()["state"] == "connected"
    assert messages == [
        "[USER-STREAM] health snapshot unavailable=FileExistsError"
    ]
