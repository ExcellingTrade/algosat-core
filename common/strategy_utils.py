import math
import os
import json
import asyncio
from datetime import datetime, timedelta
from rich.console import Console
from rich.progress import (
    Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn,
    TimeRemainingColumn, TaskProgressColumn
)
from core.time_utils import localize_to_ist, get_ist_datetime
from common.logger import get_logger
import logging
import cachetools
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.data_provider.provider import DataProvider

logger = get_logger("strategy_utils")

# In-memory cache for history fetches (TTL: 1 day, maxsize: 128)
_history_cache = cachetools.TTLCache(maxsize=128, ttl=60*60*24)

async def fetch_strikes_history(broker: 'DataProvider', strike_symbols, from_date, to_date, interval_minutes, ins_type=""):
    """
    Fetch history for multiple strikes asynchronously with a super stylish progress bar and in-memory cache.
    Args:
        broker: DataProvider instance with async get_history method.
        strike_symbols (list): List of strike symbols.
        from_date, to_date: Date range for history.
        interval_minutes: OHLC interval in minutes.
        ins_type: Instrument type (default: "").
    Returns:
        list: List of fetched history data (order matches strike_symbols).
    """
    from rich.console import Console
    console = Console()
    results = [None] * len(strike_symbols)
    success_count = 0
    fail_count = 0

    async def fetch_history(strike_symbol, idx):
        nonlocal success_count, fail_count
        # Normalize cache key: always use ISO format for dates
        def _to_iso(val):
            if hasattr(val, 'isoformat'):
                return val.isoformat()
            return str(val)
        cache_key = (strike_symbol, _to_iso(from_date), _to_iso(to_date), interval_minutes, ins_type)
        if cache_key in _history_cache:
            logger.info(f"Loaded history for {strike_symbol} from cache.")
            success_count += 1
            return _history_cache[cache_key]
        try:
            data = await broker.get_history(
                strike_symbol,
                from_date,
                to_date,
                ohlc_interval=interval_minutes,
                ins_type=ins_type
            )
            if data is not None:
                _history_cache[cache_key] = data
                success_count += 1
            else:
                fail_count += 1
            return data
        except Exception as e:
            fail_count += 1
            logger.debug(f"Error fetching history for strike {strike_symbol}: {e}")
            return None

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]Fetching:[/] {task.fields[strike]}", justify="right"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        TextColumn("[green]✔ {task.fields[success]}[/] [red]✖ {task.fields[fail]}[/]", justify="right"),
        console=console,
        transient=True,
    ) as progress:
        task_id = progress.add_task(
            "Fetching strike history...",
            total=len(strike_symbols),
            strike="",
            success=0,
            fail=0,
        )
        tasks = []
        strike_map = {}
        for idx, strike in enumerate(strike_symbols):
            coro = fetch_history(strike, idx)
            tasks.append(asyncio.create_task(coro))
            strike_map[idx] = strike
        for idx, coro in enumerate(asyncio.as_completed(tasks)):
            res = await coro
            results[idx] = res
            progress.update(
                task_id,
                advance=1,
                strike=strike_map[idx],
                success=success_count,
                fail=fail_count,
            )
    filtered_count = success_count
    logger.info(f"🟢 Completed fetching history. Successful fetches: {filtered_count}/{len(strike_symbols)} | Failures: {fail_count}")
    history_data = [res for res in results if res is not None]
    return history_data

# --- MOVED FROM broker_utils.py ---

