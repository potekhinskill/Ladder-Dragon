"""Evidence commands keep confirmation gates, provenance, and temporal inputs."""

import ast
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests.architecture.ast_contracts import extraction_digest
from tests.architecture.test_five_audit_extractions import checkout
from ladder_dragon.verification.architecture.command_ownership import EVIDENCE_COMMANDS
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner

ROOT = Path(__file__).resolve().parents[2]
DIGESTS = {
    "migrate_volatility_policy": "1e5fa824fd977a75ffbec41a5469886309b8cbf697f1a2317bb4b9483fafb75c",
    "volatility_policy": "fd73575ba28c90f7cf7026469f4610c7c1e9cdccd385b266ba0496fda2a6bef9",
    "import_entry_veto_l2": "121d5c577cf7ee89b4336c3a1483730a76145d2d2700d14b42985ba5d1a14c8d",
    "backfill_prediction_archive": "58f2560c536f43fe69665e8bfe9c3e0c40de2e28d1870b5d5d5d38b332347882",
    "import_v23_confirmation": "8798285d0371426e92c65dde157088486b2f84846abb9a8268a93ec282f8a6e8",
}


@pytest.mark.parametrize("name", EVIDENCE_COMMANDS)
def test_syntax_and_offline_cli(name, tmp_path):
    source = ROOT / (EVIDENCE_COMMANDS[name].replace(".", "/") + ".py")
    assert extraction_digest(ast.parse(source.read_text())) == DIGESTS[name]
    for args, code in [(["--help"], 0), ([], 2)]:
        result = subprocess.run([sys.executable, "-m", f"bin.{name}", *args], cwd=tmp_path,
            env={"PATH": os.defpath, "PYTHONPATH": str(ROOT), "PYTHON_DOTENV_DISABLED": "1"},
            capture_output=True, text=True, timeout=30)
        assert result.returncode == code
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("name", EVIDENCE_COMMANDS)
@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("damage", ["launcher", "forwarder", "reverse", "missing"])
def test_required_ownership_rejects_regression(checkout, name, profile, damage):
    source = checkout / (EVIDENCE_COMMANDS[name].replace(".", "/") + ".py")
    if damage == "launcher":
        path = checkout / f"bin/{name}.py"
        path.write_text(path.read_text() + "\ndef misplaced(): return 1\n")
    elif damage == "forwarder":
        source.write_text("def main():\n    return legacy()\n")
    elif damage == "reverse":
        source.write_text(source.read_text() + f"\nfrom bin.{name} import main as legacy\n")
    else:
        source.unlink()
    context = HarnessContext(root=checkout, python=sys.executable, options=HarnessOptions(
        profile=profile, output=checkout / "report.json"))
    check, = [c for c in checks_for_profile(context) if c.name == "architecture_command_ownership"]
    assert check.required
    assert HarnessRunner(context)._run_spec(check).status is (
        Status.BLOCKED if damage == "missing" else Status.FAILED)


@pytest.mark.parametrize("name,args,operation", [
    ("migrate_volatility_policy", ["--policy", "synthetic", "--report-directory", "synthetic"], "migrate_legacy_volatility_policy"),
    ("volatility_policy", ["synthetic", "--cutoff-ts-ms", "100", "--created-at-ms", "100", "--output", "synthetic"], "select_volatility_policy"),
    ("import_v23_confirmation", ["--prediction-db", "synthetic", "--report", "r", "h", "q", "h"], "PredictionShadowStore"),
])
def test_confirmation_rejected_before_authority(name, args, operation, monkeypatch):
    module = importlib.import_module(EVIDENCE_COMMANDS[name])
    def forbidden(*args, **kwargs):
        pytest.fail("operation invoked before confirmation")
    monkeypatch.setattr(module, operation, forbidden)
    monkeypatch.setattr(sys, "argv", [name, *args, "--confirm", "WRONG"])
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2


