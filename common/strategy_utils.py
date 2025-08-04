
import math
import os
import json
import asyncio
import re
from datetime import datetime, timedelta
from rich.console import Console
from rich.progress import (
    Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn,
    TimeRemainingColumn, TaskProgressColumn
)
from algosat.core.time_utils import localize_to_ist, get_ist_datetime
from algosat.common.logger import get_logger
import logging
import cachetools
from typing import TYPE_CHECKING, Optional
from algosat.utils.indicators import calculate_atr
from algosat.core.order_request import OrderRequest, Side, OrderType
from algosat.common import constants
from algosat.common.broker_utils import get_trade_day

if TYPE_CHECKING:
    from core.data_provider.provider import DataManager

logger = get_logger("strategy_utils")

# In-memory cache for history fetches (TTL: 1 day, maxsize: 128)
_history_cache = cachetools.TTLCache(maxsize=128, ttl=60*60*24)

async def fetch_instrument_history(
    broker: 'DataManager',
    strike_symbols,
    from_date,
    to_date,
    interval_minutes,
    ins_type="",
    cache=True
):
    """
    Fetch history for multiple strikes asynchronously with a super stylish progress bar and in-memory cache.
    Args:
        broker: DataManager instance with async get_history method.
        strike_symbols (list): List of strike symbols (already resolved for broker).
        from_date, to_date: Date range for history.
        interval_minutes: OHLC interval in minutes.
        ins_type: Instrument type (default: "").
        cache: Whether to use cache (default True).
    Returns:
        dict: Dict of strike_symbol -> history data.
    """
    # --- Revert: Do not sanitize from_date and to_date here, let DataManager handle it ---
    console = Console()
    results = {}
    success_count = 0
    fail_count = 0

    async def fetch_history(strike_symbol):
        nonlocal success_count, fail_count
        # Normalize cache key: always use ISO format for dates
        def _to_iso(val):
            if hasattr(val, 'isoformat'):
                return val.isoformat()
            return str(val)
        cache_key = (strike_symbol, _to_iso(from_date), _to_iso(to_date), interval_minutes, ins_type)
        # Only check cache if cache=True
        if cache and cache_key in _history_cache:
            logger.debug(f"Loaded history for {strike_symbol} from cache.")
            success_count += 1
            return strike_symbol, _history_cache[cache_key]
        try:
            data = await broker.get_history(
                strike_symbol,
                from_date,
                to_date,
                ohlc_interval=interval_minutes,
                ins_type=ins_type,
                cache=cache
            )
            if data is not None:
                if cache:
                    _history_cache[cache_key] = data
                success_count += 1
            else:
                fail_count += 1
            return strike_symbol, data
        except Exception as e:
            fail_count += 1
            logger.debug(f"Error fetching history for strike {strike_symbol}: {e}")
            return strike_symbol, None

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
        tasks = [asyncio.create_task(fetch_history(strike)) for strike in strike_symbols]
        for coro in asyncio.as_completed(tasks):
            strike, res = await coro
            results[strike] = res
            progress.update(
                task_id,
                advance=1,
                strike=strike,
                success=success_count,
                fail=fail_count,
            )
    logger.debug(f"🟢 Completed fetching history. Successful fetches: {success_count}/{len(strike_symbols)} | Failures: {fail_count}")
    return results


async def fetch_option_chain_and_first_candle_history(broker: 'DataManager', symbol, interval_minutes, max_strikes, from_date, to_date, bot_name):
    # symbol is already resolved for the broker (runner is responsible for this)
    strike_symbols = await broker.get_strike_list(symbol, max_strikes)
    if not strike_symbols:
        logger.warning(f"No strike symbols found for {symbol} using broker.get_strike_list.")
        return {}
    logger.debug(f"⏳ Strike symbols from broker.get_strike_list: {strike_symbols}")
    # Fetch history for all strikes in parallel, with progress bar
    history_data = await fetch_instrument_history(
        broker, strike_symbols, from_date, to_date, interval_minutes, ins_type=""
    )
    return history_data

