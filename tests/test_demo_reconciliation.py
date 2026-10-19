import pytest
from src.jobs.reconcile_demo import compare, fetch_all, parse_market_position


def test_signed_yes_no_positions():
    assert parse_market_position({'ticker':'A', 'position':-6}) == ('A','NO',6)
    assert parse_market_position({'ticker':'B', 'position':5}) == ('B','YES',5)
    assert parse_market_position({'ticker':'C', 'position':0}) == ('C',None,0)


def test_reconciliation_does_not_treat_closed_local_as_open():
    local=[{'market_id':'A','side':'NO','quantity':5,'status':'closed','live':1}]
    differences, errors=compare([{'ticker':'A','position':-6}],local)
    assert not errors
    assert differences[0]['result']=='mismatch'
    assert differences[0]['exchange_quantity']==6
    assert differences[0]['local_open_quantity']==0


def test_unknown_format_is_reported_not_guessed():
    differences, errors=compare([{'ticker':'A','weird_qty':4}],[])
    assert not differences
    assert len(errors)==1


@pytest.mark.asyncio
async def test_cursor_pagination():
    class Client:
        def __init__(self): self.calls=[]
        async def _make_authenticated_request(self, method, endpoint, params):
            self.calls.append(dict(params))
            if 'cursor' not in params:
                return {'market_positions':[{'ticker':'A','position':2}],'cursor':'next'}
            return {'market_positions':[{'ticker':'B','position':-3}],'cursor':''}
    c=Client()
    data=await fetch_all(c,'/portfolio/positions','market_positions')
    assert len(data)==2
    assert c.calls[1]['cursor']=='next'
