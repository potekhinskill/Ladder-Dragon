from copy import deepcopy
import hashlib
import json
import sqlite3

import pytest
import requests

from ladder_dragon.verification.bnb_fills_command import ProbeSession, main, selected_rows, verify_rows


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "stats.db"
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE trades(symbol,side,price_text,gross_qty,ts,trade_id,commission_asset,commission_amount)")
        con.execute("INSERT INTO trades VALUES('SOLUSDT','BUY','100','1',1000,3,'BNB','0.001')")
    return path


class Client:
    def __init__(self, change=None):
        self.trade = dict(symbol="SOLUSDT", id=3, orderId=8, time=1000, isBuyer=True,
                          price="100", qty="1", commissionAsset="BNB", commission="0.001")
        self.trade.update(change or {})

    def signed(self, method, path, params, timeout):
        assert (method, path, params, timeout) == ("GET", "/api/v3/myTrades", {"symbol":"SOLUSDT", "fromId":3, "limit":1}, 5)
        return [self.trade]


def test_match_is_readonly(database):
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    result = verify_rows(selected_rows(database, 100), Client())
    assert result == dict(selected=1, checked=1, matched=1, missing=0, mismatched=0)
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("change", [dict(price="101"),dict(qty="2"),dict(time=1001),
    dict(isBuyer=False),dict(commission="0.002"),dict(commissionAsset="USDT")])
def test_original_fields_must_match(database, change):
    assert verify_rows(selected_rows(database, 100), Client(change))["mismatched"] == 1


@pytest.mark.parametrize("change", [dict(symbol="ETHUSDT"),dict(orderId=True),dict(time=None),dict(isBuyer="false")])
def test_damaged_response_rejected(database, change):
    with pytest.raises(ValueError):
        verify_rows(selected_rows(database,100),Client(change))


def test_next_exchange_trade_is_not_the_requested_fill(database):
    assert verify_rows(selected_rows(database,100),Client(dict(id=4)))["missing"] == 1


def test_local_capacity_and_duplicate_rejected(database):
    with sqlite3.connect(database) as con:
        con.execute("INSERT INTO trades SELECT * FROM trades")
    for cap in (1,100):
        with pytest.raises(ValueError): selected_rows(database,cap)


def test_missing_database_is_not_created(tmp_path):
    path=tmp_path/'absent.db'
    with pytest.raises(sqlite3.Error): selected_rows(path,100)
    assert not path.exists()


@pytest.mark.parametrize("method,url", [("POST","https://api.binance.com/api/v3/myTrades"),
    ("GET","https://api.binance.com/api/v3/order"),("GET","https://other.example/api/v3/myTrades")])
def test_transport_blocks_mutations_and_other_endpoints(method,url):
    with ProbeSession(100) as session:
        with pytest.raises(RuntimeError): session.request(method,url)
        assert session.calls==0


def test_request_budget_includes_retries_and_rejects_redirect(monkeypatch):
    class Response:
        status_code=302
        def close(self): self.closed=True
    response=Response()
    def request(self,method,url,**kwargs):
        assert kwargs['allow_redirects'] is False and kwargs['stream'] is True
        return response
    monkeypatch.setattr(requests.Session,'request',request)
    with ProbeSession(1) as session:
        with pytest.raises(RuntimeError,match='REDIRECT'):session.get('https://api.binance.com/api/v3/time')
        with pytest.raises(RuntimeError,match='BUDGET'):session.get('https://api.binance.com/api/v3/time')
        assert session.calls==1 and response.closed


def test_main_does_not_print_failure_secrets(database,monkeypatch,capsys):
    from ladder_dragon.verification import bnb_fills_command as module
    monkeypatch.setenv('DASHBOARD_BINANCE_API_KEY','test')
    monkeypatch.setenv('DASHBOARD_BINANCE_API_SECRET','test')
    def fail(*args): raise requests.ConnectionError('PRIVATE_TEST_MARKER?signature=secret')
    monkeypatch.setattr(module,'verify_rows',fail)
    assert main(['--stats-db',str(database)])==2
    output=capsys.readouterr().out
    assert 'PRIVATE_TEST_MARKER' not in output and 'signature' not in output
    assert json.loads(output)['replay_allowed'] is False
