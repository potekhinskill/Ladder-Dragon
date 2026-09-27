# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: enforce concrete AI-status components and application composition.
"""Required presentation ownership checks; no AI execution authority."""

import ast
import time
from ladder_dragon.verification.architecture.route_contracts import audit_route_group
from ladder_dragon.verification.models import CheckResult, Status, EXIT_CODES

AI_FIELDS = ('AI_DAILY_COST_LIMIT_USD', 'AI_DAILY_TOKEN_LIMIT', 'AI_DECISIONS_DB', 'AI_ERROR_DEGRADED_MIN', 'AI_MAX_REQUESTS_PER_DAY', 'AI_MODE', 'AI_USAGE_LOG', 'DASHBOARD_FOLLOW_BOT_PATHS', '_ai_calibration', '_ai_database_aggregates', '_ai_usage_today', '_load_ai_runtime_status', '_runtime_data_path', 'runtime_degraded_reason', 'time')
COMPONENTS = {
    'ai_status_context': ('runtime_context', 'runtime_ai, runtime_budgets, runtime_age_sec, runtime_stale, effective_mode', 7),
    'ai_status_reader': ('read_ai_decisions', 'recent, knowledge_stats', 4),
    'ai_status_policy': ('policy_summary', 'request_limit, token_limit, cost_limit, budget_exhausted, degraded_reasons, state', 13),
}


def audit_ai_routes(root):
    violations = audit_route_group(root, group='ai', paths={'ai_status': '/api/ai/status'},
                                   fields=AI_FIELDS, bodies={'ai_status': 'try'})
    router = ast.parse((root / 'ladder_dragon/dashboard/routers/ai.py').read_text())
    imports = [(n.module, a.name) for n in router.body if isinstance(n, ast.ImportFrom)
               for a in n.names if a.asname is None]
    handler = next(n for n in ast.walk(router) if isinstance(n, ast.FunctionDef) and n.name == 'ai_status')
    calls = {}
    for component, (name, returns, count) in COMPONENTS.items():
        pair = ('ladder_dragon.dashboard.' + component, name)
        if imports.count(pair) != 1:
            violations.append(component + ':canonical_import_missing')
        tree = ast.parse((root / ('ladder_dragon/dashboard/' + component + '.py')).read_text())
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
        expected_return = ast.parse('return ' + returns).body[0]
        if (len(functions) != 1 or functions[0].name != name or
                len(functions[0].body) != count or ast.dump(functions[0].body[-1]) != ast.dump(expected_return)):
            violations.append(component + ':concrete_owner_changed')
        for n in ast.walk(tree):
            modules = ([n.module or ''] if isinstance(n, ast.ImportFrom) else
                       [a.name for a in n.names] if isinstance(n, ast.Import) else [])
            if any(m == 'ladder_dragon.dashboard.runtime' or m == 'bin' or m.startswith('bin.') for m in modules):
                violations.append(component + ':reverse_import')
        found = [n for n in ast.walk(handler) if isinstance(n, ast.Call) and
                 isinstance(n.func, ast.Name) and n.func.id == name]
        if len(found) != 1:
            violations.append(component + ':call_missing')
        else:
            calls[name] = found[0]
    expected = {
        'runtime_context': 'runtime_context(deps, runtime)',
        'read_ai_decisions': 'read_ai_decisions(deps, db_path, limit)',
        'policy_summary': 'policy_summary(deps, runtime, runtime_budgets, runtime_stale, effective_mode, usage, recent)',
    }
    for name, expression in expected.items():
        if name not in calls or ast.dump(calls[name]) != ast.dump(ast.parse(expression).body[0].value):
            violations.append(name + ':inputs_changed')
    if len(calls) == 3 and not (calls['runtime_context'].lineno < calls['read_ai_decisions'].lineno < calls['policy_summary'].lineno):
        violations.append('ai:component_order_changed')
    tries = [n for n in handler.body if isinstance(n, ast.Try)]
    guarded = ast.parse('recent, knowledge_stats = read_ai_decisions(deps, db_path, limit)').body[0]
    if len(tries) != 1 or len(tries[0].body) != 1 or ast.dump(tries[0].body[0]) != ast.dump(guarded):
        violations.append('ai:database_error_boundary_changed')
    return violations


def check_ai_routes(context):
    started = time.monotonic()
    try:
        violations = audit_ai_routes(context.root)
        status = Status.FAILED if violations else Status.PASS
    except (OSError, SyntaxError, ValueError, TypeError, StopIteration) as exc:
        violations = [type(exc).__name__]
        status = Status.BLOCKED
    return CheckResult(name='architecture_ai_routes', status=status, required=True,
                       duration_ms=int((time.monotonic() - started) * 1000),
                       summary='Concrete AI-status components and live route composition',
                       exit_code=EXIT_CODES[status], metrics={'violations': violations})
