import unittest
from decimal import Decimal
from src.utils.exchange_fill_pnl import calculate_fifo, AccountingIncomplete, extract_normalized_fill


def fill(fid, action, qty, price, fee='0', side='yes', ticker='T'):
    return dict(fill_id=fid, action=action, quantity=qty, price_dollars=price,
                fee_dollars=fee, side=side, ticker=ticker, created_time=f'2026-01-01T00:00:0{fid}Z')


class AccountingTests(unittest.TestCase):
    def calc(self, rows):
        return calculate_fifo(rows, history_complete=True, fees_verified=True)

    def test_partial_sale_and_fees(self):
        v = self.calc([fill('1','buy','5','.40','.10'), fill('2','sell','2','.60','.04')])[('T','yes')]
        self.assertEqual(v['realized_pnl'], Decimal('.32'))
        self.assertEqual(v['open_quantity'], Decimal('3'))
        self.assertEqual(v['open_cost_including_fees'], Decimal('1.26'))

    def test_no_side(self):
        v=self.calc([fill('1','buy','2','.80',side='no'),fill('2','sell','1','.90',side='no')])[('T','no')]
        self.assertEqual(v['realized_pnl'], Decimal('.10'))

    def test_duplicate(self):
        with self.assertRaises(AccountingIncomplete): self.calc([fill('1','buy','1','.4'), fill('1','buy','1','.4')])

    def test_unknown_lots(self):
        with self.assertRaises(AccountingIncomplete): self.calc([fill('1','sell','1','.4')])

    def test_incomplete_history(self):
        with self.assertRaises(AccountingIncomplete): calculate_fifo([],fees_verified=True)

    def test_unverified_fee_units(self):
        with self.assertRaises(AccountingIncomplete): calculate_fifo([],history_complete=True)

    def test_fractional(self):
        v=self.calc([fill('1','buy','2.15','.75','.02')])[('T','yes')]
        self.assertEqual(v['open_quantity'],Decimal('2.15'))

    def test_raw_fee_ambiguous(self):
        with self.assertRaises(AccountingIncomplete):
            extract_normalized_fill({'side':'yes','fee_cost':'200'})

if __name__ == '__main__':unittest.main()
