"""Read-only, conservative Demo execution replay. No order placement or DB writes.

Signed exposure is a diagnostic hypothesis based on the observed V1-style
fill side/action fields. It is NOT proof of historical ownership or cost basis.
"""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json
import os
import tempfile


def decimal_field(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def fill_quantity(row):
    for key in ('count_fp', 'quantity_fp', 'count', 'quantity'):
        if key in row:
            q = decimal_field(row[key])
            return q if q is not None and q > 0 else None
    return None


def fill_exposure_sign(row):
    """Candidate signed YES exposure; deliberately not used for orders/P&L."""
    side = str(row.get('side', '')).lower()
    action = str(row.get('action', '')).lower()
    # V1-style records observed: buy YES adds YES; sell NO adds NO.
    # Other combinations are not assumed without validated exchange semantics.
    return {('yes', 'buy'): 1, ('no', 'sell'): -1}.get((side, action))


def replay_fills(fills, inventory):
    """Compare observed fills to exchange inventory, never certify entry prices."""
    if not isinstance(fills, list):
        raise TypeError('Expected complete fills list')
    grouped = defaultdict(list)
    seen_ids = set()
    for row in fills:
        if not isinstance(row, dict):
            raise ValueError('Invalid fill record')
        ticker = row.get('ticker') or row.get('market_ticker')
        fid = row.get('fill_id') or row.get('trade_id')
        q = fill_quantity(row)
        sign = fill_exposure_sign(row)
        time = row.get('created_time') or row.get('ts')
        if not ticker or not fid or not time or q is None or sign is None:
            raise ValueError(f'Unreplayable fill: {fid or ticker or "missing ID"}')
        if str(fid) in seen_ids:
            raise ValueError(f'Duplicate fill ID: {fid}')
        seen_ids.add(str(fid))
        grouped[str(ticker)].append((str(time), str(fid), q, sign, row))

    results = []
    for (ticker, side), exchange_qty in sorted(inventory.items()):
        events = sorted(grouped.get(ticker, []), key=lambda x: (x[0], x[1]))
        signed = sum((Decimal(sign) * qty for _, _, qty, sign, _ in events), Decimal(0))
        expected = Decimal(str(exchange_qty)) * (1 if side.upper() == 'YES' else -1)
        match = bool(events) and signed == expected
        # A match proves only numerical agreement with one hypothesized mapping.
        # It does NOT prove all older fills were available, nor ownership of lots.
        results.append({
            'ticker': ticker, 'exchange_side': side, 'exchange_quantity': str(exchange_qty),
            'observed_fills': len(events), 'replayed_signed_yes_exposure': str(signed),
            'exchange_signed_yes_exposure': str(expected),
            'quantity_reconciles_under_hypothesis': match,
            'quantity_status': 'hypothesis_matches' if match else 'unreconciled',
            'cost_basis_status': 'unverified', 'entry_price': None,
            'reason': 'Price, fee, fill completeness, and lot ownership not verified; no database update.',
        })
    unknown_markets = sorted(set(grouped) - {ticker for ticker, _ in inventory})
    return {
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'mode': 'diagnostic_read_only',
        'exposure_hypothesis': 'buy YES => +YES; sell NO => -YES; other fill types rejected',
        'positions': results,
        'markets_with_fills_but_no_open_position': unknown_markets,
        'reconciled_quantities_under_hypothesis': sum(x['quantity_reconciles_under_hypothesis'] for x in results),
        'entry_prices_verified': 0,
        'automatic_exit_safe': False,
        'note': 'Matching signed quantities is not proof of correct cost basis. No P&L, trades or positions written.',
    }


def save_replay_report(report, db_path):
    path = Path(db_path).resolve().with_name('demo_replay_audit.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.demo_replay_', suffix='.json', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return str(path)
