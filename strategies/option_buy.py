from datetime import datetime, time
from typing import Any, Optional

from .base import StrategyBase
from common.logger import get_logger
from core.execution_manager import ExecutionManager
from core.data_provider.provider import DataProvider
from core.dbschema import strategy_configs
from common.strategy_utils import (
    wait_for_first_candle_completion,
    calculate_first_candle_details,
    fetch_option_chain_and_first_candle_history,
    identify_strike_price_combined,
    fetch_strikes_history,
)
from common.broker_utils import get_trade_day
from utils.utils import get_ist_datetime  # Use get_data_provider for type hints if needed

logger = get_logger(__name__)

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
        self.broker = None  # Will hold the initialized broker instance
        self.premium = trade.get("premium", 100)
        self.quantity = trade.get("quantity", 1)
        self.strike_count = trade.get("strike_count", 20)
        # Internal state
        self._strikes = []         # Selected strikes after setup()
        self._position = None      # Track current open position, if any

    async def ensure_broker(self):
        if self.broker is None:
            await self.dp._ensure_broker()
            self.broker = self.dp._broker

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
        candle_times = calculate_first_candle_details(trade_day.date(), first_candle_time, interval_minutes)
        from_date = candle_times["from_date"]
        to_date = candle_times["to_date"]
        # Ensure broker is initialized only once
        await self.ensure_broker()
        # 3. Fetch option chain and first candle history
        history_data = await fetch_option_chain_and_first_candle_history(
            self.broker, symbol, interval_minutes, max_strikes, from_date, to_date, bot_name="OptionBuy"
        )
        # 4. Identify strike prices
        ce_strike, pe_strike = identify_strike_price_combined(history_data=history_data, max_premium=max_premium)
        self._strikes = []
        if ce_strike is not None:
            self._strikes.append(ce_strike)
        if pe_strike is not None:
            self._strikes.append(pe_strike)
        logger.info(f"Selected strikes for entry: {self._strikes}")

    async def run_tick(self) -> None:
        """Called each polling interval: evaluate entry and exit."""
        await self.ensure_broker()
        await self.setup()

        now_time = get_ist_datetime().time()
        # Only check time window if both are set
        if self.start_time and self.end_time:
            if not (self.start_time <= now_time <= self.end_time):
                return

        # Use strategy_utils.fetch_strikes_history to fetch all strikes' history in batch
        if not self._strikes:
            return
        # Fetch all strike histories in parallel with progress bar
        history_data_list = await fetch_strikes_history(
            self.broker,  # Use the initialized broker
            self._strikes,
            from_date=None,  # You may want to pass correct from/to/interval here
            to_date=None,
            interval_minutes=self.config.get('interval_minutes', 5),
            ins_type="EQ"
        )
        # Map strike to its history for easy lookup
        strike_to_history = dict(zip(self._strikes, history_data_list))

        for strike in self._strikes:
            data = strike_to_history.get(strike)
            if not data:
                continue
            if not self._position:
                # No open position—check for entry
                order = self.evaluate_signal(data)
                if order:
                    logger.debug(f"Placing entry order: {order}")
                    results = await self.em.execute(self.config, order)
                    logger.debug(f"Entry results: {results}")
                    self._position = {"symbol": self.symbol, "strike": strike}
            else:
                # Position open—check for exit
                order = self.evaluate_exit(data, self._position)
                if order:
                    logger.debug(f"Placing exit order: {order}")
                    results = await self.em.execute(self.config, order)
                    logger.debug(f"Exit results: {results}")
                    self._position = None

    def evaluate_signal(self, data: Any) -> Optional[dict]:
        """
        Define entry condition.
        Return order payload if conditions met, else None.
        """
        last_price = data[-1].get("close") if data else None
        if last_price and last_price > 0:  # replace with real condition
            return {
                "symbol": self.symbol,
                "strike": self._strikes[0],
                "transaction_type": "BUY",
                "quantity": self.quantity,
            }
        return None

    def evaluate_exit(self, data: Any, position: Any) -> Optional[dict]:
        """
        Define exit condition.
        Return order payload if exit conditions met, else None.
        """
        return {
            "symbol": position["symbol"],
            "strike": position["strike"],
            "transaction_type": "SELL",
            "quantity": self.quantity,
        }