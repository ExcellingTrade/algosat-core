from datetime import datetime, time, timedelta
from typing import Any, Optional
from algosat.core.signal import TradeSignal
import pandas as pd
from algosat.common import constants, strategy_utils
from algosat.common.broker_utils import calculate_backdate_days, get_trade_day
from algosat.common.strategy_utils import calculate_end_date
from algosat.core.data_manager import DataManager
from algosat.core.order_manager import OrderManager
from algosat.core.time_utils import localize_to_ist, get_ist_datetime, to_ist
from algosat.strategies.base import StrategyBase
from algosat.common.logger import get_logger
from algosat.common import swing_utils
import asyncio

logger = get_logger(__name__)

def get_nse_holidays():
    """Get NSE holiday list - fallback implementation"""
    try:
        # Try to import from the actual location first
        from algosat.api.routes.nse_data import get_nse_holiday_list
        return get_nse_holiday_list()
    except ImportError:
        # Fallback to basic weekend check
        logger.warning("NSE holiday data not available, using basic weekend check")
        return []

def is_holiday_or_weekend(check_date):
    """
    Check if given date is a holiday or weekend.
    """
    try:
        # Check weekend (Saturday = 5, Sunday = 6)
        if check_date.weekday() >= 5:
            return True
        
        # Check holidays
        holidays = get_nse_holidays()
        return check_date.date() if hasattr(check_date, 'date') else check_date in holidays
    except Exception as e:
        logger.error(f"Error checking holiday/weekend: {e}")
        return False

