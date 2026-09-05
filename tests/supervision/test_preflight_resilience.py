"""Fail-closed supervisor preflight and recovery retry regressions."""

from decimal import Decimal
import inspect
import threading
from types import SimpleNamespace

import pytest

from ladder_dragon.supervision import preflight_resilience
from ladder_dragon.supervision import runtime as ai_supervisor


def test_transient_retry_bounds_are_bounded_and_fail_safe():
    configured = {
        "BINANCE_PREFLIGHT_BACKOFF_INITIAL_SEC": "2",
        "BINANCE_PREFLIGHT_BACKOFF_MAX_SEC": "99999",
    }
    assert preflight_resilience.retry_bounds(
        lambda key, default: configured.get(key, default)
    ) == (5, 3600)
    assert preflight_resilience.retry_bounds(
        lambda _key, _default: "invalid"
    ) == (30, 300)


def test_supervisor_transient_preflight_failure_stays_in_process(
    tmp_path, monkeypatch
):
    from ladder_dragon.execution.auth_resilience import AuthResilienceState

    attempts = []
    waits = []
    published = []
    messages = []
    state = AuthResilienceState()

    def preflight(*_args):
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError("Binance time RTT 5660 ms exceeds 5000 ms")

    monkeypatch.setattr(
        ai_supervisor, "_read_auth_resilience_state", lambda: state
    )
    monkeypatch.setattr(
        ai_supervisor, "_save_auth_resilience_state", lambda _state: None
    )
    monkeypatch.setattr(
        ai_supervisor, "_observe_public_ip", lambda current: (current, None)
    )
    monkeypatch.setattr(ai_supervisor, "_preflight_live", preflight)
    monkeypatch.setattr(
        ai_supervisor,
        "_pre_running_recovery_gate",
        lambda *_args: {"checked": 0, "blocked": False},
    )
    monkeypatch.setattr(
        ai_supervisor,
        "_wait_for_resilience_retry",
        lambda kind, delay, **kwargs: waits.append((kind, delay, kwargs)),
    )
    monkeypatch.setattr(
        ai_supervisor,
        "_publish_ai_runtime_status",
        lambda **updates: published.append(updates),
    )
    monkeypatch.setattr(ai_supervisor, "log", messages.append)
    monkeypatch.setattr(ai_supervisor, "_INFO_LOG_LAST_EMITTED", {})
    args = SimpleNamespace(
        live=True,
        binance_auth_backoff_initial_sec=60,
        binance_auth_backoff_max_sec=120,
    )
    limits = SimpleNamespace(halt_file=tmp_path / "halt.json")

    ai_supervisor._preflight_with_auth_backoff(
        args, ["SOLUSDT"], limits
    )

    assert len(attempts) == 2
    assert set(ai_supervisor._PREFLIGHT_STARTUP_PHASES) >= {
        "auth_backoff_state",
        "ip_guard",
        "live_preflight",
    }
    assert waits == [
        ("PREFLIGHT", 30, {"attempt": 1, "persistent_halt": False})
    ]
    assert any("PREFLIGHT-BACKOFF" in message for message in messages)
    recovered = [
        row for row in published
        if row.get("preflight_backoff", {}).get("active") is False
    ][-1]
    assert recovered["preflight_backoff"]["attempt"] == 1
    assert published[-1]["recovery"]["blocked"] is False


def test_failed_live_preflight_publishes_elapsed_and_success_false(
    tmp_path, monkeypatch
):
    from ladder_dragon.execution.auth_resilience import AuthResilienceState
    from ladder_dragon.supervision.startup_timing import StartupTimeline

    published = []
    monkeypatch.setattr(
        ai_supervisor, "_read_auth_resilience_state", AuthResilienceState
    )
    monkeypatch.setattr(
        ai_supervisor, "_observe_public_ip", lambda state: (state, None)
    )
    monkeypatch.setattr(
        ai_supervisor, "_preflight_live",
        lambda *_args: (_ for _ in ()).throw(ValueError("invalid local config")),
    )
    monkeypatch.setattr(
        ai_supervisor, "_STARTUP_TIMELINE", StartupTimeline()
    )
    monkeypatch.setattr(
        ai_supervisor, "_publish_ai_runtime_status",
        lambda **updates: published.append(updates),
    )
    args = SimpleNamespace(live=True)
    limits = SimpleNamespace(halt_file=tmp_path / "halt.json")

    with pytest.raises(ValueError, match="invalid local config"):
        ai_supervisor._preflight_with_auth_backoff(args, ["SOLUSDT"], limits)

    timing = next(row["startup_timing"] for row in published if "startup_timing" in row)
    assert timing["preflight_phases"]["live_preflight"]["success"] is False
    assert timing["preflight_phases"]["live_preflight"]["elapsed_ms"] >= 0


