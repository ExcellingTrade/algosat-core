from __future__ import annotations
from algosat.utils.telegram_notify import telegram_bot, send_telegram_async
from typing import Optional, Any
import asyncio
import time
from datetime import datetime, timezone
from algosat.core.time_utils import localize_to_ist
from algosat.common.logger import get_logger, set_strategy_context
from algosat.models.order_aggregate import OrderAggregate

from algosat.core.data_manager import DataManager
from algosat.core.order_manager import FYERS_STATUS_MAP, OrderManager
from algosat.core.order_cache import OrderCache
from algosat.core.order_request import OrderStatus
from algosat.common.strategy_utils import wait_for_next_candle, fetch_instrument_history

logger = get_logger("OrderMonitor")

# Order monitoring interval - used by both OrderMonitor and OrderCache for consistency
DEFAULT_ORDER_MONITOR_INTERVAL = 30.0  # seconds

class OrderMonitor:
    def __init__(
        self,
        order_id: int,
        data_manager: DataManager,
        order_manager: OrderManager,
        order_cache: OrderCache,  # new dependency
        strategy_instance=None,  # strategy instance for shared usage
        strategy_id: int = None,  # Optional: pass strategy_id directly for efficiency
        price_order_monitor_seconds: float = DEFAULT_ORDER_MONITOR_INTERVAL,  # Default 30s interval
        signal_monitor_seconds: int = None  # will be set from strategy config
    ):
        self.order_id: int = order_id
        self.data_manager: DataManager = data_manager
        self.order_manager: OrderManager = order_manager
        self.order_cache: OrderCache = order_cache
        self.strategy_instance = strategy_instance  # Store strategy instance
        self.strategy_id: int = strategy_id  # Store strategy_id if provided
        self.price_order_monitor_seconds: float = price_order_monitor_seconds
        self.signal_monitor_seconds: int = signal_monitor_seconds
        self.is_hedge: bool = False  # Will be set to True if this order has a parent_order_id
        self._hedge_detection_done: bool = False  # Flag to ensure hedge detection happens only once
        self._running: bool = True
        # Track last main order status to avoid redundant DB updates
        self._last_main_status = None
        # Track last broker order statuses to avoid redundant broker_execs updates
        self._last_broker_statuses = {}
        # Unified cache: order_id -> (order, strategy_symbol, strategy)
        self._order_strategy_cache = {}
        # Broker name cache: broker_id -> broker_name (long-lived cache since broker names rarely change)
        self._broker_name_cache = {}
        self._broker_name_cache_time = {}
        # self._db_session = None  # Will be set when needed

    def get_strategy_instance(self):
        """
        Get the strategy instance if available, otherwise return None.
        This allows methods to use the live strategy instance when available
        for better performance and access to runtime state.
        """
        return self.strategy_instance

    async def call_strategy_method(self, method_name, *args, **kwargs):
        """
        Call a method on the strategy instance if available, otherwise return None.
        This provides a way to use live strategy methods when the instance is available.
        
        Args:
            method_name: Name of the method to call on the strategy
            *args, **kwargs: Arguments to pass to the method
            
        Returns:
            The result of the method call, or None if strategy instance is not available
        """
        if self.strategy_instance is None:
            logger.debug(f"OrderMonitor: No strategy instance available for method '{method_name}'")
            return None
            
        if not hasattr(self.strategy_instance, method_name):
            logger.warning(f"OrderMonitor: Strategy instance does not have method '{method_name}'")
            return None
            
        try:
            method = getattr(self.strategy_instance, method_name)
            result = method(*args, **kwargs)
            if asyncio.iscoroutine(result):
                return await result
            return result
        except Exception as e:
            logger.error(f"OrderMonitor: Error calling strategy method '{method_name}': {e}", exc_info=True)
            return None

    async def _clear_order_cache(self, reason: str = "Order updated"):
        """
        Clear the order strategy cache to ensure fresh data is fetched after order updates.
        
        Args:
            reason: Optional reason for cache clearing (for logging)
        """
        if self.order_id in self._order_strategy_cache:
            del self._order_strategy_cache[self.order_id]
            logger.debug(f"OrderMonitor: Cleared order cache for order_id={self.order_id}. Reason: {reason}")

    async def _get_strategy_name(self, strategy=None):
        """
        Get the strategy name from various sources with fallback logic.
        
        Args:
            strategy: Optional strategy object/dict to extract name from
            
        Returns:
            str: Strategy name in lowercase, or None if not found
        """
        strategy_name = None
        
        try:
            # Priority 1: Use passed strategy parameter if it has a valid strategy_key
            if strategy is not None:
                if isinstance(strategy, dict):
                    strategy_name = strategy.get('strategy_key', None)
                else:
                    strategy_name = getattr(strategy, 'strategy_key', None)
                if strategy_name:
                    logger.debug(f"OrderMonitor: Got strategy name '{strategy_name}' from strategy parameter for order_id={self.order_id}")
            
            # Priority 2: Use strategy instance if no valid strategy parameter
            if strategy_name is None and self.strategy_instance is not None:
                strategy_name = getattr(self.strategy_instance.cfg, 'strategy_key', None)
                if strategy_name:
                    logger.debug(f"OrderMonitor: Got strategy name '{strategy_name}' from strategy_instance for order_id={self.order_id}")
            
            # Priority 3: Fetch from database if needed
            if strategy_name is None:
                _, _, _, db_strategy = await self._get_order_and_strategy(self.order_id)
                if db_strategy:
                    strategy_name = db_strategy.get('strategy_key', None)
                    if strategy_name:
                        logger.debug(f"OrderMonitor: Got strategy name '{strategy_name}' from database for order_id={self.order_id}")
            
            # Normalize to lowercase
            if strategy_name:
                strategy_name = strategy_name.lower()
                
        except Exception as e:
            logger.error(f"OrderMonitor: Error getting strategy name for order_id={self.order_id}: {e}")
            strategy_name = None
        
        return strategy_name

    async def _get_order_and_strategy(self, order_id: int):
        """
        Fetch order, strategy_symbol, strategy_config, and strategy for this order_id, cache the result.
        Returns (order, strategy_symbol, strategy_config, strategy) tuple. Always checks cache first.
        If order is missing, logs error and stops the monitor.
        """
        # Check cache first
        if order_id in self._order_strategy_cache:
            # If cache hit, we still need to ensure hedge detection has been done
            cached_order = self._order_strategy_cache[order_id][0]
            if cached_order and not hasattr(self, '_hedge_detection_done'):
                parent_order_id = cached_order.get('parent_order_id')
                if parent_order_id:
                    self.is_hedge = True
                    logger.info(f"🔍 OrderMonitor: Detected hedge order {order_id} with parent {parent_order_id} (from cache)")
                else:
                    self.is_hedge = False
                self._hedge_detection_done = True
            return self._order_strategy_cache[order_id]
        # Lazy-load session if not present
        from algosat.core.db import AsyncSessionLocal, get_order_by_id, get_strategy_symbol_by_id, get_strategy_by_id, get_strategy_config_by_id
        # Fetch order, strategy_symbol, strategy_config, and strategy in one go
        async with AsyncSessionLocal() as session:
            order = await get_order_by_id(session, order_id)
            if not order:
                logger.error(f"OrderMonitor: No order found for order_id={order_id}")
                self._order_strategy_cache[order_id] = (None, None, None, None)
                self.stop()
                return None, None, None, None
                
            # Check if this is a hedge order (has parent_order_id)
            parent_order_id = order.get('parent_order_id')
            if parent_order_id:
                self.is_hedge = True
                logger.info(f"🔍 OrderMonitor: Detected hedge order {order_id} with parent {parent_order_id}")
            else:
                self.is_hedge = False
            self._hedge_detection_done = True
                
            strategy_symbol_id = order.get('strategy_symbol_id')
            if not strategy_symbol_id:
                logger.error(f"OrderMonitor: No strategy_symbol_id for order_id={order_id}")
                self._order_strategy_cache[order_id] = (order, None, None, None)
                return order, None, None, None
            strategy_symbol = await get_strategy_symbol_by_id(session, strategy_symbol_id)
            if not strategy_symbol:
                logger.error(f"OrderMonitor: No strategy_symbol found for id={strategy_symbol_id}")
                self._order_strategy_cache[order_id] = (order, None, None, None)
                return order, None, None, None
            config_id = strategy_symbol.get('config_id')
            strategy_config = None
            if config_id:
                strategy_config = await get_strategy_config_by_id(session, config_id)
                if not strategy_config:
                    logger.error(f"OrderMonitor: No strategy_config found for id={config_id}")
            strategy_id = strategy_symbol.get('strategy_id')
            if not strategy_id:
                logger.error(f"OrderMonitor: No strategy_id in strategy_symbol for id={strategy_symbol_id}")
                self._order_strategy_cache[order_id] = (order, strategy_symbol, strategy_config, None)
                return order, strategy_symbol, strategy_config, None
            strategy = await get_strategy_by_id(session, strategy_id)
            self._order_strategy_cache[order_id] = (order, strategy_symbol, strategy_config, strategy)
            return order, strategy_symbol, strategy_config, strategy

    async def _price_order_monitor(self) -> None:
        """
        Main loop for price-based monitoring and exit.
        Uses unified order/strategy cache and helper methods for DRYness and efficiency.
        """
        await self.data_manager.ensure_broker()
        last_main_status = self._last_main_status
        last_broker_statuses = self._last_broker_statuses

        while self._running:
            # --- PRIORITY 1: Check PENDING exits FIRST before any expensive operations ---
            # Lightweight order status check to handle exits immediately
            try:
                from algosat.core.db import AsyncSessionLocal, get_order_by_id
                async with AsyncSessionLocal() as session:
                    quick_order_check = await get_order_by_id(session, self.order_id)
                    if quick_order_check:
                        quick_status = quick_order_check.get('status')
                        hedge_indicator = "🛡️[HEDGE]" if self.is_hedge else "📈[MAIN]"
                        order_symbol = quick_order_check.get('strike_symbol', 'N/A')
                        parent_id = quick_order_check.get('parent_order_id')
                        
                        if quick_status and quick_status.endswith('_PENDING'):
                            logger.info(f"OrderMonitor: {hedge_indicator} 🚨 PENDING status detected immediately: {quick_status} " +
                                       f"for order_id={self.order_id}, symbol={order_symbol}" + 
                                       (f", parent_id={parent_id}" if parent_id else ""))
                            # Process PENDING exit with minimal data
                            await self._check_and_complete_pending_exits(quick_order_check, quick_status)
                            # If monitor stopped during PENDING processing, exit loop
                            if not self._running:
                                logger.info(f"OrderMonitor: {hedge_indicator} Monitor stopped after immediate PENDING processing for order_id={self.order_id}")
                                return
                            # Clear cache after PENDING processing to get fresh data
                            await self._clear_order_cache("After immediate PENDING processing")
            except Exception as e:
                logger.error(f"OrderMonitor: Error in immediate PENDING check for order_id={self.order_id}: {e}")
                # Continue with normal flow if PENDING check fails
            
            # --- Normal monitoring flow continues if no PENDING exit processed ---
            try:
                agg: OrderAggregate = await self.data_manager.get_order_aggregate(self.order_id)
            except Exception as e:
                logger.error(f"OrderMonitor: Error in get_order_aggregate for order_id={self.order_id}: {e}")
                # If order is deleted, stop monitoring this order_id
                if "not found" in str(e).lower() or "deleted" in str(e).lower():
                    logger.info(f"OrderMonitor: Stopping monitor for order_id={self.order_id} as order is deleted.")
                    self.stop()
                    return
                await asyncio.sleep(self.price_order_monitor_seconds)
                continue
            # Fetch order, strategy_symbol, strategy_config, and strategy in one go (cached)
            order_row, strategy_symbol, strategy_config, strategy = await self._get_order_and_strategy(self.order_id)
            if order_row is None:
                logger.info(f"OrderMonitor: Stopping monitor for order_id={self.order_id} as order_row is None (order deleted).")
                self.stop()
                return
                
            # Initialize last_broker_statuses from agg.broker_orders if empty (first run or after restart)
            if not last_broker_statuses:
                current_entry_orders = [bro for bro in agg.broker_orders if getattr(bro, 'side', None) == 'ENTRY']
                for bro in current_entry_orders:
                    broker_exec_id = getattr(bro, 'id', None)
                    status = getattr(bro, 'status', None)
                    if broker_exec_id is not None and status is not None:
                        last_broker_statuses[broker_exec_id] = str(status)
            if last_main_status is None and order_row and order_row.get('status') is not None:
                last_main_status = str(order_row.get('status'))
                self._last_main_status = last_main_status
            # --- Time-based exit/stop logic before processing broker orders ---
            # Get product_type and trade_config for time-based decisions
            product_type = None
            trade_config = None
            if strategy:
                product_type = strategy.get('product_type') or strategy.get('producttype')
            if strategy_config:
                import json
                try:
                    trade_param = strategy_config.get('trade')
                    if trade_param:
                        trade_config = json.loads(trade_param) if isinstance(trade_param, str) else trade_param
                except Exception as e:
                    logger.error(f"OrderMonitor: Error parsing trade config for time-based exit: {e}")
            
            # Time-based logic
            from datetime import datetime, time as dt_time
            import pytz
            current_time = datetime.now(pytz.timezone('Asia/Kolkata'))
            current_time_only = current_time.time()
            
            # HEDGE ORDER PROTECTION: Hedge orders should NOT trigger time-based exits
            # Only main orders should handle square-off and AWAITING_ENTRY exits
            if self.is_hedge:
                logger.info(f"OrderMonitor: {hedge_indicator} Skipping time-based exit logic for hedge order_id={self.order_id}")
            else:
                logger.debug(f"OrderMonitor: {hedge_indicator} Checking time-based exit logic for main order_id={self.order_id}")
            
                # For non-DELIVERY orders: check square_off_time
                if product_type and product_type.upper() != 'DELIVERY':
                    square_off_time_str = None
                    if trade_config:
                        square_off_time_str = trade_config.get('square_off_time')
                    
                    if square_off_time_str:
                        try:
                            # Parse square_off_time (e.g., "15:25" -> time(15, 25))
                            hour, minute = map(int, square_off_time_str.split(':'))
                            square_off_time = dt_time(hour, minute)
                            
                            if current_time_only >= square_off_time:
                                logger.info(f"OrderMonitor: {hedge_indicator} Square-off time {square_off_time_str} reached for non-DELIVERY order_id={self.order_id}. Exiting order.")
                                try:
                                    msg = f"⏰ <b>Square-off Exit Triggered</b>\n<b>Order ID:</b> <code>{self.order_id}</code>\n<b>Time:</b> <code>{square_off_time_str}</code>"
                                    send_telegram_async(msg)
                                except Exception as e:
                                    logger.error(f"Failed to send Telegram square-off notification: {e}")
                                try:
                                    # Square-off time exit handling
                                    from algosat.common import constants
                                    await self.order_manager.exit_order(self.order_id, exit_reason=f"Square-off time {square_off_time_str} reached")
                                    await self.order_manager.update_order_status_in_db(self.order_id, f"{constants.TRADE_STATUS_EXIT_EOD}_PENDING")
                                    await self._clear_order_cache("Square-off time exit status updated to PENDING")
                                    logger.info(f"OrderMonitor: {hedge_indicator} EOD exit set to PENDING for order_id={self.order_id}. PENDING processor will complete the exit.")
                                    # Continue monitoring loop - PENDING check at beginning will handle completion
                                    continue
                                except Exception as e:
                                    logger.error(f"OrderMonitor: {hedge_indicator} Failed to exit order {self.order_id} at square-off time: {e}")
                        except Exception as e:
                            logger.error(f"OrderMonitor: {hedge_indicator} Error parsing square_off_time '{square_off_time_str}': {e}")
                
                # For DELIVERY orders: stop monitoring at 3:30 PM
                elif product_type and product_type.upper() == 'DELIVERY':
                    market_close_time = dt_time(15, 30)  # 3:30 PM
                    if current_time_only >= market_close_time:
                        logger.info(f"OrderMonitor: {hedge_indicator} Market close time 15:30 reached for DELIVERY order_id={self.order_id}. Stopping monitoring.")
                        self.stop()
                        return
                
                # Exit AWAITING_ENTRY orders at 15:25 (regardless of product type)
                awaiting_entry_exit_time = dt_time(15, 25)  # 3:25 PM
                current_status = order_row.get('status') if order_row else None
                if (current_time_only >= awaiting_entry_exit_time and 
                    current_status in ('AWAITING_ENTRY', OrderStatus.AWAITING_ENTRY)):
                    logger.info(f"OrderMonitor: {hedge_indicator} 15:25 reached for AWAITING_ENTRY order_id={self.order_id}. Exiting order.")
                    try:
                        msg = f"🚫 <b>AWAITING_ENTRY Cancelled</b>\n<b>Order ID:</b> <code>{self.order_id}</code>\n<b>Reason:</b> <code>15:25 reached, cancelling unfilled order</code>"
                        send_telegram_async(msg)
                    except Exception as e:
                        logger.error(f"Failed to send Telegram awaiting_entry cancel notification: {e}")
                    try:
                        await self.order_manager.exit_order(self.order_id, exit_reason="AWAITING_ENTRY order exit at 15:25")
                        # Update status to CANCELLED
                        await self.order_manager.update_order_status_in_db(self.order_id, "CANCELLED")
                        await self._clear_order_cache("AWAITING_ENTRY exit status updated")
                        self.stop()
                        return
                    except Exception as e:
                        logger.error(f"OrderMonitor: {hedge_indicator} Failed to exit AWAITING_ENTRY order {self.order_id} at 15:25: {e}")
                        return

            # --- P&L monitoring using DB data and current LTP (simplified approach) ---
            current_status = order_row.get('status') if order_row and order_row.get('status') else last_main_status
            order_symbol = order_row.get('strike_symbol') if order_row else 'N/A'
            hedge_indicator = "🛡️[HEDGE]" if self.is_hedge else "📈[MAIN]"
            parent_id = order_row.get('parent_order_id') if order_row else None
            
            logger.info(f"OrderMonitor: {hedge_indicator} CurrentStatus: {current_status} for order_id={self.order_id}, symbol={order_symbol}" + 
                       (f", parent_id={parent_id}" if parent_id else ""))
            
            # --- Telegram notification for status transition to OPEN ---
            try:
                if current_status == 'OPEN' and last_main_status != 'OPEN':
                    hedge_tag = "🛡️ HEDGE " if self.is_hedge else ""
                    msg = f"🟢 <b>{hedge_tag}Order OPEN</b>\n<b>Order ID:</b> <code>{self.order_id}</code>" + \
                          (f"\n<b>Parent ID:</b> <code>{parent_id}</code>" if parent_id else "") + \
                          f"\n<b>Symbol:</b> <code>{order_symbol}</code>"
                    send_telegram_async(msg)
            except Exception as e:
                logger.error(f"Failed to send Telegram OPEN notification: {e}")

            # --- Use live broker order data from order_cache for ENTRY side ---
            entry_broker_db_orders = [bro for bro in agg.broker_orders if getattr(bro, 'side', None) == 'ENTRY']
            all_statuses = []
            status_set = set()
            
            logger.info(f"OrderMonitor: {hedge_indicator} Processing {len(entry_broker_db_orders)} ENTRY broker executions for order_id={self.order_id}, symbol={order_symbol}")
            
            try:
                for bro in entry_broker_db_orders:
                    try:
                        broker_exec_id = getattr(bro, 'id', None)
                        broker_order_id = getattr(bro, 'order_id', None)
                        broker_id = getattr(bro, 'broker_id', None)
                        broker_symbol = getattr(bro, 'symbol', None) or getattr(bro, 'tradingsymbol', None)
                        
                        logger.debug(f"OrderMonitor: {hedge_indicator} Processing broker_exec_id={broker_exec_id}, " +
                                   f"broker_order_id={broker_order_id}, broker_id={broker_id}, symbol={broker_symbol} for order_id={self.order_id}")
                        
                        broker_name = None
                        if broker_id is not None:
                            try:
                                broker_name = await self._get_broker_name_with_cache(broker_id)
                            except Exception as e:
                                logger.error(f"OrderMonitor: {hedge_indicator} Could not get broker name for broker_id={broker_id}: {e}")
                        # If broker_order_id is None or empty, order is not placed, set status to FAILED
                        cache_order = None
                        if not broker_order_id:
                            broker_status = "FAILED"
                            logger.warning(f"OrderMonitor: {hedge_indicator} No broker_order_id for exec_id={broker_exec_id}, setting status to FAILED")
                        else:
                            cache_lookup_order_id = self._get_cache_lookup_order_id(
                                broker_order_id, broker_name, product_type
                            )
                            # Fetch live broker order from order_cache
                            if broker_name and cache_lookup_order_id:
                                try:
                                    cache_order = await self.order_cache.get_order_by_id(broker_name, cache_lookup_order_id)
                                    logger.debug(f"OrderMonitor: {hedge_indicator} Fetched order from cache for order_id={self.order_id}, " +
                                               f"broker_name={broker_name}, broker_order_id={cache_lookup_order_id}: {cache_order}")  
                                except Exception as e:
                                    logger.error(f"OrderMonitor: {hedge_indicator} Error fetching order from cache for order_id={self.order_id}," +
                                               f"broker_name={broker_name}, order_id={cache_lookup_order_id}: {e}")
                            # Use status from cache_order if available, else fallback to DB
                            broker_status = None
                            if cache_order and 'status' in cache_order:
                                broker_status = cache_order['status']
                                logger.debug(f"OrderMonitor: {hedge_indicator} Using cache status '{broker_status}' for broker_exec_id={broker_exec_id}")
                            else:
                                logger.info(f"OrderMonitor: {hedge_indicator} Using DB status for broker_order_id={broker_order_id} " +
                                          f"as cache_order not found or missing status for order_id {self.order_id}")
                                broker_status = getattr(bro, 'status', None)
                            if broker_status and isinstance(broker_status, int) and broker_name == "fyers":
                                broker_status = FYERS_STATUS_MAP.get(broker_status, broker_status)
                            # Normalize broker_status
                            if broker_status and isinstance(broker_status, str) and broker_status.startswith("OrderStatus."):
                                broker_status = broker_status.split(".")[-1]
                            elif broker_status and isinstance(broker_status, OrderStatus):
                                broker_status = broker_status.value
                            # broker_status = "FILLED"

                        all_statuses.append(broker_status)
                        status_set.add(broker_status)
                        
                        logger.info(f"OrderMonitor: {hedge_indicator} Broker execution status: exec_id={broker_exec_id}, " +
                                  f"broker={broker_name}, symbol={broker_symbol}, status={broker_status}")
                    except Exception as e:
                        logger.error(f"OrderMonitor: {hedge_indicator} Unexpected error processing broker order " +
                                   f"(exec_id={getattr(bro, 'id', None)}): {e}", exc_info=True)
                        all_statuses.append("FAILED")
                        status_set.add("FAILED")
                    last_status = last_broker_statuses.get(broker_exec_id)
                    # --- Enhancement: Also check executed_quantity for PARTIALLY_FILLED updates ---
                    # Get executed_quantity from broker (cache or bro)
                    broker_executed_quantity = None
                    broker_placed_quantity = None
                    if cache_order:
                        broker_executed_quantity = cache_order.get("executed_quantity") or cache_order.get("filled_quantity") or cache_order.get("filledQty")
                        broker_placed_quantity = cache_order.get("quantity") or cache_order.get("qty") or cache_order.get("filledQty")
                    # if broker_executed_quantity is None:
                        # broker_executed_quantity = getattr(bro, "executed_quantity", None) or getattr(bro, "filled_quantity", None) or getattr(bro, "filledQty", None)
                    # Get DB executed_quantity (from bro)
                    db_executed_quantity = getattr(bro, "executed_quantity", None) or getattr(bro, "filled_quantity", None) or getattr(bro, "filledQty", None)
                    # Only update if status changed, or for PARTIALLY_FILLED if executed_quantity increased
                    should_update = False
                    if broker_status != last_status:
                        should_update = True
                    elif broker_status in ("PARTIALLY_FILLED", "PARTIAL"):
                        try:
                            if broker_executed_quantity is not None and db_executed_quantity is not None:
                                if float(broker_executed_quantity) > float(db_executed_quantity):
                                    should_update = True
                        except Exception as e:
                            logger.error(f"OrderMonitor: Error comparing executed_quantity for broker_exec_id={broker_exec_id}: {e}")
                    if should_update:
                        # If status transitions from PENDING/PARTIAL to FILLED/PARTIAL, update all fields
                        transition_to_filled = (
                            (last_status in ("PENDING", "TRIGGER_PENDING", "PARTIAL", "PARTIALLY_FILLED")) and
                            (broker_status in ("FILLED", "PARTIAL", "PARTIALLY_FILLED"))
                        )
                        if transition_to_filled:
                            from datetime import datetime, timezone
                            executed_quantity = broker_executed_quantity
                            quantity = broker_placed_quantity
                            execution_price = None
                            symbol_val = None
                            # Prefer cache_order for execution details, fallback to bro
                            if cache_order:
                                execution_price = cache_order.get("exec_price") or cache_order.get("execution_price") or cache_order.get("average_price") or cache_order.get("tradedPrice")
                                order_type = cache_order.get("order_type")
                                # Apply Fyers order type mapping if this is a Fyers broker response
                                if broker_name and broker_name.lower() == "fyers" and order_type is not None:
                                    from algosat.core.order_manager import FYERS_ORDER_TYPE_MAP
                                    order_type = FYERS_ORDER_TYPE_MAP.get(order_type, str(order_type))
                                product_type_val = cache_order.get("product_type")
                                # Get quantity from cache_order (qty or quantity)
                                quantity = cache_order.get("qty") or cache_order.get("quantity")
                                # Get symbol from cache_order (symbol or tradingsymbol)
                                symbol_val = cache_order.get("symbol") or cache_order.get("tradingsymbol")
                            if execution_price is None:
                                execution_price = getattr(bro, "exec_price", None) or getattr(bro, "execution_price", None) or getattr(bro, "average_price", None) or getattr(bro, "tradedPrice", None)
                            if order_type is None:
                                order_type = getattr(bro, "order_type", None)
                                # Apply Fyers order type mapping if this is a Fyers broker response
                                if broker_name and broker_name.lower() == "fyers" and order_type is not None:
                                    from algosat.core.order_manager import FYERS_ORDER_TYPE_MAP
                                    order_type = FYERS_ORDER_TYPE_MAP.get(order_type, str(order_type))
                            if product_type_val is None:
                                product_type_val = getattr(bro, "product_type", None)
                            if quantity is None:
                                quantity = getattr(bro, "qty", None) or getattr(bro, "quantity", None)
                            if symbol_val is None:
                                symbol_val = getattr(bro, "symbol", None) or getattr(bro, "tradingsymbol", None)
                            
                            # Note: execution_time is handled by order_manager.py during status transitions
                            
                            # Use update_rows_in_table directly for comprehensive broker execution updates
                            from algosat.core.db import AsyncSessionLocal, update_rows_in_table
                            from algosat.core.dbschema import broker_executions
                            
                            comprehensive_update_fields = {
                                "status": broker_status.value if hasattr(broker_status, 'value') else str(broker_status),
                                "executed_quantity": executed_quantity,
                                "quantity": quantity,
                                "execution_price": execution_price,
                                "order_type": order_type,
                                "product_type": product_type_val,
                                "symbol": symbol_val,
                                "raw_execution_data": self.order_manager._serialize_datetime_for_json(cache_order)  # Store complete broker order data
                                # Note: execution_time is handled by order_manager.py during status transitions
                            }
                            
                            # Remove None values to avoid unnecessary DB updates
                            comprehensive_update_fields = {k: v for k, v in comprehensive_update_fields.items() if v is not None}
                            
                            logger.info(f"OrderMonitor: {hedge_indicator} Comprehensive update for broker_exec_id={broker_exec_id} " +
                                      f"with fields: {list(comprehensive_update_fields.keys())}")
                            
                            async with AsyncSessionLocal() as comp_session:
                                await update_rows_in_table(
                                    target_table=broker_executions,
                                    condition=broker_executions.c.id == broker_exec_id,
                                    new_values=comprehensive_update_fields
                                )
                                logger.debug(f"OrderMonitor: {hedge_indicator} Successfully updated broker_exec_id={broker_exec_id} with comprehensive data")
                        else:
                            # Simple status-only update
                            logger.info(f"OrderMonitor: {hedge_indicator} Simple status update for broker_exec_id={broker_exec_id}: {broker_status}")
                            await self.order_manager.update_broker_exec_status_in_db(broker_exec_id, broker_status)
                        last_broker_statuses[broker_exec_id] = broker_status
            except Exception as e:
                logger.error(f"OrderMonitor: {hedge_indicator} Unexpected error in broker order status loop: {e}", exc_info=True)
               

            # --- Aggregate and update Orders table with sum of broker_execs quantities ---
            try:
                from algosat.core.db import AsyncSessionLocal, update_rows_in_table, get_order_by_id
                from algosat.core.dbschema import orders, broker_executions
                async with AsyncSessionLocal() as session:
                    # Fetch all broker_executions for this order with side='ENTRY' (fresh from DB for latest values)
                    from algosat.core.db import get_broker_executions_for_order
                    broker_exec_rows = await get_broker_executions_for_order(session, self.order_id, side='ENTRY')
                    total_quantity = 0
                    total_executed_quantity = 0
                    vwap_total_value = 0.0
                    vwap_total_qty = 0.0
                    for be in broker_exec_rows:
                        q = be.get('quantity') or 0
                        eq = be.get('executed_quantity') or 0
                        exec_price = be.get('execution_price') or 0
                        try:
                            q = float(q) if q is not None else 0
                        except Exception:
                            q = 0
                        try:
                            eq = float(eq) if eq is not None else 0
                        except Exception:
                            eq = 0
                        try:
                            exec_price = float(exec_price) if exec_price is not None else 0
                        except Exception:
                            exec_price = 0
                        total_quantity += q
                        total_executed_quantity += eq
                        vwap_total_value += eq * exec_price
                        vwap_total_qty += eq
                    entry_price = round(vwap_total_value / vwap_total_qty, 2) if vwap_total_qty > 0 else None
                    # Fetch current order values from DB
                    current_order = await get_order_by_id(session, self.order_id)
                    current_qty = current_order.get('qty') if current_order else None
                    current_executed_quantity = current_order.get('executed_quantity') if current_order else None
                    current_entry_price = current_order.get('entry_price') if current_order else None
                    # Only update if any value changed
                    if (
                        float(total_quantity) != float(current_qty or 0) or
                        float(total_executed_quantity) != float(current_executed_quantity or 0) or
                        (entry_price is not None and float(entry_price) != float(current_entry_price or 0))
                    ):
                        update_fields = {"qty": total_quantity, "executed_quantity": total_executed_quantity}
                        if entry_price is not None:
                            update_fields["entry_price"] = entry_price
                        await update_rows_in_table(
                            target_table=orders,
                            condition=orders.c.id == self.order_id,
                            new_values=update_fields
                        )
                        logger.info(f"OrderMonitor: {hedge_indicator} Updated Orders table for order_id={self.order_id} " +
                                  f"with qty={total_quantity}, executed_quantity={total_executed_quantity}, entry_price={entry_price}")
                    else:
                        logger.debug(f"OrderMonitor: {hedge_indicator} No change in qty, executed_quantity, entry_price for order_id={self.order_id}. Skipping DB update.")
            except Exception as e:
                logger.error(f"OrderMonitor: {hedge_indicator} Error updating aggregated quantity/executed_quantity for order_id={self.order_id}: {e}")
            logger.info(f"OrderMonitor: {hedge_indicator} Order {self.order_id} ENTRY broker statuses (live): {all_statuses}")
            # --- Decision logic for main order status ---
            # PRESERVE EXIT STATUS PRIORITY: Don't overwrite exit statuses with broker-derived OPEN status
            current_db_status = order_row.get('status') if order_row else None
            main_status = None
            
            logger.info(f"OrderMonitor: {hedge_indicator} Status decision logic: current_db_status={current_db_status}, " +
                       f"broker_status_set={status_set}")
            
            # Check if current order status is an exit status (base or PENDING) - preserve it
            if current_db_status and (
                current_db_status.startswith('EXIT_') or 
                current_db_status.endswith('_PENDING') or
                current_db_status in ('CLOSED', 'CANCELLED', 'REJECTED', 'FAILED')
            ):
                # Preserve the exit/terminal status, don't override with broker status
                main_status = current_db_status
                logger.info(f"OrderMonitor: {hedge_indicator} Preserving exit/terminal status '{current_db_status}' " +
                           f"for order_id={self.order_id} (not overriding with broker status)")
            else:
                # Normal broker-based status logic for non-exit statuses
                if any(s in ("FILLED", "PARTIALLY_FILLED", "OPEN") for s in status_set):
                    main_status = OrderStatus.OPEN
                elif all(s == "PENDING" for s in all_statuses) and all_statuses:
                    main_status = OrderStatus.AWAITING_ENTRY
                elif all(s == "CANCELLED" for s in all_statuses) and all_statuses:
                    main_status = OrderStatus.CANCELLED
                elif all(s == "REJECTED" for s in all_statuses) and all_statuses:
                    main_status = OrderStatus.REJECTED
                elif all(s == "FAILED" for s in all_statuses) and all_statuses:
                    main_status = OrderStatus.FAILED
                elif all(s in ("REJECTED", "FAILED") for s in all_statuses) and all_statuses:
                    main_status = OrderStatus.CANCELLED
            # Only update Orders table if status changed AND we're not preserving an exit status
            if main_status is not None and main_status != last_main_status:
                # Don't update DB if we're preserving an exit status (it's already the correct status)
                if main_status == current_db_status:
                    logger.debug(f"OrderMonitor: Status preserved for order_id={self.order_id}: {main_status} (no DB update needed)")
                    last_main_status = main_status  # Update local tracking
                elif main_status == OrderStatus.OPEN and any(s in ("FILLED", "PARTIALLY_FILLED") for s in status_set):
                    from datetime import datetime, timezone
                    entry_time = datetime.now(timezone.utc)
                    logger.info(f"OrderMonitor: {hedge_indicator} Updating order_id={self.order_id} to {main_status} with entry_time={entry_time}")
                    await self.order_manager.update_order_status_in_db(self.order_id, main_status)
                    await self.order_manager.update_order_stop_loss_in_db(self.order_id, order_row.get('stop_loss'))
                    from algosat.core.db import AsyncSessionLocal, update_rows_in_table
                    from algosat.core.dbschema import orders

                    await update_rows_in_table(
                        target_table=orders,
                        condition=orders.c.id == self.order_id,
                        new_values={"entry_time": entry_time}
                    )
                    await self._clear_order_cache("Order status updated to OPEN with entry_time")
                else:
                    logger.info(f"OrderMonitor: {hedge_indicator} Updating order_id={self.order_id} to {main_status}")
                    await self.order_manager.update_order_status_in_db(self.order_id, main_status)
                    await self._clear_order_cache(f"Order status updated to {main_status}")
                last_main_status = main_status
                if main_status in (OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.FAILED):
                    logger.info(f"OrderMonitor: {hedge_indicator} Order {self.order_id} reached terminal status {main_status}. Checking for child orders to close.")
                    
                    # CRITICAL FIX: Close child orders when main order fails
                    # NOTE: This should only apply to main orders, not hedge orders
                    if not self.is_hedge:
                        try:
                            if await self.order_manager.has_child_orders(self.order_id):
                                logger.info(f"OrderMonitor: {hedge_indicator} Found child orders for failed main order {self.order_id}. Closing them before stopping monitor.")
                                await self.order_manager.exit_child_orders(
                                    parent_order_id=self.order_id,
                                    exit_reason=f"Parent order {self.order_id} reached terminal status {main_status}",
                                    check_live_status=True  # Check live status to update hedge orders before exit decisions
                                )
                                logger.info(f"OrderMonitor: {hedge_indicator} Successfully closed child orders for failed order {self.order_id}")
                            else:
                                logger.debug(f"OrderMonitor: {hedge_indicator} No child orders found for order {self.order_id}")
                        except Exception as e:
                            logger.error(f"OrderMonitor: {hedge_indicator} Error closing child orders for failed order {self.order_id}: {e}", exc_info=True)
                            # Continue to stop monitor even if child order closure fails
                    else:
                        logger.info(f"OrderMonitor: {hedge_indicator} Hedge order {self.order_id} reached terminal status {main_status}. Skipping child order closure logic.")
                    
                    logger.info(f"OrderMonitor: {hedge_indicator} Order {self.order_id} reached terminal status {main_status}. Stopping monitor.")
                    try:
                        hedge_tag = "🛡️ HEDGE " if self.is_hedge else ""
                        msg = f"❗ <b>{hedge_tag}Order Terminal Status</b>\n<b>Order ID:</b> <code>{self.order_id}</code>" + \
                              (f"\n<b>Parent ID:</b> <code>{parent_id}</code>" if parent_id else "") + \
                              f"\n<b>Status:</b> <code>{main_status}</code>\n<b>Symbol:</b> <code>{order_symbol}</code>\nAll brokers reported this status. Stopping monitor."
                        send_telegram_async(msg)
                    except Exception as e:
                        logger.error(f"Failed to send Telegram terminal status notification: {e}")
                    self.stop()
                    return
                
                # Refresh order_row after status update to ensure methods get latest data
                try:
                    # Clear cache and fetch fresh order data after DB update
                    await self._clear_order_cache("After status update - refreshing order data for method calls")
                    order_row, _, _, _ = await self._get_order_and_strategy(self.order_id)
                    logger.debug(f"OrderMonitor: Refreshed order_row after status update for order_id={self.order_id}")
                except Exception as e:
                    logger.error(f"OrderMonitor: Error refreshing order_row after status update: {e}")
                
            # REFRESH ORDER STATUS: Get fresh order data after broker execution updates
            # This ensures we have the latest status for position monitoring and price checks
            try:
                await self._clear_order_cache("Before position monitoring - ensuring fresh order data")
                order_row, _, _, _ = await self._get_order_and_strategy(self.order_id)
                logger.debug(f"OrderMonitor: Refreshed order_row before position monitoring for order_id={self.order_id}")
            except Exception as e:
                logger.error(f"OrderMonitor: Error refreshing order_row before position monitoring: {e}")
                
            # --- Combined OPEN order processing: Price-based exit logic + Position monitoring ---
            # Use actual database status as source of truth, not derived broker status
            actual_order_status = order_row.get('status') if order_row else None
            if actual_order_status == 'OPEN':
                # Fetch current LTP once for both exit logic and position monitoring
                current_ltp = await self._update_current_price_for_open_order(order_row)
                
                # HEDGE ORDER PROTECTION: Price-based exits should only apply to main orders
                if not self.is_hedge:
                    await self._check_price_based_exit(order_row, strategy, actual_order_status, current_ltp)
                else:
                    logger.debug(f"OrderMonitor: {hedge_indicator} Skipping price-based exit check for hedge order {self.order_id}")
                
                # P&L calculation using DB data and current LTP (simplified approach)
                # NOTE: This P&L calculation should apply to both main and hedge orders for monitoring purposes
                try:
                    # Get ENTRY broker executions from database
                    async with AsyncSessionLocal() as session:
                        entry_broker_db_orders = await get_broker_executions_for_order(session, self.order_id, side='ENTRY') 
                    
                    # Use the LTP already fetched above for PnL calculations
                    if current_ltp is None or current_ltp <= 0:
                        logger.warning(f"OrderMonitor: {hedge_indicator} Invalid LTP ({current_ltp}) for order_id={self.order_id}, setting to 0 for PnL calculation")
                        current_ltp = 0.0
                    else:
                        logger.debug(f"OrderMonitor: {hedge_indicator} Using fetched LTP={current_ltp} for PnL calculation for order_id={self.order_id}")
                    
                    total_pnl = 0.0
                    valid_executions_count = 0
                    
                    for bro in entry_broker_db_orders:
                        # Skip processing if broker execution is invalid or failed
                        broker_status = bro.get('status', '').upper()
                        symbol_val = bro.get('symbol', None) or bro.get('tradingsymbol', None)
                        executed_quantity = bro.get('executed_quantity', None) or bro.get('quantity', None)
                        entry_price = bro.get('execution_price', None)
                        entry_side = bro.get('action', '').upper()
                        
                        # Simple validation: skip if essential data is missing or execution failed
                        if (broker_status != 'FILLED' or 
                            symbol_val is None or 
                            executed_quantity is None or 
                            executed_quantity <= 0 or
                            entry_price is None or 
                            entry_price <= 0):
                            logger.debug(f"OrderMonitor: {hedge_indicator} Skipping P&L calculation for broker execution - "
                                       f"status={broker_status}, symbol={symbol_val}, qty={executed_quantity}, price={entry_price}")
                            continue
                        
                        # Calculate P&L for this execution using DB data + current LTP
                        execution_pnl = 0.0
                        if entry_side == 'BUY':
                            # Long position: profit when current_price > entry_price
                            execution_pnl = (current_ltp - float(entry_price)) * executed_quantity
                        elif entry_side == 'SELL':
                            # Short position: profit when current_price < entry_price
                            execution_pnl = (float(entry_price) - current_ltp) * executed_quantity
                        else:
                            logger.warning(f"OrderMonitor: {hedge_indicator} Unknown entry side '{entry_side}' for P&L calculation")
                            continue
                        
                        total_pnl += execution_pnl
                        valid_executions_count += 1
                        
                        logger.info(f"OrderMonitor: {hedge_indicator} P&L calculation for execution:")
                        logger.info(f"  Broker ID: {bro.get('broker_id')}")
                        logger.info(f"  Entry Side: {entry_side}")
                        logger.info(f"  Entry Price: {entry_price}")
                        logger.info(f"  Current LTP: {current_ltp}")
                        logger.info(f"  Executed Quantity: {executed_quantity}")
                        logger.info(f"  Execution P&L: {execution_pnl}")
                    
                    logger.info(f"OrderMonitor: {hedge_indicator} Total P&L calculation completed for order_id={self.order_id}:")
                    logger.info(f"  Valid executions processed: {valid_executions_count}")
                    logger.info(f"  Total P&L: {total_pnl}")
                    
                    # Update order PnL field in DB
                    try:
                        logger.info(f"OrderMonitor: {hedge_indicator} About to update PnL for order_id={self.order_id} with value={total_pnl}")
                        await self.order_manager.update_order_pnl_in_db(self.order_id, total_pnl)
                        logger.info(f"OrderMonitor: {hedge_indicator} Successfully called update_order_pnl_in_db for order_id={self.order_id}: {total_pnl}")
                        
                        # Verify the update by reading back from DB
                        from algosat.core.db import AsyncSessionLocal, get_order_by_id
                        async with AsyncSessionLocal() as session:
                            updated_order = await get_order_by_id(session, self.order_id)
                            current_pnl_in_db = updated_order.get('pnl') if updated_order else None
                            logger.info(f"OrderMonitor: {hedge_indicator} PnL verification for order_id={self.order_id} - Expected: {total_pnl}, Actual in DB: {current_pnl_in_db}")
                    except Exception as e:
                        logger.error(f"OrderMonitor: {hedge_indicator} Error updating order PnL for order_id={self.order_id}: {e}")
                    
                    # � UPDATE BROKER EXECUTIONS PNL: Update P&L for all ENTRY broker executions using current LTP
                    try:
                        await self._update_broker_executions_pnl(current_ltp, entry_broker_db_orders)
                    except Exception as e:
                        logger.error(f"OrderMonitor: {hedge_indicator} Error updating broker executions P&L for order_id={self.order_id}: {e}")
                    
                    # �🚨 PER-TRADE LOSS VALIDATION - ONLY FOR MAIN ORDERS 🚨
                    # HEDGE ORDER PROTECTION: Hedge orders should NOT trigger loss limit exits
                    if not self.is_hedge:
                        try:
                            # 1. Get trade enabled brokers count from risk summary and current order data
                            from algosat.core.db import get_broker_risk_summary
                            async with AsyncSessionLocal() as session:
                                risk_data = await get_broker_risk_summary(session)
                                trade_enabled_brokers = risk_data.get('summary', {}).get('trade_enabled_brokers', 0)
                                
                                # 2. Get lot_qty from current order (within same session)
                                current_order = await get_order_by_id(session, self.order_id)
                                lot_qty = current_order.get('lot_qty', 0) if current_order else 0
                            
                            # 3. Get max_loss_per_lot from strategy config
                            max_loss_per_lot = 0
                            if strategy_config and strategy_config.get('trade'):
                                import json
                                try:
                                    trade_config = json.loads(strategy_config['trade']) if isinstance(strategy_config['trade'], str) else strategy_config['trade']
                                    max_loss_per_lot = trade_config.get('max_loss_per_lot', 0)
                                except Exception as e:
                                    logger.error(f"OrderMonitor: {hedge_indicator} Error parsing trade config for max_loss_per_lot: {e}")
                            
                            # 4. Calculate total risk exposure
                            total_risk_exposure = lot_qty * trade_enabled_brokers * max_loss_per_lot
                            
                            # 5. Check if loss exceeds limit
                            if total_risk_exposure > 0 and total_pnl < -abs(total_risk_exposure):
                                logger.critical(f"🚨 {hedge_indicator} PER-TRADE LOSS LIMIT EXCEEDED for order_id={self.order_id}! "
                                              f"Current P&L: {total_pnl}, Max Loss: {total_risk_exposure} "
                                              f"(lot_qty: {lot_qty} × brokers: {trade_enabled_brokers} × max_loss_per_lot: {max_loss_per_lot})")
                                
                                # 6. Exit the order immediately
                                await self.order_manager.exit_order(self.order_id, exit_reason="Per-trade loss limit exceeded")
                                # Update status to max loss exit PENDING - let check_and_complete_pending_exits handle completion
                                from algosat.common import constants
                                await self.order_manager.update_order_status_in_db(self.order_id, f"{constants.TRADE_STATUS_EXIT_MAX_LOSS}_PENDING")
                                await self._clear_order_cache("Per-trade loss limit exit status updated to PENDING")
                                logger.critical(f"🚨 {hedge_indicator} Per-trade loss limit exit set to PENDING for order_id={self.order_id}. PENDING processor will complete the exit.")
                                # Continue monitoring loop - PENDING check at beginning will handle completion
                                continue
                            else:
                                logger.debug(f"OrderMonitor: {hedge_indicator} Per-trade risk check passed for order_id={self.order_id}. "
                                           f"P&L: {total_pnl}, Risk exposure: {total_risk_exposure}")
                                
                        except Exception as e:
                            logger.error(f"OrderMonitor: {hedge_indicator} Error in per-trade loss validation for order_id={self.order_id}: {e}")
                    else:
                        logger.debug(f"OrderMonitor: {hedge_indicator} Skipping per-trade loss validation for hedge order {self.order_id}")
                    
                    # Note: Position closure detection has been removed since we now rely on 
                    # exit order status tracking instead of broker position matching
                    
                except Exception as e:
                    logger.error(f"OrderMonitor: {hedge_indicator} Error in P&L monitoring: {e}", exc_info=True)
            logger.debug(f"OrderMonitor: {hedge_indicator} Broker position monitoring completed for order_id={self.order_id}")
            logger.debug("Next check in {self.price_order_monitor_seconds} seconds...")
            await asyncio.sleep(self.price_order_monitor_seconds)
        logger.info(f"OrderMonitor: {hedge_indicator} Stopping price monitor for order_id={self.order_id} (last status: {last_main_status})")
    
    async def _check_price_based_exit(self, order_row, strategy, current_main_status, current_ltp=None):
        """
        Check price-based exit conditions for OptionBuy and OptionSell strategies.
        Compare LTP with target_price and stop_loss to trigger exits.
        
        Args:
            order_row: Order data from database
            strategy: Strategy instance or dict
            current_main_status: Current main order status
            current_ltp: Pre-fetched LTP to avoid duplicate API calls (optional)
        """
        try:
            order_symbol = order_row.get('strike_symbol', 'N/A') if order_row else 'N/A'
            hedge_indicator = "🛡️[HEDGE]" if self.is_hedge else "📈[MAIN]"
            parent_id = order_row.get('parent_order_id') if order_row else None
            
            logger.info(f"OrderMonitor: {hedge_indicator} Starting price-based exit check for order_id={self.order_id}, " +
                       f"symbol={order_symbol}, status={current_main_status}" + 
                       (f", parent_id={parent_id}" if parent_id else ""))
            
            # HEDGE ORDER PROTECTION: Hedge orders should NEVER trigger price-based exits
            if self.is_hedge:
                logger.info(f"OrderMonitor: {hedge_indicator} BLOCKING price-based exit check for hedge order_id={self.order_id}. " +
                           f"Hedge orders should not trigger independent exits.")
                return
            
            # Only check for OPEN orders
            if current_main_status != 'OPEN':
                logger.debug(f"OrderMonitor: {hedge_indicator} ⏸️ SKIP: Price check skipped - order_id={self.order_id} status is '{current_main_status}', not 'OPEN'")
                return
            
            # Only for OptionBuy and OptionSell strategies
            strategy_name = await self._get_strategy_name(strategy)
            
            logger.info(f"OrderMonitor: 📋 Price check - order_id={self.order_id}, strategy='{strategy_name}'")
            
            if strategy_name not in ['optionbuy', 'optionsell']:
                # logger.debug(f"OrderMonitor: ⏸️ SKIP: Price check skipped - order_id={self.order_id} strategy '{strategy_name}' not supported for price-based exits. Supported: [optionbuy, optionsell]")
                return
                
            # Get required values from order
            strike_symbol = order_row.get('strike_symbol')
            target_price = order_row.get('target_price')
            stop_loss = order_row.get('stop_loss')
            side = order_row.get('side', '').upper()
            
            logger.info(f"OrderMonitor: Price check data - order_id={self.order_id}, symbol={strike_symbol}, target={target_price}, SL={stop_loss}, side={side}")
            
            if not strike_symbol:
                logger.warning(f"OrderMonitor: No strike_symbol for price-based exit check, order_id={self.order_id}")
                return
                
            if target_price is None and stop_loss is None:
                logger.info(f"OrderMonitor: No target_price or stop_loss set for order_id={self.order_id} - skipping price check")
                return
                
            # Use direct LTP API call instead of position-based LTP
            ltp = None
            if current_ltp is not None:
                ltp = float(current_ltp)
                logger.info(f"OrderMonitor: Using passed LTP for price check: order_id={self.order_id}, symbol={strike_symbol}, LTP={ltp}")
            else:
                # Fallback: fetch LTP directly using data_manager.get_ltp()
                try:
                    logger.info(f"OrderMonitor: Fetching LTP directly for symbol={strike_symbol}, order_id={self.order_id}")
                    ltp_data = await self.data_manager.get_ltp(strike_symbol)
                    if ltp_data and isinstance(ltp_data, dict):
                        ltp = float(ltp_data.get('ltp', 0))
                        logger.info(f"OrderMonitor: Successfully fetched direct LTP for price check: order_id={self.order_id}, symbol={strike_symbol}, LTP={ltp}")
                    else:
                        logger.warning(f"OrderMonitor: Invalid LTP data for symbol={strike_symbol}, order_id={self.order_id}: {ltp_data}")
                        return
                except Exception as e:
                    logger.error(f"OrderMonitor: Error fetching direct LTP for symbol={strike_symbol}, order_id={self.order_id}: {e}")
                    return
                    
            logger.info(f"OrderMonitor: 🔍 PRICE CHECK - order_id={self.order_id}, symbol={strike_symbol}, LTP={ltp}, target={target_price}, SL={stop_loss}, side={side}")
            
            # Check exit conditions based on strategy and side
            should_exit = False
            exit_reason = None
            exit_status = None
            
            if side == 'BUY':  # Long position
                logger.debug(f"OrderMonitor: Checking BUY position exit conditions for order_id={self.order_id}")
                # ltp = 250.0  # Mocked LTP for testing
                # Target hit: LTP >= target_price
                if target_price is not None and ltp >= float(target_price):
                    should_exit = True
                    exit_reason = f"Target hit: LTP {ltp} >= Target {target_price}"
                    exit_status = "EXIT_TARGET"
                    logger.info(f"OrderMonitor: 🎯 TARGET HIT - {exit_reason} for order_id={self.order_id}")
                    
                # Stoploss hit: LTP <= stop_loss
                elif stop_loss is not None and ltp <= float(stop_loss):
                    should_exit = True
                    exit_reason = f"Stoploss hit: LTP {ltp} <= SL {stop_loss}"
                    exit_status = "EXIT_STOPLOSS"
                    logger.info(f"OrderMonitor: 🛑 STOP LOSS HIT - {exit_reason} for order_id={self.order_id}")
                else:
                    logger.debug(f"OrderMonitor: No exit condition met for BUY order_id={self.order_id} - LTP={ltp}, target={target_price}, SL={stop_loss}")
                    
            elif side == 'SELL':  # Short position
                logger.debug(f"OrderMonitor: Checking SELL position exit conditions for order_id={self.order_id}")
                
                # Target hit: LTP <= target_price
                if target_price is not None and ltp <= float(target_price):
                    should_exit = True
                    exit_reason = f"Target hit: LTP {ltp} <= Target {target_price}"
                    exit_status = "EXIT_TARGET"
                    logger.info(f"OrderMonitor: 🎯 TARGET HIT - {exit_reason} for order_id={self.order_id}")
                    
                # Stoploss hit: LTP >= stop_loss
                elif stop_loss is not None and ltp >= float(stop_loss):
                    should_exit = True
                    exit_reason = f"Stoploss hit: LTP {ltp} >= SL {stop_loss}"
                    exit_status = "EXIT_STOPLOSS"
                    logger.info(f"OrderMonitor: 🛑 STOP LOSS HIT - {exit_reason} for order_id={self.order_id}")
                else:
                    logger.debug(f"OrderMonitor: No exit condition met for SELL order_id={self.order_id} - LTP={ltp}, target={target_price}, SL={stop_loss}")
            else:
                logger.warning(f"OrderMonitor: Unknown side '{side}' for order_id={self.order_id}")
            
            if should_exit:
                logger.critical(f"OrderMonitor: 🚨 PRICE-BASED EXIT TRIGGERED for order_id={self.order_id}. {exit_reason}")
                
                try:
                    # Call exit_order immediately when price condition is met
                    await self.order_manager.exit_order(
                        parent_order_id=self.order_id,
                        exit_reason=exit_reason,
                        ltp=ltp
                    )
                    
                    # Update order status to PENDING equivalent for consistent processing
                    from algosat.common import constants
                    if exit_status == "EXIT_TARGET":
                        pending_status = f"{constants.TRADE_STATUS_EXIT_TARGET}_PENDING"
                    elif exit_status == "EXIT_STOPLOSS":
                        pending_status = f"{constants.TRADE_STATUS_EXIT_STOPLOSS}_PENDING"
                    else:
                        pending_status = f"{constants.TRADE_STATUS_EXIT_CLOSED}_PENDING"
                        
                    await self.order_manager.update_order_status_in_db(
                        order_id=self.order_id,
                        status=pending_status
                    )
                    
                    logger.critical(f"OrderMonitor: ✅ Price-based exit initiated for order_id={self.order_id}. Status updated to {pending_status}. Price monitor will complete the exit with full broker details.")
                    
                    # Don't stop monitoring yet - let the PENDING exit processing complete the exit
                    # The _check_and_complete_pending_exits method will handle final processing and stop monitoring
                    return
                    
                except Exception as e:
                    logger.error(f"OrderMonitor: ❌ Error initiating price-based exit for order_id={self.order_id}: {e}")
                    # Fallback: stop monitoring to prevent infinite loops
                    self.stop()
                    return
            else:
                logger.debug(f"OrderMonitor: ✅ Price check completed - no exit conditions met for order_id={self.order_id}")
                    
        except Exception as e:
            logger.error(f"OrderMonitor: ❌ Error in price-based exit check for order_id={self.order_id}: {e}", exc_info=True)

    async def _check_and_complete_pending_exits(self, order_row, current_order_status):
        """
        Check for PENDING exit statuses set by signal monitor or price-based exits and complete the exit process.
        This method calculates exit_price, exit_time, PnL and updates the final exit status.
        
        This handles exits from both:
        1. Signal monitor: When evaluate_exit() returns True
        2. Price-based exits: When target_price or stop_loss conditions are met
        
        Args:
            order_row: Order data from database
            current_order_status: Current main order status
        """
        try:
            if not order_row:
                return
                
            order_status = order_row.get('status')
            if not order_status or not order_status.endswith('_PENDING'):
                return  # Not a pending exit status
                
            logger.info(f"OrderMonitor: 🔄 Processing PENDING exit status for order_id={self.order_id}: {order_status}")
            
            # Extract the final exit status by removing _PENDING suffix
            final_exit_status = order_status.replace('_PENDING', '')
            exit_reason = f"Signal monitor triggered: {final_exit_status}"
            # --- Telegram notification for finalized exit ---
            try:
                msg = f"🔴 <b>Order Exited</b>\n<b>Order ID:</b> <code>{self.order_id}</code>\n<b>Reason:</b> <code>{final_exit_status}</code>"
                send_telegram_async(msg)
            except Exception as e:
                logger.error(f"Failed to send Telegram exit notification: {e}")
            
            # Get all broker order details instead of positions for accurate execution data
            logger.info(f"OrderMonitor: 🔍 Fetching broker order details for exit calculation - order_id={self.order_id}")
            all_broker_orders = await self.order_manager.get_all_broker_order_details()
            logger.info(f"OrderMonitor: Retrieved order details from {len(all_broker_orders)} brokers")
            logger.debug(f"OrderMonitor: Broker order details: {all_broker_orders}")
            
            if not all_broker_orders:
                logger.warning(f"OrderMonitor: ⚠️ No broker order details available from get_all_broker_order_details()")
                
            # Get broker executions for this order (ENTRY side to find corresponding exit orders)
            logger.info(f"OrderMonitor: 📊 Fetching ENTRY broker executions for order_id={self.order_id} to match with exit orders")
            from algosat.core.db import AsyncSessionLocal, get_broker_executions_for_order
            async with AsyncSessionLocal() as session:
                entry_broker_db_orders = await get_broker_executions_for_order(session, self.order_id, side='ENTRY')
                logger.info(f"OrderMonitor: Found {len(entry_broker_db_orders)} ENTRY broker executions for order_id={self.order_id}")
                
                # Also get existing EXIT executions to check for exit_broker_order_id
                existing_exit_executions = await get_broker_executions_for_order(session, self.order_id, side='EXIT')
                logger.info(f"OrderMonitor: Found {len(existing_exit_executions)} existing EXIT broker executions for order_id={self.order_id}")
            
            # Calculate exit details from actual broker order details
            logger.info(f"OrderMonitor: 🧮 Starting order-details based exit calculation for {len(entry_broker_db_orders)} ENTRY executions")
            total_exit_value = 0.0
            total_exit_qty = 0.0
            total_pnl = 0.0
            exit_details_available = False
            broker_exit_data = []  # Store individual broker exit details for broker_executions updates
            
            for i, bro in enumerate(entry_broker_db_orders):
                logger.info(f"OrderMonitor: 📋 Processing ENTRY execution {i+1}/{len(entry_broker_db_orders)} for order_id={self.order_id}")
                
                broker_status = bro.get('status', '').upper()
                symbol_val = bro.get('symbol', None) or bro.get('tradingsymbol', None)
                entry_qty = bro.get('executed_quantity', None) or bro.get('quantity', None)
                broker_id = bro.get('broker_id', None)
                entry_broker_order_id = bro.get('broker_order_id', None)
                entry_price = bro.get('execution_price', None)
                product = bro.get('product_type', None) or bro.get('product', None)
                
                logger.info(f"OrderMonitor: ENTRY execution details - broker_id={broker_id}, entry_order_id={entry_broker_order_id}, status={broker_status}, symbol={symbol_val}, entry_qty={entry_qty}, entry_price={entry_price}")
                
                if (broker_status == 'FAILED' or symbol_val is None or entry_qty is None or entry_qty == 0 or entry_price is None):
                    logger.warning(f"OrderMonitor: ⏸️ Skipping ENTRY execution - broker_id={broker_id}, reason: status={broker_status}, symbol={symbol_val}, entry_qty={entry_qty}, entry_price={entry_price}")
                    continue
                    
                broker_name = None
                if broker_id is not None:
                    try:
                        broker_name = await self._get_broker_name_with_cache(broker_id)
                        logger.info(f"OrderMonitor: Resolved broker_id={broker_id} to broker_name='{broker_name}'")
                    except Exception as e:
                        logger.error(f"OrderMonitor: Could not get broker name for broker_id={broker_id}: {e}")
                        continue
                else:
                    logger.warning(f"OrderMonitor: ⏸️ Skipping ENTRY execution - broker_id is None")
                    continue
                
                # Step 1: Find exit order ID based on broker type
                exit_broker_order_id = None
                cache_lookup_order_id = self._get_cache_lookup_order_id(entry_broker_order_id, broker_name, product)
                
                if broker_name and broker_name.lower() == "zerodha":
                    # For Zerodha: Check if we have stored exit_broker_order_id in existing EXIT executions
                    logger.info(f"OrderMonitor: 🔍 Looking for Zerodha exit_broker_order_id in existing EXIT executions for entry_order_id={entry_broker_order_id}")
                    for exit_exec in existing_exit_executions:
                        if (exit_exec.get('broker_id') == broker_id and 
                            exit_exec.get('broker_order_id') == entry_broker_order_id and
                            exit_exec.get('exit_broker_order_id')):
                            exit_broker_order_id = exit_exec.get('exit_broker_order_id')
                            logger.info(f"OrderMonitor: ✅ Found stored Zerodha exit_broker_order_id={exit_broker_order_id} for entry_order_id={entry_broker_order_id}")
                            break
                    
                    if not exit_broker_order_id:
                        logger.warning(f"OrderMonitor: ⚠️ No stored exit_broker_order_id found for Zerodha entry_order_id={entry_broker_order_id}")
                        
                        # Alternative: Search Zerodha order details for exit order (fallback)
                        logger.info(f"OrderMonitor: 🔍 Searching Zerodha order details as fallback for exit order matching entry_order_id={entry_broker_order_id}")
                        zerodha_orders = all_broker_orders.get('zerodha', [])
                        
                        # Use order_row['created_at'] (UTC) for entry time
                        entry_order_time = order_row.get('created_at')
                        for order in zerodha_orders:
                            order_status = order.get('status', '').upper()
                            order_symbol = order.get('tradingsymbol', '')
                            order_side = order.get('transaction_type', '').upper()
                            order_product = order.get('product', '')
                            order_id = order.get('order_id', '')
                            # Use execution_time from broker order info (IST, naive)
                            order_time = order.get('execution_time')
                            # Look for exit orders (opposite side) with matching symbol and product
                            entry_side = bro.get('action', '').upper()
                            expected_exit_side = 'SELL' if entry_side == 'BUY' else 'BUY'
                            # Match criteria for exit orders
                            symbol_match = order_symbol == symbol_val
                            side_match = order_side == expected_exit_side
                            product_match = order_product == product
                            status_valid = order_status in ['COMPLETE', 'FILLED']  # Only process completed orders
                            different_order = order_id != entry_broker_order_id  # Different from entry order
                            time_valid = True
                            if entry_order_time and order_time:
                                try:
                                    from dateutil.parser import parse as parse_dt
                                    from datetime import timezone as dt_timezone
                                    entry_dt = parse_dt(str(entry_order_time))
                                    order_dt = parse_dt(str(order_time))
                                    # Use localize_to_ist to ensure order_dt is IST aware, entry_dt is UTC aware
                                    order_dt_ist = localize_to_ist(order_dt)
                                    # entry_dt is UTC (from DB), order_dt_ist is IST (from broker)
                                    # Convert order_dt_ist to UTC for comparison
                                    order_dt_utc = order_dt_ist.astimezone(dt_timezone.utc)
                                    if entry_dt.tzinfo is None:
                                        entry_dt = entry_dt.replace(tzinfo=dt_timezone.utc)
                                    time_valid = order_dt_utc >= entry_dt
                                except Exception as e:
                                    logger.warning(f"OrderMonitor: Could not parse/convert order times for time check: {e}")
                            logger.debug(f"OrderMonitor: Zerodha fallback exit order check - id={order_id}, symbol_match={symbol_match}, side_match={side_match}, product_match={product_match}, status_valid={status_valid}({order_status}), different_order={different_order}, time_valid={time_valid}")
                            if (symbol_match and side_match and product_match and status_valid and different_order and time_valid):
                                exit_broker_order_id = order_id
                                logger.info(f"OrderMonitor: ✅ Found Zerodha exit order via fallback: id={exit_broker_order_id}, symbol={order_symbol}, side={order_side}, status={order_status}")
                                break
                        
                elif broker_name and broker_name.lower() == "fyers":
                    # For Fyers: Optimized BO exit order matching
                    logger.info(f"OrderMonitor: 🔍 Searching Fyers order details for exit order matching entry_order_id={entry_broker_order_id}")
                    fyers_orders = all_broker_orders.get('fyers', [])
                    product_type = bro.get('product_type', '') or bro.get('product', '')
                    if str(product_type).upper() == 'BO' and entry_broker_order_id and '-BO-1' in entry_broker_order_id:
                        # Extract base order id (trim -BO-1)
                        base_order_id = entry_broker_order_id.replace('-BO-1', '')
                        # Find BO-2 and BO-3 legs
                        bo_legs = [o for o in fyers_orders if o.get('id', '').startswith(base_order_id) and o.get('id', '') != entry_broker_order_id and '-BO-' in o.get('id', '')]
                        logger.info(f"OrderMonitor: Fyers BO detected. Base order id: {base_order_id}. Found {len(bo_legs)} BO legs.")
                        # Of the two legs, pick the one with status FILLED (status==2)
                        filled_leg = None
                        for leg in bo_legs:
                            if leg.get('status') == 2:
                                filled_leg = leg
                                break
                        if filled_leg:
                            exit_broker_order_id = filled_leg.get('id')
                            logger.info(f"OrderMonitor: ✅ Optimized Fyers BO exit order: id={exit_broker_order_id}, status=FILLED")
                        else:
                            logger.warning(f"OrderMonitor: ⚠️ No FILLED BO leg found for base_order_id={base_order_id}")
                    else:
                        # Fallback to generic logic for non-BO
                        # Use order_row['created_at'] (UTC) for entry time
                        entry_order_time = order_row.get('created_at')
                        for order in fyers_orders:
                            order_status_code = order.get('status')
                            order_symbol = order.get('symbol', '')
                            order_side = order.get('side')
                            order_product = order.get('productType', '')
                            order_id = order.get('id', '')
                            # Use execution_time from broker order info (IST, naive)
                            order_time = order.get('execution_time')
                            if order_status_code == 2:
                                order_status = 'FILLED'
                            elif order_status_code == 1:
                                order_status = 'CANCELLED'
                            else:
                                order_status = f'STATUS_{order_status_code}'
                            entry_side = bro.get('action', '').upper()
                            if entry_side == 'BUY':
                                expected_exit_side_code = -1
                            elif entry_side == 'SELL':
                                expected_exit_side_code = 1
                            else:
                                logger.warning(f"OrderMonitor: Unknown entry side '{entry_side}' for Fyers exit matching")
                                continue
                            symbol_match = order_symbol == symbol_val
                            side_match = order_side == expected_exit_side_code
                            product_match = order_product == product
                            status_valid = order_status in ['FILLED', 'COMPLETE']
                            different_order = order_id != entry_broker_order_id
                            is_bo_order = '-BO-' in order_id
                            bo_status_valid = True
                            if is_bo_order:
                                bo_status_valid = order_status_code == 2
                            time_valid = True
                            if entry_order_time and order_time:
                                try:
                                    from dateutil.parser import parse as parse_dt
                                    from datetime import timezone as dt_timezone
                                    entry_dt = parse_dt(str(entry_order_time))
                                    order_dt = parse_dt(str(order_time))
                                    # Use localize_to_ist to ensure order_dt is IST aware, entry_dt is UTC aware
                                    order_dt_ist = localize_to_ist(order_dt)
                                    # entry_dt is UTC (from DB), order_dt_ist is IST (from broker)
                                    # Convert order_dt_ist to UTC for comparison
                                    order_dt_utc = order_dt_ist.astimezone(dt_timezone.utc)
                                    if entry_dt.tzinfo is None:
                                        entry_dt = entry_dt.replace(tzinfo=dt_timezone.utc)
                                    time_valid = order_dt_utc >= entry_dt
                                except Exception as e:
                                    logger.warning(f"OrderMonitor: Could not parse/convert order times for time check: {e}")
                            logger.debug(f"OrderMonitor: Fyers exit order check - id={order_id}, symbol_match={symbol_match}, side_match={side_match}({order_side}=={expected_exit_side_code}), product_match={product_match}, status_valid={status_valid}({order_status}), different_order={different_order}, bo_status_valid={bo_status_valid}, time_valid={time_valid}")
                            if (symbol_match and side_match and product_match and status_valid and different_order and bo_status_valid and time_valid):
                                exit_broker_order_id = order_id
                                logger.info(f"OrderMonitor: ✅ Found Fyers exit order: id={exit_broker_order_id}, symbol={order_symbol}, side_code={order_side}, status={order_status}, status_code={order_status_code}")
                                break
                        if not exit_broker_order_id:
                            logger.warning(f"OrderMonitor: ⚠️ No matching Fyers exit order found for entry_order_id={entry_broker_order_id}, symbol={symbol_val}, expected_exit_side_code={expected_exit_side_code if 'expected_exit_side_code' in locals() else 'N/A'}")
                
                else:
                    logger.warning(f"OrderMonitor: Unsupported broker for exit order ID detection: '{broker_name}'")
                    continue
                
                # Step 2: If we found exit order ID, get execution details from broker order details
                if exit_broker_order_id:
                    logger.info(f"OrderMonitor: 🎯 Found exit_broker_order_id={exit_broker_order_id}, fetching execution details from broker orders")
                    
                    # Find exit order details in broker orders
                    exit_order_details = None
                    broker_orders = all_broker_orders.get(broker_name.lower(), [])
                    
                    for order in broker_orders:
                        if order.get('id') == exit_broker_order_id or order.get('order_id') == exit_broker_order_id:
                            exit_order_details = order
                            logger.info(f"OrderMonitor: ✅ Found exit order details: {exit_order_details}")
                            break
                    
                    if exit_order_details:
                        exit_details_available = True
                        
                        # Extract execution data based on broker type
                        if broker_name.lower() == "zerodha":
                            # Zerodha fields: average_price, filled_quantity
                            exit_price = exit_order_details.get('average_price', 0) or exit_order_details.get('price', 0)
                            exit_qty = exit_order_details.get('filled_quantity', 0) or exit_order_details.get('quantity', 0)
                            exit_status = exit_order_details.get('status', 'UNKNOWN')
                            
                        elif broker_name.lower() == "fyers":
                            # Fyers fields: tradedPrice, filledQty  
                            exit_price = exit_order_details.get('tradedPrice', 0) or exit_order_details.get('limitPrice', 0)
                            exit_qty = exit_order_details.get('filledQty', 0) or exit_order_details.get('qty', 0)
                            exit_status = exit_order_details.get('status', 'UNKNOWN')
                            
                        else:
                            logger.warning(f"OrderMonitor: Unknown broker type for execution data extraction: {broker_name}")
                            continue
                        
                        # Validate execution data
                        if exit_price == 0 or exit_qty == 0:
                            logger.warning(f"OrderMonitor: ⚠️ Invalid exit execution data - exit_price={exit_price}, exit_qty={exit_qty} for exit_order_id={exit_broker_order_id}")
                            continue
                        
                        # Calculate PnL: (exit_price - entry_price) * quantity
                        # For SELL positions, PnL is (entry_price - exit_price) * quantity
                        entry_side = bro.get('action', '').upper()
                        if entry_side == 'BUY':
                            # Long position: profit when exit_price > entry_price
                            broker_pnl = (float(exit_price) - float(entry_price)) * int(exit_qty)
                        elif entry_side == 'SELL':
                            # Short position: profit when exit_price < entry_price  
                            broker_pnl = (float(entry_price) - float(exit_price)) * int(exit_qty)
                        else:
                            logger.warning(f"OrderMonitor: Unknown entry side '{entry_side}' for PnL calculation")
                            broker_pnl = 0
                        
                        logger.info(f"OrderMonitor: 💰 PnL calculation - entry_side={entry_side}, entry_price={entry_price}, exit_price={exit_price}, exit_qty={exit_qty}, broker_pnl={broker_pnl}")
                        
                        # Calculate proper exit action based on entry side
                        if entry_side == 'BUY':
                            exit_action = 'SELL'
                        elif entry_side == 'SELL':
                            exit_action = 'BUY'
                        else:
                            exit_action = 'EXIT'  # Fallback for unknown entry side
                        
                        # Store individual broker exit data for broker_executions table
                        exit_data = {
                            'broker_id': broker_id,
                            'broker_order_id': entry_broker_order_id,
                            'exit_broker_order_id': exit_broker_order_id,
                            'exit_price': float(exit_price),
                            'executed_quantity': int(exit_qty),
                            'product_type': product,
                            'symbol': symbol_val,
                            'broker_pnl': broker_pnl,
                            'exit_status': exit_status,
                            'exit_action': exit_action  # Add proper exit action
                        }
                        broker_exit_data.append(exit_data)
                        logger.info(f"OrderMonitor: Added exit data: {exit_data}")
                        
                        # Accumulate for VWAP calculation
                        total_exit_value += float(exit_price) * int(exit_qty)
                        total_exit_qty += int(exit_qty)
                        total_pnl += broker_pnl
                        
                        logger.info(f"OrderMonitor: Exit details for {broker_name}: exit_order_id={exit_broker_order_id}, exit_price={exit_price}, exit_qty={exit_qty}, pnl={broker_pnl}")
                        logger.info(f"OrderMonitor: Running totals - exit_value={total_exit_value}, exit_qty={total_exit_qty}, pnl={total_pnl}")
                        
                    else:
                        logger.warning(f"OrderMonitor: ❌ Exit order details not found in broker orders for exit_broker_order_id={exit_broker_order_id}")
                        
                else:
                    logger.warning(f"OrderMonitor: ❌ No exit order ID found for entry_order_id={entry_broker_order_id}, broker={broker_name}")
                    # Continue processing other entries even if one fails
            
            logger.info(f"OrderMonitor: 📊 Exit calculation summary for order_id={self.order_id}:")
            logger.info(f"  - exit_details_available: {exit_details_available}")
            logger.info(f"  - total_exit_value: {total_exit_value}")
            logger.info(f"  - total_exit_qty: {total_exit_qty}")
            logger.info(f"  - total_pnl: {total_pnl}")
            logger.info(f"  - broker_exit_data count: {len(broker_exit_data)}")
            
            # Calculate final exit price (VWAP) and complete the exit
            final_exit_price = total_exit_value / total_exit_qty if total_exit_qty > 0 else None
            logger.info(f"OrderMonitor: Calculated final_exit_price (VWAP): {final_exit_price}")
            
            # ENHANCED LOGIC: Always complete the exit, even if no exit details are available
            # This prevents orders from staying in PENDING state indefinitely
            
            if exit_details_available and len(broker_exit_data) > 0:
                logger.info(f"OrderMonitor: ✅ Completing PENDING exit for order_id={self.order_id}")
                logger.info(f"    Final Exit Price (VWAP): {final_exit_price}")
                logger.info(f"    Total PnL: {total_pnl}")
                logger.info(f"    Final Status: {final_exit_status}")
                
                # Update exit details in database
                from datetime import datetime, timezone
                from algosat.core.db import update_rows_in_table
                from algosat.core.dbschema import orders
                
                exit_time = datetime.now(timezone.utc)
                update_fields = {
                    "status": final_exit_status,
                    "exit_time": exit_time,
                    "pnl": total_pnl
                }
                
                if final_exit_price is not None:
                    update_fields["exit_price"] = round(final_exit_price, 2)
                
                async with AsyncSessionLocal() as session:
                    await update_rows_in_table(
                        target_table=orders,
                        condition=orders.c.id == self.order_id,
                        new_values=update_fields
                    )
                    await self._clear_order_cache()  # Clear cache after order status update
                    
                    # Insert EXIT broker_executions entries directly with calculated exit details
                    logger.info(f"OrderMonitor: Checking and inserting {len(broker_exit_data)} EXIT broker_executions with calculated details for order_id={self.order_id}")
                    
                    for exit_data in broker_exit_data:
                        try:
                            # Check if EXIT entry already exists for this broker_order_id
                            from algosat.core.db import get_broker_executions_for_order
                            existing_exits = await get_broker_executions_for_order(
                                session, 
                                self.order_id, 
                                side='EXIT',
                                
                            )
                            
                            # Filter to check if this specific broker_order_id already has an EXIT entry
                            existing_exit = None
                            for exit_entry in existing_exits:
                                if exit_entry.get('broker_order_id') == exit_data['broker_order_id']:
                                    existing_exit = exit_entry
                                    break
                            
                            if existing_exit:
                                logger.info(f"OrderMonitor: EXIT broker_execution already exists for broker_id={exit_data['broker_id']}, broker_order_id={exit_data['broker_order_id']}. Updating execution_price and execution_time.")
                                
                                # Update existing EXIT entry with calculated execution details
                                from algosat.core.db import update_rows_in_table
                                from algosat.core.dbschema import broker_executions
                                
                                await update_rows_in_table(
                                    target_table=broker_executions,
                                    condition=(
                                        (broker_executions.c.parent_order_id == self.order_id) &
                                        (broker_executions.c.broker_id == exit_data['broker_id']) &
                                        (broker_executions.c.broker_order_id == exit_data['broker_order_id']) &
                                        (broker_executions.c.side == 'EXIT')
                                    ),
                                    new_values={
                                        "execution_price": round(exit_data['exit_price'], 2),
                                        "exit_broker_order_id": exit_data.get('exit_broker_order_id'),
                                        "execution_time": exit_time,
                                        "notes": f"PENDING exit updated with order details. PnL: {exit_data['broker_pnl']}",
                                        "status": 'FILLED'  # Ensure status is FILLED since we have order details
                                    }
                                )
                                await self._clear_order_cache()  # Clear cache after broker execution update
                                logger.info(f"OrderMonitor: Updated existing EXIT broker_execution for broker_id={exit_data['broker_id']}, new_price={exit_data['exit_price']}")
                                continue
                            
                            # No existing EXIT entry found, proceed with insertion
                            await self.order_manager._insert_exit_broker_execution(
                                session,
                                parent_order_id=self.order_id,
                                broker_id=exit_data['broker_id'],
                                broker_order_id=exit_data['broker_order_id'],
                                side='EXIT',
                                status='FILLED',  # Mark as FILLED since we calculated from order details
                                executed_quantity=exit_data['executed_quantity'],
                                execution_price=round(exit_data['exit_price'], 2),
                                product_type=exit_data['product_type'],
                                order_type='MARKET',  # Assume MARKET for exits
                                order_messages=f"PENDING exit completion: {final_exit_status}",
                                symbol=exit_data['symbol'],
                                execution_time=exit_time,
                                notes=f"PENDING exit via order_monitor with order details. PnL: {exit_data['broker_pnl']}",
                                action=exit_data['exit_action'],  # Use calculated exit action instead of 'EXIT'
                                exit_reason=exit_reason,
                                exit_broker_order_id=exit_data.get('exit_broker_order_id')
                            )
                            logger.info(f"OrderMonitor: Inserted new EXIT broker_execution for broker_id={exit_data['broker_id']}, price={exit_data['exit_price']}")
                        except Exception as e:
                            logger.error(f"OrderMonitor: Error inserting EXIT broker_execution for broker_id={exit_data['broker_id']}: {e}")
                
                logger.critical(f"OrderMonitor: ✅ Successfully completed PENDING exit for order_id={self.order_id}. Status: {final_exit_status}, Exit Price: {final_exit_price}, PnL: {total_pnl}")
                
                # Stop monitoring this order
                self.stop()
                return
                
            else:
                # ENHANCED FALLBACK: Always close the order even if no exit details are available
                # This prevents orders from staying in PENDING state indefinitely
                logger.warning(f"OrderMonitor: ⚠️ No exit details available from broker order details for order_id={self.order_id}. Forcing order closure with fallback logic.")
                logger.warning(f"OrderMonitor: Fallback reasons analysis:")
                logger.warning(f"  - Total ENTRY executions processed: {len(entry_broker_db_orders)}")
                logger.warning(f"  - exit_details_available: {exit_details_available}")
                logger.warning(f"  - all_broker_orders available: {len(all_broker_orders)} brokers")
                logger.warning(f"  - broker_exit_data collected: {len(broker_exit_data)}")
                
                if not entry_broker_db_orders:
                    logger.error(f"OrderMonitor: No ENTRY executions found for order_id={self.order_id} - this should not happen for PENDING exits")
                
                if not all_broker_orders:
                    logger.error(f"OrderMonitor: No broker order details available - check broker API connectivity")
                
                # FORCE CLOSURE: Update order status regardless of exit details availability
                logger.critical(f"OrderMonitor: 🔒 FORCING ORDER CLOSURE for order_id={self.order_id} to prevent infinite PENDING state")
                
                # Calculate basic exit details for fallback - PRESERVE existing PnL
                from datetime import datetime, timezone
                exit_time = datetime.now(timezone.utc)
                
                # Read existing PnL from database to preserve it
                existing_pnl = order_row.get('pnl') if order_row else None
                fallback_pnl = total_pnl if total_pnl != 0 else existing_pnl  # Use calculated PnL if available, otherwise preserve existing
                fallback_exit_price = final_exit_price  # May be None, that's okay
                
                logger.info(f"OrderMonitor: Fallback PnL handling - calculated_pnl={total_pnl}, existing_pnl={existing_pnl}, fallback_pnl={fallback_pnl}")
                
                # Update orders table with fallback exit details
                logger.info(f"OrderMonitor: Updating order status to {final_exit_status} for order_id={self.order_id} (FALLBACK)")
                from algosat.core.db import update_rows_in_table
                from algosat.core.dbschema import orders
                
                fallback_update_fields = {
                    "status": final_exit_status,
                    "exit_time": exit_time
                }
                
                # Only update PnL if we have a meaningful value (calculated or existing)
                if fallback_pnl is not None:
                    fallback_update_fields["pnl"] = fallback_pnl
                    logger.info(f"OrderMonitor: Including PnL in fallback update: {fallback_pnl}")
                else:
                    logger.warning(f"OrderMonitor: No PnL value available (calculated or existing) - leaving PnL field unchanged")
                
                if fallback_exit_price is not None:
                    fallback_update_fields["exit_price"] = round(fallback_exit_price, 2)
                
                async with AsyncSessionLocal() as session:
                    await update_rows_in_table(
                        target_table=orders,
                        condition=orders.c.id == self.order_id,
                        new_values=fallback_update_fields
                    )
                    await self._clear_order_cache()  # Clear cache after order status update
                    
                    logger.critical(f"OrderMonitor: ✅ ORDER FORCED CLOSED - order_id={self.order_id}, status={final_exit_status}, pnl={fallback_pnl} (existing: {existing_pnl})")
                
                # Insert basic EXIT broker_executions entries for audit trail
                logger.info(f"OrderMonitor: Creating fallback EXIT broker_executions entries for audit trail - order_id={self.order_id}")
                
                async with AsyncSessionLocal() as session:
                    for bro in entry_broker_db_orders:
                        broker_status = bro.get('status', '').upper()
                        if broker_status == 'FAILED':
                            logger.debug(f"OrderMonitor: Skipping FAILED broker execution for fallback EXIT creation")
                            continue
                            
                        try:
                            # Check if EXIT entry already exists for this broker_order_id
                            from algosat.core.db import get_broker_executions_for_order
                            existing_exits = await get_broker_executions_for_order(
                                session, 
                                self.order_id, 
                                side='EXIT'
                            )
                            
                            # Filter to check if this specific broker_order_id already has an EXIT entry
                            existing_exit = None
                            for exit_entry in existing_exits:
                                if (exit_entry.get('broker_order_id') == bro.get('broker_order_id') and 
                                    exit_entry.get('broker_id') == bro.get('broker_id')):
                                    existing_exit = exit_entry
                                    break
                            
                            if existing_exit:
                                logger.info(f"OrderMonitor: EXIT broker_execution already exists for broker_id={bro.get('broker_id')}, broker_order_id={bro.get('broker_order_id')}. Updating for fallback closure.")
                                
                                # Update existing EXIT entry with fallback details
                                from algosat.core.db import update_rows_in_table
                                from algosat.core.dbschema import broker_executions
                                
                                await update_rows_in_table(
                                    target_table=broker_executions,
                                    condition=(
                                        (broker_executions.c.parent_order_id == self.order_id) &
                                        (broker_executions.c.broker_id == bro.get('broker_id')) &
                                        (broker_executions.c.broker_order_id == bro.get('broker_order_id')) &
                                        (broker_executions.c.side == 'EXIT')
                                    ),
                                    new_values={
                                        "execution_time": exit_time,
                                        "notes": f"FALLBACK CLOSURE - No exit order details available. Status: {final_exit_status}",
                                        "status": 'CLOSED'  # Use CLOSED status for fallback
                                    }
                                )
                                await self._clear_order_cache()
                                logger.info(f"OrderMonitor: Updated existing EXIT broker_execution (fallback closure) for broker_id={bro.get('broker_id')}")
                                continue
                            
                            # Calculate proper exit action for fallback
                            entry_action = bro.get('action', '').upper()
                            if entry_action == 'BUY':
                                fallback_exit_action = 'SELL'
                            elif entry_action == 'SELL':
                                fallback_exit_action = 'BUY'
                            else:
                                fallback_exit_action = 'EXIT'  # Fallback for unknown entry action
                            
                            # No existing EXIT entry found, create new fallback entry
                            # Ensure executed_quantity is never None for database NOT NULL constraint
                            fallback_quantity = bro.get('executed_quantity') or bro.get('quantity') or 0
                            
                            await self.order_manager._insert_exit_broker_execution(
                                session,
                                parent_order_id=self.order_id,
                                broker_id=bro.get('broker_id'),
                                broker_order_id=bro.get('broker_order_id'),
                                side='EXIT',
                                status='CLOSED',  # Use CLOSED since we don't have detailed execution info
                                executed_quantity=fallback_quantity,
                                execution_price=bro.get('execution_price', 0),  # Use entry price as fallback
                                product_type=bro.get('product_type'),
                                order_type='MARKET',
                                order_messages=f"FALLBACK CLOSURE: {final_exit_status}",
                                symbol=bro.get('symbol') or bro.get('tradingsymbol'),
                                execution_time=exit_time,
                                notes=f"FALLBACK CLOSURE - No exit order details available. Forced closure to prevent infinite PENDING state.",
                                action=fallback_exit_action,  # Use calculated exit action
                                exit_reason=f"Fallback closure: {exit_reason}",
                                exit_broker_order_id=None  # No exit order ID available
                            )
                            logger.info(f"OrderMonitor: Inserted fallback EXIT broker_execution for broker_id={bro.get('broker_id')}")
                            
                        except Exception as e:
                            logger.error(f"OrderMonitor: Error creating fallback EXIT broker_execution for broker_id={bro.get('broker_id')}: {e}")
                            # Continue with other brokers even if one fails
                
                logger.critical(f"OrderMonitor: ⚠️ FALLBACK CLOSURE COMPLETED for order_id={self.order_id}. Status: {final_exit_status}, PnL: {fallback_pnl} (preserved existing: {existing_pnl})")
                
                # Stop monitoring this order - ALWAYS stop regardless of success/failure
                self.stop()
                return
            
            # Clear order strategy cache since order status has changed
            if self.order_id in self._order_strategy_cache:
                del self._order_strategy_cache[self.order_id]
                
        except Exception as e:
            logger.error(f"OrderMonitor: ❌ Error completing PENDING exit for order_id={self.order_id}: {e}", exc_info=True)
            
            # ULTIMATE FALLBACK: Force order closure even in case of complete failure
            # This ensures orders are NEVER stuck in PENDING state
            logger.critical(f"OrderMonitor: 🚨 ULTIMATE FALLBACK - Forcing order closure due to processing error for order_id={self.order_id}")
            
            try:
                final_exit_status = order_row.get('status', '').replace('_PENDING', '') if order_row else 'EXIT_CLOSED'
                
                # FORCE UPDATE: Always update status regardless of previous errors
                from datetime import datetime, timezone
                from algosat.core.db import update_rows_in_table
                from algosat.core.dbschema import orders
                
                emergency_exit_time = datetime.now(timezone.utc)
                
                # PRESERVE existing PnL during emergency closure
                existing_pnl = order_row.get('pnl') if order_row else None
                logger.info(f"OrderMonitor: Emergency closure PnL handling - existing_pnl={existing_pnl}")
                
                emergency_update_fields = {
                    "status": final_exit_status,
                    "exit_time": emergency_exit_time,
                    "notes": f"EMERGENCY CLOSURE - Processing failed with error: {str(e)[:200]}"
                }
                
                # Only update PnL if we don't have an existing value (preserve existing if available)
                if existing_pnl is None:
                    emergency_update_fields["pnl"] = 0.0  # Only set to 0 if no existing value
                    logger.warning(f"OrderMonitor: No existing PnL found - setting to 0.0 for emergency closure")
                else:
                    logger.info(f"OrderMonitor: Preserving existing PnL value: {existing_pnl}")
                    # Don't include PnL in update fields to leave it unchanged
                
                async with AsyncSessionLocal() as session:
                    await update_rows_in_table(
                        target_table=orders,
                        condition=orders.c.id == self.order_id,
                        new_values=emergency_update_fields
                    )
                    await self._clear_order_cache()
                
                logger.critical(f"OrderMonitor: ✅ EMERGENCY ORDER CLOSURE SUCCESSFUL for order_id={self.order_id}, status={final_exit_status}")
                
                # Try to create emergency EXIT broker_executions for audit trail (best effort)
                try:
                    from algosat.core.db import get_broker_executions_for_order
                    async with AsyncSessionLocal() as session:
                        entry_broker_db_orders = await get_broker_executions_for_order(session, self.order_id, side='ENTRY')
                        
                        logger.info(f"OrderMonitor: Creating emergency EXIT broker_executions for {len(entry_broker_db_orders)} ENTRY executions")
                        
                        for bro in entry_broker_db_orders:
                            broker_status = bro.get('status', '').upper()
                            if broker_status == 'FAILED':
                                continue
                                
                            try:
                                # Check if EXIT entry already exists
                                existing_exits = await get_broker_executions_for_order(session, self.order_id, side='EXIT')
                                existing_exit = None
                                for exit_entry in existing_exits:
                                    if (exit_entry.get('broker_order_id') == bro.get('broker_order_id') and 
                                        exit_entry.get('broker_id') == bro.get('broker_id')):
                                        existing_exit = exit_entry
                                        break
                                
                                if existing_exit:
                                    # Update existing EXIT with emergency closure
                                    from algosat.core.dbschema import broker_executions
                                    await update_rows_in_table(
                                        target_table=broker_executions,
                                        condition=(
                                            (broker_executions.c.parent_order_id == self.order_id) &
                                            (broker_executions.c.broker_id == bro.get('broker_id')) &
                                            (broker_executions.c.broker_order_id == bro.get('broker_order_id')) &
                                            (broker_executions.c.side == 'EXIT')
                                        ),
                                        new_values={
                                            "execution_time": emergency_exit_time,
                                            "notes": f"EMERGENCY CLOSURE - Error in exit processing: {str(e)[:100]}",
                                            "status": 'CLOSED'
                                        }
                                    )
                                    logger.debug(f"OrderMonitor: Updated EXIT broker_execution (emergency) for broker_id={bro.get('broker_id')}")
                                    continue
                                
                                # Calculate proper exit action for emergency closure
                                entry_action = bro.get('action', '').upper()
                                if entry_action == 'BUY':
                                    emergency_exit_action = 'SELL'
                                elif entry_action == 'SELL':
                                    emergency_exit_action = 'BUY'
                                else:
                                    emergency_exit_action = 'EXIT'  # Fallback
                                
                                # Create new emergency EXIT entry
                                # Ensure executed_quantity is never None for database NOT NULL constraint
                                emergency_quantity = bro.get('executed_quantity') or bro.get('quantity') or 0
                                
                                await self.order_manager._insert_exit_broker_execution(
                                    session,
                                    parent_order_id=self.order_id,
                                    broker_id=bro.get('broker_id'),
                                    broker_order_id=bro.get('broker_order_id'),
                                    side='EXIT',
                                    status='CLOSED',
                                    executed_quantity=emergency_quantity,
                                    execution_price=bro.get('execution_price', 0),
                                    product_type=bro.get('product_type'),
                                    order_type='MARKET',
                                    order_messages=f"EMERGENCY CLOSURE: {final_exit_status}",
                                    symbol=bro.get('symbol') or bro.get('tradingsymbol'),
                                    execution_time=emergency_exit_time,
                                    notes=f"EMERGENCY CLOSURE - Error in exit processing. Forced closure to prevent infinite PENDING.",
                                    action=emergency_exit_action,  # Use calculated exit action
                                    exit_reason=f"Emergency closure due to processing error",
                                    exit_broker_order_id=None
                                )
                                logger.debug(f"OrderMonitor: Inserted emergency EXIT broker_execution for broker_id={bro.get('broker_id')}")
                                
                            except Exception as inner_e:
                                logger.error(f"OrderMonitor: Error creating emergency EXIT broker_execution for broker_id={bro.get('broker_id')}: {inner_e}")
                                # Continue with other brokers
                                
                except Exception as audit_e:
                    logger.error(f"OrderMonitor: Error creating emergency audit trail: {audit_e}")
                    # Don't fail the emergency closure for audit issues
                
                logger.critical(f"OrderMonitor: 🔒 ULTIMATE FALLBACK COMPLETED for order_id={self.order_id}")
                
            except Exception as e2:
                logger.critical(f"OrderMonitor: ❌ ULTIMATE FALLBACK FAILED for order_id={self.order_id}: {e2}", exc_info=True)
                logger.critical(f"OrderMonitor: 🚨 ORDER MAY BE STUCK IN PENDING STATE - MANUAL INTERVENTION REQUIRED for order_id={self.order_id}")
            
            finally:
                # ALWAYS stop monitoring regardless of success/failure to prevent infinite loops
                logger.critical(f"OrderMonitor: 🛑 STOPPING MONITOR for order_id={self.order_id} (emergency or error condition)")
                self.stop()


    def _get_cache_lookup_order_id(self, broker_order_id, broker_name, product_type):
        """
        Helper to determine cache key for broker order id.
        For Fyers: Only BO orders without existing -BO- suffix need -BO-1 appended.
        """
        if not broker_order_id or not broker_name:
            return broker_order_id
            
        # Only apply to Fyers broker
        if broker_name.lower() != 'fyers':
            return broker_order_id
            
        # Only apply to BO product type
        if not product_type or product_type.lower() != 'bo':
            return broker_order_id
            
        # Don't append if order_id already has -BO- suffix
        if '-BO-' in str(broker_order_id):
            return broker_order_id
            
        # Append -BO-1 suffix for Fyers BO orders without existing suffix
        return f"{broker_order_id}-BO-1"

    async def _get_broker_name_with_cache(self, broker_id: int) -> str:
        """
        Get broker name by ID with long-lived caching (24 hours).
        Broker names rarely change, so we can cache them for a long time.
        """
        if broker_id is None:
            return None
            
        now = time.time()
        cache_duration = 24 * 60 * 60  # 24 hours in seconds
        
        # Check if we have a cached value that's still valid
        if (broker_id in self._broker_name_cache and 
            broker_id in self._broker_name_cache_time and
            (now - self._broker_name_cache_time[broker_id]) < cache_duration):
            return self._broker_name_cache[broker_id]
        
        # Cache miss or expired - fetch from database
        try:
            broker_name = await self.data_manager.get_broker_name_by_id(broker_id)
            # Cache the result
            self._broker_name_cache[broker_id] = broker_name
            self._broker_name_cache_time[broker_id] = now
            return broker_name
        except Exception as e:
            logger.error(f"OrderMonitor: Error fetching broker name for broker_id={broker_id}: {e}")
            # Return cached value even if expired, as fallback
            return self._broker_name_cache.get(broker_id, None)

    def _clear_broker_name_cache(self, broker_id: int = None):
        """
        Clear broker name cache. If broker_id is specified, clear only that entry.
        Otherwise, clear entire cache.
        """
        if broker_id is not None:
            self._broker_name_cache.pop(broker_id, None)
            self._broker_name_cache_time.pop(broker_id, None)
        else:
            self._broker_name_cache.clear()
            self._broker_name_cache_time.clear()

    async def _update_current_price_in_db(self, strike_symbol: str, current_price: float):
        """
        Update current_price and price_last_updated fields in orders table.
        
        Args:
            strike_symbol: The strike symbol to update price for
            current_price: The current LTP price
        """
        try:
            from datetime import datetime, timezone
            from algosat.core.db import AsyncSessionLocal, update_rows_in_table
            from algosat.core.dbschema import orders
            
            price_last_updated = datetime.now(timezone.utc)
            
            async with AsyncSessionLocal() as session:
                # Update orders table with current price
                await update_rows_in_table(
                    target_table=orders,
                    condition=(orders.c.id == self.order_id) & (orders.c.strike_symbol == strike_symbol),
                    new_values={
                        "current_price": current_price,
                        "price_last_updated": price_last_updated
                    }
                )
                await self._clear_order_cache()  # Clear cache after order price update
                
            logger.debug(f"OrderMonitor: Updated current_price={current_price} for order_id={self.order_id}, symbol={strike_symbol}")
            
        except Exception as e:
            logger.error(f"OrderMonitor: Error updating current_price for order_id={self.order_id}, symbol={strike_symbol}: {e}")

    async def _update_current_price_for_open_order(self, order_row):
        """
        Fetch LTP directly for an open order and update the current_price in the database.
        
        Args:
            order_row: Order data from database
            
        Returns:
            float: Current LTP if successfully fetched, None otherwise
        """
        try:
            if not order_row:
                return None
                
            strike_symbol = order_row.get('strike_symbol')
            if not strike_symbol:
                logger.warning(f"OrderMonitor: No strike_symbol found for order_id={self.order_id}")
                return None
                
            # Fetch LTP directly using data_manager.get_ltp()
            logger.info(f"OrderMonitor: Fetching current LTP for order_id={self.order_id}, symbol={strike_symbol}")
            ltp_data = await self.data_manager.get_ltp(strike_symbol)
            
            if ltp_data and isinstance(ltp_data, dict):
                # Handle different LTP response formats
                current_ltp = 0.0
                if 'ltp' in ltp_data:
                    # Format: {'ltp': 49.45}
                    current_ltp = float(ltp_data.get('ltp', 0))
                elif strike_symbol in ltp_data:
                    # Format: {'NSE:SYMBOL': 49.45}
                    current_ltp = float(ltp_data.get(strike_symbol, 0))
                else:
                    # Try to get first value if it's a single-item dict
                    values = list(ltp_data.values())
                    if values and len(values) == 1:
                        current_ltp = float(values[0])
                
                logger.debug(f"OrderMonitor: Extracted current_ltp={current_ltp} from ltp_data={ltp_data}")
                
                if current_ltp > 0:
                    # Update current_price in database
                    await self._update_current_price_in_db(strike_symbol, current_ltp)
                    logger.info(f"OrderMonitor: Successfully updated current_price={current_ltp} for order_id={self.order_id}, symbol={strike_symbol}")
                    return current_ltp
                else:
                    logger.warning(f"OrderMonitor: Invalid LTP value ({current_ltp}) for order_id={self.order_id}, symbol={strike_symbol}")
                    return None
            else:
                logger.warning(f"OrderMonitor: Invalid LTP data for order_id={self.order_id}, symbol={strike_symbol}: {ltp_data}")
                return None
                
        except Exception as e:
            logger.error(f"OrderMonitor: Error fetching/updating current price for order_id={self.order_id}: {e}")
            return None

    async def _update_broker_executions_pnl(self, current_ltp: float, entry_broker_db_orders: list):
        """
        Update P&L field for all ENTRY broker executions using current LTP.
        This provides real-time P&L data for StrategyManager to consume.
        
        Args:
            current_ltp: Current market price (LTP) for the symbol
            entry_broker_db_orders: List of ENTRY broker execution records from database
        """
        try:
            if not current_ltp or current_ltp <= 0:
                logger.debug(f"OrderMonitor: Invalid LTP ({current_ltp}) for broker executions P&L update")
                return
                
            if not entry_broker_db_orders:
                logger.debug(f"OrderMonitor: No ENTRY broker executions found for P&L update")
                return
            
            logger.info(f"OrderMonitor: Updating P&L for {len(entry_broker_db_orders)} broker executions using LTP={current_ltp}")
            
            from algosat.core.db import AsyncSessionLocal, update_rows_in_table
            from algosat.core.dbschema import broker_executions
            
            async with AsyncSessionLocal() as session:
                update_count = 0
                
                for bro in entry_broker_db_orders:
                    try:
                        # Extract execution details
                        broker_exec_id = bro.get('id')
                        executed_quantity = int(bro.get('executed_quantity', 0))
                        execution_price = float(bro.get('execution_price', 0))
                        entry_side = bro.get('action', '').upper()
                        
                        if not all([broker_exec_id, executed_quantity > 0, execution_price > 0]):
                            logger.warning(f"OrderMonitor: Skipping P&L update for broker_exec_id={broker_exec_id} - invalid data")
                            continue
                        
                        # Calculate P&L: (current_price - entry_price) * quantity for BUY
                        #                (entry_price - current_price) * quantity for SELL
                        if entry_side == 'BUY':
                            # Long position: profit when current_price > entry_price
                            calculated_pnl = (current_ltp - float(execution_price)) * executed_quantity
                        elif entry_side == 'SELL':
                            # Short position: profit when current_price < entry_price
                            calculated_pnl = (float(execution_price) - current_ltp) * executed_quantity
                        else:
                            logger.warning(f"OrderMonitor: Unknown entry side '{entry_side}' for P&L calculation")
                            calculated_pnl = 0.0
                        
                        # Round to 4 decimal places (matching database precision)
                        calculated_pnl = round(calculated_pnl, 4)
                        
                        # Update broker_executions.pnl field
                        await update_rows_in_table(
                            target_table=broker_executions,
                            condition=broker_executions.c.id == broker_exec_id,
                            new_values={'pnl': calculated_pnl}
                        )
                        
                        update_count += 1
                        logger.debug(f"OrderMonitor: Updated P&L for broker_exec_id={broker_exec_id}: "
                                   f"side={entry_side}, entry_price={execution_price}, ltp={current_ltp}, "
                                   f"qty={executed_quantity}, pnl={calculated_pnl}")
                        
                    except Exception as e:
                        logger.error(f"OrderMonitor: Error updating P&L for broker_exec_id={bro.get('id')}: {e}")
                        continue
                
                await session.commit()
                logger.info(f"OrderMonitor: Successfully updated P&L for {update_count}/{len(entry_broker_db_orders)} broker executions")
                
        except Exception as e:
            logger.error(f"OrderMonitor: Error in _update_broker_executions_pnl: {e}")

    async def _get_normalized_broker_status(self, bro, broker_name, cache_lookup_order_id):
        """
        Helper to get latest broker status from cache (if available), fallback to DB, and normalize.
        """
        latest_status = None
        if broker_name and cache_lookup_order_id:
            cache_order = await self.order_cache.get_order_by_id(broker_name, cache_lookup_order_id)
            if cache_order:
                latest_status = str(cache_order.get("status"))
        broker_status = latest_status if latest_status is not None else str(bro.status)
        # Normalize broker_status to plain value (e.g., 'TRIGGER_PENDING')
        if broker_status.startswith("OrderStatus."):
            broker_status = broker_status.split(".")[-1]
        return broker_status

    async def _signal_monitor(self) -> None:
        await self.data_manager.ensure_broker()
        while self._running:
            try:
                # Use strategy instance if available, otherwise fetch from database
                if self.strategy_instance is not None:
                    # Use the passed strategy instance - still need order_row from database
                    order_row, strategy_symbol, strategy_config, _ = await self._get_order_and_strategy(self.order_id)
                    strategy = self.strategy_instance
                    logger.debug(f"OrderMonitor: Using passed strategy instance for order_id={self.order_id}")
                else:
                    # Fallback to database strategy fetch
                    order_row, strategy_symbol, strategy_config, strategy = await self._get_order_and_strategy(self.order_id)
                    logger.debug(f"OrderMonitor: Using database strategy for order_id={self.order_id}")
            except Exception as e:
                logger.error(f"OrderMonitor: Error in _get_order_and_strategy for order_id={self.order_id}: {e}", exc_info=True)
                await asyncio.sleep(self.signal_monitor_seconds)
                continue

            if strategy is None or order_row is None:
                logger.warning(f"OrderMonitor: Missing strategy or order_row for order_id={self.order_id}. Skipping iteration.")
                await asyncio.sleep(self.signal_monitor_seconds)
                continue

            # Check if order status is already one of the exit statuses (base or PENDING) set by signal monitor
            # If so, skip calling evaluate_exit to avoid repeatedly updating the same status
            current_order_status = order_row.get('status') if order_row else None
            if current_order_status:
                from algosat.common import constants
                exit_statuses = {
                    # Base exit statuses
                    constants.TRADE_STATUS_EXIT_STOPLOSS,
                    constants.TRADE_STATUS_EXIT_TARGET, 
                    constants.TRADE_STATUS_EXIT_RSI_TARGET,
                    constants.TRADE_STATUS_EXIT_REVERSAL,
                    constants.TRADE_STATUS_EXIT_EOD,
                    constants.TRADE_STATUS_EXIT_HOLIDAY,
                    constants.TRADE_STATUS_EXIT_MAX_LOSS,
                    constants.TRADE_STATUS_EXIT_EXPIRY,
                    constants.TRADE_STATUS_EXIT_ATOMIC_FAILED,
                    # PENDING exit statuses
                    f"{constants.TRADE_STATUS_EXIT_STOPLOSS}_PENDING",
                    f"{constants.TRADE_STATUS_EXIT_TARGET}_PENDING", 
                    f"{constants.TRADE_STATUS_EXIT_RSI_TARGET}_PENDING",
                    f"{constants.TRADE_STATUS_EXIT_REVERSAL}_PENDING",
                    f"{constants.TRADE_STATUS_EXIT_EOD}_PENDING",
                    f"{constants.TRADE_STATUS_EXIT_HOLIDAY}_PENDING",
                    f"{constants.TRADE_STATUS_EXIT_MAX_LOSS}_PENDING",
                    f"{constants.TRADE_STATUS_EXIT_EXPIRY}_PENDING",
                    f"{constants.TRADE_STATUS_EXIT_ATOMIC_FAILED}_PENDING",
                }
                
                if current_order_status in exit_statuses:
                    logger.debug(f"OrderMonitor: ⏸️ SKIP: Order status '{current_order_status}' is already an exit status - skipping evaluate_exit for order_id={self.order_id}")
                    await asyncio.sleep(self.signal_monitor_seconds)
                    continue

            # Determine strategy_id
            strategy_id = None
            if isinstance(strategy, dict):
                strategy_id = strategy.get('id')
            else:
                strategy_id = getattr(strategy, 'id', None)

            logger.info(f"OrderMonitor: Calling evaluate_exit for order_id={self.order_id}, strategy_id={strategy_id}")
            try:
                # Use call_strategy_method for consistency when strategy instance is available
                if self.strategy_instance is not None:
                    should_exit = await self.call_strategy_method("evaluate_exit", order_row)
                    if should_exit is None:
                        # Fallback to direct method call if call_strategy_method failed
                        evaluate_exit_fn = getattr(strategy, "evaluate_exit", None)
                        if evaluate_exit_fn is None:
                            logger.warning(f"OrderMonitor: Strategy missing evaluate_exit method for order_id={self.order_id}")
                            await asyncio.sleep(self.signal_monitor_seconds)
                            continue
                        result = evaluate_exit_fn(order_row)
                        if asyncio.iscoroutine(result):
                            should_exit = await result
                        else:
                            should_exit = result
                else:
                    # Direct method call for database strategy
                    evaluate_exit_fn = getattr(strategy, "evaluate_exit", None)
                    if evaluate_exit_fn is None:
                        logger.warning(f"OrderMonitor: Strategy missing evaluate_exit method for order_id={self.order_id}")
                        await asyncio.sleep(self.signal_monitor_seconds)
                        continue
                    result = evaluate_exit_fn(order_row)
                    if asyncio.iscoroutine(result):
                        should_exit = await result
                    else:
                        should_exit = result
            except Exception as e:
                logger.error(f"OrderMonitor: Exception in evaluate_exit for order_id={self.order_id}: {e}", exc_info=True)
                await asyncio.sleep(self.signal_monitor_seconds)
                continue

            if should_exit:
                logger.critical(f"OrderMonitor: ✅ evaluate_exit returned True for order_id={self.order_id}. Calling exit_order first, then converting to PENDING.")
                await self._clear_order_cache("evaluate_exit returned True")
                try:
                    # Call exit_order immediately when strategy decides to exit
                    # Use check_live_status=True to ensure hedge orders get status updates before exit decisions
                    await self.order_manager.exit_order(
                        parent_order_id=self.order_id,
                        exit_reason="Signal monitor triggered exit",
                        check_live_status=True
                    )
                    logger.info(f"OrderMonitor: Successfully called exit_order for order_id={self.order_id}")
                    
                    # Small delay to ensure DB transaction is committed before fetching updated status
                    await asyncio.sleep(0.1)
                    
                    # Clear cache to ensure we get fresh order data after evaluate_exit updated the status
                    await self._clear_order_cache("After exit_order to fetch fresh status")
                    # Get the current order status after evaluate_exit to see what exit type was set
                    order_row_updated, _, _, _ = await self._get_order_and_strategy(self.order_id)
                    current_status = order_row_updated.get('status') if order_row_updated else None
                    
                    logger.debug(f"OrderMonitor: After evaluate_exit, fetched current_status={current_status} for order_id={self.order_id}")
                    
                    # Convert specific exit statuses to PENDING equivalents
                    pending_status = None
                    if current_status:
                        from algosat.common import constants
                        status_mapping = {
                            constants.TRADE_STATUS_EXIT_STOPLOSS: f"{constants.TRADE_STATUS_EXIT_STOPLOSS}_PENDING",
                            constants.TRADE_STATUS_EXIT_TARGET: f"{constants.TRADE_STATUS_EXIT_TARGET}_PENDING", 
                            constants.TRADE_STATUS_EXIT_RSI_TARGET: f"{constants.TRADE_STATUS_EXIT_RSI_TARGET}_PENDING",
                            constants.TRADE_STATUS_EXIT_REVERSAL: f"{constants.TRADE_STATUS_EXIT_REVERSAL}_PENDING",
                            constants.TRADE_STATUS_EXIT_EOD: f"{constants.TRADE_STATUS_EXIT_EOD}_PENDING",
                            constants.TRADE_STATUS_EXIT_HOLIDAY: f"{constants.TRADE_STATUS_EXIT_HOLIDAY}_PENDING",
                            constants.TRADE_STATUS_EXIT_MAX_LOSS: f"{constants.TRADE_STATUS_EXIT_MAX_LOSS}_PENDING",
                            constants.TRADE_STATUS_EXIT_EXPIRY: f"{constants.TRADE_STATUS_EXIT_EXPIRY}_PENDING",
                            constants.TRADE_STATUS_EXIT_ATOMIC_FAILED: f"{constants.TRADE_STATUS_EXIT_ATOMIC_FAILED}_PENDING",
                        }
                        
                        pending_status = status_mapping.get(current_status)
                    
                    if pending_status:
                        # Update status to PENDING equivalent 
                        await self.order_manager.update_order_status_in_db(self.order_id, pending_status)
                        logger.info(f"OrderMonitor: Updated order_id={self.order_id} status from {current_status} to {pending_status}. Price monitor will complete the exit.")
                    else:
                        # Fallback: call exit_order directly for non-standard exit statuses
                        logger.warning(f"OrderMonitor: Unknown exit status {current_status} for order_id={self.order_id}. Using direct exit_order.")
                        await self.order_manager.exit_order(self.order_id, exit_reason="Signal monitor exit - unknown status")
                        self.stop()
                        return
                        
                except Exception as e:
                    logger.error(f"OrderMonitor: Failed to convert exit status to PENDING for order_id={self.order_id}: {e}", exc_info=True)
                    # Fallback to direct exit
                    try:
                        await self.order_manager.exit_order(self.order_id, exit_reason="Signal monitor exit - error in pending conversion")
                    except Exception as e2:
                        logger.error(f"OrderMonitor: Failed fallback exit for order_id={self.order_id}: {e2}", exc_info=True)
                    self.stop()
                    return
                
                # Don't stop monitoring yet - let price monitor complete the exit
                logger.info(f"OrderMonitor: Signal monitor set PENDING status for order_id={self.order_id}. Continuing monitoring for price monitor to complete exit.")
                
            else:
                # Clear order strategy cache since order status may have changed
                await self._clear_order_cache("Order status may have changed")
            
            # Sleep for the configured signal monitor interval
            await asyncio.sleep(self.signal_monitor_seconds)

    async def start(self) -> None:
        # Get strategy context for logging
        strategy_context = None
        try:
            # Use the unified helper method to get strategy name
            strategy_context = await self._get_strategy_name()
        except Exception as e:
            logger.error(f"OrderMonitor: Error getting strategy context for order_id={self.order_id}: {e}")
            strategy_context = None
        
        # Set strategy context for all OrderMonitor operations
        with set_strategy_context(strategy_context) if strategy_context else set_strategy_context("order_monitor"):
            # Fetch signal_monitor_seconds from strategy config if not set
            if self.signal_monitor_seconds is None:
                # Use strategy instance if available, otherwise fetch from database
                if self.strategy_instance is not None:
                    strategy = self.strategy_instance
                    # Still need strategy_config and strategy_symbol from database for strategy_id
                    _, strategy_symbol, strategy_config, _ = await self._get_order_and_strategy(self.order_id)
                    logger.debug(f"OrderMonitor: Using passed strategy instance for signal_monitor_seconds calculation")
                else:
                    # Use unified cache-based access for strategy_config and strategy
                    _, strategy_symbol, strategy_config, strategy = await self._get_order_and_strategy(self.order_id)
                    logger.debug(f"OrderMonitor: Using database strategy for signal_monitor_seconds calculation")
                    
                # Get strategy_id from multiple sources (priority order)
                strategy_id = None
                
                # Priority 1: Use strategy_id passed to constructor (most efficient)
                if self.strategy_id is not None:
                    strategy_id = self.strategy_id
                    logger.debug(f"OrderMonitor: Using constructor strategy_id={strategy_id} for order_id={self.order_id}")
                # Priority 2: Get from strategy_symbol (most reliable from database)
                elif strategy_symbol:
                    strategy_id = strategy_symbol.get('strategy_id')
                    logger.debug(f"OrderMonitor: Found strategy_id={strategy_id} from strategy_symbol for order_id={self.order_id}")
                else:
                    logger.warning(f"OrderMonitor: No strategy_id available for order_id={self.order_id}, using fallback signal_monitor_seconds")
                    
                logger.info(f"OrderMonitor: Using strategy_id={strategy_id} for signal_monitor_seconds calculation")
                
                import json
                trade_param = strategy_config.get('trade') if strategy_config else None
                if strategy_id in (1, 2):
                    # For strategy_id 1, 2: use interval_minutes from trade param
                    interval_minutes = None
                    if trade_param:
                        try:
                            trade_param_dict = json.loads(trade_param) if isinstance(trade_param, str) else trade_param
                            interval_minutes = trade_param_dict.get('interval_minutes')
                        except Exception as e:
                            logger.error(f"OrderMonitor: Could not parse trade_param for order_id={self.order_id}: {e}")
                    if interval_minutes:
                        self.signal_monitor_seconds = int(interval_minutes) * 60
                    else:
                        self.signal_monitor_seconds = 5 * 60  # fallback default
                elif strategy_id in (3, 4):
                    # For strategy_id 3, 4: use stoploss.timeframe from trade param
                    stoploss_timeframe = None
                    if trade_param:
                        try:
                            trade_param_dict = json.loads(trade_param) if isinstance(trade_param, str) else trade_param
                            stoploss_section = trade_param_dict.get('stoploss', {})
                            stoploss_timeframe = stoploss_section.get('timeframe')
                        except Exception as e:
                            logger.error(f"OrderMonitor: Could not parse stoploss section for order_id={self.order_id}: {e}")
                    if stoploss_timeframe:
                        # Remove 'm' prefix if present and convert to int
                        if isinstance(stoploss_timeframe, str) and stoploss_timeframe.endswith('m'):
                            stoploss_timeframe = stoploss_timeframe[:-1]
                        try:
                            self.signal_monitor_seconds = int(stoploss_timeframe) * 60
                        except Exception as e:
                            logger.error(f"OrderMonitor: Could not convert stoploss_timeframe to int for order_id={self.order_id}: {e}")
                            self.signal_monitor_seconds = 5 * 60
                    else:
                        self.signal_monitor_seconds = 5 * 60
                else:
                    # fallback default
                    logger.info(f"OrderMonitor: Using fallback signal_monitor_seconds (300) for order_id={self.order_id}")
                    self.signal_monitor_seconds = 5 * 60
            logger.info(f"Starting monitors for order_id={self.order_id} (price: {self.price_order_monitor_seconds}s, signal: {self.signal_monitor_seconds}s)")
            
            # For hedge orders, only run price monitor (skip signal monitor)
            if self.is_hedge:
                logger.info(f"OrderMonitor: Running only price monitor for hedge order {self.order_id}")
                await self._price_order_monitor()
            else:
                await asyncio.gather(self._price_order_monitor(), self._signal_monitor())

    def stop(self) -> None:
        self._running = False

    @property
    async def strategy(self):
        """
        Returns the strategy dict for this order_id (uses unified order/strategy cache).
        If strategy instance is available, returns that; otherwise fetches from database.
        """
        if self.strategy_instance is not None:
            return self.strategy_instance
        _, _, _, strategy = await self._get_order_and_strategy(self.order_id)
        return strategy