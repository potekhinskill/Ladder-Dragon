import hashlib
import hmac
import json
from decimal import Decimal
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
from websocket import ABNF, WebSocketException, WebSocketTimeoutException

import ladder_dragon.execution.user_stream as user_stream_module

from ladder_dragon.execution.user_stream import (
    BinanceUserDataObserver,
    CURRENT_USER_STREAM_SOAK_EPOCH_ID,
    OrderEventMailbox,
    PERSISTED_COUNTERS,
    parse_order_signal,
    reconciliation_due,
    signed_subscription_request,
    websocket_api_url,
)
from ladder_dragon.execution.execution_latency import (
    append_execution_latency_sample,
    load_execution_latencies,
    load_execution_outcomes,
)
from ladder_dragon.execution.user_stream_soak import audit_user_stream_soak
from ladder_dragon.execution.user_stream_shadow import (
    consume_controlled_reconnect,
    reconcile_order_events,
)


def soak_epoch(started_at, **baseline_overrides):
    """Build a complete sanitized epoch baseline for audit tests."""
    baseline = {name: 0 for name in PERSISTED_COUNTERS}
    baseline.update(baseline_overrides)
    return [{
        "id": CURRENT_USER_STREAM_SOAK_EPOCH_ID,
        "started_at": started_at,
        "baseline": baseline,
    }]


def test_controlled_reconnect_request_waits_for_connected_observer():
    class Observer:
        def __init__(self):
            self.connection_state = "reconnecting"
            self.requests = 0

        def state(self):
            return {"state": self.connection_state}

        def request_reconnect_drill(self):
            self.requests += 1

    observer = Observer()
    requested = threading.Event()
    requested.set()
    messages = []

    assert not consume_controlled_reconnect(
        observer, requested, logger=messages.append
    )
    assert requested.is_set()
    observer.connection_state = "connected"
    assert consume_controlled_reconnect(
        observer, requested, logger=messages.append
    )
    assert observer.requests == 1
    assert not requested.is_set()
    assert messages == ["[USER-STREAM-SOAK] controlled reconnect requested"]


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
        "S": "BUY",
        "o": "LIMIT_MAKER",
        "p": "75.50",
        "P": "0",
        "q": "0.10000000",
        "L": "75.50",
        "l": "0.01000000",
        "z": "0.01000000",
        "Z": "0.75500000",
        "n": "0.00001",
        "N": "BNB",
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
    assert signal.side == "BUY"
    assert signal.order_type == "LIMIT_MAKER"
    assert signal.stop_price == "0"
    assert signal.order_price == "75.50"
    assert signal.original_quantity == "0.10000000"
    assert signal.last_price == "75.50"
    assert signal.cumulative_quote == "0.75500000"
    assert signal.commission_amount == "0.00001"
    assert signal.commission_asset == "BNB"
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
    assert payload["schema_version"] == 4
    assert payload["order_type"] == "LIMIT_MAKER"
    assert payload["order_price"] == "75.50"
    assert payload["original_quantity"] == "0.10000000"
    assert load_execution_latencies(path) == [20]


def test_execution_outcomes_group_partial_and_terminal_reports(tmp_path):
    path = tmp_path / "execution-latency.ndjson"
    for report, received in (
        (
            execution_report(
                x="NEW", X="NEW", t=-1, l="0", z="0", Z="0"
            ),
            1_700_000_000_020,
        ),
        (
            execution_report(
                x="TRADE", X="PARTIALLY_FILLED", l="0.04", z="0.04",
                Z="3.02000000",
            ),
            1_700_000_000_050,
        ),
        (
            execution_report(
                x="TRADE", X="FILLED", l="0.06", z="0.10",
                Z="7.55000000", t=457,
            ),
            1_700_000_000_080,
        ),
    ):
        signal = parse_order_signal(report, received_time_ms=received)
        assert signal is not None
        append_execution_latency_sample(
            path,
            signal,
            intent_created_at_ms=1_700_000_000_000,
            commission_quote=(
                Decimal("0.001")
                if signal.execution_type == "TRADE" else None
            ),
            commission_value_status=(
                "converted"
                if signal.execution_type == "TRADE" else "not_applicable"
            ),
        )

    outcomes = load_execution_outcomes(path)

    assert len(outcomes) == 1
    assert outcomes[0].final_status == "FILLED"
    assert outcomes[0].fill_ratio == Decimal("1")
    assert outcomes[0].average_fill_price == Decimal("75.5000000")
    assert outcomes[0].first_fill_received_at_ms == 1_700_000_000_050
    assert outcomes[0].final_received_at_ms == 1_700_000_000_080
    assert outcomes[0].commission_quote == Decimal("0.002")


