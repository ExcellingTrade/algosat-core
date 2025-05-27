from algosat.core.signal import SignalType
from algosat.core.order_request import OrderType

# keyed by broker name (UPPERCASE), then by signal type
ORDER_DEFAULTS = {
    "ZERODHA": {
        SignalType.ENTRY:    {"order_type": OrderType.MARKET, "product_type": "MIS"},
        SignalType.STOPLOSS: {"order_type": OrderType.SL,     "product_type": "NRML"},
        SignalType.TRAIL:    {"order_type": OrderType.SL,     "product_type": "NRML", "trail_by": 50},
    },
    "FYERS": {
        SignalType.ENTRY:    {"order_type": OrderType.MARKET, "product_type": "INTRADAY"},
        SignalType.STOPLOSS: {"order_type": OrderType.SL,     "product_type": "BRACKET"},
        SignalType.TRAIL:    {"order_type": OrderType.SL,     "product_type": "BRACKET", "trail_by": 50},
    },
    # Add more brokers as needed
}
