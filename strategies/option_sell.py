from datetime import datetime, time, timedelta
from typing import Any, Optional

import pandas as pd
from algosat.strategies.base import StrategyBase
from algosat.common.logger import get_logger
from algosat.core.execution_manager import ExecutionManager
from algosat.core.data_manager import DataManager
from algosat.core.dbschema import strategy_configs
from algosat.core.order_manager import OrderManager
from algosat.core.broker_manager import BrokerManager
from algosat.core.order_request import Side
from algosat.core.db import AsyncSessionLocal, get_all_orders_for_strategy_symbol_and_tradeday, get_order_by_id
from algosat.core.signal import TradeSignal, SignalType
from algosat.common.strategy_utils import (
    calculate_end_date,
    detect_regime,
    get_regime_reference_points,
    wait_for_first_candle_completion,
    calculate_first_candle_details,
    fetch_option_chain_and_first_candle_history,
    identify_strike_price_combined,
    fetch_instrument_history,
    calculate_backdate_days,
    localize_to_ist,
    calculate_trade,
    get_max_premium_from_config,
)
# Import regime detection helpers
from algosat.utils.indicators import (
    calculate_atr_trial_stops,
    calculate_supertrend,
    calculate_atr,
    calculate_sma,
    calculate_vwap,
)
from algosat.core.time_utils import get_ist_datetime
from algosat.common.broker_utils import get_trade_day
from algosat.common import constants
import json
import os
import time as time_module
import asyncio
from algosat.core.signal import TradeSignal, SignalType
from algosat.models.strategy_config import StrategyConfig
from algosat.core.db import AsyncSessionLocal, get_open_orders_for_symbol_and_tradeday
from algosat.core.strategy_symbol_utils import get_strategy_symbol_id
from algosat.core.db import get_open_orders_for_strategy_symbol_and_tradeday

logger = get_logger(__name__)

IDENTIFIED_STRIKES_FILE = "/opt/algosat/Files/cache/identified_strikes.json"
LOCK_FILE = IDENTIFIED_STRIKES_FILE + ".lock"

def ensure_cache_dir():
    cache_dir = os.path.dirname(IDENTIFIED_STRIKES_FILE)
    os.makedirs(cache_dir, exist_ok=True)

async def acquire_lock(lock_file, timeout=30):
    start_time = time_module.time()
    while os.path.exists(lock_file):
        if time.time() - start_time > timeout:
            raise TimeoutError(f"Could not acquire lock on {lock_file} within {timeout} seconds.")
        await asyncio.sleep(0.1)
    with open(lock_file, 'w') as f:
        f.write(str(os.getpid()))

def release_lock(lock_file):
    if os.path.exists(lock_file):
        os.remove(lock_file)

async def load_identified_strikes_cache():
    ensure_cache_dir()
    await acquire_lock(LOCK_FILE)
    try:
        if os.path.exists(IDENTIFIED_STRIKES_FILE):
            with open(IDENTIFIED_STRIKES_FILE, "r") as f:
                try:
                    return json.load(f)
                except Exception:
                    return {}
        return {}
    finally:
        release_lock(LOCK_FILE)

async def save_identified_strikes_cache(cache):
    ensure_cache_dir()
    await acquire_lock(LOCK_FILE)
    try:
        with open(IDENTIFIED_STRIKES_FILE, "w") as f:
            json.dump(cache, f, indent=2, default=str)
    finally:
        release_lock(LOCK_FILE)

def cleanup_old_strike_cache(cache, days=1):
    now = datetime.now()
    keys_to_delete = []
    for key, value in cache.items():
        try:
            parts = key.split("_")
            date_str = parts[1]
            cache_date = datetime.fromisoformat(date_str)
            if (now.date() - cache_date.date()).days > days:
                keys_to_delete.append(key)
        except Exception:
            continue
    for key in keys_to_delete:
        del cache[key]

def cleanup_pre_candle_cache(cache, trade_day, first_candle_time, interval_minutes):
    """
    Clean up cache entries for today that were created before the first candle completion time.
    This prevents using strikes identified from pre-market or test data during actual trading.
    
    Args:
        cache: The cache dictionary
        trade_day: Current trade day datetime
        first_candle_time: First candle time string (e.g., "09:15")
        interval_minutes: Interval in minutes
    """
    from datetime import datetime, time as dt_time
    
    today_str = trade_day.date().isoformat()
    keys_to_delete = []
    
    # Calculate first candle completion time for today (ensure timezone awareness)
    first_candle_time_parts = first_candle_time.split(":")
    first_candle_hour = int(first_candle_time_parts[0])
    first_candle_minute = int(first_candle_time_parts[1])
    
    # Create first candle completion time with same timezone as trade_day
    first_candle_completion_time = datetime.combine(
        trade_day.date(),
        dt_time(first_candle_hour, first_candle_minute)
    ) + timedelta(minutes=interval_minutes)
    
    # Make timezone-aware if trade_day has timezone info
    if trade_day.tzinfo:
        first_candle_completion_time = first_candle_completion_time.replace(tzinfo=trade_day.tzinfo)
    
    # Check cache entries for today
    for key, value in cache.items():
        try:
            parts = key.split("_")
            if len(parts) >= 2:
                cache_date_str = parts[1]
                
                # Only check entries for today
                if cache_date_str == today_str:
                    # Check if cache entry has metadata with creation timestamp
                    if isinstance(value, dict) and 'metadata' in value and 'created_at' in value['metadata']:
                        created_at_str = value['metadata']['created_at']
                        created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                        
                        # Ensure both datetimes have same timezone info for comparison
                        if first_candle_completion_time.tzinfo and not created_at.tzinfo:
                            # Make created_at timezone-aware (assume it's in same timezone as trade_day)
                            created_at = created_at.replace(tzinfo=first_candle_completion_time.tzinfo)
                        elif not first_candle_completion_time.tzinfo and created_at.tzinfo:
                            # Convert created_at to naive datetime for comparison
                            created_at = created_at.replace(tzinfo=None)
                        elif first_candle_completion_time.tzinfo and created_at.tzinfo:
                            # Both are timezone-aware, convert created_at to same timezone
                            created_at = created_at.astimezone(first_candle_completion_time.tzinfo)
                        
                        # If cache was created before first candle completion, mark for deletion
                        if created_at < first_candle_completion_time:
                            keys_to_delete.append(key)
                            logger.info(f"Marking cache entry for deletion: {key} (created at {created_at} before first candle completion at {first_candle_completion_time})")
                    else:
                        # Legacy cache entry without metadata - assume it's invalid for today
                        keys_to_delete.append(key)
                        logger.info(f"Marking legacy cache entry for deletion: {key} (no creation metadata)")
        except Exception as e:
            logger.warning(f"Error checking cache entry {key}: {e}")
            continue
    
    # Delete invalid entries
    for key in keys_to_delete:
        del cache[key]
        logger.info(f"Deleted pre-candle cache entry: {key}")
    
    return len(keys_to_delete)

