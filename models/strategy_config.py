"""StrategyConfig Pydantic schema."""

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class StrategyConfig(BaseModel):
    id: int  # config_id
    strategy_id: int
    name: Optional[str] = None  # config name
    description: Optional[str] = None  # config description
    exchange: str
    instrument: Optional[str] = None
    trade: Dict[str, Any] = Field(default_factory=dict)
    indicators: Dict[str, Any] = Field(default_factory=dict)
    
    # Symbol-specific fields (from the active symbol)
    symbol: Optional[str] = None  # Underlying symbol name (e.g., "NIFTY50", "BANKNIFTY")
    symbol_id: Optional[int] = None  # strategy_symbols.id (the strategy_symbol_id for DB relations)
    
    # Strategy-level fields
    strategy_key: Optional[str] = None
    strategy_name: Optional[str] = None
    
    # Legacy fields for backward compatibility
    is_default: bool = False
    enabled: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
