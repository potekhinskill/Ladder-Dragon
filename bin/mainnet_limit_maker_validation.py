#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: expose the separately confirmed Mainnet LIMIT_MAKER validation drill.
"""Run the one-shot Mainnet LIMIT_MAKER validation drill."""

from ladder_dragon.verification.live.mainnet_limit_maker_validation import main


if __name__ == "__main__":
    raise SystemExit(main())
