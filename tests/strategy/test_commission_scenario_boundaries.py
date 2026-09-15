import json
import runpy

import pytest

from bin.replay_historical_entries import _combined_path_report
from ladder_dragon.strategy.prediction.historical_policy import fingerprint
from ladder_dragon.strategy.prediction.historical_selection import _validate
from ladder_dragon.strategy.prediction.replay_progress import PathCheckpoint


@pytest.mark.parametrize("location", ["policy", "baseline", "veto"])
def test_retagged_scenario_fails_selection_validation(location):
    report = runpy.run_path("tests/strategy/test_historical_selection.py")["report"](0)
    _validate(report, cutoff_ts_ms=report["cutoff_ts_ms"])
    if location == "policy":
        report["policy"]["commission_asset_scenario"] = "QUOTE"
        report["policy_sha256"] = fingerprint(report["policy"])
    else:
        report["episodes"][location][0]["commission_asset_evidence"] = "POLICY_ASSUMPTION"
    report["report_sha256"] = fingerprint({key: value for key, value in report.items() if key != "report_sha256"})
    with pytest.raises(ValueError, match="commission scenarios"):
        _validate(report, cutoff_ts_ms=report["cutoff_ts_ms"])


@pytest.mark.parametrize("marker", ["commission_asset_scenario", "commission_asset_evidence"])
def test_checkpoint_revalidates_scenario_markers_on_write_and_read(tmp_path, marker):
    h = runpy.run_path("tests/strategy/test_replay_progress.py")
    cache = PathCheckpoint(tmp_path, h["binding"]())
    report = h["report"]()
    report["episodes"] = {"baseline": [{marker: "QUOTE"}], "veto": []}
    with pytest.raises(ValueError, match="commission scenarios"):
        cache.write([report])
    assert cache.read() is None
    cache.write([h["report"]()])
    payload = json.loads(cache.path.read_text())
    payload["reports"] = [report]
    payload["checkpoint_sha256"] = fingerprint({key: value for key, value in payload.items() if key != "checkpoint_sha256"})
    cache.path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="commission scenarios"):
        cache.read()


def paths(statuses):
    request = {"paths": [], "cohort_contract": "synthetic", "stability_block_index": 0}
    reports = []
    for index, status in enumerate(statuses):
        request["paths"].append(dict(start_ms=1 + index * 10, entry_end_ms=2 + index * 10,
                                     end_ms=3 + index * 10, cutoff_ms=3 + index * 10))
        policy = {"symbol": "SOLUSDT", "commission_asset_scenario": "QUOTE"}
        report = dict(status=status, policy=policy, policy_sha256=fingerprint(policy),
                      model_contract="historical_net_inventory_scenarios_v4", model_source_sha256s={"model": "a" * 64},
                      episodes={"baseline": [], "veto": []}, remaining_gates=["commission asset qualification"],
                      summaries={name: dict(opportunities=0, filled=0, censored=int(status == "INCOMPLETE_HISTORY"),
                                            net_pnl_quote="0") for name in ("baseline", "veto")})
        reports.append((report, {"context": []}, [format(index + 1, "064x")]))
    return request, reports


@pytest.mark.parametrize("statuses, expected", [
    (["COMPLETE_COMMISSION_SCENARIO"] * 3, "COMPLETE_COMMISSION_SCENARIO"),
    (["COMPLETE_COMMISSION_SCENARIO", "COMPLETE_SELECTION_REPLAY", "COMPLETE_COMMISSION_SCENARIO"], "COMPLETE_COMMISSION_SCENARIO"),
    (["COMPLETE_COMMISSION_SCENARIO", "INCOMPLETE_HISTORY", "COMPLETE_COMMISSION_SCENARIO"], "INCOMPLETE_HISTORY"),
])
def test_combined_paths_preserve_qualification_status(statuses, expected):
    report = _combined_path_report(*paths(statuses))
    assert report["status"] == expected
    assert report["apply_allowed"] is False and report["promotion_eligible"] is False


def test_combiner_rejects_all_retagged_scenarios():
    with pytest.raises(ValueError, match="commission scenarios"):
        _combined_path_report(*paths(["COMPLETE_SELECTION_REPLAY"] * 3))
