import json

from ladder_dragon.execution import telegram_alerts
def test_migrated_variable_names_are_supported_in_current_config(tmp_path, monkeypatch):
    config = tmp_path / "telegram.env"
    config.write_text(
        "BOT_ALERTS_ENABLED=0\nBOT_TOKEN=secret-token\nCHAT_ID=123\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TELEGRAM_ALERTS_CONFIG", str(config))
    values = telegram_alerts.load_config()
    assert values["BOT_TOKEN"] == "secret-token"
    assert telegram_alerts.send_message("test") is False


def test_retired_system_path_is_not_read(tmp_path, monkeypatch):
    current = tmp_path / "telegram.env"
    retired = tmp_path / "bot-alerts.env"
    retired.write_text("BOT_TOKEN=retired-secret\nCHAT_ID=123\n", encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_ALERTS_CONFIG", str(current))
    monkeypatch.setattr(
        telegram_alerts,
        "DEFAULT_CONFIG",
        retired,
        raising=False,
    )

    assert telegram_alerts.load_config() == {}


def test_systemd_environment_works_when_config_path_is_not_readable(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(
        "TELEGRAM_ALERTS_CONFIG",
        str(tmp_path / "closed" / "telegram.env"),
    )
    monkeypatch.setenv("TELEGRAM_ALERTS_ENABLED", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "environment-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "321")

    values = telegram_alerts.load_config()

    assert values["TELEGRAM_ALERTS_ENABLED"] == "1"
    assert values["TELEGRAM_BOT_TOKEN"] == "environment-token"
    assert values["TELEGRAM_CHAT_ID"] == "321"


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
        "Ladder Dragon: circuit_breaker\nReason: daily loss exceeded"
    )


def test_binance_auth_alert_is_redacted_and_deduplicated(tmp_path, monkeypatch):
    config = tmp_path / "telegram.env"
    config.write_text(
        "TELEGRAM_ALERTS_ENABLED=1\n"
        "TELEGRAM_BOT_TOKEN=secret-token\n"
        "TELEGRAM_CHAT_ID=123\n",
        encoding="utf-8",
    )
    state = tmp_path / "auth-alert.json"
    monkeypatch.setenv("TELEGRAM_ALERTS_CONFIG", str(config))
    monkeypatch.setenv("BINANCE_AUTH_ALERT_STATE", str(state))
    captured = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout):
        captured.append(json.loads(request.data.decode("utf-8")))
        return Response()

    monkeypatch.setattr(telegram_alerts.urllib.request, "urlopen", fake_urlopen)
    assert telegram_alerts.notify_binance_auth_error(
        status=401,
        code=-2015,
        endpoint="https://api.binance.com/api/v3/account?signature=secret",
        message="Invalid API-key=secret-key",
    ) is True
    assert telegram_alerts.notify_binance_auth_error(
        status=401,
        code=-2015,
        endpoint="https://api.binance.com/api/v3/openOrders",
        message="Invalid API-key=secret-key",
    ) is False
    assert len(captured) == 1
    assert "-2015" in captured[0]["text"]
    assert "secret-key" not in captured[0]["text"]
    assert "api.binance.com/api/v3/account" in captured[0]["text"]


def test_ip_guard_notices_are_operator_focused(monkeypatch):
    notices = []
    monkeypatch.setattr(
        telegram_alerts,
        "notify",
        lambda *args, **kwargs: notices.append((args, kwargs)) or True,
    )

    assert telegram_alerts.notify_public_ip_change() is True
    assert telegram_alerts.notify_binance_auth_recovered(
        public_ip_accepted=True
    ) is True

    assert notices == [
        ((
            "public IP change detected",
            [
                "Two independent sources confirmed the change",
                "Binance access is checked automatically; BUY remains blocked",
                "No Raspberry Pi restart is required",
            ],
        ), {}),
        ((
            "Binance access restored",
            [
                "Signed Binance access succeeded",
                "IP Guard accepted the new public IP",
                "Other risk gates remain unchanged",
            ],
        ), {}),
    ]


def test_binance_auth_alert_retries_after_failed_delivery(tmp_path, monkeypatch):
    state = tmp_path / "auth-alert.json"
    now = [1000.0]
    results = iter([False, True])
    attempts = []
    monkeypatch.setenv("BINANCE_AUTH_ALERT_STATE", str(state))
    monkeypatch.setattr(telegram_alerts.time, "time", lambda: now[0])

    def fake_notify(event, reasons, metadata):
        attempts.append((event, reasons, metadata))
        return next(results)

    monkeypatch.setattr(telegram_alerts, "notify", fake_notify)
    kwargs = {
        "status": 401,
        "code": -2015,
        "endpoint": "/api/v3/openOrders",
        "retry_sec": 60.0,
    }

    assert telegram_alerts.notify_binance_auth_error(**kwargs) is False
    assert json.loads(state.read_text(encoding="utf-8"))["delivered"] is False
    now[0] += 59.0
    assert telegram_alerts.notify_binance_auth_error(**kwargs) is False
    assert len(attempts) == 1
    now[0] += 1.0
    assert telegram_alerts.notify_binance_auth_error(**kwargs) is True
    assert json.loads(state.read_text(encoding="utf-8"))["delivered"] is True
    assert len(attempts) == 2
