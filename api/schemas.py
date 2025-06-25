from pydantic import BaseModel, Field, field_serializer
from typing import Optional, Any, Dict, List
from datetime import datetime
from algosat.core.time_utils import to_ist
from enum import Enum

# --- Authentication Schemas ---
class LoginRequest(BaseModel):
    """Request model for user login."""
    username: str = Field(..., description="Username for authentication", min_length=1, max_length=50)
    password: str = Field(..., description="Password for authentication", min_length=1, max_length=100)

class TokenResponse(BaseModel):
    """Response model for authentication token."""
    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(..., description="Token expiration time in seconds")
    user_info: Dict[str, Any] = Field(..., description="Authenticated user information")

# --- Order Type and Product Type Enums ---
class OrderTypeEnum(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"

class ProductTypeEnum(str, Enum):
    INTRADAY = "INTRADAY"
    DELIVERY = "DELIVERY"

# --- Strategy Schemas ---
class StrategyConfigBase(BaseModel):
    name: str = Field(..., description="Human-readable name for the config")
    description: Optional[str] = Field(None, description="Description of what this config does")
    exchange: str
    instrument: Optional[str] = Field(None, description="Instrument type")
    trade: Dict[str, Any] = Field(default_factory=dict)
    indicators: Dict[str, Any] = Field(default_factory=dict)
    order_type: OrderTypeEnum = Field(..., description="Order type: MARKET or LIMIT")
    product_type: ProductTypeEnum = Field(..., description="Product type: INTRADAY or DELIVERY")

class StrategyConfigCreate(StrategyConfigBase):
    pass

class StrategyConfigUpdate(BaseModel):
    name: Optional[str] = Field(None, description="Human-readable name for the config")
    description: Optional[str] = Field(None, description="Description of what this config does")
    exchange: Optional[str] = None
    instrument: Optional[str] = None
    trade: Optional[Dict[str, Any]] = None
    indicators: Optional[Dict[str, Any]] = None
    order_type: Optional[OrderTypeEnum] = None
    product_type: Optional[ProductTypeEnum] = None

class StrategyConfigResponse(StrategyConfigBase):
    id: int
    strategy_id: int
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def serialize_dt(self, v):
        if isinstance(v, str):
            return v
        return v.isoformat() if v else None

    class Config:
        from_attributes = True

class StrategyListResponse(BaseModel):
    id: int
    key: str
    name: str
    enabled: bool
    order_type: OrderTypeEnum
    product_type: ProductTypeEnum
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
    name: str
    description: Optional[str] = None
    exchange: str
    instrument: Optional[str] = None
    order_type: OrderTypeEnum
    product_type: ProductTypeEnum
    
    class Config:
        from_attributes = True

class StrategyConfigDetailResponse(StrategyConfigListResponse):
    trade: Dict[str, Any] = Field(default_factory=dict)
    indicators: Dict[str, Any] = Field(default_factory=dict)
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

# --- Order Schemas ---
class OrderListResponse(BaseModel):
    """Order list response with basic metadata."""
    id: int
    symbol: str
    status: str
    side: Optional[str] = None
    entry_price: Optional[float] = None
    lot_qty: Optional[int] = None
    signal_time: Optional[datetime] = None
    entry_time: Optional[datetime] = None

    @field_serializer("signal_time", "entry_time")
    def serialize_dt(self, v):
        if v is None:
            return None
        ist_dt = to_ist(v)
        return ist_dt.isoformat()

    class Config:
        from_attributes = True

class OrderDetailResponse(BaseModel):
    """Order detail response with full information."""
    id: int
    strategy_config_id: int
    symbol: str
    candle_range: Optional[float] = None
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None
    signal_time: Optional[datetime] = None
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    status: str
    reason: Optional[str] = None
    atr: Optional[float] = None
    supertrend_signal: Optional[str] = None
    lot_qty: Optional[int] = None
    side: Optional[str] = None
    qty: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Add any other fields from the orders table as needed

    @field_serializer("signal_time", "entry_time", "exit_time", "created_at", "updated_at")
    def serialize_dt(self, v):
        if v is None:
            return None
        ist_dt = to_ist(v)
        return ist_dt.isoformat()

    class Config:
        from_attributes = True

class BrokerExecutionResponse(BaseModel):
    id: int
    order_id: int
    broker: Optional[str] = None
    broker_name: Optional[str] = None
    broker_id: Optional[int] = None
    broker_order_ids: Optional[Any] = None
    order_messages: Optional[Any] = None
    status: str
    raw_response: Optional[Any] = None
    filled_qty: Optional[float] = None
    avg_price: Optional[float] = None
    executed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def validate(cls, value):
        # If 'broker' is missing but 'broker_name' is present, use that
        if 'broker' not in value or value['broker'] is None:
            if 'broker_name' in value and value['broker_name']:
                value['broker'] = value['broker_name']
        return value

    @field_serializer("executed_at", "created_at", "updated_at")
    def serialize_dt(self, v):
        if v is None:
            return None
        ist_dt = to_ist(v)
        return ist_dt.isoformat()

    class Config:
        from_attributes = True

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

# --- User Schemas ---
class UserRegisterRequest(BaseModel):
    """Request model for user registration."""
    username: str = Field(..., min_length=3, max_length=50, description="Unique username for the user")
    email: str = Field(..., min_length=5, max_length=254, description="User's email address")
    password: str = Field(..., min_length=8, max_length=128, description="User's password (will be hashed)")
    full_name: Optional[str] = Field(None, max_length=100, description="Full name of the user")

class UserResponse(BaseModel):
    """Response model for user information."""
    id: int
    username: str
    email: str
    full_name: Optional[str]
    is_active: bool
    role: str
    created_at: datetime
    updated_at: datetime
    class Config:
        from_attributes = True

class StrategySymbolBase(BaseModel):
    strategy_id: int
    symbol: str
    config_id: int
    status: str = 'active'

class StrategySymbolCreate(StrategySymbolBase):
    pass

class StrategySymbolResponse(StrategySymbolBase):
    id: int
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def serialize_dt(self, v):
        if isinstance(v, str):
            return v
        return v.isoformat() if v else None

    class Config:
        from_attributes = True

class StrategySymbolWithConfigResponse(StrategySymbolResponse):
    config_name: Optional[str] = None
    config_description: Optional[str] = None
    trade_count: Optional[int] = 0
    current_pnl: Optional[float] = 0.0
    enabled: Optional[bool] = None  # Computed from status
