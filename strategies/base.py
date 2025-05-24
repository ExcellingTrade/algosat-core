from abc import ABC, abstractmethod
from typing import Any, Optional
from core.data_manager import DataManager


class StrategyBase(ABC):
    """
    Abstract base class for trading strategies.
    """

    def __init__(self, config: Any, data_manager: DataManager, execution_manager: Any):
        """
        :param config: StrategyConfig object or dict containing 'params' JSON and other settings.
        :param data_manager: DataManager instance for market data access.
        :param execution_manager: ExecutionManager instance for order placement.
        """
        self.config = config
        self.dp = data_manager
        self.em = execution_manager

        # Extract top-level fields
        self.exchange = getattr(config, "exchange", None) or config.get("exchange")
        self.instrument = getattr(config, "instrument", None) or config.get("instrument")
        self.trade = getattr(config, "trade", None) or config.get("trade", {})
        self.indicators = getattr(config, "indicators", None) or config.get("indicators", {})
        # Compute symbol from config fields
        trade_symbol = self.trade.get("symbol") or getattr(config, "symbol", None) or config.get("symbol")
        self.trade_symbol = trade_symbol
        self.symbol = trade_symbol  # For backward compatibility, but do not format here
        # Do not format symbol here; let BrokerManager/DataManager handle it
        # Timeframe and poll_interval can be in trade dict
        self.timeframe: str = self.trade.get("timeframe", "1m")
        self.poll_interval: int = self.trade.get("poll_interval", 60)

    async def setup(self) -> None:
        """
        One-time setup before the main polling loop.
        For example, fetch and cache initial data.
        Concrete strategies may override.
        """
        pass

    @abstractmethod
    async def process_cycle(self) -> None:
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