def identify_strike_price_combined(option_chain_df=None, history_data=None, max_premium=200):
    import pandas as pd
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
            for strike_symbol, strike_data in history_data.items():
                if strike_data is not None:
                    latest_close = strike_data.iloc[-1][constants.COLUMN_CLOSE]
                    history_combined.append(
                        {constants.COLUMN_SYMBOL: strike_symbol,
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

# async def evaluate_signals(candle_data, history_df, trade_config, strike_symbol):
#     # ...strategy logic for signal evaluation...
#     pass

# async def evaluate_trade_signal(candle, history_upto_candle, trade_config, strike_symbol):
#     signal = await evaluate_signals(candle, history_upto_candle, trade_config, strike_symbol)
#     if signal:
#         # ...construct trade dict...
#         return signal  # or trade dict
#     return None

# async def evaluate_exit_conditions(trade, candle, current_signal_direction):
#     # ...strategy logic for exit conditions...
#     pass

async def wait_for_first_candle_completion(interval_minutes, first_candle_time, symbol=None):
    from datetime import datetime, timedelta
    from algosat.core.time_utils import get_ist_datetime, localize_to_ist
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
        # Always localize to IST (timezone-aware)
        first_candle_start = localize_to_ist(first_candle_start)
        first_candle_close = first_candle_start  # (can add timedelta if needed)
        from_date = first_candle_start
        to_date = first_candle_close
        logger.debug(f"🚀 Calculated first candle details (IST-aware): start={first_candle_start}, close={first_candle_close}")
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
    Returns the timestamp for the last **completed** candle of the given interval.
    If now is 10:43 and interval is 5, returns 10:35 (because 10:40 candle is forming).
    """
    # Strip seconds/microseconds
    current_time = current_date.replace(second=0, microsecond=0)
    # Minutes since midnight
    total_minutes = current_time.hour * 60 + current_time.minute
    # Floor to nearest interval (could be current incomplete candle)
    floored_minutes = (total_minutes // interval_minutes) * interval_minutes
    # Subtract one interval to get the *previous* completed candle
    completed_minutes = floored_minutes - interval_minutes
    if completed_minutes < 0:
        # Handle edge case at midnight
        completed_minutes = 0
    end_date = current_time.replace(hour=0, minute=0) + timedelta(minutes=completed_minutes)
    return end_date

# --- Utility: Dynamic Buffer Calculation ---
def get_dynamic_buffer(candle_range, threshold, small_buffer, large_buffer):
    """
    Calculate dynamic buffer for entry and stop-loss based on candle range.

    :param candle_range: Range of the candle (high - low).
    :param threshold: If candle range is LESS than the threshold, use large_buffer (to avoid whipsaws).
                     If candle range is GREATER THAN OR EQUAL to the threshold, use small_buffer.
    :param small_buffer: Buffer value for large ranges (>= threshold).
    :param large_buffer: Buffer value for small ranges (< threshold).
    :return: Buffer value based on candle range and threshold.
    """
    return large_buffer if candle_range < threshold else small_buffer


# --- Utility: Calculate Trade Details ---
def calculate_trade(candle, history_upto_candle, strike_symbol, trade_config, side, target_atr_multiplier=None):
    """
    Calculate the trade details (entry, stop loss, target) based on the given side (buy/sell).

    :param candle: The current candle data.
    :param history_upto_candle: Historical data up to the current candle.
    :param strike_symbol: Symbol of the option being traded.
    :param trade_config: Configuration parameters for trade calculation.
    :param side: Side enum (Side.BUY or Side.SELL)
    :return: A dictionary containing trade details.
    """
    history_upto_candle = calculate_atr(history_upto_candle, trade_config.get('atr_multiplier',10))
    atr_value = history_upto_candle['atr'].iloc[-1].round(2)
    candle_range = round(candle[constants.COLUMN_HIGH] - candle[constants.COLUMN_LOW], 2)

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

    if side == Side.BUY:
        entry = candle[constants.COLUMN_HIGH] + entry_buffer
        sl = candle[constants.COLUMN_LOW] - stop_loss_buffer
        if target_atr_multiplier is not None:
            target = entry + (atr_value * target_atr_multiplier) - target_buffer
        else:
            target = entry + ((atr_value * trade_config['atr_target_multiplier']) - target_buffer)
        side_val = 1
    elif side == Side.SELL:
        entry = candle[constants.COLUMN_LOW] - entry_buffer
        sl = candle[constants.COLUMN_HIGH] + stop_loss_buffer
        if target_atr_multiplier is not None:
            target = entry - (atr_value * target_atr_multiplier) + target_buffer
        else:
            target = entry - ((atr_value * trade_config['atr_target_multiplier']) - target_buffer)
        side_val = -1
    else:
        raise ValueError("Invalid side. Use Side.BUY or Side.SELL.")

    sl = round(round(sl / 0.05) * 0.05, 2)
    target = round(round(target / 0.05) * 0.05, 2)

    is_call_option = constants.OPTION_TYPE_CALL in strike_symbol
    lot_qty = trade_config["ce_lot_qty"] if is_call_option else trade_config["pe_lot_qty"]

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
        constants.TRADE_KEY_SIGNAL_DIRECTION: constants.TRADE_DIRECTION_BUY if side == Side.BUY else constants.TRADE_DIRECTION_SELL,
        constants.TRADE_KEY_LOT_QTY: lot_qty,
        constants.TRADE_KEY_SIDE: side  # Store as Side enum, not int
    }
    return trade

def get_trade_config_value(trade_config, key, default=None):
    # Handles dict, tuple/list, or SQLAlchemy Row
    if isinstance(trade_config, dict):
        if key in trade_config:
            return trade_config.get(key, default)
        # If not found, check for nested 'trade' dict
        if 'trade' in trade_config and isinstance(trade_config['trade'], dict):
            return trade_config['trade'].get(key, default)
        return default
    if hasattr(trade_config, key):
        return getattr(trade_config, key, default)
    if hasattr(trade_config, 'trade') and isinstance(getattr(trade_config, 'trade'), dict):
        # SQLAlchemy row or object with .trade dict
        return getattr(trade_config, 'trade').get(key, default)
    if isinstance(trade_config, (tuple, list)):
        # Try to get from a dict in the tuple (common in ORM row)
        for item in trade_config:
            if isinstance(item, dict):
                if key in item:
                    return item[key]
                if 'trade' in item and isinstance(item['trade'], dict) and key in item['trade']:
                    return item['trade'][key]
        return default
    return default

# async def process_trade(order_manager, trade, trade_config, strategy_config_id, broker_id):
#     """
#     Process the trade: Place the order using OrderManager based on trade details and config.
#     Only perform trade calculations here; broker-specific product/order type logic is handled in OrderManager.
#     :param order_manager: OrderManager instance.
#     :param trade: Trade dictionary containing trade details.
#     :param trade_config: Trade configuration dictionary, tuple, or ORM row.
#     :param strategy_config_id: Strategy config ID for DB tracking.
#     :param broker_id: Broker ID for DB tracking.
#     :return: Result dict for the placed order or error info.
#     """
#     try:
#         symbol = trade[constants.TRADE_KEY_SYMBOL]
#         is_call_option = constants.OPTION_TYPE_CALL in symbol
#         lot_qty = get_trade_config_value(trade_config, "ce_lot_qty") if is_call_option else get_trade_config_value(trade_config, "pe_lot_qty")
#         lot_size = get_trade_config_value(trade_config, "lot_size", 1)
#         if lot_qty is None or lot_size is None:
#             logger.error(f"[process_trade] Missing lot_qty or lot_size in trade_config: ce_lot_qty={get_trade_config_value(trade_config, 'ce_lot_qty')}, pe_lot_qty={get_trade_config_value(trade_config, 'pe_lot_qty')}, lot_size={lot_size}")
#             return {"status": "error", "error": "Missing lot_qty or lot_size in trade_config"}
#         total_qty = lot_qty * lot_size
#         entry_price = round(round(trade[constants.TRADE_KEY_ENTRY_PRICE] / 0.05) * 0.05, 2)
#         sl_price = round(round(trade[constants.TRADE_KEY_STOP_LOSS] / 0.05) * 0.05, 2)
#         target_price = round(round(trade[constants.TRADE_KEY_TARGET_PRICE] / 0.05) * 0.05, 2)
#         trigger_price_diff = get_trade_config_value(trade_config, 'trigger_price_diff', 0)
#         stopPrice = (entry_price - trigger_price_diff) if trade["side"] == 1 else (entry_price + trigger_price_diff)
#         stopPrice = round(round(stopPrice / 0.05) * 0.05, 2)
#         # Map side and order_type to enums (always use Side enum, never broker-specific int)
#         side_enum = Side.BUY if trade['side'] == 1 else Side.SELL
#         order_type_enum = OrderType.LIMIT  # Default to LIMIT, can be made dynamic if needed
#         order_request = OrderRequest(
#             symbol=symbol,
#             quantity=total_qty,
#             side=side_enum,  # Always pass Side enum, never int
#             order_type=order_type_enum,
#             price=entry_price,
#             trigger_price=stopPrice,
#             product_type=get_trade_config_value(trade_config, 'product_type', None),
#             tag=str(strategy_config_id),
#             validity="DAY",
#             extra={
#                 "stopLoss": sl_price,
#                 "takeProfit": abs(target_price)
#             }
#         )
#         logger.info(f"[process_trade] Placing order for {symbol} | qty: {total_qty} | entry: {entry_price} | sl: {sl_price} | target: {target_price}")
#         # Place order via OrderManager (OrderManager will set productType/type based on broker)
#         result = await order_manager.place_order(
#             config=trade_config,
#             order_payload=order_request,
#             strategy_name=None  # Optionally pass strategy name if needed
#         )
#         if result.get('status') == 'success':
#             logger.info(f"[process_trade] Order placed successfully: {result}")
#         else:
#             logger.warning(f"[process_trade] Order placement failed: {result}")
#         return result
#     except Exception as error:
#         logger.error(f"Error processing trade: {error}", exc_info=True)
#         return {"status": "error", "error": str(error)}

async def get_broker_symbol(broker_manager, broker_name, symbol, instrument_type=None):
    """
    Utility to get the correct symbol/token for a broker using BrokerManager.get_symbol_info.
    """
    return await broker_manager.get_symbol_info(broker_name, symbol, instrument_type)

async def wait_for_next_candle(interval_minutes: int) -> float:
    """
    Wait until the next candle boundary for the given interval in minutes.
    Returns the wait time in seconds.
    """
    now = get_ist_datetime() # Get current IST datetime     
    minutes = now.minute % interval_minutes
    seconds = now.second
    microseconds = now.microsecond
    # Time until next candle
    delta = timedelta(
        minutes=interval_minutes - minutes if minutes > 0 or seconds > 0 or microseconds > 0 else 0,
        seconds=-seconds,
        microseconds=-microseconds
    )
    if delta.total_seconds() <= 0:
        delta = timedelta(minutes=interval_minutes)
    wait_time = delta.total_seconds()
    logger.info(f"Waiting for next candle: {wait_time} seconds (interval: {interval_minutes} minutes)")
    # Use asyncio.sleep to wait for the next candle
    if wait_time < 0:
        logger.warning(f"Negative wait time calculated: {wait_time} seconds. Adjusting to 0.")
        wait_time = 0
    await asyncio.sleep(wait_time)
    return wait_time


def get_max_premium_from_config(trade_config: dict, symbol: str, current_dt: 'datetime') -> Optional[int]:
    """
    Determine the maximum premium based on the trade_config, symbol, and current datetime.
    Expiry type (weekly/monthly) is auto-detected from symbol:
      - For NIFTY and BANKNIFTY, treat as "weekly".
      - For all other symbols, treat as "monthly".
    Symbol is sanitized (strips NSE: prefix, -INDEX suffix, NIFTYBANK→BANKNIFTY, etc).
    Supports dynamic selection via max_premium_selection in config for weekly/monthly expiries.
    Returns None if:
      - No entry found for the specific weekday/week
      - Selected premium exceeds max_threshold
      - max_premium_selection is not configured properly
    Logs the expiry_type, detection path, and selected premium.
    Args:
        trade_config (dict): The trade config dict.
        symbol (str): The trading symbol (e.g., "NIFTY", "NSE:BANKNIFTY", etc).
        current_dt (datetime): The current datetime (IST).
    Returns:
        Optional[int]: The selected max_premium value or None if not found/invalid.
    """
    # --- Symbol sanitization (same as get_atm_strike_symbol in swing_utils.py) ---
    orig_symbol = symbol
    if symbol.startswith("NSE:"):
        symbol = symbol[4:]
    if symbol.endswith("-INDEX"):
        symbol = symbol[:-6]
    m = re.match(r"^(NIFTY|BANKNIFTY)\d+$", symbol)
    if m:
        symbol = m.group(1)
    if symbol == "NIFTYBANK":
        symbol = "BANKNIFTY"
    symbol_upper = symbol.upper()
    # --- Detect expiry_type ---
    # For NIFTY and BANKNIFTY: weekly. For all others: monthly.
    if symbol_upper in ("NIFTY"):
        expiry_type = "weekly"
        expiry_reason = f"Detected as weekly expiry for symbol '{symbol_upper}'"
    else:
        expiry_type = "monthly"
        expiry_reason = f"Detected as monthly expiry for symbol '{symbol_upper}'"
    # --- Select max_premium from selection ---
    max_premium_selection = trade_config.get("max_premium_selection")
    result = None
    details = ""
    try:
        if isinstance(max_premium_selection, dict):
            if expiry_type == "weekly":
                weekday = current_dt.strftime("%A").lower()
                weekly_map = max_premium_selection.get("weekly", {})
                if weekday in weekly_map:
                    result = weekly_map[weekday]
                    details = f"weekly, day={weekday}"
                else:
                    result = None
                    details = f"weekly, day={weekday} not found"
                    logger.warning(
                        f"[get_max_premium_from_config] WEEKLY: No entry for weekday='{weekday}' in map, returning None (symbol={orig_symbol})"
                    )
            elif expiry_type == "monthly":
                day = current_dt.day
                week_of_month = ((day - 1) // 7) + 1
                week_key = f"week{week_of_month}"
                monthly_map = max_premium_selection.get("monthly", {})
                if week_key in monthly_map:
                    result = monthly_map[week_key]
                    details = f"monthly, {week_key}"
                else:
                    result = None
                    details = f"monthly, {week_key} not found"
                    logger.warning(
                        f"[get_max_premium_from_config] MONTHLY: No entry for {week_key} in map, returning None (symbol={orig_symbol})"
                    )
            else:
                result = None
                details = "unknown expiry_type"
        else:
            result = None
            details = "no max_premium_selection"
    except Exception as e:
        logger.warning(f"[get_max_premium_from_config] Error during max_premium selection: {e}")
        result = None
        details = "exception fallback"
    
    # Check against max_threshold if result is valid
    if result is not None:
        max_threshold = max_premium_selection.get("max_threshold") if isinstance(max_premium_selection, dict) else None
        if max_threshold is not None and result > max_threshold:
            logger.warning(
                f"[get_max_premium_from_config] Selected premium {result} exceeds max_threshold {max_threshold}, returning None (symbol={orig_symbol})"
            )
            result = None
            details += f", exceeded max_threshold={max_threshold}"
    
    logger.debug(
        f"[get_max_premium_from_config] symbol={orig_symbol} (sanitized={symbol_upper}), expiry_type={expiry_type} ({expiry_reason}), {details}, selected max_premium={result}"
    )
    return result

from datetime import datetime, timedelta

async def get_regime_reference_points(
    data_manager,
    symbol: str,
    first_candle_time: str = "09:15",
    first_candle_interval: int = 5,
    current_dt: datetime = None,
) -> dict:
    """
    Fetch previous day high/low and first candle high/low for regime identification.
    """
    logger = logging.getLogger("regime_utils")

    # Get today's trading day (IST)
    trade_day = get_trade_day(current_dt or get_ist_datetime())
    prev_day = trade_day - timedelta(days=1)

    # 1. Fetch previous day OHLC
    prev_day_history = await fetch_instrument_history(
        data_manager,
        [symbol],
        prev_day,
        prev_day,
        interval_minutes="day",  # Or 1440, depending on your system
        ins_type=""
    )
    prev_day_ohlc = prev_day_history.get(symbol)
    if prev_day_ohlc is None or prev_day_ohlc.empty:
        logger.warning(f"Could not fetch previous day OHLC for {symbol} on {prev_day}")
        return None
    prev_day_high = float(prev_day_ohlc.iloc[-1]['high'])
    prev_day_low = float(prev_day_ohlc.iloc[-1]['low'])

    # 2. Fetch today's first candle
    # first_candle_start = datetime.combine(trade_day, datetime.strptime(first_candle_time, "%H:%M").time())
    # first_candle_end = first_candle_start + timedelta(minutes=first_candle_interval)
    candle_times = calculate_first_candle_details(trade_day.date(), first_candle_time, first_candle_interval)
    from_date = candle_times["from_date"]
    to_date = candle_times["to_date"]
    today_intraday = await fetch_instrument_history(
        data_manager,
        [symbol],
        from_date,
        to_date,
        interval_minutes=first_candle_interval,
        ins_type=""
    )
    first_candle_df = today_intraday.get(symbol)
    if first_candle_df is None or first_candle_df.empty:
        logger.warning(f"Could not fetch first candle for {symbol} on {trade_day}")
        return None
    first_candle_high = float(first_candle_df.iloc[0]['high'])
    first_candle_low = float(first_candle_df.iloc[0]['low'])

    return {
        "prev_day_high": prev_day_high,
        "prev_day_low": prev_day_low,
        "first_candle_high": first_candle_high,
        "first_candle_low": first_candle_low,
        "first_candle_time": first_candle_time,
        "first_candle_interval": first_candle_interval,
        "trade_day": trade_day
    }


def detect_regime(
    entry_price: float,
    regime_ref: dict,
    option_type: str,   # "CE" or "PE"
    strategy: str       # "BUY" or "SELL"
):
    """
    Universal regime detector for options strategies.

    Args:
        entry_price (float): The entry price for the option.
        regime_ref (dict): Reference dict with keys: prev_day_high, prev_day_low, first_candle_high, first_candle_low.
        option_type (str): "CE" or "PE"
        strategy (str): "BUY" or "SELL"
    Returns:
        str: One of {"Uptrend", "Downtrend", "Sideways", "NoTrade"}
    """

    ph = regime_ref["prev_day_high"]
    pl = regime_ref["prev_day_low"]
    fh = regime_ref["first_candle_high"]
    fl = regime_ref["first_candle_low"]

    # BUY strategies
    if strategy.upper() == "BUY":
        if option_type.upper() == "CE":
            # CE BUY in uptrend
            if entry_price > ph and entry_price > fh:
                return "Uptrend"
            elif entry_price > fh:
                return "Sideways"
            else:
                return "NoTrade"
        elif option_type.upper() == "PE":
            # PE BUY in downtrend
            if entry_price < pl and entry_price < fl:
                return "Downtrend"
            elif entry_price < fl:
                return "Sideways"
            else:
                return "NoTrade"

    # SELL strategies
    elif strategy.upper() == "SELL":
        if option_type.upper() == "PE":
            # PE SELL in uptrend
            if entry_price > ph and entry_price > fh:
                return "Uptrend"
            elif entry_price > fh:
                return "Sideways"
            else:
                return "NoTrade"
        elif option_type.upper() == "CE":
            # CE SELL in downtrend
            if entry_price < pl and entry_price < fl:
                return "Downtrend"
            elif entry_price < fl:
                return "Sideways"
            else:
                return "NoTrade"

    # Default
    return "NoTrade"
