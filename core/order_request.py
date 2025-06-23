from pydantic import BaseModel, Field
from pydantic import field_validator
from enum import Enum
from typing import Optional, Dict, Any, List

class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    def to_fyers(self):
        return 1 if self == Side.BUY else -1
    def to_zerodha(self):
        return self.value

class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_LIMIT = "SL_LIMIT"
    OPTION_STRATEGY = "OPTION_STRATEGY"

class ProductType(str, Enum):
    INTRADAY = "INTRADAY"
    NRML = "NRML"
    MIS = "MIS"
    CNC = "CNC"
    OPTION_STRATEGY = "OPTION_STRATEGY"  # Accept logical value for validation
    BO = "BO"  # Accept broker-specific value for validation

class OrderStatus(str, Enum):
    AWAITING_ENTRY = "AWAITING_ENTRY"
    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    COMPLETED = "COMPLETED"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    TRIGGER_PENDING = "TRIGGER_PENDING"
    AMO_REQ_RECEIVED = "AMO_REQ_RECEIVED"

class OrderRequest(BaseModel):
    symbol: str
    quantity: int
    side: Side
    order_type: OrderType
    price: Optional[float] = None
    trigger_price: Optional[float] = None
    product_type: Optional[ProductType] = None
    tag: Optional[str] = None
    validity: Optional[str] = None
    exchange: Optional[str] = None
    variety: Optional[str] = None
    extra: Dict[str, Any] = {}

    @field_validator('quantity')
    def positive_quantity(cls, v):
        if v <= 0:
            raise ValueError('quantity must be a positive integer')
        return v

    @field_validator('price', mode='before')
    def limit_requires_price(cls, v, values):
        try:
            order_type = values.data.get('order_type') if hasattr(values, 'data') else values.get('order_type')
            if order_type == OrderType.LIMIT and v is None:
                raise ValueError("limit orders require a 'price' value")
            return v
        except Exception as e:
            print(f"Error in price validation: {e}")
            return v

    @field_validator('trigger_price', mode='before')
    def sl_requires_trigger_price(cls, v, values):
        order_type = values.data.get('order_type') if hasattr(values, 'data') else values.get('order_type')
        if order_type == OrderType.SL and v is None:
            raise ValueError("stop-loss orders require a 'trigger_price' value")
        return v

    def to_fyers_dict(self) -> dict:
        # Map logical types to Fyers-specific
        order_type = self.order_type
        product_type = self.product_type
        strategy_name = self.extra.get('strategy_name')
        if order_type == OrderType.OPTION_STRATEGY:
            order_type = "SL_LIMIT"
        if product_type == ProductType.OPTION_STRATEGY:
            product_type = "BO"
        # Extract lot_qty, lot_size, stoploss, takeprofit from extra if present
        # lot_qty = self.extra.get("lot_qty")
        # lot_size = self.extra.get("lot_size")
        # stoploss = self.extra.get("stoploss") or self.extra.get("stopLoss")
        # takeprofit = self.extra.get("takeprofit") or self.extra.get("takeProfit")
        fyers_dict = {
            "symbol": self.symbol,
            "qty": self.quantity,
            "type": ORDER_TYPE_MAP.get(order_type, 2) if isinstance(order_type, OrderType) else ORDER_TYPE_MAP.get(OrderType(order_type), 2),
            "side": self.side.to_fyers(),
            "productType": PRODUCT_TYPE_MAP.get(product_type, "INTRADAY") if isinstance(product_type, str) else PRODUCT_TYPE_MAP.get(product_type.value, "INTRADAY"),
            "limitPrice": float(self.price) if self.price is not None else 0,
            "stopPrice": float(self.trigger_price) if self.trigger_price is not None else 0,
            "disclosedQty": self.extra.get("disclosedQty", 0),
            "validity": self.validity or "DAY",
            "offlineOrder": self.extra.get("offlineOrder", False),
            "stopLoss": self.extra.get("stopLoss", 0),
            "takeProfit": self.extra.get("takeProfit", 0),
            "orderTag": self.tag or ""
        }
        # Optionally include lot_qty and lot_size for downstream broker logic
        # if lot_qty is not None:
        #     fyers_dict["lot_qty"] = lot_qty
        # if lot_size is not None:
        #     fyers_dict["lot_size"] = lot_size
        # Only include orderTag if productType is not BO
        product_type_val = fyers_dict.get("productType")
        if product_type_val == "BO":
            fyers_dict.pop("orderTag", None)
        return fyers_dict

    def to_zerodha_dict(self) -> dict:
        # Map logical types to Zerodha-specific
        order_type = self.order_type
        product_type = self.product_type
        strategy_name = self.extra.get('strategy_name')
        if order_type == OrderType.OPTION_STRATEGY:
            order_type = "SL"
        if product_type == ProductType.OPTION_STRATEGY:
            product_type = "MIS"
        return {
            "tradingsymbol": self.symbol,
            "exchange": self.exchange or "NFO",
            "transaction_type": self.side.to_zerodha(),
            "quantity": self.quantity,
            "order_type": order_type.value if isinstance(order_type, OrderType) else order_type,
            "product": product_type.value if isinstance(product_type, ProductType) else product_type or "MIS",
            "variety": self.variety or "regular",
            "price": self.price,
            "trigger_price": self.trigger_price,
            "validity": self.validity or "DAY",
            "tag": self.tag,
        }

