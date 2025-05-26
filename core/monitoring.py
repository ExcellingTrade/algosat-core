"""
Monitoring and observability for Algosat trading system.
Provides metrics collection, health checks, and performance monitoring.
"""
import time
import asyncio
import logging
import traceback
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from functools import wraps
from contextlib import asynccontextmanager

import structlog
from prometheus_client import (
    Counter, Histogram, Gauge, Summary, Info,
    CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST
)

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

class TradingMetrics:
    """Prometheus metrics for trading system monitoring."""
    
    def __init__(self, registry: Optional[CollectorRegistry] = None):
        self.registry = registry or CollectorRegistry()
        
        # System metrics
        self.requests_total = Counter(
            'algosat_requests_total',
            'Total number of requests',
            ['method', 'endpoint', 'status'],
            registry=self.registry
        )
        
        self.request_duration = Histogram(
            'algosat_request_duration_seconds',
            'Request duration in seconds',
            ['method', 'endpoint'],
            registry=self.registry
        )
        
        # Trading metrics
        self.orders_total = Counter(
            'algosat_orders_total',
            'Total number of orders placed',
            ['broker', 'side', 'status', 'strategy'],
            registry=self.registry
        )
        
        self.order_execution_time = Histogram(
            'algosat_order_execution_seconds',
            'Order execution time in seconds',
            ['broker', 'order_type'],
            registry=self.registry
        )
        
        self.positions_current = Gauge(
            'algosat_positions_current',
            'Current number of open positions',
            ['broker', 'symbol'],
            registry=self.registry
        )
        
        self.pnl_total = Gauge(
            'algosat_pnl_total',
            'Total profit and loss',
            ['broker', 'strategy'],
            registry=self.registry
        )
        
        self.balance_current = Gauge(
            'algosat_balance_current',
            'Current account balance',
            ['broker'],
            registry=self.registry
        )
        
        # Strategy metrics
        self.strategy_executions = Counter(
            'algosat_strategy_executions_total',
            'Total strategy executions',
            ['strategy_name', 'signal_type'],
            registry=self.registry
        )
        
        self.strategy_success_rate = Gauge(
            'algosat_strategy_success_rate',
            'Strategy success rate percentage',
            ['strategy_name'],
            registry=self.registry
        )
        
        # Data feed metrics
        self.data_feed_latency = Histogram(
            'algosat_data_feed_latency_seconds',
            'Data feed latency in seconds',
            ['broker', 'symbol'],
            registry=self.registry
        )
        
        self.data_feed_errors = Counter(
            'algosat_data_feed_errors_total',
            'Total data feed errors',
            ['broker', 'error_type'],
            registry=self.registry
        )
        
        # Broker metrics
        self.broker_connection_status = Gauge(
            'algosat_broker_connection_status',
            'Broker connection status (1=connected, 0=disconnected)',
            ['broker'],
            registry=self.registry
        )
        
        self.broker_api_calls = Counter(
            'algosat_broker_api_calls_total',
            'Total broker API calls',
            ['broker', 'endpoint', 'status'],
            registry=self.registry
        )
        
        # Error metrics
        self.errors_total = Counter(
            'algosat_errors_total',
            'Total number of errors',
            ['component', 'error_type'],
            registry=self.registry
        )
        
        # Performance metrics
        self.memory_usage = Gauge(
            'algosat_memory_usage_bytes',
            'Memory usage in bytes',
            registry=self.registry
        )
        
        self.cpu_usage = Gauge(
            'algosat_cpu_usage_percent',
            'CPU usage percentage',
            registry=self.registry
        )


