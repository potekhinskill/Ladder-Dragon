"""Safety audit extraction preserves exact contracts and executable rejection."""

import ast
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.architecture.ast_contracts import extraction_digest
from tests.architecture.test_five_audit_extractions import checkout
from tests.architecture.test_digest_extractions import _check
from ladder_dragon.verification.architecture.command_ownership import AUTHORITY_OWNERS, AUTHORITY_LINKS
from ladder_dragon.verification.models import Status

ROOT = Path(__file__).resolve().parents[2]
DIGESTS = {
    "AuthorityCallContract": "20d99d09b0d36b65a687729c34cfde7d21fbc12031105db3931900e1d8c615d7",
    "AuthorityBindingContract": "fafda61fb672336cd8f216ce76cc9277d7e9fff163ae4382486acad3607223e4",
    "AUTHORITY_CALL_CONTRACTS": "ced414d35ec6c46df57f66e71b897c5594280250393e4165afa6590ef2c86726",
    "AUTHORITY_BINDING_CONTRACTS": "664f99e708d5aa234e2686feede27bff6ef77bf53e1683a085661cacc3c21e91",
    "_CallObservation": "ab7bfe40662f5693e7dbb5ce66c77de4a71f88066d9a77a28ed00e473eeb24fc",
    "_contains_positive_gate": "6feb87278b357118d821bf2b072503bf3c0e7c54b92c19163c7630f0547a613f",
    "_CallVisitor": "fc73b8380b95c86700bdc7583447aaf42608e3775306bf46c49de6f7646dc023",
    "_function_calls": "d585468da827f71aa71a5dfa095ad419078d6214f06380c355109f352866a51d",
    "_BindingVisitor": "12b9a6f269a538bb03bec0af5377a61f53f2df332e9974fc978a8fb3ebfcf9bc",
    "_scope_bindings": "199d45650b3936f32074a96287c5d4e759f65b67ef3ad331613f966836ef6062",
    "_canonical_import_count": "16f5c0190004d585287d8a2daa79d8fb1b9bf7ccd4d087193aaa57c1c103f461",
    "_module_bindings": "0feb6db2e7577a1c96b776082e1bf93683bcfa77c620d9c6e37aab7b2604aad8",
    "_canonical_class_binding_count": "c63c505ea9e45a3a3f32e802efd340efccc03c36d80b55569652c6d2d61b8ce3",
    "_audit_binding_contract": "6e06a1aa39cf4b70d52c9d952f5ddcdbbca200dd0e318700653bfc24ef24f689",
    "audit_execution_authority_paths": "878bc1a68cfa0d0e3f026833fbc800e37b0c2e9ca22b27ed0072a0ce0fad2fc3",
    "main": "2dff2eb1bdd8c6a016e67b78db080d093d8096c7f4f22dab0ce2bbdd45004303"
}


def tree(owner, root=ROOT):
    return ast.parse((root / f"ladder_dragon/verification/{owner}.py").read_text())


@pytest.mark.parametrize("name", DIGESTS)
def test_exact_original_contracts_and_implementation(name):
    nodes = [n for owner in AUTHORITY_OWNERS for n in tree(owner).body
             if getattr(n, "name", None) == name or
             isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)]
    assert len(nodes) == 1
    node = copy.deepcopy(nodes[0])
    if name == "main":
        root_expr = node.body[0].value
        assert isinstance(root_expr, ast.Subscript) and root_expr.slice.value == 2
        root_expr.slice.value = 1
    assert extraction_digest(ast.Module(body=[node], type_ignores=[])) == DIGESTS[name]


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("owner", AUTHORITY_OWNERS)
@pytest.mark.parametrize("damage", ["forwarder", "reverse", "missing"])
def test_harness_rejects_owner_damage(checkout, profile, owner, damage):
    path = checkout / f"ladder_dragon/verification/{owner}.py"
    if damage == "forwarder":
        source = tree(owner, checkout)
        node = next(n for n in source.body if getattr(n, "name", None) == AUTHORITY_OWNERS[owner][0])
        node.body = [ast.Pass()]
        path.write_text(ast.unparse(source))
    elif damage == "reverse":
        path.write_text(path.read_text() + "\nfrom bin.audit_execution_authority_paths import main as legacy\n")
    else:
        path.unlink()
    assert _check(checkout, profile) is (Status.BLOCKED if damage == "missing" else Status.FAILED)


LINKS = [(owner, dep) for owner, deps in AUTHORITY_LINKS.items() for dep in deps]


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("owner,dependency", LINKS)
def test_harness_rejects_detached_import(checkout, profile, owner, dependency):
    path = checkout / f"ladder_dragon/verification/{owner}.py"
    path.write_text(path.read_text().replace(f"verification.{dependency} import", "verification.wrong import"))
    assert _check(checkout, profile) is Status.FAILED


@pytest.mark.parametrize("profile", ["local", "release"])
@pytest.mark.parametrize("name", ["AUTHORITY_CALL_CONTRACTS", "AUTHORITY_BINDING_CONTRACTS"])
def test_harness_rejects_empty_contracts(checkout, profile, name):
    path = checkout / "ladder_dragon/verification/authority_contracts.py"
    source = tree("authority_contracts", checkout)
    target = next(n for n in source.body if isinstance(n, ast.Assign) and n.targets[0].id == name)
    target.value = ast.Tuple(elts=[], ctx=ast.Load())
    path.write_text(ast.unparse(source))
    assert _check(checkout, profile) is Status.FAILED


@pytest.mark.parametrize("profile", ["local", "release"])
def test_harness_rejects_launcher_logic(checkout, profile):
    path = checkout / "bin/audit_execution_authority_paths.py"
    path.write_text(path.read_text() + "\ndef misplaced(): return 1\n")
    assert _check(checkout, profile) is Status.FAILED


def test_command_resolves_checkout_not_working_directory(tmp_path):
    from ladder_dragon.verification.authority_paths import audit_execution_authority_paths
    result = subprocess.run([sys.executable, "-m", "bin.audit_execution_authority_paths"],
        cwd=tmp_path, env={"PATH": os.defpath, "PYTHONPATH": str(ROOT), "PYTHON_DOTENV_DISABLED": "1"},
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == audit_execution_authority_paths(ROOT)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("ready", [True, False])
def test_command_exit_and_canonical_root(ready, monkeypatch, capsys):
    from ladder_dragon.verification import authority_command as command
    roots = []
    report = {"ready": ready, "checked": [], "violations": [] if ready else ["synthetic"]}
    monkeypatch.setattr(command, "audit_execution_authority_paths", lambda root: roots.append(root) or report)
    assert command.main() == (0 if ready else 2)
    assert roots == [ROOT]
    assert json.loads(capsys.readouterr().out) == report
