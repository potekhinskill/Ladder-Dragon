from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import json

import pytest

from ladder_dragon.strategy.market_replay import ReplayCalibration
from ladder_dragon.strategy.replay_readiness import audit_replay_readiness
from ladder_dragon.strategy.volatility_policy import (
    VOLATILITY_EVENT_POPULATION,
    VOLATILITY_MEASUREMENT_WINDOW_MS,
    VOLATILITY_METRIC,
    VOLATILITY_PUBLISH_INTERVAL_MS,
    confirmed_volatility_scope,
    confirmation_cohort_reasons,
    migrate_legacy_volatility_policy,
    read_volatility_policy,
    select_volatility_policy,
    verify_volatility_policy,
    verify_volatility_scope,
    volatility_policy_migration_readiness,
)


DAY_MS = 86_400_000


def calibration(index: int, volatility: str) -> ReplayCalibration:
    return ReplayCalibration(
        schema_version=5,
        archive_sha256=f"{index:064x}",
        first_ts_ms=index * DAY_MS,
        last_ts_ms=index * DAY_MS + VOLATILITY_MEASUREMENT_WINDOW_MS,
        event_count=1_000,
        book_event_count=700,
        trade_count=300,
        execution_sample_count=0,
        eligible=True,
        reasons=(),
        spread_pct=Decimal("0.0001"),
        slippage_pct=Decimal("0.0002"),
        participation_rate=Decimal("0.2"),
        partial_fill_ratio=Decimal("0.5"),
        latency_ms_p95=100,
        market_impact_bps=Decimal("1"),
        volatility_bps_p95=Decimal(volatility),
        volatility_metric=VOLATILITY_METRIC,
        volatility_event_population=VOLATILITY_EVENT_POPULATION,
        volatility_measurement_window_ms=VOLATILITY_MEASUREMENT_WINDOW_MS,
        latency_source="public_event_receive",
    )


def selection_reports(tmp_path):
    paths = []
    for index in range(1, 101):
        volatility = Decimal(index) / Decimal("100")
        path = tmp_path / f"segment-{index}.calibration.json"
        path.write_text(
            json.dumps(calibration(index, str(volatility)).as_dict()),
            encoding="utf-8",
        )
        paths.append(path)
    return paths


def policy(tmp_path):
    cutoff = 101 * DAY_MS
    return select_volatility_policy(
        selection_reports(tmp_path),
        cutoff_ts_ms=cutoff,
        created_at_ms=cutoff,
    )


def test_policy_freezes_selection_hashes_and_empirical_tertiles(tmp_path):
    payload = policy(tmp_path)

    assert payload["low_max_bps"] == "0.34"
    assert payload["high_min_bps"] == "0.67"
    assert payload["selection_report_count"] == 100
    assert payload["selection_bucket_counts"] == {
        "low": 34,
        "normal": 32,
        "high": 34,
    }
    assert payload["quantile_rule"] == "ZERO_INFLATED_EMPIRICAL_TERTILES_V2"
    assert payload["confirmation_reuses_selection"] is False
    assert payload["schema_version"] == 5
    assert payload["volatility_event_population"] == VOLATILITY_EVENT_POPULATION
    assert payload["volatility_metric"] == VOLATILITY_METRIC
    assert payload["measurement_window_ms"] == VOLATILITY_MEASUREMENT_WINDOW_MS
    assert payload["publish_interval_ms"] == VOLATILITY_PUBLISH_INTERVAL_MS
    assert verify_volatility_policy(payload) is True
    damaged = dict(payload, high_min_bps="0.1")
    assert verify_volatility_policy(damaged) is False


def test_legacy_policy_migration_preserves_selection_and_archives_source(
    tmp_path,
):
    current = policy(tmp_path)
    legacy = dict(current)
    for field in (
        "measurement_window_ms", "publish_interval_ms",
        "selection_report_minimum_window_ms",
        "selection_report_maximum_window_ms",
        "selection_confirmable_buckets", "selection_blocked_buckets",
        "selection_bucket_activation_policy",
        "volatility_event_population",
    ):
        legacy.pop(field)
    legacy["schema_version"] = 2
    legacy["volatility_metric"] = "CALIBRATION_EVENT_MOVE_P95_BPS"
    legacy.pop("policy_sha256")
    from ladder_dragon.strategy.prediction.episode_semantics import (
        canonical_digest,
    )
    legacy["policy_sha256"] = canonical_digest(legacy)
    policy_path = tmp_path / "volatility-policy.json"
    policy_path.write_text(json.dumps(legacy), encoding="utf-8")

    migrated = migrate_legacy_volatility_policy(policy_path, tmp_path)

    assert verify_volatility_policy(migrated) is True
    assert migrated["low_max_bps"] == legacy["low_max_bps"]
    assert migrated["selection_report_sha256s"] == legacy[
        "selection_report_sha256s"
    ]
    archive = tmp_path / (
        f"volatility-policy.schema2-{legacy['policy_sha256']}.json"
    )
    assert json.loads(archive.read_text(encoding="utf-8")) == legacy


