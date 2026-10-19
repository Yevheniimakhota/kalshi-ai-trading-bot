import os
import sqlite3
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.jobs.reconcile_demo import parse_market_position
from src.jobs.sync_positions import sync_demo_positions


def test_signed_fractional_no():
    assert parse_market_position({'ticker': 'KXGREENTERRITORY-29-27', 'position_fp': '-2.15'}) == ('KXGREENTERRITORY-29-27', 'NO', Decimal('2.15'))


def test_signed_fractional_yes():
    assert parse_market_position({'ticker': 'X', 'position_fp': '0.75'}) == ('X', 'YES', Decimal('0.75'))


@pytest.mark.asyncio
async def test_startup_and_repeat_sync(tmp_path, monkeypatch):
    monkeypatch.setenv('KALSHI_ENV', 'demo')
    path = tmp_path / 'test.db'
    with sqlite3.connect(path) as con:
        con.execute('''CREATE TABLE positions (id INTEGER PRIMARY KEY, market_id TEXT NOT NULL, side TEXT NOT NULL,
          entry_price REAL NOT NULL, quantity INTEGER NOT NULL, timestamp TEXT NOT NULL, rationale TEXT,
          confidence REAL, live BOOLEAN NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'open', strategy TEXT,
          stop_loss_price REAL, take_profit_price REAL, max_hold_hours INTEGER, target_confidence_change REAL,
          UNIQUE(market_id, side))''')
    class Client:
        base_url = 'https://demo-api.kalshi.co'
        async def _make_authenticated_request(self, method, endpoint, params):
            if endpoint.endswith('/positions'):
                return {'market_positions': [{'ticker': 'KXGREENTERRITORY-29-27', 'position_fp': '-2.15'}]}
            return {'orders': []}
    db = SimpleNamespace(db_path=str(path))
    first = await sync_demo_positions(db, Client())
    second = await sync_demo_positions(db, Client())
    assert first['added'] == 1
    assert second['added'] == 0 and second['updated'] == 1
    with sqlite3.connect(path) as con:
        row = con.execute('SELECT side, quantity, strategy, status FROM positions').fetchone()
    assert row == ('NO', 2.15, 'exchange_unmanaged', 'open')
