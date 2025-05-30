# core/broker_manager.py

import asyncio
from typing import Dict, Optional, List, Callable
from algosat.brokers.factory import get_broker
from algosat.common.broker_utils import get_broker_credentials, upsert_broker_credentials
from algosat.common.default_broker_configs import DEFAULT_BROKER_CONFIGS
from algosat.common.logger import get_logger
from algosat.core.db import get_trade_enabled_brokers as db_get_trade_enabled_brokers
from algosat.core.order_request import OrderRequest, OrderType
from algosat.core.signal import TradeSignal, SignalType
from algosat.core.order_defaults import ORDER_DEFAULTS
from algosat.models.strategy_config import StrategyConfig

logger = get_logger("BrokerManager")

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

class BrokerManager:
    def __init__(self):
        self.brokers: Dict[str, object] = {}
        # --- Symbol/Instrument resolution for all brokers ---
        self._instrument_cache = {}

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
            # Pass force_reauth if supported
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
        else:
            logger.warning(f"🟡 Authentication failed for {broker_key}")
        return success

    async def setup(self):
        logger.debug("🔄 Starting BrokerManager setup...")
        enabled_brokers = await self._discover_enabled_brokers()
        for broker_key in enabled_brokers:
            await self._prompt_for_missing_credentials(broker_key)
            await self._authenticate_broker(broker_key)
        logger.info("🟢 BrokerManager setup complete.")

    async def reauthenticate_broker(self, broker_key: str, retries=3, delay=1) -> bool:
        broker = self.brokers.get(broker_key)
        if not broker:
            logger.info(f"🔄 Broker {broker_key} not initialized. Initializing now...")
            # Attempt to authenticate broker if not initialized
            return await self._authenticate_broker(broker_key, retries=retries, delay=delay, force_reauth=True)
        logger.info(f"🔄 Reauthenticating broker: {broker_key}")
        try:
            # Pass force_reauth=True if supported
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
            return False
        if success:
            logger.info(f"🟢 Reauthentication successful for {broker_key}")
        else:
            logger.warning(f"🟡 Reauthentication failed for {broker_key}")
        return success

    async def reauthenticate_all(self):
        logger.info("🟢 Reauthenticating all enabled brokers...")
        for broker_key in list(self.brokers.keys()):
            await self.reauthenticate_broker(broker_key)

    def get_data_broker(self, broker_name: Optional[str] = None):
        """
        Returns the broker instance to be used for fetching data.
        If broker_name is given, return that broker if available and valid.
        Otherwise, return the broker with is_data_provider enabled in the DB.
        """
        if broker_name and broker_name in self.brokers and self.brokers[broker_name]:
            return self.brokers[broker_name]
        # Find the broker with is_data_provider enabled in the DB
        from algosat.core.db import get_data_enabled_broker, AsyncSessionLocal
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            async def _get():
                async with AsyncSessionLocal() as session:
                    return await get_data_enabled_broker(session)
            broker_row = loop.run_until_complete(_get())
            if broker_row:
                bname = broker_row.get("broker_name")
                if bname in self.brokers and self.brokers[bname]:
                    return self.brokers[bname]
        except Exception as e:
            logger.error(f"Error fetching data provider broker from DB: {e}")
        return None

    async def get_all_trade_enabled_brokers(self) -> Dict[str, object]:
        """
        Returns a dict of broker_name -> broker_obj (can be None if not authenticated) for all brokers
        where trade_execution_enabled is True in the DB, regardless of authentication status.
        """
        enabled_broker_names = await db_get_trade_enabled_brokers()
        return {name: self.brokers.get(name) for name in enabled_broker_names}

    async def place_order(self, order_payload, strategy_name=None, retries=3, delay=1):
        """
        Place order in all trade-enabled brokers (even if not authenticated), with retry on retryable errors.
        Accepts an OrderRequest object and passes it to each broker's place_order.
        Returns a dict of broker_name -> order result.
        """
        if not isinstance(order_payload, OrderRequest):
            raise ValueError("order_payload must be an OrderRequest instance")
        results = {}
        all_brokers = await self.get_all_trade_enabled_brokers()
        for broker_name, broker in all_brokers.items():
            if not broker:
                results[broker_name] = {"status": False, "message": "Broker not initialized or not authenticated"}
                continue
            if not hasattr(broker, "place_order") or not callable(getattr(broker, "place_order", None)):
                results[broker_name] = {"status": False, "message": "place_order not implemented"}
                continue
            try:
                result = await async_retry(broker.place_order, order_payload, retries=retries, delay=delay)
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
            if instrument_type == 'INDEX':
                fyers_symbol = f"{exchange}:{symbol}-INDEX"
            elif instrument_type == 'EQ':
                fyers_symbol = f"{exchange}:{symbol}-EQ"
            elif instrument_type == 'NFO':
                fyers_symbol = f"{exchange}:{symbol}"
            else:
                fyers_symbol = f"{exchange}:{symbol}"
            return {'symbol': fyers_symbol}
        elif broker_name == 'zerodha':
            # Zerodha expects instrument_token for everything (quotes, ltp, history, etc.)
            # Cache instruments for performance
            if 'zerodha' not in self._instrument_cache:
                broker = self.brokers.get('zerodha')
                if not broker or not broker.kite:
                    raise Exception("Zerodha broker not initialized or not logged in.")
                loop = asyncio.get_event_loop()
                instruments = await loop.run_in_executor(None, broker.kite.instruments, None)
                self._instrument_cache['zerodha'] = instruments
            else:
                instruments = self._instrument_cache['zerodha']
            # Find instrument token and correct display symbol
            token = None
            display_symbol = symbol
            for i in instruments:
                # Zerodha uses 'INDICES' for index segment
                seg = i.get('segment', '')
                name = i.get('name', '').upper()
                ins_type = i.get('instrument_type', '').upper()
                tradingsymbol = i.get('tradingsymbol', '')
                # For index, user may input NIFTY50, but Zerodha expects NIFTY 50
                if instrument_type and instrument_type.upper() == 'INDEX' and seg == 'INDICES':
                    if name.replace(' ', '').upper() == symbol.replace(' ', '').upper():
                        token = i['instrument_token']
                        display_symbol = tradingsymbol
                        break
                elif instrument_type and instrument_type.upper() == 'EQ' and seg == 'NSE':
                    if name == symbol.upper():
                        token = i['instrument_token']
                        display_symbol = tradingsymbol
                        break
                elif instrument_type and instrument_type.upper() == 'NFO' and seg == 'NFO-OPT':
                    if name == symbol.upper():
                        token = i['instrument_token']
                        display_symbol = tradingsymbol
                        break
                elif not instrument_type:
                    if name == symbol.upper():
                        token = i['instrument_token']
                        display_symbol = tradingsymbol
                        break
            if token is None:
                raise Exception(f"Instrument token not found for {symbol} {instrument_type}")
            return {'symbol': display_symbol, 'instrument_token': token}
        else:
            # Default: just return symbol
            return {'symbol': symbol}

    def build_order_request_from_signal(self, signal: TradeSignal, config: StrategyConfig) -> OrderRequest:
        """
        Build a broker-agnostic OrderRequest from a TradeSignal and StrategyConfig.
        Ensures order_type is always set, using broker/signal defaults, config, or fallback to OrderType.MARKET.
        Populates all relevant fields for DB and broker adapters, using the 'extra' field for non-core OrderRequest fields.
        """
        broker_name = getattr(config, 'broker_id', 'fyers')
        defaults = ORDER_DEFAULTS.get(broker_name, {}).get(signal.signal_type, {})
        # Priority: config.trade['order_type'] > defaults > fallback
        order_type = None
        if hasattr(config, 'trade') and isinstance(config.trade, dict):
            ot = config.trade.get('order_type')
            if ot:
                if isinstance(ot, OrderType):
                    order_type = ot
                elif isinstance(ot, str):
                    try:
                        order_type = OrderType[ot.upper()]
                    except Exception:
                        order_type = None
        if not order_type:
            ot = defaults.get('order_type')
            if isinstance(ot, OrderType):
                order_type = ot
            elif isinstance(ot, str):
                try:
                    order_type = OrderType[ot.upper()]
                except Exception:
                    order_type = None
        if not order_type:
            order_type = OrderType.MARKET
        # --- Only include fields defined in OrderRequest, others go in 'extra' ---
        order_kwargs = {**defaults}
        order_kwargs.update({
            'symbol': signal.symbol,
            'side': signal.side,
            'order_type': order_type,
            'quantity': getattr(config, 'quantity', 1) or (config.trade.get('quantity', 1) if hasattr(config, 'trade') and isinstance(config.trade, dict) else 1),
        })
        # Core OrderRequest fields
        if hasattr(signal, 'price') and signal.price is not None:
            order_kwargs['price'] = signal.price
        if hasattr(signal, 'trigger_price') and signal.trigger_price is not None:
            order_kwargs['trigger_price'] = signal.trigger_price
        # All other fields go into 'extra'
        extra = {}
        for field in [
            'candle_range', 'entry_price', 'stop_loss', 'target_price', 'profit', 'signal_time', 'exit_time',
            'exit_price', 'status', 'reason', 'atr', 'supertrend_signal', 'lot_qty', 'entry_time', 'order_ids', 'order_messages']:
            val = getattr(signal, field, None)
            if val is not None:
                extra[field] = val
        # Also allow config to override/add extra fields
        if hasattr(config, 'extra') and isinstance(config.extra, dict):
            extra.update({k: v for k, v in config.extra.items() if v is not None})
        order_kwargs['extra'] = extra
        return OrderRequest(**order_kwargs)
