"""Read-only accounting baseline for a new, empty Kalshi Demo account.

No trading action, no legacy SQLite mutation, never resets or truncates state.
"""
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from decimal import Decimal

from src.jobs.demo_order_lifecycle import fetch_all
from src.utils.exchange_fill_pnl import calculate_fifo, extract_normalized_fill, AccountingIncomplete

class SessionError(ValueError):
    pass


def session_file():
    return Path(os.environ.get('KALSHI_TEST_SESSION_PATH') or 'demo_test_session.json').resolve()


def _account_fingerprint(client):
    key = str(getattr(client, 'api_key', '') or '').strip()
    if not key:
        raise SessionError('No API key identity')
    return hashlib.sha256(key.encode()).hexdigest()


async def fetch_snapshot(client):
    if os.getenv('KALSHI_ENV','').lower() != 'demo':
        raise SessionError('Demo environment required')
    url = str(getattr(client, 'base_url','')).rstrip('/').lower()
    if url != 'https://demo-api.kalshi.co':
        raise SessionError('Refusing non-Demo endpoint')
    positions_raw = await fetch_all(client, '/trade-api/v2/portfolio/positions', 'market_positions')
    orders_raw = await fetch_all(client, '/trade-api/v2/portfolio/orders', 'orders', {'status':'resting'})
    fills_raw = await fetch_all(client, '/trade-api/v2/portfolio/fills', 'fills')
    balance = await client.get_balance()
    if not isinstance(balance,dict) or 'balance' not in balance:
        raise SessionError('Invalid balance response')
    if any(not isinstance(x,dict) for x in positions_raw+orders_raw+fills_raw):
        raise SessionError('Invalid account records')
    return {'account_fingerprint':_account_fingerprint(client), 'positions':positions_raw,
            'orders':orders_raw,'fills':fills_raw, 'balance':balance,
            'observed_at_utc':datetime.now(timezone.utc).isoformat()}


def _quantity(position):
    raw=position.get('position_fp', position.get('position'))
    if raw is None:
        raise SessionError('Position quantity missing')
    try:
        qty=Decimal(str(raw))
    except Exception as exc:
        raise SessionError('Invalid position quantity') from exc
    if not qty.is_finite():
        raise SessionError('Non-finite quantity')
    return qty


def read_session(path):
    path=Path(path)
    if not path.exists():return None
    b=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(b,dict) or b.get('version')!=1 or not b.get('account_fingerprint') or not b.get('started_at_utc'):
        raise SessionError('Invalid stored baseline; do not overwrite automatically')
    return b


def create_clean_session(snapshot,path):
    path=Path(path)
    if snapshot.get('fills'):
        raise SessionError('Account already has fills; zero-history baseline refused')
    if snapshot.get('orders'):
        raise SessionError('Account has resting orders; cancel/check before starting')
    if any(_quantity(p)!=0 for p in snapshot.get('positions',[])):
        raise SessionError('Account has an open position; empty baseline refused')
    identity=snapshot.get('account_fingerprint')
    if not isinstance(identity,str) or len(identity)!=64:
        raise SessionError('Account fingerprint unavailable')
    baseline={'version':1,'account_fingerprint':identity,
              'started_at_utc':snapshot['observed_at_utc'],
              'initial_balance':str(snapshot['balance']['balance']), 'initial_fills':0,
              'initial_open_positions':0, 'initial_resting_orders':0}
    # Atomic create: no resetting a test session, even on restart.
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as f:
        json.dump(baseline,f,indent=2)
    return baseline


def session_report(baseline,snapshot):
    if snapshot['account_fingerprint']!=baseline['account_fingerprint']:
        raise SessionError('API key belongs to a different account; session refused')
    raw=snapshot['fills']
    rows=[];reason=None;verified=False;total=None
    try:
        normalized=[extract_normalized_fill(f) for f in raw]
        results=calculate_fifo(normalized,history_complete=True,fees_verified=True)
        total=sum((r['realized_pnl'] for r in results.values()), Decimal(0))
        rows=[{'Ticker':t,'Side':s,'Realized P&L USD':str(v['realized_pnl']),
               'Fees USD':str(v['fees']), 'Open contracts':str(v['open_quantity']),
               'Cost incl. fees USD':str(v['open_cost_including_fees'])}
              for (t,s),v in sorted(results.items())]
        verified=True
    except (AccountingIncomplete,ValueError,KeyError,TypeError) as exc:
        reason=f'FIFO incomplete: {exc}'
    return {'fills_count':len(raw),'resting_count':len(snapshot['orders']),
            'positions_count':sum(_quantity(p)!=0 for p in snapshot['positions']),
            'fifo_rows':rows,'pnl_verified':verified,
            'realized_total':str(total) if verified else None,'reason':reason}
