"""Безопасные агрегаты истории и рынка для AI-рекомендателя.

Модуль не передаёт LLM сырые сделки, идентификаторы заявок, полный баланс или
стакан. Вместо этого рассчитываются ограниченные числовые признаки, а решения
AI сохраняются отдельно и позднее оцениваются по движению цены.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from trade_accounting import TradeExecution, replay_average_cost


ZERO = Decimal("0")
HORIZONS_SEC = (900, 3600, 14_400)


@dataclass(frozen=True)
class TradeFeatures:
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
                       COALESCE(NULLIF(commission_quote, ''), CAST(fee_quote AS TEXT)),
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
                "DELETE FROM ai_decisions WHERE created_at < ?",
                (int(time.time()) - 365 * 86_400,),
            )

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
        now: int | None = None,
    ) -> str:
        decision_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO ai_decisions(
                    decision_id, symbol, created_at, price,
                    deterministic_mode, recommended_mode, width_scale,
                    cap_scale, confidence, applied
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    decision_id, symbol.upper(), int(now or time.time()), price,
                    deterministic_mode, recommended_mode, width_scale,
                    cap_scale, confidence, int(applied),
                ),
            )
        return decision_id

    def settle(
        self,
        symbol: str,
        current_price: float,
        *,
        now: int | None = None,
    ) -> int:
        now = int(now or time.time())
        updated = 0
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT decision_id, created_at, price,
                       return_15m, return_1h, return_4h
                FROM ai_decisions
                WHERE symbol=? AND created_at>=?
                  AND (return_15m IS NULL OR return_1h IS NULL OR return_4h IS NULL)
                """,
                (symbol.upper(), now - 86_400),
            ).fetchall()
            for decision_id, created_at, price, *existing in rows:
                if price <= 0:
                    continue
                changes: dict[str, float] = {}
                for index, (column, horizon) in enumerate(zip(
                    ("return_15m", "return_1h", "return_4h"),
                    HORIZONS_SEC,
                )):
                    if existing[index] is None and now - created_at >= horizon:
                        changes[column] = current_price / price - 1
                if not changes:
                    continue
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
        return AdvisorPerformance(s15, a15, s1h, a1h, s4h, a4h)


def directional_success(mode: str, market_return: float) -> int:
    normalized = mode.upper()
    threshold = 0.001
    if normalized == "UP":
        return int(market_return > threshold)
    if normalized == "DOWN":
        return int(market_return < -threshold)
    return int(abs(market_return) <= threshold)
