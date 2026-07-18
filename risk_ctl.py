#!/usr/bin/env python3
# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Назначение файла и опасные границы логики должны оставаться понятными при сопровождении.
"""Manual operator control for the persistent circuit breaker."""

import argparse
import json

from dotenv import load_dotenv

from ladder_dragon.risk.risk_manager import RiskLimits, RiskManager
from ladder_dragon.execution.venue_config import apply_testnet_paths


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Inspect or manually reset the trading circuit breaker")
    parser.add_argument("command", choices=("status", "reset"))
    parser.add_argument("--force", action="store_true", help="reset before cooldown expires after manual review")
    parser.add_argument("--testnet", action="store_true", help="inspect/reset isolated Testnet circuit state")
    args = parser.parse_args()

    if args.testnet:
        apply_testnet_paths()
    limits = RiskLimits.from_env()
    manager = RiskManager(limits)
    if args.command == "status":
        payload = {
            "halt_file": str(limits.halt_file),
            "halted": limits.halt_file.exists(),
            "state_file": str(limits.state_file),
        }
        if limits.halt_file.exists():
            payload["halt"] = json.loads(limits.halt_file.read_text(encoding="utf-8"))
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    manager.reset(force=args.force)
    print("Circuit breaker reset. Review account state before restarting LIVE mode.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
