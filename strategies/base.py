from abc import ABC, abstractmethod
from typing import Any, Optional


class StrategyBase(ABC):
    """
    Abstract base class for trading strategies.
    """

    def __init__(self, config: Any, data_provider: Any, execution_manager: Any):
        """
        :param config: StrategyConfig object or dict containing 'params' JSON and other settings.
        :param data_provider: DataProvider instance for market data access.
        :param execution_manager: ExecutionManager instance for order placement.
        """
        self.config = config
        self.dp = data_provider
        self.em = execution_manager

        # Extract common parameters from config.params (or config['params'])
        params = None
        try:
            if hasattr(config, "params"):
                params = getattr(config, "params", {})
            elif isinstance(config, dict):
                params = config.get("params", {})
            else:
                params = {}
        except Exception as e:
            import logging

            logging.error(f"Error extracting params from config: {e}")
            params = {}
        self.params = params
        # Timeframe for candles, e.g. '1m', '5m', etc.
        self.timeframe: str = params.get("timeframe", "1m")
        # Poll interval in seconds between run_tick calls (overrides strategy_manager if set)
        self.poll_interval: int = params.get("poll_interval", 60)
        # Strategy symbol(s)
        # Accepts either a list of symbols or a single symbol (from DB schema)
        if "symbols" in params and isinstance(params["symbols"], list):
            self.symbols = params["symbols"]
        elif "symbol" in params:
            self.symbols = [params["symbol"]]
        else:
            self.symbols = []

    async def setup(self) -> None:
        """
        One-time setup before the main polling loop.
        For example, fetch and cache initial data.
        Concrete strategies may override.
        """
        pass

    @abstractmethod
    async def run_tick(self) -> None:
        """
        Called once per candle (per poll interval).
        Should:
          1. Fetch necessary data via self.dp (e.g., option chain, history).
          2. Call evaluate_signal and place entry orders.
          3. Call evaluate_exit and place exit orders.
        """
        ...

    @abstractmethod
    def evaluate_signal(self, data: Any) -> Optional[dict]:
        """
        Evaluate entry conditions based on fetched data.
        Return an order payload dict if entry condition is met, otherwise None.
        """
        ...

    @abstractmethod
    def evaluate_exit(self, data: Any, position: Any) -> Optional[dict]:
        """
        Evaluate exit conditions based on fetched data and current position.
        Return an order payload dict if exit condition is met, otherwise None.
        """
        ...
