from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
import sqlite3

from ladder_dragon.supervision.champion_probation import (
    apply_champion_probation_gate,
    evaluate_champion_probation,
)
from ladder_dragon.risk.risk_manager import RiskDecision


def _champion() -> dict[str, dict[str, object]]:
    return {
        "SOLUSDT": {
            "activation_id": "champion:sol:v1",
            "activated_at_ms": 1_000,
            "execution_policy": {
                "probation": {
                    "schema_version": 3,
                    "duration_hours": 24,
                    "maximum_entries": 3,
                    "minimum_terminal_entries": 1,
                    "minimum_closed_lifecycles": 1,
                    "maximum_turnover_usdt": "18",
                    "maximum_equity_loss_usdt": "3",
                }
            },
        }
    }


def _journal(
    path: Path,
    rows: int,
    *,
    state: str = "FILLED",
    closed: int = 0,
    executed_qty: str | None = None,
) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE order_intents (client_order_id TEXT,symbol TEXT,"
            "side TEXT,state TEXT,quantity TEXT,price TEXT,executed_qty TEXT,"
            "metadata_json TEXT)"
        )
        connection.execute(
            "CREATE TABLE order_lifecycle_closures ("
            "parent_client_order_id TEXT,symbol TEXT)"
        )
        for index in range(rows):
            connection.execute(
                "INSERT INTO order_intents VALUES(?,?,?,?,?,?,?,?)",
                (
                    f"buy-{index}",
                    "SOLUSDT",
                    "BUY",
                    state,
                    "0.06",
                    "100",
                    executed_qty
                    if executed_qty is not None
                    else "0.06" if state == "FILLED" else "0",
                    json.dumps({
                        "champion": {"activation_id": "champion:sol:v1"}
                    }),
                ),
            )
            if index < closed:
                connection.execute(
                    "INSERT INTO order_lifecycle_closures VALUES(?,?)",
                    (f"buy-{index}", "SOLUSDT"),
                )


def test_probation_blocks_the_fourth_entry_and_passes_after_time(tmp_path):
    journal = tmp_path / "orders.sqlite3"
    state = tmp_path / "probation.json"
    _journal(journal, 3, closed=1)

    active = evaluate_champion_probation(
        _champion(),
        journal_path=journal,
        state_path=state,
        equity_usdt=Decimal("100"),
        now_ms=2_000,
    )
    passed = evaluate_champion_probation(
        _champion(),
        journal_path=journal,
        state_path=state,
        equity_usdt=Decimal("100"),
        now_ms=24 * 60 * 60_000 + 2_000,
    )

    assert active["status"] == "PROBATION_WAITING_FOR_EXPIRY"
    assert active["buy_blocked"] is True
    assert active["limit_reason_code"] == (
        "MAXIMUM_ENTRIES_AND_TURNOVER_REACHED"
    )
    assert passed["status"] == "PASS"
    assert passed["buy_blocked"] is False
    assert passed["closed_lifecycles"] == 1


def test_expired_probation_waits_for_an_existing_lifecycle(tmp_path):
    journal = tmp_path / "orders.sqlite3"
    state = tmp_path / "probation.json"
    _journal(journal, 1, state="PROTECTED", executed_qty="0.06")

    evaluate_champion_probation(
        _champion(), journal_path=journal, state_path=state,
        equity_usdt=Decimal("100"), now_ms=2_000,
    )
    report = evaluate_champion_probation(
        _champion(), journal_path=journal, state_path=state,
        equity_usdt=Decimal("100"), now_ms=24 * 60 * 60_000 + 2_000,
    )

    assert report["status"] == "EXPIRED_WAITING_FOR_EXISTING_LIFECYCLES"
    assert report["buy_blocked"] is True
    assert report["self_recovery_possible"] is True
    assert report["operator_action_required"] is False
    assert report["closed_lifecycles"] == 0

    with sqlite3.connect(journal) as connection:
        connection.execute(
            "UPDATE order_intents SET state='CLOSED' WHERE client_order_id='buy-0'"
        )
        connection.execute(
            "INSERT INTO order_lifecycle_closures VALUES(?,?)",
            ("buy-0", "SOLUSDT"),
        )
    passed = evaluate_champion_probation(
        _champion(), journal_path=journal, state_path=state,
        equity_usdt=Decimal("100"), now_ms=24 * 60 * 60_000 + 3_000,
    )

    assert passed["status"] == "PASS"
    assert passed["buy_blocked"] is False


