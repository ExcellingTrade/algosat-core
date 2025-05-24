from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, Dict, Any

class Side(Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    # add more order types here if needed

@dataclass(frozen=True)
class OrderRequest:
    """
    Generic order request DTO capturing the strategy's intent.
    """
    symbol: str
    quantity: int
    side: Side                     # BUY or SELL
    order_type: OrderType          # MARKET, LIMIT, SL, etc.
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    product_type: Optional[str] = None  # MIS, NRML, INTRADAY, etc.
    tag: Optional[str] = None
    validity: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # validation: positive quantity
        if self.quantity <= 0:
            raise ValueError("quantity must be a positive integer")

        # validation: LIMIT orders require a price
        if self.order_type == OrderType.LIMIT and self.price is None:
            raise ValueError("limit orders require a 'price' value")

        # validation: SL orders require a trigger_price
        if self.order_type == OrderType.SL and self.trigger_price is None:
            raise ValueError("stop-loss orders require a 'trigger_price' value")

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dict, omitting any fields with None values.
        """
        return {k: v for k, v in asdict(self).items() if v is not None}
