from datetime import datetime
from decimal import Decimal
import sqlite3
from zoneinfo import ZoneInfo

from bin import daily_trading_digest
from ladder_dragon.execution import tools_stats


TZ = ZoneInfo("Asia/Almaty")


def _timestamp(day: int, hour: int = 12) -> int:
    return int(datetime(2026, 7, day, hour, tzinfo=TZ).timestamp() * 1000)


def test_digest_uses_complete_periods_exact_fifo_and_english_only(tmp_path):
    db = tmp_path / "stats.db"
    connection = tools_stats.init_db(str(db))
    tools_stats.apply_trade(
        connection, "SOLUSDT", "BUY", "100", "1",
        ts=_timestamp(1), trade_id=1, commission_asset="USDT",
        commission_amount="0.10", commission_quote="0.10",
        commission_value_status="exact",
    )
    tools_stats.apply_trade(
        connection, "SOLUSDT", "SELL", "110", "0.5",
        ts=_timestamp(25), trade_id=2, commission_asset="USDT",
        commission_amount="0.055", commission_quote="0.055",
        commission_value_status="exact",
    )
    connection.close()

    message, key = daily_trading_digest.build_digest(
        db,
        now=datetime(2026, 7, 26, 9, tzinfo=TZ),
        timezone_name="Asia/Almaty",
    )

    assert key == "2026-07-26"
    assert "Yesterday (2026-07-25 → 2026-07-26)" in message
    assert "Realized FIFO net PnL: +4.90 USDT" in message
    assert "Cash flow: +54.95 USDT" in message
    assert "Fees: -0.06 USDT" in message
    assert "Fees: +" not in message
    assert "Fills: 1 (BUY 0 / SELL 1)" in message
    assert not any("\u0400" <= character <= "\u04ff" for character in message)


def test_digest_excludes_incomplete_symbol_without_fabricating_cost_basis(tmp_path):
    db = tmp_path / "stats.db"
    connection = tools_stats.init_db(str(db))
    tools_stats.apply_trade(
        connection, "ETHUSDT", "SELL", "2000", "0.5",
        ts=_timestamp(25), trade_id=2, commission_asset="USDT",
        commission_amount="1", commission_quote="1",
        commission_value_status="exact",
    )
    tools_stats.apply_trade(
        connection, "SOLUSDT", "BUY", "100", "1",
        ts=_timestamp(24), trade_id=3, commission_asset="USDT",
        commission_amount="0.1", commission_quote="0.1",
        commission_value_status="exact",
    )
    tools_stats.apply_trade(
        connection, "SOLUSDT", "SELL", "110", "0.5",
        ts=_timestamp(25), trade_id=4, commission_asset="USDT",
        commission_amount="0.055", commission_quote="0.055",
        commission_value_status="exact",
    )
    connection.close()

    message, _ = daily_trading_digest.build_digest(
        db,
        now=datetime(2026, 7, 26, 9, tzinfo=TZ),
        timezone_name="Asia/Almaty",
    )

    assert "Realized FIFO net PnL: +4.90 USDT" in message
    assert "Fills: 2 (BUY 1 / SELL 1)" in message
    assert "ETHUSDT — incomplete FIFO history" in message
    assert "1000.00 USDT" not in message


def test_successful_delivery_is_idempotent_and_failure_is_retried(tmp_path, monkeypatch):
    db = tmp_path / "stats.db"
    connection = tools_stats.init_db(str(db))
    connection.close()
    state = tmp_path / "digest.json"
    sent = []
    monkeypatch.setattr(
        daily_trading_digest,
        "send_message",
        lambda message: not sent.append(message),
    )
    monkeypatch.setattr(
        daily_trading_digest,
        "_timezone",
        lambda _name: TZ,
    )
    monkeypatch.setattr(
        daily_trading_digest,
        "datetime",
        type(
            "FixedDateTime",
            (),
            {"now": staticmethod(lambda tz=None: datetime(2026, 7, 26, 9, tzinfo=TZ))},
        ),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["daily_trading_digest", "--db", str(db), "--state", str(state)],
    )

    assert daily_trading_digest.main() == 0
    assert daily_trading_digest.main() == 0
    assert len(sent) == 1
    assert state.stat().st_mode & 0o777 == 0o600


def test_fee_with_no_quote_value_blocks_report(tmp_path):
    db = tmp_path / "stats.db"
    connection = tools_stats.init_db(str(db))
    tools_stats.apply_trade(
        connection, "SOLUSDT", "BUY", "100", "1",
        ts=_timestamp(25), trade_id=3, commission_asset="BNB",
        commission_amount="0.001", commission_quote=None,
        commission_value_status="unpriced",
    )
    connection.close()

    with sqlite3.connect(db) as check:
        assert check.execute(
            "SELECT commission_quote_text FROM trades_exact WHERE trade_id=3"
        ).fetchone()[0] is None
    message, _ = daily_trading_digest.build_digest(
        db,
        now=datetime(2026, 7, 26, 9, tzinfo=TZ),
        timezone_name="Asia/Almaty",
    )
    assert "SOLUSDT — unpriced or invalid exact trade data" in message
    assert "Fills: 0 (BUY 0 / SELL 0)" in message


