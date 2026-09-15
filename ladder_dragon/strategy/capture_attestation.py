# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: verify collector attestations without granting replay authority.
"""Pure trust boundary. Keys and clock evidence come from reviewed callers.

No key discovery, network, persistence, or trust-on-first-use is permitted here.
A trusted signature attests the collector's claims, not the exchange itself.
"""

from dataclasses import dataclass
import hashlib
import json
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from ladder_dragon.strategy.bnb_capture import pairs

DOMAIN = b'LadderDragon:public-capture-attestation:v1\x00'


def integer(value, *, signed=False):
    if type(value) is not int or not (-2**63 if signed else 0) <= value < 2**63:
        raise ValueError('ATTESTATION_INTEGER_INVALID')
    return value


def bounded_json(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= 16384:
        raise ValueError('ATTESTATION_BYTES_INVALID')
    try:
        return json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, RecursionError):
        raise ValueError('ATTESTATION_JSON_INVALID') from None


@dataclass(frozen=True)
class ClockWindow:
    measured_wall_ns: int
    measured_mono_ns: int
    offset_ns: int
    uncertainty_ns: int
    ttl_ns: int
    drift_ppm: int

    def receipt_interval(self, wall_ns, mono_ns):
        """Map receipt to an exchange-time interval; ambiguous order stays unknown."""
        wall_ns, mono_ns = integer(wall_ns), integer(mono_ns)
        age = mono_ns - self.measured_mono_ns
        if not 0 <= age < self.ttl_ns:
            raise ValueError('ATTESTATION_CLOCK_EXPIRED')
        drift = (age * self.drift_ppm + 999999) // 1000000
        if abs((wall_ns-self.measured_wall_ns)-age) > drift:
            raise ValueError('ATTESTATION_CLOCK_JUMP')
        center = wall_ns + self.offset_ns
        radius = self.uncertainty_ns + drift
        if center - radius <= 0:
            raise ValueError('ATTESTATION_CLOCK_RANGE')
        return center-radius, center+radius


def clock_window(evidence, *, max_uncertainty_ns, max_ttl_ns, max_drift_ppm):
    """Check independent policy ceilings, never limits supplied by the artifact."""
    fields = {'measured_wall_ns', 'measured_mono_ns', 'offset_ns', 'uncertainty_ns',
              'ttl_ns', 'drift_ppm', 'synchronized', 'source'}
    if not isinstance(evidence, dict) or set(evidence) not in (fields, fields | {'measurement_sha256'}):
        raise ValueError('ATTESTATION_CLOCK_SCHEMA')
    if 'measurement_sha256' in evidence and (not isinstance(evidence['measurement_sha256'], str)
            or re.fullmatch('[0-9a-f]{64}', evidence['measurement_sha256']) is None):
        raise ValueError('ATTESTATION_CLOCK_MEASUREMENT')
    if evidence['synchronized'] is not True or evidence['source'] != 'collector-clock-v1':
        raise ValueError('ATTESTATION_CLOCK_UNTRUSTED')
    for value in (max_uncertainty_ns, max_ttl_ns, max_drift_ppm):
        if integer(value) <= 0:
            raise ValueError('ATTESTATION_CLOCK_POLICY')
    values = {k: integer(evidence[k], signed=k == 'offset_ns') for k in fields
              if k not in {'synchronized', 'source'}}
    if (values['measured_wall_ns'] <= 0 or not 0 < values['uncertainty_ns'] <= max_uncertainty_ns
            or not 0 < values['ttl_ns'] <= max_ttl_ns
            or not 0 < values['drift_ppm'] <= max_drift_ppm):
        raise ValueError('ATTESTATION_CLOCK_LIMIT')
    return ClockWindow(**values)


def payload(manifest_bytes, clock, *, collector_id):
    """Bind exact diagnostic manifest bytes, without upgrading its safety flags."""
    manifest = bounded_json(manifest_bytes)
    fields = {'schema', 'status', 'symbol', 'events', 'bytes', 'archive_sha256',
              'replay_allowed', 'source_authenticated', 'clock_verified', 'signature'}
    if (not isinstance(manifest, dict) or set(manifest) != fields
            or manifest['schema'] != 'bnb_rest_capture_v1'
            or manifest['status'] != 'DIAGNOSTIC_ONLY' or manifest['symbol'] != 'BNBUSDT'
            or any(manifest[k] is not False for k in ('replay_allowed', 'source_authenticated', 'clock_verified'))
            or manifest['signature'] is not None):
        raise ValueError('ATTESTATION_MANIFEST_INVALID')
    if not 0 < integer(manifest['events']) <= 10000 or not 0 < integer(manifest['bytes']) <= 64*1024*1024:
        raise ValueError('ATTESTATION_MANIFEST_LIMIT')
    if not isinstance(manifest['archive_sha256'], str) or re.fullmatch('[0-9a-f]{64}', manifest['archive_sha256']) is None:
        raise ValueError('ATTESTATION_ARCHIVE_HASH')
    if not isinstance(collector_id, str) or re.fullmatch('[a-zA-Z0-9_-]{1,64}', collector_id) is None:
        raise ValueError('ATTESTATION_COLLECTOR_INVALID')
    return {'schema': 'collector_attestation_v1', 'collector_id': collector_id,
            'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(), 'clock': clock,
            'replay_allowed': False}


def sign(manifest_bytes, clock, *, collector_id, private_key, **policy):
    """Return a detached in-memory signature; never load or export a private key."""
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError('ATTESTATION_SIGNER_INVALID')
    clock_window(clock, **policy)
    body = json.dumps(payload(manifest_bytes, clock, collector_id=collector_id),
                      sort_keys=True, separators=(',', ':')).encode()
    if len(body) > 16384:
        raise ValueError('ATTESTATION_BYTES_INVALID')
    return body, private_key.sign(DOMAIN + body)


def verify(manifest_bytes, body, signature, *, trusted_public_key, expected_collector_id, **policy):
    """Return a clock window only; archive membership and fill ownership remain separate."""
    value = bounded_json(body)
    if type(signature) is not bytes or len(signature) != 64:
        raise ValueError('ATTESTATION_SIGNATURE_INVALID')
    if type(trusted_public_key) is not bytes or len(trusted_public_key) != 32:
        raise ValueError('ATTESTATION_TRUST_KEY_INVALID')
    try:
        Ed25519PublicKey.from_public_bytes(trusted_public_key).verify(signature, DOMAIN + body)
    except InvalidSignature:
        raise ValueError('ATTESTATION_SIGNATURE_INVALID') from None
    if not isinstance(value, dict) or set(value) != {'schema', 'collector_id', 'manifest_sha256', 'clock', 'replay_allowed'}:
        raise ValueError('ATTESTATION_SCHEMA_INVALID')
    expected = payload(manifest_bytes, value['clock'], collector_id=expected_collector_id)
    if value != expected or value['replay_allowed'] is not False:
        raise ValueError('ATTESTATION_BINDING_INVALID')
    return clock_window(value['clock'], **policy)


def require_before_fill(window, *, wall_ns, mono_ns, fill_time_ms):
    """Require the entire receipt uncertainty interval strictly before the fill."""
    fill = integer(fill_time_ms) * 1000000
    interval = window.receipt_interval(wall_ns, mono_ns)
    if interval[1] >= fill:
        raise ValueError('ATTESTATION_RECEIPT_ORDER_UNKNOWN')
    return interval