def test_execution_outcomes_use_canonical_legacy_commission_status(tmp_path):
    path = tmp_path / "execution-latency.ndjson"
    signal = parse_order_signal(
        execution_report(
            x="TRADE",
            X="FILLED",
            l="0.10",
            z="0.10",
            Z="7.55000000",
            t=458,
        ),
        received_time_ms=1_700_000_000_080,
    )
    assert signal is not None
    append_execution_latency_sample(
        path,
        signal,
        intent_created_at_ms=1_700_000_000_000,
        commission_quote=Decimal("0.001"),
        commission_value_status="legacy",
    )

    outcomes = load_execution_outcomes(path)

    assert len(outcomes) == 1
    assert outcomes[0].commission_quote == Decimal("0.001")


def test_execution_outcomes_reject_unknown_commission_status(tmp_path):
    path = tmp_path / "execution-latency.ndjson"
    signal = parse_order_signal(
        execution_report(
            x="TRADE",
            X="FILLED",
            l="0.10",
            z="0.10",
            Z="7.55000000",
            t=459,
        ),
        received_time_ms=1_700_000_000_080,
    )
    assert signal is not None
    append_execution_latency_sample(
        path,
        signal,
        intent_created_at_ms=1_700_000_000_000,
        commission_quote=Decimal("0.001"),
        commission_value_status="guessed",
    )

    outcomes = load_execution_outcomes(path)

    assert len(outcomes) == 1
    assert outcomes[0].commission_quote is None


def test_mailbox_deduplicates_events_and_consumes_only_requested_order():
    mailbox = OrderEventMailbox(max_events=4)
    first = parse_order_signal(execution_report())
    second = parse_order_signal(execution_report(i=124, c="other"))
    assert first is not None and second is not None

    assert mailbox.put(first) is True
    assert mailbox.put(first) is False
    replayed_with_different_envelope_time = parse_order_signal(
        execution_report(E=first.event_time_ms + 5)
    )
    assert replayed_with_different_envelope_time is not None
    assert mailbox.put(replayed_with_different_envelope_time) is False
    assert mailbox.put(second) is True
    assert mailbox.consume_for([123]) == [first]
    assert mailbox.consume_for([123]) == []
    assert mailbox.consume_for([124]) == [second]


def test_mailbox_wait_returns_immediately_when_event_is_pending():
    mailbox = OrderEventMailbox(max_events=4)
    event = parse_order_signal(execution_report())
    assert event is not None

    assert mailbox.wait(0) is False
    assert mailbox.put(event) is True
    assert mailbox.wait(10) is True
    assert mailbox.consume_for([event.order_id]) == [event]
    assert mailbox.wait(0) is False


def test_read_only_soak_mailbox_can_drain_all_events():
    mailbox = OrderEventMailbox(max_events=4)
    first = parse_order_signal(execution_report(i=123))
    second = parse_order_signal(execution_report(i=124))
    assert first is not None and second is not None
    mailbox.put(first)
    mailbox.put(second)

    assert mailbox.consume_all() == [first, second]
    assert mailbox.consume_all() == []


