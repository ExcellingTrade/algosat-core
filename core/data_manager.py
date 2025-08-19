"""Market data caching and rate-limiting utilities."""

import asyncio
import shelve
from datetime import datetime, timedelta
from cachetools import TTLCache
import inspect
import pandas as pd
from algosat.common.logger import get_logger
from algosat.models.order_aggregate import OrderAggregate, BrokerOrder
from typing import List, Dict, Any, Optional, Union
from algosat.core.db import get_broker_executions_for_order, get_order_by_id
from algosat.core.async_retry import async_retry_with_rate_limit, RetryConfig, get_retry_config

logger = get_logger("data_manager")

# Per-broker rate limit settings moved to algosat.core.rate_limiter.py
# Use GlobalRateLimiter.DEFAULT_RATE_CONFIGS for all rate limiting configuration

class _CacheManager:
    """
    A hybrid in-memory + persistent disk cache manager.
    """
    def __init__(self, maxsize: int = 512, shelve_path: str = "/tmp/algosat_cache.db"):
        self.caches: Dict[int, TTLCache] = {}
        self.maxsize = maxsize
        self.shelve_path = shelve_path

    def get_cache(self, ttl: int) -> TTLCache:
        if ttl not in self.caches:
            self.caches[ttl] = TTLCache(maxsize=self.maxsize, ttl=ttl)
        return self.caches[ttl]

    def get(self, key: str, ttl: int = 60) -> Any:
        # Check in-memory
        cache = self.get_cache(ttl)
        if key in cache:
            return cache[key]
        # Check shelve
        with shelve.open(self.shelve_path) as db:
            return db.get(key)

    def set(self, key: str, value: Any, ttl: int = 60) -> None:
        cache = self.get_cache(ttl)
        cache[key] = value
        with shelve.open(self.shelve_path) as db:
            db[key] = value

    @staticmethod
    def seconds_until_midnight_ist() -> int:
        now = datetime.utcnow() + timedelta(hours=5, minutes=30)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return int((tomorrow - now).total_seconds())

class _RateLimiter:
    def __init__(self, max_calls: int, interval_sec: float):
        self.semaphore = asyncio.Semaphore(max_calls)
        self.interval = interval_sec

    async def __aenter__(self) -> None:
        await self.semaphore.acquire()

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await asyncio.sleep(self.interval)
        self.semaphore.release()


# Legacy per-broker rate limiter map - DEPRECATED
# Now using GlobalRateLimiter through broker_manager coordination
# The rate_limiter_map parameter is maintained for backward compatibility
# but new implementations should use the global rate limiter via broker_manager

def validate_broker_response(response: Any, expected_type: str = "option_chain", symbol: Optional[str] = None) -> bool:
    """Validate broker API response. Return True if valid, False if invalid."""
    try:
        if expected_type == "option_chain":
            if not (isinstance(response, dict) and response.get("code", response.get("statuscode")) == 200 and response.get("data") and response["data"].get("optionsChain")):
                logger.debug(f"Invalid option chain data received for '{symbol}': {response}")
                return False
        elif expected_type == "history":
            if response is None:
                logger.debug(f"No history data received for '{symbol}' (None returned)")
                return False
            if isinstance(response, pd.DataFrame):
                required_cols = {"timestamp", "open", "high", "low", "close", "volume"}
                if not required_cols.issubset(set(response.columns)) or response.empty:
                    logger.debug(f"Invalid DataFrame for history for '{symbol}': columns={response.columns}, empty={response.empty}")
                    return False
            else:
                logger.debug(f"Invalid history data type for '{symbol}': {type(response)}")
                return False
        elif expected_type == "ltp":
            if response is None:
                logger.debug(f"No LTP data received for '{symbol}' (None returned)")
                return False
        else:
            if not (isinstance(response, dict) and response.get("code", response.get("statuscode")) == 200 and response.get("data")):
                logger.debug(f"Invalid data received for '{symbol}': {response}")
                return False
        return True
    except Exception as e:
        logger.error(f"Exception in validate_broker_response for {expected_type} {symbol}: {e}")
        return False

