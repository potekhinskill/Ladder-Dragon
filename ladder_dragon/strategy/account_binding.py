# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: check supplied account claims without network or admission authority.
"""Pure structural validation; callers must independently establish provenance.

Matching caller-supplied identities does not authenticate their source, prove
freshness, or qualify historical fills. No credentials or storage are accessed.
"""

from decimal import Decimal, InvalidOperation
import json
import re


MAX_ACCOUNT_BYTES = 1024 * 1024
MAX_PERMISSION_BYTES = 16 * 1024
MUTATION_FIELDS = frozenset({
    "enableWithdrawals", "enableInternalTransfer", "enableMargin",
    "enableFutures", "permitsUniversalTransfer", "enableVanillaOptions",
    "enableFixApiTrade", "enableSpotAndMarginTrading",
    "enablePortfolioMarginTrading",
})
BOOLEAN_FIELDS = MUTATION_FIELDS | {
    "enableReading", "enableFixReadOnly", "ipRestrict",
}


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _constant(_value):
    raise ValueError


def _object(raw, maximum):
    if type(raw) is not bytes or not 0 < len(raw) <= maximum:
        raise ValueError
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                       parse_float=Decimal, parse_constant=_constant)
    if type(value) is not dict:
        raise ValueError
    return value


def _identifier(value):
    return type(value) is int and 0 < value < 2**63


def _scope(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _result(reason):
    # Never return identity, scope, balances, provider text, or implied authority.
    return {
        "status": "CLAIMS_MATCH_ONLY" if reason == "MATCH" else "BLOCKED",
        "reason": reason,
        "account_authenticated": False,
        "private_fills_authenticated": False,
        "replay_allowed": False,
    }


def validate_account_claims(*, expected_uid, expected_scope, account_scope,
                            permission_scope, account_body, permission_body):
    """Compare bounded supplied claims, never attest actual API retrieval.

    The strict permission profile rejects absent and new fields for review.
    Account-level trading flags do not describe the selected key's permissions.
    Transport deadlines, HTTP status, clock and enrollment trust are external.
    """
    if not _identifier(expected_uid) or not all(
        _scope(value) for value in (expected_scope, account_scope, permission_scope)
    ):
        return _result("BINDING_INVALID")
    if expected_scope != account_scope or expected_scope != permission_scope:
        return _result("CREDENTIAL_SCOPE_MISMATCH")
    try:
        account = _object(account_body, MAX_ACCOUNT_BYTES)
    except (ValueError, TypeError, RecursionError, OverflowError, InvalidOperation):
        return _result("ACCOUNT_BODY_INVALID")
    if "code" in account or not _identifier(account.get("uid")):
        return _result("ACCOUNT_IDENTITY_INVALID")
    if account["uid"] != expected_uid:
        return _result("ACCOUNT_IDENTITY_MISMATCH")
    try:
        permission = _object(permission_body, MAX_PERMISSION_BYTES)
    except (ValueError, TypeError, RecursionError, OverflowError, InvalidOperation):
        return _result("PERMISSION_BODY_INVALID")
    if (set(permission) != BOOLEAN_FIELDS | {"createTime"}
            or not _identifier(permission.get("createTime"))
            or any(type(permission[key]) is not bool for key in BOOLEAN_FIELDS)):
        return _result("PERMISSION_SCHEMA_INVALID")
    if not permission["enableReading"]:
        return _result("READ_PERMISSION_REQUIRED")
    if any(permission[key] for key in MUTATION_FIELDS):
        return _result("MUTATION_PERMISSION_ENABLED")
    return _result("MATCH")