def test_shadow_event_reconciliation_uses_get_and_validates_identity():
    first = parse_order_signal(execution_report(i=123))
    duplicate_order = parse_order_signal(
        execution_report(i=123, X="FILLED", z="0.1")
    )
    second = parse_order_signal(execution_report(i=124))
    assert first is not None and duplicate_order is not None and second is not None
    calls = []

    def signed_get(path, params):
        calls.append((path, dict(params)))
        return {"symbol": params["symbol"], "orderId": params["orderId"]}

    count = reconcile_order_events(
        [first, duplicate_order, second],
        signed_get=signed_get,
    )

    assert count == 2
    assert calls == [
        ("/api/v3/order", {"symbol": "SOLUSDT", "orderId": 123}),
        ("/api/v3/order", {"symbol": "SOLUSDT", "orderId": 124}),
    ]


def test_shadow_event_reconciliation_fails_closed_on_wrong_order():
    event = parse_order_signal(execution_report(i=123))
    assert event is not None

    with pytest.raises(RuntimeError, match="identity mismatch"):
        reconcile_order_events(
            [event],
            signed_get=lambda _path, _params: {
                "symbol": "SOLUSDT",
                "orderId": 999,
            },
        )


def test_mailbox_wait_for_ignores_unrelated_pending_events():
    mailbox = OrderEventMailbox(max_events=4)
    unrelated = parse_order_signal(execution_report(i=999, c="other"))
    tracked = parse_order_signal(execution_report(i=123, c="tracked"))
    assert unrelated is not None and tracked is not None

    assert mailbox.put(unrelated) is True
    assert mailbox.wait_for([123], 0) is False
    assert mailbox.put(tracked) is True
    assert mailbox.wait_for([123], 10) is True


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


class RawFrameConnection(FakeConnection):
    def recv(self):
        frame = next(self.frames)
        return frame if isinstance(frame, str) else json.dumps(frame)


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


def test_controlled_reconnect_drill_closes_only_the_stream_socket(tmp_path):
    connection = FakeConnection([])
    observer = BinanceUserDataObserver(
        api_key="key",
        api_secret="secret",
        rest_base_url="https://testnet.binance.vision",
        mailbox=OrderEventMailbox(),
        logger=lambda _message: None,
        state_path=tmp_path / "stream.json",
    )
    observer._connection = connection
    observer._set_state(state="connected")

    observer.request_reconnect_drill()

    assert connection.closed is True
    assert observer.state()["controlled_reconnect_drills"] == 1
    assert observer.state()["rest_reconciliations"] == 0


def test_state_file_writes_are_rate_limited_but_memory_stays_current(
    tmp_path,
    monkeypatch,
):
    monotonic_now = [100.0]
    replacements = []
    real_replace = user_stream_module.os.replace

    def observed_replace(source, target):
        replacements.append((source, target))
        real_replace(source, target)

    monkeypatch.setattr(user_stream_module.os, "replace", observed_replace)
    observer = BinanceUserDataObserver(
        api_key="key",
        api_secret="secret",
        rest_base_url="https://api.binance.com",
        mailbox=OrderEventMailbox(),
        logger=lambda message: None,
        state_path=tmp_path / "stream.json",
        state_persist_interval_sec=5,
        monotonic=lambda: monotonic_now[0],
    )

    observer._set_state(last_event_at=1.0)
    observer._set_state(last_event_at=2.0)
    observer._set_state(last_event_at=3.0)

    assert observer.state()["last_event_at"] == 3.0
    assert len(replacements) == 1
    assert json.loads((tmp_path / "stream.json").read_text())[
        "last_event_at"
    ] == 1.0

    monotonic_now[0] += 5.0
    observer._set_state(last_event_at=4.0)
    assert len(replacements) == 2
    assert json.loads((tmp_path / "stream.json").read_text())[
        "last_event_at"
    ] == 4.0


