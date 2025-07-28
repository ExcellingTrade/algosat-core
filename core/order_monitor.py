from __future__ import annotations
from typing import Optional, Any
import asyncio
import time
from datetime import datetime
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
        price_order_monitor_seconds: float = 30.0,  # 1 minute default
        signal_monitor_seconds: int = None  # will be set from strategy config
    ):
        self.order_id: int = order_id
        self.data_manager: DataManager = data_manager
        self.order_manager: OrderManager = order_manager
        self.order_cache: OrderCache = order_cache
        self.strategy_instance = strategy_instance  # Store strategy instance
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
                                await self.order_manager.exit_order(self.order_id, reason=f"Square-off time {square_off_time_str} reached")
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

            # --- Price-based exit logic for OptionBuy and OptionSell strategies ---
            await self._check_price_based_exit(order_row, strategy, last_main_status)

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
                                except Exception as e:
                                    logger.error(f"OrderMonitor: Error fetching order from cache for broker_name={broker_name}, order_id={cache_lookup_order_id}: {e}")
                            # Use status from cache_order if available, else fallback to DB
                            broker_status = None
                            if cache_order and 'status' in cache_order:
                                broker_status = cache_order['status']
                            else:
                                broker_status = getattr(bro, 'status', None)
                            if broker_status and isinstance(broker_status, int) and broker_name == "fyers":
                                broker_status = FYERS_STATUS_MAP.get(broker_status, broker_status)
                            # Normalize broker_status
                            if broker_status and isinstance(broker_status, str) and broker_status.startswith("OrderStatus."):
                                broker_status = broker_status.split(".")[-1]
                            elif broker_status and isinstance(broker_status, OrderStatus):
                                broker_status = broker_status.value

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
                            (last_status in ("PENDING", "PARTIAL", "PARTIALLY_FILLED")) and
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
                    self.stop()
                    return
                
            # --- monitor positions if status is OPEN ---
            # Only for OPEN status, check broker positions and update order status/PnL based on positions
            if last_main_status == str(OrderStatus.OPEN) or (main_status == OrderStatus.OPEN):
                try:
                    # Use new helper to get all broker positions (with cache)
                    all_positions = await self._get_all_broker_positions_with_cache()
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
                        # broker_id = getattr(bro, 'broker_id', None)
                        broker_id = bro.get('broker_id', None)
                        broker_name = None
                        if broker_id is not None:
                            try:
                                broker_name = await self._get_broker_name_with_cache(broker_id)
                            except Exception as e:
                                logger.error(f"OrderMonitor: Could not get broker name for broker_id={broker_id}: {e}")
                        # broker_name = await self.data_manager.get_broker_name_by_id(bro.get("broker_id"))
                        symbol_val = bro.get('symbol', None) or bro.get('tradingsymbol', None)
                        qty = bro.get('quantity', None)
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
                                        # Match by tradingsymbol, product, and buy_quantity or overnight_quantity
                                        product_match = (str(pos.get('product')).upper() == str(product).upper()) if product else True
                                        entry_price_match = (float(pos.get('buy_price', 0)) == float(exec_price)) if exec_price else True
                                        qty_match = (int(pos.get('buy_quantity', 0)) == int(qty)) or (int(pos.get('overnight_quantity', 0)) == int(qty))
                                        if (
                                            pos.get('tradingsymbol') == symbol_val and
                                            qty_match and
                                            product_match and
                                            entry_price_match
                                        ):
                                            matched_pos = pos
                                            logger.info(f"OrderMonitor: Matched Zerodha position for symbol={symbol_val}: {pos}")
                                            break
                                    except Exception as e:
                                        logger.error(f"OrderMonitor: Error matching Zerodha position: {e}")
                            # Fyers: positions is a list of dicts
                            elif broker_name and broker_name.lower() == "fyers":
                                for pos in positions:
                                    try:
                                        # Fyers fields: 'symbol', 'qty', 'productType', 'buyAvg', 'side'
                                        product_match = (str(pos.get('productType')).upper() == str(product).upper()) if product else True
                                        qty_match = (int(pos.get('buyQty', 0)) == int(qty))
                                        symbol_match = (pos.get('symbol') == symbol_val)
                                        if symbol_match and qty_match and product_match:
                                            matched_pos = pos
                                            logger.info(f"OrderMonitor: Matched Fyers position for symbol={symbol_val}: {pos}")
                                            break
                                    except Exception as e:
                                        logger.error(f"OrderMonitor: Error matching Fyers position: {e}")
                        else:
                            logger.warning(f"OrderMonitor: No positions found for broker={broker_name} (positions data: {positions})")
                        
                        # If match found, update order/broker_exec status and accumulate PnL
                        if matched_pos:
                            logger.info(f"OrderMonitor: Processing matched position for broker={broker_name}: {matched_pos}")
                            # Zerodha: use 'pnl' field; Fyers: use 'pl' field
                            pnl_val = 0.0
                            closed = False
                            if broker_name and broker_name.lower() == "zerodha":
                                pnl_val = float(matched_pos.get('pnl', 0))
                                # If quantity is 0, consider squared off
                                if int(matched_pos.get('quantity', 0)) == 0:
                                    closed = True
                            elif broker_name and broker_name.lower() == "fyers":
                                pnl_val = float(round(matched_pos.get('pl', 0),2))
                                if int(matched_pos.get('qty', 0)) == 0:
                                    closed = True
                            
                            total_pnl += pnl_val
                            logger.info(f"OrderMonitor: Added PnL {pnl_val} from {broker_name} position. Total PnL now: {total_pnl}")
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
                            logger.critical(f"🚨 Exited order_id={self.order_id} due to per-trade loss limit breach")
                            self.stop()
                            return
                        else:
                            logger.debug(f"OrderMonitor: Per-trade risk check passed for order_id={self.order_id}. "
                                       f"P&L: {total_pnl}, Risk exposure: {total_risk_exposure}")
                            
                    except Exception as e:
                        logger.error(f"OrderMonitor: Error in per-trade loss validation for order_id={self.order_id}: {e}")
                    
                    # If all positions are squared off, update status to CLOSED/EXITED
                    if all_closed and entry_broker_db_orders:
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
                except Exception as e:
                    logger.error(f"OrderMonitor: Error in broker position monitoring: {e}", exc_info=True)
            await asyncio.sleep(self.price_order_monitor_seconds)
        logger.info(f"OrderMonitor: Stopping price monitor for order_id={self.order_id} (last status: {last_main_status})")
    
    async def _check_price_based_exit(self, order_row, strategy, last_main_status):
        """
        Check price-based exit conditions for OptionBuy and OptionSell strategies.
        Compare LTP with target_price and stop_loss to trigger exits.
        """
        try:
            # Only check for OPEN orders
            if last_main_status != 'OPEN':
                return
            
            # Only for OptionBuy and OptionSell strategies
            strategy_name = None
            if isinstance(strategy, dict):
                strategy_name = strategy.get('name', '').lower()
            else:
                strategy_name = getattr(strategy, 'name', '').lower()
                
            if strategy_name not in ['optionbuy', 'optionsell']:
                return
                
            # Get required values from order
            strike_symbol = order_row.get('strike_symbol')
            target_price = order_row.get('target_price')
            stop_loss = order_row.get('stop_loss')
            side = order_row.get('side', '').upper()
            
            if not strike_symbol:
                logger.debug(f"OrderMonitor: No strike_symbol for price-based exit check, order_id={self.order_id}")
                return
                
            if target_price is None and stop_loss is None:
                logger.debug(f"OrderMonitor: No target_price or stop_loss set for order_id={self.order_id}")
                return
                
            # Get current LTP
            try:
                ltp_response = await self.data_manager.get_ltp(strike_symbol)
                if isinstance(ltp_response, dict):
                    ltp = ltp_response.get(strike_symbol)
                else:
                    ltp = ltp_response
                    
                if ltp is None:
                    logger.debug(f"OrderMonitor: Could not get LTP for {strike_symbol}, order_id={self.order_id}")
                    return
                    
                ltp = float(ltp)
                logger.debug(f"OrderMonitor: Price check for order_id={self.order_id}, symbol={strike_symbol}, LTP={ltp}, target={target_price}, SL={stop_loss}, side={side}")
                
            except Exception as e:
                logger.error(f"OrderMonitor: Error getting LTP for {strike_symbol}, order_id={self.order_id}: {e}")
                return
            
            # Check exit conditions based on strategy and side
            should_exit = False
            exit_reason = None
            exit_status = None
            
            if side == 'BUY':  # Long position
                # Target hit: LTP >= target_price
                if target_price is not None and ltp >= float(target_price):
                    should_exit = True
                    exit_reason = f"Target hit: LTP {ltp} >= Target {target_price}"
                    exit_status = "EXIT_TARGET"
                # Stoploss hit: LTP <= stop_loss
                elif stop_loss is not None and ltp <= float(stop_loss):
                    should_exit = True
                    exit_reason = f"Stoploss hit: LTP {ltp} <= SL {stop_loss}"
                    exit_status = "EXIT_STOPLOSS"
                    
            elif side == 'SELL':  # Short position
                # Target hit: LTP <= target_price
                if target_price is not None and ltp <= float(target_price):
                    should_exit = True
                    exit_reason = f"Target hit: LTP {ltp} <= Target {target_price}"
                    exit_status = "EXIT_TARGET"
                # Stoploss hit: LTP >= stop_loss
                elif stop_loss is not None and ltp >= float(stop_loss):
                    should_exit = True
                    exit_reason = f"Stoploss hit: LTP {ltp} >= SL {stop_loss}"
                    exit_status = "EXIT_STOPLOSS"
            
            if should_exit:
                logger.info(f"OrderMonitor: Price-based exit triggered for order_id={self.order_id}. {exit_reason}")
                
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
                    
                    logger.info(f"OrderMonitor: Successfully exited order_id={self.order_id} due to price condition. Status updated to {status_constant}")
                    
                    # Stop monitoring this order
                    self.stop()
                    return
                    
                except Exception as e:
                    logger.error(f"OrderMonitor: Error exiting order_id={self.order_id} due to price condition: {e}")
                    
        except Exception as e:
            logger.error(f"OrderMonitor: Error in price-based exit check for order_id={self.order_id}: {e}")


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
                logger.info(f"OrderMonitor: evaluate_exit returned True for order_id={self.order_id}. Exiting order.")
                try:
                    await self.order_manager.exit_order(self.order_id)
                except Exception as e:
                    logger.error(f"OrderMonitor: Failed to exit order {self.order_id}: {e}", exc_info=True)
                self.stop()
                return

            await asyncio.sleep(self.signal_monitor_seconds)

    async def start(self) -> None:
        # Fetch signal_monitor_seconds from strategy config if not set
        if self.signal_monitor_seconds is None:
            # Use strategy instance if available, otherwise fetch from database
            if self.strategy_instance is not None:
                strategy = self.strategy_instance
                # Still need strategy_config from database
                _, _, strategy_config, _ = await self._get_order_and_strategy(self.order_id)
                logger.debug(f"OrderMonitor: Using passed strategy instance for signal_monitor_seconds calculation")
            else:
                # Use unified cache-based access for strategy_config and strategy
                _, _, strategy_config, strategy = await self._get_order_and_strategy(self.order_id)
                logger.debug(f"OrderMonitor: Using database strategy for signal_monitor_seconds calculation")
                
            strategy_id = None
            if strategy:
                # Try to get id from strategy object (dict or object)
                strategy_id = getattr(strategy, 'id', None)
                if strategy_id is None and isinstance(strategy, dict):
                    strategy_id = strategy.get('id')
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