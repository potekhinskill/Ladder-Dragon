# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: record bounded public BNB observations without replay admission.
"""Bounded public REST observations; never authenticated replay evidence."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time

from ladder_dragon.execution.market_http_body import read_body
from ladder_dragon.strategy.capture_storage import check_slots, prepare_slot
from ladder_dragon.strategy.capture_diagnostics import CaptureDiagnostics
from ladder_dragon.strategy.capture_transport import capture_session

URL = "https://data-api.binance.vision/api/v3/aggTrades"
BODY_LIMIT = 65536
STORE_LIMIT = 64 * 1024 * 1024
RESERVE = 16 * 1024 * 1024


def external_store(root):
    """Require an existing dedicated mounted directory, never root storage."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir() or not os.path.ismount(root):
        raise ValueError("CAPTURE_EXTERNAL_MOUNT_REQUIRED")
    if root.stat().st_dev == Path('/').stat().st_dev:
        raise ValueError("CAPTURE_ROOT_DEVICE_FORBIDDEN")
    if shutil.disk_usage(root).free < STORE_LIMIT + RESERVE:
        raise ValueError("CAPTURE_DISK_RESERVE")
    return root.resolve()


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("CAPTURE_DUPLICATE_KEY")
        result[key] = value
    return result


def trades(raw, previous):
    """Reject gaps and malformed fields; REST does not attest event receipt."""
    if not isinstance(raw, bytes) or len(raw) > BODY_LIMIT:
        raise ValueError("CAPTURE_BODY_LIMIT")
    rows = json.loads(raw, object_pairs_hook=pairs)
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError("CAPTURE_ROWS_INVALID")
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'a', 'p', 'q', 'f', 'l', 'T', 'm', 'M'}:
            raise ValueError("CAPTURE_ROW_INVALID")
        for key in ('a', 'f', 'l', 'T'):
            if type(row[key]) is not int or not 0 <= row[key] < 2**63:
                raise ValueError("CAPTURE_ID_INVALID")
        if row['T'] <= 0 or row['f'] > row['l']:
            raise ValueError("CAPTURE_TIME_OR_RANGE_INVALID")
        for key in ('p', 'q'):
            value = row[key]
            if (not isinstance(value, str) or len(value) > 64
                    or re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', value) is None
                    or not any(c in '123456789' for c in value)):
                raise ValueError("CAPTURE_DECIMAL_INVALID")
        if type(row['m']) is not bool or type(row['M']) is not bool:
            raise ValueError("CAPTURE_BOOLEAN_INVALID")
        if previous is not None and (row['a'] != previous['a'] + 1 or row['T'] < previous['T']):
            raise ValueError("CAPTURE_SEQUENCE_GAP")
        previous = row
    return rows, previous


