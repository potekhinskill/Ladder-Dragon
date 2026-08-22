from pathlib import Path
import time

import pytest

from ladder_dragon.verification.live.validation_archive import (
    ContinuousDepthArchive,
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
    def recorder(*_args, **_options):
        raise ValueError("public stream failed")

    archive = ContinuousDepthArchive(
        symbol="SOLUSDT",
        directory=tmp_path,
        label="maker",
        tail_sec=0,
        recorder=recorder,
    )

    with pytest.raises(RuntimeError, match="before readiness"):
        archive.start()
