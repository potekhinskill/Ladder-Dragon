"""Управление портфельным риском Ladder Dragon по принципу fail-closed.

Модуль намеренно не зависит от Binance HTTP: решения можно воспроизводимо
тестировать на готовых снимках портфеля. Дневные базы equity и halt-маркер
хранятся на диске, поэтому перезапуск супервизора не снимает остановку.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from typing import Iterable, Optional

from trade_accounting import TradeExecution


def money(value: object) -> Decimal:
    """Преобразовать внешнее число в Decimal без наследования шума float."""
    return Decimal(str(value or 0))


@dataclass(frozen=True)
class RiskLimits:
    """Все жёсткие лимиты и пути постоянного состояния circuit breaker."""
    max_daily_loss_usdt: Decimal
    max_start_drawdown_pct: Decimal
    max_peak_drawdown_pct: Decimal
    portfolio_cap_usdt: Decimal
    daily_turnover_cap_usdt: Decimal
    daily_trade_count_cap: int
    daily_buy_cap_usdt: Decimal
    open_order_count_cap: int
    correlated_cap_usdt: Decimal
    reserve_usdt: Decimal
    max_consecutive_losses: int
    cooldown_sec: int
    halt_file: Path
    state_file: Path
    alerts_file: Path

    @classmethod
    def from_env(cls) -> "RiskLimits":
        run_dir = Path(os.getenv("BOT_RUN_DIR", "/run/mybot"))
        return cls(
            max_daily_loss_usdt=money(os.getenv("CB_MAX_DAILY_LOSS_USDT", "100")),
            max_start_drawdown_pct=money(os.getenv("CB_MAX_START_DRAWDOWN_PCT", "0.03")),
            max_peak_drawdown_pct=money(os.getenv("CB_MAX_PEAK_DRAWDOWN_PCT", "0.02")),
            portfolio_cap_usdt=money(os.getenv("RISK_PORTFOLIO_CAP_USDT", "3000")),
            daily_turnover_cap_usdt=money(os.getenv("RISK_DAILY_TURNOVER_CAP_USDT", "5000")),
            daily_trade_count_cap=int(os.getenv("RISK_DAILY_TRADE_COUNT_CAP", "120")),
            daily_buy_cap_usdt=money(os.getenv("RISK_DAILY_BUY_CAP_USDT", "2500")),
            open_order_count_cap=int(os.getenv("RISK_OPEN_ORDER_COUNT_CAP", "30")),
            correlated_cap_usdt=money(os.getenv("RISK_CORRELATED_CAP_USDT", "2500")),
            reserve_usdt=money(os.getenv("RISK_RESERVE_USDT", "300")),
            max_consecutive_losses=int(os.getenv("RISK_MAX_CONSECUTIVE_LOSSES", "4")),
            cooldown_sec=int(os.getenv("RISK_COOLDOWN_SEC", "900")),
            halt_file=Path(os.getenv("CB_HALT_FILE", str(run_dir / "circuit_halt.json"))),
            state_file=Path(os.getenv("CB_STATE_FILE", str(run_dir / "risk_state.json"))),
            alerts_file=Path(os.getenv("CB_ALERTS_FILE", str(run_dir / "risk_alerts.ndjson"))),
        )

    def validate(self) -> None:
        positive = {
            "CB_MAX_DAILY_LOSS_USDT": self.max_daily_loss_usdt,
            "CB_MAX_START_DRAWDOWN_PCT": self.max_start_drawdown_pct,
            "CB_MAX_PEAK_DRAWDOWN_PCT": self.max_peak_drawdown_pct,
            "RISK_PORTFOLIO_CAP_USDT": self.portfolio_cap_usdt,
            "RISK_DAILY_TURNOVER_CAP_USDT": self.daily_turnover_cap_usdt,
            "RISK_DAILY_BUY_CAP_USDT": self.daily_buy_cap_usdt,
            "RISK_CORRELATED_CAP_USDT": self.correlated_cap_usdt,
        }
        for name, value in positive.items():
            if value <= 0:
                raise ValueError(f"{name} must be > 0")
        for name, value in {
            "CB_MAX_START_DRAWDOWN_PCT": self.max_start_drawdown_pct,
            "CB_MAX_PEAK_DRAWDOWN_PCT": self.max_peak_drawdown_pct,
        }.items():
            if value >= 1:
                raise ValueError(f"{name} must be a fraction between 0 and 1")
        if self.reserve_usdt < 0:
            raise ValueError("RISK_RESERVE_USDT must be >= 0")
        if self.daily_trade_count_cap <= 0 or self.open_order_count_cap <= 0:
            raise ValueError("order/trade count caps must be > 0")
        if self.max_consecutive_losses <= 0 or self.cooldown_sec < 0:
            raise ValueError("loss streak must be > 0 and cooldown must be >= 0")


@dataclass(frozen=True)
class RiskSnapshot:
    """Атомарный снимок портфеля, ордеров и дневной торговой активности."""
    equity_usdt: Decimal
    exposure_usdt: Decimal
    free_usdt: Decimal
    daily_turnover_usdt: Decimal = Decimal("0")
    daily_buy_usdt: Decimal = Decimal("0")
    daily_trade_count: int = 0
    open_order_count: int = 0
    correlated_exposure_usdt: Decimal = Decimal("0")
    consecutive_losses: int = 0


@dataclass(frozen=True)
class RiskDecision:
    """Результат проверки: полный halt либо запрет только на новые BUY."""
    halted: bool
    buy_blocked: bool
    reasons: tuple[str, ...] = ()
    daily_loss_usdt: Decimal = Decimal("0")
    start_drawdown_pct: Decimal = Decimal("0")
    peak_drawdown_pct: Decimal = Decimal("0")


@dataclass
class RiskState:
    day: str
    start_equity_usdt: str
    peak_equity_usdt: str
    last_equity_usdt: str
    halted: bool = False
    halt_reasons: list[str] = field(default_factory=list)
    halted_at: Optional[str] = None
    cooldown_until: float = 0.0
    cooldown_reason: str = ""


def _utc_day(now: Optional[float] = None) -> str:
    return datetime.fromtimestamp(now or time.time(), timezone.utc).date().isoformat()


def _atomic_json(path: Path, payload: dict) -> None:
    # Состояние нельзя оставлять частично записанным: сначала fsync временного
    # файла, затем атомарная замена целевого JSON.
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def create_manual_halt(
    reason: str,
    *,
    limits: Optional[RiskLimits] = None,
    now: Optional[float] = None,
    metadata: Optional[dict] = None,
) -> Path:
    """Создать постоянный halt при сбое исполнения вне RiskManager."""
    limits = limits or RiskLimits.from_env()
    now = float(now or time.time())
    reasons = [str(reason)]
    try:
        current = json.loads(limits.halt_file.read_text(encoding="utf-8"))
        reasons = list(dict.fromkeys([*(current.get("reasons") or []), *reasons]))
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
        pass
    payload = {
        "halted_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "reasons": reasons,
        "manual_reset_required": True,
        "cooldown_until": now + limits.cooldown_sec,
    }
    if metadata:
        payload["metadata"] = metadata
    _atomic_json(limits.halt_file, payload)
    limits.alerts_file.parent.mkdir(parents=True, exist_ok=True)
    alert = {
        "ts": payload["halted_at"],
        "event": "execution_safety_halt",
        "reasons": reasons,
        "metadata": metadata or {},
    }
    with limits.alerts_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(alert, ensure_ascii=False, sort_keys=True) + "\n")
    return limits.halt_file


class RiskManager:
    """Вычисляет риски и сохраняет состояние между циклами и рестартами."""
    def __init__(self, limits: RiskLimits):
        limits.validate()
        self.limits = limits

    def _load(self, equity: Decimal, now: float) -> RiskState:
        try:
            raw = json.loads(self.limits.state_file.read_text(encoding="utf-8"))
            state = RiskState(**raw)
        except (FileNotFoundError, json.JSONDecodeError, TypeError, OSError):
            state = RiskState(_utc_day(now), str(equity), str(equity), str(equity))
        if state.day != _utc_day(now):
            # Новый день обновляет базы equity, но не снимает circuit halt:
            # разблокировка всегда требует осознанного ручного reset.
            state.day = _utc_day(now)
            state.start_equity_usdt = str(equity)
            state.peak_equity_usdt = str(equity)
            state.last_equity_usdt = str(equity)
        if self.limits.halt_file.exists():
            state.halted = True
            try:
                marker = json.loads(self.limits.halt_file.read_text(encoding="utf-8"))
                state.halt_reasons = list(marker.get("reasons") or state.halt_reasons)
                state.halted_at = marker.get("halted_at") or state.halted_at
            except (json.JSONDecodeError, OSError):
                if not state.halt_reasons:
                    state.halt_reasons = ["halt marker exists"]
        return state

    def _save(self, state: RiskState) -> None:
        _atomic_json(self.limits.state_file, asdict(state))

    def _alert(self, event: str, reasons: Iterable[str], snapshot: RiskSnapshot) -> None:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "reasons": list(reasons),
            "equity_usdt": str(snapshot.equity_usdt),
            "exposure_usdt": str(snapshot.exposure_usdt),
        }
        self.limits.alerts_file.parent.mkdir(parents=True, exist_ok=True)
        with self.limits.alerts_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    def trip(self, state: RiskState, reasons: Iterable[str], snapshot: RiskSnapshot, now: float) -> None:
        # Halt записывается раньше уведомления. Даже если webhook или лог недоступен,
        # следующий запуск увидит маркер и не возобновит покупки.
        reasons = list(dict.fromkeys(reasons))
        state.halted = True
        state.halt_reasons = reasons
        state.halted_at = datetime.fromtimestamp(now, timezone.utc).isoformat()
        state.cooldown_until = max(state.cooldown_until, now + self.limits.cooldown_sec)
        marker = {
            "halted_at": state.halted_at,
            "reasons": reasons,
            "manual_reset_required": True,
            "cooldown_until": state.cooldown_until,
            "equity_usdt": str(snapshot.equity_usdt),
        }
        _atomic_json(self.limits.halt_file, marker)
        self._alert("circuit_breaker", reasons, snapshot)

    def evaluate(self, snapshot: RiskSnapshot, now: Optional[float] = None) -> RiskDecision:
        """Проверить circuit breaker и мягкие лимиты новых BUY."""
        now = float(now or time.time())
        state = self._load(snapshot.equity_usdt, now)
        start = money(state.start_equity_usdt)
        if start <= 0 and snapshot.equity_usdt > 0:
            start = snapshot.equity_usdt
            state.start_equity_usdt = str(start)
            state.peak_equity_usdt = str(start)
        peak = max(money(state.peak_equity_usdt), snapshot.equity_usdt)
        state.peak_equity_usdt = str(peak)
        state.last_equity_usdt = str(snapshot.equity_usdt)

        daily_loss = max(Decimal("0"), start - snapshot.equity_usdt)
        start_dd = (daily_loss / start) if start > 0 else Decimal("0")
        peak_loss = max(Decimal("0"), peak - snapshot.equity_usdt)
        peak_dd = (peak_loss / peak) if peak > 0 else Decimal("0")

        # Нарушение equity-лимитов — необратимый автоматикой circuit halt.
        circuit_reasons: list[str] = []
        if daily_loss >= self.limits.max_daily_loss_usdt:
            circuit_reasons.append(
                f"daily equity loss {daily_loss:.2f} USDT >= {self.limits.max_daily_loss_usdt:.2f}"
            )
        if start_dd >= self.limits.max_start_drawdown_pct:
            circuit_reasons.append(
                f"start-equity drawdown {start_dd:.4%} >= {self.limits.max_start_drawdown_pct:.4%}"
            )
        if peak_dd >= self.limits.max_peak_drawdown_pct:
            circuit_reasons.append(
                f"peak-equity drawdown {peak_dd:.4%} >= {self.limits.max_peak_drawdown_pct:.4%}"
            )

        if circuit_reasons and not state.halted:
            self.trip(state, circuit_reasons, snapshot, now)

        # Остальные лимиты блокируют новые BUY, но не запрещают сопровождать
        # существующие позиции и защитные SELL/OCO.
        block_reasons: list[str] = []
        if snapshot.exposure_usdt >= self.limits.portfolio_cap_usdt:
            block_reasons.append(
                f"portfolio exposure {snapshot.exposure_usdt:.2f} >= {self.limits.portfolio_cap_usdt:.2f} USDT"
            )
        if snapshot.daily_turnover_usdt >= self.limits.daily_turnover_cap_usdt:
            block_reasons.append("daily turnover cap reached")
        if snapshot.daily_buy_usdt >= self.limits.daily_buy_cap_usdt:
            block_reasons.append("daily BUY notional cap reached")
        if snapshot.daily_trade_count >= self.limits.daily_trade_count_cap:
            block_reasons.append("daily trade count cap reached")
        if snapshot.open_order_count >= self.limits.open_order_count_cap:
            block_reasons.append("open order count cap reached")
        if snapshot.correlated_exposure_usdt >= self.limits.correlated_cap_usdt:
            block_reasons.append("correlated asset exposure cap reached")
        if snapshot.free_usdt <= self.limits.reserve_usdt:
            block_reasons.append("protected USDT reserve reached")
        if snapshot.consecutive_losses >= self.limits.max_consecutive_losses:
            block_reasons.append("consecutive loss limit reached")
        if state.cooldown_until > now:
            block_reasons.append(
                f"cooldown active until {datetime.fromtimestamp(state.cooldown_until, timezone.utc).isoformat()}"
            )

        self._save(state)
        reasons = tuple(state.halt_reasons if state.halted else block_reasons)
        return RiskDecision(
            halted=state.halted,
            buy_blocked=state.halted or bool(block_reasons),
            reasons=reasons,
            daily_loss_usdt=daily_loss,
            start_drawdown_pct=start_dd,
            peak_drawdown_pct=peak_dd,
        )

    def start_cooldown(self, reason: str, seconds: Optional[int] = None, now: Optional[float] = None) -> None:
        now = float(now or time.time())
        state = self._load(Decimal("0"), now)
        state.cooldown_until = max(state.cooldown_until, now + int(seconds or self.limits.cooldown_sec))
        state.cooldown_reason = reason
        self._save(state)

    def reset(self, *, force: bool = False, now: Optional[float] = None) -> None:
        now = float(now or time.time())
        state = self._load(Decimal("0"), now)
        if not force and state.cooldown_until > now:
            until = datetime.fromtimestamp(state.cooldown_until, timezone.utc).isoformat()
            raise RuntimeError(f"cooldown is active until {until}; use --force only after manual review")
        try:
            self.limits.halt_file.unlink()
        except FileNotFoundError:
            pass
        state.halted = False
        state.halt_reasons = []
        state.halted_at = None
        state.cooldown_until = 0.0
        state.cooldown_reason = ""
        self._save(state)


def load_daily_trade_metrics(db_path: str, symbols: Iterable[str], now: Optional[float] = None) -> dict:
    """Прочитать дневные метрики из ledger; при неполных данных упасть закрыто."""
    now = float(now or time.time())
    start = int(datetime.fromtimestamp(now, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
    wanted = [s.upper() for s in symbols]
    placeholders = ",".join("?" for _ in wanted)
    if not wanted:
        raise ValueError("at least one symbol is required")
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5) as con:
        columns = {str(row[1]) for row in con.execute("PRAGMA table_info(trades)")}
        exact = {
            "price_text", "gross_qty", "net_qty", "commission_asset",
            "commission_amount", "commission_quote", "commission_value_status",
        }.issubset(columns)
        if exact:
            accounting_columns = """
                COALESCE(NULLIF(price_text, ''), CAST(price AS TEXT)),
                COALESCE(NULLIF(gross_qty, ''), CAST(qty AS TEXT)),
                COALESCE(NULLIF(net_qty, ''), CAST(qty AS TEXT)),
                COALESCE(commission_asset, ''),
                COALESCE(NULLIF(commission_amount, ''), '0'),
                CASE WHEN commission_value_status = 'unpriced' THEN NULL
                     ELSE COALESCE(commission_quote, CAST(fee_quote AS TEXT)) END,
                COALESCE(NULLIF(commission_value_status, ''), 'legacy')
            """
        else:
            accounting_columns = """
                CAST(price AS TEXT), CAST(qty AS TEXT), CAST(qty AS TEXT),
                '', '0', CAST(COALESCE(fee_quote, 0) AS TEXT), 'legacy'
            """
        daily_sql = f"""
            SELECT symbol, side, {accounting_columns},
                   CASE WHEN ts > 1000000000000 THEN CAST(ts/1000 AS INTEGER) ELSE ts END AS ts_s
            FROM trades
            WHERE symbol IN ({placeholders})
              AND (CASE WHEN ts > 1000000000000 THEN CAST(ts/1000 AS INTEGER) ELSE ts END) >= ?
            ORDER BY ts_s, id
        """
        history_sql = f"""
            SELECT symbol, side, {accounting_columns},
                   CASE WHEN ts > 1000000000000 THEN CAST(ts/1000 AS INTEGER) ELSE ts END AS ts_s
            FROM trades
            WHERE symbol IN ({placeholders})
            ORDER BY ts_s, id
        """
        rows = con.execute(daily_sql, (*wanted, start)).fetchall()
        history = con.execute(history_sql, wanted).fetchall()

    def execution(row: tuple) -> TradeExecution:
        symbol, side, price, gross, net, asset, amount, quote_value, status, _ = row
        return TradeExecution.create(
            symbol=symbol,
            side=side,
            price=price,
            gross_qty=gross,
            net_qty=net,
            commission_asset=asset,
            commission_amount=amount,
            commission_quote=quote_value,
            commission_value_status=status,
        )

    daily_executions = [execution(row) for row in rows]
    # Неоценённая комиссия BNB/третьего актива обязана остановить telemetry:
    # молчаливое занижение расходов опаснее временной блокировки BUY.
    for trade in daily_executions:
        trade.valued_commission()
    turnover = sum((trade.price * trade.gross_qty for trade in daily_executions), Decimal("0"))
    buys = sum(
        (trade.price * trade.gross_qty for trade in daily_executions if trade.side == "BUY"),
        Decimal("0"),
    )

    # Для серии убытков восстанавливаем среднюю себестоимость по всей истории,
    # а не только по сделкам текущего дня.
    inventory: dict[str, tuple[Decimal, Decimal]] = {}
    sell_results: list[Decimal] = []
    for row in history:
        trade = execution(row)
        qty, avg = inventory.get(trade.symbol, (Decimal("0"), Decimal("0")))
        if trade.side == "BUY":
            new_qty = qty + trade.net_qty
            avg = ((avg * qty) + trade.buy_cost_quote()) / new_qty if new_qty > 0 else Decimal("0")
            qty = new_qty
        else:
            used = min(qty, trade.net_qty)
            ratio = used / trade.net_qty if trade.net_qty > 0 else Decimal("0")
            sell_results.append(trade.sell_proceeds_quote() * ratio - avg * used)
            qty -= used
            if qty <= 0:
                qty, avg = Decimal("0"), Decimal("0")
        inventory[trade.symbol] = (qty, avg)
    streak = 0
    for result in reversed(sell_results):
        if result < 0:
            streak += 1
        else:
            break
    return {
        "daily_turnover_usdt": turnover,
        "daily_buy_usdt": buys,
        "daily_trade_count": len(rows),
        "consecutive_losses": streak,
    }
