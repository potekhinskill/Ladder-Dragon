# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: derive source-hashed minute bars from verified Binance archives.
"""Strict archive adapter for look-ahead-safe prediction backfill."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path

from ladder_dragon.strategy.prediction import PredictionBar


@dataclass(frozen=True)
class VerifiedPredictionArchive:
    symbol: str
    source_sha256: str
    bars: tuple[PredictionBar, ...]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_verified_prediction_archive(
    path: str | Path,
) -> VerifiedPredictionArchive:
    """Load aggTrades only after companion metadata authenticates the source."""
    archive = Path(path)
    metadata_path = archive.with_suffix(archive.suffix + ".metadata.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict) or int(metadata.get("schema_version", 0)) != 1:
        raise ValueError("prediction archive metadata is invalid")
    symbol = str(metadata.get("symbol", "")).upper()
    if not symbol or not symbol.isalnum():
        raise ValueError("prediction archive symbol is invalid")
    source_hash = _sha256(archive)
    if str(metadata.get("archive_sha256", "")).lower() != source_hash:
        raise ValueError("prediction archive SHA-256 does not match metadata")
    if metadata.get("contains_secrets") is not False:
        raise ValueError("prediction archive secret-safety is not attested")

    minutes: dict[int, list[Decimal]] = {}
    with archive.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"archive line {line_number} is not an object")
            if str(payload.get("e", "")) != "aggTrade":
                continue
            if str(payload.get("s", symbol)).upper() != symbol:
                raise ValueError(f"archive line {line_number} changes symbol")
            try:
                timestamp = int(payload.get("T", payload.get("E")))
                price = Decimal(str(payload["p"]))
                quantity = Decimal(str(payload["q"]))
            except (
                InvalidOperation,
                KeyError,
                TypeError,
                ValueError,
            ) as exc:
                raise ValueError(
                    f"archive line {line_number} has invalid trade values"
                ) from exc
            if timestamp < 0 or not price.is_finite() or price <= 0:
                raise ValueError(f"archive line {line_number} has invalid price")
            if not quantity.is_finite() or quantity <= 0:
                raise ValueError(f"archive line {line_number} has invalid quantity")
            minute = timestamp - timestamp % 60_000
            row = minutes.setdefault(
                minute, [price, price, price, price, Decimal("0")]
            )
            row[1] = max(row[1], price)
            row[2] = min(row[2], price)
            row[3] = price
            row[4] += quantity

    bars = tuple(
        PredictionBar(
            open_time_ms=minute,
            close_time_ms=minute + 59_999,
            open=values[0],
            high=values[1],
            low=values[2],
            close=values[3],
            volume=values[4],
        )
        for minute, values in sorted(minutes.items())
    )
    if not bars:
        raise ValueError("prediction archive contains no aggregate trades")
    return VerifiedPredictionArchive(symbol, source_hash, bars)
