"""Five concrete P2 owners, immutable relocation syntax, CLI and harness parity."""

import ast
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tests.architecture.ast_contracts import extraction_digest
from ladder_dragon.verification.architecture.command_ownership import COMMANDS, CONTRACTS, audit_commands
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner

ROOT = Path(__file__).resolve().parents[2]
# Pre-move HEAD syntax, excluding only __main__ and adjusting checkout depth.
DIGESTS = {
    "semantic_authorities": "d591602d723f3ed5c37564c073623654f47ab84d31f59ce1b065b3bec3361c0a",
    "exchange_boundaries": "6c8499c72984def990c7803cf7efe34417b0b19f40b44cd8c4f5dcaba3413444",
    "guard_contracts": "dd888da37916b0bf133e05c8ae377d00816681a3c819b5d76f99ae1d194f7d3b",
    "ai_readiness": "9ac6c0ce3684e7931873f0d63f1dabf5c4aad427cde34f15cb8be5ac5464f7ff",
    "replay_readiness": "2990a3caf996fec5ad1d4b1b419622c7b95931d4fa5bfa1a8e872210fe5ad0b4",
}


@pytest.mark.parametrize("name", COMMANDS)
def test_unchanged_concrete_implementation(name):
    owner, _ = COMMANDS[name]
    assert extraction_digest(ast.parse((ROOT/f"ladder_dragon/verification/{owner}.py").read_text())) == DIGESTS[name]
    assert audit_commands(ROOT) == []


def cli(name, tmp_path, *args):
    return subprocess.run([sys.executable,"-m",f"bin.audit_{name}",*args],cwd=tmp_path,
                          env={"PATH":os.defpath,"PYTHONPATH":str(ROOT),"PYTHON_DOTENV_DISABLED":"1"},
                          capture_output=True,text=True,timeout=30)


@pytest.mark.parametrize("name", list(COMMANDS)[:3])
def test_real_safety_command_checkout_and_output(name,tmp_path):
    owner, function = COMMANDS[name]
    expected = getattr(importlib.import_module(f"ladder_dragon.verification.{owner}"),function)(ROOT)
    result = cli(name,tmp_path)
    assert result.returncode == (0 if expected["ready"] else 2)
    assert json.loads(result.stdout) == expected
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("name", ["ai_readiness","replay_readiness"])
def test_readiness_help_and_required_arguments_remain_offline(name,tmp_path):
    assert cli(name,tmp_path,"--help").returncode == 0
    assert cli(name,tmp_path).returncode == 2
    assert list(tmp_path.iterdir()) == []


@pytest.fixture
def checkout(tmp_path):
    from ladder_dragon.verification.architecture.experiment_ownership import EXPERIMENT_OWNERS
    for owner in EXPERIMENT_OWNERS:
        relative = f"ladder_dragon/strategy/prediction/experiment_{owner}.py"
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, path)
    from ladder_dragon.verification.architecture.ladder_pct_ownership import LADDER_OWNERS
    for owner in LADDER_OWNERS:
        relative = f"ladder_dragon/strategy/ladder_pct_{owner}.py"
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, path)
    from ladder_dragon.verification.architecture.runtime_entry_ownership import INERT_PACKAGES
    for relative in INERT_PACKAGES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, path)
    from ladder_dragon.verification.architecture.harness_ownership import HARNESS_OWNERS
    for relative in ["ladder_dragon/__init__.py", *[owner.replace(".", "/") + ".py" for owner in HARNESS_OWNERS]]:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, path)
    from ladder_dragon.verification.architecture.command_ownership import SOAK_OWNERS
    for owner in SOAK_OWNERS:
        relative = f"ladder_dragon/verification/live/{owner}.py"
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, path)
    from ladder_dragon.verification.architecture.command_ownership import AUTHORITY_OWNERS
    for owner in AUTHORITY_OWNERS:
        relative = f"ladder_dragon/verification/{owner}.py"
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, path)
    from ladder_dragon.verification.architecture.command_ownership import AUTOTUNE_OWNERS
    for owner in AUTOTUNE_OWNERS:
        relative = f"ladder_dragon/strategy/{owner}.py"
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, path)
    from ladder_dragon.verification.architecture.command_ownership import DIGEST_OWNERS
    for owner in DIGEST_OWNERS:
        relative = f"ladder_dragon/execution/{owner}.py"
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, path)
    for name,(owner,_) in CONTRACTS.items():
        for relative in (f"bin/{name}.py",owner.replace(".", "/") + ".py"):
            path=tmp_path/relative;path.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/relative,path)
    return tmp_path


@pytest.mark.parametrize("profile",["local","release"])
@pytest.mark.parametrize("name",COMMANDS)
@pytest.mark.parametrize("damage",["launcher_logic","forwarder","reverse_import","missing"])
def test_required_harness_rejects_regression(checkout,profile,name,damage):
    owner,definition=COMMANDS[name]
    launcher=checkout/f"bin/audit_{name}.py"
    source=checkout/f"ladder_dragon/verification/{owner}.py"
    if damage=="launcher_logic":
        launcher.write_text(launcher.read_text()+"\ndef misplaced(): return 1\n")
    elif damage=="forwarder":
        source.write_text(f"def {definition}(*args):\n    return legacy(*args)\n")
    elif damage=="reverse_import":
        source.write_text(source.read_text()+f"\nfrom bin.audit_{name} import main as legacy\n")
    else:
        source.unlink()
    context=HarnessContext(root=checkout,python=sys.executable,options=HarnessOptions(
        profile=profile,output=checkout/"report.json"))
    checks=[c for c in checks_for_profile(context) if c.name=="architecture_command_ownership"]
    assert len(checks)==1 and checks[0].required
    result=HarnessRunner(context)._run_spec(checks[0])
    assert result.status is (Status.BLOCKED if damage=="missing" else Status.FAILED)


@pytest.mark.parametrize("ready",[True,False])
@pytest.mark.parametrize("name",["ai_readiness","replay_readiness"])
def test_readiness_command_preserves_gate_exit_and_options(name,ready,monkeypatch,capsys):
    owner,_=COMMANDS[name]
    module=importlib.import_module(f"ladder_dragon.verification.{owner}")
    calls=[]
    class Report:
        def as_dict(self): return {"ready":ready,"synthetic":True}
    report=Report();report.ready=ready
    def audit(*args,**kwargs):
        calls.append((args,kwargs));return report
    monkeypatch.setattr(module,f"audit_{name}",audit)
    if name=="ai_readiness":
        argv=["audit","--db","synthetic.sqlite3","--symbol","SOLUSDT"]
    else:
        argv=["audit","synthetic.json"]
        monkeypatch.setattr(module,"read_calibration",lambda path: {"synthetic":path})
    monkeypatch.setattr(sys,"argv",argv)
    assert module.main()==(0 if ready else 2)
    assert json.loads(capsys.readouterr().out)==report.as_dict()
    assert len(calls)==1
    assert calls[0][1]["minimum_closed_decisions" if name=="ai_readiness" else "minimum_archives"]==(60 if name=="ai_readiness" else 3)
