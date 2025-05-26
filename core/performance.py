"""
Performance optimization module for Algosat trading system.
Provides advanced caching, connection pooling, and async optimizations.
"""

import asyncio
import time
import weakref
from typing import Dict, List, Optional, Any, Callable, Set
from datetime import datetime, timedelta
from functools import wraps, lru_cache
from contextlib import asynccontextmanager
import aioredis
import json
import pickle
import hashlib
from dataclasses import dataclass, asdict
from enum import Enum
import psutil
import gc
from concurrent.futures import ThreadPoolExecutor
import threading

from common.logger import get_logger
from core.config_manager import get_config

logger = get_logger("performance")
config = get_config()


class CacheLevel(Enum):
    """Cache levels for different data types."""
    MEMORY = "memory"
    REDIS = "redis"
    PERSISTENT = "persistent"


@dataclass
class CacheConfig:
    """Configuration for cache behavior."""
    ttl: int = 300  # Time to live in seconds
    max_size: int = 1000
    level: CacheLevel = CacheLevel.MEMORY
    compression: bool = False
    serialization: str = "json"  # json, pickle


class AdvancedCacheManager:
    """
    Multi-level cache manager with Redis, memory, and persistent storage.
    Supports cache warming, eviction policies, and compression.
    """
    
    def __init__(self):
        self.memory_caches: Dict[str, Dict] = {}
        self.redis_client: Optional[aioredis.Redis] = None
        self.cache_configs: Dict[str, CacheConfig] = {}
        self.cache_stats: Dict[str, Dict] = {}
        self.cache_locks: Dict[str, asyncio.Lock] = {}
        self._redis_pool_created = False
        
    async def initialize_redis(self):
        """Initialize Redis connection pool."""
        if not self._redis_pool_created:
            try:
                self.redis_client = aioredis.from_url(
                    config.redis.url,
                    max_connections=config.redis.max_connections,
                    retry_on_timeout=True,
                    socket_keepalive=True,
                    socket_keepalive_options={},
                    health_check_interval=30
                )
                await self.redis_client.ping()
                self._redis_pool_created = True
                logger.info("Redis cache initialized successfully")
            except Exception as e:
                logger.warning(f"Redis initialization failed: {e}")
                self.redis_client = None
    
    def register_cache(self, name: str, config: CacheConfig):
        """Register a cache with specific configuration."""
        self.cache_configs[name] = config
        self.cache_stats[name] = {
            'hits': 0,
            'misses': 0,
            'sets': 0,
            'evictions': 0,
            'size': 0
        }
        self.cache_locks[name] = asyncio.Lock()
        
        if config.level == CacheLevel.MEMORY:
            from cachetools import TTLCache
            self.memory_caches[name] = TTLCache(
                maxsize=config.max_size,
                ttl=config.ttl
            )
    
    def _serialize_value(self, value: Any, method: str = "json") -> bytes:
        """Serialize value for storage."""
        if method == "json":
            return json.dumps(value, default=str).encode()
        elif method == "pickle":
            return pickle.dumps(value)
        else:
            raise ValueError(f"Unknown serialization method: {method}")
    
    def _deserialize_value(self, data: bytes, method: str = "json") -> Any:
        """Deserialize value from storage."""
        if method == "json":
            return json.loads(data.decode())
        elif method == "pickle":
            return pickle.loads(data)
        else:
            raise ValueError(f"Unknown serialization method: {method}")
    
    def _generate_key(self, cache_name: str, key: str) -> str:
        """Generate cache key with namespace."""
        return f"algosat:{cache_name}:{key}"
    
    async def get(self, cache_name: str, key: str) -> Optional[Any]:
        """Get value from cache with fallback strategy."""
        if cache_name not in self.cache_configs:
            return None
            
        config = self.cache_configs[cache_name]
        cache_key = self._generate_key(cache_name, key)
        
        # Try memory cache first
        if cache_name in self.memory_caches:
            value = self.memory_caches[cache_name].get(key)
            if value is not None:
                self.cache_stats[cache_name]['hits'] += 1
                return value
        
        # Try Redis cache
        if config.level == CacheLevel.REDIS and self.redis_client:
            try:
                data = await self.redis_client.get(cache_key)
                if data:
                    value = self._deserialize_value(data, config.serialization)
                    # Populate memory cache for faster access
                    if cache_name in self.memory_caches:
                        self.memory_caches[cache_name][key] = value
                    self.cache_stats[cache_name]['hits'] += 1
                    return value
            except Exception as e:
                logger.warning(f"Redis get error for {cache_key}: {e}")
        
        self.cache_stats[cache_name]['misses'] += 1
        return None
    
    async def set(self, cache_name: str, key: str, value: Any, ttl: Optional[int] = None):
        """Set value in cache with appropriate storage level."""
        if cache_name not in self.cache_configs:
            return
            
        config = self.cache_configs[cache_name]
        ttl = ttl or config.ttl
        cache_key = self._generate_key(cache_name, key)
        
        async with self.cache_locks[cache_name]:
            # Set in memory cache
            if cache_name in self.memory_caches:
                self.memory_caches[cache_name][key] = value
            
            # Set in Redis cache
            if config.level == CacheLevel.REDIS and self.redis_client:
                try:
                    data = self._serialize_value(value, config.serialization)
                    await self.redis_client.setex(cache_key, ttl, data)
                except Exception as e:
                    logger.warning(f"Redis set error for {cache_key}: {e}")
            
            self.cache_stats[cache_name]['sets'] += 1
    
    async def invalidate(self, cache_name: str, pattern: str = "*"):
        """Invalidate cache entries matching pattern."""
        # Clear memory cache
        if cache_name in self.memory_caches:
            if pattern == "*":
                self.memory_caches[cache_name].clear()
            else:
                keys_to_remove = [k for k in self.memory_caches[cache_name].keys() if pattern in k]
                for k in keys_to_remove:
                    del self.memory_caches[cache_name][k]
        
        # Clear Redis cache
        if self.redis_client:
            try:
                cache_pattern = self._generate_key(cache_name, pattern)
                keys = await self.redis_client.keys(cache_pattern)
                if keys:
                    await self.redis_client.delete(*keys)
            except Exception as e:
                logger.warning(f"Redis invalidation error: {e}")
    
    async def warm_cache(self, cache_name: str, warm_function: Callable):
        """Warm cache with precomputed values."""
        logger.info(f"Warming cache: {cache_name}")
        try:
            warm_data = await warm_function()
            for key, value in warm_data.items():
                await self.set(cache_name, key, value)
            logger.info(f"Cache {cache_name} warmed with {len(warm_data)} entries")
        except Exception as e:
            logger.error(f"Cache warming failed for {cache_name}: {e}")
    
    def get_stats(self) -> Dict[str, Dict]:
        """Get cache statistics."""
        stats = {}
        for name, stat in self.cache_stats.items():
            hit_rate = stat['hits'] / (stat['hits'] + stat['misses']) if (stat['hits'] + stat['misses']) > 0 else 0
            stats[name] = {
                **stat,
                'hit_rate': hit_rate,
                'memory_size': len(self.memory_caches.get(name, {}))
            }
        return stats


