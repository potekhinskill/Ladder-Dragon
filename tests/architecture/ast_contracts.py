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


def restore_transport_diagnostic_import(tree):
    """Reverse only the reviewed split import for historical syntax comparisons."""
    for node in list(tree.body):
        if isinstance(node, ast.ImportFrom) and node.module == "ladder_dragon.observability.transport_errors":
            tree.body.remove(node)
            previous = next(n for n in tree.body if isinstance(n, ast.ImportFrom)
                            and n.module == "ladder_dragon.execution.market_http_body")
            previous.names.append(ast.alias(name="transport_error"))
            tree.body.insert(tree.body.index(previous), ast.parse(
                "from urllib3.exceptions import HTTPError as UrllibHttpError").body[0])
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and isinstance(node.type, ast.Name) and node.type.id == "TRANSPORT_ERRORS":
            node.type = ast.parse("(requests.RequestException, UrllibHttpError)", mode="eval").body
    return tree