def test_ip_guard_overlaps_local_preflight_before_remote_reads(
    tmp_path, monkeypatch
):
    from ladder_dragon.execution.auth_resilience import AuthResilienceState

    local_check_started = threading.Event()
    guard_finished = threading.Event()

    def observe(state):
        assert local_check_started.wait(timeout=2)
        guard_finished.set()
        return state, None

    def preflight(_args, _symbols, _limits, before_remote):
        local_check_started.set()
        before_remote()
        assert guard_finished.is_set()

    monkeypatch.setattr(
        ai_supervisor, "_read_auth_resilience_state", AuthResilienceState
    )
    monkeypatch.setattr(ai_supervisor, "_observe_public_ip", observe)
    monkeypatch.setattr(ai_supervisor, "_preflight_live", preflight)
    monkeypatch.setattr(
        ai_supervisor, "_save_auth_resilience_state", lambda _state: None
    )
    monkeypatch.setattr(
        ai_supervisor, "_pre_running_recovery_gate",
        lambda *_args: {"checked": 0, "blocked": False},
    )
    monkeypatch.setattr(
        ai_supervisor, "_publish_ai_runtime_status", lambda **_updates: None
    )
    args = SimpleNamespace(live=True)
    limits = SimpleNamespace(halt_file=tmp_path / "halt.json")

    ai_supervisor._preflight_with_auth_backoff(args, ["SOLUSDT"], limits)

    assert ai_supervisor._PREFLIGHT_STARTUP_PHASES["ip_guard"]["overlapped"] is True


def test_signed_account_read_follows_joined_clock_and_filters(
    tmp_path, monkeypatch
):
    events = []

    class Connection:
        def execute(self, _query):
            return self

        def fetchall(self):
            return []

        def close(self):
            return None

    def public_checks(*_args, **_kwargs):
        events.append("public_complete")
        return {
            "SOLUSDT": {
                "tickSize": 1,
                "stepSize": 1,
                "minQty": 1,
                "minNotional": 1,
            }
        }

    def signed_get(_path):
        assert events == ["ip_complete", "public_complete"]
        events.append("account")
        return {"canTrade": True}

    monkeypatch.setenv("BOT_STATS_DB", str(tmp_path / "stats.sqlite3"))
    monkeypatch.setattr(ai_supervisor.TM, "API_KEY", "configured")
    monkeypatch.setattr(ai_supervisor.TM, "API_SECRET", "configured")
    monkeypatch.setattr(ai_supervisor.tools_stats, "init_db", lambda _path: Connection())
    monkeypatch.setattr(ai_supervisor, "read_clock_and_filters", public_checks)
    monkeypatch.setattr(ai_supervisor.TM, "_signed_get", signed_get)
    args = SimpleNamespace(
        live=True, testnet=False, cap_ceil_usdt="6", target_buy_per_symbol=1
    )
    limits = SimpleNamespace(
        validate=lambda: None,
        portfolio_cap_usdt=Decimal("100"),
        daily_buy_cap_usdt=Decimal("100"),
        correlated_cap_usdt=Decimal("100"),
        reserve_usdt=Decimal("10"),
        halt_file=tmp_path / "halt.json",
    )

    ai_supervisor._preflight_live(
        args, ["SOLUSDT"], limits, lambda: events.append("ip_complete")
    )

    assert events == ["ip_complete", "public_complete", "account"]


