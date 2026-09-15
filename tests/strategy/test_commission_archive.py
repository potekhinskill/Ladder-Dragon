import hashlib
from io import BytesIO
from decimal import Decimal

import pytest

from ladder_dragon.strategy.prediction.commission_archive import extract_price_record, value_archived_bnb_fill
from tests.strategy.test_commission_evidence import evidence, encoded


def archive(price):
    rows = [dict(s="BNBUSDT", lastUpdateId=1, _source="binance-public-rest-depth"),
            dict(s="BNBUSDT", e="depthUpdate", U=2, u=2), price]
    raw = b"".join(encoded(row) + b"\n" for row in rows)
    manifest = dict(schema_version=1, symbol="BNBUSDT", contains_secrets=False,
                    event_count=3, depth_event_count=1, trade_event_count=1,
                    archive_sha256=hashlib.sha256(raw).hexdigest())
    return raw, manifest


def extract(raw, manifest, **changes):
    manifest_bytes = encoded(manifest)
    args = dict(manifest_bytes=manifest_bytes, manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
                symbol="BNBUSDT", aggregate_trade_id=77, maximum_archive_bytes=4096)
    args.update(changes)
    return extract_price_record(BytesIO(raw), **args)


def test_full_chain_retains_archive_record_and_fill_identity(evidence):
    journal, fills, price = evidence
    raw, manifest = archive(price)
    before = journal.get("buy")
    result = value_archived_bnb_fill(
        stream=BytesIO(raw), manifest_bytes=encoded(manifest),
        manifest_sha256=hashlib.sha256(encoded(manifest)).hexdigest(),
        aggregate_trade_id=77, maximum_archive_bytes=4096, parent=before, trade_id=1,
        fills_bytes=encoded(fills), fills_sha256=hashlib.sha256(encoded(fills)).hexdigest(), max_age_ms=1000)
    assert result.commission.valuation.quote_value == Decimal("0.0600")
    assert result.archive_sha256 == manifest["archive_sha256"]
    assert result.price_line_number == 3 and result.commission.trade_id == 1
    assert journal.get("buy") == before
    assert extract(raw, manifest).record == encoded(price) + b"\n"


@pytest.mark.parametrize("change", [dict(schema_version=True), dict(schema_version=2),
    dict(symbol="ETHUSDT"), dict(contains_secrets=True), dict(event_count=4),
    dict(depth_event_count=True), dict(archive_sha256="0" * 64)])
def test_manifest_mismatch_rejected(evidence, change):
    raw, manifest = archive(evidence[2])
    with pytest.raises(ValueError):
        extract(raw, dict(manifest, **change))


@pytest.mark.parametrize("mode", ["suffix", "price", "truncate", "pin", "capacity", "missing", "boolean"])
def test_corruption_and_invalid_selection_rejected(evidence, mode):
    raw, manifest = archive(evidence[2])
    kwargs = {}
    if mode == "suffix":
        raw += b"{}\n"
    elif mode == "price":
        raw = raw.replace(b'"600"', b'"601"')
    elif mode == "truncate":
        raw = raw[:-2]
    elif mode == "pin":
        kwargs["manifest_sha256"] = "0" * 64
    elif mode == "capacity":
        kwargs["maximum_archive_bytes"] = len(raw) - 1
    else:
        kwargs["aggregate_trade_id"] = True if mode == "boolean" else 78
    with pytest.raises(ValueError):
        extract(raw, manifest, **kwargs)


def test_matching_trade_does_not_allow_early_return(evidence):
    raw, manifest = archive(evidence[2])
    raw += encoded(evidence[2]) + b"\n"
    manifest.update(event_count=4, trade_event_count=2, archive_sha256=hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match="ambiguous"):
        extract(raw, manifest)


def test_rehashed_foreign_tail_still_fails_market_check(evidence):
    raw, manifest = archive(evidence[2])
    raw += encoded(dict(evidence[2], s="ETHUSDT", a=78)) + b"\n"
    manifest.update(event_count=4, trade_event_count=2, archive_sha256=hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match="market"):
        extract(raw, manifest)


def test_exact_capacity_is_valid_and_oversized_line_is_bounded(evidence):
    raw, manifest = archive(evidence[2])
    assert extract(raw, manifest, maximum_archive_bytes=len(raw)).line_number == 3
    with pytest.raises(ValueError):
        extract(b" " * 1048577, manifest, maximum_archive_bytes=2097152)


def test_real_recorder_format_is_accepted_without_reencoding(tmp_path, evidence):
    import json
    from ladder_dragon.strategy.depth_archive import record_public_depth
    from tests.test_depth_archive import FakeConnection, FakeResponse

    class Session:
        def get(self, *args, **kwargs):
            return FakeResponse()

    connection = FakeConnection()
    connection.frames = iter([
        {"data": dict(e="depthUpdate", E=1010, s="BNBUSDT", U=101, u=101, b=[], a=[])},
        {"data": evidence[2]},
    ])
    ticks = iter([1000, 1000, 1005, 1015, 1900, 1930])
    output = tmp_path / "BNBUSDT.jsonl"
    record_public_depth("BNBUSDT", output, max_events=3, session=Session(),
                        connect=lambda *args, **kwargs: connection, clock_ms=lambda: next(ticks))
    metadata = output.with_suffix(".jsonl.metadata.json").read_bytes()
    with output.open("rb") as stream:
        result = extract_price_record(stream, manifest_bytes=metadata,
            manifest_sha256=hashlib.sha256(metadata).hexdigest(), symbol="BNBUSDT",
            aggregate_trade_id=77, maximum_archive_bytes=4096)
    assert result.archive_sha256 == hashlib.sha256(output.read_bytes()).hexdigest()
    assert json.loads(result.record)["_received_at_ms"] == 1900


def test_hash_check_covers_unselected_tail(evidence):
    raw, manifest = archive(evidence[2])
    raw += encoded(dict(evidence[2], a=78)) + b"\n"
    manifest.update(event_count=4, trade_event_count=2, archive_sha256=hashlib.sha256(raw).hexdigest())
    raw = raw[:-2] + b" \n"
    with pytest.raises(ValueError):
        extract(raw, manifest)
