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
    assert "esc(name.replace" in script
    assert ".shadow-experiment-list" in styles
    for key in (
        "shadow_experiment_summary",
        "shadow_samples",
        "shadow_outcomes",
        "shadow_overdue",
        "shadow_fill",
        "shadow_regimes",
    ):
        assert locales.count(f"{key}:") == 2
