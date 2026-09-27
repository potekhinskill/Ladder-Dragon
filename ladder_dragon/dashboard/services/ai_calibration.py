# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve dashboard AI reporting with explicit service ownership.

from typing import Dict, List


def calibration(recent: List[Dict]) -> List[Dict]:
    result = []
    for low, high in ((0, .65), (.65, .70), (.70, .80), (.80, 1.01)):
        rows = [
            row for row in recent
            if low <= float(row.get("confidence") or 0) < high
            and row.get("return_1h") is not None
        ]
        success = 0
        for row in rows:
            ret = float(row["return_1h"])
            mode = row.get("recommended_mode")
            success += int(
                (mode == "UP" and ret > .001)
                or (mode == "DOWN" and ret < -.001)
                or (mode == "FLAT" and abs(ret) <= .001)
            )
        result.append({
            "bucket": f"{low:.2f}-{min(high, 1):.2f}",
            "samples": len(rows),
            "accuracy": success / len(rows) if rows else 0,
        })
    return result
