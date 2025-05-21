"""Market data caching and rate-limiting utilities."""

import asyncio
import shelve
from datetime import datetime, timedelta
from cachetools import TTLCache
import inspect
import pandas as pd
from common.logger import get_logger

logger = get_logger("data_manager")

async def _async_retry(coro_func, *args, max_attempts=3, initial_delay=1, backoff=2, exceptions=(Exception,), **kwargs):
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
            await asyncio.sleep(delay)
            delay *= backoff

############################################################
# Per-broker rate limit settings: requests per second
_RATE_LIMITS = {
    "fyers": 10,
    "angel": 5,
    "zerodha": 5,
}
############################################################

class _CacheManager:
    """
    A hybrid in-memory + persistent disk cache manager.
    """
    def __init__(self, maxsize=512, shelve_path="/tmp/algosat_cache.db"):
        self.caches = {}
        self.maxsize = maxsize
        self.shelve_path = shelve_path

    def get_cache(self, ttl: int):
        if ttl not in self.caches:
            self.caches[ttl] = TTLCache(maxsize=self.maxsize, ttl=ttl)
        return self.caches[ttl]

    def get(self, key, ttl=60):
        # Check in-memory
        cache = self.get_cache(ttl)
        if key in cache:
            return cache[key]
        # Check shelve
        with shelve.open(self.shelve_path) as db:
            return db.get(key)

    def set(self, key, value, ttl=60):
        cache = self.get_cache(ttl)
        cache[key] = value
        with shelve.open(self.shelve_path) as db:
            db[key] = value

    @staticmethod
    def seconds_until_midnight_ist():
        now = datetime.utcnow() + timedelta(hours=5, minutes=30)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return int((tomorrow - now).total_seconds())

class _RateLimiter:
    def __init__(self, max_calls, interval_sec):
        self.semaphore = asyncio.Semaphore(max_calls)
        self.interval = interval_sec

    async def __aenter__(self):
        await self.semaphore.acquire()

    async def __aexit__(self, exc_type, exc, tb):
        await asyncio.sleep(self.interval)
        self.semaphore.release()


# Build the per-broker rate limiter map
rate_limiter_map = {
    broker_name: _RateLimiter(max_calls=limit, interval_sec=1)
    for broker_name, limit in _RATE_LIMITS.items()
}

# To use per-broker rate limiting, pass `rate_limiter_map=rate_limiter_map` when creating your DataManager:
# Example:
# data_manager = DataManager(
#     broker=...,                # your broker instance
#     broker_name=...,           # broker name string (e.g., "fyers")
#     broker_manager=...,        # your broker manager
#     rate_limiter_map=rate_limiter_map,
# )

def validate_broker_response(response, expected_type="option_chain", symbol=None):
    """Validate broker API response. Raise ValueError if invalid."""
    if expected_type == "option_chain":
        if not (isinstance(response, dict) and response.get("code", response.get("statuscode")) == 200 and response.get("data") and response["data"].get("optionsChain")):
            logger.debug(f"Invalid option chain data received for '{symbol}': {response}")
            raise ValueError(f"Invalid option chain data received for '{symbol}'")
    elif expected_type == "history":
        if response is None:
            logger.debug(f"No history data received for '{symbol}' (None returned)")
            raise ValueError(f"No history data received for '{symbol}'")
        if isinstance(response, pd.DataFrame):
            required_cols = {"timestamp", "open", "high", "low", "close", "volume"}
            if not required_cols.issubset(set(response.columns)) or response.empty:
                logger.debug(f"Invalid DataFrame for history for '{symbol}': columns={response.columns}, empty={response.empty}")
                raise ValueError(f"Invalid DataFrame for history for '{symbol}'")
        else:
            logger.debug(f"Invalid history data type for '{symbol}': {type(response)}")
            raise ValueError(f"Invalid history data type for '{symbol}'")
    else:
        if not (isinstance(response, dict) and response.get("code", response.get("statuscode")) == 200 and response.get("data")):
            logger.debug(f"Invalid data received for '{symbol}': {response}")
            raise ValueError(f"Invalid data received for '{symbol}'")

class DataManager:
    """
    Central data manager responsible for broker API access,
    per-broker rate-limiting, and caching.
    """
    def __init__(self, broker=None, broker_name=None, cache=None, rate_limiter=None, rate_limiter_map=None, broker_manager=None):
        self.broker = broker
        self.broker_name = broker_name
        self.broker_manager = broker_manager
        self.cache = cache or _CacheManager()
        self.rate_limiter = rate_limiter or _RateLimiter(max_calls=10, interval_sec=1)
        self.rate_limiter_map = rate_limiter_map or {}

    def get_current_broker_name(self):
        if self.broker_name:
            return self.broker_name
        # Try to get name from broker object if possible
        if self.broker and hasattr(self.broker, "name"):
            return self.broker.name
        return None

    def get_active_rate_limiter(self):
        broker_name = self.get_current_broker_name()
        if broker_name and broker_name in self.rate_limiter_map:
            return self.rate_limiter_map[broker_name]
        return self.rate_limiter

    async def ensure_broker(self):
        if self.broker:
            return
        if self.broker_manager:
            # Always use get_data_broker for unified broker selection logic
            self.broker = self.broker_manager.get_data_broker(broker_name=self.broker_name)
        if not self.broker:
            raise RuntimeError("No broker available for DataManager!")

    async def get_option_chain(self, symbol, expiry=None, ttl=120):
        await self.ensure_broker()
        cache_key = f"option_chain:{symbol}:{expiry}"
        cached = self.cache.get(cache_key, ttl=ttl)
        if cached is not None:
            return cached
        async def _fetch():
            async with self.get_active_rate_limiter():
                result = self.broker.get_option_chain(symbol, expiry)
                option_chain = await result if inspect.isawaitable(result) else result
                validate_broker_response(option_chain, expected_type="option_chain", symbol=symbol)
                self.cache.set(cache_key, option_chain, ttl=ttl)
                return option_chain
        return await _async_retry(_fetch)

    async def get_history(self, symbol, from_date, to_date, ohlc_interval, ins_type="", ttl=600, cache=True):
        await self.ensure_broker()
        cache_key = f"history:{symbol}:{from_date}:{to_date}:{ohlc_interval}:{ins_type}"
        if cache:
            cached = self.cache.get(cache_key, ttl=ttl)
            if cached is not None:
                logger.info(f"Cache hit for history: {cache_key}") 
                return cached
        async def _fetch():
            async with self.get_active_rate_limiter():
                result = self.broker.get_history(symbol, from_date, to_date, ohlc_interval, ins_type)
                history = await result if inspect.isawaitable(result) else result
                validate_broker_response(history, expected_type="history", symbol=symbol)
                if cache:
                    self.cache.set(cache_key, history, ttl=ttl)
                return history
        return await _async_retry(_fetch)


# Example: instantiate a global DataManager with per-broker rate limiting
# (Replace ... with actual broker and broker_manager if using as singleton)
# data_manager = DataManager(
#     broker=...,                # your broker instance
#     broker_name=...,           # broker name string (e.g., "fyers")
#     broker_manager=...,        # your broker manager
#     rate_limiter_map=rate_limiter_map,
# )
