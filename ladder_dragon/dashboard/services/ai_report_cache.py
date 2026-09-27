# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: preserve dashboard AI reporting with explicit service ownership.

from typing import Dict, Optional


def cache_get(deps, key: str) -> Optional[Dict]:
    now = deps.time.monotonic()
    with deps._AI_SUMMARY_CACHE_LOCK:
        entry = deps._AI_SUMMARY_CACHE.get(key)
        if not entry or now - float(entry["cached_at"]) > deps.DASHBOARD_AI_AGGREGATE_CACHE_SEC:
            deps._AI_SUMMARY_CACHE.pop(key, None)
            return None
        return dict(entry["payload"])


def cache_put(deps, key: str, payload: Dict) -> Dict:
    with deps._AI_SUMMARY_CACHE_LOCK:
        deps._AI_SUMMARY_CACHE[key] = {
            "cached_at": deps.time.monotonic(),
            "payload": dict(payload),
        }
        # Runtime path changes are rare; this bound prevents abandoned paths
        # from accumulating after repeated configuration migrations.
        while len(deps._AI_SUMMARY_CACHE) > 16:
            oldest = min(
                deps._AI_SUMMARY_CACHE,
                key=lambda item: float(deps._AI_SUMMARY_CACHE[item]["cached_at"]),
            )
            deps._AI_SUMMARY_CACHE.pop(oldest, None)
    return payload
