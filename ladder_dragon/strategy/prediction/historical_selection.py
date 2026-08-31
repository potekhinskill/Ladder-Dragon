# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: freeze cutoff-safe historical entry-veto selection evidence.
"""Strict historical replay importer that cannot satisfy live confirmation."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
from math import comb
from pathlib import Path
import time
from typing import Iterable, Mapping

from ladder_dragon.strategy.prediction.historical_entry_replay import MODEL_CONTRACT
from ladder_dragon.strategy.prediction.historical_policy import fingerprint
from ladder_dragon.strategy.prediction.entry_diagnostics import (
    MAXIMUM_SELECTION_ARTIFACTS,
)


MINIMUM_REPORT_BLOCKS = 3
MINIMUM_INDEPENDENT_PATHS = 12
LEGACY_MINIMUM_OPPORTUNITIES = 30
PATH_MINIMUM_OPPORTUNITIES = 12
MAXIMUM_REPORTS = 128
MAXIMUM_REPORT_BYTES = 16 * 1024 * 1024
PATH_COHORT_CONTRACT = "provider_bounded_disjoint_paths_v1"
REQUIRED_STABILITY_BLOCKS = 4
PATHS_PER_STABILITY_BLOCK = 3
PLANNING_RATE_FAMILY_ALPHA = Decimal("0.05")
PLANNING_RATE_HYPOTHESES = 3
PLANNING_RATE_ALPHA = (
    PLANNING_RATE_FAMILY_ALPHA / Decimal(PLANNING_RATE_HYPOTHESES)
)


def _decimal(value: object, *, field: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"historical {field} is invalid") from exc
    if not number.is_finite():
        raise ValueError(f"historical {field} is invalid")
    return number


def _one_sided_binomial_lower_bound(
    successes: int, trials: int, *, alpha: Decimal = PLANNING_RATE_ALPHA
) -> Decimal:
    """Return a conservative exact lower bound for one binomial rate."""
    if type(successes) is not int or type(trials) is not int:
        raise ValueError("historical planning counts are invalid")
    if not 0 <= successes <= trials <= 10_000:
        raise ValueError("historical planning counts are invalid")
    if trials == 0 or successes == 0:
        return Decimal("0")
    if not Decimal("0") < alpha < Decimal("1"):
        raise ValueError("historical planning alpha is invalid")

    # Invert P_p[X >= successes] = alpha. The lower endpoint is returned
    # conservatively, so rounding cannot make confirmation capacity smaller.
    with localcontext() as context:
        context.prec = 60

        def upper_tail(probability: Decimal) -> Decimal:
            complement = Decimal("1") - probability
            return sum(
                Decimal(comb(trials, outcome))
                * probability**outcome
                * complement ** (trials - outcome)
                for outcome in range(successes, trials + 1)
            )

        lower = Decimal("0")
        upper = Decimal(successes) / Decimal(trials)
        for _ in range(160):
            midpoint = (lower + upper) / Decimal("2")
            if upper_tail(midpoint) < alpha:
                lower = midpoint
            else:
                upper = midpoint
        return +lower


def _load(path: Path, expected_sha256: str) -> dict[str, object]:
    if path.stat().st_size > MAXIMUM_REPORT_BYTES:
        raise ValueError("historical replay report is oversized")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("historical replay file fingerprint differs")
    try:
        report = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("historical replay report is invalid") from exc
    if not isinstance(report, dict):
        raise ValueError("historical replay report must be an object")
    embedded = report.get("report_sha256")
    body = {key: value for key, value in report.items() if key != "report_sha256"}
    if embedded != fingerprint(body):
        raise ValueError("historical replay report identity differs")
    return report


def _validate(report: Mapping[str, object], *, cutoff_ts_ms: int) -> None:
    body = {key: value for key, value in report.items() if key != "report_sha256"}
    if report.get("report_sha256") != fingerprint(body):
        raise ValueError("historical replay report identity differs")
    schema = report.get("schema_version")
    if (
        schema not in {1, 2}
        or report.get("model_contract") != MODEL_CONTRACT
        or report.get("status") != "COMPLETE_SELECTION_REPLAY"
        or report.get("mode") != "SHADOW"
        or report.get("apply_allowed") is not False
        or report.get("promotion_eligible") is not False
        or report.get("selection_artifact_ready") is not False
    ):
        raise ValueError("historical replay is not selection-only and complete")
    for field in ("start_ts_ms", "entry_end_ts_ms", "end_ts_ms", "cutoff_ts_ms"):
        if type(report.get(field)) is not int:
            raise ValueError("historical replay timestamp is invalid")
    if not (
        0 < report["start_ts_ms"] < report["entry_end_ts_ms"]
        < report["end_ts_ms"] <= report["cutoff_ts_ms"] <= cutoff_ts_ms
    ):
        raise ValueError("historical replay exceeds the frozen cutoff")
    if not isinstance(report.get("policy"), dict):
        raise ValueError("historical replay policy is unavailable")
    if report.get("policy_sha256") != fingerprint(report["policy"]):
        raise ValueError("historical replay policy identity differs")
    if not isinstance(report.get("source_sha256s"), list) or not report["source_sha256s"]:
        raise ValueError("historical replay sources are unavailable")
    if any(
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
        for value in report["source_sha256s"]
    ) or len(report["source_sha256s"]) != len(set(report["source_sha256s"])):
        raise ValueError("historical replay source identity is invalid")
    if not isinstance(report.get("episodes"), dict) or set(report["episodes"]) != {"baseline", "veto"}:
        raise ValueError("historical replay paired episodes are unavailable")
    if schema == 2:
        windows = report.get("path_windows")
        if (
            report.get("cohort_contract") != PATH_COHORT_CONTRACT
            or type(report.get("stability_block_index")) is not int
            or not 0 <= report["stability_block_index"] < REQUIRED_STABILITY_BLOCKS
            or not isinstance(windows, list)
            or len(windows) != PATHS_PER_STABILITY_BLOCK
        ):
            raise ValueError("historical path cohort identity is invalid")
        previous_end = -1
        path_hashes: set[str] = set()
        for window in windows:
            if not isinstance(window, dict) or set(window) != {
                "start_ts_ms", "entry_end_ts_ms", "end_ts_ms",
                "cutoff_ts_ms", "source_sha256s",
            }:
                raise ValueError("historical path window is invalid")
            if any(
                type(window.get(field)) is not int
                for field in (
                    "start_ts_ms", "entry_end_ts_ms", "end_ts_ms",
                    "cutoff_ts_ms",
                )
            ) or not (
                previous_end < window["start_ts_ms"]
                < window["entry_end_ts_ms"] < window["end_ts_ms"]
                <= window["cutoff_ts_ms"] <= cutoff_ts_ms
            ):
                raise ValueError("historical path timestamps are invalid")
            hashes = window["source_sha256s"]
            if (
                not isinstance(hashes, list)
                or not hashes
                or any(not isinstance(value, str) or len(value) != 64 for value in hashes)
                or path_hashes & set(hashes)
            ):
                raise ValueError("historical path sources are invalid")
            path_hashes.update(hashes)
            previous_end = int(window["end_ts_ms"])
        if (
            path_hashes != set(report["source_sha256s"])
            or report["start_ts_ms"] != windows[0]["start_ts_ms"]
            or report["entry_end_ts_ms"] != windows[-1]["entry_end_ts_ms"]
            or report["end_ts_ms"] != windows[-1]["end_ts_ms"]
            or report["cutoff_ts_ms"] != windows[-1]["cutoff_ts_ms"]
        ):
            raise ValueError("historical path block boundary differs")


def _rows(report: Mapping[str, object], name: str) -> list[Mapping[str, object]]:
    rows = report["episodes"][name]
    if not isinstance(rows, list) or len(rows) > 10_000:
        raise ValueError("historical replay episode capacity differs")
    output = []
    previous = -1
    for row in rows:
        if not isinstance(row, dict) or type(row.get("started_at_ms")) is not int:
            raise ValueError("historical replay episode is invalid")
        if row["started_at_ms"] < previous:
            raise ValueError("historical replay episodes are not chronological")
        previous = row["started_at_ms"]
        _decimal(row.get("net_pnl_quote"), field="PnL")
        if type(row.get("censored")) is not bool:
            raise ValueError("historical replay censor flag is invalid")
        output.append(row)
    return output


def load_historical_report(
    path: Path, expected_sha256: str
) -> dict[str, object]:
    """Load one immutable replay report for an explicit evidence role."""
    return _load(path, expected_sha256)


def validate_historical_replay_report(
    report: Mapping[str, object], *, cutoff_ts_ms: int
) -> None:
    """Validate one complete paired report without assigning its cohort role."""
    _validate(report, cutoff_ts_ms=cutoff_ts_ms)


def historical_report_rows(
    report: Mapping[str, object], name: str
) -> list[Mapping[str, object]]:
    """Return validated chronological episode rows from one policy arm."""
    if name not in {"baseline", "veto"}:
        raise ValueError("historical replay policy arm is invalid")
    return _rows(report, name)


def _net(rows: Iterable[Mapping[str, object]]) -> Decimal:
    return sum(
        (_decimal(row["net_pnl_quote"], field="PnL") for row in rows if not row["censored"]),
        Decimal("0"),
    )


def _independent(rows: list[Mapping[str, object]], spacing_ms: int) -> list[Mapping[str, object]]:
    selected: list[Mapping[str, object]] = []
    next_allowed = -1
    for row in rows:
        stamp = int(row["started_at_ms"])
        if stamp >= next_allowed:
            selected.append(row)
            next_allowed = stamp + spacing_ms
    return selected


def historical_selection_artifact(
    reports: list[dict[str, object]],
    *,
    source_generation: str,
    candidate_fingerprint: str,
    cutoff_ts_ms: int,
) -> dict[str, object]:
    """Build one immutable selection artifact from non-overlapping reports."""
    if not reports or len(reports) > MAXIMUM_REPORTS:
        raise ValueError("historical selection report count is invalid")
    if type(cutoff_ts_ms) is not int or cutoff_ts_ms <= 0:
        raise ValueError("historical selection cutoff is invalid")
    if len(candidate_fingerprint) != 64:
        raise ValueError("historical selection candidate identity is invalid")
    reports = sorted(reports, key=lambda row: int(row.get("start_ts_ms", 0)))
    for report in reports:
        _validate(report, cutoff_ts_ms=cutoff_ts_ms)
    path_cohort = all(report.get("schema_version") == 2 for report in reports)
    if path_cohort:
        if (
            len(reports) != REQUIRED_STABILITY_BLOCKS
            or [report["stability_block_index"] for report in reports]
            != list(range(REQUIRED_STABILITY_BLOCKS))
        ):
            raise ValueError("historical stability block cohort is incomplete")
    elif not (
        all(report.get("schema_version") == 1 for report in reports)
        and len(reports) >= MINIMUM_REPORT_BLOCKS
    ):
        raise ValueError("historical selection report schemas differ")
    policy = reports[0]["policy"]
    policy_sha = reports[0]["policy_sha256"]
    model_sources = reports[0].get("model_source_sha256s")
    previous_end = -1
    source_hashes: set[str] = set()
    for report in reports:
        if report["policy_sha256"] != policy_sha or report.get("model_source_sha256s") != model_sources:
            raise ValueError("historical replay implementations or policies differ")
        if report["start_ts_ms"] <= previous_end:
            raise ValueError("historical replay blocks overlap")
        previous_end = int(report["end_ts_ms"])
        hashes = set(report["source_sha256s"])
        if source_hashes & hashes:
            raise ValueError("historical replay source is reused")
        source_hashes |= hashes
    veto_rows = [row for report in reports for row in _rows(report, "veto")]
    baseline_rows = [row for report in reports for row in _rows(report, "baseline")]
    spacing_ms = max(21_600_000, int(policy["holding_ms"]))
    independent = _independent(veto_rows, spacing_ms)
    opportunities = sum(int(report["summaries"]["veto"]["opportunities"]) for report in reports)
    veto_net, baseline_net = _net(veto_rows), _net(baseline_rows)
    block_deltas = [
        _net(_rows(report, "veto")) - _net(_rows(report, "baseline"))
        for report in reports
    ]
    stable_blocks = sum(delta >= 0 for delta in block_deltas)
    vetoed = sum(
        row.get("terminal_reason") == "ENTRY_VETO" for row in veto_rows
    )
    filled_rows = [
        row for row in veto_rows
        if (
            "entry_filled_quantity" not in row
            or _decimal(
                row.get("entry_filled_quantity"), field="filled quantity"
            ) > 0
        )
    ]
    independent_terminal = [row for row in independent if not row["censored"]]
    if path_cohort and any(
        type(row.get("eligible_for_promotion")) is not bool
        or not isinstance(row.get("start_regime"), str)
        or "entry_filled_quantity" not in row
        for row in independent_terminal
    ):
        raise ValueError("historical path planning metadata is incomplete")
    eligible_independent = [
        row for row in independent_terminal
        if row.get("eligible_for_promotion") is True
    ]
    filled_independent = [
        row for row in eligible_independent
        if _decimal(
            row.get("entry_filled_quantity"), field="filled quantity"
        ) > 0
    ]
    range_filled_independent = [
        row for row in filled_independent if row.get("start_regime") == "RANGE"
    ]
    planning_denominator = len(independent)

    def planning_lower(successes: int) -> Decimal:
        # Bonferroni-adjusted exact bounds cover all three planning rates.
        # Future confirmation outcomes must never resize this source cohort.
        return _one_sided_binomial_lower_bound(
            successes, planning_denominator
        )

    target_reachability = (
        Decimal(sum(row.get("terminal_reason") == "TAKE_PROFIT" for row in filled_rows))
        / Decimal(len(filled_rows))
        if filled_rows else Decimal("0")
    )
    veto_rate = Decimal(vetoed) / Decimal(opportunities) if opportunities else Decimal("0")
    ready = bool(
        opportunities >= (
            PATH_MINIMUM_OPPORTUNITIES
            if path_cohort else LEGACY_MINIMUM_OPPORTUNITIES
        )
        and len(independent) >= MINIMUM_INDEPENDENT_PATHS
        and stable_blocks * 3 >= len(reports) * 2
        and Decimal("0.05") <= veto_rate <= Decimal("0.40")
        and veto_net > 0
        and veto_net > baseline_net
    )
    if not ready:
        raise ValueError("historical replay selection criteria are incomplete")
    selected_rule = {
        "contract_version": "l2_adverse_selection_cancel_v3",
        "prefill_price_change_max_bps": str(policy["veto_price_bps"]),
        "prefill_signed_trade_flow_max": str(policy["veto_signed_flow"]),
        "prefill_order_flow_imbalance_max": str(policy["veto_ofi"]),
        "cancel_latency_ms": int(policy["cancel_latency_ms"]),
        "signal_window_ms": int(policy["signal_window_ms"]),
    }
    report_identities = [str(report["report_sha256"]) for report in reports]
    artifact = {
        "schema_version": 5 if path_cohort else 2,
        "mode": "SHADOW_SELECTION",
        "evidence_role": "HISTORICAL_SELECTION_ONLY",
        "can_change_orders": False,
        "historical_evidence_reused_for_confirmation": False,
        "symbol": str(policy["symbol"]),
        "source_generation": str(source_generation),
        "candidate_fingerprint": str(candidate_fingerprint),
        "cutoff_ts_ms": cutoff_ts_ms,
        "policy_sha256": str(policy_sha),
        "model_source_sha256s": model_sources,
        "source_archive_sha256s": sorted(source_hashes),
        "report_sha256s": report_identities,
        "selection_cohort_sha256": fingerprint({"reports": report_identities}),
        "cohort_contract": (
            PATH_COHORT_CONTRACT if path_cohort else "legacy_time_blocks_v1"
        ),
        "selection_metrics": {
            "opportunities": opportunities,
            "independent_paths": len(independent),
            "report_blocks": len(reports),
            "stable_blocks": stable_blocks,
            "veto_rate": format(veto_rate, "f"),
            "baseline_net_pnl_quote": format(baseline_net, "f"),
            "veto_net_pnl_quote": format(veto_net, "f"),
            "target_reachability": format(target_reachability, "f"),
            "planning_path_count": planning_denominator,
            "eligible_terminal_paths": len(eligible_independent),
            "filled_paths": len(filled_independent),
            "range_filled_paths": len(range_filled_independent),
            "planning_rate_family_alpha": format(
                PLANNING_RATE_FAMILY_ALPHA, "f"
            ),
            "planning_rate_hypotheses": PLANNING_RATE_HYPOTHESES,
            "planning_rate_alpha": format(PLANNING_RATE_ALPHA, "f"),
            "eligible_path_rate_lower_bound": format(
                planning_lower(len(eligible_independent)), "f"
            ),
            "filled_path_rate_lower_bound": format(
                planning_lower(len(filled_independent)), "f"
            ),
            "range_filled_path_rate_lower_bound": format(
                planning_lower(len(range_filled_independent)), "f"
            ),
            "confirmation_capacity_policy": (
                "bonferroni_clopper_pearson_lower_bound_v1"
            ),
        },
        "selected_rule": selected_rule,
    }
    return {**artifact, "artifact_sha256": fingerprint(artifact)}


def import_historical_selection(
    store,
    *,
    report_files: list[tuple[Path, str]],
    source_generation: str,
    candidate_fingerprint: str,
    cutoff_ts_ms: int,
) -> dict[str, object]:
    """Append one historical artifact after file and cohort verification."""
    reports = [_load(path, expected) for path, expected in report_files]
    artifact = historical_selection_artifact(
        reports,
        source_generation=source_generation,
        candidate_fingerprint=candidate_fingerprint,
        cutoff_ts_ms=cutoff_ts_ms,
    )
    with store._connect() as connection:
        count = int(connection.execute(
            "SELECT COUNT(*) FROM prediction_entry_veto_selection_artifacts"
        ).fetchone()[0])
        if count >= MAXIMUM_SELECTION_ARTIFACTS:
            raise RuntimeError("entry-veto selection artifact capacity reached")
        connection.execute(
            """INSERT INTO prediction_entry_veto_selection_artifacts
               (artifact_sha256,symbol,generation,candidate_fingerprint,
                cutoff_ts_ms,artifact_json,created_at_ms)
               VALUES(?,?,?,?,?,?,?)""",
            (
                artifact["artifact_sha256"], artifact["symbol"],
                source_generation, candidate_fingerprint, cutoff_ts_ms,
                json.dumps(
                    {key: value for key, value in artifact.items() if key != "artifact_sha256"},
                    sort_keys=True, separators=(",", ":"),
                ),
                int(time.time() * 1000),
            ),
        )
    return artifact


__all__ = ["historical_selection_artifact", "import_historical_selection"]
