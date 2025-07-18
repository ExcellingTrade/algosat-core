from enum import Enum
from dataclasses import dataclass
from algosat.core.order_request import Side

class SignalType(Enum):
    ENTRY     = "ENTRY"
    STOPLOSS  = "STOPLOSS"
    TRAIL     = "TRAIL"

@dataclass
class TradeSignal:
    symbol: str
    side: Side
    signal_type: SignalType
    price: float = None
    candle_range: float = None
    entry_price: float = None
    stop_loss: float = None
    target_price: float = None
    signal_time: str = None
    exit_time: str = None
    exit_price: float = None
    status: str = None
    reason: str = None
    atr: float = None
    signal_direction: str = None
    lot_qty: int = None
    side_value: int = None