class HealthChecker:
    """Health check manager for system components."""
    
    def __init__(self):
        self.checks: Dict[str, Any] = {}
        self.last_check_time = {}
        self.check_interval = 30  # seconds
        self.start_time = time.time()  # Track when health checker was initialized
        
    def register_check(self, name: str, check_func, critical: bool = False):
        """Register a health check function."""
        self.checks[name] = {
            'func': check_func,
            'critical': critical,
            'status': 'unknown',
            'message': '',
            'last_check': None
        }
        
    async def run_checks(self) -> Dict[str, Any]:
        """Run all health checks and return status."""
        results = {}
        overall_status = 'healthy'
        
        for name, check in self.checks.items():
            try:
                start_time = time.time()
                if asyncio.iscoroutinefunction(check['func']):
                    status, message = await check['func']()
                else:
                    status, message = check['func']()
                
                check_time = time.time() - start_time
                
                results[name] = {
                    'status': status,
                    'message': message,
                    'duration': check_time,
                    'critical': check['critical'],
                    'timestamp': datetime.utcnow().isoformat()
                }
                
                self.checks[name]['status'] = status
                self.checks[name]['message'] = message
                self.checks[name]['last_check'] = datetime.utcnow()
                
                if status != 'healthy' and check['critical']:
                    overall_status = 'unhealthy'
                elif status != 'healthy' and overall_status != 'unhealthy':
                    overall_status = 'degraded'
                    
            except Exception as e:
                logger.error(f"Health check {name} failed", error=str(e))
                results[name] = {
                    'status': 'error',
                    'message': f'Check failed: {str(e)}',
                    'critical': check['critical'],
                    'timestamp': datetime.utcnow().isoformat()
                }
                
                if check['critical']:
                    overall_status = 'unhealthy'
                elif overall_status != 'unhealthy':
                    overall_status = 'degraded'
        
        return {
            'status': overall_status,
            'checks': results,
            'timestamp': datetime.utcnow().isoformat()
        }


class PerformanceMonitor:
    """Performance monitoring and alerting."""
    
    def __init__(self, metrics: TradingMetrics):
        self.metrics = metrics
        self.alerts = []
        self.thresholds = {
            'order_execution_time': 5.0,  # seconds
            'data_feed_latency': 1.0,     # seconds
            'memory_usage': 1024 * 1024 * 1024,  # 1GB
            'cpu_usage': 80.0,            # percentage
            'error_rate': 0.05            # 5%
        }
        
    def check_thresholds(self):
        """Check performance thresholds and generate alerts."""
        current_time = datetime.utcnow()
        
        # Check order execution time
        # This would need to be implemented with actual metric collection
        
        # Check memory usage
        try:
            import psutil
            memory_mb = psutil.virtual_memory().used
            self.metrics.memory_usage.set(memory_mb)
            
            if memory_mb > self.thresholds['memory_usage']:
                self.create_alert('high_memory_usage', f'Memory usage: {memory_mb / 1024 / 1024:.1f}MB')
                
            cpu_percent = psutil.cpu_percent(interval=1)
            self.metrics.cpu_usage.set(cpu_percent)
            
            if cpu_percent > self.thresholds['cpu_usage']:
                self.create_alert('high_cpu_usage', f'CPU usage: {cpu_percent:.1f}%')
                
        except ImportError:
            logger.warning("psutil not available for system monitoring")
    
    def create_alert(self, alert_type: str, message: str):
        """Create performance alert."""
        alert = {
            'type': alert_type,
            'message': message,
            'timestamp': datetime.utcnow().isoformat(),
            'severity': 'warning'
        }
        self.alerts.append(alert)
        logger.warning(f"Performance alert: {alert_type}", message=message)
        
        # Keep only recent alerts (last 24 hours)
        cutoff_time = datetime.utcnow() - timedelta(hours=24)
        self.alerts = [
            alert for alert in self.alerts 
            if datetime.fromisoformat(alert['timestamp']) > cutoff_time
        ]


def monitor_execution_time(metrics: TradingMetrics, component: str):
    """Decorator to monitor function execution time."""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                duration = time.time() - start_time
                metrics.request_duration.labels(
                    method=component,
                    endpoint=func.__name__
                ).observe(duration)
                return result
            except Exception as e:
                metrics.errors_total.labels(
                    component=component,
                    error_type=type(e).__name__
                ).inc()
                raise
                
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                metrics.request_duration.labels(
                    method=component,
                    endpoint=func.__name__
                ).observe(duration)
                return result
            except Exception as e:
                metrics.errors_total.labels(
                    component=component,
                    error_type=type(e).__name__
                ).inc()
                raise
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator


