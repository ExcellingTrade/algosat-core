from abc import ABC, abstractmethod
from typing import Any, Dict, List
import datetime
from .models import BalanceSummary

class BrokerInterface(ABC):
    async def check_margin_availability(self, broker, total_qty, *order_params_list):
        """
        Check if the sufficient margin is available before placing the trade.
        Should be implemented by broker wrappers that support margin checks.
        """
        raise NotImplementedError
    """
    Abstract base class defining the contract for all broker wrappers.
    Using Python's built-in `abc` module, this declares methods that
    every concrete broker implementation must override.
    """

    @abstractmethod
    async def login(self) -> None:
        """
        Perform login to the broker's platform and initialize any required
        session state (e.g., cookies, tokens).
        """
        ...

    @abstractmethod
    async def place_order(self, order_payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Place an order with the given payload.
        Returns a dict containing the broker's response (order ID, status, etc.).
        """
        ...

    @abstractmethod
    async def get_positions(self) -> List[Dict[str, Any]]:
        """
        Retrieve current open positions from the broker.
        Returns a list of position dictionaries.
        """
        ...

    @abstractmethod
    async def get_history(self, symbol: str, **kwargs: Any) -> Any:
        """
        Fetch historical market data for the given symbol.
        Keyword args can include timeframe, date ranges, etc.
        Returns raw data (e.g., list of OHLCV points).
        """
        ...

    @abstractmethod
    async def get_profile(self) -> Dict[str, Any]:
        """
        Retrieve user profile information from the broker.
        Returns a dict containing profile data.
        """
        ...

    @abstractmethod
    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch a full quote for the given symbol.
        """
        pass

    @abstractmethod
    async def get_ltp(self, symbol: str) -> Any:
        """
        Fetch the last traded price for the given symbol.
        """
        pass

    @abstractmethod
    async def get_strike_list(
        self,
        symbol: str,
        expiry: datetime.date,
        atm_count: int,
        itm_count: int,
        otm_count: int
    ) -> List[str]:
        """
        Return a list of tradingsymbols or tokens for CE and PE strikes:
        ATM, ITM, and OTM based on counts.
        """
        pass

    @abstractmethod
    async def get_order_details(self) -> list[dict]:
        """
        Fetch all order details for the current account/session from the broker.
        Returns a list of order dicts (structure broker-specific).
        """
        ...

    @abstractmethod
    async def get_balance(self, *args, **kwargs) -> dict:
        """
        Fetch account balance (raw API response).
        """
        ...

    @abstractmethod
    async def get_balance_summary(self, *args, **kwargs) -> BalanceSummary:
        """
        Return summary: total_balance, available, utilized (standardized output).
        """
        ...

    @abstractmethod
    async def cancel_order(self, *args, **kwargs):
        """
        Cancel an order. Arguments depend on broker implementation.
        """
        pass

    @abstractmethod
    async def check_margin_availability(self, broker, total_qty, *order_params_list):
        """
        Check if the sufficient margin is available before placing the trade.
        Should be implemented by broker wrappers that support margin checks.
        """
        pass