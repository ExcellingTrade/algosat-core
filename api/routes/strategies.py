from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any, List

from algosat.core.db import (
    get_all_strategies,
    get_strategy_by_id,
    get_strategy_configs_by_strategy_id,
    get_strategy_config_by_id,
    update_strategy_config,
)
from algosat.api.schemas import (
    StrategyListResponse,
    StrategyDetailResponse,
    StrategyConfigListResponse,
    StrategyConfigDetailResponse,
    StrategyConfigUpdate,
)
from algosat.api.dependencies import get_db
from algosat.api.auth_dependencies import get_current_user
from algosat.core.security import EnhancedInputValidator, InvalidInputError
from algosat.common.logger import get_logger

logger = get_logger("api.strategies")

# Require authentication for all endpoints in this router
router = APIRouter(dependencies=[Depends(get_current_user)])
input_validator = EnhancedInputValidator()

@router.get("/", response_model=List[StrategyListResponse])
async def list_strategies(db=Depends(get_db)):
    try:
        strategies = [StrategyListResponse(**row) for row in await get_all_strategies(db)]
        return sorted(strategies, key=lambda s: s.id)
    except Exception as e:
        logger.error(f"Error in list_strategies: {e}")
        raise

@router.get("/{strategy_id}", response_model=StrategyDetailResponse)
async def get_strategy(strategy_id: int, db=Depends(get_db)):
    try:
        validated_strategy_id = input_validator.validate_integer(strategy_id, "strategy_id", min_value=1)
        row = await get_strategy_by_id(db, validated_strategy_id)
        if not row:
            raise HTTPException(status_code=404, detail="Strategy not found")
        return StrategyDetailResponse(**row)
    except Exception as e:
        logger.error(f"Error in get_strategy: {e}")
        raise

@router.get("/{strategy_id}/configs", response_model=List[StrategyConfigListResponse])
async def list_strategy_configs_for_strategy(strategy_id: int, db=Depends(get_db)):
    try:
        validated_strategy_id = input_validator.validate_integer(strategy_id, "strategy_id", min_value=1)
        configs = [StrategyConfigListResponse(**row) for row in await get_strategy_configs_by_strategy_id(db, validated_strategy_id)]
        return sorted(configs, key=lambda c: c.id)
    except Exception as e:
        logger.error(f"Error in list_strategy_configs_for_strategy: {e}")
        raise

@router.get("/configs/{config_id}", response_model=StrategyConfigDetailResponse)
async def get_strategy_config_detail(config_id: int, db=Depends(get_db)):
    try:
        validated_config_id = input_validator.validate_integer(config_id, "config_id", min_value=1)
        row = await get_strategy_config_by_id(db, validated_config_id)
        if not row:
            raise HTTPException(status_code=404, detail="Strategy config not found")
        # Convert SQLAlchemy Row to dict if needed
        if hasattr(row, "_mapping"):
            row = dict(row._mapping)
        return StrategyConfigDetailResponse(**row)
    except Exception as e:
        logger.error(f"Error in get_strategy_config_detail: {e}")
        raise

@router.get("/{strategy_id}/confesigs/{config_id}", response_model=StrategyConfigDetailResponse)
async def get_strategy_config_detail_for_strategy(strategy_id: int, config_id: int, db=Depends(get_db)):
    try:
        validated_strategy_id = input_validator.validate_integer(strategy_id, "strategy_id", min_value=1)
        validated_config_id = input_validator.validate_integer(config_id, "config_id", min_value=1)
        row = await get_strategy_config_by_id(db, validated_config_id)
        if not row:
            raise HTTPException(status_code=404, detail="Strategy config not found")
        if hasattr(row, "_mapping"):
            row = dict(row._mapping)
        if "params" not in row or row["params"] is None:
            row["params"] = {}
        if row.get("strategy_id") != validated_strategy_id: # Use validated id
            raise HTTPException(status_code=404, detail="Strategy config does not belong to this strategy")
        return StrategyConfigDetailResponse(**row)
    except Exception as e:
        logger.error(f"Error in get_strategy_config_detail_for_strategy: {e}")
        raise

@router.put("/configs/{config_id}", response_model=StrategyConfigDetailResponse)
async def update_strategy_config_params(config_id: int, update: StrategyConfigUpdate, db=Depends(get_db)):
    validated_config_id = input_validator.validate_integer(config_id, "config_id", min_value=1)
    # Validate fields within update.params if necessary.
    if update.params:
        for key, value in update.params.items():
            if isinstance(value, str):
                update.params[key] = input_validator.validate_and_sanitize(value, f"params.{{key}}", max_length=1024)
            elif isinstance(value, (int, float)):
                pass
    # Enforce order_type and product_type restrictions
    if update.order_type and update.order_type not in ("MARKET", "LIMIT"):
        raise HTTPException(status_code=400, detail="order_type must be 'MARKET' or 'LIMIT'")
    if update.product_type and update.product_type not in ("INTRADAY", "DELIVERY"):
        raise HTTPException(status_code=400, detail="product_type must be 'INTRADAY' or 'DELIVERY'")
    # Fetch current config
    row = await get_strategy_config_by_id(db, validated_config_id)
    if not row:
        raise HTTPException(status_code=404, detail="Strategy config not found")
    if hasattr(row, "_mapping"):
        row = dict(row._mapping)
    allowed_keys = set(row["params"].keys())
    update_params = update.params or {}
    filtered_params = {k: v for k, v in update_params.items() if k in allowed_keys}
    new_params = {**row["params"], **filtered_params}
    update_data = {"params": new_params}
    if update.enabled is not None:
        update_data["enabled"] = update.enabled
    if update.order_type:
        update_data["order_type"] = update.order_type
    if update.product_type:
        update_data["product_type"] = update.product_type
    updated = await update_strategy_config(db, validated_config_id, update_data)
    if hasattr(updated, "_mapping"):
        updated = dict(updated._mapping)
    return StrategyConfigDetailResponse(**updated)
