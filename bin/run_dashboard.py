#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: start the read-only dashboard service.
"""Run the dashboard on loopback only."""

import os
import sys
from pathlib import Path

import uvicorn


def main() -> None:
    # After moving the CLI into bin/, the project root is one level above.
    # Use an absolute application directory so systemd does not depend on cwd.
    project_dir = Path(__file__).resolve().parents[1]
    app_dir = project_dir / "FastAPI" / "pi-dashboard"
    sys.path.insert(0, str(app_dir))
    from app import app

    port = int(os.getenv("DASHBOARD_PORT", "8081"))
    uvicorn.run(app, host="127.0.0.1", port=port, proxy_headers=True)


if __name__ == "__main__":
    main()
