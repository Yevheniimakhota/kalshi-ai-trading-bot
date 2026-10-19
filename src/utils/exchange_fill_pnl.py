"""Read-only FIFO fill accounting. Never submits orders or writes trading DB.

All amounts are dollars. Kalshi API fee_cost is fixed-point USD (not cents).
A complete fills history is REQUIRED before results can be called realized P&L.
"""
from collections import defaultdict, deque
from decimal import Decimal, InvalidOperation


class AccountingIncomplete(ValueError):
    pass


def dec(value):
    try:
        x = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AccountingIncomplete(f'Invalid decimal {value!r}') from exc
    if not x.is_finite():
        raise AccountingIncomplete('Non-finite numeric value')
    return x


def calculate_fifo(fills, *, history_complete=False, fees_verified=False):
    """Return verified FIFO results or raise AccountingIncomplete, no silent defaults.

    Fills are expected to be **normalized** dictionaries with:
      fill_id, ticker, side (yes/no), action (buy/sell), quantity,
      price_dollars, fee_dollars, created_time.
    Fee allocation: purchase fees follow lots; sale fees charged at execution.
    Partial closes allocate buy fees proportionally to shares closed.
    """
    if not history_complete:
        raise AccountingIncomplete('Full fill history not independently verified')
    if not fees_verified:
        raise AccountingIncomplete('Fee currency units and coverage not verified')
    lots = defaultdict(deque)
    totals = defaultdict(lambda: {'realized_pnl': Decimal(0), 'fees': Decimal(0),
                                  'open_quantity': Decimal(0), 'open_cost_including_fees': Decimal(0)})
    seen = set()
    ordered = sorted(fills, key=lambda f: (str(f['created_time']), str(f['fill_id'])))
    for f in ordered:
        fid = str(f['fill_id'])
        if not fid or fid in seen:
            raise AccountingIncomplete(f'Missing or duplicate fill ID: {fid!r}')
        seen.add(fid)
        ticker = str(f['ticker']); side = str(f['side']).lower(); action = str(f['action']).lower()
        if not ticker or side not in ('yes', 'no') or action not in ('buy', 'sell'):
            raise AccountingIncomplete('Unknown ticker, side or action')
        qty, price, fee = dec(f['quantity']), dec(f['price_dollars']), dec(f['fee_dollars'])
        if qty <= 0 or not 0 <= price <= 1 or fee < 0:
            raise AccountingIncomplete('Invalid fill quantity, price or fee')
        key = (ticker, side); summary = totals[key]
        summary['fees'] += fee
        if action == 'buy':
            lots[key].append([qty, price, fee])
            continue
        remaining = qty
        while remaining:
            if not lots[key]:
                raise AccountingIncomplete(f'Sell exceeds known owned lots for {ticker} {side}; history may be incomplete')
            lotqty, lotprice, lotfee = lots[key][0]
            take = min(remaining, lotqty)
            buy_fee_part = lotfee * take / lotqty
            sell_fee_part = fee * take / qty
            summary['realized_pnl'] += (price - lotprice) * take - buy_fee_part - sell_fee_part
            remaining -= take
            if take == lotqty:
                lots[key].popleft()
            else:
                lots[key][0] = [lotqty - take, lotprice, lotfee - buy_fee_part]
    for key, queue in lots.items():
        totals[key]['open_quantity'] = sum((lot[0] for lot in queue), Decimal(0))
        totals[key]['open_cost_including_fees'] = sum((lot[0]*lot[1] + lot[2] for lot in queue), Decimal(0))
    return dict(totals)


def extract_normalized_fill(raw, *, fee_dollars_field='fee_cost'):
    """Convert official Kalshi fee_cost (fixed-point USD), without scaling.

    A nonempty fee_cost_dollars can be accepted only with an explicit override.
    Missing or empty fee values are rejected; never assume zero fees.
    """
    if raw.get(fee_dollars_field) in (None, ''):
        raise AccountingIncomplete(f'{fee_dollars_field} missing/empty; commission cannot be verified')
    side = str(raw['side']).lower()
    price_field = f'{side}_price_dollars'
    quantity = raw.get('count_fp')
    if quantity is None:
        raise AccountingIncomplete('count_fp missing; fractional quantity not verified')
    return {'fill_id': raw['fill_id'], 'ticker': raw['ticker'], 'side': side,
            'action': raw['action'], 'quantity': quantity,
            'price_dollars': raw[price_field], 'fee_dollars': raw[fee_dollars_field],
            'created_time': raw['created_time']}