def test_observer_state_snapshot_is_serialized_by_observer_lock(tmp_path):
    observer = BinanceUserDataObserver(
        api_key="key",
        api_secret="secret",
        rest_base_url="https://api.binance.com",
        mailbox=OrderEventMailbox(),
        logger=lambda message: None,
        state_path=tmp_path / "stream.json",
    )
    started = threading.Event()
    completed = threading.Event()
    captured = []

    def read_snapshot():
        started.set()
        captured.append(observer.state())
        completed.set()

    with observer._state_lock:
        observer._state.update(
            {"state": "connected", "sessions": 1}
        )
        reader = threading.Thread(target=read_snapshot)
        reader.start()
        assert started.wait(1)
        assert completed.wait(0.05) is False
        observer._state.update(
            {"state": "reconnecting", "sessions": 2}
        )

    reader.join(timeout=1)
    assert completed.is_set()
    assert len(captured) == 1
    assert captured[0]["state"] == "reconnecting"
    assert captured[0]["sessions"] == 2


def test_malformed_frame_is_counted_without_reconnecting_session(tmp_path):
    messages = []
    connection = RawFrameConnection([
        {"status": 200, "result": {"subscriptionId": 0}},
        "{not-json",
        execution_report(),
        {"event": {"e": "eventStreamTerminated", "E": 1}},
    ])
    mailbox = OrderEventMailbox()
    observer = BinanceUserDataObserver(
        api_key="key",
        api_secret="secret",
        rest_base_url="https://api.binance.com",
        mailbox=mailbox,
        logger=messages.append,
        state_path=tmp_path / "stream.json",
        connect=lambda *args, **kwargs: connection,
    )

    with pytest.raises(RuntimeError, match="ended"):
        observer._observe_connection()

    assert observer.state()["bad_frames"] == 1
    assert len(mailbox.consume_for([123])) == 1
    assert messages.count(
        "[USER-STREAM] discarded malformed frame; "
        "REST polling remains authoritative"
    ) == 1


def test_subscription_timestamp_uses_injected_server_clock(tmp_path):
    connection = FakeConnection([
        {"status": 200, "result": {"subscriptionId": 0}},
        {"event": {"e": "eventStreamTerminated", "E": 1}},
    ])
    observer = BinanceUserDataObserver(
        api_key="key",
        api_secret="secret",
        rest_base_url="https://api.binance.com",
        mailbox=OrderEventMailbox(),
        logger=lambda message: None,
        state_path=tmp_path / "stream.json",
        connect=lambda *args, **kwargs: connection,
        timestamp_ms=lambda: 1_700_000_005_123,
    )

    with pytest.raises(RuntimeError, match="ended"):
        observer._observe_connection()

    assert connection.sent[0]["params"]["timestamp"] == 1_700_000_005_123


def test_silent_session_reconnects_after_deadline(tmp_path):
    class SilentConnection(FakeConnection):
        def recv(self):
            if not hasattr(self, "subscribed"):
                self.subscribed = True
                return json.dumps({
                    "status": 200,
                    "result": {"subscriptionId": 0},
                })
            raise WebSocketTimeoutException("silent")

    ticks = iter((0.0, 0.0, 0.0, 0.5, 2.0))
    connection = SilentConnection([])
    observer = BinanceUserDataObserver(
        api_key="key",
        api_secret="secret",
        rest_base_url="https://api.binance.com",
        mailbox=OrderEventMailbox(),
        logger=lambda message: None,
        state_path=tmp_path / "stream.json",
        connect=lambda *args, **kwargs: connection,
        idle_timeout_sec=1,
        monotonic=lambda: next(ticks),
    )

    with pytest.raises(TimeoutError, match="silent-session"):
        observer._observe_connection()

    assert connection.pings == 1


