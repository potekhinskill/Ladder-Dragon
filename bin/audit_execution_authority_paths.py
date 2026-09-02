#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: prove execution authority checks remain on each mutation-capable path.
"""Audit execution authority call sites, ordering, and cycle placement."""

from __future__ import annotations

import ast
from dataclasses import dataclass
import json
from pathlib import Path

from ladder_dragon.verification.source_contracts import (
    expression_identity,
    qualified_functions,
)


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


@dataclass(frozen=True)
class _CallObservation:
    identity: str
    line: int
    positive_gates: frozenset[str]
    enclosing_loops: frozenset[str]
    branch_depth: int
    try_body_depth: int
    direct_statement: bool


def _contains_positive_gate(node: ast.AST, expected: str) -> bool:
    if expression_identity(node) == expected:
        return True
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
        return any(_contains_positive_gate(value, expected) for value in node.values)
    return False


class _CallVisitor(ast.NodeVisitor):
    def __init__(self, *, expected_gate: str) -> None:
        self.expected_gate = expected_gate
        self.gates: list[str] = []
        self.loops: list[str] = []
        self.branch_depth = 0
        self.try_body_depth = 0
        self.direct_call_nodes: set[int] = set()
        self.observations: list[_CallObservation] = []

    def visit_Call(self, node: ast.Call) -> None:
        identity = expression_identity(node.func)
        self.observations.append(
            _CallObservation(
                identity=identity,
                line=node.lineno,
                positive_gates=frozenset(self.gates),
                enclosing_loops=frozenset(self.loops),
                branch_depth=self.branch_depth,
                try_body_depth=self.try_body_depth,
                direct_statement=id(node) in self.direct_call_nodes,
            )
        )
        self.generic_visit(node)

    def visit_Expr(self, node: ast.Expr) -> None:
        if isinstance(node.value, ast.Call):
            self.direct_call_nodes.add(id(node.value))
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if isinstance(node.value, ast.Call):
            self.direct_call_nodes.add(id(node.value))
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.value, ast.Call):
            self.direct_call_nodes.add(id(node.value))
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        gated = bool(
            self.expected_gate
            and _contains_positive_gate(node.test, self.expected_gate)
        )
        if gated:
            self.gates.append(self.expected_gate)
        self.branch_depth += 1
        for child in node.body:
            self.visit(child)
        self.branch_depth -= 1
        if gated:
            self.gates.pop()
        self.branch_depth += 1
        for child in node.orelse:
            self.visit(child)
        self.branch_depth -= 1

    def visit_For(self, node: ast.For) -> None:
        self.visit(node.target)
        self.visit(node.iter)
        loop_identity = expression_identity(node.iter) or ast.unparse(node.iter)
        if loop_identity:
            self.loops.append(loop_identity)
        for child in node.body:
            self.visit(child)
        if loop_identity:
            self.loops.pop()
        for child in node.orelse:
            self.visit(child)

    visit_AsyncFor = visit_For

    def visit_While(self, node: ast.While) -> None:
        self.visit(node.test)
        loop_identity = expression_identity(node.test) or ast.unparse(node.test)
        self.loops.append(loop_identity)
        for child in node.body:
            self.visit(child)
        self.loops.pop()
        for child in node.orelse:
            self.visit(child)

    def visit_Try(self, node: ast.Try) -> None:
        self.try_body_depth += 1
        for child in node.body:
            self.visit(child)
        self.try_body_depth -= 1
        for handler in node.handlers:
            self.visit(handler)
        for child in node.orelse:
            self.visit(child)
        for child in node.finalbody:
            self.visit(child)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return None

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return None


def _function_calls(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    expected_gate: str,
) -> tuple[_CallObservation, ...]:
    visitor = _CallVisitor(expected_gate=expected_gate)
    for statement in function.body:
        visitor.visit(statement)
    return tuple(visitor.observations)


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
    return {
        "ready": not violations,
        "checked": checked,
        "violations": sorted(violations),
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    report = audit_execution_authority_paths(root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
