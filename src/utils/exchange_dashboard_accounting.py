"""Explicit-source Kalshi dashboard metrics. Read-only; no writes or order logic.

Exchange-reported realized P&L applies only to positions returned by the
selected positions endpoint, not necessarily archived/settled lifetime P&L.
Estimated unrealized is liquidation at current bid, excluding new exit fees.
"""
from decimal import Decimal, InvalidOperation


def decimal_field(value):
    if value is None or isinstance(value,bool):
        raise ValueError('Missing numeric exchange field')
    try: result=Decimal(str(value))
    except (ValueError,TypeError,InvalidOperation):
        raise ValueError('Invalid numeric exchange field') from None
    if not result.is_finite():
        raise ValueError('Nonfinite numeric exchange field')
    return result


def summarize_market_positions(rows, bids):
    """Only sums Kalshi realized_pnl_dollars supplied for each unique ticker.

    Never add event_positions as that would double-count market-level results.
    Bid valuation is an estimate and must not be labeled official Kalshi P&L.
    """
    realized=Decimal(0); unrealized=Decimal(0)
    realized_verified=True; estimated_verified=True; positions=[]; seen=set()
    for pos in rows:
        ticker=pos.get('ticker')
        if not ticker or ticker in seen:
            raise ValueError('Duplicate or missing exchange ticker')
        seen.add(ticker)
        qty=decimal_field(pos.get('position_fp',pos.get('position')))
        try:realized+=decimal_field(pos['realized_pnl_dollars'])
        except (KeyError,ValueError):realized_verified=False
        if qty == 0:continue
        side='YES' if qty>0 else 'NO'; owned=abs(qty)
        est=None
        try:
            cost=decimal_field(pos['market_exposure_dollars'])
            bid=decimal_field(bids[(ticker,side)])
            if not Decimal(0)<bid<Decimal(1) or cost<0:raise ValueError('Invalid bid/basis')
            est=owned*bid-cost
            unrealized+=est
        except (KeyError,ValueError):
            estimated_verified=False
        positions.append({'Ticker':ticker,'Side':side,'Contracts':str(owned),
                          'Exposure ($)':pos.get('market_exposure_dollars'),
                          'Bid ($)':str(bids.get((ticker,side),'—')),
                          'Unrealized est. ($)':str(est.quantize(Decimal('0.0001'))) if est is not None else 'Unavailable',
                          'Realized exchange ($)':pos.get('realized_pnl_dollars')})
    return {'realized': realized if realized_verified else None,
            'unrealized_estimate':unrealized if estimated_verified else None,
            'positions':positions,'position_count':len(positions)}