def test_schema4_policy_reselects_same_archives_on_depth_updates(tmp_path):
    current = policy(tmp_path)
    legacy = dict(current)
    legacy["schema_version"] = 4
    legacy["volatility_metric"] = "EVENT_MOVE_P95_BPS_OVER_55_MINUTES_V1"
    legacy.pop("volatility_event_population")
    legacy.pop("policy_sha256")
    from ladder_dragon.strategy.prediction.episode_semantics import (
        canonical_digest,
    )
    legacy["policy_sha256"] = canonical_digest(legacy)
    policy_path = tmp_path / "volatility-policy.json"
    policy_path.write_text(json.dumps(legacy), encoding="utf-8")

    migrated = migrate_legacy_volatility_policy(policy_path, tmp_path)

    assert migrated["schema_version"] == 5
    assert migrated["selection_archive_sha256s"] == (
        legacy["selection_archive_sha256s"]
    )
    assert migrated["volatility_event_population"] == (
        VOLATILITY_EVENT_POPULATION
    )
    assert policy_path.with_name(
        f"volatility-policy.schema4-{legacy['policy_sha256']}.json"
    ).is_file()


def test_schema4_migration_waits_for_every_frozen_archive(tmp_path):
    current = policy(tmp_path)
    legacy = dict(current)
    legacy["schema_version"] = 4
    legacy["volatility_metric"] = "EVENT_MOVE_P95_BPS_OVER_55_MINUTES_V1"
    legacy.pop("volatility_event_population")
    legacy.pop("policy_sha256")
    from ladder_dragon.strategy.prediction.episode_semantics import (
        canonical_digest,
    )
    legacy["policy_sha256"] = canonical_digest(legacy)
    policy_path = tmp_path / "volatility-policy.json"
    policy_path.write_text(json.dumps(legacy), encoding="utf-8")
    missing = tmp_path / "segment-100.calibration.json"
    missing.unlink()

    waiting = volatility_policy_migration_readiness(policy_path, tmp_path)

    assert waiting["status"] == "WAITING_SELECTION_SOURCES"
    assert waiting["selection_sources_ready"] == 99
    assert waiting["selection_sources_required"] == 100
    missing.write_text(
        json.dumps(calibration(100, "1").as_dict()), encoding="utf-8"
    )
    ready = volatility_policy_migration_readiness(policy_path, tmp_path)
    assert ready["status"] == "READY_FOR_MIGRATION"
    assert ready["selection_sources_ready"] == 100


def test_zero_inflated_selection_splits_positive_tail_without_empty_bucket(tmp_path):
    paths = []
    for index in range(1, 101):
        volatility = "0" if index <= 59 else str(Decimal(index) / Decimal("100"))
        path = tmp_path / f"zero-inflated-{index}.json"
        path.write_text(
            json.dumps(calibration(index, volatility).as_dict()),
            encoding="utf-8",
        )
        paths.append(path)

    payload = select_volatility_policy(
        paths,
        cutoff_ts_ms=101 * DAY_MS,
        created_at_ms=101 * DAY_MS,
    )

    assert payload["low_max_bps"] == "0"
    assert payload["selection_bucket_counts"] == {
        "low": 59,
        "normal": 20,
        "high": 21,
    }


def test_production_shaped_zero_inflation_has_reachable_buckets(tmp_path):
    paths = []
    for index in range(1, 227):
        volatility = (
            "0"
            if index <= 164
            else str(Decimal("0.9119") + Decimal(index - 165) / Decimal("10000"))
        )
        path = tmp_path / f"production-shape-{index}.json"
        path.write_text(
            json.dumps(calibration(index, volatility).as_dict()),
            encoding="utf-8",
        )
        paths.append(path)

    payload = select_volatility_policy(
        paths,
        cutoff_ts_ms=227 * DAY_MS,
        created_at_ms=227 * DAY_MS,
    )

    assert payload["selection_bucket_counts"] == {
        "low": 164,
        "normal": 30,
        "high": 32,
    }
    assert verify_volatility_policy(payload) is True


def test_exact_window_zero_inflation_uses_scoped_safe_bounds(tmp_path):
    paths = []
    for index in range(1, 163):
        volatility = "0" if index <= 130 else "0.95"
        path = tmp_path / f"exact-window-{index}.calibration.json"
        path.write_text(
            json.dumps(calibration(index, volatility).as_dict()),
            encoding="utf-8",
        )
        paths.append(path)

    payload = select_volatility_policy(
        paths,
        cutoff_ts_ms=163 * DAY_MS,
        created_at_ms=163 * DAY_MS,
    )

    assert payload["quantile_rule"] == "PREREGISTERED_SAFE_BOUNDS_V1"
    assert payload["low_max_bps"] == "0.5"
    assert payload["high_min_bps"] == "2"
    assert payload["selection_confirmable_buckets"] == ["low", "normal"]
    assert payload["selection_blocked_buckets"] == ["high"]
    assert verify_volatility_policy(payload) is True

    cutoff = int(payload["cutoff_ts_ms"])
    confirmation = [
        replace(
            calibration(300 + index, value),
            first_ts_ms=cutoff + 1 + index * DAY_MS,
            last_ts_ms=cutoff + VOLATILITY_MEASUREMENT_WINDOW_MS + 1
            + index * DAY_MS,
        )
        for index, value in enumerate(("0", "0", "0", "3", "3", "3"))
    ]
    scope = confirmed_volatility_scope(payload, confirmation)
    assert scope["confirmed_buckets"] == ["low"]
    assert scope["blocked_buckets"] == ["normal", "high"]


