#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: expose the bounded Mainnet STOP_LOSS_LIMIT validation drill.
"""CLI compatibility wrapper for STOP_LOSS_LIMIT validation."""

from ladder_dragon.verification.live.mainnet_stop_limit_validation import main


if __name__ == "__main__":
    raise SystemExit(main())
