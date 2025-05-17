from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update, delete
from core.dbschema import broker_credentials
from api.schemas import BrokerResponse, BrokerCreate, BrokerUpdate
from api.dependencies import get_db
from typing import List

router = APIRouter()

@router.get("/", response_model=List[BrokerResponse])
async def list_brokers(db=Depends(get_db)):
    result = await db.execute(select(broker_credentials))
    return [BrokerResponse(**dict(row._mapping)) for row in result.fetchall()]

@router.get("/{broker_name}", response_model=BrokerResponse)
async def get_broker(broker_name: str, db=Depends(get_db)):
    result = await db.execute(select(broker_credentials).where(broker_credentials.c.broker_name == broker_name))
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Broker not found")
    return BrokerResponse(**dict(row._mapping))

@router.post("/", response_model=BrokerResponse)
async def add_broker(broker: BrokerCreate, db=Depends(get_db)):
    stmt = broker_credentials.insert().values(**broker.dict())
    res = await db.execute(stmt)
    await db.commit()
    broker_id = res.inserted_primary_key[0]
    result = await db.execute(select(broker_credentials).where(broker_credentials.c.id == broker_id))
    row = result.first()
    return BrokerResponse(**dict(row._mapping))

@router.delete("/{broker_name}")
async def delete_broker(broker_name: str, db=Depends(get_db)):
    stmt = delete(broker_credentials).where(broker_credentials.c.broker_name == broker_name)
    await db.execute(stmt)
    await db.commit()
    return {"status": "deleted", "broker_name": broker_name}

@router.put("/{broker_name}/enable")
async def enable_broker(broker_name: str, db=Depends(get_db)):
    stmt = update(broker_credentials).where(broker_credentials.c.broker_name == broker_name).values(is_enabled=True)
    await db.execute(stmt)
    await db.commit()
    return {"status": "enabled", "broker_name": broker_name}

@router.put("/{broker_name}/disable")
async def disable_broker(broker_name: str, db=Depends(get_db)):
    stmt = update(broker_credentials).where(broker_credentials.c.broker_name == broker_name).values(is_enabled=False)
    await db.execute(stmt)
    await db.commit()
    return {"status": "disabled", "broker_name": broker_name}

@router.put("/{broker_name}/enable-data-provider")
async def enable_data_provider(broker_name: str, db=Depends(get_db)):
    stmt = update(broker_credentials).where(broker_credentials.c.broker_name == broker_name).values(is_data_provider=True)
    await db.execute(stmt)
    await db.commit()
    return {"status": "data_provider_enabled", "broker_name": broker_name}

@router.put("/{broker_name}/disable-data-provider")
async def disable_data_provider(broker_name: str, db=Depends(get_db)):
    stmt = update(broker_credentials).where(broker_credentials.c.broker_name == broker_name).values(is_data_provider=False)
    await db.execute(stmt)
    await db.commit()
    return {"status": "data_provider_disabled", "broker_name": broker_name}

@router.put("/{broker_name}/enable-trade-execution")
async def enable_trade_execution(broker_name: str, db=Depends(get_db)):
    stmt = update(broker_credentials).where(broker_credentials.c.broker_name == broker_name).values(trade_execution_enabled=True)
    await db.execute(stmt)
    await db.commit()
    return {"status": "trade_execution_enabled", "broker_name": broker_name}

@router.put("/{broker_name}/disable-trade-execution")
async def disable_trade_execution(broker_name: str, db=Depends(get_db)):
    stmt = update(broker_credentials).where(broker_credentials.c.broker_name == broker_name).values(trade_execution_enabled=False)
    await db.execute(stmt)
    await db.commit()
    return {"status": "trade_execution_disabled", "broker_name": broker_name}

@router.post("/{broker_name}/auth")
async def reauth_broker(broker_name: str):
    # TODO: Implement broker re-authentication logic
    return {"status": "reauth_triggered", "broker_name": broker_name}
