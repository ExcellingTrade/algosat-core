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

class ExecutionSide(str, Enum):
    """Indicates whether an execution represents opening or closing a position"""
    ENTRY = "ENTRY"  # Opening a position (initial buy/sell)
    EXIT = "EXIT"    # Closing a position (square-off, SL, TP, manual exit)

class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_LIMIT = "SL_LIMIT"
    OPTION_STRATEGY = "OPTION_STRATEGY"

class ProductType(str, Enum):
    INTRADAY = "INTRADAY"
    DELIVERY = "DELIVERY"
    NRML = "NRML"
    MARGIN = "MARGIN"
    MIS = "MIS"
    CNC = "CNC"
    OPTION_STRATEGY = "OPTION_STRATEGY"  # Accept logical value for validation
    BO = "BO"  # Accept broker-specific value for validation
    CO = "CO"  # Cover Order product type
    INTRADAY_OPTION = "INTRADAY_OPTION"
    INTRADAY_SWING = "INTRADAY_SWING"

class OrderStatus(str, Enum):
    AWAITING_ENTRY = "AWAITING_ENTRY"  # Order placed but not yet executed (all broker orders in trigger pending state)
    OPEN = "OPEN"                      # At least one broker order has been executed
    CANCELLED = "CANCELLED"            # Order has been cancelled
    CLOSED = "CLOSED"                  # Order is closed (exit executed)
    FAILED = "FAILED"                  # All broker orders failed
    
    # Legacy statuses for backward compatibility
    PENDING = "PENDING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    COMPLETED = "COMPLETED"
    COMPLETE = "COMPLETE"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    TRIGGER_PENDING = "TRIGGER_PENDING"
    AMO_REQ_RECEIVED = "AMO_REQ_RECEIVED"