class ConnectionPoolManager:
    """
    Advanced connection pool manager for database and broker connections.
    Supports health checks, automatic failover, and connection warming.
    """
    
    def __init__(self):
        self.pools: Dict[str, Any] = {}
        self.pool_configs: Dict[str, Dict] = {}
        self.health_checkers: Dict[str, Callable] = {}
        self.circuit_breakers: Dict[str, Dict] = {}
        self._monitoring_task: Optional[asyncio.Task] = None
        
    def register_pool(self, name: str, pool_factory: Callable, config: Dict, health_checker: Callable):
        """Register a connection pool with health checking."""
        self.pool_configs[name] = config
        self.health_checkers[name] = health_checker
        self.circuit_breakers[name] = {
            'state': 'closed',  # closed, open, half-open
            'failure_count': 0,
            'last_failure': None,
            'threshold': config.get('failure_threshold', 5),
            'timeout': config.get('circuit_timeout', 60)
        }
        
        # Create pool
        self.pools[name] = pool_factory(**config)
        logger.info(f"Registered connection pool: {name}")
    
    async def get_connection(self, pool_name: str):
        """Get connection with circuit breaker protection."""
        breaker = self.circuit_breakers[pool_name]
        
        # Check circuit breaker state
        if breaker['state'] == 'open':
            if time.time() - breaker['last_failure'] > breaker['timeout']:
                breaker['state'] = 'half-open'
            else:
                raise ConnectionError(f"Circuit breaker open for pool: {pool_name}")
        
        try:
            pool = self.pools[pool_name]
            connection = await pool.acquire()
            
            # Reset circuit breaker on success
            if breaker['state'] == 'half-open':
                breaker['state'] = 'closed'
                breaker['failure_count'] = 0
                
            return connection
            
        except Exception as e:
            # Update circuit breaker on failure
            breaker['failure_count'] += 1
            breaker['last_failure'] = time.time()
            
            if breaker['failure_count'] >= breaker['threshold']:
                breaker['state'] = 'open'
                logger.warning(f"Circuit breaker opened for pool: {pool_name}")
                
            raise e
    
    async def release_connection(self, pool_name: str, connection):
        """Release connection back to pool."""
        try:
            pool = self.pools[pool_name]
            await pool.release(connection)
        except Exception as e:
            logger.error(f"Error releasing connection to {pool_name}: {e}")
    
    @asynccontextmanager
    async def get_connection_context(self, pool_name: str):
        """Context manager for connection handling."""
        connection = None
        try:
            connection = await self.get_connection(pool_name)
            yield connection
        finally:
            if connection:
                await self.release_connection(pool_name, connection)
    
    async def health_check_all_pools(self):
        """Perform health checks on all pools."""
        for pool_name, health_checker in self.health_checkers.items():
            try:
                async with self.get_connection_context(pool_name) as conn:
                    await health_checker(conn)
                logger.debug(f"Health check passed for pool: {pool_name}")
            except Exception as e:
                logger.warning(f"Health check failed for pool {pool_name}: {e}")
    
    async def start_monitoring(self):
        """Start background monitoring of connection pools."""
        async def monitor():
            while True:
                try:
                    await self.health_check_all_pools()
                    await asyncio.sleep(30)  # Check every 30 seconds
                except Exception as e:
                    logger.error(f"Pool monitoring error: {e}")
                    await asyncio.sleep(10)
        
        self._monitoring_task = asyncio.create_task(monitor())
    
    async def stop_monitoring(self):
        """Stop background monitoring."""
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass


