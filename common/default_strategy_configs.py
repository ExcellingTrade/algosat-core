# default_strategy_configs.py
# Default configs for OptionBuy, OptionSell, and SwingHighLow strategies

from datetime import datetime

# Default config for OptionBuy strategy
OPTION_BUY_DEFAULT_CONFIG = {
    "symbol": "NIFTY50",
    "exchange": "NSE",
    "params": {
        "start_date": "2024-12-17",
        "end_date": "2024-12-17",
        "max_range": 15,
        "max_trades": 3,
        "max_premium": 200,
        "max_strikes": 40,
        "min_strike_count_perc": 0.70,
        "entry_buffer": 0,
        "sl_buffer": 0,
        "atr_target_multiplier": 3,
        "threshold_entry": 60,
        "range_threshold_entry": 25,
        "range_threshold_stoploss": 20,
        "range_threshold_target": 15,
        "small_entry_buffer": 2.5,
        "large_entry_buffer": 5.75,
        "small_sl_buffer": 2.5,
        "large_sl_buffer": 5.75,
        "small_target_buffer": 5.25,
        "large_target_buffer": 3.75,
        "max_nse_qty": 900,
        "lot_size": 25,
        "ce_lot_qty": 1,
        "pe_lot_qty": 1,
        "price_rounding_step": 0.05,
        "interval_minutes": 5,
        "is_paper_trade": False,
        "trailing_stoploss": False,
        "is_backtest": False,
        "no_trade_after": "14:45",
        "square_off_time": "15:15",
        "first_candle_time": "09:15",
        "max_loss_percentage": 25,
        "max_loss_trades": 2,
        "trigger_price_diff": 0.20,
        "atr_trailing_stop_period": 14,
        "atr_trailing_stop_multiplier": 3,
        "atr_trailing_stop_buffer": 3.0,
        "check_margin": False,
        "telegram_message_interval": 60,
        "instrument": "INDEX",
        # indicators
        "supertrend_period": 7,
        "supertrend_multiplier": 3,
        "sma_period": 14,
        "atr_multiplier": 14,
    },
    "is_default": True,
    "enabled": True,
}

# Default config for OptionSell strategy (same as OptionBuy for now, can be customized)
OPTION_SELL_DEFAULT_CONFIG = {
    **OPTION_BUY_DEFAULT_CONFIG,
    # You can override or add OptionSell-specific params here
}

# Default config for SwingHighLow (leave blank for now)
SWING_HIGH_LOW_DEFAULT_CONFIG = {}

DEFAULT_STRATEGY_CONFIGS = {
    "OptionBuy": OPTION_BUY_DEFAULT_CONFIG,
    "OptionSell": OPTION_SELL_DEFAULT_CONFIG,
    "SwingHighLow": SWING_HIGH_LOW_DEFAULT_CONFIG,
}
