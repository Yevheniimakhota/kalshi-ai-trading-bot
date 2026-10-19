"""Kalshi DEMO read-only exit preflight. Never grants execution permission."""
import json
import os
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from src.jobs.reconcile_demo import fetch_all, parse_market_position
from src.jobs.order_reservation_audit import audit_order_reservations


def _snapshot(positions, orders):
    inventory = {}
    for row in positions:
        ticker, side, qty = parse_market_position(row)
        if qty:
            key = (ticker, side)
            if key in inventory:
                raise ValueError(f'Duplicate position {key}')
            inventory[key] = qty
    audit = audit_order_reservations(orders, inventory)
    if audit['invalid_orders'] or audit['orders_on_markets_without_positions']:
        raise ValueError('Malformed or orphan resting orders')
    # Compare complete order fingerprints, not only their total quantities.
    fingerprint = []
    for order in orders:
        count = order.get('remaining_count_fp', order.get('remaining_count'))
        amount = Decimal(str(count))
        if not amount.is_finite() or amount < 0:
            raise ValueError('Invalid remaining_count')
        fingerprint.append((str(order.get('order_id')), str(order.get('ticker') or order.get('market_ticker')),
                            str(order.get('side')).upper(), str(order.get('action')).lower(),
                            str(order.get('status')).lower(), str(amount)))
    return inventory, audit, sorted(fingerprint)


async def run_demo_exit_preflight(client):
    if os.getenv('KALSHI_ENV', '').lower() != 'demo' or 'demo-api.kalshi.co' not in str(client.base_url).lower():
        raise RuntimeError('Exit preflight is restricted to Kalshi Demo')
    async def read():
        positions = await fetch_all(client, '/trade-api/v2/portfolio/positions', 'market_positions')
        orders = await fetch_all(client, '/trade-api/v2/portfolio/orders', 'orders', {'status': 'resting'})
        return _snapshot(positions, orders)
    first_inventory, first_audit, first_orders = await read()
    second_inventory, second_audit, second_orders = await read()
    stable = first_inventory == second_inventory and first_orders == second_orders
    results = []
    for entry in second_audit['positions']:
        reasons = list(entry['blocking_reasons'])
        if not stable:
            reasons.append('Position/order snapshots changed between consecutive reads')
        reasons.append('No exchange-authoritative available-to-sell confirmation')
        reasons.append('Cost basis and safe execution policy are not verified')
        results.append({'ticker': entry['ticker'], 'side': entry['side'],
                        'exchange_quantity': entry['exchange_quantity'],
                        'same_side_sell_remaining': entry['same_side_sell_remaining'],
                        'unreserved_quantity_candidate': entry['unreserved_quantity_candidate'],
                        'decision': 'BLOCKED', 'reasons': sorted(set(reasons))})
    return {'timestamp_utc': datetime.now(timezone.utc).isoformat(), 'mode': 'diagnostic_read_only',
            'two_reads_stable': stable, 'positions': results,
            'resting_order_count': second_audit['resting_order_count'],
            'automatic_exit_safe': False, 'orders_submitted': 0,
            'note': 'Repeated reads are not atomic. BLOCKED is mandatory; no authorization to trade.'}


def save_exit_preflight_report(report, db_path):
    path = Path(db_path).resolve().with_name('demo_exit_preflight_audit.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.demo_preflight_', suffix='.json', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(report, out, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return str(path)
