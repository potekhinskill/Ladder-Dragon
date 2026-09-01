# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: kill mutations that bypass execution-authority call-site contracts.
"""Mutation regressions for execution-authority path placement."""

from __future__ import annotations

import json
from pathlib import Path

from bin.audit_execution_authority_paths import (
    AUTHORITY_CALL_CONTRACTS,
    audit_execution_authority_paths,
)


ROOT = Path(__file__).resolve().parents[1]


def _copy_sources(destination: Path) -> None:
    for relative in {contract.path for contract in AUTHORITY_CALL_CONTRACTS}:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        source = (ROOT / relative).read_text(encoding="utf-8")
        target.write_text(source, encoding="utf-8")


def _replace(path: Path, old: str, new: str) -> None:
    source = path.read_text(encoding="utf-8")
    assert old in source
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


def test_execution_authority_path_audit_accepts_current_sources() -> None:
    assert audit_execution_authority_paths(ROOT)["violations"] == []


def test_audit_rejects_missing_per_plan_lifecycle_check(tmp_path: Path) -> None:
    _copy_sources(tmp_path)
    target = tmp_path / "ladder_dragon/supervision/runtime.py"
    _replace(
        target,
        "verify_active_champion_lifecycle(_PREDICTION_SHADOW, symbol=symbol,",
        "ignored_champion_lifecycle(_PREDICTION_SHADOW, symbol=symbol,",
    )
    report = audit_execution_authority_paths(tmp_path)
    assert any(
        item.endswith(
            "run_for_symbol->verify_active_champion_lifecycle:required call count is 0"
        )
        for item in report["violations"]
    )


def test_audit_rejects_lifecycle_check_after_market_read(tmp_path: Path) -> None:
    _copy_sources(tmp_path)
    target = tmp_path / "ladder_dragon/supervision/runtime.py"
    _replace(
        target,
        "verify_active_champion_lifecycle(_PREDICTION_SHADOW, symbol=symbol,",
        "ignored_champion_lifecycle(_PREDICTION_SHADOW, symbol=symbol,",
    )
    _replace(
        target,
        "    now_p = get_last_price(symbol)\n",
        "    now_p = get_last_price(symbol)\n"
        "    verify_active_champion_lifecycle(...)\n",
    )
    report = audit_execution_authority_paths(tmp_path)
    assert any(
        item.endswith(
            "run_for_symbol->verify_active_champion_lifecycle:"
            "authority check follows protected boundary"
        )
        for item in report["violations"]
    )


def test_audit_rejects_ungated_lifecycle_check(tmp_path: Path) -> None:
    _copy_sources(tmp_path)
    target = tmp_path / "ladder_dragon/supervision/runtime.py"
    _replace(
        target,
        "    if execution_allowed:\n"
        "        if _PREDICTION_SHADOW is None:\n",
        "    if True:\n"
        "        if _PREDICTION_SHADOW is None:\n",
    )
    report = audit_execution_authority_paths(tmp_path)
    assert any(
        item.endswith(
            "run_for_symbol->verify_active_champion_lifecycle:"
            "not gated by execution_allowed"
        )
        for item in report["violations"]
    )


def test_audit_rejects_fail_open_or_gate(tmp_path: Path) -> None:
    _copy_sources(tmp_path)
    target = tmp_path / "ladder_dragon/supervision/runtime.py"
    _replace(
        target,
        "    if execution_allowed:\n"
        "        if _PREDICTION_SHADOW is None:\n",
        "    if execution_allowed or True:\n"
        "        if _PREDICTION_SHADOW is None:\n",
    )
    report = audit_execution_authority_paths(tmp_path)
    assert any(
        item.endswith(
            "run_for_symbol->verify_active_champion_lifecycle:"
            "not gated by execution_allowed"
        )
        for item in report["violations"]
    )


def test_audit_rejects_lifecycle_check_outside_revoke_try(tmp_path: Path) -> None:
    _copy_sources(tmp_path)
    target = tmp_path / "ladder_dragon/supervision/runtime.py"
    old = """        try:
            verify_active_champion_lifecycle(_PREDICTION_SHADOW, symbol=symbol,
"""
    new = """        verify_active_champion_lifecycle(...)
        try:
            ignored_champion_lifecycle(_PREDICTION_SHADOW, symbol=symbol,
"""
    _replace(target, old, new)
    report = audit_execution_authority_paths(tmp_path)
    assert any(
        item.endswith(
            "run_for_symbol->verify_active_champion_lifecycle:"
            "try-body depth is 0, expected 1"
        )
        for item in report["violations"]
    )


def test_audit_rejects_nonexecuting_comprehension_decoy(tmp_path: Path) -> None:
    _copy_sources(tmp_path)
    target = tmp_path / "ladder_dragon/supervision/runtime.py"
    old = """        try:
            verify_active_champion_lifecycle(_PREDICTION_SHADOW, symbol=symbol,
"""
    new = """        try:
            [verify_active_champion_lifecycle(...) for _item in ()]
            ignored_champion_lifecycle(_PREDICTION_SHADOW, symbol=symbol,
"""
    _replace(target, old, new)
    report = audit_execution_authority_paths(tmp_path)
    assert any(
        item.endswith(
            "run_for_symbol->verify_active_champion_lifecycle:"
            "authority call is not a direct statement"
        )
        for item in report["violations"]
    )


