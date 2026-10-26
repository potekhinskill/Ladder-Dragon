# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify and install the isolated downstream static analyzer.
"""Install the reviewed downstream scanner without overriding dependency resolution."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from ladder_dragon.verification.semgrep_build import rebuild
from ladder_dragon.verification.semgrep_environment import host_key

ROOT = Path(__file__).resolve().parents[2]


def _check_storage(root):
    """Bound disposable build storage; cleanup requires an explicit operator action."""
    size = 0
    if root.is_symlink():
        raise ValueError("symlink build storage")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("symlink build artifact")
        if path.is_file():
            size += path.stat().st_size
    if size > 1536 * 1024**2:
        raise ValueError("build storage limit; review old artifacts before retry")


def _write_contract(path, content):
    if path.is_symlink():
        raise ValueError("symlink contract")
    if path.exists():
        if path.read_text() != content:
            raise ValueError("existing build contract differs")
    else:
        with path.open("x") as stream:
            stream.write(content)


def install(root):
    manifest = json.loads((root / "requirements/semgrep-build.json").read_text())
    target = manifest["platforms"][host_key()]
    _check_storage(root / ".runtime/semgrep-build")
    work = root / ".runtime/semgrep-build" / manifest["version"] / host_key()
    environment = root / ".semgrep-venv"
    if work.is_symlink() or environment.is_symlink():
        raise ValueError("symlink build or environment")
    work.mkdir(parents=True, exist_ok=True)
    child_env = {
        "PATH": os.defpath, "HOME": str(work), "LANG": "C.UTF-8",
        "PIP_CONFIG_FILE": os.devnull, "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_CACHE_DIR": "1",
        "PYTHON_DOTENV_DISABLED": "1",
    }

    def run(argv):
        subprocess.run(argv, cwd=root, env=child_env, check=True, timeout=900)

    source_lock = work / "source.lock"
    _write_contract(source_lock, target["url"] + " --hash=sha256:" + target["source_sha256"] + "\n")
    source = work / target["filename"]
    if not source.exists():
        run([sys.executable, "-m", "pip", "download", "--no-deps", "--only-binary=:all:",
             "--require-hashes", "--dest", str(work), "-r", str(source_lock)])
    if (source.is_symlink() or source.stat().st_size > 96 * 1024**2
            or hashlib.sha256(source.read_bytes()).hexdigest() != target["source_sha256"]):
        raise ValueError("source integrity mismatch")
    wheel = work / target["filename"].replace("-1.168.0-", "-" + manifest["version"] + "-", 1)
    if not wheel.exists():
        rebuild(source, work)
    if (wheel.is_symlink() or wheel.stat().st_size > 512 * 1024**2
            or hashlib.sha256(wheel.read_bytes()).hexdigest() != target["wheel_sha256"]):
        raise ValueError("built wheel integrity mismatch")
    wheel_lock = work / "wheel.lock"
    _write_contract(wheel_lock, wheel.as_uri() + " --hash=sha256:" + target["wheel_sha256"] + "\n")
    if not environment.exists():
        run([sys.executable, "-m", "venv", str(environment)])
    python = str(environment / "bin/python")
    run([python, "-m", "pip", "install", "--require-hashes",
         "-r", str(root / "requirements/semgrep-bootstrap.lock")])
    run([python, "-m", "pip", "install", "--require-hashes",
         "-r", str(root / "requirements/semgrep.lock"), "-r", str(wheel_lock)])
    run([python, "-m", "pip", "check"])
    run([python, "-I", str(root / "ladder_dragon/verification/semgrep_environment.py"), str(root)])


def main(argv=None):
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    try:
        install(ROOT)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        print("Semgrep installation failed; do not run verification with a fallback scanner", file=sys.stderr)
        return 2
    return 0
