from pathlib import Path
import time

import pytest

from ladder_dragon.verification.live.validation_archive import (
    ContinuousDepthArchive,
    ValidationArchiveCapacityError,
    ValidationArchiveEvidenceError,
    ValidationArchiveReadinessError,
    validation_archive_capacity,
)


def _metadata(digest: str = "a") -> dict[str, object]:
    return {
        "contains_secrets": False,
        "archive_sha256": digest * 64,
        "depth_event_count": 100,
        "trade_event_count": 50,
    }


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
        return _metadata()

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
        return _metadata("b")

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


def test_continuous_archive_passes_production_evidence_minimums(tmp_path):
    observed: dict[str, object] = {}

    def recorder(_symbol, output, **options):
        observed.update(options)
        Path(output).write_text("{}\n", encoding="utf-8")
        options["ready_callback"]()
        while not options["stop_requested"]():
            time.sleep(0.001)
        return _metadata()

    archive = ContinuousDepthArchive(
        symbol="SOLUSDT",
        directory=tmp_path,
        label="maker",
        tail_sec=0,
        recorder=recorder,
    )

    archive.start()
    archive.stop()

    assert observed["minimum_depth_events_before_stop"] == 100
    assert observed["minimum_trade_events_before_stop"] == 50
    assert callable(observed["force_stop_requested"])


def test_continuous_archive_rejects_short_terminal_evidence(tmp_path):
    def recorder(_symbol, output, **options):
        Path(output).write_text("{}\n", encoding="utf-8")
        options["ready_callback"]()
        while not options["stop_requested"]():
            time.sleep(0.001)
        metadata = _metadata()
        metadata["depth_event_count"] = 99
        metadata["trade_event_count"] = 49
        return metadata

    archive = ContinuousDepthArchive(
        symbol="SOLUSDT",
        directory=tmp_path,
        label="maker",
        tail_sec=0,
        recorder=recorder,
    )
    archive.start()

    with pytest.raises(
        ValidationArchiveEvidenceError,
        match="code=PUBLIC_ARCHIVE_EVIDENCE_INSUFFICIENT",
    ) as captured:
        archive.stop()

    assert "private-source-text" not in str(captured.value)


def test_continuous_archive_forces_bounded_short_evidence_stop(tmp_path):
    observed = {"forced": False}

    def recorder(_symbol, output, **options):
        Path(output).write_text("private-source-text\n", encoding="utf-8")
        options["ready_callback"]()
        while not options["force_stop_requested"]():
            time.sleep(0.001)
        observed["forced"] = True
        metadata = _metadata()
        metadata["depth_event_count"] = 1
        metadata["trade_event_count"] = 1
        return metadata

    archive = ContinuousDepthArchive(
        symbol="SOLUSDT",
        directory=tmp_path,
        label="maker",
        tail_sec=0,
        evidence_timeout_sec=0.01,
        recorder=recorder,
    )
    archive.start()

    with pytest.raises(ValidationArchiveEvidenceError) as captured:
        archive.stop()

    assert observed["forced"] is True
    assert "private-source-text" not in str(captured.value)


def test_validation_archive_capacity_requires_complete_batch_slots(tmp_path):
    directory = tmp_path / "archives"
    directory.mkdir()
    for index in range(21):
        (directory / f"archive-{index}.jsonl").write_text("{}\n")

    with pytest.raises(
        ValidationArchiveCapacityError,
        match="code=PUBLIC_ARCHIVE_CAPACITY_INSUFFICIENT",
    ) as captured:
        validation_archive_capacity(directory, required_sessions=12)

    capacity = validation_archive_capacity(directory, required_sessions=11)
    assert capacity["occupied_sessions"] == 21
    assert capacity["available_sessions"] == 11
    assert "private-source-text" not in str(captured.value)