async def fetch_option_chain_and_first_candle_history(broker: 'DataProvider', symbol, interval_minutes, max_strikes, from_date, to_date, bot_name):
    # This is a simplified version; adapt as needed
    option_chain_response = await broker.get_option_chain(symbol, int(max_strikes))
    if not option_chain_response.get('data') or not option_chain_response['data'].get('optionsChain'):
        return []
    import pandas as pd
    from common import constants
    option_chain_df = pd.DataFrame(option_chain_response['data']['optionsChain'])
    strike_symbols = option_chain_df[constants.COLUMN_SYMBOL].unique()
    strike_symbols = [s for s in strike_symbols if (s.endswith(constants.OPTION_TYPE_CALL)
                                                    or s.endswith(constants.OPTION_TYPE_PUT)) and "INDEX" not in s]
    logger.debug(f"⏳ Strike symbols filtered for calls and puts (excluding INDEX): {strike_symbols}")
    # Fetch history for all strikes in parallel, with progress bar
    history_data = await fetch_strikes_history(
        broker, strike_symbols, from_date, to_date, interval_minutes, ins_type=""
    )
    return history_data

def identify_strike_price_combined(option_chain_df=None, history_data=None, max_premium=200):
    import pandas as pd
    from common import constants
    try:
        if option_chain_df is not None:
            # Normalize price field if needed (e.g., ltp to price)
            if constants.COLUMN_LTP in option_chain_df.columns:
                option_chain_df = option_chain_df.copy()
                option_chain_df[constants.COLUMN_PRICE] = option_chain_df[constants.COLUMN_LTP]
            ce_data = option_chain_df[
                option_chain_df[constants.COLUMN_SYMBOL].str.endswith(constants.OPTION_TYPE_CALL)
                & (option_chain_df[constants.COLUMN_PRICE] <= max_premium)]
            pe_data = option_chain_df[
                option_chain_df[constants.COLUMN_SYMBOL].str.endswith(constants.OPTION_TYPE_PUT)
                & (option_chain_df[constants.COLUMN_PRICE] <= max_premium)]

            # Debug: list all CE candidates under max_premium
            logger.debug(
                "[STRIKE DEBUG] CE candidates (symbol, price):\n%s",
                ce_data[[constants.COLUMN_SYMBOL, constants.COLUMN_PRICE]].to_string(index=False)
            )
            # Debug: list all PE candidates under max_premium
            logger.debug(
                "[STRIKE DEBUG] PE candidates (symbol, price):\n%s",
                pe_data[[constants.COLUMN_SYMBOL, constants.COLUMN_PRICE]].to_string(index=False)
            )

        elif history_data is not None:
            history_combined = []
            for strike_data in history_data:
                if strike_data is not None:
                    latest_close = strike_data.iloc[-1][constants.COLUMN_CLOSE]
                    history_combined.append(
                        {constants.COLUMN_SYMBOL: strike_data.attrs[constants.COLUMN_SYMBOL],
                         constants.COLUMN_PRICE: latest_close})
            option_chain_df = pd.DataFrame(history_combined)
            ce_data = option_chain_df[
                option_chain_df[constants.COLUMN_SYMBOL].str.endswith(constants.OPTION_TYPE_CALL)
                & (option_chain_df[constants.COLUMN_PRICE] <= max_premium)]
            pe_data = option_chain_df[
                option_chain_df[constants.COLUMN_SYMBOL].str.endswith(constants.OPTION_TYPE_PUT)
                & (option_chain_df[constants.COLUMN_PRICE] <= max_premium)]

            # Debug: list all CE candidates under max_premium
            logger.debug(
                "🟢 [STRIKE DEBUG] CE candidates (symbol, price):\n%s",
                ce_data[[constants.COLUMN_SYMBOL, constants.COLUMN_PRICE]].to_string(index=False)
            )
            # Debug: list all PE candidates under max_premium
            logger.debug(
                "🟢 [STRIKE DEBUG] PE candidates (symbol, price):\n%s",
                pe_data[[constants.COLUMN_SYMBOL, constants.COLUMN_PRICE]].to_string(index=False)
            )
        else:
            logger.warning("🟡 No option_chain_df or history_data provided to identify strikes.")
            return None, None

        from common import constants
        # Select the highest-price CE and PE under max_premium
        if not ce_data.empty:
            ce_sorted = ce_data.sort_values(by=constants.COLUMN_PRICE, ascending=False)
            ce_strike = ce_sorted.iloc[0][constants.COLUMN_SYMBOL]
        else:
            ce_strike = None

        if not pe_data.empty:
            pe_sorted = pe_data.sort_values(by=constants.COLUMN_PRICE, ascending=False)
            pe_strike = pe_sorted.iloc[0][constants.COLUMN_SYMBOL]
        else:
            pe_strike = None

        # Debug: selected strikes
        logger.debug(f"[STRIKE DEBUG] Selected CE strike: {ce_strike}, PE strike: {pe_strike}")

        return ce_strike, pe_strike
    except Exception as error:
        logger.error(f"🔴 Error in identify_strike_price_combined: {error}")
        return None, None