class OrderRequest(BaseModel):
    symbol: str  # Strike/tradeable symbol (e.g., "NIFTY50-25JUN25-23400-CE")
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
        # If product_type is INTRADAY_OPTION, set to INTRADAY for Fyers
        if product_type == ProductType.INTRADAY_OPTION:
            product_type = ProductType.INTRADAY
        # If product_type is INTRADAY_SWING, set to MARGIN for Fyers
        if product_type == ProductType.INTRADAY_SWING:
            product_type = ProductType.MARGIN
        if order_type == OrderType.OPTION_STRATEGY:
            order_type = "SL_LIMIT"
        # Map DELIVERY to MARGIN for Fyers
        if product_type == ProductType.OPTION_STRATEGY:
            product_type = "BO"
        elif product_type == ProductType.DELIVERY or (isinstance(product_type, str) and product_type.upper() == "DELIVERY"):
            product_type = "MARGIN"
        
        # Get base values
        limit_price = float(self.price) if self.price is not None else 0
        stop_loss_raw = getattr(self, 'stop_loss', None) or self.extra.get("stopLoss") or self.extra.get("stoploss") or self.extra.get("stop_loss") or 0
        
        # For takeProfit, prioritize target_price over pre-calculated takeProfit
        target_price_from_extra = self.extra.get("target_price")
        take_profit_raw = target_price_from_extra if target_price_from_extra is not None else self.extra.get("takeProfit", 0)
        
        # Calculate stopLoss and takeProfit for BO/CO product types
        final_product_type = PRODUCT_TYPE_MAP.get(product_type, "INTRADAY") if isinstance(product_type, str) else PRODUCT_TYPE_MAP.get(product_type.value, "INTRADAY")
        
        if final_product_type in ["BO", "CO"]:
            # For BO/CO: stopLoss and takeProfit are denominated in rupees from trade price
            # Handle directional logic based on BUY/SELL side
            if self.side == Side.BUY:
                # BUY: stop is below entry, target is above entry
                stop_loss_raw_value = abs(limit_price - float(stop_loss_raw)) if stop_loss_raw else 0
                # For BUY: takeProfit = target_price - entry_price (target should be above entry)
                take_profit_raw_value = float(take_profit_raw) - limit_price if take_profit_raw and float(take_profit_raw) > limit_price else 0
            else:  # SELL
                # SELL: stop is above entry, target is below entry
                stop_loss_raw_value = abs(float(stop_loss_raw) - limit_price) if stop_loss_raw else 0
                # For SELL: takeProfit = entry_price - target_price (target should be below entry)
                take_profit_raw_value = limit_price - float(take_profit_raw) if take_profit_raw and float(take_profit_raw) < limit_price else 0
            
            # Round to nearest 0.05 with 2 decimal places
            stop_loss_value = round(round(stop_loss_raw_value / 0.05) * 0.05, 2) if stop_loss_raw_value > 0 else 0
            take_profit_value = round(round(take_profit_raw_value / 0.05) * 0.05, 2) if take_profit_raw_value > 0 else 0
        else:
            # For other product types: use raw values and round them too
            stop_loss_raw_value = float(stop_loss_raw) if stop_loss_raw else 0
            take_profit_raw_value = float(take_profit_raw) if take_profit_raw else 0
            
            # Round to nearest 0.05 with 2 decimal places
            stop_loss_value = round(round(stop_loss_raw_value / 0.05) * 0.05, 2) if stop_loss_raw_value > 0 else 0
            take_profit_value = round(round(take_profit_raw_value / 0.05) * 0.05, 2) if take_profit_raw_value > 0 else 0
        
        fyers_dict = {
            "symbol": self.symbol,
            "qty": self.quantity,
            "type": ORDER_TYPE_MAP.get(order_type, 2) if isinstance(order_type, OrderType) else ORDER_TYPE_MAP.get(OrderType(order_type), 2),
            "side": self.side.to_fyers(),
            "productType": final_product_type,
            "limitPrice": limit_price,
            "stopPrice": float(self.trigger_price) if self.trigger_price is not None else 0,
            "disclosedQty": self.extra.get("disclosedQty", 0),
            "validity": self.validity or "DAY",
            "offlineOrder": self.extra.get("offlineOrder", False),
            "stopLoss": stop_loss_value,
            "takeProfit": take_profit_value,
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
        # Map INTRADAY_OPTION to MIS, INTRADAY_SWING to NRML, DELIVERY to NRML for Zerodha
        if product_type == ProductType.OPTION_STRATEGY:
            product_type = "MIS"
        elif product_type == ProductType.INTRADAY_OPTION:
            product_type = "MIS"
        elif product_type == ProductType.INTRADAY_SWING:
            product_type = "NRML"
        elif product_type == ProductType.DELIVERY or (isinstance(product_type, str) and product_type.upper() == "DELIVERY"):
            product_type = "NRML"
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

    def to_angel_dict(self) -> dict:
        """
        Convert OrderRequest to Angel One broker format.
        
        Angel One specific mappings:
        - variety: Always "NORMAL"
        - ordertype: MARKET, LIMIT, SL, SL-M
        - producttype: INTRADAY, DELIVERY, MARGIN, BO, CO
        - transactiontype: BUY, SELL
        - duration: DAY, IOC
        """
        # Map order types to Angel format
        order_type = self.order_type
        print(f"Mapping order type: {order_type}")
        
        if order_type == OrderType.MARKET:
            angel_order_type = "MARKET"
        elif order_type == OrderType.LIMIT:
            angel_order_type = "LIMIT"
        elif order_type == OrderType.SL:
            angel_order_type = "SL-M"  # Stop Loss Market
        elif order_type == OrderType.SL_LIMIT:
            angel_order_type = "SL"    # Stop Loss Limit
        elif order_type == OrderType.OPTION_STRATEGY:
            angel_order_type = "STOPLOSS_LIMIT"    # OPTION_STRATEGY maps to Stop Loss Limit
        else:
            angel_order_type = "MARKET"  # Default fallback
            
        print(f"Angel order type: {angel_order_type}")
        # Map product types to Angel format
        product_type = self.product_type
        if product_type == ProductType.INTRADAY_OPTION or product_type == ProductType.OPTION_STRATEGY:
            angel_product_type = "INTRADAY"
        elif product_type == ProductType.INTRADAY_SWING:
            angel_product_type = "CARRYFORWARD"
        elif product_type == ProductType.DELIVERY:
            angel_product_type = "CARRYFORWARD"
        else:
            angel_product_type = "INTRADAY"  # Default fallback
        
        # Get instrument token from extra field
        instrument_token = ""
        if self.extra and self.extra.get('instrument_token'):
            instrument_token = str(self.extra['instrument_token'])
        
        # Set variety based on order type
        if angel_order_type in ["STOPLOSS_LIMIT", "STOPLOSS_MARKET", "SL", "SL-M"]:
            angel_variety = "STOPLOSS"
        else:
            angel_variety = "NORMAL"
        
        angel_dict = {
            "variety": angel_variety,  # Dynamic based on order type
            "tradingsymbol": self.symbol,
            "symboltoken": instrument_token,
            "transactiontype": self.side.value.upper(),  # BUY or SELL
            "exchange": self.exchange or "NFO",
            "ordertype": angel_order_type,
            "producttype": angel_product_type,
            "duration": "DAY",  # Default to DAY
            "price": str(self.price) if self.price else "0",
            "triggerprice": str(self.trigger_price) if self.trigger_price else "0",
            "squareoff": "0",  # Default to 0
            "stoploss": "0",  # Default to 0 for non-SL orders
            "quantity": str(self.quantity)
        }
        
        # Special handling for SL orders - Angel uses triggerprice for activation
        # and stoploss field is only for ROBO (Bracket Orders) according to docs
        if angel_order_type in ["STOPLOSS_LIMIT","SL", "SL-M"]:
            # For SL orders, triggerprice is the activation price
            if self.trigger_price and self.trigger_price > 0:
                angel_dict["triggerprice"] = str(self.trigger_price)
            else:
                # For SL orders without trigger_price, use price as trigger
                # This is common for option strategies where price acts as trigger
                if self.price and self.price > 0:
                    angel_dict["triggerprice"] = str(self.price)
                    # For SL-Market orders, price should be 0
                    if angel_order_type == "SL-M":
                        angel_dict["price"] = "0"
                else:
                    # If no valid trigger price available, fallback to MARKET order
                    angel_dict["ordertype"] = "MARKET"
                    angel_dict["price"] = "0"
                    angel_dict["triggerprice"] = "0"
        
        return angel_dict

ORDER_TYPE_MAP = {
    OrderType.LIMIT: 1,
    OrderType.MARKET: 2,
    OrderType.SL: 3,
    OrderType.SL_LIMIT: 4,
}
PRODUCT_TYPE_MAP = {
    "INTRADAY": "INTRADAY",
    "NRML": "NRML",
    "MARGIN": "MARGIN",
    "MIS": "INTRADAY",
    "CNC": "CNC",
    "BO": "BO",  # Accept broker-specific value for validation
    "CO": "CO",  # Cover Order product type
}

class OrderResponse(BaseModel):
    status: OrderStatus
    order_id: str = ""
    order_message: str = ""
    broker: Optional[str] = None
    raw_response: Optional[Any] = None
    # Optionally, include extra info for DB
    symbol: Optional[str] = None
    side: Optional[str] = None
    quantity: Optional[int] = None
    execQuantity: int = 0
    execPrice: float = 0.0
    order_type: Optional[str] = None  
    product_type: Optional[str] = None  
    # strategy_id: Optional[Any] = None
    # signal_id: Optional[Any] = None
    # Add more fields as needed for DB

    @field_validator('status', mode='before')
    def ensure_enum_status(cls, v):
        try:
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
        except Exception as e:
            import logging
            logging.error(f"OrderResponse.ensure_enum_status error: {e}")
            raise ValueError(f"OrderResponse.ensure_enum_status error: {e}")

    @classmethod
    def from_fyers(cls, response: dict, order_request=None, strategy_id=None, signal_id=None) -> "OrderResponse":
        try:
            if response is None:
                return cls(
                    status=OrderStatus.FAILED,
                    order_id="",
                    order_message="No response from Fyers broker",
                    broker="fyers",
                    raw_response=None,
                    symbol=getattr(order_request, 'symbol', None),
                    side=getattr(order_request, 'side', None),
                    quantity=getattr(order_request, 'qty', None),
                    execQuantity=getattr(order_request, 'filledQty', None),
                    execPrice=getattr(order_request, 'tradedPrice', None),
                    order_type=getattr(order_request, 'type', None),
                    # strategy_id=strategy_id,
                    # signal_id=signal_id
                )
            order_id = response.get("id") or response.get("order_id") or response.get("data", {}).get("id")
            status = OrderStatus.AWAITING_ENTRY if response.get("s") == "ok" else OrderStatus.FAILED
            message = response.get("message", "")
            if not order_id:
                order_id = ""
            if not message:
                message = "Order placed" if status == OrderStatus.AWAITING_ENTRY else "Fyers broker returned error with no message"
            return cls(
                status=status,
                order_id=str(order_id),
                order_message=message,
                broker="fyers",
                raw_response=response,
                symbol=getattr(order_request, 'symbol', None),
                side=getattr(order_request, 'side', None),
                quantity=getattr(order_request, 'qty', None),
                execQuantity=response.get('filledQty', None),
                execPrice=response.get('tradedPrice', 0.0),
                order_type=getattr(order_request, 'order_type', None),
                product_type=getattr(order_request, 'product_type', None),
                # strategy_id=strategy_id,
                # signal_id=signal_id
            )
        except Exception as e:
            import logging
            logging.error(f"OrderResponse.from_fyers error: {e}")
            return cls(
                status=OrderStatus.FAILED,
                order_id="",
                order_message=f"OrderResponse.from_fyers error: {e}",
                broker="fyers",
                raw_response=response,
                symbol=getattr(order_request, 'symbol', None),
                side=getattr(order_request, 'side', None),
                quantity=getattr(order_request, 'qty', None),
                execQuantity=getattr(order_request, 'filledQty', None),
                execPrice=getattr(order_request, 'tradedPrice', None),
                order_type=getattr(order_request, 'order_type', None),
                product_type=getattr(order_request, 'product_type', None),
                # strategy_id=strategy_id,
            )

    @classmethod
    def from_zerodha(cls, response: dict, order_request=None, strategy_id=None, signal_id=None) -> "OrderResponse":
        try:
            order_id = response.get("order_id")
            status = OrderStatus.AWAITING_ENTRY if response.get("status") == "TRIGGER PENDING" else response.get("status")  
            message = "Order placed" if order_id else "Zerodha broker returned error with no message"
            return cls(
                status=status,
                order_id=str(order_id) if order_id else "",
                order_message=message,
                broker="zerodha",
                raw_response=response,
                symbol=getattr(order_request, 'symbol', None),
                side=getattr(order_request, 'side', None),
                quantity=getattr(order_request, 'quantity', None),
                execQuantity=response.get('filled_quantity', None),
                execPrice=response.get('average_price', None),
                order_type=response.get('order_type', None),
                product_type=response.get('product_type', None),
                # strategy_id=strategy_id,
                # signal_id=signal_id
            )
        except Exception as e:
            import logging
            logging.error(f"OrderResponse.from_zerodha error: {e}")
            return cls(
                status=OrderStatus.FAILED,
                order_id="",
                order_message=f"OrderResponse.from_zerodha error: {e}",
                broker="zerodha",
                raw_response=response,
                symbol=getattr(order_request, 'symbol', None),
                side=getattr(order_request, 'side', None),
                quantity=getattr(order_request, 'quantity', None),
                execQuantity=None,
                execPrice=None,
                order_type=None,
                product_type=None,
                # strategy_id=strategy_id,
            )
