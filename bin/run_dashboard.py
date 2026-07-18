#!/usr/bin/env python3
# Copyright (c) 2026 IURII Potekhin / Ladder Dragon. All rights reserved.
# Назначение файла и опасные границы логики должны оставаться понятными при сопровождении.
"""Run the dashboard on loopback only."""

import os
import sys
from pathlib import Path

import uvicorn


def main() -> None:
    # После переноса CLI в bin/ корень проекта находится на уровень выше.
    # Указываем абсолютный каталог приложения, чтобы systemd не зависел от cwd.
    project_dir = Path(__file__).resolve().parents[1]
    app_dir = project_dir / "FastAPI" / "pi-dashboard"
    sys.path.insert(0, str(app_dir))
    from app import app  # noqa: PLC0415 — импорт после фиксации пути приложения

    port = int(os.getenv("DASHBOARD_PORT", "8081"))
    uvicorn.run(app, host="127.0.0.1", port=port, proxy_headers=True)


if __name__ == "__main__":
    main()
