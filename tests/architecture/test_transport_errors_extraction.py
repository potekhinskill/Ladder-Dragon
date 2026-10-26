"""Transport diagnostics retain source, safe failures and mandatory ownership."""

import ast
from pathlib import Path
import shutil
import sys

import pytest

from ladder_dragon.observability import transport_errors as diagnostics
from ladder_dragon.verification.architecture.transport_errors import OWNER, OWNER_PATH, READER, CONSUMER
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner
from tests.architecture.ast_contracts import extraction_digest, restore_transport_diagnostic_import

ROOT = Path(__file__).resolve().parents[2]
DIGESTS = {
    "transport_cause": "20e6c09839004639cb0350b2b514fbe80aa04ca4b6ba72f3a8e9a758de414d0e",
    "transport_error": "7308d039e290cd8133c75a5d801ced658969f47e77a95db07d4c99d938fe98ce",
    "MarketResponseError": "9def7b4009149255db103ccffa45b196c63bb9ce260969908b5f36020e3a359b",
    "remaining_seconds": "d5f29ea6b3eb505c93915ddadb02d1b338f81d5981ab2ac7c15e2f81084001cb",
    "read_body": "c93140bb9e3c8efb64a5e6d3067fde1e5c086b1931ecd58edd7a3f6c3c3cd319",
}


@pytest.mark.parametrize("name", DIGESTS)
def test_all_relocated_and_retained_definitions_are_unchanged(name):
    path = OWNER_PATH if name.startswith("transport_") else READER
    tree = ast.parse((ROOT / path).read_text())
    node = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name)
    assert extraction_digest(node) == DIGESTS[name]


def test_consumer_syntax_changes_only_the_split_import():
    tree = restore_transport_diagnostic_import(ast.parse((ROOT / CONSUMER).read_text()))
    assert extraction_digest(tree) == "84ea0c0d2982cbc5bae45c7b0723ff3a20c0071ca24d93e3608e8cbe7d51bd20"


def test_real_consumer_and_reader_have_separate_owners():
    from ladder_dragon.execution import tools_market, market_http_body
    assert tools_market.transport_error is diagnostics.transport_error
    from urllib3.exceptions import HTTPError
    import requests
    assert tools_market.TRANSPORT_ERRORS is diagnostics.TRANSPORT_ERRORS
    assert diagnostics.TRANSPORT_ERRORS == (requests.RequestException, HTTPError)
    assert tools_market.read_body is market_http_body.read_body
    assert not hasattr(market_http_body, "transport_error")
    assert not hasattr(market_http_body, "transport_cause")
    assert diagnostics._DIAGNOSTIC_PATHS == frozenset({
        "/api/v3/time", "/api/v3/exchangeInfo", "/api/v3/ticker/price",
        "/api/v3/klines", "/api/v3/depth", "/api/v3/aggTrades",
        "/api/v3/account", "/api/v3/myTrades", "/api/v3/openOrders",
        "/api/v3/order", "/api/v3/orderList", "/api/v3/openOrderList",
    })
    assert market_http_body.MAX_RESPONSE_BYTES == 8 * 1024 * 1024
    assert market_http_body.CHUNK_BYTES == 8192


@pytest.mark.parametrize("profile", ("local", "release"))
@pytest.mark.parametrize("damage", (
    None, "missing", "syntax", "stub", "method_stub", "reverse", "relative",
    "legacy", "reader_dependency", "import", "shadow", "exception_types",
))
def test_required_contract(tmp_path, profile, damage):
    for path in (OWNER_PATH, READER, CONSUMER):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)
    owner, reader, consumer = (tmp_path / path for path in (OWNER_PATH, READER, CONSUMER))
    if damage == "missing":
        owner.unlink()
    elif damage == "syntax":
        owner.write_text("def")
    elif damage == "stub":
        owner.write_text("from legacy import *\n")
    elif damage == "method_stub":
        tree = ast.parse(owner.read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "transport_error")
        node.body = ast.parse("return legacy()").body
        owner.write_text(ast.unparse(tree))
    elif damage in {"reverse", "relative"}:
        owner.write_text(owner.read_text() + ("\nfrom ..execution import tools_market\n"
                          if damage == "relative" else "\nimport ladder_dragon.execution.tools_market\n"))
    elif damage == "legacy":
        reader.write_text(reader.read_text() + "\ndef transport_error(*args):\n    pass\n")
    elif damage == "reader_dependency":
        reader.write_text(reader.read_text() + "\nfrom ladder_dragon.observability.transport_errors import transport_error\n")
    elif damage == "import":
        consumer.write_text(consumer.read_text().replace(OWNER, "ladder_dragon.execution.market_http_body"))
    elif damage == "shadow":
        consumer.write_text(consumer.read_text() + "\ntransport_error = lambda *args: None\n")
    elif damage == "exception_types":
        owner.write_text(owner.read_text().replace("requests.RequestException, urllib_errors.HTTPError", "Exception,"))
    context = HarnessContext(root=tmp_path, python=sys.executable,
                             options=HarnessOptions(profile=profile, output=tmp_path / "report.json"))
    spec, = [s for s in checks_for_profile(context) if s.name == "architecture_transport_errors"]
    assert spec.required
    result = HarnessRunner(context)._run_spec(spec)
    expected = (Status.PASS if damage is None else Status.BLOCKED
                if damage in {"missing", "syntax"} else Status.FAILED)
    assert result.status is expected, result.metrics
