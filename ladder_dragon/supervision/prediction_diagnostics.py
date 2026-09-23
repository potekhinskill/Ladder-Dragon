# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: retain safe SQLite stages without changing prediction failures.
"""Bounded diagnostics; no retries, SQL text, paths, or new persistent state."""

import sqlite3


STAGES = frozenset({
    "settle", "strategy_history", "strategy_record", "control_record",
    "experiments", "reanchor_history", "reanchor_record", "reanchor_samples",
    "control_gates", "summary",
})


def prediction_success_status(*, flow_available: bool, orderbook_available: bool) -> dict:
    """Clear previous diagnostic detail without granting execution authority."""
    return {
        "mode": "SHADOW", "horizons_min": [1, 5, 15],
        "can_change_orders": False,
        "trade_flow_available": flow_available,
        "orderbook_available": orderbook_available,
        "last_error": None, "last_error_detail": None,
    }


def prediction_failure_status(error: BaseException, safe_detail: str) -> dict:
    """Publish an already-sanitized failure without changing SHADOW authority."""
    return {
        "mode": "SHADOW", "can_change_orders": False,
        "last_error": type(error).__name__, "last_error_detail": safe_detail,
    }


def prediction_operation(stage, operation, *args, **kwargs):
    """Annotate SQLite failure and re-raise the original exception unchanged."""
    if stage not in STAGES:
        raise ValueError("unknown prediction diagnostic stage")
    try:
        return operation(*args, **kwargs)
    except sqlite3.Error as error:
        error.prediction_stage = stage
        raise


def sqlite_failure_summary(error: sqlite3.Error) -> str:
    """Derive names from SQLite constants, never from exception message text."""
    fields = ["OperationalError" if isinstance(error, sqlite3.OperationalError) else "DatabaseError"]
    stage = getattr(error, "prediction_stage", None)
    fields.append(f"stage={stage if isinstance(stage, str) and stage in STAGES else 'unknown'}")
    code = getattr(error, "sqlite_errorcode", None)
    # Python 3.10 has neither result constants nor error metadata. Report unknown
    # there; never infer a code from translated or provider-controlled text.
    names = {1: "SQLITE_ERROR", 5: "SQLITE_BUSY", 6: "SQLITE_LOCKED",
             8: "SQLITE_READONLY", 9: "SQLITE_INTERRUPT", 10: "SQLITE_IOERR",
             11: "SQLITE_CORRUPT", 13: "SQLITE_FULL", 14: "SQLITE_CANTOPEN",
             19: "SQLITE_CONSTRAINT", 26: "SQLITE_NOTADB"}
    if type(code) is int and 0 <= code <= 65535 and (code & 255) in names:
        fields.extend((f"sqlite_code={code}", f"sqlite_name={names[code & 255]}"))
    else:
        fields.append("sqlite_name=unknown")
    return " ".join(fields)
