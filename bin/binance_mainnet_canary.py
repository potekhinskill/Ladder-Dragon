#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve the separately confirmed Mainnet canary CLI.

"""Separately confirmed Mainnet canary command."""

from ladder_dragon.verification.live.mainnet_canary import main


if __name__ == "__main__":
    raise SystemExit(main())
