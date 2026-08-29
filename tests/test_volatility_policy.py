from __future__ import annotations

from decimal import Decimal
import json

import pytest

from ladder_dragon.strategy.market_replay import ReplayCalibration
from ladder_dragon.strategy.replay_readiness import audit_replay_readiness
from ladder_dragon.strategy.volatility_policy import (
    confirmation_cohort_reasons,
    read_volatility_policy,
    select_volatility_policy,
    verify_volatility_policy,
)


DAY_MS = 86_400_000


def calibration(index: int, volatility: str) -> ReplayCalibration:
    return ReplayCalibration(
        schema_version=4,
        archive_sha256=f"{index:064x}",
        first_ts_ms=index * DAY_MS,
        last_ts_ms=index * DAY_MS + 900_000,
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
        latency_source="public_event_receive",
    )


def selection_reports(tmp_path):
    paths = []
    for index in range(1, 101):
        volatility = Decimal(index) / Decimal("100")
        path = tmp_path / f"calibration-{index}.json"
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
    assert verify_volatility_policy(payload) is True
    damaged = dict(payload, high_min_bps="0.1")
    assert verify_volatility_policy(damaged) is False


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
