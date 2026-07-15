from order_identity import client_order_id


def test_client_order_id_is_stable_inside_retry_bucket():
    first = client_order_id("SOLUSDT", "BUY", "ladder", "100.00", "0.2", now=1000)
    retry = client_order_id("SOLUSDT", "BUY", "ladder", "100.00", "0.2", now=1001)
    assert first == retry
    assert len(first) <= 36


def test_client_order_id_changes_for_distinct_intent():
    buy = client_order_id("SOLUSDT", "BUY", "ladder", "100.00", "0.2", now=1000)
    sell = client_order_id("SOLUSDT", "SELL", "ladder", "100.00", "0.2", now=1000)
    assert buy != sell
