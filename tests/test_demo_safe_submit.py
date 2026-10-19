import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from src.jobs.demo_safe_submit import submit_demo_buy

class TestSafeSubmission(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.old = os.environ.get('KALSHI_ENV')
        os.environ['KALSHI_ENV']='demo'
        self.tmp=tempfile.TemporaryDirectory()
        self.db=str(Path(self.tmp.name)/'trading.sqlite3')
        self.client=type('Client',(),{})()
        self.client.base_url='https://demo-api.kalshi.co'
        self.client.get_balance=AsyncMock(return_value={'balance':100000})
        self.client.place_order=AsyncMock(return_value={'order':{'order_id':'oid1'}})
        self.client._make_authenticated_request=AsyncMock(return_value={'orders':[]})
    def tearDown(self):
        if self.old is None: os.environ.pop('KALSHI_ENV',None)
        else: os.environ['KALSHI_ENV']=self.old
        self.tmp.cleanup()
    async def submit(self,**kw):
        return await submit_demo_buy(self.client,self.db,intent_key='intent1',ticker='TEST',side='YES',count=2,price_cents=20,confirm=True,**kw)
    async def test_success_and_duplicate_block(self):
        r=await self.submit()
        self.assertEqual(r['state'],'ACKNOWLEDGED_NOT_FILLED')
        with self.assertRaises(RuntimeError): await self.submit()
        self.assertEqual(self.client.place_order.await_count,1)
    async def test_ambiguous_error_no_retry(self):
        self.client.place_order.side_effect=TimeoutError('unknown')
        with self.assertRaises(TimeoutError): await self.submit()
        with self.assertRaises(RuntimeError): await self.submit()
        self.assertEqual(self.client.place_order.await_count,1)
    async def test_resting_block(self):
        self.client._make_authenticated_request.return_value={'orders':[{'ticker':'TEST'}]}
        with self.assertRaises(RuntimeError): await self.submit()
        self.client.place_order.assert_not_awaited()
    async def test_confirm_required(self):
        with self.assertRaises(PermissionError):
            await submit_demo_buy(self.client,self.db,intent_key='x',ticker='TEST',side='YES',count=1,price_cents=20)
    async def test_live_block(self):
        self.client.base_url='https://api.kalshi.com'
        with self.assertRaises(RuntimeError): await self.submit()
