# core/vps_performance.py
"""
VPS-specific performance optimizations for single-user Algosat deployment.
Focuses on memory management, connection pooling, and local caching.
"""
import os
import psutil
import asyncio
import aiofiles
import json
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from collections import defaultdict, deque
from dataclasses import dataclass, asdict
import sqlite3
import threading
from algosat.common.logger import get_logger

logger = get_logger("VPSPerformance")

@dataclass
class SystemMetrics:
    """System performance metrics."""
    cpu_percent: float
    memory_percent: float
    disk_usage_percent: float
    network_io: Dict[str, int]
    process_count: int
    timestamp: datetime

class LocalCache:
    """High-performance local cache for single-user VPS deployment."""
    
    def __init__(self, max_size: int = 10000, ttl_seconds: int = 300):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, Dict] = {}
        self._access_times: Dict[str, datetime] = {}
        self._lock = threading.Lock()
        
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        with self._lock:
            if key not in self._cache:
                return None
                
            # Check TTL
            if datetime.now() - self._access_times[key] > timedelta(seconds=self.ttl_seconds):
                del self._cache[key]
                del self._access_times[key]
                return None
                
            self._access_times[key] = datetime.now()
            return self._cache[key]['value']
    
    def set(self, key: str, value: Any) -> None:
        """Set value in cache."""
        with self._lock:
            # Implement LRU eviction if cache is full
            if len(self._cache) >= self.max_size:
                # Remove oldest accessed item
                oldest_key = min(self._access_times.keys(), 
                               key=lambda k: self._access_times[k])
                del self._cache[oldest_key]
                del self._access_times[oldest_key]
            
            self._cache[key] = {'value': value}
            self._access_times[key] = datetime.now()
    
    def delete(self, key: str) -> None:
        """Delete key from cache."""
        with self._lock:
            self._cache.pop(key, None)
            self._access_times.pop(key, None)
    
    def clear(self) -> None:
        """Clear entire cache."""
        with self._lock:
            self._cache.clear()
            self._access_times.clear()
    
    def size(self) -> int:
        """Get current cache size."""
        return len(self._cache)

class ConnectionPool:
    """Lightweight connection pool for database connections."""
    
    def __init__(self, max_connections: int = 5):
        self.max_connections = max_connections
        self._pool = asyncio.Queue(maxsize=max_connections)
        self._connections_created = 0
        self._lock = asyncio.Lock()
    
    async def get_connection(self):
        """Get a connection from the pool."""
        try:
            # Try to get existing connection
            connection = await asyncio.wait_for(self._pool.get(), timeout=1.0)
            return connection
        except asyncio.TimeoutError:
            # Create new connection if pool is empty and we haven't hit max
            async with self._lock:
                if self._connections_created < self.max_connections:
                    connection = await self._create_connection()
                    self._connections_created += 1
                    return connection
                else:
                    # Wait for a connection to become available
                    return await self._pool.get()
    
    async def return_connection(self, connection):
        """Return a connection to the pool."""
        if connection and not connection.is_closed():
            await self._pool.put(connection)
    
    async def _create_connection(self):
        """Create a new database connection."""
        # This would be implemented based on your database setup
        # Placeholder for now
        pass

