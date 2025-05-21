from datetime import datetime, time, timedelta
from typing import Any, Optional

from .base import StrategyBase
from common.logger import get_logger
from core.execution_manager import ExecutionManager
from core.data_manager import DataManager
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
    calculate_trade,
)
from utils.indicators import (
    calculate_supertrend,
    calculate_atr,
    calculate_sma,
    calculate_vwap,
)
from core.time_utils import get_ist_datetime
from common.broker_utils import get_trade_day
from common import constants
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

    def __init__(self, config: dict, data_manager: DataManager, execution_manager: Any):
        super().__init__(config, data_manager, execution_manager)
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
        # await wait_for_first_candle_completion(interval_minutes, first_candle_time, symbol)
        # 2. Calculate first candle data using the correct trade day
        trade_day = get_trade_day(get_ist_datetime()) - timedelta(days=1)
        # 3. Fetch option chain and identify strikes
        cache = load_identified_strikes_cache()
        cache_key = f"{symbol}_{trade_day.date().isoformat()}_{interval_minutes}_{max_strikes}_{max_premium}"
        cleanup_old_strike_cache(cache, days=1)
        if cache_key in cache:
            self._strikes = cache[cache_key]
            logger.debug(f"Loaded identified strikes from persistent cache: {self._strikes}")
            save_identified_strikes_cache(cache)
            return
        candle_times = calculate_first_candle_details(trade_day.date(), first_candle_time, interval_minutes)
        from_date = candle_times["from_date"]
        to_date = candle_times["to_date"]
        # await self.ensure_broker()  # Only for order placement, not for data fetch
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
        Refactored for clarity: 1) Fetch history, 2) Compute indicators, 3) Evaluate signal, 4) Place order.
        """
        if getattr(self, '_setup_failed', False) or not self._strikes:
            logger.warning("process_cycle aborted: setup failed or no strikes available.")
            return
        trade_config = self.trade
        interval_minutes = trade_config.get('interval_minutes', 5)
        trade_day = get_trade_day(get_ist_datetime()) - timedelta(days=1)
        # 1. Fetch history for all strikes
        history_data = await self.fetch_history_data(
            self.dp, self._strikes, trade_day, trade_config
        )
        if not history_data or all(h is None or getattr(h, 'empty', False) for h in history_data.values()):
            logger.warning("No history data received for strikes. Skipping signal evaluation.")
            return
        # 2. Compute indicators for each strike
        indicator_data = {
            strike: self.compute_indicators(data, trade_config, strike)
            for strike, data in history_data.items()
            if data is not None and not getattr(data, 'empty', False)
        }
        # 3. Evaluate trade signal for each strike
        for strike, data in indicator_data.items():
            try:
                signal_payload = self.evaluate_trade_signal(data, trade_config, strike)
                # 4. Place order if signal
                await self.place_order(signal_payload, data, strike)
            except Exception as e:
                logger.error(f"Error during signal evaluation or order for {strike}: {e}")

    async def fetch_history_data(self, broker, strike_symbols, current_date, trade_config: dict):
        """
        Fetch candle data for the given strike symbols.
        Split out for clarity and easier backtest override.
        """
        try:
            back_days = calculate_backdate_days(trade_config['interval_minutes'])
            trade_day = get_trade_day(current_date - timedelta(days=back_days))
            start_date = datetime.combine(trade_day, time(9, 15))
            current_end_date = datetime.combine(localize_to_ist(current_date),
                                                get_ist_datetime().time())
            end_date = calculate_end_date(current_end_date,
                                          trade_config['interval_minutes'])
            end_date = end_date.replace(hour=10, minute=20, second=0, microsecond=0)
            logger.info(f"Fetching history for strike symbols {', '.join(str(strike) for strike in strike_symbols)}...")
            history_data = await fetch_strikes_history(
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

    def compute_indicators(self, data, trade_config, strike):
        """
        Compute all indicators on the DataFrame for a given strike.
        Returns the updated DataFrame.
        """
        try:
            data = calculate_supertrend(data, trade_config.get('supertrend_period', 10), trade_config.get('supertrend_multiplier', 2))
            data = calculate_atr(data, trade_config.get('atr_multiplier', 10))
            data = calculate_sma(data, trade_config.get('sma_period', 25))
            data = calculate_vwap(data)
        except Exception as e:
            logger.error(f"Error calculating indicators for {strike}: {e}")
        return data

    async def place_order(self, signal_payload, data, strike):
        """
        Place order using execution manager if there is a valid signal.
        Overridable for live or backtest order manager.
        """
        if signal_payload:
            ts = data.iloc[-1].get('timestamp', 'N/A')
            logger.info(f"Signal formed for {strike} at {ts}: {signal_payload}")
            await self.em.execute(self.config, signal_payload)
        else:
            logger.debug(f"No signal for {strike} at {data.iloc[-1].get('timestamp', 'N/A')}")

    def evaluate_trade_signal(self, data, config: dict, strike: str) -> Optional[dict]:
        """
        Decide whether to enter, exit, or do nothing based on the latest candle.
        Returns a trade payload dict when a signal is generated, otherwise None.
        """
        # If not in a position, check entry conditions
        if self._position is None:
            return self.evaluate_signal(data, config, strike)
        # If in a position, check exit conditions
        else:
            return self.evaluate_exit(data, config, strike)

    def evaluate_signal(self, data, config: dict, strike: str) -> Optional[dict]:
        """
        Entry logic: Only enter on BUY signal if not immediately after a SELL-to-BUY reversal.
        Skips entry if previous candle was SELL and current is BUY (fresh reversal).
        """
        if self._position is not None:
            return None
        try:
            prev = data.iloc[-2]
            curr = data.iloc[-1]

            # Calculate candle range and check max_range
            candle_range = round(curr['high'] - curr['low'], 2)
            max_range = config.get('max_range', 100)  # Default to 100 if not set
            if candle_range > max_range:
                logger.debug(
                    f"No valid signal for {strike} at {curr.get('timestamp')}: Candle range {candle_range} exceeds max {max_range}."
                )
                return None

            # Cool-off logic: skip entry on fresh SELL-to-BUY reversal
            if (
                prev["supertrend_signal"] == constants.TRADE_DIRECTION_SELL
                and curr["supertrend_signal"] == constants.TRADE_DIRECTION_BUY
            ):
                logger.info(
                    f"Signal reversed from SELL to BUY, skipping entry due to cool-off. {strike} at {curr.get('timestamp')}"
                )
                return None

            # Only enter if current and previous candle are both BUY
            if (
                curr["supertrend_signal"] == constants.TRADE_DIRECTION_BUY
                and prev["supertrend_signal"] == constants.TRADE_DIRECTION_BUY
                and curr['close'] > curr['vwap']
                and curr['close'] > curr['sma']
                and curr['high'] < 500
            ):
                trade_dict = calculate_trade(curr, data, strike, config, side=1)
                self._position = {
                    'strike': strike,
                    'entry_price': trade_dict.get(constants.TRADE_KEY_ENTRY_PRICE),
                    'timestamp': curr.get('timestamp')
                }
                logger.info(f"🟢 Signal formed for {strike} at {curr.get('timestamp')}: Entry at {trade_dict.get(constants.TRADE_KEY_ENTRY_PRICE)}")
                return trade_dict
            else:
                logger.debug(
                    f"No valid signal formed for {strike} at candle: {curr.get('timestamp')}"
                )
        except Exception as e:
            logger.error(f"Error in evaluate_signal for {strike}: {e}")
        return None

    def evaluate_exit(self, data, config: dict, strike: str) -> Optional[dict]:
        """
        Exit logic: trigger on Supertrend flip down, stoploss, or target hit.
        :param data: DataFrame with historical and latest candle data.
        :param config: Dict containing strategy configuration.
        :param strike: The strike identifier to evaluate.
        :return: Trade payload dict if exit signal, else None.
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