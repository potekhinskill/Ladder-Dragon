# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: expose fixed capture failure codes without exception payloads.
"""Per-invocation diagnostics only; no evidence writes or admission changes."""

import json
import requests

from ladder_dragon.execution.market_http_body import MarketResponseError

STAGES = frozenset('options credential signer limits storage slot session clock_request clock_body clock_validate clock_close market_request market_body market_validate receipt_validate observation_write pause session_close final_storage manifest_write attestation_sign attestation_write complete'.split())
STAGES = STAGES | frozenset(('clock_warmup_request', 'clock_warmup_body', 'clock_warmup_close'))
REASONS = frozenset('''CAPTURE_OPTIONS_INVALID CAPTURE_SIGNING_OPTIONS_REQUIRED
CAPTURE_BODY_LIMIT CAPTURE_BOOLEAN_INVALID CAPTURE_CLOCK_JUMP CAPTURE_CLOCK_REQUEST_BUDGET
CAPTURE_DEADLINE CAPTURE_DECIMAL_INVALID CAPTURE_DEVICE_CHANGED CAPTURE_DISK_RESERVE
CAPTURE_DUPLICATE_KEY CAPTURE_EXTERNAL_MOUNT_REQUIRED CAPTURE_FUTURE_TRADE CAPTURE_HTTP_STATUS
CAPTURE_ID_INVALID CAPTURE_LIMIT_INVALID CAPTURE_NO_TRADES CAPTURE_ROOT_DEVICE_FORBIDDEN
CAPTURE_ROWS_INVALID CAPTURE_ROW_INVALID CAPTURE_SEQUENCE_GAP CAPTURE_STORE_LIMIT CAPTURE_TIME_OR_RANGE_INVALID
CAPTURE_CLOCK_BODY CAPTURE_CLOCK_DEADLINE CAPTURE_CLOCK_HTTP CAPTURE_CLOCK_ORDER CAPTURE_CLOCK_SOURCE
CAPTURE_SIGNER_KEY CAPTURE_SIGNER_REUSE CAPTURE_KEY_ALGORITHM_INVALID CAPTURE_KEY_CHANGED
CAPTURE_KEY_DIRECTORY_PERMISSIONS CAPTURE_KEY_FILE_PERMISSIONS CAPTURE_KEY_FORMAT_INVALID
CAPTURE_KEY_PATH_INVALID CAPTURE_KEY_PIN_INVALID CAPTURE_KEY_PIN_MISMATCH
CAPTURE_SLOT_CAPACITY CAPTURE_SLOT_CHANGED CAPTURE_SLOT_CONTENTS CAPTURE_SLOT_DIRECTORY
CAPTURE_SLOT_FILE CAPTURE_SLOT_INVALID CAPTURE_TOTAL_CAPACITY
ATTESTATION_ARCHIVE_HASH ATTESTATION_BYTES_INVALID ATTESTATION_CLOCK_EXPIRED ATTESTATION_CLOCK_JUMP
ATTESTATION_CLOCK_LIMIT ATTESTATION_CLOCK_MEASUREMENT ATTESTATION_CLOCK_POLICY ATTESTATION_CLOCK_RANGE
ATTESTATION_CLOCK_SCHEMA ATTESTATION_CLOCK_UNTRUSTED ATTESTATION_COLLECTOR_INVALID
ATTESTATION_INTEGER_INVALID ATTESTATION_JSON_INVALID ATTESTATION_MANIFEST_INVALID
ATTESTATION_MANIFEST_LIMIT ATTESTATION_SIGNER_INVALID'''.split())


class CaptureDiagnostics:
    def __init__(self):
        self.stage = 'options'
        self.network = []

    def record_network(self, stage, values):
        # Keep only bounded, fixed fields; no hosts, addresses, or exceptions.
        if len(self.network) >= 100:
            return
        entry = {'stage': stage if stage in ('clock_warmup_request', 'clock_request', 'market_request') else 'unknown'}
        for name in ('dns_ns', 'dns_calls', 'request_headers_ns', 'non_dns_headers_ns'):
            value = values.get(name)
            entry[name] = value if type(value) is int and 0 <= value < 2**63 else None
        for name, allowed in (('phase', ('dns', 'tcp', 'tls_headers', 'headers')),
                              ('outcome', ('failed', 'headers_received'))):
            value = values.get(name)
            entry[name] = value if type(value) is str and value in allowed else 'unknown'
        self.network.append(entry)

    def mark(self, stage):
        self.stage = stage if type(stage) is str and stage in STAGES else 'unknown'

    def failure(self, error):
        # Match whole fixed tokens only. Never stringify provider errors or paths.
        reason, kind = 'INTERNAL_ERROR', 'RuntimeError'
        for cls, code, category in (
            (requests.exceptions.SSLError, 'TLS_ERROR', 'SSLError'),
            (requests.Timeout, 'TIMEOUT', 'Timeout'),
            (requests.RequestException, 'HTTP_TRANSPORT_ERROR', 'RequestException'),
            (FileExistsError, 'FILE_EXISTS', 'OSError'),
            (FileNotFoundError, 'FILE_NOT_FOUND', 'OSError'),
            (PermissionError, 'PERMISSION_DENIED', 'OSError'),
            (OSError, 'IO_ERROR', 'OSError'),
            (MarketResponseError, 'HTTP_BODY_INVALID', 'RuntimeError'),
            (json.JSONDecodeError, 'JSON_INVALID', 'ValueError'),
            (UnicodeError, 'ENCODING_INVALID', 'ValueError'),
            (ValueError, 'VALIDATION_FAILED', 'ValueError'),
        ):
            if isinstance(error, cls):
                reason, kind = code, category
                break
        if type(error) is ValueError and len(error.args) == 1:
            token = error.args[0]
            if type(token) is str and token in REASONS:
                reason = token
        stage = self.stage if type(self.stage) is str and self.stage in STAGES else 'unknown'
        report = dict(status='BLOCKED', stage=stage, reason=reason, error_type=kind, replay_allowed=False)
        if self.network:
            report['network'] = self.network
        return report
