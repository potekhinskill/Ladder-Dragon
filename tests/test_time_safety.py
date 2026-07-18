import pytest

from ladder_dragon.execution.time_safety import assess_exchange_clock


def test_clock_check_accounts_for_network_uncertainty():
    check = assess_exchange_clock(
        server_time_ms=11_500,
        request_started_ms=10_000,
        response_finished_ms=12_400,
        max_offset_ms=1000,
        max_round_trip_ms=5000,
    )
    assert check.offset_ms == 300
    assert check.guaranteed_offset_ms == 0
    assert check.safe


def test_clock_check_rejects_high_rtt_and_real_offset():
    slow = assess_exchange_clock(
        server_time_ms=10_000,
        request_started_ms=10_000,
        response_finished_ms=16_000,
        max_round_trip_ms=5000,
    )
    assert not slow.safe
    with pytest.raises(RuntimeError, match="RTT"):
        slow.require_safe()

    skewed = assess_exchange_clock(
        server_time_ms=14_000,
        request_started_ms=10_000,
        response_finished_ms=10_200,
        max_offset_ms=1000,
    )
    assert not skewed.safe
    with pytest.raises(RuntimeError, match="clock offset"):
        skewed.require_safe()
