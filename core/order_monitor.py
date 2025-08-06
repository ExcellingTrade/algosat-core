from __future__ import annotations
from typing import Optional, Any
import asyncio
import time
from datetime import datetime, timezone
import pytz
from algosat.common.logger import get_logger
from algosat.models.order_aggregate import OrderAggregate

from algosat.core.data_manager import DataManager
from algosat.core.order_manager import FYERS_STATUS_MAP, OrderManager
from algosat.core.order_cache import OrderCache
from algosat.core.order_request import OrderStatus
from algosat.common.strategy_utils import wait_for_next_candle, fetch_instrument_history

logger = get_logger("OrderMonitor")

class OrderMonitor:
    def __init__(
        self,
        order_id: int,
        data_manager: DataManager,
        order_manager: OrderManager,
        order_cache: OrderCache,  # new dependency
        strategy_instance=None,  # strategy instance for shared usage
        strategy_id: int = None,  # Optional: pass strategy_id directly for efficiency
        price_order_monitor_seconds: float = 30.0,  # 1 minute default
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
                # --- Add position cache fields ---
        self._positions_cache = None
        self._positions_cache_time = None
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

    async def _get_order_and_strategy(self, order_id: int):
        """
        Fetch order, strategy_symbol, strategy_config, and strategy for this order_id, cache the result.
        Returns (order, strategy_symbol, strategy_config, strategy) tuple. Always checks cache first.
        If order is missing, logs error and stops the monitor.
        """
        # Check cache first
        if order_id in self._order_strategy_cache:
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
                            logger.info(f"OrderMonitor: Square-off time {square_off_time_str} reached for non-DELIVERY order_id={self.order_id}. Exiting order.")
                            try:
                                await self.order_manager.exit_order(self.order_id, exit_reason=f"Square-off time {square_off_time_str} reached")
                                # Update status to EOD exit
                                from algosat.common import constants
                                await self.order_manager.update_order_status_in_db(self.order_id, constants.TRADE_STATUS_EXIT_EOD)
                                self.stop()
                                return
                            except Exception as e:
                                logger.error(f"OrderMonitor: Failed to exit order {self.order_id} at square-off time: {e}")
                    except Exception as e:
                        logger.error(f"OrderMonitor: Error parsing square_off_time '{square_off_time_str}': {e}")
            
            # For DELIVERY orders: stop monitoring at 3:30 PM
            elif product_type and product_type.upper() == 'DELIVERY':
                market_close_time = dt_time(15, 30)  # 3:30 PM
                if current_time_only >= market_close_time:
                    logger.info(f"OrderMonitor: Market close time 15:30 reached for DELIVERY order_id={self.order_id}. Stopping monitoring.")
                    self.stop()
                    return
            
            # Exit AWAITING_ENTRY orders at 15:25 (regardless of product type)
            awaiting_entry_exit_time = dt_time(15, 25)  # 3:25 PM
            current_status = order_row.get('status') if order_row else None
            if (current_time_only >= awaiting_entry_exit_time and 
                current_status in ('AWAITING_ENTRY', OrderStatus.AWAITING_ENTRY)):
                logger.info(f"OrderMonitor: 15:25 reached for AWAITING_ENTRY order_id={self.order_id}. Exiting order.")
                try:
                    await self.order_manager.exit_order(self.order_id, reason="AWAITING_ENTRY order exit at 15:25")
                    # Update status to CANCELLED
                    await self.order_manager.update_order_status_in_db(self.order_id, "CANCELLED")
                    self.stop()
                    return
                except Exception as e:
                    logger.error(f"OrderMonitor: Failed to exit AWAITING_ENTRY order {self.order_id} at 15:25: {e}")
                    return

            # --- Update current price for OPEN orders and get LTP for exit checks ---
            current_ltp = None
            current_status = order_row.get('status') if order_row and order_row.get('status') else last_main_status
            logger.info(f"CurrentStatus: {current_status}")
            if current_status == OrderStatus.OPEN or current_status == 'OPEN':
                current_ltp = await self._update_current_price_for_open_order(order_row)

            # --- Use live broker order data from order_cache for ENTRY side ---
            entry_broker_db_orders = [bro for bro in agg.broker_orders if getattr(bro, 'side', None) == 'ENTRY']
            all_statuses = []
            status_set = set()
            try:
                for bro in entry_broker_db_orders:
                    try:
                        broker_exec_id = getattr(bro, 'id', None)
                        broker_order_id = getattr(bro, 'order_id', None)
                        broker_id = getattr(bro, 'broker_id', None)
                        broker_name = None
                        if broker_id is not None:
                            try:
                                broker_name = await self._get_broker_name_with_cache(broker_id)
                            except Exception as e:
                                logger.error(f"OrderMonitor: Could not get broker name for broker_id={broker_id}: {e}")
                        # If broker_order_id is None or empty, order is not placed, set status to FAILED
                        cache_order = None
                        if not broker_order_id:
                            broker_status = "FAILED"
                        else:
                            cache_lookup_order_id = self._get_cache_lookup_order_id(
                                broker_order_id, broker_name, product_type
                            )
                            # Fetch live broker order from order_cache
                            if broker_name and cache_lookup_order_id:
                                try:
                                    cache_order = await self.order_cache.get_order_by_id(broker_name, cache_lookup_order_id)
                                    logger.debug(f"OrderMonitor: Fetched order from cache for broker_name={broker_name}, order_id={cache_lookup_order_id}: {cache_order}")  
                                except Exception as e:
                                    logger.error(f"OrderMonitor: Error fetching order from cache for broker_name={broker_name}, order_id={cache_lookup_order_id}: {e}")
                            # Use status from cache_order if available, else fallback to DB
                            broker_status = None
                            if cache_order and 'status' in cache_order:
                                broker_status = cache_order['status']
                            else:
                                logger.info(f"OrderMonitor: Using DB status for broker_order_id={broker_order_id} as cache_order not found or missing status for order_id {self.order_id}")
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
                    except Exception as e:
                        logger.error(f"OrderMonitor: Unexpected error processing broker order (exec_id={getattr(bro, 'id', None)}): {e}", exc_info=True)
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
                                product_type_val = cache_order.get("product_type")
                                # Get quantity from cache_order (qty or quantity)
                                quantity = cache_order.get("qty") or cache_order.get("quantity")
                                # Get symbol from cache_order (symbol or tradingsymbol)
                                symbol_val = cache_order.get("symbol") or cache_order.get("tradingsymbol")
                            if execution_price is None:
                                execution_price = getattr(bro, "exec_price", None) or getattr(bro, "execution_price", None) or getattr(bro, "average_price", None) or getattr(bro, "tradedPrice", None)
                            if order_type is None:
                                order_type = getattr(bro, "order_type", None)
                            if product_type_val is None:
                                product_type_val = getattr(bro, "product_type", None)
                            if quantity is None:
                                quantity = getattr(bro, "qty", None) or getattr(bro, "quantity", None)
                            if symbol_val is None:
                                symbol_val = getattr(bro, "symbol", None) or getattr(bro, "tradingsymbol", None)
                            execution_time = datetime.now(timezone.utc)
                            await self.order_manager.update_broker_exec_status_in_db(
                                broker_exec_id,
                                broker_status,
                                executed_quantity=executed_quantity,
                                quantity = quantity,
                                execution_price=execution_price,
                                order_type=order_type,
                                product_type=product_type_val,
                                execution_time=execution_time,
                                symbol=symbol_val
                            )
                        else:
                            await self.order_manager.update_broker_exec_status_in_db(broker_exec_id, broker_status)
                        last_broker_statuses[broker_exec_id] = broker_status
            except Exception as e:
                logger.error(f"OrderMonitor: Unexpected error in broker order status loop: {e}", exc_info=True)
               

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
                        logger.info(f"OrderMonitor: Updated Orders table for order_id={self.order_id} with qty={total_quantity}, executed_quantity={total_executed_quantity}, entry_price={entry_price}")
                    else:
                        logger.debug(f"OrderMonitor: No change in qty, executed_quantity, entry_price for order_id={self.order_id}. Skipping DB update.")
            except Exception as e:
                logger.error(f"OrderMonitor: Error updating aggregated quantity/executed_quantity for order_id={self.order_id}: {e}")
            logger.info(f"OrderMonitor: Order {self.order_id} ENTRY broker statuses (live): {all_statuses}")
            # --- Decision logic for main order status ---
            main_status = None
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
            # Only update Orders table if status changed
            if main_status is not None and main_status != last_main_status:
                if main_status == OrderStatus.OPEN and any(s in ("FILLED", "PARTIALLY_FILLED") for s in status_set):
                    from datetime import datetime, timezone
                    entry_time = datetime.now(timezone.utc)
                    logger.info(f"OrderMonitor: Updating order_id={self.order_id} to {main_status} with entry_time={entry_time}")
                    await self.order_manager.update_order_status_in_db(self.order_id, main_status)
                    await self.order_manager.update_order_stop_loss_in_db(self.order_id, order_row.get('stop_loss'))
                    from algosat.core.db import AsyncSessionLocal, update_rows_in_table
                    from algosat.core.dbschema import orders

                    await update_rows_in_table(
                        target_table=orders,
                        condition=orders.c.id == self.order_id,
                        new_values={"entry_time": entry_time}
                    )
                else:
                    logger.info(f"OrderMonitor: Updating order_id={self.order_id} to {main_status}")
                    await self.order_manager.update_order_status_in_db(self.order_id, main_status)
                last_main_status = main_status
                if main_status in (OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.FAILED):
                    logger.info(f"OrderMonitor: Order {self.order_id} reached terminal status {main_status}. Stopping monitor.")
                    self.stop()
                    return
                
            # --- Price-based exit logic for OptionBuy and OptionSell strategies ---
            # Call after status is determined to ensure we have the correct OPEN status
            current_order_status = last_main_status if last_main_status else current_status
            if current_order_status == OrderStatus.OPEN or current_order_status == 'OPEN':
                await self._check_price_based_exit(order_row, strategy, current_order_status, current_ltp)
            
            # --- Check for PENDING exit statuses from signal monitor ---
            # If signal monitor set a PENDING exit status, complete the exit with full broker details
            await self._check_and_complete_pending_exits(order_row, current_order_status or last_main_status)
            
            # If the order monitor was stopped during PENDING exit processing, exit immediately
            if not self._running:
                return
                
            # --- monitor positions if status is OPEN ---
            # Only for OPEN status, check broker positions and update order status/PnL based on positions
            if last_main_status == str(OrderStatus.OPEN) or (main_status == OrderStatus.OPEN):
                try:
                    # Use new helper to get all broker positions (with cache)
                    all_positions = await self._get_all_broker_positions_with_cache()
                    logger.info(f"OrderMonitor: Fetched all broker positions for order_id={self.order_id}: {all_positions}")
                    # Map broker_id to positions
                    broker_positions_map = {}
                    if all_positions and isinstance(all_positions, dict):
                        broker_positions_map = all_positions
                    # For each broker_exec in ENTRY, match to broker positions by broker, symbol, quantity, product
                    async with AsyncSessionLocal() as session:
                    # entry_broker_db_orders = [bro for bro in agg.broker_orders if getattr(bro, 'side', None) == 'ENTRY']
                        entry_broker_db_orders = await get_broker_executions_for_order(session, self.order_id, side='ENTRY') 
                    total_pnl = 0.0
                    all_closed = True
                    for bro in entry_broker_db_orders:
                        # Skip processing if broker execution is invalid or failed
                        broker_status = bro.get('status', '').upper()
                        symbol_val = bro.get('symbol', None) or bro.get('tradingsymbol', None)
                        qty = bro.get('quantity', None)
                        
                        # Simple validation checks: skip if status is FAILED or missing essential data
                        if (broker_status == 'FAILED' or 
                            symbol_val is None or 
                            qty is None or 
                            qty == 0):
                            logger.debug(f"OrderMonitor: Skipping position matching for order_id={self.order_id} - "
                                       f"invalid broker execution: status={broker_status}, symbol={symbol_val}, qty={qty}")
                            continue
                        
                        # broker_id = getattr(bro, 'broker_id', None)
                        broker_id = bro.get('broker_id', None)
                        broker_name = None
                        if broker_id is not None:
                            try:
                                broker_name = await self._get_broker_name_with_cache(broker_id)
                            except Exception as e:
                                logger.error(f"OrderMonitor: Could not get broker name for broker_id={broker_id}: {e}")
                        # broker_name = await self.data_manager.get_broker_name_by_id(bro.get("broker_id"))
                        product = bro.get('product_type', None) or bro.get('product', None)
                        exec_price = bro.get('execution_price', None)
                        # Find matching position for this broker
                        positions = broker_positions_map.get(broker_name.lower() if broker_name else "", None)
                        matched_pos = None
                        logger.info(f"OrderMonitor: Looking for positions for broker_name={broker_name}, symbol={symbol_val}, qty={qty}, product={product}")
                        logger.info(f"OrderMonitor: Available broker_positions_map keys: {list(broker_positions_map.keys()) if broker_positions_map else 'None'}")
                        
                        if positions:
                            logger.info(f"OrderMonitor: Found {len(positions)} positions for broker {broker_name}")
                            # Zerodha: positions is a dict with 'net' key
                            if broker_name and broker_name.lower() == "zerodha":
                                for pos in positions:
                                    try:
                                        logger.info(f"pos.get('tradingsymbol') = {pos.get('tradingsymbol')}, symbol_val = {symbol_val}, qty = {qty}, product = {product}, exec_price = {exec_price}")
                                        # Match by tradingsymbol and product only
                                        product_match = (str(pos.get('product')).upper() == str(product).upper()) if product else True
                                        # entry_price_match = (float(pos.get('buy_price', 0)) == float(exec_price)) if exec_price else True
                                        
                                        # # Flexible quantity matching: handle duplicate orders for same symbol
                                        # broker_buy_qty = int(pos.get('buy_quantity', 0))
                                        # broker_overnight_qty = int(pos.get('overnight_quantity', 0))
                                        # broker_current_qty = int(pos.get('quantity', 0))
                                        # db_qty = int(qty)
                                        
                                        # # For closed positions (quantity=0), use buy_quantity for matching
                                        # # For open positions, use quantity for matching
                                        # qty_match = False
                                        
                                        # if broker_current_qty == 0:
                                        #     # Position is closed - match against buy_quantity or overnight_quantity
                                        #     logger.debug(f"OrderMonitor: Closed position detected (qty=0) - matching against buy_qty={broker_buy_qty}, overnight_qty={broker_overnight_qty}")
                                        #     
                                        #     if broker_buy_qty > 0 and db_qty > 0:
                                        #         qty_match = (broker_buy_qty % db_qty == 0) or (db_qty % broker_buy_qty == 0)
                                        #         if qty_match:
                                        #             logger.info(f"OrderMonitor: Matched closed position by buy_quantity: broker_buy_qty={broker_buy_qty}, db_qty={db_qty}")
                                        #     elif broker_overnight_qty > 0 and db_qty > 0:
                                        #         qty_match = (broker_overnight_qty % db_qty == 0) or (db_qty % broker_overnight_qty == 0)
                                        #         if qty_match:
                                        #             logger.info(f"OrderMonitor: Matched closed position by overnight_quantity: broker_overnight_qty={broker_overnight_qty}, db_qty={db_qty}")
                                        # else:
                                        #     # Position is open - match against current quantity
                                        #     logger.debug(f"OrderMonitor: Open position detected (qty={broker_current_qty}) - standard matching")
                                        #     if broker_current_qty > 0 and db_qty > 0:
                                        #         qty_match = (broker_current_qty % db_qty == 0) or (db_qty % broker_current_qty == 0)
                                        
                                        # # Fallback to exact match for safety
                                        # if not qty_match:
                                        #     qty_match = (broker_buy_qty == db_qty) or (broker_overnight_qty == db_qty) or (broker_current_qty == db_qty)
                                        
                                        if (
                                            pos.get('tradingsymbol') == symbol_val and
                                            product_match
                                            # qty_match and
                                            # entry_price_match
                                        ):
                                            matched_pos = pos
                                            
                                            # Log potential duplicate detection
                                            broker_qty = int(pos.get('buy_quantity', 0)) or int(pos.get('overnight_quantity', 0)) or int(pos.get('quantity', 0))
                                            position_status = "CLOSED" if int(pos.get('quantity', 0)) == 0 else "OPEN"
                                            
                                            if broker_qty > int(qty) and broker_qty % int(qty) == 0:
                                                multiplier = broker_qty // int(qty)
                                                logger.warning(f"OrderMonitor: Detected potential duplicate orders - "
                                                             f"Broker quantity ({broker_qty}) is {multiplier}x DB quantity ({qty}) "
                                                             f"for symbol={symbol_val} (Position: {position_status})")
                                            
                                            logger.info(f"OrderMonitor: Matched Zerodha position for symbol={symbol_val} (Status: {position_status}): {pos}")
                                            break
                                    except Exception as e:
                                        logger.error(f"OrderMonitor: Error matching Zerodha position: {e}")
                            # Fyers: positions is a list of dicts
                            elif broker_name and broker_name.lower() == "fyers":
                                for pos in positions:
                                    try:
                                        # Fyers fields: 'symbol', 'qty', 'productType', 'buyAvg', 'side'
                                        product_match = (str(pos.get('productType')).upper() == str(product).upper()) if product else True
                                        
                                        # # Flexible quantity matching: handle duplicate orders for same symbol
                                        # broker_buy_qty = int(pos.get('buyQty', 0))
                                        # broker_current_qty = int(pos.get('qty', 0))
                                        # db_qty = int(qty)
                                        
                                        # # For closed positions (qty=0), use buyQty for matching
                                        # # For open positions, use qty for matching
                                        # qty_match = False
                                        
                                        # if broker_current_qty == 0:
                                        #     # Position is closed - match against buyQty
                                        #     logger.debug(f"OrderMonitor: Closed Fyers position detected (qty=0) - matching against buyQty={broker_buy_qty}")
                                        #     
                                        #     if broker_buy_qty > 0 and db_qty > 0:
                                        #         qty_match = (broker_buy_qty % db_qty == 0) or (db_qty % broker_buy_qty == 0)
                                        #         if qty_match:
                                        #             logger.info(f"OrderMonitor: Matched closed Fyers position by buyQty: broker_buy_qty={broker_buy_qty}, db_qty={db_qty}")
                                        # else:
                                        #     # Position is open - match against current qty
                                        #     logger.debug(f"OrderMonitor: Open Fyers position detected (qty={broker_current_qty}) - standard matching")
                                        #     if broker_current_qty > 0 and db_qty > 0:
                                        #         qty_match = (broker_current_qty % db_qty == 0) or (db_qty % broker_current_qty == 0)
                                        
                                        # # Fallback to exact match for safety
                                        # if not qty_match:
                                        #     qty_match = (broker_buy_qty == db_qty) or (broker_current_qty == db_qty)
                                        
                                        symbol_match = (pos.get('symbol') == symbol_val)
                                        if symbol_match and product_match:
                                            # qty_match:
                                            matched_pos = pos
                                            
                                            # Log potential duplicate detection
                                            broker_qty = int(pos.get('buyQty', 0)) or int(pos.get('qty', 0))
                                            position_status = "CLOSED" if int(pos.get('qty', 0)) == 0 else "OPEN"
                                            
                                            if broker_qty > int(qty) and broker_qty % int(qty) == 0:
                                                multiplier = broker_qty // int(qty)
                                                logger.warning(f"OrderMonitor: Detected potential duplicate orders - "
                                                             f"Broker quantity ({broker_qty}) is {multiplier}x DB quantity ({qty}) "
                                                             f"for symbol={symbol_val} (Position: {position_status})")
                                            
                                            logger.info(f"OrderMonitor: Matched Fyers position for symbol={symbol_val} (Status: {position_status}): {pos}")
                                            break
                                    except Exception as e:
                                        logger.error(f"OrderMonitor: Error matching Fyers position: {e}")
                        else:
                            logger.warning(f"OrderMonitor: No positions found for broker={broker_name} (positions data: {positions})")
                        
                        # If match found, update order/broker_exec status and accumulate PnL
                        if matched_pos:
                            logger.info(f"OrderMonitor: Processing matched position for broker={broker_name}: {matched_pos}")
                            # Zerodha: use 'pnl' field; Fyers: use 'pl' field
                            broker_total_pnl = 0.0
                            broker_total_qty = 0
                            our_qty = int(qty)
                            closed = False
                            
                            if broker_name and broker_name.lower() == "zerodha":
                                broker_total_pnl = float(matched_pos.get('pnl', 0))
                                # For quantity determination: prefer buy_quantity for closed positions, quantity for open positions
                                broker_current_qty = int(matched_pos.get('quantity', 0))
                                if broker_current_qty == 0:
                                    # Closed position - use buy_quantity or overnight_quantity
                                    broker_total_qty = int(matched_pos.get('buy_quantity', 0)) or int(matched_pos.get('overnight_quantity', 0))
                                    logger.debug(f"OrderMonitor: Using buy_quantity={broker_total_qty} for closed Zerodha position PnL calculation")
                                else:
                                    # Open position - use current quantity
                                    broker_total_qty = broker_current_qty
                                    logger.debug(f"OrderMonitor: Using current quantity={broker_total_qty} for open Zerodha position PnL calculation")
                                
                                # Position closure detection
                                if broker_current_qty == 0:
                                    closed = True
                            elif broker_name and broker_name.lower() == "fyers":
                                broker_total_pnl = float(round(matched_pos.get('pl', 0), 2))
                                # For Fyers: use buyQty for closed positions, qty for open positions
                                broker_current_qty = int(matched_pos.get('qty', 0))
                                if broker_current_qty == 0:
                                    # Closed position - use buyQty
                                    broker_total_qty = int(matched_pos.get('buyQty', 0))
                                    logger.debug(f"OrderMonitor: Using buyQty={broker_total_qty} for closed Fyers position PnL calculation")
                                else:
                                    # Open position - use current qty
                                    broker_total_qty = broker_current_qty
                                    logger.debug(f"OrderMonitor: Using current qty={broker_total_qty} for open Fyers position PnL calculation")
                                
                                # Position closure detection
                                if broker_current_qty == 0:
                                    closed = True
                            
                            # Calculate proportional PnL for our specific quantity
                            if broker_total_qty > 0 and our_qty > 0:
                                # Proportional PnL = (Our Quantity / Broker Total Quantity) * Broker Total PnL
                                proportional_pnl = (our_qty / broker_total_qty) * broker_total_pnl
                                logger.info(f"OrderMonitor: PnL Calculation for {broker_name}:")
                                logger.info(f"  Broker Total PnL: {broker_total_pnl}")
                                logger.info(f"  Broker Total Qty: {broker_total_qty}")
                                logger.info(f"  Our DB Qty: {our_qty}")
                                logger.info(f"  Proportional PnL: {proportional_pnl} = ({our_qty}/{broker_total_qty}) * {broker_total_pnl}")
                            else:
                                proportional_pnl = 0.0
                                logger.warning(f"OrderMonitor: Cannot calculate proportional PnL - broker_total_qty={broker_total_qty}, our_qty={our_qty}")
                            
                            total_pnl += proportional_pnl
                            logger.info(f"OrderMonitor: Added proportional PnL {proportional_pnl} from {broker_name} position. Total PnL now: {total_pnl}")
                            
                            # Log potential duplicate order detection based on PnL difference
                            if broker_total_qty > our_qty and broker_total_qty % our_qty == 0:
                                multiplier = broker_total_qty // our_qty
                                expected_total_pnl = proportional_pnl * multiplier
                                pnl_diff = abs(broker_total_pnl - expected_total_pnl)
                                if pnl_diff > 0.01:  # Allow small rounding differences
                                    logger.warning(f"OrderMonitor: PnL calculation discrepancy detected!")
                                    logger.warning(f"  Expected total PnL: {expected_total_pnl} (proportional_pnl * {multiplier})")
                                    logger.warning(f"  Actual broker PnL: {broker_total_pnl}")
                                    logger.warning(f"  Difference: {pnl_diff}")
                            
                            if closed:
                                # --- Enhancement: Insert EXIT broker_execution before marking CLOSED ---
                                try:
                                    from datetime import datetime, timezone
                                    execution_time = datetime.now(timezone.utc)
                                    orig_side_raw = bro.get('action') or ''
                                    # Handle enum values like SIDE.BUY or string values like 'BUY'
                                    if hasattr(orig_side_raw, 'value'):
                                        # It's an enum, extract the value
                                        orig_side = str(orig_side_raw.value).upper()
                                    elif hasattr(orig_side_raw, 'name'):
                                        # It's an enum, extract the name
                                        orig_side = str(orig_side_raw.name).upper()
                                    else:
                                        # It's a string, use as is
                                        orig_side = str(orig_side_raw).upper()
                                    
                                    # Remove any enum prefix like 'SIDE.' if present
                                    if '.' in orig_side:
                                        orig_side = orig_side.split('.')[-1]
                                    
                                    if orig_side == 'BUY':
                                        exit_action = 'SELL'
                                    elif orig_side == 'SELL':
                                        exit_action = 'BUY'
                                    else:
                                        exit_action = ''
                                    execution_price = None
                                    executed_quantity = None
                                    symbol_val_exit = bro.get('symbol', None) or bro.get('tradingsymbol', None)
                                    product = bro.get('product_type', None) or bro.get('product', None)
                                    broker_id = bro.get("broker_id")
                                    broker_order_id = bro.get("broker_order_id")
                                    # Zerodha
                                    if broker_name and broker_name.lower() == "zerodha":
                                        if orig_side and orig_side.upper() == "BUY":
                                            execution_price = matched_pos.get('sell_price')
                                            executed_quantity = matched_pos.get('buy_quantity', None)
                                        elif orig_side and orig_side.upper() == "SELL":
                                            execution_price = matched_pos.get('buy_price')
                                            executed_quantity = matched_pos.get('sell_quantity', None)
                                        else:
                                            execution_price = matched_pos.get('sell_price') or matched_pos.get('buy_price')
                                            executed_quantity = matched_pos.get('quantity', None)
                                    # Fyers
                                    elif broker_name and broker_name.lower() == "fyers":
                                        # Fyers fields: 'side' (BUY/SELL), 'sellAvg', 'buyAvg', 'qty'
                                        if orig_side and orig_side.upper() == "BUY":
                                            execution_price = matched_pos.get('sellAvg', None)
                                            executed_quantity = matched_pos.get('buyQty', None)
                                        elif orig_side and orig_side.upper() == "SELL":
                                            execution_price = matched_pos.get('buyAvg', None)
                                            executed_quantity = matched_pos.get('sellQty', None)
                                        else:
                                            execution_price = matched_pos.get('sellAvg', None) or matched_pos.get('buyAvg', None)
                                            executed_quantity = matched_pos.get('qty', None)
                                    # fallback
                                    if execution_price is None:
                                        execution_price = matched_pos.get('sell_price') or matched_pos.get('buy_price')
                                    if executed_quantity is None:
                                        executed_quantity = matched_pos.get('quantity', None)
                                    # Use close time as now


                                    # Check if EXIT broker_execution already exists for this parent_order_id, broker_id, broker_order_id
                                    from algosat.core.db import AsyncSessionLocal, get_broker_executions_for_order
                                    async with AsyncSessionLocal() as session:
                                        existing_execs = await get_broker_executions_for_order(
                                            session,
                                            self.order_id,
                                            side='EXIT'
                                        )
                                    found = None
                                    for ex in existing_execs:
                                        if ex.get('broker_id') == broker_id and ex.get('broker_order_id') == broker_order_id:
                                            found = ex
                                            break
                                    if found:
                                        # Update only execution_price
                                        await self.order_manager.update_broker_execution_price(found.get('id'), execution_price)
                                        logger.info(f"OrderMonitor: Updated execution_price for EXIT broker_execution id={found.get('id')}")
                                    else:
                                        await self.order_manager.insert_broker_execution(
                                            parent_order_id=self.order_id,
                                            broker_id=broker_id,
                                            broker_order_id=broker_order_id,
                                            action=exit_action,
                                            side='EXIT',
                                            status='FILLED',
                                            executed_quantity=be.get('executed_quantity', 0),
                                            execution_price=execution_price,
                                            product_type=product_type,
                                            order_type='MARKET',
                                            order_messages=f"Order exited:",
                                            symbol=symbol_val_exit,
                                            execution_time=execution_time,
                                            notes=f"Order Exited"
                                        )
                                        logger.info(f"OrderMonitor: Inserted new EXIT broker_execution for parent_order_id={self.order_id}, broker_id={broker_id}, broker_order_id={broker_order_id}")
                                except Exception as e:
                                    logger.error(f"OrderMonitor: Error inserting/updating EXIT broker_execution: {e}")
                            else:
                                all_closed = False
                        else:
                            logger.warning(f"OrderMonitor: No matching position found for broker={broker_name}, symbol={symbol_val}, qty={qty}, product={product}")
                            all_closed = False
                    # Update order PnL field in DB
                    try:
                        logger.info(f"OrderMonitor: About to update PnL for order_id={self.order_id} with value={total_pnl}")
                        await self.order_manager.update_order_pnl_in_db(self.order_id, total_pnl)
                        logger.info(f"OrderMonitor: Successfully called update_order_pnl_in_db for order_id={self.order_id}: {total_pnl}")
                        
                        # Verify the update by reading back from DB
                        from algosat.core.db import AsyncSessionLocal, get_order_by_id
                        async with AsyncSessionLocal() as session:
                            updated_order = await get_order_by_id(session, self.order_id)
                            current_pnl_in_db = updated_order.get('pnl') if updated_order else None
                            logger.info(f"OrderMonitor: PnL verification for order_id={self.order_id} - Expected: {total_pnl}, Actual in DB: {current_pnl_in_db}")
                    except Exception as e:
                        logger.error(f"OrderMonitor: Error updating order PnL for order_id={self.order_id}: {e}")
                    
                    # 🚨 PER-TRADE LOSS VALIDATION 🚨
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
                                logger.error(f"OrderMonitor: Error parsing trade config for max_loss_per_lot: {e}")
                        
                        # 4. Calculate total risk exposure
                        total_risk_exposure = lot_qty * trade_enabled_brokers * max_loss_per_lot
                        
                        # 5. Check if loss exceeds limit
                        if total_risk_exposure > 0 and total_pnl < -abs(total_risk_exposure):
                            logger.critical(f"🚨 PER-TRADE LOSS LIMIT EXCEEDED for order_id={self.order_id}! "
                                          f"Current P&L: {total_pnl}, Max Loss: {total_risk_exposure} "
                                          f"(lot_qty: {lot_qty} × brokers: {trade_enabled_brokers} × max_loss_per_lot: {max_loss_per_lot})")
                            
                            # 6. Exit the order immediately
                            await self.order_manager.exit_order(self.order_id, reason="Per-trade loss limit exceeded")
                            # Update status to max loss exit
                            from algosat.common import constants
                            await self.order_manager.update_order_status_in_db(self.order_id, constants.TRADE_STATUS_EXIT_MAX_LOSS)
                            logger.critical(f"🚨 Exited order_id={self.order_id} due to per-trade loss limit breach")
                            self.stop()
                            return
                        else:
                            logger.debug(f"OrderMonitor: Per-trade risk check passed for order_id={self.order_id}. "
                                       f"P&L: {total_pnl}, Risk exposure: {total_risk_exposure}")
                            
                    except Exception as e:
                        logger.error(f"OrderMonitor: Error in per-trade loss validation for order_id={self.order_id}: {e}")
                    
                    # If all positions are squared off, update status to CLOSED/EXITED
                    # Only update to CLOSED if order is currently in a "running" state
                    if all_closed and entry_broker_db_orders:
                        # Get current order status to check if we should update to CLOSED
                        current_order_status = order_row.get('status') if order_row else None
                        allowed_statuses_for_closed = ['OPEN', 'AWAITING_ENTRY', str(OrderStatus.OPEN), str(OrderStatus.AWAITING_ENTRY)]
                        
                        if current_order_status in allowed_statuses_for_closed:
                            try:
                                from datetime import datetime, timezone
                                from algosat.core.db import AsyncSessionLocal, update_rows_in_table, get_broker_executions_for_order
                                from algosat.core.dbschema import orders
                                # Calculate VWAP exit price for each broker
                                async with AsyncSessionLocal() as session:
                                    exit_execs = await get_broker_executions_for_order(session, self.order_id, side='EXIT')
                                broker_vwap = {}
                                broker_qty = {}
                                for ex in exit_execs:
                                    broker_id = ex.get('broker_id')
                                    exec_price = float(ex.get('execution_price') or 0)
                                    exec_qty = int(ex.get('executed_quantity') or 0)
                                    if broker_id not in broker_vwap:
                                        broker_vwap[broker_id] = 0.0
                                        broker_qty[broker_id] = 0
                                    broker_vwap[broker_id] += exec_price * exec_qty
                                    broker_qty[broker_id] += exec_qty
                                # Compute VWAP per broker
                                broker_exit_prices = {}
                                for broker_id in broker_vwap:
                                    qty = broker_qty[broker_id]
                                    vwap = broker_vwap[broker_id] / qty if qty > 0 else 0.0
                                    broker_exit_prices[broker_id] = vwap
                                # For orders table, set exit_price as the average VWAP across all brokers
                                total_vwap = sum(broker_vwap.values())
                                total_qty = sum(broker_qty.values())
                                avg_exit_price = total_vwap / total_qty if total_qty > 0 else None
                                update_fields = {
                                    "status": "CLOSED",
                                    "exit_time": datetime.now(timezone.utc)
                                }
                                if avg_exit_price is not None:
                                    update_fields["exit_price"] = round(avg_exit_price, 2)
                                await update_rows_in_table(
                                    target_table=orders,
                                    condition=orders.c.id == self.order_id,
                                    new_values=update_fields
                                )
                                logger.info(
                                    f"OrderMonitor: All broker positions squared off for order_id={self.order_id}. "
                                    f"Updated orders table with {update_fields} (VWAP exit_price: {avg_exit_price})"
                                )
                                self.stop()
                                return
                            except Exception as e:
                                logger.error(f"OrderMonitor: Error updating order status to CLOSED: {e}")
                        else:
                            logger.info(
                                f"OrderMonitor: All positions squared off for order_id={self.order_id}, "
                                f"but current status '{current_order_status}' is not in running state. "
                                f"Skipping CLOSED status update to preserve exit status."
                            )
                except Exception as e:
                    logger.error(f"OrderMonitor: Error in broker position monitoring: {e}", exc_info=True)
            await asyncio.sleep(self.price_order_monitor_seconds)
        logger.info(f"OrderMonitor: Stopping price monitor for order_id={self.order_id} (last status: {last_main_status})")
    
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
            logger.info(f"OrderMonitor: Starting price-based exit check for order_id={self.order_id}, status={current_main_status}")
            
            # Only check for OPEN orders
            if current_main_status != 'OPEN':
                logger.info(f"OrderMonitor: ⏸️ SKIP: Price check skipped - order_id={self.order_id} status is '{current_main_status}', not 'OPEN'")
                return
            
            # Only for OptionBuy and OptionSell strategies
            strategy_name = None
            if isinstance(strategy, dict):
                strategy_name = strategy.get('strategy_key', '').lower()
            else:
                strategy_name = getattr(strategy, 'strategy_key', '').lower()
            
            logger.info(f"OrderMonitor: 📋 Price check - order_id={self.order_id}, strategy='{strategy_name}'")
            
            if strategy_name not in ['optionbuy', 'optionsell']:
                logger.info(f"OrderMonitor: ⏸️ SKIP: Price check skipped - order_id={self.order_id} strategy '{strategy_name}' not supported for price-based exits. Supported: [optionbuy, optionsell]")
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
                
            # Get current LTP (use pre-fetched LTP if available, otherwise fetch)
            ltp = None
            if current_ltp is not None:
                ltp = float(current_ltp)
                logger.info(f"OrderMonitor: Using pre-fetched LTP for price check: order_id={self.order_id}, symbol={strike_symbol}, LTP={ltp}")
            else:
                try:
                    logger.info(f"OrderMonitor: Fetching LTP for price check: order_id={self.order_id}, symbol={strike_symbol}")
                    ltp_response = await self.data_manager.get_ltp(strike_symbol)
                    if isinstance(ltp_response, dict):
                        ltp = ltp_response.get(strike_symbol)
                    else:
                        ltp = ltp_response
                        
                    if ltp is None:
                        logger.warning(f"OrderMonitor: Could not get LTP for {strike_symbol}, order_id={self.order_id}")
                        return
                        
                    ltp = float(ltp)
                    logger.info(f"OrderMonitor: Fetched LTP for price check: order_id={self.order_id}, symbol={strike_symbol}, LTP={ltp}")
                    
                except Exception as e:
                    logger.error(f"OrderMonitor: Error getting LTP for {strike_symbol}, order_id={self.order_id}: {e}")
                    return
                    
            logger.info(f"OrderMonitor: 🔍 PRICE CHECK - order_id={self.order_id}, symbol={strike_symbol}, LTP={ltp}, target={target_price}, SL={stop_loss}, side={side}")
            
            # Check exit conditions based on strategy and side
            should_exit = False
            exit_reason = None
            exit_status = None
            
            if side == 'BUY':  # Long position
                logger.debug(f"OrderMonitor: Checking BUY position exit conditions for order_id={self.order_id}")
                
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
                    # Exit the order via OrderManager
                    await self.order_manager.exit_order(
                        parent_order_id=self.order_id,
                        exit_reason=exit_reason,
                        ltp=ltp
                    )
                    
                    # Update order status with appropriate exit status
                    from algosat.common import constants
                    if exit_status == "EXIT_TARGET":
                        status_constant = constants.TRADE_STATUS_EXIT_TARGET
                    elif exit_status == "EXIT_STOPLOSS":
                        status_constant = constants.TRADE_STATUS_EXIT_STOPLOSS
                    else:
                        status_constant = constants.TRADE_STATUS_EXIT_CLOSED
                        
                    await self.order_manager.update_order_status_in_db(
                        order_id=self.order_id,
                        status=status_constant
                    )
                    
                    logger.critical(f"OrderMonitor: ✅ Successfully exited order_id={self.order_id} due to price condition. Status updated to {status_constant}")
                    
                    # Stop monitoring this order
                    self.stop()
                    return
                    
                except Exception as e:
                    logger.error(f"OrderMonitor: ❌ Error exiting order_id={self.order_id} due to price condition: {e}")
            else:
                logger.debug(f"OrderMonitor: ✅ Price check completed - no exit conditions met for order_id={self.order_id}")
                    
        except Exception as e:
            logger.error(f"OrderMonitor: ❌ Error in price-based exit check for order_id={self.order_id}: {e}", exc_info=True)

    async def _check_and_complete_pending_exits(self, order_row, current_order_status):
        """
        Check for PENDING exit statuses set by signal monitor and complete the exit process.
        This method calculates exit_price, exit_time, PnL and updates the final exit status.
        
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
            
            # Get all broker positions to calculate current exit details
            all_positions = await self._get_all_broker_positions_with_cache()
            broker_positions_map = {}
            if all_positions and isinstance(all_positions, dict):
                broker_positions_map = all_positions
                
            # Get broker executions for this order
            from algosat.core.db import AsyncSessionLocal, get_broker_executions_for_order
            async with AsyncSessionLocal() as session:
                entry_broker_db_orders = await get_broker_executions_for_order(session, self.order_id, side='ENTRY')
            
            # Calculate exit details from current broker positions and prepare broker_executions data
            total_exit_value = 0.0
            total_exit_qty = 0.0
            total_pnl = 0.0
            exit_details_available = False
            broker_exit_data = []  # Store individual broker exit details for broker_executions updates
            
            for bro in entry_broker_db_orders:
                broker_status = bro.get('status', '').upper()
                symbol_val = bro.get('symbol', None) or bro.get('tradingsymbol', None)
                qty = bro.get('quantity', None)
                
                if (broker_status == 'FAILED' or symbol_val is None or qty is None or qty == 0):
                    continue
                    
                broker_id = bro.get('broker_id', None)
                broker_name = None
                if broker_id is not None:
                    try:
                        broker_name = await self._get_broker_name_with_cache(broker_id)
                    except Exception as e:
                        logger.error(f"OrderMonitor: Could not get broker name for broker_id={broker_id}: {e}")
                        continue
                
                # Find matching position for exit price calculation
                positions = broker_positions_map.get(broker_name.lower() if broker_name else "", None)
                if not positions:
                    continue
                    
                # Find matching position
                matched_pos = None
                product = bro.get('product_type', None) or bro.get('product', None)
                
                if broker_name and broker_name.lower() == "zerodha":
                    for pos in positions:
                        try:
                            product_match = (str(pos.get('product')).upper() == str(product).upper()) if product else True
                            if pos.get('tradingsymbol') == symbol_val and product_match:
                                matched_pos = pos
                                break
                        except Exception as e:
                            logger.error(f"OrderMonitor: Error matching Zerodha position: {e}")
                            
                elif broker_name and broker_name.lower() == "fyers":
                    for pos in positions:
                        try:
                            product_match = (str(pos.get('productType')).upper() == str(product).upper()) if product else True
                            if pos.get('symbol') == symbol_val and product_match:
                                matched_pos = pos
                                break
                        except Exception as e:
                            logger.error(f"OrderMonitor: Error matching Fyers position: {e}")
                
                if matched_pos:
                    exit_details_available = True
                    our_qty = int(qty)
                    
                    # Get current exit price and PnL
                    if broker_name and broker_name.lower() == "zerodha":
                        broker_pnl = float(matched_pos.get('pnl', 0))
                        # Calculate current exit price (entry_price + pnl_per_unit)
                        entry_price = bro.get('execution_price', 0) or 0
                        if our_qty > 0:
                            pnl_per_unit = broker_pnl / our_qty
                            current_exit_price = float(entry_price) + pnl_per_unit
                        else:
                            current_exit_price = float(entry_price)
                            
                    elif broker_name and broker_name.lower() == "fyers":
                        broker_pnl = float(matched_pos.get('pl', 0))
                        # For Fyers, try to get current market price or calculate from PnL
                        current_exit_price = matched_pos.get('ltp', 0) or matched_pos.get('marketVal', 0) or 0
                        if current_exit_price == 0:
                            entry_price = bro.get('execution_price', 0) or 0
                            if our_qty > 0:
                                pnl_per_unit = broker_pnl / our_qty
                                current_exit_price = float(entry_price) + pnl_per_unit
                            else:
                                current_exit_price = float(entry_price)
                    else:
                        current_exit_price = 0
                        broker_pnl = 0
                    
                    # Store individual broker exit data for broker_executions table
                    broker_exit_data.append({
                        'broker_id': broker_id,
                        'broker_order_id': bro.get('broker_order_id'),
                        'exit_price': current_exit_price,
                        'executed_quantity': our_qty,
                        'product_type': product,
                        'symbol': symbol_val,
                        'broker_pnl': broker_pnl
                    })
                    
                    # Accumulate for VWAP calculation
                    total_exit_value += current_exit_price * our_qty
                    total_exit_qty += our_qty
                    total_pnl += broker_pnl
                    
                    logger.info(f"OrderMonitor: Exit details for {broker_name}: exit_price={current_exit_price}, qty={our_qty}, pnl={broker_pnl}")
            
            # Calculate final exit price (VWAP) and complete the exit
            final_exit_price = total_exit_value / total_exit_qty if total_exit_qty > 0 else None
            
            if exit_details_available:
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
                                broker_id=exit_data['broker_id']
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
                                        "execution_time": exit_time,
                                        "notes": f"PENDING exit updated with calculated details. PnL: {exit_data['broker_pnl']}",
                                        "status": 'FILLED'  # Ensure status is FILLED since we have calculated details
                                    }
                                )
                                logger.info(f"OrderMonitor: Updated existing EXIT broker_execution for broker_id={exit_data['broker_id']}, new_price={exit_data['exit_price']}")
                                continue
                            
                            # No existing EXIT entry found, proceed with insertion
                            await self.order_manager._insert_exit_broker_execution(
                                session,
                                parent_order_id=self.order_id,
                                broker_id=exit_data['broker_id'],
                                broker_order_id=exit_data['broker_order_id'],
                                side='EXIT',
                                status='FILLED',  # Mark as FILLED since we calculated from positions
                                executed_quantity=exit_data['executed_quantity'],
                                execution_price=round(exit_data['exit_price'], 2),
                                product_type=exit_data['product_type'],
                                order_type='MARKET',  # Assume MARKET for exits
                                order_messages=f"PENDING exit completion: {final_exit_status}",
                                symbol=exit_data['symbol'],
                                execution_time=exit_time,
                                notes=f"PENDING exit via order_monitor with calculated details. PnL: {exit_data['broker_pnl']}",
                                action='EXIT',
                                exit_reason=exit_reason
                            )
                            logger.info(f"OrderMonitor: Inserted new EXIT broker_execution for broker_id={exit_data['broker_id']}, price={exit_data['exit_price']}")
                        except Exception as e:
                            logger.error(f"OrderMonitor: Error inserting EXIT broker_execution for broker_id={exit_data['broker_id']}: {e}")
                
                logger.critical(f"OrderMonitor: ✅ Successfully completed PENDING exit for order_id={self.order_id}. Status: {final_exit_status}, Exit Price: {final_exit_price}, PnL: {total_pnl}")
                
                # Stop monitoring this order
                self.stop()
                return
                
            else:
                # Fallback: No position data available, create basic EXIT entries for audit trail
                logger.warning(f"OrderMonitor: No exit details available from positions for order_id={self.order_id}. Creating basic EXIT entries.")
                
                # Get basic broker execution data for EXIT entries
                exit_time = datetime.now(timezone.utc)
                
                # Update orders table with basic exit details
                await self.order_manager.update_order_status_in_db(self.order_id, final_exit_status)
                
                # Insert basic EXIT broker_executions entries for audit trail
                async with AsyncSessionLocal() as session:
                    logger.info(f"OrderMonitor: Checking and creating basic EXIT broker_executions entries for order_id={self.order_id}")
                    
                    for bro in entry_broker_db_orders:
                        broker_status = bro.get('status', '').upper()
                        if broker_status == 'FAILED':
                            continue
                            
                        try:
                            # Check if EXIT entry already exists for this broker_order_id
                            from algosat.core.db import get_broker_executions_for_order
                            existing_exits = await get_broker_executions_for_order(
                                session, 
                                self.order_id, 
                                side='EXIT',
                                broker_id=bro.get('broker_id')
                            )
                            
                            # Filter to check if this specific broker_order_id already has an EXIT entry
                            existing_exit = None
                            for exit_entry in existing_exits:
                                if exit_entry.get('broker_order_id') == bro.get('broker_order_id'):
                                    existing_exit = exit_entry
                                    break
                            
                            if existing_exit:
                                logger.info(f"OrderMonitor: EXIT broker_execution already exists for broker_id={bro.get('broker_id')}, broker_order_id={bro.get('broker_order_id')}. Updating execution_time for fallback.")
                                
                                # Update existing EXIT entry with execution time (fallback case)
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
                                        "notes": f"Fallback exit updated - no position data available",
                                        "status": 'CLOSED'  # Keep CLOSED status for fallback
                                    }
                                )
                                logger.info(f"OrderMonitor: Updated existing EXIT broker_execution (fallback) for broker_id={bro.get('broker_id')}")
                                continue
                            
                            # No existing EXIT entry found, proceed with fallback insertion
                            await self.order_manager._insert_exit_broker_execution(
                                session,
                                parent_order_id=self.order_id,
                                broker_id=bro.get('broker_id'),
                                broker_order_id=bro.get('broker_order_id'),
                                side='EXIT',
                                status='CLOSED',  # Mark as CLOSED since no position details
                                executed_quantity=bro.get('quantity', 0),
                                execution_price=bro.get('execution_price', 0),  # Use entry price as fallback
                                product_type=bro.get('product_type'),
                                order_type='MARKET',
                                order_messages=f"PENDING exit completion (fallback): {final_exit_status}",
                                symbol=bro.get('symbol') or bro.get('tradingsymbol'),
                                execution_time=exit_time,
                                notes=f"Fallback exit - no position data available",
                                action='EXIT',
                                exit_reason=exit_reason
                            )
                            logger.info(f"OrderMonitor: Inserted fallback EXIT broker_execution for broker_id={bro.get('broker_id')}")
                        except Exception as e:
                            logger.error(f"OrderMonitor: Error inserting fallback EXIT broker_execution for broker_id={bro.get('broker_id')}: {e}")
                
                logger.warning(f"OrderMonitor: ⚠️ Completed PENDING exit for order_id={self.order_id} with basic details. Status: {final_exit_status}")
                
                # Stop monitoring this order
                self.stop()
                return
            
            # Clear order strategy cache since order status has changed
            if self.order_id in self._order_strategy_cache:
                del self._order_strategy_cache[self.order_id]
                
        except Exception as e:
            logger.error(f"OrderMonitor: ❌ Error completing PENDING exit for order_id={self.order_id}: {e}", exc_info=True)
            
            # Fallback: Update to final status and create basic EXIT entries for error recovery
            try:
                final_exit_status = order_row.get('status', '').replace('_PENDING', '') if order_row else 'EXIT_CLOSED'
                
                # Update status
                await self.order_manager.update_order_status_in_db(self.order_id, final_exit_status)
                
                # Insert basic EXIT broker_executions for error recovery audit trail
                from datetime import datetime, timezone
                async with AsyncSessionLocal() as session:
                    logger.info(f"OrderMonitor: Checking and creating error recovery EXIT broker_executions entries for order_id={self.order_id}")
                    
                    # Get entry broker executions for basic EXIT entries
                    from algosat.core.db import get_broker_executions_for_order
                    entry_broker_db_orders = await get_broker_executions_for_order(session, self.order_id, side='ENTRY')
                    
                    exit_time = datetime.now(timezone.utc)
                    for bro in entry_broker_db_orders:
                        broker_status = bro.get('status', '').upper()
                        if broker_status == 'FAILED':
                            continue
                            
                        try:
                            # Check if EXIT entry already exists for this broker_order_id
                            existing_exits = await get_broker_executions_for_order(
                                session, 
                                self.order_id, 
                                side='EXIT',
                                broker_id=bro.get('broker_id')
                            )
                            
                            # Filter to check if this specific broker_order_id already has an EXIT entry
                            existing_exit = None
                            for exit_entry in existing_exits:
                                if exit_entry.get('broker_order_id') == bro.get('broker_order_id'):
                                    existing_exit = exit_entry
                                    break
                            
                            if existing_exit:
                                logger.info(f"OrderMonitor: EXIT broker_execution already exists for broker_id={bro.get('broker_id')}, broker_order_id={bro.get('broker_order_id')}. Updating execution_time for error recovery.")
                                
                                # Update existing EXIT entry with execution time (error recovery case)
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
                                        "notes": f"Error recovery - PENDING exit processing failed",
                                        "status": 'CLOSED'  # Keep CLOSED status for error recovery
                                    }
                                )
                                logger.info(f"OrderMonitor: Updated existing EXIT broker_execution (error recovery) for broker_id={bro.get('broker_id')}")
                                continue
                            
                            # No existing EXIT entry found, proceed with error recovery insertion
                            await self.order_manager._insert_exit_broker_execution(
                                session,
                                parent_order_id=self.order_id,
                                broker_id=bro.get('broker_id'),
                                broker_order_id=bro.get('broker_order_id'),
                                side='EXIT',
                                status='CLOSED',
                                executed_quantity=bro.get('quantity', 0),
                                execution_price=bro.get('execution_price', 0),
                                product_type=bro.get('product_type'),
                                order_type='MARKET',
                                order_messages=f"Error recovery exit: {final_exit_status}",
                                symbol=bro.get('symbol') or bro.get('tradingsymbol'),
                                execution_time=exit_time,
                                notes=f"Error recovery - PENDING exit processing failed",
                                action='EXIT',
                                exit_reason="PENDING exit - error recovery"
                            )
                        except Exception as e:
                            logger.error(f"OrderMonitor: Error inserting error recovery EXIT broker_execution: {e}")
                
                logger.error(f"OrderMonitor: ⚠️ Fallback exit completed for order_id={self.order_id}")
                self.stop()
            except Exception as e2:
                logger.error(f"OrderMonitor: ❌ Failed fallback exit for order_id={self.order_id}: {e2}", exc_info=True)


    def _get_cache_lookup_order_id(self, broker_order_id, broker_name, product_type):
        """
        Helper to determine cache key for broker order id (handles Fyers intraday hack).
        """
        if (
            product_type
            and product_type.lower() == 'intraday'
            and broker_name
            and broker_name.lower() == 'fyers'
            and broker_order_id
            and not broker_order_id.endswith('-BO-1')
        ):
            return f"{broker_order_id}-BO-1"
        return broker_order_id

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
                
            logger.debug(f"OrderMonitor: Updated current_price={current_price} for order_id={self.order_id}, symbol={strike_symbol}")
            
        except Exception as e:
            logger.error(f"OrderMonitor: Error updating current_price for order_id={self.order_id}, symbol={strike_symbol}: {e}")

    async def _update_current_price_for_open_order(self, order_row):
        """
        Update current price for any OPEN order regardless of strategy type.
        Called during the main monitoring loop for all OPEN orders.
        
        Args:
            order_row: The order row from database
            
        Returns:
            float: Current LTP price if successfully fetched, None otherwise
        """
        try:
            # Only update price for OPEN orders
            if order_row.get('status') != 'OPEN':
                return None
                
            strike_symbol = order_row.get('strike_symbol')
            if not strike_symbol:
                return None
                
            # Get current LTP
            ltp_response = await self.data_manager.get_ltp(strike_symbol)
            if isinstance(ltp_response, dict):
                ltp = ltp_response.get(strike_symbol)
            else:
                ltp = ltp_response
                
            if ltp is None:
                logger.debug(f"OrderMonitor: Could not get LTP for {strike_symbol}, order_id={self.order_id}")
                return None
                
            ltp = float(ltp)
            
            # Update current price in database
            await self._update_current_price_in_db(strike_symbol, ltp)
            logger.debug(f"OrderMonitor: Updated current_price={ltp} for order_id={self.order_id}, symbol={strike_symbol}")
            
            # Return the LTP for use in exit checks
            return ltp
            
        except Exception as e:
            logger.error(f"OrderMonitor: Error updating current price for OPEN order_id={self.order_id}: {e}")
            return None

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
                logger.info(f"OrderMonitor: evaluate_exit returned True for order_id={self.order_id}. Converting exit status to PENDING state.")
                try:
                    # Small delay to ensure DB transaction is committed before fetching updated status
                    await asyncio.sleep(0.1)
                    
                    # Clear cache to ensure we get fresh order data after evaluate_exit updated the status
                    if self.order_id in self._order_strategy_cache:
                        del self._order_strategy_cache[self.order_id]
                    
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
                if self.order_id in self._order_strategy_cache:
                    del self._order_strategy_cache[self.order_id]

            await asyncio.sleep(self.signal_monitor_seconds)

    async def start(self) -> None:
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
        await asyncio.gather(self._price_order_monitor(), self._signal_monitor())
        # await asyncio.gather( self._signal_monitor())

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

    async def _get_all_broker_positions_with_cache(self):
        """
        Helper to get all broker positions, with 10s cache to avoid repeated API calls.
        """
        import time
        now = time.time()
        if (
            hasattr(self, "_positions_cache")
            and hasattr(self, "_positions_cache_time")
            and self._positions_cache is not None
            and self._positions_cache_time is not None
            and (now - self._positions_cache_time) < 10
        ):
            return self._positions_cache
        try:
            positions = await self.order_manager.broker_manager.get_all_broker_positions()
            self._positions_cache = positions
            self._positions_cache_time = now
            return positions
        except Exception as e:
            logger.error(f"OrderMonitor: Error fetching broker positions: {e}")
            return self._positions_cache