from pathlib import Path

from ladder_dragon.strategy.prediction import historical_replay_planner as planner
from ladder_dragon.strategy.prediction.episode_semantics import (
    v23_evidence_semantics_contract,
)
from ladder_dragon.strategy.prediction.historical_policy import fingerprint


def test_planner_creates_review_drafts_without_queueing_or_importing(
    tmp_path, monkeypatch
):
    archive = tmp_path / "segment.jsonl"
    archive.write_text("public", encoding="utf-8")
    start = 1_000_000
    finish = start + planner.SIGNAL_WARMUP_MS + planner.BLOCK_COUNT * (
        planner.ENTRY_WINDOW_MS + planner.TERMINAL_TAIL_MS
    )
    metadata = {
        "started_at_ms": start,
        "finished_at_ms": finish,
        "archive_sha256": "a" * 64,
    }
    monkeypatch.setattr(
        planner, "_latest_chain", lambda *_args: [(archive, metadata)]
    )
    classifier = fingerprint(
        v23_evidence_semantics_contract()["regime_classifier"]
    )

    def context(*_args, **kwargs):
        assert kwargs["classifier_fingerprint"] == classifier
        return {
            "context": [{
                "classifier_fingerprint": classifier,
                "panic_source_fingerprint": "b" * 64,
            }]
        }

    monkeypatch.setattr(planner, "export_context", context)
    draft_directory = tmp_path / "drafts"

    report = planner.plan_replay_drafts(
        tmp_path, draft_directory, tmp_path / "context.sqlite3"
    )

    drafts = list(draft_directory.glob("*.json"))
    assert report["status"] == "DRAFTS_READY_FOR_OPERATOR_REVIEW"
    assert report["draft_count"] == 108
    assert len(drafts) == 108
    assert report["automatic_queueing"] is False
    assert report["automatic_selection_import"] is False
    assert not (tmp_path / "requests").exists()
