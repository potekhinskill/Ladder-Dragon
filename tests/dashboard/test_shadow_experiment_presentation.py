"""Compact SHADOW experiment dashboard regressions."""

from pathlib import Path


def test_shadow_experiments_are_collapsed_and_use_safe_runtime_fields():
    index = Path("FRONT/index.html").read_text(encoding="utf-8")
    script = Path("FRONT/dashboard.js").read_text(encoding="utf-8")
    styles = Path("FRONT/dashboard.css").read_text(encoding="utf-8")
    locales = Path("FRONT/locales.js").read_text(encoding="utf-8")

    assert '<details class="shadow-experiments"' in index
    assert "function updateShadowExperiments(prediction)" in script
    assert "row.available_independent_samples" in script
    assert "row.training_independent_samples" in script
    assert "row.required_training_independent_samples" in script
    assert "row.live_training_independent_samples" in script
    assert "row.evaluated_independent_samples" in script
    assert "const measured=evaluated>0" in script
    assert "row.required_total_independent_samples" in script
    assert "row.estimated_ready_ts_ms" in script
    assert "row.estimated_ready_days" in script
    assert "row.readiness_reason" in script
    assert "row.historical_training_independent_samples" in script
    assert "outcomes.overdue" in script
    assert "row.configuration_holm_passed" in script
    assert "report.eligible_for_second_gate_review" in script
    assert "report.confirmation_evidence" in script
    assert "confirmationProgress.confirmation_futile" in script
    assert "confirmation.execution_model_gate" in script
    assert "episode.evidence_quality" in script
    assert "episode.excursion_diagnostics" in script
    assert "episode.entry_quality_diagnostics" in script
    assert "shadow_statistics_gate" in script
    assert "shadow_regime_gate" in script
    assert "shadow_replay_gate" in script
    assert "shadow_activation_gate" in script
    assert "const launchLine=Number.isFinite(launchAt)" in script
    assert "report.selection_progress" in script
    assert "progress.resolved_outcomes" in script
    assert "Object.entries(symbols)" in script
    assert "Object.values(symbols)" not in script
    assert "superseded_reports" in script
    assert "lifecycle_status" in script
    assert "<h3>${esc(symbol)}" in script
    assert "openHistoryKeys" in script
    assert "details.shadow-experiment-history[open][data-history-key]" in script
    assert 'data-history-key="${esc(historyKey)}"' in script
    assert "openHistoryKeys.has(historyKey)?' open':''" in script
    assert "shadow_selection_only" in script
    assert ".shadow-experiment-list" in styles
    assert ".shadow-experiment-symbol" in styles
    assert ".shadow-experiment-history" in styles
    for key in (
        "shadow_experiment_summary",
        "shadow_generation_progress",
        "shadow_samples",
        "shadow_raw",
        "shadow_available",
        "shadow_training",
        "shadow_historical_training",
        "shadow_live_training",
        "shadow_evaluated",
        "shadow_required_total",
        "shadow_ready_eta",
        "shadow_ready_days",
        "shadow_waiting_reason",
        "shadow_statistics_gate",
        "shadow_regime_gate",
        "shadow_replay_gate",
        "shadow_activation_gate",
        "shadow_evidence_quality",
        "shadow_excursions",
        "shadow_entry_quality",
        "shadow_target_reach",
        "shadow_break_even",
        "shadow_not_scheduled",
        "shadow_safety_only",
        "shadow_outcomes",
        "shadow_overdue",
        "shadow_fill",
        "shadow_regimes",
        "shadow_confirmation",
        "shadow_execution_model",
        "shadow_futile",
        "shadow_windows",
        "shadow_selection_only",
        "shadow_supersedes",
    ):
        assert locales.count(f"{key}:") == 2
