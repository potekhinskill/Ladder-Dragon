"""Compact SHADOW experiment dashboard regressions."""

from pathlib import Path


def test_shadow_experiments_are_collapsed_and_use_safe_runtime_fields():
    index = Path("FRONT/index.html").read_text(encoding="utf-8")
    script = Path("FRONT/dashboard.js").read_text(encoding="utf-8")
    styles = Path("FRONT/dashboard.css").read_text(encoding="utf-8")
    locales = Path("FRONT/locales.js").read_text(encoding="utf-8")

    assert '<details class="shadow-experiments"' in index
    assert "function updateShadowExperiments(prediction)" in script
    assert "row.independent_samples" in script
    assert "outcomes.overdue" in script
    assert "row.configuration_holm_passed" in script
    assert "report.eligible_for_second_gate_review" in script
    assert "report.confirmation_evidence" in script
    assert "Object.entries(symbols)" in script
    assert "Object.values(symbols)" not in script
    assert "superseded_reports" in script
    assert "lifecycle_status" in script
    assert "<h3>${esc(symbol)}" in script
    assert "shadow_selection_only" in script
    assert ".shadow-experiment-list" in styles
    assert ".shadow-experiment-symbol" in styles
    assert ".shadow-experiment-history" in styles
    for key in (
        "shadow_experiment_summary",
        "shadow_samples",
        "shadow_outcomes",
        "shadow_overdue",
        "shadow_fill",
        "shadow_regimes",
        "shadow_confirmation",
        "shadow_windows",
        "shadow_selection_only",
        "shadow_supersedes",
    ):
        assert locales.count(f"{key}:") == 2
