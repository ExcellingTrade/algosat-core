from typing import Any, Optional
import pandas as pd
from algosat.strategies.base import StrategyBase
from algosat.common.logger import get_logger
from algosat.common import swing_utils
import asyncio

logger = get_logger(__name__)

class SwingHighLowBuyStrategy(StrategyBase):
    """
    Concrete implementation of a Swing High/Low breakout buy strategy.
    Modularized and standardized to match option_buy.py structure.
    """
    def __init__(self, config, data_manager, execution_manager):
        super().__init__(config, data_manager, execution_manager)
        # Standardized config/state
        self.symbol = self.cfg.symbol
        self.exchange = self.cfg.exchange
        self.instrument = self.cfg.instrument
        self.trade = self.cfg.trade
        self.indicators = self.cfg.indicators
        self.order_manager = execution_manager
        # Internal state
        self._strikes = []
        self._positions = {}  # open positions by strike
        self._setup_failed = False
        self._hh_levels = []
        self._ll_levels = []
        # For easy reference in evaluate_signal
        self._entry_cfg = self.trade.get("entry", {})
        self._stoploss_cfg = self.trade.get("stoploss", {})
        logger.info(f"SwingHighLowBuyStrategy config: {self.trade}")
    
    async def ensure_broker(self):
        # No longer needed for data fetches, but keep for order placement if required
        await self.dp._ensure_broker()

    async def setup(self) -> None:
        """
        One-time setup: cache required swing pivots for the entry timeframe.
        """
        try:
            entry_cfg = self._entry_cfg
            entry_timeframe = entry_cfg.get("timeframe", "5m")
            entry_swing_left_bars = entry_cfg.get("swing_left_bars", 3)
            entry_swing_right_bars = entry_cfg.get("swing_right_bars", 3)
            from algosat.common.strategy_utils import get_trade_day, get_ist_datetime, calculate_first_candle_details
            trade_day = get_trade_day(get_ist_datetime())
            interval_minutes = int(entry_timeframe.replace("m", "")) if entry_timeframe.endswith("m") else 5
            first_candle_time = self.trade.get("first_candle_time", "09:15")
            candle_times = calculate_first_candle_details(trade_day.date(), first_candle_time, interval_minutes)
            from_date = candle_times["from_date"]
            to_date = candle_times["to_date"]
            from algosat.common import strategy_utils
            spot_history_dict = await strategy_utils.fetch_instrument_history(
                self.dp, [self.symbol], from_date, to_date, interval_minutes, ins_type=self.instrument, cache=True
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
            # Compute and cache swing pivots
            indicators = self.compute_indicators(df, entry_cfg)
            self._hh_levels = indicators.get("hh_levels", [])
            self._ll_levels = indicators.get("ll_levels", [])
            logger.info(f"Identified {len(self._hh_levels)} HH and {len(self._ll_levels)} LL pivots for {self.symbol} (entry config)")
            self._strikes = self.select_strikes_from_pivots()
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
        Main signal evaluation cycle:
        - Fetch entry and confirmation timeframe spot data.
        - Identify breakout as per swing logic.
        - Use confirmation logic (N confirmation candles above swing high).
        - On signal, call process_order.
        Returns order info dict if an order is placed, else None.
        """
        try:
            if self._setup_failed or not self._strikes:
                logger.warning("process_cycle aborted: setup failed or no strikes available.")
                return None
            entry_cfg = self._entry_cfg
            confirm_cfg = self.trade.get("confirmation", {})
            entry_tf = entry_cfg.get("timeframe", "5m")
            confirm_tf = confirm_cfg.get("timeframe", "1m")
            entry_minutes = int(entry_tf.replace("m", "")) if entry_tf.endswith("m") else 5
            confirm_minutes = int(confirm_tf.replace("m", "")) if confirm_tf.endswith("m") else 1
            n_confirm = confirm_cfg.get("candles", 1)
            from algosat.common import strategy_utils
            now = pd.Timestamp.now(tz="Asia/Kolkata")
            # Fetch entry timeframe spot data
            from_date_entry = now - pd.Timedelta(minutes=entry_minutes * (max(entry_cfg.get("swing_left_bars", 3), entry_cfg.get("swing_right_bars", 3)) + 3))
            to_date_entry = now
            spot_history_dict_entry = await strategy_utils.fetch_instrument_history(
                self.data_manager, [self.symbol], from_date_entry, to_date_entry, entry_minutes, cache=False
            )
            spot_entry = spot_history_dict_entry.get(self.symbol)
            spot_df_entry = pd.DataFrame(spot_entry) if spot_entry else None
            # Fetch confirmation timeframe spot data (last n_confirm+1 bars)
            from_date_confirm = now - pd.Timedelta(minutes=confirm_minutes * (n_confirm + 1))
            to_date_confirm = now
            spot_history_dict_confirm = await strategy_utils.fetch_instrument_history(
                self.data_manager, [self.symbol], from_date_confirm, to_date_confirm, confirm_minutes, ins_type=self.instrument, cache=False
            )
            spot_confirm = spot_history_dict_confirm.get(self.symbol)
            spot_df_confirm = pd.DataFrame(spot_confirm) if spot_confirm else None
            # Only use the first strike for now (ATM)
            strike = self._strikes[0] if self._strikes else None
            # Evaluate signal
            signal_payload = self.evaluate_signal(spot_df_entry, spot_df_confirm, entry_cfg, strike)
            # Place order if signal
            order_info = await self.process_order(signal_payload, strike)
            if order_info:
                self._positions[strike] = [order_info]
                return order_info
            return None
        except Exception as e:
            logger.error(f"Error in process_cycle: {e}", exc_info=True)
            return None

    async def process_order(self, signal_payload, strike):
        """
        Place an order using the order_manager, passing config as in option_buy.py.
        Returns order info dict if an order is placed, else None.
        """
        if signal_payload:
            ts = signal_payload.get('timestamp', 'N/A')
            logger.info(f"Signal formed for {strike} at {ts}: {signal_payload}")
            # Compose order request
            order_request = {
                "symbol": signal_payload.get("symbol", self.symbol),
                "strike": signal_payload.get("strike", strike),
                "side": signal_payload.get("side", "BUY"),
                "qty": signal_payload.get("qty"),
                "price": signal_payload.get("price"),
                "order_type": self.trade.get("order_type", "MARKET"),
            }
            result = await self.order_manager.place_order(
                self.cfg,
                order_request,
                strategy_name=None
            )
            if result:
                logger.info(f"Order placed successfully: {result}")
                return {**order_request, **result}
            else:
                logger.error(f"Order placement failed: {result}")
        else:
            logger.debug(f"No signal for {strike}.")
        return None

    def evaluate_signal(self, spot_df_entry: pd.DataFrame, spot_df_confirm: pd.DataFrame, config: dict, strike: str) -> Optional[dict]:
        """
        Evaluate entry signal for CE:
        - Detect breakout: price must close above last swing high + entry_buffer (from entry config) on entry timeframe.
        - Require N confirmation candles (from confirmation config) that close above swing high.
        - Only after both conditions are met, generate an entry signal (with price, strike, qty, etc).
        - Uses spot data only for swing high detection.
        """
        if spot_df_entry is None or len(spot_df_entry) < 2 or spot_df_confirm is None or len(spot_df_confirm) < 2:
            logger.info("Not enough spot data for signal evaluation.")
            return None
        # Calculate pivots and get last swing points every call (entry timeframe)
        entry_left = config.get("swing_left_bars", 3)
        entry_right = config.get("swing_right_bars", 3)
        swing_df = swing_utils.find_hhlh_pivots(
            spot_df_entry,
            left_bars=entry_left,
            right_bars=entry_right
        )
        last_hh, _, _, _ = swing_utils.get_last_swing_points(swing_df)
        if not last_hh:
            logger.info("No HH pivot available for signal evaluation.")
            return None
        entry_buffer = config.get("entry_buffer", 0)
        last_row_entry = spot_df_entry.iloc[-1]
        close_entry = last_row_entry["close"]
        breakout = close_entry > (last_hh['price'] + entry_buffer)
        if not breakout:
            logger.info(f"No breakout: close={close_entry}, last_hh+buffer={last_hh['price'] + entry_buffer}")
            return None
        # Confirmation logic: require N confirmation candles above swing high
        confirm_cfg = self.trade.get("confirmation", {})
        n_confirm = confirm_cfg.get("candles", 1)
        confirm_ok = True
        if n_confirm > 0 and len(spot_df_confirm) >= n_confirm:
            last_hh_price = last_hh['price'] + entry_buffer
            for i in range(-n_confirm, 0):
                if spot_df_confirm.iloc[i]["close"] <= last_hh_price:
                    confirm_ok = False
                    break
        if not confirm_ok:
            logger.info(f"Confirmation failed: not all last {n_confirm} closes above {last_hh['price'] + entry_buffer}")
            return None
        # Only enter if not already in position for this strike
        if self._positions.get(strike):
            logger.info(f"Position already open for {strike}, skipping entry.")
            return None
        # Compose entry signal dict
        ce_lot_qty = self.trade.get("ce_lot_qty", 2)
        lot_size = self.trade.get("lot_size", 75)
        qty = ce_lot_qty * lot_size
        signal = {
            "symbol": self.symbol,
            "strike": strike,
            "side": "BUY",
            "qty": qty,
            "price": close_entry,
            "timestamp": last_row_entry["timestamp"],
        }
        # RSI ignore logic (entry)
        rsi_ignore_above = config.get("rsi_ignore_above", 80)
        rsi_period = self.indicators.get("rsi_period", 14)
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
            signal["rsi_at_entry"] = float(rsi_val)
        logger.info(f"Entry signal generated: {signal}")
        return signal

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
