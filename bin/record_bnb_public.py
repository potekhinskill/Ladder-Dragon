# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: expose bounded diagnostic BNB collection without trading authority.
"""Run one diagnostic-only public BNB capture on an external mount."""
import argparse
import json
import requests

from ladder_dragon.strategy.bnb_capture import collect
from ladder_dragon.strategy.capture_clock import CaptureSigner
from ladder_dragon.strategy.capture_credentials import load_capture_key
from ladder_dragon.strategy.capture_diagnostics import CaptureDiagnostics


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError('CAPTURE_OPTIONS_INVALID')


def main():
    diagnostics = CaptureDiagnostics()
    parser = SafeParser(description=__doc__)
    parser.add_argument('--external-mount', required=True)
    parser.add_argument('--requests-limit', type=int, default=10)
    parser.add_argument('--duration-sec', type=int, default=30)
    parser.add_argument('--slot', choices=('original', 'signed-test'), default='original')
    parser.add_argument('--signing-credential')
    parser.add_argument('--trusted-key-sha256')
    parser.add_argument('--collector-id')
    parser.add_argument('--clock-max-uncertainty-ms', type=int)
    parser.add_argument('--clock-ttl-ms', type=int)
    parser.add_argument('--clock-drift-ppm', type=int)
    try:
        args = parser.parse_args()
        attestor = None
        signing = (args.signing_credential, args.trusted_key_sha256, args.collector_id,
                   args.clock_max_uncertainty_ms, args.clock_ttl_ms, args.clock_drift_ppm)
        if any(value is not None for value in signing) or args.slot == 'signed-test':
            if (any(value is None for value in signing) or args.slot != 'signed-test'
                    or min(args.clock_max_uncertainty_ms, args.clock_ttl_ms, args.clock_drift_ppm) <= 0):
                raise ValueError('CAPTURE_SIGNING_OPTIONS_REQUIRED')
            diagnostics.mark('credential')
            key = load_capture_key(args.signing_credential, expected_public_sha256=args.trusted_key_sha256)
            policy = dict(max_uncertainty_ns=args.clock_max_uncertainty_ms*1000000,
                          max_ttl_ns=args.clock_ttl_ms*1000000, max_drift_ppm=args.clock_drift_ppm)
            diagnostics.mark('signer')
            attestor = CaptureSigner(private_key=key, collector_id=args.collector_id, policy=policy,
                                     diagnostics=diagnostics)
        diagnostics.mark('limits')
        report = collect(args.external_mount, requests_limit=args.requests_limit,
                         duration_sec=args.duration_sec, slot=args.slot, attestor=attestor,
                         diagnostics=diagnostics)
    except (OSError, ValueError, RuntimeError, requests.RequestException) as error:
        print(json.dumps(diagnostics.failure(error)))
        return 2
    # Diagnostics are command output only, never part of the signed manifest.
    if diagnostics.network:
        report = dict(report, network=diagnostics.network)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
