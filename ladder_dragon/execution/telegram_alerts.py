# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Purpose: keep the file role and safety boundaries clear during maintenance.
"""Безопасная доставка аварийных уведомлений в Telegram.

Токен и chat id читаются только из root-owned файла конфигурации на Raspberry
Pi. В репозитории и в журнал не попадают ни секрет, ни URL с токеном.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request


DEFAULT_CONFIG = Path("/etc/ladder-dragon/telegram.env")
LEGACY_CONFIG = Path("/etc/bot-alerts.env")
AUTH_ALERT_STATE = Path("/run/mybot/binance-auth-alert.json")


def _parse_env(path: Path) -> dict[str, str]:
    """Прочитать простой KEY=VALUE-файл без shell-исполнения."""
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, PermissionError, OSError):
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[:1] == value[-1:] and value[:1] in {"'", '"'}:
            value = value[1:-1]
        values[name] = value
    return values


def load_config() -> dict[str, str]:
    """Загрузить новый конфиг, затем совместимый legacy-файл."""
    configured = Path(os.getenv("TELEGRAM_ALERTS_CONFIG", str(DEFAULT_CONFIG)))
    values = _parse_env(configured)
    if configured != LEGACY_CONFIG:
        legacy = _parse_env(LEGACY_CONFIG)
        for key, value in legacy.items():
            values.setdefault(key, value)
    return values


def _first(values: dict[str, str], *names: str) -> str:
    for name in names:
        value = values.get(name, "").strip()
        if value:
            return value
    return ""


def send_message(text: str, *, timeout: float = 5.0) -> bool:
    """Отправить сообщение; отсутствие Telegram не ломает торговый контур."""
    values = load_config()
    enabled = _first(values, "TELEGRAM_ALERTS_ENABLED", "BOT_ALERTS_ENABLED")
    if enabled.lower() in {"0", "false", "no", "off"}:
        return False
    token = _first(
        values, "TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN", "BOT_TOKEN", "TG_BOT_TOKEN"
    )
    chat_id = _first(
        values, "TELEGRAM_CHAT_ID", "TELEGRAM_CHAT", "CHAT_ID", "TG_CHAT_ID"
    )
    if not token or not chat_id:
        return False
    payload = json.dumps(
        {"chat_id": chat_id, "text": text[:3900], "disable_web_page_preview": True},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "ladder-dragon"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def notify(event: str, reasons: list[str] | tuple[str, ...], metadata: dict | None = None) -> bool:
    """Сформировать короткое уведомление с точной причиной остановки."""
    lines = [f"Ladder Dragon: {event}", "Причина: " + "; ".join(str(item) for item in reasons)]
    if metadata:
        safe = {str(key): str(value) for key, value in metadata.items()}
        lines.append("Детали: " + json.dumps(safe, ensure_ascii=False, sort_keys=True))
    return send_message("\n".join(lines))


def notify_binance_auth_error(
    *,
    status: int | None,
    code: int | None,
    endpoint: str,
    message: str = "",
    cooldown_sec: float = 1800.0,
) -> bool:
    """Сообщить о неверном ключе/подписи без утечки секрета и спама.

    Binance не возвращает ключ в таких ошибках, но сообщение всё равно
    нормализуется и обрезается. Повтор одной ошибки подавляется на cooldown.
    """
    status_text = str(status if status is not None else "unknown")
    code_text = str(code if code is not None else "unknown")
    safe_endpoint = str(endpoint).split("?", 1)[0][:120]
    safe_message = re.sub(
        r"(?i)(api[-_ ]?key|api[-_ ]?secret|signature|token|password)\s*[:=]?\s*\S+",
        "<redacted>",
        str(message),
    )[:180]
    key = f"{status_text}:{code_text}:{safe_endpoint}"
    state_path = Path(os.getenv("BINANCE_AUTH_ALERT_STATE", str(AUTH_ALERT_STATE)))
    now = time.time()
    try:
        previous = json.loads(state_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, PermissionError, OSError, TypeError, json.JSONDecodeError):
        previous = {}
    try:
        previous_ts = float(previous.get("ts", 0))
    except (TypeError, ValueError):
        previous_ts = 0.0
    if previous.get("key") == key and now - previous_ts < max(0.0, cooldown_sec):
        return False
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = state_path.with_name(f".{state_path.name}.{os.getpid()}.tmp")
        temporary.write_text(json.dumps({"key": key, "ts": now}), encoding="utf-8")
        os.replace(temporary, state_path)
    except OSError:
        # The notification still matters; failure to persist dedup state must
        # not hide an authentication problem.
        pass
    reason = f"Binance auth failed: HTTP {status_text}, code {code_text}"
    if safe_message:
        reason += f" ({safe_message})"
    return notify(
        "binance_auth_failed",
        [reason],
        {"endpoint": safe_endpoint},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a Ladder Dragon Telegram alert")
    parser.add_argument("--event", required=True)
    parser.add_argument("--message", required=True)
    args = parser.parse_args()
    return 0 if send_message(f"Ladder Dragon: {args.event}\n{args.message}") else 1


if __name__ == "__main__":
    raise SystemExit(main())
