from datetime import datetime, time, timedelta
from typing import Any, Optional

from .base import StrategyBase
from common.logger import get_logger
from core.execution_manager import ExecutionManager
from core.data_provider.provider import DataProvider
from core.dbschema import strategy_configs
from common.strategy_utils import (
    calculate_end_date,
    wait_for_first_candle_completion,
    calculate_first_candle_details,
    fetch_option_chain_and_first_candle_history,
    identify_strike_price_combined,
    fetch_strikes_history,
    # evaluate_signals, evaluate_trade_signal  # removed, now in-class
    calculate_backdate_days,
    localize_to_ist,
    calculate_supertrend,
    calculate_atr,
    calculate_sma,
)
from core.time_utils import get_ist_datetime
from common.broker_utils import get_trade_day

import json
import os

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

class OptionBuyStrategy(StrategyBase):
    """
    Concrete implementation of the Option Buy strategy.
    Fetches option chain at setup, picks strikes by premium threshold,
    then on each tick evaluates entry and exit signals.
    """

    def __init__(self, config: dict, data_provider: DataProvider, execution_manager: ExecutionManager):
        super().__init__(config, data_provider, execution_manager)
        trade = self.trade
        self.start_time = None
        self.end_time = None
        self.premium = trade.get("premium", 100)
        self.quantity = trade.get("quantity", 1)
        self.strike_count = trade.get("strike_count", 20)
        # Internal state
        self._strikes = []         # Selected strikes after setup()
        self._position = None      # Track current open position, if any
        self._setup_failed = False # Track if setup failed

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
        max_premium = trade.get("max_premium", 200)
        symbol = self.symbol
        if not symbol:
            logger.error("No symbol configured for OptionBuy strategy.")
            return
        # 1. Wait for first candle completion
        await wait_for_first_candle_completion(interval_minutes, first_candle_time, symbol)
        # 2. Calculate first candle data using the correct trade day
        trade_day = get_trade_day(get_ist_datetime())
        cache = load_identified_strikes_cache()
        cache_key = f"{symbol}_{trade_day.date().isoformat()}_{interval_minutes}_{max_strikes}_{max_premium}"
        cleanup_old_strike_cache(cache, days=1)
        if cache_key in cache:
            self._strikes = cache[cache_key]
            logger.info(f"Loaded identified strikes from persistent cache: {self._strikes}")
            save_identified_strikes_cache(cache)
            return
        candle_times = calculate_first_candle_details(trade_day.date(), first_candle_time, interval_minutes)
        from_date = candle_times["from_date"]
        to_date = candle_times["to_date"]
        await self.ensure_broker()  # Only for order placement, not for data fetch
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

    async def process_cycle(self) -> None:
        """
        Main signal evaluation cycle for OptionBuyStrategy.
        1. If setup failed or no strikes, do not proceed.
        2. If strikes available, fetch history for those strikes for the correct date range.
        3. Calculate indicators and evaluate trade signals for each strike.
        """
        if getattr(self, '_setup_failed', False) or not self._strikes:
            logger.warning("process_cycle aborted: setup failed or no strikes available.")
            return
        if 'trade' not in self.config:
            logger.error("Missing 'trade' section in config. Aborting process_cycle.")
            return
        trade_config = self.config['trade']
        interval_minutes = trade_config.get('interval_minutes', 5)
        trade_day = get_trade_day(get_ist_datetime())
        # Use fetch_live_candle_data to get history for all strikes
        history_data_list = await self.fetch_live_candle_data(
            self.dp, self._strikes, trade_day, trade_config
        )
        if not history_data_list or all(h is None for h in history_data_list):
            logger.warning("No history data received for strikes. Skipping signal evaluation.")
            return
        # Map strike to its history for easy lookup
        strike_to_history = dict(zip(self._strikes, history_data_list))
        for strike in self._strikes:
            data = strike_to_history.get(strike)
            if data is None or data.empty:
                logger.warning(f"No data for strike {strike}, skipping.")
                continue
            # Calculate indicators: supertrend, atr, ema
            try:
                data = calculate_supertrend(data, trade_config.get('supertrend_period', 10), trade_config.get('supertrend_multiplier', 3))
                data = calculate_atr(data, trade_config.get('atr_multiplier', 1.5))
                data = calculate_sma(data, trade_config.get('ema_period', 21))
            except Exception as e:
                logger.error(f"Error calculating indicators for {strike}: {e}")
                continue
            # Generate entry/exit signal for this candle
            try:
                signal_payload = self.evaluate_trade_signal(latest_candle := data.iloc[-1], data, trade_config, strike)
                if signal_payload:
                    ts = latest_candle.get('timestamp', 'N/A')
                    logger.info(f"Signal formed for {strike} at {ts}: {signal_payload}")
                    await self.em.execute(self.config, signal_payload)
                else:
                    logger.debug(f"No signal for {strike} at {latest_candle.get('timestamp', 'N/A')}")
            except Exception as e:
                logger.error(f"Error during signal evaluation for {strike}: {e}")

    async def fetch_live_candle_data(self, broker, strike_symbols, current_date, trade_config: dict):
        """
        Fetch live candle data for the given strike symbols.

        :param current_date: The date for which the trade gonna processed
        :param trade_config: Dict containing trade configuration details
        :param broker: Broker instance.
        :param strike_symbols: List of strike symbols to fetch data for.
        :return: List of DataFrames with live candle data.
        """
        try:
            # Calculate start and end dates for history fetch
            back_days = calculate_backdate_days(trade_config['interval_minutes'])
            trade_day = get_trade_day(current_date - timedelta(days=back_days))
            start_date = datetime.combine(trade_day, time(9, 15))
            current_end_date = datetime.combine(localize_to_ist(current_date),
                                                get_ist_datetime().time())
            end_date = calculate_end_date(current_end_date,
                                          trade_config['interval_minutes'])  # Current trading day until the market close

            # Fetch history for all necessary dates
            logger.info(f"Fetching history for strike symbols {strike_symbols}...")
        
            history_data = await fetch_strikes_history(
            self.dp,
            self._strikes,
            from_date=start_date,
            to_date=end_date,
            interval_minutes=trade_config['interval_minutes'],
            ins_type="EQ"
        )

            return history_data
        except Exception as error:
            logger.error(f"Error fetching live candle data: {error}")
            return []

    def evaluate_trade_signal(self, latest_candle: dict, data, config: dict, strike: str) -> Optional[dict]:
        """
        Decide whether to enter, exit, or do nothing based on the latest candle.
        Returns a trade payload dict when a signal is generated, otherwise None.
        """
        # If not in a position, check entry conditions
        if self._position is None:
            return self.evaluate_signal(latest_candle, data, config, strike)
        # If in a position, check exit conditions
        else:
            return self.evaluate_exit(latest_candle, data, config, strike)

    def evaluate_signal(self, latest_candle, data, config: dict, strike: str) -> Optional[dict]:
        """
        Entry logic: trigger when Supertrend flips from down to up.
        """
        if self._position is not None:
            return None
        try:
            prev = data.iloc[-2]
            curr = data.iloc[-1]
            # Supertrend uptrend flag (assumes calculate_supertrend added 'in_uptrend')
            if not prev['in_uptrend'] and curr['in_uptrend']:
                entry_price = curr['close']
                # Record position details
                self._position = {
                    'strike': strike,
                    'entry_price': entry_price,
                    'timestamp': curr.get('timestamp')
                }
                return {
                    'action': 'BUY',
                    'symbol': self.symbol,
                    'strike': strike,
                    'quantity': self.quantity,
                    'order_type': config.get('order_type', 'MARKET'),
                    'product_type': config.get('product_type', 'INTRADAY'),
                    'price': entry_price
                }
        except Exception as e:
            logger.error(f"Error in evaluate_signal for {strike}: {e}")
        return None

    def evaluate_exit(self, latest_candle, data, config: dict, strike: str) -> Optional[dict]:
        """
        Exit logic: trigger on Supertrend flip down, stoploss, or target hit.
        """
        if self._position is None:
            return None
        try:
            prev = data.iloc[-2]
            curr = data.iloc[-1]
            # 1) Supertrend reversal down
            if prev.get('in_uptrend') and not curr.get('in_uptrend'):
                exit_price = curr['close']
                self._position = None
                return {
                    'action': 'SELL',
                    'symbol': self.symbol,
                    'strike': strike,
                    'quantity': self.quantity,
                    'order_type': config.get('order_type', 'MARKET'),
                    'product_type': config.get('product_type', 'INTRADAY'),
                    'price': exit_price
                }
            # 2) Stoploss (percent-based)
            entry_price = self._position.get('entry_price', 0)
            max_loss_pct = config.get('max_loss_percentage', 25)
            stoploss_price = entry_price * (1 - max_loss_pct / 100)
            if curr['low'] <= stoploss_price:
                self._position = None
                return {
                    'action': 'SELL',
                    'symbol': self.symbol,
                    'strike': strike,
                    'quantity': self.quantity,
                    'order_type': config.get('order_type', 'MARKET'),
                    'product_type': config.get('product_type', 'INTRADAY'),
                    'price': stoploss_price
                }
            # 3) Target (ATR-based)
            atr_multiplier = config.get('atr_target_multiplier', 3)
            target_price = entry_price + curr.get('atr', 0) * atr_multiplier
            if curr['high'] >= target_price:
                self._position = None
                return {
                    'action': 'SELL',
                    'symbol': self.symbol,
                    'strike': strike,
                    'quantity': self.quantity,
                    'order_type': config.get('order_type', 'MARKET'),
                    'product_type': config.get('product_type', 'INTRADAY'),
                    'price': target_price
                }
        except Exception as e:
            logger.error(f"Error in evaluate_exit for {strike}: {e}")
        return None