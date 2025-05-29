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
    SL_LIMIT = "SL_LIMIT"  # Stop-Loss Limit Order
    # add more order types here if needed

class OrderStatus(Enum):
    """
    Represents the various states an order can be in.
    Values should align with database representations and broker responses where applicable.
    """
    AWAITING_ENTRY = "AWAITING_ENTRY"    # Order placed, waiting for market conditions to trigger entry.
    PENDING = "PENDING"                  # Order sent to broker, awaiting execution or confirmation.
    OPEN = "OPEN"                        # Order is active in the market (partially or fully).
    PARTIALLY_FILLED = "PARTIALLY_FILLED"  # Order has been partially executed.
    FILLED = "FILLED"                    # Order has been fully executed. (aka COMPLETED)
    COMPLETED = "COMPLETED"              # Order has been fully executed.
    CANCELLED = "CANCELLED"              # Order has been cancelled.
    REJECTED = "REJECTED"                # Order was rejected by the broker or system.
    FAILED = "ORDER_FAILED"              # Order placement failed or an error occurred during processing.
    EXPIRED = "EXPIRED"                  # Order expired without execution.
    # Other potential statuses from constants.py if needed:
    # e.g., TRADE_STATUS_EXIT_STOPLOSS, TRADE_STATUS_EXIT_TARGET etc.
    # For now, focusing on generic order lifecycle statuses.

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
    product_type: Optional[str] = None  # MIS, NRML, INTRADAY, BO, etc.
    tag: Optional[str] = None
    validity: Optional[str] = None
    exchange: Optional[str] = None  # e.g., "NSE", "NFO"
    variety: Optional[str] = None   # e.g., "regular", "NORMAL"
    extra: Dict[str, Any] = field(default_factory=dict)
    # The extra dict can include: stopLoss, stopPrice, profit, signal_time, exit_time, exit_price, status, reason, atr, signal_direction, side_value

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
