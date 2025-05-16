"""
utils.py

This module contains utility functions that provide common functionality
to be reused across different parts of the application.

Features:
- Date and Time Utilities: Provides functions to handle date and time operations,
  including fetching the current datetime in Indian Standard Time (IST).
- General Utility Methods: Includes reusable helper methods to keep the codebase DRY (Don't Repeat Yourself).

Usage:
- Import the required utility function in your module.
- Use it to simplify complex or repetitive operations.

Example:
    from common.utils import get_ist_datetime

    Current_time = get_ist_datetime()
    print(f "Current IST time: {current_time}")

Functions:
- get_ist_datetime: Returns the current datetime in IST.
"""
from datetime import datetime, timedelta

import pytz

from common import constants
from common.constants import EOD_EXIT_ICON

# Updated ACTION_ICONS with constants.<VARIABLE_NAME>
ACTION_ICONS = {
    constants.SIGNAL_FORMED_ACTION: constants.SIGNAL_FORMED_ICON,  # For signal formed
    constants.STOPLOSS_HIT_ACTION: constants.STOPLOSS_HIT_ICON,  # For stoploss hit
    constants.TARGET_ACHIEVED_ACTION: constants.TARGET_ACHIEVED_ICON,  # For target achieved
    constants.TRADE_ENTRY_CANCELLED_ACTION: constants.TRADE_ENTRY_CANCELLED_ICON,  # For trade entry canceled
    constants.SIGNAL_IGNORED_ACTION: constants.SIGNAL_IGNORED_ICON,  # For signal ignored due to cool-off
    constants.TRADE_EXIT_REVERSAL_ACTION: constants.TRADE_EXIT_REVERSAL_ICON,  # For trade exit due to reversal
    constants.TRADE_EXIT_MARKET_CLOSE_ACTION: constants.TRADE_EXIT_MARKET_CLOSE_ICON,  # For market close action
    constants.FILE_SAVED_ACTION: constants.FILE_SAVED_ICON,  # For file saved or relative operations
    constants.PROGRAM_EXIT_ACTION: constants.PROGRAM_EXIT_ICON,
    constants.TRADE_TOTAL_PROFIT_POSITIVE_ACTION: constants.TRADE_TOTAL_PROFIT_POSITIVE_ICON,
    constants.TRADE_TOTAL_PROFIT_NEGATIVE_ACTION: constants.TRADE_TOTAL_PROFIT_NEGATIVE_ICON,
    constants.ORDER_PLACED_SUCCESS_ACTION: constants.ORDER_PLACED_SUCCESS_ICON,
    constants.TRADE_ENTRY_EXECUTED_ACTION: constants.TRADE_ENTRY_EXECUTED_ICON,
    constants.PROGRAM_ENTRY_ACTION: constants.PROGRAM_ENTRY_ICON,
    constants.EOD_EXIT_ACTION: EOD_EXIT_ICON,
    constants.TRADE_SQUARE_OFF_ACTION: constants.TRADE_SQUARE_OFF_ICON
}


def get_ist_datetime():
    """
    Get the current datetime in Indian Standard Time (IST).

    :return: A datetime object in IST.
    """
    ist_timezone = pytz.timezone("Asia/Kolkata")
    return datetime.now(ist_timezone)


def localize_to_ist(input_datetime: datetime) -> datetime:
    """
    Localize a naive datetime object to IST or ensure an aware datetime is in IST.

    :param input_datetime: A naive or aware datetime object.
    :return: A datetime object localized to IST timezone.
    """
    ist_timezone = pytz.timezone("Asia/Kolkata")

    if input_datetime.tzinfo is None:  # If the datetime is naive
        return ist_timezone.localize(input_datetime)
    else:  # If the datetime is already aware, convert to IST
        return input_datetime.astimezone(ist_timezone)


# Calculate end_date for fetching historical data
def calculate_end_date(current_date, interval_minutes):
    """
    Calculate the end date/time to fetch historical data, ensuring no incomplete candles are included.

    :param current_date:
    :param interval_minutes: Candle interval in minutes.
    :return: Adjusted datetime object for the end date.
    """
    # current_time = current_date.replace(hour=10, minute=30)
    current_time = current_date
    end_date = (
            current_time - timedelta(minutes=interval_minutes)
    ).replace(second=0, microsecond=0)
    return end_date


def get_action_icon(action: str) -> str:
    """
    Retrieve the icon for a specific trading action.

    :param action: The action name (e.g., 'signal_formed', 'stoploss_hit').
    :return: A string representing the icon.
    """
    return ACTION_ICONS.get(action, "❓")  # Default icon for unknown actions
