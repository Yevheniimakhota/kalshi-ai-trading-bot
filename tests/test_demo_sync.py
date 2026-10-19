"""Pure API-shape checks; integration tests require the project's dependencies."""
import pytest
from src.jobs.reconcile_demo import parse_market_position, fetch_all


def test_yes_no_inventory():
    assert parse_market_position({'ticker': 'A', 'position': -5}) == ('A', 'NO', 5)
    assert parse_market_position({'ticker': 'B', 'position': 3}) == ('B', 'YES', 3)


def test_unknown_representation_rejected():
    with pytest.raises(ValueError):
        parse_market_position({'ticker': 'A'})


@pytest.mark.asyncio
async def test_pagination_is_complete():
    class Fake:
        async def _make_authenticated_request(self, method, endpoint, params):
            if params.get('cursor') == 'next':
                return {'market_positions': [{'ticker': 'B', 'position': -2}]}
            return {'market_positions': [{'ticker': 'A', 'position': 1}], 'cursor': 'next'}
    rows = await fetch_all(Fake(), '/trade-api/v2/portfolio/positions', 'market_positions')
    assert len(rows) == 2
