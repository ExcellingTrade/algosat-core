from .exceptions import DataFetchError
from brokers.factory import get_broker
from core.db import AsyncSessionLocal
from core.dbschema import broker_credentials
from sqlalchemy import select
import inspect

class DataProvider:
    """
    Abstracts all data fetching; determines which broker to use for market data.
    Fetches the broker dynamically from DB (where is_data_provider=True).
    Optionally caches the broker to avoid repeated lookups.
    """

    def __init__(self, cache_manager=None):
        self.cache = cache_manager
        self._broker = None  # Cache the broker instance after first lookup

    async def _ensure_broker(self):
        """
        Ensures self._broker is set to the enabled data provider broker.
        """
        if self._broker:
            return
        # Optionally cache broker_name itself for X seconds in process memory
        broker_name = None
        if self.cache:
            broker_name = self.cache.get("data_provider_broker_name", ttl=60)
        if not broker_name:
            # Query DB for the broker with is_data_provider=True and is_enabled=True
            async with AsyncSessionLocal() as sess:
                row = await sess.execute(
                    select(broker_credentials.c.broker_name)
                    .where(broker_credentials.c.is_data_provider == True)
                    .where(broker_credentials.c.is_enabled == True)
                )
                broker_name = row.scalar_one_or_none()
            if not broker_name:
                raise RuntimeError("No broker is configured as data provider (is_data_provider=True)!")
            if self.cache:
                self.cache.set("data_provider_broker_name", broker_name, ttl=60)
        self._broker = get_broker(broker_name)

    async def get_option_chain(self, symbol: str, strike_count: int = 20):
        """Fetch the option chain for a given symbol asynchronously from the data provider broker."""
        await self._ensure_broker()
        try:
            # Broker method can be sync or async
            result = self._broker.get_option_chain(symbol, strike_count)
            chain = await result if inspect.isawaitable(result) else result
            return chain
        except Exception as e:
            raise DataFetchError(f"Failed to fetch option chain for '{symbol}': {e}") from e

    async def get_history(self, symbol: str, strike: float, interval: str):
        """Fetch historical data for a given symbol, strike, and interval asynchronously from the data provider broker."""
        await self._ensure_broker()
        try:
            result = self._broker.get_history(symbol, strike=strike, interval=interval)
            history = await result if inspect.isawaitable(result) else result
            return history
        except Exception as e:
            raise DataFetchError(
                f"Failed to fetch history for symbol='{symbol}', strike={strike}, interval='{interval}': {e}"
            ) from e
