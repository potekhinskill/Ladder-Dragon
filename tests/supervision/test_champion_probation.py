from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
import sqlite3

from ladder_dragon.supervision.champion_probation import (
    evaluate_champion_probation,
)


def _champion() -> dict[str, dict[str, object]]:
    return {
        "SOLUSDT": {
            "activation_id": "champion:sol:v1",
            "activated_at_ms": 1_000,
            "execution_policy": {
                "probation": {
                    "duration_hours": 24,
                    "maximum_entries": 3,
                    "minimum_terminal_entries": 1,
                    "maximum_turnover_usdt": "18",
                    "maximum_equity_loss_usdt": "3",
                }
            },
        }
    }


def _journal(path: Path, rows: int, *, state: str = "FILLED") -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE order_intents (symbol TEXT,side TEXT,state TEXT,"
            "quantity TEXT,price TEXT,metadata_json TEXT)"
        )
        for index in range(rows):
            connection.execute(
                "INSERT INTO order_intents VALUES(?,?,?,?,?,?)",
                (
                    "SOLUSDT",
                    "BUY",
                    state,
                    "0.06",
                    "100",
                    json.dumps({
                        "champion": {"activation_id": "champion:sol:v1"}
                    }),
                ),
            )


def test_probation_blocks_the_fourth_entry_and_passes_after_time(tmp_path):
    journal = tmp_path / "orders.sqlite3"
    state = tmp_path / "probation.json"
    _journal(journal, 3)

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

    assert active["status"] == "PROBATION"
    assert active["buy_blocked"] is True
    assert passed["status"] == "PASS"
    assert passed["buy_blocked"] is False


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
