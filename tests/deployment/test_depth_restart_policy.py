import subprocess
import sys

from deploy.depth_restart_policy import depth_restart_required


def test_supervisor_and_presentation_changes_preserve_depth_session():
    assert not depth_restart_required(
        [
            "ladder_dragon/supervision/runtime.py",
            "FastAPI/pi-dashboard/app.py",
            "FRONT/dashboard.js",
            "CHANGELOG.md",
            "product_version.py",
        ]
    )


def test_depth_runtime_and_unknown_changes_require_restart():
    for path in (
        "bin/depth_archive_service.py",
        "ladder_dragon/strategy/depth_capture.py",
        "requirements/raspberry.lock",
        "deploy/record_depth_archive.sh",
        "unexpected.txt",
    ):
        assert depth_restart_required([path])


def test_one_depth_change_overrides_preservable_changes():
    assert depth_restart_required(
        ["ladder_dragon/supervision/runtime.py", "pyproject.toml"]
    )


def test_empty_or_invalid_inventory_requires_restart():
    assert depth_restart_required([])
    assert depth_restart_required([""])
    assert depth_restart_required(["/absolute/path"])


def test_null_delimited_cli_reports_policy():
    result = subprocess.run(
        [sys.executable, "deploy/depth_restart_policy.py", "--null"],
        input=b"ladder_dragon/supervision/runtime.py\0CHANGELOG.md\0",
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == b"preserve\n"