class AsyncTaskManager:
    """
    Advanced async task manager with prioritization, batching, and resource limits.
    """
    
    def __init__(self, max_concurrent_tasks: int = 100):
        self.semaphore = asyncio.Semaphore(max_concurrent_tasks)
        self.task_queues: Dict[str, asyncio.Queue] = {}
        self.running_tasks: Set[asyncio.Task] = set()
        self.task_stats: Dict[str, Dict] = {}
        self.executor = ThreadPoolExecutor(max_workers=10)
        
    def register_queue(self, name: str, max_size: int = 1000):
        """Register a task queue with priority support."""
        self.task_queues[name] = asyncio.Queue(maxsize=max_size)
        self.task_stats[name] = {
            'submitted': 0,
            'completed': 0,
            'failed': 0,
            'queue_size': 0
        }
    
    async def submit_task(self, queue_name: str, coro: Callable, priority: int = 0, *args, **kwargs):
        """Submit a task to specified queue with priority."""
        if queue_name not in self.task_queues:
            self.register_queue(queue_name)
        
        task_item = {
            'coro': coro,
            'args': args,
            'kwargs': kwargs,
            'priority': priority,
            'submitted_at': time.time()
        }
        
        await self.task_queues[queue_name].put(task_item)
        self.task_stats[queue_name]['submitted'] += 1
        self.task_stats[queue_name]['queue_size'] += 1
    
    async def process_queue(self, queue_name: str):
        """Process tasks from a specific queue."""
        queue = self.task_queues[queue_name]
        
        while True:
            try:
                task_item = await queue.get()
                self.task_stats[queue_name]['queue_size'] -= 1
                
                async with self.semaphore:
                    task = asyncio.create_task(self._execute_task(queue_name, task_item))
                    self.running_tasks.add(task)
                    task.add_done_callback(self.running_tasks.discard)
                    
            except Exception as e:
                logger.error(f"Error processing queue {queue_name}: {e}")
                await asyncio.sleep(1)
    
    async def _execute_task(self, queue_name: str, task_item: Dict):
        """Execute individual task with error handling."""
        try:
            coro = task_item['coro']
            args = task_item['args']
            kwargs = task_item['kwargs']
            
            if asyncio.iscoroutinefunction(coro):
                result = await coro(*args, **kwargs)
            else:
                # Run in thread pool for CPU-bound tasks
                result = await asyncio.get_event_loop().run_in_executor(
                    self.executor, coro, *args
                )
            
            self.task_stats[queue_name]['completed'] += 1
            return result
            
        except Exception as e:
            self.task_stats[queue_name]['failed'] += 1
            logger.error(f"Task execution failed in queue {queue_name}: {e}")
            raise
    
    async def batch_process(self, queue_name: str, batch_size: int = 10):
        """Process tasks in batches for better throughput."""
        queue = self.task_queues[queue_name]
        
        while True:
            try:
                batch = []
                for _ in range(batch_size):
                    try:
                        task_item = await asyncio.wait_for(queue.get(), timeout=1.0)
                        batch.append(task_item)
                        self.task_stats[queue_name]['queue_size'] -= 1
                    except asyncio.TimeoutError:
                        break
                
                if batch:
                    tasks = [
                        asyncio.create_task(self._execute_task(queue_name, item))
                        for item in batch
                    ]
                    await asyncio.gather(*tasks, return_exceptions=True)
                    
            except Exception as e:
                logger.error(f"Batch processing error for {queue_name}: {e}")
                await asyncio.sleep(1)
    
    def get_stats(self) -> Dict[str, Dict]:
        """Get task processing statistics."""
        stats = {}
        for name, stat in self.task_stats.items():
            stats[name] = {
                **stat,
                'success_rate': stat['completed'] / max(stat['submitted'], 1),
                'active_tasks': len([t for t in self.running_tasks if not t.done()])
            }
        return stats


