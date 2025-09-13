# core/broker_manager.py

import asyncio
from typing import Dict, Optional, List, Callable
from algosat.brokers.factory import get_broker
from algosat.common.broker_utils import get_broker_credentials, upsert_broker_credentials, update_broker_status
from algosat.common.default_broker_configs import DEFAULT_BROKER_CONFIGS
from algosat.common.logger import get_logger
from algosat.core.time_utils import get_ist_now
from algosat.core.rate_limiter import get_rate_limiter, RateConfig
from algosat.core.async_retry import async_retry_with_rate_limit, RetryConfig, get_retry_config, broker_retry
from algosat.core.db import AsyncSessionLocal, get_strategy_by_id, get_trade_enabled_brokers as db_get_trade_enabled_brokers
from datetime import datetime, time as dt_time
from algosat.core.order_request import OrderRequest, OrderType, Side
from algosat.core.signal import TradeSignal, SignalType
from algosat.core.order_defaults import ORDER_DEFAULTS
from algosat.models.strategy_config import StrategyConfig

logger = get_logger("BrokerManager")

# Broker-specific rate limits moved to algosat.core.rate_limiter.py
# Use GlobalRateLimiter.DEFAULT_RATE_CONFIGS for all rate limiting configuration

def is_retryable_exception(exc):
    # Customize this as needed: don't retry on 4xx errors (e.g., BadRequest), retry on network/server errors
    if hasattr(exc, 'status_code'):
        # Example: HTTPException with status_code
        return not (400 <= exc.status_code < 500)
    if isinstance(exc, ValueError):
        # ValueError often means bad input, don't retry
        return False
    # Add more logic as needed
    return True

