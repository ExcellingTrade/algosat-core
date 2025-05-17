from pydantic import BaseModel, Field, field_serializer
from typing import Optional, Any, Dict, List
from datetime import datetime

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
        from_attributes = True

class StrategyListResponse(BaseModel):
    id: int
    key: str
    name: str
    enabled: bool
    class Config:
        from_attributes = True

class StrategyDetailResponse(StrategyListResponse):
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def serialize_dt(self, v):
        if isinstance(v, str):
            return v
        return v.isoformat() if v else None

class StrategyConfigListResponse(BaseModel):
    id: int
    symbol: str
    exchange: str
    enabled: bool
    is_default: Optional[bool] = False
    class Config:
        from_attributes = True

class StrategyConfigDetailResponse(StrategyConfigListResponse):
    params: Dict[str, Any]
    strategy_id: int
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def serialize_dt(self, v):
        if isinstance(v, str):
            return v
        return v.isoformat() if v else None

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
        from_attributes = True

class BrokerListResponse(BaseModel):
    id: int
    broker_name: str
    is_enabled: bool
    is_data_provider: bool
    trade_execution_enabled: bool
    notes: Optional[str] = None

    class Config:
        from_attributes = True

class BrokerDetailResponse(BrokerListResponse):
    credentials: Dict[str, Any]

    @staticmethod
    def mask_sensitive(data: dict) -> dict:
        creds = data.get("credentials", {})
        # Remove or mask sensitive fields
        for k in ["access_token", "refresh_token", "api_secret", "password", "totp_secret"]:
            if k in creds:
                creds[k] = "****"
        data["credentials"] = creds
        return data

    @classmethod
    def from_db(cls, data: dict):
        return cls(**cls.mask_sensitive(data))

# --- Position Schemas ---
class PositionResponse(BaseModel):
    broker: str
    symbol: str
    quantity: float
    avg_price: float
    pnl: float
    status: str
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None

    @field_serializer("opened_at", "closed_at")
    def serialize_dt(self, v):
        if isinstance(v, str):
            return v
        return v.isoformat() if v else None

    class Config:
        from_attributes = True

# --- Trade Schemas ---
class TradeLogResponse(BaseModel):
    id: int
    config_id: int
    timestamp: datetime
    order_type: str
    qty: int
    price: Any
    status: str
    raw_response: Any

    @field_serializer("timestamp")
    def serialize_dt(self, v):
        if isinstance(v, str):
            return v
        return v.isoformat() if v else None

    class Config:
        from_attributes = True

class PnLResponse(BaseModel):
    total_pnl: float
    details: Optional[List[Any]] = None
    class Config:
        from_attributes = True
