#!/usr/bin/env python3
"""Run the dashboard on loopback only."""

import os
from pathlib import Path

import uvicorn


def main() -> None:
    app_dir = Path(__file__).resolve().parent / "FastAPI" / "pi-dashboard"
    port = int(os.getenv("DASHBOARD_PORT", "8081"))
    uvicorn.run("app:app", app_dir=str(app_dir), host="127.0.0.1", port=port, proxy_headers=True)


if __name__ == "__main__":
    main()
