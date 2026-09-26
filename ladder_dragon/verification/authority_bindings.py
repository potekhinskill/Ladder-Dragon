# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own execution authority source checks without changing safety contracts.
"""Execution authority_bindings implementation."""

from __future__ import annotations

import ast

from ladder_dragon.verification.source_contracts import expression_identity
from ladder_dragon.verification.authority_contracts import AuthorityBindingContract


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
