import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from src.jobs.demo_order_lifecycle import decimal_value, register_order, reconcile_demo_orders

class FakeClient:
    base_url='https://demo-api.kalshi.co'

class TestLifecycle(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=str(Path(self.tmp.name)/'demo.db')
        self.env=patch.dict(os.environ, {'KALSHI_ENV':'demo'})
        self.env.start()
    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()
    async def test_empty(self):
        result=await reconcile_demo_orders(FakeClient(),self.db)
        self.assertEqual(result['orders'],[])
        self.assertFalse(result['automatic_exit_safe'])
    async def test_scoped_partial_fill(self):
        register_order(self.db,order_id='id1',ticker='T',side='YES',action='sell')
        async def fetch(client,path,key,params=None):
            if key=='orders':
                return [{'order_id':'id1','ticker':'T','side':'yes','action':'sell','status':'resting'}]
            return [{'fill_id':'f1','order_id':'id1','ticker':'T','count_fp':'0.25'}]
        with patch('src.jobs.demo_order_lifecycle.fetch_all',fetch):
            result=await reconcile_demo_orders(FakeClient(),self.db)
        self.assertEqual(result['orders'][0]['filled_quantity'],'0.25')
        self.assertEqual(result['orders'][0]['state'],'RESTING')
    async def test_duplicate_fills_block(self):
        register_order(self.db,order_id='id1',ticker='T',side='NO',action='sell')
        async def fetch(client,path,key,params=None):
            if key=='orders':
                return [{'order_id':'id1','ticker':'T','side':'NO','action':'sell','status':'executed'}]
            return [{'fill_id':'f','order_id':'id1','ticker':'T','count':'1'}]*2
        with patch('src.jobs.demo_order_lifecycle.fetch_all',fetch):
            result=await reconcile_demo_orders(FakeClient(),self.db)
        self.assertEqual(result['orders'][0]['state'],'UNVERIFIED')
    async def test_reject_live(self):
        with patch.dict(os.environ,{'KALSHI_ENV':'live'}):
            with self.assertRaises(RuntimeError):
                await reconcile_demo_orders(FakeClient(),self.db)
    def test_duplicate_registration_identity(self):
        register_order(self.db,order_id='id1',ticker='T',side='YES',action='sell')
        with self.assertRaises(ValueError):
            register_order(self.db,order_id='id1',ticker='OTHER',side='YES',action='sell')
    def test_bad_numbers(self):
        for v in ('NaN','Infinity','-1',None,True):
            with self.assertRaises(ValueError): decimal_value(v)
if __name__=='__main__': unittest.main()
