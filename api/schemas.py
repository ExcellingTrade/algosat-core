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

class StrategyConfigCreate(StrategyConfigBase):
    pass

class StrategyConfigUpdate(BaseModel):
    name: Optional[str] = Field(None, description="Human-readable name for the config")
    description: Optional[str] = Field(None, description="Description of what this config does")
    exchange: Optional[str] = None
    instrument: Optional[str] = None
    trade: Optional[Dict[str, Any]] = None
    indicators: Optional[Dict[str, Any]] = None

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
    description: Optional[str] = Field(None, description="Strategy description")
    enabled: bool
    order_type: OrderTypeEnum
    product_type: ProductTypeEnum
    created_at: datetime
    updated_at: datetime
    
    @field_serializer("created_at", "updated_at")
    def serialize_dt(self, v):
        if isinstance(v, str):
            return v
        return v.isoformat() if v else None
    
    class Config:
        from_attributes = True

class StrategyDetailResponse(StrategyListResponse):
    # Inherits all fields from StrategyListResponse including created_at and updated_at
    pass

class StrategyUpdate(BaseModel):
    """Schema for updating strategy - only order_type and product_type allowed, not name"""
    order_type: Optional[OrderTypeEnum] = Field(None, description="Order type: MARKET or LIMIT")
    product_type: Optional[ProductTypeEnum] = Field(None, description="Product type: INTRADAY or DELIVERY")
    
    class Config:
        from_attributes = True

class StrategyConfigListResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    exchange: str
    instrument: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    @field_serializer("created_at", "updated_at")
    def serialize_dt(self, v):
        if isinstance(v, str):
            return v
        return v.isoformat() if v else None
    
    class Config:
        from_attributes = True

class StrategyConfigDetailResponse(StrategyConfigListResponse):
    trade: Dict[str, Any] = Field(default_factory=dict)
    indicators: Dict[str, Any] = Field(default_factory=dict)
    strategy_id: int

# --- Broker Schemas ---
class BrokerBase(BaseModel):
    broker_name: str
    credentials: Dict[str, Any]
    is_enabled: bool
    is_data_provider: bool
    trade_execution_enabled: bool
    status: str = "DISCONNECTED"
    last_auth_check: Optional[datetime] = None  # Accept datetime for DB compatibility
    notes: Optional[str] = None
    max_loss: Optional[float] = 10000.0
    max_profit: Optional[float] = 50000.0

    @field_serializer("last_auth_check")
    def serialize_last_auth_check(self, v):
        if isinstance(v, str):
            return v
        return v.isoformat() if v else None

class BrokerCreate(BrokerBase):
    pass

class BrokerUpdate(BaseModel):
    credentials: Optional[Dict[str, Any]] = None
    is_enabled: Optional[bool] = None
    is_data_provider: Optional[bool] = None
    trade_execution_enabled: Optional[bool] = None
    status: Optional[str] = None
    last_auth_check: Optional[datetime] = None
    max_loss: Optional[float] = None
    max_profit: Optional[float] = None

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
    status: str = "DISCONNECTED"
    last_auth_check: Optional[datetime] = None
    notes: Optional[str] = None
    max_loss: Optional[float] = 10000.0
    max_profit: Optional[float] = 50000.0

    @field_serializer("last_auth_check")
    def serialize_last_auth_check(self, v):
        if isinstance(v, str):
            return v
        return v.isoformat() if v else None

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
class PlaceOrderResponse(BaseModel):
    """Response model for place_order API endpoint."""
    order_id: int = Field(..., description="Unique order ID from the orders table")
    traded_price: float = Field(default=0.0, description="Traded price (0.0 for pending orders, will be updated per broker)")
    status: str = Field(default="AWAITING_ENTRY", description="Current order status")
    broker_responses: Dict[str, Any] = Field(default_factory=dict, description="Responses from individual brokers")

