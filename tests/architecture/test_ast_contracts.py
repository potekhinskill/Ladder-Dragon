"""Compatibility must preserve meaningful syntax and original AST objects."""

import ast
import copy

import pytest

from tests.architecture.ast_contracts import extraction_digest


@pytest.mark.parametrize("source", ["def f(): pass", "async def f(): pass", "class C: pass"])
def test_empty_type_parameters_preserve_digest_without_mutating_input(source):
    original = ast.parse(source)
    extended = copy.deepcopy(original)
    declaration = extended.body[0]
    if "type_params" not in declaration._fields:
        declaration._fields += ("type_params",)
    declaration.type_params = []
    before = ast.dump(extended)
    assert extraction_digest(extended) == extraction_digest(original)
    assert ast.dump(extended) == before
    declaration.type_params = [ast.Name(id="T", ctx=ast.Load())]
    assert extraction_digest(extended) != extraction_digest(original)


@pytest.mark.parametrize("source", [
    "def f(): return 2", "def g(): return 1", "@guard\ndef f(): return 1",
    "def f(x): return 1", "def f():\n check()\n return 1",
])
def test_behavior_changes_still_change_digest(source):
    assert extraction_digest(ast.parse(source)) != extraction_digest(ast.parse("def f(): return 1"))


def test_nonempty_generic_parameters_remain_observable_when_parser_supports_them():
    if not hasattr(ast, "TypeVar"):
        pytest.skip("Python 3.12 generic syntax is unavailable")
    plain = extraction_digest(ast.parse("def f(): pass"))
    assert extraction_digest(ast.parse("def f[T](): pass")) != plain
    assert extraction_digest(ast.parse("def f[T](): pass")) != extraction_digest(ast.parse("def f[U](): pass"))