def test_control_pong_keeps_quiet_live_session_connected(tmp_path):
    now = [0.0]

    class HeartbeatConnection(FakeConnection):
        def __init__(self):
            super().__init__([
                {"status": 200, "result": {"subscriptionId": 0}},
            ])
            self.frame_calls = 0

        def recv_data_frame(self, *, control_frame=False):
            assert control_frame is True
            self.frame_calls += 1
            if self.frame_calls == 1:
                now[0] = 0.5
                raise WebSocketTimeoutException("idle")
            if self.frame_calls == 3:
                now[0] = 1.2
                raise WebSocketTimeoutException("idle")
            if self.frame_calls == 2:
                return ABNF.OPCODE_PONG, SimpleNamespace(data=b"")
            payload = (
                execution_report()
                if self.frame_calls == 4
                else {"event": {"e": "eventStreamTerminated", "E": 1}}
            )
            return ABNF.OPCODE_TEXT, SimpleNamespace(data=json.dumps(payload))

    connection = HeartbeatConnection()
    mailbox = OrderEventMailbox()
    observer = BinanceUserDataObserver(
        api_key="key",
        api_secret="secret",
        rest_base_url="https://api.binance.com",
        mailbox=mailbox,
        logger=lambda message: None,
        state_path=tmp_path / "stream.json",
        connect=lambda *args, **kwargs: connection,
        idle_timeout_sec=1,
        monotonic=lambda: now[0],
    )

    with pytest.raises(RuntimeError, match="ended"):
        observer._observe_connection()

    assert connection.pings == 2
    assert len(mailbox.consume_for([123])) == 1
    assert observer.state()["last_transport_activity_at"] is not None
    persisted = json.loads((tmp_path / "stream.json").read_text())
    assert persisted["last_transport_activity_at"] is not None


def test_observer_restores_only_sanitized_cumulative_soak_state(tmp_path):
    path = tmp_path / "stream.json"
    path.write_text(json.dumps({
        "state": "connected",
        "first_observed_at": 1000,
        "reconnects": 2,
        "connection_attempts": 3,
        "sessions": 2,
        "disconnects": 1,
        "order_events": 4,
        "duplicates": 1,
        "out_of_order_events": 1,
        "last_error": "must-not-be-restored",
        "api_key": "must-not-be-read",
    }))

    observer = BinanceUserDataObserver(
        api_key="key",
        api_secret="secret",
        rest_base_url="https://api.binance.com",
        mailbox=OrderEventMailbox(),
        logger=lambda message: None,
        state_path=path,
    )

    state = observer.state()
    assert state["state"] == "stopped"
    assert state["first_observed_at"] == 1000
    assert state["reconnects"] == 2
    assert state["sessions"] == 2
    assert state["order_events"] == 4
    assert state["last_error"] is None
    assert state["soak_epoch_error"] is None
    assert state["soak_epochs"][0]["baseline"]["reconnects"] == 2
    assert state["soak_epochs"][0]["baseline"]["order_events"] == 4
    assert "api_key" not in state


def test_user_stream_soak_audit_requires_duration_freshness_and_drills(
    tmp_path,
):
    path = tmp_path / "stream.json"
    path.write_text(json.dumps({
        "state": "connected",
        "first_observed_at": 1_000,
        "sessions": 3,
        "reconnects": 1,
        "controlled_reconnect_drills": 1,
        "order_events": 2,
        "rest_reconciliations": 4,
        "event_woken_rest_reconciliations": 2,
        "soak_epochs": soak_epoch(1_000),
    }))
    path.touch()

    ready = audit_user_stream_soak(
        [path],
        minimum_hours=24,
        maximum_stale_sec=180,
        require_reconnect=True,
        require_order_event=True,
        require_event_woken_rest=True,
        now=1_000 + 25 * 3600,
    )
    assert ready.ready is True
    assert ready.as_dict()["rest_remains_authoritative"] is True
    assert ready.streams[0]["reconnects_per_hour"] == 0.04
    assert ready.streams[0]["transport_failure_reconnects_per_hour"] == 0
    assert ready.streams[0]["lifetime_reconnects"] == 1

    blocked = audit_user_stream_soak(
        [path],
        minimum_hours=48,
        require_reconnect=True,
        require_order_event=True,
        require_event_woken_rest=True,
        now=1_000 + 25 * 3600,
    )
    assert blocked.ready is False
    assert "soak duration" in " ".join(blocked.reasons)


