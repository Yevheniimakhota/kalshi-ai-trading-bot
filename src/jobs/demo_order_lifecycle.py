"""Read-only Kalshi Demo order lifecycle reconciliation.

Never submits/cancels orders and never changes positions/trade_logs.
A tracked order must be explicitly registered by exchange order ID.
"""
import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

async def fetch_all(client, endpoint, key, params=None):
    """Fetch all pages; reject malformed or looping pagination."""
    result, seen = [], set()
    cursor = None
    for _ in range(100):
        query = dict(params or {})
        query['limit'] = 100
        if cursor:
            query['cursor'] = cursor
        data = await client._make_authenticated_request('GET', endpoint, params=query)
        if not isinstance(data, dict) or not isinstance(data.get(key), list):
            raise ValueError(f'Invalid {key} API response')
        result.extend(data[key])
        next_cursor = data.get('cursor')
        if not next_cursor:
            return result
        if not isinstance(next_cursor, str) or next_cursor in seen:
            raise ValueError('Invalid or repeated API cursor')
        seen.add(next_cursor)
        cursor = next_cursor
    raise ValueError('Pagination limit exceeded')


def decimal_value(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('missing or invalid numeric value')
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('invalid numeric value') from None
    if not d.is_finite() or d < 0:
        raise ValueError('nonfinite or negative value')
    return d


def _demo(client):
    if os.getenv('KALSHI_ENV', '').lower() != 'demo':
        raise RuntimeError('Demo only')
    url = str(getattr(client, 'base_url', '')).lower().rstrip('/')
    if not (url.startswith('https://demo-api.kalshi.co/') or url == 'https://demo-api.kalshi.co'):
        raise RuntimeError('Demo API URL required')


def _db_path(db_path):
    return str(Path(db_path).with_name('demo_order_lifecycle.sqlite3'))


def initialize(db_path):
    """Separate journal; existing trading database schema remains untouched."""
    with closing(sqlite3.connect(_db_path(db_path), timeout=15)) as db, db:
        db.execute('''CREATE TABLE IF NOT EXISTS tracked_orders (
            order_id TEXT PRIMARY KEY, ticker TEXT NOT NULL,
            side TEXT NOT NULL CHECK(side IN ('YES','NO')),
            action TEXT NOT NULL CHECK(action IN ('buy','sell')),
            state TEXT NOT NULL DEFAULT 'UNVERIFIED',
            filled_quantity TEXT, last_error TEXT, updated_at TEXT NOT NULL
        )''')


def register_order(db_path, *, order_id, ticker, side, action):
    """Manually register an existing exchange order; no API mutation."""
    if not all(isinstance(x, str) and x.strip() for x in (order_id, ticker, side, action)):
        raise ValueError('order identity required')
    side, action = side.upper(), action.lower()
    if side not in ('YES', 'NO') or action not in ('buy', 'sell'):
        raise ValueError('invalid side/action')
    initialize(db_path)
    with closing(sqlite3.connect(_db_path(db_path), timeout=15)) as db, db:
        db.execute('''INSERT OR IGNORE INTO tracked_orders
            (order_id,ticker,side,action,updated_at) VALUES(?,?,?,?,?)''',
            (order_id, ticker, side, action, datetime.now(timezone.utc).isoformat()))
        row = db.execute('SELECT ticker,side,action FROM tracked_orders WHERE order_id=?', (order_id,)).fetchone()
        if row != (ticker,side,action):
            raise ValueError('order ID already registered with different identity')


def _fill_quantity(fill):
    for field in ('count_fp', 'count'):
        if field in fill and fill[field] is not None:
            return decimal_value(fill[field])
    raise ValueError('fill quantity missing')


async def reconcile_demo_orders(client, db_path):
    """Inspect tracked IDs; never infer completion from missing open orders.

    Exchange order status is reported separately from fill quantity. A fill
    quantity is diagnostic only; no local position/P&L changes.
    """
    _demo(client)
    initialize(db_path)
    with closing(sqlite3.connect(_db_path(db_path), timeout=15)) as db, db:
        tracked = db.execute('SELECT order_id,ticker,side,action FROM tracked_orders ORDER BY order_id').fetchall()
    report = {'timestamp_utc': datetime.now(timezone.utc).isoformat(),
              'mode': 'demo_read_only', 'orders_submitted': 0,
              'positions_updated': 0, 'automatic_exit_safe': False, 'orders': []}
    for order_id, ticker, side, action in tracked:
        item = {'order_id':order_id,'ticker':ticker,'side':side,'action':action,
                'state':'UNVERIFIED','filled_quantity':None,'reason':None}
        try:
            # Filtered order lookup; don't use resting-only results to conclude filled.
            orders = await fetch_all(client, '/trade-api/v2/portfolio/orders', 'orders', {'ticker':ticker})
            matches = [o for o in orders if o.get('order_id') == order_id]
            if len(matches) != 1:
                raise ValueError('Order absent or duplicated in exchange order history')
            order = matches[0]
            if str(order.get('ticker','')) != ticker or str(order.get('side','')).upper() != side or str(order.get('action','')).lower() != action:
                raise ValueError('Exchange order identity mismatch')
            status = str(order.get('status','')).lower()
            if status not in ('resting','executed','canceled','cancelled','pending'):
                raise ValueError('Unrecognized order status: '+status)
            # Order-scoped fills, paginated via the existing fetch_all helper.
            fills = await fetch_all(client, '/trade-api/v2/portfolio/fills', 'fills', {'order_id':order_id})
            ids = set()
            total = Decimal(0)
            for f in fills:
                fid = f.get('fill_id') or f.get('trade_id')
                if not isinstance(fid,str) or not fid or fid in ids:
                    raise ValueError('Missing or duplicate fill identity')
                ids.add(fid)
                if str(f.get('order_id','')) != order_id or str(f.get('ticker','')) != ticker:
                    raise ValueError('Fill identity mismatch')
                total += _fill_quantity(f)
            item['state'] = status.upper()
            item['filled_quantity'] = str(total)
            item['reason'] = 'Order status and scoped fills observed; no position/P&L inference'
        except Exception as exc:
            item['state'] = 'UNVERIFIED'
            item['filled_quantity'] = None
            item['reason'] = f'{type(exc).__name__}: {str(exc)[:200]}'
        report['orders'].append(item)
        with closing(sqlite3.connect(_db_path(db_path), timeout=15)) as db, db:
            db.execute('''UPDATE tracked_orders SET state=?,filled_quantity=?,last_error=?,updated_at=? WHERE order_id=?''',
                (item['state'],item['filled_quantity'], item['reason'] if item['state']=='UNVERIFIED' else None,
                 datetime.now(timezone.utc).isoformat(),order_id))
    return report


def save_report(report, db_path):
    target = Path(db_path).with_name('demo_order_lifecycle_audit.json')
    tmp = target.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    os.replace(tmp, target)
    return str(target)