class MemoryOptimizer:
    """
    Memory optimization utilities for the trading system.
    """
    
    def __init__(self):
        self.memory_threshold = 85  # Percentage
        self.gc_frequency = 60  # seconds
        self._monitoring_task: Optional[asyncio.Task] = None
        
    def get_memory_usage(self) -> Dict[str, float]:
        """Get current memory usage statistics."""
        memory = psutil.virtual_memory()
        process = psutil.Process()
        
        return {
            'system_percent': memory.percent,
            'system_available': memory.available / (1024**3),  # GB
            'process_rss': process.memory_info().rss / (1024**3),  # GB
            'process_vms': process.memory_info().vms / (1024**3),  # GB
            'process_percent': process.memory_percent()
        }
    
    def optimize_memory(self):
        """Perform memory optimization operations."""
        # Force garbage collection
        collected = gc.collect()
        
        # Get memory stats
        memory_stats = self.get_memory_usage()
        
        logger.info(f"Memory optimization: collected {collected} objects, "
                   f"process memory: {memory_stats['process_percent']:.1f}%")
        
        return memory_stats
    
    async def start_monitoring(self):
        """Start background memory monitoring."""
        async def monitor():
            while True:
                try:
                    memory_stats = self.get_memory_usage()
                    
                    if memory_stats['process_percent'] > self.memory_threshold:
                        logger.warning(f"High memory usage detected: {memory_stats['process_percent']:.1f}%")
                        self.optimize_memory()
                    
                    await asyncio.sleep(self.gc_frequency)
                    
                except Exception as e:
                    logger.error(f"Memory monitoring error: {e}")
                    await asyncio.sleep(10)
        
        self._monitoring_task = asyncio.create_task(monitor())
    
    async def stop_monitoring(self):
        """Stop background memory monitoring."""
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass


