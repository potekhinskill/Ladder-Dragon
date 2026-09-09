"""Mutation tests for literal service links and required profile invocation."""

import json
from pathlib import Path
import shutil

import pytest

from ladder_dragon.verification.architecture import service_links as links
from ladder_dragon.verification.architecture.surfaces import CONTRACT as SURFACES
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner


@pytest.fixture
def checkout(tmp_path):
    root = Path(__file__).resolve().parents[2]
    files = json.loads((root / SURFACES).read_text())["files"]
    for name in [*files, SURFACES, links.CONTRACT]:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    return tmp_path


def test_current_links_and_implicit_timer_targets(checkout):
    result = links.audit_service_links(checkout)
    assert result["status"] == "PASS"
    assert result["unit_count"] == 25
    assert result["installation_count"] == 7
    assert {"source": "deploy/ladder-dragon-backup.timer", "directive": "Unit",
            "target": "deploy/ladder-dragon-backup.service"} in result["edges"]
    assert "shell reachability" in result["limits"]
    assert str(checkout) not in json.dumps(result)


@pytest.mark.parametrize("change", ["target", "argument", "duplicate", "section", "empty", "new_directive"])
def test_changed_execution_contract_fails(checkout, change):
    path = checkout / "deploy/ladder-dragon-daily-digest.service"
    text = path.read_text()
    original = next(line for line in text.splitlines() if line.startswith("ExecStart="))
    replacement = {"target": original.replace("bin.daily_trading_digest", "bin.stats_view"),
                   "argument": original + " --PRIVATE_MARKER", "duplicate": original + "\n" + original,
                   "section": "[Unit]\n" + original, "empty": "# " + original,
                   "new_directive": original + "\nExecStop=/PRIVATE_MARKER"}[change]
    path.write_text(text.replace(original, replacement))
    result = links.audit_service_links(checkout)
    assert result["status"] == "FAILED"
    assert "PRIVATE_MARKER" not in json.dumps(result)


@pytest.mark.parametrize("change", ["missing_target", "changed_install", "duplicate_install", "symlink", "continuation", "timer"])
def test_invalid_targets_and_installations_cannot_pass(checkout, change):
    installer = checkout / links.INSTALLER
    expected = "FAILED"
    if change == "missing_target":
        (checkout / "bin/daily_trading_digest.py").unlink()
        expected = "BLOCKED"
    elif change == "changed_install":
        installer.write_text(installer.read_text().replace("/usr/local/bin/pi-watchdog_v3.sh", "/usr/local/bin/PRIVATE_MARKER"))
    elif change == "duplicate_install":
        installer.write_text(installer.read_text() + '\ninstall -o root -g root -m 0755 "${PROJECT_DIR}/deploy/pi-watchdog_v3.sh" /usr/local/bin/pi-watchdog_v3.sh\n')
        expected = "BLOCKED"
    elif change == "symlink":
        installer.unlink()
        private = checkout / "private"
        private.write_text("PRIVATE_MARKER")
        installer.symlink_to(private)
        expected = "BLOCKED"
    elif change == "continuation":
        (checkout / "deploy/mybot.service").write_text("[Service]\nExecStart=\\\nPRIVATE_MARKER\n")
        expected = "BLOCKED"
    else:
        (checkout / "deploy/ladder-dragon-backup.timer").write_text("[Timer]\nUnit=PRIVATE_MARKER.service\n")
    result = links.audit_service_links(checkout)
    assert result["status"] == expected
    assert "PRIVATE_MARKER" not in json.dumps(result)


@pytest.mark.parametrize("change", ["coverage", "schema", "duplicate", "path", "digest"])
def test_manifest_errors_do_not_pass(checkout, change):
    path = checkout / links.CONTRACT
    payload = json.loads(path.read_text())
    expected = "BLOCKED"
    if change == "coverage":
        payload["units"].pop("deploy/mybot.service")
        expected = "FAILED"
    elif change == "schema":
        payload["schema_version"] = True
    elif change == "duplicate":
        path.write_text('{"schema_version":1,"schema_version":1}')
        assert links.audit_service_links(checkout)["status"] == expected
        return
    elif change == "path":
        payload["installed_files"]["/usr/local/bin/test"] = "../PRIVATE_MARKER"
    else:
        payload["units"]["deploy/mybot.service"][0]["sha256"] = 4
    path.write_text(json.dumps(payload))
    result = links.audit_service_links(checkout)
    assert result["status"] == expected
    assert "PRIVATE_MARKER" not in json.dumps(result)


@pytest.mark.parametrize("profile", ["local", "release"])
def test_profile_requires_service_links(checkout, profile):
    (checkout / "deploy/mybot.service").write_text("[Service]\nExecStart=/unknown\n")
    context = HarnessContext(root=checkout, python="python", options=HarnessOptions(
        profile=profile, output=checkout / "report.json"))
    specs = [spec for spec in checks_for_profile(context) if spec.name == "architecture_service_links"]
    assert len(specs) == 1 and specs[0].required
    assert HarnessRunner(context)._run_spec(specs[0]).status is Status.FAILED


def test_read_only_targets_and_bounded_output(checkout, monkeypatch):
    (checkout / "bin/daily_trading_digest.py").write_text("raise RuntimeError('PRIVATE_MARKER')\n")
    result = links.audit_service_links(checkout)
    assert result["status"] == "PASS"
    assert "PRIVATE_MARKER" not in json.dumps(result)
    monkeypatch.setattr(links, "MAX_REPORT", 10)
    assert links.audit_service_links(checkout)["status"] == "BLOCKED"


def test_command_propagates_service_link_failure(monkeypatch, capsys):
    from ladder_dragon.verification.architecture import cli

    for name in ("audit", "audit_references", "audit_surfaces"):
        monkeypatch.setattr(cli, name, lambda root: {"status": "PASS"})
    monkeypatch.setattr(cli, "audit_service_links", lambda root: {"status": "FAILED"})
    assert cli.main() == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAILED"
