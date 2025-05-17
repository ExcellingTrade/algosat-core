from fastapi import APIRouter, Depends, HTTPException, Body
from core.db import get_all_brokers, get_broker_by_name, add_broker, update_broker, delete_broker
from api.schemas import BrokerResponse, BrokerCreate, BrokerUpdate, BrokerListResponse, BrokerDetailResponse
from api.dependencies import get_db
from typing import List

router = APIRouter()

@router.get("/", response_model=List[BrokerListResponse])
async def list_brokers(db=Depends(get_db)):
    return [BrokerListResponse(**row) for row in await get_all_brokers(db)]

@router.get("/{broker_name}", response_model=BrokerDetailResponse)
async def get_broker(broker_name: str, db=Depends(get_db)):
    row = await get_broker_by_name(db, broker_name)
    if not row:
        raise HTTPException(status_code=404, detail="Broker not found")
    return BrokerDetailResponse.from_db(row)

@router.post("/", response_model=BrokerResponse)
async def add_broker_api(broker: BrokerCreate, db=Depends(get_db)):
    row = await add_broker(db, broker.dict())
    return BrokerResponse(**row)

@router.delete("/{broker_name}")
async def delete_broker_api(broker_name: str, db=Depends(get_db)):
    await delete_broker(db, broker_name)
    return {"status": "deleted", "broker_name": broker_name}

@router.put("/{broker_name}/enable")
async def enable_broker(broker_name: str, db=Depends(get_db)):
    row = await update_broker(db, broker_name, {"is_enabled": True})
    return {"status": "enabled", "broker_name": broker_name}

@router.put("/{broker_name}/disable")
async def disable_broker(broker_name: str, db=Depends(get_db)):
    row = await update_broker(db, broker_name, {"is_enabled": False})
    return {"status": "disabled", "broker_name": broker_name}

@router.put("/{broker_name}/enable-data-provider")
async def enable_data_provider(broker_name: str, db=Depends(get_db)):
    row = await update_broker(db, broker_name, {"is_data_provider": True})
    return {"status": "data_provider_enabled", "broker_name": broker_name}

@router.put("/{broker_name}/disable-data-provider")
async def disable_data_provider(broker_name: str, db=Depends(get_db)):
    row = await update_broker(db, broker_name, {"is_data_provider": False})
    return {"status": "data_provider_disabled", "broker_name": broker_name}

@router.put("/{broker_name}/enable-trade-execution")
async def enable_trade_execution(broker_name: str, db=Depends(get_db)):
    row = await update_broker(db, broker_name, {"trade_execution_enabled": True})
    return {"status": "trade_execution_enabled", "broker_name": broker_name}

@router.put("/{broker_name}/disable-trade-execution")
async def disable_trade_execution(broker_name: str, db=Depends(get_db)):
    row = await update_broker(db, broker_name, {"trade_execution_enabled": False})
    return {"status": "trade_execution_disabled", "broker_name": broker_name}

@router.post("/{broker_name}/auth")
async def reauth_broker(broker_name: str):
    # TODO: Implement broker re-authentication logic
    return {"status": "reauth_triggered", "broker_name": broker_name}

@router.put("/{broker_name}", response_model=BrokerResponse)
async def update_broker_api(
    broker_name: str,
    update: BrokerUpdate = Body(...),
    db=Depends(get_db)
):
    row = await update_broker(db, broker_name, {k: v for k, v in update.dict(exclude_unset=True).items()})
    if not row:
        raise HTTPException(status_code=404, detail="Broker not found")
    return BrokerResponse(**row)
