# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify complete signed REST archives before fill-bound valuation.
"""One composed read-only prerequisite; never a selection or execution gate."""

from dataclasses import dataclass
import hashlib

from ladder_dragon.strategy.bnb_capture import URL, trades
from ladder_dragon.strategy.capture_attestation import bounded_json, integer, verify, require_before_fill
from ladder_dragon.strategy.capture_clock import derive_clock
from ladder_dragon.strategy.prediction.commission_evidence import (
    BoundCommission, _pinned_json, settled_bnb_fill,
)
from ladder_dragon.strategy.prediction.causal_commission import value_bnb_commission


@dataclass(frozen=True)
class SignedCommission:
    commission: BoundCommission
    archive_sha256: str
    attestation_sha256: str
    measurement_sha256: str
    price_record_sha256: str
    replay_allowed: bool = False
    private_fills_authenticated: bool = False


def value_signed_capture(*, stream, manifest_bytes, attestation_bytes, signature,
                         measurement_bytes, trusted_public_key, expected_collector_id,
                         clock_policy, aggregate_trade_id, parent, trade_id,
                         fills_bytes, fills_sha256, max_age_ms, maximum_archive_bytes):
    """Consume the entire archive before returning any selected financial value.

    The caller must authenticate private fills separately; durable matching
    alone cannot prove exchange origin of an externally supplied timestamp.
    """
    integer(aggregate_trade_id)
    if not 0 < integer(maximum_archive_bytes) <= 64*1024*1024:
        raise ValueError('SIGNED_CAPTURE_CAPACITY')
    window = verify(manifest_bytes, attestation_bytes, signature,
                    trusted_public_key=trusted_public_key,
                    expected_collector_id=expected_collector_id, **clock_policy)
    clock = derive_clock(measurement_bytes, **clock_policy)
    if bounded_json(attestation_bytes)['clock'] != clock:
        raise ValueError('SIGNED_CAPTURE_CLOCK_BINDING')
    manifest = bounded_json(manifest_bytes)
    selected_fill = settled_bnb_fill(parent=parent, trade_id=trade_id,
                                     fills_bytes=fills_bytes, fills_sha256=fills_sha256)
    fields = {'schema', 'symbol', 'source', 'received_at_ns', 'monotonic_ns',
              'clock_uncertainty_ns', 'clock_verified', 'replay_allowed', 'response_utf8'}
    digest = hashlib.sha256()
    total = count = lines = 0
    selected = previous = last_wall = last_mono = None
    while True:
        raw = stream.readline(min(524289, maximum_archive_bytes-total+1))
        if raw == b'':
            break
        if type(raw) is not bytes or len(raw) > 524288 or not raw.endswith(b'\n'):
            raise ValueError('SIGNED_CAPTURE_LINE')
        total += len(raw)
        lines += 1
        if total > maximum_archive_bytes or lines > 100:
            raise ValueError('SIGNED_CAPTURE_CAPACITY')
        digest.update(raw)
        record_hash = hashlib.sha256(raw).hexdigest()
        r = _pinned_json(raw, record_hash, 524288)
        if (not isinstance(r, dict) or set(r) != fields
                or r['schema'] != 'bnb_rest_observation_v1' or r['symbol'] != 'BNBUSDT'
                or r['source'] != URL or r['clock_uncertainty_ns'] is not None
                or r['clock_verified'] is not False or r['replay_allowed'] is not False
                or not isinstance(r['response_utf8'], str)):
            raise ValueError('SIGNED_CAPTURE_RECORD')
        wall, mono = integer(r['received_at_ns']), integer(r['monotonic_ns'])
        if last_wall is not None and (wall < last_wall or mono < last_mono):
            raise ValueError('SIGNED_CAPTURE_RECEIPT_ORDER')
        lower, _ = window.receipt_interval(wall, mono)
        rows, previous = trades(r['response_utf8'].encode(), previous)
        for row in rows:
            if row['T']*1000000 > lower:
                raise ValueError('SIGNED_CAPTURE_MARKET_TIME')
            count += 1
            if row['a'] == aggregate_trade_id:
                if selected is not None:
                    raise ValueError('SIGNED_CAPTURE_DUPLICATE')
                selected = (row, wall, mono, record_hash)
        last_wall, last_mono = wall, mono
    if (digest.hexdigest() != manifest['archive_sha256'] or total != manifest['bytes']
            or count != manifest['events'] or selected is None):
        raise ValueError('SIGNED_CAPTURE_ARCHIVE_BINDING')
    row, wall, mono, record_hash = selected
    _, upper = require_before_fill(window, wall_ns=wall, mono_ns=mono,
                                   fill_time_ms=selected_fill['time'])
    valuation = value_bnb_commission(symbol=parent.symbol,
        commission_amount=selected_fill['commission'], fill_time_ms=selected_fill['time'],
        max_age_ms=max_age_ms, price_evidence=dict(symbol='BNBUSDT', price=row['p'],
            market_time_ms=row['T'], available_at_ms=(upper+999999)//1000000,
            source_sha256=record_hash))
    bound = BoundCommission(parent.symbol, parent.exchange_order_id, trade_id,
                            selected_fill['time'], fills_sha256, valuation)
    return SignedCommission(bound, digest.hexdigest(), hashlib.sha256(attestation_bytes).hexdigest(),
                            hashlib.sha256(measurement_bytes).hexdigest(), record_hash)
