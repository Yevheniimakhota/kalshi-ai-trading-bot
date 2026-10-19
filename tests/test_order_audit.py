import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from src.jobs.order_audit import audit_resting_orders, save_audit

class OrderAuditTests(unittest.TestCase):
    def test_order_on_position_market(self):
        report = audit_resting_orders([{'ticker': 'ABC', 'order_id': '1', 'side': 'bid', 'remaining_count_fp': '1.25'}], {('ABC', 'NO'): Decimal('2.15')})
        self.assertEqual(report['orders_on_position_markets'], 1)
        self.assertEqual(report['resting_orders'][0]['remaining_count'], '1.25')
        self.assertEqual(report['exchange_positions'][0]['quantity'], '2.15')
        self.assertFalse(report['automatic_exit_safe'])

    def test_missing_count_does_not_guess(self):
        report = audit_resting_orders([{'ticker': 'ABC', 'order_id': '1'}], {})
        self.assertIsNone(report['resting_orders'][0]['remaining_count'])
        self.assertEqual(report['orders_missing_remaining_count'], 1)

    def test_unrelated_orders_and_unknown_market(self):
        report = audit_resting_orders([{'ticker': 'OTHER'}, {'order_id': '2'}], {('ABC','YES'): Decimal(3)})
        self.assertEqual(report['orders_on_other_markets'], 1)
        self.assertEqual(report['orders_missing_market'], 1)

    def test_save_json_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            target = save_audit({'ok': True}, str(Path(directory) / 'trading_system_demo.db'))
            self.assertEqual(json.loads(Path(target).read_text())['ok'], True)

if __name__ == '__main__':
    unittest.main()
