# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve the existing dashboard access boundary.

import ipaddress
import secrets
from fastapi import Request
from fastapi.responses import JSONResponse
from ladder_dragon.dashboard.security_dependencies import AccessState


def _is_loopback_peer(peer: str) -> bool:
    """Return true only for a parsed loopback address."""
    try:
        return ipaddress.ip_address(peer).is_loopback
    except ValueError:
        return False


def _rate_limit_client(peer: str, forwarded: str, *, proxy_authenticated: bool) -> str:
    """Accept the nginx client address only across the trusted local boundary."""
    if not proxy_authenticated or not _is_loopback_peer(peer):
        return peer
    try:
        return str(ipaddress.ip_address(forwarded))
    except ValueError:
        return peer


def _prune_rate_buckets(state: AccessState, now: float) -> None:
    """Remove expired client keys while the caller holds ``_RATE_LOCK``."""
    if now - state._RATE_PRUNE_STATE['last'] < 60:
        return
    cutoff = now - 60
    for (stale_client, stale_bucket) in list(state._RATE_BUCKETS.items()):
        while stale_bucket and stale_bucket[0] <= cutoff:
            stale_bucket.popleft()
        if not stale_bucket:
            state._RATE_BUCKETS.pop(stale_client, None)
    state._RATE_PRUNE_STATE['last'] = now


def build_access_middleware(state: AccessState):
    async def authenticate_and_rate_limit(request: Request, call_next):
        """Authenticate every API request and enforce a bounded per-client rate."""
        if request.url.path.startswith('/api/'):
            peer = request.client.host if request.client else 'unknown'
            proxy_user = request.headers.get('X-Authenticated-User', '')
            proxy_secret = request.headers.get('X-Dashboard-Proxy-Secret', '')
            bearer = request.headers.get('Authorization', '')
            header_token = request.headers.get('X-Dashboard-Token', '')
            supplied = bearer[7:] if bearer.startswith('Bearer ') else header_token
            proxy_authenticated = (
                state.DASHBOARD_TRUST_PROXY_AUTH
                and _is_loopback_peer(peer)
                and bool(proxy_user)
                and bool(state.DASHBOARD_PROXY_AUTH_SECRET)
                and secrets.compare_digest(proxy_secret, state.DASHBOARD_PROXY_AUTH_SECRET)
            )
            token_authenticated = (
                bool(state.DASHBOARD_AUTH_TOKEN)
                and secrets.compare_digest(supplied, state.DASHBOARD_AUTH_TOKEN)
            )
            authenticated = proxy_authenticated or token_authenticated
            if not authenticated:
                proxy_configured = state.DASHBOARD_TRUST_PROXY_AUTH and bool(state.DASHBOARD_PROXY_AUTH_SECRET)
                status = 503 if not state.DASHBOARD_AUTH_TOKEN and (not proxy_configured) else 401
                return JSONResponse({'ok': False, 'error': 'dashboard authentication required'}, status_code=status)
            client = _rate_limit_client(peer, request.headers.get('X-Real-IP', ''), proxy_authenticated=proxy_authenticated)
            now = state.time.monotonic()
            with state._RATE_LOCK:
                _prune_rate_buckets(state, now)
                bucket = state._RATE_BUCKETS[client]
                while bucket and bucket[0] <= now - 60:
                    bucket.popleft()
                if len(bucket) >= state.DASHBOARD_RATE_LIMIT_PER_MIN:
                    return JSONResponse(
                        {'ok': False, 'error': 'rate limit exceeded'},
                        status_code=429,
                        headers={'Retry-After': str(max(1, int(61 - (now - bucket[0]))))},
                    )
                bucket.append(now)
            if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
                content_type = request.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
                host = request.headers.get('Host', '')
                scheme = request.headers.get('X-Forwarded-Proto', request.url.scheme)
                expected_origin = f'{scheme}://{host}'
                origin = request.headers.get('Origin', '')
                fetch_site = request.headers.get('Sec-Fetch-Site', '')
                csrf = request.headers.get('X-CSRF-Token', '')
                if content_type != 'application/json':
                    return JSONResponse({'ok': False, 'error': 'JSON content type required'}, status_code=415)
                if not origin or not secrets.compare_digest(origin, expected_origin):
                    return JSONResponse({'ok': False, 'error': 'cross-origin request blocked'}, status_code=403)
                if fetch_site and fetch_site not in {'same-origin', 'same-site'}:
                    return JSONResponse({'ok': False, 'error': 'cross-site request blocked'}, status_code=403)
                if not csrf or not secrets.compare_digest(csrf, state.DASHBOARD_CSRF_TOKEN):
                    return JSONResponse({'ok': False, 'error': 'CSRF token required'}, status_code=403)
        return await call_next(request)

    return authenticate_and_rate_limit
