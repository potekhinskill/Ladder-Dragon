from copy import deepcopy
import json
import sqlite3

import pytest

from ladder_dragon.strategy.prediction.context_journal import ContextJournal, export_context
from ladder_dragon.strategy.prediction.context_sources import attest, fee_source, filter_source
from ladder_dragon.strategy.prediction.episode_semantics import v23_evidence_semantics_contract
from ladder_dragon.strategy.prediction.historical_policy import fingerprint
from ladder_dragon.supervision.panic_observer import panic_observer_fingerprint

SYMBOL = "SOLUSDT"
SESSION = "a" * 32
CLASSIFIER = v23_evidence_semantics_contract()["regime_classifier"]


def sources(now=1000):
    return {
        "runtime": attest("runtime", SYMBOL, now, {
            "classifier": CLASSIFIER, "regime": "RANGE", "panic": False, "panic_hits": 0,
            "panic_source_fingerprint": panic_observer_fingerprint(),
            "panic_observed_at_ms": now,
        }),
        "filters": attest("filters", SYMBOL, now, {
            "tick_size": "0.01", "step_size": "0.001", "minimum_quantity": "0.001", "minimum_notional_quote": "5",
        }),
        "fees": attest("fees", SYMBOL, now, {
            "maker_buy_fee_pct": "0.001", "maker_sell_fee_pct": "0.001",
            "taker_buy_fee_pct": "0.001", "taker_sell_fee_pct": "0.001",
        }),
    }


def append(journal, now=1000, **kwargs):
    return journal.append(symbol=SYMBOL, session_id=SESSION, observed_at_ms=now,
                          sources=sources(now), **kwargs)


def export(path, start=2000, end=10_000):
    return export_context(path, symbol=SYMBOL, classifier_fingerprint=fingerprint(CLASSIFIER),
                          start_ms=start, end_ms=end, cutoff_ms=end)


def test_round_trip_has_sources_without_authority(tmp_path):
    journal = ContextJournal(tmp_path / "context.sqlite3")
    append(journal)
    result = export(journal.path)
    assert result["context"][0]["maker_buy_fee_pct"] == "0.001"
    assert result["context"][0]["source_sha256"] == fingerprint(sources())
    assert result["records"][0]["payload"]["sources"] == sources()
    assert result["mode"] == "SHADOW" and result["apply_allowed"] is False
    assert fingerprint({k: v for k, v in result.items() if k != "sha256"}) == result["sha256"]


def test_future_rows_do_not_change_export(tmp_path):
    journal = ContextJournal(tmp_path / "context.sqlite3")
    append(journal)
    first = export(journal.path)
    journal.append(symbol=SYMBOL, session_id=SESSION, observed_at_ms=11_000, reason="SOURCE_UNAVAILABLE")
    assert export(journal.path) == first


def test_explicit_failure_cannot_hide_behind_previous_lifetime(tmp_path):
    journal = ContextJournal(tmp_path / "context.sqlite3")
    append(journal)
    journal.append(symbol=SYMBOL, session_id=SESSION, observed_at_ms=3000, reason="PANIC_UNAVAILABLE")
    append(journal, 4000)
    with pytest.raises(ValueError, match="unavailable"):
        export(journal.path)


def test_expiry_future_and_restart_block(tmp_path):
    journal = ContextJournal(tmp_path / "context.sqlite3")
    append(journal)
    with pytest.raises(ValueError, match="tail"):
        export(journal.path, end=181000)
    with pytest.raises(ValueError, match="unavailable"):
        export(journal.path, start=999)
    journal.append(symbol=SYMBOL, session_id="b" * 32, observed_at_ms=3000, sources=sources(3000))
    with pytest.raises(ValueError, match="session"):
        export(journal.path)


def test_gap_cannot_be_backfilled_with_a_later_observation(tmp_path):
    journal = ContextJournal(tmp_path / "context.sqlite3")
    append(journal)
    append(journal, 182000)
    with pytest.raises(ValueError, match="gap"):
        export(journal.path, end=190000)


def test_changed_classifier_and_symbol_do_not_cross_cohorts(tmp_path):
    journal = ContextJournal(tmp_path / "context.sqlite3")
    append(journal)
    with pytest.raises(ValueError, match="classifier"):
        export_context(journal.path, symbol=SYMBOL, classifier_fingerprint="c" * 64,
                       start_ms=2000, end_ms=10000, cutoff_ms=10000)
    with pytest.raises(ValueError, match="unavailable"):
        export_context(journal.path, symbol="ETHUSDT", classifier_fingerprint=fingerprint(CLASSIFIER),
                       start_ms=2000, end_ms=10000, cutoff_ms=10000)


