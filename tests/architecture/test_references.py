"""Reference maps detect stale anchors without granting execution authority."""

import json
from pathlib import Path

import pytest

from ladder_dragon.verification.architecture import references
from ladder_dragon.verification.models import HarnessContext, HarnessOptions, Status
from ladder_dragon.verification.profiles import checks_for_profile
from ladder_dragon.verification.runner import HarnessRunner


@pytest.fixture
def mapped(tmp_path):
    (tmp_path / "schemas").mkdir()
    (tmp_path / "ladder_dragon").mkdir()
    (tmp_path / "ladder_dragon/store.py").write_text(
        "raise RuntimeError('PRIVATE_MARKER')\nclass Store:\n    def save(self):\n        pass\nLIMIT = 1\n"
    )
    records = [dict(id="store", kind="store", path="ladder_dragon/store.py",
                    anchors=["Store.save"], data_class="authoritative", review_phase="P4"),
               dict(id="budget", kind="binding", path="ladder_dragon/store.py",
                    anchors=["LIMIT"], data_class="source_policy", review_phase="P4")]
    (tmp_path / references.REFERENCE_MAP).write_text(json.dumps(dict(
        schema_version=1, scope="reviewed_source_references_not_writer_authorization", records=records)))
    return tmp_path


def test_source_only_observations_and_hash_changes(mapped):
    first = references.audit_references(mapped)
    assert first["status"] == "PASS"
    assert "PRIVATE_MARKER" not in json.dumps(first)
    source = mapped / "ladder_dragon/store.py"
    source.write_text(source.read_text().replace("LIMIT = 1", "LIMIT = 2"))
    second = references.audit_references(mapped)
    assert second["status"] == "PASS"
    assert first["records"][1]["anchors"] != second["records"][1]["anchors"]
    assert "not a complete writer inventory" in second["limits"]


@pytest.mark.parametrize("source", [
    "LIMIT = 1\n", "class Store:\n    def save(self): pass\nLIMIT=1\nLIMIT=2\n",
    "class Store:\n    def save(self): pass\ndef decoy():\n    LIMIT=1\n",
    "class Store:\n    def save(self): pass\n    def save(self): pass\nLIMIT=1\n",
    "class Store:\n    def save(self): pass\nclass Store:\n    def save(self): pass\nLIMIT=1\n",
])
def test_missing_duplicate_and_nested_decoy_anchors_fail(mapped, source):
    (mapped / "ladder_dragon/store.py").write_text(source)
    assert references.audit_references(mapped)["status"] == "FAILED"


@pytest.mark.parametrize("damage", ["missing", "duplicate", "anchor", "path", "phase", "class", "extra"])
def test_invalid_map_blocks(mapped, damage):
    path = mapped / references.REFERENCE_MAP
    payload = json.loads(path.read_text())
    item = payload["records"][0]
    if damage == "missing":
        path.unlink()
    else:
        if damage == "duplicate":
            payload["records"].append(item)
        elif damage == "anchor":
            item["anchors"] *= 2
        elif damage == "path":
            item["path"] = "ladder_dragon/../private.py"
        elif damage == "phase":
            item["review_phase"] = "P8"
        elif damage == "class":
            item["data_class"] = "source_policy"
        else:
            item["grant"] = True
        path.write_text(json.dumps(payload))
    assert references.audit_references(mapped)["status"] == "BLOCKED"


@pytest.mark.parametrize("damage", ["missing", "syntax", "symlink", "oversize"])
def test_invalid_source_has_safe_diagnostics(mapped, damage):
    source = mapped / "ladder_dragon/store.py"
    source.unlink()
    if damage == "symlink":
        private = mapped / "private"
        private.write_text("PRIVATE_MARKER")
        source.symlink_to(private)
    elif damage != "missing":
        source.write_text("PRIVATE_MARKER=(" if damage == "syntax" else "x" * (1024 * 1024 + 1))
    result = references.audit_references(mapped)
    assert result["status"] == "BLOCKED"
    assert "PRIVATE_MARKER" not in json.dumps(result)
    assert str(mapped) not in json.dumps(result)


@pytest.mark.parametrize("profile", ["local", "release"])
def test_real_profile_requires_reference_check(mapped, profile):
    (mapped / "ladder_dragon/store.py").write_text("LIMIT=1\n")
    context = HarnessContext(root=mapped, python="python", options=HarnessOptions(
        profile=profile, output=mapped / "report.json"))
    specs = [spec for spec in checks_for_profile(context) if spec.name == "architecture_references"]
    assert len(specs) == 1 and specs[0].required
    assert HarnessRunner(context)._run_spec(specs[0]).status is Status.FAILED


def test_repository_map_and_report_ceiling(mapped, monkeypatch):
    assert references.audit_references(Path(__file__).resolve().parents[2])["status"] == "PASS"
    monkeypatch.setattr(references, "MAX_REPORT", 10)
    assert references.audit_references(mapped)["status"] == "BLOCKED"
