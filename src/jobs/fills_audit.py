"""Kalshi Demo fills audit: read-only, no inferred realized P&L or entry price.

A complete paginated API snapshot is required. Reports are deliberately
conservative: old fills can be missing from the accessible history, and
opposing orders do not prove a closing trade.
"""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import tempfile


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return d if d.is_finite() and d >= 0 else None


def fill_quantity(row):
    # Never interpret a field named `count` if a fixed-point field exists.
    for field in ('count_fp', 'quantity_fp', 'count', 'quantity'):
        if field in row:
            return number(row[field])
    return None


def build_fills_report(fills, inventory, resting):
    if not isinstance(fills, list):
        raise TypeError('Fills must be a list')
    per_market = defaultdict(list)
    bad = 0
    ids = set()
    duplicates = 0
    for fill in fills:
        if not isinstance(fill, dict):
            raise ValueError('Invalid fill object')
        ticker = fill.get('ticker') or fill.get('market_ticker')
        fid = fill.get('fill_id') or fill.get('trade_id')
        if fid:
            if str(fid) in ids:
                duplicates += 1
                continue
            ids.add(str(fid))
        qty = fill_quantity(fill)
        if not isinstance(ticker, str) or not ticker or qty is None or qty == 0:
            bad += 1
            continue
        # V1 side/action and V2 bid/ask semantics vary. Preserve raw fields;
        # don't classify an execution as opening or closing a YES/NO position.
        per_market[ticker].append({
            'fill_id': str(fid) if fid else None,
            'order_id': str(fill.get('order_id')) if fill.get('order_id') else None,
            'quantity': str(qty),
            'side': str(fill.get('side') or 'unknown'),
            'action': str(fill.get('action') or 'unknown'),
            'created_time': str(fill.get('created_time') or fill.get('ts') or ''),
            'price_fields_present': sorted(k for k in fill if k in ('yes_price','no_price','price','price_dollars','yes_price_dollars','no_price_dollars')),
        })
    resting_ids = {str(o.get('order_id') or o.get('id')) for o in resting if isinstance(o, dict) and (o.get('order_id') or o.get('id'))}
    return {
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'exchange_positions': [
            {'ticker': ticker, 'side': side, 'quantity': str(qty),
             'observed_fill_count_on_market': len(per_market.get(ticker, [])),
             'cost_basis_status': 'unverified', 'entry_price': None}
            for (ticker, side), qty in sorted(inventory.items())
        ],
        'total_fills_returned': len(fills),
        'valid_fills': sum(map(len, per_market.values())),
        'invalid_or_incomplete_fills': bad,
        'duplicate_fill_ids': duplicates,
        'fills_linked_to_resting_orders': sum(1 for group in per_market.values() for f in group if f['order_id'] in resting_ids),
        'resting_order_count': len(resting),
        'fills_by_market': {ticker: group for ticker, group in sorted(per_market.items())},
        'entry_prices_verified': 0,
        'automatic_exit_safe': False,
        'note': 'Historical fills alone cannot prove current open-lot cost basis. No entry price, P&L, or reserved quantity inferred. No orders placed.',
    }


async def fetch_all_fills(client, max_pages=100, page_size=100):
    if 'demo-api.kalshi.co' not in str(client.base_url).lower():
        raise RuntimeError('Fills audit requires Kalshi Demo')
    cursor = None
    seen = set()
    result = []
    for _ in range(max_pages):
        params = {'limit': page_size}
        if cursor:
            params['cursor'] = cursor
        payload = await client._make_authenticated_request('GET', '/trade-api/v2/portfolio/fills', params=params)
        if not isinstance(payload, dict) or not isinstance(payload.get('fills'), list):
            raise ValueError('Malformed fills response')
        result.extend(payload['fills'])
        next_cursor = payload.get('cursor')
        if not next_cursor:
            return result
        if not isinstance(next_cursor, str) or next_cursor in seen:
            raise ValueError('Repeated/invalid fills cursor')
        seen.add(next_cursor)
        cursor = next_cursor
    raise RuntimeError('Fills pagination exceeded safety limit; incomplete snapshot')


async def audit_demo_fills(client, inventory, resting):
    fills = await fetch_all_fills(client)
    return build_fills_report(fills, inventory, resting)


def save_fills_audit(report, db_path):
    path = Path(db_path).resolve().with_name('demo_fills_audit.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.demo_fills_', suffix='.json', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return str(path)
