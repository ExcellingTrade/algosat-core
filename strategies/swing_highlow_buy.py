from datetime import datetime, time, timedelta
from typing import Any, Optional
from algosat.core.signal import TradeSignal
import pandas as pd
from algosat.common import constants, strategy_utils
from algosat.common.broker_utils import calculate_backdate_days, get_trade_day
from algosat.common.strategy_utils import calculate_end_date
from algosat.core.data_manager import DataManager
from algosat.core.order_manager import OrderManager
from algosat.core.time_utils import localize_to_ist, get_ist_datetime
from algosat.strategies.base import StrategyBase
from algosat.common.logger import get_logger
from algosat.common import swing_utils
import asyncio

logger = get_logger(__name__)

class SwingHighLowBuyStrategy(StrategyBase):

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
    Concrete implementation of a Swing High/Low breakout buy strategy.
    Modularized and standardized to match option_buy.py structure.
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
        self.entry_swing_left_bars = self._entry_cfg.get("swing_left_bars", 3)
        self.entry_swing_right_bars = self._entry_cfg.get("swing_right_bars", 3)
        self.entry_buffer = self._entry_cfg.get("entry_buffer", 0)
        self.stop_timeframe = self._stoploss_cfg.get("timeframe", "5m")
        self.stop_percentage = self._stoploss_cfg.get("percentage", 0.05)
        self.confirm_timeframe = self._confirm_cfg.get("timeframe", "1m")
        self.confirm_minutes = int(self.confirm_timeframe.replace("m", "")) if self.confirm_timeframe.endswith("m") else 1
        self.confirm_candles = self._confirm_cfg.get("candles", 1)
        self.ce_lot_qty = self.trade.get("ce_lot_qty", 2)
        self.lot_size = self.trade.get("lot_size", 75)
        self.rsi_ignore_above = self._entry_cfg.get("rsi_ignore_above", 80)
        self.rsi_period = self.indicators.get("rsi_period", 14)
        logger.info(f"SwingHighLowBuyStrategy config: {self.trade}")
    
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
                f"SwingHighLowBuyStrategy setup: symbol={self.symbol}, "
                f"entry_timeframe={self.entry_timeframe}, stop_timeframe={self.stop_timeframe}, "
                f"entry_swing_left_bars={self.entry_swing_left_bars}, entry_swing_right_bars={self.entry_swing_right_bars}, "
                f"entry_buffer={self.entry_buffer}, confirm_timeframe={self.confirm_timeframe}, "
                f"confirm_candles={self.confirm_candles}, ce_lot_qty={self.ce_lot_qty}, lot_size={self.lot_size}, "
                f"rsi_ignore_above={self.rsi_ignore_above}, rsi_period={self.rsi_period}, stop_percentage={self.stop_percentage}"
            )
        except Exception as e:
            logger.error(f"SwingHighLowBuyStrategy setup failed: {e}", exc_info=True)
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
            if interval_minutes == 1:
                current_end_date = current_end_date.replace(hour=10, minute=15)  # Align to minute
            elif interval_minutes == 5:
                current_end_date = current_end_date.replace(hour=10, minute=20)
            current_end_date = current_end_date.replace(day=18)
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
        Place an order using the order_manager, passing config as in option_buy.py.
        Returns order info dict if an order is placed, else None.
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

    # The dual timeframe breakout logic is now handled directly in process_cycle.
    # The previous single-timeframe breakout evaluate_signal is obsolete and removed.

    def evaluate_exit(self, data: Any, position: Any) -> Optional[dict]:
        """
        Evaluate exit conditions based on fetched data and current position.
        This method combines price-based and candle-based exit logic.
        Return an order payload dict if exit condition is met, otherwise None.
        """
        try:
            if not position:
                return None
            
            # Extract necessary info from position
            parent_order_id = position.get("order_id") or position.get("id")
            if not parent_order_id:
                logger.warning("No order ID found in position data")
                return None
            
            # Get current price from data
            last_price = None
            if isinstance(data, dict):
                last_price = data.get("ltp") or data.get("close") or data.get("price")
            elif hasattr(data, 'iloc') and len(data) > 0:  # DataFrame
                last_row = data.iloc[-1]
                last_price = last_row.get("close") or last_row.get("ltp")
            
            if last_price is None:
                logger.warning("Could not extract price from data for exit evaluation")
                return None
            
            # For now, implement basic exit logic
            # In a production environment, this would check stop loss, take profit, 
            # trailing stops, time-based exits, etc.
            
            # Example: Simple percentage-based stop loss
            entry_price = position.get("entry_price") or position.get("price")
            if entry_price:
                stop_loss_pct = self._stoploss_cfg.get("percentage", 0.05)  # 5% default
                stop_loss_price = entry_price * (1 - stop_loss_pct)
                
                if last_price <= stop_loss_price:
                    logger.info(f"Stop loss triggered: price {last_price} <= stop {stop_loss_price}")
                    return {
                        "symbol": position.get("symbol", self.symbol),
                        "strike": position.get("strike"),
                        "side": "SELL",  # Exit by selling
                        "qty": position.get("qty"),
                        "price": last_price,
                        "order_type": "MARKET",
                        "exit_reason": "stop_loss"
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"Error in evaluate_exit: {e}", exc_info=True)
            return None
        
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
            # ltp_response = await self.dp.get_ltp(self.symbol)
            # if isinstance(ltp_response, dict):
            #     spot_price = ltp_response.get(self.symbol)
            # else:
            #     spot_price = ltp_response
            spot_price = last_candle["close"]  # Use last candle close as spot price
            strike = swing_utils.get_atm_strike_symbol(self.cfg.symbol, spot_price, breakout_type, self.trade)
            qty = self.ce_lot_qty * self.lot_size if breakout_type == "CE" else self.trade.get("pe_lot_qty", 1) * self.lot_size
            if breakout_type == "CE":
                lot_qty = config.get("ce_lot_qty", 1)
            else:
                lot_qty = config.get("pe_lot_qty", 1)
            logger.info(f"Breakout detected: type={breakout_type}, trend={trend}, direction={direction}, strike={strike}, price={last_candle['close']}")
            from algosat.core.signal import Side
            signal = TradeSignal(
                symbol=strike,
                side="BUY",
                # price=last_candle["close"],
                signal_type=SignalType.ENTRY,
                signal_time=last_candle["timestamp"],
                signal_direction=direction,
                lot_qty=lot_qty,
            )
            logger.info(f"Breakout detected: type={breakout_type}, direction={direction}, strike={strike}, price={last_candle['close']}")
            return signal
        except Exception as e:
            logger.error(f"Error in evaluate_signal: {e}", exc_info=True)
            return None

    async def evaluate_price_exit(self, parent_order_id: int, last_price: float):
        """
        Exit based on price (stub for parity with option_buy.py).
        """
        return None

    async def evaluate_candle_exit(self, parent_order_id: int, history: dict):
        """
        Exit based on candle history (stub for parity with option_buy.py).
        """
        return None