def test_user_stream_soak_blocks_chronic_reconnect_churn(tmp_path):
    path = tmp_path / "stream.json"
    path.write_text(json.dumps({
        "state": "connected",
        "first_observed_at": 1_000,
        "sessions": 241,
        "reconnects": 240,
        "transport_failure_reconnects": 240,
        "order_events": 2,
        "rest_reconciliations": 4,
        "event_woken_rest_reconciliations": 2,
        "soak_epochs": soak_epoch(1_000),
    }))
    path.touch()

    blocked = audit_user_stream_soak(
        [path],
        minimum_hours=24,
        maximum_transport_failure_reconnects_per_hour=1,
        now=1_000 + 25 * 3600,
    )

    assert blocked.ready is False
    assert blocked.streams[0]["reconnects_per_hour"] == 9.6
    assert blocked.streams[0]["transport_failure_reconnects_per_hour"] == 9.6
    assert "transport-failure reconnect rate is too high" in " ".join(
        blocked.reasons
    )


def test_user_stream_soak_allows_expected_idle_reconnects(tmp_path):
    path = tmp_path / "stream.json"
    path.write_text(json.dumps({
        "state": "connected",
        "first_observed_at": 1_000,
        "sessions": 4,
        "reconnects": 112,
        "idle_reconnects": 111,
        "transport_failure_reconnects": 0,
        "controlled_reconnect_drills": 1,
        "order_events": 2,
        "rest_reconciliations": 100,
        "event_woken_rest_reconciliations": 2,
        "soak_epochs": soak_epoch(1_000),
    }))

    ready = audit_user_stream_soak(
        [path],
        minimum_hours=24,
        maximum_transport_failure_reconnects_per_hour=1,
        require_reconnect=True,
        require_order_event=True,
        require_event_woken_rest=True,
        now=1_000 + 25 * 3600,
    )

    assert ready.ready is True
    assert ready.streams[0]["reconnects_per_hour"] == 4.48
    assert ready.streams[0]["transport_failure_reconnects_per_hour"] == 0


def test_user_stream_soak_uses_epoch_without_deleting_lifetime_evidence(
    tmp_path,
):
    path = tmp_path / "stream.json"
    payload = {
        "state": "connected",
        "first_observed_at": 1_000,
        "sessions": 37,
        "reconnects": 1_070,
        "controlled_reconnect_drills": 5,
        "order_events": 3,
        "rest_reconciliations": 6_700,
        "event_woken_rest_reconciliations": 3,
        "soak_epochs": soak_epoch(
            1_000 + 100 * 3600,
            sessions=36,
            reconnects=1_069,
            controlled_reconnect_drills=4,
            order_events=2,
            rest_reconciliations=6_600,
            event_woken_rest_reconciliations=2,
        ),
    }
    path.write_text(json.dumps(payload))

    ready = audit_user_stream_soak(
        [path],
        minimum_hours=24,
        maximum_transport_failure_reconnects_per_hour=1,
        require_reconnect=True,
        require_order_event=True,
        require_event_woken_rest=True,
        now=1_000 + 125 * 3600,
    )

    assert ready.ready is True
    row = ready.streams[0]
    assert row["reconnects"] == 1
    assert row["lifetime_reconnects"] == 1_070
    assert row["reconnects_per_hour"] == 0.04
    assert row["order_events"] == 1
    assert row["lifetime_order_events"] == 3
    assert row["age_hours"] == 25
    assert row["lifetime_age_hours"] == 125


