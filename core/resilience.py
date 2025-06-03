"""
Resilience patterns for Algosat trading system.
Implements circuit breakers, retry mechanisms, fault tolerance, and structured error handling.
Enhanced for production VPS deployment with comprehensive error tracking and recovery.
"""
import asyncio
import time
import logging
import sqlite3
import json
from datetime import datetime, timedelta
from typing import Any, Callable, Optional, Dict, List
from functools import wraps
from enum import Enum
from pathlib import Path
import random
import traceback

logger = logging.getLogger(__name__)


class ErrorSeverity(Enum):
    """Error severity levels for structured error handling."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ErrorCategory(Enum):
    """Error categories for better classification."""
    NETWORK = "NETWORK"
    DATABASE = "DATABASE"
    BROKER_API = "BROKER_API"
    TRADING = "TRADING"
    VALIDATION = "VALIDATION"
    SYSTEM = "SYSTEM"
    AUTHENTICATION = "AUTHENTICATION"


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, blocking requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreaker:
    """Circuit breaker for fault tolerance."""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        timeout: int = 60,
        expected_exception: tuple = (Exception,)
    ):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.expected_exception = expected_exception
        
        self.failure_count = 0
        self.last_failure_time = None
        self.state = CircuitState.CLOSED
        
    def _should_attempt_request(self) -> bool:
        """Determine if request should be attempted."""
        if self.state == CircuitState.CLOSED:
            return True
        elif self.state == CircuitState.OPEN:
            if self.last_failure_time and time.time() - self.last_failure_time >= self.timeout:
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        else:  # HALF_OPEN
            return True
    
    def _on_success(self):
        """Handle successful request."""
        self.failure_count = 0
        self.state = CircuitState.CLOSED
        
    def _on_failure(self):
        """Handle failed request."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
    
    def __call__(self, func: Callable) -> Callable:
        """Decorator for circuit breaker."""
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not self._should_attempt_request():
                raise CircuitBreakerOpenError(f"Circuit breaker open for {func.__name__}")
            
            try:
                result = await func(*args, **kwargs)
                self._on_success()
                return result
            except self.expected_exception as e:
                self._on_failure()
                raise
                
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            if not self._should_attempt_request():
                raise CircuitBreakerOpenError(f"Circuit breaker open for {func.__name__}")
            
            try:
                result = func(*args, **kwargs)
                self._on_success()
                return result
            except self.expected_exception as e:
                self._on_failure()
                raise
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper


