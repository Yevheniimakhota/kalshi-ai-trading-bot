import unittest
from decimal import Decimal
from src.jobs.exit_preflight_audit import _snapshot

class PreflightTests(unittest.TestCase):
    def test_empty_snapshot(self):
        inv, report, orders = _snapshot([], [])
        self.assertEqual(inv, {})
        self.assertEqual(orders, [])
        self.assertFalse(report['automatic_exit_safe'])

    def test_invalid_order_blocks(self):
        with self.assertRaises(ValueError):
            _snapshot([], [{'ticker':'A','order_id':'x','side':'YES','action':'sell','status':'resting','remaining_count_fp':'NaN'}])

    def test_orphan_order_blocks(self):
        with self.assertRaises(ValueError):
            _snapshot([], [{'ticker':'A','order_id':'x','side':'YES','action':'sell','status':'resting','remaining_count_fp':'1'}])
