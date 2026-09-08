# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: bound public IP observations before consensus validation.
"""Read one public IP source without retaining its response or endpoint."""

import time

from ladder_dragon.execution.market_http_body import MarketResponseError, read_body


def read_public_ip(get, endpoint):
    """Bound body bytes and elapsed reads; socket timeouts bound blocked reads."""
    deadline = time.monotonic() + 5
    with get(endpoint, timeout=5, stream=True, allow_redirects=False) as response:
        if response.status_code != 200:
            raise MarketResponseError("public IP source unavailable")
        return read_body(response, deadline=deadline, max_bytes=4096).decode("ascii")
