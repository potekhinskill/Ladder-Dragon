from pathlib import Path


def test_positions_and_ai_quality_share_one_responsive_row_with_consistent_type():
    index = Path("FRONT/index.html").read_text(encoding="utf-8")
    styles = Path("FRONT/dashboard.css").read_text(encoding="utf-8")

    assert 'class="card monitor-card position-monitor-card"' in index
    assert 'class="card monitor-card ai-quality-card"' in index
    assert 'class="card monitor-card full"' not in index
    assert "--font-base:13px" in styles
    assert "--font-heading:15px" in styles
    assert ".ai-quality-card .monitor-grid{grid-template-columns:1fr}" in styles
    assert "@media (max-width:800px){.grid-monitor{grid-template-columns:1fr}" in styles
    assert "font-size:10px" not in styles
    assert "font-size:11px" not in styles
    assert "font-size:12px" not in styles
