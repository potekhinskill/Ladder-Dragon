import sqlite3
from decimal import Decimal

import pytest

from ladder_dragon.execution.cost_basis_import import (
    CostBasisImportPlan,
    apply_cost_basis_plan,
    build_cost_basis_plan,
    read_plan,
    write_plan,
)
from ladder_dragon.execution.inventory_lots import add_lot, cost_basis_coverage
from ladder_dragon.execution import tools_stats
from bin import import_legacy_cost_basis


def trade(
    trade_id,
    side,
    price,
    qty,
    *,
    commission="0",
    commission_asset="USDT",
    commission_quote=None,
):
    row = {
        "id": trade_id,
        "orderId": 10_000 + trade_id,
        "time": 1_700_000_000_000 + trade_id,
        "isBuyer": side == "BUY",
        "price": str(price),
        "qty": str(qty),
        "commission": str(commission),
        "commissionAsset": commission_asset,
    }
    if commission_quote is not None:
        row["commissionQuote"] = str(commission_quote)
        row["commissionValueStatus"] = "converted"
    return row


def covered_plan(created_at=100):
    rows = [
        trade(1, "BUY", "100", "1", commission="0.001", commission_asset="SOL"),
        trade(2, "BUY", "80", "1", commission="0.08", commission_asset="USDT"),
        trade(
            3,
            "SELL",
            "120",
            "0.5",
            commission="0.00002",
            commission_asset="BNB",
            commission_quote="0.01",
        ),
    ]
    return build_cost_basis_plan(
        "SOLUSDT",
        account_quantity=Decimal("1.499"),
        tolerance_quantity=Decimal("0.0001"),
        trades=rows,
        created_at=created_at,
    )


def test_cost_basis_plan_reconstructs_fifo_and_commissions_exactly():
    plan = covered_plan()
    assert plan.trade_count == 3
    assert plan.reconstructed_quantity == Decimal("1.499")
    assert [lot.quantity for lot in plan.lots] == [
        Decimal("0.499"),
        Decimal("1"),
    ]
    first_cost = Decimal("100") / Decimal("0.999")
    expected_average = (
        Decimal("0.499") * first_cost + Decimal("80.08")
    ) / Decimal("1.499")
    assert plan.weighted_average == expected_average
    assert CostBasisImportPlan.from_dict(plan.as_dict()) == plan


def test_cost_basis_plan_file_is_private_and_hash_verified(tmp_path):
    path = tmp_path / "basis.json"
    plan = covered_plan()
    write_plan(path, plan)
    assert path.stat().st_mode & 0o777 == 0o600
    assert read_plan(path) == plan
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            plan.plan_sha256, "0" * len(plan.plan_sha256)
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="hash mismatch"):
        read_plan(path)


def test_cost_basis_plan_rejects_incomplete_history_and_unpriced_fee():
    with pytest.raises(ValueError, match="SELL exceeds reconstructed history"):
        build_cost_basis_plan(
            "SOLUSDT",
            account_quantity=Decimal("0"),
            tolerance_quantity=Decimal("0.001"),
            trades=[trade(1, "SELL", "100", "1")],
            created_at=100,
        )
    with pytest.raises(ValueError, match="unpriced BNB commission"):
        build_cost_basis_plan(
            "SOLUSDT",
            account_quantity=Decimal("1"),
            tolerance_quantity=Decimal("0.001"),
            trades=[
                trade(
                    1,
                    "BUY",
                    "100",
                    "1",
                    commission="0.01",
                    commission_asset="BNB",
                )
            ],
            created_at=100,
        )


def test_cost_basis_apply_is_atomic_archival_and_idempotent():
    connection = sqlite3.connect(":memory:")
    add_lot(
        connection,
        symbol="SOLUSDT",
        qty=Decimal("9"),
        price=Decimal("999"),
        source_order_id="legacy-wrong",
    )
    connection.commit()
    plan = covered_plan()
    batch_id = apply_cost_basis_plan(connection, plan)
    assert batch_id.startswith("basis-")
    assert apply_cost_basis_plan(connection, plan) == batch_id
    assert connection.execute(
        "SELECT COUNT(*) FROM inventory_lots WHERE status='SUPERSEDED'"
    ).fetchone()[0] == 1
    coverage = cost_basis_coverage(
        connection,
        "SOLUSDT",
        plan.account_quantity,
        tolerance_qty=plan.tolerance_quantity,
    )
    assert coverage.covered is True
    assert coverage.average_price == plan.weighted_average
    row = connection.execute(
        "SELECT qty_text,avg_cost_text,last_trade_id FROM inventory "
        "WHERE symbol='SOLUSDT'"
    ).fetchone()
    assert row == (
        format(plan.reconstructed_quantity, "f"),
        format(plan.weighted_average, "f"),
        plan.last_trade_id,
    )


