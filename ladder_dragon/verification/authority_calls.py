# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own execution authority source checks without changing safety contracts.
"""Execution authority_calls implementation."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from ladder_dragon.verification.source_contracts import expression_identity


@dataclass(frozen=True)
class _CallObservation:
    identity: str
    line: int
    positive_gates: frozenset[str]
    enclosing_loops: frozenset[str]
    branch_depth: int
    try_body_depth: int
    direct_statement: bool
    positional_args: tuple[str, ...]


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
                positional_args=tuple(expression_identity(arg) for arg in node.args),
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