class OptionSellStrategy(StrategyBase):
    """
    Concrete implementation of the Option Buy strategy.
    Fetches option chain at setup, picks strikes by premium threshold,
    then on each tick evaluates entry and exit signals.
    """

    def __init__(self, config: StrategyConfig, data_manager: DataManager, execution_manager: OrderManager):
        super().__init__(config, data_manager, execution_manager)
        # All config access should use self.cfg (the StrategyConfig dataclass)
        self.symbol = self.cfg.symbol
        self.name = "OptionSell"
        self.exchange = self.cfg.exchange
        self.instrument = self.cfg.instrument
        self.trade = self.cfg.trade
        self.indicators = self.cfg.indicators
        self.trade_symbol = self.cfg.symbol
        self.timeframe = self.trade.get("timeframe", "1m")
        self.poll_interval = self.trade.get("poll_interval", 60)
        self.start_time = None
        self.end_time = None
        self.premium = self.trade.get("premium", 100)
        self.quantity = self.trade.get("quantity", 1)
        self.strike_count = self.trade.get("strike_count", 20)
        # Internal state
        self._strikes = []         # Selected strikes after setup()
        self._position = None      # Track current open position, if any
        self._setup_failed = False # Track if setup failed
        self.order_manager = execution_manager  # <-- Fix: store execution_manager as order_manager
        self._positions = {}       # Track open positions by strike
        self._last_signal_direction = {}  # Track last signal direction per strike
        # Regime reference loaded at setup
        self.regime_reference = None

    async def ensure_broker(self):
        # No longer needed for data fetches, but keep for order placement if required
        await self.dp._ensure_broker()

    async def setup(self) -> None:
        """One-time setup: modular workflow for OptionSell."""
        if self._strikes:
            return
        trade = self.trade
        interval_minutes = trade.get("interval_minutes", 5)
        first_candle_time = trade.get("first_candle_time", "09:15")
        symbol = self.symbol
        if not symbol:
            logger.error("No symbol configured for OptionSell strategy.")
            return
        # 1. Wait for first candle completion
        await wait_for_first_candle_completion(interval_minutes, first_candle_time, symbol)
        await asyncio.sleep(2)  # Give some time for the first candle to complete
        logger.info('First candle completed, proceeding with setup...')
        
        max_strikes = trade.get("max_strikes", 40)
       
        today_dt = get_ist_datetime()
        # Dynamically select max_premium (expiry_type is auto-detected inside)
        max_premium = get_max_premium_from_config(trade, symbol, today_dt)
        if max_premium is None:
            logger.error(f"Failed to determine max_premium for {symbol} on {today_dt}. Check configuration.")
            self._setup_failed = True
            return
        
        # 2. Calculate first candle data using the correct trade day
        trade_day = get_trade_day(get_ist_datetime())
        # 3. Fetch option chain and identify strikes
        cache = await load_identified_strikes_cache()
        cache_key = f"{symbol}_{trade_day.date().isoformat()}_{interval_minutes}_{max_strikes}_{max_premium}"
        
        # Clean up old cache entries (older than 10 days)
        cleanup_old_strike_cache(cache, days=10)
        
        # Clean up today's cache entries that were created before first candle completion
        deleted_count = cleanup_pre_candle_cache(cache, trade_day, first_candle_time, interval_minutes)
        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} pre-candle cache entries for today")
        
        # Check if we have a valid cache entry for today (after cleanup)
        if cache_key in cache:
            cache_entry = cache[cache_key]
            
            # Handle both legacy format (list) and new format (dict with metadata)
            if isinstance(cache_entry, list):
                self._strikes = cache_entry
                logger.info(f"Loaded identified strikes from legacy cache: {self._strikes}")
            elif isinstance(cache_entry, dict) and 'strikes' in cache_entry:
                self._strikes = cache_entry['strikes']
                logger.info(f"Loaded identified strikes from cache: {self._strikes}")
                logger.info(f"Cache created at: {cache_entry.get('metadata', {}).get('created_at', 'unknown')}")
            else:
                logger.warning(f"Invalid cache entry format for key {cache_key}, will regenerate")
                del cache[cache_key]  # Remove invalid entry
            
            if self._strikes:
                await save_identified_strikes_cache(cache)
                return
        candle_times = calculate_first_candle_details(trade_day.date(), first_candle_time, interval_minutes)
        from_date = candle_times["from_date"]
        to_date = candle_times["to_date"]
        history_data = await fetch_option_chain_and_first_candle_history(
            self.dp, symbol, interval_minutes, max_strikes, from_date, to_date, bot_name="OptionSell"
        )
        if not history_data or all(h is None for h in history_data):
            history_data = None
        ce_strike, pe_strike = identify_strike_price_combined(history_data=history_data, max_premium=max_premium)
        self._strikes = []
        if ce_strike is not None:
            self._strikes.append(ce_strike)
        if pe_strike is not None:
            self._strikes.append(pe_strike)
        if self._strikes:
            # Store strikes with metadata including creation timestamp
            from datetime import datetime, timezone
            cache_entry = {
                'strikes': self._strikes,
                'metadata': {
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'first_candle_time': first_candle_time,
                    'interval_minutes': interval_minutes,
                    'max_premium': max_premium,
                    'symbol': symbol
                }
            }
            cache[cache_key] = cache_entry
            await save_identified_strikes_cache(cache)
            logger.info(f"Cached identified strikes with metadata: {self._strikes}")
            logger.info(f"Cache metadata: created_at={cache_entry['metadata']['created_at']}, first_candle_time={first_candle_time}")
        if not self._strikes:
            logger.error("Failed to identify any valid strike prices. Setup failed.")
            self._setup_failed = True
        else:
            self._setup_failed = False
            logger.info(f"Selected strikes for entry: {self._strikes}")
        # Load regime reference once at setup (similar to option_buy)
        try:
            today_dt = get_ist_datetime()
            interval_minutes = trade.get("interval_minutes", 5)
            first_candle_time = trade.get("first_candle_time", "09:15")
            self.regime_reference = await get_regime_reference_points(
                self.dp,
                self.symbol,
                first_candle_time,
                interval_minutes,
                today_dt
            )
            logger.info(f"Regime reference points for {symbol}: {self.regime_reference}")
        except Exception as e:
            logger.error(f"Error loading regime reference: {e}")
            self.regime_reference = None

    async def sync_open_positions(self):
        """
        Synchronize self._positions with open orders in the database for all strikes for the current trade day.
        Uses the strategy_id from config to find related strategy_symbols and their open orders.
        Now uses the strike_symbol field directly from orders table instead of joining with strategy_symbols.
        Also tracks the last signal direction per strike.
        """
        self._positions = {}
        open_statuses = ['AWAITING_ENTRY', 'OPEN', 'PARTIALLY_FILLED', 'PENDING', 'TRIGGER_PENDING']
        async with AsyncSessionLocal() as session:
            from algosat.core.db import get_all_orders_for_strategy_and_tradeday

            trade_day = get_trade_day(get_ist_datetime())
            strategy_id = getattr(self.cfg, 'strategy_id', None)

            if not strategy_id:
                logger.warning("No strategy_id found in config, cannot sync open positions")
                return

            # Get all orders for this strategy on the current trade day (no status filter)
            all_orders = await get_all_orders_for_strategy_and_tradeday(session, strategy_id, trade_day)

            # Filter for open statuses
            open_orders = [o for o in all_orders if o.get('status') in open_statuses]

            # Group open orders by strike symbol
            for order in open_orders:
                strike_symbol = order.get("strike_symbol")
                if strike_symbol and strike_symbol in self._strikes:
                    if strike_symbol not in self._positions:
                        self._positions[strike_symbol] = []
                    self._positions[strike_symbol].append(order)

            # For all orders (not just open), sort by strike and timestamp, and set last_signal_direction
            orders_by_strike = {}
            for order in all_orders:
                strike_symbol = order.get("strike_symbol")
                if strike_symbol and strike_symbol in self._strikes:
                    if strike_symbol not in orders_by_strike:
                        orders_by_strike[strike_symbol] = []
                    orders_by_strike[strike_symbol].append(order)

            from datetime import datetime
            def safe_parse_timestamp(ts):
                # Accepts string (ISO), datetime, or None. Returns a sortable value.
                if isinstance(ts, datetime):
                    return ts
                if isinstance(ts, str):
                    try:
                        # Try ISO format first
                        return datetime.fromisoformat(ts)
                    except Exception:
                        pass
                # If None or malformed, return minimal value so it sorts first
                return datetime.min

            for strike_symbol, order_list in orders_by_strike.items():
                # Sort by timestamp ascending (oldest to newest), robust to malformed/missing timestamps
                sorted_orders = sorted(order_list, key=lambda o: safe_parse_timestamp(o.get("timestamp")))
                if sorted_orders:
                    self._last_signal_direction[strike_symbol] = sorted_orders[-1].get("side")

            logger.debug(f"Synced positions for strategy {strategy_id}: {list(self._positions.keys())}")
            logger.debug(f"Synced last_signal_direction: {self._last_signal_direction}")

    async def check_trade_limits(self) -> tuple[bool, str]:
        """
        Check if the symbol has exceeded maximum trades or maximum loss trades configured limits.
        Now symbol-based instead of strategy-based.
        Returns (can_trade: bool, reason: str)
        """
        try:
            trade_config = self.trade
            max_trades = trade_config.get('max_trades', None)
            max_loss_trades = trade_config.get('max_loss_trades', None)
            
            # If no limits are configured, allow trading
            if max_trades is None and max_loss_trades is None:
                return True, "No trade limits configured"
            
            symbol_id = getattr(self.cfg, 'symbol_id', None)
            if not symbol_id:
                logger.warning("No symbol_id found in config, cannot check trade limits")
                return True, "No symbol_id found, allowing trade"
            
            trade_day = get_trade_day(get_ist_datetime())
            
            async with AsyncSessionLocal() as session:
                # Get all orders for this strategy symbol on the current trade day
                all_orders = await get_all_orders_for_strategy_symbol_and_tradeday(session, symbol_id, trade_day)
                
                # Count completed trades (both profitable and loss trades)
                completed_statuses = [
                    constants.TRADE_STATUS_EXIT_TARGET,
                    constants.TRADE_STATUS_EXIT_STOPLOSS,
                    constants.TRADE_STATUS_EXIT_REVERSAL,
                    constants.TRADE_STATUS_EXIT_EOD,
                    constants.TRADE_STATUS_EXIT_MAX_LOSS,
                    constants.TRADE_STATUS_EXIT_ATOMIC_FAILED,
                    constants.TRADE_STATUS_ENTRY_CANCELLED,
                    constants.TRADE_STATUS_EXIT_CLOSED
                    
                ]
                
                completed_trades = [order for order in all_orders if order.get('status') in completed_statuses]
                total_completed_trades = len(completed_trades)
                
                # Count loss trades (excluding profitable trades)
                loss_statuses = [
                    constants.TRADE_STATUS_EXIT_STOPLOSS,
                    constants.TRADE_STATUS_EXIT_MAX_LOSS,
                    constants.TRADE_STATUS_ENTRY_CANCELLED
                ]
                
                loss_trades = [order for order in completed_trades if order.get('status') in loss_statuses]
                total_loss_trades = len(loss_trades)
                
                logger.debug(f"Trade limits check - Total completed trades: {total_completed_trades}, Loss trades: {total_loss_trades}")
                logger.debug(f"Trade limits config - Max trades: {max_trades}, Max loss trades: {max_loss_trades}")
                logger.debug(f"Completed trade statuses found: {[order.get('status') for order in completed_trades]}")
                logger.debug(f"Loss trade statuses found: {[order.get('status') for order in loss_trades]}")
                
                # Check max_trades limit
                if max_trades is not None and total_completed_trades >= max_trades:
                    reason = f"Maximum trades limit reached for symbol: {total_completed_trades}/{max_trades}"
                    logger.info(reason)
                    return False, reason
                
                # Check max_loss_trades limit
                if max_loss_trades is not None and total_loss_trades >= max_loss_trades:
                    reason = f"Maximum loss trades limit reached for symbol: {total_loss_trades}/{max_loss_trades}"
                    logger.info(reason)
                    return False, reason
                
                return True, f"Trade limits OK for symbol - Completed: {total_completed_trades}/{max_trades or 'unlimited'}, Loss: {total_loss_trades}/{max_loss_trades or 'unlimited'}"
                
        except Exception as e:
            logger.error(f"Error checking trade limits: {e}")
            # On error, allow trading to avoid blocking legitimate trades
            return True, f"Error checking trade limits, allowing trade: {e}"
            

    async def process_cycle(self) -> Optional[dict]:
        """
        Main signal evaluation cycle for OptionBuyStrategy.
        Refactored for clarity: 1) Fetch history, 2) Compute indicators, 3) Evaluate signal, 4) Place order.
        Returns order info dict if an order is placed, else None.
        """
        if getattr(self, '_setup_failed', False) or not self._strikes:
            logger.warning("process_cycle aborted: setup failed or no strikes available.")
            return None
        
        # Check trade limits before proceeding with any new trades
        can_trade, limit_reason = await self.check_trade_limits()
        if not can_trade:
            logger.warning(f"process_cycle aborted: {limit_reason}")
            return None
        
        logger.debug(f"Trade limits check passed: {limit_reason}")

        trade_config = self.trade
        interval_minutes = trade_config.get('interval_minutes', 5)
        trade_day = get_trade_day(get_ist_datetime())#  - timedelta(days=4)
        # 1. Fetch history for all strikes
        history_data = await self.fetch_history_data(
            self.dp, self._strikes, trade_day, trade_config
        )
        if not history_data or all(h is None or getattr(h, 'empty', False) for h in history_data.values()):
            logger.warning("No history data received for strikes. Skipping signal evaluation.")
            return None
        # 2. Compute entry indicators for each strike
        indicator_data = {
            strike: self.compute_entry_indicators(data, strike)
            for strike, data in history_data.items()
            if data is not None and not getattr(data, 'empty', False)
        }
        await self.sync_open_positions()  # Sync in-memory with DB
        # 3. Evaluate trade signal for each strike
        for strike, data in indicator_data.items():
            try:
                # Check DB-synced open positions
                if self._positions.get(strike):
                    logger.info(f"DB: Position already open for {strike}, skipping signal evaluation and order placement.")
                    continue
                signal_payload = await self.evaluate_trade_signal(data, trade_config, strike)
                # 4. Place order if signal
                order_info = await self.process_order(signal_payload, data, strike)
                if order_info:
                    # Immediately update in-memory _positions for this strike to prevent duplicate signals in next run
                    self._positions[strike] = [order_info]
                    logger.debug(f"Updated in-memory _positions for {strike} after order placement: {self._positions[strike]}")
                    return order_info  # Return as soon as an order is placed
            except Exception as e:
                logger.error(f"Error during signal evaluation or order for {strike}: {e}")
        return None  # No order placed

    async def fetch_history_data(self, broker, strike_symbols, current_date, trade_config: dict):
        """
        Fetch candle data for the given strike symbols.
        Split out for clarity and easier backtest override.
        All datetimes are IST-aware.
        """
        try:
            back_days = calculate_backdate_days(trade_config['interval_minutes'])
            trade_day = get_trade_day(current_date - timedelta(days=back_days))
            # Make start_date and end_date IST-aware
            start_date = localize_to_ist(datetime.combine(trade_day, time(9, 15)))
            current_end_date = localize_to_ist(datetime.combine(current_date, get_ist_datetime().time()))
            end_date = calculate_end_date(current_end_date, trade_config['interval_minutes'])
            # end_date = end_date.replace(hour=9, minute=45, second=0, microsecond=0)
            logger.debug(f"Fetching history for strike symbols {', '.join(str(strike) for strike in strike_symbols)}...")
            logger.debug(f"Start date: {start_date}, End date: {end_date}, Interval: {trade_config['interval_minutes']} minutes")
            history_data = await fetch_instrument_history(
                self.dp,
                self._strikes,
                from_date=start_date,
                to_date=end_date,
                interval_minutes=trade_config['interval_minutes'],
                ins_type="",
                cache=False
            )
            return history_data
        except Exception as error:
            logger.error(f"Error fetching candle data: {error}")
            return {}

    def compute_entry_indicators(self, data, strike):
        """
        Compute all entry indicators on the DataFrame for a given strike using self.indicators['entry'].
        Returns the updated DataFrame.
        """
        try:
            if data is None or len(data) < 2:
                logger.warning(f"Not enough candles for signal evaluation in {strike}")
                return data
            cols = [constants.COLUMN_OPEN, constants.COLUMN_LOW, constants.COLUMN_CLOSE, constants.COLUMN_HIGH, 'volume']
            data.loc[:, cols] = data[cols].apply(pd.to_numeric, errors='coerce')
            data.dropna(subset=cols, inplace=True)

            # Get entry indicator config from self.indicators
            entry_conf = self.indicators.get('entry', {})
            supertrend_period = entry_conf.get('supertrend_period', 10)
            supertrend_multiplier = entry_conf.get('supertrend_multiplier', 2)
            sma_period = entry_conf.get('sma_period', 14)
            atr_period = entry_conf.get('atr_period', 14)

            data = calculate_supertrend(data, supertrend_period, supertrend_multiplier)
            data = calculate_atr(data, atr_period)
            data = calculate_sma(data, sma_period)
            data = calculate_vwap(data)
            data['supertrend'] = data['supertrend'].round(2)
            data['vwap'] = data['vwap'].round(2)
            data['sma'] = data['sma'].round(2)
        except Exception as e:
            logger.error(f"Error calculating indicators for {strike}: {e}")
        return data
        

    def get_config_id(self):
        """
        Safely extract the id from self.cfg (StrategyConfig dataclass).
        """
        if hasattr(self, 'cfg') and hasattr(self.cfg, 'id'):
            return self.cfg.id
        return None

    async def process_order(self, signal_payload, data, strike):
        """
        Process order using the new TradeSignal and BrokerManager logic.
        Always pass self.cfg (StrategyConfig) as the config to order_manager.place_order for correct DB logging.
        Returns order info dict with local DB order_id if an order is placed, else None.
        Now also fetches hedge symbol and logs it.
        Implements robust hedge order handling: checks if ALL hedge orders failed before aborting,
        allows partial hedge success, sets parent_order_id relationships, and provides comprehensive cleanup.
        """
        if not signal_payload:
            logger.debug(f"No signal for {strike} at {data.iloc[-1].get('timestamp', 'N/A')}")
            return None

        ts = data.iloc[-1].get('timestamp', 'N/A')
        logger.info(f"Signal formed for {strike} at {ts}: {signal_payload}")

        # 1. Fetch and place hedge order first
        hedge_order_result = None
        try:
            # Use signal_payload.symbol (the actual option symbol) for hedge calculation
            option_symbol = signal_payload.symbol
            logger.info(f"🔍 Fetching hedge symbol for {option_symbol}")
            hedge_symbol = await self.fetch_hedge_symbol(self.order_manager.broker_manager, option_symbol, self.trade)
            if not hedge_symbol:
                logger.error(f"❌ No hedge symbol found for {option_symbol}, aborting trade.")
                return None

            logger.info(f"🛡️ Hedge symbol identified for {option_symbol}: {hedge_symbol}")
            
            hedge_signal_payload = TradeSignal(
                symbol=hedge_symbol,
                side="BUY",
                signal_type=SignalType.HEDGE_ENTRY,
                signal_time=signal_payload.signal_time,
                signal_direction="hedge buy",
                lot_qty=signal_payload.lot_qty,
            )
            
            logger.debug(f"Building hedge order request for {hedge_symbol}")
            hedge_order_request = await self.order_manager.broker_manager.build_order_request_for_strategy(
                hedge_signal_payload, self.cfg
            )
            
            logger.info(f"📤 Placing hedge order for {hedge_symbol} (Main: {option_symbol})")
            hedge_order_result = await self.order_manager.place_order(
                self.cfg, hedge_order_request, strategy_name=None
            )
            logger.debug(f"Hedge order result for {hedge_symbol}: {hedge_order_result}")

            # Check if ALL hedge orders failed (proceed if at least one hedge succeeds)
            failed_statuses = {"FAILED", "CANCELLED", "REJECTED"}
            broker_responses = hedge_order_result.get('broker_responses') if hedge_order_result else None
            all_failed = False
            
            if broker_responses and isinstance(broker_responses, dict):
                statuses = [str(resp.get('status')).split('.')[-1].replace("'>", "").upper() if resp else None for resp in broker_responses.values()]
                logger.debug(f"Hedge order broker statuses for {hedge_symbol}: {statuses}")
                
                # Check if ALL hedge orders failed (instead of ANY)
                valid_statuses = [s for s in statuses if s]  # Filter out None values
                if valid_statuses and all(s in failed_statuses for s in valid_statuses):
                    all_failed = True
                    failed_hedge_brokers = [broker_id for broker_id, resp in broker_responses.items() 
                                          if resp and str(resp.get('status')).split('.')[-1].replace("'>", "").upper() in failed_statuses]
                    logger.error(f"❌ ALL hedge orders failed for {hedge_symbol}: {[s for s in valid_statuses if s in failed_statuses]}")
                    logger.error(f"❌ All failed hedge brokers: {failed_hedge_brokers}")
                elif any(s in failed_statuses for s in valid_statuses):
                    # Some hedge orders failed, but at least one succeeded
                    failed_hedge_brokers = [broker_id for broker_id, resp in broker_responses.items() 
                                          if resp and str(resp.get('status')).split('.')[-1].replace("'>", "").upper() in failed_statuses]
                    successful_hedge_brokers = [broker_id for broker_id, resp in broker_responses.items() 
                                              if resp and str(resp.get('status')).split('.')[-1].replace("'>", "").upper() not in failed_statuses]
                    logger.warning(f"⚠️ Some hedge orders failed for {hedge_symbol}: {[s for s in valid_statuses if s in failed_statuses]}")
                    logger.warning(f"⚠️ Failed hedge brokers: {failed_hedge_brokers}")
                    logger.info(f"✅ Successful hedge brokers: {successful_hedge_brokers} - Continuing with trade")
            
            if all_failed:
                failed_hedge_brokers = [broker_id for broker_id, resp in broker_responses.items() 
                                       if resp and str(resp.get('status')).split('.')[-1].replace("'>", "").upper() in failed_statuses]
                
                # Comprehensive logging for hedge order failure
                logger.error(f"🚨 CRITICAL: ALL hedge orders failed for {hedge_symbol} (Main: {option_symbol}), aborting entire trade")
                logger.error(f"💥 Failed hedge brokers: {failed_hedge_brokers}")
                logger.error(f"💥 Hedge order failure details:")
                for broker_id, resp in broker_responses.items():
                    if resp:
                        broker_order_id = resp.get('broker_order_id')
                        status = str(resp.get('status')).split('.')[-1].replace("'>", "").upper()
                        error_msg = resp.get('error_message') or resp.get('message') or 'No error message'
                        logger.error(f"💥   Broker {broker_id}: Order ID {broker_order_id}, Status: {status}, Error: {error_msg}")
                    else:
                        logger.error(f"💥   Broker {broker_id}: No response data available")
                
                # Call exit order even if hedge order fails to ensure no orphaned orders
                hedge_order_id = hedge_order_result.get("order_id") or hedge_order_result.get("id")
                if hedge_order_id:
                    logger.warning(f"🔄 Attempting to clean up failed hedge order {hedge_order_id}")
                    await self.order_manager.exit_order(hedge_order_id, exit_reason="All hedge orders failure")
                return None
            
            hedge_order_id = hedge_order_result.get("order_id") or hedge_order_result.get("id")
            logger.info(f"✅ Hedge order placed successfully for {hedge_symbol} (Main: {option_symbol}). Hedge Order ID: {hedge_order_id}")

        except Exception as e:
            logger.error(f"💥 An exception occurred while placing the hedge order for {option_symbol}: {e}", exc_info=True)
            logger.error(f"💥 Hedge symbol: {hedge_symbol if 'hedge_symbol' in locals() else 'Not determined'}")
            return None  # Abort if hedge placement fails

        # 2. Place main SELL order and handle potential failure
        main_order_result = None
        try:
            logger.info(f"Building order request for main SELL order: {option_symbol}")
            order_request = await self.order_manager.broker_manager.build_order_request_for_strategy(
                signal_payload, self.cfg
            )
            logger.info(f"Placing main SELL order for {option_symbol}")
            
            main_order_result = await self.order_manager.place_order(
                self.cfg, order_request, strategy_name=None
            )
            logger.debug(f"Main SELL order result for {option_symbol}: {main_order_result}")
            
            # Check if ALL main orders failed (consistent with hedge logic)
            main_broker_responses = main_order_result.get('broker_responses') if main_order_result else None
            main_all_failed = False
            
            if main_broker_responses and isinstance(main_broker_responses, dict):
                main_statuses = [str(resp.get('status')).split('.')[-1].replace("'>", "").upper() if resp else None for resp in main_broker_responses.values()]
                logger.debug(f"Main order broker statuses for {option_symbol}: {main_statuses}")
                
                # Check if ALL main orders failed (instead of ANY)
                valid_main_statuses = [s for s in main_statuses if s]  # Filter out None values
                if valid_main_statuses and all(s in failed_statuses for s in valid_main_statuses):
                    main_all_failed = True
                    failed_main_brokers = [broker_id for broker_id, resp in main_broker_responses.items() 
                                          if resp and str(resp.get('status')).split('.')[-1].replace("'>", "").upper() in failed_statuses]
                    logger.error(f"❌ ALL main SELL orders failed for {option_symbol}: {[s for s in valid_main_statuses if s in failed_statuses]}")
                    logger.error(f"❌ All failed main brokers: {failed_main_brokers}")
                elif any(s in failed_statuses for s in valid_main_statuses):
                    # Some main orders failed, but at least one succeeded
                    failed_main_brokers = [broker_id for broker_id, resp in main_broker_responses.items() 
                                          if resp and str(resp.get('status')).split('.')[-1].replace("'>", "").upper() in failed_statuses]
                    successful_main_brokers = [broker_id for broker_id, resp in main_broker_responses.items() 
                                              if resp and str(resp.get('status')).split('.')[-1].replace("'>", "").upper() not in failed_statuses]
                    logger.warning(f"⚠️ Some main SELL orders failed for {option_symbol}: {[s for s in valid_main_statuses if s in failed_statuses]}")
                    logger.warning(f"⚠️ Failed main brokers: {failed_main_brokers}")
                    logger.info(f"✅ Successful main brokers: {successful_main_brokers} - Continuing with trade")

            if main_all_failed:
                failed_main_brokers = [broker_id for broker_id, resp in main_broker_responses.items() 
                                      if resp and str(resp.get('status')).split('.')[-1].replace("'>", "").upper() in failed_statuses]
                
                # Comprehensive logging for main order failure
                logger.error(f"🚨 CRITICAL: ALL main SELL orders failed for {option_symbol}")
                logger.error(f"💥 Failed main brokers: {failed_main_brokers}")
                logger.error(f"💥 Main order failure details:")
                for broker_id, resp in main_broker_responses.items():
                    if resp:
                        broker_order_id = resp.get('broker_order_id')
                        status = str(resp.get('status')).split('.')[-1].replace("'>", "").upper()
                        error_msg = resp.get('error_message') or resp.get('message') or 'No error message'
                        logger.error(f"💥   Broker {broker_id}: Order ID {broker_order_id}, Status: {status}, Error: {error_msg}")
                    else:
                        logger.error(f"💥   Broker {broker_id}: No response data available")
                
                raise Exception(f"ALL main SELL orders failed/cancelled/rejected for {option_symbol}. Failed brokers: {failed_main_brokers}. Details: {main_order_result}")

            logger.info(f"✅ Main SELL order placed successfully for {option_symbol}. Order ID: {main_order_result.get('order_id') or main_order_result.get('id')}")
            
            # Set parent_order_id relationship: hedge order is child of main order
            hedge_order_id = hedge_order_result.get("order_id") or hedge_order_result.get("id")
            main_order_id = main_order_result.get('order_id') or main_order_result.get('id')
            
            if hedge_order_id and main_order_id:
                try:
                    logger.info(f"🔗 Setting parent_order_id relationship: hedge {hedge_order_id} -> main {main_order_id}")
                    await self.order_manager.set_parent_order_id(hedge_order_id, main_order_id)
                    logger.debug(f"✅ Parent-child relationship established: hedge {hedge_order_id} is child of main {main_order_id}")
                except Exception as e:
                    logger.error(f"⚠️ Failed to set parent_order_id relationship for hedge {hedge_order_id} -> main {main_order_id}: {e}")
            
            # Return merged order_request + main_order_result format like other strategies
            # Convert OrderRequest to dict for merging
            if hasattr(order_request, 'dict'):
                order_request_dict = order_request.dict()
            else:
                order_request_dict = dict(order_request)
            return {**order_request_dict, **main_order_result}

        except Exception as e:
            logger.critical(f"🚨 CRITICAL: Main SELL order failed for {option_symbol} after hedge was placed. Attempting to exit hedge. Error: {e}", exc_info=True)
            
            # Extract hedge order details for cleanup
            hedge_order_id = hedge_order_result.get("order_id") or hedge_order_result.get("id")
            hedge_broker_responses = hedge_order_result.get('broker_responses') if hedge_order_result else None
            
            # Log detailed main order failure context for the orphaned hedge cleanup
            logger.error(f"💀 Orphaned hedge order detected due to main order failure:")
            logger.error(f"💀   Main Strike: {option_symbol}")
            logger.error(f"💀   Hedge Order ID: {hedge_order_id}")
            logger.error(f"💀   Main Order Failure: {str(e)}")
            
            # Log hedge order broker details that need cleanup
            if hedge_broker_responses:
                logger.error(f"💀 Hedge order brokers requiring cleanup:")
                for broker_id, response in hedge_broker_responses.items():
                    if response:
                        broker_order_id = response.get('broker_order_id')
                        status = str(response.get('status')).split('.')[-1].replace("'>", "").upper() if response.get('status') else 'Unknown'
                        logger.error(f"💀   Broker {broker_id}: Order ID {broker_order_id}, Status: {status}")
                    else:
                        logger.error(f"💀   Broker {broker_id}: No response data available")
            
            if hedge_order_id:
                try:
                    logger.warning(f"🔄 Attempting to exit orphaned hedge order {hedge_order_id} for {option_symbol}")
                    await self.order_manager.exit_order(hedge_order_id, exit_reason=f"Main order failure: {str(e)[:100]}")
                    logger.info(f"✅ Successfully initiated exit for orphaned hedge order {hedge_order_id} (Strike: {option_symbol})")
                    
                    # Log hedge order exit confirmation with broker details
                    if hedge_broker_responses:
                        logger.info(f"📊 Hedge order cleanup initiated for brokers: {list(hedge_broker_responses.keys())}")
                        
                except Exception as exit_e:
                    logger.error(f"💥 FATAL: Failed to exit orphaned hedge order {hedge_order_id} for {option_symbol}. "
                               f"Manual intervention required immediately! Error: {exit_e}", exc_info=True)
                    logger.error(f"💥 MANUAL ACTION REQUIRED: Hedge order {hedge_order_id} for {option_symbol} is orphaned and could not be auto-exited")
                    
                    # Log comprehensive context for manual intervention
                    if hedge_broker_responses:
                        logger.error(f"💥 Manual cleanup required for brokers: {list(hedge_broker_responses.keys())}")
                        for broker_id, response in hedge_broker_responses.items():
                            if response:
                                broker_order_id = response.get('broker_order_id')
                                status = str(response.get('status')).split('.')[-1].replace("'>", "").upper() if response.get('status') else 'Unknown'
                                error_msg = response.get('error_message') or response.get('message') or 'No error message'
                                logger.error(f"💥   Broker {broker_id}: Order ID {broker_order_id}, Status: {status}, Error: {error_msg}")
                            else:
                                logger.error(f"💥   Broker {broker_id}: No response data available")
            else:
                logger.error(f"💥 FATAL: Could not find order_id for orphaned hedge order for {option_symbol}. "
                           f"Manual intervention required immediately!")
                logger.error(f"💥 MANUAL ACTION REQUIRED: Hedge order details for manual cleanup: {hedge_order_result}")
                
                # Log broker-specific details for manual cleanup
                if hedge_broker_responses:
                    logger.error(f"💥 Manual cleanup required - Hedge brokers: {list(hedge_broker_responses.keys())}")
                    for broker_id, response in hedge_broker_responses.items():
                        if response:
                            broker_order_id = response.get('broker_order_id')
                            status = str(response.get('status')).split('.')[-1].replace("'>", "").upper() if response.get('status') else 'Unknown'
                            error_msg = response.get('error_message') or response.get('message') or 'No error message'
                            logger.error(f"💥   Broker {broker_id}: Order ID {broker_order_id}, Status: {status}, Error: {error_msg}")
                        else:
                            logger.error(f"💥   Broker {broker_id}: No response data available")
            
            return None

    async def evaluate_signal(self, data, config: dict, strike: str) -> Optional[TradeSignal]:
        """
        Entry logic: Only enter on SELL signal if not immediately after a BUY-to-SELL reversal.
        Skips entry if previous candle was BUY and current is SELL (fresh reversal).
        Prevents stacking same direction trades using last signal direction tracking.
        Adds regime detection (as in option_buy) and adjusts trade params if sideways.
        """
        # Prevent duplicate entry signals for the same strike if a position is already open
        if self._positions.get(strike):
            return None
        try:
            prev = data.iloc[-2]
            curr = data.iloc[-1]
            candle_range = round(curr['high'] - curr['low'], 2)
            max_range = config.get('max_range', 100)
            logger.debug(f"Evaluating signal for {strike} at {curr.get('timestamp')}: prev={prev}, curr={curr}, candle_range={candle_range}, max_range={max_range}")
            if candle_range > max_range:
                logger.debug(
                    f"No valid signal for {strike} at {curr.get('timestamp')}: Candle range {candle_range} exceeds max {max_range} with curr high {curr['high']} and curr low {curr['low']}."
                )
                return None
            # Track signal direction logic
            curr_signal_direction = curr.get("supertrend_signal")
            last_signal_direction = self._last_signal_direction.get(strike)
            logger.debug(f"Current signal direction for {strike}: {curr_signal_direction}, Last signal direction: {last_signal_direction}")

            # Reset last_signal_direction to None if signal flipped to BUY from SELL
            if curr_signal_direction == constants.TRADE_DIRECTION_BUY and last_signal_direction == constants.TRADE_DIRECTION_SELL:
                self._last_signal_direction[strike] = None
                logger.info(
                    f"Signal flipped to BUY for {strike} at {curr.get('timestamp')}. Reset last_signal_direction to None."
                )
            # Only allow SELL entries, and prevent stacking same direction
            if (
                prev["supertrend_signal"] == constants.TRADE_DIRECTION_BUY
                and curr["supertrend_signal"] == constants.TRADE_DIRECTION_SELL
            ):
                logger.info(
                    f"Signal reversed from BUY to SELL, skipping entry due to cool-off. {strike} at {curr.get('timestamp')}"
                )
                return None
            # Prevent stacking same direction (e.g., multiple SELLs)
            if (
                curr_signal_direction == constants.TRADE_DIRECTION_SELL
                and last_signal_direction == constants.TRADE_DIRECTION_SELL
            ):
                logger.info(
                    f"Skipping signal for {strike} at {curr.get('timestamp')}: Last signal direction is also SELL, not allowing stacking same direction."
                )
                return None
            
            # Calculate threshold_entry using configured premium + max_threshold
            today_dt = get_ist_datetime()
            configured_premium = get_max_premium_from_config(config, self.symbol, today_dt)
            max_premium_selection = config.get("max_premium_selection", {})
            max_threshold = max_premium_selection.get("max_threshold", 0) if isinstance(max_premium_selection, dict) else 0
            
            if configured_premium is not None:
                threshold_entry = configured_premium + max_threshold
                logger.debug(f"Calculated threshold_entry: configured_premium={configured_premium} + max_threshold={max_threshold} = {threshold_entry} for {strike}")
            else:
                threshold_entry = 500  # Fallback value
                logger.warning(f"Could not determine configured premium for {strike}, using fallback threshold_entry={threshold_entry}")
            logger.debug(f"For Strike {strike} close={curr['close']}, vwap={curr['vwap']}, sma={curr['sma']}, threshold_entry={threshold_entry}")
            if (
                curr["supertrend_signal"] == constants.TRADE_DIRECTION_SELL
                and prev["supertrend_signal"] == constants.TRADE_DIRECTION_SELL
                and curr['close'] < curr['vwap']
                and curr['close'] < curr['sma']
                and curr['low'] > threshold_entry
            ):
                # --- Sideways regime logic ---
                sideways_enabled = config.get('sideways_trade_enabled', False)
                sideways_qty_perc = config.get('sideways_qty_percentage', 0)
                sideways_target_atr_multiplier = config.get("sideways_target_atr_multiplier", 1)
                option_type = "CE" if strike.endswith("CE") else "PE"
                trade_dict = calculate_trade(curr, data, strike, config, side=Side.SELL)
                lot_qty = trade_dict.get(constants.TRADE_KEY_LOT_QTY, 0)
                
                # Check if regime_reference is available, if not try to get it
                if not getattr(self, 'regime_reference', None):
                    logger.warning("regime_reference is empty, attempting to fetch regime reference points")
                    interval_minutes = config.get("interval_minutes", 5)
                    first_candle_time = config.get("first_candle_time", "09:15")
                    today_dt = get_ist_datetime()
                    self.regime_reference = await get_regime_reference_points(
                        self.dp,
                        self.symbol,
                        first_candle_time,
                        interval_minutes,
                        today_dt
                    )
                    logger.info(f"Regime reference points for {self.symbol}: {self.regime_reference}")
                
                # If regime_reference is still empty, skip sideways calculation
                if not getattr(self, 'regime_reference', None):
                    logger.error("regime_reference is still empty after retry, skipping sideways regime detection")
                    regime = "Unknown"
                else:
                    regime = detect_regime(
                        entry_price=trade_dict.get(constants.TRADE_KEY_ENTRY_PRICE),
                        regime_ref=getattr(self, 'regime_reference', None),
                        option_type=option_type,
                        strategy="SELL"
                    )
                
                logger.info(f"Regime detected for {strike}: {regime} (entry_price={trade_dict.get(constants.TRADE_KEY_ENTRY_PRICE)}, option_type={option_type})")
                if sideways_enabled and regime == "Sideways":
                    if sideways_qty_perc == 0:
                        logger.info(f"Sideways regime detected for {strike} at {curr.get('timestamp')}, sideways_qty_percentage is 0, skipping trade.")
                        return None
                    new_lot_qty = int(round(lot_qty * sideways_qty_perc / 100))
                    if new_lot_qty == 0:
                        logger.info(f"Sideways regime detected for {strike} at {curr.get('timestamp')}, computed lot_qty is 0, skipping trade.")
                        return None
                     # Call calculate_trade again with the configured sideways_target_atr_multiplier and new lot_qty
                    logger.debug(f"Calculating trade for {strike} with new lot_qty={new_lot_qty} and sideways_target_atr_multiplier={sideways_target_atr_multiplier}")
                    trade_dict = calculate_trade(curr, data, strike, config, side=Side.SELL, target_atr_multiplier=sideways_target_atr_multiplier)
                    trade_dict[constants.TRADE_KEY_LOT_QTY] = new_lot_qty
                    logger.info(f"Sideways regime detected for {strike} at {curr.get('timestamp')}, updating lot_qty to {new_lot_qty} ({sideways_qty_perc}% of {lot_qty}) and using target_atr_multiplier={sideways_target_atr_multiplier}")
                elif not sideways_enabled and regime == "Sideways":
                    # If sideways is not enabled, skip the trade entirely
                    logger.info(f"Sideways regime detected for {strike} at {curr.get('timestamp')}, but sideways_trade_enabled is False, skipping trade.")
                    return None
                orig_target = trade_dict.get(constants.TRADE_KEY_TARGET_PRICE)

                # Trailing stoploss logic: update target if enabled (for non-sideways regime or if config wants it)
                if config.get("trailing_stoploss", False) and regime != "sideways":
                    try:
                        atr_value = data['atr'].iloc[-1].round(2)
                        atr_mult = config.get('atr_target_multiplier', 1)
                        trade_dict[constants.TRADE_KEY_ACTUAL_TARGET] = orig_target  # Save the original target
                        trade_dict[constants.TRADE_KEY_TARGET_PRICE] = orig_target - 1 * (atr_value * (atr_mult * 5))
                        logger.debug(f"updating new target for {strike} to {trade_dict[constants.TRADE_KEY_TARGET_PRICE]}")
                    except Exception as e:
                        logger.error(f"Error updating trailing target for {strike}: {e}")
                self._positions[strike] = [{
                    'strike': strike,
                    'entry_price': trade_dict.get(constants.TRADE_KEY_ENTRY_PRICE),
                    'timestamp': curr.get('timestamp')
                }]
                self._last_signal_direction[strike] = constants.TRADE_DIRECTION_SELL
                logger.info(
                    f"🔴 Signal formed for {strike} at {curr.get('timestamp')}: Entry at {trade_dict.get(constants.TRADE_KEY_ENTRY_PRICE)} | Updated last_signal_direction to SELL | regime={regime}, lot_qty={trade_dict.get(constants.TRADE_KEY_LOT_QTY)}, target={trade_dict.get(constants.TRADE_KEY_TARGET_PRICE)}"
                )
                return TradeSignal(
                    symbol=strike,
                    side=Side.SELL,
                    price=trade_dict.get(constants.TRADE_KEY_ENTRY_PRICE),
                    signal_type=SignalType.ENTRY,
                    candle_range=trade_dict.get(constants.TRADE_KEY_CANDLE_RANGE),
                    entry_price=trade_dict.get(constants.TRADE_KEY_ENTRY_PRICE),
                    stop_loss=trade_dict.get(constants.TRADE_KEY_STOP_LOSS),
                    target_price=trade_dict.get(constants.TRADE_KEY_TARGET_PRICE),
                    signal_time=trade_dict.get(constants.TRADE_KEY_SIGNAL_TIME),
                    exit_time=trade_dict.get(constants.TRADE_KEY_EXIT_TIME),
                    exit_price=trade_dict.get(constants.TRADE_KEY_EXIT_PRICE),
                    status=trade_dict.get(constants.TRADE_KEY_STATUS),
                    reason=trade_dict.get(constants.TRADE_KEY_REASON),
                    atr=trade_dict.get(constants.TRADE_KEY_ATR),
                    signal_direction=trade_dict.get(constants.TRADE_KEY_SIGNAL_DIRECTION),
                    lot_qty=trade_dict.get(constants.TRADE_KEY_LOT_QTY),
                    side_value=Side.SELL,
                    orig_target=orig_target
                )
            else:
                logger.debug(
                    f"No valid signal formed for {strike} at candle: {curr.get('timestamp')} | last_signal_direction={last_signal_direction}, curr_signal_direction={curr_signal_direction}"
                )
        except Exception as e:
            logger.error(f"Error in evaluate_signal for {strike}: {e}")
        return None


    async def evaluate_trade_signal(self, data, config: dict, strike: str) -> Optional[TradeSignal]:
        """
        Decide whether to enter or do nothing based on the latest candle.
        Returns a TradeSignal when a signal is generated, otherwise None.
        Only entry logic is handled here; exit logic is handled by OrderMonitor.
        Uses last signal direction to prevent stacking same direction trades.
        """
        if not self._positions.get(strike):
            result = await self.evaluate_signal(data, config, strike)
            if result:
                logger.info(f"Accepted trade signal for {strike}: {result.side}")
            else:
                logger.debug(f"Skipped trade signal for {strike} due to direction logic or no valid signal.")
            return result
        else:
            logger.debug(f"Position already open for {strike}, skipping signal evaluation.")
            return None


    async def update_trailing_stoploss(self, order_row, history_df, trade_config):
        """
        Trailing stop loss logic supporting ATR or supertrend type, based on trailing_stoploss_type in config.
        For SELL trades, ATR and supertrend stops are trailed downwards.
        """
        try:
            if not trade_config.get("trailing_stoploss_enabled", False):
                return
            if history_df is None or len(history_df) < 2:
                return
            stoploss_type = str(trade_config.get("trailing_stoploss_type", "ATR")).strip().lower()
            stoploss_conf = self.indicators.get('stoploss', {})
            last_candle = history_df.iloc[-1]
            order_id = order_row.get('id')
            current_sl = order_row.get('stop_loss')
            ltp = last_candle.get('close')

            if stoploss_type == "atr":
                # Use ATR trailing stoploss for SELL
                atr_trailing_stop_multiplier = stoploss_conf.get('atr_trailing_stop_multiplier', 3)
                atr_trailing_stop_period = stoploss_conf.get('atr_trailing_stop_period', 10)
                atr_trailing_stop_buffer = stoploss_conf.get('atr_trailing_stop_buffer', 0.0)
                history_df = calculate_atr_trial_stops(history_df, atr_trailing_stop_multiplier, atr_trailing_stop_period)
                new_trail_sl = history_df.iloc[-1]['sell_stop'] + atr_trailing_stop_buffer
                new_trail_sl = round(round(new_trail_sl / 0.05) * 0.05, 2)
                # Only update if new stop is lower (for short position) and ltp < new_trail_sl
                if current_sl is not None and new_trail_sl < current_sl and ltp < new_trail_sl:
                    await self.order_manager.update_order_stop_loss_in_db(order_id, new_trail_sl)
                    logger.debug(f"Trailing stop-loss (ATR, SELL) updated in DB for order {order_id}. New SL: {new_trail_sl}")
            elif stoploss_type == "supertrend":
                # Use supertrend as trailing stoploss for SELL
                supertrend_trailing_period = stoploss_conf.get('supertrend_trailing_period', 10)
                supertrend_trailing_multiplier = stoploss_conf.get('supertrend_trailing_multiplier', 3)
                # Calculate supertrend
                st_df = calculate_supertrend(history_df.copy(), supertrend_trailing_period, supertrend_trailing_multiplier)
                new_trail_sl = st_df.iloc[-1]['supertrend']
                new_trail_sl = round(round(new_trail_sl / 0.05) * 0.05, 2)
                # Only update if new stop is lower (for short position) and ltp < new_trail_sl
                if current_sl is not None and new_trail_sl < current_sl and ltp < new_trail_sl:
                    await self.order_manager.update_order_stop_loss_in_db(order_id, new_trail_sl)
                    logger.debug(f"Trailing stop-loss (Supertrend, SELL) updated in DB for order {order_id}. New SL: {new_trail_sl}")
            else:
                logger.warning(f"Unknown trailing_stoploss_type '{stoploss_type}' for order {order_id}. Supported: ATR, supertrend.")
        except Exception as e:
            logger.error(f"Error in update_trailing_stoploss for order_id={order_row.get('id')}: {e}")

    async def evaluate_exit(self, order_row):
        """
        Evaluate exit for a given order_row.
        Exit if supertrend flips from SELL to BUY (for short trades).
        """
        try:
            strike_symbol = order_row.get('strike_symbol')
            order_id = order_row.get('id')
            if not strike_symbol:
                logger.error("evaluate_exit: Missing strike_symbol in order_row.")
                return False
            trade_config = self.trade
            # Fetch candle history for the strike
            history_dict = await fetch_instrument_history(
                self.dp,
                [strike_symbol],
                interval_minutes=trade_config.get('interval_minutes', 5),
                ins_type="",
                cache=False
            )
            history_df = history_dict.get(str(strike_symbol))
            entry_conf = self.indicators.get('entry', {})
            supertrend_period = entry_conf.get('supertrend_period', 10)
            supertrend_multiplier = entry_conf.get('supertrend_multiplier', 2)
            history_df = calculate_supertrend(history_df, supertrend_period, supertrend_multiplier)
            if history_df is None or len(history_df) < 2:
                logger.warning(f"evaluate_exit: Not enough history for {strike_symbol}.")
                return False
            # Trailing stoploss logic
            if trade_config.get("trailing_stoploss_enabled", False):
                await self.update_trailing_stoploss(order_row, history_df, trade_config)
            # Check for supertrend reversal exit (SELL to BUY)
            last_candle = history_df.iloc[-1]
            if last_candle.get('supertrend_signal') == constants.TRADE_DIRECTION_BUY:
                 # Update status to SUPERTREND_REVERSAL instead of exiting
                await self.order_manager.update_order_status_in_db(
                    order_id=order_id,
                    status=constants.TRADE_STATUS_EXIT_REVERSAL
                )
                logger.info(f"evaluate_exit: Supertrend reversal (SELL to BUY) detected for {strike_symbol}. Exit signal triggered.")
                return True
            return False
        except Exception as e:
            logger.error(f"Error in evaluate_exit for order_id={order_row.get('id')}: {e}")
            return False
        
    async def fetch_hedge_symbol(self, broker, strike, trade_config):
        """
        Identify the hedge symbol from the option chain for the given strike, based on opp_side_max_premium.

        :param broker: Broker instance.
        :param strike: The strike symbol for which to find the hedge (e.g., 'NIFTY25JUL24500CE').
        :param trade_config: Trade configuration dictionary.
        :return: The hedge symbol or None if not found.
        """
        try:
            # Use the passed strike symbol to infer option type
            opp_side = constants.OPTION_TYPE_CALL if constants.OPTION_TYPE_CALL in strike else constants.OPTION_TYPE_PUT
            max_premium = trade_config.get("opp_side_max_premium") or self.trade.get("opp_side_max_premium")
            logger.info(f"Identifying hedge symbol for {opp_side} with max premium: {max_premium}")
            # Assume broker.get_option_chain returns all options for the relevant symbol family
            option_chain_response = await self.dp.get_option_chain(strike, trade_config.get("max_strikes", 40))
            option_chain_df = pd.DataFrame(option_chain_response['data']['optionsChain'])
            # Filter for the opposite side
            hedge_options = option_chain_df[
                (option_chain_df[constants.COLUMN_OPTION_TYPE] == opp_side) &
                (pd.to_numeric(option_chain_df[constants.COLUMN_LTP], errors='coerce') <= max_premium)
            ]
            if hedge_options.empty:
                logger.warning("No suitable hedge options found.")
                return None
            # Select the closest strike price (highest LTP under max_premium)
            hedge_options[constants.COLUMN_LTP] = pd.to_numeric(
                hedge_options[constants.COLUMN_LTP], errors='coerce'
            )
            hedge_option = hedge_options.loc[hedge_options[constants.COLUMN_LTP].idxmax()]
            hedge_symbol = hedge_option[constants.COLUMN_SYMBOL]
            logger.info(f"Hedge symbol identified: {hedge_symbol}")
            return hedge_symbol
        except Exception as error:
            logger.error(f"Error fetching hedge symbol: {error}")
            return None