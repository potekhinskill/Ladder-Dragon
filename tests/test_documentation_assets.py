from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / "docs" / "assets" / "dashboard-overview-sanitized.png"


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
