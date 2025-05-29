from pydantic import BaseModel
from typing import List, Optional, Dict, Any

class BrokerOrder(BaseModel):
    broker_id: int
    order_id: Optional[int]  # local DB order id
    status: str
    raw_response: Dict[str, Any]

class OrderAggregate(BaseModel):
    strategy_config_id: int
    parent_order_id: Optional[int]
    symbol: str
    entry_price: Optional[float]
    side: Optional[str]
    broker_orders: List[BrokerOrder]
