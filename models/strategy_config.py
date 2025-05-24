"""StrategyConfig Pydantic schema."""

from typing import Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class StrategyConfig(BaseModel):
    id: int
    strategy_id: int
    symbol: str
    exchange: str
    instrument: Optional[str] = None
    trade: Dict[str, Any] = Field(default_factory=dict)
    indicators: Dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False
    enabled: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
