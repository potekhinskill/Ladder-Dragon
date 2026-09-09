"""Verify routed guidance and comprehensive completion profiles without live inputs."""

from pathlib import Path
import re
import sys

import pytest

from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner
from ladder_dragon.verification.technical_english import DEFAULT_DOCUMENTS, check_documents


ROOT = Path(__file__).resolve().parents[1]
GUIDE = "docs/AGENT_WORKFLOW.md"
SKILL = ".agents/skills/ladder-dragon-architecture/SKILL.md"
AUDITS = {
    "numeric_boundary_audit": "bin.audit_numeric_boundaries",
    "semantic_authority_audit": "bin.audit_semantic_authorities",
    "exchange_boundary_audit": "bin.audit_exchange_boundaries",
    "guard_contract_audit": "bin.audit_guard_contracts",
    "execution_authority_path_audit": "bin.audit_execution_authority_paths",
}


@pytest.mark.parametrize("document", [GUIDE, SKILL])
def test_routed_documents_and_lesson_anchors_exist(document):
    path = ROOT / document
    targets = re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8"))
    assert targets
    for target in targets:
        relative, _, fragment = target.partition("#")
        destination = (path.parent / relative).resolve()
        assert destination.is_relative_to(ROOT)
        assert destination.is_file(), target
        if fragment:
            headings = re.findall(r"^#+ (.+)$", destination.read_text(encoding="utf-8"), re.M)
            anchors = {re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-") for heading in headings}
            assert fragment in anchors, target


@pytest.mark.parametrize("document", [GUIDE, SKILL])
def test_guidance_is_required_by_documentation_verification(tmp_path, document):
    assert document in DEFAULT_DOCUMENTS
    issues = check_documents(tmp_path)
    assert any(issue.path == tmp_path / document and issue.rule == "STE-MISSING-DOCUMENT" for issue in issues)
    path = tmp_path / document
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Do not " + "repeat " * 30 + "this instruction.\n", encoding="utf-8")
    issues = check_documents(tmp_path)
    assert any(issue.path == path and issue.rule == "STE-SENTENCE-LENGTH" for issue in issues)


@pytest.mark.parametrize("profile", ["local", "release"])
def test_completion_profiles_keep_unfiltered_tests_and_required_audits(tmp_path, profile):
    context = HarnessContext(root=tmp_path, python=sys.executable, options=HarnessOptions(
        profile=profile, output=tmp_path / "report.json"))
    specs = checks_for_profile(context)
    for name, module in {"pytest": "pytest", **AUDITS}.items():
        matches = [spec for spec in specs if spec.name == name]
        assert len(matches) == 1
        assert matches[0].required
        assert matches[0].argv == (sys.executable, "-m", module)
        assert matches[0].blocked_reason is None
    for name in ("source_compile", "release_continuity", "tracked_secret_scan"):
        matches = [spec for spec in specs if spec.name == name]
        assert len(matches) == 1 and matches[0].required


@pytest.mark.parametrize("profile", ["local", "release"])
def test_real_completion_command_does_not_skip_a_failing_test(tmp_path, monkeypatch, profile):
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_selected.py").write_text("def test_selected():\n    assert True\n", encoding="utf-8")
    (tests / "test_other.py").write_text(
        "def test_other():\n    assert False, 'PRIVATE_MARKER'\n", encoding="utf-8")
    context = HarnessContext(root=tmp_path, python=sys.executable, options=HarnessOptions(
        profile=profile, output=tmp_path / "report.json"))
    spec = next(spec for spec in checks_for_profile(context) if spec.name == "pytest")
    result = HarnessRunner(context)._run_spec(spec)
    assert result.required and result.status == Status.FAILED
    assert result.exit_code == 1
    assert result.metrics["passed"] == 1
    assert result.metrics["failed"] == 1
    assert "PRIVATE_MARKER" not in str(result.as_dict())
