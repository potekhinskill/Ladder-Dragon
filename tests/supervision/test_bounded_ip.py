"""IP observation bytes, deadlines, consensus, and blocked heartbeats."""

from datetime import datetime, timezone
import gzip
import io

import pytest
import requests
from urllib3.response import HTTPResponse

from ladder_dragon.execution import market_http_body
from ladder_dragon.execution.auth_resilience import AuthResilienceState
from ladder_dragon.supervision import public_ip_read, runtime, preflight_resilience


def response(payload, encoding="identity", status=200):
    result = requests.Response()
    result.status_code = status
    result.headers.update({"Content-Encoding": encoding, "Content-Length": "1"})
    result.raw = HTTPResponse(io.BytesIO(payload), preload_content=False)
    return result


@pytest.mark.parametrize("encoding", ["identity", "gzip"])
@pytest.mark.parametrize("oversized", [False, True])
def test_bounded_body(encoding, oversized):
    payload = b"private-marker" * 500 if oversized else b"203.0.113.11\n"
    result = response(gzip.compress(payload) if encoding == "gzip" else payload, encoding)
    def get(endpoint, **kwargs):
        assert kwargs == dict(timeout=5, stream=True, allow_redirects=False)
        return result
    if oversized:
        with pytest.raises(market_http_body.MarketResponseError) as caught:
            public_ip_read.read_public_ip(get, "https://example.invalid")
        assert "private-marker" not in str(caught.value)
    else:
        assert public_ip_read.read_public_ip(get, "https://example.invalid") == payload.decode()
    assert result.raw.closed


def test_slow_chunks_and_cleanup(monkeypatch):
    clock = [0]
    result = response(b"")
    monkeypatch.setattr(public_ip_read.time, "monotonic", lambda: clock[0])
    def read1(*args, **kwargs):
        clock[0] += 1
        return b" "
    monkeypatch.setattr(result.raw, "read1", read1)
    with pytest.raises(requests.Timeout):
        public_ip_read.read_public_ip(lambda *a, **kw: result, "https://example.invalid")
    assert clock[0] == 5 and result.raw.closed


@pytest.mark.parametrize("status", [302, 500])
def test_rejected_status_cannot_create_consensus(monkeypatch, capsys, status):
    monkeypatch.setenv("BINANCE_PUBLIC_IP_ENDPOINTS", "https://one.example.invalid,https://two.example.invalid")
    results = []
    def get(endpoint, **kwargs):
        result = response(b"private-marker", status=status)
        results.append(result)
        return result
    monkeypatch.setattr(runtime.requests, "get", get)
    state, consensus = runtime._observe_public_ip(AuthResilienceState())
    assert state == AuthResilienceState() and consensus is None
    assert all(result.raw.closed for result in results)
    assert "private-marker" not in str(capsys.readouterr())


def test_ip_wait_preserves_full_delay_and_halt():
    clock, sleeps, published = [0], [], []
    def sleep(delay):
        sleeps.append(delay)
        clock[0] += delay
    preflight_resilience.wait_for_retry("IP", 300, attempt=1, persistent_halt=True,
        publish=lambda **data: published.append(data), monotonic=lambda: clock[0],
        sleep=sleep, now_utc=lambda: datetime(2026, 9, 8, tzinfo=timezone.utc))
    assert sum(sleeps) == 300 and max(sleeps) <= 30
    assert len(published) == 10
    assert all(row["state"] == "IP_BLOCKED" and row["risk"]["halted"]
               and row["risk"]["buy_blocked"] for row in published)
    assert [row["ip_backoff"]["retry_in_sec"] for row in published] == list(range(300, 0, -30))
