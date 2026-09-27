# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: validate bounded SOL trade pages without asserting history completeness.
"""Pure pagination contract; no credentials, storage, or accounting authority."""

import json
from decimal import localcontext

from ladder_dragon.execution.exchange_evidence import checked_trade
from ladder_dragon.execution.order_fill_evidence import amount
from ladder_dragon.execution.time_safety import assess_exchange_clock
from ladder_dragon.strategy.bnb_capture import pairs

SYMBOL = 'SOLUSDT'
CUTOFF_MS = 1789516800000  # 2026-09-16 00:00:00 UTC, exclusive.
PAGE_SIZE = 200
MAX_PAGES = 20
MAX_BODY = 256 * 1024


def decode(raw, limit):
    if type(raw) is not bytes or not 0 < len(raw) <= limit:
        raise ValueError('HISTORY_BODY_INVALID')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))


def interval(packet, previous_end=0):
    start, end, elapsed = (packet[k] for k in ('started_ms', 'finished_ms', 'elapsed_ms'))
    if (any(type(v) is not int for v in (start, end, elapsed))
            or not 0 < start <= end < 2**63 or start < previous_end
            or not 0 <= elapsed <= 5000 or end-start > 5000 or abs(end-start-elapsed) > 2):
        raise ValueError('HISTORY_INTERVAL_INVALID')
    return end


def clock(packet):
    interval(packet)
    value = decode(packet['body'], 1024)
    if (type(value) is not dict or set(value) != {'serverTime'}
            or type(value['serverTime']) is not int or not 0 < value['serverTime'] < 2**63):
        raise ValueError('HISTORY_CLOCK_INVALID')
    check = assess_exchange_clock(server_time_ms=value['serverTime'],
        request_started_ms=packet['started_ms'], response_finished_ms=packet['finished_ms'])
    if not check.safe:
        raise ValueError('HISTORY_CLOCK_INVALID')
    return check.offset_ms


def page(raw, cursor, previous_time, finished_ms):
    """Validate the entire page before allowing any cursor advancement."""
    if type(cursor) is not int or not 0 <= cursor < 2**63:
        raise ValueError('HISTORY_CURSOR_INVALID')
    rows = decode(raw, MAX_BODY)
    if type(rows) is not list or len(rows) > PAGE_SIZE:
        raise ValueError('HISTORY_PAGE_INVALID')
    previous_id = cursor-1
    included = 0
    with localcontext() as context:
        context.prec = 512
        for row in rows:
            checked_trade(row, SYMBOL)
            if (any(not 0 <= row[k] < 2**63 for k in ('id', 'orderId', 'time'))
                    or row['id'] <= previous_id or row['time'] < previous_time
                    or row['time'] > finished_ms
                    or any(type(row.get(k)) is not bool for k in ('isMaker', 'isBestMatch'))):
                raise ValueError('HISTORY_SEQUENCE_INVALID')
            price, quantity, quote, _fee = (amount(row.get(k)) for k in ('price', 'qty', 'quoteQty', 'commission'))
            if price*quantity != quote:
                raise ValueError('HISTORY_QUOTE_INVALID')
            previous_id, previous_time = row['id'], row['time']
            included += row['time'] < CUTOFF_MS
    return dict(next_cursor=previous_id+1, last_time=previous_time, records=len(rows),
                included=included, excluded=len(rows)-included,
                stop=('CUTOFF_OBSERVED' if rows and previous_time >= CUTOFF_MS else
                      'SHORT_PAGE_OBSERVED' if len(rows) < PAGE_SIZE else None))


def validate_capture(pages, clocks):
    """Recheck source bytes and conservative stop reason before persistence or use."""
    if type(pages) is not list or not 1 <= len(pages) <= MAX_PAGES or type(clocks) is not list or len(clocks) != 2:
        raise ValueError('HISTORY_CAPTURE_INVALID')
    clock(clocks[0]); clock(clocks[1])
    previous_end = clocks[0]['finished_ms']
    cursor = previous_time = included = records = 0
    result = None
    fields = {'started_ms', 'finished_ms', 'elapsed_ms', 'body'}
    if any(type(c) is not dict or set(c) != fields for c in clocks):
        raise ValueError('HISTORY_CLOCK_FIELDS_INVALID')
    for packet in pages:
        if (type(packet) is not dict or set(packet) != fields | {'from_id'}
                or type(packet['from_id']) is not int or packet['from_id'] != cursor):
            raise ValueError('HISTORY_PACKET_INVALID')
        if result and result['stop']:
            raise ValueError('HISTORY_AFTER_STOP')
        previous_end = interval(packet, previous_end)
        result = page(packet['body'], cursor, previous_time, previous_end)
        cursor, previous_time = result['next_cursor'], result['last_time']
        included += result['included']; records += result['records']
    interval(clocks[1], previous_end)
    if not result['stop'] and len(pages) != MAX_PAGES:
        raise ValueError('HISTORY_PREMATURE_STOP')
    if (clocks[1]['finished_ms']-clocks[0]['started_ms'] > 150000
            or CUTOFF_MS > clocks[0]['started_ms']):
        raise ValueError('HISTORY_CAPTURE_TIME_INVALID')
    return dict(stop_reason='LIMIT_REACHED' if len(pages) == MAX_PAGES else result['stop'],
                pages=len(pages), records=records, included_records=included,
                excluded_records=records-included, next_cursor=cursor,
                history_complete=False, private_fills_authenticated=False, replay_allowed=False)
