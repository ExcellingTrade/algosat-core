from fastapi import APIRouter, Depends, HTTPException
from api.schemas import PositionResponse
from api.dependencies import get_db
from typing import List

router = APIRouter()

# (For future: you can add get_all_positions, get_positions_by_broker, etc. to core/db.py)

@router.get("/", response_model=List[PositionResponse])
async def list_positions(db=Depends(get_db)):
    # TODO: Integrate with broker wrappers to fetch live positions
    positions = []
    return sorted(positions, key=lambda p: getattr(p, 'id', 0))

@router.get("/{broker_name}", response_model=List[PositionResponse])
async def list_positions_for_broker(broker_name: str):
    # TODO: Integrate with broker wrappers to fetch live positions for a broker
    positions = []  # Replace with actual DB/broker call
    if not positions:
        raise HTTPException(status_code=404, detail="No positions found for broker")
    return positions
