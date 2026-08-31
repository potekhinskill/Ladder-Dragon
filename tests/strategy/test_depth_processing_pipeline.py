from __future__ import annotations

import json

from ladder_dragon.strategy import depth_processing as subject


def _archive(directory, name: str, digest: str, started_at_ms: int):
    archive = directory / f"{name}.jsonl"
    archive.write_text("public\n", encoding="utf-8")
    archive.with_suffix(".jsonl.metadata.json").write_text(
        json.dumps({
            "contains_secrets": False,
            "archive_sha256": digest,
            "started_at_ms": started_at_ms,
        }),
        encoding="utf-8",
    )
    return archive


def test_inventory_prioritizes_frozen_then_post_cutoff_sources(
    tmp_path, monkeypatch
):
    before = _archive(tmp_path, "before", "1" * 64, 10)
    after = _archive(tmp_path, "after", "2" * 64, 200)
    frozen = _archive(tmp_path, "frozen", "3" * 64, 20)
    policy = tmp_path / ".historical-replay" / "volatility-policy.json"
    policy.parent.mkdir()
    policy.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        subject,
        "volatility_policy_migration_readiness",
        lambda *_args: {
            "schema_version": 1,
            "status": "WAITING_SELECTION_SOURCES",
            "migration_required": True,
            "source_policy_schema_version": 4,
            "selection_sources_ready": 0,
            "selection_sources_required": 1,
        },
    )
    monkeypatch.setattr(
        subject,
        "volatility_policy_source_contract",
        lambda *_args: (frozenset({"3" * 64}), 100),
    )

    status, pending = subject.calibration_inventory(tmp_path)

    assert pending == [frozen, after, before]
    assert status["status"] == "BACKLOG_INCOMPLETE"
    assert status["volatility_policy_migration"][
        "selection_sources_required"
    ] == 1


def test_migration_eta_uses_only_measured_calibration_time():
    status = {
        "volatility_policy_migration": {
            "selection_sources_ready": 2,
            "selection_sources_required": 5,
        }
    }

    subject._attach_migration_eta(status, None)
    migration = status["volatility_policy_migration"]
    assert migration["selection_sources_remaining"] == 3
    assert migration["estimated_seconds_remaining"] is None

    subject._attach_migration_eta(status, 2.5)
    assert migration["average_calibration_seconds"] == 2.5
    assert migration["estimated_seconds_remaining"] == 8


def test_backlog_migrates_only_after_readiness(tmp_path, monkeypatch):
    ready = {
        "volatility_policy_migration": {
            "status": "READY_FOR_MIGRATION",
            "selection_sources_ready": 1,
            "selection_sources_required": 1,
        }
    }
    current = {
        "volatility_policy_migration": {
            "status": "CURRENT_POLICY",
            "selection_sources_ready": 1,
            "selection_sources_required": 1,
        }
    }
    inventories = iter(((ready, []), (current, [])))
    monkeypatch.setattr(
        subject, "calibration_inventory", lambda _directory: next(inventories)
    )
    migrated = []
    monkeypatch.setattr(
        subject,
        "migrate_legacy_volatility_policy",
        lambda *args: migrated.append(args),
    )
    monkeypatch.setattr(subject, "atomic_json", lambda *args, **kwargs: None)

    class Stop:
        stopped = False

        def is_set(self):
            return self.stopped

        def wait(self, _seconds):
            self.stopped = True
            return True

    subject.process_backlog(tmp_path, Stop())

    assert len(migrated) == 1
