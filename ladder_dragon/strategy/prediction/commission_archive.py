# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: bind commission price records to complete pinned public archives.
"""Bounded read-only membership check; neither venue authentication nor depth replay."""

from dataclasses import dataclass
import hashlib

from ladder_dragon.execution.trade_accounting import symbol_assets
from ladder_dragon.strategy.prediction.commission_evidence import (
    BoundCommission, _pinned_json, value_settled_bnb_fill,
)


@dataclass(frozen=True)
class ArchivePrice:
    record: bytes
    archive_sha256: str
    manifest_sha256: str
    line_number: int


def extract_price_record(stream, *, manifest_bytes, manifest_sha256, symbol,
                         aggregate_trade_id, maximum_archive_bytes):
    """Consume a caller-owned binary stream once; never reopen or close it."""
    if (type(aggregate_trade_id) is not int or aggregate_trade_id < 0
            or type(maximum_archive_bytes) is not int or maximum_archive_bytes <= 0):
        raise ValueError("invalid archive selection or byte limit")
    manifest = _pinned_json(manifest_bytes, manifest_sha256, 16384)
    counters = ("event_count", "depth_event_count", "trade_event_count")
    if (not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int
            or manifest["schema_version"] != 1 or manifest.get("symbol") != symbol
            or manifest.get("contains_secrets") is not False
            or any(type(manifest.get(k)) is not int or manifest[k] <= 0 for k in counters)
            or manifest["event_count"] != 1 + manifest["depth_event_count"] + manifest["trade_event_count"]):
        raise ValueError("archive manifest contract differs")
    digest = hashlib.sha256()
    total = count = depth_count = trade_count = 0
    selected = None
    # Size and line ceilings bound memory even when the manifest lies.
    while True:
        raw = stream.readline(min(1048577, maximum_archive_bytes - total + 1))
        if raw == b"":
            break
        if type(raw) is not bytes:
            raise ValueError("archive requires a binary stream")
        total += len(raw)
        count += 1
        if total > maximum_archive_bytes or len(raw) > 1048576 or count > manifest["event_count"]:
            raise ValueError("archive capacity or event count exceeded")
        digest.update(raw)
        row = _pinned_json(raw, hashlib.sha256(raw).hexdigest(), 1048576)
        if not isinstance(row, dict) or row.get("s") != symbol:
            raise ValueError("archive row market differs")
        if count == 1:
            if "lastUpdateId" not in row or row.get("_source") != "binance-public-rest-depth":
                raise ValueError("archive initial snapshot is missing")
        elif row.get("e") == "depthUpdate":
            depth_count += 1
        elif row.get("e") == "aggTrade":
            trade_count += 1
            if type(row.get("a")) is not int or row["a"] < 0:
                raise ValueError("archive trade identity is invalid")
            if row["a"] == aggregate_trade_id:
                if selected is not None or len(raw) > 16384:
                    raise ValueError("archive selected trade is ambiguous or oversized")
                selected = (raw, count)
        else:
            raise ValueError("archive event type is unsupported")
    if (digest.hexdigest() != manifest.get("archive_sha256")
            or (count, depth_count, trade_count) != tuple(manifest[k] for k in counters)):
        raise ValueError("archive digest or counts differ from manifest")
    if selected is None:
        raise ValueError("archive selected trade is missing")
    return ArchivePrice(selected[0], digest.hexdigest(), manifest_sha256, selected[1])


@dataclass(frozen=True)
class ArchivedCommission:
    commission: BoundCommission
    archive_sha256: str
    manifest_sha256: str
    price_line_number: int


def value_archived_bnb_fill(*, stream, manifest_bytes, manifest_sha256,
                           aggregate_trade_id, maximum_archive_bytes, parent,
                           trade_id, fills_bytes, fills_sha256, max_age_ms):
    """Keep complete archive membership beside the existing fill-bound result."""
    _, quote = symbol_assets(parent.symbol)
    price = extract_price_record(
        stream, manifest_bytes=manifest_bytes, manifest_sha256=manifest_sha256,
        symbol="BNB" + quote, aggregate_trade_id=aggregate_trade_id,
        maximum_archive_bytes=maximum_archive_bytes,
    )
    commission = value_settled_bnb_fill(
        parent=parent, trade_id=trade_id, fills_bytes=fills_bytes, fills_sha256=fills_sha256,
        price_event_bytes=price.record, price_event_sha256=hashlib.sha256(price.record).hexdigest(),
        max_age_ms=max_age_ms,
    )
    return ArchivedCommission(commission, price.archive_sha256, price.manifest_sha256, price.line_number)
