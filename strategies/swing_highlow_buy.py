from typing import Any, Optional
from algosat.strategies.base import StrategyBase
from algosat.common.logger import get_logger
from algosat.common import swing_utils
import pandas as pd
import asyncio

logger = get_logger(__name__)

class SwingHighLowBuyStrategy(StrategyBase):
    """
    Swing High/Low Breakout Options Buy Strategy.
    Implements swing high/low entry, trailing stoploss, ATR/RSI/fixed target, and advanced exit logic.
    Config is expected in the trade and indicators fields of the config dataclass.
    """
    def __init__(self, config, data_manager, execution_manager):
        super().__init__(config, data_manager, execution_manager)
        self.symbol = self.cfg.symbol
        self.exchange = self.cfg.exchange
        self.instrument = self.cfg.instrument
        self.trade = self.cfg.trade  # Main config dict for strategy logic
        self.indicators = self.cfg.indicators  # Indicator config dict
        # Entry config
        self.entry_cfg = self.trade.get("entry", {})
        self.entry_timeframe = self.entry_cfg.get("timeframe", "5m")
        self.entry_swing_left_bars = self.entry_cfg.get("swing_left_bars", 3)
        self.entry_swing_right_bars = self.entry_cfg.get("swing_right_bars", 3)
        self.entry_buffer = self.entry_cfg.get("entry_buffer", 0)
        self.entry_confirmation_tf = self.entry_cfg.get("confirmation_candle_timeframe", "1m")
        self.atm_strike_offset = self.entry_cfg.get("atm_strike_offset", 0)
        # Stoploss config
        self.stoploss_cfg = self.trade.get("stoploss", {})
        self.stoploss_timeframe = self.stoploss_cfg.get("timeframe", "3m")
        self.stoploss_swing_left_bars = self.stoploss_cfg.get("swing_left_bars", 3)
        self.stoploss_swing_right_bars = self.stoploss_cfg.get("swing_right_bars", 3)
        self.stoploss_trailing = self.stoploss_cfg.get("trailing", True)
        self.stoploss_sl_buffer = self.stoploss_cfg.get("sl_buffer", 0)
        self.stoploss_confirmation_tf = self.stoploss_cfg.get("confirmation_candle_timeframe", "1m")
        # Other config fields
        self.target_cfg = self.trade.get("target", {})
        self.carry_forward_cfg = self.trade.get("carry_forward", {})
        self.expiry_exit_cfg = self.trade.get("expiry_exit", {})
        self.holiday_exit = self.trade.get("holiday_exit", False)
        self.square_off_time = self.trade.get("square_off_time", "15:10")
        self.max_nse_qty = self.trade.get("max_nse_qty", 900)
        self.lot_size = self.trade.get("lot_size", 75)
        self.ce_lot_qty = self.trade.get("ce_lot_qty", 2)
        self.pe_lot_qty = self.trade.get("pe_lot_qty", 1)
        self.max_trades_per_day = self.trade.get("max_trades_per_day", 3)
        self.max_loss_trades_per_day = self.trade.get("max_loss_trades_per_day", 2)
        self.max_loss_per_lot = self.trade.get("max_loss_per_lot", 2000)
        self.premium_selection = self.trade.get("premium_selection", {})
        # Indicator config
        self.atr_period = self.indicators.get("atr_period", 10)
        self.rsi_period = self.indicators.get("rsi_period", 14)
        self.sma_period = self.indicators.get("sma_period", 14)
        # Internal state
        self._strikes = []
        self._positions = {}
        self._setup_failed = False
        self._hh_levels = []
        self._ll_levels = []
        # Document config usage
        logger.info(f"Entry config: timeframe={self.entry_timeframe}, swing_left_bars={self.entry_swing_left_bars}, swing_right_bars={self.entry_swing_right_bars}, entry_buffer={self.entry_buffer}, confirmation_tf={self.entry_confirmation_tf}, atm_strike_offset={self.atm_strike_offset}")
        logger.info(f"Stoploss config: timeframe={self.stoploss_timeframe}, swing_left_bars={self.stoploss_swing_left_bars}, swing_right_bars={self.stoploss_swing_right_bars}, trailing={self.stoploss_trailing}, sl_buffer={self.stoploss_sl_buffer}, confirmation_tf={self.stoploss_confirmation_tf}")

    async def setup(self) -> None:
        """
        One-time setup for the strategy: fetch historical spot data for swing high/low detection
        using entry config timeframe and swing settings. Sets _setup_failed if unable to proceed.
        """
        try:
            from algosat.common.strategy_utils import get_trade_day, get_ist_datetime, calculate_first_candle_details
            trade_day = get_trade_day(get_ist_datetime())
            interval_minutes = int(self.entry_timeframe.replace("m", "")) if self.entry_timeframe.endswith("m") else 5
            first_candle_time = self.trade.get("first_candle_time", "09:15")
            candle_times = calculate_first_candle_details(trade_day.date(), first_candle_time, interval_minutes)
            from_date = candle_times["from_date"]
            to_date = candle_times["to_date"]
            # Fetch spot history ONLY (never option strikes)
            from algosat.common import strategy_utils
            spot_history_dict = await strategy_utils.fetch_strikes_history(
                self.data_manager, [self.symbol], from_date, to_date, interval_minutes, ins_type=self.instrument, cache=True
            )
            spot_history = spot_history_dict.get(self.symbol)
            if not spot_history or len(spot_history) < 20:
                logger.error(f"Not enough bars for swing calculation: got {len(spot_history) if spot_history else 0}")
                self._setup_failed = True
                return
            df = pd.DataFrame(spot_history)
            if not all(col in df.columns for col in ["timestamp", "high", "low", "close"]):
                logger.error("Missing required columns in OHLCV data")
                self._setup_failed = True
                return
            # Calculate swing pivots using entry swing config
            swing_df = swing_utils.find_hhlh_pivots(
                df,
                left_bars=self.entry_swing_left_bars,
                right_bars=self.entry_swing_right_bars
            )
            hh_points = swing_df[swing_df["is_HH"]]
            ll_points = swing_df[swing_df["is_LL"]]
            self._hh_levels = hh_points[["timestamp", "zz"]].to_dict("records")
            self._ll_levels = ll_points[["timestamp", "zz"]].to_dict("records")
            logger.info(f"Identified {len(self._hh_levels)} HH and {len(self._ll_levels)} LL pivots for {self.symbol} (entry config)")
            self._strikes = self.select_strikes_from_pivots()
        except Exception as e:
            logger.error(f"SwingHighLowBuyStrategy setup failed: {e}", exc_info=True)
            self._setup_failed = True

    def select_strikes_from_pivots(self):
        """
        Select option strikes for entry based on the latest swing high/low pivots.
        This can be customized: e.g., use the most recent HH/LL, or a buffer above/below, etc.
        Returns a list of strike symbols (strings) to monitor/trade.
        """
        # Example: Use the latest HH and LL price as reference for strike selection
        if not self._hh_levels or not self._ll_levels:
            logger.warning("No HH/LL pivots available for strike selection.")
            return []
        latest_hh = self._hh_levels[-1]["zz"]
        latest_ll = self._ll_levels[-1]["zz"]
        # Use premium_selection config or fallback to ATM/OTM logic
        strikes = []
        # Example: ATM strike (rounded to nearest 50/100)
        atm = round((latest_hh + latest_ll) / 2, -2)
        strikes.append(atm)
        # Optionally add OTM/ITM strikes based on config
        otm_offset = self.premium_selection.get("otm_offset", 100)
        strikes.append(atm + otm_offset)
        strikes.append(atm - otm_offset)
        # Convert to string if needed (depends on broker symbol format)
        return [str(s) for s in strikes]

    async def place_order(self, strike: str, price: float, qty: int) -> Optional[dict]:
        """
        Place a buy order using the order_manager. Returns order details dict if successful.
        """
        try:
            order_details = {
                "symbol": self.symbol,
                "strike": strike,
                "side": "BUY",
                "qty": qty,
                "price": price,
            }
            # Integrate with order_manager (assume async API)
            result = await self.order_manager.place_order(
                symbol=self.symbol,
                strike=strike,
                side="BUY",
                qty=qty,
                price=price,
                order_type="MARKET",  # or use config
            )
            order_id = result.get("order_id") if result else None
            if order_id:
                logger.info(f"Order placed successfully: {order_id}")
                return {"order_id": order_id, **order_details}
            else:
                logger.error(f"Order placement failed: {result}")
                return None
        except Exception as e:
            logger.error(f"Exception in place_order: {e}", exc_info=True)
            return None

    async def process_cycle(self) -> Optional[dict]:
        """
        Main signal evaluation cycle: fetch latest spot data, check for HH/LL breakout,
        and place buy order if breakout conditions are met and no open position exists.
        After entry, starts stoploss monitoring loop.
        """
        try:
            # Fetch latest spot candle (assume 1 bar, most recent)
            from algosat.common import strategy_utils
            interval_minutes = self.trade.get("interval_minutes", 5)
            now = pd.Timestamp.now(tz="Asia/Kolkata")
            # Use last completed candle's time window
            to_date = now.floor(f"{interval_minutes}min")
            from_date = to_date - pd.Timedelta(minutes=interval_minutes)
            spot_history_dict = await strategy_utils.fetch_strikes_history(
                self.data_manager, [self.symbol], from_date, to_date, interval_minutes, ins_type=self.instrument, cache=False
            )
            spot_history = spot_history_dict.get(self.symbol)
            if not spot_history or len(spot_history) == 0:
                logger.warning("No latest spot candle available for signal evaluation.")
                return None
            latest_candle = spot_history[-1]
            # Check for breakout above HH or below LL
            if not self._hh_levels or not self._ll_levels:
                logger.warning("No HH/LL pivots available for signal evaluation.")
                return None
            last_hh = self._hh_levels[-1]["zz"]
            last_ll = self._ll_levels[-1]["zz"]
            close = latest_candle["close"]
            # Only buy if price breaks above last HH (bullish breakout)
            if close > last_hh:
                if self._positions.get("buy", False):
                    logger.info("Already in buy position, skipping new entry.")
                    return None
                # Place buy order using order_manager
                strike = self._strikes[0] if self._strikes else None
                qty = self.ce_lot_qty * self.lot_size
                order_result = await self.place_order(strike, close, qty)
                if order_result:
                    self._positions["buy"] = True
                    # Start stoploss monitoring loop after entry
                    logger.info("Starting stoploss monitoring after entry.")
                    asyncio.create_task(self.monitor_stoploss_loop(order_result))
                    return order_result
                else:
                    logger.error("Order placement failed in process_cycle.")
                    return None
            else:
                logger.info(f"No breakout: close={close}, last_hh={last_hh}")
            return None
        except Exception as e:
            logger.error(f"Error in process_cycle: {e}", exc_info=True)
            return None

    def evaluate_signal(self, spot_df_entry: pd.DataFrame, spot_df_confirm: pd.DataFrame, config: dict, strike: str) -> Optional[dict]:
        """
        Evaluate entry signal for CE:
        - Detect breakout: price must close above last swing high + entry_buffer (from entry config) on entry timeframe.
        - Require a confirmation candle (from confirmation_candle_timeframe) that closes above previous close on confirmation timeframe.
        - Only after both conditions are met, generate an entry signal (with price, strike, qty, etc).
        - Uses spot data only for swing high detection.
        - Always fetches latest swing points using swing_utils.get_last_swing_points.
        """
        if spot_df_entry is None or len(spot_df_entry) < 2 or spot_df_confirm is None or len(spot_df_confirm) < 2:
            logger.info("Not enough spot data for signal evaluation.")
            return None
        # Calculate pivots and get last swing points every call (entry timeframe)
        swing_df = swing_utils.find_hhlh_pivots(
            spot_df_entry,
            left_bars=self.entry_swing_left_bars,
            right_bars=self.entry_swing_right_bars
        )
        last_hh, last_ll, _, _ = swing_utils.get_last_swing_points(swing_df)
        if not last_hh:
            logger.info("No HH pivot available for signal evaluation.")
            return None
        entry_buffer = self.entry_buffer
        # 1. Detect breakout: close > last_hh['price'] + entry_buffer (entry timeframe)
        last_row_entry = spot_df_entry.iloc[-1]
        close_entry = last_row_entry["close"]
        breakout = close_entry > (last_hh['price'] + entry_buffer)
        if not breakout:
            logger.info(f"No breakout: close={close_entry}, last_hh+buffer={last_hh['price'] + entry_buffer}")
            return None
        # 2. Confirmation candle logic (confirmation timeframe)
        last_row_confirm = spot_df_confirm.iloc[-1]
        prev_close_confirm = spot_df_confirm.iloc[-2]["close"]
        close_confirm = last_row_confirm["close"]
        if close_confirm <= prev_close_confirm:
            logger.info(f"Confirmation failed: close={close_confirm} <= prev_close={prev_close_confirm}")
            return None
        # 3. Generate entry signal
        qty = self.ce_lot_qty * self.lot_size
        signal = {
            "symbol": self.symbol,
            "strike": strike,
            "side": "BUY",
            "qty": qty,
            "price": close_entry,
            "timestamp": last_row_entry["timestamp"],
        }
        # 4. RSI ignore logic (entry)
        rsi_ignore_above = self.entry_cfg.get("rsi_ignore_above", 80)
        rsi_ignore_below = self.entry_cfg.get("rsi_ignore_below", 20)
        rsi_period = self.rsi_period
        # Calculate RSI on entry timeframe
        close_series = spot_df_entry["close"]
        rsi = None
        if len(close_series) >= rsi_period:
            delta = close_series.diff()
            gain = delta.where(delta > 0, 0.0)
            loss = -delta.where(delta < 0, 0.0)
            avg_gain = gain.rolling(window=rsi_period, min_periods=rsi_period).mean()
            avg_loss = loss.rolling(window=rsi_period, min_periods=rsi_period).mean()
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            rsi_val = rsi.iloc[-1]
            logger.info(f"RSI at entry: {rsi_val}")
            if rsi_val >= rsi_ignore_above:
                logger.info(f"RSI {rsi_val} >= rsi_ignore_above {rsi_ignore_above}: ignoring entry signal.")
                return None
        signal = {
            "symbol": self.symbol,
            "strike": strike,
            "side": "BUY",
            "qty": qty,
            "price": close_entry,
            "timestamp": last_row_entry["timestamp"],
            "rsi_at_entry": float(rsi_val) if rsi is not None else None,
        }
        logger.info(f"Entry signal generated: {signal}")
        return signal

    async def evaluate_price_exit(self, parent_order_id: int, last_price: float):
        """Exit based on price (stub)."""
        return None

    async def evaluate_candle_exit(self, parent_order_id: int, history: dict):
        """Exit based on candle history (stub)."""
        return None

    async def evaluate_stoploss_exit(self, spot_df_sl: pd.DataFrame, spot_df_confirm_sl: pd.DataFrame, entry_signal: dict) -> Optional[dict]:
        """
        Evaluate stoploss exit for CE:
        - Use stoploss config timeframe and swing settings to find latest swing low.
        - SL is updated to latest swing low (trailing if enabled).
        - Exit if close < swing low + sl_buffer, and next 1-min candle closes below previous close.
        - If trailing is enabled, SL is adjusted upward for every new higher swing low.
        - Returns exit signal dict if exit condition met, else None.
        """
        if spot_df_sl is None or len(spot_df_sl) < 2 or spot_df_confirm_sl is None or len(spot_df_confirm_sl) < 2:
            logger.info("Not enough spot data for stoploss evaluation.")
            return None
        # Calculate pivots and get last swing points every call (stoploss timeframe)
        swing_df = swing_utils.find_hhlh_pivots(
            spot_df_sl,
            left_bars=self.stoploss_swing_left_bars,
            right_bars=self.stoploss_swing_right_bars
        )
        _, last_ll, _, _ = swing_utils.get_last_swing_points(swing_df)
        if not last_ll:
            logger.info("No LL pivot available for stoploss evaluation.")
            return None
        sl_buffer = self.stoploss_sl_buffer
        # 1. Compute stoploss level: swing low + sl_buffer
        sl_level = last_ll['price'] + sl_buffer
        last_row_sl = spot_df_sl.iloc[-1]
        close_sl = last_row_sl["close"]
        # 2. Exit if close < sl_level
        if close_sl >= sl_level:
            logger.info(f"No stoploss exit: close={close_sl}, sl_level={sl_level}")
            return None
        # 3. Confirmation candle logic (1-min candle closes below previous close)
        last_row_confirm = spot_df_confirm_sl.iloc[-1]
        prev_close_confirm = spot_df_confirm_sl.iloc[-2]["close"]
        close_confirm = last_row_confirm["close"]
        if close_confirm >= prev_close_confirm:
            logger.info(f"Stoploss confirmation failed: close={close_confirm} >= prev_close={prev_close_confirm}")
            return None
        # 4. Trailing logic: if enabled, SL is updated upward for every new higher swing low
        # (This is handled by always using latest swing low)
        qty = entry_signal["qty"] if entry_signal else None
        signal = {
            "symbol": self.symbol,
            "side": "SELL",
            "qty": qty,
            "price": close_sl,
            "timestamp": last_row_sl["timestamp"],
            "sl_level": sl_level,
        }
        logger.info(f"Stoploss exit signal generated: {signal}")
        return signal

    async def monitor_stoploss_loop(self, entry_signal: dict):
        """
        After entry, periodically fetch new spot history every X (stoploss timeframe) minutes
        and evaluate stoploss exit logic. Stops when stoploss exit is triggered.
        - Uses stoploss config for timeframe, swing, buffer, and confirmation tf.
        - All spot data is fetched fresh each cycle.
        - Logs all config usage and actions.
        """
        import asyncio
        from algosat.common import strategy_utils
        symbol = self.symbol
        stoploss_tf = self.stoploss_timeframe
        confirm_tf = self.stoploss_confirmation_tf
        interval_minutes = int(stoploss_tf.replace("m", "")) if stoploss_tf.endswith("m") else 3
        confirm_minutes = int(confirm_tf.replace("m", "")) if confirm_tf.endswith("m") else 1
        logger.info(f"Starting stoploss monitoring loop: stoploss_tf={stoploss_tf}, confirm_tf={confirm_tf}")
        last_exit_signal = None
        while True:
            now = pd.Timestamp.now(tz="Asia/Kolkata")
            # Fetch stoploss timeframe spot history (enough bars for swing calc)
            sl_bars = max(self.stoploss_swing_left_bars, self.stoploss_swing_right_bars) + 3
            from_date_sl = now - pd.Timedelta(minutes=interval_minutes * sl_bars)
            to_date_sl = now
            spot_history_dict_sl = await strategy_utils.fetch_strikes_history(
                self.data_manager, [symbol], from_date_sl, to_date_sl, interval_minutes, ins_type=self.instrument, cache=False
            )
            spot_history_sl = spot_history_dict_sl.get(symbol)
            spot_df_sl = pd.DataFrame(spot_history_sl) if spot_history_sl else None
            # Fetch confirmation tf spot history (last 2 bars)
            from_date_confirm = now - pd.Timedelta(minutes=confirm_minutes * 2)
            to_date_confirm = now
            spot_history_dict_confirm = await strategy_utils.fetch_strikes_history(
                self.data_manager, [symbol], from_date_confirm, to_date_confirm, confirm_minutes, ins_type=self.instrument, cache=False
            )
            spot_history_confirm = spot_history_dict_confirm.get(symbol)
            spot_df_confirm = pd.DataFrame(spot_history_confirm) if spot_history_confirm else None
            # Evaluate stoploss exit
            exit_signal = await self.evaluate_stoploss_exit(spot_df_sl, spot_df_confirm, entry_signal)
            if exit_signal:
                logger.info(f"Stoploss exit triggered: {exit_signal}")
                # Place exit order (integrate with order_manager if needed)
                # await self.place_exit_order(exit_signal)  # Implement as needed
                last_exit_signal = exit_signal
                break
            logger.info(f"No stoploss exit. Sleeping for {interval_minutes} minutes.")
            await asyncio.sleep(interval_minutes * 60)
        return last_exit_signal
