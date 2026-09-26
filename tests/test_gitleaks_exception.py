# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: constrain secret-scan exceptions to reviewed reproducible findings.
"""Exact historical findings never exempt a path, rule, or future commit."""

import ast
from pathlib import Path
import subprocess

import pytest

from tests.architecture import test_history_route_extraction as history_contract


ROOT = Path(__file__).resolve().parents[1]
HISTORY_COMMIT = "dfb68bac6037e6205f60410309575b5109a7b266"
HISTORY_PATH = "tests/architecture/test_history_route_extraction.py"
HISTORY_FINDINGS = ((32, "api_trades_filled"), (33, "api_orders_filled"), (34, "api_fills"))


def test_gitleaks_exceptions_are_exactly_the_reviewed_fingerprints():
    entries = [
        line.strip()
        for line in (ROOT / ".gitleaksignore").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert entries == [
        "7fd70b96b2dff80242e942aadbbcd2582a496166:"
        "ladder_dragon/execution/journal/buy_inventory.py:generic-api-key:11"
    ] + [f"{HISTORY_COMMIT}:{HISTORY_PATH}:generic-api-key:{line}"
         for line, _ in HISTORY_FINDINGS]


def test_reviewed_finding_is_a_metadata_field_not_a_credential():
    source = ROOT / "ladder_dragon/execution/journal/buy_inventory.py"
    bindings = [
        node for node in ast.parse(source.read_text()).body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "SETTLEMENT_KEY"
                for target in node.targets)
    ]
    assert len(bindings) == 1
    assert ast.literal_eval(bindings[0].value) == "buy_inventory_settlement_v1"


@pytest.mark.parametrize("line,name", HISTORY_FINDINGS)
def test_history_finding_is_a_reproducible_syntax_digest(line, name):
    # Read only the public historical test file, never a secret finding value.
    source = subprocess.run(
        ["git", "show", f"{HISTORY_COMMIT}:{HISTORY_PATH}"],
        cwd=ROOT, check=True, capture_output=True, text=True, timeout=10,
    ).stdout
    bindings = [node for node in ast.parse(source).body
                if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "DIGESTS"
                        for target in node.targets)]
    assert len(bindings) == 1
    entries = bindings[0].value
    assert isinstance(entries, ast.Dict)
    matched = [(key, value) for key, value in zip(entries.keys, entries.values)
               if isinstance(key, ast.Constant) and key.value == name]
    assert len(matched) == 1
    key, value = matched[0]
    assert key.lineno == value.lineno == line
    assert ast.literal_eval(value) == history_contract.DIGESTS[name]
    # Recompute from the concrete function; a hash-looking constant is not proof.
    history_contract.test_original_syntax(name)