def test_stats_recalculation_uses_imported_basis_then_new_trades():
    connection = sqlite3.connect(":memory:")
    connection.executescript(tools_stats.SCHEMA)
    plan = covered_plan()
    apply_cost_basis_plan(connection, plan)
    tools_stats.apply_trade(
        connection,
        "SOLUSDT",
        "SELL",
        Decimal("120"),
        Decimal("0.499"),
        trade_id=4,
        fee_quote=Decimal("0"),
        commission_quote=Decimal("0"),
        commission_value_status="exact",
    )
    qty, average, realized = tools_stats.get_inventory_decimal(
        connection, "SOLUSDT"
    )
    assert qty == Decimal("1.000")
    assert average == plan.weighted_average
    assert realized > 0


def test_apply_requires_stopped_confirmation_and_rejects_fresh_heartbeat(
    tmp_path, monkeypatch
):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "ai_status.json").write_text(
        '{"state":"RUNNING","updated_at":"2099-01-01T00:00:00+00:00"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("BOT_RUN_DIR", str(run_dir))
    monkeypatch.delenv("BOT_SERVICE_STOPPED_CONFIRMED", raising=False)
    with pytest.raises(RuntimeError, match="STOPPED_CONFIRMED"):
        import_legacy_cost_basis._require_stopped_runtime()
    monkeypatch.setenv("BOT_SERVICE_STOPPED_CONFIRMED", "YES")
    with pytest.raises(RuntimeError, match="fresh RUNNING heartbeat"):
        import_legacy_cost_basis._require_stopped_runtime()

    (run_dir / "ai_status.json").write_text(
        '{"state":"STOPPED","updated_at":"2099-01-01T00:00:00+00:00"}',
        encoding="utf-8",
    )
    import_legacy_cost_basis._require_stopped_runtime()


def test_trade_history_pagination_refuses_truncation(monkeypatch):
    batch = [trade(index, "BUY", "100", "1") for index in range(1000)]
    monkeypatch.setattr(
        import_legacy_cost_basis.market,
        "_signed_get",
        lambda *args, **kwargs: batch,
    )
    with pytest.raises(RuntimeError, match="incomplete"):
        import_legacy_cost_basis.fetch_all_trades("SOLUSDT", max_pages=1)


def test_live_plan_rejects_existing_symbol_orders(monkeypatch):
    monkeypatch.setattr(import_legacy_cost_basis.market, "BASE_URL", "https://api.binance.com")
    monkeypatch.setattr(
        import_legacy_cost_basis.market,
        "_signed_get",
        lambda *args, **kwargs: [{"orderId": 123}],
    )
    with pytest.raises(RuntimeError, match="zero open symbol orders"):
        import_legacy_cost_basis.build_live_plan(
            "SOLUSDT", tolerance_pct=Decimal("0"), max_pages=1
        )


def test_cost_basis_apply_rolls_back_when_post_import_verification_fails(
    monkeypatch,
):
    connection = sqlite3.connect(":memory:")
    add_lot(
        connection,
        symbol="SOLUSDT",
        qty=Decimal("9"),
        price=Decimal("999"),
        source_order_id="existing",
    )
    connection.commit()
    monkeypatch.setattr(
        "ladder_dragon.execution.cost_basis_import.cost_basis_coverage",
        lambda *args, **kwargs: type(
            "Coverage", (), {"covered": False, "average_price": None, "reason": "forced"}
        )(),
    )
    with pytest.raises(RuntimeError, match="post-import verification failed"):
        apply_cost_basis_plan(connection, covered_plan())
    assert connection.execute(
        "SELECT status FROM inventory_lots WHERE source_order_id='existing'"
    ).fetchone()[0] == "OPEN"
    assert connection.execute(
        "SELECT COUNT(*) FROM inventory_lot_imports"
    ).fetchone()[0] == 0
