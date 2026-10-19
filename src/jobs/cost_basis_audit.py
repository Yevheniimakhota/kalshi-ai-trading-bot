"""Demo-only read-only indicative open-lot price audit.

IMPORTANT: Kalshi side/action mapping here is a *hypothesis* from phase 5C,
not a verified exchange accounting model. No DB changes, P&L or trading.
"""
from collections import defaultdict, deque
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json
import os
import tempfile


def dec(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        d = Decimal(str(value))
        return d if d.is_finite() else None
    except (ValueError, TypeError, InvalidOperation):
        return None


def qty_of(row):
    for key in ('count_fp', 'quantity_fp', 'count', 'quantity'):
        if key in row:
            v = dec(row[key])
            return v if v is not None and v > 0 else None
    return None


def price_of(row, owned_side):
    """Use only explicit side-specific DOLLAR prices, never cents or generic price."""
    key = 'yes_price_dollars' if owned_side == 'YES' else 'no_price_dollars'
    v = dec(row.get(key))
    return v if v is not None and Decimal('0') <= v <= Decimal('1') else None


def _time(row):
    raw = row.get('created_time') or row.get('ts')
    if not isinstance(raw, str):
        raise ValueError('Missing execution timestamp')
    try:
        parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('Invalid execution timestamp') from exc
    if parsed.tzinfo is None:
        raise ValueError('Execution timestamp has no timezone')
    return parsed.astimezone(timezone.utc)


def audit_cost_basis(fills, inventory):
    """Reconstruct FIFO *indicative* lots, refusing missing/ambiguous prices.

    Mapping matches phase 5C only: buy YES = +YES, sell NO = -YES.
    A buy YES first reduces NO exposure, a sell NO first reduces YES exposure.
    FIFO is a diagnostic assumption; do not treat resulting price as verified.
    """
    if not isinstance(fills, list):
        raise TypeError('Expected complete list of fills')
    grouped = defaultdict(list)
    ids = set()
    for row in fills:
        if not isinstance(row, dict):
            raise ValueError('Malformed fill')
        fid = row.get('fill_id') or row.get('trade_id')
        ticker = row.get('ticker') or row.get('market_ticker')
        qty = qty_of(row)
        direction = {('yes', 'buy'): 1, ('no', 'sell'): -1}.get(
            (str(row.get('side', '')).lower(), str(row.get('action', '')).lower()))
        if not fid or not ticker or qty is None or direction is None:
            raise ValueError('Unusable fill: missing ID, ticker, quantity, or unsupported action')
        if str(fid) in ids:
            raise ValueError('Duplicate fill ID')
        ids.add(str(fid))
        grouped[str(ticker)].append((_time(row), str(fid), qty, direction, row))

    positions = []
    for (ticker, side), exchange_qty in sorted(inventory.items()):
        events = sorted(grouped.get(ticker, []), key=lambda x: (x[0], x[1]))
        lots = deque()  # (signed side, quantity, price per owned contract)
        missing_price = False
        crosses_zero = False
        fee_fields_present = set()
        for _, _, quantity, direction, row in events:
            # An event can reduce existing opposite lots, then create new lots.
            remaining = quantity
            while remaining and lots and lots[0][0] != direction:
                old_side, old_qty, old_price = lots.popleft()
                consumed = min(remaining, old_qty)
                remaining -= consumed
                if old_qty > consumed:
                    lots.appendleft((old_side, old_qty - consumed, old_price))
            if remaining:
                if any(l[0] != direction for l in lots):
                    raise ValueError('Mixed-direction inventory replay')
                if remaining != quantity:
                    crosses_zero = True
                price = price_of(row, 'YES' if direction == 1 else 'NO')
                if price is None:
                    missing_price = True
                lots.append((direction, remaining, price))
            for key in row:
                if 'fee' in key.lower():
                    fee_fields_present.add(key)
        signed = sum((Decimal(s) * q for s, q, _ in lots), Decimal(0))
        expected = dec(exchange_qty) * (1 if side.upper() == 'YES' else -1)
        match = bool(events) and expected is not None and signed == expected
        open_qty = sum((q for _, q, _ in lots), Decimal(0))
        all_prices = bool(lots) and all(price is not None for _, _, price in lots)
        indicative = (sum((q * price for _, q, price in lots), Decimal(0)) / open_qty
                      if match and all_prices and not missing_price and open_qty else None)
        # Prices are hypothetical, NOT verified, even when indicative is present.
        positions.append({
            'ticker': ticker, 'exchange_side': side, 'exchange_quantity': str(exchange_qty),
            'observed_fills': len(events), 'replayed_signed_yes_exposure': str(signed),
            'quantity_matches_hypothesis': bool(match),
            'indicative_fifo_entry_price_dollars': str(indicative) if indicative is not None else None,
            'cost_basis_status': 'indicative_unverified' if indicative is not None else 'unavailable',
            'entry_price_verified': None, 'fee_fields_observed': sorted(fee_fields_present),
            'fees_reconciled': False, 'lot_policy': 'FIFO diagnostic assumption',
            'crossed_zero_during_replay': crosses_zero,
            'reason': ('Historical completeness, Kalshi trade semantics, fees and FIFO lot policy are not verified. '
                       'Indicative prices must not be written to DB or used for exits.'),
        })
    return {
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'mode': 'diagnostic_read_only', 'positions': positions,
        'quantity_matches': sum(p['quantity_matches_hypothesis'] for p in positions),
        'indicative_prices_available': sum(p['indicative_fifo_entry_price_dollars'] is not None for p in positions),
        'verified_entry_prices': 0, 'automatic_exit_safe': False,
        'note': 'No trades, P&L, orders, or SQLite changes. Prices are indicative only; no fee reconciliation.',
    }


def save_cost_basis_report(report, db_path):
    path = Path(db_path).resolve().with_name('demo_cost_basis_audit.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.demo_cost_', suffix='.json', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(report, out, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return str(path)
