# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own execution authority source checks without changing safety contracts.
"""Execution authority_paths implementation."""

from __future__ import annotations

import ast
from pathlib import Path

from ladder_dragon.verification.source_contracts import qualified_functions
from ladder_dragon.verification.authority_contracts import AUTHORITY_CALL_CONTRACTS, AUTHORITY_BINDING_CONTRACTS
from ladder_dragon.verification.authority_calls import _function_calls
from ladder_dragon.verification.authority_bindings import _audit_binding_contract


def audit_execution_authority_paths(root: Path) -> dict[str, object]:
    """Verify authority checks at the registered execution call sites."""
    violations: list[str] = []
    checked: list[str] = []
    trees: dict[str, ast.Module] = {}
    for contract in AUTHORITY_CALL_CONTRACTS:
        identity = f"{contract.path}:{contract.caller}->{contract.required_call}"
        checked.append(identity)
        path = root / contract.path
        if not path.is_file():
            violations.append(identity + ":source missing")
            continue
        tree = trees.get(contract.path)
        if tree is None:
            tree = ast.parse(
                path.read_text(encoding="utf-8"), filename=contract.path
            )
            trees[contract.path] = tree
        function = qualified_functions(tree).get(contract.caller)
        if function is None:
            violations.append(identity + ":caller missing")
            continue
        calls = _function_calls(function, expected_gate=contract.positive_gate)
        required = [
            observation
            for observation in calls
            if observation.identity == contract.required_call
        ]
        if len(required) != 1:
            violations.append(identity + f":required call count is {len(required)}")
            continue
        observed = required[0]
        if (
            contract.positive_gate
            and contract.positive_gate not in observed.positive_gates
        ):
            violations.append(
                identity + f":not gated by {contract.positive_gate}"
            )
        if observed.branch_depth != contract.required_branch_depth:
            violations.append(
                identity
                + f":branch depth is {observed.branch_depth}, expected "
                + str(contract.required_branch_depth)
            )
        if observed.try_body_depth != contract.required_try_body_depth:
            violations.append(
                identity
                + f":try-body depth is {observed.try_body_depth}, expected "
                + str(contract.required_try_body_depth)
            )
        if not observed.direct_statement:
            violations.append(identity + ":authority call is not a direct statement")
        if contract.required_args and observed.positional_args != contract.required_args:
            violations.append(identity + ":authority attestation arguments changed")
        for loop in contract.enclosing_loops:
            if loop not in observed.enclosing_loops:
                violations.append(identity + f":not inside {loop} loop")
        boundary_lines = [
            observation.line
            for observation in calls
            if observation.identity in contract.before_calls
        ]
        if contract.before_calls and not boundary_lines:
            violations.append(identity + ":protected boundary missing")
        elif boundary_lines and observed.line >= min(boundary_lines):
            violations.append(identity + ":authority check follows protected boundary")
    for contract in AUTHORITY_BINDING_CONTRACTS:
        identity = f"{contract.path}:{contract.call_identity}:binding provenance"
        checked.append(identity)
        tree = trees.get(contract.path)
        if tree is None:
            path = root / contract.path
            if not path.is_file():
                continue
            tree = ast.parse(
                path.read_text(encoding="utf-8"), filename=contract.path
            )
            trees[contract.path] = tree
        functions = qualified_functions(tree)
        violations.extend(_audit_binding_contract(tree, functions, contract))
    return {
        "ready": not violations,
        "checked": checked,
        "violations": sorted(violations),
    }