class OrderListResponse(BaseModel):
    """Order list response with basic metadata."""
    id: int  # This is the order_id from orders table
    order_id: int  # Alias for id for clarity in frontend
    strategy_name: Optional[str] = None  # Strategy name from strategies table
    symbol: Optional[str] = None  # This will be the strategy symbol name (from join)
    strike_symbol: Optional[str] = None  # Actual tradeable symbol
    pnl: Optional[float] = None  # Profit/Loss for this order
    status: str  # Now supports: AWAITING_ENTRY, OPEN, CLOSED, CANCELLED, FAILED
    side: Optional[str] = None
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None  # Exit price for this order
    current_price: Optional[float] = None  # Current LTP price for strike symbol
    price_last_updated: Optional[datetime] = None  # When the current_price was last updated
    lot_qty: Optional[int] = None
    qty: Optional[int] = None
    executed_quantity: Optional[int] = None  # <-- Add this field
    signal_time: Optional[datetime] = None
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None  # Exit time for this order
    created_at: Optional[datetime] = None
    traded_price: Optional[float] = Field(default=0.0, description="Actual traded price")
    broker_executions: Optional[List[Dict[str, Any]]] = Field(default=[], description="List of broker executions for this order")
    smart_level_enabled: Optional[bool] = Field(default=False, description="Whether smart levels are enabled for this strategy symbol")
    is_hedge: bool = Field(default=False, description="Whether this order is a hedge order (has parent_order_id)")
    parent_order_id: Optional[int] = Field(None, description="Parent order ID if this is a hedge order")

    @field_serializer("signal_time", "entry_time", "exit_time", "created_at", "price_last_updated")
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
    current_price: Optional[float] = None  # Current LTP price for strike symbol
    price_last_updated: Optional[datetime] = None  # When the current_price was last updated
    signal_time: Optional[datetime] = None
    entry_time: Optional[datetime] = None
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    status: str  # Now supports: AWAITING_ENTRY, OPEN, CLOSED, CANCELLED, FAILED
    reason: Optional[str] = None
    atr: Optional[float] = None
    supertrend_signal: Optional[str] = None
    lot_qty: Optional[int] = None
    side: Optional[str] = None
    qty: Optional[int] = None
    executed_quantity: Optional[int] = None  # <-- Add this field
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    traded_price: Optional[float] = Field(default=0.0, description="Actual traded price")
    # Add any other fields from the orders table as needed

    @field_serializer("signal_time", "entry_time", "exit_time", "created_at", "updated_at", "price_last_updated")
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
    enable_smart_levels: bool = False

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

