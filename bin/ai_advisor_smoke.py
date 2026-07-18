#!/usr/bin/env python3
# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Purpose: exercise advisory decisions without placing orders.
"""English documentation."""

from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv
import requests

from ladder_dragon.ai.ai_advisor import (
    AIAdvisor,
    AdvisorConfig,
    MarketContext,
    limit_cap_by_recommendation,
)


SCENARIOS = (
    MarketContext(
        symbol="UPTREND",
        price=100.0,
        atr_pct=0.009,
        deterministic_mode="UP",
        candidate_mode="UP",
        ema_gap_pct=0.018,
        ema_slope=0.0012,
        adx=34.0,
        ladder_low_pct=-0.5,
        ladder_down_pct=-20.0,
        ladder_up_pct=20.0,
        target_buys=4,
        risk_safe_cap_usdt=40.0,
    ),
    MarketContext(
        symbol="DOWNTREND",
        price=100.0,
        atr_pct=0.018,
        deterministic_mode="DOWN",
        candidate_mode="DOWN",
        ema_gap_pct=-0.022,
        ema_slope=-0.0015,
        adx=38.0,
        ladder_low_pct=-0.5,
        ladder_down_pct=-20.0,
        ladder_up_pct=20.0,
        target_buys=4,
        risk_safe_cap_usdt=40.0,
    ),
    MarketContext(
        symbol="SIDEWAYS",
        price=100.0,
        atr_pct=0.004,
        deterministic_mode="FLAT",
        candidate_mode="FLAT",
        ema_gap_pct=0.0001,
        ema_slope=0.00001,
        adx=9.0,
        ladder_low_pct=-0.5,
        ladder_down_pct=-20.0,
        ladder_up_pct=20.0,
        target_buys=4,
        risk_safe_cap_usdt=40.0,
    ),
    MarketContext(
        symbol="SHOCK",
        price=100.0,
        atr_pct=0.075,
        deterministic_mode="FLAT",
        candidate_mode="DOWN",
        ema_gap_pct=-0.035,
        ema_slope=-0.0035,
        adx=49.0,
        ladder_low_pct=-0.5,
        ladder_down_pct=-20.0,
        ladder_up_pct=20.0,
        target_buys=4,
        risk_safe_cap_usdt=40.0,
        trade_count_30d=42,
        sell_count_30d=18,
        net_realized_pnl_30d=-12.4,
        win_rate_30d=0.39,
        avg_win_usdt_30d=2.1,
        avg_loss_usdt_30d=-3.4,
        consecutive_losses=4,
        fees_usdt_30d=5.2,
        turnover_usdt_30d=1800,
        position_pnl_pct=-0.06,
        return_15m=-0.028,
        return_1h=-0.051,
        return_4h=-0.074,
        return_24h=-0.11,
        volume_ratio_1h=3.2,
        spread_bps=18,
        orderbook_imbalance_top5=-0.42,
        orderbook_imbalance_top20=-0.31,
        open_buy_count=3,
        open_sell_count=1,
        open_buy_exposure_usdt=30,
        portfolio_cap_used_pct=0.8,
        free_reserve_ratio=1.05,
        ai_samples_15m=45,
        ai_accuracy_15m=0.51,
        ai_samples_1h=38,
        ai_accuracy_1h=0.47,
        ai_samples_4h=31,
        ai_accuracy_4h=0.45,
    ),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke-English AI-English English Binance English English"
    )
    parser.add_argument(
        "--provider",
        choices=("deepseek", "openai", "compatible"),
        default=os.getenv("AI_PROVIDER", "deepseek"),
    )
    parser.add_argument("--model", default=os.getenv("AI_MODEL", ""))
    parser.add_argument("--base-url", default=os.getenv("AI_BASE_URL", ""))
    parser.add_argument("--timeout-sec", type=float, default=15.0)
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=float(os.getenv("AI_MIN_CONFIDENCE", "0.65")),
    )
    return parser


def main() -> int:
    load_dotenv(override=False)
    args = build_parser().parse_args()
    defaults = {
        "deepseek": (
            "https://api.deepseek.com",
            "deepseek-v4-flash",
            "DEEPSEEK_API_KEY",
        ),
        "openai": (
            "https://api.openai.com/v1",
            "gpt-5-mini",
            "OPENAI_API_KEY",
        ),
        "compatible": (args.base_url, args.model, "AI_API_KEY"),
    }
    default_url, default_model, key_name = defaults[args.provider]
    advisor = AIAdvisor(
        AdvisorConfig(
            enabled=True,
            provider=args.provider,
            model=args.model or default_model,
            base_url=(args.base_url or default_url).rstrip("/"),
            api_key=os.getenv(key_name, ""),
            timeout_sec=args.timeout_sec,
            cache_sec=0,
            min_confidence=0.0,
            usage_log_path=os.getenv(
                "AI_USAGE_LOG", ".runtime/ai_usage.ndjson"
            ),
            usage_log_max_bytes=int(
                os.getenv("AI_USAGE_LOG_MAX_BYTES", "5242880")
            ),
        ),
        session=requests.Session(),
        logger=print,
    )

    failures = 0
    eligible = 0
    for scenario in SCENARIOS:
        recommendation = advisor.recommend(scenario)
        if recommendation is None:
            failures += 1
            print(f"[FAIL] {scenario.symbol}: no valid recommendation")
            continue
        applied_cap = limit_cap_by_recommendation(
            scenario.risk_safe_cap_usdt,
            recommendation.cap_scale,
        )
        cap_safe = applied_cap <= scenario.risk_safe_cap_usdt
        would_apply = recommendation.confidence >= args.min_confidence
        eligible += int(would_apply)
        if not cap_safe:
            failures += 1
        print(
            f"[PASS] {scenario.symbol}: mode={recommendation.mode} "
            f"width={recommendation.ladder_width_scale:.2f} "
            f"cap_scale={recommendation.cap_scale:.2f} "
            f"confidence={recommendation.confidence:.2f} "
            f"applied_cap={applied_cap:.2f}/"
            f"{scenario.risk_safe_cap_usdt:.2f} cap_safe={cap_safe} "
            f"would_apply={would_apply}"
        )

    print(
        f"[SUMMARY] provider={args.provider} scenarios={len(SCENARIOS)} "
        f"passed={len(SCENARIOS) - failures} failed={failures} "
        f"would_apply={eligible} min_confidence={args.min_confidence:.2f} "
        "binance_calls=0 orders=0"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
