from copy import deepcopy
import pytest

from bin.verify_bnb_fills import complete_order, verify_rows, selected_rows, ProbeSession
from tests.test_verify_bnb_fills import Client, database


class OrderClient(Client):
    def __init__(self):
        super().__init__()
        self.trade['quoteQty']='100'
        self.order=dict(symbol='SOLUSDT',orderId=8,side='BUY',status='FILLED',origQty='1',executedQty='1',cummulativeQuoteQty='100')
        self.fills=[deepcopy(self.trade)]
        self.order_reads=0
    def signed(self,method,path,params,timeout):
        assert method=='GET'
        if path=='/api/v3/order':
            self.order_reads+=1
            return self.order
        if 'orderId' in params: return self.fills
        return super().signed(method,path,params,timeout)


def test_complete_order_chain(database):
    client=OrderClient()
    result=verify_rows(selected_rows(database,100),client,verify_orders=True)
    assert result['matched']==1 and result['complete_orders']==1


@pytest.mark.parametrize('change',[dict(orderId=9),dict(symbol='ETHUSDT'),dict(status='NEW'),
    dict(executedQty='0.5'),dict(origQty='0'),dict(cummulativeQuoteQty='99'),dict(side='SELL')])
def test_order_mutations_rejected(change):
    client=OrderClient();client.order.update(change)
    with pytest.raises(ValueError):complete_order(client,'SOLUSDT',8)


@pytest.mark.parametrize('change',[dict(orderId=9),dict(symbol='ETHUSDT'),dict(isBuyer=False),
    dict(qty='0.5',quoteQty='50'),dict(quoteQty='99'),dict(time=None),dict(price='1e2')])
def test_fill_mutations_rejected(change):
    client=OrderClient();client.fills[0].update(change)
    with pytest.raises(ValueError):complete_order(client,'SOLUSDT',8)


@pytest.mark.parametrize('mode',['empty','duplicate','oversized'])
def test_fill_collection_is_bounded_and_unique(mode):
    client=OrderClient();client.fills*= {'empty':0,'duplicate':2,'oversized':1001}[mode]
    with pytest.raises(ValueError):complete_order(client,'SOLUSDT',8)


def test_changed_fee_between_reads_rejected(database):
    client=OrderClient();client.fills[0]['commission']='0.002'
    with pytest.raises(ValueError,match='CHANGED_BETWEEN'):verify_rows(selected_rows(database,100),client,verify_orders=True)


def test_terminal_partial_and_shared_order_cache(database):
    client=OrderClient();client.order.update(status='CANCELED',origQty='2')
    rows=selected_rows(database,100)
    assert verify_rows(rows+rows,client,verify_orders=True)['complete_orders']==1
    assert client.order_reads==1


def test_order_capability_never_permits_mutation():
    with ProbeSession(300,verify_orders=True) as session:
        for method in ('POST','DELETE','PUT'):
            with pytest.raises(RuntimeError):session.request(method,'https://api.binance.com/api/v3/order')
        assert session.calls==0