class RetryStrategy:
    """Retry strategy with exponential backoff."""
    
    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        retryable_exceptions: tuple = (Exception,)
    ):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.retryable_exceptions = retryable_exceptions
        
    def _calculate_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt."""
        delay = self.base_delay * (self.exponential_base ** attempt)
        delay = min(delay, self.max_delay)
        
        if self.jitter:
            delay *= (0.5 + random.random() * 0.5)  # Add 0-50% jitter
            
        return delay
    
    def __call__(self, func: Callable) -> Callable:
        """Decorator for retry logic."""
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(self.max_attempts):
                try:
                    result = await func(*args, **kwargs)
                    return result
                except self.retryable_exceptions as e:
                    last_exception = e
                    if attempt < self.max_attempts - 1:
                        delay = self._calculate_delay(attempt)
                        logger.warning(
                            f"Attempt {attempt + 1} failed for {func.__name__}, "
                            f"retrying in {delay:.2f}s: {str(e)}"
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"All {self.max_attempts} attempts failed for {func.__name__}")
                        
            raise last_exception
            
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(self.max_attempts):
                try:
                    result = func(*args, **kwargs)
                    return result
                except self.retryable_exceptions as e:
                    last_exception = e
                    if attempt < self.max_attempts - 1:
                        delay = self._calculate_delay(attempt)
                        logger.warning(
                            f"Attempt {attempt + 1} failed for {func.__name__}, "
                            f"retrying in {delay:.2f}s: {str(e)}"
                        )
                        time.sleep(delay)
                    else:
                        logger.error(f"All {self.max_attempts} attempts failed for {func.__name__}")
                        
            raise last_exception
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper


class Timeout:
    """Timeout decorator for operations."""
    
    def __init__(self, seconds: float):
        self.seconds = seconds
        
    def __call__(self, func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                result = await asyncio.wait_for(func(*args, **kwargs), timeout=self.seconds)
                return result
            except asyncio.TimeoutError:
                raise TimeoutError(f"{func.__name__} timed out after {self.seconds} seconds")
                
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # For sync functions, we can't implement proper timeout without threading
            # This is a placeholder implementation
            return func(*args, **kwargs)
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper


class BulkheadPattern:
    """Bulkhead pattern for resource isolation."""
    
    def __init__(self, max_concurrent: int = 10):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        
    def __call__(self, func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            async with self.semaphore:
                return await func(*args, **kwargs)
        return wrapper


class TradingExceptionHandler:
    """Centralized exception handling for trading operations."""
    
    def __init__(self):
        self.error_counts = {}
        self.last_errors = {}
        
    def handle_broker_error(self, broker_name: str, operation: str, error: Exception):
        """Handle broker-specific errors."""
        error_key = f"{broker_name}:{operation}:{type(error).__name__}"
        self.error_counts[error_key] = self.error_counts.get(error_key, 0) + 1
        self.last_errors[error_key] = {
            'timestamp': datetime.utcnow(),
            'error': str(error),
            'count': self.error_counts[error_key]
        }
        
        logger.error(
            f"Broker error in {broker_name}.{operation}",
            error_type=type(error).__name__,
            error_message=str(error),
            error_count=self.error_counts[error_key]
        )
        
        # Implement specific error handling logic
        if "authentication" in str(error).lower():
            self._handle_auth_error(broker_name, error)
        elif "network" in str(error).lower() or "connection" in str(error).lower():
            self._handle_network_error(broker_name, error)
        elif "rate limit" in str(error).lower():
            self._handle_rate_limit_error(broker_name, error)
        else:
            self._handle_generic_error(broker_name, operation, error)
    
    def _handle_auth_error(self, broker_name: str, error: Exception):
        """Handle authentication errors."""
        logger.critical(f"Authentication failed for {broker_name}: {error}")
        # Could trigger re-authentication workflow
        
    def _handle_network_error(self, broker_name: str, error: Exception):
        """Handle network connectivity errors."""
        logger.warning(f"Network error for {broker_name}: {error}")
        # Could trigger connection retry
        
    def _handle_rate_limit_error(self, broker_name: str, error: Exception):
        """Handle rate limiting errors."""
        logger.warning(f"Rate limit exceeded for {broker_name}: {error}")
        # Could implement backoff strategy
        
    def _handle_generic_error(self, broker_name: str, operation: str, error: Exception):
        """Handle generic errors."""
        logger.error(f"Generic error in {broker_name}.{operation}: {error}")
        
    def get_error_summary(self) -> Dict[str, Any]:
        """Get summary of recent errors."""
        return {
            'error_counts': self.error_counts.copy(),
            'recent_errors': self.last_errors.copy(),
            'timestamp': datetime.utcnow().isoformat()
        }


class HealthyInstanceSelector:
    """Select healthy instances for load balancing."""
    
    def __init__(self):
        self.instances = {}
        self.health_checks = {}
        
    def register_instance(self, name: str, instance: Any, health_check: Callable):
        """Register an instance with health check."""
        self.instances[name] = {
            'instance': instance,
            'healthy': True,
            'last_check': None,
            'failure_count': 0
        }
        self.health_checks[name] = health_check
        
    async def get_healthy_instance(self) -> Optional[Any]:
        """Get a healthy instance."""
        healthy_instances = []
        
        for name, info in self.instances.items():
            if await self._is_healthy(name):
                healthy_instances.append(info['instance'])
                
        if not healthy_instances:
            return None
            
        # Simple round-robin selection
        return random.choice(healthy_instances)
    
    async def _is_healthy(self, name: str) -> bool:
        """Check if instance is healthy."""
        try:
            health_check = self.health_checks[name]
            if asyncio.iscoroutinefunction(health_check):
                result = await health_check()
            else:
                result = health_check()
                
            self.instances[name]['healthy'] = result
            self.instances[name]['last_check'] = datetime.utcnow()
            
            if result:
                self.instances[name]['failure_count'] = 0
            else:
                self.instances[name]['failure_count'] += 1
                
            return result
        except Exception as e:
            logger.error(f"Health check failed for {name}: {e}")
            self.instances[name]['healthy'] = False
            self.instances[name]['failure_count'] += 1
            return False


# Custom exceptions
class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass


class AlgosatError(Exception):
    """Base exception for Algosat trading system with structured error information."""
    
    def __init__(self, message: str, category: ErrorCategory = ErrorCategory.SYSTEM,
                 severity: ErrorSeverity = ErrorSeverity.MEDIUM, 
                 details: Optional[str] = None, context: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.category = category
        self.severity = severity
        self.details = details
        self.context = context or {}
        self.timestamp = datetime.utcnow()
        self.error_id = f"{category.value}_{int(time.time() * 1000)}"


class TradingSystemError(AlgosatError):
    """Base exception for trading system errors."""
    def __init__(self, message: str, severity: ErrorSeverity = ErrorSeverity.HIGH, **kwargs):
        super().__init__(message, ErrorCategory.TRADING, severity, **kwargs)


class BrokerConnectionError(AlgosatError):
    """Raised when broker connection fails."""
    def __init__(self, message: str, severity: ErrorSeverity = ErrorSeverity.HIGH, **kwargs):
        super().__init__(message, ErrorCategory.BROKER_API, severity, **kwargs)


class OrderExecutionError(AlgosatError):
    """Raised when order execution fails."""
    def __init__(self, message: str, severity: ErrorSeverity = ErrorSeverity.CRITICAL, **kwargs):
        super().__init__(message, ErrorCategory.TRADING, severity, **kwargs)


class DataFeedError(AlgosatError):
    """Raised when data feed fails."""
    def __init__(self, message: str, severity: ErrorSeverity = ErrorSeverity.MEDIUM, **kwargs):
        super().__init__(message, ErrorCategory.NETWORK, severity, **kwargs)


class NetworkError(AlgosatError):
    """Network connectivity errors."""
    def __init__(self, message: str, severity: ErrorSeverity = ErrorSeverity.MEDIUM, **kwargs):
        super().__init__(message, ErrorCategory.NETWORK, severity, **kwargs)


class DatabaseError(AlgosatError):
    """Database operation errors."""
    def __init__(self, message: str, severity: ErrorSeverity = ErrorSeverity.HIGH, **kwargs):
        super().__init__(message, ErrorCategory.DATABASE, severity, **kwargs)


class ValidationError(AlgosatError):
    """Input validation errors."""
    def __init__(self, message: str, severity: ErrorSeverity = ErrorSeverity.MEDIUM, **kwargs):
        super().__init__(message, ErrorCategory.VALIDATION, severity, **kwargs)


class ErrorTracker:
    """Enhanced error tracking with database persistence and analytics."""
    
    def __init__(self, data_dir: str = "/opt/algosat/data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "resilience_errors.db"
        self._init_db()
        self.recent_errors = []
        
    def _init_db(self):
        """Initialize error tracking database."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS error_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                error_id TEXT UNIQUE NOT NULL,
                category TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                details TEXT,
                context TEXT,
                function_name TEXT,
                traceback_info TEXT,
                retry_count INTEGER DEFAULT 0,
                resolved BOOLEAN DEFAULT FALSE,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS error_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_key TEXT UNIQUE NOT NULL,
                category TEXT NOT NULL,
                occurrence_count INTEGER DEFAULT 1,
                first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                pattern_description TEXT
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recovery_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                error_id TEXT NOT NULL,
                action_type TEXT NOT NULL,
                action_description TEXT,
                success BOOLEAN DEFAULT FALSE,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (error_id) REFERENCES error_events (error_id)
            )
        """)
        
        conn.commit()
        conn.close()
    
    def track_error(self, error: Exception, function_name: str = "", retry_count: int = 0) -> str:
        """Track an error occurrence with enhanced metadata."""
        try:
            if isinstance(error, AlgosatError):
                error_id = error.error_id
                category = error.category.value
                severity = error.severity.value
                message = error.message
                details = error.details
                context = error.context
            else:
                error_id = f"SYSTEM_{int(time.time() * 1000)}"
                category = ErrorCategory.SYSTEM.value
                severity = ErrorSeverity.MEDIUM.value
                message = str(error)
                details = None
                context = {}
            
            # Store in database
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO error_events 
                (error_id, category, severity, message, details, context, function_name, 
                 traceback_info, retry_count, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                error_id, category, severity, message, details,
                json.dumps(context) if context else None, function_name,
                traceback.format_exc(), retry_count, datetime.utcnow()
            ))
            
            # Update error patterns
            pattern_key = f"{category}:{message[:100]}"
            cursor.execute("""
                INSERT OR IGNORE INTO error_patterns (pattern_key, category, pattern_description)
                VALUES (?, ?, ?)
            """, (pattern_key, category, message))
            
            cursor.execute("""
                UPDATE error_patterns 
                SET occurrence_count = occurrence_count + 1, last_seen = CURRENT_TIMESTAMP
                WHERE pattern_key = ?
            """, (pattern_key,))
            
            conn.commit()
            conn.close()
            
            # Update in-memory tracking
            self.recent_errors.append({
                'error_id': error_id,
                'category': category,
                'severity': severity,
                'message': message,
                'timestamp': datetime.utcnow(),
                'function_name': function_name
            })
            
            # Keep only recent 50 errors in memory
            if len(self.recent_errors) > 50:
                self.recent_errors.pop(0)
            
            # Log based on severity
            if severity == ErrorSeverity.CRITICAL.value:
                logger.critical(f"CRITICAL ERROR [{error_id}]: {message}", extra={'error_id': error_id})
            elif severity == ErrorSeverity.HIGH.value:
                logger.error(f"HIGH SEVERITY ERROR [{error_id}]: {message}", extra={'error_id': error_id})
            elif severity == ErrorSeverity.MEDIUM.value:
                logger.warning(f"MEDIUM SEVERITY ERROR [{error_id}]: {message}", extra={'error_id': error_id})
            else:
                logger.info(f"LOW SEVERITY ERROR [{error_id}]: {message}", extra={'error_id': error_id})
            
            return error_id
            
        except Exception as e:
            logger.error(f"Failed to track error: {e}")
            return ""
    
    def record_recovery_action(self, error_id: str, action_type: str, 
                             action_description: str, success: bool = False):
        """Record a recovery action taken for an error."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO recovery_actions 
                (error_id, action_type, action_description, success)
                VALUES (?, ?, ?, ?)
            """, (error_id, action_type, action_description, success))
            
            conn.commit()
            conn.close()
            
            logger.info(f"Recorded recovery action for {error_id}: {action_type} - {'Success' if success else 'Failed'}")
            
        except Exception as e:
            logger.error(f"Failed to record recovery action: {e}")
    
    async def get_recent_errors(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent errors from the database and in-memory cache."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT error_id, category, severity, message, function_name, timestamp
                FROM error_events 
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (limit,))
            
            db_errors = cursor.fetchall()
            conn.close()
            
            # Convert to dict format
            recent_errors = []
            for row in db_errors:
                recent_errors.append({
                    'error_id': row[0],
                    'category': row[1],
                    'severity': row[2],
                    'message': row[3],
                    'function_name': row[4] or '',
                    'timestamp': row[5],
                    'error_type': row[2]  # For backward compatibility
                })
            
            return recent_errors
            
        except Exception as e:
            logger.error(f"Failed to get recent errors: {e}")
            # Fallback to in-memory errors if database fails
            return self.recent_errors[-limit:] if self.recent_errors else []

    async def get_error_trends(self, hours: int = 24) -> Dict[str, Any]:
        """Get error trends and statistics."""
        try:
            analytics = self.get_error_analytics(hours=hours)
            
            # Extract trend data from analytics
            trends = {
                'total_errors': analytics.get('total_errors', 0),
                'time_period_hours': hours,
                'error_by_category': {},
                'error_by_severity': {},
                'hourly_trends': analytics.get('error_trends', [])
            }
            
            # Process error summary for categories and severities
            for error_summary in analytics.get('error_summary', []):
                category = error_summary['category']
                severity = error_summary['severity']
                count = error_summary['count']
                
                if category not in trends['error_by_category']:
                    trends['error_by_category'][category] = 0
                trends['error_by_category'][category] += count
                
                if severity not in trends['error_by_severity']:
                    trends['error_by_severity'][severity] = 0
                trends['error_by_severity'][severity] += count
            
            return trends
            
        except Exception as e:
            logger.error(f"Failed to get error trends: {e}")
            return {
                'total_errors': 0,
                'time_period_hours': hours,
                'error_by_category': {},
                'error_by_severity': {},
                'hourly_trends': []
            }

    def get_error_analytics(self, hours: int = 24) -> Dict[str, Any]:
        """Get comprehensive error analytics."""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)
            
            # Error summary by category and severity
            cursor.execute("""
                SELECT category, severity, COUNT(*) as count
                FROM error_events 
                WHERE timestamp >= ?
                GROUP BY category, severity
                ORDER BY count DESC
            """, (cutoff_time,))
            error_summary = cursor.fetchall()
            
            # Top error patterns
            cursor.execute("""
                SELECT p.pattern_key, p.category, p.occurrence_count, p.pattern_description
                FROM error_patterns p
                WHERE p.last_seen >= ?
                ORDER BY p.occurrence_count DESC
                LIMIT 10
            """, (cutoff_time,))
            top_patterns = cursor.fetchall()
            
            # Recovery success rate
            cursor.execute("""
                SELECT 
                    action_type,
                    COUNT(*) as total_actions,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful_actions
                FROM recovery_actions r
                JOIN error_events e ON r.error_id = e.error_id
                WHERE e.timestamp >= ?
                GROUP BY action_type
            """, (cutoff_time,))
            recovery_stats = cursor.fetchall()
            
            # Error trend by hour
            cursor.execute("""
                SELECT 
                    strftime('%Y-%m-%d %H:00:00', timestamp) as hour,
                    COUNT(*) as error_count,
                    severity
                FROM error_events 
                WHERE timestamp >= ?
                GROUP BY strftime('%Y-%m-%d %H:00:00', timestamp), severity
                ORDER BY hour
            """, (cutoff_time,))
            error_trends = cursor.fetchall()
            
            conn.close()
            
            return {
                'time_period_hours': hours,
                'total_errors': sum(row[2] for row in error_summary),
                'error_summary': [
                    {'category': row[0], 'severity': row[1], 'count': row[2]}
                    for row in error_summary
                ],
                'top_error_patterns': [
                    {'pattern': row[0], 'category': row[1], 'count': row[2], 'description': row[3]}
                    for row in top_patterns
                ],
                'recovery_stats': [
                    {
                        'action_type': row[0], 
                        'total_actions': row[1], 
                        'successful_actions': row[2],
                        'success_rate': (row[2] / row[1] * 100) if row[1] > 0 else 0
                    }
                    for row in recovery_stats
                ],
                'error_trends': [
                    {'hour': row[0], 'count': row[1], 'severity': row[2]}
                    for row in error_trends
                ]
            }
            
        except Exception as e:
            logger.error(f"Failed to generate error analytics: {e}")
            return {}


# Enhanced resilience decorators
def resilient_operation(max_retries: int = 3, circuit_breaker: Optional[CircuitBreaker] = None,
                       timeout_seconds: Optional[float] = None, 
                       error_tracker: Optional[ErrorTracker] = None):
    """Enhanced decorator combining retry, circuit breaker, timeout, and error tracking."""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    # Apply timeout if specified
                    if timeout_seconds:
                        result = await asyncio.wait_for(
                            func(*args, **kwargs), 
                            timeout=timeout_seconds
                        )
                    else:
                        result = await func(*args, **kwargs)
                    
                    # Record successful recovery if this was a retry
                    if attempt > 0 and error_tracker and last_exception:
                        error_id = error_tracker.track_error(last_exception, func.__name__, attempt)
                        error_tracker.record_recovery_action(
                            error_id, "RETRY_SUCCESS", 
                            f"Operation succeeded after {attempt} retries", True
                        )
                    
                    return result
                    
                except Exception as e:
                    last_exception = e
                    
                    # Track error
                    if error_tracker:
                        error_id = error_tracker.track_error(e, func.__name__, attempt)
                        if attempt < max_retries:
                            error_tracker.record_recovery_action(
                                error_id, "RETRY_ATTEMPT",
                                f"Retry attempt {attempt + 1} of {max_retries}", False
                            )
                    
                    if attempt == max_retries:
                        # Final attempt failed
                        if error_tracker:
                            error_tracker.record_recovery_action(
                                error_id, "RETRY_EXHAUSTED",
                                f"All {max_retries + 1} attempts failed", False
                            )
                        break
                    
                    # Calculate delay for next retry
                    delay = min(2 ** attempt, 60)  # Exponential backoff with max 60s
                    delay *= (0.5 + random.random() * 0.5)  # Add jitter
                    
                    logger.warning(f"Attempt {attempt + 1} failed for {func.__name__}, retrying in {delay:.2f}s: {e}")
                    await asyncio.sleep(delay)
            
            # All retries exhausted
            raise last_exception
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            # Similar logic for sync functions
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    result = func(*args, **kwargs)
                    
                    if attempt > 0 and error_tracker and last_exception:
                        error_id = error_tracker.track_error(last_exception, func.__name__, attempt)
                        error_tracker.record_recovery_action(
                            error_id, "RETRY_SUCCESS",
                            f"Operation succeeded after {attempt} retries", True
                        )
                    
                    return result
                    
                except Exception as e:
                    last_exception = e
                    
                    if error_tracker:
                        error_id = error_tracker.track_error(e, func.__name__, attempt)
                        if attempt < max_retries:
                            error_tracker.record_recovery_action(
                                error_id, "RETRY_ATTEMPT",
                                f"Retry attempt {attempt + 1} of {max_retries}", False
                            )
                    
                    if attempt == max_retries:
                        if error_tracker:
                            error_tracker.record_recovery_action(
                                error_id, "RETRY_EXHAUSTED",
                                f"All {max_retries + 1} attempts failed", False
                            )
                        break
                    
                    delay = min(2 ** attempt, 60)
                    delay *= (0.5 + random.random() * 0.5)
                    
                    logger.warning(f"Attempt {attempt + 1} failed for {func.__name__}, retrying in {delay:.2f}s: {e}")
                    time.sleep(delay)
            
            raise last_exception
        
        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    
    return decorator


# Custom exceptions
class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass


class TradingSystemError(Exception):
    """Base exception for trading system errors."""
    pass


class BrokerConnectionError(TradingSystemError):
    """Raised when broker connection fails."""
    pass


class OrderExecutionError(TradingSystemError):
    """Raised when order execution fails."""
    pass


class DataFeedError(TradingSystemError):
    """Raised when data feed fails."""
    pass


# Pre-configured resilience patterns with enhanced error tracking
error_tracker = ErrorTracker()

broker_circuit_breaker = CircuitBreaker(
    failure_threshold=3,
    timeout=300,  # 5 minutes
    expected_exception=(BrokerConnectionError, ConnectionError, TimeoutError)
)

order_retry = RetryStrategy(
    max_attempts=3,
    base_delay=1.0,
    max_delay=10.0,
    retryable_exceptions=(OrderExecutionError, ConnectionError)
)

data_feed_retry = RetryStrategy(
    max_attempts=5,
    base_delay=0.5,
    max_delay=5.0,
    retryable_exceptions=(DataFeedError, ConnectionError)
)

order_timeout = Timeout(30.0)  # 30 seconds
data_timeout = Timeout(10.0)   # 10 seconds

# Enhanced global instances
exception_handler = TradingExceptionHandler()
broker_selector = HealthyInstanceSelector()

# Enhanced decorators with error tracking
@resilient_operation(max_retries=3, timeout_seconds=30.0, error_tracker=error_tracker)
async def resilient_broker_call(func, *args, **kwargs):
    """Resilient wrapper for broker API calls."""
    return await func(*args, **kwargs)

@resilient_operation(max_retries=2, timeout_seconds=10.0, error_tracker=error_tracker)
async def resilient_database_call(func, *args, **kwargs):
    """Resilient wrapper for database calls."""
    return await func(*args, **kwargs)

@resilient_operation(max_retries=5, timeout_seconds=5.0, error_tracker=error_tracker)
async def resilient_data_feed_call(func, *args, **kwargs):
    """Resilient wrapper for data feed calls."""
    return await func(*args, **kwargs)
