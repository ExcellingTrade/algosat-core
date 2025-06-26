"""
Pydantic models for broker-related data structures.
"""
from pydantic import BaseModel, Field
from typing import Optional


class BalanceSummary(BaseModel):
    """
    Standardized balance summary model for all brokers.
    Provides consistent structure with default values of 0.
    """
    total_balance: float = Field(default=0.0, description="Total account balance")
    available: float = Field(default=0.0, description="Available balance for trading")
    utilized: float = Field(default=0.0, description="Utilized/blocked balance")
    
    class Config:
        # Allow extra fields in case brokers provide additional balance info
        extra = "allow"
        # Use float instead of Decimal for easier JSON serialization
        json_encoders = {
            float: lambda v: round(v, 2) if v else 0.0
        }
    
    def to_dict(self) -> dict:
        """Convert to dictionary for backward compatibility."""
        return {
            "total_balance": self.total_balance,
            "available": self.available,
            "utilized": self.utilized
        }
