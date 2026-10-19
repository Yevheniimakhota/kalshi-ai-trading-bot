"""Conservative read-only Kalshi Demo order reservation audit.

This module DOES NOT establish exchange-authoritative available inventory.
It blocks automatic exits regardless of audit outcome.
"""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json
import os
import tempfile


def _nonnegative_decimal(value, label):
    if value is None or isinstance(value, bool):
        raise ValueError(f'{label}: missing or invalid')
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f'{label}: invalid decimal') from None
    if not number.is_finite() or number < 0:
        raise ValueError(f'{label}: must be finite and nonnegative')
    return number


def audit_order_reservations(resting_orders, inventory):
    """Estimate same-side sell reservations; block when other orders are ambiguous.

    inventory maps (ticker, YES/NO) to Decimal quantities. This report is
    advisory only and must never be used to authorize an exit order.
    """
    if not isinstance(resting_orders, list) or not isinstance(inventory, dict):
        raise TypeError('Expected orders list and inventory dict')
    holdings = {}
    for key, raw_qty in inventory.items():
        if not isinstance(key, tuple) or len(key) != 2:
            raise ValueError('Invalid inventory key')
        ticker, side = key
        if not isinstance(ticker, str) or not ticker or side not in ('YES', 'NO'):
            raise ValueError('Invalid inventory ticker or side')
        holdings[(ticker, side)] = _nonnegative_decimal(raw_qty, 'position quantity')

    grouped = defaultdict(list)
    seen_ids = set()
    invalid_orders = []
    for index, order in enumerate(resting_orders):
        if not isinstance(order, dict):
            invalid_orders.append({'index': index, 'reason': 'invalid order object'})
            continue
        ticker = order.get('ticker') or order.get('market_ticker')
        oid = order.get('order_id')
        if not isinstance(ticker, str) or not ticker:
            invalid_orders.append({'index': index, 'reason': 'missing ticker'})
            continue
        if not isinstance(oid, str) or not oid or oid in seen_ids:
            invalid_orders.append({'index': index, 'ticker': ticker, 'reason': 'missing/duplicate order_id'})
            grouped[ticker].append({'valid': False, 'reason': 'missing/duplicate order_id'})
            continue
        seen_ids.add(oid)
        side = str(order.get('side', '')).upper()
        action = str(order.get('action', '')).lower()
        status = str(order.get('status', '')).lower()
        count_value = order.get('remaining_count_fp', order.get('remaining_count'))
        try:
            count = _nonnegative_decimal(count_value, 'remaining_count')
        except ValueError:
            count = None
        valid = side in ('YES', 'NO') and action in ('buy', 'sell') and status == 'resting' and count is not None
        if not valid:
            invalid_orders.append({'index': index, 'ticker': ticker, 'order_id': oid, 'reason': 'invalid side/action/status/remaining_count'})
        grouped[ticker].append({'valid': valid, 'order_id': oid, 'side': side,
                                'action': action, 'remaining': count})

    results = []
    for (ticker, side), quantity in sorted(holdings.items()):
        orders = grouped.get(ticker, [])
        reserved = Decimal('0')
        blocking = []
        details = []
        for order in orders:
            if not order['valid']:
                blocking.append('Malformed or duplicate resting order on market')
                continue
            same_side_sell = order['action'] == 'sell' and order['side'] == side
            if same_side_sell:
                reserved += order['remaining']
                classification = 'same_side_sell_reservation_candidate'
            else:
                # Other orders may change exposure, collateral, or available inventory.
                # Never infer they are harmless from side/action alone.
                classification = 'other_order_requires_exchange_verification'
                blocking.append('Other resting order on market requires exchange reservation verification')
            details.append({'order_id': order['order_id'], 'side': order['side'],
                            'action': order['action'], 'remaining_count': str(order['remaining']),
                            'classification': classification})
        if reserved > quantity:
            blocking.append('Same-side sell orders exceed observed position')
        # A numerical lower bound on potentially unreserved inventory, not permission to trade.
        candidate = max(Decimal('0'), quantity - reserved)
        blocking.extend([
            'Order snapshot and position snapshot are not atomic',
            'Exchange reservation semantics and available-to-sell balance not verified',
            'Automatic exits disabled pending explicit safe execution design',
        ])
        results.append({'ticker': ticker, 'side': side, 'exchange_quantity': str(quantity),
                        'same_side_sell_remaining': str(reserved),
                        'unreserved_quantity_candidate': str(candidate),
                        'reservation_status': 'diagnostic_unverified',
                        'resting_orders_on_market': len(orders), 'order_details': details,
                        'blocking_reasons': sorted(set(blocking)),
                        'eligible_for_automatic_exits': False})
    markets_without_positions = sorted(set(grouped) - {key[0] for key in holdings})
    return {'timestamp_utc': datetime.now(timezone.utc).isoformat(),
            'mode': 'diagnostic_read_only', 'resting_order_count': len(resting_orders),
            'positions': results, 'invalid_orders': invalid_orders,
            'orders_on_markets_without_positions': markets_without_positions,
            'automatic_exit_safe': False,
            'note': 'Same-side sell quantity is a reservation candidate, not an exchange-verified available balance. No orders or DB writes.'}


def save_order_reservation_report(report, db_path):
    path = Path(db_path).resolve().with_name('demo_order_reservation_audit.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.demo_reservation_', suffix='.json', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return str(path)
