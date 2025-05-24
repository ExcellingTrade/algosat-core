from typing import Optional, Any

class OrderRequest:
    def __init__(
        self,
        symbol: str,
        quantity: int,
        side: str,  # "BUY" or "SELL"
        order_type: str,  # "MARKET", "LIMIT", "SL", etc.
        price: Optional[float] = None,
        trigger_price: Optional[float] = None,
        product_type: Optional[str] = None,  # "MIS", "NRML", etc.
        tag: Optional[str] = None,
        validity: Optional[str] = None,
        exchange: Optional[str] = None,
        segment: Optional[str] = None,
        variety: Optional[str] = None,
        extra: Optional[dict] = None,
    ):
        self.symbol = symbol
        self.quantity = quantity
        self.side = side
        self.order_type = order_type
        self.price = price
        self.trigger_price = trigger_price
        self.product_type = product_type
        self.tag = tag
        self.validity = validity
        self.exchange = exchange
        self.segment = segment
        self.variety = variety
        self.extra = extra or {}

    def to_dict(self) -> dict:
        return self.__dict__
