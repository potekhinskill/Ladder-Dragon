#!/usr/bin/env python3
# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Назначение файла и опасные границы логики должны оставаться понятными при сопровождении.
"""Экспорт защищённых журналов mybot для read-only nginx-каталога."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


OUTPUT_DIR = Path(os.getenv("BOT_LOG_EXPORT_DIR", "/var/lib/ladder-dragon/logs"))
RETENTION_DAYS = max(1, int(os.getenv("BOT_LOG_RETENTION_DAYS", "7")))
MAX_BYTES = max(64 * 1024, int(os.getenv("BOT_LOG_MAX_BYTES", "5242880")))
CURRENT_LINES = max(100, int(os.getenv("BOT_LOG_CURRENT_LINES", "3000")))

SENSITIVE_NAMES = (
    "authorization|x-mbx-apikey|api[_-]?key|api[_-]?secret|secret|password|"
    "token|cookie|set-cookie|webhook(?:_url)?|private[_-]?key|access[_-]?key"
)
REDACTIONS = (
    (
        re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/=-]+"),
        r"\1<redacted>",
    ),
    (
        # JSON-ключи с quoted value: "apiKey":"value".
        re.compile(
            rf"(?ix)(?P<prefix>[\"'](?:{SENSITIVE_NAMES})[\"']\s*:\s*)"
            rf"(?P<quote>[\"'])(?P<value>[^\"']*)(?P=quote)"
        ),
        r"\g<prefix>\g<quote><redacted>\g<quote>",
    ),
    (
        # Text key=value, HTTP headers и неquoted JSON values.
        re.compile(
            rf"(?ix)(?P<prefix>\b(?:{SENSITIVE_NAMES})\b\s*[:=]\s*)"
            r"(?P<value>[^\s,;\"'}]+)"
        ),
        r"\g<prefix><redacted>",
    ),
    (
        re.compile(
            r"(?i)([?&](?:signature|api[_-]?key|token|secret|password|"
            r"timestamp|recvWindow)=)[^&\s]+"
        ),
        r"\1<redacted>",
    ),
    (
        re.compile(r"(?i)(https?://[^/\s:@]+:)[^@\s/]+@"),
        r"\1<redacted>@",
    ),
    (
        re.compile(
            r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?"
            r"-----END [A-Z0-9 ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "<redacted-private-key>",
    ),
)


def sanitize(text: str) -> tuple[str, int]:
    """Удалить credential-like значения, сохранив диагностическую структуру."""
    replacements = 0
    for pattern, replacement in REDACTIONS:
        text, count = pattern.subn(replacement, text)
        replacements += count
    return text, replacements


def journal(*args: str) -> str:
    """Прочитать systemd journal без shell и вернуть текст даже при пустом логе."""
    result = subprocess.run(
        ["journalctl", "-u", "mybot", "--no-pager", "-o", "short-iso", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.strip() or "journalctl failed")
    return result.stdout


def tail_bytes(text: str) -> str:
    """Оставить последние полные строки в пределах лимита файла."""
    data = text.encode("utf-8", errors="replace")
    if len(data) <= MAX_BYTES:
        return text
    data = data[-MAX_BYTES:]
    newline = data.find(b"\n")
    if newline >= 0:
        data = data[newline + 1 :]
    return data.decode("utf-8", errors="replace")


def atomic_write(path: Path, text: str, mode: int = 0o640) -> None:
    """Не показывать nginx частично записанный файл."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def cleanup(now: datetime) -> None:
    """Удалить только управляемые дневные журналы старше TTL."""
    cutoff = (now - timedelta(days=RETENTION_DAYS)).date()
    for path in OUTPUT_DIR.glob("mybot-????-??-??.log"):
        try:
            stamp = datetime.strptime(path.stem.removeprefix("mybot-"), "%Y-%m-%d")
        except ValueError:
            continue
        if stamp.date() < cutoff:
            path.unlink(missing_ok=True)


def main() -> None:
    now = datetime.now(timezone.utc)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(OUTPUT_DIR, 0o750)

    current_raw = journal("-n", str(CURRENT_LINES))
    current, current_redactions = sanitize(current_raw)
    current = tail_bytes(current)
    atomic_write(OUTPUT_DIR / "current.log", current)

    day = now.strftime("%Y-%m-%d")
    daily_raw = journal("--since", f"{day} 00:00:00 UTC")
    daily, daily_redactions = sanitize(daily_raw)
    daily = tail_bytes(daily)
    atomic_write(OUTPUT_DIR / f"mybot-{day}.log", daily)

    status = {
        "generated_at": now.isoformat(),
        "retention_days": RETENTION_DAYS,
        "max_bytes_per_file": MAX_BYTES,
        "current_lines": len(current.splitlines()),
        "daily_lines": len(daily.splitlines()),
        "redactions": current_redactions + daily_redactions,
    }
    atomic_write(
        OUTPUT_DIR / "status.json",
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
    )
    atomic_write(
        OUTPUT_DIR / "README.txt",
        (
            "Sanitized Ladder Dragon logs.\n"
            "current.log: latest journal lines.\n"
            "mybot-YYYY-MM-DD.log: daily UTC log, size-limited.\n"
            f"Retention: {RETENTION_DAYS} days. Secrets are redacted.\n"
        ),
    )
    cleanup(now)


if __name__ == "__main__":
    main()
