from pathlib import Path

from ladder_dragon.supervision.panic_observer import (
    panic_observer_fingerprint,
    panic_observer_path,
    read_panic_observation,
    refresh_panic_observation,
)


def klines(*, current: str = "100", previous: str = "100"):
    rows = [
        [index * 60_000, "100", "101", "99", previous, "1",
         index * 60_000 + 59_999]
        for index in range(120)
    ]
    rows[-1][4] = current
    return rows


def public(payload):
    def get(endpoint, params):
        assert endpoint == "/api/v3/klines"
        assert params == {"symbol": "SOLUSDT", "interval": "1m", "limit": 120}
        return payload
    return get


def test_observer_debounces_and_persists_without_worker(tmp_path):
    first = refresh_panic_observation(
        "SOLUSDT", public_get=public(klines(current="95")),
        now_ms=1_000_000, run_dir=tmp_path,
    )
    assert first["on"] is False and first["hits"] == 1
    second = refresh_panic_observation(
        "SOLUSDT", public_get=public(klines(current="95")),
        now_ms=1_060_000, run_dir=tmp_path,
    )
    assert second["on"] is True and second["hits"] == 2
    assert second["source_fingerprint"] == panic_observer_fingerprint()
    assert read_panic_observation(
        "SOLUSDT", now_ms=1_060_001, run_dir=tmp_path
    ) == second


def test_stale_or_wrong_fingerprint_never_becomes_context(tmp_path):
    refresh_panic_observation(
        "SOLUSDT", public_get=public(klines()), now_ms=1_000_000,
        run_dir=tmp_path,
    )
    assert read_panic_observation(
        "SOLUSDT", now_ms=1_120_001, run_dir=tmp_path
    ) is None
    path = panic_observer_path("SOLUSDT", run_dir=tmp_path)
    text = path.read_text(encoding="utf-8").replace(
        panic_observer_fingerprint(), "0" * 64
    )
    path.write_text(text, encoding="utf-8")
    assert read_panic_observation(
        "SOLUSDT", now_ms=1_000_001, run_dir=tmp_path
    ) is None


def test_observer_state_is_bounded_and_non_secret(tmp_path):
    refresh_panic_observation(
        "SOLUSDT", public_get=public(klines()), now_ms=1_000_000,
        run_dir=tmp_path,
    )
    path = panic_observer_path("SOLUSDT", run_dir=tmp_path)
    assert path.stat().st_size < 16_384
    assert path.stat().st_mode & 0o077 == 0
    assert b"api" not in path.read_bytes().lower()


def test_invalid_symbol_cannot_escape_run_directory(tmp_path):
    try:
        panic_observer_path("../SOLUSDT", run_dir=tmp_path)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid symbol was accepted")
    assert not any(Path(tmp_path).iterdir())
