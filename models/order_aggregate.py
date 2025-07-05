from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Union

class BrokerOrder(BaseModel):
    id: Optional[int] = None  # Add id field for broker_executions table PK
    broker_id: int
    order_id: Union[str, int, List[Union[str, int]], None]  # Accepts str, int, or list
    status: str
    side: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None  # Allow None/null values

class OrderAggregate(BaseModel):
    strategy_config_id: int
    parent_order_id: Optional[int]
    symbol: str
    entry_price: Optional[float]
    side: Optional[str]
    broker_orders: List[BrokerOrder]