def test_structural_digest_failure_sends_one_deduplicated_warning(
    tmp_path,
    monkeypatch,
):
    db = tmp_path / "stats.db"
    db.write_bytes(b"not sqlite")
    state = tmp_path / "digest.json"
    sent = []
    monkeypatch.setattr(
        daily_trading_digest,
        "send_message",
        lambda message: not sent.append(message),
    )
    monkeypatch.setattr(
        daily_trading_digest,
        "_timezone",
        lambda _name: TZ,
    )
    monkeypatch.setattr(
        daily_trading_digest,
        "datetime",
        type(
            "FixedDateTime",
            (),
            {
                "now": staticmethod(
                    lambda tz=None: datetime(2026, 7, 26, 9, tzinfo=TZ)
                )
            },
        ),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["daily_trading_digest", "--db", str(db), "--state", str(state)],
    )

    assert daily_trading_digest.main() == 2
    assert daily_trading_digest.main() == 2
    assert len(sent) == 1
    assert "daily trading digest BLOCKED" in sent[0]
    assert "No financial figures were sent." in sent[0]


def test_missing_database_sends_one_deduplicated_warning(
    tmp_path,
    monkeypatch,
):
    state = tmp_path / "digest.json"
    sent = []
    monkeypatch.setattr(
        daily_trading_digest,
        "send_message",
        lambda message: not sent.append(message),
    )
    monkeypatch.setattr(daily_trading_digest, "_timezone", lambda _name: TZ)
    monkeypatch.setattr(
        daily_trading_digest,
        "datetime",
        type(
            "FixedDateTime",
            (),
            {
                "now": staticmethod(
                    lambda tz=None: datetime(2026, 7, 26, 9, tzinfo=TZ)
                )
            },
        ),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "daily_trading_digest",
            "--db",
            str(tmp_path / "missing.db"),
            "--state",
            str(state),
        ],
    )

    assert daily_trading_digest.main() == 2
    assert daily_trading_digest.main() == 2
    assert len(sent) == 1
    assert "Reason: FileNotFoundError" in sent[0]


def test_fifo_old_basis_is_not_cycle_profit(tmp_path, monkeypatch):
    sentinel = "private-digest-fixture"
    monkeypatch.setenv("BINANCE_API_KEY", sentinel)
    db = tmp_path / "stats.db"
    connection = tools_stats.init_db(str(db))
    for tid, day, side, price, status in (
        (1, 1, "BUY", "230", "legacy"),
        (2, 25, "BUY", "100", "exact"),
        (3, 25, "SELL", "99", "exact"),
    ):
        tools_stats.apply_trade(
            connection, "SOLUSDT", side, price, "1", ts=_timestamp(day),
            trade_id=tid, commission_value_status=status,
        )
    connection.close()
    message, _ = daily_trading_digest.build_digest(
        db, now=datetime(2026, 7, 26, 9, tzinfo=TZ), timezone_name="Asia/Almaty",
    )
    yesterday = message.split("Last 7 complete days")[0]
    assert "Realized FIFO net PnL: -131.00 USDT" in yesterday
    assert "Cash flow: -1.00 USDT" in yesterday
    assert "FIFO cost of sold inventory: +230.00 USDT" in yesterday
    assert "Cost from purchases before this period: +230.00 USDT" in yesterday
    assert "LEGACY included" in yesterday
    assert "Closed-cycle net PnL: UNAVAILABLE" in message
    assert "do not subtract them again" in message
    assert "only from exact" not in message
    assert sentinel not in message


def test_fifo_quality_tracks_consumed_lots_and_period_boundaries(tmp_path):
    db = tmp_path / "stats.db"
    connection = tools_stats.init_db(str(db))
    for tid, day, side, qty, status in (
        (1, 24, "BUY", "1", "exact"),
        (2, 25, "BUY", "1", "exact"),
        (3, 25, "SELL", "1.5", "exact"),
        (4, 26, "BUY", "1", "legacy"),
    ):
        tools_stats.apply_trade(
            connection, "SOLUSDT", side, "100", qty, ts=_timestamp(day),
            trade_id=tid, commission_value_status=status,
        )
    connection.close()
    message, _ = daily_trading_digest.build_digest(
        db, now=datetime(2026, 7, 26, 9, tzinfo=TZ), timezone_name="Asia/Almaty",
    )
    yesterday, week = message.split("Last 7 complete days")
    assert "Cost from purchases before this period: +100.00 USDT" in yesterday
    assert "Cost from purchases before this period: 0.00 USDT" in week
    assert "FIFO cost of sold inventory: +150.00 USDT" in yesterday
    assert "LEGACY included" not in message
    assert "exchange history not independently verified" in message


def test_excluded_symbol_cannot_contribute_basis_or_quality(tmp_path):
    db = tmp_path / "stats.db"
    connection = tools_stats.init_db(str(db))
    for tid, side, qty in ((1, "BUY", "1"), (2, "SELL", "2")):
        tools_stats.apply_trade(
            connection, "SOLUSDT", side, "100", qty, ts=_timestamp(25),
            trade_id=tid, commission_value_status="legacy",
        )
    connection.close()
    message, _ = daily_trading_digest.build_digest(
        db, now=datetime(2026, 7, 26, 9, tzinfo=TZ), timezone_name="Asia/Almaty",
    )
    assert "SOLUSDT — incomplete FIFO history" in message
    assert "FIFO cost of sold inventory: 0.00 USDT" in message
    assert "LEGACY included" not in message
