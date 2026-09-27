# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: enforce concrete AI reporting owners and live composition.
"""Structural ownership checks complement service behavior regressions."""

import ast
import time
from ladder_dragon.verification.models import CheckResult, Status, EXIT_CODES

PREFIX = 'ladder_dragon/dashboard/'
OWNERS = {'ai_report_cache': {'cache_get': 2, 'cache_put': 2},
          'ai_usage': {'usage_today': 12},
          'ai_aggregates': {'database_aggregates': 13},
          'ai_calibration': {'calibration': 3}}
FIELDS = ('AI_ERROR_DEGRADED_WINDOW_SEC', 'DASHBOARD_AI_AGGREGATE_CACHE_SEC',
          '_AI_SUMMARY_CACHE', '_AI_SUMMARY_CACHE_LOCK', '_ai_cache_get', '_ai_cache_put', 'time')
BINDINGS = {'_ai_reporting_state': 'AiReportingState(vars())',
            '_ai_cache_get': 'partial(cache_get, _ai_reporting_state)',
            '_ai_cache_put': 'partial(cache_put, _ai_reporting_state)',
            '_ai_usage_today': 'partial(usage_today, _ai_reporting_state)',
            '_ai_database_aggregates': 'partial(database_aggregates, _ai_reporting_state)'}


def binding_matches(tree, name, expression):
    nodes = [n for n in ast.walk(tree) if isinstance(n, ast.Name)
             and isinstance(n.ctx, ast.Store) and n.id == name]
    values = [n.value for n in tree.body if isinstance(n, ast.Assign)
              and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
              and n.targets[0].id == name]
    return len(nodes) == len(values) == 1 and ast.dump(values[0]) == ast.dump(ast.parse(expression).body[0].value)


def adapter_valid(tree):
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'AiReportingState']
    if len(classes) != 1:
        return False
    expected = ast.parse('''@dataclass(frozen=True)
class AiReportingState:
    _namespace: Mapping[str, Any] = field(repr=False)
    def __getattr__(self, name: str) -> Any:
        if name not in AI_REPORTING_FIELDS:
            raise AttributeError(name)
        try:
            return self._namespace[name]
        except KeyError:
            raise AttributeError(name) from None
''').body[0]
    actual = classes[0]
    actual.body = [n for n in actual.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))]
    return ast.dump(actual) == ast.dump(expected)


def audit_ai_reporting(root):
    runtime = ast.parse((root / PREFIX / 'runtime.py').read_text())
    state = ast.parse((root / PREFIX / 'ai_reporting_dependencies.py').read_text())
    violations = []
    imports = [(n.module, a.name, a.asname) for n in runtime.body
               if isinstance(n, ast.ImportFrom) for a in n.names]
    required = [('functools', 'partial', None),
                ('ladder_dragon.dashboard.ai_reporting_dependencies', 'AiReportingState', None)]
    trees = [state]
    for module, names in OWNERS.items():
        tree = ast.parse((root / PREFIX / 'services' / (module + '.py')).read_text())
        trees.append(tree)
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
        if {n.name for n in functions} != set(names) or len(functions) != len(names):
            violations.append(module + ':owner_set_changed')
        for name, count in names.items():
            owned = [n for n in functions if n.name == name]
            if len(owned) != 1 or len(owned[0].body) < count:
                violations.append(name + ':concrete_owner_missing')
            alias = '_ai_calibration' if name == 'calibration' else None
            required.append(('ladder_dragon.dashboard.services.' + module, name, alias))
    for item in required:
        if imports.count(item) != 1:
            violations.append(item[1] + ':canonical_import_missing')
    for name, expression in BINDINGS.items():
        if not binding_matches(runtime, name, expression):
            violations.append(name + ':live_binding_changed')
    protected = set(BINDINGS) | {'_ai_calibration'}
    if any(isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in protected for n in ast.walk(runtime)):
        violations.append('runtime:owner_returned')
    if not binding_matches(state, 'AI_REPORTING_FIELDS', 'frozenset(' + repr(FIELDS) + ')') or not adapter_valid(state):
        violations.append('state:live_scope_changed')
    for tree in trees:
        for n in ast.walk(tree):
            modules = ([n.module or ''] if isinstance(n, ast.ImportFrom) else
                       [a.name for a in n.names] if isinstance(n, ast.Import) else [])
            if any(m == 'ladder_dragon.dashboard.runtime' or m == 'bin' or m.startswith('bin.') for m in modules):
                violations.append('service:reverse_import')
    return violations


def check_ai_reporting(context):
    started = time.monotonic()
    try:
        violations = audit_ai_reporting(context.root)
        status = Status.FAILED if violations else Status.PASS
    except (OSError, SyntaxError, ValueError, TypeError) as exc:
        violations, status = [type(exc).__name__], Status.BLOCKED
    return CheckResult(name='architecture_ai_reporting', status=status, required=True,
                       duration_ms=int((time.monotonic() - started) * 1000),
                       summary='Concrete AI reporting services and live composition',
                       exit_code=EXIT_CODES[status], metrics={'violations': violations})
