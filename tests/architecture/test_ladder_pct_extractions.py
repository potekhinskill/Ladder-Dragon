"""Exact legacy ladder syntax, synthetic dispatch, and required ownership."""

import ast
import copy
from decimal import Decimal
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ladder_dragon.strategy import ladder_pct_command as command
from ladder_dragon.strategy import ladder_pct_dispatch as dispatch
from ladder_dragon.strategy import ladder_pct_market as market
from ladder_dragon.strategy import ladder_pct_math as math
from ladder_dragon.verification.architecture.ladder_pct_ownership import LADDER_OWNERS, LADDER_LINKS
from ladder_dragon.verification.models import Status
from tests.architecture.ast_contracts import extraction_digest
from tests.architecture.test_digest_extractions import _check
from tests.architecture.test_five_audit_extractions import checkout

ROOT = Path(__file__).resolve().parents[2]
# Captured from the original command before extraction.
DIGESTS = {
    "die": "7242b1f23d0c4ac3b272077b112ad16e22d5b86f2345b1e706401899b391b9c6",
    "round_down_to_step": "9505bebf0457200c052f1d3a9af9dc9716353860ab8f094125a3f4bd9b078001",
    "round_up_to_step": "1348c935c3eb9462dd1db2ed6dd68d310761858f4099750c6a27f9ad65ae239b",
    "fmt_decimal": "4b4ffce9f0f50ce3aa061f464f60971978bfc85556a0ab2e6ff5da69de0f8586",
    "calc_atr": "c910960fbafde465911968848ef671cb51a83e48b0802a7147e8852f8f66a116",
    "parse_args": "3e7ee4776e2caa1c98454d07af0d1ab183ccac09329cce7d48b75d6a3c6d50ac",
    "_filters_decimal": "450415e8b98124e5173d9241c386f5284f84e2aad0b52133e3e623cc24360663",
    "_now_price_decimal": "a129e854dedc6518e7a808c950a4d6243a5544b77e6eb43ede9053cfd4ca882b",
    "main": "1ed1913cf4858bc09f5ba3d511a061cfb8fff96edeaed78cff69ad69132c5f8e",
}


def path(owner, root=ROOT):
    return root / f"ladder_dragon/strategy/ladder_pct_{owner}.py"


def definitions():
    return {n.name: n for owner in LADDER_OWNERS for n in ast.parse(path(owner).read_text()).body
            if isinstance(n, ast.FunctionDef)}


@pytest.mark.parametrize("name", DIGESTS)
def test_original_functions_survive_exact_recomposition(name):
    nodes = definitions()
    node = copy.deepcopy(nodes[name])
    if name == "main":
        substitutions = {
            "parse_percentages": ("min_pct_in, max_pct_in, density = parse_percentages(args)", "return min_pct_in, max_pct_in, density"),
            "raw_levels": ("min_pct, max_pct, atr_pct, buy_q, sell_q = raw_levels(now, tick, min_pct_in, max_pct_in, density, np, atr_abs)", "return min_pct, max_pct, atr_pct, buy_q, sell_q"),
            "check_min_notional": ("check_min_notional(args, flt)", None),
            "launch_executor": ("return launch_executor(args, symbol, levels_str)", None),
        }
        body = []
        restored = set()
        for statement in node.body:
            for nested, marker in (("uniq_keep", "buy_q = uniq_keep(buy_q)"),
                                   ("thin_ticks", "buy_q_sorted = thin_ticks(buy_q_sorted, tick, int(args.min_ticks_gap))"),
                                   ("thin_abs_pct", "gap_pct = Decimal(str(max(0.0, args.min_abs_gap_pct)))")):
                if ast.dump(statement) == ast.dump(ast.parse(marker).body[0]):
                    body.append(copy.deepcopy(nodes[nested]))
                    restored.add(nested)
            for helper, (call, returned) in substitutions.items():
                if ast.dump(statement) == ast.dump(ast.parse(call).body[0]):
                    contents = copy.deepcopy(nodes[helper].body)
                    if returned is not None:
                        assert ast.dump(contents.pop()) == ast.dump(ast.parse(returned).body[0])
                    body.extend(contents)
                    restored.add(helper)
                    break
            else:
                body.append(statement)
        assert restored == set(substitutions) | {"uniq_keep", "thin_ticks", "thin_abs_pct"}
        node.body = body
    assert extraction_digest(ast.Module(body=[node], type_ignores=[])) == DIGESTS[name]


def test_float_calls_are_relocated_not_added():
    calls = [n for owner in LADDER_OWNERS for n in ast.walk(ast.parse(path(owner).read_text()))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "float"]
    assert len(calls) == 6


