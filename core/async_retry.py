"""
Enhanced async retry utilities with integrated rate limiting.
Provides configurable retry logic with exponential backoff and 
automatic rate limiting coordination.
"""

import asyncio
import random
import time
from typing import Any, Callable, Optional, Union, Tuple, Dict
from functools import wraps
from algosat.common.logger import get_logger
from algosat.core.rate_limiter import rate_limited_call

logger = get_logger("async_retry")

class RetryConfig:
    """Configuration for retry behavior."""
    
    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay: float = 1.0,
        backoff: float = 2.0,
        max_delay: float = 60.0,
        jitter: bool = True,
        exceptions: Tuple = (Exception,),
        rate_limit_broker: Optional[str] = None,
        rate_limit_tokens: int = 1
    ):
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.backoff = backoff
        self.max_delay = max_delay
        self.jitter = jitter
        self.exceptions = exceptions
        self.rate_limit_broker = rate_limit_broker
        self.rate_limit_tokens = rate_limit_tokens

async def async_retry_with_rate_limit(
    coro_func: Callable,
    *args,
    config: Optional[RetryConfig] = None,
    **kwargs
) -> Any:
    """
    Execute an async function with retry logic and optional rate limiting.
    
    Args:
        coro_func: The async function to execute
        *args: Positional arguments for the function
        config: RetryConfig instance with retry parameters
        **kwargs: Keyword arguments for the function
        
    Returns:
        The result of the successful function call
        
    Raises:
        The last exception if all retries fail
    """
    if config is None:
        config = RetryConfig()
    
    attempt = 0
    delay = config.initial_delay
    last_exception = None
    
    while attempt < config.max_attempts:
        try:
            # Apply rate limiting if configured
            if config.rate_limit_broker:
                async with rate_limited_call(config.rate_limit_broker, config.rate_limit_tokens):
                    result = await coro_func(*args, **kwargs)
            else:
                result = await coro_func(*args, **kwargs)
            
            if attempt > 0:
                logger.info(f"Retry successful on attempt {attempt + 1}/{config.max_attempts}")
            
            return result
            
        except config.exceptions as e:
            attempt += 1
            last_exception = e
            
            if attempt >= config.max_attempts:
                logger.error(f"All {config.max_attempts} retry attempts failed. Last error: {e}")
                raise
            
            # Calculate delay with jitter
            actual_delay = delay
            if config.jitter:
                actual_delay += random.uniform(0, delay * 0.1)  # Add up to 10% jitter
            
            actual_delay = min(actual_delay, config.max_delay)
            
            logger.warning(f"Attempt {attempt}/{config.max_attempts} failed: {e}. Retrying in {actual_delay:.2f}s...")
            await asyncio.sleep(actual_delay)
            
            # Exponential backoff
            delay = min(delay * config.backoff, config.max_delay)
    
    # This should never be reached, but just in case
    raise last_exception

def broker_retry(
    broker_name: str,
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    backoff: float = 2.0,
    tokens: int = 1,
    exceptions: Tuple = (Exception,)
):
    """
    Decorator for broker API methods that adds retry logic and rate limiting.
    
    Args:
        broker_name: Name of the broker for rate limiting
        max_attempts: Maximum number of retry attempts
        initial_delay: Initial delay between retries
        backoff: Backoff multiplier for delay
        tokens: Number of rate limit tokens to acquire
        exceptions: Tuple of exceptions to catch and retry
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            config = RetryConfig(
                max_attempts=max_attempts,
                initial_delay=initial_delay,
                backoff=backoff,
                exceptions=exceptions,
                rate_limit_broker=broker_name,
                rate_limit_tokens=tokens
            )
            return await async_retry_with_rate_limit(func, *args, config=config, **kwargs)
        return wrapper
    return decorator

# Predefined configurations for common scenarios
BROKER_RETRY_CONFIGS = {
    "default": RetryConfig(
        max_attempts=3,
        initial_delay=1.0,
        backoff=2.0,
        max_delay=30.0
    ),
    "aggressive": RetryConfig(
        max_attempts=5,
        initial_delay=0.5,
        backoff=1.5,
        max_delay=15.0
    ),
    "conservative": RetryConfig(
        max_attempts=2,
        initial_delay=2.0,
        backoff=3.0,
        max_delay=60.0
    ),
    "order_critical": RetryConfig(
        max_attempts=5,
        initial_delay=0.5,
        backoff=1.2,
        max_delay=10.0,
        exceptions=(ConnectionError, TimeoutError, Exception)  # Broad exception handling for critical operations
    ),
    "data_fetch": RetryConfig(
        max_attempts=3,
        initial_delay=1.0,
        backoff=2.0,
        max_delay=20.0,
        exceptions=(ConnectionError, TimeoutError)  # More specific exceptions for data operations
    )
}

def get_retry_config(name: str) -> RetryConfig:
    """Get a predefined retry configuration by name."""
    return BROKER_RETRY_CONFIGS.get(name, BROKER_RETRY_CONFIGS["default"])

class RetryStats:
    """Track retry statistics for monitoring."""
    
    def __init__(self):
        self.total_calls = 0
        self.successful_calls = 0
        self.failed_calls = 0
        self.retry_counts: Dict[int, int] = {}  # attempt_number -> count
        self.last_reset = time.time()
    
    def record_success(self, attempts: int):
        """Record a successful call."""
        self.total_calls += 1
        self.successful_calls += 1
        self.retry_counts[attempts] = self.retry_counts.get(attempts, 0) + 1
    
    def record_failure(self, attempts: int):
        """Record a failed call (after all retries)."""
        self.total_calls += 1
        self.failed_calls += 1
        self.retry_counts[attempts] = self.retry_counts.get(attempts, 0) + 1
    
    def get_stats(self) -> Dict:
        """Get current statistics."""
        success_rate = (self.successful_calls / self.total_calls * 100) if self.total_calls > 0 else 0
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "success_rate": f"{success_rate:.1f}%",
            "retry_distribution": self.retry_counts,
            "uptime": time.time() - self.last_reset
        }
    
    def reset(self):
        """Reset all statistics."""
        self.total_calls = 0
        self.successful_calls = 0
        self.failed_calls = 0
        self.retry_counts.clear()
        self.last_reset = time.time()

# Global retry statistics
_retry_stats = RetryStats()
