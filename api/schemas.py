from pydantic import BaseModel, Field
from typing import Optional, Any, Dict, List

# --- Strategy Schemas ---
class StrategyConfigBase(BaseModel):
    symbol: str
    exchange: str
    params: Dict[str, Any]
    enabled: bool
    is_default: Optional[bool] = False

class StrategyConfigCreate(StrategyConfigBase):
    pass

class StrategyConfigUpdate(BaseModel):
    params: Dict[str, Any]
    enabled: Optional[bool]

class StrategyConfigResponse(StrategyConfigBase):
    id: int
    strategy_id: int

    class Config:
        orm_mode = True

# --- Broker Schemas ---
class BrokerBase(BaseModel):
    broker_name: str
    credentials: Dict[str, Any]
    is_enabled: bool
    is_data_provider: bool
    trade_execution_enabled: bool
    notes: Optional[str] = None

class BrokerCreate(BrokerBase):
    pass

class BrokerUpdate(BaseModel):
    credentials: Optional[Dict[str, Any]]
    is_enabled: Optional[bool]
    is_data_provider: Optional[bool]
    trade_execution_enabled: Optional[bool]

class BrokerResponse(BrokerBase):
    id: int
    class Config:
        orm_mode = True

# --- Position Schemas ---
class PositionResponse(BaseModel):
    broker: str
    symbol: str
    quantity: float
    avg_price: float
    pnl: float
    status: str

# --- Trade Schemas ---
class TradeLogResponse(BaseModel):
    id: int
    config_id: int
    timestamp: str
    order_type: str
    qty: int
    price: Any
    status: str
    raw_response: Any

class PnLResponse(BaseModel):
    total_pnl: float
    details: Optional[List[Any]] = None