def test_expired_probation_requires_review_when_no_entry_exists(tmp_path):
    journal = tmp_path / "orders.sqlite3"
    state = tmp_path / "probation.json"
    _journal(journal, 0)

    evaluate_champion_probation(
        _champion(), journal_path=journal, state_path=state,
        equity_usdt=Decimal("100"), now_ms=2_000,
    )
    report = evaluate_champion_probation(
        _champion(), journal_path=journal, state_path=state,
        equity_usdt=Decimal("100"), now_ms=24 * 60 * 60_000 + 2_000,
    )

    assert report["status"] == "EXPIRED_INSUFFICIENT_EVIDENCE"
    assert report["block_reason_code"] == "EXPIRED_INSUFFICIENT_EVIDENCE"
    assert report["operator_action_required"] is True
    assert report["self_recovery_possible"] is False
    assert report["missing_terminal_entries"] == 1
    assert report["missing_closed_lifecycles"] == 1
    assert "client_order_id" not in report


def test_terminal_unfilled_entry_cannot_claim_lifecycle_recovery(tmp_path):
    journal = tmp_path / "orders.sqlite3"
    state = tmp_path / "probation.json"
    _journal(journal, 1, state="CANCELED", executed_qty="0")

    evaluate_champion_probation(
        _champion(), journal_path=journal, state_path=state,
        equity_usdt=Decimal("100"), now_ms=2_000,
    )
    report = evaluate_champion_probation(
        _champion(), journal_path=journal, state_path=state,
        equity_usdt=Decimal("100"), now_ms=24 * 60 * 60_000 + 2_000,
    )

    assert report["status"] == "EXPIRED_INSUFFICIENT_EVIDENCE"
    assert report["terminal_entries"] == 1
    assert report["maximum_closed_lifecycles_without_new_buys"] == 0
    assert report["operator_action_required"] is True


def test_exhausted_entry_limit_requires_review_before_expiry(tmp_path):
    journal = tmp_path / "orders.sqlite3"
    state = tmp_path / "probation.json"
    _journal(journal, 3, state="CANCELED", executed_qty="0")

    report = evaluate_champion_probation(
        _champion(), journal_path=journal, state_path=state,
        equity_usdt=Decimal("100"), now_ms=2_000,
    )

    assert report["status"] == "LIMIT_REACHED_INSUFFICIENT_EVIDENCE"
    assert report["buy_blocked"] is True
    assert report["limit_reason_code"] == (
        "MAXIMUM_ENTRIES_AND_TURNOVER_REACHED"
    )
    assert report["operator_action_required"] is True
    assert report["can_pass_without_new_entries"] is False


def test_probation_gate_reports_expiry_reason_instead_of_entry_limit(tmp_path):
    journal = tmp_path / "orders.sqlite3"
    state = tmp_path / "probation.json"
    _journal(journal, 0)
    evaluate_champion_probation(
        _champion(), journal_path=journal, state_path=state,
        equity_usdt=Decimal("100"), now_ms=2_000,
    )
    halts: list[str] = []

    report, decision = apply_champion_probation_gate(
        _champion(),
        Decimal("100"),
        RiskDecision(halted=False, buy_blocked=False, reasons=()),
        environ={
            "BOT_ORDER_JOURNAL": str(journal),
            "BOT_CHAMPION_PROBATION_STATE": str(state),
        },
        limits=object(),
        create_halt=lambda reason, **_kwargs: halts.append(reason),
        now_ms=24 * 60 * 60_000 + 2_000,
    )

    assert report["status"] == "EXPIRED_INSUFFICIENT_EVIDENCE"
    assert decision.halted is False
    assert decision.buy_blocked is True
    assert decision.reasons == (
        "CHAMPION probation expired with insufficient evidence; "
        "a reviewed activation is required",
    )
    assert halts == []


def test_probation_equity_loss_requests_a_persistent_halt(tmp_path):
    journal = tmp_path / "orders.sqlite3"
    state = tmp_path / "probation.json"
    _journal(journal, 0)
    evaluate_champion_probation(
        _champion(),
        journal_path=journal,
        state_path=state,
        equity_usdt=Decimal("100"),
        now_ms=2_000,
    )

    report = evaluate_champion_probation(
        _champion(),
        journal_path=journal,
        state_path=state,
        equity_usdt=Decimal("97"),
        now_ms=3_000,
    )

    assert report["status"] == "FAILED"
    assert report["buy_blocked"] is True
    assert "loss limit" in str(report["halt_reason"])


def test_probation_does_not_expire_while_persistent_halt_is_active(tmp_path):
    journal = tmp_path / "orders.sqlite3"
    state = tmp_path / "probation.json"
    _journal(journal, 0)

    waiting = evaluate_champion_probation(
        _champion(), journal_path=journal, state_path=state,
        equity_usdt=Decimal("100"), now_ms=2_000, paused=True,
    )
    started = evaluate_champion_probation(
        _champion(), journal_path=journal, state_path=state,
        equity_usdt=Decimal("100"), now_ms=50_000,
    )

    assert waiting["status"] == "WAITING_FOR_HALT_RESET"
    assert state.exists() is True
    assert started["status"] == "PROBATION"
