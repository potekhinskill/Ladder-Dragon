"""Безопасные агрегаты истории и рынка для AI-рекомендателя.

Модуль не передаёт LLM сырые сделки, идентификаторы заявок, полный баланс или
стакан. Вместо этого рассчитываются ограниченные числовые признаки, а решения
AI сохраняются отдельно и позднее оцениваются по движению цены.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from trade_accounting import TradeExecution, replay_average_cost


ZERO = Decimal("0")
HORIZONS_SEC = (900, 3600, 14_400)


def evaluate_realized_ai_pnl(
    fills: Sequence[Mapping[str, Any]], *, baseline_exit_price: float | None = None,
    baseline_entry_price: float | None = None,
) -> dict[str, float | int | None]:
    """Оценить рекомендацию по фактическим fills, а не по synthetic candles.

    Возвращает net PnL, duration и opportunity-cost против equal-notional
    buy-and-hold baseline. Неполные/отменённые заявки игнорируются.
    """
    buys = [f for f in fills if str(f.get("side", "")).upper() == "BUY" and str(f.get("status", "FILLED")).upper() == "FILLED"]
    sells = [f for f in fills if str(f.get("side", "")).upper() == "SELL" and str(f.get("status", "FILLED")).upper() == "FILLED"]
    bought_qty = sum(float(f.get("qty", f.get("executedQty", 0)) or 0) for f in buys)
    sold_qty = sum(float(f.get("qty", f.get("executedQty", 0)) or 0) for f in sells)
    buy_notional = sum(float(f.get("price", 0) or 0) * float(f.get("qty", f.get("executedQty", 0)) or 0) for f in buys)
    sell_notional = sum(float(f.get("price", 0) or 0) * float(f.get("qty", f.get("executedQty", 0)) or 0) for f in sells)
    fees = sum(float(f.get("fee_quote", f.get("commission_quote", 0)) or 0) for f in fills)
    net = sell_notional - buy_notional - fees
    entry = baseline_entry_price or (buy_notional / bought_qty if bought_qty else None)
    exit_price = baseline_exit_price or (sell_notional / sold_qty if sold_qty else None)
    opportunity = None
    if entry and exit_price and bought_qty:
        opportunity = (exit_price - entry) * bought_qty - net
    timestamps = [float(f.get("ts", f.get("time", 0)) or 0) for f in fills if f.get("ts", f.get("time"))]
    duration = (max(timestamps) - min(timestamps)) if len(timestamps) >= 2 else None
    return {"net_pnl_quote": net, "buy_qty": bought_qty, "sell_qty": sold_qty,
            "holding_duration_sec": duration, "opportunity_cost_quote": opportunity,
            "baseline_entry_price": entry, "baseline_exit_price": exit_price}


@dataclass(frozen=True)
class TradeFeatures:
    trade_history_available: bool = False
    trade_count_30d: int = 0
    sell_count_30d: int = 0
    net_realized_pnl_30d: float = 0.0
    win_rate_30d: float = 0.0
    avg_win_usdt_30d: float = 0.0
    avg_loss_usdt_30d: float = 0.0
    consecutive_losses: int = 0
    fees_usdt_30d: float = 0.0
    turnover_usdt_30d: float = 0.0
    position_pnl_pct: float = 0.0


@dataclass(frozen=True)
class MarketFeatures:
    market_data_available: bool = False
    orderbook_available: bool = False
    market_data_age_sec: float = 999999.0
    return_15m: float = 0.0
    return_1h: float = 0.0
    return_4h: float = 0.0
    return_24h: float = 0.0
    volume_ratio_1h: float = 1.0
    spread_bps: float = 0.0
    orderbook_imbalance_top5: float = 0.0
    orderbook_imbalance_top20: float = 0.0


@dataclass(frozen=True)
class PortfolioFeatures:
    portfolio_data_available: bool = False
    portfolio_data_age_sec: float = 999999.0
    open_buy_count: int = 0
    open_sell_count: int = 0
    open_buy_exposure_usdt: float = 0.0
    portfolio_cap_used_pct: float = 0.0
    free_reserve_ratio: float = 0.0


@dataclass(frozen=True)
class AdvisorPerformance:
    ai_samples_15m: int = 0
    ai_accuracy_15m: float = 0.0
    ai_samples_1h: int = 0
    ai_accuracy_1h: float = 0.0
    ai_samples_4h: int = 0
    ai_accuracy_4h: float = 0.0
    ai_vs_baseline_samples_1h: int = 0
    ai_edge_vs_baseline_1h: float = 0.0


def load_trade_features(
    db_path: str,
    symbol: str,
    current_price: float,
    *,
    now_ms: int | None = None,
) -> TradeFeatures:
    """Свести последние 30 дней сделок в PnL/fees/series-признаки."""
    if not db_path or not Path(db_path).exists():
        return TradeFeatures()
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    start_ms = now_ms - 30 * 86_400_000
    try:
        with sqlite3.connect(
            f"file:{db_path}?mode=ro", uri=True, timeout=3
        ) as connection:
            rows = connection.execute(
                """
                SELECT ts, side,
                       COALESCE(NULLIF(price_text, ''), CAST(price AS TEXT)),
                       COALESCE(NULLIF(gross_qty, ''), CAST(qty AS TEXT)),
                       COALESCE(NULLIF(net_qty, ''), CAST(qty AS TEXT)),
                       commission_asset,
                       commission_amount,
                       CASE WHEN commission_value_status='unpriced' THEN NULL
                            ELSE COALESCE(NULLIF(commission_quote, ''), CAST(fee_quote AS TEXT)) END,
                       commission_value_status
                FROM (
                    SELECT * FROM trades
                    WHERE symbol=? AND ts<=?
                    ORDER BY ts DESC, id DESC
                    LIMIT 1000
                )
                ORDER BY ts, id
                """,
                (symbol.upper(), now_ms),
            ).fetchall()
            inventory = connection.execute(
                """
                SELECT COALESCE(NULLIF(qty_text, ''), CAST(qty AS TEXT)),
                       COALESCE(NULLIF(avg_cost_text, ''), CAST(avg_cost AS TEXT))
                FROM inventory WHERE symbol=?
                """,
                (symbol.upper(),),
            ).fetchone()
    except sqlite3.Error:
        return TradeFeatures()

    executions: list[TradeExecution] = []
    execution_times: list[int] = []
    fees = ZERO
    turnover = ZERO
    for row in rows:
        try:
            timestamp = int(row[0])
            fee = Decimal(str(row[7] or "0"))
            execution = TradeExecution.create(
                symbol=symbol,
                side=row[1],
                price=row[2],
                gross_qty=row[3],
                net_qty=row[4],
                commission_asset=row[5] or "",
                commission_amount=row[6] or 0,
                commission_quote=fee,
                commission_value_status=row[8] or "legacy",
            )
            executions.append(execution)
            execution_times.append(timestamp)
            if timestamp >= start_ms:
                fees += fee
                turnover += execution.price * execution.gross_qty
        except (ArithmeticError, TypeError, ValueError):
            continue
    replay = replay_average_cost(executions, allow_unpriced=True)
    sell_times = [
        timestamp
        for execution, timestamp in zip(executions, execution_times)
        if execution.side == "SELL"
    ]
    sells = [
        result
        for result, timestamp in zip(replay.sell_results, sell_times)
        if timestamp >= start_ms
    ]
    recent_trade_count = sum(timestamp >= start_ms for timestamp in execution_times)
    wins = [value for value in sells if value > 0]
    losses = [value for value in sells if value < 0]
    consecutive_losses = 0
    for value in reversed(sells):
        if value >= 0:
            break
        consecutive_losses += 1
    position_pnl = 0.0
    if inventory:
        try:
            qty, avg = Decimal(str(inventory[0])), Decimal(str(inventory[1]))
            if qty > 0 and avg > 0 and current_price > 0:
                position_pnl = float(Decimal(str(current_price)) / avg - 1)
        except ArithmeticError:
            pass
    return TradeFeatures(
        trade_history_available=True,
        trade_count_30d=recent_trade_count,
        sell_count_30d=len(sells),
        net_realized_pnl_30d=float(sum(sells, ZERO)),
        win_rate_30d=(len(wins) / len(sells) if sells else 0.0),
        avg_win_usdt_30d=(
            float(sum(wins, ZERO) / len(wins)) if wins else 0.0
        ),
        avg_loss_usdt_30d=(
            float(sum(losses, ZERO) / len(losses)) if losses else 0.0
        ),
        consecutive_losses=consecutive_losses,
        fees_usdt_30d=float(fees),
        turnover_usdt_30d=float(turnover),
        position_pnl_pct=position_pnl,
    )


def market_features_from_klines(
    klines: Sequence[Sequence[Any]],
) -> MarketFeatures:
    """Сжать до 24 часов 5m-свечей в доходности и относительный объём."""
    valid = [row for row in klines if len(row) > 5 and float(row[4]) > 0]
    if not valid:
        return MarketFeatures()
    current = float(valid[-1][4])

    def period_return(bars: int) -> float:
        index = max(0, len(valid) - 1 - bars)
        previous = float(valid[index][4])
        return current / previous - 1 if previous > 0 else 0.0

    recent = [float(row[5]) for row in valid[-12:]]
    previous = [float(row[5]) for row in valid[-24:-12]]
    recent_avg = sum(recent) / len(recent) if recent else 0.0
    previous_avg = sum(previous) / len(previous) if previous else 0.0
    return MarketFeatures(
        market_data_available=True,
        market_data_age_sec=max(
            0.0,
            time.time() - float(valid[-1][6]) / 1000
            if len(valid[-1]) > 6 and float(valid[-1][6]) > 0 else 0.0,
        ),
        return_15m=period_return(3),
        return_1h=period_return(12),
        return_4h=period_return(48),
        return_24h=period_return(288),
        volume_ratio_1h=(recent_avg / previous_avg if previous_avg > 0 else 1.0),
    )


def orderbook_features(depth: Mapping[str, Any]) -> tuple[float, float, float]:
    bids = depth.get("bids")
    asks = depth.get("asks")
    if not isinstance(bids, list) or not isinstance(asks, list) or not bids or not asks:
        return 0.0, 0.0, 0.0
    try:
        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        midpoint = (best_bid + best_ask) / 2
        spread_bps = (best_ask - best_bid) / midpoint * 10_000
    except (ArithmeticError, IndexError, TypeError, ValueError):
        return 0.0, 0.0, 0.0

    def imbalance(levels: int) -> float:
        bid_qty = sum(float(row[1]) for row in bids[:levels])
        ask_qty = sum(float(row[1]) for row in asks[:levels])
        total = bid_qty + ask_qty
        return (bid_qty - ask_qty) / total if total > 0 else 0.0

    try:
        return spread_bps, imbalance(5), imbalance(20)
    except (ArithmeticError, IndexError, TypeError, ValueError):
        return spread_bps, 0.0, 0.0


def build_market_features(
    symbol: str,
    *,
    get_klines: Callable[..., Sequence[Sequence[Any]]],
    public_get: Callable[..., Any],
) -> MarketFeatures:
    try:
        base = market_features_from_klines(
            get_klines(symbol, "5m", limit=289)
        )
    except Exception:
        base = MarketFeatures()
    try:
        spread, top5, top20 = orderbook_features(
            public_get("/api/v3/depth", {"symbol": symbol, "limit": 20})
        )
    except Exception:
        spread, top5, top20 = 0.0, 0.0, 0.0
    return MarketFeatures(
        market_data_available=base.market_data_available,
        orderbook_available=bool(spread or top5 or top20),
        market_data_age_sec=base.market_data_age_sec,
        return_15m=base.return_15m,
        return_1h=base.return_1h,
        return_4h=base.return_4h,
        return_24h=base.return_24h,
        volume_ratio_1h=base.volume_ratio_1h,
        spread_bps=spread,
        orderbook_imbalance_top5=top5,
        orderbook_imbalance_top20=top20,
    )


def build_portfolio_features(
    symbol: str,
    *,
    open_orders: Iterable[Mapping[str, Any]],
    balances: Mapping[str, Mapping[str, Any]],
    portfolio_cap_usdt: float,
    reserve_usdt: float,
) -> PortfolioFeatures:
    orders = tuple(open_orders)
    buys = [
        order for order in orders
        if str(order.get("symbol", "")).upper() == symbol.upper()
        and str(order.get("side", "")).upper() == "BUY"
    ]
    sells = [
        order for order in orders
        if str(order.get("symbol", "")).upper() == symbol.upper()
        and str(order.get("side", "")).upper() == "SELL"
    ]
    def remaining_exposure(order: Mapping[str, Any]) -> float:
        remaining = max(
            0.0,
            float(order.get("origQty") or 0)
            - float(order.get("executedQty") or 0),
        )
        return float(order.get("price") or 0) * remaining

    exposure = sum(
        remaining_exposure(order)
        for order in buys
    )
    total_buy_exposure = sum(
        remaining_exposure(order)
        for order in orders
        if str(order.get("side", "")).upper() == "BUY"
    )
    free_usdt = float(balances.get("USDT", {}).get("free", 0) or 0)
    return PortfolioFeatures(
        portfolio_data_available=True,
        portfolio_data_age_sec=0.0,
        open_buy_count=len(buys),
        open_sell_count=len(sells),
        open_buy_exposure_usdt=exposure,
        portfolio_cap_used_pct=(
            total_buy_exposure / portfolio_cap_usdt
            if portfolio_cap_usdt > 0 else 0.0
        ),
        free_reserve_ratio=(
            free_usdt / reserve_usdt if reserve_usdt > 0 else 0.0
        ),
    )


class AdvisorDecisionStore:
    """Хранить рекомендации и оценивать направление через 15m/1h/4h."""

    def __init__(self, db_path: str) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _init(self) -> None:
        with self._connect() as connection:
            # Отдельная таблица fills не смешивает прогноз модели с фактом
            # исполнения и позволяет считать PnL конкретной рекомендации.
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_decisions(
                    decision_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    price REAL NOT NULL,
                    deterministic_mode TEXT NOT NULL,
                    recommended_mode TEXT NOT NULL,
                    width_scale REAL NOT NULL,
                    cap_scale REAL NOT NULL,
                    confidence REAL NOT NULL,
                    applied INTEGER NOT NULL,
                    policy_status TEXT NOT NULL DEFAULT '',
                    policy_reasons TEXT NOT NULL DEFAULT '',
                    benchmark_mode TEXT NOT NULL DEFAULT '',
                    evaluation_json TEXT NOT NULL DEFAULT '{}',
                    feature_json TEXT NOT NULL DEFAULT '[]',
                    return_15m REAL,
                    return_1h REAL,
                    return_4h REAL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS ai_decisions_symbol_time "
                "ON ai_decisions(symbol, created_at)"
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS ai_fills(
                    fill_id TEXT PRIMARY KEY, decision_id TEXT NOT NULL,
                    symbol TEXT NOT NULL, side TEXT NOT NULL, price REAL NOT NULL,
                    qty REAL NOT NULL, fee_quote REAL NOT NULL DEFAULT 0,
                    exit_reason TEXT NOT NULL DEFAULT '', ts INTEGER NOT NULL,
                    FOREIGN KEY(decision_id) REFERENCES ai_decisions(decision_id)
                )"""
            )
            connection.execute("CREATE INDEX IF NOT EXISTS ai_fills_decision ON ai_fills(decision_id, ts)")
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(ai_decisions)")
            }
            for column, ddl in (
                ("policy_status", "TEXT NOT NULL DEFAULT ''"),
                ("policy_reasons", "TEXT NOT NULL DEFAULT ''"),
                ("benchmark_mode", "TEXT NOT NULL DEFAULT ''"),
                ("evaluation_json", "TEXT NOT NULL DEFAULT '{}'"),
                ("feature_json", "TEXT NOT NULL DEFAULT '[]'"),
            ):
                if column not in columns:
                    connection.execute(
                        f"ALTER TABLE ai_decisions ADD COLUMN {column} {ddl}"
                    )
            connection.execute(
                "DELETE FROM ai_decisions WHERE created_at < ?",
                (int(time.time()) - 365 * 86_400,),
            )

    def record_fill(self, decision_id: str, *, symbol: str, side: str,
                    price: float, qty: float, fee_quote: float = 0.0,
                    exit_reason: str = "", ts: int | None = None) -> str:
        """Привязать фактический Binance fill/OCO/stop к AI decision."""
        fill_id = uuid.uuid4().hex
        with self._connect() as connection:
            exists = connection.execute("SELECT 1 FROM ai_decisions WHERE decision_id=?", (decision_id,)).fetchone()
            if not exists:
                raise ValueError(f"unknown AI decision: {decision_id}")
            connection.execute(
                "INSERT INTO ai_fills(fill_id,decision_id,symbol,side,price,qty,fee_quote,exit_reason,ts) VALUES(?,?,?,?,?,?,?,?,?)",
                (fill_id, decision_id, symbol.upper(), side.upper(), float(price), float(qty),
                 float(fee_quote), exit_reason, int(ts or time.time())),
            )
        return fill_id

    def evaluate_execution(self, decision_id: str, *, baseline_exit_price: float | None = None) -> dict[str, Any]:
        """Рассчитать realized net PnL и baseline equal-notional по fills."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT side,price,qty,fee_quote,exit_reason,ts FROM ai_fills WHERE decision_id=? ORDER BY ts",
                (decision_id,),
            ).fetchall()
            decision = connection.execute("SELECT price FROM ai_decisions WHERE decision_id=?", (decision_id,)).fetchone()
        if not decision:
            raise ValueError(f"unknown AI decision: {decision_id}")
        fills = [{"side": r[0], "price": r[1], "qty": r[2], "fee_quote": r[3], "exit_reason": r[4], "ts": r[5]} for r in rows]
        # Baseline использует тот же entry и объём, поэтому сравнение не
        # выигрывает искусственно за счёт другого размера позиции.
        result = evaluate_realized_ai_pnl(fills, baseline_entry_price=float(decision[0]), baseline_exit_price=baseline_exit_price)
        result["decision_id"] = decision_id
        with self._connect() as connection:
            row = connection.execute("SELECT evaluation_json FROM ai_decisions WHERE decision_id=?", (decision_id,)).fetchone()
            evaluation = json.loads((row[0] if row else "{}") or "{}")
            evaluation["realized_execution"] = result
            connection.execute("UPDATE ai_decisions SET evaluation_json=? WHERE decision_id=?", (json.dumps(evaluation), decision_id))
        return result

    def record(
        self,
        *,
        symbol: str,
        price: float,
        deterministic_mode: str,
        recommended_mode: str,
        width_scale: float,
        cap_scale: float,
        confidence: float,
        applied: bool,
        policy_status: str = "",
        policy_reasons: str = "",
        benchmark_mode: str = "",
        feature_json: str = "[]",
        now: int | None = None,
    ) -> str:
        decision_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO ai_decisions(
                    decision_id, symbol, created_at, price,
                    deterministic_mode, recommended_mode, width_scale,
                    cap_scale, confidence, applied, policy_status,
                    policy_reasons, benchmark_mode, feature_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    decision_id, symbol.upper(), int(now or time.time()), price,
                    deterministic_mode, recommended_mode, width_scale,
                    cap_scale, confidence, int(applied),
                    policy_status, policy_reasons, benchmark_mode,
                    feature_json,
                ),
            )
        return decision_id

    def settle(
        self,
        symbol: str,
        current_price: float,
        *,
        now: int | None = None,
        price_lookup: Callable[[str, int], float] | None = None,
        candles_lookup: Callable[[str, int, int], Sequence[Sequence[Any]]] | None = None,
    ) -> int:
        now = int(now or time.time())
        updated = 0
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT decision_id, created_at, price,recommended_mode,
                       deterministic_mode,width_scale,cap_scale,evaluation_json,
                       return_15m, return_1h, return_4h
                FROM ai_decisions
                WHERE symbol=? AND created_at>=?
                  AND (return_15m IS NULL OR return_1h IS NULL OR return_4h IS NULL)
                """,
                (symbol.upper(), now - 86_400),
            ).fetchall()
            for (
                decision_id, created_at, price, recommended_mode,
                deterministic_mode, width_scale, cap_scale, evaluation_json,
                *existing
            ) in rows:
                if price <= 0:
                    continue
                changes: dict[str, Any] = {}
                evaluations = json.loads(evaluation_json or "{}")
                for index, (column, horizon) in enumerate(zip(
                    ("return_15m", "return_1h", "return_4h"),
                    HORIZONS_SEC,
                )):
                    if existing[index] is None and now - created_at >= horizon:
                        horizon_price = current_price
                        if price_lookup is not None:
                            try:
                                horizon_price = float(
                                    price_lookup(symbol, (created_at + horizon) * 1000)
                                )
                            except Exception:
                                horizon_price = current_price
                        changes[column] = horizon_price / price - 1
                        if candles_lookup is not None:
                            try:
                                candles = candles_lookup(
                                    symbol,
                                    created_at * 1000,
                                    (created_at + horizon) * 1000,
                                )
                                evaluations[column.removeprefix("return_")] = {
                                    "ai": virtual_plan_result(
                                        price, recommended_mode, width_scale,
                                        cap_scale, candles,
                                    ),
                                    "baseline": virtual_plan_result(
                                        price, deterministic_mode, 1.0, 1.0,
                                        candles,
                                    ),
                                }
                            except Exception:
                                pass
                if not changes:
                    continue
                if evaluations:
                    changes["evaluation_json"] = json.dumps(
                        evaluations, sort_keys=True
                    )
                assignments = ", ".join(f"{column}=?" for column in changes)
                connection.execute(
                    f"UPDATE ai_decisions SET {assignments} WHERE decision_id=?",
                    (*changes.values(), decision_id),
                )
                updated += 1
        return updated

    def performance(self, symbol: str, *, limit: int = 300) -> AdvisorPerformance:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT recommended_mode, return_15m, return_1h, return_4h
                FROM ai_decisions
                WHERE symbol=? ORDER BY created_at DESC LIMIT ?
                """,
                (symbol.upper(), limit),
            ).fetchall()

        def score(index: int) -> tuple[int, float]:
            values = [
                directional_success(mode, row[index])
                for row in rows
                if row[index] is not None
                for mode in (row[0],)
            ]
            return len(values), (sum(values) / len(values) if values else 0.0)

        s15, a15 = score(1)
        s1h, a1h = score(2)
        s4h, a4h = score(3)
        comparisons = [
            directional_success(row[0], row[2])
            - directional_success(row[4], row[2])
            for row in self._comparison_rows(symbol, limit)
            if row[2] is not None
        ]
        return AdvisorPerformance(
            s15, a15, s1h, a1h, s4h, a4h,
            len(comparisons),
            sum(comparisons) / len(comparisons) if comparisons else 0.0,
        )

    def _comparison_rows(self, symbol: str, limit: int) -> list[tuple]:
        with self._connect() as connection:
            return connection.execute(
                """
                SELECT recommended_mode,return_15m,return_1h,return_4h,
                       deterministic_mode
                FROM ai_decisions
                WHERE symbol=? ORDER BY created_at DESC LIMIT ?
                """,
                (symbol.upper(), limit),
            ).fetchall()

    def dashboard_summary(self, *, limit: int = 50) -> dict[str, Any]:
        from ai_policy import confidence_calibration

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT decision_id,symbol,created_at,deterministic_mode,
                       recommended_mode,width_scale,cap_scale,confidence,
                       applied,policy_status,policy_reasons,benchmark_mode,
                       return_15m,return_1h,return_4h,evaluation_json
                FROM ai_decisions ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            calibration_rows = connection.execute(
                """
                SELECT confidence,return_1h,recommended_mode
                FROM ai_decisions WHERE return_1h IS NOT NULL
                ORDER BY created_at DESC LIMIT 1000
                """
            ).fetchall()
        recent = [
            {
                "decision_id": row[0],
                "symbol": row[1],
                "created_at": row[2],
                "baseline_mode": row[3],
                "recommended_mode": row[4],
                "width_scale": row[5],
                "cap_scale": row[6],
                "confidence": row[7],
                "applied": bool(row[8]),
                "status": row[9],
                "reasons": row[10].split(",") if row[10] else [],
                "benchmark_mode": row[11],
                "return_15m": row[12],
                "return_1h": row[13],
                "return_4h": row[14],
                "evaluation": json.loads(row[15] or "{}"),
            }
            for row in rows
        ]
        changed = sum(
            row["recommended_mode"] != row["baseline_mode"] for row in recent
        )
        return {
            "recent": recent,
            "recommendation_count": len(recent),
            "applied_count": sum(row["applied"] for row in recent),
            "changed_mode_count": changed,
            "ai_vs_baseline_1h": self._edge_summary(recent),
            "calibration_1h": confidence_calibration(calibration_rows),
        }

    def statistical_prediction(
        self,
        context: Any,
        *,
        min_samples: int = 60,
    ) -> dict[str, Any]:
        from ai_statistical import (
            MulticlassLogisticRegime,
            context_vector,
            return_label,
        )

        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT feature_json,return_1h FROM ai_decisions
                WHERE return_1h IS NOT NULL AND feature_json!='[]'
                ORDER BY created_at DESC LIMIT 2000
                """
            ).fetchall()
        examples = []
        for feature_json, result in rows:
            try:
                vector = json.loads(feature_json)
                if isinstance(vector, list) and len(vector) == 10:
                    examples.append((vector, return_label(float(result))))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        model = MulticlassLogisticRegime()
        model.fit(examples)
        prediction = model.predict(context_vector(context), min_samples=min_samples)
        return {
            "mode": prediction.mode,
            "confidence": prediction.confidence,
            "samples": prediction.samples,
            "available": prediction.available,
        }

    @staticmethod
    def _edge_summary(recent: list[dict[str, Any]]) -> dict[str, float | int]:
        values = [
            directional_success(row["recommended_mode"], row["return_1h"])
            - directional_success(row["baseline_mode"], row["return_1h"])
            for row in recent if row["return_1h"] is not None
        ]
        return {
            "samples": len(values),
            "edge": sum(values) / len(values) if values else 0.0,
        }


