# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own execution authority source checks without changing safety contracts.
"""Execution authority_contracts implementation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthorityCallContract:
    """Describe one mandatory execution-authority call site."""

    path: str
    caller: str
    required_call: str
    positive_gate: str = ""
    required_branch_depth: int = 0
    required_try_body_depth: int = 1
    enclosing_loops: tuple[str, ...] = ()
    before_calls: tuple[str, ...] = ()
    required_args: tuple[str, ...] = ()


@dataclass(frozen=True)
class AuthorityBindingContract:
    """Describe one canonical authority-call binding."""

    path: str
    caller: str
    call_identity: str
    import_module: str
    import_name: str
    local_name: str
    owner_class: str = ""
    class_attribute: str = ""


AUTHORITY_CALL_CONTRACTS = (
    AuthorityCallContract(
        path="ladder_dragon/supervision/runtime.py",
        caller="main",
        required_call="run_for_symbol",
        required_try_body_depth=2,
        enclosing_loops=("True", "symbols"),
    ),
    AuthorityCallContract(
        path="ladder_dragon/supervision/runtime.py",
        caller="run_for_symbol",
        required_call="require_supervisor_authority_binding",
        positive_gate="execution_allowed",
        required_branch_depth=1,
        before_calls=("verify_active_champion_lifecycle", "get_last_price"),
        required_args=("verify_active_champion_lifecycle",),
    ),
    AuthorityCallContract(
        path="ladder_dragon/supervision/runtime.py",
        caller="run_for_symbol",
        required_call="verify_active_champion_lifecycle",
        positive_gate="execution_allowed",
        required_branch_depth=1,
        before_calls=("get_last_price",),
    ),
    AuthorityCallContract(
        path="ladder_dragon/execution/worker/lifecycle.py",
        caller="run_worker",
        required_call="_lock.acquire",
        required_try_body_depth=0,
        before_calls=(
            "WorkerResources.verify_champion",
            "state.TM._refresh_time_offset",
            "state._signed_request",
            "state.pull_filters",
        ),
    ),
    AuthorityCallContract(
        path="ladder_dragon/execution/worker/lifecycle.py",
        caller="run_worker",
        required_call="WorkerResources.require_authority_binding",
        positive_gate="state.LIVE_MODE",
        required_branch_depth=1,
        before_calls=(
            "WorkerResources.verify_champion",
            "state.TM._refresh_time_offset",
            "state._signed_request",
            "state.pull_filters",
        ),
        required_args=("WorkerResources.verify_champion",),
    ),
    AuthorityCallContract(
        path="ladder_dragon/execution/worker/lifecycle.py",
        caller="run_worker",
        required_call="WorkerResources.verify_champion",
        positive_gate="state.LIVE_MODE",
        required_branch_depth=1,
        before_calls=(
            "state.TM._refresh_time_offset",
            "state._signed_request",
            "state.pull_filters",
            "state._order_journal",
            "state.reconcile_nonterminal_orders",
            "state.get_price",
            "run_event_loop",
        ),
    ),
)


AUTHORITY_BINDING_CONTRACTS = (
    AuthorityBindingContract(
        path="ladder_dragon/supervision/runtime.py",
        caller="run_for_symbol",
        call_identity="require_supervisor_authority_binding",
        import_module="ladder_dragon.supervision.authority_attestation",
        import_name="require_supervisor_authority_binding",
        local_name="require_supervisor_authority_binding",
    ),
    AuthorityBindingContract(
        path="ladder_dragon/supervision/runtime.py",
        caller="run_for_symbol",
        call_identity="verify_active_champion_lifecycle",
        import_module="ladder_dragon.strategy.prediction.champion_registry",
        import_name="verify_active_champion_lifecycle",
        local_name="verify_active_champion_lifecycle",
    ),
    AuthorityBindingContract(
        path="ladder_dragon/execution/worker/lifecycle.py",
        caller="run_worker",
        call_identity="WorkerResources.require_authority_binding",
        import_module="ladder_dragon.execution.worker.authority_attestation",
        import_name="require_worker_authority_binding",
        local_name="require_worker_authority_binding",
        owner_class="WorkerResources",
        class_attribute="require_authority_binding",
    ),
    AuthorityBindingContract(
        path="ladder_dragon/execution/worker/lifecycle.py",
        caller="run_worker",
        call_identity="WorkerResources.verify_champion",
        import_module="ladder_dragon.execution.worker.champion_preflight",
        import_name="require_live_champion",
        local_name="require_live_champion",
        owner_class="WorkerResources",
        class_attribute="verify_champion",
    ),
)