async def async_retry(func: Callable, *args, retries=3, delay=1, **kwargs):
    """Legacy async retry function - DEPRECATED, use async_retry_with_rate_limit instead."""
    last_exc = None
    for attempt in range(retries):
        try:
            return await func(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if not is_retryable_exception(exc):
                raise
            if attempt < retries - 1:
                logger.warning(f"Retryable error in {func.__name__}: {exc}. Retrying ({attempt+1}/{retries})...")
                await asyncio.sleep(delay)
    raise last_exc

async def is_token_stale(broker_key: str) -> bool:
    """
    Check if the broker's token is stale (generated before today's 6:00 AM IST).
    Returns True if token needs refresh, False if still valid.
    """
    try:
        full_config = await get_broker_credentials(broker_key)
        if not full_config or not isinstance(full_config, dict):
            return True  # No config means we need to authenticate
        
        credentials = full_config.get("credentials", {})
        generated_on_str = credentials.get("generated_on")
        
        if not generated_on_str:
            return True  # No generation time means we need to authenticate
        
        # Parse the generated_on timestamp (format: "DD/MM/YYYY HH:MM:SS")
        try:
            generated_on_naive = datetime.strptime(generated_on_str, "%d/%m/%Y %H:%M:%S")
        except ValueError:
            logger.warning(f"Invalid generated_on format for {broker_key}: {generated_on_str}")
            return True
        
        # Convert the parsed datetime to IST timezone-aware datetime
        from algosat.core.time_utils import localize_to_ist
        generated_on = localize_to_ist(generated_on_naive)
        
        # Get current IST time and today's 6:00 AM IST
        now_ist = get_ist_now()
        today_6am = now_ist.replace(hour=6, minute=0, second=0, microsecond=0)
        
        # If current time is before 6 AM, check against yesterday's 6 AM
        if now_ist.time() < dt_time(6, 0):
            from datetime import timedelta
            today_6am = today_6am - timedelta(days=1)
        
        # Token is stale if it was generated before today's 6:00 AM
        is_stale = generated_on < today_6am
        
        if is_stale:
            logger.info(f"Token for {broker_key} is stale (generated: {generated_on_str}, cutoff: {today_6am})")
        else:
            logger.debug(f"Token for {broker_key} is still valid (generated: {generated_on_str}, cutoff: {today_6am})")
        
        return is_stale
    except Exception as e:
        logger.error(f"Error checking token staleness for {broker_key}: {e}")
        return True  # On error, assume stale and re-authenticate

class BrokerManager:
    def __init__(self):
        self.brokers: Dict[str, object] = {}
        # --- Symbol/Instrument resolution for all brokers ---
        self._instrument_cache = {}
        self._rate_limiter = None  # Will be initialized async

    async def _ensure_rate_limiter(self):
        """Initialize rate limiter if not already done."""
        if self._rate_limiter is None:
            self._rate_limiter = await get_rate_limiter()
            
            # Configure rate limits using global configuration
            from algosat.core.rate_limiter import GlobalRateLimiter
            global_limiter = await GlobalRateLimiter.get_instance()
            for broker_name, rate_config in global_limiter._rate_configs.items():
                # Use the global rate configuration directly
                self._rate_limiter.configure_broker(broker_name, rate_config)
                logger.info(f"Configured trading rate limits for {broker_name}: {rate_config.rps} rps, burst: {rate_config.burst}")

    async def _discover_enabled_brokers(self) -> List[str]:
        # Discover all brokers that have credentials or default configs
        enabled_brokers = []
        # Get all broker keys from default configs
        all_broker_keys = list(DEFAULT_BROKER_CONFIGS.keys())
        for broker_key in all_broker_keys:
            full_config = await get_broker_credentials(broker_key)
            if not full_config:
                full_config = DEFAULT_BROKER_CONFIGS.get(broker_key)
                if full_config:
                    if "credentials" not in full_config:
                        full_config["credentials"] = {}
                    if "required_auth_fields" not in full_config:
                        full_config["required_auth_fields"] = []
                    await upsert_broker_credentials(broker_key, full_config)
                    enabled_brokers.append(broker_key)
            else:
                enabled_brokers.append(broker_key)
        return enabled_brokers

    async def _prompt_for_missing_credentials(self, broker_key: str) -> bool:
        logger.debug(f"🔑 Prompting for missing credentials for broker: {broker_key}")
        full_config = await get_broker_credentials(broker_key)
        if not full_config:
            logger.warning(f"🟡 No configuration found for {broker_key}. Skipping credential prompt.")
            return False
        current_credentials = full_config.get("credentials", {})
        required_fields = full_config.get("required_auth_fields", [])
        if not required_fields:
            logger.warning(f"🟡 No required authentication fields defined for {broker_key}. Skipping prompt.")
            return False
        credentials_updated = False
        for field in required_fields:
            if not current_credentials.get(field):
                value = input(f"Enter {field} for broker {broker_key}: ")
                if value:
                    current_credentials[field] = value
                    credentials_updated = True
        if credentials_updated:
            full_config["credentials"] = current_credentials
            await upsert_broker_credentials(broker_key, full_config)
            logger.info(f"🟢 Credentials updated for {broker_key}")
            return True
        return False

    async def _authenticate_broker(self, broker_key: str, retries=3, delay=1, force_reauth: bool = False) -> bool:
        broker = get_broker(broker_key)
        if not broker:
            logger.error(f"🔴 Could not instantiate broker: {broker_key}")
            self.brokers[broker_key] = None
            return False
        try:
            import inspect
            if hasattr(broker, 'login') and 'force_reauth' in inspect.signature(broker.login).parameters:
                success = await async_retry(broker.login, force_reauth=force_reauth, retries=retries, delay=delay)
            else:
                success = await async_retry(broker.login, retries=retries, delay=delay)
        except Exception as e:
            logger.error(f"🔴 Broker login failed for {broker_key}: {e}")
            self.brokers[broker_key] = None
            return False
        self.brokers[broker_key] = broker if success else None
        if success:
            logger.info(f"🟢 Authentication successful for {broker_key}")
            # For Zerodha, fetch and cache instruments as DataFrame after login/profile
            if broker_key == 'zerodha' and hasattr(broker, 'kite') and broker.kite:
                try:
                    import pandas as pd
                    loop = asyncio.get_event_loop()
                    # Fetch instruments as DataFrame asynchronously
                    instruments = await loop.run_in_executor(None, lambda: pd.DataFrame(broker.kite.instruments()))
                    self._instrument_cache['zerodha'] = instruments
                    logger.info("Zerodha instruments cached as DataFrame after auth.")
                except Exception as e:
                    logger.warning(f"Failed to fetch Zerodha instruments after auth: {e}")
        else:
            logger.warning(f"🟡 Authentication failed for {broker_key}")
        return success

    async def setup(self, poll_interval=2, max_wait=60, force_auth=False):
        logger.debug("🔄 Starting BrokerManager setup...")
        enabled_brokers = await self._discover_enabled_brokers()
        from algosat.core.db import AsyncSessionLocal, get_broker_by_name
        for broker_key in enabled_brokers:
            await self._prompt_for_missing_credentials(broker_key)
            # Check broker status in DB
            status = None
            wait_time = 0
            while True:
                async with AsyncSessionLocal() as session:
                    broker_row = await get_broker_by_name(session, broker_key)
                    status = broker_row["status"] if broker_row else None
                if status == "AUTHENTICATING":
                    if wait_time >= max_wait:
                        logger.warning(f"Timeout waiting for {broker_key} to finish authenticating. Proceeding to authenticate.")
                        reason = "Timeout waiting for authentication"
                        await update_broker_status(broker_key, "ERROR", notes=f"Re-authentication failed ({reason})")
                        break
                    logger.info(f"{broker_key} is currently authenticating. Waiting...")
                    await asyncio.sleep(poll_interval)
                    wait_time += poll_interval
                elif status == "CONNECTED":
                    # Check if token is stale even if status is CONNECTED
                    token_is_stale = await is_token_stale(broker_key)
                    if force_auth or token_is_stale:
                        reason = "force_auth is set" if force_auth else "token is stale"
                        logger.info(f"{broker_key} is CONNECTED but {reason}. Proceeding to re-authenticate.")
                        await update_broker_status(broker_key, "AUTHENTICATING", notes=f"Re-authenticating ({reason})...")
                        success = await self._authenticate_broker(broker_key, force_reauth=True)
                        status_final = "CONNECTED" if success else "ERROR"
                        await update_broker_status(broker_key, status_final, notes="" if success else f"Re-authentication failed ({reason})")
                    else:
                        logger.info(f"{broker_key} is already CONNECTED and token is fresh. Re-instantiating and authenticating broker wrapper.")
                        # Re-instantiate and authenticate the broker wrapper
                        broker = get_broker(broker_key)
                        if broker:
                            try:
                                import inspect
                                if hasattr(broker, 'login') and 'force_reauth' in inspect.signature(broker.login).parameters:
                                    success = await async_retry(broker.login, force_reauth=False, retries=3, delay=1)
                                else:
                                    success = await async_retry(broker.login, retries=3, delay=1)
                                
                                if success:
                                    self.brokers[broker_key] = broker
                                    logger.info(f"🟢 Re-authentication successful for {broker_key}")
                                else:
                                    logger.warning(f"🟡 Re-authentication failed for {broker_key}")
                                    self.brokers[broker_key] = None
                            except Exception as e:
                                logger.error(f"🔴 Re-authentication failed for {broker_key}: {e}")
                                self.brokers[broker_key] = None
                        else:
                            logger.error(f"🔴 Could not re-instantiate broker: {broker_key}")
                            self.brokers[broker_key] = None
                    break
                else:
                    # Set status to AUTHENTICATING before authentication
                    await update_broker_status(broker_key, "AUTHENTICATING", notes="Authenticating...")
                    success = await self._authenticate_broker(broker_key, force_reauth=force_auth)
                    # Update DB with authentication result for each broker
                    status_final = "CONNECTED" if success else "ERROR"
                    await update_broker_status(broker_key, status_final, notes="" if success else "Initial authentication failed")
                    break
        logger.info("🟢 BrokerManager setup complete.")

    async def reauthenticate_broker(self, broker_key: str, retries=3, delay=1) -> bool:
        # Set status to AUTHENTICATING before re-authentication
        await update_broker_status(broker_key, "AUTHENTICATING", notes="Re-authenticating...")
        broker = self.brokers.get(broker_key)
        if not broker:
            logger.info(f"🔄 Broker {broker_key} not initialized. Initializing now...")
            success = await self._authenticate_broker(broker_key, retries=retries, delay=delay, force_reauth=True)
        else:
            logger.info(f"🔄 Reauthenticating broker: {broker_key}")
            try:
                if hasattr(broker, 'login'):
                    import inspect
                    if 'force_reauth' in inspect.signature(broker.login).parameters:
                        success = await async_retry(broker.login, force_reauth=True, retries=retries, delay=delay)
                    else:
                        success = await async_retry(broker.login, retries=retries, delay=delay)
                else:
                    success = False
            except Exception as e:
                logger.error(f"Reauthentication failed for {broker_key}: {e}")
                success = False
        # Update status after re-auth
        status = "CONNECTED" if success else "ERROR"
        await update_broker_status(broker_key, status, notes="" if success else "Re-authentication failed")
        if success:
            logger.info(f"🟢 Reauthentication successful for {broker_key}")
        else:
            logger.warning(f"🟡 Reauthentication failed for {broker_key}")
        return success

    async def reauthenticate_all(self):
        logger.info("🟢 Reauthenticating all enabled brokers...")
        for broker_key in list(self.brokers.keys()):
            await self.reauthenticate_broker(broker_key)

    async def get_data_broker(self, broker_name: Optional[str] = None):
        """
        Returns the broker instance to be used for fetching data.
        If broker_name is given, return that broker if available and valid.
        Otherwise, return the broker with is_data_provider enabled in the DB.
        """
        if broker_name and broker_name in self.brokers and self.brokers[broker_name]:
            return self.brokers[broker_name]
        # Find the broker with is_data_provider enabled in the DB
        from algosat.core.db import get_data_enabled_broker, AsyncSessionLocal
        async with AsyncSessionLocal() as session:
            broker_row = await get_data_enabled_broker(session)
            if broker_row:
                bname = broker_row.get("broker_name")
                if bname in self.brokers and self.brokers[bname]:
                    return self.brokers[bname]
        return None

    async def get_all_trade_enabled_brokers(self) -> Dict[str, object]:
        """
        Returns a dict of broker_name -> broker_obj (can be None if not authenticated) for all brokers
        where trade_execution_enabled is True in the DB, regardless of authentication status.
        """
        enabled_broker_names = await db_get_trade_enabled_brokers()
        return {name: self.brokers.get(name) for name in enabled_broker_names}

    async def place_order(
        self,
        order_payload: OrderRequest,
        strategy_name: Optional[str] = None,
        retries: int = 3,
        delay: int = 1,
        check_margin: bool = False
    ) -> dict:
        """
        Place order in all trade-enabled brokers (even if not authenticated), with retry on retryable errors.
        Accepts an OrderRequest object and passes it to each broker's place_order.
        Returns a dict of broker_name -> order result, with broker_id included.
        """
        if not isinstance(order_payload, OrderRequest):
            raise ValueError("order_payload must be an OrderRequest instance")
        results = {}
        all_brokers = await self.get_all_trade_enabled_brokers()
        from algosat.core.db import AsyncSessionLocal, get_broker_by_name
        async with AsyncSessionLocal() as session:
            for broker_name, broker in all_brokers.items():
                if not broker:
                    results[broker_name] = {"status": False, "message": "Broker not initialized or not authenticated"}
                    continue
                if not hasattr(broker, "place_order") or not callable(getattr(broker, "place_order", None)):
                    results[broker_name] = {"status": False, "message": "place_order not implemented"}
                    continue
                try:
                    # Resolve symbol for this broker
                    symbol_info = await self.get_symbol_info(broker_name, order_payload.symbol, instrument_type='NFO')
                    
                    # Prepare extra field with instrument_token if available
                    extra_data = order_payload.extra.copy() if order_payload.extra else {}
                    if symbol_info.get("instrument_token"):
                        extra_data["instrument_token"] = symbol_info["instrument_token"]
                    
                    # Ensure side is always the correct Enum, not a string
                    broker_order_payload = order_payload.copy(update={
                        "symbol": symbol_info["symbol"],
                        "side": order_payload.side if isinstance(order_payload.side, Side) else Side(order_payload.side),
                        "extra": extra_data
                    })

                    # Margin check logic
                    if check_margin:
                        from algosat.core.order_request import OrderResponse, OrderStatus
                        if not hasattr(broker, "check_margin_availability") or not callable(getattr(broker, "check_margin_availability", None)):
                            results[broker_name] = OrderResponse(
                                status=OrderStatus.FAILED,
                                order_id="",
                                order_message="Margin check not implemented for this broker",
                                broker=broker_name,
                                raw_response=None,
                                symbol=getattr(order_payload, 'symbol', None),
                                side=getattr(order_payload, 'side', None),
                                quantity=getattr(order_payload, 'quantity', None),
                                order_type=getattr(order_payload, 'order_type', None)
                            ).dict()
                            continue
                        try:
                            # Use enhanced retry with rate limiting for margin check
                            await self._ensure_rate_limiter()
                            retry_config = get_retry_config("default")
                            retry_config.rate_limit_broker = broker_name
                            retry_config.rate_limit_tokens = 1
                            retry_config.max_attempts = retries
                            retry_config.initial_delay = delay
                            
                            async def _check_margin():
                                return await broker.check_margin_availability(broker_order_payload)
                            
                            margin_ok = await async_retry_with_rate_limit(_check_margin, config=retry_config)
                        except Exception as e:
                            logger.error(f"Error checking margin: {e}")
                            results[broker_name] = OrderResponse(
                                status=OrderStatus.FAILED,
                                order_id="",
                                order_message=f"Margin check error: {e}",
                                broker=broker_name,
                                raw_response=None,
                                symbol=getattr(order_payload, 'symbol', None),
                                side=getattr(order_payload, 'side', None),
                                quantity=getattr(order_payload, 'quantity', None),
                                order_type=getattr(order_payload, 'order_type', None)
                            ).dict()
                            continue
                        if not margin_ok:
                            logger.warning(f"Insufficient margin for {broker_name} on {order_payload.symbol}")
                            results[broker_name] = OrderResponse(
                                status=OrderStatus.FAILED,
                                order_id="",
                                order_message="Insufficient margin",
                                broker=broker_name,
                                raw_response=None,
                                symbol=getattr(order_payload, 'symbol', None),
                                side=getattr(order_payload, 'side', None),
                                quantity=getattr(order_payload, 'quantity', None),
                                order_type=getattr(order_payload, 'order_type', None)
                            ).dict()
                            continue

                    # Place order with enhanced retry and rate limiting
                    await self._ensure_rate_limiter()
                    retry_config = get_retry_config("order_critical")  # Use critical config for orders
                    retry_config.rate_limit_broker = broker_name
                    retry_config.rate_limit_tokens = 1
                    retry_config.max_attempts = retries
                    retry_config.initial_delay = delay
                    
                    async def _place_order():
                        return await broker.place_order(broker_order_payload)
                    
                    result = await async_retry_with_rate_limit(_place_order, config=retry_config)
                    broker_row = await get_broker_by_name(session, broker_name)
                    broker_id = broker_row["id"] if broker_row else None
                    result["broker_id"] = broker_id
                    results[broker_name] = result
                except Exception as e:
                    results[broker_name] = {"status": False, "message": str(e)}
        return results

    async def get_profile(self, broker_name, retries=3, delay=1):
        broker = self.brokers.get(broker_name)
        if not broker or not hasattr(broker, "get_profile"):
            return None
        try:
            return await async_retry(broker.get_profile, retries=retries, delay=delay)
        except Exception as e:
            logger.error(f"get_profile failed for {broker_name}: {e}")
            return None

    async def get_positions(self, broker_name, retries=3, delay=1):
        broker = self.brokers.get(broker_name)
        if not broker or not hasattr(broker, "get_positions"):
            return None
        try:
            return await async_retry(broker.get_positions, retries=retries, delay=delay)
        except Exception as e:
            logger.error(f"get_positions failed for {broker_name}: {e}")
            return None

    async def get_holdings(self, broker_name, retries=3, delay=1):
        broker = self.brokers.get(broker_name)
        if not broker or not hasattr(broker, "get_holdings"):
            return None
        try:
            return await async_retry(broker.get_holdings, retries=retries, delay=delay)
        except Exception as e:
            logger.error(f"get_holdings failed for {broker_name}: {e}")
            return None

    async def get_funds(self, broker_name, retries=3, delay=1):
        broker = self.brokers.get(broker_name)
        if not broker or not hasattr(broker, "get_funds"):
            return None
        try:
            return await async_retry(broker.get_funds, retries=retries, delay=delay)
        except Exception as e:
            logger.error(f"get_funds failed for {broker_name}: {e}")
            return None

    async def get_orders(self, broker_name, retries=3, delay=1):
        broker = self.brokers.get(broker_name)
        if not broker or not hasattr(broker, "get_orders"):
            return None
        try:
            return await async_retry(broker.get_orders, retries=retries, delay=delay)
        except Exception as e:
            logger.error(f"get_orders failed for {broker_name}: {e}")
            return None

    async def get_trade_book(self, broker_name, retries=3, delay=1):
        broker = self.brokers.get(broker_name)
        if not broker or not hasattr(broker, "get_trade_book"):
            return None
        try:
            return await async_retry(broker.get_trade_book, retries=retries, delay=delay)
        except Exception as e:
            logger.error(f"get_trade_book failed for {broker_name}: {e}")
            return None

    async def get_margins(self, broker_name, retries=3, delay=1):
        broker = self.brokers.get(broker_name)
        if not broker or not hasattr(broker, "get_margins"):
            return None
        try:
            return await async_retry(broker.get_margins, retries=retries, delay=delay)
        except Exception as e:
            logger.error(f"get_margins failed for {broker_name}: {e}")
            return None

    async def get_trade_enabled_brokers(self):
        """
        Return a list of broker names where trade_execution_enabled is True.
        """
        return await db_get_trade_enabled_brokers()

    async def get_active_trade_brokers(self) -> Dict[str, object]:
        """
        Returns a dict of broker_name -> broker_obj for brokers that are both
        trade enabled in DB and are live/authenticated right now.
        """
        enabled_broker_names = await db_get_trade_enabled_brokers()
        return {
            name: self.brokers[name]
            for name in enabled_broker_names
            if name in self.brokers and self.brokers[name] is not None
        }

    async def get_symbol_info(self, broker_name: str, symbol: str, instrument_type: str = None) -> dict:
        """
        Returns broker-specific symbol info for a logical symbol/instrument_type.
        For Zerodha: returns { 'symbol': symbol, 'instrument_token': int }
        For Fyers: returns { 'symbol': 'NSE:SBIN-EQ' } etc.
        """
        broker_name = broker_name.lower()
        if broker_name == 'fyers':
            # Fyers expects NSE:SBIN-EQ, NSE:NIFTY50-INDEX, etc.
            exchange = 'NSE'
            if instrument_type is not None:
                instrument_type = instrument_type.upper()
            # Remove duplicate NSE: prefix if present
            sanitized_symbol = symbol
            if sanitized_symbol.startswith(f"{exchange}:"):
                sanitized_symbol = sanitized_symbol[len(f"{exchange}:"):]  # Remove leading NSE:
            if instrument_type == 'INDEX':
                fyers_symbol = f"{exchange}:{sanitized_symbol}-INDEX"
            elif instrument_type == 'EQ':
                fyers_symbol = f"{exchange}:{sanitized_symbol}-EQ"
            elif instrument_type == 'NFO':
                fyers_symbol = f"{exchange}:{sanitized_symbol}"
            else:
                fyers_symbol = f"{exchange}:{sanitized_symbol}"
            return {'symbol': fyers_symbol}
        elif broker_name == 'zerodha':
            import pandas as pd
            sanitized_symbol = symbol
            if ':' in symbol:
                sanitized_symbol = symbol.split(':', 1)[1]
            sanitized_symbol = sanitized_symbol.split('-')[0] if '-' in sanitized_symbol else sanitized_symbol
            # Use cached DataFrame if available, else fetch and cache
            if 'zerodha' not in self._instrument_cache:
                broker = self.brokers.get('zerodha')
                if not broker or not broker.kite:
                    raise Exception("Zerodha broker not initialized or not logged in.")
                loop = asyncio.get_event_loop()
                instruments = await loop.run_in_executor(None, lambda: pd.DataFrame(broker.kite.instruments()))
                self._instrument_cache['zerodha'] = instruments
            else:
                instruments = self._instrument_cache['zerodha']
            df = instruments
            match = None
            # For index (e.g., NIFTY, BANKNIFTY)
            if instrument_type and instrument_type.upper() == 'INDEX':
                # Zerodha uses 'INDICES' for index segment, match by name (ignoring spaces)
                match = df[(df['segment'] == 'INDICES') & (df['name'].str.replace(' ', '').str.upper() == sanitized_symbol.replace(' ', '').upper())]
            # For equity
            elif instrument_type and instrument_type.upper() == 'EQ':
                match = df[(df['segment'] == 'NSE') & (df['name'].str.upper() == sanitized_symbol.upper())]
            # For options (NFO-OPT)
            elif instrument_type and instrument_type.upper() == 'NFO':
                match = df[(df['segment'] == 'NFO-OPT') & (df['tradingsymbol'].str.upper() == sanitized_symbol.upper())]
            # Fallback: just match tradingsymbol
            else:
                match = df[df['tradingsymbol'].str.upper() == sanitized_symbol.upper()]
            if match is not None and not match.empty:
                row = match.iloc[0]
                return {'symbol': row['tradingsymbol'], 'instrument_token': row['instrument_token']}
            raise Exception(f"Instrument token not found for {sanitized_symbol} {instrument_type}")
        elif broker_name == 'angel':
            # Angel One broker symbol conversion
            return await self._get_angel_symbol_info(symbol, instrument_type)
        else:
            # Default: just return symbol
            return {'symbol': symbol}

    import asyncio
    from algosat.core.db import AsyncSessionLocal, get_strategy_by_id
    async def build_order_request_for_strategy(self, signal: TradeSignal, config: StrategyConfig) -> OrderRequest:
        """
        Build a broker-agnostic OrderRequest from a TradeSignal and StrategyConfig.
        Uses logical order_type and product_type for OptionBuy/OptionSell, and config values for others.
        For hedge entry signals, always use MARKET/INTRADAY.
        """
        order_type = None
        product_type = None
        strategy_id = getattr(config, 'strategy_id', None)
        strategy_name = None

        from algosat.core.signal import SignalType
        if strategy_id is not None:
            async with AsyncSessionLocal() as session:
                strat = await get_strategy_by_id(session, strategy_id)
                if strat:
                    strategy_name = strat.get('key')
                    if getattr(signal, 'signal_type', None) == SignalType.HEDGE_ENTRY:
                        order_type = "MARKET"
                        if strategy_name in ["OptionBuy", "OptionSell"]:
                            product_type = "INTRADAY_OPTION"
                        else:
                            product_type = "INTRADAY_SWING"
                    else:
                        if strategy_name in ["OptionBuy", "OptionSell"]:
                            order_type = "OPTION_STRATEGY"
                            product_type = "OPTION_STRATEGY"
                        else:
                            order_type = strat.get('order_type')
                            product_type = strat.get('product_type')
        if not order_type:
            order_type = "MARKET"
        if not product_type:
            product_type = "INTRADAY"
        order_kwargs = {
            'symbol': signal.symbol,
            'side': signal.side,
            'order_type': order_type,
            'product_type': product_type,
            'tag': "".join([signal.strategy_name, signal.signal_type, signal.symbol, str(signal.side)]) if hasattr(signal, 'strategy_name') else "AlgoOrder",
            'quantity': getattr(config, 'quantity', 1) or (config.trade.get('quantity', 1) if hasattr(config, 'trade') and isinstance(config.trade, dict) else 1),
        }
        # Core OrderRequest fields
        if hasattr(signal, 'price') and signal.price is not None and product_type != 'DELIVERY':
            order_kwargs['price'] = signal.price
        if hasattr(signal, 'trigger_price') and signal.trigger_price is not None:
            order_kwargs['trigger_price'] = signal.trigger_price
        # All other fields go into 'extra'
        extra = {}
        for field in [
            'candle_range', 'entry_price', 'stop_loss', 'target_price', 'profit', 'signal_time', 'exit_time', 'trigger_price_diff',
            'exit_price', 'status', 'reason', 'atr', 'supertrend_signal', 'lot_qty', 'entry_time', 'order_ids', 'order_messages',
            'entry_spot_price', 'entry_spot_swing_high', 'entry_spot_swing_low', 'stoploss_spot_level', 'target_spot_level',
            'signal_direction', 'entry_rsi', 'expiry_date', 'orig_target'
        ]:
            val = getattr(signal, field, None)
            if val is not None:
                extra[field] = val
        # Add lot_size from config/trade config if present
        lot_size = None
        lot_qty = None
        if hasattr(config, 'lot_size'):
            lot_size = config.lot_size
        elif hasattr(config, 'trade') and isinstance(config.trade, dict):
            lot_size = config.trade.get('lot_size')
            trigger_price_diff = config.trade.get('trigger_price_diff', 0.0)
        if lot_size is not None:
            extra['lot_size'] = lot_size
        if 'trigger_price_diff' not in extra:
            extra['trigger_price_diff'] = trigger_price_diff if 'trigger_price_diff' in config.trade else 0.0
        if 'target_price' in extra:
            try:
                # For Fyers BO orders, pass the actual target_price, not the difference
                # The to_fyers_dict() method will calculate the takeProfit difference correctly
                logger.debug(f"target_price processing: entry_price={extra['entry_price']}, target_price={extra['target_price']}")
                # Round target_price to nearest 0.05
                extra['target_price'] = round(extra['target_price'] / 0.05) * 0.05
                # Don't pre-calculate takeProfit here - let to_fyers_dict() handle it based on target_price
            except Exception as e:
                logger.warning(f"Could not process target_price: {e}")
        # Only compute entry_price and stopPrice if signal.price is not None and product_type is not DELIVERY
        if getattr(signal, 'price', None) is not None and product_type != 'DELIVERY':
            entry_price = round(round(signal.price / 0.05) * 0.05, 2)
            trigger_price_diff = extra['trigger_price_diff']
            stopPrice = (entry_price - trigger_price_diff) if signal.side == Side.BUY.value else (entry_price + trigger_price_diff)
            stopPrice = round(round(stopPrice / 0.05) * 0.05, 2)
            order_kwargs['trigger_price'] = stopPrice
        else:
            entry_price = None
            stopPrice = None
        # Only set quantity if lot_size and lot_qty are present
        if lot_size is not None and 'lot_qty' in extra and extra['lot_qty'] is not None:
            order_kwargs['quantity'] = lot_size * extra['lot_qty']
        

        # Normalize side for OptionBuy/OptionSell strategies
        # Also allow config to override/add extra fields
        if hasattr(config, 'extra') and isinstance(config.extra, dict):
            extra.update({k: v for k, v in config.extra.items() if v is not None})
        # Pass strategy_name for downstream mapping if needed
        extra['strategy_name'] = strategy_name
        order_kwargs['extra'] = extra
        return OrderRequest(**order_kwargs)

    async def get_all_broker_order_details(self, retries=3, delay=1) -> dict:
        """
        Fetch order details from all trade-enabled brokers with rate limiting.
        Returns a dict: broker_name -> list of order dicts (empty list if no orders).
        """
        await self._ensure_rate_limiter()
        enabled_brokers = await self.get_all_trade_enabled_brokers()
        broker_orders = {}
        
        for broker_name, broker in enabled_brokers.items():
            try:
                if broker is None or not hasattr(broker, "get_order_details"):
                    broker_orders[broker_name] = []
                    continue
                
                # Create retry config with rate limiting
                retry_config = get_retry_config("default")
                retry_config.rate_limit_broker = broker_name
                retry_config.rate_limit_tokens = 1
                retry_config.max_attempts = retries
                retry_config.initial_delay = delay
                
                async def _fetch_orders():
                    return await broker.get_order_details()
                
                orders = await async_retry_with_rate_limit(_fetch_orders, config=retry_config)
                if not isinstance(orders, list):
                    orders = []
                broker_orders[broker_name] = orders
                
            except Exception as e:
                logger.error(f"BrokerManager: Failed to fetch orders for {broker_name}: {e}")
                broker_orders[broker_name] = []
        
        return broker_orders

    async def get_all_broker_positions(self, retries=3, delay=1) -> dict:
        """
        Fetch positions from all trade-enabled brokers with rate limiting.
        Returns a dict: broker_name -> list of positions (empty list if error or not available).
        """
        await self._ensure_rate_limiter()
        enabled_brokers = await self.get_all_trade_enabled_brokers()
        broker_positions = {}
        
        for broker_name, broker in enabled_brokers.items():
            try:
                if broker is None or not hasattr(broker, "get_positions"):
                    broker_positions[broker_name] = []
                    continue
                
                # Create retry config with rate limiting
                retry_config = get_retry_config("default")
                retry_config.rate_limit_broker = broker_name
                retry_config.rate_limit_tokens = 1
                retry_config.max_attempts = retries
                retry_config.initial_delay = delay
                
                async def _fetch_positions():
                    return await broker.get_positions()
                
                positions = await async_retry_with_rate_limit(_fetch_positions, config=retry_config)
                
                # Handle broker-specific response formats
                if broker_name == 'zerodha' and isinstance(positions, dict) and 'net' in positions:
                    positions = positions.get('net', [])
                if broker_name == 'fyers' and isinstance(positions, dict) and 'netPositions' in positions:
                    positions = positions.get('netPositions', [])
                if broker_name == 'angel' and isinstance(positions, dict) and 'data' in positions:
                    positions = positions.get('data', [])
                if not isinstance(positions, list):
                    positions = []
                
                broker_positions[broker_name] = positions
                
            except Exception as e:
                logger.error(f"BrokerManager: Failed to fetch positions for {broker_name}: {e}")
                broker_positions[broker_name] = []
        
        return broker_positions
    

    async def get_broker_by_id(self, broker_id: int) -> Optional[object]:
        """
        Fetch the broker object from self.brokers using broker_id.
        """
        from algosat.core.db import AsyncSessionLocal, get_broker_by_id as db_get_broker_by_id
        async with AsyncSessionLocal() as session:
            broker_row = await db_get_broker_by_id(session, broker_id)
            if not broker_row:
                logger.error(f"BrokerManager: No broker found in DB for broker_id={broker_id}")
                return None
            broker_name = broker_row.get("broker_name")
            if broker_name in self.brokers:
                return self.brokers[broker_name]
            logger.error(f"BrokerManager: Broker name {broker_name} not found in self.brokers for broker_id={broker_id}")
            return None

    async def exit_order(self, broker_id, broker_order_id, symbol=None, product_type=None, exit_reason=None, side=None, retries=3, delay=1):
        """
        Route exit order to the correct broker by broker_id with rate limiting.
        """
        await self._ensure_rate_limiter()
        broker = await self.get_broker_by_id(broker_id)
        if not broker:
            raise RuntimeError(f"No broker found for broker_id={broker_id}")
        
        # Get broker_name for rate limiting
        from algosat.core.db import AsyncSessionLocal, get_broker_by_id as db_get_broker_by_id
        async with AsyncSessionLocal() as session:
            broker_row = await db_get_broker_by_id(session, broker_id)
            broker_name = broker_row.get("broker_name") if broker_row else None
        
        if not broker_name:
            raise RuntimeError(f"No broker_name found for broker_id={broker_id}")
        
        # If symbol is provided, normalize it for the broker
        normalized_symbol = symbol
        if symbol:
            try:
                symbol_info = await self.get_symbol_info(broker_name, symbol, instrument_type='NFO')
                normalized_symbol = symbol_info.get('symbol', symbol)
                logger.debug(f"BrokerManager: Symbol normalized from {symbol} to {normalized_symbol}")
            except Exception as symbol_lookup_error:
                logger.warning(f"BrokerManager: Symbol lookup failed for {symbol}, using original symbol: {symbol_lookup_error}")
                normalized_symbol = symbol  # Use original symbol if lookup fails
        
        # Create retry config with rate limiting
        retry_config = get_retry_config("order_critical")
        retry_config.rate_limit_broker = broker_name
        retry_config.rate_limit_tokens = 1
        retry_config.max_attempts = retries
        retry_config.initial_delay = delay
        
        async def _exit_order():
            return await broker.exit_order(broker_order_id, symbol=normalized_symbol, product_type=product_type, exit_reason=exit_reason, side=side)
        
        return await async_retry_with_rate_limit(_exit_order, config=retry_config)

    async def cancel_order(self, broker_id, broker_order_id, symbol=None, product_type=None, variety=None, cancel_reason=None, retries=3, delay=1, **kwargs):
        """
        Cancel an order for the given broker with rate limiting.
        Routes to the correct broker's cancel_order implementation.
        For Fyers: pass broker_order_id (with -BO-1 if needed).
        For Zerodha: pass variety and order_id.
        """
        await self._ensure_rate_limiter()
        broker = await self.get_broker_by_id(broker_id)
        if broker is None:
            logger.error(f"BrokerManager: Could not find broker for id: {broker_id}")
            return None
        
        # Get broker_name for rate limiting
        from algosat.core.db import AsyncSessionLocal, get_broker_by_id as db_get_broker_by_id
        async with AsyncSessionLocal() as session:
            broker_row = await db_get_broker_by_id(session, broker_id)
            broker_name = broker_row.get("broker_name") if broker_row else None
        
        if not broker_name:
            logger.error(f"BrokerManager: No broker_name found for broker_id={broker_id}")
            return None
        
        # Set default variety for Zerodha if not provided
        if broker_name.lower() == "zerodha" and variety is None:
            variety = "regular"
        
        # Create retry config with rate limiting
        retry_config = get_retry_config("order_critical")
        retry_config.rate_limit_broker = broker_name
        retry_config.rate_limit_tokens = 1
        retry_config.max_attempts = retries
        retry_config.initial_delay = delay
        
        async def _cancel_order():
            # Handle broker-specific parameters
            if broker_name.lower() == "zerodha":
                return await broker.cancel_order(broker_order_id, symbol=symbol, product_type=product_type, variety=variety, cancel_reason=cancel_reason, **kwargs)
            elif broker_name.lower() == "angel":
                # Angel uses "variety" parameter but defaults to "NORMAL"
                angel_variety = variety or "NORMAL"
                return await broker.cancel_order(broker_order_id, symbol=symbol, product_type=product_type, variety=angel_variety, cancel_reason=cancel_reason, **kwargs)
            else:
                # For other brokers (like Fyers), don't pass variety parameter
                return await broker.cancel_order(broker_order_id, symbol=symbol, product_type=product_type, cancel_reason=cancel_reason, **kwargs)
        
        return await async_retry_with_rate_limit(_cancel_order, config=retry_config)

    async def _get_angel_symbol_info(self, symbol: str, instrument_type: str = None) -> dict:
        """
        Convert symbols to Angel One broker format and get instrument token.
        
        Symbol conversion patterns:
        Input: NIFTY2591624950CE -> Output: NIFTY16SEP2524950CE
        Input format: {underlying}{yy}{m}{dd}{strike}{CE/PE}
        Angel format: {underlying}{dd}{MMM}{yy}{strike}{CE/PE}
        
        Input month format (from get_atm_strike_symbol):
        - Jan-Sep: Numbers 1, 2, 3, 4, 5, 6, 7, 8, 9
        - Oct: Letter O
        - Nov: Letter N  
        - Dec: Letter D
        
        Examples:
        - NIFTY2591624950CE -> NIFTY16SEP2524950CE (16 Sep 2025, Strike 24950, Call)
        - NIFTY25O2047500PE -> NIFTY20OCT2547500PE (20 Oct 2025, Strike 47500, Put)
        - NIFTY25N1525000CE -> NIFTY15NOV2525000CE (15 Nov 2025, Strike 25000, Call)
        - NIFTY25D3030000PE -> NIFTY30DEC2530000PE (30 Dec 2025, Strike 30000, Put)
        """
        import re
        from datetime import datetime
        
        try:
            # Get Angel broker instance for instruments lookup
            angel_broker = self.brokers.get('angel')
            if not angel_broker:
                raise Exception("Angel broker not available for symbol conversion")
            
            # Handle simple cases (non-option symbols)
            if instrument_type and instrument_type.upper() in ['EQ', 'INDEX']:
                # For equity and index, try direct lookup first
                token = await angel_broker.get_instrument_token(symbol)
                return {'symbol': symbol, 'instrument_token': token} if token else {'symbol': symbol}
            
            # Parse option symbol format: {underlying}{yyMdd}{strike}{CE/PE}
            # Example: NIFTY2591624950CE = NIFTY + 25916 + 24950 + CE 
            # Where 25916 = 25(year) + 9(month) + 16(day) -> 16 Sep 2025
            # For Oct/Nov/Dec: NIFTY25O20, NIFTY25N15, NIFTY25D30 (O=Oct, N=Nov, D=Dec)
            
            # Try to match pattern with letters for Oct/Nov/Dec
            pattern_with_letters = r'^([A-Z]+)(\d{2})([OND])(\d{1,2})(\d+)(CE|PE)$'
            match = re.match(pattern_with_letters, symbol.upper())
            
            if match:
                underlying, year, month_letter, day, strike, option_type = match.groups()
                
                # Convert letter month to number
                letter_to_month = {'O': '10', 'N': '11', 'D': '12'}
                month = letter_to_month[month_letter]
                
            else:
                # Try to match pattern with date encoding for Jan-Sep
                pattern = r'^([A-Z]+)(\d{5})(\d+)(CE|PE)$'
                match = re.match(pattern, symbol.upper())
                
                if match:
                    underlying, date_part, strike, option_type = match.groups()
                    
                    # Parse 5-digit date: YYMDD format for Jan-Sep
                    if len(date_part) == 5:
                        # Format: YYMDD (25916 = 25 + 9 + 16)
                        year = date_part[:2]  # 25
                        month_day = date_part[2:]  # 916
                        
                        # Parse month and day from remaining digits
                        if len(month_day) == 3:
                            # Could be M + DD (9 + 16) for single digit month
                            if month_day[0] in '123456789' and month_day[1:].isdigit():
                                month = month_day[0]  # 9
                                day = month_day[1:]   # 16
                            else:
                                # Invalid format, try direct lookup
                                token = await angel_broker.get_instrument_token(symbol)
                                return {'symbol': symbol, 'instrument_token': token} if token else {'symbol': symbol}
                        else:
                            # Invalid format, try direct lookup
                            token = await angel_broker.get_instrument_token(symbol)
                            return {'symbol': symbol, 'instrument_token': token} if token else {'symbol': symbol}
                    else:
                        # Different date format, try direct lookup
                        token = await angel_broker.get_instrument_token(symbol)
                        return {'symbol': symbol, 'instrument_token': token} if token else {'symbol': symbol}
                else:
                    # Try alternative pattern: {underlying}{yy}{m}{dd}{strike}{CE/PE}
                    pattern = r'^([A-Z]+)(\d{2})(\d{1,2})(\d{1,2})(\d+)(CE|PE)$'
                    match = re.match(pattern, symbol.upper())
                    
                    if not match:
                        # If pattern doesn't match, try direct lookup
                        token = await angel_broker.get_instrument_token(symbol)
                        return {'symbol': symbol, 'instrument_token': token} if token else {'symbol': symbol}
                    
                    underlying, year, month, day, strike, option_type = match.groups()
            
            # Convert year (25 -> 2025)
            full_year = 2000 + int(year)
            
            # Convert month number to month character (matching get_atm_strike_symbol format)
            # Jan-Sep: numbers 1-9, Oct-Dec: letters O, N, D
            nse_weekly_map = {
                1: "1", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6",
                7: "7", 8: "8", 9: "9", 10: "O", 11: "N", 12: "D"
            }
            
            month_char = nse_weekly_map.get(int(month.lstrip('0')), '1')  # Remove leading zero and convert to int
            
            # Format day with leading zero if needed
            day_formatted = day.zfill(2)
            
            # Convert to Angel format: {underlying}{dd}{MMM}{yy}{strike}{CE/PE}
            # Angel uses full month abbreviations like JAN, FEB, SEP, OCT, NOV, DEC
            month_names = {
                1: 'JAN', 2: 'FEB', 3: 'MAR', 4: 'APR', 5: 'MAY', 6: 'JUN',
                7: 'JUL', 8: 'AUG', 9: 'SEP', 10: 'OCT', 11: 'NOV', 12: 'DEC'
            }
            
            month_abbr = month_names.get(int(month.lstrip('0')), 'JAN')  # Convert to int and get abbr
            angel_symbol = f"{underlying}{day_formatted}{month_abbr}{year}{strike}{option_type}"
            
            logger.info(f"Angel: Converting {symbol} -> {angel_symbol}")
            
            # Get instrument token from Angel broker
            token = await angel_broker.get_instrument_token(angel_symbol)
            
            if token:
                logger.info(f"Angel: Found token for {angel_symbol} (token: {token})")
                return {'symbol': angel_symbol, 'instrument_token': token}
            else:
                # If not found, return converted symbol without token (no additional warning needed)
                return {'symbol': angel_symbol}
                
        except Exception as e:
            logger.error(f"Error in Angel symbol conversion for {symbol}: {e}")
            # Fallback: return original symbol
            return {'symbol': symbol}
        
        return await async_retry_with_rate_limit(_cancel_order, config=retry_config)
