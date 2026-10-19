import unittest
from decimal import Decimal
from src.jobs.fills_audit import build_fills_report, fetch_all_fills

class AuditTests(unittest.TestCase):
    def test_fractional_fills_and_unknown_basis(self):
        r=build_fills_report([{'ticker':'ABC','fill_id':'a','count_fp':'2.15','side':'no','action':'buy'}],{('ABC','NO'):Decimal('2.15')},[])
        self.assertEqual(r['valid_fills'],1)
        self.assertEqual(r['fills_by_market']['ABC'][0]['quantity'],'2.15')
        self.assertIsNone(r['exchange_positions'][0]['entry_price'])
        self.assertFalse(r['automatic_exit_safe'])
    def test_duplicate_fill_id(self):
        fill={'ticker':'ABC','fill_id':'a','count_fp':'1'}
        r=build_fills_report([fill,fill],{},[])
        self.assertEqual(r['duplicate_fill_ids'],1)
    def test_invalid_count(self):
        r=build_fills_report([{'ticker':'ABC','count_fp':'NaN'}],{},[])
        self.assertEqual(r['invalid_or_incomplete_fills'],1)

class PaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_pagination(self):
        class Fake:
            base_url='https://demo-api.kalshi.co'
            async def _make_authenticated_request(self,method,path,params=None):
                return {'fills':[{'ticker':'ABC','count_fp':'1'}], 'cursor':'next'} if 'cursor' not in params else {'fills':[{'ticker':'ABC','count_fp':'2'}], 'cursor':''}
        self.assertEqual(len(await fetch_all_fills(Fake())),2)
    async def test_repeated_cursor_fails(self):
        class Fake:
            base_url='https://demo-api.kalshi.co'
            async def _make_authenticated_request(self,method,path,params=None):
                return {'fills':[], 'cursor':'same'}
        with self.assertRaises(ValueError):
            await fetch_all_fills(Fake())
if __name__=='__main__': unittest.main()
