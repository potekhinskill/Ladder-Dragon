# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: bind successful single-order responses to their submitted intent.
"""A malformed acknowledgement is uncertainty, never permission to resubmit."""

from ladder_dragon.execution.exchange_evidence import checked_order, exact_nonnegative
from ladder_dragon.execution.orders.reconciliation import UncertainOrderSubmission


def checked_submission(dependencies, journal, params, payload):
    """Validate RESULT evidence before any acceptance writer; never resubmit."""
    try:
        checked_order(payload, params["symbol"], client_id=params["newClientOrderId"], list_id=-1)
        if payload.get("side") != params["side"] or payload.get("type") != params["type"]:
            raise ValueError("submission direction or type mismatch")
        original = exact_nonnegative(payload.get("origQty"))
        executed = exact_nonnegative(payload.get("executedQty"))
        if original != exact_nonnegative(params["quantity"]) or executed > original:
            raise ValueError("submission quantity mismatch")
        status = payload.get("status")
        if (status not in {"NEW", "PARTIALLY_FILLED", "FILLED", "CANCELED", "EXPIRED", "EXPIRED_IN_MATCH", "REJECTED"}
                or (status == "NEW" and executed != 0)
                or (status == "FILLED" and executed != original)
                or (status == "PARTIALLY_FILLED" and not 0 < executed < original)):
            raise ValueError("submission status mismatch")
        if "price" in params and exact_nonnegative(payload.get("price")) != exact_nonnegative(params["price"]):
            raise ValueError("submission price mismatch")
    except (RuntimeError, ValueError, TypeError):
        if journal is not None:
            journal.mark_unknown(params["newClientOrderId"], "invalid submission evidence")
        dependencies.halt("invalid submission evidence", symbol=params["symbol"],
                          client_order_id=params["newClientOrderId"])
        raise UncertainOrderSubmission("invalid submission evidence") from None
    return payload
