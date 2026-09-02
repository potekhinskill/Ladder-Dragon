from pathlib import Path
import time

import pytest

from ladder_dragon.verification.live.validation_archive import (
    ContinuousDepthArchive,
    ValidationArchiveReadinessError,
)


def test_continuous_archive_is_ready_before_stop_and_publishes(tmp_path):
    observed = {"ready": False, "stopped": False}

    def recorder(symbol, output, **options):
        assert symbol == "SOLUSDT"
        Path(output).write_text("{}\n", encoding="utf-8")
        options["ready_callback"]()
        observed["ready"] = True
        while not options["stop_requested"]():
            time.sleep(0.001)
        observed["stopped"] = True
        return {"contains_secrets": False, "archive_sha256": "a" * 64}

    archive = ContinuousDepthArchive(
        symbol="SOLUSDT",
        directory=tmp_path,
        label="maker",
        tail_sec=0,
        recorder=recorder,
    )
    path = archive.start()

    assert observed["ready"] is True
    assert path.parent == tmp_path
    assert archive.stop()["archive_sha256"] == "a" * 64
    assert observed["stopped"] is True


def test_continuous_archive_fails_closed_before_readiness(tmp_path):
    calls = 0

    def recorder(*_args, **_options):
        nonlocal calls
        calls += 1
        raise ValueError("private-source-text")

    archive = ContinuousDepthArchive(
        symbol="SOLUSDT",
        directory=tmp_path,
        label="maker",
        retry_delay_sec=0,
        tail_sec=0,
        recorder=recorder,
    )

    with pytest.raises(
        ValidationArchiveReadinessError,
        match="code=PUBLIC_ARCHIVE_SOURCE_FAILED attempts=3 cause=ValueError",
    ) as captured:
        archive.start()

    assert calls == 3
    assert "private-source-text" not in str(captured.value)


def test_continuous_archive_retries_only_before_readiness(tmp_path):
    calls = 0

    def recorder(_symbol, output, **options):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise OSError("temporary public source failure")
        Path(output).write_text("{}\n", encoding="utf-8")
        options["ready_callback"]()
        while not options["stop_requested"]():
            time.sleep(0.001)
        return {"contains_secrets": False, "archive_sha256": "b" * 64}

    archive = ContinuousDepthArchive(
        symbol="SOLUSDT",
        directory=tmp_path,
        label="stop",
        retry_delay_sec=0,
        tail_sec=0,
        recorder=recorder,
    )

    archive.start()

    assert archive.stop()["archive_sha256"] == "b" * 64
    assert calls == 3


def test_continuous_archive_never_retries_after_readiness(tmp_path):
    calls = 0

    def recorder(_symbol, _output, **options):
        nonlocal calls
        calls += 1
        options["ready_callback"]()
        raise ValueError("post-readiness source failure")

    archive = ContinuousDepthArchive(
        symbol="SOLUSDT",
        directory=tmp_path,
        label="maker",
        retry_delay_sec=0,
        tail_sec=0,
        recorder=recorder,
    )

    archive.start()
    with pytest.raises(RuntimeError, match="archive failed") as captured:
        archive.stop()

    assert calls == 1
    assert "post-readiness source failure" not in str(captured.value)
