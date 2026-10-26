"""Ticker ownership, import isolation and unchanged exact validation."""

import ast
from decimal import Decimal
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from ladder_dragon.market_data import tickers
from ladder_dragon.verification.architecture.market_tickers import OWNER, OWNER_PATH, CONSUMER, POLICY
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner
from tests.architecture.ast_contracts import extraction_digest, restore_transport_diagnostic_import

ROOT = Path(__file__).resolve().parents[2]
DIGESTS = {
    OWNER_PATH: "da7647ab417a9783f40bac97db03809272a618bcd1163f224cf8b66ad58afe61",
    CONSUMER: "4431456ef7a89ca62eaa90b145fb1c05656ef95b984b0a6281ea5e7186f36c81",
}


@pytest.mark.parametrize("path", DIGESTS)
def test_pre_move_syntax(path):
    tree = ast.parse((ROOT / path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == OWNER:
            node.module = "ladder_dragon.execution.market_tickers"
    assert extraction_digest(restore_transport_diagnostic_import(tree)) == DIGESTS[path]


def test_requested_exact_values_and_missing_observations():
    exact = "1.123456789123456789"
    assert tickers.requested_prices([
        {"symbol": "SOLUSDT", "price": exact}, {"symbol": "UNUSED", "price": "0"},
    ], {"SOLUSDT", "MISSING"}) == {"SOLUSDT": Decimal(exact)}
    with pytest.raises(ValueError, match="invalid batch ticker response"):
        tickers.requested_prices([{"symbol": "UNUSED"}] * 2, set())


def test_real_adapter_uses_canonical_validator():
    from ladder_dragon.execution import tools_market
    assert tools_market.valuation_prices is tickers.valuation_prices


def test_public_import_without_execution_or_network(tmp_path):
    code = '''
import sys, importlib.abc
class Deny(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('ladder_dragon.execution', 'ladder_dragon.supervision', 'requests', 'dotenv')):
            raise AssertionError('unexpected capability')
sys.meta_path.insert(0, Deny())
from ladder_dragon.market_data.tickers import requested_prices
assert requested_prices([], {'SOLUSDT'}) == {}
'''
    result = subprocess.run([sys.executable, "-S", "-c", code], cwd=tmp_path,
        env={"PATH": os.defpath, "PYTHONPATH": str(ROOT), "PYTHON_DOTENV_DISABLED": "1"},
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("profile", ("local", "release"))
@pytest.mark.parametrize("damage", (
    None, "missing", "syntax", "stub", "method_stub", "requested_stub", "reverse",
    "relative", "initializer", "policy", "legacy", "import", "shadow",
))
def test_required_contract(tmp_path, profile, damage):
    for path in (OWNER_PATH, CONSUMER, POLICY, "ladder_dragon/market_data/__init__.py"):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)
    owner, consumer = tmp_path / OWNER_PATH, tmp_path / CONSUMER
    if damage == "missing":
        owner.unlink()
    elif damage == "syntax":
        owner.write_text("def")
    elif damage == "stub":
        owner.write_text("from legacy import *\n")
    elif damage in {"method_stub", "requested_stub"}:
        tree = ast.parse(owner.read_text())
        name = "valuation_prices" if damage == "method_stub" else "requested_prices"
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        node.body = ast.parse("return legacy()").body
        owner.write_text(ast.unparse(tree))
    elif damage in {"reverse", "relative", "initializer", "policy"}:
        target = (owner.parent / "__init__.py" if damage == "initializer"
                  else tmp_path / POLICY if damage == "policy" else owner)
        target.write_text(target.read_text() + ("\nfrom ..execution import tools_market\n"
                          if damage == "relative" else "\nimport ladder_dragon.execution.tools_market\n"))
    elif damage == "legacy":
        (consumer.parent / "market_tickers.py").write_text("from ladder_dragon.market_data.tickers import *\n")
    elif damage == "import":
        consumer.write_text(consumer.read_text().replace(OWNER, "ladder_dragon.execution.market_tickers"))
    elif damage == "shadow":
        consumer.write_text(consumer.read_text() + "\nvaluation_prices = lambda *args: {}\n")
    context = HarnessContext(root=tmp_path, python=sys.executable,
                             options=HarnessOptions(profile=profile, output=tmp_path / "report.json"))
    spec, = [s for s in checks_for_profile(context) if s.name == "architecture_market_tickers"]
    assert spec.required
    result = HarnessRunner(context)._run_spec(spec)
    expected = (Status.PASS if damage is None else Status.BLOCKED
                if damage in {"missing", "syntax"} else Status.FAILED)
    assert result.status is expected, result.metrics
