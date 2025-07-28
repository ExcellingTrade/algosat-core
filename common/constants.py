"""
constants.py

this module defines reusable constants for trade statuses and other configurations
used across the application. centralizing these constants ensures consistency
and makes the codebase easier to maintain.

usage:
- Import specific constants or the entire module to access predefined values.
- Helps avoid hardcoding strings and values throughout the code.

Example:
    from constants import TRADE_STATUS_OPEN

    if trade["status"] == TRADE_STATUS_OPEN:
        print ("Trade is currently open.")
"""
import os
import sys

from algosat.utils.config_wrapper import get_log_config, load_config


# Get the directory of the calling script
def get_caller_directory() -> str:
    """
    Get the directory of the script that is calling this function.

    :return: Directory path of the calling script.
    """
    try:
        # Find the main script being executed
        script_name = os.path.splitext(os.path.basename(__import__("__main__").__file__))[0]
        return os.path.dirname(os.path.abspath(script_name))
    except Exception as e:
        sys.exit("error reading config file")


config_file = os.path.join(get_caller_directory(), "config.cfg")
load_config(config_file)
log_config = get_log_config()

LOG_LEVELS = {
    "fyers_wrapper": "DEBUG",
    "broker_utils": "DEBUG",
    "main_algo": "DEBUG",
    "default": "DEBUG",
    "indicators": "DEBUG"
}

# Trade statuses
TRADE_STATUS_AWAITING_ENTRY = "AWAITING_ENTRY"
TRADE_STATUS_OPEN = "OPEN"
TRADE_STATUS_EXIT_STOPLOSS = "EXIT_STOPLOSS"
TRADE_STATUS_EXIT_TARGET = "EXIT_TARGET"
TRADE_STATUS_EXIT_REVERSAL = "EXIT_REVERSAL"
TRADE_STATUS_ENTRY_CANCELLED = "ENTRY_CANCELLED"
TRADE_STATUS_ORDER_FAILED = "ORDER_FAILED"
TRADE_STATUS_EXIT_EOD = "EXIT_EOD"
TRADE_STATUS_EXIT_MAX_LOSS = "EXIT_MAX_LOSS"
TRADE_STATUS_EXIT_EXPIRY = "EXIT_EXPIRY"
TRADE_STATUS_EXIT_CLOSED = "CLOSED"

ORDER_STATUS_FULLY_EXECUTED = "fully_executed"
ORDER_STATUS_PARTIALLY_EXECUTED = "partially_executed"
ORDER_STATUS_NOT_EXECUTED = "not_executed"

# Trade dictionary keys
TRADE_KEY_SYMBOL = "symbol"
TRADE_KEY_HEDGE_SYMBOL = "hedge_symbol"
TRADE_KEY_PROFIT = "profit"
TRADE_KEY_SIDE = "side"
TRADE_KEY_ORDER_IDS = "order_ids"
TRADE_KEY_SL_ORDER_IDS = "sl_order_ids"
TRADE_KEY_TARGET_ORDER_IDS = "target_order_ids"
TRADE_CANDLE_HIGH = "trade_candle_high"
TRADE_KEY_HEDGE_ORDER_IDS = "hedge_order_ids"
TRADE_KEY_ORDER_MESSAGES = "order_messages"
TRADE_KEY_SL_ORDER_MESSAGES = "sl_order_messages"
TRADE_KEY_TARGET_ORDER_MESSAGES = "target_order_messages"
TRADE_KEY_HEDGE_ORDER_MESSAGES = "hedge_order_messages"
TRADE_KEY_ENTRY_PRICE = "entry_price"
TRADE_KEY_TARGET_PRICE = "target_price"
TRADE_KEY_ACTUAL_TARGET = "actual_target"
TRADE_KEY_STOP_LOSS = "stop_loss"
TRADE_KEY_ENTRY_TIME = "entry_time"
TRADE_KEY_SIGNAL_TIME = "signal_time"
TRADE_KEY_EXIT_TIME = "exit_time"
TRADE_KEY_EXIT_PRICE = "exit_price"
TRADE_KEY_STATUS = "status"
TRADE_KEY_SL_STATUS = "sl_status"
TRADE_KEY_TARGET_STATUS = "target_status"
TRADE_KEY_LOT_QTY = "lot_qty"
TRADE_KEY_HEDGE_STATUS = "hedge_status"
TRADE_KEY_REASON = "reason"
TRADE_KEY_ORDER_STATUS = "order_status"
TRADE_KEY_HEDGE_ORDER_STATUS = "order_status"
TRADE_KEY_CANDLE_RANGE = "candle_range"
TRADE_KEY_ATR = "atr"
TRADE_KEY_SIGNAL_DIRECTION = "supertrend_signal"

# constants for trade exit reasons
TRADE_REASON_MARKET_CLOSED = "Market Closed"
TRADE_REASON_TARGET_HIT = "Target Hit"
TRADE_REASON_STOPLOSS_HIT = "Stoploss Hit"
TRADE_REASON_WINDOW_CLOSED = "Trade window closed"
TRADE_SIGNAL_REVERSED_ENTRY_CANCEL = "Signal reversed before entry"
TRADE_SIGNAL_REVERSED_EXIT = "Supertrend reversal"


