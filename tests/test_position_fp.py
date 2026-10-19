import pytest
from src.jobs.reconcile_demo import parse_market_position

@pytest.mark.parametrize('row,expected', [
    ({'ticker':'YES-MARKET','position_fp':'5.00'}, ('YES-MARKET','YES',5)),
    ({'ticker':'NO-MARKET','position_fp':'-6.00'}, ('NO-MARKET','NO',6)),
    ({'ticker':'ZERO','position_fp':'0.00'}, ('ZERO',None,0)),
    ({'ticker':'OLD','position':-2}, ('OLD','NO',2)),
    ({'ticker':'SEPARATE','yes_count_fp':'3.00'}, ('SEPARATE','YES',3)),
    ({'ticker':'SEPARATE-NO','no_count_fp':'4.00'}, ('SEPARATE-NO','NO',4)),
])
def test_supported_position_formats(row,expected):
    assert parse_market_position(row)==expected

@pytest.mark.parametrize('row', [
    {'ticker':'A','position_fp':'1.25'},
    {'ticker':'A','position_fp':'nan'},
    {'ticker':'A','yes_count':2,'no_count':3},
    {'ticker':'A'},
])
def test_unsafe_positions_rejected(row):
    with pytest.raises(ValueError):
        parse_market_position(row)
