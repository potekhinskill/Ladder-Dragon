"""Experiment CLI ownership, exact syntax, and synthetic authority order."""

import ast
import copy
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from ladder_dragon.strategy.prediction import experiment_actions as actions
from ladder_dragon.strategy.prediction import experiment_command as command
from ladder_dragon.verification.architecture.experiment_ownership import EXPERIMENT_OWNERS, EXPERIMENT_LINKS
from ladder_dragon.verification.models import Status
from tests.architecture.ast_contracts import extraction_digest
from tests.architecture.test_digest_extractions import _check
from tests.architecture.test_five_audit_extractions import checkout

ROOT = Path(__file__).resolve().parents[2]
DIGESTS = {
    "_parser": "58e5db3777a7175a668cd4e2c295a4181c94770ad7851b8b4c2ebe6397e086ab",
    "_source_commit": "44838eadb04b3c774059a8ec583913929748de5b6b9fe6f77169bb5a522cbc2d",
    "_freeze_horizons": "6c49eaa4a36a1106e72d9a305edc12d38a92c96e004c6094610ffb2efe01017d",
    "_entry_veto_inputs": "62b941241222366f7527c6c334e2e448147175be35f26a9e360d023818451756",
    "_selection_variants": "37f7f9b43754eb9c2ab76d4ae6b9b13d160c7c7f77d1eaa0fe7353fb56fd01f4",
    "_preselected_episode_variant": "9379649b5bb52d3dc2ecf65debd42961713ec741adb86c0a0512387d79c301ad",
    "main": "9e408b71b132d36fdaaf9169f18c5df882131ddf6d933779f94408b971f887f6"
}


def path(owner, root=ROOT):
    return root / f"ladder_dragon/strategy/prediction/experiment_{owner}.py"


def definitions():
    return {n.name: n for o in EXPERIMENT_OWNERS for n in ast.parse(path(o).read_text()).body
            if isinstance(n, ast.FunctionDef)}


@pytest.mark.parametrize("name", DIGESTS)
def test_exact_original_syntax_after_recomposition(name):
    nodes = definitions()
    node = copy.deepcopy(nodes[name])
    if name == "main":
        restored = set()
        branch = node.body[2]
        while True:
            statement = branch.body[0]
            if len(branch.body) == 1 and isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Call):
                fn = statement.value.func
                if isinstance(fn, ast.Name) and fn.id.startswith("handle_"):
                    assert ast.dump(statement) == ast.dump(ast.parse(f"payload = {fn.id}(args, store)").body[0])
                    body = copy.deepcopy(nodes[fn.id].body)
                    assert ast.dump(body.pop()) == ast.dump(ast.parse("return payload").body[0])
                    branch.body = body
                    restored.add(fn.id)
            if len(branch.orelse) == 1 and isinstance(branch.orelse[0], ast.If):
                branch = branch.orelse[0]
            else:
                assert ast.dump(branch.orelse[0]) == ast.dump(ast.parse("return handle_freeze(args, store)").body[0])
                body = copy.deepcopy(nodes["handle_freeze"].body)
                assert ast.dump(ast.Module(body=body[-2:], type_ignores=[])) == ast.dump(ast.Module(body=node.body[-2:], type_ignores=[]))
                branch.orelse = body[:-2]
                restored.add("handle_freeze")
                break
        assert restored == set(EXPERIMENT_OWNERS["actions"])
    assert extraction_digest(ast.Module(body=[node], type_ignores=[])) == DIGESTS[name]


@pytest.mark.parametrize("profile", ["local", "release"])
def test_complete_fixture(checkout, profile):
    assert _check(checkout, profile) is Status.PASS


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("owner", EXPERIMENT_OWNERS)
@pytest.mark.parametrize("damage", ["missing", "forwarder", "reverse"])
def test_required_owner_rejection(checkout, profile, owner, damage):
    target = path(owner, checkout)
    if damage == "missing":
        target.unlink()
    elif damage == "reverse":
        target.write_text(target.read_text() + "\nfrom bin.prediction_experiment import main\n")
    else:
        tree = ast.parse(target.read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef))
        fn.body = ast.parse("return legacy()").body
        target.write_text(ast.unparse(tree))
    assert _check(checkout, profile) is (Status.BLOCKED if damage == "missing" else Status.FAILED)


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("owner,dependency", [(o,d) for o, links in EXPERIMENT_LINKS.items() for d in links])
def test_required_link_rejection(checkout, profile, owner, dependency):
    target = path(owner, checkout)
    target.write_text(target.read_text().replace(f"from ladder_dragon.strategy.prediction.experiment_{dependency} import", "from unreviewed import"))
    assert _check(checkout, profile) is Status.FAILED


@pytest.mark.parametrize("action", [
    "finalize", "supersede", "entry_veto_freeze", "entry_veto_import_history",
    "champion_activate", "episode_bootstrap", "model_validation_import",
])
def test_confirmation_fails_before_any_resource_access(action):
    with pytest.raises(SystemExit, match="--confirm must equal"):
        getattr(actions, f"handle_{action}")(SimpleNamespace(confirm="WRONG"), object())