def standardize_order_status(broker_name, raw_status, raw_response=None):
    """
    Map broker-specific order status to standardized status.
    Supported: FILLED, PARTIALLY_FILLED, REJECTED, CANCELLED, PENDING
    """
    zerodha_pending_statuses = {
        "PUT ORDER REQ RECEIVED", "VALIDATION PENDING", "OPEN PENDING", "MODIFY VALIDATION PENDING",
        "MODIFY PENDING", "TRIGGER PENDING", "CANCEL PENDING", "AMO REQ RECEIVED"
    }
    if broker_name == "fyers":
        # Fyers status is usually int, but sometimes string (e.g., 'PARTIAL')
        try:
            status = int(raw_status) if raw_status is not None and str(raw_status).isdigit() else None
        except Exception:
            status = None
        if status == 2:
            remaining = raw_response.get("remainingQuantity") if raw_response else None
            if remaining is not None and remaining > 0:
                return "PARTIALLY_FILLED"
            return "FILLED"
        elif status == 5:
            return "REJECTED"
        elif status == 1:
            return "CANCELLED"
        elif status == 6:
            return "PENDING"
        # Handle string status like 'PARTIAL'
        if isinstance(raw_status, str) and raw_status.upper() in ("PARTIAL", "PARTIALLY_FILLED"):
            return "PARTIALLY_FILLED"
        elif isinstance(raw_status, str) and raw_status.upper() == "FILLED":
            return "FILLED"
        elif isinstance(raw_status, str) and raw_status.upper() == "REJECTED":
            return "REJECTED"
        elif isinstance(raw_status, str) and raw_status.upper() == "CANCELLED":
            return "CANCELLED"
        elif isinstance(raw_status, str) and raw_status.upper() == "PENDING":
            return "PENDING"
        else:
            return "PENDING"
    elif broker_name == "zerodha":
        # Zerodha status is string
        status = str(raw_status).upper() if raw_status else ""
        if status in zerodha_pending_statuses:
            return "PENDING"
        elif status == "COMPLETE" or status == "FILLED":
            # Check for partial fill
            pending = raw_response.get("pending_quantity") if raw_response else None
            if pending is not None and pending > 0:
                return "PARTIALLY_FILLED"
            return "FILLED"
        elif status == "REJECTED":
            return "REJECTED"
        elif status == "CANCELLED":
            return "CANCELLED"
        else:
            return "PENDING"
    else:
        # Default fallback
        return str(raw_status).upper() if raw_status else "PENDING"