def test_audit_rejects_plan_call_outside_symbol_cycle(tmp_path: Path) -> None:
    _copy_sources(tmp_path)
    target = tmp_path / "ladder_dragon/supervision/runtime.py"
    _replace(target, "            for sym in symbols:\n", "            for sym in ():\n")
    report = audit_execution_authority_paths(tmp_path)
    assert any(
        item.endswith("main->run_for_symbol:not inside symbols loop")
        for item in report["violations"]
    )


def test_audit_rejects_plan_call_outside_repeating_cycle(tmp_path: Path) -> None:
    _copy_sources(tmp_path)
    target = tmp_path / "ladder_dragon/supervision/runtime.py"
    _replace(target, "        while True:\n", "        if True:\n")
    report = audit_execution_authority_paths(tmp_path)
    assert any(
        item.endswith("main->run_for_symbol:not inside True loop")
        for item in report["violations"]
    )


def test_audit_rejects_conditionally_bypassable_authority_call(
    tmp_path: Path,
) -> None:
    _copy_sources(tmp_path)
    target = tmp_path / "ladder_dragon/supervision/runtime.py"
    old = """        try:
            verify_active_champion_lifecycle(_PREDICTION_SHADOW, symbol=symbol,
"""
    new = """        try:
            if symbol:
                verify_active_champion_lifecycle(_PREDICTION_SHADOW, symbol=symbol,
"""
    _replace(target, old, new)
    report = audit_execution_authority_paths(tmp_path)
    assert any(
        item.endswith(
            "run_for_symbol->verify_active_champion_lifecycle:"
            "branch depth is 2, expected 1"
        )
        for item in report["violations"]
    )


def test_audit_rejects_worker_check_after_exchange_access(tmp_path: Path) -> None:
    _copy_sources(tmp_path)
    target = tmp_path / "ladder_dragon/execution/worker/lifecycle.py"
    _replace(
        target,
        "            champion = WorkerResources.verify_champion(state, args)\n",
        "            champion = None\n",
    )
    _replace(
        target,
        '            server = state._public_get("/api/v3/time")\n',
        '            server = state._public_get("/api/v3/time")\n'
        "            champion = WorkerResources.verify_champion(state, args)\n",
    )
    report = audit_execution_authority_paths(tmp_path)
    assert any(
        item.endswith(
            "run_worker->WorkerResources.verify_champion:"
            "authority check follows protected boundary"
        )
        for item in report["violations"]
    )


def test_audit_rejects_ungated_worker_preflight(tmp_path: Path) -> None:
    _copy_sources(tmp_path)
    target = tmp_path / "ladder_dragon/execution/worker/lifecycle.py"
    _replace(
        target,
        "    if state.LIVE_MODE:\n"
        "        # Repeat preflight because a worker can start without the supervisor.\n",
        "    if True:\n"
        "        # Repeat preflight because a worker can start without the supervisor.\n",
    )
    report = audit_execution_authority_paths(tmp_path)
    assert any(
        item.endswith(
            "run_worker->WorkerResources.verify_champion:"
            "not gated by state.LIVE_MODE"
        )
        for item in report["violations"]
    )


def test_audit_ignores_nested_decoy_calls(tmp_path: Path) -> None:
    _copy_sources(tmp_path)
    target = tmp_path / "ladder_dragon/supervision/runtime.py"
    _replace(
        target,
        "verify_active_champion_lifecycle(_PREDICTION_SHADOW, symbol=symbol,",
        "ignored_champion_lifecycle(_PREDICTION_SHADOW, symbol=symbol,",
    )
    _replace(
        target,
        '    """Build one plan; optionally retain only read-only SHADOW telemetry."""\n',
        '    """Build one plan; optionally retain only read-only SHADOW telemetry."""\n'
        "    def decoy() -> None:\n"
        "        verify_active_champion_lifecycle(...)\n",
    )
    report = audit_execution_authority_paths(tmp_path)
    assert any(
        item.endswith(
            "run_for_symbol->verify_active_champion_lifecycle:required call count is 0"
        )
        for item in report["violations"]
    )


def test_audit_fails_closed_without_disclosing_source_content(tmp_path: Path) -> None:
    _copy_sources(tmp_path)
    missing = tmp_path / "ladder_dragon/execution/worker/lifecycle.py"
    missing.unlink()
    marker = "sensitive-value-not-for-report"
    runtime = tmp_path / "ladder_dragon/supervision/runtime.py"
    runtime.write_text(
        runtime.read_text(encoding="utf-8") + f"\n# {marker}\n",
        encoding="utf-8",
    )
    report = audit_execution_authority_paths(tmp_path)
    assert report["ready"] is False
    assert any(item.endswith(":source missing") for item in report["violations"])
    assert marker not in json.dumps(report, sort_keys=True)
