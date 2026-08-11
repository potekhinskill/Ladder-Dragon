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


def test_operational_rows_keep_readable_value_widths():
    index = Path("FRONT/index.html").read_text(encoding="utf-8")
    styles = Path("FRONT/dashboard.css").read_text(encoding="utf-8")

    assert index.count('class="card monitor-card operations-monitor-card"') == 2
    assert ".operations-monitor-card .monitor-grid{grid-template-columns:1fr}" in styles
    assert (
        ".operations-monitor-card .monitor-row{display:grid;"
        "grid-template-columns:minmax(150px,42%) minmax(0,1fr);column-gap:16px}"
    ) in styles
    assert ".operations-monitor-card .monitor-row>span:last-child{overflow-wrap:break-word;word-break:normal}" in styles
    assert ".operations-monitor-card .monitor-row>span:last-child{text-align:left}" in styles