# Performance decorators
def cache_result(cache_name: str, ttl: int = 300, key_func: Optional[Callable] = None):
    """Decorator to cache function results."""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            cache_manager = get_cache_manager()
            
            # Generate cache key
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                # Simple key generation
                key_parts = [str(arg) for arg in args]
                key_parts.extend([f"{k}={v}" for k, v in sorted(kwargs.items())])
                cache_key = hashlib.md5(":".join(key_parts).encode()).hexdigest()
            
            # Try to get from cache
            result = await cache_manager.get(cache_name, cache_key)
            if result is not None:
                return result
            
            # Execute function and cache result
            result = await func(*args, **kwargs)
            await cache_manager.set(cache_name, cache_key, result, ttl)
            
            return result
        return wrapper
    return decorator


def measure_performance(func):
    """Decorator to measure function performance."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            execution_time = time.perf_counter() - start_time
            logger.debug(f"{func.__name__} executed in {execution_time:.4f}s")
            return result
        except Exception as e:
            execution_time = time.perf_counter() - start_time
            logger.error(f"{func.__name__} failed after {execution_time:.4f}s: {e}")
            raise
    return wrapper


# Global instances
_cache_manager: Optional[AdvancedCacheManager] = None
_connection_pool_manager: Optional[ConnectionPoolManager] = None
_task_manager: Optional[AsyncTaskManager] = None
_memory_optimizer: Optional[MemoryOptimizer] = None


def get_cache_manager() -> AdvancedCacheManager:
    """Get global cache manager instance."""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = AdvancedCacheManager()
    return _cache_manager


def get_connection_pool_manager() -> ConnectionPoolManager:
    """Get global connection pool manager instance."""
    global _connection_pool_manager
    if _connection_pool_manager is None:
        _connection_pool_manager = ConnectionPoolManager()
    return _connection_pool_manager


def get_task_manager() -> AsyncTaskManager:
    """Get global task manager instance."""
    global _task_manager
    if _task_manager is None:
        _task_manager = AsyncTaskManager()
    return _task_manager


def get_memory_optimizer() -> MemoryOptimizer:
    """Get global memory optimizer instance."""
    global _memory_optimizer
    if _memory_optimizer is None:
        _memory_optimizer = MemoryOptimizer()
    return _memory_optimizer


async def initialize_performance_systems():
    """Initialize all performance optimization systems."""
    logger.info("Initializing performance optimization systems...")
    
    # Initialize cache manager
    cache_manager = get_cache_manager()
    await cache_manager.initialize_redis()
    
    # Register common caches
    cache_manager.register_cache("market_data", CacheConfig(
        ttl=300, max_size=2000, level=CacheLevel.REDIS
    ))
    cache_manager.register_cache("option_chains", CacheConfig(
        ttl=120, max_size=500, level=CacheLevel.REDIS
    ))
    cache_manager.register_cache("historical_data", CacheConfig(
        ttl=3600, max_size=1000, level=CacheLevel.REDIS
    ))
    
    # Initialize task manager
    task_manager = get_task_manager()
    task_manager.register_queue("market_data", max_size=2000)
    task_manager.register_queue("order_processing", max_size=1000)
    task_manager.register_queue("analytics", max_size=500)
    
    # Start monitoring
    memory_optimizer = get_memory_optimizer()
    await memory_optimizer.start_monitoring()
    
    logger.info("Performance optimization systems initialized successfully")


async def shutdown_performance_systems():
    """Shutdown all performance optimization systems."""
    logger.info("Shutting down performance optimization systems...")
    
    # Stop monitoring tasks
    memory_optimizer = get_memory_optimizer()
    await memory_optimizer.stop_monitoring()
    
    connection_pool_manager = get_connection_pool_manager()
    await connection_pool_manager.stop_monitoring()
    
    logger.info("Performance optimization systems shut down")