@asynccontextmanager
async def monitor_trade_execution(metrics: TradingMetrics, broker: str, order_type: str):
    """Context manager to monitor trade execution time."""
    start_time = time.time()
    try:
        yield
        duration = time.time() - start_time
        metrics.order_execution_time.labels(
            broker=broker,
            order_type=order_type
        ).observe(duration)
    except Exception as e:
        metrics.errors_total.labels(
            component='trade_execution',
            error_type=type(e).__name__
        ).inc()
        raise


# Global monitoring instances
trading_metrics = TradingMetrics()
health_checker = HealthChecker()
performance_monitor = PerformanceMonitor(trading_metrics)


# Health check functions
async def check_database_health():
    """Check database connectivity."""
    try:
        from core.db import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            await session.execute("SELECT 1")
        return 'healthy', 'Database connection successful'
    except Exception as e:
        return 'unhealthy', f'Database connection failed: {str(e)}'


async def check_broker_connections():
    """Check broker connectivity."""
    try:
        from core.broker_manager import BrokerManager
        broker_manager = BrokerManager()
        connected_brokers = len([
            broker for broker in broker_manager.brokers.values()
            if hasattr(broker, 'is_connected') and broker.is_connected()
        ])
        
        if connected_brokers == 0:
            return 'unhealthy', 'No brokers connected'
        elif connected_brokers < len(broker_manager.brokers):
            return 'degraded', f'{connected_brokers}/{len(broker_manager.brokers)} brokers connected'
        else:
            return 'healthy', f'All {connected_brokers} brokers connected'
    except Exception as e:
        return 'unhealthy', f'Broker check failed: {str(e)}'


def check_system_resources():
    """Check system resource usage."""
    try:
        import psutil
        memory_percent = psutil.virtual_memory().percent
        cpu_percent = psutil.cpu_percent(interval=1)
        
        if memory_percent > 90 or cpu_percent > 90:
            return 'unhealthy', f'High resource usage: Memory {memory_percent}%, CPU {cpu_percent}%'
        elif memory_percent > 80 or cpu_percent > 80:
            return 'degraded', f'Moderate resource usage: Memory {memory_percent}%, CPU {cpu_percent}%'
        else:
            return 'healthy', f'Resource usage normal: Memory {memory_percent}%, CPU {cpu_percent}%'
    except ImportError:
        return 'unknown', 'psutil not available for resource monitoring'
    except Exception as e:
        return 'error', f'Resource check failed: {str(e)}'


# Register health checks
health_checker.register_check('database', check_database_health, critical=True)
health_checker.register_check('brokers', check_broker_connections, critical=True)
health_checker.register_check('system_resources', check_system_resources, critical=False)

# VPS-specific monitoring additions
import psutil
import sqlite3
from pathlib import Path
from collections import defaultdict, deque