@pytest.mark.parametrize("operation,function,args", [
    ("status", "list_experiments", ["--symbol", "SOLUSDT"]),
    ("show", "load_manifest", ["synthetic"]),
    ("report", "confirmation_report", ["synthetic"]),
    ("champions", "list_champions", ["--symbol", "SOLUSDT"]),
])
def test_read_dispatch_and_json(monkeypatch, capsys, operation, function, args):
    store = object()
    calls = []
    monkeypatch.setattr(command, "PredictionShadowStore", lambda p: calls.append(str(p)) or store)
    def read(s, *a, **kw):
        assert s is store
        calls.append(function)
        return {"status": "SYNTHETIC"}
    monkeypatch.setattr(command, function, read)
    assert command.main(["--database", "synthetic.sqlite", operation, *args]) == 0
    assert calls == ["synthetic.sqlite", function]
    assert json.loads(capsys.readouterr().out) == {"status": "SYNTHETIC"}


def test_help_does_not_initialize_store(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError("Store initialized before parser exit")
    monkeypatch.setattr(command, "PredictionShadowStore", forbidden)
    with pytest.raises(SystemExit) as exc:
        command.main(["--help"])
    assert exc.value.code == 0


@pytest.mark.parametrize("source_failure", [False, True])
def test_activation_holds_halt_through_source_and_writer(monkeypatch, source_failure):
    events = []
    store, limits = object(), object()
    monkeypatch.setattr(actions, "RiskLimits", SimpleNamespace(from_env=lambda: limits))
    @contextmanager
    def halt(value):
        assert value is limits
        events.append("lock")
        try:
            yield
        finally:
            events.append("unlock")
    monkeypatch.setattr(actions, "confirmed_execution_halt", halt)
    def source():
        assert events == ["lock"]
        events.append("source")
        if source_failure:
            raise RuntimeError("synthetic source failure")
        return "a" * 40
    def activate(value, **kw):
        assert value is store and events == ["lock", "source"]
        assert kw["execution_halt_confirmed"] is True
        assert kw["expected_previous_activation_id"] is None
        assert kw["source_commit"] == "a" * 40
        assert kw["maximum_order_notional_usdt"] == "6"
        events.append("write")
        return {"status": "SYNTHETIC"}
    monkeypatch.setattr(actions, "_source_commit", source)
    monkeypatch.setattr(actions, "activate_champion", activate)
    args = SimpleNamespace(confirm="ACTIVATE", expected_previous_activation_id=" NONE ",
                           experiment_id="synthetic", report_sha256="b"*64, manifest_sha256="c"*64,
                           expected_execution_policy_fingerprint="d"*64,
                           maximum_order_usdt="6", maximum_inventory_usdt="18")
    if source_failure:
        with pytest.raises(RuntimeError, match="synthetic source"):
            actions.handle_champion_activate(args, store)
        assert events == ["lock", "source", "unlock"]
    else:
        assert actions.handle_champion_activate(args, store) == {"status": "SYNTHETIC"}
        assert events == ["lock", "source", "write", "unlock"]


def test_history_mismatched_identities_stop_before_manifest():
    args = SimpleNamespace(confirm="IMPORT-HISTORICAL-VETO", report=["synthetic"], report_sha256=[])
    with pytest.raises(ValueError, match="identities are incomplete"):
        actions.handle_entry_veto_import_history(args, object())


def test_validation_fingerprint_failure_never_writes(tmp_path, monkeypatch):
    report = tmp_path / "synthetic.json"
    report.write_text('{"synthetic":true}')
    def forbidden(*a, **kw):
        raise AssertionError("Invalid report reached writer")
    monkeypatch.setattr(actions, "record_model_validation", forbidden)
    args = SimpleNamespace(confirm="IMPORT", report=report, report_sha256="0"*64)
    with pytest.raises(ValueError, match="fingerprint differs"):
        actions.handle_model_validation_import(args, object())


def test_freeze_preview_retains_blocked_exit_without_source_or_writer(monkeypatch, capsys):
    candidate = SimpleNamespace(variant_id="candidate")
    spec = SimpleNamespace(lifecycle_mode="PROMOTION", statistical_design_version="synthetic")
    monkeypatch.setattr(actions, "experiment_spec_for_generation", lambda *a, **kw: spec)
    monkeypatch.setattr(actions, "_freeze_horizons", lambda *a: (300,360))
    seen = []
    def variants(store, **kw):
        seen.append(kw["cutoff"])
        return (candidate,)
    monkeypatch.setattr(actions, "_selection_variants", variants)
    monkeypatch.setattr(actions, "variant_fingerprints", lambda *a, **kw: ("candidate-hash","baseline-hash"))
    monkeypatch.setattr(actions, "candidate_rule", lambda *a, **kw: {"rule":"synthetic"})
    def forbidden(*a, **kw):
        raise AssertionError("Preview reached mutation")
    monkeypatch.setattr(actions, "_source_commit", forbidden)
    monkeypatch.setattr(actions, "freeze_experiment", forbidden)
    args = SimpleNamespace(generation="synthetic", symbol="SOLUSDT", selection_end_ts_ms=123,
                           variant_id="candidate", confirm="", experiment_id="synthetic")
    assert actions.handle_freeze(args, object()) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "BLOCKED" and payload["apply_allowed"] is False
    assert payload["selection_end_ts_ms"] == 123 and seen == [123]
