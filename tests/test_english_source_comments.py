import ast
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = ("ladder_dragon", "bin", "FastAPI", "deploy", "FRONT")
SOURCE_SUFFIXES = {".py", ".sh", ".js", ".ts", ".html", ".css", ".sql"}
CYRILLIC = re.compile(r"[\u0400-\u04ff]")


def _source_files():
    for root_name in SOURCE_ROOTS:
        root = ROOT / root_name
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            relative = path.relative_to(ROOT)
            if "locales" in relative.parts or path.name == "locales.js":
                continue
            yield path


def test_non_locale_source_contains_only_english_text():
    violations = []
    for path in _source_files():
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if CYRILLIC.search(line):
                violations.append(f"{path.relative_to(ROOT)}:{line_number}")
    assert violations == []


def test_critical_long_running_nodes_have_english_docstrings():
    required = {
        "ladder_dragon/supervision/runtime.py": {
            "smart_rolling",
            "position_guard_and_maybe_flatten",
            "refresh_vwap_runtime_maps",
        },
        "ladder_dragon/execution/binance_transport.py": {
            "request_with_backoff",
            "signed_request",
        },
        "ladder_dragon/execution/order_recovery.py": {
            "_init_schema",
            "prepare",
            "find_active",
        },
        "ladder_dragon/strategy/market_replay.py": {
            "process",
            "calibrate_market_events",
        },
    }
    missing = []
    for relative, names in required.items():
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        functions = {
            node.name: ast.get_docstring(node)
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for name in names:
            docstring = functions.get(name)
            if not docstring or CYRILLIC.search(docstring):
                missing.append(f"{relative}:{name}")
    assert missing == []
