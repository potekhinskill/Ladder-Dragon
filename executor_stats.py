"""Импорт сделок и точная оценка комиссий для исполнителя."""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Any, Callable, MutableMapping, Optional, Tuple

import requests


def commission_quote_value(
    symbol: str,
    commission_asset: str,
    commission_amount: Decimal,
    trade_price: Decimal,
    trade_time_ms: int,
    *,
    symbol_assets: Callable[[str], Tuple[str, str]],
    public_get: Callable[..., Any],
    cache: MutableMapping[Tuple[str, str, int], Decimal],
) -> Tuple[Optional[Decimal], str]:
    """Оценить комиссию Binance в quote-активе по времени сделки."""
    base, quote = symbol_assets(symbol)
    asset = commission_asset.strip().upper()
    if commission_amount <= 0:
        return Decimal("0"), "none"
    if asset == quote.upper():
        return commission_amount, "exact"
    if asset == base.upper():
        return commission_amount * trade_price, "exact"

    minute_ms = int(trade_time_ms // 60_000 * 60_000)
    key = (asset, quote.upper(), minute_ms)
    cached = cache.get(key)
    if cached is not None:
        return commission_amount * cached, "converted"

    # Для BNB и других третьих активов ищем прямую или обратную минутную пару
    # на момент сделки. Текущая цена исказила бы исторический PnL.
    for pair, inverse in ((asset + quote.upper(), False), (quote.upper() + asset, True)):
        try:
            candles = public_get(
                "/api/v3/klines",
                {"symbol": pair, "interval": "1m", "startTime": minute_ms, "limit": 1},
            )
            if not isinstance(candles, list) or not candles:
                continue
            close = Decimal(str(candles[0][4]))
            if close <= 0:
                continue
            conversion = Decimal("1") / close if inverse else close
            cache[key] = conversion
            return commission_amount * conversion, "converted"
        except (ArithmeticError, IndexError, TypeError, ValueError, requests.RequestException):
            continue
    return None, "unpriced"


def poll_mytrades_once(
    symbol: str,
    *,
    connection: sqlite3.Connection,
    stats: Any,
    signed_request: Callable[..., Any],
    commission_value: Callable[..., Tuple[Optional[Decimal], str]],
    logger: Callable[[str], None],
    on_fill: Callable[[dict], None] | None = None,
) -> None:
    """Импортировать новую порцию /myTrades, не продвигаясь мимо неизвестной комиссии."""
    last_id = None
    try:
        last_id = stats.get_last_trade_id(connection, symbol)
    except Exception as exc:
        logger(f"[STATS] get_last_trade_id error: {exc}")

    params = {"symbol": symbol, "limit": 1000}
    if last_id is not None:
        params["fromId"] = int(last_id) + 1
    try:
        trades = signed_request("GET", "/api/v3/myTrades", params) or []
    except Exception as exc:
        logger(f"[STATS] myTrades error: {exc}")
        return
    if not isinstance(trades, list) or not trades:
        return

    # Курсор обновляется только после полностью оценённой сделки. Иначе запись
    # с неизвестной комиссией была бы навсегда пропущена следующим опросом.
    max_id = last_id or -1
    for trade in trades:
        try:
            trade_id = int(trade.get("id"))
            side = "BUY" if trade.get("isBuyer") else "SELL"
            price = Decimal(str(trade.get("price")))
            quantity = Decimal(str(trade.get("qty")))
            timestamp = int(trade.get("time"))
            commission = Decimal(str(trade.get("commission", "0") or "0"))
            commission_asset = str(trade.get("commissionAsset", "")).upper()
            fee_quote, fee_status = commission_value(
                symbol, commission_asset, commission, price, timestamp
            )
            try:
                stats.apply_trade(
                    connection,
                    symbol,
                    side,
                    price,
                    quantity,
                    fee_quote=fee_quote or Decimal("0"),
                    ts=timestamp,
                    trade_id=trade_id,
                    gross_qty=quantity,
                    commission_asset=commission_asset,
                    commission_amount=commission,
                    commission_quote=fee_quote,
                    commission_value_status=fee_status,
                )
            except sqlite3.OperationalError as exc:
                if "locked" in str(exc).lower():
                    logger("[STATS] skip: database is locked")
                    break
                logger(f"[STATS] apply_trade error: {exc}")
                continue
            if fee_status == "unpriced":
                logger(
                    f"[STATS] {symbol} trade_id={trade_id}: "
                    f"{commission_asset or 'unknown'} commission is unpriced; "
                    "importer will retry before advancing"
                )
                break
            if on_fill is not None:
                on_fill({
                    "trade_id": trade_id, "symbol": symbol, "side": side,
                    "order_id": trade.get("orderId"),
                    "price": price, "qty": quantity, "fee_quote": fee_quote or Decimal("0"),
                    "commission_asset": commission_asset, "commission_amount": commission,
                    "ts": timestamp,
                })
            max_id = max(max_id, trade_id)
        except Exception as exc:
            logger(f"[STATS] parse trade error: {exc}")

    if max_id != (last_id or -1):
        try:
            stats.set_last_trade_id(connection, symbol, int(max_id))
        except Exception as exc:
            logger(f"[STATS] set_last_trade_id error: {exc}")
