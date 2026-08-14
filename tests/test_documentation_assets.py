from __future__ import annotations

from pathlib import Path

from ladder_dragon.execution.user_stream import CURRENT_USER_STREAM_SOAK_EPOCH_ID


ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / "docs" / "assets" / "dashboard-overview-sanitized.png"
RUNTIME_REFERENCE = ROOT / "docs" / "RUNTIME_SAFETY_AND_REPORTING.md"
DECISIONS = ROOT / "DECISIONS.md"
MISTAKES = ROOT / "MISTAKES.md"


def test_sanitized_dashboard_preview_is_documented() -> None:
    assert ASSET.is_file()
    assert ASSET.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    introduction = (ROOT / "docs" / "INTRODUCTION.md").read_text(
        encoding="utf-8"
    )
    assert "docs/assets/dashboard-overview-sanitized.png" in readme
    assert "assets/dashboard-overview-sanitized.png" in introduction
    assert "DEMO" in readme or "demonstration data" in readme


def test_live_dashboard_capture_is_not_committed_as_documentation() -> None:
    asset_bytes = ASSET.read_bytes()
    forbidden_metadata = (
        b"acb32f2f22964cde9e01e943a9ee2efe",
        b"17541359278",
        b"311.87874973",
        b"3378143",
    )
    for value in forbidden_metadata:
        assert value not in asset_bytes

    tracked_docs = {
        path.name
        for path in (ROOT / "docs" / "assets").iterdir()
        if path.is_file()
    }
    original_capture_prefix = "\u0421\u043a\u0440\u0438\u043d\u0448\u043e\u0442"
    assert not any(name.startswith(original_capture_prefix) for name in tracked_docs)


def test_runtime_safety_reference_is_linked_and_matches_current_contracts() -> None:
    assert RUNTIME_REFERENCE.is_file()
    reference = RUNTIME_REFERENCE.read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    introduction = (ROOT / "docs" / "INTRODUCTION.md").read_text(
        encoding="utf-8"
    )
    runbook = (ROOT / "docs" / "RASPBERRY_PI_INSTALL.md").read_text(
        encoding="utf-8"
    )

    for required in (
        "TP > market > STOP > STOP_LIMIT",
        "HALT and SHADOW are separate states",
        "Managed and legacy inventory",
        "Exact PnL and dashboard availability",
        "Excluded symbols",
        "RISK_STABLE_INFO_LOG_INTERVAL_SEC",
    ):
        assert required in reference
    epoch_version = CURRENT_USER_STREAM_SOAK_EPOCH_ID.rsplit("-v", 1)[1]
    assert f"current v{epoch_version} epoch" in reference
    assert "retains the v1 through v4 epochs" in reference
    assert "docs/RUNTIME_SAFETY_AND_REPORTING.md" in readme
    assert "RUNTIME_SAFETY_AND_REPORTING.md" in introduction
    assert "RUNTIME_SAFETY_AND_REPORTING.md" in runbook


def test_agent_learning_records_are_required_and_structured() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    decisions = DECISIONS.read_text(encoding="utf-8")
    mistakes = MISTAKES.read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Read `DECISIONS.md` and `MISTAKES.md` completely" in agents
    assert "root cause" in agents.lower()
    for heading in ("**Context:**", "**Decision:**", "**Why it worked:**", "**Reuse:**"):
        assert heading in decisions
    for heading in ("**Impact:**", "**Root cause:**", "**Correction:**", "**Prevention:**"):
        assert heading in mistakes
    assert "DECISIONS.md" in readme
    assert "MISTAKES.md" in readme


def test_remote_branch_policy_keeps_only_main() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

    assert "Keep `main` as the only branch published to GitHub" in agents
    assert "never push that branch to `origin`" in agents
    assert "blocks creation of every branch except `main`" in agents
