"""
Global rate limiter for broker API calls.
Provides shared rate limiting across BrokerManager and DataProvider to ensure
we don't exceed broker API limits when both components use the same broker.
"""

import asyncio
import time
from typing import Dict, Optional
from contextlib import asynccontextmanager
from dataclasses import dataclass
from algosat.common.logger import get_logger

logger = get_logger("rate_limiter")

@dataclass
class RateConfig:
    """Configuration for broker rate limiting."""
    rps: int  # Requests per second
    burst: int = None  # Max burst requests (defaults to rps)
    window: float = 1.0  # Time window in seconds
    
    def __post_init__(self):
        if self.burst is None:
            self.burst = self.rps

class TokenBucket:
    """
    Token bucket implementation for rate limiting.
    Allows burst requests up to capacity, then refills at steady rate.
    """
    
    def __init__(self, rate_config: RateConfig):
        self.capacity = rate_config.burst
        self.tokens = rate_config.burst
        self.refill_rate = rate_config.rps  # tokens per second
        self.last_refill = time.time()
        self._lock = asyncio.Lock()
    
    async def acquire(self, tokens: int = 1) -> bool:
        """
        Try to acquire tokens from bucket.
        Returns True if tokens acquired, False if not enough tokens.
        """
        async with self._lock:
            await self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False
    
    async def wait_for_tokens(self, tokens: int = 1) -> float:
        """
        Calculate how long to wait for tokens to be available.
        Returns wait time in seconds.
        """
        async with self._lock:
            await self._refill()
            if self.tokens >= tokens:
                return 0.0
            
            needed_tokens = tokens - self.tokens
            wait_time = needed_tokens / self.refill_rate
            return wait_time
    
    async def _refill(self):
        """Refill bucket based on time elapsed."""
        now = time.time()
        elapsed = now - self.last_refill
        
        if elapsed > 0:
            tokens_to_add = elapsed * self.refill_rate
            self.tokens = min(self.capacity, self.tokens + tokens_to_add)
            self.last_refill = now

class BrokerRateLimiter:
    """Rate limiter for a specific broker."""
    
    def __init__(self, broker_name: str, rate_config: RateConfig):
        self.broker_name = broker_name
        self.rate_config = rate_config
        self.bucket = TokenBucket(rate_config)
        self.call_count = 0
        self.last_call_time = 0
    
    @asynccontextmanager
    async def acquire(self, tokens: int = 1):
        """
        Context manager for rate-limited API calls.
        Waits if necessary to respect rate limits.
        """
        # Wait for tokens to be available
        wait_time = await self.bucket.wait_for_tokens(tokens)
        if wait_time > 0:
            logger.debug(f"Rate limiting {self.broker_name}: waiting {wait_time:.2f}s for {tokens} tokens")
            await asyncio.sleep(wait_time)
        
        # Acquire tokens
        acquired = await self.bucket.acquire(tokens)
        if not acquired:
            # This shouldn't happen after wait_for_tokens, but just in case
            logger.warning(f"Failed to acquire tokens for {self.broker_name} after waiting")
            await asyncio.sleep(1.0 / self.rate_config.rps)
        
        self.call_count += 1
        self.last_call_time = time.time()
        
        logger.debug(f"Rate limiter {self.broker_name}: acquired {tokens} tokens (call #{self.call_count})")
        
        try:
            yield
        finally:
            # Add a small delay to ensure we don't exceed the rate
            min_interval = 1.0 / self.rate_config.rps
            elapsed = time.time() - self.last_call_time
            if elapsed < min_interval:
                additional_wait = min_interval - elapsed
                logger.debug(f"Rate limiter {self.broker_name}: additional wait {additional_wait:.3f}s")
                await asyncio.sleep(additional_wait)

class GlobalRateLimiter:
    """
    Singleton global rate limiter that coordinates API calls across
    BrokerManager and DataProvider for all brokers.
    """
    
    _instance: Optional['GlobalRateLimiter'] = None
    _lock = None  # Will be initialized when needed
    
    # Default rate configurations per broker
    DEFAULT_RATE_CONFIGS = {
        "fyers": RateConfig(rps=10, burst=15, window=1.0),
        "angel": RateConfig(rps=5, burst=8, window=1.0),
        "zerodha": RateConfig(rps=5, burst=5, window=1.0),  # Conservative for Zerodha
    }
    
    def __init__(self):
        self._limiters: Dict[str, BrokerRateLimiter] = {}
        self._rate_configs: Dict[str, RateConfig] = self.DEFAULT_RATE_CONFIGS.copy()
    
    @classmethod
    async def get_instance(cls) -> 'GlobalRateLimiter':
        """Get the singleton instance."""
        if cls._instance is None:
            if cls._lock is None:
                cls._lock = asyncio.Lock()
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    def configure_broker(self, broker_name: str, rate_config: RateConfig):
        """Configure or update rate limits for a broker."""
        self._rate_configs[broker_name] = rate_config
        # Remove existing limiter so it gets recreated with new config
        if broker_name in self._limiters:
            del self._limiters[broker_name]
        logger.info(f"Configured rate limits for {broker_name}: {rate_config.rps} rps, burst={rate_config.burst}")
    
    def get_limiter(self, broker_name: str) -> BrokerRateLimiter:
        """Get or create rate limiter for a broker."""
        if broker_name not in self._limiters:
            rate_config = self._rate_configs.get(
                broker_name, 
                RateConfig(rps=1, burst=1)  # Conservative default
            )
            self._limiters[broker_name] = BrokerRateLimiter(broker_name, rate_config)
            logger.info(f"Created rate limiter for {broker_name}: {rate_config.rps} rps")
        
        return self._limiters[broker_name]
    
    @asynccontextmanager
    async def acquire(self, broker_name: str, tokens: int = 1):
        """Acquire rate limit tokens for a broker."""
        limiter = self.get_limiter(broker_name)
        async with limiter.acquire(tokens):
            yield
    
    def get_stats(self) -> Dict[str, Dict]:
        """Get statistics for all rate limiters."""
        stats = {}
        for broker_name, limiter in self._limiters.items():
            stats[broker_name] = {
                "call_count": limiter.call_count,
                "last_call_time": limiter.last_call_time,
                "current_tokens": limiter.bucket.tokens,
                "capacity": limiter.bucket.capacity,
                "refill_rate": limiter.bucket.refill_rate,
            }
        return stats

# Convenience functions for easy access
async def get_rate_limiter() -> GlobalRateLimiter:
    """Get the global rate limiter instance."""
    return await GlobalRateLimiter.get_instance()

@asynccontextmanager
async def rate_limited_call(broker_name: str, tokens: int = 1):
    """Context manager for rate-limited broker API calls."""
    limiter = await get_rate_limiter()
    async with limiter.acquire(broker_name, tokens):
        yield
