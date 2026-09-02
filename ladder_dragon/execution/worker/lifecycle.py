# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own worker preflight, resource startup, and shutdown lifecycle.
"""Worker lifecycle and mutable runtime orchestration."""
from __future__ import annotations
from collections.abc import MutableMapping
from dataclasses import dataclass
import re
from typing import Any
from ladder_dragon.execution.worker.event_loop import WorkerLoopContext, run_event_loop
from ladder_dragon.execution.worker.lock_guard import release_lock_on_error
from ladder_dragon.execution.worker.champion_preflight import champion_entry_veto_rule, champion_ladder, require_live_champion
from ladder_dragon.execution.worker.authority_attestation import require_worker_authority_binding
from ladder_dragon.supervision.startup_timing import StartupTimeline, log_worker_startup
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
@dataclass
class WorkerResources:
    """Stop every worker resource even when one cleanup operation fails."""
    verify_champion = staticmethod(require_live_champion)
    require_authority_binding = staticmethod(require_worker_authority_binding)
    build_champion_ladder = staticmethod(champion_ladder)
    entry_veto_rule = staticmethod(champion_entry_veto_rule)
    startup_timeline = staticmethod(StartupTimeline)
    log_startup = staticmethod(log_worker_startup)
    state: WorkerRuntimeState
    lock: Any
    user_stream_observer: Any = None
    market_observer: Any = None
    def close(self) -> None:
        """Close transports and observers, then always release the symbol lock."""
        callbacks = []
        if self.state._WS_TRADING_TRANSPORT is not None:
            callbacks.append(
                ("websocket trading transport", self.state._WS_TRADING_TRANSPORT.close)
            )
        if self.market_observer is not None:
            callbacks.append(("market observer", self.market_observer.stop))
        if self.user_stream_observer is not None:
            callbacks.append(("user stream observer", self.user_stream_observer.stop))
        callbacks.append(("symbol lock", self.lock.release))
        for label, callback in callbacks:
            try:
                callback()
            except (OSError, RuntimeError, ValueError) as exc:
                self.state.dbg(f"[WORKER-CLEANUP] {label} failed={type(exc).__name__}")
def normalize_symbol(symbol: str) -> str:
    """Return a Binance symbol or fail before any exchange request."""
    normalized = str(symbol).strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{5,20}", normalized):
        raise ValueError("symbol must match [A-Z0-9]{5,20}")
    return normalized