@pytest.mark.parametrize("profile", ["local", "release"])
def test_complete_ladder_fixture_passes(checkout, profile):
    assert _check(checkout, profile) is Status.PASS


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("owner", LADDER_OWNERS)
@pytest.mark.parametrize("damage", ["missing", "forwarder", "reverse"])
def test_required_harness_rejects_owner_damage(checkout, profile, owner, damage):
    target = path(owner, checkout)
    if damage == "missing":
        target.unlink()
    elif damage == "reverse":
        target.write_text(target.read_text() + "\nfrom bin.ladder_pct_runner import main\n")
    else:
        tree = ast.parse(target.read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == LADDER_OWNERS[owner][0])
        fn.body = ast.parse("return legacy()").body
        target.write_text(ast.unparse(tree))
    assert _check(checkout, profile) is (Status.BLOCKED if damage == "missing" else Status.FAILED)


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("owner,dependency", [(o, d) for o, links in LADDER_LINKS.items() for d in links])
def test_required_harness_rejects_detached_component(checkout, profile, owner, dependency):
    target = path(owner, checkout)
    target.write_text(target.read_text().replace(f"from ladder_dragon.strategy.ladder_pct_{dependency} import", "from unreviewed import"))
    assert _check(checkout, profile) is Status.FAILED


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("damage", ["precision", "dotenv", "launcher"])
def test_required_harness_preserves_startup_and_launcher(checkout, profile, damage):
    target = path("command", checkout)
    if damage == "precision":
        target.write_text(target.read_text().replace("prec = 28", "prec = 12"))
    elif damage == "dotenv":
        target.write_text(target.read_text().replace("load_dotenv()", "pass"))
    else:
        target = checkout / "bin/ladder_pct_runner.py"
        target.write_text(target.read_text() + "\nmain()\n")
    assert _check(checkout, profile) is Status.FAILED


@pytest.fixture
def synthetic(monkeypatch):
    calls, launches = [], []
    filters = {"tickSize": "1", "minNotional": "5", "stepSize": "0.01"}

    def read(name, value):
        def get(*args, **kwargs):
            calls.append(name)
            return value
        return get

    monkeypatch.setattr(market, "TM", SimpleNamespace(
        get_ticker_price=read("ticker", "100"), get_symbol_filters=read("filters", filters),
        get_klines=read("klines", []), BinanceHttpError=RuntimeError))
    monkeypatch.setitem(sys.modules, "numpy", SimpleNamespace(
        geomspace=lambda a, b, num: SimpleNamespace(tolist=lambda: [a, b])))

    def run(argv, check):
        assert check is False
        launches.append(argv)
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(dispatch.subprocess, "run", run)
    monkeypatch.delenv("BOT_CAP_PER_ORDER", raising=False)

    def invoke(*args):
        monkeypatch.setattr(sys, "argv", ["ladder_pct_runner", "--symbol", "solusdt", "--ladder-pct=-1,-1,2", *args])
        return command.main()

    return invoke, calls, launches, filters


@pytest.mark.parametrize("side,levels", [("both", "99,101"), ("buys", "99"), ("sells", "101")])
def test_ordered_reads_exact_levels_and_child_exit(synthetic, side, levels):
    invoke, reads, launches, _filters = synthetic
    with pytest.raises(SystemExit) as exc:
        invoke("--one-side", side, "--live", "--only-new-fills")
    assert exc.value.code == 7
    assert reads == ["ticker", "filters", "klines"]
    assert launches == [["python3", "-u", "bin/autosize_universal.py", "--symbol", "SOLUSDT",
                         "--ladder-prices", levels, "--live", "--only-new-fills",
                         "--max-oco-per-symbol", "4", "--tp1", "0.08", "--tp2", "0.08",
                         "--sl", "-0.015", "--status-interval", "1", "--loop-minutes", "5"]]


@pytest.mark.parametrize("kill", [False, True])
def test_empty_filter_result_never_launches(synthetic, kill):
    invoke, reads, launches, _filters = synthetic
    arguments = ["--one-side", "buys", "--min-buy-offset-pct", "50"]
    if kill:
        with pytest.raises(SystemExit) as exc:
            invoke(*arguments, "--kill-if-empty")
        assert exc.value.code == 4
    else:
        assert invoke(*arguments) == 0
    assert launches == [] and reads == ["ticker", "filters", "klines"]


def test_strict_notional_stops_before_child(synthetic):
    invoke, _reads, launches, _filters = synthetic
    with pytest.raises(SystemExit) as exc:
        invoke("--min-order-usdt", "1", "--strict-minnotional")
    assert exc.value.code == 3 and not launches


def test_legacy_invalid_cap_fallback_is_unchanged(synthetic, monkeypatch):
    invoke, _reads, launches, _filters = synthetic
    monkeypatch.setenv("BOT_CAP_PER_ORDER", "invalid-synthetic")
    with pytest.raises(SystemExit) as exc:
        invoke("--strict-minnotional")
    assert exc.value.code == 7 and len(launches) == 1


def test_invalid_percentages_fail_before_market_reads(synthetic):
    invoke, reads, launches, _filters = synthetic
    with pytest.raises(SystemExit) as exc:
        invoke("--ladder-pct=1,2,2")
    assert exc.value.code == 2 and not reads and not launches


def test_invalid_tick_stops_before_klines(synthetic):
    invoke, reads, launches, filters = synthetic
    filters["tickSize"] = "-1"
    with pytest.raises(SystemExit) as exc:
        invoke()
    assert exc.value.code == 6 and reads == ["ticker", "filters"] and not launches


def test_keyboard_interrupt_keeps_exit_130(synthetic, monkeypatch):
    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt
    monkeypatch.setattr(dispatch.subprocess, "run", interrupt)
    with pytest.raises(SystemExit) as exc:
        synthetic[0]()
    assert exc.value.code == 130


def test_decimal_helpers_keep_rounding_and_spacing():
    d = Decimal
    assert math.round_down_to_step(d("100.125"), d("0.01")) == d("100.12")
    assert math.round_up_to_step(d("100.125"), d("0.01")) == d("100.13")
    assert math.uniq_keep([d("1.0"), d("1"), d("2")]) == [d("1"), d("2")]
    assert math.thin_ticks([d("99"), d("98"), d("97")], d("1"), 2) == [d("99"), d("97")]
    assert math.thin_abs_pct([d("100"), d("101"), d("103")], d("2")) == [d("100"), d("103")]
