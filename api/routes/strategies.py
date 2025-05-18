from fastapi import APIRouter, Depends, HTTPException
from core.db import (
    get_all_strategies,
    get_strategy_by_id,
    get_strategy_configs_by_strategy_id,
    get_strategy_config_by_id,
    update_strategy_config,
)
from api.schemas import (
    StrategyListResponse,
    StrategyDetailResponse,
    StrategyConfigListResponse,
    StrategyConfigDetailResponse,
    StrategyConfigUpdate,
)
from api.dependencies import get_db
from typing import List

router = APIRouter()

@router.get("/", response_model=List[StrategyListResponse])
async def list_strategies(db=Depends(get_db)):
    strategies = [StrategyListResponse(**row) for row in await get_all_strategies(db)]
    return sorted(strategies, key=lambda s: s.id)

@router.get("/{strategy_id}", response_model=StrategyDetailResponse)
async def get_strategy(strategy_id: int, db=Depends(get_db)):
    row = await get_strategy_by_id(db, strategy_id)
    if not row:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return StrategyDetailResponse(**row)

@router.get("/{strategy_id}/configs", response_model=List[StrategyConfigListResponse])
async def list_strategy_configs_for_strategy(strategy_id: int, db=Depends(get_db)):
    configs = [StrategyConfigListResponse(**row) for row in await get_strategy_configs_by_strategy_id(db, strategy_id)]
    return sorted(configs, key=lambda c: c.id)

@router.get("/configs/{config_id}", response_model=StrategyConfigDetailResponse)
async def get_strategy_config_detail(config_id: int, db=Depends(get_db)):
    row = await get_strategy_config_by_id(db, config_id)
    if not row:
        raise HTTPException(status_code=404, detail="Strategy config not found")
    # Convert SQLAlchemy Row to dict if needed
    if hasattr(row, "_mapping"):
        row = dict(row._mapping)
    return StrategyConfigDetailResponse(**row)

@router.get("/{strategy_id}/configs/{config_id}", response_model=StrategyConfigDetailResponse)
async def get_strategy_config_detail_for_strategy(strategy_id: int, config_id: int, db=Depends(get_db)):
    row = await get_strategy_config_by_id(db, config_id)
    if not row:
        raise HTTPException(status_code=404, detail="Strategy config not found")
    if hasattr(row, "_mapping"):
        row = dict(row._mapping)
    if "params" not in row or row["params"] is None:
        row["params"] = {}
    if row.get("strategy_id") != strategy_id:
        raise HTTPException(status_code=404, detail="Strategy config does not belong to this strategy")
    return StrategyConfigDetailResponse(**row)

@router.put("/configs/{config_id}", response_model=StrategyConfigDetailResponse)
async def update_strategy_config_params(config_id: int, update: StrategyConfigUpdate, db=Depends(get_db)):
    # Fetch current config
    row = await get_strategy_config_by_id(db, config_id)
    if not row:
        raise HTTPException(status_code=404, detail="Strategy config not found")
    if hasattr(row, "_mapping"):
        row = dict(row._mapping)
    # Only allow updating fields present in params
    allowed_keys = set(row["params"].keys())
    update_params = update.params or {}
    filtered_params = {k: v for k, v in update_params.items() if k in allowed_keys}
    # Merge with existing params
    new_params = {**row["params"], **filtered_params}
    update_data = {"params": new_params}
    if update.enabled is not None:
        update_data["enabled"] = update.enabled
    updated = await update_strategy_config(db, config_id, update_data)
    if hasattr(updated, "_mapping"):
        updated = dict(updated._mapping)
    return StrategyConfigDetailResponse(**updated)
