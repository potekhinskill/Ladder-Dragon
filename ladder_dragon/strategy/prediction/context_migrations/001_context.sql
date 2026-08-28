CREATE TABLE context_schema(version INTEGER PRIMARY KEY, sha256 TEXT NOT NULL);
CREATE TABLE historical_context_records(
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    observed_at_ms INTEGER NOT NULL CHECK(observed_at_ms > 0),
    session_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('AVAILABLE','BLOCKED')),
    payload TEXT NOT NULL CHECK(length(payload) <= 8192),
    sha256 TEXT NOT NULL UNIQUE,
    previous_sha256 TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'SHADOW' CHECK(mode = 'SHADOW'),
    apply_allowed INTEGER NOT NULL DEFAULT 0 CHECK(apply_allowed = 0),
    UNIQUE(symbol, observed_at_ms)
);
CREATE INDEX context_time ON historical_context_records(symbol, observed_at_ms);
CREATE TRIGGER context_no_update BEFORE UPDATE ON historical_context_records
BEGIN SELECT RAISE(ABORT, 'historical context is immutable'); END;
CREATE TRIGGER context_no_delete BEFORE DELETE ON historical_context_records
BEGIN SELECT RAISE(ABORT, 'historical context requires verified archival'); END;
