# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: enforce dashboard access ownership and live application composition.
"""Structural access contracts supplement behavioral security regressions."""

import ast
import time
from ladder_dragon.verification.architecture.route_contracts import audit_route_group
from ladder_dragon.verification.models import CheckResult, Status, EXIT_CODES

ACCESS_FIELDS = ('DASHBOARD_AUTH_TOKEN', 'DASHBOARD_CSRF_TOKEN', 'DASHBOARD_PROXY_AUTH_SECRET', 'DASHBOARD_RATE_LIMIT_PER_MIN', 'DASHBOARD_TRUST_PROXY_AUTH', '_RATE_BUCKETS', '_RATE_LOCK', '_RATE_PRUNE_STATE', 'time')
OWNERS = {'_is_loopback_peer', '_rate_limit_client', '_prune_rate_buckets', 'build_access_middleware'}


def audit_security_routes(root):
    violations = audit_route_group(
        root, group='security', paths={'csrf_token': '/api/security/csrf'},
        fields={'DASHBOARD_CSRF_TOKEN'}, bodies={'csrf_token':
        '"""Return a process-local token only to an authenticated same-origin client."""\n'
        'return {"ok": True, "csrf_token": state.DASHBOARD_CSRF_TOKEN}'},
    )
    runtime = ast.parse((root / 'ladder_dragon/dashboard/runtime.py').read_text())
    access = ast.parse((root / 'ladder_dragon/dashboard/access_policy.py').read_text())
    deps = ast.parse((root / 'ladder_dragon/dashboard/security_dependencies.py').read_text())
    functions = {n.name: n for n in access.body if isinstance(n, ast.FunctionDef)}
    if set(functions) != OWNERS or len(access.body) != len(OWNERS) + 5:
        violations.append('access:owner_set_changed')
    imports = {(n.module, a.name) for n in runtime.body if isinstance(n, ast.ImportFrom)
               for a in n.names if a.asname is None}
    if not {('ladder_dragon.dashboard.access_policy', 'build_access_middleware'),
            ('ladder_dragon.dashboard.security_dependencies', 'AccessState')} <= imports:
        violations.append('access:canonical_import_missing')
    expected = ast.parse('app.middleware("http")(build_access_middleware(AccessState(vars())))').body[0]
    registrations = [n for n in runtime.body if isinstance(n, ast.Expr) and ast.dump(n) == ast.dump(expected)]
    middleware_calls = [n for n in ast.walk(runtime) if isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Attribute) and n.func.attr == 'middleware']
    if len(registrations) != 1 or len(middleware_calls) != 1:
        violations.append('access:live_registration_changed')
    if any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and
           n.name in OWNERS | {'authenticate_and_rate_limit'} for n in runtime.body):
        violations.append('access:runtime_owner_returned')
    factory = functions.get('build_access_middleware')
    if factory is None or len(factory.body) != 2 or not isinstance(factory.body[0], ast.AsyncFunctionDef):
        violations.append('access:middleware_owner_missing')
    else:
        handler = factory.body[0]
        final = ast.parse('return authenticate_and_rate_limit').body[0]
        if handler.name != 'authenticate_and_rate_limit' or ast.dump(factory.body[-1]) != ast.dump(final):
            violations.append('access:dispatch_changed')
        if len(handler.body) != 3 or not isinstance(handler.body[1], ast.If) or not isinstance(handler.body[-1], ast.Return):
            violations.append('access:middleware_body_changed')
        elif not isinstance(handler.body[-1].value, ast.Await):
            violations.append('access:continuation_changed')
    for name in OWNERS - {'build_access_middleware'}:
        if name not in functions or len(functions[name].body) < 2:
            violations.append('access:helper_owner_missing')
    declared = [n for n in deps.body if isinstance(n, ast.Assign) and
                any(isinstance(t, ast.Name) and t.id == 'ACCESS_FIELDS' for t in n.targets)]
    expected_fields = ast.parse('frozenset(' + repr(ACCESS_FIELDS) + ')').body[0].value
    classes = {n.name: n for n in deps.body if isinstance(n, ast.ClassDef)}
    if len(declared) != 1 or ast.dump(declared[0].value) != ast.dump(expected_fields):
        violations.append('access:scope_changed')
    if 'AccessState' not in classes:
        violations.append('access:adapter_missing')
    else:
        reference = next(n for n in classes['SecurityRouteState'].body if isinstance(n, ast.FunctionDef))
        expected_method = ast.parse(ast.unparse(reference).replace('SECURITY_FIELDS', 'ACCESS_FIELDS')).body[0]
        methods = [n for n in classes['AccessState'].body if isinstance(n, ast.FunctionDef)]
        if len(methods) != 1 or ast.dump(methods[0]) != ast.dump(expected_method):
            violations.append('access:live_resolution_changed')
    for n in ast.walk(access):
        modules = ([n.module or ''] if isinstance(n, ast.ImportFrom) else
                   [a.name for a in n.names] if isinstance(n, ast.Import) else [])
        if any(m == 'ladder_dragon.dashboard.runtime' or m == 'bin' or m.startswith('bin.') for m in modules):
            violations.append('access:reverse_import')
    return violations


def check_security_routes(context):
    started = time.monotonic()
    try:
        violations = audit_security_routes(context.root)
        status = Status.FAILED if violations else Status.PASS
    except (OSError, SyntaxError, ValueError, TypeError, KeyError, StopIteration) as exc:
        violations = [type(exc).__name__]
        status = Status.BLOCKED
    return CheckResult(name='architecture_security_routes', status=status, required=True,
                       duration_ms=int((time.monotonic() - started) * 1000),
                       summary='Concrete access middleware and CSRF route with live bindings',
                       exit_code=EXIT_CODES[status], metrics={'violations': violations})
