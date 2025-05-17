"""Market data caching and rate-limiting utilities."""

from cachetools import TTLCache
from datetime import datetime, timedelta
import asyncio

class CacheManager:
    """
    A simple in-memory cache manager with TTL (time-to-live) support.
    Suitable for option chain, history, etc.
    """

    def __init__(self, maxsize=512):
        self.caches = {}
        self.maxsize = maxsize

    def get_cache(self, ttl: int):
        """
        Returns a TTLCache instance for a given TTL (seconds).
        Reuses the cache per-TTL to avoid excessive objects.
        """
        if ttl not in self.caches:
            self.caches[ttl] = TTLCache(maxsize=self.maxsize, ttl=ttl)
        return self.caches[ttl]

    def get(self, key, ttl=60):
        """
        Fetch an item from cache (using appropriate TTL bucket).
        """
        cache = self.get_cache(ttl)
        return cache.get(key)

    def set(self, key, value, ttl=60):
        """
        Set an item in cache (using appropriate TTL bucket).
        """
        cache = self.get_cache(ttl)
        cache[key] = value

    @staticmethod
    def seconds_until_midnight_ist():
        """Returns seconds until midnight IST (UTC+5:30)."""
        now = datetime.utcnow() + timedelta(hours=5, minutes=30)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return int((tomorrow - now).total_seconds())

class RateLimiter:
    """
    Async token-bucket rate limiter (e.g., 10 req/sec per broker).
    Use with 'async with' per API call.
    """

    def __init__(self, max_calls, interval_sec):
        self.semaphore = asyncio.Semaphore(max_calls)
        self.interval = interval_sec

    async def __aenter__(self):
        await self.semaphore.acquire()

    async def __aexit__(self, exc_type, exc, tb):
        await asyncio.sleep(self.interval)
        self.semaphore.release()
