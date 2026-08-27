# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve and verify continuous public depth segment boundaries.
"""Bounded book reconstruction and immutable, hash-linked public segments."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
from typing import Iterable, Iterator

from ladder_dragon.strategy.market_replay import BookLevel, MarketEvent, archive_sha256

MAX_FRAME_BYTES = 2 * 1024 * 1024
MAX_BOOK_LEVELS = 20_000
MAX_SEGMENTS = 10_000


def bounded_json(path: Path) -> dict:
    with path.open("rb") as handle:
        raw = handle.read(MAX_FRAME_BYTES + 1)
    if len(raw) > MAX_FRAME_BYTES:
        raise ValueError("public metadata exceeds byte limit")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("public metadata must be an object")
    return value


def atomic_json(path: Path, value: dict, *, replace: bool = False) -> None:
    """Publish a complete report; immutable evidence must never be overwritten."""
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write((json.dumps(value, sort_keys=True) + "\n").encode())
            handle.flush()
            os.fsync(handle.fileno())
        if replace:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class PublicBook:
    """Keep bounded Decimal levels and reject missing depth or trade sequences."""

    def __init__(self) -> None:
        self.bids: dict[Decimal, Decimal] = {}
        self.asks: dict[Decimal, Decimal] = {}
        self.update_id: int | None = None
        self.trade_id: int | None = None
        self.received_ms = 0
        self.bid_floor: Decimal | None = None
        self.ask_ceiling: Decimal | None = None

    @staticmethod
    def _update(side: dict, rows: list, *, floor=None, ceiling=None) -> None:
        if not isinstance(rows, list) or len(rows) > MAX_BOOK_LEVELS:
            raise ValueError("invalid public book levels")
        for price, quantity in rows:
            p, q = Decimal(str(price)), Decimal(str(quantity))
            if not p.is_finite() or not q.is_finite() or p <= 0 or q < 0:
                raise ValueError("invalid public book number")
            # A finite REST snapshot does not prove absent levels outside its
            # original range. Never widen that range from isolated diffs.
            if floor is not None and p < floor or ceiling is not None and p > ceiling:
                continue
            if q:
                side[p] = q
            else:
                side.pop(p, None)
        if len(side) > MAX_BOOK_LEVELS:
            raise ValueError("public book capacity reached")

    def apply(self, row: dict, *, level_limit: int = 100) -> MarketEvent:
        received = int(row["_received_at_ms"])
        if received < self.received_ms or received <= 0:
            raise ValueError("public receive clock moved backwards")
        trades = ()
        kind = row.get("e", "depthSnapshot")
        if "lastUpdateId" in row:
            self.bids.clear()
            self.asks.clear()
            self._update(self.bids, row["bids"])
            self._update(self.asks, row["asks"])
            if not self.bids or not self.asks:
                raise ValueError("public snapshot has an empty side")
            self.bid_floor = Decimal(str(row.get("known_bid_floor", min(self.bids))))
            self.ask_ceiling = Decimal(str(row.get("known_ask_ceiling", max(self.asks))))
            if (not self.bid_floor.is_finite() or not self.ask_ceiling.is_finite()
                    or not 0 < self.bid_floor <= min(self.bids)
                    or self.ask_ceiling < max(self.asks)):
                raise ValueError("invalid known public book range")
            self.update_id = int(row["lastUpdateId"])
        elif kind == "depthUpdate":
            if self.update_id is None or not (
                int(row["U"]) <= self.update_id + 1 <= int(row["u"])
            ) or ("pu" in row and int(row["pu"]) != self.update_id):
                raise ValueError("public depth sequence gap")
            self._update(self.bids, row["b"], floor=self.bid_floor)
            self._update(self.asks, row["a"], ceiling=self.ask_ceiling)
            self.update_id = int(row["u"])
        elif kind == "aggTrade":
            identifier = int(row["a"])
            if self.trade_id is not None and identifier != self.trade_id + 1:
                raise ValueError("public aggregate trade sequence gap")
            self.trade_id = identifier
            price, qty = Decimal(str(row["p"])), Decimal(str(row["q"]))
            if not price.is_finite() or not qty.is_finite() or min(price, qty) <= 0:
                raise ValueError("invalid aggregate trade number")
            if type(row["m"]) is not bool:
                raise ValueError("invalid public aggressor flag")
            trades = ((price, qty, "SELL" if row["m"] else "BUY"),)
        else:
            raise ValueError("unsupported public event")
        if not self.bids or not self.asks or max(self.bids) >= min(self.asks):
            raise ValueError("public book is empty or crossed")
        self.received_ms = received
        return MarketEvent(
            received,
            tuple(BookLevel(p, q) for p, q in sorted(self.bids.items(), reverse=True)[:level_limit]),
            tuple(BookLevel(p, q) for p, q in sorted(self.asks.items())[:level_limit]),
            trades=trades, event_type=kind, received_ts_ms=received,
        )

    def snapshot(self, symbol: str) -> dict:
        return {
            "s": symbol, "E": self.received_ms,
            "_received_at_ms": self.received_ms,
            "_source": "carried-public-book",
            "lastUpdateId": self.update_id,
            "known_bid_floor": str(self.bid_floor),
            "known_ask_ceiling": str(self.ask_ceiling),
            "bids": [[str(p), str(q)] for p, q in sorted(self.bids.items(), reverse=True)],
            "asks": [[str(p), str(q)] for p, q in sorted(self.asks.items())],
        }


class SegmentWriter:
    """Publish bounded authoritative evidence without deleting older records."""

    def __init__(self, directory: Path, symbol: str, session_id: str, index: int,
                 previous: dict | None, book: PublicBook, capacity_bytes: int) -> None:
        if not 0 <= index < MAX_SEGMENTS:
            raise ValueError("segment count capacity reached")
        self.target = directory / f"{symbol}-{session_id}-{index:06d}.jsonl"
        self.temporary = self.target.with_name(f".{self.target.name}.tmp")
        self.handle = self.temporary.open("xb")
        self.digest = hashlib.sha256()
        self.count = self.depth_count = self.trade_count = self.size = 0
        self.capacity_bytes = capacity_bytes
        self.metadata = {
            "schema_version": 2, "symbol": symbol, "session_id": session_id,
            "segment_index": index,
            "previous_archive_sha256": previous["archive_sha256"] if previous else None,
            "started_at_ms": book.received_ms,
            "first_snapshot_update_id": book.update_id,
            "first_trade_id": book.trade_id,
            "contains_secrets": False,
        }
        self.emit(book.snapshot(symbol))

    def emit(self, row: dict) -> None:
        raw = (json.dumps(row, separators=(",", ":")) + "\n").encode()
        if len(raw) > MAX_FRAME_BYTES or self.size + len(raw) > self.capacity_bytes:
            raise ValueError("public archive byte capacity reached")
        self.handle.write(raw)
        self.digest.update(raw)
        self.size += len(raw)
        self.count += 1
        self.depth_count += row.get("e") == "depthUpdate"
        self.trade_count += row.get("e") == "aggTrade"

    def finish(self, book: PublicBook, reason: str) -> dict:
        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.handle.close()
        metadata = dict(self.metadata, finished_at_ms=book.received_ms,
                        last_update_id=book.update_id, last_trade_id=book.trade_id,
                        event_count=self.count, depth_event_count=self.depth_count,
                        trade_event_count=self.trade_count, end_reason=reason,
                        archive_sha256=self.digest.hexdigest())
        # The sidecar is the commit marker. Readers ignore unfinished files.
        os.link(self.temporary, self.target)
        self.temporary.unlink()
        atomic_json(self.target.with_suffix(".jsonl.metadata.json"), metadata)
        return metadata


def verified_segments(paths: Iterable[Path]) -> list[tuple[Path, dict]]:
    """Validate a complete chain before exposing any replay opportunity."""
    output: list[tuple[Path, dict]] = []
    for path in paths:
        if len(output) >= MAX_SEGMENTS:
            raise ValueError("too many public segments")
        metadata = bounded_json(path.with_suffix(".jsonl.metadata.json"))
        if metadata.get("schema_version") not in {1, 2}:
            raise ValueError("unsupported public segment schema")
        if metadata.get("contains_secrets") is not False:
            raise ValueError("archive is not public evidence")
        if archive_sha256(path) != metadata.get("archive_sha256"):
            raise ValueError("public archive hash mismatch")
        if output:
            old = output[-1][1]
            if not (
                metadata.get("schema_version") == old.get("schema_version") == 2
                and metadata.get("session_id") == old.get("session_id")
                and metadata.get("symbol") == old.get("symbol")
                and metadata.get("segment_index") == old.get("segment_index") + 1
                and metadata.get("previous_archive_sha256") == old.get("archive_sha256")
                and metadata.get("first_snapshot_update_id") == old.get("last_update_id")
                and metadata.get("first_trade_id") == old.get("last_trade_id")
                and metadata.get("started_at_ms") == old.get("finished_at_ms")
            ):
                raise ValueError("unproven public segment boundary")
        output.append((path, metadata))
    if not output:
        raise ValueError("no public segments supplied")
    return output


def iter_segment_events(segments: list[tuple[Path, dict]], *,
                        exchange_clock: bool = False, level_limit: int = 100) -> Iterator[MarketEvent]:
    """Stream exact receive order; never sort future events into the past."""
    book = PublicBook()
    if not 1 <= level_limit <= MAX_BOOK_LEVELS:
        raise ValueError("invalid historical book depth")
    for number, (path, metadata) in enumerate(segments):
        digest = hashlib.sha256()
        count = 0
        with path.open("rb") as handle:
            while raw := handle.readline(MAX_FRAME_BYTES + 1):
                if len(raw) > MAX_FRAME_BYTES:
                    raise ValueError("archive frame exceeds byte limit")
                digest.update(raw)
                row = json.loads(raw)
                if not isinstance(row, dict) or row.get("s") != metadata["symbol"]:
                    raise ValueError("archive symbol mismatch")
                if count == 0:
                    if row.get("lastUpdateId") != metadata["first_snapshot_update_id"]:
                        raise ValueError("archive seed mismatch")
                    if number:
                        if row != book.snapshot(metadata["symbol"]):
                            raise ValueError("carried book differs at rotation")
                        count += 1
                        continue
                    book.trade_id = metadata.get("first_trade_id")
                elif "lastUpdateId" in row:
                    raise ValueError("unexpected snapshot inside public segment")
                event = book.apply(row, level_limit=level_limit)
                count += 1
                yield replace(event, ts_ms=int(row["E"])) if exchange_clock else event
        if (digest.hexdigest() != metadata["archive_sha256"]
                or count != metadata["event_count"]
                or book.update_id != metadata["last_update_id"]):
            raise ValueError("public segment changed during replay")
        if metadata.get("schema_version") == 2 and (
            book.trade_id != metadata["last_trade_id"]
            or book.received_ms != metadata["finished_at_ms"]
        ):
            raise ValueError("public segment terminal state mismatch")
