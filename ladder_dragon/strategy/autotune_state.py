# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own a VWAP autotune boundary with unchanged tuning behavior.
"""VWAP autotune_state implementation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional


def load_prev_values(path: Optional[str]) -> Dict[str, Dict[str, object]]:
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    return {}


def save_values(path: Optional[str], values: Dict[str, Dict[str, object]]) -> None:
    if not path:
        return
    tmp = Path(path + ".tmp")
    dst = Path(path)
    try:
        tmp.write_text(json.dumps(values, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(dst)
    except (OSError, TypeError, ValueError):
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
