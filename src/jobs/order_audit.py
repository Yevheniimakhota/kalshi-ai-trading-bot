"""Read-only audit of Kalshi Demo resting orders against exchange inventory.

This module NEVER places/cancels orders and NEVER infers cost basis or fills.
"""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import tempfile


def _nonnegative_decimal(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return number if number.is_finite() and number >= 0 else None


def _remaining(order):
    """Prefer exchange-provided remaining count; never guess from fills."""
    for key in ('remaining_count_fp', 'remaining_count', 'remaining_quantity_fp', 'remaining_quantity'):
        if key in order:
            return _nonnegative_decimal(order[key])
    return None


def audit_resting_orders(resting, inventory):
    """Return conservative, JSON-safe inventory/order audit.

    inventory maps (ticker, YES/NO) -> Decimal quantity. Kalshi v2 bid/ask
    does NOT, by itself, establish a position-closing order. Never subtract
    resting order quantities from available inventory here.
    """
    if not isinstance(resting, list):
        raise TypeError('resting must be a complete list of order objects')
    by_market = defaultdict(list)
    unknown_market = 0
    unknown_remaining = 0
    for item in resting:
        if not isinstance(item, dict):
            raise ValueError('Unexpected order object')
        ticker = item.get('ticker') or item.get('market_ticker')
        if not isinstance(ticker, str) or not ticker:
            unknown_market += 1
            continue
        count = _remaining(item)
        if count is None:
            unknown_remaining += 1
        # Never store full API payload, credentials, or unverified price fields.
        by_market[ticker].append({
            'order_id': str(item.get('order_id') or item.get('id') or ''),
            'side': str(item.get('side') or 'unknown'),
            'action': str(item.get('action') or 'unknown'),
            'remaining_count': str(count) if count is not None else None,
            'status': str(item.get('status') or 'resting'),
        })
    inventory_markets = {ticker for ticker, side in inventory}
    return {
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'exchange_positions': [
            {'ticker': ticker, 'side': side, 'quantity': str(qty),
             'resting_orders_on_market': len(by_market.get(ticker, []))}
            for (ticker, side), qty in sorted(inventory.items())
        ],
        'resting_order_count': len(resting),
        'orders_on_position_markets': sum(len(by_market.get(t, [])) for t in inventory_markets),
        'orders_on_other_markets': sum(len(orders) for t, orders in by_market.items() if t not in inventory_markets),
        'orders_missing_market': unknown_market,
        'orders_missing_remaining_count': unknown_remaining,
        'resting_orders': [order | {'ticker': ticker} for ticker, orders in sorted(by_market.items()) for order in orders],
        'automatic_exit_safe': False,
        'note': 'Order side/action and remaining count are informational only. No fill/cost-basis or reserved-contract conclusion.',
    }


def save_audit(report, db_path):
    """Write report beside the Demo database, replacing the previous snapshot."""
    path = Path(db_path).resolve().with_name('demo_order_audit.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.demo_order_audit_', suffix='.json', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            json.dump(report, file, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return str(path)
