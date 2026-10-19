"""Demo-only automatic exits with durable order identity, never optimistic closing.

The strategy decides WHEN to exit. This module only verifies owned inventory and
places at most one SELL intent per local position. Exchange fills alone update
inventory through sync; an order acknowledgement never creates local P&L.
"""
from decimal import Decimal, ROUND_FLOOR
from src.jobs.demo_order_lifecycle import _demo, fetch_all, register_order
from src.jobs.demo_safe_submit import _reserve, _mark
from src.jobs.demo_owned_lots import verified_bot_lot, dec, OwnershipUnverified
from src.jobs.reconcile_demo import parse_market_position


async def submit_demo_exit(client, db_path, position, limit_price):
    _demo(client)
    if not position.id or not position.live or position.status!='open':
        raise ValueError('Only synchronized live bot positions can be exited')
    if not position.strategy or position.strategy == 'exchange_unmanaged':
        raise ValueError('Manual/unmanaged positions are not automatically sold')
    side = str(position.side).upper()
    if side not in ('YES','NO'):
        raise ValueError('Invalid side')
    ask = dec(limit_price)
    if not Decimal('0') < ask < Decimal('1'):
        raise ValueError('Invalid sell price')
    cents = int((ask * 100).to_integral_value(rounding=ROUND_FLOOR))
    if cents < 1 or cents > 99:
        raise ValueError('Sell price out of supported 1..99 cents')

    # Read full exchange snapshots. A resting order (including one made manually)
    # is an exclusion, not an opportunity to submit another SELL.
    for attempt in (1,2):
        orders = await fetch_all(client,'/trade-api/v2/portfolio/orders','orders',{'ticker':position.market_id})
        if any(not isinstance(o,dict) or not o.get('ticker') for o in orders):
            raise ValueError('Malformed resting order snapshot')
        if any(o['ticker']==position.market_id and str(o.get('status','')).lower() not in ('executed','canceled','cancelled') for o in orders):
            raise RuntimeError('Existing active/unknown order on ticker; do not duplicate exit')
        exchange_positions = await fetch_all(client,'/trade-api/v2/portfolio/positions','market_positions')
        holdings = {}
        for r in exchange_positions:
            ticker, owned_side, qty = parse_market_position(r)
            if qty:
                if (ticker, owned_side) in holdings:
                    raise ValueError('Duplicate exchange inventory')
                holdings[(ticker, owned_side)] = qty
        qty = holdings.get((position.market_id,side),Decimal(0))
        if qty <= 0 or qty != dec(position.quantity):
            raise OwnershipUnverified('Position has changed since local sync')
        if attempt == 1:
            initial_qty = qty
        elif qty != initial_qty:
            raise OwnershipUnverified('Inventory changed during sell preflight')

    fills = await fetch_all(client,'/trade-api/v2/portfolio/fills','fills')
    owned = verified_bot_lot(db_path,position.id,position.market_id,side,qty,fills)
    if abs(owned['entry_price']-dec(position.entry_price)) > Decimal('0.000001'):
        raise OwnershipUnverified('Local entry price disagrees with confirmed BUY fills')
    # Kalshi client v2 order payload supports quantities with two decimal places,
    # but the old local contract size is integer; require a whole inventory for exit.
    if qty != qty.to_integral_value() or qty < 1:
        raise OwnershipUnverified('Fractional inventory needs separate sizing support')
    count = int(qty)
    intent_key = f'original_strategy_exit_position_{position.id}'
    cid = _reserve(db_path,intent_key,position.market_id,side,count,cents)
    _mark(db_path,intent_key,'SUBMITTING')
    try:
        kwargs=dict(ticker=position.market_id,client_order_id=cid,
                    side=side.lower(),action='sell',count=count,type_='limit')
        kwargs['yes_price' if side=='YES' else 'no_price'] = cents
        response = await client.place_order(**kwargs)
        order = response.get('order',response) if isinstance(response,dict) else None
        oid = order.get('order_id') if isinstance(order,dict) else None
        if not isinstance(oid,str) or not oid:
            raise ValueError('Uncertain exchange acknowledgement; manual reconciliation')
        _mark(db_path,intent_key,'ACKNOWLEDGED',oid)
        register_order(db_path,order_id=oid,ticker=position.market_id,side=side,action='sell')
        return {'state':'ACKNOWLEDGED_NOT_FILLED','order_id':oid,'count':count}
    except BaseException as exc:
        _mark(db_path,intent_key,'UNKNOWN_REQUIRES_RECONCILIATION',error=f'{type(exc).__name__}: {str(exc)[:180]}')
        raise