class SwingHighLowSellStrategy(StrategyBase):

    async def sync_open_positions(self):
        """
        Synchronize self._positions with open orders in the database for this strategy for the current trade day.
        Uses the strategy_id from config to find related open orders.
        """
        self._positions = {}
        from algosat.core.db import get_open_orders_for_strategy_and_tradeday
        from algosat.core.db import AsyncSessionLocal
        trade_day = get_trade_day(get_ist_datetime())
        strategy_id = getattr(self.cfg, 'strategy_id', None)
        if not strategy_id:
            logger.warning("No strategy_id found in config, cannot sync open positions")
            return
        async with AsyncSessionLocal() as session:
            open_orders = await get_open_orders_for_strategy_and_tradeday(session, strategy_id, trade_day)
            for order in open_orders:
                symbol = order.get("strike_symbol")
                if symbol:
                    if symbol not in self._positions:
                        self._positions[symbol] = []
                    self._positions[symbol].append(order)
            logger.debug(f"Synced positions for strategy {strategy_id}: {list(self._positions.keys())}")
    """
    Concrete implementation of a Swing High/Low breakout SELL strategy.
    Modularized and standardized to match option_buy.py structure.
    This strategy sells options (PE/CE) on swing high/low breakouts using a dual timeframe approach.
    """
    def __init__(self, config, data_manager: DataManager, execution_manager: OrderManager):
        super().__init__(config, data_manager, execution_manager)
        # Standardized config/state
        self.symbol = self.cfg.symbol
        self.exchange = self.cfg.exchange
        self.instrument = self.cfg.instrument
        self.trade = self.cfg.trade
        self.indicators = self.cfg.indicators
        self.order_manager = execution_manager
        # Internal state
        self._strikes = []  # Not used for spot, but kept for interface parity
        self._positions = {}  # open positions by strike
        self._setup_failed = False
        self._hh_levels = []
        self._ll_levels = []
        self._pending_signal = None  # Dict with 'breakout_price', 'breakout_time'
        self._pending_signal_confirm_until = None  # Timestamp until which confirmation window ends
        # Config fields modularized
        self._entry_cfg = self.trade.get("entry", {})
        self._stoploss_cfg = self.trade.get("stoploss", {})
        self._confirm_cfg = self.trade.get("confirmation", {})
        self.entry_timeframe = self._entry_cfg.get("timeframe", "5m")
        self.entry_minutes = int(self.entry_timeframe.replace("m", "")) if self.entry_timeframe.endswith("m") else 5
        self.stoploss_timeframe = self._stoploss_cfg.get("timeframe", "5m")
        self.stoploss_minutes = int(self.stoploss_timeframe.replace("m", "")) if self.stoploss_timeframe.endswith("m") else 5
        self.entry_swing_left_bars = self._entry_cfg.get("swing_left_bars", 3)
        self.entry_swing_right_bars = self._entry_cfg.get("swing_right_bars", 3)
        self.entry_buffer = self._entry_cfg.get("entry_buffer", 0)
        self.stop_percentage = self._stoploss_cfg.get("percentage", 0.05)
        self.confirm_timeframe = self._confirm_cfg.get("timeframe", "1m")
        self.confirm_minutes = int(self.confirm_timeframe.replace("m", "")) if self.confirm_timeframe.endswith("m") else 1
        self.confirm_candles = self._confirm_cfg.get("candles", 1)
        self.pe_lot_qty = self.trade.get("pe_lot_qty", 2)
        self.lot_size = self.trade.get("lot_size", 75)
        self.rsi_ignore_above = self._entry_cfg.get("rsi_ignore_above", 80)
        self.rsi_period = self.indicators.get("rsi_period", 14)
        logger.info(f"SwingHighLowSellStrategy config: {self.trade}")
    
    async def ensure_broker(self):
        # No longer needed for data fetches, but keep for order placement if required
        await self.dp._ensure_broker()

    async def setup(self) -> None:
        """
        One-time setup: assign key config parameters to self for easy access throughout the strategy.
        No data fetching or calculations are performed here.
        """
        try:
            # All config fields are set in __init__, nothing else to do.
            logger.info(
                f"SwingHighLowSellStrategy setup: symbol={self.symbol}, "
                f"entry_timeframe={self.entry_timeframe}, stop_timeframe={self.stoploss_timeframe}, "
                f"entry_swing_left_bars={self.entry_swing_left_bars}, entry_swing_right_bars={self.entry_swing_right_bars}, "
                f"entry_buffer={self.entry_buffer}, confirm_timeframe={self.confirm_timeframe}, "
                f"confirm_candles={self.confirm_candles}, pe_lot_qty={self.pe_lot_qty}, lot_size={self.lot_size}, "
                f"rsi_ignore_above={self.rsi_ignore_above}, rsi_period={self.rsi_period}, stop_percentage={self.stop_percentage}"
            )
        except Exception as e:
            logger.error(f"SwingHighLowSellStrategy setup failed: {e}", exc_info=True)
            self._setup_failed = True

    def compute_indicators(self, df: pd.DataFrame, config: dict) -> dict:
        """
        Compute swing pivots and any other indicators for the strategy.
        Returns a dict with keys: hh_levels, ll_levels.
        """
        try:
            left_bars = config.get("swing_left_bars", 3)
            right_bars = config.get("swing_right_bars", 3)
            swing_df = swing_utils.find_hhlh_pivots(
                df,
                left_bars=left_bars,
                right_bars=right_bars
            )
            hh_points = swing_df[swing_df["is_HH"]]
            ll_points = swing_df[swing_df["is_LL"]]
            hh_levels = hh_points[["timestamp", "zz"]].to_dict("records")
            ll_levels = ll_points[["timestamp", "zz"]].to_dict("records")
            return {"hh_levels": hh_levels, "ll_levels": ll_levels}
        except Exception as e:
            logger.error(f"Error in compute_indicators: {e}", exc_info=True)
            return {"hh_levels": [], "ll_levels": []}

    def select_strikes_from_pivots(self):
        """
        Select option strikes for entry based on latest swing high/low pivots.
        Returns a list of strike symbols to monitor/trade.
        """
        if not self._hh_levels or not self._ll_levels:
            logger.warning("No HH/LL pivots available for strike selection.")
            return []
        latest_hh = self._hh_levels[-1]["zz"]
        latest_ll = self._ll_levels[-1]["zz"]
        premium_selection = self.trade.get("premium_selection", {})
        atm = round((latest_hh + latest_ll) / 2, -2)
        strikes = [atm]
        otm_offset = premium_selection.get("otm_offset", 100)
        strikes.append(atm + otm_offset)
        strikes.append(atm - otm_offset)
        return [str(s) for s in strikes]

    async def process_cycle(self) -> Optional[dict]:
        """
        Modularized process_cycle: fetches data, evaluates signal, places order, and confirms entry.
        All signal logic is moved to evaluate_signal.
        """
        try:
            if self._setup_failed:
                logger.warning("process_cycle aborted: setup failed.")
                return None

            # Sync open positions from DB before proceeding
            await self.sync_open_positions()
            # If any open position exists, skip processing
            if self._positions and any(self._positions.values()):
                logger.info("Open position(s) exist for this strategy, skipping process_cycle.")
                return None

            # 1. Fetch latest confirm timeframe data (1-min by default)
            confirm_history_dict = await self.fetch_history_data(
                self.dp, [self.symbol], self.confirm_minutes
            )
            confirm_df = confirm_history_dict.get(self.symbol)
            if confirm_df is not None and not isinstance(confirm_df, pd.DataFrame):
                confirm_df = pd.DataFrame(confirm_df)
            # Defensive check
            if confirm_df is None or len(confirm_df) < 2:
                logger.info("Not enough confirm_df data for breakout evaluation.")
                return None
            # Only use closed candles
            now = pd.Timestamp.now(tz="Asia/Kolkata").floor("min")
            df = confirm_df.copy()
            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                df = df.sort_values("timestamp")
                df = df.set_index("timestamp")
            else:
                logger.error("confirm_df missing 'timestamp' column.")
                return None
            if df.index.tz is None:
                df.index = df.index.tz_localize("Asia/Kolkata")
            df = df[df.index < now].copy()
            if df is None or len(df) < 2:
                logger.info("Not enough closed 1-min candles for breakout evaluation.")
                return None
            confirm_df_sorted = df.reset_index()

            # 2. Fetch entry timeframe candles
            entry_history_dict = await self.fetch_history_data(
                self.dp, [self.symbol], self.entry_minutes
            )
            entry_df = entry_history_dict.get(self.symbol)
            if entry_df is not None and not isinstance(entry_df, pd.DataFrame):
                entry_df = pd.DataFrame(entry_df)
            if entry_df is None or len(entry_df) < 10:
                logger.info("Not enough entry_df data for swing high/low detection.")
                return None

            # 3. Evaluate signal using modular method
            signal = await self.evaluate_signal(entry_df, confirm_df_sorted, self.trade)
            if not signal:
                logger.info("No trade signal detected for this cycle.")
                return None
            logger.info(f"Trade signal detected: {signal}")

            # 4. Place order if signal
            order_info = await self.process_order(signal, confirm_df_sorted, signal.symbol)
            if order_info:
                # Check if all broker_responses are terminal (FAILED, CANCELLED, REJECTED)
                broker_responses = order_info.get('broker_responses') if order_info else None
                failed_statuses = {"FAILED", "CANCELLED", "REJECTED"}
                all_failed = False
                if broker_responses and isinstance(broker_responses, dict):
                    statuses = [str(resp.get('status')) if resp else None for resp in broker_responses.values()]
                    statuses = [s.split('.')[-1].replace("'", "").replace(">", "").upper() if s else None for s in statuses]
                    if statuses and all(s in failed_statuses for s in statuses if s):
                        all_failed = True
                if all_failed:
                    logger.error(f"Order placement failed for all brokers, skipping atomic confirmation: {order_info}")
                    return order_info
                logger.info(f"Order placed: {order_info}. Awaiting atomic confirmation on next entry candle close.")
                # Wait for next entry candle to confirm breakout
                await strategy_utils.wait_for_next_candle(self.entry_minutes)
                # Fetch fresh entry_df for confirmation
                entry_history_dict2 = await self.fetch_history_data(
                    self.dp, [self.symbol], self.entry_minutes
                )
                entry_df2 = entry_history_dict2.get(self.symbol)
                if entry_df2 is not None and not isinstance(entry_df2, pd.DataFrame):
                    entry_df2 = pd.DataFrame(entry_df2)
                if entry_df2 is None or len(entry_df2) < 2:
                    logger.warning("Not enough entry_df data for atomic confirmation after order.")
                    # Unable to confirm, exit order for safety
                    await self.exit_order(order_info.get("order_id") or order_info.get("id"))
                    logger.info(f"Entry confirmation failed due to missing data. Order exited: {order_info}")
                    return None
                entry_df2_sorted = entry_df2.sort_values("timestamp")
                latest_entry = entry_df2_sorted.iloc[-1]
                # Confirm based on the breakout direction
                confirm_last_close = confirm_df.iloc[-1]["close"] if "close" in confirm_df.columns else None
                if (signal.signal_direction == "UP" and latest_entry["close"] > confirm_last_close) or \
                   (signal.signal_direction == "DOWN" and latest_entry["close"] < confirm_last_close):
                    logger.info("Breakout confirmed after atomic check, holding position.")
                    return order_info
                else:
                    logger.info("Breakout failed atomic confirmation, exiting order.")
                    await self.exit_order(order_info.get("order_id") or order_info.get("id"))
                    logger.info(f"Entry confirmation failed (candle close {latest_entry['close']} not confirming breakout). Order exited: {order_info}")
                    return None
            else:
                logger.error("Order placement failed in dual timeframe breakout.")
                return None
        except Exception as e:
            logger.error(f"Error in process_cycle: {e}", exc_info=True)
            return None

    async def cancel_order(self, order_id):
        logger.info(f"Stub: cancelling order {order_id}")
        # Implement integration with order manager if needed

    async def exit_order(self, order_id):
        """
        Immediately exit/cancel the given order (atomic entry confirmation).
        """
        logger.info(f"Exiting order {order_id} due to failed atomic entry confirmation.")
        # Implement integration with order manager if needed, e.g., cancel or market exit
        await self.cancel_order(order_id)

    async def fetch_history_data(self, broker, symbols, interval_minutes):
        """
        Modular history fetch for spot/option data, returns dict[symbol] = pd.DataFrame.
        All datetimes should be timezone-aware (IST).
        Calculates from_date and to_date internally based on config and current time.
        """
        from algosat.common import strategy_utils
        try:
            current_date = pd.Timestamp.now(tz="Asia/Kolkata")
            back_days = calculate_backdate_days(interval_minutes)
            trade_day = get_trade_day(current_date - timedelta(days=back_days))
            start_date = localize_to_ist(datetime.combine(trade_day, time(9, 15)))
            current_end_date = localize_to_ist(datetime.combine(current_date, get_ist_datetime().time()))
            # if interval_minutes == 1:
            #     current_end_date = current_end_date.replace(hour=10, minute=15)  # Align to minute
            # elif interval_minutes == 5:
            #     current_end_date = current_end_date.replace(hour=10, minute=20)
            # current_end_date = current_end_date.replace(day=18)
            end_date = calculate_end_date(current_end_date, interval_minutes)
            # end_date = end_date.replace(day=15,hour=10, minute=48, second=0, microsecond=0)  # Market close time
            logger.info(f"Fetching history for {symbols} from {start_date} to {end_date} interval {interval_minutes}m")
            # history_dict = await strategy_utils.fetch_instrument_history(
            #     broker, symbols, start_date, end_date, interval_minutes, ins_type=self.instrument, cache=False
            # )
            
            history_data = await strategy_utils.fetch_instrument_history(
                self.dp,
                [self.symbol],
                from_date=start_date,
                to_date=end_date,
                interval_minutes=interval_minutes,
                ins_type="",
                cache=False
            )
            
            return history_data
        except Exception as e:
            logger.error(f"Error in fetch_history_data: {e}", exc_info=True)
            return {}

    async def process_order(self, signal_payload, data, strike):
        """
        Place an order using the order_manager, passing config as in option_sell.py.
        Returns order info dict if an order is placed, else None.
        This is a SELL strategy: sells PE on UP breakouts, sells CE on DOWN breakouts.
        """
        if signal_payload:
            ts = data.iloc[-1].get('timestamp', 'N/A') if hasattr(data, 'iloc') and len(data) > 0 else signal_payload.get('timestamp', 'N/A')
            logger.info(f"Signal formed for {strike} at {ts}: {signal_payload}")

            order_request = await self.order_manager.broker_manager.build_order_request_for_strategy(
                signal_payload, self.cfg
            )
            result = await self.order_manager.place_order(
                self.cfg,
                order_request,
                strategy_name=None
            )
            if result:
                logger.info(f"Order placed successfully: {result}")
                # Convert OrderRequest to dict for merging
                if hasattr(order_request, 'dict'):
                    order_request_dict = order_request.dict()
                else:
                    order_request_dict = dict(order_request)
                return {**order_request_dict, **result}
            else:
                logger.error(f"Order placement failed: {result}")
                return None
        else:
            logger.debug(f"No signal for {strike}.")
            return None


    async def evaluate_exit(self, order_row):
        """
        Evaluate exit for a given order_row with prioritized exit conditions:
        1. Next Day Stoploss Update (first, but don't exit immediately)
        2. Stop Loss Check (with potentially updated stoploss)
        3. Target Achievement 
        4. Swing High/Low Stoploss Update
        5. Holiday Exit
        
        Args:
            order_row: The order dict (from DB).
        Returns:
            True if exit signal should be triggered, else False.
        """
        try:
            strike_symbol = order_row.get('strike_symbol') or order_row.get('symbol') or order_row.get('strike')
            if not strike_symbol:
                logger.error("evaluate_exit: Missing strike_symbol in order_row.")
                return False
                
            order_id = order_row.get('id') or order_row.get('order_id')
            logger.info(f"evaluate_exit: Checking exit conditions for order_id={order_id}, strike={strike_symbol}")
            
            # Use the spot symbol for spot-level checks
            spot_symbol = self.symbol
            trade_config = self.trade
            
            # Fetch recent candle history for spot price checks
            history_dict = await self.fetch_history_data(
                self.dp, [spot_symbol], self.stoploss_minutes
            )
            history_df = history_dict.get(str(spot_symbol))
            if history_df is None or len(history_df) < 2:
                logger.warning(f"evaluate_exit: Not enough history for {spot_symbol}.")
                return False
                
            # Get current spot price
            current_spot_price = history_df.iloc[-1].get("close") 
            if current_spot_price is None:
                logger.error(f"evaluate_exit: Could not get current spot price for {spot_symbol}")
                return False
            
            logger.info(f"evaluate_exit: Current spot price={current_spot_price} for order_id={order_id}")
            
            # Initialize stoploss from order (will be updated if next day)
            stoploss_spot_level = order_row.get("stoploss_spot_level")
            target_spot_level = order_row.get("target_spot_level")
            signal_direction = order_row.get("signal_direction") or order_row.get("direction", "").upper()
            
            # PRIORITY 1: NEXT DAY STOPLOSS UPDATE (UPDATE ONLY, DON'T EXIT)
            carry_forward_config = trade_config.get("carry_forward", {})
            if carry_forward_config.get("enabled", False):
                try:
                    from algosat.core.time_utils import get_ist_datetime
                    from algosat.common.broker_utils import get_trade_day
                    from datetime import datetime, timedelta
                    
                    # Get order entry date and current date
                    current_datetime = get_ist_datetime()
                    current_trade_day = get_trade_day(current_datetime)
                    
                    # Get order entry date
                    order_timestamp = order_row.get("signal_time") or order_row.get("created_at") or order_row.get("timestamp")
                    if order_timestamp:
                        if isinstance(order_timestamp, str):
                            order_datetime = datetime.fromisoformat(order_timestamp.replace('Z', '+00:00'))
                        else:
                            order_datetime = order_timestamp
                        
                        # Convert order_datetime to IST for consistent trade day calculation
                        # (database timestamps are typically in UTC)
                        order_datetime_ist = to_ist(order_datetime)
                        order_trade_day = get_trade_day(order_datetime_ist)
                        
                        # Check if it's next trading day
                        if current_trade_day > order_trade_day:
                            # Calculate first candle completion time based on stoploss timeframe
                            market_open_time = current_datetime.replace(hour=9, minute=15, second=0, microsecond=0)
                            first_candle_end_time = market_open_time + timedelta(minutes=self.stoploss_minutes)
                            
                            logger.info(f"evaluate_exit: Next day detected - order_id={order_id}, entry_day={order_trade_day}, current_day={current_trade_day}, first_candle_end_time={first_candle_end_time}, current_time={current_datetime}")
                            
                            # Check if first candle of the day is completed
                            if current_datetime >= first_candle_end_time:
                                # Get first candle data to update stoploss
                                first_candle_history = await self.fetch_history_data(
                                    self.dp, [spot_symbol], self.stoploss_minutes
                                )
                                first_candle_df = first_candle_history.get(str(spot_symbol))
                                
                                if first_candle_df is not None and len(first_candle_df) > 0:
                                    # Get today's first candle (9:15 - first_candle_end_time)
                                    first_candle_df = first_candle_df.copy()
                                    first_candle_df['timestamp'] = pd.to_datetime(first_candle_df['timestamp'])
                                    
                                    # Convert market_open_time and first_candle_end_time to pandas Timestamp, ensuring timezone compatibility
                                    market_open_ts = pd.to_datetime(market_open_time)
                                    first_candle_end_ts = pd.to_datetime(first_candle_end_time)
                                    
                                    # Ensure all timestamps are timezone-naive for comparison
                                    if first_candle_df['timestamp'].dt.tz is not None:
                                        first_candle_df['timestamp'] = first_candle_df['timestamp'].dt.tz_localize(None)
                                    if market_open_ts.tz is not None:
                                        market_open_ts = market_open_ts.tz_localize(None)
                                    if first_candle_end_ts.tz is not None:
                                        first_candle_end_ts = first_candle_end_ts.tz_localize(None)
                                    
                                    today_candles = first_candle_df[
                                        (first_candle_df['timestamp'] >= market_open_ts) & 
                                        (first_candle_df['timestamp'] <= first_candle_end_ts)
                                    ]
                                    
                                    if len(today_candles) > 0:
                                        first_candle = today_candles.iloc[0]  # First candle of the day
                                        first_candle_open = first_candle.get("open")
                                        current_stoploss = stoploss_spot_level  # Current stoploss (could be swing low/high)
                                        
                                        # Check if market opened beyond current stoploss and update accordingly
                                        should_update_stoploss = False
                                        
                                        if signal_direction == "UP":  # CE trade
                                            # For CE: Update stoploss if market opened below current stoploss
                                            if first_candle_open and current_stoploss and first_candle_open < float(current_stoploss):
                                                should_update_stoploss = True
                                                updated_stoploss = first_candle.get("low")
                                                update_reason = f"market opened {first_candle_open} below stoploss {current_stoploss}"
                                            
                                        elif signal_direction == "DOWN":  # PE trade  
                                            # For PE: Update stoploss if market opened above current stoploss
                                            if first_candle_open and current_stoploss and first_candle_open > float(current_stoploss):
                                                should_update_stoploss = True
                                                updated_stoploss = first_candle.get("high")
                                                update_reason = f"market opened {first_candle_open} above stoploss {current_stoploss}"
                                        
                                        if should_update_stoploss and updated_stoploss:
                                            stoploss_spot_level = updated_stoploss  # Update for subsequent checks
                                            logger.info(f"evaluate_exit: Next day {signal_direction} - UPDATED stoploss to first candle {'low' if signal_direction == 'UP' else 'high'} {updated_stoploss} (was {current_stoploss}) - {update_reason}")
                                            # Update DB with new stoploss
                                            await self.update_stoploss_in_db(order_id, updated_stoploss)
                                        else:
                                            logger.info(f"evaluate_exit: Next day - Stoploss NOT updated. Market opened at {first_candle_open}, current stoploss={current_stoploss}, direction={signal_direction}")
                                else:
                                    logger.warning(f"evaluate_exit: Could not get first candle data for next day stoploss update")
                            else:
                                logger.info(f"evaluate_exit: Waiting for first candle completion. Current: {current_datetime}, First candle ends: {first_candle_end_time}")
                                
                except Exception as e:
                    logger.error(f"Error in next day stoploss update logic: {e}")
            
            # PRIORITY 2: TWO-CANDLE STOPLOSS CONFIRMATION CHECK
            if stoploss_spot_level is not None and len(history_df) >= 2:
                # Get last two candles for confirmation
                last_two_candles = history_df.tail(2)
                prev_candle = last_two_candles.iloc[0]
                current_candle = last_two_candles.iloc[1]
                
                # Two-candle confirmation logic for SELL strategy (flip logic vs buy)
                if signal_direction == "DOWN":  # CE sell trade (sell call on DOWN breakout)
                    # Exit if price > stoploss (stoploss hit upwards)
                    if (prev_candle.get("close", 0) > float(stoploss_spot_level) and 
                        current_candle.get("close", 0) > prev_candle.get("close", 0)):
                        logger.info(f"evaluate_exit: TWO-CANDLE STOPLOSS confirmed for CE SELL trade. order_id={order_id}, "
                                    f"prev_candle={prev_candle.get('close')} > stoploss={stoploss_spot_level}, "
                                    f"current_candle={current_candle.get('close')} > prev_candle={prev_candle.get('close')}")
                        return True
                elif signal_direction == "UP":  # PE sell trade (sell put on UP breakout)
                    # Exit if price < stoploss (stoploss hit downwards)
                    if (prev_candle.get("close", 0) < float(stoploss_spot_level) and 
                        current_candle.get("close", 0) < prev_candle.get("close", 0)):
                        logger.info(f"evaluate_exit: TWO-CANDLE STOPLOSS confirmed for PE SELL trade. order_id={order_id}, "
                                    f"prev_candle={prev_candle.get('close')} < stoploss={stoploss_spot_level}, "
                                    f"current_candle={current_candle.get('close')} < prev_candle={prev_candle.get('close')}")
                        return True
            
            # PRIORITY 3: TARGET ACHIEVEMENT CHECK (SELL strategy: reverse logic)
            if target_spot_level is not None:
                # Check target based on trade direction
                if signal_direction == "DOWN":  # CE sell
                    if float(current_spot_price) <= float(target_spot_level):
                        logger.info(f"evaluate_exit: TARGET achieved for CE SELL trade. order_id={order_id}, spot_price={current_spot_price} <= target={target_spot_level}")
                        return True
                elif signal_direction == "UP":  # PE sell
                    if float(current_spot_price) >= float(target_spot_level):
                        logger.info(f"evaluate_exit: TARGET achieved for PE SELL trade. order_id={order_id}, spot_price={current_spot_price} >= target={target_spot_level}")
                        return True
            
            # PRIORITY 4: SWING HIGH/LOW STOPLOSS UPDATE (SELL logic: flip vs buy)
            try:
                # Calculate latest swing high/low from current history data
                if len(history_df) >= 10:  # Need enough data for swing calculation
                    swing_df = swing_utils.find_hhlh_pivots(
                        history_df,
                        left_bars=self.entry_swing_left_bars,
                        right_bars=self.entry_swing_right_bars
                    )
                    latest_hh, latest_ll = swing_utils.get_latest_confirmed_high_low(swing_df)
                    
                    if latest_hh and latest_ll:
                        new_stoploss = None
                        if signal_direction == "DOWN":  # CE sell
                            # New stoploss is latest swing high, but take min of current and new (stoploss above entry)
                            latest_swing_high = latest_hh["price"]
                            if stoploss_spot_level:
                                new_stoploss = min(float(stoploss_spot_level), float(latest_swing_high))
                            else:
                                new_stoploss = float(latest_swing_high)
                            if new_stoploss != float(stoploss_spot_level):
                                logger.info(f"evaluate_exit: CE SELL - Updated stoploss from {stoploss_spot_level} to {new_stoploss} (latest swing high)")
                                stoploss_spot_level = new_stoploss
                                await self.update_stoploss_in_db(order_id, new_stoploss)
                        elif signal_direction == "UP":  # PE sell
                            # New stoploss is latest swing low, but take max of current and new (stoploss below entry)
                            latest_swing_low = latest_ll["price"]
                            if stoploss_spot_level:
                                new_stoploss = max(float(stoploss_spot_level), float(latest_swing_low))
                            else:
                                new_stoploss = float(latest_swing_low)
                            if new_stoploss != float(stoploss_spot_level):
                                logger.info(f"evaluate_exit: PE SELL - Updated stoploss from {stoploss_spot_level} to {new_stoploss} (latest swing low)")
                                stoploss_spot_level = new_stoploss
                                await self.update_stoploss_in_db(order_id, new_stoploss)
            except Exception as e:
                logger.error(f"Error in swing high/low stoploss update: {e}")
            
            # PRIORITY 5: NEXT DAY SWING EXIT (Check last two candles for swing breach)
            carry_forward_config = trade_config.get("carry_forward", {})
            if carry_forward_config.get("enabled", False):
                try:
                    from algosat.core.time_utils import get_ist_datetime
                    from algosat.common.broker_utils import get_trade_day
                    from datetime import datetime, timedelta
                    
                    # Get order entry date and current date
                    current_datetime = get_ist_datetime()
                    current_trade_day = get_trade_day(current_datetime)
                    
                    # Get order entry date
                    order_timestamp = order_row.get("signal_time") or order_row.get("created_at") or order_row.get("timestamp")
                    if order_timestamp:
                        if isinstance(order_timestamp, str):
                            order_datetime = datetime.fromisoformat(order_timestamp.replace('Z', '+00:00'))
                        else:
                            order_datetime = order_timestamp
                        
                        # Convert order_datetime to IST for consistent trade day calculation
                        # (database timestamps are typically in UTC)
                        order_datetime_ist = to_ist(order_datetime)
                        order_trade_day = get_trade_day(order_datetime_ist)
                        
                        # Check if it's next trading day
                        if current_trade_day > order_trade_day:
                            # Calculate first candle completion time
                            market_open_time = current_datetime.replace(hour=9, minute=15, second=0, microsecond=0)
                            first_candle_end_time = market_open_time + timedelta(minutes=self.stoploss_minutes)
                            
                            # Get history data AFTER first candle completion time
                            post_first_candle_history = await self.fetch_history_data(
                                self.dp, [spot_symbol], self.stoploss_minutes
                            )
                            post_first_candle_df = post_first_candle_history.get(str(spot_symbol))
                            
                            if post_first_candle_df is not None and len(post_first_candle_df) > 0:
                                # Filter to get data after first candle end time
                                post_first_candle_df = post_first_candle_df.copy()
                                post_first_candle_df['timestamp'] = pd.to_datetime(post_first_candle_df['timestamp'])
                                
                                # Convert first_candle_end_time to pandas Timestamp, ensuring timezone compatibility
                                first_candle_end_ts = pd.to_datetime(first_candle_end_time)
                                
                                # Ensure all timestamps are timezone-naive for comparison
                                if post_first_candle_df['timestamp'].dt.tz is not None:
                                    post_first_candle_df['timestamp'] = post_first_candle_df['timestamp'].dt.tz_localize(None)
                                if first_candle_end_ts.tz is not None:
                                    first_candle_end_ts = first_candle_end_ts.tz_localize(None)
                                
                                post_first_candle_df = post_first_candle_df[
                                    post_first_candle_df['timestamp'] > first_candle_end_ts
                                ].copy()
                                
                                # Check if we have at least 2 candles post first candle
                                if len(post_first_candle_df) >= 2:
                                    # Check last two candles for stoploss breach confirmation
                                    last_two_candles = post_first_candle_df.tail(2)
                                    prev_candle = last_two_candles.iloc[0]
                                    current_candle = last_two_candles.iloc[1]
                                    
                                    # Use current stoploss level (updated by PRIORITY 1 and 4)
                                    current_stoploss = stoploss_spot_level
                                    
                                    if signal_direction == "UP":  # CE trade
                                        # Two-candle confirmation: prev_candle below stoploss AND current_candle below prev_candle
                                        if (current_stoploss and
                                            prev_candle.get("close", 0) < float(current_stoploss) and 
                                            current_candle.get("close", 0) < prev_candle.get("close", 0)):
                                            
                                            logger.info(f"evaluate_exit: NEXT DAY TWO-CANDLE STOPLOSS for CE trade. order_id={order_id}, "
                                                      f"prev_candle={prev_candle.get('close')} < stoploss={current_stoploss}, "
                                                      f"current_candle={current_candle.get('close')} < prev_candle={prev_candle.get('close')} (post-first-candle)")
                                            return True
                                            
                                    elif signal_direction == "DOWN":  # PE trade
                                        # Two-candle confirmation: prev_candle above stoploss AND current_candle above prev_candle
                                        if (current_stoploss and
                                            prev_candle.get("close", 0) > float(current_stoploss) and 
                                            current_candle.get("close", 0) > prev_candle.get("close", 0)):
                                            
                                            logger.info(f"evaluate_exit: NEXT DAY TWO-CANDLE STOPLOSS for PE trade. order_id={order_id}, "
                                                      f"prev_candle={prev_candle.get('close')} > stoploss={current_stoploss}, "
                                                      f"current_candle={current_candle.get('close')} > prev_candle={prev_candle.get('close')} (post-first-candle)")
                                            return True
                                else:
                                    logger.debug(f"evaluate_exit: Not enough post-first-candle data for swing exit check. Need 2, have {len(post_first_candle_df)}")
                            else:
                                logger.warning(f"evaluate_exit: Could not get post-first-candle history data for swing exit check")
                                
                except Exception as e:
                    logger.error(f"Error in next day swing exit logic: {e}")
            
            # PRIORITY 6: HOLIDAY EXIT CHECK
            holiday_exit_config = trade_config.get("holiday_exit", {})
            if holiday_exit_config.get("enabled", False):
                try:
                    from algosat.core.time_utils import get_ist_datetime
                    
                    current_datetime = get_ist_datetime()
                    exit_before_days = holiday_exit_config.get("exit_before_days", 0)
                    
                    # Check next few days for holidays
                    from datetime import timedelta
                    for i in range(1, exit_before_days + 2):  # Check tomorrow and day after
                        check_date = current_datetime + timedelta(days=i)
                        
                        if is_holiday_or_weekend(check_date):
                            # Check if current time is after exit time
                            exit_time = holiday_exit_config.get("exit_time", "14:30")
                            try:
                                exit_hour, exit_minute = map(int, exit_time.split(":"))
                                exit_datetime = current_datetime.replace(
                                    hour=exit_hour, minute=exit_minute, second=0, microsecond=0
                                )
                                
                                if current_datetime >= exit_datetime:
                                    logger.info(f"evaluate_exit: HOLIDAY exit triggered. order_id={order_id}, upcoming_holiday={check_date.strftime('%Y-%m-%d')}, time={current_datetime.strftime('%H:%M')}")
                                    return True
                            except Exception as e:
                                logger.error(f"Error parsing holiday exit time {exit_time}: {e}")
                            break  # Exit on first holiday found
                                
                except Exception as e:
                    logger.error(f"Error in holiday exit logic: {e}")
            
            # PRIORITY 7: RSI-based exit (optional)
            target_cfg = trade_config.get("target", {})
            rsi_exit_config = target_cfg.get("rsi_exit", {})
            if rsi_exit_config.get("enabled", False):
                try:
                    from algosat.utils.indicators import calculate_rsi
                    
                    # Fetch fresh data using entry timeframe for RSI consistency
                    rsi_history_dict = await self.fetch_history_data(
                        self.dp, [spot_symbol], self.entry_minutes
                    )
                    rsi_history_df = rsi_history_dict.get(str(spot_symbol))
                    
                    if rsi_history_df is not None and len(rsi_history_df) > 0:
                        # Calculate RSI on entry timeframe data
                        rsi_period = rsi_exit_config.get("rsi_period", self.rsi_period or 14)
                        rsi_df = calculate_rsi(rsi_history_df, rsi_period)
                        
                        if "rsi" in rsi_df.columns and len(rsi_df) > 0:
                            current_rsi = rsi_df["rsi"].iloc[-1]
                            entry_rsi = order_row.get("entry_rsi")
                            
                            logger.info(f"evaluate_exit: RSI check - current_rsi={current_rsi}, entry_rsi={entry_rsi}, direction={signal_direction}")
                            
                            # RSI exit logic with ignore conditions
                            if signal_direction == "UP":  # CE trade
                                target_level = rsi_exit_config.get("ce_target_level", 60)
                                ignore_above = rsi_exit_config.get("ce_ignore_above", 80)
                                
                                # Check ignore condition: if entry RSI was above ignore threshold, skip RSI exit
                                if entry_rsi is not None and float(entry_rsi) >= ignore_above:
                                    logger.info(f"evaluate_exit: RSI exit IGNORED for CE trade - entry_rsi={entry_rsi} >= ignore_above={ignore_above}")
                                    # Don't trigger RSI exit, continue to other checks
                                else:
                                    # Normal RSI exit logic
                                    if current_rsi >= target_level:
                                        logger.info(f"evaluate_exit: RSI exit for CE trade. order_id={order_id}, rsi={current_rsi} >= target_level={target_level}")
                                        return True
                                        
                            elif signal_direction == "DOWN":  # PE trade
                                target_level = rsi_exit_config.get("pe_target_level", 20)
                                ignore_below = rsi_exit_config.get("pe_ignore_below", 10)
                                
                                # Check ignore condition: if entry RSI was below ignore threshold, skip RSI exit
                                if entry_rsi is not None and float(entry_rsi) <= ignore_below:
                                    logger.info(f"evaluate_exit: RSI exit IGNORED for PE trade - entry_rsi={entry_rsi} <= ignore_below={ignore_below}")
                                    # Don't trigger RSI exit, continue to other checks
                                else:
                                    # Normal RSI exit logic
                                    if current_rsi <= target_level:
                                        logger.info(f"evaluate_exit: RSI exit for PE trade. order_id={order_id}, rsi={current_rsi} <= target_level={target_level}")
                                        return True
                        else:
                            logger.warning(f"evaluate_exit: Could not calculate current RSI - missing RSI column")
                    else:
                        logger.warning(f"evaluate_exit: Could not fetch history data for RSI calculation")
                                
                except Exception as e:
                    logger.error(f"Error in RSI exit logic: {e}")
            
            # PRIORITY 8: EXPIRY EXIT CHECK
            expiry_date = order_row.get("expiry_date")
            expiry_exit_config = trade_config.get("expiry_exit", {})
            if expiry_date is not None and expiry_exit_config.get("enabled", False):
                try:
                    from algosat.core.time_utils import get_ist_datetime
                    from datetime import datetime
                    
                    current_datetime = get_ist_datetime()
                    
                    # Convert expiry_date to pandas datetime if it's a string
                    if isinstance(expiry_date, str):
                        expiry_dt = pd.to_datetime(expiry_date)
                    else:
                        expiry_dt = expiry_date
                    
                    # Check if today is the expiry date
                    if current_datetime.date() == expiry_dt.date():
                        # Get expiry exit time from config (default to 15:15)
                        expiry_exit_time = expiry_exit_config.get("expiry_exit_time", "15:15")
                        
                        try:
                            # Parse expiry_exit_time (format: "HH:MM")
                            exit_hour, exit_minute = map(int, expiry_exit_time.split(":"))
                            exit_time = current_datetime.replace(
                                hour=exit_hour, minute=exit_minute, second=0, microsecond=0
                            )
                            
                            if current_datetime >= exit_time:
                                logger.info(f"evaluate_exit: EXPIRY exit triggered. order_id={order_id}, expiry_date={expiry_date}, current_time={current_datetime.strftime('%H:%M')}, exit_time={expiry_exit_time}")
                                return True
                        except Exception as e:
                            logger.error(f"Error parsing expiry exit time {expiry_exit_time}: {e}")
                            
                except Exception as e:
                    logger.error(f"Error in expiry exit logic: {e}")
            
            # No exit condition met
            logger.debug(f"evaluate_exit: No exit condition met for order_id={order_id}")
            return False
            
        except Exception as e:
            logger.error(f"Error in evaluate_exit for order_id={order_row.get('id')}: {e}", exc_info=True)
            return False
    
    def update_stoploss_in_db(self, order_id, new_stoploss):
        """Update stoploss level in database"""
        try:
            from algosat.core.db import AsyncSessionLocal
            with AsyncSessionLocal as session:
                # Update orders table with new stoploss
                query = "UPDATE orders SET stoploss_spot_level = %s WHERE id = %s"
                session.execute(query, (float(new_stoploss), order_id))
                session.commit()
                logger.info(f"Updated stoploss in DB: order_id={order_id}, new_stoploss={new_stoploss}")
        except Exception as e:
            logger.error(f"Error updating stoploss in DB for order_id={order_id}: {e}")
    
    def update_target_in_db(self, order_id, new_target):
        """Update target level in database"""
        try:
            from algosat.core.db import AsyncSessionLocal
            with AsyncSessionLocal as session:
                # Update orders table with new target
                query = "UPDATE orders SET target_spot_level = %s WHERE id = %s"
                session.execute(query, (float(new_target), order_id))
                session.commit()
                logger.info(f"Updated target in DB: order_id={order_id}, new_target={new_target}")
        except Exception as e:
            logger.error(f"Error updating target in DB for order_id={order_id}: {e}")
    
    def update_swing_levels_in_db(self, order_id, swing_high=None, swing_low=None):
        """Update swing high/low levels in database"""
        try:
            from algosat.core.db import AsyncSessionLocal
            with AsyncSessionLocal as session:
                # Build dynamic query based on provided parameters
                update_fields = []
                params = []
                
                if swing_high is not None:
                    update_fields.append("entry_spot_swing_high = %s")
                    params.append(float(swing_high))
                
                if swing_low is not None:
                    update_fields.append("entry_spot_swing_low = %s")
                    params.append(float(swing_low))
                
                if update_fields:
                    query = f"UPDATE orders SET {', '.join(update_fields)} WHERE id = %s"
                    params.append(order_id)
                    session.execute(query, params)
                    session.commit()
                    logger.info(f"Updated swing levels in DB: order_id={order_id}, swing_high={swing_high}, swing_low={swing_low}")
        except Exception as e:
            logger.error(f"Error updating swing levels in DB for order_id={order_id}: {e}")
    
    def update_entry_rsi_in_db(self, order_id, entry_rsi):
        """Update entry RSI level in database"""
        try:
            from algosat.core.db import AsyncSessionLocal
            with AsyncSessionLocal as session:
                # Update orders table with entry RSI
                query = "UPDATE orders SET entry_rsi = %s WHERE id = %s"
                session.execute(query, (float(entry_rsi), order_id))
                session.commit()
                logger.info(f"Updated entry_rsi in DB: order_id={order_id}, entry_rsi={entry_rsi}")
        except Exception as e:
            logger.error(f"Error updating entry_rsi in DB for order_id={order_id}: {e}")
    
    async def update_exit_status_in_db(self, order_id, exit_result):
        """
        Update the order exit status in database when exit is triggered.
        Args:
            order_id: The order ID to update
            exit_result: Dict containing exit information from evaluate_exit
        """
        try:
            from algosat.core.db import AsyncSessionLocal
            from algosat.core.db import update_order_exit_status
            
            async with AsyncSessionLocal() as session:
                await update_order_exit_status(
                    session, 
                    order_id, 
                    exit_reason=exit_result.get('exit_reason'),
                    exit_price=exit_result.get('exit_price'),
                    exit_metadata=exit_result
                )
                logger.info(f"Updated exit status in DB for order_id={order_id}, reason={exit_result.get('exit_reason')}")
                
        except Exception as e:
            logger.error(f"Error updating exit status in DB for order_id={order_id}: {e}", exc_info=True)
        
    async def evaluate_signal(self, entry_df, confirm_df, config) -> Optional[TradeSignal]:
        """
        Modular method to evaluate entry signals for swing high/low breakouts.
        Returns a TradeSignal object if signal is detected, else None.
        """
        from algosat.core.signal import TradeSignal, SignalType
        try:
            # 1. Identify most recent swing high/low from entry_df
            entry_left = self.entry_swing_left_bars
            entry_right = self.entry_swing_right_bars
            swing_df = swing_utils.find_hhlh_pivots(
                entry_df,
                left_bars=entry_left,
                right_bars=entry_right
            )
            last_hh, last_ll, last_hl, last_lh = swing_utils.get_last_swing_points(swing_df)
            logger.info(f"Latest swing points: HH={last_hh}, LL={last_ll}, HL={last_hl}, LH={last_lh}")
            last_hh, last_ll = swing_utils.get_latest_confirmed_high_low(swing_df)
            if not last_hh or not last_ll:
                logger.info("No HH/LL pivot available for breakout evaluation.")
                return None
            entry_buffer = self.entry_buffer
            breakout_high_level = last_hh["price"] + entry_buffer
            breakout_low_level = last_ll["price"] - entry_buffer

            # Prepare new fields
            entry_spot_price = None
            entry_spot_swing_high = None
            entry_spot_swing_low = None
            stoploss_spot_level = None
            target_spot_level = None

            # 2. In confirm_df, check last two closed candles for breakout
            if "timestamp" in confirm_df.columns:
                confirm_df = confirm_df.sort_values("timestamp")
            last_two = confirm_df.tail(2)
            if len(last_two) < 2:
                logger.info("Not enough 1-min candles for confirmation logic.")
                return None
            prev_candle = last_two.iloc[0]
            last_candle = last_two.iloc[1]

            # 3. Determine breakout direction and signal
            breakout_type = None
            trend = None
            direction = None
            signal_price = None
            if prev_candle["close"] > breakout_high_level and last_candle["close"] > prev_candle["close"]:
                breakout_type = "CE"
                trend = "UP"
                direction = "UP"
                signal_price = breakout_high_level
            elif prev_candle["close"] < breakout_low_level and last_candle["close"] < prev_candle["close"]:
                breakout_type = "PE"
                trend = "DOWN"
                direction = "DOWN"
                signal_price = breakout_low_level
            else:
                logger.debug("No breakout detected in confirm candles.")
                return None

            # 4. Get spot price and ATM strike for option
            spot_price = last_candle["close"]  # Use last candle close as spot price
            strike, expiry_date = swing_utils.get_atm_strike_symbol(self.cfg.symbol, spot_price, breakout_type, self.trade)
            qty = self.ce_lot_qty * self.lot_size if breakout_type == "CE" else self.trade.get("pe_lot_qty", 1) * self.lot_size
            if breakout_type == "CE":
                lot_qty = config.get("ce_lot_qty", 1)
                stoploss_spot_level = last_ll["price"]  # Stoploss is swing low for CE
            else:
                lot_qty = config.get("pe_lot_qty", 1)
                stoploss_spot_level = last_hh["price"]  # Stoploss is swing high for PE

            entry_spot_price = spot_price
            entry_spot_swing_high = last_hh["price"]
            entry_spot_swing_low = last_ll["price"]

            # Target calculation
            target_cfg = config.get("target", {})
            target_type = target_cfg.get("type", "ATR")
            if target_type == "ATR":
                # Calculate ATR on entry timeframe (5m default)
                atr_period = target_cfg.get("atr_period", 14)
                atr_multiplier = target_cfg.get("atr_multiplier", 3)  # Default to 3x ATR
                # Defensive: ensure entry_df has enough data
                atr_value = None
                try:
                    from algosat.utils.indicators import calculate_atr
                    atr_df = calculate_atr(entry_df, atr_period)
                    if "atr" in atr_df.columns:
                        atr_value = atr_df["atr"].iloc[-1]
                except Exception as e:
                    logger.error(f"Error calculating ATR for target: {e}")
                
                if atr_value is not None:
                    if breakout_type == "CE":
                        # For CE: Target = swing_high + (ATR * multiplier)
                        target_spot_level = float(entry_spot_swing_high) + (float(atr_value) * float(atr_multiplier))
                    else:
                        # For PE: Target = swing_low - (ATR * multiplier)
                        target_spot_level = float(entry_spot_swing_low) - (float(atr_value) * float(atr_multiplier))
                else:
                    logger.warning("Could not calculate ATR for target, using fallback")
                    target_spot_level = None
            elif target_type == "fixed":
                fixed_points = target_cfg.get("fixed_points", 0)
                if breakout_type == "CE":
                    # For CE: Target = swing_high + fixed_points
                    target_spot_level = float(entry_spot_swing_high) + float(fixed_points)
                else:
                    # For PE: Target = swing_low - fixed_points  
                    target_spot_level = float(entry_spot_swing_low) - float(fixed_points)
            else:
                target_spot_level = None

            # Calculate entry RSI using entry timeframe
            entry_rsi_value = None
            try:
                from algosat.utils.indicators import calculate_rsi
                rsi_period = self.rsi_period or 14
                
                # Use entry timeframe data for RSI calculation to ensure consistency
                rsi_df = calculate_rsi(entry_df, rsi_period)
                if "rsi" in rsi_df.columns and len(rsi_df) > 0:
                    entry_rsi_value = rsi_df["rsi"].iloc[-1]
                    logger.info(f"Entry RSI calculated: {entry_rsi_value} (period={rsi_period})")
                else:
                    logger.warning("Could not calculate entry RSI - missing RSI column")
            except Exception as e:
                logger.error(f"Error calculating entry RSI: {e}")

            logger.info(f"Breakout detected: type={breakout_type}, trend={trend}, direction={direction}, strike={strike}, price={last_candle['close']}, entry_spot_price={entry_spot_price}, entry_spot_swing_high={entry_spot_swing_high}, entry_spot_swing_low={entry_spot_swing_low}, stoploss_spot_level={stoploss_spot_level}, target_spot_level={target_spot_level}, entry_rsi={entry_rsi_value}, target_type={target_type}, expiry_date={expiry_date}")
            from algosat.core.signal import Side
            signal = TradeSignal(
                symbol=strike,
                side="SELL",
                signal_type=SignalType.ENTRY,
                signal_time=last_candle["timestamp"],
                signal_direction=direction,
                lot_qty=lot_qty,
                entry_spot_price=entry_spot_price,
                entry_spot_swing_high=entry_spot_swing_high,
                entry_spot_swing_low=entry_spot_swing_low,
                stoploss_spot_level=stoploss_spot_level,
                target_spot_level=target_spot_level,
                entry_rsi=entry_rsi_value,
                expiry_date=expiry_date
            )
            logger.info(f"Breakout detected: type={breakout_type}, direction={direction}, strike={strike}, price={last_candle['close']}")
            return signal
        except Exception as e:
            logger.error(f"Error in evaluate_signal: {e}", exc_info=True)
            return None