@pytest.mark.parametrize("directory", [False, True])
def test_l2_selects_exactly_one_source(directory, monkeypatch, capsys):
    from ladder_dragon.strategy.prediction import entry_veto_import_command as module
    store = object()
    calls = []
    monkeypatch.setattr(module, "PredictionShadowStore", lambda path: store)
    def archive(*args):
        calls.append(("archive", args)); return {"synthetic": True}
    def history(*args):
        calls.append(("history", args)); return {"synthetic": True}
    monkeypatch.setattr(module, "import_entry_veto_l2_archive", archive)
    monkeypatch.setattr(module, "import_entry_veto_l2_history", history)
    monkeypatch.setattr(sys, "argv", ["import", "--prediction-db", "synthetic", "--archive-directory" if directory else "--archive", "source"])
    assert module.main() == 0
    assert calls == [("history" if directory else "archive", (store, Path("source")))]
    assert json.loads(capsys.readouterr().out) == {"synthetic": True}


@pytest.mark.parametrize("fails", [False, True])
def test_backfill_verifies_source_before_store_and_preserves_cutoff(fails, monkeypatch, capsys):
    from ladder_dragon.strategy.prediction import archive_backfill_command as module
    calls = []
    def load(path):
        calls.append("verified")
        if fails:
            raise ValueError("synthetic damaged archive")
        return SimpleNamespace(symbol="SOLUSDT", bars=("synthetic-bar",), source_sha256="a" * 64)
    class Store:
        def __init__(self, path):
            assert calls == ["verified"]
            calls.append("store")
        def backfill_expired(self, symbol, bars, **kwargs):
            assert symbol == "SOLUSDT" and bars == ("synthetic-bar",)
            assert kwargs == {"source_sha256": "a" * 64, "as_of_ms": 123}
            return 1
    monkeypatch.setattr(module, "load_verified_prediction_archive", load)
    monkeypatch.setattr(module, "PredictionShadowStore", Store)
    args = ["synthetic", "--database", "synthetic.sqlite", "--as-of-ms", "123"]
    if fails:
        with pytest.raises(ValueError):
            module.main(args)
        assert calls == ["verified"]
    else:
        assert module.main(args) == 0
        assert json.loads(capsys.readouterr().out)["trading_changes"] is False


@pytest.mark.parametrize("fails", [False, True])
def test_confirmation_preserves_report_identities_and_failure(fails, monkeypatch, capsys):
    from ladder_dragon.strategy.prediction import confirmation_import_command as module
    store = object()
    monkeypatch.setattr(module, "PredictionShadowStore", lambda path: store)
    def import_reports(actual, reports):
        assert actual is store and reports == [(Path("report"), "a" * 64, Path("request"), "b" * 64)]
        if fails:
            raise ValueError("synthetic")
        return {"apply_allowed": False}
    monkeypatch.setattr(module, "import_v23_confirmation_reports", import_reports)
    monkeypatch.setattr(sys, "argv", ["import", "--prediction-db", "synthetic", "--report", "report", "a" * 64,
        "request", "b" * 64, "--confirm", "IMPORT-V23-DISJOINT-CONFIRMATION"])
    assert module.main() == (2 if fails else 0)
    output = capsys.readouterr().out
    assert "BLOCKED" in output if fails else json.loads(output)["apply_allowed"] is False


def test_migration_passes_exact_paths(monkeypatch, capsys):
    from ladder_dragon.strategy import volatility_migration_command as module
    def migrate(policy, reports):
        assert (policy, reports) == (Path("synthetic-policy"), Path("synthetic-reports"))
        return {"schema_version": 3, "policy_sha256": "a" * 64}
    monkeypatch.setattr(module, "migrate_legacy_volatility_policy", migrate)
    monkeypatch.setattr(sys, "argv", ["migrate", "--policy", "synthetic-policy", "--report-directory",
        "synthetic-reports", "--confirm", "MIGRATE-FROZEN-VOLATILITY-POLICY"])
    assert module.main() == 0
    assert json.loads(capsys.readouterr().out)["policy_sha256"] == "a" * 64
