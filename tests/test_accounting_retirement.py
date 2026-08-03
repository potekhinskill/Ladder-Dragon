from decimal import Decimal
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from bin import retire_legacy_accounting
from ladder_dragon.persistence.migrations import migrate
from ladder_dragon.execution.accounting_retirement import (
    exact_only_schema,
    retire_accounting_schema,
)
from ladder_dragon.execution import tools_stats


def test_retirement_cli_blocks_before_irreversible_database_work(
    tmp_path,
    monkeypatch,
):
    database = tmp_path / "stats.db"
    backup = tmp_path / "stats.before-v3.db"
    database.touch()
    report = SimpleNamespace(
        ready_for_major_removal=True,
        as_dict=lambda: {"ready_for_major_removal": True},
    )
    mutations = []
    monkeypatch.setattr(
        retire_legacy_accounting,
        "audit_compatibility",
        lambda *args, **kwargs: report,
    )
    monkeypatch.setattr(
        retire_legacy_accounting,
        "_require_stopped_runtime",
        lambda: (_ for _ in ()).throw(RuntimeError("runtime is active")),
    )
    monkeypatch.setattr(
        retire_legacy_accounting,
        "retire_accounting_schema",
        lambda *args: mutations.append(args),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "retire_legacy_accounting",
            "--stats-db",
            str(database),
            "--backup",
            str(backup),
            "--apply",
            "--confirm",
            retire_legacy_accounting.CONFIRMATION,
        ],
    )

    with pytest.raises(RuntimeError, match="runtime is active"):
        retire_legacy_accounting.main()

    assert mutations == []
    assert not backup.exists()


def test_exact_only_retirement_is_backed_up_and_runtime_remains_writable(
    tmp_path: Path,
):
    database = tmp_path / "stats.db"
    backup = tmp_path / "stats.before-v3.db"
    migrate(str(database), exact_new_database=False)
    connection = sqlite3.connect(database)
    tools_stats.apply_trade(
        connection,
        "SOLUSDT",
        "BUY",
        Decimal("75.125"),
        Decimal("0.125"),
        trade_id=1,
        commission_asset="USDT",
        commission_amount=Decimal("0.01"),
        commission_quote=Decimal("0.01"),
        commission_value_status="quote",
    )
    connection.close()

    assert retire_accounting_schema(database, backup) is True
    assert backup.is_file()

    connection = sqlite3.connect(database)
    assert exact_only_schema(connection) is True
    assert tools_stats.get_inventory_decimal(connection, "SOLUSDT")[0] == Decimal(
        "0.125"
    )
    assert tools_stats.apply_trade(
        connection,
        "SOLUSDT",
        "SELL",
        Decimal("76.00"),
        Decimal("0.025"),
        trade_id=2,
        commission_asset="USDT",
        commission_amount=Decimal("0.01"),
        commission_quote=Decimal("0.01"),
        commission_value_status="quote",
    ) is True
    assert tools_stats.get_inventory_decimal(connection, "SOLUSDT")[0] == Decimal(
        "0.100"
    )
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    connection.close()

    with sqlite3.connect(backup) as old:
        assert {"price", "qty", "fee_quote"} <= {
            str(row[1]) for row in old.execute("PRAGMA table_info(trades)")
        }
