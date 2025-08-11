from .exceptions import DataFetchError
from algosat.brokers.factory import get_broker
from algosat.core.db import AsyncSessionLocal
from algosat.core.dbschema import broker_credentials
from algosat.core.rate_limiter import get_rate_limiter, RateConfig
from algosat.core.async_retry import async_retry_with_rate_limit, RetryConfig, get_retry_config
from sqlalchemy import select
import inspect
import asyncio
import random
from typing import Dict
from algosat.common.logger import get_logger

logger = get_logger("data_provider")

# Per-broker rate limit settings moved to algosat.core.rate_limiter.py
# Use GlobalRateLimiter.DEFAULT_RATE_CONFIGS for all rate limiting configuration

async def _async_retry(coro_func, *args, max_attempts=3, initial_delay=1, backoff=2, exceptions=(Exception,), **kwargs):
    """Legacy async retry function - DEPRECATED, use async_retry_with_rate_limit instead."""
    attempt = 0
    delay = initial_delay
    while attempt < max_attempts:
        try:
            return await coro_func(*args, **kwargs)
        except exceptions as e:
            attempt += 1
            if attempt >= max_attempts:
                raise
            logger.debug(f"Retry {attempt}/{max_attempts} after error: {e}. Retrying in {delay} seconds...")
            await asyncio.sleep(delay + random.uniform(0, 0.5))
            delay *= backoff

def validate_broker_response(response, expected_type="option_chain", symbol=None):
    """Validate broker API response. Raise DataFetchError if invalid."""
    import pandas as pd
    if expected_type == "option_chain":
        if not (isinstance(response, dict) and response.get("code", response.get("statuscode")) == 200 and response.get("data") and response["data"].get("optionsChain")):
            logger.debug(f"Invalid option chain data received for '{symbol}': {response}")
            raise DataFetchError(f"Invalid option chain data received for '{symbol}'")
    elif expected_type == "history":
        # Accept a DataFrame with at least one row and required columns, or None (means failure)
        if response is None:
            logger.debug(f"No history data received for '{symbol}' (None returned)")
            raise DataFetchError(f"No history data received for '{symbol}'")
        if isinstance(response, pd.DataFrame):
            required_cols = {"timestamp", "open", "high", "low", "close", "volume"}
            if not required_cols.issubset(set(response.columns)) or response.empty:
                logger.debug(f"Invalid DataFrame for history for '{symbol}': columns={response.columns}, empty={response.empty}")
                raise DataFetchError(f"Invalid DataFrame for history for '{symbol}'")
        else:
            logger.debug(f"Invalid history data type for '{symbol}': {type(response)}")
            raise DataFetchError(f"Invalid history data type for '{symbol}'")
    else:
        if not (isinstance(response, dict) and response.get("code", response.get("statuscode")) == 200 and response.get("data")):
            logger.debug(f"Invalid data received for '{symbol}': {response}")
            raise DataFetchError(f"Invalid data received for '{symbol}'")

class DataProvider:
    """
    Abstracts all data fetching; determines which broker to use for market data.
    Fetches the broker dynamically from DB (where is_data_provider=True).
    Uses global rate limiter for coordinated API throttling across components.
    """

    def __init__(self, cache_manager=None):
        self.cache = cache_manager
        self._broker = None  # Cache the broker instance after first lookup
        self._rate_limiter = None  # Will be initialized async

    async def _ensure_broker(self):
        """
        Ensures self._broker is set to the enabled data provider broker.
        Also initializes rate limiter if needed.
        """
        if self._broker:
            return
            
        # Initialize rate limiter if not already done
        if self._rate_limiter is None:
            self._rate_limiter = await get_rate_limiter()
        
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
        # Ensure the broker instance has a .name attribute for logging/rate limiting
        self._broker.name = broker_name
        
        # Configure rate limiter for this broker using global configuration
        from algosat.core.rate_limiter import GlobalRateLimiter
        rate_config = GlobalRateLimiter.get_default_rate_config(broker_name)
        self._rate_limiter.configure_broker(broker_name, rate_config)
        logger.info(f"Configured data provider rate limits for {broker_name}: {rate_config.rps} rps, burst: {rate_config.burst}")

    async def get_option_chain(self, symbol: str, strike_count: int = 20):
        """Fetch the option chain for a given symbol asynchronously from the data provider broker."""
        await self._ensure_broker()
        broker_name = self._broker.name
        
        async def _fetch():
            async with self._rate_limiter.acquire(broker_name, tokens=1):
                result = self._broker.get_option_chain(symbol, strike_count)
                option_chain = await result if inspect.isawaitable(result) else result
                validate_broker_response(option_chain, expected_type="option_chain", symbol=symbol)
                return option_chain
        
        # Use enhanced retry with rate limiting
        retry_config = get_retry_config("data_fetch")
        retry_config.rate_limit_broker = broker_name
        retry_config.rate_limit_tokens = 1
        
        try:
            return await async_retry_with_rate_limit(_fetch, config=retry_config)
        except Exception as e:
            logger.error(f"Failed to fetch option chain for '{symbol}': {e}")
            raise DataFetchError(f"Failed to fetch option chain for '{symbol}': {e}") from e

    async def get_history(self, symbol: str, from_date, to_date, ohlc_interval=1, ins_type="EQ"):
        """Fetch historical data for a given symbol and parameters asynchronously from the data provider broker."""
        await self._ensure_broker()
        broker_name = self._broker.name
        
        async def _fetch():
            async with self._rate_limiter.acquire(broker_name, tokens=1):
                result = self._broker.get_history(
                    symbol,
                    from_date,
                    to_date,
                    ohlc_interval=ohlc_interval,
                    ins_type=ins_type
                )
                history = await result if inspect.isawaitable(result) else result
                validate_broker_response(history, expected_type="history", symbol=symbol)
                return history
        
        # Use enhanced retry with rate limiting
        retry_config = get_retry_config("data_fetch")
        retry_config.rate_limit_broker = broker_name
        retry_config.rate_limit_tokens = 1
        
        try:
            return await async_retry_with_rate_limit(_fetch, config=retry_config)
        except Exception as e:
            logger.debug(f"Failed to fetch history for symbol='{symbol}', from_date={from_date}, to_date={to_date}, ohlc_interval={ohlc_interval}, ins_type={ins_type}: {e}")
            raise DataFetchError(
                f"Failed to fetch history for symbol='{symbol}', from_date={from_date}, to_date={to_date}, ohlc_interval={ohlc_interval}, ins_type={ins_type}: {e}"
            ) from e

# Singleton instance for application-wide use
_data_provider_instance: DataProvider = None

def get_data_provider(cache_manager=None) -> DataProvider:
    """
    Return a shared DataProvider instance. 
    If not already created, initializes one with the optional cache_manager.
    """
    global _data_provider_instance
    if _data_provider_instance is None:
        _data_provider_instance = DataProvider(cache_manager)
    return _data_provider_instance
