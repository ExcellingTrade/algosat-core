"""
broker_utils.py

Utility functions to support interactions with brokers and streamline operations such as
data processing, time calculations, and cleanup tasks.

This module contains helper functions used across different brokers, including
- Calculating trade days and other time-related utilities.
- Graceful exit handling.
- Data cleanup and organization.

Functions in this module are designed to be reusable and modular, making it easy to extend
or modify for different brokers or trading strategies.

Author: Excelling Trade (Suresh)
"""
import asyncio
import json
import math
import os
import sys
from datetime import datetime, time, timedelta
import copy

import pandas as pd
import requests
from rich.align import Align
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn

from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from algosat.core.db import AsyncSessionLocal, update_broker
from algosat.core.dbschema import broker_credentials
from algosat.core.time_utils import get_ist_now, get_ist_datetime, localize_to_ist

from algosat.common import constants
from algosat.utils.config_wrapper import get_config, get_trade_config
from algosat.utils.indicators import calculate_atr
from algosat.common.logger import get_logger
from algosat.utils.rich_utils import ProgressHandler
from algosat.utils.telegram_bot import TelegramBot
from algosat.utils.utils import get_action_icon

logger = get_logger("broker_utils")
progress_handler = ProgressHandler.get_instance()

HOLIDAY_FILE = os.path.join(constants.CONFIG_DIR, "nse_holidays.json")
bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

# Global variable to track last sent Telegram message timestamp
last_sent_time = None
last_sticker_sent_time = None


def grace_exit():
    """
    Perform any cleanup operations before exiting the program.
    """
    logger.info("🔄 Performing graceful shutdown...")


def get_trade_day(date_val: datetime):
    """
    Get the nearest valid trading day prior to or on the given date.

    This function determines the most recent trading day that is not a weekend (Saturday or Sunday)
    and not listed as a trading holiday. The holiday list is fetched dynamically from the NSE.

    :param date_val: A `datetime` object representing the reference date.
    :return: A `datetime` object representing the nearest valid trading day.

    Notes:
        - If the holiday list is unavailable, the function assumes no holidays (empty list).
        - The function iterates backwards from the given date to find the nearest trading day.
    """
    holiday_list = get_nse_holiday_list()
    if holiday_list is None:
        logger.warning("🟡 NSE holiday list unavailable, assuming no holidays.")
        holiday_list = []  # Default to an empty list if no holidays are provided

    no_of_days = 0
    while True:
        current_day = date_val - timedelta(days=no_of_days)
        if current_day.weekday() < 5 and current_day.date().strftime(
                "%d-%b-%Y") not in holiday_list:  # Monday-Friday and not a holiday
            return current_day
        no_of_days += 1


