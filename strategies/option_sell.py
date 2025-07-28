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
from algosat.core.db import AsyncSessionLocal, get_order_by_id
from algosat.core.signal import TradeSignal, SignalType
from algosat.common.strategy_utils import (
    calculate_end_date,
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
# Import regime detection helpers (stub: as in option_buy)
try:
    from algosat.common.strategy_utils import detect_regime, get_regime_reference
except ImportError:
    # Stubs if not present
    def detect_regime(entry_price, regime_reference, option_type, trade_mode):
        return "sideways"
    def get_regime_reference(symbol, timeframe, config):
        return {}
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
from algosat.core.signal import TradeSignal, SignalType
from algosat.models.strategy_config import StrategyConfig
from algosat.core.db import AsyncSessionLocal, get_open_orders_for_symbol_and_tradeday
from algosat.core.strategy_symbol_utils import get_strategy_symbol_id
from algosat.core.db import get_open_orders_for_strategy_symbol_and_tradeday

logger = get_logger(__name__)

IDENTIFIED_STRIKES_FILE = "/opt/algosat/Files/cache/identified_strikes.json"

def ensure_cache_dir():
    cache_dir = os.path.dirname(IDENTIFIED_STRIKES_FILE)
    os.makedirs(cache_dir, exist_ok=True)

def load_identified_strikes_cache():
    ensure_cache_dir()
    if os.path.exists(IDENTIFIED_STRIKES_FILE):
        with open(IDENTIFIED_STRIKES_FILE, "r") as f:
            try:
                return json.load(f)
            except Exception:
                return {}
    return {}

def save_identified_strikes_cache(cache):
    ensure_cache_dir()
    with open(IDENTIFIED_STRIKES_FILE, "w") as f:
        json.dump(cache, f, indent=2, default=str)

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
        self._regime_reference = None

    async def ensure_broker(self):
        # No longer needed for data fetches, but keep for order placement if required
        await self.dp._ensure_broker()

    async def setup(self) -> None:
        """One-time setup: modular workflow for OptionBuy."""
        if self._strikes:
            return
        trade = self.trade
        interval_minutes = trade.get("interval_minutes", 5)
        first_candle_time = trade.get("first_candle_time", "09:15")
        max_strikes = trade.get("max_strikes", 40)
        symbol = self.symbol
        if not symbol:
            logger.error("No symbol configured for OptionBuy strategy.")
            return
        today_dt = get_ist_datetime()
        # Dynamically select max_premium (expiry_type is auto-detected inside)
        max_premium = get_max_premium_from_config(trade, symbol, today_dt)
        # 1. Wait for first candle completion
        await wait_for_first_candle_completion(interval_minutes, first_candle_time, symbol)
        # 2. Calculate first candle data using the correct trade day
        trade_day = get_trade_day(get_ist_datetime())
        # 3. Fetch option chain and identify strikes
        cache = load_identified_strikes_cache()
        cache_key = f"{symbol}_{trade_day.date().isoformat()}_{interval_minutes}_{max_strikes}_{max_premium}"
        cleanup_old_strike_cache(cache, days=10)
        if cache_key in cache:
            self._strikes = cache[cache_key]
            logger.info(f"Loaded identified strikes from persistent cache: {self._strikes}")
            save_identified_strikes_cache(cache)
            return
        candle_times = calculate_first_candle_details(trade_day.date(), first_candle_time, interval_minutes)
        from_date = candle_times["from_date"]
        to_date = candle_times["to_date"]
        history_data = await fetch_option_chain_and_first_candle_history(
            self.dp, symbol, interval_minutes, max_strikes, from_date, to_date, bot_name="OptionBuy"
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
            cache[cache_key] = self._strikes
            save_identified_strikes_cache(cache)
            logger.info(f"Cached identified strikes persistently: {self._strikes}")
        if not self._strikes:
            logger.error("Failed to identify any valid strike prices. Setup failed.")
            self._setup_failed = True
        else:
            self._setup_failed = False
            logger.info(f"Selected strikes for entry: {self._strikes}")
        # Load regime reference once at setup (as in option_buy)
        try:
            self._regime_reference = get_regime_reference(self.symbol, self.timeframe, self.cfg)
            logger.info(f"Loaded regime reference for {self.symbol}: {self._regime_reference}")
        except Exception as e:
            logger.error(f"Error loading regime reference: {e}")
            self._regime_reference = None

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
            

    async def process_cycle(self) -> Optional[dict]:
        """
        Main signal evaluation cycle for OptionBuyStrategy.
        Refactored for clarity: 1) Fetch history, 2) Compute indicators, 3) Evaluate signal, 4) Place order.
        Returns order info dict if an order is placed, else None.
        """
        if getattr(self, '_setup_failed', False) or not self._strikes:
            logger.warning("process_cycle aborted: setup failed or no strikes available.")
            return None
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
                signal_payload = self.evaluate_trade_signal(data, trade_config, strike)
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
        """
        if signal_payload:
            ts = data.iloc[-1].get('timestamp', 'N/A')
            logger.info(f"Signal formed for {strike} at {ts}: {signal_payload}")
            # Fetch hedge symbol for this strike (pass strike directly)
            hedge_symbol = await self.fetch_hedge_symbol(self.order_manager.broker_manager, strike, self.trade)
            if hedge_symbol:
                logger.info(f"Hedge symbol for {strike}: {hedge_symbol}")
                hedge_signal_payload = TradeSignal(
                    symbol=hedge_symbol,
                    side="BUY",
                    signal_type=SignalType.HEDGE_ENTRY,
                    signal_time=signal_payload.signal_time,
                    signal_direction="hedge buy",
                    lot_qty=signal_payload.lot_qty,
                )
                # Build order request for hedge
                hedge_order_request = await self.order_manager.broker_manager.build_order_request_for_strategy(
                    hedge_signal_payload, self.cfg
                )
                # Place hedge order
                hedge_order_result = await self.order_manager.place_order(
                    self.cfg,
                    hedge_order_request,
                    strategy_name=None
                )
                logger.debug(f"Hedge order result for {hedge_symbol}: {hedge_order_result}")
                 # Check if any broker response is failed/cancelled/rejected
                failed_statuses = {"FAILED", "CANCELLED", "REJECTED"}
                broker_responses = hedge_order_result.get('broker_responses') if hedge_order_result else None
                any_failed = False
                if broker_responses and isinstance(broker_responses, dict):
                    statuses = [str(resp.get('status')) if resp else None for resp in broker_responses.values()]
                    statuses = [s.split('.')[-1].replace("'", "").replace(">", "").upper() if s else None for s in statuses]
                    if any(s in failed_statuses for s in statuses if s):
                        any_failed = True
                if any_failed:
                    logger.error(f"At least one hedge order broker response failed/cancelled/rejected, aborting entry. Details: {hedge_order_result}")
                    hedge_order_id = hedge_order_result.get("order_id") or hedge_order_result.get("id")
                    if hedge_order_id:
                        await self.exit_order(hedge_order_id)
                    return None

            else:
                logger.error(f"No hedge symbol found for {strike}")
                return None
            
            

            
            order_request = await self.order_manager.broker_manager.build_order_request_for_strategy(
                signal_payload, self.cfg
            )
            # Place order(s) with broker(s) via OrderManager, which handles DB updates
            result = await self.order_manager.place_order(
                self.cfg,  # config (StrategyConfig, has id)
                order_request,
                strategy_name=None
            )
            return result
        else:
            logger.debug(f"No signal for {strike} at {data.iloc[-1].get('timestamp', 'N/A')}")
            return None

    def evaluate_signal(self, data, config: dict, strike: str) -> Optional[TradeSignal]:
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
            if candle_range > max_range:
                logger.debug(
                    f"No valid signal for {strike} at {curr.get('timestamp')}: Candle range {candle_range} exceeds max {max_range} with curr high {curr['high']} and curr low {curr['low']}."
                )
                return None
            # Track signal direction logic
            curr_signal_direction = curr.get("supertrend_signal")
            last_signal_direction = self._last_signal_direction.get(strike)

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
            threshold_entry = config.get('threshold_entry', 500)
            if (
                curr["supertrend_signal"] == constants.TRADE_DIRECTION_SELL
                and prev["supertrend_signal"] == constants.TRADE_DIRECTION_SELL
                and curr['close'] < curr['vwap']
                and curr['close'] < curr['sma']
                and curr['low'] > threshold_entry
            ):
                # --- Begin regime detection logic (as in option_buy) ---
                entry_price = curr['close']
                option_type = constants.OPTION_TYPE_CALL if "CE" in strike else constants.OPTION_TYPE_PUT
                # Use cached regime_reference if available
                regime_reference = getattr(self, "_regime_reference", None)
                if not regime_reference:
                    try:
                        regime_reference = get_regime_reference(self.symbol, self.timeframe, self.cfg)
                        self._regime_reference = regime_reference
                    except Exception as e:
                        logger.error(f"Could not compute regime_reference: {e}")
                        regime_reference = {}
                sideways_enabled = config.get('sideways_trade_enabled', False)
                sideways_qty_perc = config.get('sideways_qty_percentage', 0)
                option_type = "CE" if strike.endswith("CE") else "PE"
                trade_dict = calculate_trade(curr, data, strike, config, side=Side.BUY)
                lot_qty = trade_dict.get(constants.TRADE_KEY_LOT_QTY, 0)
                regime = detect_regime(entry_price, regime_reference, option_type, "SELL")
                logger.info(f"Regime detected for {strike}: {regime} (entry_price={entry_price}, option_type={option_type})")
                if sideways_enabled and regime == "Sideways":
                    if sideways_qty_perc == 0:
                        logger.info(f"Sideways regime detected for {strike} at {curr.get('timestamp')}, sideways_qty_percentage is 0, skipping trade.")
                        return None
                    new_lot_qty = int(round(lot_qty * sideways_qty_perc / 100))
                    if new_lot_qty == 0:
                        logger.info(f"Sideways regime detected for {strike} at {curr.get('timestamp')}, computed lot_qty is 0, skipping trade.")
                        return None
                    # Call calculate_trade again with target_atr_multiplier=1 and new lot_qty
                    trade_dict = calculate_trade(curr, data, strike, config, side=Side.SELL, target_atr_multiplier=1)
                    trade_dict[constants.TRADE_KEY_LOT_QTY] = new_lot_qty
                    logger.info(f"Sideways regime detected for {strike} at {curr.get('timestamp')}, updating lot_qty to {new_lot_qty} ({sideways_qty_perc}% of {lot_qty}) and using target_atr_multiplier=1")
                
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
                    f"🔴 Signal formed for {strike} at {curr.get('timestamp')}: Entry at {trade_dict.get(constants.TRADE_KEY_ENTRY_PRICE)} | Updated last_signal_direction to SELL | regime={regime}, lot_qty={adjusted_qty}, target={trade_dict.get(constants.TRADE_KEY_TARGET_PRICE)}"
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


    def evaluate_trade_signal(self, data, config: dict, strike: str) -> Optional[TradeSignal]:
        """
        Decide whether to enter or do nothing based on the latest candle.
        Returns a TradeSignal when a signal is generated, otherwise None.
        Only entry logic is handled here; exit logic is handled by OrderMonitor.
        Uses last signal direction to prevent stacking same direction trades.
        """
        if not self._positions.get(strike):
            result = self.evaluate_signal(data, config, strike)
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
            option_chain_response = await broker.get_option_chain(strike, trade_config.get("max_strikes", 40))
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