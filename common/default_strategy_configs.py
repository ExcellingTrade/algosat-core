# default_strategy_configs.py
# Default configs for OptionBuy, OptionSell, and SwingHighLow strategies

from datetime import datetime

# Default config for OptionBuy strategy
OPTION_BUY_DEFAULT_CONFIG = {
    "key": "OptionBuy",
    "name": "Option Buy Intraday Config",
    "description": "Default intraday configuration for option buying strategy.",
    "product_type": "INTRADAY",
    "order_type": "MARKET",
}

# Default config for OptionSell strategy (same as OptionBuy for now, can be customized)
OPTION_SELL_DEFAULT_CONFIG = {
    **OPTION_BUY_DEFAULT_CONFIG,
    "name": "Option Sell Intraday Config",
    "key": "OptionSell",
    "description": "Default intraday configuration for option selling strategy.",
    "product_type": "INTRADAY",
    "order_type": "MARKET",
}

# Default config for SwingHighLowBuy
SWING_HIGH_LOW_BUY_DEFAULT_CONFIG = {
    "name": "Swing High Low Buy Config",
    "key": "SwingHighLowBuy",
    "description": "Default delivery configuration for swing high/low buy strategy.",
    "product_type": "DELIVERY",
    "order_type": "MARKET",
}

# Default config for SwingHighLowSell (copy of Buy, can be customized)
SWING_HIGH_LOW_SELL_DEFAULT_CONFIG = {
    **SWING_HIGH_LOW_BUY_DEFAULT_CONFIG,
    "key": "SwingHighLowSell",
    "name": "Swing High Low Sell Config",
    "description": "Default delivery configuration for swing high/low sell strategy.",
}

DEFAULT_STRATEGY_CONFIGS = {
    "OptionBuy": OPTION_BUY_DEFAULT_CONFIG,
    "OptionSell": OPTION_SELL_DEFAULT_CONFIG,
    "SwingHighLowBuy": SWING_HIGH_LOW_BUY_DEFAULT_CONFIG,
    "SwingHighLowSell": SWING_HIGH_LOW_SELL_DEFAULT_CONFIG,
}
