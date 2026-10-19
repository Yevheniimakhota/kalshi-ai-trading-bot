import unittest
from decimal import Decimal
from src.jobs.cost_basis_audit import audit_cost_basis


def fill(fid, side, action, count, yes='0.25', no='0.75', ts='2026-10-15T00:00:00Z'):
    return {'fill_id': fid, 'ticker': 'A', 'side': side, 'action': action,
            'count_fp': count, 'yes_price_dollars': yes, 'no_price_dollars': no,
            'created_time': ts}


class CostAuditTests(unittest.TestCase):
    def test_yes_fractional(self):
        r = audit_cost_basis([fill('a', 'yes', 'buy', '29.81')], {('A', 'YES'): Decimal('29.81')})
        p = r['positions'][0]
        self.assertEqual(p['indicative_fifo_entry_price_dollars'], '0.25')
        self.assertIsNone(p['entry_price_verified'])
        self.assertFalse(r['automatic_exit_safe'])

    def test_no_partial_offset_fifo(self):
        r = audit_cost_basis([fill('a', 'no', 'sell', '20'), fill('b', 'yes', 'buy', '9', ts='2026-10-16T00:00:00Z')],
                             {('A', 'NO'): Decimal('11')})
        self.assertTrue(r['positions'][0]['quantity_matches_hypothesis'])
        self.assertEqual(r['positions'][0]['indicative_fifo_entry_price_dollars'], '0.75')

    def test_missing_price_not_guessed(self):
        row = fill('a', 'yes', 'buy', '2')
        del row['yes_price_dollars']
        r = audit_cost_basis([row], {('A', 'YES'): Decimal('2')})
        self.assertIsNone(r['positions'][0]['indicative_fifo_entry_price_dollars'])

    def test_quantity_mismatch_blocks_price(self):
        r = audit_cost_basis([fill('a', 'yes', 'buy', '2')], {('A', 'YES'): Decimal('3')})
        self.assertIsNone(r['positions'][0]['indicative_fifo_entry_price_dollars'])

    def test_duplicate_fills_fail(self):
        with self.assertRaises(ValueError):
            audit_cost_basis([fill('a', 'yes', 'buy', '1'), fill('a', 'yes', 'buy', '1')], {})

    def test_unsupported_semantics_fail(self):
        with self.assertRaises(ValueError):
            audit_cost_basis([fill('a', 'no', 'buy', '1')], {})

    def test_fractional_no(self):
        r = audit_cost_basis([fill('a', 'no', 'sell', '2.15')], {('A', 'NO'): Decimal('2.15')})
        self.assertEqual(r['positions'][0]['indicative_fifo_entry_price_dollars'], '0.75')


if __name__ == '__main__':
    unittest.main()
