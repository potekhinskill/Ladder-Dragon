"""Stable extraction fingerprints for supported Python AST versions."""

import ast
import copy
import hashlib


def extraction_digest(tree: ast.AST) -> str:
    """Ignore only empty generic declarations introduced by Python 3.12."""
    normalized = copy.deepcopy(tree)
    declarations = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    for node in ast.walk(normalized):
        if isinstance(node, declarations) and getattr(node, "type_params", None) == []:
            node._fields = tuple(field for field in node._fields if field != "type_params")
    return hashlib.sha256(ast.dump(normalized, include_attributes=False).encode()).hexdigest()
