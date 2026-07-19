import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PARSER = ROOT / "deploy/read_update_trust.py"
FINGERPRINT = "808B9F52CB6C08901703EF7C113144122F1830A0"


def run_parser(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PARSER), str(path)],
        text=True,
        capture_output=True,
        check=False,
    )


def test_update_trust_parser_accepts_exactly_one_fingerprint(tmp_path):
    config = tmp_path / "update-trust.conf"
    config.write_text(
        f"# pinned release key\nTRUSTED_GPG_FINGERPRINT={FINGERPRINT.lower()}\n"
    )

    result = run_parser(config)

    assert result.returncode == 0
    assert result.stdout.strip() == FINGERPRINT


def test_update_trust_parser_rejects_shell_and_duplicate_fields(tmp_path):
    shell = tmp_path / "shell.conf"
    shell.write_text(f"TRUSTED_GPG_FINGERPRINT=$(echo {FINGERPRINT})\n")
    duplicate = tmp_path / "duplicate.conf"
    duplicate.write_text(
        f"TRUSTED_GPG_FINGERPRINT={FINGERPRINT}\n"
        f"TRUSTED_GPG_FINGERPRINT={FINGERPRINT}\n"
    )

    assert run_parser(shell).returncode == 2
    assert run_parser(duplicate).returncode == 2
