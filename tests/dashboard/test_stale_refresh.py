from ladder_dragon.dashboard.services import stale_refresh


class DeferredThread:
    created = []

    def __init__(self, *, target, args, name, daemon):
        self.target = target
        self.args = args
        self.name = name
        self.daemon = daemon
        self.__class__.created.append(self)

    def start(self):
        return None


def test_cache_returns_immediately_and_starts_only_one_refresh(monkeypatch):
    DeferredThread.created = []
    monkeypatch.setattr(stale_refresh.threading, "Thread", DeferredThread)
    now = [100.0]
    cache = stale_refresh.StaleWhileRefreshCache(
        ttl_sec=10,
        maximum_stale_sec=30,
        load_errors=(RuntimeError, TypeError),
        error_logger=lambda exc: None,
        clock=lambda: now[0],
    )

    first = cache.get("SOL", lambda: {"value": 7})
    second = cache.get("SOL", lambda: {"value": 8})

    assert first == (None, "refreshing", None)
    assert second == (None, "refreshing", None)
    assert len(DeferredThread.created) == 1
    DeferredThread.created[0].target(*DeferredThread.created[0].args)
    assert cache.get("SOL", lambda: {"value": 9}) == (
        {"value": 7}, "fresh", 0.0,
    )


def test_cache_returns_stale_data_while_refresh_runs(monkeypatch):
    DeferredThread.created = []
    monkeypatch.setattr(stale_refresh.threading, "Thread", DeferredThread)
    now = [100.0]
    cache = stale_refresh.StaleWhileRefreshCache(
        ttl_sec=10,
        maximum_stale_sec=30,
        load_errors=(RuntimeError, TypeError),
        error_logger=lambda exc: None,
        clock=lambda: now[0],
    )
    cache._entries["SOL"] = {"ts": 85.0, "payload": {"value": 7}}

    assert cache.get("SOL", lambda: {"value": 8}) == (
        {"value": 7}, "stale", 15.0,
    )
    assert len(DeferredThread.created) == 1


def test_cache_drops_expired_data_and_logs_safe_refresh_failure(monkeypatch):
    DeferredThread.created = []
    monkeypatch.setattr(stale_refresh.threading, "Thread", DeferredThread)
    errors = []
    cache = stale_refresh.StaleWhileRefreshCache(
        ttl_sec=10,
        maximum_stale_sec=30,
        load_errors=(RuntimeError, TypeError),
        error_logger=lambda exc: errors.append(type(exc).__name__),
        clock=lambda: 100.0,
    )
    cache._entries["SOL"] = {"ts": 60.0, "payload": {"secret": "old"}}

    assert cache.get("SOL", lambda: (_ for _ in ()).throw(RuntimeError("private"))) == (
        None, "refreshing", None,
    )
    DeferredThread.created[0].target(*DeferredThread.created[0].args)
    assert errors == ["RuntimeError"]


def test_cache_evicts_oldest_entry_at_growth_limit(monkeypatch):
    DeferredThread.created = []
    monkeypatch.setattr(stale_refresh.threading, "Thread", DeferredThread)
    now = [100.0]
    cache = stale_refresh.StaleWhileRefreshCache(
        ttl_sec=10,
        maximum_stale_sec=30,
        load_errors=(RuntimeError, TypeError),
        error_logger=lambda exc: None,
        clock=lambda: now[0],
        maximum_entries=2,
    )
    cache._entries.update({
        "old": {"ts": 90.0, "payload": {"value": 1}},
        "new": {"ts": 95.0, "payload": {"value": 2}},
    })

    cache.get("third", lambda: {"value": 3})
    DeferredThread.created[0].target(*DeferredThread.created[0].args)

    assert set(cache._entries) == {"new", "third"}