# --- Execution and P&L Schemas ---
class ExecutionSideEnum(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"

class GranularExecutionResponse(BaseModel):
    """Response model for individual execution records."""
    id: int
    parent_order_id: int
    broker_id: int
    broker_order_id: str
    side: ExecutionSideEnum
    execution_price: float
    executed_quantity: int
    execution_time: Optional[datetime] = None
    execution_id: Optional[str] = None
    is_partial_fill: bool = False
    sequence_number: Optional[int] = None
    symbol: Optional[str] = None
    order_type: Optional[str] = None
    notes: Optional[str] = None
    status: str
    created_at: datetime

    @field_serializer('execution_time', 'created_at')
    def serialize_datetime(self, dt: Optional[datetime]) -> Optional[str]:
        return to_ist(dt).isoformat() if dt else None

class ExecutionSummaryResponse(BaseModel):
    """Response model for execution summary with VWAP calculations."""
    order_id: int
    entry_executions: List[GranularExecutionResponse]
    exit_executions: List[GranularExecutionResponse]
    entry_vwap: float
    exit_vwap: float
    entry_qty: int
    exit_qty: int
    realized_pnl: float
    unrealized_pnl: float

# --- Orders Summary Schema ---
class OrdersSummaryResponse(BaseModel):
    """Response model for orders summary by symbol."""
    symbol: str = Field(..., description="Symbol name")
    total_trades: int = Field(default=0, description="Total number of trades/orders")
    open_trades: int = Field(default=0, description="Number of open trades")
    closed_trades: int = Field(default=0, description="Number of closed trades")
    total_pnl: float = Field(default=0.0, description="Total P&L for all orders")
    live_pnl: float = Field(default=0.0, description="Live P&L for open positions")
    avg_trade_pnl: float = Field(default=0.0, description="Average P&L per trade")

# --- Orders PNL Statistics Schema ---
class OrdersPnlStatsResponse(BaseModel):
    """Response model for overall and today's P&L statistics."""
    overall_pnl: float = Field(..., description="Overall P&L for all trades")
    overall_trade_count: int = Field(..., description="Total number of trades")
    today_pnl: float = Field(..., description="Today's P&L")
    today_trade_count: int = Field(..., description="Today's trade count")

# --- Strategy Statistics Schema ---
class StrategyStatsResponse(BaseModel):
    """Response model for strategy profit/loss statistics."""
    strategies_in_profit: int = Field(..., description="Number of strategies currently in profit")
    strategies_in_loss: int = Field(..., description="Number of strategies currently in loss")
    total_strategies: int = Field(..., description="Total number of strategies with trades")

# --- Daily PNL History Schema ---
class DailyPnlData(BaseModel):
    """Response model for daily P&L data point."""
    date: str = Field(..., description="Date in YYYY-MM-DD format")
    daily_pnl: float = Field(..., description="P&L for this specific day")
    trade_count: int = Field(..., description="Number of trades on this day")
    cumulative_pnl: float = Field(..., description="Cumulative P&L up to this date")

class DailyPnlHistoryResponse(BaseModel):
    """Response model for daily P&L history."""
    history: List[DailyPnlData] = Field(..., description="List of daily P&L data")
    total_days: int = Field(..., description="Total number of days with data")

# --- Per-Strategy Statistics Schema ---
class PerStrategyStatsData(BaseModel):
    """Response model for individual strategy statistics."""
    strategy_id: int = Field(..., description="Strategy ID")
    strategy_name: str = Field(..., description="Strategy name")
    live_pnl: float = Field(..., description="Today's P&L for this strategy")
    overall_pnl: float = Field(..., description="All-time P&L for this strategy")
    trade_count: int = Field(..., description="Total number of trades for this strategy")
    win_rate: float = Field(..., description="Win rate percentage (0-100)")

class PerStrategyStatsResponse(BaseModel):
    """Response model for per-strategy statistics."""
    strategies: List[PerStrategyStatsData] = Field(..., description="List of strategy statistics")
    total_strategies: int = Field(..., description="Total number of strategies")

# --- Smart Levels Schemas ---
class SmartLevelBase(BaseModel):
    """Base schema for Smart Level with common fields."""
    name: str = Field(..., description="Name for the smart level", min_length=1, max_length=100)
    is_active: bool = Field(True, description="Whether this smart level is active")
    entry_level: float = Field(..., description="Entry level price")
    bullish_target: Optional[float] = Field(None, description="Bullish target price (should be above entry_level)")
    bearish_target: Optional[float] = Field(None, description="Bearish target price (should be below entry_level)")
    initial_lot_ce: Optional[int] = Field(None, description="Initial lots for Call options", ge=0)
    initial_lot_pe: Optional[int] = Field(None, description="Initial lots for Put options", ge=0)
    remaining_lot_ce: Optional[int] = Field(None, description="Remaining lots for Call options", ge=0)
    remaining_lot_pe: Optional[int] = Field(None, description="Remaining lots for Put options", ge=0)
    ce_buy_enabled: bool = Field(False, description="Enable CE buy orders")
    ce_sell_enabled: bool = Field(False, description="Enable CE sell orders")
    pe_buy_enabled: bool = Field(False, description="Enable PE buy orders")
    pe_sell_enabled: bool = Field(False, description="Enable PE sell orders")
    max_trades: Optional[int] = Field(None, description="Maximum number of trades allowed", ge=0)
    max_loss_trades: Optional[int] = Field(None, description="Maximum number of loss trades allowed", ge=0)
    pullback_percentage: Optional[float] = Field(None, description="Pullback percentage for entry", ge=0, le=100)
    strict_entry_vs_swing_check: bool = Field(False, description="Enable strict entry vs swing check validation")
    notes: Optional[str] = Field(None, description="Additional notes for this smart level")

class SmartLevelCreate(SmartLevelBase):
    """Schema for creating a new Smart Level."""
    strategy_symbol_id: int = Field(..., description="Strategy symbol ID this smart level belongs to", gt=0)

class SmartLevelUpdate(BaseModel):
    """Schema for updating an existing Smart Level."""
    name: Optional[str] = Field(None, description="Name for the smart level", min_length=1, max_length=100)
    is_active: Optional[bool] = Field(None, description="Whether this smart level is active")
    entry_level: Optional[float] = Field(None, description="Entry level price")
    bullish_target: Optional[float] = Field(None, description="Bullish target price (should be above entry_level)")
    bearish_target: Optional[float] = Field(None, description="Bearish target price (should be below entry_level)")
    initial_lot_ce: Optional[int] = Field(None, description="Initial lots for Call options", ge=0)
    initial_lot_pe: Optional[int] = Field(None, description="Initial lots for Put options", ge=0)
    remaining_lot_ce: Optional[int] = Field(None, description="Remaining lots for Call options", ge=0)
    remaining_lot_pe: Optional[int] = Field(None, description="Remaining lots for Put options", ge=0)
    ce_buy_enabled: Optional[bool] = Field(None, description="Enable CE buy orders")
    ce_sell_enabled: Optional[bool] = Field(None, description="Enable CE sell orders")
    pe_buy_enabled: Optional[bool] = Field(None, description="Enable PE buy orders")
    pe_sell_enabled: Optional[bool] = Field(None, description="Enable PE sell orders")
    max_trades: Optional[int] = Field(None, description="Maximum number of trades allowed", ge=0)
    max_loss_trades: Optional[int] = Field(None, description="Maximum number of loss trades allowed", ge=0)
    pullback_percentage: Optional[float] = Field(None, description="Pullback percentage for entry", ge=0, le=100)
    strict_entry_vs_swing_check: Optional[bool] = Field(None, description="Enable strict entry vs swing check validation")
    notes: Optional[str] = Field(None, description="Additional notes for this smart level")

class SmartLevelResponse(SmartLevelBase):
    """Schema for Smart Level response."""
    id: int = Field(..., description="Smart Level ID")
    strategy_symbol_id: int = Field(..., description="Strategy symbol ID this smart level belongs to")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")

    @field_serializer("created_at", "updated_at")
    def serialize_dt(self, v):
        if isinstance(v, str):
            return v
        return v.isoformat() if v else None

    class Config:
        from_attributes = True
