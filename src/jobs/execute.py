"""
Trade Execution Job

This job takes a position and executes it as a trade.
"""
import asyncio
import uuid
from datetime import datetime
from typing import Optional, Dict
from dataclasses import dataclass

from src.utils.database import DatabaseManager, Position
from src.config.settings import settings
from src.utils.logging_setup import get_trading_logger
from src.clients.kalshi_client import KalshiClient, KalshiAPIError
from src.utils.market_prices import get_market_prices, is_tradeable_market

@dataclass(frozen=True)
class ExecutionResult:
    # ACK is a submitted order, NEVER proof of an exchange fill.
    status: str  # ACKNOWLEDGED_NOT_FILLED, PAPER_SIMULATED, BLOCKED, UNKNOWN
    order_id: Optional[str] = None
    reason: str = ''

    @property
    def accepted(self) -> bool:
        return self.status in ('ACKNOWLEDGED_NOT_FILLED', 'PAPER_SIMULATED')

    @property
    def filled(self) -> bool:
        # API acknowledgements cannot establish fills; paper has no exchange fill.
        return False


async def execute_position_result(
    position: Position, 
    live_mode: bool, 
    db_manager: DatabaseManager, 
    kalshi_client: KalshiClient
) -> ExecutionResult:
    """
    Executes a single trade position.
    
    Args:
        position: The position to execute.
        live_mode: Whether to execute a live or simulated trade.
        db_manager: The database manager instance.
        kalshi_client: The Kalshi client instance.
        
    Returns:
        ExecutionResult with submission state, not an inferred fill.
    """
    logger = get_trading_logger("trade_execution")
    logger.info(f"🎯 Executing position for market: {position.market_id}")
    logger.info(f"🎛️ Live mode: {live_mode}")
    
    if live_mode:
        # Preserve strategy-produced ticker/side/size, but never invent a fill.
        # This returns True for an ACKNOWLEDGED ORDER, not for acquired contracts.
        import os
        from decimal import Decimal
        from src.jobs.demo_safe_submit import submit_demo_buy
        if os.getenv('KALSHI_ENV', '').lower() != 'demo' or 'demo-api.kalshi.co' not in str(getattr(kalshi_client, 'base_url', '')).lower():
            logger.error('Exchange entry remains disabled outside Kalshi Demo')
            return ExecutionResult('BLOCKED')
        if position.status != 'pending':
            logger.error('Refusing Demo BUY unless local position is pending')
            return ExecutionResult('BLOCKED', reason='position not pending')
        try:
            qty = Decimal(str(position.quantity))
            if not qty.is_finite() or qty != qty.to_integral_value() or qty <= 0:
                logger.error('Demo entry requires a whole positive contract count')
                return ExecutionResult('BLOCKED')
            side = str(position.side).upper()
            if side not in ('YES', 'NO'):
                return ExecutionResult('BLOCKED')
            market_result = await kalshi_client.get_market(position.market_id)
            market = market_result.get('market', {})
            if not is_tradeable_market(market):
                return ExecutionResult('BLOCKED')
            _, ya, _, na = get_market_prices(market)
            ask = Decimal(str(ya if side == 'YES' else na)) * 100
            cents = int(ask.to_integral_value(rounding='ROUND_CEILING'))
            if not 1 <= cents <= 99:
                return ExecutionResult('BLOCKED')
            # Stable per-local-position ID; crash/restart cannot replay same intent.
            if position.id is None:
                logger.error('Position must be durably stored before creating order')
                return ExecutionResult('BLOCKED')
            response = await submit_demo_buy(
                kalshi_client, db_manager.db_path,
                intent_key=f'original_strategy_position_{position.id}',
                ticker=position.market_id, side=side, count=int(qty),
                price_cents=cents, confirm=True,
            )
            logger.info(f"DEMO BUY submitted, NOT filled: {response['order_id']}")
            # No update_position_to_live: only confirmed fills may update inventory.
            return ExecutionResult('ACKNOWLEDGED_NOT_FILLED', order_id=response['order_id'])
        except Exception as exc:
            logger.error(f'Demo order not confirmed; inspect durable intent/exchange before any retry: {exc}')
            return ExecutionResult('UNKNOWN', reason=str(exc))
    else:
        # Simulate the trade
        await db_manager.update_position_to_live(position.id, position.entry_price)
        logger.info(f"📝 PAPER TRADE SIMULATED for {position.market_id} - No real money used")
        logger.info(f"📊 Would have used: ${position.quantity * position.entry_price:.2f}")
        return ExecutionResult('PAPER_SIMULATED')


async def execute_position(position: Position, live_mode: bool,
                           db_manager: DatabaseManager,
                           kalshi_client: KalshiClient) -> bool:
    """Backward compatible boolean interface. True means ACK or paper simulated,
    never confirmed exchange fill. Prefer execute_position_result for logging.
    """
    return (await execute_position_result(position, live_mode, db_manager, kalshi_client)).accepted


async def place_sell_limit_order(
    position: Position, limit_price: float, db_manager: DatabaseManager,
    kalshi_client: KalshiClient
) -> bool:
    """Submit one verified Demo SELL. True means submitted, NOT filled/closed."""
    logger=get_trading_logger('sell_limit_order')
    try:
        from src.jobs.demo_safe_exit import submit_demo_exit
        result=await submit_demo_exit(kalshi_client,db_manager.db_path,position,limit_price)
        logger.info(f"SELL SUBMITTED (NOT FILLED): {position.market_id} "
                    f"{position.side} count={result['count']} order_id={result['order_id']}")
        return True
    except Exception as exc:
        logger.warning(f'Exit skipped for {position.market_id}: {exc}')
        return False


async def _conditional_exit_orders(db_manager, kalshi_client, threshold, take_profit):
    """Original profit/loss thresholds; no new strategy decision rules."""
    logger=get_trading_logger('exchange_exit')
    results={'orders_placed':0,'positions_processed':0}
    positions=await db_manager.get_open_live_positions()
    for position in positions:
        if position.strategy in (None,'exchange_unmanaged') or position.entry_price<=0:
            continue
        results['positions_processed']+=1
        try:
            market=(await kalshi_client.get_market(position.market_id)).get('market',{})
            yes_bid,_,no_bid,_=get_market_prices(market)
            current=yes_bid if position.side.upper()=='YES' else no_bid
            if not (0<current<1):
                continue
            profit=(current-position.entry_price)/position.entry_price
            trigger=profit>=threshold if take_profit else profit<=threshold
            if trigger:
                ok=await place_sell_limit_order(position,current,db_manager,kalshi_client)
                if ok:results['orders_placed']+=1
        except Exception as exc:
            logger.warning(f'Conditional exit skipped for {position.market_id}: {exc}')
    return results


async def place_profit_taking_orders(db_manager:DatabaseManager, kalshi_client:KalshiClient,
                                    profit_threshold:float=0.25)->Dict[str,int]:
    return await _conditional_exit_orders(db_manager,kalshi_client,profit_threshold,True)


async def place_stop_loss_orders(db_manager:DatabaseManager,kalshi_client:KalshiClient,
                                 stop_loss_threshold:float=-0.10)->Dict[str,int]:
    return await _conditional_exit_orders(db_manager,kalshi_client,stop_loss_threshold,False)
