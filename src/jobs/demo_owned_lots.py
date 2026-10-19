"""Demo-only ownership verification. Never infer strategy ownership from an API position.

A position can be auto-exited ONLY if the current inventory is exactly explained
by fills for a durably acknowledged BUY submitted for its local position id.
Any other fill on the same market/side makes the lot unmanaged (manual activity).
"""
import sqlite3
from contextlib import closing
from decimal import Decimal, InvalidOperation
from pathlib import Path


class OwnershipUnverified(ValueError):
    pass


def dec(value):
    try:
        value = Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        raise OwnershipUnverified('Invalid decimal') from None
    if not value.is_finite():
        raise OwnershipUnverified('Non-finite decimal')
    return value


def verified_bot_lot(db_path, position_id, ticker, side, exchange_qty, fills):
    """Read bot BUY journal and complete observed fills; return exact average price.

    Raises if history, ownership, price or quantity is not provably consistent.
    A completed fill does not mean that all relevant account history is complete.
    We additionally require every returned fill for that ticker/side to belong
    to this BUY. Conservative: manual transactions disable automatic exits.
    """
    if not isinstance(fills, list):
        raise OwnershipUnverified('Complete fill snapshot unavailable')
    path = Path(db_path).with_name('demo_submission_intents.sqlite3')
    if not path.is_file():
        raise OwnershipUnverified('Submission journal unavailable')
    with closing(sqlite3.connect(f'file:{path.as_posix()}?mode=ro',uri=True)) as db:
        row = db.execute('SELECT order_id,state,ticker,side FROM submission_intents WHERE intent_key=?',
                         (f'original_strategy_position_{position_id}',)).fetchone()
    if not row or row[1] != 'ACKNOWLEDGED' or not row[0]:
        raise OwnershipUnverified('No acknowledged bot BUY')
    oid, _, journal_ticker, journal_side = row
    if (journal_ticker, journal_side) != (ticker, side):
        raise OwnershipUnverified('Journal identity mismatch')
    quantity = dec(exchange_qty)
    if quantity <= 0:
        raise OwnershipUnverified('No exchange inventory')
    seen=set(); owned=Decimal(0); cost=Decimal(0); fees=Decimal(0)
    for f in fills:
        if not isinstance(f, dict):
            raise OwnershipUnverified('Malformed fill')
        ft = f.get('ticker') or f.get('market_ticker')
        if ft != ticker:
            continue
        # Kalshi's canonical direction is outcome_side/book_side. The deprecated
        # action field may read "sell" for a confirmed Demo BUY-NO order. Do not
        # infer order intent from that legacy field: the durable bot submission
        # journal already fixes the order_id and its BUY-NO intent.
        outcome = str(f.get('outcome_side') or '').lower()
        book = str(f.get('book_side') or '').lower()
        if outcome not in ('yes', 'no') or book not in ('bid', 'ask'):
            raise OwnershipUnverified('Canonical fill direction missing/invalid')
        if (outcome == 'yes' and book != 'bid') or (outcome == 'no' and book != 'ask'):
            raise OwnershipUnverified('Contradictory canonical fill direction')
        if outcome.upper() != side:
            raise OwnershipUnverified('Unrelated opposite-outcome fill on same market')
        if f.get('order_id') != oid:
            raise OwnershipUnverified('Manual or unrelated fills exist for this position')
        fid=f.get('fill_id')
        if not fid or fid in seen:
            raise OwnershipUnverified('Missing or duplicated fill ID')
        seen.add(fid)
        n=dec(f.get('count_fp'))
        px=dec(f.get(f'{side.lower()}_price_dollars'))
        fee=dec(f.get('fee_cost'))
        if n<=0 or not Decimal(0)<px<Decimal(1) or fee<0:
            raise OwnershipUnverified('Invalid fill price/quantity/fee')
        owned+=n; cost+=n*px; fees+=fee
    if not seen or owned != quantity:
        raise OwnershipUnverified(f'Bot fills {owned} do not match exchange inventory {quantity}')
    return {'quantity': quantity, 'entry_price':cost/owned, 'buy_fees':fees, 'order_id':oid}
