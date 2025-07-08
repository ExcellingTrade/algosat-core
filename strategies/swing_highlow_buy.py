from typing import Any, Optional
from algosat.strategies.base import StrategyBase
from algosat.common.logger import get_logger
from algosat.common import swing_utils
import pandas as pd

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
        # Parse all required fields from config
        self.entry_cfg = self.trade.get("entry", {})
        self.stoploss_cfg = self.trade.get("stoploss", {})
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

    async def setup(self) -> None:
        """
        One-time setup for the strategy: fetch historical data, calculate swing highs/lows,
        and select relevant strikes for trading. Sets _setup_failed if unable to proceed.
        """
        try:
            # --- Calculate trade day and time window (reuse OptionBuy logic) ---
            from algosat.common.strategy_utils import get_trade_day, get_ist_datetime, calculate_first_candle_details
            trade_day = get_trade_day(get_ist_datetime())
            interval_minutes = self.trade.get("interval_minutes", 5)
            first_candle_time = self.trade.get("first_candle_time", "09:15")
            lookback = self.trade.get("lookback", 100)
            candle_times = calculate_first_candle_details(trade_day.date(), first_candle_time, interval_minutes)
            from_date = candle_times["from_date"]
            to_date = candle_times["to_date"]
            # --- Fetch spot history using strategy_utils.fetch_strikes_history (for spot, pass [self.symbol]) ---
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
            # Ensure columns: ['timestamp', 'open', 'high', 'low', 'close', 'volume']
            if not all(col in df.columns for col in ["timestamp", "high", "low", "close"]):
                logger.error("Missing required columns in OHLCV data")
                self._setup_failed = True
                return
            # Calculate swing pivots using swing_utils
            swing_df = swing_utils.find_hhlh_pivots(df)
            # Extract only HH and LL pivots
            hh_points = swing_df[swing_df["is_HH"]]
            ll_points = swing_df[swing_df["is_LL"]]
            self._hh_levels = hh_points[["timestamp", "zz"]].to_dict("records")
            self._ll_levels = ll_points[["timestamp", "zz"]].to_dict("records")
            logger.info(f"Identified {len(self._hh_levels)} HH and {len(self._ll_levels)} LL pivots for {self.symbol}")
            # Optionally: select strikes based on latest HH/LL or other logic
            # self._strikes = self.select_strikes_from_pivots()
        except Exception as e:
            logger.error(f"SwingHighLowBuyStrategy setup failed: {e}", exc_info=True)
            self._setup_failed = True

    async def process_cycle(self) -> Optional[dict]:
        """Main signal evaluation cycle (stub)."""
        return None

    def evaluate_signal(self, data, config: dict, strike: str) -> Optional[Any]:
        """Entry signal logic (stub)."""
        return None

    async def evaluate_price_exit(self, parent_order_id: int, last_price: float):
        """Exit based on price (stub)."""
        return None

    async def evaluate_candle_exit(self, parent_order_id: int, history: dict):
        """Exit based on candle history (stub)."""
        return None
