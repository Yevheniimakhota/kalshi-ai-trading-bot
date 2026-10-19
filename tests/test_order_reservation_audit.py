import unittest
from decimal import Decimal
from src.jobs.order_reservation_audit import audit_order_reservations


class ReservationTests(unittest.TestCase):
    def test_full_sell_reservation(self):
        report = audit_order_reservations([{'order_id':'a','ticker':'LOL','side':'yes','action':'sell','status':'resting','remaining_count':'29.81'}], {('LOL','YES'): Decimal('29.81')})
        p = report['positions'][0]
        self.assertEqual(p['same_side_sell_remaining'], '29.81')
        self.assertEqual(Decimal(p['unreserved_quantity_candidate']), Decimal('0'))
        self.assertFalse(report['automatic_exit_safe'])

    def test_other_order_blocks(self):
        p = audit_order_reservations([{'order_id':'a','ticker':'T','side':'yes','action':'buy','status':'resting','remaining_count':'2'}], {('T','NO'):Decimal('3')})['positions'][0]
        self.assertTrue(any('Other resting order' in x for x in p['blocking_reasons']))
        self.assertFalse(p['eligible_for_automatic_exits'])

    def test_oversell_blocks(self):
        p = audit_order_reservations([{'order_id':'a','ticker':'T','side':'yes','action':'sell','status':'resting','remaining_count':'4'}], {('T','YES'):Decimal('3')})['positions'][0]
        self.assertIn('Same-side sell orders exceed observed position', p['blocking_reasons'])

    def test_fractional_exact(self):
        orders = [{'order_id':'a','ticker':'T','side':'no','action':'sell','status':'resting','remaining_count':'0.10'}, {'order_id':'b','ticker':'T','side':'no','action':'sell','status':'resting','remaining_count':'0.20'}]
        p = audit_order_reservations(orders, {('T','NO'):Decimal('0.30')})['positions'][0]
        self.assertEqual(Decimal(p['unreserved_quantity_candidate']), Decimal('0'))

    def test_invalid_does_not_authorize(self):
        p = audit_order_reservations([{'order_id':'a','ticker':'T','side':'yes','action':'sell','status':'resting','remaining_count':'NaN'}], {('T','YES'):Decimal('2')})
        self.assertEqual(len(p['invalid_orders']), 1)
        self.assertFalse(p['automatic_exit_safe'])

    def test_duplicate_order_detected(self):
        orders = [{'order_id':'a','ticker':'T','side':'yes','action':'sell','status':'resting','remaining_count':'1'}] * 2
        self.assertEqual(len(audit_order_reservations(orders, {('T','YES'):Decimal('3')})['invalid_orders']), 1)


if __name__ == '__main__':
    unittest.main()