async def evaluate_signals(candle_data, history_df, trade_config, strike_symbol):
    # ...strategy logic for signal evaluation...
    pass

async def evaluate_trade_signal(candle, history_upto_candle, trade_config, strike_symbol):
    signal = await evaluate_signals(candle, history_upto_candle, trade_config, strike_symbol)
    if signal:
        # ...construct trade dict...
        return signal  # or trade dict
    return None

async def evaluate_exit_conditions(trade, candle, current_signal_direction):
    # ...strategy logic for exit conditions...
    pass

async def wait_for_first_candle_completion(interval_minutes, first_candle_time, symbol=None):
    from datetime import datetime, timedelta
    from core.time_utils import get_ist_datetime, localize_to_ist
    from rich.progress import Progress, TextColumn, BarColumn, TimeElapsedColumn, TimeRemainingColumn
    import asyncio
    current_time = get_ist_datetime()
    first_candle_start = datetime.combine(current_time.date(),
                                          datetime.strptime(first_candle_time, "%H:%M").time())
    first_candle_start = localize_to_ist(first_candle_start)
    first_candle_close = first_candle_start + timedelta(minutes=interval_minutes)
    symbol_str = f" for {symbol}" if symbol else ""
    if current_time >= first_candle_close:
        logger.info(f"⏳ First candle has already completed{symbol_str} at {first_candle_time}.")
        return
    wait_time = (first_candle_close - current_time).total_seconds()
    human_readable_time = str(timedelta(seconds=wait_time)).split(".")[0]
    logger.info(f"⏳ Waiting for the first candle to complete{symbol_str} at {first_candle_time}. Estimated time remaining: {human_readable_time}.")

    from rich.console import Console as _Console
    console = _Console(stderr=False)
    with Progress(
        TextColumn("[blue bold]{task.description}[/]"),
        BarColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        transient=True,  # Progress bar disappears after completion
        refresh_per_second=1,
        auto_refresh=True,
        console=console,
    ) as progress:
        task = progress.add_task(
            description=f"Waiting for first candle completion{symbol_str} at {first_candle_time}",
            total=wait_time
        )
        start = current_time
        while not progress.finished:
            await asyncio.sleep(1)
            now = get_ist_datetime()
            elapsed = (now - start).total_seconds()
            progress.update(task, completed=elapsed, refresh=True)
    logger.info(f"🟢 First candle completed{symbol_str} at {first_candle_time}. Waiting additional 20 seconds...")
    await asyncio.sleep(20)

def calculate_first_candle_details(current_date, first_candle_time, interval_minutes):
    try:
        first_candle_start = datetime.combine(current_date,
                                              datetime.strptime(first_candle_time, "%H:%M").time())
        first_candle_start = localize_to_ist(first_candle_start)
        first_candle_close = first_candle_start
        # + timedelta(minutes=interval_minutes)
        from_date = first_candle_start
        to_date = first_candle_close
        logger.debug(f"🚀 Calculated first candle details: start={first_candle_start}, close={first_candle_close}")
        return {
            "first_candle_start": first_candle_start,
            "first_candle_close": first_candle_close,
            "from_date": from_date,
            "to_date": to_date,
        }
    except Exception as error:
        logger.error(f"🔴 Error calculating first candle details: {error}")
        raise ValueError(f"Error calculating first candle details: {error}")
    
    
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