# Constants for Action Types and Icons
SIGNAL_FORMED_ACTION = "signal_formed"
SIGNAL_FORMED_ICON = "🔔"

EOD_EXIT_ACTION = "eod_exit"
EOD_EXIT_ICON = "🕞"

TRADE_ENTRY_CANCELLED_ACTION = "trade_entry_cancelled"
TRADE_ENTRY_CANCELLED_ICON = "❌ "

TRADE_ENTRY_EXECUTED_ACTION = "trade_entry_executed"
TRADE_ENTRY_EXECUTED_ICON = "🚀"

STOPLOSS_HIT_ACTION = "stoploss_hit"
STOPLOSS_HIT_ICON = "💔"

PROGRAM_ENTRY_ACTION = "welcome"
PROGRAM_ENTRY_ICON = "👋 | WELCOME"

PROGRAM_EXIT_ACTION = "goodbye"
PROGRAM_EXIT_ICON = "👋"

TARGET_ACHIEVED_ACTION = "target_achieved"
TARGET_ACHIEVED_ICON = "🎯"

SIGNAL_IGNORED_ACTION = "signal_ignored"
SIGNAL_IGNORED_ICON = "⏭️"

TRADE_EXIT_REVERSAL_ACTION = "trade_exit_reversal"
TRADE_EXIT_REVERSAL_ICON = "↩️"  # Indicates a reversal action

TRADE_EXIT_MARKET_CLOSE_ACTION = "trade_exit_market_close"
TRADE_EXIT_MARKET_CLOSE_ICON = "🔚"

TRADE_TOTAL_PROFIT_POSITIVE_ACTION = "total_profit_positive"
TRADE_TOTAL_PROFIT_POSITIVE_ICON = "🎉"

TRADE_TOTAL_PROFIT_NEGATIVE_ACTION = "total_profit_negative"
TRADE_TOTAL_PROFIT_NEGATIVE_ICON = "🔻"

TRADE_SQUARE_OFF_ACTION = "square_off"
TRADE_SQUARE_OFF_ICON = "🏃‍➡️"

TRADE_TRIAL_SL_UPDATE_ACTION = "trial_sl_update"
TRADE_TRIAL_SL_UPDATE_ICON = "🔧"


# Order actions
ORDER_PLACED_SUCCESS_ACTION = "order_success"
ORDER_PLACED_SUCCESS_ICON = "🎉"
ORDER_PLACED_FAILURE_ACTION = "order_failed"
ORDER_PLACED_FAILURE_ICON = "🚫"

FILE_SAVED_ACTION = "file_saved"
FILE_SAVED_ICON = "💾"

# Log levels (if needed)
LOG_LEVEL_INFO = "INFO"
LOG_LEVEL_ERROR = "ERROR"
LOG_LEVEL_DEBUG = "DEBUG"

# Other constants

TRADE_DIRECTION_BUY = "BUY"
TRADE_DIRECTION_SELL = "SELL"

# Option chain Column names
COLUMN_SYMBOL = "symbol"
COLUMN_PRICE = "price"
COLUMN_TIMESTAMP = "timestamp"
COLUMN_CLOSE = "close"
COLUMN_OPEN = "open"
COLUMN_HIGH = "high"
COLUMN_LOW = "low"
COLUMN_LTP = "ltp"
COLUMN_OPTION_TYPE = "option_type"

# Option types
OPTION_TYPE_CALL = "CE"
OPTION_TYPE_PUT = "PE"

# Determine the root directory dynamically (assumes this script is in a subdirectory of the root)
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Paths relative to the root directory
CACHE_DIR = os.path.join(ROOT_DIR, "Files/cache")
TRADE_RECORDS_DIR = os.path.join(ROOT_DIR, "Files/trades")
BACKTEST_RESULTS_DIR = os.path.join(ROOT_DIR, "Files/backtest_results")

LOG_DIR = os.path.join(ROOT_DIR, "Files/logs")
FYER_LOG_DIR = os.path.join(ROOT_DIR, "Files/logs/Fyer")
CONFIG_DIR = os.path.join(ROOT_DIR, "Files/Config")

os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(FYER_LOG_DIR, exist_ok=True)
os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(TRADE_RECORDS_DIR, exist_ok=True)
os.makedirs(BACKTEST_RESULTS_DIR, exist_ok=True)

# Formatter for trade records
TRADE_FILE_FORMAT = "%Y-%m-%d_%H-%M-%S"

ORDER_BOOK_DIR = os.path.join(ROOT_DIR, "Files/trades/")

# Colors
CONSOLE_SIGNAL_LOG_COLOR = "magenta"

#Messages
SIGNAL_FORMED_MESSAGE = "Signal formed"
STOPLOSS_HIT_MESSAGE = "Stoploss hit. Exiting position"
TARGET_HIT_MESSAGE = "Target hit. Exiting position"
SIGNAL_REVERSED_MESSAGE = "Supertrend Signal reversed. Exiting position"
TRADE_EXECUTION_MESSAGE = "Trade executed"
STOPLOSS_BEFORE_ENTRY_MESSAGE = "Stoploss order executed before entry"
TARGET_BEFORE_ENTRY_MESSAGE = "Target order executed before entry"