def collect(root, *, requests_limit=10, duration_sec=30, session_factory=None,
            wall=time.time_ns, mono=time.monotonic_ns, pause=time.sleep, attestor=None, slot='original',
            diagnostics=None):
    """One exclusive bounded run; interrupted files remain diagnostic."""
    diagnostics = diagnostics if diagnostics is not None else CaptureDiagnostics()
    diagnostics.mark('limits')
    if (type(requests_limit) is not int or not 1 <= requests_limit <= 100
            or type(duration_sec) is not int or not 1 <= duration_sec <= 300):
        raise ValueError("CAPTURE_LIMIT_INVALID")
    if attestor is not None and requests_limit < 3:
        raise ValueError('CAPTURE_CLOCK_REQUEST_BUDGET')
    diagnostics.mark('storage')
    mount = external_store(root)
    device = mount.stat().st_dev
    # Fixed exclusive slots preserve earlier observations and bound repeated runs.
    diagnostics.mark('slot')
    target = prepare_slot(mount, slot)
    start = mono()
    capture_deadline = time.monotonic() + duration_sec
    previous = None
    last_wall, last_mono = wall(), start
    count = total = 0
    digest = hashlib.sha256()
    diagnostics.mark('session')
    factory = session_factory if session_factory is not None else lambda: capture_session(diagnostics)
    with factory() as session, (target / 'observations.jsonl').open('xb') as output:
        session.trust_env = False
        session.auth = None
        session.headers.clear()
        session.cookies.clear()
        if attestor is not None:
            diagnostics.mark('clock_request')
            attestor.start(session, wall, mono, capture_deadline)
        trade_requests = requests_limit - (2 if attestor is not None else 0)
        for attempt in range(trade_requests):
            elapsed = mono() - start
            if elapsed >= duration_sec * 1_000_000_000:
                break
            diagnostics.mark('storage')
            if external_store(root).stat().st_dev != device:
                raise ValueError("CAPTURE_DEVICE_CHANGED")
            check_slots(mount)
            params = {'symbol': 'BNBUSDT', 'limit': 100}
            if previous is not None:
                params['fromId'] = previous['a'] + 1
            budget = min(5, duration_sec - elapsed / 1_000_000_000,
                         capture_deadline - time.monotonic())
            if budget <= 0:
                raise ValueError('CAPTURE_DEADLINE')
            session.cookies.clear()
            request_deadline = time.monotonic() + budget
            diagnostics.mark('market_request')
            with session.get(URL, params=params, stream=True, allow_redirects=False, timeout=budget) as response:
                if response.status_code != 200:
                    raise ValueError("CAPTURE_HTTP_STATUS")
                diagnostics.mark('market_body')
                raw = read_body(response, deadline=request_deadline, max_bytes=BODY_LIMIT)
                received, monotonic = wall(), mono()
            diagnostics.mark('market_validate')
            if monotonic - start >= duration_sec * 1_000_000_000:
                raise ValueError("CAPTURE_DEADLINE")
            if (received < last_wall or monotonic < last_mono
                    or abs((received-last_wall) - (monotonic-last_mono)) > 100_000_000):
                raise ValueError("CAPTURE_CLOCK_JUMP")
            rows, previous = trades(raw, previous)
            if attestor is not None:
                diagnostics.mark('receipt_validate')
                attestor.observe(received, monotonic)
            diagnostics.mark('market_validate')
            if any(row['T'] * 1_000_000 > received for row in rows):
                raise ValueError("CAPTURE_FUTURE_TRADE")
            record = {'schema': 'bnb_rest_observation_v1', 'symbol': 'BNBUSDT',
                      'source': URL, 'received_at_ns': received, 'monotonic_ns': monotonic,
                      'clock_uncertainty_ns': None, 'clock_verified': False,
                      'replay_allowed': False, 'response_utf8': raw.decode('utf-8')}
            encoded = (json.dumps(record, separators=(',', ':')) + '\n').encode()
            if total + len(encoded) > STORE_LIMIT - 65536:
                raise ValueError("CAPTURE_STORE_LIMIT")
            diagnostics.mark('observation_write')
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
            digest.update(encoded)
            total += len(encoded)
            count += len(rows)
            last_wall, last_mono = received, monotonic
            if attempt + 1 < trade_requests:
                diagnostics.mark('pause')
                pause(min(1, max(0, duration_sec - (mono()-start)/1_000_000_000)))
        diagnostics.mark('session_close')
    diagnostics.mark('final_storage')
    if count == 0:
        raise ValueError("CAPTURE_NO_TRADES")
    if external_store(root).stat().st_dev != device:
        raise ValueError("CAPTURE_DEVICE_CHANGED")
    check_slots(mount)
    manifest = {'schema': 'bnb_rest_capture_v1', 'status': 'DIAGNOSTIC_ONLY',
                'symbol': 'BNBUSDT', 'events': count, 'bytes': total,
                'archive_sha256': digest.hexdigest(), 'replay_allowed': False,
                'source_authenticated': False, 'clock_verified': False,
                'signature': None}
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode()
    diagnostics.mark('manifest_write')
    with (target / 'manifest.json').open('xb') as handle:
        handle.write(manifest_bytes)
        handle.flush()
        os.fsync(handle.fileno())
    if attestor is not None:
        diagnostics.mark('attestation_sign')
        attestor.publish(manifest_bytes, target)
    diagnostics.mark('complete')
    return manifest
