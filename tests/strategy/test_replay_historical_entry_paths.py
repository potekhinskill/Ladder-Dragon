import json
from pathlib import Path

from bin import replay_historical_entries as module
from ladder_dragon.strategy.prediction.historical_entry_replay import MODEL_CONTRACT
from ladder_dragon.strategy.prediction.historical_policy import fingerprint


def test_path_batch_replays_each_session_separately(tmp_path, monkeypatch):
    policy = {
        "symbol": "SOLUSDT",
        "classifier_fingerprint": "a" * 64,
    }
    paths = []
    for index in range(3):
        start = 1_000_000 + index * 30_000_000
        digest = format(index + 1, "064x")
        paths.append({
            "archives": [{
                "path": str(tmp_path / f"session-{index}.jsonl"),
                "sha256": digest,
            }],
            "start_ms": start,
            "entry_end_ms": start + 300_000,
            "end_ms": start + 21_901_000,
            "cutoff_ms": start + 21_901_000,
        })
    request = {
        "request_schema_version": 2,
        "cohort_contract": "provider_bounded_gap_opportunity_aligned_paths_v4",
        "stability_block_index": 0,
        "policy": policy,
        "paths": paths,
    }
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    output_path = tmp_path / "report.json"
    verified_calls = []

    def verified(sources):
        source_paths = list(sources)
        assert len(source_paths) == 1
        index = int(source_paths[0].stem.rsplit("-", 1)[1])
        verified_calls.append(index)
        path = paths[index]
        return [(source_paths[0], {
            "archive_sha256": path["archives"][0]["sha256"],
            "symbol": "SOLUSDT",
            "started_at_ms": path["start_ms"] - 300_000,
            "finished_at_ms": path["cutoff_ms"],
        })]

    monkeypatch.setattr(module, "verified_segments", verified)
    monkeypatch.setattr(
        module,
        "iter_segment_events",
        lambda segments, **_kwargs: iter([segments[0][1]["archive_sha256"]]),
    )
    monkeypatch.setattr(
        module,
        "export_context",
        lambda *_args, **_kwargs: {"context": [{"public": True}]},
    )

    def replay(events, *, jobs, start_ms, **_kwargs):
        assert len(list(events)) == 1
        assert len(jobs) == 1
        episode = {
            "episode_id": "same-local-id",
            "started_at_ms": start_ms,
            "net_pnl_quote": "1",
            "censored": False,
            "terminal_reason": "TAKE_PROFIT",
        }
        return [{
            "model_contract": MODEL_CONTRACT,
            "status": "COMPLETE_SELECTION_REPLAY",
            "policy": jobs[0][0],
            "policy_sha256": fingerprint(jobs[0][0]),
            "model_source_sha256s": {"model.py": "b" * 64},
            "remaining_gates": ["LIVE_CONFIRMATION"],
            "summaries": {
                "baseline": {
                    "opportunities": 1, "filled": 1,
                    "net_pnl_quote": "1", "censored": 0,
                },
                "veto": {
                    "opportunities": 1, "filled": 1,
                    "net_pnl_quote": "1", "censored": 0,
                },
            },
            "episodes": {"baseline": [episode], "veto": [episode]},
        }]

    monkeypatch.setattr(module, "historical_entry_replays", replay)

    report = module.run_replay_request_batch(
        [(request_path, output_path)],
        context_db=tmp_path / "context.sqlite3",
    )[0]

    assert verified_calls == [0, 1, 2]
    assert report["schema_version"] == 2
    assert len(report["path_windows"]) == 3
    assert report["summaries"]["veto"]["opportunities"] == 3
    assert [row["episode_id"] for row in report["episodes"]["veto"]] == [
        "path-0:same-local-id",
        "path-1:same-local-id",
        "path-2:same-local-id",
    ]
    stored = json.loads(output_path.read_text(encoding="utf-8"))
    assert stored["report_sha256"] == fingerprint({
        key: value for key, value in stored.items() if key != "report_sha256"
    })
    assert str(tmp_path) not in json.dumps(stored)
