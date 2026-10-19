import unittest
from decimal import Decimal
from src.jobs.replay_audit import replay_fills


def fill(fid, ticker, side, action, count, ts='2026-10-15T00:00:00Z'):
    return {'fill_id': fid, 'ticker': ticker, 'side': side, 'action': action,
            'count_fp': count, 'created_time': ts}


class ReplayAuditTests(unittest.TestCase):
    def test_yes_fractional(self):
        report = replay_fills([fill('1', 'A', 'yes', 'buy', '29.81')], {('A', 'YES'): Decimal('29.81')})
        self.assertTrue(report['positions'][0]['quantity_reconciles_under_hypothesis'])
        self.assertIsNone(report['positions'][0]['entry_price'])
        self.assertFalse(report['automatic_exit_safe'])

    def test_no_from_yes_buy_and_no_sell(self):
        fills = [fill('1', 'A', 'no', 'sell', '20'), fill('2', 'A', 'yes', 'buy', '9')]
        report = replay_fills(fills, {('A', 'NO'): Decimal('11')})
        self.assertEqual(report['positions'][0]['replayed_signed_yes_exposure'], '-11')
        self.assertTrue(report['positions'][0]['quantity_reconciles_under_hypothesis'])

    def test_mismatch_is_not_verified(self):
        report = replay_fills([fill('1', 'A', 'yes', 'buy', '2')], {('A', 'YES'): Decimal('3')})
        self.assertEqual(report['positions'][0]['quantity_status'], 'unreconciled')

    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            replay_fills([fill('1', 'A', 'yes', 'buy', '1'), fill('1', 'A', 'yes', 'buy', '1')], {})

    def test_ambiguous_side_rejected(self):
        with self.assertRaises(ValueError):
            replay_fills([fill('1', 'A', 'no', 'buy', '1')], {})

    def test_no_fills_not_reconciled(self):
        report = replay_fills([], {('A', 'YES'): Decimal('0.5')})
        self.assertFalse(report['positions'][0]['quantity_reconciles_under_hypothesis'])


if __name__ == '__main__':
    unittest.main()
