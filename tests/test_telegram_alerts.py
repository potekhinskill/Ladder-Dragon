import json

import telegram_alerts


def test_legacy_config_is_supported_without_exposing_values(tmp_path, monkeypatch):
    config = tmp_path / "telegram.env"
    config.write_text(
        "BOT_ALERTS_ENABLED=0\nBOT_TOKEN=secret-token\nCHAT_ID=123\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_ALERTS_CONFIG", str(config))
    values = telegram_alerts.load_config()
    assert values["BOT_TOKEN"] == "secret-token"
    assert telegram_alerts.send_message("test") is False


def test_send_message_posts_json_without_logging_secret(tmp_path, monkeypatch):
    config = tmp_path / "telegram.env"
    config.write_text(
        "TELEGRAM_ALERTS_ENABLED=1\n"
        "TELEGRAM_BOT_TOKEN=secret-token\n"
        "TELEGRAM_CHAT_ID=123\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_ALERTS_CONFIG", str(config))
    captured = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(telegram_alerts.urllib.request, "urlopen", fake_urlopen)
    assert telegram_alerts.notify("circuit_breaker", ["daily loss exceeded"]) is True
    assert "secret-token" in captured["url"]
    assert captured["body"]["chat_id"] == "123"
    assert captured["body"]["text"] == (
        "Ladder Dragon: circuit_breaker\nПричина: daily loss exceeded"
    )
