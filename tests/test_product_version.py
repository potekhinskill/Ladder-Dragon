import re
import subprocess
import sys
from pathlib import Path

import product_version


SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def test_product_version_is_semver_and_has_no_legacy_entrypoint():
    assert SEMVER.fullmatch(product_version.__version__)
    assert Path("bin/autosize_universal.py").is_file()
    assert not Path("1.8_autosize_universal.py").exists()


def test_supervisor_and_executor_report_the_same_product_version():
    expected = product_version.product_label
    commands = [
        ([sys.executable, "-m", "bin.ai_supervisor", "--version"], expected("supervisor")),
        ([sys.executable, "-m", "bin.autosize_universal", "--version"], expected("executor")),
    ]
    for command, label in commands:
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        assert result.returncode == 0
        assert result.stdout.strip() == label


def test_package_metadata_uses_canonical_version_module():
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in pyproject
    assert 'version = {attr = "product_version.__version__"}' in pyproject
