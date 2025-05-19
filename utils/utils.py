"""
utils.py

This module contains utility functions that provide common functionality
to be reused across different parts of the application.

Features:
- General Utility Methods: Includes reusable helper methods to keep the codebase DRY (Don't Repeat Yourself).

Usage:
- Import the required utility function in your module.
- Use it to simplify complex or repetitive operations.

Example:
    from common.utils import some_utility_function

    result = some_utility_function(args)
    print(f"Result: {result}")

Functions:
- some_utility_function: Description of what the function does.
"""

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


def get_action_icon(action: str) -> str:
    """
    Retrieve the icon for a specific trading action.

    :param action: The action name (e.g., 'signal_formed', 'stoploss_hit').
    :return: A string representing the icon.
    """
    return ACTION_ICONS.get(action, "❓")  # Default icon for unknown actions