def run_worker(state: WorkerRuntimeState) -> None:
    """Run one symbol worker against live runtime dependencies."""
    startup_timing = WorkerResources.startup_timeline(state.time.monotonic)
    parser = state.build_executor_parser()
    args = state.validate_executor_args(parser, parser.parse_args())
    state.log(f"[VERSION] {state.product_label('executor')}")
    state.LIVE_MODE = bool(args.live)
    champion = None
    state.WS_TRADING_MODE = args.ws_trading_mode
    if state.LIVE_MODE:
        # Supervisor risk calculation treats target-buy as a hard maximum.
        # Therefore LIVE always checks existing BUY orders.
        args.enforce_target_buys = True

    symbol = normalize_symbol(args.symbol)
    WorkerResources.log_startup(startup_timing, state.log, symbol, "configuration")
    # A duplicate worker exits before database or exchange preflight traffic.
    _lock = state.SymbolLock(symbol)
    lock_acquired = _lock.acquire()
    if not lock_acquired:
        return
    WorkerResources.log_startup(startup_timing, state.log, symbol, "lock")
    with release_lock_on_error(_lock):
        if state.LIVE_MODE:
            # Repeat preflight because a worker can start without the supervisor.
            try:
                WorkerResources.require_authority_binding(WorkerResources.verify_champion)
                champion = WorkerResources.verify_champion(state, args)
                WorkerResources.log_startup(startup_timing, state.log, symbol, "champion")
            except (OSError, state.sqlite3.Error, RuntimeError, TypeError, ValueError) as exc:
                parser.error(f"LIVE CHAMPION verification failed: {exc}")
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
                WorkerResources.log_startup(startup_timing, state.log, symbol, "database")
                state.TM._refresh_time_offset(
                    timeout=15,
                    max_offset_ms=int(state.os.getenv("RISK_MAX_TIME_OFFSET_MS", "1000")),
                    max_round_trip_ms=int(state.os.getenv("RISK_MAX_TIME_RTT_MS", "5000")),
                )
                WorkerResources.log_startup(startup_timing, state.log, symbol, "clock")
                state.pull_filters(symbol)
                WorkerResources.log_startup(startup_timing, state.log, symbol, "filters")
                account = state._signed_request("GET", "/api/v3/account")
                if account.get("canTrade") is not True:
                    raise RuntimeError("Binance account/API key is not allowed to trade")
                WorkerResources.log_startup(startup_timing, state.log, symbol, "account")
                state._order_journal()
                WorkerResources.log_startup(startup_timing, state.log, symbol, "journal")
                # Reconcile every ordinary BUY/SELL intent before any new LIVE
                # action. This closes externally cancelled orders and definitive
                # Binance -2013 absences without manual SQLite edits.
                state.reconcile_nonterminal_orders(symbol)
                WorkerResources.log_startup(startup_timing, state.log, symbol, "reconciliation")
            except (OSError, state.sqlite3.Error, state.requests.RequestException, RuntimeError, KeyError, ValueError) as exc:
                parser.error(f"LIVE preflight failed: {exc}")
    attach_oco = bool(args.attach_oco_on_fill)
    # OCO status is no longer hidden behind a question mark: before the first check,
    # explicitly show that protection is not confirmed. This distinguishes a
    # pending BUY from a verified OCO in logs and the dashboard.
    protection_state = "not_checked" if attach_oco else "disabled"
    resources = WorkerResources(state=state, lock=_lock)
    user_stream_mailbox = state.OrderEventMailbox()
    user_stream_observer: Optional[state.BinanceUserDataObserver] = None
    market_store: state.MarketSnapshotStore | None = None
    market_observer: state.BinanceMarketDataObserver | None = None
    try:
        ladder_prices = state.parse_comma_floats(args.ladder_prices)
        entry_veto_rule = WorkerResources.entry_veto_rule(champion)
        # --- Breakeven: keep OCO linked to the original BUY average price ---
        be_syms = {s.strip().upper() for s in args.breakeven_on_tp1_symbols.split(",") if s.strip()}
        BE_ENABLED = symbol.upper() in be_syms
        fee_pct = max(state.Decimal("0"), state.getenv_decimal("BOT_FEE_PCT", state.DEFAULT_SPOT_FEE_PCT))
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
                resources.user_stream_observer = user_stream_observer
                user_stream_observer.start()
        if args.fast_market_mode != "OFF":
            market_store = state.MarketSnapshotStore(symbol)
            market_observer = state.BinanceMarketDataObserver(
                market_store,
                testnet="testnet" in state.BINANCE_API_BASE.lower(),
                logger=state.log,
            )
            resources.market_observer = market_observer
            market_observer.start()
            state.log(
                f"[FAST-MARKET] {symbol} mode={args.fast_market_mode} "
                f"max_age={args.fast_market_max_age_ms}ms"
            )
        current_price = state.get_price(symbol)
        if champion is not None:
            ladder_prices = WorkerResources.build_champion_ladder(state, champion, current_price)

        # Protection deduplication also runs here: direct worker startup must not
        # depend on whether the supervisor normalized the ladder.
        ladder_prices = state.dedup_ladder(symbol, ladder_prices, current_price)

        started_at = state.time.time()
        warmup = state.cleanup_warmup_sec()
        state.log(
            f"[status] {symbol} pid={state.os.getpid()} "
            f"OCO:{protection_state} | "
            f"started:{state.datetime.fromtimestamp(started_at).strftime('%Y-%m-%d %H:%M:%S')} | "
            f"left:{int(args.loop_minutes * 60)}s | last: idle"
        )

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
                    entry_veto_rule=entry_veto_rule,
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

        # Sell free holdings only when they do not compete with a protected BUY.
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

        loop_context = WorkerLoopContext(
            state=state,
            args=args,
            symbol=symbol,
            attach_oco=attach_oco,
            ladder_prices=ladder_prices,
            placed_ids=placed_ids,
            panic_active=panic_active,
            panic_sell_floor_pct=panic_sell_floor_pct,
            breakeven=breakeven,
            breakeven_state=be_state,
            user_stream_mailbox=user_stream_mailbox,
            user_stream_observer=user_stream_observer,
            market_store=market_store,
            entry_veto_rule=entry_veto_rule,
            started_at=started_at,
            protection_state=protection_state,
        )
        WorkerResources.log_startup(startup_timing, state.log, symbol, "worker_ready")
        return run_event_loop(loop_context)
    finally:
        resources.close()
