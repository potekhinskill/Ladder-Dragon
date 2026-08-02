"""User Stream reconnect classification regressions."""

from ladder_dragon.execution.user_stream import (
    BinanceUserDataObserver,
    OrderEventMailbox,
)


def _observer(tmp_path, failure):
    observer = BinanceUserDataObserver(
        api_key="key",
        api_secret="secret",
        rest_base_url="https://api.binance.com",
        mailbox=OrderEventMailbox(),
        logger=lambda message: None,
        state_path=tmp_path / "stream.json",
    )
    calls = {"count": 0}

    def observe():
        calls["count"] += 1
        if calls["count"] == 1:
            raise failure
        observer._stop.set()

    observer._observe_connection = observe
    observer._stop.wait = lambda delay: False
    return observer


def test_idle_refresh_is_not_a_transport_failure(tmp_path):
    observer = _observer(tmp_path, TimeoutError("silent session"))

    observer._run()

    state = observer.state()
    assert state["reconnects"] == 1
    assert state["idle_reconnects"] == 1
    assert state["transport_failure_reconnects"] == 0
    assert state["last_error"] is None


def test_transport_failure_is_counted_separately(tmp_path):
    observer = _observer(tmp_path, RuntimeError("transport closed"))

    observer._run()

    state = observer.state()
    assert state["reconnects"] == 1
    assert state["idle_reconnects"] == 0
    assert state["transport_failure_reconnects"] == 1
    assert state["last_error"] == "RuntimeError"


def test_controlled_reconnect_is_not_a_transport_failure(tmp_path):
    observer = _observer(tmp_path, RuntimeError("controlled close"))
    observer._controlled_reconnect_pending.set()

    observer._run()

    state = observer.state()
    assert state["reconnects"] == 1
    assert state["transport_failure_reconnects"] == 0
    assert state["last_error"] is None
