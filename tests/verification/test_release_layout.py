"""Revision checks must fail closed without removing private or unknown files."""

import json
import os
from pathlib import Path
import subprocess

import pytest

from ladder_dragon.verification import release_layout as layout


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.DEVNULL).decode().strip()


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "commit.gpgsign", "false")
    for name in ("bin/live.py", "bin/old.py", "deploy/tool.py"):
        path = root / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("pass\n")
    (root / "schemas").mkdir()
    (root / "schemas/architecture_service_links.json").write_text(json.dumps({
        "installed_files": {"/usr/local/libexec/ladder-dragon/tool.py": "deploy/tool.py"}}))
    for source, _ in layout.DASHBOARD_ASSETS:
        path = root / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "baseline")
    previous = git(root, "rev-parse", "HEAD")
    git(root, "rm", "bin/old.py")
    git(root, "commit", "-m", "remove legacy code")
    expected = git(root, "rev-parse", "HEAD")
    return root, expected, previous


def test_clean_revision_does_not_read_or_delete_private_files(checkout, monkeypatch):
    root, expected, previous = checkout
    for name in (".env", "db/orders.sqlite3", "bin/data/private.py", "bin/__pycache__/old.pyc", ".venv/old.py"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("PRIVATE_MARKER")
    original = layout._read

    def checked(base, name):
        assert "private" not in name and ".env" not in name and "orders" not in name
        return original(base, name)

    monkeypatch.setattr(layout, "_read", checked)
    report = layout.audit(root, expected, previous)
    assert report["status"] == "PASS" and report["deleted_files"] == 0
    assert "PRIVATE_MARKER" not in json.dumps(report)
    assert (root / ".env").read_text() == "PRIVATE_MARKER"


@pytest.mark.parametrize("damage", ["missing", "changed", "legacy", "unknown", "symlink", "directory_link", "root_code", "hardlink"])
def test_unsafe_layout_blocks_without_cleanup(checkout, tmp_path, damage):
    root, expected, previous = checkout
    target = root / "bin/live.py"
    private = tmp_path / "PRIVATE_MARKER"
    private.write_text("PRIVATE_CONTENT")
    if damage == "missing": target.unlink()
    elif damage == "changed": target.write_text("raise RuntimeError('PRIVATE_CONTENT')")
    elif damage in {"legacy", "unknown", "root_code"}:
        target = root / {"legacy": "bin/old.py", "unknown": "bin/PRIVATE_MARKER.py", "root_code": "old.pyc"}[damage]
        target.write_text("PRIVATE_CONTENT")
    elif damage == "directory_link":
        (root / "bin/external").symlink_to(tmp_path, target_is_directory=True)
    else:
        target.unlink()
        if damage == "hardlink": os.link(private, target)
        else: target.symlink_to(private)
    report = layout.audit(root, expected, previous)
    assert report["status"] == "BLOCKED" and report["deleted_files"] == 0
    assert "PRIVATE_MARKER" not in json.dumps(report) and "PRIVATE_CONTENT" not in json.dumps(report)
    assert private.read_text() == "PRIVATE_CONTENT"
    if damage != "missing": assert os.path.lexists(target)


def publication(checkout, tmp_path):
    root, expected, previous = checkout
    web, installed = tmp_path / "web", tmp_path / "installed"
    for source, target in layout.DASHBOARD_ASSETS:
        path = web / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((root / source).read_bytes())
    target = installed / "usr/local/libexec/ladder-dragon/tool.py"
    target.parent.mkdir(parents=True)
    target.write_bytes((root / "deploy/tool.py").read_bytes())
    return web, installed


@pytest.mark.parametrize("damage", [None, "extra_web", "hidden_web", "runtime", "content"])
def test_installed_inventory_is_exact(checkout, tmp_path, damage):
    root, expected, previous = checkout
    web, installed = publication(checkout, tmp_path)
    if damage == "extra_web": (web / "old.js").write_text("PRIVATE_CONTENT")
    if damage == "hidden_web": (web / ".env").write_text("PRIVATE_CONTENT")
    if damage == "runtime": (installed / "usr/local/libexec/ladder-dragon/old.py").write_text("PRIVATE_CONTENT")
    if damage == "content": (web / "index.html").write_text("PRIVATE_CONTENT")
    report = layout.audit(root, expected, previous, web_root=web, installed_root=installed)
    assert report["status"] == ("PASS" if damage is None else "BLOCKED")
    assert "PRIVATE_CONTENT" not in json.dumps(report) and report["deleted_files"] == 0


def test_capacity_and_wrong_sha_fail_closed(checkout, monkeypatch):
    root, expected, previous = checkout
    assert layout.audit(root, previous, previous)["status"] == "BLOCKED"
    monkeypatch.setattr(layout, "MAX_ENTRIES", 1)
    assert layout.audit(root, expected, previous)["status"] == "BLOCKED"


def test_retired_external_command_is_reported_and_preserved(checkout, tmp_path):
    root, _, previous = checkout
    web, installed = publication(checkout, tmp_path)
    manifest = root / "schemas/architecture_service_links.json"
    manifest.write_text(json.dumps({"installed_files": {}}))
    git(root, "add", "schemas/architecture_service_links.json")
    git(root, "commit", "-m", "retire installed command")
    expected = git(root, "rev-parse", "HEAD")
    report = layout.audit(root, expected, previous, web_root=web, installed_root=installed)
    assert any(f["kind"] == "retired_install_present" for f in report["findings"])
    assert (installed / "usr/local/libexec/ladder-dragon/tool.py").is_file()


def test_matching_corrupted_source_and_publication_do_not_pass(checkout, tmp_path):
    root, expected, previous = checkout
    web, installed = publication(checkout, tmp_path)
    (root / "CHANGELOG.md").write_text("corrupted")
    (web / "CHANGELOG.md").write_text("corrupted")
    assert layout.audit(root, expected, previous, web_root=web, installed_root=installed)["status"] == "BLOCKED"


def test_unknown_findings_are_bounded(checkout):
    root, expected, previous = checkout
    for index in range(110):
        (root / f"bin/PRIVATE_{index}.py").write_text("PRIVATE_CONTENT")
    report = layout.audit(root, expected, previous)
    assert report["finding_count"] == 110 and len(report["findings"]) == 100
    assert len(json.dumps(report)) < 20000 and "PRIVATE" not in json.dumps(report)


def test_updater_runs_both_revisions_before_starting_services():
    source = (Path(__file__).resolve().parents[2] / "deploy/update_raspberry_pi.sh").read_text()
    calls = [m.start() for m in __import__("re").finditer(r"-m ladder_dragon.verification.release_layout", source)]
    assert len(calls) == 2
    mutation = source.index('EXTERNAL_DEPLOYMENT_MUTATED=1\n', source.index('LAYOUT_SHA='))
    assert mutation < calls[0] < source.index('PROJECT_DIR="${PROJECT_DIR}" deploy/install_runtime_assets.sh')
    assert calls[1] < source.index('systemctl restart ladder-dragon-user-stream-shadow.service')
    assert '--expected-sha "${LAYOUT_SHA}" --previous-sha "${LAYOUT_PREVIOUS_SHA}"' in source
    assert '|| fail "installed release revision is blocked' in source
