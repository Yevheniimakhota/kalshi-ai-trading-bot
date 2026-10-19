"""Explicit, fail-closed Kalshi Demo BUY submission.

No automatic exits. Durable intent prevents retries after ambiguous network errors.
Does not mark positions open/closed or calculate P&L. Single process or multiple
processes coordinate via SQLite unique intent key.
"""
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from src.jobs.demo_order_lifecycle import _demo, decimal_value, fetch_all, register_order


def _journal(db_path):
    return str(Path(db_path).with_name('demo_submission_intents.sqlite3'))


def _initialize(db_path):
    with closing(sqlite3.connect(_journal(db_path), timeout=15)) as db, db:
        db.execute('''CREATE TABLE IF NOT EXISTS submission_intents (
            intent_key TEXT PRIMARY KEY, client_order_id TEXT NOT NULL UNIQUE,
            ticker TEXT NOT NULL, side TEXT NOT NULL, count TEXT NOT NULL,
            price_cents INTEGER NOT NULL, state TEXT NOT NULL,
            order_id TEXT, error TEXT, updated_at TEXT NOT NULL
        )''')


def _reserve(db_path, intent_key, ticker, side, count, cents):
    _initialize(db_path)
    now = datetime.now(timezone.utc).isoformat()
    with closing(sqlite3.connect(_journal(db_path), timeout=15)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            row = db.execute('SELECT ticker,side,count,price_cents,state,client_order_id FROM submission_intents WHERE intent_key=?', (intent_key,)).fetchone()
            if row:
                if row[:4] != (ticker,side,str(count),cents):
                    raise ValueError('Intent key reused with different order parameters')
                raise RuntimeError('Intent already exists; never retry submission automatically. Inspect exchange by client_order_id: '+row[5])
            cid = str(uuid.uuid4())
            db.execute('INSERT INTO submission_intents VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (intent_key,cid,ticker,side,str(count),cents,'RESERVED',None,None,now))
            db.commit()
            return cid
        except BaseException:
            db.rollback()
            raise


def _mark(db_path, intent_key, state, order_id=None, error=None):
    with closing(sqlite3.connect(_journal(db_path), timeout=15)) as db, db:
        db.execute('UPDATE submission_intents SET state=?,order_id=?,error=?,updated_at=? WHERE intent_key=?',
                   (state,order_id,error,datetime.now(timezone.utc).isoformat(),intent_key))


async def submit_demo_buy(client, db_path, *, intent_key, ticker, side, count, price_cents, confirm=False):
    """Submit one explicit limit BUY in Demo only, never auto-retry.

    Must be invoked manually with confirm=True. Refuses any existing resting
    order on same ticker (conservative, avoids order interactions). Count must
    be an integer; fractional inventory is intentionally unsupported here.
    Existing intents are never resubmitted, even after crash/network timeout.
    """
    _demo(client)
    if not confirm:
        raise PermissionError('Explicit confirm=True required')
    if not isinstance(intent_key,str) or not intent_key.strip() or len(intent_key)>128:
        raise ValueError('Stable nonempty intent_key required')
    if not isinstance(ticker,str) or not ticker.strip():
        raise ValueError('ticker required')
    side = str(side).upper()
    if side not in ('YES','NO'):
        raise ValueError('side must be YES or NO')
    if isinstance(count,bool) or not isinstance(count,int) or count<=0:
        raise ValueError('Only positive integer contract count supported')
    if isinstance(price_cents,bool) or not isinstance(price_cents,int) or not 1<=price_cents<=99:
        raise ValueError('Price must be integer cents 1..99')
    # No write if validation or preflight fails. Fail closed if snapshot incomplete.
    resting = await fetch_all(client, '/trade-api/v2/portfolio/orders','orders',{'status':'resting'})
    if any(not isinstance(o,dict) or not o.get('ticker') for o in resting):
        raise ValueError('Malformed resting-order snapshot')
    if any(o['ticker']==ticker for o in resting):
        raise RuntimeError('Resting order exists on this market; manual review required')
    # Price and quantity are bounds, NOT a guarantee of fill or affordability.
    balance = await client.get_balance()
    if not isinstance(balance,dict) or 'balance' not in balance:
        raise ValueError('Cannot verify Demo available balance')
    available = decimal_value(balance['balance'])
    if available < Decimal(count*price_cents):
        raise RuntimeError('Insufficient Demo balance (excluding possible fees)')
    # Reserve durable identity BEFORE network mutation. Failures are ambiguous.
    cid = _reserve(db_path,intent_key,ticker,side,count,price_cents)
    _mark(db_path,intent_key,'SUBMITTING')
    try:
        kwargs = dict(ticker=ticker,client_order_id=cid,side=side.lower(),action='buy',
                      count=count,type_='limit')
        kwargs['yes_price' if side=='YES' else 'no_price'] = price_cents
        response = await client.place_order(**kwargs)
        obj = response.get('order',response) if isinstance(response,dict) else None
        oid = obj.get('order_id') if isinstance(obj,dict) else None
        if not isinstance(oid,str) or not oid:
            raise ValueError('Submission response missing order_id; manual reconciliation required')
        _mark(db_path,intent_key,'ACKNOWLEDGED',oid)
        # If registration fails, durable order_id remains for manual recovery.
        register_order(db_path,order_id=oid,ticker=ticker,side=side,action='buy')
        return {'intent_key':intent_key,'client_order_id':cid,'order_id':oid,
                'state':'ACKNOWLEDGED_NOT_FILLED','positions_updated':0}
    except BaseException as exc:
        _mark(db_path,intent_key,'UNKNOWN_REQUIRES_RECONCILIATION',error=f'{type(exc).__name__}: {str(exc)[:200]}')
        raise
