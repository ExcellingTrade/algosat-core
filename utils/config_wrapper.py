"""
configwrapper.py

This module provides utility functions to simplify working with configuration files.
It abstracts the process of reading, writing, and validating configuration parameters,
allowing other modules to retrieve configuration values in a structured and dynamic manner.

Features:
- Load configuration files with support for defaults.
- Retrieve configuration parameters with type casting and fallback values.
- Modular design to adapt to multiple configuration formats or sources.

Intended Usage:
- This module is designed to be imported and used in other parts of the application
  to fetch and validate configuration settings efficiently.

Example:
    from configwrapper import get_config

    # Fetch a configuration value with a fallback
    api_key = get_config("API", "key", fallback="default_key")
"""
import configparser
import logging
from typing import Any, Optional, Type, Union

# Global variable for the config object
CONFIG = configparser.ConfigParser()


def load_config(config_file: str):
    """
    Load the configuration file dynamically.

    :param config_file: Path to the configuration file.
    """
    global CONFIG
    CONFIG.read(config_file)


def update_config(config_file: str, section: str, key: str, value: Any):
    """
    Update a specific field in the configuration and save it back to the file.

    :param config_file: Path to the configuration file.
    :param section: Section name in the configuration.
    :param key: Key name to update.
    :param value: New value to set for the key.
    """
    try:
        # Ensure the section exists in CONFIG
        if not CONFIG.has_section(section):
            CONFIG.add_section(section)

        # Update the key with the new value
        CONFIG.set(section, key, str(value))

        # Write the updated configuration back to the file
        with open(config_file, "w") as config_file_obj:
            CONFIG.write(config_file_obj)

        # logger.debug(f"Updated '{section}.{key}' to '{value}' in  {config_file}the configuration.")
    except Exception as e:
        raise ValueError(f"Error updating config '{section}.{key}': {e}")


def get_config(section: str, key: str, fallback: Optional[Any] = None, value_type: Type[Any] = str) -> Union[
    str, int, float, bool, None]:
    """
    Retrieve a configuration value with optional type conversion and fallback.

    :param section: Section name in the configuration file.
    :param key: Key name in the configuration file.
    :param fallback: Default value if key is not found.
    :param value_type: Desired type of the value (str, int, float, bool).
    :return: Config value in the specified type, or fallback if key/section is missing.
    """
    try:
        if value_type is bool:
            # Use getboolean for boolean values
            return CONFIG.getboolean(section, key, fallback=fallback)
        raw_value = CONFIG.get(section, key, fallback=fallback)
        # Convert to the desired type if necessary
        if value_type is not str and raw_value is not None:
            return value_type(raw_value)
        return raw_value
    except Exception as e:
        raise ValueError(f"Error retrieving config '{section}.{key}': {e}")