def get_nse_holiday_list():
    """
    Fetch the list of trading holidays from the NSE (National Stock Exchange) API.

    This function retrieves the trading holiday calendar from a local JSON file if it exists and is recent.
    If the file is older than one month or doesn't exist, the function fetches the data from the NSE API.

    Returns:
        list: A list of strings representing trading holiday dates in the format 'YYYY-MM-DD'.

    Notes:
        - Fetches holidays from the NSE API if the local file is outdated or doesn't exist.
        - Caches the fetched holidays in a JSON file for future use.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.76 '
                      'Safari/537.36',
        "Upgrade-Insecure-Requests": "1", "DNT": "1",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate"}
    nse_holiday_list_url = 'https://www.nseindia.com/api/holiday-master?type=trading'

    # Check if the cached holiday file exists and is recent
    if os.path.exists(HOLIDAY_FILE):
        file_modified_time = localize_to_ist(datetime.fromtimestamp(os.path.getmtime(HOLIDAY_FILE)))
        if get_ist_now() - file_modified_time < timedelta(days=30):
            try:
                with open(HOLIDAY_FILE, 'r') as f:
                    logger.debug("Loaded NSE holiday list from cache.")
                    return json.load(f)  # Return holidays from the cached file
            except Exception as err:
                logger.error(f"🔴 Error reading holiday file: {err}. Re-fetching holidays...")

    # Fetch holidays from NSE API
    tries = 1
    max_retries = 3
    while tries <= max_retries:
        try:
            response = requests.get(nse_holiday_list_url, headers=headers, timeout=25)
            response.raise_for_status()  # Raise an exception for HTTP errors
            data = response.json()
            holidays = [d['tradingDate'] for d in data['CM']]
            # Cache the holidays in a local JSON file
            with open(HOLIDAY_FILE, 'w') as f:
                json.dump(holidays, f, indent=2)
            logger.info("🟢 NSE holiday list updated from API.")
            return holidays
        except Exception as err:
            logger.warning(f"🟡 Error fetching holidays from NSE API (Attempt {tries}/{max_retries}): {err}")
            tries += 1

    # Return an empty list if all attempts fail
    logger.error("🔴 Failed to fetch NSE holiday list after multiple attempts.")
    return []


async def pre_market_check():
    """
    Perform checks to ensure the script runs only during market hours and non-holidays.

    - Exits if triggered after market the "close" (3:30 PM).
    - Waits until 9:15 AM if triggered before market open.
    - Verifies if the current day is a holiday.

    :return: None
    """
    try:
        # Market timings
        market_open_time = time(9, 15)
        market_close_time = time(15, 30)
        now = get_ist_datetime()
        console = Console(width=150)

        # Check for NSE holidays
        nse_holidays = get_nse_holiday_list()
        is_weekeend = now.weekday() >= 5
        today_str = now.strftime("%d-%b-%Y")
        if today_str in nse_holidays or is_weekeend:
            # console.print(f"[red bold]Today ({today_str}) is a market holiday. Exiting script.[/]")
            print_signal_message_to_console(message="Market is holiday today", color="cyan", icon="🏝")
            shutdown_gracefully("Marker is holiday")

        # Convert market times to timezone-aware datetime objects
        localized_market_open_time = localize_to_ist(datetime.combine(now.date(), market_open_time))
        localized_market_close_time = localize_to_ist(datetime.combine(now.date(), market_close_time))
        # Check if the script triggered after market close
        if now >= localized_market_close_time:
            logger.info("🟡 Market is closed. Script triggered after market close. Exiting script.")
            shutdown_gracefully("Marker is closed")

        # Wait until 9:15 AM if triggered before the market open
        now = get_ist_datetime()
        if now < localized_market_open_time:
            wait_time = (localized_market_open_time - now).total_seconds()
            total_time = str(timedelta(seconds=wait_time)).split(".")[0]  # Human-readable total time
            logger.info("⏳ Waiting until market opens at %s. Estimated wait time: %s.", localized_market_open_time.strftime('%H:%M:%S'), total_time)

            with Progress(
                    TextColumn("[cyan]{task.description}[/]"),
                    BarColumn(),
                    TextColumn("[green]{task.completed} seconds elapsed[/]"),
                    TimeElapsedColumn(),
                    TimeRemainingColumn(),
                    transient=True,  # Progress bar disappears after completion
                    console=Console()
            ) as progress:
                task = progress.add_task(
                    description=f"Waiting for market open ({total_time})", total=wait_time
                )
                while not progress.finished:
                    await asyncio.sleep(1)
                    progress.update(task, advance=1)

        logger.info("🟢 Market is open. Proceeding with the script.")
    except Exception as error:
        logger.error(f"🔴 Error during pre-market check: {error}")
        exit(1)


async def wait_for_next_candle(interval_minutes):
    """
    Wait until the next candle starts based on the given interval, with a progress bar.

    :param interval_minutes: Candle interval in minutes.
    """
    current_time = get_ist_datetime()
    # Calculate the start time of the next candle
    next_candle_start = (
            current_time + timedelta(minutes=interval_minutes - current_time.minute % interval_minutes)
    ).replace(second=0, microsecond=0)
    wait_time = math.ceil((localize_to_ist(next_candle_start) - current_time).total_seconds())

    logger.debug(f"Waiting {wait_time} seconds for the next candle.")

    console = Console(width=150)

    # Display progress bar with Rich
    with Progress(
            TextColumn("[blue bold]{task.description}[/]"),
            BarColumn(),
            TextColumn("[green]{task.completed} seconds elapsed[/]"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            transient=True,  # Progress bar disappears after completion
            console=console
    ) as progress:
        task = progress.add_task(
            description="Waiting for next candle to start",
            total=wait_time
        )
        while not progress.finished:
            await asyncio.sleep(1)
            progress.update(task, advance=1)

    logger.info("⏳ Next candle is starting...")


def save_order_book(order_book, bot_name):
    """Persist the order book to a JSON file."""
    order_book_file = os.path.join(constants.ORDER_BOOK_DIR,
                                   f"{bot_name}_order_book_{get_ist_now().strftime('%Y-%m-%d')}.json")
    with open(order_book_file, "w") as f:
        # noinspection PyTypeChecker
        json.dump(order_book, f, indent=4, default=str)


def load_order_book(bot_name):
    """
    Load the order book from a JSON file. Handles errors like missing, empty, or corrupted files gracefully.

    :return: A dictionary with `open_trades` and `closed_trades` lists.
    """
    order_book_file = os.path.join(constants.ORDER_BOOK_DIR,
                                   f"{bot_name}_order_book_{get_ist_now().strftime('%Y-%m-%d')}.json")
    if os.path.exists(order_book_file):
        try:
            with open(order_book_file, "r") as f:
                data = json.load(f)
                # Validate the structure of the loaded data
                if isinstance(data, dict) and "open_trades" in data and "closed_trades" in data:
                    return data
                else:
                    logger.debug("Order book file structure is invalid. Resetting order book.")
                    return {"open_trades": [], "closed_trades": []}
        except json.JSONDecodeError:
            logger.debug(f"Order book file '{order_book_file}' is corrupted. Resetting order book.")
            return {"open_trades": [], "closed_trades": []}
        except Exception as error:
            logger.error(f"🔴 Unexpected error loading order book: {error}")
            return {"open_trades": [], "closed_trades": []}

    # If the file doesn't exist, return an empty order book
    logger.debug(f"Order book file '{os.path.basename(order_book_file)}' not found. Initializing a new order book.")
    return {"open_trades": [], "closed_trades": []}


def combine_backtest_results(backtest_dir, output_file, start_date, end_date, lot_size, lot_qty, bot_name):
    """
    Combine all backtest result files into a single Excel file with profit calculation,
    filter files based on start and end date, and display summary using Rich.

    :param backtest_dir: Directory containing backtest result JSON files.
    :param output_file: Path for the combined Excel file.
    :param start_date: Start date for filtering files.
    :param end_date: End date for filtering files.
    :param lot_size: Lot size for calculating profit.
    :param lot_qty: Quantity of lots for each trade.
    :param bot_name: Name of the bot calling this
    """
    console = Console()
    result_files = [
        file for file in os.listdir(backtest_dir)
        if isinstance(file, str) and file.endswith(".json")
           and file.startswith(bot_name)  # Ensure filename starts with bot_name
           and is_file_within_date_range(file, start_date, end_date)
    ]
    combined_data = []
    trade_config = get_trade_config()

    for file in result_files:
        file_path = os.path.join(backtest_dir, file)
        try:
            # Read the JSON file
            data = pd.read_json(file_path)
            if not data.empty:

                # Add profit column with lot size and quantity dynamically based on symbol
                data['profit'] = data.apply(
                    lambda row: (
                        (row['exit_price'] - row['entry_price']) * lot_size *
                        (trade_config["ce_lot_qty"] if constants.OPTION_TYPE_CALL in row['symbol'] else trade_config[
                            "pe_lot_qty"])
                        if row['side'] == 1 else
                        (row['entry_price'] - row['exit_price']) * lot_size *
                        (trade_config["ce_lot_qty"] if constants.OPTION_TYPE_CALL in row['symbol'] else trade_config[
                            "pe_lot_qty"])
                    )
                    if row['status'] in [
                        constants.TRADE_STATUS_EXIT_TARGET,
                        constants.TRADE_STATUS_EXIT_STOPLOSS,
                        constants.TRADE_STATUS_EXIT_REVERSAL,
                        constants.TRADE_STATUS_EXIT_EOD,
                        constants.TRADE_STATUS_EXIT_MAX_LOSS,
                        constants.TRADE_REASON_MARKET_CLOSED
                    ]
                    else 0,
                    axis=1
                )
            else:
                data['profit'] = []
            combined_data.append(data)
        except Exception as error:
            console.print(f"[red]Error reading file {file}: {error}[/]")

    if combined_data:
        # Combine all data into a single DataFrame
        combined_df = pd.concat(combined_data, ignore_index=True)

        # Save combined results to Excel
        combined_df.to_excel(output_file, index=False)

        # Display summary table
        display_trade_summary(combined_df, console)

        # Display entries as a table
        display_trade_entries(combined_df, console)

        # Print success message
        result_message = (
            f"All daily backtest results from {start_date.date()} to {end_date.date()} "
            f"have been successfully combined into: [bold]{os.path.basename(output_file)}[/]."
        )
        console.print(f"{get_action_icon(constants.FILE_SAVED_ACTION)}: [green]{result_message}[/]")
    else:
        console.print(f"[yellow]No data available to combine between {start_date} and {end_date}.[/]")


def is_file_within_date_range(file_name, start_date, end_date):
    """
    Check if a file's date (embedded in its name) is within the specified date range.

    :param file_name: Name of the file.
    :param start_date: Start date for filtering.
    :param end_date: End date for filtering.
    :return: True if within the date range, False otherwise.
    """
    try:
        # Extract date from file name (e.g., `BOT_NAME-backtest_2024-12-20.json`)
        date_str = file_name.split("_")[-1].replace(".json", "")
        file_date = datetime.strptime(date_str, "%Y-%m-%d")
        return start_date <= file_date <= end_date
    except ValueError:
        return False


def display_trade_summary(data, console):
    """
    Display a summary of trades using a Rich table.

    :param data: DataFrame containing the backtest results.
    :param console: Rich console instance.
    """
    if not data.empty:
        total_trades = len(data)
        successful_trades = len(data[data[constants.TRADE_KEY_PROFIT] > 0])
        cancelled_trades = len(data[data[constants.TRADE_KEY_STATUS] == constants.TRADE_STATUS_ENTRY_CANCELLED])
        loss_trades = len(data[data[constants.TRADE_KEY_PROFIT] < 0])
        total_profit = data[constants.TRADE_KEY_PROFIT].sum()
        win_rate = round((successful_trades / (total_trades - cancelled_trades)) * 100, 2) \
            if total_trades > cancelled_trades else 0

        summary_table = Table(
            title="[bold magenta]Backtest Summary[/]",
            title_justify="center",
            show_header=True,
            header_style="bold magenta"
        )
        summary_table.add_column("Metric", style="bold cyan")
        summary_table.add_column("Value", justify="right")

        # Determine styles for win rate and total profit
        win_rate_style = "cyan" if win_rate >= 50 else "bold red"
        total_profit_style = "bold green" if total_profit >= 0 else "bold red"
        loss_trades_style = "bold red" if loss_trades > 0 else "bold green"

        # Choose the icon based on profit
        profit_icon = get_action_icon(constants.TRADE_TOTAL_PROFIT_POSITIVE_ACTION) if total_profit > 0 \
            else get_action_icon(constants.TRADE_TOTAL_PROFIT_NEGATIVE_ACTION)

        summary_table.add_row("Total Trades", str(total_trades))
        summary_table.add_row("Successful Trades", str(successful_trades))
        summary_table.add_row("Cancelled Trades", str(cancelled_trades))
        summary_table.add_row("Loss Trades", f"[{loss_trades_style}]{loss_trades}[/]")
        summary_table.add_row("Win Rate", f"[{win_rate_style}]{win_rate}%[/]")
        # summary_table.add_row("Total Profit", f"[{total_profit_style}]₹{total_profit:,.2f}[/]")
        summary_table.add_row(
            "Total Profit",
            f"{profit_icon}[{total_profit_style}]₹{total_profit:,.2f}",
            style="bold green" if total_profit > 0 else "bold red"
        )

        # Center align the table in the terminal
        console.print(Align.center(summary_table))
        console.print()  # blank line separation
    else:
        console.print("[yellow bold]No backtest data to be summarized")
        console.print()


def display_trade_entries(data, console):
    """
    Display trade entries using a Rich table.

    :param data: DataFrame containing the backtest results.
    :param console: Rich console instance.
    """
    if not data.empty:
        data = data.sort_values(by=constants.TRADE_KEY_SIGNAL_TIME)
        entries_table = Table(
            title="[bold green]Trade Entries[/]",
            title_justify="center",
            show_header=True,
            header_style="bold green"
        )
        entries_table.add_column("Symbol", style="cyan", justify="left")
        entries_table.add_column("Signal Time", style="yellow", justify="right")
        entries_table.add_column("Entry Time", style="yellow", justify="right")
        entries_table.add_column("Exit Time", style="yellow", justify="right")
        entries_table.add_column("Entry Price", style="bold blue", justify="right")
        entries_table.add_column("Exit Price", style="bold blue", justify="right")
        entries_table.add_column("Exit Reason", style="bold magenta", justify="left")
        entries_table.add_column("Lot Qty", style="bold green", justify="center")
        entries_table.add_column("Profit", style="bold magenta", justify="center")

        for _, row in data.iterrows():
            # Determine profit style: green for positive, red for negative
            profit_style = "bold green" if row[constants.TRADE_KEY_PROFIT] >= 0 else "bold red"

            entries_table.add_row(
                row[constants.TRADE_KEY_SYMBOL],
                str(row[constants.TRADE_KEY_SIGNAL_TIME]) if row[constants.TRADE_KEY_SIGNAL_TIME] else "NaT",
                str(row[constants.TRADE_KEY_ENTRY_TIME]) if row[constants.TRADE_KEY_ENTRY_TIME] else "NaT",
                str(row[constants.TRADE_KEY_EXIT_TIME]) if row[constants.TRADE_KEY_EXIT_TIME] else "NaT",
                f"₹{row[constants.TRADE_KEY_ENTRY_PRICE]:,.2f}" if row[constants.TRADE_KEY_ENTRY_PRICE] else "₹0.00",
                f"₹{row[constants.TRADE_KEY_EXIT_PRICE]:,.2f}" if row[constants.TRADE_KEY_EXIT_PRICE] else "₹0.00",
                f"{row[constants.TRADE_KEY_REASON]:<20}",
                str(row[constants.TRADE_KEY_LOT_QTY]),
                f"[{profit_style}]₹{row[constants.TRADE_KEY_PROFIT]:,.2f}[/]"
            )
        console.print(Align.center(entries_table))
        console.print()  # blank line separation
    else:
        console.print("[yellow bold]No trades to be summarized")
        console.print()  # blank line separation.


def calculate_next_candle_close(interval_minutes):
    """
    Calculate the next candle close time based on the current time and interval.

    :param interval_minutes: Interval duration in minutes.
    :return: Datetime object for the next candle close time.
    """
    current_time = get_ist_datetime()
    minutes = (current_time.minute // interval_minutes) * interval_minutes
    next_candle_close = current_time.replace(minute=minutes % 60, second=0, microsecond=0)
    if minutes >= 60:
        next_candle_close += timedelta(hours=1)
    next_candle_close = localize_to_ist(next_candle_close)
    if next_candle_close <= current_time:
        next_candle_close += timedelta(minutes=interval_minutes)
    return next_candle_close


def calculate_backdate_days(interval_minutes):
    """
    Calculate the number of days to fetch history based on the interval.

    :param interval_minutes: Interval duration in minutes.
    :return: Number of days to fetch history.
    """
    if interval_minutes >= 60:  # Hourly or more
        return 20  # Fetch 10 days for larger intervals
    elif interval_minutes >= 15:
        return 15  # Fetch 5 days for 15-minute intervals
    else:
        return 10  # Fetch 3 days for smaller intervals


# Utility Functions
def record_trade_results(results, output_file):
    """Save trade results to a file."""
    backtest_file = os.path.join(constants.BACKTEST_RESULTS_DIR, output_file)
    # os.makedirs(output_file, exist_ok=True)
    with open(backtest_file, 'w') as f:
        # noinspection PyTypeChecker
        json.dump(results, f, indent=4, default=str)
    logger.debug(f"Backtest results saved to {backtest_file}.")
    result_message = f"Backtest results saved: {os.path.basename(backtest_file)}."
    progress_handler.print_message(f"{get_action_icon(constants.FILE_SAVED_ACTION)}: {result_message}", color="green")


def get_dynamic_buffer(candle_range, threshold, small_buffer, large_buffer):
    """
    Calculate dynamic buffer for entry and stop-loss based on candle range.

    :param candle_range: Range of the candle (high - low).
    :param threshold: Threshold range to determine which buffer to use.
    :param small_buffer: Buffer value for small ranges (<= threshold).
    :param large_buffer: Buffer value for large ranges (> threshold).
    :return: Buffer value based on candle range.
    """
    return large_buffer if candle_range < threshold else small_buffer


async def check_margin_availability(broker, total_qty, *order_params_list):
    """
    Check if the sufficient margin is available before placing the trade.

    :param broker: Broker instance (FyerWrapper).
    :param total_qty: Total quantity of the order.
    :param order_params_list: One or more dictionaries containing parameters for the orders.
    :return: True if sufficient margin is available, otherwise False.
    """
    try:
        # return True
        # Handle the case where a single dictionary is passed instead of multiple
        if len(order_params_list) == 1 and isinstance(order_params_list[0], dict):
            order_params_list = [order_params_list[0]]

        # Create margin request data
        margin_request_data = {
            "data": [
                {
                    "symbol": order_params["symbol"],
                    "qty": total_qty,  # Use total_qty for the first order
                    "side": order_params["side"],
                    "type": order_params.get("type", 1),  # Default to market order
                    "productType": order_params.get("productType", "BO"),
                    "limitPrice": order_params.get("limitPrice", 0.0),
                    "stopLoss": order_params.get("stopLoss", 0.0),
                    "stopPrice": order_params.get("stopPrice", 0.0),
                    "takeProfit": order_params.get("takeProfit", 0.0),
                }
                for idx, order_params in enumerate(order_params_list)
            ]
        }
        logger.debug(f"Margin req data: {margin_request_data}")
        # Perform margin check
        margin_response = await broker.check_margin(margin_request_data)
        logger.debug(margin_response)
        margin_avail = margin_response["margin_avail"]
        margin_required = margin_response["margin_new_order"]

        # Log margin details
        logger.info(
            f"💸 Margin Check: Required: {margin_required}, Available: {margin_avail}, Orders: {[order['symbol'] for order in margin_request_data['data']]}"
        )

        # Return whether a sufficient margin is available
        return margin_required <= margin_avail
    except Exception as error:
        logger.error(f"🔴 Error checking margin: {error}")
        return False


def get_square_off_time(current_date):
    """
    Returns the localized square-off time for the given date.

    :param current_date: A datetime.date object representing the current date.
    :return: A datetime object representing the square-off time localized to IST.
    """
    square_off_time_str = get_config("trade", "square_off_time", fallback="15:15")
    square_off_time = datetime.combine(
        current_date, datetime.strptime(square_off_time_str, "%H:%M").time()
    )
    return localize_to_ist(square_off_time)  # Localized to IST


def is_square_off_time():
    """
    Check if the current time has reached or passed the square-off time.

    :return: True if the current time is greater than or equal to the square-off time, False otherwise.
    """
    current_time = get_ist_datetime()  # Get current time in IST
    square_off_time = get_square_off_time(current_time.date())  # Get today's square-off time
    return current_time >= square_off_time


async def square_off_all_trades(broker, open_trades, latest_candle: pd.DataFrame):
    """
    Exit all open trades at square-off time.
    """
    exit_price = None
    if latest_candle is not None and not latest_candle.empty:
        exit_price = latest_candle[constants.COLUMN_CLOSE]
    else:
        exit_price = None
    for trade in open_trades:
        trade[constants.TRADE_KEY_EXIT_PRICE] = exit_price
        trade[constants.TRADE_KEY_EXIT_TIME] = str(get_square_off_time(get_ist_now().date()))
        trade[constants.TRADE_KEY_STATUS] = constants.TRADE_STATUS_EXIT_EOD
        trade[constants.TRADE_KEY_REASON] = "Square off"
        if trade[constants.TRADE_KEY_SIDE] == -1:
            await handle_sl_tp_trade_exit_or_cancel(broker, trade)
        else:
            await handle_trade_exit_or_cancel(broker, trade)
        logger.debug(f"Exited trade for {trade[constants.COLUMN_SYMBOL]} at square-off time.")


async def check_loss_and_square_off(broker, trade_config, open_trades, latest_candle):
    """
    check if the total loss (realized + unrealized) exceeds the max loss percentage
    of the 'limit at the start of the day' and square off positions.

    :param broker: broker instance (FyersWrapper).
    :param trade_config: trade configuration dictionary containing max loss percentage.
    :param open_trades: list of open trades for this strategy
    :param latest_candle: latest candle series
    """
    try:
        # Retrieve the maximum allowable loss percentage
        max_loss_percentage = trade_config.get('max_loss_percentage', 15)  # Default to 15% if not configured

        # Fetch balance to get the 'limit at the start of the day'
        balance_response = await broker.get_balance()
        if balance_response.get('code') != 200 or balance_response.get('s') != 'ok':
            logger.error(f"Error fetching balance: {balance_response.get('message', 'Unknown error')}")
            return

        # Extract 'limit at the start of the day'
        fund_limits = balance_response.get('fund_limit', [])
        limit_start_of_day = next(
            (item['equityAmount'] for item in fund_limits if item['title'] == 'Limit at start of the day'), 0
        )
        if limit_start_of_day <= 0:
            logger.error("Invalid or missing 'limit at the start of the day'. Cannot compute loss percentage.")
            return

        # Fetch positions to calculate total loss
        positions_response = await broker.get_positions()
        if positions_response.get('code') != 200 or positions_response.get('s') != 'ok':
            logger.error(f"Error fetching positions: {positions_response.get('message', 'Unknown error')}")
            return

        # Calculate total profit/loss
        overall = positions_response.get('overall', {})
        total_pl_realized = overall.get('pl_realized', 0)
        total_pl_unrealized = overall.get('pl_unrealized', 0)
        total_p_l = total_pl_realized + total_pl_unrealized  # Total P/L

        # Only calculate loss percentage if there is a net loss
        if total_p_l < 0:
            loss_percentage = (abs(total_p_l) / limit_start_of_day) * 100
        else:
            loss_percentage = 0  # No loss if total_loss is positive

        # Determine P/L indicators with better icons
        total_pnl_icon = "🟢💹" if total_p_l >= 0 else "🔴📉"
        loss_percentage_icon = "🟢📈" if loss_percentage <= 0 else "🔴📉"

        # Check if there is at least one open trade
        has_open_trade = any(trade[constants.TRADE_KEY_STATUS] == constants.TRADE_STATUS_OPEN for trade in open_trades)

        # Proceed only if there's at least one open trade
        if has_open_trade:
            # Format message with Telegram's supported HTML tags
            message = (
                f"{total_pnl_icon} <b>Total P/L</b>: <code>{total_p_l:.2f}</code> | "
                f"{loss_percentage_icon} <b>Loss %</b>: <code>{loss_percentage:.2f}%</code>\n"
                f"📊 <b>Limit Start of Day</b>: <code>{limit_start_of_day:.2f}</code> | "
                f"🚨 <b>Max Allowed</b>: <code>{max_loss_percentage:.2f}%</code>\n\n"
            )

            # Collect individual trade PNLs
            trade_pnl_messages = []
            for trade in open_trades:
                pnl = await get_pnl_for_symbol(broker, trade[constants.COLUMN_SYMBOL])
                if pnl is not None:
                    pnl_icon = "🟢📈" if pnl >= 0 else "🔴📉"  # Uptrend/Downtrend icons
                    trade_pnl_messages.append(
                        f"{pnl_icon} <b>{trade[constants.COLUMN_SYMBOL]}</b>: <code>{float(round(pnl, 2))}</code>"
                    )

            # Append trade-specific messages if any trades exist
            if trade_pnl_messages:
                message += "<b>📌 Individual Trade PNLs:</b>\n" + "\n".join(trade_pnl_messages)

            # ✅ Send the message since we confirmed an open trade exists
            send_telegram_message(message)

        # Check if loss exceeds the maximum allowed percentage
        if total_p_l < 0 and loss_percentage >= max_loss_percentage:
            logger.warning(
                f"🟡 Loss percentage {loss_percentage:.2f}% exceeds max limit of {max_loss_percentage}%. Initiating square off..."
            )
            # Call the square_off_positions method
            await square_off_all_trades(broker, open_trades=open_trades, latest_candle=latest_candle)
            exit_price = latest_candle[constants.COLUMN_CLOSE]
            for trade in open_trades:
                trade[constants.TRADE_KEY_EXIT_PRICE] = exit_price
                trade[constants.TRADE_KEY_EXIT_TIME] = str(get_square_off_time(get_ist_now().date()))
                trade[constants.TRADE_KEY_STATUS] = constants.TRADE_STATUS_EXIT_MAX_LOSS
                trade[constants.TRADE_KEY_REASON] = "Square off max loss"
            await shutdown_gracefully("Exiting: Max Loss Reached")
        else:
            logger.debug("Loss percentage within limit. No action required.")
    except Exception as error:
        logger.error(f"🔴 Error in check_loss_and_square_off: {error}")


def calculate_new_target(trade, history_df, trade_config):
    """
    Calculate a new target price for the trade.

    :param trade: Trade dictionary.
    :param history_df: DataFrame containing trade history.
    :param trade_config: Configuration for trading.
    :return: New target price.
    """
    # Calculate ATR and dynamic buffer
    atr_value = history_df['atr'].iloc[-1].round(2)
    target_buffer = get_dynamic_buffer(
        atr_value,
        trade_config["range_threshold_target"],
        trade_config["small_target_buffer"],
        trade_config["large_target_buffer"],
    )
    trade[constants.TRADE_KEY_ATR] = atr_value

    # Determine direction of adjustment based on trade side
    atr_adjustment = (atr_value * trade_config['atr_target_multiplier']) - target_buffer

    if trade[constants.TRADE_KEY_SIDE] == 1:
        new_target = trade[constants.TRADE_KEY_ENTRY_PRICE] + atr_adjustment
    else:  # For short positions (side == -1)
        new_target = trade[constants.TRADE_KEY_ENTRY_PRICE] - atr_adjustment

    # Apply rounding step
    step_value = trade_config.get("price_rounding_step", 0.05)  # Make step configurable
    new_target = round(round(new_target / step_value) * step_value, 2)

    # Adjust target for trailing stop-loss if enabled
    if trade_config.get("trailing_stoploss", False):
        trade["actual_target"] = new_target  # Save the original target
        # sl_adjustment = 2 * (atr_value * trade_config['atr_multiplier'])
        sl_adjustment = 2 * atr_value
        new_target = new_target + sl_adjustment if trade[constants.TRADE_KEY_SIDE] == 1 else new_target - sl_adjustment
    new_target = round(round(new_target / step_value) * step_value, 2)
    return new_target


def count_executed_trades(order_book, ignore_statuses=None) -> int:
    """
    Count the number of executed trades from the order book.

    This method evaluates the closed trades in the order book and counts the trades
    that have been executed, ignoring trades with specific statuses (e.g., "ENTRY_CANCELLED").

    :param order_book: A dictionary containing "open_trades" and "closed_trades" lists.
    :param ignore_statuses: A list of statuses to ignore while counting executed trades.
                            Default is ["ENTRY_CANCELLED"].
    :return: The count of executed trades.
    """
    if ignore_statuses is None:
        ignore_statuses = [constants.TRADE_STATUS_ENTRY_CANCELLED]

    closed_trades = order_book.get("closed_trades", [])
    executed_trades = [
        trade for trade in closed_trades if trade.get("status") not in ignore_statuses
    ]

    return len(executed_trades)


def count_loss_trades(closed_trades):
    """
    Count the number of trades in loss from the closed trades list.

    This method evaluates the closed trades and counts those where the
    trade resulted in a loss based on the 'side' (buy or sell).

    :param closed_trades: A list of closed trade dictionaries.
    :return: The count of trades in loss.
    """
    loss_trades = [
        trade for trade in closed_trades
        if trade.get(constants.TRADE_KEY_STATUS) != constants.TRADE_STATUS_ENTRY_CANCELLED  # Exclude cancelled entries
           and (
                   (trade.get("side") == 1 and trade.get("exit_price", 0) < trade.get("entry_price",
                                                                                      0)) or  # Buy side loss
                   (trade.get("side") == -1 and trade.get("exit_price", 0) > trade.get("entry_price", 0))
               # Sell side loss
           )
    ]
    return len(loss_trades)


def print_signal_message_to_console(message: str, color: str = "white", symbol: str = None, icon: str = "✘",
                                    timestamp: str = ""):
    """
    Print a neatly aligned message to the progress console with specific formatting.

    :param message: The message to print.
    :param color: The color for displaying the message in the console (default is white).
    :param symbol: The symbol associated with the message (default is None).
    :param icon: The icon to display (default is ✘).
    :param timestamp: The timestamp for the message (default is empty string).
    """
    # logger.debug(message)  # Log the original message

    # Ensure all inputs are strings
    icon = str(icon)
    timestamp = str(timestamp) if timestamp else ""  # Convert timestamp to string if not None
    symbol = str(symbol) if symbol else ""

    # Define column widths for alignment
    # icon_column_width = 5
    timestamp_column_width = 25
    symbol_column_width = 35

    # Strip unnecessary characters and format timestamp
    timestamp = timestamp.strip("{}'")  # Remove curly braces or single quotes from timestamp

    # Format each column with fixed width
    icon_formatted = f" {icon} "  # Left-align icon
    timestamp_formatted = f"{timestamp:<{timestamp_column_width}}"  # Left-align timestamp
    symbol_formatted = f"{symbol:<{symbol_column_width}}"  # Left-align symbol
    is_backtest = get_config("trade", "is_backtest", fallback=False, value_type=bool)

    # Combine formatted components into the final message
    if symbol:
        console_message = f"{icon_formatted}| {timestamp_formatted}| {symbol_formatted}| {message}"
        #  Send the bot message only for live trading
        if not is_backtest:
            send_telegram_message(console_message, check_last_sent_time=False)

    else:
        console_message = f"{icon_formatted}{message}"

    # Print the formatted message to the console
    progress_handler.print_message(console_message, color)


def check_trade_conditions(
        closed_trades,
        current_signal_direction,
        last_signal_direction,
        trades_taken,
        candle,
        trade_config,
        strike_symbol,
):
    """
    Check various conditions before initiating a new trade.

    :param closed_trades: List of closed trades.
    :param current_signal_direction: Current signal direction from the strategy.
    :param last_signal_direction: Last signal direction recorded.
    :param trades_taken: The Number of trades already took.
    :param candle: Current candle data as a dictionary or DataFrame row.
    :param trade_config: Trade configuration dictionary.
    :param strike_symbol: Current strike symbol being processed.
    :return: Tuple (bool, str) - (should_skip_trade, updated_last_signal_direction)
    """
    # Check the number of loss trades
    loss_trade_count = count_loss_trades(closed_trades)

    # Check for "no trade after" time
    no_trade_after = pd.Timestamp(datetime.combine(
        candle[constants.COLUMN_TIMESTAMP].date(),
        datetime.strptime(trade_config['no_trade_after'], "%H:%M").time()
    ))

    if pd.Timestamp(candle[constants.COLUMN_TIMESTAMP]) > no_trade_after:
        logger.debug(f"Not taking any new trade for {strike_symbol} after {no_trade_after}")

        return True, last_signal_direction

    # Skip new trades if loss count exceeds limit
    if loss_trade_count >= trade_config['max_loss_trades']:
        logger.debug(f"Not taking any new trade for {strike_symbol} at "
                     f"{str(candle[constants.COLUMN_TIMESTAMP])} as loss count "
                     f"({loss_trade_count}) reached max allowed ({trade_config['max_loss_trades']}).")

        return True, last_signal_direction

    # Skip new trades if the maximum number of trades is reached
    if trades_taken >= trade_config['max_trades']:
        logger.debug(
            f"Maximum number of trades ({trade_config['max_trades']}) reached for {strike_symbol} "
            f"at {str(candle[constants.COLUMN_TIMESTAMP])}. Skipping new trade.")

        return True, last_signal_direction

    # Handle signal reversal logic
    if last_signal_direction is not None and current_signal_direction == last_signal_direction:
        message = f"No signal reversal detected for {strike_symbol} at {str(candle[constants.COLUMN_TIMESTAMP])}. " \
                  f"Skipping trade."
        logger.debug(message)
        console_message = "Signal reversal not detected. Skipping trade"
        print_signal_message_to_console(
            message=console_message,
            symbol=strike_symbol,
            color=constants.CONSOLE_SIGNAL_LOG_COLOR,
            icon=get_action_icon(constants.SIGNAL_IGNORED_ACTION),
            timestamp=candle[constants.COLUMN_TIMESTAMP]
        )

        return True, last_signal_direction

    # Update last signal direction on successful conditions
    return False, last_signal_direction


def check_live_trade_conditions(trade_config, latest_candle, strike_symbol, closed_trades, last_signal_direction,
                                bot_name):
    """
    Check whether live trade conditions are met.

    :param trade_config: Dictionary containing trade configuration parameters.
    :param latest_candle: Latest candle data.
    :param strike_symbol: Current strike symbol being evaluated.
    :param closed_trades: List of closed trades.
    :param last_signal_direction: The last signal direction (BUY/SELL).
    :param bot_name: Name of the trading bot for loading the order book.
    :return: Tuple (bool, str) - Whether trade conditions are met and the reason if not.
    """
    # Load order book and calculate trades executed
    order_book = load_order_book(bot_name)
    trades_executed_so_far = count_executed_trades(order_book)

    # Count loss trades
    loss_trade_count = count_loss_trades(closed_trades)
    current_signal_direction = latest_candle["supertrend_signal"]
    timestamp = latest_candle[constants.COLUMN_TIMESTAMP]

    # Skip new trades if loss count exceeds limit
    if loss_trade_count >= trade_config['max_loss_trades']:
        reason = (f"Not taking any new trade for {strike_symbol} at {timestamp} as loss count "
                  f"({loss_trade_count}) reached max allowed ({trade_config['max_loss_trades']}).")
        return False, reason

    # Skip new trades if the maximum number of trades is reached
    if trades_executed_so_far >= trade_config['max_trades']:
        reason = (f"Maximum number of trades ({trade_config['max_trades']}) reached "
                  f"for {strike_symbol} at {timestamp}. Skipping.")
        return False, reason

    # Handle signal reversal logic
    if last_signal_direction is not None and current_signal_direction == last_signal_direction:
        reason = (f"No signal reversal detected for {strike_symbol} at {timestamp}. "
                  f"Current signal: {current_signal_direction}. Skipping trade.")
        return False, reason

    # Check for "no trade after" time
    no_trade_after_time = datetime.strptime(trade_config['no_trade_after'], "%H:%M").time()
    no_trade_after = localize_to_ist(datetime.combine(get_ist_datetime().date(), no_trade_after_time))
    if get_ist_datetime() > no_trade_after:
        reason = f"Not taking any new trade for {strike_symbol} after {trade_config['no_trade_after']}."
        return False, reason

    # All conditions satisfied
    return True, "Trade conditions satisfied."


def calculate_trade(candle, history_upto_candle, strike_symbol, trade_config, side):
    """
    Calculate the trade details (entry, stop loss, target) based on the given side (buy/sell).

    :param candle: The current candle data.
    :param history_upto_candle: Historical data up to the current candle.
    :param strike_symbol: Symbol of the option being traded.
    :param trade_config: Configuration parameters for trade calculation.
    :param side: "1" for "buy", -1 for "sell".
    :return: A dictionary containing trade details.
    """
    # Calculate ATR
    history_upto_candle = calculate_atr(history_upto_candle, trade_config['atr_multiplier'])
    atr_value = history_upto_candle['atr'].iloc[-1].round(2)
    candle_range = round(candle[constants.COLUMN_HIGH] - candle[constants.COLUMN_LOW], 2)

    # Calculate dynamic buffers
    entry_buffer = get_dynamic_buffer(
        candle_range,
        trade_config["range_threshold_entry"],
        trade_config["small_entry_buffer"],
        trade_config["large_entry_buffer"],
    )
    stop_loss_buffer = get_dynamic_buffer(
        candle_range,
        trade_config["range_threshold_stoploss"],
        trade_config["small_sl_buffer"],
        trade_config["large_sl_buffer"],
    )
    target_buffer = get_dynamic_buffer(
        atr_value,
        trade_config["range_threshold_target"],
        trade_config["small_target_buffer"],
        trade_config["large_target_buffer"],
    )

    # Determine entry, stop loss, and target prices
    if side == 1:  # "Buy" scenario
        entry = candle[constants.COLUMN_HIGH] + entry_buffer
        sl = candle[constants.COLUMN_LOW] - stop_loss_buffer
        target = entry + ((atr_value * trade_config['atr_target_multiplier']) - target_buffer)
    elif side == -1:  # Sell scenario
        entry = candle[constants.COLUMN_LOW] - entry_buffer
        sl = candle[constants.COLUMN_HIGH] + stop_loss_buffer
        target = entry - ((atr_value * trade_config['atr_target_multiplier']) - target_buffer)
    else:
        raise ValueError("Invalid side. Use 1 for buy or -1 for sell.")

    # Round values to match broker precision
    sl = round(round(sl / 0.05) * 0.05, 2)
    target = round(round(target / 0.05) * 0.05, 2)

    # Determine option type and lot quantity
    is_call_option = constants.OPTION_TYPE_CALL in strike_symbol
    lot_qty = trade_config["ce_lot_qty"] if is_call_option else trade_config["pe_lot_qty"]

    # Construct trade dictionary
    trade = {
        constants.TRADE_KEY_SYMBOL: strike_symbol,
        constants.TRADE_KEY_CANDLE_RANGE: candle_range,
        constants.TRADE_KEY_ENTRY_PRICE: entry,
        constants.TRADE_KEY_STOP_LOSS: sl,
        constants.TRADE_KEY_TARGET_PRICE: target,
        constants.TRADE_KEY_SIGNAL_TIME: candle[constants.COLUMN_TIMESTAMP],
        constants.TRADE_KEY_EXIT_TIME: None,
        constants.TRADE_KEY_EXIT_PRICE: 0,
        constants.TRADE_KEY_STATUS: constants.TRADE_STATUS_AWAITING_ENTRY,
        constants.TRADE_KEY_REASON: None,
        constants.TRADE_KEY_ATR: atr_value,
        constants.TRADE_KEY_SIGNAL_DIRECTION: constants.TRADE_DIRECTION_BUY
        if side == 1 else constants.TRADE_DIRECTION_SELL,
        constants.TRADE_KEY_LOT_QTY: lot_qty,
        constants.TRADE_KEY_SIDE: side
    }

    return trade


def summarize_live_trades(bot_name: str):
    """
    Summarize the closed trades from all JSON files in the trades directory.

    :param bot_name: Bot name.
    """
    console = Console()
    lot_size = get_config("trade", "lot_size", fallback=25, value_type=int)

    # Load order book and calculate trades executed
    order_book = load_order_book(bot_name)
    closed_trades_data = order_book.get("closed_trades", [])

    # Convert closed trades to a DataFrame
    df_closed_trades = pd.DataFrame(closed_trades_data)

    # Add profit column with lot size and quantity
    df_closed_trades[constants.TRADE_KEY_PROFIT] = df_closed_trades.apply(
        lambda row: (
            (row[constants.TRADE_KEY_EXIT_PRICE] - row[constants.TRADE_KEY_ENTRY_PRICE]) * lot_size * row[
                constants.TRADE_KEY_LOT_QTY]
            if row['side'] == 1 else
            (row[constants.TRADE_KEY_ENTRY_PRICE] - row[constants.TRADE_KEY_EXIT_PRICE]) * lot_size * row[
                constants.TRADE_KEY_LOT_QTY]
        )
        if row['status'] in [constants.TRADE_STATUS_EXIT_TARGET, constants.TRADE_STATUS_EXIT_STOPLOSS,
                             constants.TRADE_STATUS_EXIT_REVERSAL, constants.TRADE_STATUS_EXIT_EOD,
                             constants.TRADE_STATUS_EXIT_MAX_LOSS]
        else 0,
        axis=1
    )

    # Summary Metrics
    total_trades = len(df_closed_trades)
    successful_trades = len(df_closed_trades[df_closed_trades['profit'] > 0])
    loss_trades = len(df_closed_trades[df_closed_trades['profit'] <= 0])
    total_profit = df_closed_trades['profit'].sum()
    win_rate = round((successful_trades / total_trades) * 100, 2) if total_trades > 0 else 0

    # Display Summary
    summary_table = Table(
        title="[bold green]End of Day Trade Summary[/]",
        title_justify="center",
        show_header=True,
        header_style="bold magenta"
    )
    summary_table.add_column("Metric", style="bold cyan")
    summary_table.add_column("Value", justify="right")
    summary_table.add_row("Total Trades", str(total_trades))
    summary_table.add_row("Successful Trades", str(successful_trades))
    summary_table.add_row("Loss Trades", str(loss_trades))
    summary_table.add_row("Win Rate", f"{win_rate}%")
    summary_table.add_row("Total Profit", f"₹{total_profit:,.2f}")

    console.print(Align.center(summary_table))
    console.print("\n")

    # Display Trade Entries
    entries_table = Table(
        title="[bold green]Trade Entries[/]",
        title_justify="center",
        show_header=True,
        header_style="bold green"
    )
    entries_table.add_column("Symbol", style="cyan", justify="left")
    entries_table.add_column("Signal Time", style="yellow", justify="right")
    entries_table.add_column("Exit Time", style="yellow", justify="right")
    entries_table.add_column("Entry Price", style="bold blue", justify="right")
    entries_table.add_column("Exit Price", style="bold blue", justify="right")
    entries_table.add_column("Profit", style="bold magenta", justify="right")

    for _, row in df_closed_trades.iterrows():
        profit_style = "bold green" if row['profit'] > 0 else "bold red"
        entries_table.add_row(
            row['symbol'],
            str(row['signal_time']) if row['signal_time'] else "NaT",
            str(row['exit_time']) if row['exit_time'] else "NaT",
            f"₹{row['entry_price']:,.2f}" if row['entry_price'] else "₹0.00",
            f"₹{row['exit_price']:,.2f}" if row['exit_price'] else "₹0.00",
            f"[{profit_style}]₹{row['profit']:,.2f}[/]"
        )

    console.print(Align.center(entries_table))
    console.print("\n")


def shutdown_gracefully(reason):
    """
    Perform any cleanup and shutdown gracefully.

    :param reason: The reason for shutdown to log or display.
    """
    # console = Console(width=150)

    if reason:
        logger.debug(reason)
        # console.print(f"\n[green_yellow]Shutting down gracefully: {reason}[/green_yellow]")

    # Stop the progress bar if active
    try:
        progress_handler.stop_progress()
    except Exception as e:
        logger.debug(f"Error stopping progress handler: {e}")
    sys.exit(0)


async def handle_trade_exit_or_cancel(broker, trade):
    """
    Handle trade exit or cancel orders based on their execution status.

    :param broker: Broker instance with methods for get_order_details, exit_positions, and cancel_order.
    :param trade: Trade dictionary containing details of the trade, including order IDs.
    """
    try:
        # Fetch order details from the broker
        order_details = await broker.get_order_details()
        order_book_df = pd.DataFrame(order_details['orderBook'])

        if order_book_df.empty:
            logger.debug("Received empty order book. No actions required.")
            return

        # Filter for current symbol's orders
        symbol_orders = order_book_df[order_book_df[constants.COLUMN_SYMBOL] == trade[constants.COLUMN_SYMBOL]]

        # Combine main orders and hedge orders into a single list
        all_order_ids = trade.get(constants.TRADE_KEY_ORDER_IDS, []) + trade.get(constants.TRADE_KEY_HEDGE_ORDER_IDS,
                                                                                 [])

        for order_id in all_order_ids:
            # Check the status of BO-1 (entry order)
            entry_order = symbol_orders[symbol_orders['id'] == f"{order_id}-BO-1"]

            if not entry_order.empty:
                order_status = entry_order.iloc[0]['status']
                remaining_qty = entry_order.iloc[0]['remainingQuantity']

                if order_status == 2:  # Status 2: Order executed
                    # Exit positions for executed orders
                    stop_loss_order = symbol_orders[
                        (symbol_orders['id'] == f"{int(order_id) + 1}-BO-2") &
                        (symbol_orders['parentId'] == f"{order_id}-BO-1")
                        ]
                    if remaining_qty > 0:
                        logger.debug(f"cancelling partially executed order {order_id}-BO-1")
                        cancel_response = await broker.cancel_order(f"{order_id}-BO-1")
                        logger.debug(
                            f"Canceled non-executed order {order_id}-BO-1 for {trade[constants.COLUMN_SYMBOL]}. "
                            f"Response received {cancel_response}")
                    # since this is BO order if any of the leg is cancelled or executed, the trade is exited
                    if not stop_loss_order.empty and stop_loss_order.iloc[0]['status'] in [1, 2]:
                        continue
                    exit_response = await broker.exit_positions({"id": f"{trade[constants.COLUMN_SYMBOL]}-BO"})
                    logger.debug(f"Exited position for {trade[constants.COLUMN_SYMBOL]} due to "
                                 f"{trade[constants.TRADE_KEY_REASON]}. Response: {exit_response}")

                else:
                    # Cancel non-executed orders
                    cancel_response = await broker.cancel_order(f"{order_id}-BO-1")
                    logger.debug(
                        f"Canceled non-executed order {order_id}-BO-1 for {trade[constants.COLUMN_SYMBOL]}. "
                        f"Response received {cancel_response}")
            else:
                logger.debug(
                    f"Order ID {order_id}-BO not found in the order book for {trade[constants.COLUMN_SYMBOL]}.")

    except Exception as e:
        logger.error(f"Error handling trade for {trade[constants.COLUMN_SYMBOL]}: {str(e)}")


async def handle_sl_tp_trade_exit_or_cancel(broker, trade):
    """
    Handle trade exit or cancel orders based on execution status.

    :param broker: Broker instance with methods for get_order_details, exit_positions, and cancel_order.
    :param trade: Trade dictionary containing trade details, including order IDs.
    """
    try:
        # Fetch order details from the broker
        order_details = await broker.get_order_details()
        order_book_df = pd.DataFrame(order_details['orderBook'])

        if order_book_df.empty:
            logger.debug("Received empty order book. No actions required.")
            return

        # **1️⃣ Process Entry, SL, and Target Orders**
        symbol_orders = order_book_df[order_book_df[constants.COLUMN_SYMBOL] == trade[constants.COLUMN_SYMBOL]]

        # Collect order IDs (excluding hedge for now)
        main_order_ids = (
                trade.get(constants.TRADE_KEY_ORDER_IDS, []) +
                trade.get(constants.TRADE_KEY_SL_ORDER_IDS, []) +
                trade.get(constants.TRADE_KEY_TARGET_ORDER_IDS, [])
        )

        # **2️⃣ Process Hedge Orders (if any)**
        hedge_order_ids = trade.get(constants.TRADE_KEY_HEDGE_ORDER_IDS, [])
        hedge_symbol_orders = pd.DataFrame()

        if trade.get("hedge_symbol"):  # Ensure hedge symbol exists
            hedge_symbol_orders = order_book_df[
                order_book_df[constants.COLUMN_SYMBOL] == trade["hedge_symbol"]
                ]

        # **3️⃣ Process Orders for Main and Hedge**
        async def process_orders(order_ids, order_data, symbol):
            """ Process both main and hedge orders (cancel/exit based on execution). """
            for order_id in order_ids:
                order = order_data[order_data['id'] == str(order_id)]

                if not order.empty:
                    order_status = order.iloc[0]['status']
                    remaining_qty = order.iloc[0]['remainingQuantity']

                    if order_status == 2:  # Order fully/partially executed
                        # Exit position
                        # exit_symbol = trade["hedge_symbol"] if is_hedge else trade[constants.COLUMN_SYMBOL]
                        exit_response = await broker.exit_positions({"id": f"{symbol}-INTRADAY"})
                        logger.debug(
                            f"Exited position for {symbol} due "
                            f"to {trade[constants.TRADE_KEY_REASON]}. "
                            f"Response: {exit_response}"
                        )

                        if remaining_qty > 0:
                            # Cancel partially executed order
                            logger.debug(f"Cancelling partially executed order {order_id}")
                            cancel_response = await broker.cancel_order(str(order_id))
                            logger.debug(
                                f"Canceled partially executed order {order_id} for {symbol}. "
                                f"Response: {cancel_response}"
                            )
                    else:
                        # Cancel non-executed orders
                        cancel_response = await broker.cancel_order(str(order_id))
                        logger.debug(
                            f"Canceled non-executed order {order_id} for {symbol}. "
                            f"Response: {cancel_response}"
                        )
                else:
                    logger.debug(f"Order ID {order_id} not found in the order book for {symbol}.")

        # Process main orders
        logger.debug(f"Processing main order ids exit for {trade[constants.COLUMN_SYMBOL]}")
        await process_orders(main_order_ids, symbol_orders, trade[constants.COLUMN_SYMBOL])

        # Process hedge orders (if applicable)
        if hedge_order_ids:
            logger.debug(f"Processing hedge order ids exit for {trade[constants.TRADE_KEY_HEDGE_SYMBOL]}")
            await process_orders(hedge_order_ids, hedge_symbol_orders, trade[constants.TRADE_KEY_HEDGE_SYMBOL])

    except Exception as e:
        logger.error(f"Error handling trade for {trade[constants.COLUMN_SYMBOL]}: {str(e)}")


async def get_pnl_for_symbol(broker, symbol):
    """
    Fetch the PnL (Profit/Loss) for a given symbol from the broker's net positions.

    :param broker: Broker instance to fetch positions.
    :param symbol: The trading symbol (e.g., "NSE:NIFTY2521322950CE").
    :return: PnL value as a float (can be negative), or None if not found.
    """
    try:
        # Fetch positions from the broker
        positions = await broker.get_positions()
        net_positions = pd.DataFrame(positions['netPositions'])

        # Filter for the requested symbol
        current_trade = net_positions[net_positions["symbol"] == symbol]

        if not current_trade.empty:
            pnl_value = float(current_trade["pl"].squeeze())  # Convert to float for safety
            return pnl_value
        else:
            logger.warning(f"Symbol {symbol} not found in net positions.")
            return None
    except Exception as e:
        logger.error(f"Error fetching PnL for {symbol}: {e}")
        return None  # Return None in case of an error


def send_telegram_message(message, total_p_n_l=None, check_last_sent_time=True):
    """
    Send a message to Telegram, ensuring it is sent only once per telegram_message_interval.
    Stickers are sent separately every 120 seconds, but NOT with the first message.

    :param message: The message to send.
    :param total_p_n_l: Total profit/loss for determining stickers.
    :param check_last_sent_time: To check last sent time or not
    """
    telegram_bot = TelegramBot(bot_token=bot_token, chat_id=chat_id)
    if not check_last_sent_time:
        telegram_bot.send_message(message)
        return
    global last_sent_time, last_sticker_sent_time
    sticker_send_interval = 1800
    telegram_message_interval = get_config("trade", "telegram_message_interval", fallback=60, value_type=int)
    current_time = get_ist_datetime()

    # Initialize last_sent_time and last_sticker_sent_time on first run
    if last_sent_time is None:
        last_sent_time = current_time - timedelta(minutes=telegram_message_interval + 1)
    if last_sticker_sent_time is None:
        last_sticker_sent_time = current_time

        # Time elapsed since last message and last sticker
    time_since_last_message = (current_time - last_sent_time).total_seconds()
    time_since_last_sticker = (current_time - last_sticker_sent_time).total_seconds()

    # print(f"{time_since_last_message} sec since last message, {time_since_last_sticker} sec since last sticker.")

    # ✅ Send message only if telegram_message_interval has passed
    if time_since_last_message >= telegram_message_interval:
        telegram_bot.send_message(message)
        last_sent_time = current_time  # Update last message sent time

    # ✅ Send sticker separately every 120 seconds, but NOT with the first message
    if time_since_last_sticker >= sticker_send_interval and last_sent_time != last_sticker_sent_time:
        sticker_id = ("CAACAgUAAxkBAAMcZ64GftxRITC5oeSM732gtnAmsdkAAi0JAAI65LlUYWh9P-NFllg2BA"
                      if total_p_n_l and total_p_n_l > 0 else
                      "CAACAgIAAxkBAAMWZ63iXk39cPNhCyVGi-7_l3JPfYcAAl4AAwr8wgXFBG3RXmljjzYE")
        telegram_bot.send_sticker(sticker_id)
        last_sticker_sent_time = current_time  # Update last sticker sent time


async def get_broker_credentials(broker_name: str) -> dict:
    """
    Fetch the full configuration for `broker_name` from the `broker_credentials` table.
    Returns an empty dict if none found.
    """
    async with AsyncSessionLocal() as session:
        stmt = select(broker_credentials).where(
            broker_credentials.c.broker_name == broker_name
        )
        result = await session.execute(stmt)
        row = result.mappings().one_or_none()
        
        if row is None:
            return {}
            
        # Convert SQLAlchemy Row to a regular dict
        config = {key: value for key, value in row.items()}
        return config


async def upsert_broker_credentials(broker_name: str, config: dict) -> None:
    """
    Insert or update the broker configuration for `broker_name` in the `broker_credentials` table.
    
    Args:
        broker_name: The name of the broker (e.g., 'fyers', 'angel')
        config: Dictionary containing the full broker configuration including credentials
    """
    # Make a deep copy to avoid modifying the input dict or nested dicts
    config_copy = copy.deepcopy(config)
    
    # Ensure broker_name is consistent
    config_copy["broker_name"] = broker_name
    
    # Create the insert statement with all fields from the config
    stmt = pg_insert(broker_credentials).values(**config_copy)
    
    # Set up the on_conflict section with all updatable fields
    set_values = {key: config_copy[key] for key in config_copy if key != "broker_name" and key != "created_at"}
    set_values["updated_at"] = func.now()
    
    stmt = stmt.on_conflict_do_update(
        index_elements=[broker_credentials.c.broker_name],
        set_=set_values
    )
    
    async with AsyncSessionLocal() as session:
        await session.execute(stmt)
        await session.commit()
    
    # Log the updated credentials for debug
    updated = await get_broker_credentials(broker_name)
    logger.info(f"Updated broker credentials for {broker_name}: access_token={updated.get('credentials',{}).get('access_token')} generated_on={updated.get('credentials',{}).get('generated_on')}")


async def fetch_table_data(table, *where_clauses) -> list[dict]:
    """
    Generic helper to fetch rows from any SQLAlchemy Table.
    Returns a list of dicts for each row.
    """
    async with AsyncSessionLocal() as session:
        stmt = select(table)
        if where_clauses:
            stmt = stmt.where(*where_clauses)
        result = await session.execute(stmt)
        return [dict(row) for row in result.mappings().all()]


def can_reuse_token(generated_on_str, ist_timezone=None):
    """
    Check if a broker token can be reused based on its 'generated_on' timestamp.
    The token is reusable if:
      - It was generated after 6 AM IST today, or
      - It was generated before 6 AM IST, but the current time is still before 6 AM IST.

    :param generated_on_str: The 'generated_on' string in '%d/%m/%Y %H:%M:%S' format.
    :param ist_timezone: pytz.timezone object for IST (optional, will use Asia/Kolkata if not provided)
    :return: True if token can be reused, False otherwise.
    """
    import pytz
    if ist_timezone is None:
        ist_timezone = pytz.timezone("Asia/Kolkata")
    try:
        token_generated_on = ist_timezone.localize(datetime.strptime(generated_on_str, "%d/%m/%Y %H:%M:%S"))
        current_ist_time = get_ist_datetime()
        if current_ist_time.tzinfo is None:
            current_ist_time = ist_timezone.localize(current_ist_time)
        today_6am = current_ist_time.replace(hour=5, minute=0, second=0, microsecond=0)
        # Token is valid if generated after 6 AM today, or if generated before 6 AM and it's still before 6 AM
        if token_generated_on >= today_6am or current_ist_time < today_6am:
            return True
        return False
    except Exception as e:
        logger.error(f"Error in can_reuse_token: {e}")
        return False
    

async def update_broker_status(broker_name, status, notes="", last_check=None):
    """Helper to update broker status in DB."""
    now_ist = last_check or get_ist_now()
    async with AsyncSessionLocal() as session:
        await update_broker(session, broker_name, {
            "status": status,
            "last_auth_check": now_ist,
            "updated_at": now_ist,
            "notes": notes
        })