def test_observer_does_not_reset_an_existing_soak_epoch(tmp_path):
    path = tmp_path / "stream.json"
    payload = {
        "state": "connected",
        "first_observed_at": 1_000,
        "sessions": 10,
        "reconnects": 20,
        "soak_epochs": soak_epoch(2_000, sessions=9, reconnects=19),
    }
    path.write_text(json.dumps(payload))

    observer = BinanceUserDataObserver(
        api_key="key",
        api_secret="secret",
        rest_base_url="https://api.binance.com",
        mailbox=OrderEventMailbox(),
        logger=lambda message: None,
        state_path=path,
        clock=lambda: 3_000,
    )

    state = observer.state()
    assert len(state["soak_epochs"]) == 1
    assert state["soak_epochs"][0]["started_at"] == 2_000
    assert state["soak_epochs"][0]["baseline"]["reconnects"] == 19


def test_observer_appends_reviewed_epoch_and_preserves_previous_evidence(
    tmp_path,
):
    path = tmp_path / "stream.json"
    previous_v1 = {
        "id": "transport-stability-2026-08-v1",
        "started_at": 1_000,
        "baseline": {name: 0 for name in PERSISTED_COUNTERS},
    }
    previous_v2_baseline = {name: 0 for name in PERSISTED_COUNTERS}
    previous_v2_baseline.update({"sessions": 3, "reconnects": 2_000})
    previous_v2 = {
        "id": "transport-stability-2026-08-v2",
        "started_at": 1_500,
        "baseline": previous_v2_baseline,
    }
    previous_v3_baseline = {name: 0 for name in PERSISTED_COUNTERS}
    previous_v3_baseline.update({"sessions": 4, "reconnects": 2_100})
    previous_v3 = {
        "id": "transport-stability-2026-08-v3",
        "started_at": 1_750,
        "baseline": previous_v3_baseline,
    }
    previous_v4 = {
        "id": "transport-stability-2026-08-v4",
        "started_at": 1_900,
        "baseline": dict(previous_v3_baseline),
    }
    path.write_text(json.dumps({
        "state": "connected",
        "first_observed_at": 900,
        "sessions": 5,
        "reconnects": 2_210,
        "order_events": 2,
        "rest_reconciliations": 544,
        "event_woken_rest_reconciliations": 2,
        "soak_epochs": [previous_v1, previous_v2, previous_v3, previous_v4],
    }))

    observer = BinanceUserDataObserver(
        api_key="key",
        api_secret="secret",
        rest_base_url="https://api.binance.com",
        mailbox=OrderEventMailbox(),
        logger=lambda message: None,
        state_path=path,
        clock=lambda: 2_000,
    )

    epochs = observer.state()["soak_epochs"]
    assert [row["id"] for row in epochs] == [
        "transport-stability-2026-08-v1",
        "transport-stability-2026-08-v2",
        "transport-stability-2026-08-v3",
        "transport-stability-2026-08-v4",
        CURRENT_USER_STREAM_SOAK_EPOCH_ID,
    ]
    assert epochs[0] == previous_v1
    assert epochs[1] == previous_v2
    assert epochs[2] == previous_v3
    assert epochs[3] == previous_v4
    assert epochs[4]["started_at"] == 2_000
    assert epochs[4]["baseline"]["reconnects"] == 2_210
    assert epochs[4]["baseline"]["sessions"] == 5
    assert epochs[4]["baseline"]["order_events"] == 2
    assert epochs[4]["baseline"]["rest_reconciliations"] == 544
    assert epochs[4]["baseline"]["event_woken_rest_reconciliations"] == 2


