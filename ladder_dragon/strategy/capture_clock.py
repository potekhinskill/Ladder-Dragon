# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: retain bounded public clock measurements for signed capture.
"""Exchange time is bracketed by receipt clocks, not asserted from a flag."""

import hashlib
import json
import os
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ladder_dragon.execution.market_http_body import read_body
from ladder_dragon.strategy.capture_attestation import bounded_json, clock_window, integer, sign
from ladder_dragon.strategy.capture_diagnostics import CaptureDiagnostics

TIME_URL = 'https://data-api.binance.vision/api/v3/time'


def derive_clock(raw, **policy):
    measurement = bounded_json(raw)
    fields = {'source', 'started_wall_ns', 'started_mono_ns', 'finished_wall_ns',
              'finished_mono_ns', 'response_utf8'}
    if not isinstance(measurement, dict) or set(measurement) != fields or measurement['source'] != TIME_URL:
        raise ValueError('CAPTURE_CLOCK_SOURCE')
    response_text = measurement['response_utf8']
    if not isinstance(response_text, str) or len(response_text) > 1024:
        raise ValueError('CAPTURE_CLOCK_BODY')
    response = bounded_json(response_text.encode())
    if not isinstance(response, dict) or set(response) != {'serverTime'}:
        raise ValueError('CAPTURE_CLOCK_BODY')
    server = integer(response['serverTime']) * 1000000
    sw, sm, fw, fm = (integer(measurement[k]) for k in
                      ('started_wall_ns', 'started_mono_ns', 'finished_wall_ns', 'finished_mono_ns'))
    if not 0 < sw <= fw or fm <= sm or server <= 0 or fm-sm > 5000000000:
        raise ValueError('CAPTURE_CLOCK_ORDER')
    if abs((fw-sw)-(fm-sm)) > 1000000:
        raise ValueError('CAPTURE_CLOCK_JUMP')
    # A millisecond server sample can occur anywhere in the entire request interval.
    lower, upper = server-fw, server+1000000-sw
    offset = (lower+upper)//2
    uncertainty = max(offset-lower, upper-offset) + abs((fw-sw)-(fm-sm))
    clock = dict(measured_wall_ns=fw, measured_mono_ns=fm, offset_ns=offset,
                 uncertainty_ns=uncertainty, ttl_ns=policy['max_ttl_ns'],
                 drift_ppm=policy['max_drift_ppm'], synchronized=True,
                 source='collector-clock-v1', measurement_sha256=hashlib.sha256(raw).hexdigest())
    clock_window(clock, **policy)
    return clock


class CaptureSigner:
    """Per-run signer with no key loading or trust enrollment."""

    def __init__(self, *, private_key, collector_id, policy, diagnostics=None):
        if not isinstance(private_key, Ed25519PrivateKey):
            raise ValueError('CAPTURE_SIGNER_KEY')
        self.private_key = private_key
        self.diagnostics = diagnostics if diagnostics is not None else CaptureDiagnostics()
        self.collector_id = collector_id
        self.policy = dict(policy)
        self.measurement = self.clock = None
        self.started = False

    def warmup(self, session, deadline):
        """Consume one public request; discard its bytes before clock sampling."""
        self.diagnostics.mark('clock_warmup_request')
        budget = min(5, deadline-time.monotonic())
        if budget <= 0:
            raise ValueError('CAPTURE_CLOCK_DEADLINE')
        request_deadline = min(deadline, time.monotonic()+budget)
        with session.get(TIME_URL, stream=True, allow_redirects=False, timeout=budget) as response:
            if response.status_code != 200:
                raise ValueError('CAPTURE_CLOCK_HTTP')
            self.diagnostics.mark('clock_warmup_body')
            read_body(response, deadline=request_deadline, max_bytes=1024)
            self.diagnostics.mark('clock_warmup_close')
        if time.monotonic() >= request_deadline:
            raise ValueError('CAPTURE_CLOCK_DEADLINE')
        session.cookies.clear()

    def start(self, session, wall, mono, deadline):
        if self.started:
            raise ValueError('CAPTURE_SIGNER_REUSE')
        self.started = True
        self.warmup(session, deadline)
        self.diagnostics.mark('clock_request')
        started_wall, started_mono = wall(), mono()
        budget = min(5, deadline-time.monotonic())
        if budget <= 0:
            raise ValueError('CAPTURE_CLOCK_DEADLINE')
        request_deadline = min(deadline, time.monotonic()+budget)
        with session.get(TIME_URL, stream=True, allow_redirects=False, timeout=budget) as response:
            if response.status_code != 200:
                raise ValueError('CAPTURE_CLOCK_HTTP')
            self.diagnostics.mark('clock_body')
            raw = read_body(response, deadline=request_deadline, max_bytes=1024)
            finished_wall, finished_mono = wall(), mono()
            self.diagnostics.mark('clock_close')
        self.diagnostics.mark('clock_validate')
        self.measurement = json.dumps(dict(source=TIME_URL, started_wall_ns=started_wall,
            started_mono_ns=started_mono, finished_wall_ns=finished_wall,
            finished_mono_ns=finished_mono, response_utf8=raw.decode()),
            sort_keys=True, separators=(',', ':')).encode()
        self.clock = derive_clock(self.measurement, **self.policy)

    def observe(self, wall_ns, mono_ns):
        return clock_window(self.clock, **self.policy).receipt_interval(wall_ns, mono_ns)

    def publish(self, manifest_bytes, target):
        self.diagnostics.mark('attestation_sign')
        body, signature = sign(manifest_bytes, self.clock, collector_id=self.collector_id,
                               private_key=self.private_key, **self.policy)
        self.diagnostics.mark('attestation_write')
        for name, data in (('clock.json', self.measurement), ('attestation.json', body),
                           ('attestation.sig', signature)):
            with (target / name).open('xb') as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
