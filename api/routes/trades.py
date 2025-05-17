from fastapi import APIRouter, Depends, Query, HTTPException
from api.schemas import TradeLogResponse, PnLResponse
from typing import List

router = APIRouter()

# (For future: you can add get_all_trades, get_trade_by_id, get_aggregate_pnl, etc. to core/db.py)

@router.get("/", response_model=List[TradeLogResponse])
async def list_trades():
    # TODO: Query trade_logs table
    return []

@router.get("/{trade_id}", response_model=TradeLogResponse)
async def get_trade(trade_id: int):
    # TODO: Query trade_logs table for specific trade
    trade = None  # Replace with actual DB call
    if not trade:
        raise HTTPException(status_code=404, detail="Trade not found")
    return trade

@router.get("/pnl", response_model=PnLResponse)
async def get_aggregate_pnl(broker: str = Query(None)):
    # TODO: Aggregate PnL from trade_logs, optionally filter by broker
    return PnLResponse(total_pnl=0.0)
