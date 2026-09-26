# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: enforce shared dashboard router composition contracts.
"""Source-only checks shared by explicitly reviewed route groups."""

import ast

RUNTIME = "ladder_dragon/dashboard/runtime.py"


def audit_route_group(root, *, group, paths, fields, bodies, methods=None, async_names=()):
    router_path = f"ladder_dragon/dashboard/routers/{group}.py"
    state_path = f"ladder_dragon/dashboard/{group}_dependencies.py"
    factory_name = f"build_{group}_router"
    state_name = f"{group.title()}RouteState"
    fields_name = f"{group.upper()}_FIELDS"
    trees = {p: ast.parse((root / p).read_text(encoding="utf-8")) for p in (RUNTIME, router_path, state_path)}
    violations = []
    factories = [n for n in trees[router_path].body if isinstance(n, ast.FunctionDef) and n.name == factory_name]
    if len(factories) != 1:
        return [f"{group}:factory_missing"]
    factory = factories[0]
    handlers = [n for n in factory.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if len(handlers) != len(paths) or {n.name for n in handlers} != set(paths):
        violations.append(f"{group}:handler_set_changed")
    if ast.dump(factory.body[0]) != ast.dump(ast.parse("router = APIRouter()").body[0]) or ast.dump(factory.body[-1]) != ast.dump(ast.parse("return router").body[0]):
        violations.append(f"{group}:construction_changed")
    for name, path in paths.items():
        kind = ast.AsyncFunctionDef if name in async_names else ast.FunctionDef
        nodes = [n for n in handlers if isinstance(n, kind) and n.name == name]
        method = (methods or {}).get(name, "get")
        expected = ast.parse(f'router.{method}("{path}")').body[0].value
        if len(nodes) != 1 or len(nodes[0].decorator_list) != 1 or ast.dump(nodes[0].decorator_list[0]) != ast.dump(expected):
            violations.append(f"{group}:{name}:route_missing")
            continue
        rule = bodies[name]
        if isinstance(rule, int):
            valid = len(nodes[0].body) >= rule
        elif rule == "try":
            valid = any(isinstance(n, ast.Try) and n.handlers for n in nodes[0].body)
        else:
            valid = ast.dump(ast.Module(body=nodes[0].body, type_ignores=[])) == ast.dump(ast.parse(rule))
        if not valid:
            violations.append(f"{group}:{name}:concrete_owner_missing")
    for n in trees[RUNTIME].body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if n.name in paths:
                violations.append(f"{group}:runtime_owner_returned")
            for d in n.decorator_list:
                if isinstance(d, ast.Call) and d.args and isinstance(d.args[0], ast.Constant) and d.args[0].value in paths.values():
                    violations.append(f"{group}:duplicate_runtime_route")
    calls = [n for n in ast.walk(trees[RUNTIME]) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "include_router"
             and any(isinstance(x, ast.Name) and x.id == factory_name for x in ast.walk(n))]
    expected = ast.parse(f"app.include_router({factory_name}({state_name}(vars())))").body[0].value
    if len(calls) != 1 or ast.dump(calls[0]) != ast.dump(expected):
        violations.append(f"{group}:live_registration_changed")
    imports = {(n.module, a.name) for n in trees[RUNTIME].body if isinstance(n, ast.ImportFrom)
               for a in n.names if a.asname is None}
    for pair in ((f"ladder_dragon.dashboard.routers.{group}", factory_name),
                 (f"ladder_dragon.dashboard.{group}_dependencies", state_name)):
        if pair not in imports:
            violations.append(f"{group}:canonical_import_missing")
    declared = [n for n in trees[state_path].body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == fields_name for t in n.targets)]
    expected_fields = ast.parse("frozenset(" + repr(tuple(sorted(fields))) + ")").body[0].value
    if len(declared) != 1 or ast.dump(declared[0].value) != ast.dump(expected_fields):
        violations.append(f"{group}:dependency_scope_changed")
    classes = [n for n in trees[state_path].body if isinstance(n, ast.ClassDef) and n.name == state_name]
    if len(classes) != 1:
        violations.append(f"{group}:live_adapter_missing")
    else:
        methods = [n for n in classes[0].body if isinstance(n, ast.FunctionDef)]
        expected_method = ast.parse(
            'def __getattr__(self, name: str) -> Any:\n'
            f'    if name not in {fields_name}:\n        raise AttributeError(name)\n'
            '    try:\n        return self._namespace[name]\n'
            '    except KeyError:\n        raise AttributeError(name) from None\n'
        ).body[0]
        if len(methods) != 1 or ast.dump(methods[0]) != ast.dump(expected_method):
            violations.append(f"{group}:live_resolution_changed")
    for path in (router_path, state_path):
        for node in ast.walk(trees[path]):
            modules = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                       [a.name for a in node.names] if isinstance(node, ast.Import) else [])
            if any(m == "ladder_dragon.dashboard.runtime" or m == "bin" or m.startswith("bin.") for m in modules):
                violations.append(f"{group}:reverse_runtime_dependency")
    return violations
