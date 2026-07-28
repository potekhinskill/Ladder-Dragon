# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: validate worker bootstrap inputs and own the mutable runtime loop.

"""Worker bootstrap and mutable runtime orchestration."""

from __future__ import annotations

from collections.abc import MutableMapping
import re
from typing import Any


class WorkerRuntimeState:
    """Expose live worker module state without snapshotting mutable globals."""

    def __init__(self, namespace: MutableMapping[str, Any]) -> None:
        object.__setattr__(self, "_namespace", namespace)

    def __getattr__(self, name: str) -> Any:
        try:
            return self._namespace[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        self._namespace[name] = value

    def namespace(self) -> MutableMapping[str, Any]:
        """Return the live namespace for services that require late binding."""
        return self._namespace


def normalize_symbol(symbol: str) -> str:
    """Return a Binance symbol or fail before any exchange request."""
    normalized = str(symbol).strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,20}", normalized):
        raise ValueError("symbol must match [A-Z0-9]{5,20}")
    return normalized


def run_worker(state: WorkerRuntimeState) -> None:
    """Run one symbol worker against live runtime dependencies."""
    parser = state.build_executor_parser()
    args = state.validate_executor_args(parser, parser.parse_args())
    state.log(f"[VERSION] {state.product_label('executor')}")
    state.LIVE_MODE = bool(args.live)
    state.WS_TRADING_MODE = args.ws_trading_mode
    if state.LIVE_MODE:
        # Supervisor risk calculation treats target-buy as a hard maximum.
        # Therefore LIVE always checks existing BUY orders.
        args.enforce_target_buys = True

    if state.LIVE_MODE:
        # Repeat preflight even after supervisor validation: a worker can be started
        # independently or long after the original check.
        halt_file = state.Path(
            state.os.getenv(
                "CB_HALT_FILE",
                state.os.path.join(state.bot_run_dir(), "circuit_halt.json"),
            )
        )
        if halt_file.exists():
            parser.error(f"circuit halt exists: {halt_file}; reset through risk_ctl.py")
        stats_db = state.os.getenv("BOT_STATS_DB", "").strip()
        if not stats_db:
            parser.error("BOT_STATS_DB is required for LIVE mode")
        try:
            with state.sqlite3.connect(stats_db, timeout=5) as con:
                con.execute("SELECT 1 FROM trades LIMIT 1").fetchall()
            t0 = int(state.time.time() * 1000)
            server = state._public_get("/api/v3/time")
            t1 = int(state.time.time() * 1000)
            state.assess_exchange_clock(
                server_time_ms=int(server["serverTime"]),
                request_started_ms=t0,
                response_finished_ms=t1,
                max_offset_ms=int(state.os.getenv("RISK_MAX_TIME_OFFSET_MS", "1000")),
                max_round_trip_ms=int(state.os.getenv("RISK_MAX_TIME_RTT_MS", "5000")),
            ).require_safe()
            state.pull_filters(args.symbol.upper())
            account = state._signed_request("GET", "/api/v3/account")
            if account.get("canTrade") is not True:
                raise RuntimeError("Binance account/API key is not allowed to trade")
            state._order_journal()
            # Reconcile every ordinary BUY/SELL intent before any new LIVE
            # action. This closes externally cancelled orders and definitive
            # Binance -2013 absences without manual SQLite edits.
            state.reconcile_nonterminal_orders(args.symbol.upper())
        except (OSError, state.sqlite3.Error, state.requests.RequestException, RuntimeError, KeyError, ValueError) as exc:
            parser.error(f"LIVE preflight failed: {exc}")
    attach_oco = bool(args.attach_oco_on_fill)

    symbol = args.symbol

    # OCO status is no longer hidden behind a question mark: before the first check,
    # explicitly show that protection is not confirmed. This distinguishes a
    # pending BUY from a verified OCO in logs and the dashboard.
    protection_state = "not_checked" if attach_oco else "disabled"

    def status_message(left: int) -> str:
        return (
            f"[status] {symbol} pid={state.os.getpid()} OCO:{protection_state} | "
            f"started:{state.datetime.fromtimestamp(started_at).strftime('%Y-%m-%d %H:%M:%S')} | "
            f"left:{int(left)}s | last: idle"
        )

    # --- per-symbol lock: a second process for the symbol exits immediately ---
    _lock = state.SymbolLock(symbol)
    if not _lock.acquire():
        return

    user_stream_mailbox = state.OrderEventMailbox()
    user_stream_observer: Optional[state.BinanceUserDataObserver] = None
    market_store: state.MarketSnapshotStore | None = None
    market_observer: state.BinanceMarketDataObserver | None = None
    try:
        ladder_prices = state.parse_comma_floats(args.ladder_prices)

        # --- Breakeven: keep OCO linked to the original BUY average price ---
        be_syms = {s.strip().upper() for s in args.breakeven_on_tp1_symbols.split(",") if s.strip()}
        BE_ENABLED = symbol.upper() in be_syms
        fee_pct = max(state.Decimal("0"), state.getenv_decimal("BOT_FEE_PCT", "0.00075"))
        BE_OFFSET = (
            args.breakeven_offset_pct
            if args.breakeven_offset_pct is not None
            else state.Decimal("2") * fee_pct
        )
        BE_CHECK_N = max(1, int(args.breakeven_check_interval))
        breakeven = state.BreakevenRuntime(
            enabled=BE_ENABLED,
            offset_pct=BE_OFFSET,
            check_interval=BE_CHECK_N,
        )
        be_state = state.BreakevenStateStore(state.bot_run_dir, state.dbg)

        if BE_ENABLED:
            state.log(f"[BE] {symbol} enabled | offset={BE_OFFSET:.4%} | check={BE_CHECK_N}s")
        else:
            state.dbg(f"[BE] {symbol} disabled")

        state.install_signal_handlers()
        state.pull_filters(symbol)
        user_stream_enabled = (
            state.LIVE_MODE
            and state.os.getenv("BOT_USER_STREAM_SHADOW", "1").lower()
            in ("1", "true", "yes")
        )
        if user_stream_enabled:
            if not state.API_KEY or not state.API_SECRET:
                state.log(
                    f"[USER-STREAM] {symbol} disabled: credentials unavailable; "
                    "REST polling remains authoritative"
                )
            else:
                user_stream_observer = state.BinanceUserDataObserver(
                    api_key=state.API_KEY,
                    api_secret=state.API_SECRET,
                    rest_base_url=state.BINANCE_API_BASE,
                    mailbox=user_stream_mailbox,
                    logger=state.log,
                    state_path=state.Path(state.bot_run_dir())
                    / f"user_stream_{symbol.upper()}.json",
                    timestamp_ms=state.TM._timestamp_ms,
                    state_persist_interval_sec=state._compat_float(
                        state.os.getenv("BOT_USER_STREAM_STATE_WRITE_SEC", "5")
                    ),
                    idle_timeout_sec=state._compat_float(
                        state.os.getenv("BOT_USER_STREAM_IDLE_TIMEOUT_SEC", "90")
                    ),
                )
                user_stream_observer.start()
        if args.fast_market_mode != "OFF":
            market_store = state.MarketSnapshotStore(symbol)
            market_observer = state.BinanceMarketDataObserver(
                market_store,
                testnet="testnet" in state.BINANCE_API_BASE.lower(),
                logger=state.log,
            )
            market_observer.start()
            state.log(
                f"[FAST-MARKET] {symbol} mode={args.fast_market_mode} "
                f"max_age={args.fast_market_max_age_ms}ms"
            )
        current_price = state.get_price(symbol)

        # Protection deduplication also runs here: direct worker startup must not
        # depend on whether the supervisor normalized the ladder.
        ladder_prices = state.dedup_ladder(symbol, ladder_prices, current_price)

        started_at = state.time.time()
        warmup = state.cleanup_warmup_sec()
        state.log(status_message(int(args.loop_minutes * 60)))

        # BUY size comes from the environment (per-order cap) when supplied by supervisor.
        cap = state._cap_decimal(
            "BOT_CAP_PER_ORDER",
            state.os.getenv("BOT_CAP_PER_ORDER", "50"),
        )

        vwap_ratio: Optional[float] = None
        vwap_value: Optional[float] = None
        need_vwap = (
            args.buy_vwap_premium is not None or
            (args.buy_vwap_discount is not None and state._compat_float(args.buy_vwap_discount) > 0) or
            (args.buy_vwap_discount_scale is not None and state._compat_float(args.buy_vwap_discount_scale) != 1.0)
        )
        if need_vwap:
            try:
                vwap_value = state.get_vwap_cached(
                    symbol,
                    interval=args.buy_vwap_interval or "1m",
                    window=max(5, int(args.buy_vwap_window)),
                    ttl_sec=15,
                )
            except (
                state.requests.RequestException,
                RuntimeError,
                ValueError,
                ArithmeticError,
                OSError,
            ) as e:
                state.dbg(f"[VWAP] {symbol} calc err: {e}")
                vwap_value = None
            if vwap_value and vwap_value > 0:
                vwap_ratio = current_price / vwap_value

        # Average price and panic state jointly control BUY permission and the minimum
        # acceptable protective SELL price.
        safety_buy_block_reason: Optional[str] = None
        try:
            ema20, atr, prev_close = state.get_indicators_cached(symbol, args.panic_interval, ttl_sec=20)
            state._clear_safety_control_failure("panic-indicators", symbol)
            raw_panic_active = state.panic_raw(
                current_price,
                ema20,
                atr,
                prev_close,
                state._compat_float(args.panic_drop_pct),
                state._compat_float(args.panic_k_atr),
            )
        except (
            state.requests.RequestException,
            RuntimeError,
            ValueError,
            ArithmeticError,
            OSError,
        ) as exc:
            ema20 = atr = prev_close = None
            raw_panic_active = True
            state._record_safety_control_failure("panic-indicators", symbol, exc)
            safety_buy_block_reason = "panic-indicators-unavailable"
        try:
            avg_px = state.avg_entry(symbol, cache_ttl=args.avg_cache_ttl, lookback=args.avg_lookback)
        except (
            state.requests.RequestException,
            RuntimeError,
            ValueError,
            ArithmeticError,
            OSError,
            state.sqlite3.Error,
        ):
            avg_px = None
        panic_active, panic_block_reason = state._panic_state_fail_closed(
            "panic-state",
            symbol,
            lambda: state.update_panic_state(
                symbol=symbol,
                now_px=current_price,
                ema20=ema20, atr=atr, prev_close=prev_close,
                avg_entry_px=avg_px,
                panic_drop_pct=state._compat_float(args.panic_drop_pct),
                panic_k_atr=state._compat_float(args.panic_k_atr),
                debounce_checks=int(args.panic_debounce_checks),
                cooldown_sec=int(args.panic_cooldown_sec),
            ),
        )
        if panic_block_reason is not None:
            safety_buy_block_reason = panic_block_reason

        trend_interval = args.buy_trend_interval or args.panic_interval
        if trend_interval == args.panic_interval:
            trend_ema = ema20
        else:
            try:
                trend_ema, _, _ = state.get_indicators_cached(symbol, trend_interval, ttl_sec=20)
            except (
                state.requests.RequestException,
                RuntimeError,
                ValueError,
                ArithmeticError,
                OSError,
            ):
                trend_ema = None

        bear_gap = 0.0
        bear_mode = False
        if trend_ema and trend_ema > 0 and args.buy_trend_ema_gap is not None:
            try:
                gap_thr = max(0.0, state._compat_float(args.buy_trend_ema_gap))
            except (TypeError, ValueError, OverflowError):
                gap_thr = 0.0
            bear_gap = max(0.0, (trend_ema - current_price) / trend_ema)
            bear_mode = (bear_gap > 0.0) and (bear_gap >= gap_thr)
        if bear_mode:
            state.log(f"[BEAR] {symbol} price≈{state.fmt_price_sym(symbol, current_price)} EMA({trend_interval})≈{state.fmt_price_sym(symbol, trend_ema or 0)} gap≈{bear_gap:.4f}")

        if bear_mode and args.bear_buy_shift_pct > 0:
            ladder_prices = state.adjust_buy_ladder(symbol, ladder_prices, current_price, state._compat_float(args.bear_buy_shift_pct))
            ladder_prices = state.dedup_ladder(symbol, ladder_prices, current_price)

        if bear_mode and args.bear_cap_scale is not None:
            scale = state.Decimal(str(state.clamp(state._compat_float(args.bear_cap_scale), 0.0, 5.0)))
            if scale != state.Decimal("1"):
                cap *= scale
                state.log(f"[BEAR] {symbol} cap scale {scale:.3f} → {cap:.2f} USDT")

        if vwap_ratio is not None and args.buy_vwap_discount is not None:
            try:
                discount_thr = state.clamp(state._compat_float(args.buy_vwap_discount), 0.0, 0.5)
            except (TypeError, ValueError, OverflowError):
                discount_thr = 0.0
            if discount_thr > 0 and vwap_ratio <= (1.0 - discount_thr):
                scale = state.Decimal(
                    str(state.clamp(state._compat_float(args.buy_vwap_discount_scale), 0.1, 10.0))
                )
                if scale != state.Decimal("1"):
                    old_cap = cap
                    cap *= scale
                    state.log(
                        f"[VWAP] {symbol} discount ratio={vwap_ratio:.4f} <= 1-{discount_thr:.4f} → cap {old_cap:.2f}→{cap:.2f} x{scale:.2f}"
                    )

        try:
            clamped_cap, cap_limits = state.hard_buy_cap(symbol, cap)
        except ValueError as exc:
            clamped_cap = state.Decimal("0")
            cap_limits = {}
            state.log(f"[CAP-HARD-ERROR] {symbol} {exc}; BUY disabled")
        if clamped_cap != cap:
            rendered = ",".join(
                f"{name}={value}" for name, value in sorted(cap_limits.items())
            )
            state.log(
                f"[CAP-HARD] {symbol} proposed={cap} "
                f"final={clamped_cap} limits={rendered}"
            )
        cap = clamped_cap

        use_remainder_in_last = state.effective_remainder_policy(
            requested=bool(args.use_remainder_in_last),
            live_mode=state.LIVE_MODE,
        )
        if state.LIVE_MODE and args.use_remainder_in_last:
            state.log(
                f"[CAP-HARD] {symbol} --use-remainder-in-last ignored in LIVE"
            )

        # Run the gap control before any new BUY. A failed check is a safety
        # state, not an informational error; replacement workers may otherwise
        # place exposure while protection telemetry is unavailable.
        if state.LIVE_MODE and state.os.getenv("BOT_GAP_WATCHDOG", "1").lower() in ("1", "true", "yes"):
            gap_block_reason = state._gap_watchdog_fail_closed(
                symbol,
                current_price,
                dependencies=state._protection_dependencies(),
                gap_tolerance_pct=max(
                    0.0,
                    state.getenv_float("BOT_GAP_TOLERANCE_PCT", 0.001),
                ),
            )
            if gap_block_reason is not None:
                safety_buy_block_reason = gap_block_reason

        # The debounce controls escalation/flattening.  It must never create a
        # window in which a fresh LIVE executor submits BUY exposure between the
        # first and second confirmation of the same adverse signal.
        skip_buys_reason = state._panic_buy_block_reason(
            safety_buy_block_reason,
            live_mode=state.LIVE_MODE,
            raw_signal=raw_panic_active,
            debounced_active=panic_active,
            skip_while_panic=args.skip_buy_while_panic,
        )
        panic_sell_floor_pct = args.panic_sell_floor_pct
        if skip_buys_reason is None and bear_mode and args.bear_skip_buys:
            skip_buys_reason = "bear-trend"
        elif skip_buys_reason is None and cap <= 0:
            skip_buys_reason = "cap<=0"
        elif (
            skip_buys_reason is None
            and vwap_ratio is not None
            and args.buy_vwap_premium is not None
        ):
            try:
                premium = max(
                    state.Decimal("0"),
                    state.exact_decimal(
                        args.buy_vwap_premium,
                        field="BUY VWAP premium",
                    ),
                )
                hysteresis = max(
                    state.Decimal("0"),
                    state.getenv_decimal("BUY_VWAP_HYSTERESIS_PCT", "0.0002"),
                )
                previous_vwap_block = state._VWAP_PREMIUM_BLOCKED.get(
                    symbol.upper(), False
                )
                current_vwap_block = (
                    state.vwap_premium_blocked(
                        previously_blocked=previous_vwap_block,
                        price_to_vwap_ratio=str(vwap_ratio),
                        premium=premium,
                        hysteresis=hysteresis,
                    )
                    if premium > 0
                    else False
                )
                state._VWAP_PREMIUM_BLOCKED[symbol.upper()] = current_vwap_block
            except (ArithmeticError, TypeError, ValueError):
                current_vwap_block = True
                premium = state.Decimal("0")
                hysteresis = state.Decimal("0")
                state._VWAP_PREMIUM_BLOCKED[symbol.upper()] = True
            if current_vwap_block:
                skip_buys_reason = "buy-vwap-premium"
                if vwap_value:
                    state.log(
                        f"[VWAP] {symbol} now≈{state.fmt_price_sym(symbol, current_price)} vwap≈{state.fmt_price_sym(symbol, vwap_value)} "
                        f"ratio={vwap_ratio:.6f} premium={premium} "
                        f"hysteresis={hysteresis} blocked={current_vwap_block} "
                        "→ skip BUY"
                    )

        # Before new BUY orders, recover unfinished intents after restart. This makes
        # the same FILLED/PARTIAL BUY pass through OCO protection again.
        placed_ids: List[int] = (
            state.recover_pending_buy_order_ids(symbol)
            if state.LIVE_MODE and attach_oco
            else []
        )
        if skip_buys_reason:
            state.log(f"[SKIP-BUY] {symbol} reason={skip_buys_reason}; new BUY orders suppressed this cycle")
        else:
            try:
                new_ids = state.service_place_buys(
                    symbol,
                    ladder_prices,
                    cap,
                    min_order_usdt=args.min_order_usdt,
                    cap_floor_usdt=args.cap_floor_usdt,
                    target_buy_per_symbol=args.target_buy_per_symbol,
                    enforce_limit=args.enforce_target_buys,
                    use_remainder_in_last=use_remainder_in_last,
                    buy_limit_maker=args.buy_limit_maker,
                    live_mode=state.LIVE_MODE,
                    market_store=market_store,
                    market_policy=state.DecisionFreshnessPolicy(
                        max_age_ms=args.fast_market_max_age_ms,
                        max_spread_bps=args.fast_market_max_spread_bps,
                        max_price_move_bps=args.fast_market_max_move_bps,
                        minimum_net_edge_bps=(
                            args.fast_market_min_net_edge_bps
                        ),
                    ),
                    market_mode=args.fast_market_mode,
                    otoco_mode=args.otoco_mode,
                    stop_limit_offset_pct=args.stop_limit_offset_pct,
                    runtime=state.namespace(),
                )
                placed_ids = list(dict.fromkeys([*placed_ids, *new_ids]))
            except (
                state.requests.RequestException,
                RuntimeError,
                ValueError,
                ArithmeticError,
            ) as e:
                state.log(f"[ERR] maybe_place_buys: {e}")
            try:
                state._observe_buy_market(symbol, placed_ids, current_price)
            except (
                RuntimeError,
                ValueError,
                ArithmeticError,
                OSError,
                state.sqlite3.Error,
            ) as exc:
                state._record_safety_control_failure(
                    "order-lifetime-observation", symbol, exc
                )

        # Sell free holdings separately only when they do not compete for the same
        # base balance as an OCO waiting for a new BUY to execute.
        if args.auto_oco_holdings and (not attach_oco or not placed_ids):
            if attach_oco and not placed_ids:
                state.dbg("[AUTO-OCO] no new BUYs this run → enabling auto_oco_holdings for free base")
            try:
                _ = state.place_sells_from_holdings(
                    symbol,
                    ladder_prices,
                    args.max_oco_per_symbol,
                    enforce_limit=getattr(args, "enforce_sell_limit", False),
                    avg_entry_px=avg_px,
                    panic_active=panic_active,
                    sell_limit_maker=args.sell_limit_maker,
                    panic_sell_floor_pct=panic_sell_floor_pct,
                    runtime=state.namespace(),
                )
            except (
                state.requests.RequestException,
                RuntimeError,
                ValueError,
                ArithmeticError,
            ) as e:
                state.log(f"[ERR] maybe_place_sells: {e}")
        else:
            if attach_oco and placed_ids:
                state.dbg("[SKIP] auto_oco_holdings: skipped because attach_oco_on_fill is enabled and new BUYs exist")

        # One-time trade collection when statistics are enabled.
        try:
            state.sync_account_trades(symbol, runtime=state.namespace())
        except (
            state.requests.RequestException,
            RuntimeError,
            ValueError,
            ArithmeticError,
            OSError,
            state.sqlite3.Error,
        ) as e:
            state.log(f"[STATS] poll error: {e}")

        # The runtime loop does not create new BUY orders. It observes existing orders,
        # confirms FILLED/PARTIAL states, and always creates protection.
        last_check = 0
        panic_cancel_applied = False

        def record_stream_events(stream_events) -> None:
            """Persist sanitized event latency outside the order mutation path."""
            journal = state._order_journal()
            latency_path = state.os.getenv(
                "BOT_EXECUTION_LATENCY_LOG",
                str(
                    state.Path(state.__file__).resolve().parents[3]
                    / "logs"
                    / "execution_latency.ndjson"
                ),
            )
            if journal is None:
                return
            for event in stream_events:
                created_ms = journal.created_at_ms_for_exchange_order(
                    event.order_id
                )
                if created_ms is None:
                    continue
                try:
                    commission_quote = None
                    commission_status = "not_applicable"
                    if event.execution_type == "TRADE":
                        commission_amount = state.Decimal(event.commission_amount)
                        if commission_amount == 0:
                            commission_quote = state.Decimal("0")
                            commission_status = "exact"
                        else:
                            commission_quote, commission_status = (
                                state._commission_quote_value(
                                    event.symbol,
                                    event.commission_asset,
                                    commission_amount,
                                    state.Decimal(event.last_price),
                                    event.transaction_time_ms,
                                )
                            )
                    state.append_execution_latency_sample(
                        latency_path,
                        event,
                        intent_created_at_ms=created_ms,
                        commission_quote=commission_quote,
                        commission_value_status=commission_status,
                    )
                except (
                    ArithmeticError,
                    OSError,
                    TypeError,
                    ValueError,
                ) as exc:
                    state.dbg(
                        "[USER-STREAM] execution latency sample "
                        f"unavailable={type(exc).__name__}"
                    )

        def reconcile_tracked_buys(
            stream_events,
            *,
            event_woken: bool,
        ) -> None:
            """Run authoritative protection immediately after a WS wakeup."""
            nonlocal placed_ids, protection_state
            trace = state.LatencyTrace(symbol, "fill-reconcile")
            if event_woken:
                trace.mark("fill_received")
            pending_before = list(placed_ids)
            terminal_unfilled: set[int] = set()
            placed_ids = state.protect_filled_buys(
                symbol,
                placed_ids,
                ladder_prices,
                config=state.ProtectionConfig(
                    stop_limit_offset_pct=args.stop_limit_offset_pct,
                    oco_fallback=args.oco_fallback,
                    sell_limit_maker=args.sell_limit_maker,
                    avg_cache_ttl=args.avg_cache_ttl,
                    avg_lookback=args.avg_lookback,
                    panic_sell_floor_pct=panic_sell_floor_pct,
                ),
                panic_active=panic_active,
                breakeven_enabled=breakeven.enabled,
                state_store=be_state,
                dependencies=state._protection_dependencies(),
                terminal_unfilled_order_ids=terminal_unfilled,
            )
            if user_stream_observer is not None:
                user_stream_observer.record_rest_reconciliation(
                    event_woken=event_woken
                )
            protection_state = state._protection_state_after_sweep(
                pending_before,
                placed_ids,
                terminal_unfilled,
            )
            if event_woken and protection_state == "confirmed":
                trace.mark("protection_active")
            if event_woken:
                try:
                    trace.append(
                        state.os.getenv(
                            "BOT_LATENCY_TRACE_LOG",
                            str(
                                state.Path(state.__file__).resolve().parents[3]
                                / "logs"
                                / "latency_trace.ndjson"
                            ),
                        )
                    )
                except OSError as exc:
                    state.dbg(
                        "[LATENCY] trace unavailable="
                        f"{type(exc).__name__}"
                    )

        for left in state.trading_wakeups(
            int(args.loop_minutes * 60),
            running=lambda: state.RUN,
            wait=lambda timeout: (
                user_stream_mailbox.wait_for(placed_ids, timeout)
                if user_stream_observer is not None and placed_ids
                else state.time.sleep(timeout)
            ),
        ):
            stream_events = (
                user_stream_mailbox.consume_for(placed_ids)
                if attach_oco and placed_ids
                else []
            )
            if stream_events:
                record_stream_events(stream_events)
                latest = stream_events[-1]
                state.log(
                    f"[USER-STREAM] {symbol} order={latest.order_id} "
                    f"event={latest.execution_type}/{latest.order_status}; "
                    "immediate authoritative REST reconciliation"
                )
                reconcile_tracked_buys(
                    stream_events,
                    event_woken=True,
                )
                last_check = 0

            if state.status_due(left, args.status_interval):
                state.log(status_message(left))

            # Periodically refresh indicators/panic state in the lightweight mode.
            previous_panic_active = panic_active
            try:
                ema20, atr, prev_close = state.get_indicators_cached(symbol, args.panic_interval, ttl_sec=20)
                avg_px = state.avg_entry(symbol, cache_ttl=args.avg_cache_ttl, lookback=args.avg_lookback)
                runtime_price = state.get_price(symbol)
                state._observe_buy_market(symbol, placed_ids, runtime_price)
                panic_active, _ = state._panic_state_fail_closed(
                    "panic-runtime",
                    symbol,
                    lambda: state.update_panic_state(
                        symbol=symbol,
                        now_px=runtime_price,
                        ema20=ema20, atr=atr, prev_close=prev_close,
                        avg_entry_px=avg_px,
                        panic_drop_pct=state._compat_float(args.panic_drop_pct),
                        panic_k_atr=state._compat_float(args.panic_k_atr),
                        debounce_checks=int(args.panic_debounce_checks),
                        cooldown_sec=int(args.panic_cooldown_sec),
                    ),
                )
            except (
                state.requests.RequestException,
                RuntimeError,
                ValueError,
                ArithmeticError,
                OSError,
                state.sqlite3.Error,
            ) as exc:
                panic_active = True
                state._record_safety_control_failure("panic-runtime", symbol, exc)

            if not panic_active:
                panic_cancel_applied = False
            elif state.LIVE_MODE and not panic_cancel_applied and placed_ids:
                placed_ids = state.cancel_open_buys_for_panic(symbol, placed_ids)
                panic_cancel_applied = True
                if not placed_ids:
                    protection_state = "not_needed"

            if state.LIVE_MODE and state.os.getenv("BOT_GAP_WATCHDOG", "1").lower() in ("1", "true", "yes"):
                try:
                    gap_price = state.get_price(symbol)
                except (
                    state.requests.RequestException,
                    RuntimeError,
                    ValueError,
                    ArithmeticError,
                    OSError,
                ) as exc:
                    state._record_safety_control_failure("gap-watchdog", symbol, exc)
                else:
                    state._gap_watchdog_fail_closed(
                        symbol,
                        gap_price,
                        dependencies=state._protection_dependencies(),
                        gap_tolerance_pct=max(
                            0.0,
                            state.getenv_float("BOT_GAP_TOLERANCE_PCT", 0.001),
                        ),
                    )

            # The runtime loop deliberately cannot submit BUY orders. Once a
            # confirmed PANIC recovery leaves no BUY to protect, return normally
            # so the supervisor starts a fresh worker that re-runs every LIVE
            # preflight, Risk, gap, CAP, VWAP and open-order gate before buying.
            if state._panic_recovery_restart_required(
                live_mode=state.LIVE_MODE,
                was_active=previous_panic_active,
                is_active=panic_active,
                tracked_buy_order_ids=placed_ids,
            ):
                state.log(
                    f"[PANIC-RECOVERY] {symbol} no tracked BUY; "
                    "requesting fresh gated executor cycle"
                )
                return

            # A stream event was reconciled before indicators and other REST
            # analytics. Periodic REST remains authoritative when the stream is
            # quiet, disconnected, duplicated or out of order.
            if attach_oco and placed_ids and not stream_events:
                last_check += 1
                if state.reconciliation_due(
                    last_check,
                    args.check_fills_interval,
                    (),
                ):
                    last_check = 0
                    reconcile_tracked_buys(
                        (),
                        event_woken=False,
                    )

            # LIVE time-stop prevents a position from remaining stuck forever. Binance
            # does not provide this policy for an already filled BUY, so track position
            # age locally and close it with a MARKET order.
            max_hold_min = max(0.0, state.getenv_float("BOT_MAX_HOLDING_MINUTES", 0.0))
            if state.LIVE_MODE and max_hold_min > 0 and placed_ids:
                now_ms = int(state.time.time() * 1000)
                for oid in list(placed_ids):
                    held = state.get_order(symbol, oid)
                    if not held or str(held.get("status", "")).upper() != "FILLED":
                        continue
                    opened_ms = int(held.get("time") or held.get("transactTime") or now_ms)
                    if now_ms - opened_ms < max_hold_min * 60_000:
                        continue
                    qty_exp = state.Decimal(str(held.get("executedQty", 0) or 0))
                    # When the ledger knows lots, time-stop closes the oldest inventory
                    # first instead of an arbitrary aggregated quantity.
                    if state.STATS_CON is not None:
                        try:
                            lots = state.oldest_lots(state.STATS_CON, symbol)
                            lot_qty = sum((lot.qty for lot in lots), state.Decimal("0"))
                            if lot_qty > 0:
                                qty_exp = min(qty_exp, lot_qty)
                        except state.sqlite3.Error:
                            pass
                    if qty_exp > 0:
                        state.log(f"[TIME-STOP] {symbol} order={oid} age>{max_hold_min:g}m; flattening")
                        state.place_market_order(symbol, "SELL", qty_exp,
                                           ref_price=state.get_price_exact(symbol),
                                           filters=state.symbol_filters.get(symbol))
                    state._trip_execution_halt("max holding time exceeded", symbol=symbol, order_id=oid)
                    placed_ids.remove(oid)

            # --- Breakeven OCO support after a partial TP fill ---
            if breakeven.due():
                state.maintain_breakeven(
                    symbol,
                    offset_pct=breakeven.offset_pct,
                    stop_limit_offset_pct=args.stop_limit_offset_pct,
                    state_store=be_state,
                    dependencies=state._protection_dependencies(),
                )

        return
    finally:
        if state._WS_TRADING_TRANSPORT is not None:
            state._WS_TRADING_TRANSPORT.close()
        if market_observer is not None:
            market_observer.stop()
        if user_stream_observer is not None:
            user_stream_observer.stop()
        # Always release the lock.
        _lock.release()

def main() -> None:
    """Start the worker with a live view of the runtime module namespace."""
    from ladder_dragon.execution.worker import runtime

    return run_worker(WorkerRuntimeState(vars(runtime)))