def test_capacity_and_clock_failure_preserve_all_existing_evidence(tmp_path):
    journal = ContextJournal(tmp_path / "context.sqlite3", maximum_records=1)
    append(journal)
    before = export(journal.path)
    with pytest.raises(RuntimeError, match="capacity"):
        append(journal, 3000)
    with pytest.raises(ValueError, match="clock"):
        append(journal, 900)
    assert export(journal.path) == before
    with sqlite3.connect(journal.path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("UPDATE historical_context_records SET status='BLOCKED'")
        with pytest.raises(sqlite3.IntegrityError, match="archival"):
            connection.execute("DELETE FROM historical_context_records")


def test_source_tampering_and_unknown_fields_rejected_before_write(tmp_path):
    journal = ContextJournal(tmp_path / "context.sqlite3")
    bad = sources()
    bad["fees"]["values"]["maker_buy_fee_pct"] = "0"
    with pytest.raises(ValueError, match="hash"):
        journal.append(symbol=SYMBOL, session_id=SESSION, observed_at_ms=1000, sources=bad)
    bad = sources()
    bad["runtime"]["values"]["token"] = "do-not-persist-this"
    with pytest.raises(ValueError):
        journal.append(symbol=SYMBOL, session_id=SESSION, observed_at_ms=1000, sources=bad)
    with sqlite3.connect(journal.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM historical_context_records").fetchone()[0] == 0


def test_sources_cannot_be_used_before_receipt(tmp_path):
    journal = ContextJournal(tmp_path / "context.sqlite3")
    with pytest.raises(ValueError, match="future"):
        journal.append(symbol=SYMBOL, session_id=SESSION, observed_at_ms=999, sources=sources())


def test_read_only_export_does_not_create_a_missing_database(tmp_path):
    path = tmp_path / "missing.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        export(path)
    assert not path.exists()


def test_export_limit_counts_embedded_context_and_proof(tmp_path, monkeypatch):
    from ladder_dragon.strategy.prediction import context_journal as module
    journal = ContextJournal(tmp_path / "context.sqlite3")
    append(journal)
    result = export(journal.path)
    total = len(json.dumps(result, sort_keys=True, separators=(",", ":")).encode())
    monkeypatch.setattr(module, "MAX_EXPORT_BYTES", total - 1)
    with pytest.raises(ValueError, match="capacity"):
        export(journal.path)


def test_migration_identity_and_record_hash_checked(tmp_path):
    journal = ContextJournal(tmp_path / "context.sqlite3")
    append(journal)
    with sqlite3.connect(journal.path) as connection:
        connection.execute("DROP TRIGGER context_no_update")
        connection.execute("UPDATE historical_context_records SET sha256=?", ("f" * 64,))
    with pytest.raises(ValueError, match="chain"):
        export(journal.path)
    with sqlite3.connect(journal.path) as connection:
        connection.execute("PRAGMA user_version=2")
    with pytest.raises(ValueError, match="migration"):
        ContextJournal(journal.path)


def test_projection_drops_provider_secrets_and_requires_exact_identity():
    payload = {"symbol": SYMBOL, "secret": "do-not-persist-this", "discount": {"enabledForAccount": True}}
    for name in ("standardCommission", "taxCommission", "specialCommission"):
        payload[name] = {"maker": "0.001", "taker": "0.002", "buyer": "0", "seller": "0"}
    result = fee_source(SYMBOL, payload, 1000)
    assert "do-not-persist-this" not in json.dumps(result)
    assert result["values"]["maker_buy_fee_pct"] == "0.003"
    for changed in (dict(payload, symbol="ETHUSDT"), {k: v for k, v in payload.items() if k != "taxCommission"}):
        with pytest.raises((ValueError, KeyError)):
            fee_source(SYMBOL, changed, 1000)
    payload = {"symbols": [{"symbol": SYMBOL, "status": "TRADING", "secret": "do-not-persist-this", "filters": [
        {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
        {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
        {"filterType": "NOTIONAL", "minNotional": "5"},
    ]}]}
    assert "do-not-persist-this" not in json.dumps(filter_source(SYMBOL, payload, 1000))
    invalid = deepcopy(payload)
    invalid["symbols"][0]["filters"][0]["tickSize"] = 0.01
    with pytest.raises(ValueError, match="strings"):
        filter_source(SYMBOL, invalid, 1000)