ORDER_TYPE_MAP = {
    OrderType.LIMIT: 1,
    OrderType.MARKET: 2,
    OrderType.SL: 3,
    OrderType.SL_LIMIT: 4,
}
PRODUCT_TYPE_MAP = {
    "INTRADAY": "INTRADAY",
    "NRML": "NRML",
    "MIS": "INTRADAY",
    "CNC": "CNC",
    "BO": "BO",  # Accept broker-specific value for validation
    
}

class OrderResponse(BaseModel):
    status: OrderStatus
    order_ids: List[str] = Field(default_factory=list)
    order_messages: Dict[str, str] = Field(default_factory=dict)
    broker: Optional[str] = None
    raw_response: Optional[Any] = None
    # Optionally, include extra info for DB
    symbol: Optional[str] = None
    side: Optional[str] = None
    quantity: Optional[int] = None
    order_type: Optional[str] = None
    strategy_id: Optional[Any] = None
    signal_id: Optional[Any] = None
    # Add more fields as needed for DB

    @field_validator('status', mode='before')
    def ensure_enum_status(cls, v):
        if isinstance(v, OrderStatus):
            return v
        if isinstance(v, str):
            # Accept 'OrderStatus.FAILED' or 'FAILED'
            if v.startswith('OrderStatus.'):
                v = v.split('.')[-1]
            try:
                return OrderStatus(v)
            except ValueError:
                raise ValueError(f"Invalid status value: {v}")
        raise ValueError(f"Invalid status type: {type(v)}")

    @classmethod
    def from_fyers(cls, response: dict, order_request=None, strategy_id=None, signal_id=None) -> "OrderResponse":
        # Handles both single and split order responses
        if response is None:
            return cls(
                status=OrderStatus.FAILED,
                order_ids=[],
                order_messages={"error": "No response from Fyers broker"},
                broker="fyers",
                raw_response=None,
                symbol=getattr(order_request, 'symbol', None),
                side=getattr(order_request, 'side', None),
                quantity=getattr(order_request, 'quantity', None),
                order_type=getattr(order_request, 'order_type', None),
                strategy_id=strategy_id,
                signal_id=signal_id
            )
        if isinstance(response, list):
            order_ids = [r.get("id") for r in response if r.get("s") == "ok"]
            order_messages = {r.get("id"): r.get("message", "") for r in response if r.get("id")}
            status = OrderStatus.FAILED
            if all(r.get("s") == "ok" for r in response):
                status = OrderStatus.AWAITING_ENTRY
            elif any(r.get("s") == "ok" for r in response):
                status = OrderStatus.PARTIALLY_FILLED
            return cls(
                status=status,
                order_ids=order_ids,
                order_messages=order_messages,
                broker="fyers",
                raw_response=response,
                symbol=getattr(order_request, 'symbol', None),
                side=getattr(order_request, 'side', None),
                quantity=getattr(order_request, 'quantity', None),
                order_type=getattr(order_request, 'order_type', None),
                strategy_id=strategy_id,
                signal_id=signal_id
            )
        else:
            order_id = response.get("id")
            status = OrderStatus.AWAITING_ENTRY if response.get("s") == "ok" else OrderStatus.FAILED
            # Always extract the error message from the response if present
            message = response.get("message", "")
            order_messages = {order_id: message} if order_id else {}
            if status == OrderStatus.FAILED:
                # If no order_id, or if message exists, put it under 'error' key for clarity
                if message:
                    order_messages = {"error": message}
                elif not order_messages:
                    order_messages = {"error": "Fyers broker returned error with no message"}
            return cls(
                status=status,
                order_ids=[order_id] if order_id else [],
                order_messages=order_messages,
                broker="fyers",
                raw_response=response,
                symbol=getattr(order_request, 'symbol', None),
                side=getattr(order_request, 'side', None),
                quantity=getattr(order_request, 'quantity', None),
                order_type=getattr(order_request, 'order_type', None),
                strategy_id=strategy_id,
                signal_id=signal_id
            )

    @classmethod
    def from_zerodha(cls, response: dict, order_request=None, strategy_id=None, signal_id=None) -> "OrderResponse":
        order_id = response.get("order_id")
        status = OrderStatus.AWAITING_ENTRY if response.get("status") == "TRIGGER PENDING" else response.get("status")  
        return cls(
            status=status,
            order_ids=[order_id] if order_id else [],
            order_messages={order_id: "Order placed"} if order_id else {},
            broker="zerodha",
            raw_response=response,
            symbol=getattr(order_request, 'symbol', None),
            side=getattr(order_request, 'side', None),
            quantity=getattr(order_request, 'quantity', None),
            order_type=getattr(order_request, 'order_type', None),
            strategy_id=strategy_id,
            signal_id=signal_id
        )
