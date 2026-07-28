#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve the separately confirmed Mainnet canary CLI.

"""Compatibility CLI for Mainnet canary verification."""

import sys

from ladder_dragon.verification.live import mainnet_canary as _runtime


if __name__ == "__main__":
    raise SystemExit(_runtime.main())

sys.modules[__name__] = _runtime