def get_trade_config() -> dict:
    """
    Read trade-related configuration values.

    :return: A dictionary containing trade configuration parameters.
    """
    return {
        # Buffers and thresholds
        "small_entry_buffer": get_config("trade", "small_entry_buffer", fallback=2.5, value_type=float),
        "large_entry_buffer": get_config("trade", "large_entry_buffer", fallback=5.75, value_type=float),
        "small_sl_buffer": get_config("trade", "small_sl_buffer", fallback=2.5, value_type=float),
        "large_sl_buffer": get_config("trade", "large_sl_buffer", fallback=5.75, value_type=float),
        "small_target_buffer": get_config("trade", "small_target_buffer", fallback=2.5, value_type=float),
        "large_target_buffer": get_config("trade", "large_target_buffer", fallback=5.75, value_type=float),
        "range_threshold_entry": get_config("trade", "range_threshold_entry", fallback=25, value_type=float),
        "range_threshold_target": get_config("trade", "range_threshold_target", fallback=25, value_type=float),
        "threshold_entry": get_config("trade", "threshold_entry", fallback=280, value_type=float),
        "range_threshold_stoploss": get_config("trade", "range_threshold_stoploss", fallback=20, value_type=float),
        "max_loss_trades": get_config("trade", "max_loss_trades", fallback=2, value_type=int),

        # max range
        "max_range": get_config("trade", "max_range", fallback=15, value_type=float),

        # Trade limits and parameters
        "max_trades": get_config("trade", "max_trades", fallback=2, value_type=int),
        "max_premium": get_config("trade", "max_premium", fallback=100, value_type=float),
        "max_loss_percentage": get_config("trade", "max_loss_percentage", fallback=15, value_type=float),
        "opp_side_max_premium": get_config("trade", "opp_side_max_premium", fallback=3, value_type=float),
        "opp_side_target": get_config("trade", "opp_side_target", fallback=3, value_type=float),
        "max_strikes": get_config("trade", "max_strikes", fallback=40, value_type=int),
        "entry_buffer": get_config("trade", "entry_buffer", fallback=0, value_type=float),
        "sl_buffer": get_config("trade", "sl_buffer", fallback=0, value_type=float),
        "atr_target_multiplier": get_config("trade", "atr_target_multiplier", fallback=3, value_type=int),

        # indicators
        # supertrend
        "supertrend_period": get_config("indicators", "supertrend_period", fallback=10, value_type=int),
        "supertrend_multiplier": get_config("indicators", "supertrend_multiplier", fallback=2, value_type=int),
        # sma
        "sma_period": get_config("indicators", "sma_period", fallback=25, value_type=int),
        # ATR multiplier and range
        "atr_multiplier": get_config("indicators", "atr_multiplier", fallback=14, value_type=float),

        # Interval and mode
        "interval_minutes": get_config("trade", "interval_minutes", fallback=5, value_type=int),
        "order_interval_minutes": get_config("trade", "order_interval_minutes", fallback=5, value_type=int),
        "monitor_interval_minutes": get_config("trade", "monitor_interval_minutes", fallback=5, value_type=int),
        "is_paper_trade": get_config("trade", "is_paper_trade", fallback=False, value_type=bool),
        "trailing_stoploss": get_config("trade", "trailing_stoploss", fallback=False, value_type=bool),
        "is_backtest": get_config("trade", "is_backtest", fallback=False, value_type=bool),
        "no_trade_after": get_config("trade", "no_trade_after", fallback="14:45"),
        "square_off_time": get_config("trade", "square_off_time", fallback="15:15"),

        # Candle times and date range
        "first_candle_time": get_config("trade", "first_candle_time", fallback="09:15"),
        "start_date": get_config("trade", "start_date", fallback=None),  # Use None if not set
        "end_date": get_config("trade", "end_date", fallback=None),  # Use None if not set

        # order params
        "max_nse_qty": get_config("trade", "max_nse_qty", fallback=900, value_type=int),
        "check_margin": get_config("trade", "check_margin", fallback=False, value_type=bool),
        "lot_size": get_config("trade", "lot_size", fallback=25, value_type=int),
        "ce_lot_qty": get_config("trade", "ce_lot_qty", fallback=1, value_type=int),
        "pe_lot_qty": get_config("trade", "pe_lot_qty", fallback=1, value_type=int),
        "price_rounding_step": get_config("trade", "price_rounding_step", fallback=0.05, value_type=float),
        "trigger_price_diff": get_config("trade", "trigger_price_diff", fallback=0.20, value_type=float),

        "atr_trailing_stop_period": get_config("trade", "atr_trailing_stop_period", fallback=14, value_type=int),
        "atr_trailing_stop_multiplier": get_config("trade", "atr_trailing_stop_multiplier", fallback=3, value_type=int),
        "atr_trailing_stop_buffer": get_config("trade", "atr_trailing_stop_buffer", fallback=3.0, value_type=float),

        # symbol params
        "exchange": get_config("trade", "exchange", fallback="NSE"),
        "trade_symbol": get_config("trade", "trade_symbol", fallback="NIFTY50"),
        "instrument": get_config("trade", "instrument", fallback="INDEX"),
    }

def get_log_config() -> dict:
    """
    Read log levels from the 'log' section in the configuration file.

    :return: A dictionary mapping module names to their logging levels.
    """
    log_config = {}
    try:
        # Check if the 'log' section exists
        if CONFIG.has_section("log"):
            for key, value in CONFIG.items("log"):
                # Convert log level strings to logging constants
                log_level = getattr(logging, value.upper(), logging.INFO)
                log_config[key] = log_level
        else:
            print("Log section not found in the configuration file. Using default log levels.")
    except Exception as e:
        raise ValueError(f"Error reading log configuration: {e}")

    return log_config
