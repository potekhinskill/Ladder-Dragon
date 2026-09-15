# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: constrain the reviewed secret-scan exception to one metadata finding.
"""Do not broaden the approved historical Gitleaks exception."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_gitleaks_exception_is_exactly_one_reviewed_fingerprint():
    entries = [
        line.strip()
        for line in (ROOT / ".gitleaksignore").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert entries == [
        "7fd70b96b2dff80242e942aadbbcd2582a496166:"
        "ladder_dragon/execution/journal/buy_inventory.py:generic-api-key:11"
    ]


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
