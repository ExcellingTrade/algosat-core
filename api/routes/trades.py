from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Dict, Any, List  # Added List and Any
from datetime import date

from algosat.api.schemas import TradeLogResponse, PnLResponse
from algosat.api.dependencies import get_db
from algosat.api.auth_dependencies import get_current_user
from algosat.core.security import EnhancedInputValidator, InvalidInputError # Fixed import path
from algosat.common.logger import get_logger
from algosat.core.db import get_open_orders_for_strategy_symbol_and_tradeday

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


@router.get("/strategy_symbol/{strategy_symbol_id}/trades", response_model=List[TradeLogResponse])
async def list_trades_for_strategy_symbol(strategy_symbol_id: int, trade_day: date = None, db=Depends(get_db)):
    """
    List trades for a given symbol of a particular strategy (by strategy_symbol_id).
    Optionally filter by trade_day.
    """
    if trade_day is None:
        from algosat.core.time_utils import get_ist_now
        trade_day = get_ist_now().date()
    trades = await get_open_orders_for_strategy_symbol_and_tradeday(db, strategy_symbol_id, trade_day)
    return [TradeLogResponse(**trade) for trade in trades]
