#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve the authenticated Testnet smoke CLI.

"""Authenticated Testnet verification command."""

from ladder_dragon.verification.live.testnet_smoke import main


if __name__ == "__main__":
    raise SystemExit(main())
