"""Read-only, fail-closed Kalshi Demo position reconciliation.

Never submits orders or changes positions. Use the JSON report to validate
exchange state before implementing automated writes and exit order tracking.
"""
import json
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone



def parse_market_position(row):
    """Parse Kalshi signed contract inventory, including fixed-point API fields.

    Return (ticker, YES|NO|None, Decimal quantity). Preserve fractional
    contracts exactly; reject malformed or ambiguous values.
    """
    from decimal import Decimal, InvalidOperation

    if not isinstance(row, dict):
        raise ValueError('position row must be an object')
    ticker = row.get('ticker') or row.get('market_ticker')
    if not isinstance(ticker, str) or not ticker.strip():
        raise ValueError('missing market ticker')

    def count_value(value, label):
        if isinstance(value, bool):
            raise ValueError(f'invalid {label}: boolean')
        try:
            value = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError(f'invalid {label}') from None
        if not value.is_finite():
            raise ValueError(f'nonfinite {label}')
        return value

    # Kalshi fixed-point responses may use position_fp instead of position.
    # Prefer fixed-point data when both are supplied.
    signed_key = next((k for k in ('position_fp', 'position') if row.get(k) is not None), None)
    if signed_key:
        signed = count_value(row[signed_key], signed_key)
        return ticker, ('YES' if signed > 0 else 'NO' if signed < 0 else None), abs(signed)

    yes_key = next((k for k in ('yes_count_fp', 'yes_position_fp', 'yes_count', 'yes_position') if row.get(k) is not None), None)
    no_key = next((k for k in ('no_count_fp', 'no_position_fp', 'no_count', 'no_position') if row.get(k) is not None), None)
    if yes_key is None and no_key is None:
        raise ValueError('unknown position representation; inspect API field names')
    yes = count_value(row[yes_key], yes_key) if yes_key else 0
    no = count_value(row[no_key], no_key) if no_key else 0
    if yes < 0 or no < 0 or (yes and no):
        raise ValueError('ambiguous dual-sided position')
    return ticker, ('YES' if yes else 'NO' if no else None), max(yes, no)


async def fetch_all(client, endpoint, key, params=None, max_pages=200):
    """Fetch cursor-paginated API results; never treat a partial response as complete."""
    result, seen, cursor = [], set(), None
    for _ in range(max_pages):
        query = dict(params or {})
        query['limit'] = 200
        if cursor:
            query['cursor'] = cursor
        page = await client._make_authenticated_request('GET', endpoint, params=query)
        if not isinstance(page, dict) or not isinstance(page.get(key), list):
            raise ValueError(f'Unexpected {endpoint} response; refusing incomplete reconciliation')
        result.extend(page[key])
        nxt = page.get('cursor')
        if not nxt:
            return result
        if nxt in seen:
            raise ValueError('Repeated pagination cursor; refusing incomplete reconciliation')
        seen.add(nxt)
        cursor = nxt
    raise ValueError(f'Pagination exceeded {max_pages} pages')


def compare(exchange, local):
    """Compare exact ticker + side; report, never guess cost basis."""
    by_key = {}
    errors = []
    for row in exchange:
        try:
            ticker, side, count = parse_market_position(row)
            if not count:
                continue
            key = (ticker, side)
            if key in by_key:
                raise ValueError('duplicate market entry')
            by_key[key] = count
        except (ValueError, TypeError, KeyError) as exc:
            errors.append({'row': row, 'reason': str(exc)})
    local_by_key = {(r['market_id'], r['side'].upper()): r for r in local if r['live']}
    comparisons = []
    for key in sorted(set(by_key) | set(local_by_key)):
        ticker, side = key
        exchange_qty = by_key.get(key, 0)
        record = local_by_key.get(key)
        db_qty = record['quantity'] if record and record['status'] == 'open' else 0
        comparisons.append({
            'ticker': ticker, 'side': side, 'exchange_quantity': exchange_qty,
            'local_open_quantity': db_qty,
            'local_status': record['status'] if record else 'missing',
            'result': 'match' if exchange_qty == db_qty else 'mismatch',
        })
    return comparisons, errors


async def generate_report():
    from src.clients.kalshi_client import KalshiClient
    from src.utils.database import DatabaseManager
    env = os.getenv('KALSHI_ENV', '').lower()
    if env != 'demo':
        raise RuntimeError('Reconciliation is restricted to KALSHI_ENV=demo')
    client = KalshiClient()
    try:
        if 'demo-api.kalshi.co' not in client.base_url:
            raise RuntimeError(f'Unsafe environment URL: {client.base_url!r}')
        positions = await fetch_all(client, '/trade-api/v2/portfolio/positions', 'market_positions')
        # Resting orders are included so the user can identify pending exits.
        orders = await fetch_all(client, '/trade-api/v2/portfolio/orders', 'orders', {'status': 'resting'})
    finally:
        await client.close()

    db = DatabaseManager()
    db_path = Path(db.db_path)
    local = []
    if db_path.exists():
        with sqlite3.connect(f'file:{db_path.as_posix()}?mode=ro', uri=True) as con:
            con.row_factory = sqlite3.Row
            local = [dict(r) for r in con.execute('SELECT market_id,side,quantity,status,live FROM positions')]
    comparisons, errors = compare(positions, local)
    return {
        'generated_utc': datetime.now(timezone.utc).isoformat(),
        'environment': env, 'api_url': client.base_url, 'db_path': str(db_path),
        'database_exists': db_path.exists(), 'comparisons': comparisons,
        'unparsed_positions': errors,
        'resting_orders': [
            {k: order.get(k) for k in ('order_id','ticker','side','action','status','remaining_count','initial_count','fill_count')}
            for order in orders
        ],
        'safe_to_enable_automatic_exits': False,
        'note': 'Read-only. Never use this report to infer entry prices or execute sells.',
    }


def save_report(report, path=None):
    from desktop.paths import get_user_data_dir
    output = Path(path) if path else get_user_data_dir() / 'demo_reconciliation_report.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    return output
