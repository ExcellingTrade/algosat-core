from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Dict, Any, List  # Added List and Any
from datetime import date

from algosat.api.schemas import TradeLogResponse, PnLResponse, OrderListResponse
from algosat.api.dependencies import get_db
from algosat.api.auth_dependencies import get_current_user
from algosat.core.security import EnhancedInputValidator, InvalidInputError # Fixed import path
from algosat.common.logger import get_logger
from algosat.core.db import get_orders_by_strategy_symbol_id

router = APIRouter(dependencies=[Depends(get_current_user)])
input_validator = EnhancedInputValidator()  # Added
logger = get_logger("api.trades")


# (For future: you can add get_all_trades, get_trade_by_id, get_aggregate_pnl, etc. to core/db.py)


@router.get("/", response_model=List[TradeLogResponse])
async def list_trades(
    db=Depends(get_db), current_user: Dict[str, Any] = Depends(get_current_user)
):
    try:
        # TODO: Query trade_logs table
        trades = []
        return sorted(trades, key=lambda t: getattr(t, "id", 0))
    except Exception as e:
        logger.error(f"Error in list_trades: {e}")
        raise


@router.get("/{trade_id}", response_model=TradeLogResponse)
async def get_trade(
    trade_id: int, current_user: Dict[str, Any] = Depends(get_current_user)
):
    try:
        validated_trade_id = input_validator.validate_integer(trade_id, "trade_id", min_value=1)
        # TODO: Query trade_logs table for specific trade using validated_trade_id
        trade = None  # Replace with actual DB call
        if not trade:
            raise HTTPException(status_code=404, detail="Trade not found")
        return trade
    except Exception as e:
        logger.error(f"Error in get_trade: {e}")
        raise


@router.get("/pnl", response_model=PnLResponse)
async def get_aggregate_pnl(
    broker: str = Query(None), current_user: Dict[str, Any] = Depends(get_current_user)
):
    try:
        validated_broker = None
        if broker:
            validated_broker = input_validator.validate_and_sanitize(broker, "broker", expected_type=str, max_length=256, pattern=r"^[a-zA-Z0-9_-]+$", allow_none=True)
        # TODO: Aggregate PnL from trade_logs, optionally filter by validated_broker
        return PnLResponse(total_pnl=0.0)
    except Exception as e:
        logger.error(f"Error in get_aggregate_pnl: {e}")
        raise


@router.get("/strategy_symbol/{strategy_symbol_id}/trades", response_model=List[OrderListResponse])
async def list_trades_for_strategy_symbol(strategy_symbol_id: int, trade_day: date = None, db=Depends(get_db)):
    """
    List orders (trades) for a given symbol of a particular strategy (by strategy_symbol_id).
    Returns all orders for the strategy symbol, regardless of trade_day (trade_day parameter is deprecated).
    """
    try:
        # Validate strategy_symbol_id
        validated_strategy_symbol_id = input_validator.validate_integer(
            strategy_symbol_id, "strategy_symbol_id", min_value=1
        )
        
        # Get orders for this strategy symbol
        orders = await get_orders_by_strategy_symbol_id(db, validated_strategy_symbol_id)
        
        # Add order_id field for schema compatibility
        for order in orders:
            order['order_id'] = order['id']
        
        return [OrderListResponse(**order) for order in orders]
        
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error in list_trades_for_strategy_symbol: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve trades for strategy symbol")
