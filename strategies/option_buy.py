from datetime import datetime, time
from typing import Any, Optional

from .base import StrategyBase
from core.data_provider.provider import DataProvider
from core.execution_manager import ExecutionManager
from common.logger import get_logger
from core.dbschema import strategy_configs
from common.strategy_utils import (
    wait_for_first_candle_completion,
    calculate_first_candle_details,
    fetch_option_chain_and_first_candle_history,
    identify_strike_price_combined,
)

logger = get_logger(__name__)

class OptionBuyStrategy(StrategyBase):
    """
    Concrete implementation of the Option Buy strategy.
    Fetches option chain at setup, picks strikes by premium threshold,
    then on each tick evaluates entry and exit signals.
    """

    def __init__(
        self,
        config: Any,
        data_provider: DataProvider,
        execution_manager: ExecutionManager
    ):
        super().__init__(config, data_provider, execution_manager)
        params = getattr(config, "params", {})
        # Time window for entries (HH:MM strings)
        self.start_time = datetime.strptime(params.get("start_time"), "%H:%M").time()
        self.end_time   = datetime.strptime(params.get("end_time"), "%H:%M").time()
        # Premium threshold to select strikes
        self.premium    = params.get("premium", 100)
        # Number of lots / quantity per order
        self.quantity   = params.get("quantity", 1)
        # How many strikes to fetch from chain (if needed)
        self.strike_count = params.get("strike_count", 20)

        # Internal state
        self._strikes = []         # Selected strikes after setup()
        self._position = None      # Track current open position, if any

    async def setup(self) -> None:
        """One-time setup: modular workflow for OptionBuy."""
        if self._strikes:
            return
        params = getattr(self.config, "params", {})
        interval_minutes = params.get("interval_minutes", 5)
        first_candle_time = params.get("first_candle_time", "09:15")
        max_strikes = params.get("max_strikes", 40)
        max_premium = params.get("max_premium", 200)
        symbol = params.get("symbol", self.symbols[0] if self.symbols else None)
        if not symbol:
            logger.error("No symbol configured for OptionBuy strategy.")
            return
        # 1. Wait for first candle completion
        await wait_for_first_candle_completion(interval_minutes, first_candle_time)
        # 2. Calculate first candle data
        candle_times = calculate_first_candle_details(datetime.now().date(), first_candle_time)
        from_date = candle_times["from_date"]
        to_date = candle_times["to_date"]
        # 3. Fetch option chain and first candle history
        broker = self.dp._broker or await self.dp._ensure_broker() or self.dp._broker
        history_data = await fetch_option_chain_and_first_candle_history(
            broker, symbol, interval_minutes, max_strikes, from_date, to_date, bot_name="OptionBuy"
        )
        # 4. Identify strike prices
        ce_strike, pe_strike = identify_strike_price_combined(history_data=history_data, max_premium=max_premium)
        self._strikes = []
        if ce_strike is not None and not ce_strike.empty:
            self._strikes.append(ce_strike.iloc[0]["symbol"])
        if pe_strike is not None and not pe_strike.empty:
            self._strikes.append(pe_strike.iloc[0]["symbol"])
        logger.info(f"Selected strikes for entry: {self._strikes}")

    async def run_tick(self) -> None:
        """Called each polling interval: evaluate entry and exit."""
        await self.setup()

        now_time = datetime.now().time()
        # Skip ticks outside active window
        if not (self.start_time <= now_time <= self.end_time):
            return

        for symbol in self.symbols:
            for strike in self._strikes:
                # Fetch history for this strike
                data = await self.dp.get_history(symbol, strike=strike, interval=self.timeframe)

                if not self._position:
                    # No open position—check for entry
                    order = self.evaluate_signal(data)
                    if order:
                        logger.info(f"Placing entry order: {order}")
                        results = await self.em.execute(self.config, order)
                        logger.info(f"Entry results: {results}")
                        self._position = {"symbol": symbol, "strike": strike}
                else:
                    # Position open—check for exit
                    order = self.evaluate_exit(data, self._position)
                    if order:
                        logger.info(f"Placing exit order: {order}")
                        results = await self.em.execute(self.config, order)
                        logger.info(f"Exit results: {results}")
                        self._position = None

    def evaluate_signal(self, data: Any) -> Optional[dict]:
        """
        Define entry condition.
        Return order payload if conditions met, else None.
        """
        # TODO: implement your signal logic based on 'data'
        # Example placeholder:
        last_price = data[-1].get("close") if data else None
        if last_price and last_price > 0:  # replace with real condition
            return {
                "symbol": self.config.params["symbol"],
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
        # TODO: implement your exit logic
        # Example placeholder: exit after one candle
        return {
            "symbol": position["symbol"],
            "strike": position["strike"],
            "transaction_type": "SELL",
            "quantity": self.quantity,
        }