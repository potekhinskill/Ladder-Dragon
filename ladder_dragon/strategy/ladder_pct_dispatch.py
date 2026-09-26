# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve percentage-ladder notional checks and worker dispatch.

import os
import sys
import subprocess
from decimal import Decimal
from ladder_dragon.strategy.ladder_pct_math import fmt_decimal
from ladder_dragon.strategy.ladder_pct_market import die


def check_min_notional(args, flt):
    eff_order_usdt = None
    if args.min_order_usdt and args.min_order_usdt > 0:
        eff_order_usdt = Decimal(str(args.min_order_usdt))
    else:
        cap_env = os.getenv("BOT_CAP_PER_ORDER")
        if cap_env:
            try: eff_order_usdt = Decimal(str(cap_env))
            except: eff_order_usdt = None

    if eff_order_usdt is not None and flt["minNotional"] is not None and flt["minNotional"] > 0:
        min_not = flt["minNotional"]
        if eff_order_usdt < min_not:
            msg = (f"effective order USDT ({fmt_decimal(eff_order_usdt)}) is below minNotional "
                   f"({fmt_decimal(min_not)}).")
            if args.strict_minnotional:
                die(msg + " Exiting because --strict-minnotional is enabled.", code=3)
            else:
                print("[WARN]", msg, "Consider increasing CAP.")


def launch_executor(args, symbol, levels_str):
    cmd = ["python3", "-u", args.base_script, "--symbol", symbol, "--ladder-prices", levels_str]
    if args.live: cmd.append("--live")
    if args.only_new_fills: cmd.append("--only-new-fills")
    cmd += ["--max-oco-per-symbol", str(args.max_oco_per_symbol)]
    cmd += ["--tp1", str(args.tp1), "--tp2", str(args.tp2), "--sl", str(args.sl)]
    cmd += ["--status-interval", str(args.status_interval), "--loop-minutes", str(args.loop_minutes)]

    print("[LAUNCH]", " ".join(cmd))
    try:
        res = subprocess.run(cmd, check=False)
        sys.exit(res.returncode)
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Stopped by user."); sys.exit(130)
