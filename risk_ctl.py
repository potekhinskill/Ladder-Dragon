#!/usr/bin/env python3
"""Manual operator control for the persistent circuit breaker."""

import argparse
import json

from risk_manager import RiskLimits, RiskManager


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect or manually reset the trading circuit breaker")
    parser.add_argument("command", choices=("status", "reset"))
    parser.add_argument("--force", action="store_true", help="reset before cooldown expires after manual review")
    args = parser.parse_args()

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
