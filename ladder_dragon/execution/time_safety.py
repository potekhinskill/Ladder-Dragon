# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Purpose: implement the time safety component of the execution layer.
"""Network-aware exchange clock validation for LIVE preflight."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClockCheck:
    offset_ms: int
    round_trip_ms: int
    guaranteed_offset_ms: int
    safe: bool
    reason: str = ""

    def require_safe(self) -> None:
        if not self.safe:
            raise RuntimeError(self.reason)


def assess_exchange_clock(
    *,
    server_time_ms: int,
    request_started_ms: int,
    response_finished_ms: int,
    max_offset_ms: int = 1000,
    max_round_trip_ms: int = 5000,
) -> ClockCheck:
    if response_finished_ms < request_started_ms:
        raise ValueError("response time precedes request time")
    if max_offset_ms < 0 or max_round_trip_ms <= 0:
        raise ValueError("clock safety limits are invalid")
    round_trip = response_finished_ms - request_started_ms
    midpoint = (request_started_ms + response_finished_ms) // 2
    offset = int(server_time_ms) - midpoint
    # The server timestamp can have been captured anywhere inside the RTT window.
    # Only the portion outside half the RTT is a guaranteed local-clock error.
    guaranteed = max(0, abs(offset) - (round_trip // 2))
    if round_trip > max_round_trip_ms:
        reason = f"Binance time RTT {round_trip} ms exceeds {max_round_trip_ms} ms"
        return ClockCheck(offset, round_trip, guaranteed, False, reason)
    if guaranteed > max_offset_ms:
        reason = (
            f"Binance guaranteed clock offset {guaranteed} ms exceeds "
            f"{max_offset_ms} ms (estimated={offset} ms, RTT={round_trip} ms)"
        )
        return ClockCheck(offset, round_trip, guaranteed, False, reason)
    return ClockCheck(offset, round_trip, guaranteed, True)
