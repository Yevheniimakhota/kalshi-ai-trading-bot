"""Regression tests for Kalshi legacy action vs canonical outcome_side."""
import csv
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from src.jobs.demo_owned_lots import verified_bot_lot, OwnershipUnverified

OID = 'bot-demo-order-001'
TICKER = 'TEST-MARKET-1'


def fill(count='2.00', price='0.9830', *, oid=OID, outcome='no', book='ask',
         action='sell', fid='fill-1', fee='0.0024', ticker=TICKER):
    return dict(ticker=ticker, side='no', action=action,
                order_id=oid, outcome_side=outcome, book_side=book,
                fill_id=fid, count_fp=count, no_price_dollars=price,
                fee_cost=fee)


class TestCanonicalOwnership(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = str(Path(self.tmp.name) / 'trading_system_demo.db')
        journal = str(Path(self.tmp.name) / 'demo_submission_intents.sqlite3')
        with sqlite3.connect(journal) as con:
            con.execute('CREATE TABLE submission_intents (intent_key TEXT PRIMARY KEY, order_id TEXT, state TEXT, ticker TEXT, side TEXT)')
            con.execute('INSERT INTO submission_intents VALUES (?, ?, ?, ?, ?)',
                        ('original_strategy_position_20', OID, 'ACKNOWLEDGED', TICKER, 'NO'))

    def run_lot(self, fills, qty='2.00'):
        return verified_bot_lot(self.db_path, 20, TICKER, 'NO', Decimal(qty), fills)

    def test_legacy_sell_no_is_bot_buy_no_with_canonical_no(self):
        lot = self.run_lot([fill()])
        self.assertEqual(lot['entry_price'], Decimal('0.9830'))
        self.assertEqual(lot['quantity'], Decimal('2.00'))
        self.assertEqual(lot['buy_fees'], Decimal('0.0024'))

    def test_ordinary_buy_legacy_is_also_accepted_if_canonical_matches(self):
        self.assertEqual(self.run_lot([fill(action='buy')])['order_id'], OID)

    def test_partial_fills_join_by_order_id(self):
        two = [fill(count='0.75', price='0.96', fid='one', fee='0.0010'),
               fill(count='1.25', price='0.98', fid='two', fee='0.0015')]
        r = self.run_lot(two)
        self.assertEqual(r['quantity'], Decimal('2.00'))
        self.assertEqual(r['entry_price'], (Decimal('0.75')*Decimal('0.96') + Decimal('1.25')*Decimal('0.98'))/Decimal('2.00'))

    def test_manual_fill_same_market_makes_unmanaged(self):
        with self.assertRaises(OwnershipUnverified):
            self.run_lot([fill(), fill(count='0.01', oid='manual-order', fid='manual')])

    def test_opposite_canonical_side_makes_unmanaged(self):
        with self.assertRaises(OwnershipUnverified):
            self.run_lot([fill(outcome='yes',book='bid')])

    def test_contradictory_canonical_values_rejected(self):
        with self.assertRaises(OwnershipUnverified):
            self.run_lot([fill(outcome='no',book='bid')])

    def test_missing_canonical_fields_rejected(self):
        with self.assertRaises(OwnershipUnverified):
            self.run_lot([fill(book='')])

    def test_quantity_mismatch_rejected(self):
        with self.assertRaises(OwnershipUnverified):
            self.run_lot([fill(count='1.99')])

    def test_duplicate_fill_rejected(self):
        with self.assertRaises(OwnershipUnverified):
            self.run_lot([fill(count='1'), fill(count='1')])

    def test_negative_fee_rejected(self):
        with self.assertRaises(OwnershipUnverified):
            self.run_lot([fill(fee='-1')])

    def test_other_ticker_not_attributed(self):
        with self.assertRaises(OwnershipUnverified):
            self.run_lot([fill(ticker='OTHER-MARKET')])


if __name__ == '__main__':
    unittest.main()
