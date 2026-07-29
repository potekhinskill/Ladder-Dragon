"""Worker lifecycle and non-buying event-loop regressions."""

from pathlib import Path
from types import SimpleNamespace

from ladder_dragon.execution.worker.event_loop import (
    WorkerLoopContext,
    run_event_loop,
)
from ladder_dragon.execution.worker.lifecycle import (
    WorkerResources,
    WorkerRuntimeState,
)


def test_worker_cleanup_releases_every_resource_after_one_failure():
    calls = []
    messages = []

    class BrokenTransport:
        @staticmethod
        def close():
            calls.append("transport")
            raise OSError("offline")

    class Observer:
        def __init__(self, name):
            self.name = name

        def stop(self):
            calls.append(self.name)

    class Lock:
        @staticmethod
        def release():
            calls.append("lock")

    state = WorkerRuntimeState(
        {
            "_WS_TRADING_TRANSPORT": BrokenTransport(),
            "dbg": messages.append,
        }
    )
    resources = WorkerResources(
        state=state,
        lock=Lock(),
        market_observer=Observer("market"),
        user_stream_observer=Observer("user-stream"),
    )

    resources.close()

    assert calls == ["transport", "market", "user-stream", "lock"]
    assert messages == [
        "[WORKER-CLEANUP] websocket trading transport failed=OSError"
    ]


def test_event_loop_reads_live_run_state_and_never_requires_buy_service():
    observed_run = []
    synced = []
    namespace = {
        "RUN": True,
        "requests": SimpleNamespace(RequestException=RuntimeError),
        "sqlite3": SimpleNamespace(Error=RuntimeError),
        "sync_account_trades": (
            lambda symbol, runtime: synced.append((symbol, runtime))
        ),
    }
    state = WorkerRuntimeState(namespace)

    def trading_wakeups(_duration, *, running, wait):
        observed_run.append(running())
        namespace["RUN"] = False
        observed_run.append(running())
        return ()

    namespace["trading_wakeups"] = trading_wakeups
    context = WorkerLoopContext(
        state=state,
        args=SimpleNamespace(loop_minutes=1),
        symbol="SOLUSDT",
        attach_oco=True,
        ladder_prices=[75.0],
        placed_ids=[],
        panic_active=False,
        panic_sell_floor_pct=None,
        breakeven=SimpleNamespace(),
        breakeven_state=object(),
        user_stream_mailbox=object(),
        user_stream_observer=None,
        started_at=0.0,
        protection_state="not_checked",
    )

    run_event_loop(context)

    assert observed_run == [True, False]
    assert synced == [("SOLUSDT", namespace)]
    event_loop_source = Path(
        "ladder_dragon/execution/worker/event_loop.py"
    ).read_text(encoding="utf-8")
    assert "service_place_buys" not in event_loop_source
    assert "place_limit_order" not in event_loop_source
    assert "place_otoco_buy" not in event_loop_source


def test_stream_fill_is_reconciled_before_latency_persistence():
    source = Path(
        "ladder_dragon/execution/worker/event_loop.py"
    ).read_text(encoding="utf-8")
    stream_branch = source.split("if stream_events:", 1)[1]

    assert stream_branch.index("_reconcile_tracked_buys(") < (
        stream_branch.index("_record_stream_events(")
    )
