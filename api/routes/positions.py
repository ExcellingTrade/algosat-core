from fastapi import APIRouter, Depends
from api.schemas import PositionResponse
from typing import List

router = APIRouter()

@router.get("/", response_model=List[PositionResponse])
async def list_positions():
    # TODO: Integrate with broker wrappers to fetch live positions
    return []

@router.get("/{broker_name}", response_model=List[PositionResponse])
async def list_positions_for_broker(broker_name: str):
    # TODO: Integrate with broker wrappers to fetch live positions for a broker
    return []
