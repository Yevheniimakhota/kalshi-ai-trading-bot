"""Kalshi Demo read-only fee and history-completeness diagnostic.

No exchange fee reconciliation or cost-basis verification is claimed.
"""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json
import os
import tempfile


def _decimal(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        return None
    return result if result.is_finite() and result >= 0 else None


def audit_fees_and_completeness(fills, inventory, resting, cost_report):
    """Validate fee field presence and capture evidence gaps, never infer units.

    Even a fully paginated API response cannot establish that the historical
    range covers all opening trades. Matching position quantity isn't proof.
    """
    if not isinstance(fills, list) or not isinstance(resting, list):
        raise TypeError('Expected fills and resting orders lists')
    if not isinstance(cost_report, dict):
        raise TypeError('Expected cost audit report')
    cost_by_ticker = {p['ticker']: p for p in cost_report.get('positions', [])}
    by_ticker = defaultdict(list)
    ids = set()
    for fill in fills:
        if not isinstance(fill, dict):
            raise ValueError('Invalid fill object')
        ticker = fill.get('ticker') or fill.get('market_ticker')
        fid = fill.get('fill_id') or fill.get('trade_id')
        if not ticker or not fid or str(fid) in ids:
            raise ValueError('Fill missing ticker/id or duplicate id')
        ids.add(str(fid))
        by_ticker[str(ticker)].append(fill)

    orders_by_ticker = defaultdict(list)
    for order in resting:
        if not isinstance(order, dict):
            raise ValueError('Invalid resting order')
        ticker = order.get('ticker') or order.get('market_ticker')
        if not ticker:
            raise ValueError('Resting order missing market')
        orders_by_ticker[str(ticker)].append(order)

    positions = []
    for (ticker, side), qty in sorted(inventory.items()):
        rows = by_ticker.get(ticker, [])
        fee_values = []
        missing_fee = 0
        malformed_fee = 0
        for fill in rows:
            if 'fee_cost' not in fill:
                missing_fee += 1
                continue
            fee = _decimal(fill['fee_cost'])
            if fee is None:
                malformed_fee += 1
            else:
                fee_values.append(fee)
        cost = cost_by_ticker.get(ticker, {})
        # This is a raw sum in unspecified API units, NOT dollars.
        raw_fee_sum = sum(fee_values, Decimal('0')) if fee_values else None
        positions.append({
            'ticker': ticker, 'side': side, 'quantity': str(qty),
            'observed_fills': len(rows),
            'fills_with_parseable_fee_cost': len(fee_values),
            'fills_missing_fee_cost': missing_fee,
            'fills_with_invalid_fee_cost': malformed_fee,
            'raw_fee_cost_sum_units_unverified': str(raw_fee_sum) if raw_fee_sum is not None else None,
            'fee_cost_units_verified': False,
            'fee_amount_reconciled_to_exchange': False,
            'quantity_matches_hypothesis': cost.get('quantity_matches_hypothesis') is True,
            'indicative_fifo_entry_price_dollars': cost.get('indicative_fifo_entry_price_dollars'),
            'history_complete_verified': False,
            'resting_order_count_on_market': len(orders_by_ticker.get(ticker, [])),
            'entry_price_verified': False,
            'eligible_for_automatic_exits': False,
            'blocking_reasons': [
                'Historical coverage not independently verified',
                'Kalshi fill semantics and FIFO ownership not independently verified',
                'Fee units and reconciliation not verified',
                'Resting orders not reconciled to reserved inventory',
            ],
        })
    return {
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'mode': 'diagnostic_read_only',
        'total_fills': len(fills),
        'resting_order_count': len(resting),
        'positions': positions,
        'positions_with_all_observed_fee_fields_parseable': sum(
            p['observed_fills'] > 0 and p['fills_missing_fee_cost'] == 0 and
            p['fills_with_invalid_fee_cost'] == 0 for p in positions),
        'verified_entry_prices': 0,
        'fees_reconciled': False,
        'history_complete_verified': False,
        'automatic_exit_safe': False,
        'note': 'No API fee unit assumption, P&L, SQLite writes, or orders. A paginated fill snapshot does not prove historical completeness.',
    }


def save_fee_completeness_report(report, db_path):
    path = Path(db_path).resolve().with_name('demo_fee_completeness_audit.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.demo_fee_', suffix='.json', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return str(path)
