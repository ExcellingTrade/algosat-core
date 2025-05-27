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
    price: float
    signal_type: SignalType
    # Add more fields as needed (e.g., quantity, timestamp, etc.)
