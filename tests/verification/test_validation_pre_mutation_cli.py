from argparse import Namespace
from contextlib import nullcontext
import json
from types import SimpleNamespace

import pytest

from ladder_dragon.verification.live import mainnet_limit_maker_validation
from ladder_dragon.verification.live import mainnet_stop_limit_validation
from ladder_dragon.verification.live.validation_archive import (
    ValidationArchiveEvidenceError,
    ValidationArchiveReadinessError,
)
from ladder_dragon.verification.live.validation_batch import (
    PreMutationValidationFailure,
)


@pytest.mark.parametrize(
    "module",
    [mainnet_limit_maker_validation, mainnet_stop_limit_validation],
)
def test_drill_cli_returns_definite_failure_for_pre_mutation_error(
    module, monkeypatch, capsys
):
    args = Namespace(
        symbol="SOLUSDT",
        lock_file="unused.lock",
        batch_manifest="batch.json",
    )
    parser = SimpleNamespace(parse_args=lambda: args)
    monkeypatch.setattr(module, "load_dotenv", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "build_parser", lambda: parser)
    monkeypatch.setattr(module, "exclusive_lock", lambda _path: nullcontext())

    def fail_before_mutation(_args):
        source = ValidationArchiveReadinessError(
            reason_code="PUBLIC_ARCHIVE_SOURCE_FAILED",
            attempts=3,
            cause_type="WebSocketException",
        )
        raise PreMutationValidationFailure(source)

    monkeypatch.setattr(module, "run_validation_drill", fail_before_mutation)

    assert module.main() == 3
    payload = json.loads(capsys.readouterr().err)
    assert payload["status"] == "failed_definite"
    assert payload["error_code"] == "PUBLIC_ARCHIVE_SOURCE_FAILED"
    assert payload["cause_type"] == "WebSocketException"
    assert payload["readiness_attempts"] == 3


@pytest.mark.parametrize(
    "module",
    [mainnet_limit_maker_validation, mainnet_stop_limit_validation],
)
def test_drill_cli_returns_definite_failure_for_short_evidence(
    module, monkeypatch, capsys
):
    args = Namespace(
        symbol="SOLUSDT",
        lock_file="unused.lock",
        batch_manifest="batch.json",
    )
    parser = SimpleNamespace(parse_args=lambda: args)
    monkeypatch.setattr(module, "load_dotenv", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "build_parser", lambda: parser)
    monkeypatch.setattr(module, "exclusive_lock", lambda _path: nullcontext())

    def fail_after_cleanup(_args):
        raise ValidationArchiveEvidenceError()

    monkeypatch.setattr(module, "run_validation_drill", fail_after_cleanup)

    assert module.main() == 3
    payload = json.loads(capsys.readouterr().err)
    assert payload == {
        "cause_type": "EvidenceThreshold",
        "error": (
            "validation depth archive evidence is insufficient: "
            "code=PUBLIC_ARCHIVE_EVIDENCE_INSUFFICIENT "
            "cause=EvidenceThreshold"
        ),
        "error_code": "PUBLIC_ARCHIVE_EVIDENCE_INSUFFICIENT",
        "error_type": "ValidationArchiveEvidenceError",
        "status": "failed_definite",
    }
