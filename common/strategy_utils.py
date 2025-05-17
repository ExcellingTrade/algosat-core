import math
import os
import json
import asyncio
from datetime import datetime, timedelta
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from utils.utils import localize_to_ist, get_ist_datetime
from core.time_utils import wait_for_first_candle_completion, calculate_first_candle_details
import pandas as pd
from common.logger import get_logger
logger = get_logger("strategy_utils")

async def fetch_multiple_strikes_history_async(strikes, fetch_history_coro_func, *args, **kwargs):
    """
    Fetch history for multiple strikes asynchronously with a progress bar.
    Args:
        strikes (list): List of strike symbols or identifiers.
        fetch_history_coro_func (callable): Async function to fetch history for a single strike.
        *args, **kwargs: Additional arguments to pass to fetch_history_coro_func.
    Returns:
        list: List of fetched history data (order matches strikes).
    """
    from rich.console import Console
    import asyncio
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
    console = Console()
    results = [None] * len(strikes)
    total = len(strikes)
    if total == 0:
        return results
    tasks = [
        asyncio.create_task(fetch_history_coro_func(strike, *args, **kwargs))
        for strike in strikes
    ]
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task_id = progress.add_task("Fetching strike history...", total=total)
        for idx, coro in enumerate(asyncio.as_completed(tasks)):
            res = await coro
            results[idx] = res
            progress.advance(task_id)
    return results

# --- MOVED FROM broker_utils.py ---

async def fetch_option_chain_and_first_candle_history(broker, symbol, interval_minutes, max_strikes, from_date, to_date, bot_name):
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
    # Fetch history for all strikes in parallel, with progress bar
    async def fetch_history(strike_symbol):
        try:
            return await broker.get_history(
                strike_symbol,
                from_date,
                to_date,
                ohlc_interval=interval_minutes,
                ins_type=""
            )
        except Exception as e:
            # Optionally log error here
            return None
    history_data = await fetch_multiple_strikes_history_async(strike_symbols, fetch_history)
    # Filter out None results (failed fetches)
    history_data = [res for res in history_data if res is not None]
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
            logger.info(
                "[STRIKE DEBUG] CE candidates (symbol, price):\n%s",
                ce_data[[constants.COLUMN_SYMBOL, constants.COLUMN_PRICE]].to_string(index=False)
            )
            # Debug: list all PE candidates under max_premium
            logger.info(
                "[STRIKE DEBUG] PE candidates (symbol, price):\n%s",
                pe_data[[constants.COLUMN_SYMBOL, constants.COLUMN_PRICE]].to_string(index=False)
            )
        else:
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
        return None, None

def fetch_multiple_strikes_history(strikes, fetch_history_func, *args, **kwargs):
    """
    Fetch history for multiple strikes with a progress bar.
    Args:
        strikes (list): List of strike symbols or identifiers.
        fetch_history_func (callable): Function to fetch history for a single strike.
        *args, **kwargs: Additional arguments to pass to fetch_history_func.
    Returns:
        dict: Mapping of strike to its fetched history.
    """
    from rich.console import Console
    console = Console()
    results = {}
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Fetching strike history...", total=len(strikes))
        for strike in strikes:
            results[strike] = fetch_history_func(strike, *args, **kwargs)
            progress.advance(task)
    return results
