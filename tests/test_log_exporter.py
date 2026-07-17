import importlib.util
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


def load_exporter():
    path = Path("deploy/export_sanitized_logs.py").resolve()
    spec = importlib.util.spec_from_file_location("log_exporter", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_sanitize_redacts_credentials_and_binance_signature():
    exporter = load_exporter()
    source = (
        "Authorization: Bearer secret.jwt.value\n"
        "X-MBX-APIKEY=real-key\n"
        "api_secret: real-secret\n"
        "GET /api?timestamp=123&signature=abcdef&symbol=SOLUSDT\n"
    )

    sanitized, replacements = exporter.sanitize(source)

    assert replacements >= 4
    assert "secret.jwt.value" not in sanitized
    assert "real-key" not in sanitized
    assert "real-secret" not in sanitized
    assert "abcdef" not in sanitized
    assert sanitized.count("<redacted>") >= 4
    assert "SOLUSDT" in sanitized


def test_sanitize_redacts_project_prefixed_environment_secrets():
    exporter = load_exporter()
    source = (
        "DEEPSEEK_API_KEY=deepseek-secret\n"
        "DASHBOARD_BINANCE_API_SECRET='binance-secret'\n"
        "BOT_WEBHOOK_URL=https://user:password@example.invalid/hook\n"
    )

    sanitized, replacements = exporter.sanitize(source)

    assert replacements >= 3
    for secret in ("deepseek-secret", "binance-secret", "password"):
        assert secret not in sanitized


def test_sanitize_redacts_json_cookies_url_credentials_and_private_keys():
    exporter = load_exporter()
    source = (
        '{"apiKey":"json-key","token": "json-token"}\n'
        "Cookie: session=browser-secret\n"
        "https://robot:url-password@example.com/path\n"
        "-----BEGIN PRIVATE KEY-----\nprivate-material\n"
        "-----END PRIVATE KEY-----\n"
    )

    sanitized, replacements = exporter.sanitize(source)

    assert replacements >= 5
    for secret in (
        "json-key",
        "json-token",
        "browser-secret",
        "url-password",
        "private-material",
    ):
        assert secret not in sanitized


def test_tail_bytes_keeps_recent_complete_lines(monkeypatch):
    exporter = load_exporter()
    monkeypatch.setattr(exporter, "MAX_BYTES", 64)
    source = "".join(f"line-{number:03d}\n" for number in range(30))

    result = exporter.tail_bytes(source)

    assert len(result.encode()) <= 64
    assert result.endswith("line-029\n")
    assert not result.startswith("-")


def test_cleanup_removes_only_expired_managed_daily_logs(tmp_path, monkeypatch):
    exporter = load_exporter()
    now = datetime(2026, 7, 16, tzinfo=timezone.utc)
    monkeypatch.setattr(exporter, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(exporter, "RETENTION_DAYS", 7)
    expired = tmp_path / "mybot-2026-07-08.log"
    kept = tmp_path / "mybot-2026-07-09.log"
    unrelated = tmp_path / "current.log"
    for path in (expired, kept, unrelated):
        path.write_text("x")

    exporter.cleanup(now)

    assert not expired.exists()
    assert kept.exists()
    assert unrelated.exists()