def test_recovery_blocked_message_is_rate_limited(
    tmp_path, monkeypatch
):
    from ladder_dragon.execution.auth_resilience import AuthResilienceState

    recovery_attempts = []
    shadow_attempts = []
    messages = []

    def recovery(*_args):
        recovery_attempts.append(True)
        if len(recovery_attempts) <= 2:
            raise RuntimeError(
                "reconciled BUY has execution without verified protection"
            )
        return {"checked": 1, "blocked": False}

    monkeypatch.setattr(
        ai_supervisor,
        "_read_auth_resilience_state",
        lambda: AuthResilienceState(),
    )
    monkeypatch.setattr(
        ai_supervisor, "_save_auth_resilience_state", lambda _state: None
    )
    monkeypatch.setattr(
        ai_supervisor, "_observe_public_ip", lambda current: (current, None)
    )
    monkeypatch.setattr(ai_supervisor, "_preflight_live", lambda *_args: None)
    monkeypatch.setattr(
        ai_supervisor, "_pre_running_recovery_gate", recovery
    )
    monkeypatch.setattr(
        ai_supervisor,
        "_collect_blocked_shadow",
        lambda symbols, args, *, now_monotonic: shadow_attempts.append(
            (tuple(symbols), args.live, now_monotonic)
        ),
    )
    monkeypatch.setattr(
        ai_supervisor, "_refresh_ai_control", lambda _args: None
    )
    monkeypatch.setattr(ai_supervisor.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(ai_supervisor.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(
        ai_supervisor, "_publish_ai_runtime_status", lambda **_updates: None
    )
    monkeypatch.setattr(ai_supervisor, "log", messages.append)
    monkeypatch.setattr(ai_supervisor, "_INFO_LOG_LAST_EMITTED", {})
    args = SimpleNamespace(
        live=True,
        binance_auth_backoff_initial_sec=60,
        binance_auth_backoff_max_sec=120,
    )
    limits = SimpleNamespace(halt_file=tmp_path / "halt.json")

    ai_supervisor._preflight_with_auth_backoff(
        args, ["SOLUSDT"], limits
    )

    recovery_messages = [
        message for message in messages
        if "[RECOVERY] pre-RUNNING gate blocked" in message
    ]
    assert recovery_messages == [
        "[RECOVERY] pre-RUNNING gate blocked; reason="
        "reconciled BUY has execution without verified protection"
    ]
    assert len(shadow_attempts) == 2
    assert all(
        row[:2] == (("SOLUSDT",), True) for row in shadow_attempts
    )


def test_blocked_shadow_decision_preserves_recovery_status(monkeypatch):
    published = []
    monkeypatch.setattr(
        ai_supervisor,
        "_publish_ai_runtime_status",
        lambda **updates: published.append(updates),
    )

    ai_supervisor._publish_plan_decision_status(
        {"symbol": "SOLUSDT"},
        execution_allowed=False,
        publish=ai_supervisor._publish_ai_runtime_status,
    )
    ai_supervisor._publish_plan_decision_status(
        {"symbol": "SOLUSDT"},
        execution_allowed=True,
        publish=ai_supervisor._publish_ai_runtime_status,
    )

    assert published[0] == {"last_decision": {"symbol": "SOLUSDT"}}
    assert published[1] == {
        "last_decision": {"symbol": "SOLUSDT"},
        "state": "RUNNING",
    }


def test_runtime_arguments_and_singleton_precede_recovery_loop():
    runtime_source = inspect.getsource(ai_supervisor.main)

    normalized_at = runtime_source.index(
        "_normalize_runtime_args(args, symbols)"
    )
    singleton_at = runtime_source.index(
        "_acquire_singleton_lock(LOCK_FILE)"
    )
    preflight_at = runtime_source.index(
        "_preflight_with_auth_backoff(args, symbols, limits)"
    )

    assert normalized_at < preflight_at
    assert singleton_at < preflight_at


def test_recovery_shadow_receives_normalized_planning_arguments():
    args = SimpleNamespace(
        ladder_pct="0.01,0.02,0.03",
        ladder_pct_map="SOLUSDT=0.04,0.05,0.06",
        pos_max_base_map="SOLUSDT:0.126",
        pos_max_usdt_map="SOLUSDT:10",
        child_buy_vwap_premium_map="SOLUSDT:1.003",
        child_buy_vwap_discount_map="SOLUSDT:0.997",
        child_buy_vwap_discount_scale_map="SOLUSDT:0.5",
    )

    ai_supervisor._normalize_runtime_args(args)

    assert args.ladder_pct == (0.01, 0.02, 0.03)
    assert args.ladder_pct_map == {"SOLUSDT": (0.04, 0.05, 0.06)}
    assert args.pos_max_base_map == {"SOLUSDT": Decimal("0.126")}
    assert args.pos_max_usdt_map == {"SOLUSDT": Decimal("10")}
    assert args.child_buy_vwap_premium_map == {"SOLUSDT": 1.003}
    assert args.child_buy_vwap_discount_map == {"SOLUSDT": 0.997}
    assert args.child_buy_vwap_discount_scale_map == {"SOLUSDT": 0.5}


def test_supervisor_auth_backoff_does_not_hide_other_preflight_errors():
    assert preflight_resilience.is_auth_rejection(
        RuntimeError("HTTP 401: {'code': -2015}")
    )
    assert not preflight_resilience.is_auth_rejection(
        RuntimeError("position reconciliation failed")
    )
    assert [
        preflight_resilience.retry_delay(
            attempt, initial_sec=60, max_sec=900
        )
        for attempt in range(1, 7)
    ] == [60, 120, 240, 480, 900, 900]
    delay, retry_at = preflight_resilience.retry_schedule(
        3,
        initial_sec=60,
        max_sec=900,
        now=1_000.0,
    )
    assert (delay, retry_at) == (240, 1_240.0)
    assert preflight_resilience.backoff_active(
        retry_at, now=1_239.0
    )
    assert not preflight_resilience.backoff_active(
        retry_at, now=1_240.0
    )