class DataManager:
    """
    Central data manager responsible for broker API access,
    global rate-limiting coordination with broker_manager, and caching.
    """
    def __init__(self, 
                 broker: Optional[Any] = None, 
                 broker_name: Optional[str] = None, 
                 cache: Optional[_CacheManager] = None, 
                 rate_limiter: Optional[_RateLimiter] = None, 
                 rate_limiter_map: Optional[Dict[str, _RateLimiter]] = None, 
                 broker_manager: Optional[Any] = None):
        self.broker = broker
        self.broker_name = broker_name
        self.broker_manager = broker_manager
        self.cache = cache or _CacheManager()
        self.rate_limiter = rate_limiter or _RateLimiter(max_calls=10, interval_sec=1)
        self.rate_limiter_map = rate_limiter_map or {}
        # Broker name cache with 24-hour TTL (broker names rarely change)
        self._broker_name_cache = TTLCache(maxsize=100, ttl=24 * 60 * 60)

    def get_current_broker_name(self) -> Optional[str]:
        if self.broker_name:
            return self.broker_name
        # Try to get name from broker object if possible
        if self.broker and hasattr(self.broker, "name"):
            return self.broker.name
        return None

    def get_active_rate_limiter(self) -> _RateLimiter:
        broker_name = self.get_current_broker_name()
        if broker_name and broker_name in self.rate_limiter_map:
            return self.rate_limiter_map[broker_name]
        return self.rate_limiter

    async def _ensure_rate_limiter(self):
        """Ensure the broker manager's global rate limiter is available."""
        if self.broker_manager and hasattr(self.broker_manager, '_ensure_rate_limiter'):
            await self.broker_manager._ensure_rate_limiter()

    def _get_data_retry_config(self, operation_type: str = "data_fetch") -> RetryConfig:
        """Get retry configuration for data operations with global rate limiting."""
        config = get_retry_config(operation_type)
        broker_name = self.get_current_broker_name()
        if broker_name:
            config.rate_limit_broker = broker_name
            config.rate_limit_tokens = 1
        return config

    async def ensure_broker(self) -> None:
        try:
            logger.debug(f"Entering ensure_broker. Current broker: {self.broker}, broker_name: {self.broker_name}")
            if self.broker:
                logger.debug(f"Broker already set: {self.broker} (type: {type(self.broker)})")
                return
            if self.broker_manager:
                logger.debug(f"Attempting to get broker from broker_manager with broker_name: {self.broker_name}")
                try:
                    self.broker = await self.broker_manager.get_data_broker(broker_name=self.broker_name)
                    logger.debug(f"Broker set from manager: {self.broker} (type: {type(self.broker)})")
                except Exception as e:
                    logger.error(f"Exception in get_data_broker: {e}", exc_info=True)
                    raise
                if not self.broker_name and self.broker:
                    for name, broker in self.broker_manager.brokers.items():
                        if broker is self.broker:
                            self.broker_name = name
                            logger.debug(f"broker_name set from broker_manager mapping: {self.broker_name}")
                            break
            if not self.broker:
                logger.error("No broker available for DataManager! Raising RuntimeError.")
                raise RuntimeError("No broker available for DataManager!")
            logger.debug(f"Exiting ensure_broker. Final broker: {self.broker}, broker_name: {self.broker_name}")
        except Exception as e:
            logger.error(f"Error in ensure_broker: {e}", exc_info=True)
            raise

    async def get_option_chain(self, symbol: str, expiry: Optional[str] = None, ttl: int = 120) -> Dict[str, Any]:
        try:
            if not self.broker:
                raise RuntimeError("Broker not set in DataManager. Call ensure_broker() first.")
            cache_key = f"option_chain:{symbol}:{expiry}"
            cached = self.cache.get(cache_key, ttl=ttl)
            if cached is not None:
                return cached

            # Ensure global rate limiter is available
            await self._ensure_rate_limiter()
            retry_config = self._get_data_retry_config("data_fetch")

            async def _fetch():
                result = self.broker.get_option_chain(symbol, expiry)
                option_chain = await result if inspect.isawaitable(result) else result
                if not validate_broker_response(option_chain, expected_type="option_chain", symbol=symbol):
                    logger.error(f"Invalid option chain data received for '{symbol}' (after all retries)")
                    raise RuntimeError(f"Invalid option chain data received for '{symbol}'")
                self.cache.set(cache_key, option_chain, ttl=ttl)
                return option_chain

            return await async_retry_with_rate_limit(_fetch, config=retry_config)
        except Exception as e:
            logger.error(f"Error in get_option_chain for symbol={symbol}, expiry={expiry}: {e}", exc_info=True)
            raise

    async def get_history(self, 
                          symbol: str, 
                          from_date: Union[str, datetime], 
                          to_date: Union[str, datetime], 
                          ohlc_interval: Union[int, str], 
                          ins_type: str = "", 
                          ttl: int = 600, 
                          cache: bool = True) -> pd.DataFrame:
        try:
            if not self.broker:
                raise RuntimeError("Broker not set in DataManager. Call ensure_broker() first.")
            from algosat.core.time_utils import get_ist_datetime, localize_to_ist
            ist_now = get_ist_datetime()
            from_dt = pd.to_datetime(from_date)
            to_dt = pd.to_datetime(to_date)
            
            # Convert naive datetimes to IST timezone-aware for comparison
            if from_dt.tz is None:
                from_dt = localize_to_ist(from_dt)
            if to_dt.tz is None:
                to_dt = localize_to_ist(to_dt)
                
            if from_dt > ist_now:
                from algosat.common.broker_utils import get_trade_day
                prev_trade_day = get_trade_day(ist_now - timedelta(days=1))
                from_time = from_dt.time()
                from_dt = datetime.combine(prev_trade_day, from_time)
                logger.debug(f"Adjusted from_date to previous trade day (IST): {from_dt} for symbol {symbol}")
            if to_dt > ist_now:
                from algosat.common.broker_utils import get_trade_day
                prev_trade_day = get_trade_day(ist_now - timedelta(days=1))
                to_time = to_dt.time()
                to_dt = datetime.combine(prev_trade_day, to_time)
                logger.debug(f"Adjusted to_date to previous trade day (IST): {to_dt} for symbol {symbol}")
            cache_key = f"history:{symbol}:{from_dt}:{to_dt}:{ohlc_interval}:{ins_type}"
            if cache:
                cached = self.cache.get(cache_key, ttl=ttl)
                if cached is not None:
                    logger.debug(f"Cache hit for history: {cache_key}") 
                    return cached

            # Ensure global rate limiter is available
            await self._ensure_rate_limiter()
            retry_config = self._get_data_retry_config("data_fetch")

            async def _fetch():
                result = self.broker.get_history(symbol, from_dt, to_dt, ohlc_interval, ins_type)
                history = await result if inspect.isawaitable(result) else result
                if not validate_broker_response(history, expected_type="history", symbol=symbol):
                    logger.debug(f"Invalid history data received for '{symbol}' (after all retries). Response: {history}")
                    # Don't raise exception for history validation failures - just return None
                if cache and history is not None:
                    self.cache.set(cache_key, history, ttl=ttl)
                return history

            return await async_retry_with_rate_limit(_fetch, config=retry_config)
        except Exception as e:
            logger.error(f"Error in get_history for symbol={symbol}: {e}", exc_info=True)
            return None  # Return None instead of raising for history errors

    async def get_ltp(self, symbol: str, ttl: int = 5) -> Any:
        """
        Get the last traded price (LTP) for the given symbol.
        Always fetch fresh data from the broker, do not use cache.
        """
        try:
            if not self.broker:
                raise RuntimeError("Broker not set in DataManager. Call ensure_broker() first.")

            # Ensure global rate limiter is available
            await self._ensure_rate_limiter()
            retry_config = self._get_data_retry_config("data_fetch")

            async def _fetch():
                result = self.broker.get_ltp(symbol)
                ltp = await result if inspect.isawaitable(result) else result
                validate_broker_response(ltp, expected_type="ltp", symbol=symbol)
                return ltp

            return await async_retry_with_rate_limit(_fetch, config=retry_config)
        except Exception as e:
            logger.error(f"Error in get_ltp for symbol={symbol}: {e}", exc_info=True)
            raise

    async def fetch_history(self, symbol: str, interval_minutes: int = 1, lookback: int = 1) -> Optional[pd.DataFrame]:
        """
        Fetch history for a single symbol using strategy_utils.fetch_instrument_history.
        This method provides a simplified interface for single symbol history fetching.
        
        Args:
            symbol: The trading symbol
            interval_minutes: OHLC interval in minutes (default: 1)
            lookback: Number of periods to look back (default: 1)
            
        Returns:
            DataFrame with OHLC data or None if error
        """
        try:
            from datetime import datetime, timedelta
            from algosat.core.time_utils import get_ist_datetime
            from algosat.common.strategy_utils import fetch_instrument_history
            
            # Calculate date range based on lookback
            end_time = get_ist_datetime()
            # Calculate how many days back we need based on interval and lookback
            # Add extra buffer for weekends and holidays
            days_back = max(1, (lookback * interval_minutes) // (6 * 60) + 3)  # Rough estimate
            start_time = end_time - timedelta(days=days_back)
            
            # Use fetch_instrument_history for a single symbol
            history_data = await fetch_instrument_history(
                broker=self,
                strike_symbols=[symbol],
                from_date=start_time,
                to_date=end_time,
                interval_minutes=interval_minutes,
                ins_type="",
                cache=True
            )
            
            # Return the data for our symbol, or None if not found
            return history_data.get(symbol)
            
        except Exception as e:
            logger.error(f"Error in fetch_history for symbol={symbol}, interval_minutes={interval_minutes}, lookback={lookback}: {e}", exc_info=True)
            return None
        
    async def get_strike_list(self, symbol, max_strikes=40):
        try:
            if not self.broker:
                raise RuntimeError("Broker not set in DataManager. Call ensure_broker() first.")
            if hasattr(self.broker, "get_strike_list"):
                return await self.broker.get_strike_list(symbol, max_strikes)
            raise NotImplementedError(f"Broker {self.get_current_broker_name()} does not implement get_strike_list.")
        except Exception as e:
            logger.error(f"Error in get_strike_list for symbol={symbol}: {e}", exc_info=True)
            raise

    async def get_broker_symbol(self, symbol, instrument_type=None):
        # NOTE: All downstream order response handling expects order_id (string) and order_message (string).
        # Legacy order_ids/order_messages (list/dict) are no longer supported.
        try:
            broker_name = self.get_current_broker_name()
            if not self.broker_manager or not broker_name:
                raise RuntimeError("BrokerManager or broker_name not set in DataManager.")
            return await self.broker_manager.get_symbol_info(broker_name, symbol, instrument_type)
        except Exception as e:
            logger.error(f"Error in get_broker_symbol for symbol={symbol}, instrument_type={instrument_type}: {e}", exc_info=True)
            raise

    async def get_order_aggregate(self, parent_order_id: int) -> Optional[OrderAggregate]:
        from algosat.core.db import AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            order_row = await get_order_by_id(session, parent_order_id)
            if order_row is None:
                logger.warning(f"OrderAggregate: No order found for parent_order_id={parent_order_id}. It may have been deleted.")
                return None
            
            # Get broker executions for main order
            broker_execs = await get_broker_executions_for_order(session, parent_order_id)
            
            symbol = order_row.get("strike_symbol", "Unknown")
            broker_orders: List[BrokerOrder] = []
            for be in broker_execs:
                broker_name = await self.get_broker_name_by_id(be.get("broker_id"))
                std_status = standardize_order_status(
                    broker_name,
                    be.get("status"),
                    be.get("raw_response")
                )
                broker_orders.append(BrokerOrder(
                    id=be.get("id"),  # Pass the broker_executions table id
                    broker_id=be.get("broker_id"),
                    order_id=be.get("broker_order_id"),
                    status=std_status,
                    broker_name=broker_name,
                    side=be.get("side"),
                    symbol=be.get("symbol"),  # Use order symbol if available
                    raw_response=be.get("raw_response")
                ))
            return OrderAggregate(
                strategy_config_id=order_row.get("strategy_symbol_id"),
                parent_order_id=parent_order_id,
                symbol=symbol,
                entry_price=order_row.get("entry_price"),
                side=order_row.get("side"),
                broker_orders=broker_orders
            )

    async def get_broker_name_by_id(self, broker_id: int) -> str:
        """
        Get broker name by ID with 24-hour caching.
        Broker names rarely change, so we can cache them for a long time.
        """
        if broker_id is None:
            return None
            
        # Check cache first
        if broker_id in self._broker_name_cache:
            return self._broker_name_cache[broker_id]
        
        # Cache miss - fetch from database
        try:
            from algosat.core.db import AsyncSessionLocal, get_broker_by_id
            async with AsyncSessionLocal() as session:
                broker = await get_broker_by_id(session, broker_id)
                broker_name = broker["broker_name"] if broker else None
                
                # Cache the result (TTLCache handles expiration automatically)
                if broker_name is not None:
                    self._broker_name_cache[broker_id] = broker_name
                    
                return broker_name
        except Exception as e:
            logger.error(f"Error in get_broker_name_by_id for broker_id={broker_id}: {e}", exc_info=True)
            raise

    def clear_broker_name_cache(self, broker_id: int = None):
        """
        Clear broker name cache. If broker_id is specified, clear only that entry.
        Otherwise, clear entire cache.
        """
        if broker_id is not None:
            self._broker_name_cache.pop(broker_id, None)
        else:
            self._broker_name_cache.clear()