def test_observer_refuses_to_delete_epoch_history_at_growth_limit(tmp_path):
    path = tmp_path / "stream.json"
    epochs = []
    for index in range(user_stream_module.MAX_USER_STREAM_SOAK_EPOCHS):
        epochs.append({
            "id": f"historical-{index}",
            "started_at": 1_000 + index,
            "baseline": {name: 0 for name in PERSISTED_COUNTERS},
        })
    path.write_text(json.dumps({
        "state": "connected",
        "first_observed_at": 1_000,
        "soak_epochs": epochs,
    }))

    observer = BinanceUserDataObserver(
        api_key="key",
        api_secret="secret",
        rest_base_url="https://api.binance.com",
        mailbox=OrderEventMailbox(),
        logger=lambda message: None,
        state_path=path,
        clock=lambda: 2_000,
    )

    state = observer.state()
    assert len(state["soak_epochs"]) == user_stream_module.MAX_USER_STREAM_SOAK_EPOCHS
    assert state["soak_epochs"] == epochs
    assert state["soak_epoch_error"] is not None


def test_user_stream_soak_fails_closed_for_damaged_epoch(tmp_path):
    path = tmp_path / "stream.json"
    path.write_text(json.dumps({
        "state": "connected",
        "first_observed_at": 1_000,
        "sessions": 1,
        "reconnects": 1,
        "soak_epoch_error": "invalid persisted soak epoch evidence",
        "soak_epochs": [],
    }))

    blocked = audit_user_stream_soak([path], now=2_000)

    assert blocked.ready is False
    assert "unreadable snapshot" in " ".join(blocked.reasons)


def test_user_stream_soak_rejects_non_finite_reconnect_limit():
    blocked = audit_user_stream_soak(
        [],
        maximum_transport_failure_reconnects_per_hour=float("nan"),
    )

    assert blocked.ready is False
    assert "finite and non-negative" in " ".join(blocked.reasons)


def test_user_stream_persists_authoritative_rest_reconciliation_evidence(
    tmp_path,
):
    path = tmp_path / "stream.json"
    observer = BinanceUserDataObserver(
        api_key="key",
        api_secret="secret",
        rest_base_url="https://api.binance.com",
        mailbox=OrderEventMailbox(),
        logger=lambda message: None,
        state_path=path,
    )
    observer.record_rest_reconciliation(event_woken=False)
    observer.record_rest_reconciliation(event_woken=True)

    payload = json.loads(path.read_text())
    assert payload["rest_reconciliations"] == 2
    assert payload["event_woken_rest_reconciliations"] == 1
    assert payload["current_soak_epoch_id"] == CURRENT_USER_STREAM_SOAK_EPOCH_ID
    assert len(payload["soak_epochs"]) == 1
    assert "api_key" not in payload


def test_out_of_order_event_only_wakes_authoritative_rest_reconciliation(tmp_path):
    connection = FakeConnection([
        {"status": 200, "result": {"subscriptionId": 0}},
        execution_report(E=1_700_000_000_020, i=123),
        execution_report(E=1_700_000_000_010, i=124, t=457),
        {"event": {"e": "eventStreamTerminated", "E": 1}},
    ])
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

    events = mailbox.consume_for([123, 124])
    assert len(events) == 2
    assert reconciliation_due(0, 5, events) is True
    state = observer.state()
    assert state["out_of_order_events"] == 1
    assert state["last_exchange_event_time_ms"] == 1_700_000_000_020


def test_observer_reconnects_after_transport_failure_without_disabling_rest(tmp_path):
    attempts = []
    mailbox = OrderEventMailbox()
    observer = None

    def connect(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise WebSocketException("temporary disconnect")
        assert observer is not None
        observer._stop.set()
        return FakeConnection([
            {"status": 200, "result": {"subscriptionId": 0}},
        ])

    observer = BinanceUserDataObserver(
        api_key="key",
        api_secret="secret",
        rest_base_url="https://api.binance.com",
        mailbox=mailbox,
        logger=lambda message: None,
        state_path=tmp_path / "stream.json",
        connect=connect,
    )
    observer._stop.wait = lambda delay: False

    observer._run()

    assert len(attempts) == 2
    assert observer.state()["reconnects"] == 1
    assert observer.state()["connection_attempts"] == 2
    assert reconciliation_due(5, 5, []) is True


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
