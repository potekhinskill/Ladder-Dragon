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
    assert "Fills: 1 (BUY 0 / SELL 1)" in message
    assert not any("\u0400" <= character <= "\u04ff" for character in message)


def test_digest_blocks_incomplete_fifo_history(tmp_path):
    db = tmp_path / "stats.db"
    connection = tools_stats.init_db(str(db))
    tools_stats.apply_trade(
        connection, "SOLUSDT", "SELL", "110", "0.5",
        ts=_timestamp(25), trade_id=2, commission_asset="USDT",
        commission_amount="0.055", commission_quote="0.055",
        commission_value_status="exact",
    )
    connection.close()

    try:
        daily_trading_digest.build_digest(
            db,
            now=datetime(2026, 7, 26, 9, tzinfo=TZ),
            timezone_name="Asia/Almaty",
        )
    except ValueError as exc:
        assert "incomplete FIFO history" in str(exc)
    else:
        raise AssertionError("incomplete history must block the digest")


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
    try:
        daily_trading_digest.build_digest(
            db,
            now=datetime(2026, 7, 26, 9, tzinfo=TZ),
            timezone_name="Asia/Almaty",
        )
    except Exception as exc:
        assert "unpriced" in str(exc)
    else:
        raise AssertionError("unpriced commission must block the digest")