def test_confirmation_requires_disjoint_post_cutoff_archives(tmp_path):
    payload = policy(tmp_path)
    valid = [
        calibration(102, "0.2"),
        calibration(103, "0.5"),
        calibration(104, "0.9"),
    ]
    assert confirmation_cohort_reasons(payload, valid) == ()
    assert confirmation_cohort_reasons(
        payload, [calibration(1, "0.2")]
    ) == (
        "volatility confirmation starts before the cutoff",
        "volatility selection and confirmation overlap",
    )
    short = replace(
        calibration(102, "0.2"),
        last_ts_ms=102 * DAY_MS + 5 * 60_000,
    )
    assert confirmation_cohort_reasons(payload, [short]) == (
        "volatility confirmation window differs from policy",
    )


def test_selection_rejects_a_short_measurement_window(tmp_path):
    paths = selection_reports(tmp_path)
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    payload["last_ts_ms"] = payload["first_ts_ms"] + 5 * 60_000
    paths[0].write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="ineligible"):
        select_volatility_policy(
            paths,
            cutoff_ts_ms=101 * DAY_MS,
            created_at_ms=101 * DAY_MS,
        )


def test_readiness_uses_frozen_policy_only_on_confirmation(tmp_path):
    payload = policy(tmp_path)
    rows = [
        calibration(102, "0.2"),
        calibration(103, "0.5"),
        calibration(104, "0.9"),
    ]
    report = audit_replay_readiness(
        rows,
        minimum_measured_latency_archives=0,
        minimum_execution_samples=0,
        minimum_validation_reports=0,
        minimum_validated_orders=0,
        volatility_policy=payload,
    )
    assert report.ready is True
    assert report.regimes == ("high", "low", "normal")
    assert report.volatility_policy_sha256 == payload["policy_sha256"]
    assert report.volatility_confirmation_after_cutoff is True


def test_depth_inventory_tracks_disjoint_two_day_confirmation(tmp_path):
    from ladder_dragon.strategy.depth_processing import (
        _frozen_volatility_status,
    )

    payload = policy(tmp_path)
    policy_dir = tmp_path / ".historical-replay"
    policy_dir.mkdir()
    (policy_dir / "volatility-policy.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    cutoff = int(payload["cutoff_ts_ms"])
    rows = [
        calibration(200 + index, value)
        for index, value in enumerate(
            ("0.1", "0.2", "0.3", "0.5", "0.55", "0.6", "0.9", "1", "1.1")
        )
    ]
    rows = [
        replace(
            row,
            first_ts_ms=cutoff + 1 + index * (DAY_MS // 2),
            last_ts_ms=cutoff + 55 * 60_000 + 1 + index * (DAY_MS // 2),
        )
        for index, row in enumerate(rows)
    ]

    status = _frozen_volatility_status(tmp_path, rows)

    assert status["status"] == "PASS_SCOPED"
    assert status["confirmation_span_ms"] >= 2 * DAY_MS
    assert status["selection_sources_reused"] is False


def test_scope_confirms_observed_buckets_without_waiting_for_high(tmp_path):
    payload = policy(tmp_path)
    cutoff = int(payload["cutoff_ts_ms"])
    rows = [
        replace(
            calibration(200 + index, value),
            first_ts_ms=cutoff + 1 + index * DAY_MS,
            last_ts_ms=cutoff + 55 * 60_000 + 1 + index * DAY_MS,
        )
        for index, value in enumerate(("0.1", "0.2", "0.3", "0.5", "0.55", "0.6"))
    ]

    scope = confirmed_volatility_scope(payload, rows)

    assert scope["confirmed_buckets"] == ["low", "normal"]
    assert scope["blocked_buckets"] == ["high"]
    assert verify_volatility_scope(scope, policy=payload) is True
    assert "credential" not in json.dumps(scope).lower()


def test_policy_file_is_strict_and_cli_cannot_overwrite(tmp_path, monkeypatch):
    from bin import volatility_policy as command

    paths = selection_reports(tmp_path)
    cutoff = 101 * DAY_MS
    output = tmp_path / "policy.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "volatility_policy",
            *(str(path) for path in paths),
            "--cutoff-ts-ms",
            str(cutoff),
            "--created-at-ms",
            str(cutoff),
            "--output",
            str(output),
            "--confirm",
            "FREEZE-VOLATILITY-SELECTION",
        ],
    )
    assert command.main() == 0
    assert read_volatility_policy(output)["apply_allowed"] is False
    with pytest.raises(FileExistsError):
        command.main()
    serialized = output.read_text(encoding="utf-8").lower()
    assert "credential" not in serialized
    assert "secret" not in serialized