def directional_success(mode: str, market_return: float) -> int:
    normalized = mode.upper()
    fee = float(os.getenv("AI_SHADOW_FEE_PCT", "0.00075") or 0.00075)
    slippage = float(os.getenv("AI_SHADOW_SLIPPAGE_PCT", "0.0005") or 0.0005)
    spread = float(os.getenv("AI_SHADOW_SPREAD_PCT", "0.0002") or 0.0002)
    threshold = max(0.001, 2 * (fee + slippage + spread / 2))
    if normalized == "UP":
        return int(market_return > threshold)
    if normalized == "DOWN":
        return int(market_return < -threshold)
    return int(abs(market_return) <= threshold)


def virtual_plan_result(
    reference_price: float,
    mode: str,
    width_scale: float,
    cap_scale: float,
    candles: Sequence[Sequence[Any]],
) -> dict[str, float | bool]:
    """Оценить один виртуальный BUY с комиссиями и проскальзыванием."""
    offset = {"UP": 0.005, "FLAT": 0.010, "DOWN": 0.015}.get(
        mode.upper(), 0.01
    )
    entry = reference_price * (1 - offset * max(0.5, width_scale))
    valid = [row for row in candles if len(row) > 4]
    if not valid:
        return {
            "filled": False, "entry": entry, "net_return": 0.0,
            "mfe": 0.0, "mae": 0.0,
        }
    low = min(float(row[3]) for row in valid)
    if low > entry:
        return {
            "filled": False, "entry": entry, "net_return": 0.0,
            "mfe": 0.0, "mae": 0.0,
        }
    high = max(float(row[2]) for row in valid)
    close = float(valid[-1][4])
    fee = float(os.getenv("AI_SHADOW_FEE_PCT", "0.00075") or 0.00075)
    slippage = float(
        os.getenv("AI_SHADOW_SLIPPAGE_PCT", "0.0005") or 0.0005
    )
    spread = float(os.getenv("AI_SHADOW_SPREAD_PCT", "0.0002") or 0.0002)
    net_return = (close / entry - 1) - 2 * (
        fee + slippage + spread / 2
    )
    return {
        "filled": True,
        "entry": entry,
        # CAP changes absolute PnL, not percentage edge. Keep the percentage
        # metric independent of sizing so larger recommendations do not look
        # more profitable merely because they are larger.
        "net_return": net_return,
        "scaled_pnl_pct": net_return * max(0.0, cap_scale),
        "mfe": high / entry - 1,
        "mae": low / entry - 1,
    }
