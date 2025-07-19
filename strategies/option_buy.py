from datetime import datetime, time, timedelta
from typing import Any, Optional
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
from algosat.utils.indicators import (
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

class OptionBuyStrategy(StrategyBase):
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
        # await wait_for_first_candle_completion(interval_minutes, first_candle_time, symbol)
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

    async def sync_open_positions(self):
        """
        Synchronize self._positions with open orders in the database for all strikes for the current trade day.
        Uses the strategy_id from config to find related strategy_symbols and their open orders.
        Now uses the strike_symbol field directly from orders table instead of joining with strategy_symbols.
        """
        self._positions = {}
        async with AsyncSessionLocal() as session:
            from algosat.core.db import get_open_orders_for_strategy_and_tradeday
            
            trade_day = get_trade_day(get_ist_datetime())
            strategy_id = getattr(self.cfg, 'strategy_id', None)
            
            if not strategy_id:
                logger.warning("No strategy_id found in config, cannot sync open positions")
                return
            
            # Get all open orders for this strategy on the current trade day
            open_orders = await get_open_orders_for_strategy_and_tradeday(session, strategy_id, trade_day)
            
            # Group orders by strike symbol (now direct from orders.strike_symbol)
            for order in open_orders:
                strike_symbol = order.get("strike_symbol")
                if strike_symbol and strike_symbol in self._strikes:
                    if strike_symbol not in self._positions:
                        self._positions[strike_symbol] = []
                    self._positions[strike_symbol].append(order)
            
            logger.debug(f"Synced positions for strategy {strategy_id}: {list(self._positions.keys())}")

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
        # 2. Compute indicators for each strike
        indicator_data = {
            strike: self.compute_indicators(data, trade_config, strike)
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
        """
        if signal_payload:
            ts = data.iloc[-1].get('timestamp', 'N/A')
            logger.info(f"Signal formed for {strike} at {ts}: {signal_payload}")
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
        Entry logic: Only enter on BUY signal if not immediately after a SELL-to-BUY reversal.
        Skips entry if previous candle was SELL and current is BUY (fresh reversal).
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
            if (
                prev["supertrend_signal"] == constants.TRADE_DIRECTION_SELL
                and curr["supertrend_signal"] == constants.TRADE_DIRECTION_BUY
            ):
                logger.info(
                    f"Signal reversed from SELL to BUY, skipping entry due to cool-off. {strike} at {curr.get('timestamp')}"
                )
                return None
            logger.info(f"Threshold Entry: {config.get('threshold_entry', 500)}")
            if (
                curr["supertrend_signal"] == constants.TRADE_DIRECTION_BUY
                and prev["supertrend_signal"] == constants.TRADE_DIRECTION_BUY
                and curr['close'] > curr['vwap']
                and curr['close'] > curr['sma']
                and curr['high'] < 500
            ):
                trade_dict = calculate_trade(curr, data, strike, config, side=Side.BUY)
                # When signal is formed:
                self._positions[strike] = [{
                    'strike': strike,
                    'entry_price': trade_dict.get(constants.TRADE_KEY_ENTRY_PRICE),
                    'timestamp': curr.get('timestamp')
                }]
                logger.info(f"🟢 Signal formed for {strike} at {curr.get('timestamp')}: Entry at {trade_dict.get(constants.TRADE_KEY_ENTRY_PRICE)}")
                return TradeSignal(
                    symbol=strike,
                    side=trade_dict.get('side', Side.BUY),
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
                    side_value=trade_dict.get(constants.TRADE_KEY_SIDE)
                )
            else:
                logger.debug(
                    f"No valid signal formed for {strike} at candle: {curr.get('timestamp')}"
                )
        except Exception as e:
            logger.error(f"Error in evaluate_signal for {strike}: {e}")
        return None

    def evaluate_exit(self, trade: dict, candle: dict, current_signal_direction: str) -> Optional[TradeSignal]:
        """
        Evaluate exit conditions for an open trade, similar to evaluate_exit_conditions.
        Updates the in-memory trade dict and returns a TradeSignal if an exit is triggered.
        """
        strike_symbol = trade.get(constants.COLUMN_SYMBOL)
        # 1. Reversal exit
        if current_signal_direction == constants.TRADE_DIRECTION_SELL:
            if trade.get(constants.TRADE_KEY_STATUS) in [
                constants.TRADE_STATUS_EXIT_REVERSAL,
                constants.TRADE_STATUS_EXIT_STOPLOSS,
                constants.TRADE_STATUS_EXIT_TARGET,
                constants.TRADE_STATUS_ORDER_FAILED
            ]:
                return None
            logger.debug(f"{strike_symbol} | {constants.SIGNAL_REVERSED_MESSAGE}. Candle: {str(candle[constants.COLUMN_TIMESTAMP])}")
            trade[constants.TRADE_KEY_EXIT_PRICE] = candle[constants.COLUMN_CLOSE]
            trade[constants.TRADE_KEY_EXIT_TIME] = candle[constants.COLUMN_TIMESTAMP]
            trade[constants.TRADE_KEY_STATUS] = constants.TRADE_STATUS_EXIT_REVERSAL
            trade[constants.TRADE_KEY_REASON] = constants.TRADE_SIGNAL_REVERSED_EXIT
            return TradeSignal(
                symbol=strike_symbol,
                side=Side.SELL,
                price=candle[constants.COLUMN_CLOSE],
                signal_type=SignalType.REVERSAL,
                exit_time=candle[constants.COLUMN_TIMESTAMP],
                reason=constants.TRADE_SIGNAL_REVERSED_EXIT
            )
        # 2. Stop-loss exit
        if candle[constants.COLUMN_LOW] <= trade.get(constants.TRADE_KEY_STOP_LOSS, float('-inf')):
            if trade.get(constants.TRADE_KEY_STATUS) == constants.TRADE_STATUS_AWAITING_ENTRY:
                logger.debug(f"Ignore stoploss checking for {trade.get(constants.TRADE_KEY_SYMBOL, '')}")
                return None
            logger.debug(f"{strike_symbol} | {constants.STOPLOSS_HIT_MESSAGE}. Candle: {str(candle[constants.COLUMN_TIMESTAMP])}")
            trade[constants.TRADE_KEY_EXIT_PRICE] = trade.get(constants.TRADE_KEY_STOP_LOSS)
            trade[constants.TRADE_KEY_EXIT_TIME] = candle[constants.COLUMN_TIMESTAMP]
            trade[constants.TRADE_KEY_STATUS] = constants.TRADE_STATUS_EXIT_STOPLOSS
            trade[constants.TRADE_KEY_REASON] = constants.TRADE_REASON_STOPLOSS_HIT
            return TradeSignal(
                symbol=strike_symbol,
                side=Side.SELL,
                price=trade.get(constants.TRADE_KEY_STOP_LOSS),
                signal_type=SignalType.STOPLOSS,
                exit_time=candle[constants.COLUMN_TIMESTAMP],
                reason=constants.TRADE_REASON_STOPLOSS_HIT
            )
        # 3. Target exit
        if candle[constants.COLUMN_HIGH] >= trade.get(constants.TRADE_KEY_TARGET_PRICE, float('inf')):
            if trade.get(constants.TRADE_KEY_STATUS) in [
                constants.TRADE_STATUS_EXIT_REVERSAL,
                constants.TRADE_STATUS_EXIT_STOPLOSS,
                constants.TRADE_STATUS_EXIT_TARGET,
                constants.TRADE_STATUS_ORDER_FAILED
            ]:
                return None
            logger.debug(f"{strike_symbol} | {constants.TARGET_HIT_MESSAGE}. Candle: {str(candle[constants.COLUMN_TIMESTAMP])}")
            trade[constants.TRADE_KEY_EXIT_PRICE] = trade.get(constants.TRADE_KEY_TARGET_PRICE)
            trade[constants.TRADE_KEY_EXIT_TIME] = candle[constants.COLUMN_TIMESTAMP]
            trade[constants.TRADE_KEY_STATUS] = constants.TRADE_STATUS_EXIT_TARGET
            trade[constants.TRADE_KEY_REASON] = constants.TRADE_REASON_TARGET_HIT
            return TradeSignal(
                symbol=strike_symbol,
                side=Side.SELL,
                price=trade.get(constants.TRADE_KEY_TARGET_PRICE),
                signal_type=SignalType.TRAIL,
                exit_time=candle[constants.COLUMN_TIMESTAMP],
                reason=constants.TRADE_REASON_TARGET_HIT
            )
        return None

    def evaluate_trade_signal(self, data, config: dict, strike: str) -> Optional[TradeSignal]:
        """
        Decide whether to enter or do nothing based on the latest candle.
        Returns a TradeSignal when a signal is generated, otherwise None.
        Only entry logic is handled here; exit logic is handled by OrderMonitor.
        """
        if not self._positions.get(strike):
            return self.evaluate_signal(data, config, strike)
        else:
            return None

    async def evaluate_price_exit(self, parent_order_id: int, last_price: float):
        """
        Exit based on last price hitting stop_loss or target_price stored in DB.
        """
        async with AsyncSessionLocal() as session:
            order = await get_order_by_id(session, parent_order_id)
        stop_loss = order.get("stop_loss")
        target_price = order.get("target_price")
        symbol = order.get("symbol")
        if stop_loss is not None and last_price <= stop_loss:
            ts = TradeSignal(
                symbol=symbol,
                side=Side.SELL,
                price=stop_loss,
                signal_type=SignalType.STOPLOSS
            )
            return await self.order_manager.broker_manager.build_order_request_for_strategy(ts, self.cfg)
        if target_price is not None and last_price >= target_price:
            ts = TradeSignal(
                symbol=symbol,
                side=Side.SELL,
                price=target_price,
                signal_type=SignalType.TRAIL
            )
            return await self.order_manager.broker_manager.build_order_request_for_strategy(ts, self.cfg)
        return None

    async def evaluate_candle_exit(self, parent_order_id: int, history: dict):
        """
        Exit based on candle history: uses existing evaluate_exit logic.
        """
        # Determine strike from in-memory position
        strike = self._position.get('strike') if self._position else None
        if not strike:
            return None
        df = history.get(strike)
        if df is None or len(df) < 2:
            return None
        tsignal = self.evaluate_exit(df, self.trade, strike)
        if tsignal:
            return await self.order_manager.broker_manager.build_order_request_for_strategy(tsignal, self.cfg)
        return None

    def update_trailing_stop_loss(self, order_id: int, ltp: float, history: dict, order_manager=None):
        """
        ATR-based trailing stop loss logic. Updates stop_loss in DB if new stop is higher (for long positions).
        Only updates if trailing_stoploss is enabled in the config.
        Args:
            order_id: The order ID to update.
            ltp: Latest traded price.
            history: Candle/history data for the symbol.
            order_manager: OrderManager instance (required for DB update).
        """
        try:
            trade_config = self.trade
            if not trade_config.get("trailing_stoploss", False):
                return
            if not history:
                return
            # Use the latest candle for trailing logic
            symbol = None
            for k in history:
                if history[k] is not None and len(history[k]) > 0:
                    symbol = k
                    break
            if not symbol:
                return
            df = history[symbol]
            if len(df) < 2:
                return
            last_candle = df.iloc[-1]
            atr = last_candle.get('atr')
            if atr is None:
                return
            trail_atr_mult = trade_config.get('trail_atr_mult', 2)
            new_trail_sl = last_candle['close'] - atr * trail_atr_mult
            new_trail_sl = round(round(new_trail_sl / 0.05) * 0.05, 2)
            import asyncio
            async def update_db():
                async with AsyncSessionLocal() as session:
                    order = await get_order_by_id(session, order_id)
                    current_sl = order.get('stop_loss') if order else None
                    # Only update if new stop is higher (for long)
                    if current_sl is not None and new_trail_sl > current_sl and ltp > new_trail_sl:
                        if order_manager:
                            await order_manager.update_order_stop_loss_in_db(order_id, new_trail_sl)
                        logger.debug(f"Trailing stop-loss updated in DB for order {order_id}. New SL: {new_trail_sl}")
            asyncio.create_task(update_db())
        except Exception as e:
            logger.error(f"Error in update_trailing_stop_loss for order_id={order_id}: {e}")