# VPS Monitoring Classes
class VPSHealthMonitor:
    """VPS-specific health monitoring for single-user deployment."""
    
    def __init__(self, db_path: str = "/opt/algosat/algosat/Files/monitoring.db"):
        self.db_path = db_path
        self._ensure_db_exists()
        self.alert_thresholds = {
            'cpu_warning': 75.0,
            'cpu_critical': 90.0,
            'memory_warning': 80.0,
            'memory_critical': 95.0,
            'disk_warning': 85.0,
            'disk_critical': 95.0
        }
        self.metrics_cache = deque(maxlen=1440)  # 24 hours of minute data
        
    def _ensure_db_exists(self):
        """Create monitoring database if it doesn't exist."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS system_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    cpu_percent REAL,
                    memory_percent REAL,
                    disk_percent REAL,
                    network_bytes_sent INTEGER,
                    network_bytes_recv INTEGER,
                    process_count INTEGER,
                    active_connections INTEGER
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trading_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    orders_placed INTEGER DEFAULT 0,
                    orders_filled INTEGER DEFAULT 0,
                    orders_failed INTEGER DEFAULT 0,
                    total_pnl REAL DEFAULT 0,
                    active_positions INTEGER DEFAULT 0,
                    api_calls_made INTEGER DEFAULT 0
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    alert_type TEXT,
                    severity TEXT,
                    message TEXT,
                    resolved BOOLEAN DEFAULT FALSE
                )
            """)
    
    async def collect_system_metrics(self) -> Dict[str, Any]:
        """Collect comprehensive system metrics."""
        try:
            # CPU metrics
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_count = psutil.cpu_count()
            load_avg = psutil.getloadavg() if hasattr(psutil, 'getloadavg') else (0, 0, 0)
            
            # Memory metrics
            memory = psutil.virtual_memory()
            swap = psutil.swap_memory()
            
            # Disk metrics
            disk = psutil.disk_usage('/')
            disk_io = psutil.disk_io_counters()
            
            # Network metrics
            network = psutil.net_io_counters()
            
            # Process metrics
            process_count = len(psutil.pids())
            
            metrics = {
                'cpu': {
                    'percent': cpu_percent,
                    'count': cpu_count,
                    'load_avg_1m': load_avg[0],
                    'load_avg_5m': load_avg[1],
                    'load_avg_15m': load_avg[2]
                },
                'memory': {
                    'total': memory.total,
                    'available': memory.available,
                    'percent': memory.percent,
                    'used': memory.used,
                    'free': memory.free
                },
                'swap': {
                    'total': swap.total,
                    'used': swap.used,
                    'percent': swap.percent
                },
                'disk': {
                    'total': disk.total,
                    'used': disk.used,
                    'free': disk.free,
                    'percent': (disk.used / disk.total) * 100
                },
                'disk_io': {
                    'read_bytes': disk_io.read_bytes if disk_io else 0,
                    'write_bytes': disk_io.write_bytes if disk_io else 0
                },
                'network': {
                    'bytes_sent': network.bytes_sent,
                    'bytes_recv': network.bytes_recv,
                    'packets_sent': network.packets_sent,
                    'packets_recv': network.packets_recv
                },
                'processes': {
                    'count': process_count
                },
                'timestamp': datetime.now().isoformat()
            }
            
            # Store in database
            await self._store_system_metrics(metrics)
            
            # Check for alerts
            await self._check_system_alerts(metrics)
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error collecting system metrics: {e}")
            return {}
    
    async def _store_system_metrics(self, metrics: Dict[str, Any]):
        """Store metrics in database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO system_metrics 
                    (cpu_percent, memory_percent, disk_percent, 
                     network_bytes_sent, network_bytes_recv, process_count)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    metrics['cpu']['percent'],
                    metrics['memory']['percent'],
                    metrics['disk']['percent'],
                    metrics['network']['bytes_sent'],
                    metrics['network']['bytes_recv'],
                    metrics['processes']['count']
                ))
        except Exception as e:
            logger.error(f"Error storing system metrics: {e}")
    
    async def _check_system_alerts(self, metrics: Dict[str, Any]):
        """Check metrics against alert thresholds."""
        alerts = []
        
        # CPU alerts
        cpu_percent = metrics['cpu']['percent']
        if cpu_percent >= self.alert_thresholds['cpu_critical']:
            alerts.append({
                'type': 'cpu',
                'severity': 'critical',
                'message': f'CPU usage critical: {cpu_percent:.1f}%'
            })
        elif cpu_percent >= self.alert_thresholds['cpu_warning']:
            alerts.append({
                'type': 'cpu',
                'severity': 'warning',
                'message': f'CPU usage high: {cpu_percent:.1f}%'
            })
        
        # Memory alerts
        memory_percent = metrics['memory']['percent']
        if memory_percent >= self.alert_thresholds['memory_critical']:
            alerts.append({
                'type': 'memory',
                'severity': 'critical',
                'message': f'Memory usage critical: {memory_percent:.1f}%'
            })
        elif memory_percent >= self.alert_thresholds['memory_warning']:
            alerts.append({
                'type': 'memory',
                'severity': 'warning',
                'message': f'Memory usage high: {memory_percent:.1f}%'
            })
        
        # Disk alerts
        disk_percent = metrics['disk']['percent']
        if disk_percent >= self.alert_thresholds['disk_critical']:
            alerts.append({
                'type': 'disk',
                'severity': 'critical',
                'message': f'Disk usage critical: {disk_percent:.1f}%'
            })
        elif disk_percent >= self.alert_thresholds['disk_warning']:
            alerts.append({
                'type': 'disk',
                'severity': 'warning',
                'message': f'Disk usage high: {disk_percent:.1f}%'
            })
        
        # Store alerts
        for alert in alerts:
            await self._store_alert(alert)
            logger.warning(f"System alert: {alert['message']}")
    
    async def _store_alert(self, alert: Dict[str, Any]):
        """Store alert in database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO alerts (alert_type, severity, message)
                    VALUES (?, ?, ?)
                """, (alert['type'], alert['severity'], alert['message']))
        except Exception as e:
            logger.error(f"Error storing alert: {e}")
    
    async def get_recent_metrics(self, hours: int = 1) -> List[Dict[str, Any]]:
        """Get recent system metrics."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT * FROM system_metrics 
                    WHERE timestamp >= datetime('now', '-{} hours')
                    ORDER BY timestamp DESC
                """.format(hours))
                
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting recent metrics: {e}")
            return []
    
    async def get_active_alerts(self) -> List[Dict[str, Any]]:
        """Get active (unresolved) alerts."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT * FROM alerts 
                    WHERE resolved = FALSE 
                    ORDER BY timestamp DESC
                """)
                
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error getting active alerts: {e}")
            return []

class TradingMetricsCollector:
    """Collect and track trading-specific metrics."""
    
    def __init__(self, db_path: str = "/opt/algosat/algosat/Files/monitoring.db"):
        self.db_path = db_path
        self.daily_metrics = defaultdict(int)
        self.reset_time = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    async def record_order_placed(self, order_data: Dict[str, Any]):
        """Record when an order is placed."""
        self.daily_metrics['orders_placed'] += 1
        await self._update_trading_metrics()
        
        # Log detailed order info
        logger.info("Order placed", extra={
            'event_type': 'order_placed',
            'symbol': order_data.get('symbol'),
            'side': order_data.get('side'),
            'quantity': order_data.get('quantity'),
            'price': order_data.get('price')
        })
    
    async def record_order_filled(self, order_data: Dict[str, Any]):
        """Record when an order is filled."""
        self.daily_metrics['orders_filled'] += 1
        await self._update_trading_metrics()
        
        logger.info("Order filled", extra={
            'event_type': 'order_filled',
            'symbol': order_data.get('symbol'),
            'side': order_data.get('side'),
            'quantity': order_data.get('quantity'),
            'fill_price': order_data.get('fill_price')
        })
    
    async def record_order_failed(self, order_data: Dict[str, Any], error: str):
        """Record when an order fails."""
        self.daily_metrics['orders_failed'] += 1
        await self._update_trading_metrics()
        
        logger.error("Order failed", extra={
            'event_type': 'order_failed',
            'symbol': order_data.get('symbol'),
            'error': error
        })
    
    async def update_pnl(self, total_pnl: float):
        """Update total P&L."""
        self.daily_metrics['total_pnl'] = total_pnl
        await self._update_trading_metrics()
    
    async def _update_trading_metrics(self):
        """Update trading metrics in database."""
        try:
            # Check if we need to reset daily metrics
            now = datetime.now()
            if now.date() > self.reset_time.date():
                self.daily_metrics.clear()
                self.reset_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
            
            with sqlite3.connect(self.db_path) as conn:
                # Update or insert today's metrics
                conn.execute("""
                    INSERT OR REPLACE INTO trading_metrics 
                    (timestamp, orders_placed, orders_filled, orders_failed, total_pnl)
                    VALUES (date('now'), ?, ?, ?, ?)
                """, (
                    self.daily_metrics['orders_placed'],
                    self.daily_metrics['orders_filled'],
                    self.daily_metrics['orders_failed'],
                    self.daily_metrics['total_pnl']
                ))
        except Exception as e:
            logger.error(f"Error updating trading metrics: {e}")
