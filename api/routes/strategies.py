from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, update
from sqlalchemy.exc import NoResultFound
from core.dbschema import strategy_configs
from api.schemas import StrategyConfigResponse, StrategyConfigUpdate
from api.dependencies import get_db
from typing import List

router = APIRouter()

@router.get("/", response_model=List[StrategyConfigResponse])
async def list_strategy_configs(db=Depends(get_db)):
    result = await db.execute(select(strategy_configs))
    return [StrategyConfigResponse(**dict(row._mapping)) for row in result.fetchall()]

@router.get("/{config_id}", response_model=StrategyConfigResponse)
async def get_strategy_config(config_id: int, db=Depends(get_db)):
    result = await db.execute(select(strategy_configs).where(strategy_configs.c.id == config_id))
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Strategy config not found")
    return StrategyConfigResponse(**dict(row._mapping))

@router.put("/{config_id}", response_model=StrategyConfigResponse)
async def update_strategy_config(config_id: int, update: StrategyConfigUpdate, db=Depends(get_db)):
    stmt = update(strategy_configs).where(strategy_configs.c.id == config_id).values(**update.dict(exclude_unset=True))
    await db.execute(stmt)
    await db.commit()
    result = await db.execute(select(strategy_configs).where(strategy_configs.c.id == config_id))
    row = result.first()
    return StrategyConfigResponse(**dict(row._mapping))

@router.post("/{config_id}/enable")
async def enable_strategy(config_id: int, db=Depends(get_db)):
    stmt = update(strategy_configs).where(strategy_configs.c.id == config_id).values(enabled=True)
    await db.execute(stmt)
    await db.commit()
    return {"status": "enabled", "id": config_id}

@router.post("/{config_id}/disable")
async def disable_strategy(config_id: int, db=Depends(get_db)):
    stmt = update(strategy_configs).where(strategy_configs.c.id == config_id).values(enabled=False)
    await db.execute(stmt)
    await db.commit()
    return {"status": "disabled", "id": config_id}

@router.post("/{config_id}/restart")
async def restart_strategy(config_id: int):
    # TODO: Implement runner restart logic
    return {"status": "restarted", "id": config_id}
