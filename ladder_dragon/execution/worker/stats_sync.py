# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: describe worker statistics synchronization state explicitly.

"""Worker statistics synchronization service and contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, MutableMapping


@dataclass(frozen=True)
class StatsSyncConfig:
    """Validated, immutable worker statistics configuration."""

    enabled: bool
    database_path: str

    @property
    def active(self) -> bool:
        return self.enabled and bool(self.database_path.strip())


def _runtime_dependency(runtime: Mapping[str, object], name: str) -> Any:
    """Resolve one explicit worker adapter for statistics synchronization."""
    try:
        return runtime[name]
    except KeyError as exc:
        raise RuntimeError(
            f"statistics runtime dependency is unavailable: {name}"
        ) from exc


def sync_account_trades(
    symbol: str, *, runtime: MutableMapping[str, object]
) -> None:
    """Synchronize fills idempotently before advancing the durable cursor."""
    Decimal = _runtime_dependency(runtime, 'Decimal')
    STATS_CON = _runtime_dependency(runtime, 'STATS_CON')
    STATS_DB = _runtime_dependency(runtime, 'STATS_DB')
    STATS_ENABLE = _runtime_dependency(runtime, 'STATS_ENABLE')
    TOOLS_STATS = _runtime_dependency(runtime, 'TOOLS_STATS')
    _commission_quote_value = _runtime_dependency(runtime, '_commission_quote_value')
    _order_journal = _runtime_dependency(runtime, '_order_journal')
    _signed_request = _runtime_dependency(runtime, '_signed_request')
    _stats_init_if_needed = _runtime_dependency(runtime, '_stats_init_if_needed')
    dbg = _runtime_dependency(runtime, 'dbg')
    ensure_lots_schema = _runtime_dependency(runtime, 'ensure_lots_schema')
    get_order = _runtime_dependency(runtime, 'get_order')
    log = _runtime_dependency(runtime, 'log')
    os = _runtime_dependency(runtime, 'os')
    poll_mytrades_once = _runtime_dependency(runtime, 'poll_mytrades_once')
    requests = _runtime_dependency(runtime, 'requests')
    sqlite3 = _runtime_dependency(runtime, 'sqlite3')
    sync_exchange_fill = _runtime_dependency(runtime, 'sync_exchange_fill')
    if not (STATS_ENABLE and STATS_DB):
        return
    _stats_init_if_needed()
    # Initialization mutates the worker-owned connection slots. Refresh them
    # before evaluating availability or constructing callbacks.
    STATS_CON = _runtime_dependency(runtime, 'STATS_CON')
    TOOLS_STATS = _runtime_dependency(runtime, 'TOOLS_STATS')
    if STATS_CON is None or TOOLS_STATS is None:
        return
    def on_fill(fill: dict) -> None:
        """Handle on fill."""
        try:
            ensure_lots_schema(STATS_CON)
            sync_exchange_fill(STATS_CON, fill)
            STATS_CON.commit()
        except (
            sqlite3.Error,
            ValueError,
            ArithmeticError,
            RuntimeError,
        ) as exc:
            try:
                STATS_CON.rollback()
            except sqlite3.Error as rollback_exc:
                log(
                    f"[LOTS] {symbol} rollback failed: "
                    f"{type(rollback_exc).__name__}"
                )
                raise
            log(f"[LOTS] {symbol} fill sync failed: {exc}")
        # Close promotion evidence only when the SELL fill maps to a persisted,
        # exchange-verified OCO leg and Binance confirms the whole leg FILLED.
        if fill["side"] == "SELL" and fill.get("order_id") is not None:
            try:
                journal = _order_journal()
                match = (
                    journal.protection_for_leg_order_id(
                        int(fill["order_id"]),
                        symbol=symbol,
                    )
                    if journal is not None
                    else None
                )
                if match is not None:
                    protection, leg_type = match
                    exchange_order = get_order(symbol, int(fill["order_id"]))
                    if not isinstance(exchange_order, dict):
                        raise RuntimeError("OCO exit state is unavailable")
                    if str(exchange_order.get("status") or "").upper() == "FILLED":
                        exit_reason = "STOP" if "STOP" in leg_type else "TP"
                        journal.mark_exact_lifecycle_closed(
                            protection_client_order_id=protection.client_order_id,
                            exit_order_id=int(fill["order_id"]),
                            exit_reason=exit_reason,
                        )
                        log(
                            f"[LIFECYCLE-CLOSED] {symbol} parent="
                            f"{protection.parent_client_order_id} exit={exit_reason} "
                            f"order={int(fill['order_id'])}"
                        )
            except (
                KeyError,
                TypeError,
                ValueError,
                RuntimeError,
                OSError,
                sqlite3.Error,
                requests.RequestException,
            ) as exc:
                log(
                    f"[LIFECYCLE-PENDING] {symbol} order={fill.get('order_id')} "
                    f"reason={type(exc).__name__}"
                )
        # AI DB is optional: missing AI must not block the trading ledger.
        try:
            ai_db = os.getenv("AI_DECISIONS_DB", "").strip()
            if ai_db:
                from ladder_dragon.ai.context.runtime import AdvisorDecisionStore
                store = AdvisorDecisionStore(ai_db)
                order_id = fill.get("order_id")
                mapping = (
                    store.order_link_for_exchange_order(order_id)
                    if order_id is not None else None
                )
                if mapping is None:
                    store.record_unresolved_fill(
                        symbol=symbol, side=fill["side"], price=fill["price"],
                        qty=fill["qty"], fee_quote=fill["fee_quote"],
                        ts=int(fill["ts"] / 1000), order_id=order_id,
                        trade_id=fill.get("trade_id"),
                        reason="exchange_order_id_not_mapped_to_decision",
                    )
                    dbg(
                        f"[AI-FILL] {symbol} unresolved order_id={order_id}; "
                        "excluded from AI PnL"
                    )
                else:
                    decision_id = mapping["decision_id"]
                    client_order_id = mapping["client_order_id"]
                    leg_type = mapping["leg_type"]
                    expected_price = Decimal(str(
                        mapping.get("expected_price_text") or "0"
                    ))
                    fill_price = Decimal(str(fill["price"]))
                    fill_qty = Decimal(str(fill["qty"]))
                    slippage_quote = Decimal("0")
                    if expected_price and expected_price > 0:
                        slippage_quote = (
                            (fill_price - expected_price) * fill_qty
                            if fill["side"] == "BUY"
                            else (expected_price - fill_price) * fill_qty
                        )
                    normalized_leg = leg_type.upper()
                    exit_reason = (
                        "STOP" if "STOP" in normalized_leg
                        else "TP" if fill["side"] == "SELL" and normalized_leg
                        else ""
                    )
                    store.record_fill(
                        decision_id, symbol=symbol, side=fill["side"],
                        price=fill_price, qty=fill_qty,
                        fee_quote=fill["fee_quote"],
                        ts=int(fill["ts"] / 1000), order_id=order_id,
                        trade_id=fill.get("trade_id"),
                        client_order_id=client_order_id,
                        leg_type=leg_type, exit_reason=exit_reason,
                        slippage_quote=(
                            slippage_quote
                            + Decimal(str(fill.get("slippage_quote", "0") or "0"))
                        ),
                    )
                    # Update realized_execution after every actual fill. The record
                    # stays open until the final SELL; only after the last TP/STOP
                    # does it become a source of real PnL and eligible for RAG.
                    store.evaluate_execution(decision_id)
        except (sqlite3.Error, ValueError, OSError) as exc:
            dbg(f"[AI-FILL] {symbol} sync skipped: {exc}")

    poll_mytrades_once(
        symbol,
        connection=STATS_CON,
        stats=TOOLS_STATS,
        signed_request=_signed_request,
        commission_value=_commission_quote_value,
        logger=log,
        on_fill=on_fill,
    )
