# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: own a Testnet soak boundary without changing monitoring behavior.
"""Testnet soak_reports implementation."""

from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any

from ladder_dragon.verification.live.soak_policy import SoakSample


def _atomic_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def _json_sample(sample: SoakSample) -> dict[str, Any]:
    payload = asdict(sample)
    for key, value in list(payload.items()):
        if isinstance(value, Decimal):
            payload[key] = format(value, "f")
    return payload


def _finish_report(args, status, symbol, started, samples, max_seen_exposure,
                   max_seen_buys, read_failures, max_consecutive_read_failures,
                   last_source_error, reasons, last_sample):
    report = {
        "status": status,
        "symbol": symbol,
        "duration_sec": round(time.monotonic() - started, 3),
        "samples": samples,
        "max_seen_exposure_usdt": format(max_seen_exposure, "f"),
        "max_seen_open_buys": max_seen_buys,
        "read_failures": read_failures,
        "max_consecutive_read_failures": max_consecutive_read_failures,
        "last_source_error": last_source_error,
        "reasons": reasons,
        "last_sample": _json_sample(last_sample) if last_sample else None,
    }
    _atomic_report(Path(args.report), report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 1 if status in {"violation", "source_unavailable"} else 0
