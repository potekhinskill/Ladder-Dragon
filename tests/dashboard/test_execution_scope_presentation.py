from pathlib import Path


def test_dashboard_distinguishes_execution_and_shadow_only_symbols():
    index = Path("FRONT/index.html").read_text(encoding="utf-8")
    script = Path("FRONT/dashboard.js").read_text(encoding="utf-8")
    locales = Path("FRONT/locales.js").read_text(encoding="utf-8")

    assert 'id="trade-execution-symbols"' in index
    assert "execution_permitted_symbols" in script
    assert "mode==='LIVE'&&!permittedSymbols.length?'SHADOW':mode" in script
    assert "'no active CHAMPION'" in script
    assert 'id="trade-shadow-symbols"' in index
    assert "prediction.shadow_only_symbols" in script
    assert "SHADOW · ${shadowOnlySymbols.join(', ')}" in script
    assert 'execution_symbols: "Execution symbols"' in locales
    assert 'shadow_only_symbols: "SHADOW-only symbols"' in locales
    assert locales.count("execution_symbols:") == 2
    assert locales.count("shadow_only_symbols:") == 2
