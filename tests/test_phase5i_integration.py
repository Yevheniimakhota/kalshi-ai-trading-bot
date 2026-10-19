"""Offline end-to-end integration of 5H modules, with no real API calls."""
import asyncio
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from src.jobs.demo_safe_submit import submit_demo_buy, _journal
from src.jobs.demo_order_lifecycle import reconcile_demo_orders, _db_path


class FakeDemoClient:
    base_url = 'https://demo-api.kalshi.co'

    def __init__(self):
        self.orders = []
        self.fills = []
        self.calls = 0
        self.fail_after_accept = False

    async def get_balance(self):
        return {'balance': 10000}

    async def place_order(self, **params):
        self.calls += 1
        oid = f'order-{self.calls}'
        self.orders.append({'order_id': oid, 'ticker': params['ticker'],
                            'side': params['side'], 'action': params['action'],
                            'status': 'resting', 'client_order_id': params['client_order_id']})
        if self.fail_after_accept:
            raise TimeoutError('simulated response lost after exchange accepted order')
        return {'order': {'order_id': oid}}

    async def _make_authenticated_request(self, method, endpoint, params=None):
        assert method == 'GET'
        params = params or {}
        if endpoint.endswith('/orders'):
            rows = self.orders
            if params.get('status'):
                rows = [x for x in rows if x['status'] == params['status']]
            if params.get('ticker'):
                rows = [x for x in rows if x['ticker'] == params['ticker']]
            return {'orders': rows, 'cursor': ''}
        if endpoint.endswith('/fills'):
            return {'fills': [x for x in self.fills if x['order_id'] == params.get('order_id')], 'cursor': ''}
        raise AssertionError(endpoint)


class Phase5IIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / 'trading.sqlite3')
        self.client = FakeDemoClient()
        self.env = patch.dict(os.environ, {'KALSHI_ENV': 'demo'})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()  # catches SQLite connection leaks on Windows

    async def submit(self, key='click-1'):
        return await submit_demo_buy(self.client, self.db_path, intent_key=key,
                                     ticker='TEST-MARKET', side='YES', count=2,
                                     price_cents=20, confirm=True)

    async def test_submit_reconcile_partial_restart_no_double_count(self):
        accepted = await self.submit()
        self.assertEqual(accepted['state'], 'ACKNOWLEDGED_NOT_FILLED')
        self.assertEqual(self.client.calls, 1)
        self.assertEqual(accepted['positions_updated'], 0)
        self.client.fills = [{'fill_id': 'fill-1', 'order_id': 'order-1',
                              'ticker': 'TEST-MARKET', 'count': 1}]
        first = await reconcile_demo_orders(self.client, self.db_path)
        second = await reconcile_demo_orders(self.client, self.db_path)
        for report in (first, second):
            self.assertEqual(report['orders_submitted'], 0)
            self.assertEqual(report['positions_updated'], 0)
            self.assertEqual(report['orders'][0]['filled_quantity'], '1')
            self.assertFalse(report['automatic_exit_safe'])
        self.assertEqual(self.client.calls, 1)
        with closing(sqlite3.connect(_db_path(self.db_path))) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM tracked_orders').fetchone()[0], 1)
        with self.assertRaises(RuntimeError):
            await self.submit()
        self.assertEqual(self.client.calls, 1)

    async def test_ambiguous_timeout_never_retries(self):
        self.client.fail_after_accept = True
        with self.assertRaises(TimeoutError):
            await self.submit()
        with closing(sqlite3.connect(_journal(self.db_path))) as db:
            state = db.execute('SELECT state FROM submission_intents').fetchone()[0]
        self.assertEqual(state, 'UNKNOWN_REQUIRES_RECONCILIATION')
        with self.assertRaises(RuntimeError):
            await self.submit()
        self.assertEqual(self.client.calls, 1)

    async def test_resting_order_blocks_other_intent(self):
        await self.submit()
        with self.assertRaises(RuntimeError):
            await self.submit('click-2')
        self.assertEqual(self.client.calls, 1)

    async def test_live_environment_blocks_before_submission(self):
        with patch.dict(os.environ, {'KALSHI_ENV': 'prod'}):
            with self.assertRaises(RuntimeError):
                await self.submit()
        self.assertEqual(self.client.calls, 0)

    async def test_live_url_blocks_before_submission(self):
        self.client.base_url = 'https://api.elections.kalshi.com'
        with self.assertRaises(RuntimeError):
            await self.submit()
        self.assertEqual(self.client.calls, 0)

    async def test_duplicate_fill_identity_unverified(self):
        await self.submit()
        f = {'fill_id': 'same-id', 'order_id': 'order-1', 'ticker': 'TEST-MARKET', 'count': 1}
        self.client.fills = [f, dict(f)]
        report = await reconcile_demo_orders(self.client, self.db_path)
        self.assertEqual(report['orders'][0]['state'], 'UNVERIFIED')
        self.assertIsNone(report['orders'][0]['filled_quantity'])

    async def test_no_confirmation_no_order(self):
        with self.assertRaises(PermissionError):
            await submit_demo_buy(self.client, self.db_path, intent_key='click',
                                  ticker='TEST-MARKET', side='YES', count=1,
                                  price_cents=20, confirm=False)
        self.assertEqual(self.client.calls, 0)


if __name__ == '__main__':
    unittest.main()
