#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: migrate one frozen volatility policy without changing its cohort.
"""Migrate an exact schema-2 volatility policy to the bound window contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ladder_dragon.strategy.volatility_policy import (
    migrate_legacy_volatility_policy,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--report-directory", required=True, type=Path)
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()
    if args.confirm != "MIGRATE-FROZEN-VOLATILITY-POLICY":
        parser.error(
            "--confirm must be MIGRATE-FROZEN-VOLATILITY-POLICY"
        )
    payload = migrate_legacy_volatility_policy(
        args.policy, args.report_directory
    )
    print(json.dumps({
        "status": "PASS",
        "schema_version": payload["schema_version"],
        "policy_sha256": payload["policy_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
