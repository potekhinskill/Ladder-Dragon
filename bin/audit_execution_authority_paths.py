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


AUTHORITY_BINDING_CONTRACTS = (
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
        call_identity="WorkerResources.verify_champion",
        import_module="ladder_dragon.execution.worker.champion_preflight",
        import_name="require_live_champion",
        local_name="require_live_champion",
        owner_class="WorkerResources",
        class_attribute="verify_champion",
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


class _BindingVisitor(ast.NodeVisitor):
    """Collect bindings without entering a nested lexical scope."""

    def __init__(self) -> None:
        self.bindings: list[str] = []

    def _record_target(self, node: ast.AST) -> None:
        if isinstance(node, (ast.Name, ast.Attribute)):
            identity = expression_identity(node)
            if identity:
                self.bindings.append(identity)
            return
        if isinstance(node, (ast.Tuple, ast.List)):
            for item in node.elts:
                self._record_target(item)
        elif isinstance(node, ast.Starred):
            self._record_target(node.value)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self._record_target(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self._record_target(node)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.bindings.append(alias.asname or alias.name.partition(".")[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            self.bindings.append(alias.asname or alias.name)

    def visit_Global(self, node: ast.Global) -> None:
        self.bindings.extend(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.bindings.extend(node.names)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.bindings.append(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.bindings.append(node.name)


def _scope_bindings(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[str, ...]:
    visitor = _BindingVisitor()
    arguments = (
        *function.args.posonlyargs,
        *function.args.args,
        *function.args.kwonlyargs,
    )
    visitor.bindings.extend(argument.arg for argument in arguments)
    if function.args.vararg is not None:
        visitor.bindings.append(function.args.vararg.arg)
    if function.args.kwarg is not None:
        visitor.bindings.append(function.args.kwarg.arg)
    for statement in function.body:
        visitor.visit(statement)
    return tuple(visitor.bindings)


def _canonical_import_count(
    tree: ast.Module, contract: AuthorityBindingContract
) -> int:
    count = 0
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level != 0 or node.module != contract.import_module:
            continue
        count += sum(
            1
            for alias in node.names
            if alias.name == contract.import_name
            and (alias.asname or alias.name) == contract.local_name
        )
    return count


def _module_bindings(tree: ast.Module) -> tuple[str, ...]:
    visitor = _BindingVisitor()
    for statement in tree.body:
        visitor.visit(statement)
    return tuple(visitor.bindings)


def _canonical_class_binding_count(
    tree: ast.Module, contract: AuthorityBindingContract
) -> tuple[int, int]:
    canonical = 0
    total = 0
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != contract.owner_class:
            continue
        for statement in node.body:
            targets: list[ast.AST] = []
            value: ast.AST | None = None
            if isinstance(statement, ast.Assign):
                targets.extend(statement.targets)
                value = statement.value
            elif isinstance(statement, ast.AnnAssign):
                targets.append(statement.target)
                value = statement.value
            matching_targets = [
                target
                for target in targets
                if expression_identity(target) == contract.class_attribute
            ]
            total += len(matching_targets)
            if not matching_targets or not isinstance(value, ast.Call):
                continue
            if (
                expression_identity(value.func) == "staticmethod"
                and len(value.args) == 1
                and not value.keywords
                and expression_identity(value.args[0]) == contract.local_name
            ):
                canonical += len(matching_targets)
    return canonical, total


def _audit_binding_contract(
    tree: ast.Module,
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    contract: AuthorityBindingContract,
) -> list[str]:
    identity = f"{contract.path}:{contract.call_identity}:binding provenance"
    violations: list[str] = []
    if _canonical_import_count(tree, contract) != 1:
        violations.append(identity + ":canonical import count is not 1")

    module_bindings = _module_bindings(tree)
    expected_local_bindings = 1
    if module_bindings.count(contract.local_name) != expected_local_bindings:
        violations.append(identity + ":imported authority name is rebound")

    caller = functions.get(contract.caller)
    if caller is None:
        return violations
    caller_bindings = _scope_bindings(caller)
    protected_roots = {contract.local_name}
    if contract.owner_class:
        protected_roots.add(contract.owner_class)
    shadowed = sorted(protected_roots.intersection(caller_bindings))
    if shadowed:
        violations.append(identity + ":caller shadows " + ",".join(shadowed))

    if not contract.owner_class:
        return violations
    canonical, total = _canonical_class_binding_count(tree, contract)
    if canonical != 1 or total != 1:
        violations.append(identity + ":canonical class binding is not unique")
    class_identity = f"{contract.owner_class}.{contract.class_attribute}"
    if class_identity in module_bindings:
        violations.append(identity + ":class authority attribute is rebound")
    if module_bindings.count(contract.owner_class) != 1:
        violations.append(identity + ":authority owner class is rebound")
    return violations


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


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    report = audit_execution_authority_paths(root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
