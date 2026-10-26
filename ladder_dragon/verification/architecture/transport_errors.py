# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: enforce diagnostic ownership separately from bounded HTTP reading.
"""Scoped structural ownership supplements transport and redaction tests."""

import ast
import time

from ladder_dragon.verification.models import CheckResult, Status, EXIT_CODES

OWNER = "ladder_dragon.observability.transport_errors"
OWNER_PATH = "ladder_dragon/observability/transport_errors.py"
READER = "ladder_dragon/execution/market_http_body.py"
CONSUMER = "ladder_dragon/execution/tools_market.py"


def audit_transport_errors(root):
    tree = ast.parse((root / OWNER_PATH).read_text())
    violations = []
    binding = ast.parse("TRANSPORT_ERRORS = (requests.RequestException, urllib_errors.HTTPError)").body[0]
    assignments = [n for n in tree.body if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "TRANSPORT_ERRORS" for t in n.targets)]
    if len(assignments) != 1 or ast.dump(assignments[0]) != ast.dump(binding):
        violations.append("transport_errors:exception_types_changed")
    expected = {"transport_cause": 3, "transport_error": 7}
    definitions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    if len(definitions) != 2 or {n.name for n in definitions} != set(expected):
        violations.append("transport_errors:owner_missing")
    for node in definitions:
        body = [n for n in node.body if not (isinstance(n, ast.Expr)
                and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))]
        if len(body) < expected.get(node.name, 2):
            violations.append("transport_errors:forwarding_stub")
    for path, allowed in ((OWNER_PATH, {"socket", "urllib.parse", "requests", "urllib3"}),
                          (READER, {"time", "zlib", "requests"})):
        parsed = ast.parse((root / path).read_text())
        for node in ast.walk(parsed):
            modules = ([node.module if not node.level else None] if isinstance(node, ast.ImportFrom)
                       else [a.name for a in node.names] if isinstance(node, ast.Import) else [])
            if any(module not in allowed for module in modules):
                violations.append(path + ":unexpected_dependency")
        if path == READER and any(isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in expected
                                  for n in parsed.body):
            violations.append("transport_errors:legacy_definition")
    consumer = ast.parse((root / CONSUMER).read_text())
    imports = [(n.module, n.level, a.name, a.asname) for n in consumer.body
               if isinstance(n, ast.ImportFrom) for a in n.names]
    for module, name in ((OWNER, "transport_error"), (OWNER, "TRANSPORT_ERRORS"),
                         ("ladder_dragon.execution.market_http_body", "read_body"),
                         ("ladder_dragon.execution.market_http_body", "remaining_seconds")):
        if imports.count((module, 0, name, None)) != 1:
            violations.append("transport_errors:canonical_import_missing")
    if any((isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in {"transport_error", "TRANSPORT_ERRORS"})
           or (isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and n.id in {"transport_error", "TRANSPORT_ERRORS"})
           for n in ast.walk(consumer)):
        violations.append("transport_errors:consumer_binding_replaced")
    return violations


def check_transport_errors(context):
    started = time.monotonic()
    try:
        violations = audit_transport_errors(context.root)
        status = Status.FAILED if violations else Status.PASS
    except (OSError, SyntaxError, ValueError, TypeError) as exc:
        violations, status = [type(exc).__name__], Status.BLOCKED
    return CheckResult(name="architecture_transport_errors", status=status, required=True,
        duration_ms=int((time.monotonic() - started) * 1000),
        summary="Transport diagnostics and reader ownership", exit_code=EXIT_CODES[status],
        metrics={"violations": violations})