class PerformanceMonitor:
    """Monitor VPS performance metrics."""
    
    def __init__(self, monitoring_interval: int = 60):
        self.monitoring_interval = monitoring_interval
        self.metrics_history = deque(maxlen=1440)  # Keep 24 hours of minute-level data
        self.cache = LocalCache()
        self._monitoring_task = None
        
    async def start_monitoring(self):
        """Start performance monitoring."""
        if not self._monitoring_task:
            self._monitoring_task = asyncio.create_task(self._monitor_loop())
            logger.info("Performance monitoring started")
    
    async def stop_monitoring(self):
        """Stop performance monitoring."""
        if self._monitoring_task:
            self._monitoring_task.cancel()
            self._monitoring_task = None
            logger.info("Performance monitoring stopped")
    
    async def _monitor_loop(self):
        """Main monitoring loop."""
        while True:
            try:
                metrics = await self._collect_metrics()
                self.metrics_history.append(metrics)
                
                # Cache latest metrics
                self.cache.set("latest_metrics", asdict(metrics))
                
                # Check for performance issues
                await self._check_performance_alerts(metrics)
                
                await asyncio.sleep(self.monitoring_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(self.monitoring_interval)
    
    async def _collect_metrics(self) -> SystemMetrics:
        """Collect system performance metrics."""
        # CPU usage
        cpu_percent = psutil.cpu_percent(interval=1)
        
        # Memory usage
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        
        # Disk usage
        disk = psutil.disk_usage('/')
        disk_usage_percent = (disk.used / disk.total) * 100
        
        # Network I/O
        network = psutil.net_io_counters()
        network_io = {
            'bytes_sent': network.bytes_sent,
            'bytes_recv': network.bytes_recv,
            'packets_sent': network.packets_sent,
            'packets_recv': network.packets_recv
        }
        
        # Process count
        process_count = len(psutil.pids())
        
        return SystemMetrics(
            cpu_percent=cpu_percent,
            memory_percent=memory_percent,
            disk_usage_percent=disk_usage_percent,
            network_io=network_io,
            process_count=process_count,
            timestamp=datetime.now()
        )
    
    async def _check_performance_alerts(self, metrics: SystemMetrics):
        """Check for performance issues and log alerts."""
        if metrics.cpu_percent > 80:
            logger.warning(f"High CPU usage detected: {metrics.cpu_percent}%")
        
        if metrics.memory_percent > 85:
            logger.warning(f"High memory usage detected: {metrics.memory_percent}%")
        
        if metrics.disk_usage_percent > 90:
            logger.error(f"High disk usage detected: {metrics.disk_usage_percent}%")
    
    def get_current_metrics(self) -> Optional[Dict[str, Any]]:
        """Get current system metrics."""
        return self.cache.get("latest_metrics")
    
    def get_metrics_history(self, hours: int = 1) -> list:
        """Get metrics history for specified hours."""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        return [
            asdict(metrics) for metrics in self.metrics_history
            if metrics.timestamp >= cutoff_time
        ]

class OptimizedDataManager:
    """Optimized data management for VPS deployment."""
    
    def __init__(self, cache_size: int = 5000):
        self.cache = LocalCache(max_size=cache_size, ttl_seconds=300)
        self.price_cache = defaultdict(deque)
        self.max_price_history = 1000
        
    async def cache_price_data(self, symbol: str, price_data: Dict[str, Any]):
        """Cache price data with automatic cleanup."""
        cache_key = f"price_{symbol}"
        self.cache.set(cache_key, price_data)
        
        # Also maintain a rolling history
        self.price_cache[symbol].append({
            'timestamp': datetime.now(),
            'data': price_data
        })
        
        # Keep only recent data
        if len(self.price_cache[symbol]) > self.max_price_history:
            self.price_cache[symbol].popleft()
    
    async def get_cached_price(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get cached price data."""
        cache_key = f"price_{symbol}"
        return self.cache.get(cache_key)
    
    async def get_price_history(self, symbol: str, minutes: int = 60) -> list:
        """Get price history for symbol."""
        cutoff_time = datetime.now() - timedelta(minutes=minutes)
        
        if symbol not in self.price_cache:
            return []
        
        return [
            entry['data'] for entry in self.price_cache[symbol]
            if entry['timestamp'] >= cutoff_time
        ]
    
    async def cleanup_old_data(self):
        """Clean up old cached data."""
        cutoff_time = datetime.now() - timedelta(hours=24)
        
        for symbol in list(self.price_cache.keys()):
            # Remove old entries
            while (self.price_cache[symbol] and 
                   self.price_cache[symbol][0]['timestamp'] < cutoff_time):
                self.price_cache[symbol].popleft()
            
            # Remove empty deques
            if not self.price_cache[symbol]:
                del self.price_cache[symbol]

class VPSOptimizer:
    """Main VPS optimization coordinator."""
    
    def __init__(self):
        self.performance_monitor = PerformanceMonitor()
        self.data_manager = OptimizedDataManager()
        self.cache = LocalCache()
        self._cleanup_task = None
        
    async def start(self):
        """Start VPS optimizations."""
        await self.performance_monitor.start_monitoring()
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("VPS optimizations started")
    
    async def stop(self):
        """Stop VPS optimizations."""
        await self.performance_monitor.stop_monitoring()
        if self._cleanup_task:
            self._cleanup_task.cancel()
        logger.info("VPS optimizations stopped")
    
    async def _cleanup_loop(self):
        """Periodic cleanup of cached data."""
        while True:
            try:
                await asyncio.sleep(3600)  # Run every hour
                await self.data_manager.cleanup_old_data()
                logger.info("Completed periodic data cleanup")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
    
    async def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status."""
        metrics = self.performance_monitor.get_current_metrics()
        
        return {
            'system_metrics': metrics,
            'cache_stats': {
                'main_cache_size': self.cache.size(),
                'data_cache_size': self.data_manager.cache.size(),
                'price_symbols_cached': len(self.data_manager.price_cache)
            },
            'memory_info': dict(psutil.virtual_memory()._asdict()),
            'disk_info': dict(psutil.disk_usage('/')._asdict()),
            'timestamp': datetime.now().isoformat()
        }

# Global VPS optimizer instance
vps_optimizer = VPSOptimizer()

async def initialize_vps_optimizations():
    """Initialize VPS optimizations."""
    await vps_optimizer.start()

async def shutdown_vps_optimizations():
    """Shutdown VPS optimizations."""
    await vps_optimizer.stop()
